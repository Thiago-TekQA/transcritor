"""Lógica do portal: planejar, copiar, iniciar/parar execuções e montar o
estado a partir dos eventos. Não importa torch/whisperx (só pipeline_config).
"""

import ctypes
import json
import os
import shutil
import subprocess
import sys
import threading
import time

import pipeline_config as cfg

EXECUCOES_DIR = os.path.join(cfg.PORTAL_DIR, "execucoes")
ATIVA_JSON = os.path.join(cfg.PORTAL_DIR, "ativa.json")
PIPELINE_SCRIPT = os.path.join(cfg.PASTA_SCRIPTS, "pipeline.py")

ROTULOS_ETAPAS = {
    "mp3": "Gerar áudio",
    "transcricao": "Transcrição",
    "diarizacao": "Diarização",
    "resumo": "Resumo",
    "consolidar": "Consolidar",
}

# execuções cujo preparo (cópia de arquivos) está rodando neste processo
_preparando = set()
_trava = threading.Lock()


# =========================================================
# UTILITÁRIOS
# =========================================================


def _escrever_json(caminho, dados):

    os.makedirs(os.path.dirname(caminho), exist_ok=True)

    tmp = caminho + ".tmp"

    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(dados, f, ensure_ascii=False, indent=2)

    os.replace(tmp, caminho)


def _ler_json(caminho, padrao=None):

    try:

        with open(caminho, "r", encoding="utf-8") as f:
            return json.load(f)

    except (OSError, ValueError):

        return padrao


def escrever_evento(run_dir, ev, **campos):
    """Mesmo formato dos eventos do pipeline (uma linha JSON, append)."""

    registro = {"v": 1, "ts": time.strftime("%Y-%m-%dT%H:%M:%S"), "ev": ev}
    registro.update(campos)

    with open(
        os.path.join(run_dir, "eventos.jsonl"), "a", encoding="utf-8"
    ) as f:
        f.write(json.dumps(registro, ensure_ascii=False) + "\n")


def processo_vivo(pid):

    if not pid:
        return False

    try:

        k32 = ctypes.windll.kernel32

        h = k32.OpenProcess(0x1000, False, int(pid))  # QUERY_LIMITED_INFO

        if not h:
            return False

        codigo = ctypes.c_ulong()

        k32.GetExitCodeProcess(h, ctypes.byref(codigo))
        k32.CloseHandle(h)

        return codigo.value == 259  # STILL_ACTIVE

    except Exception:

        return False


def python_do_pipeline():

    venv = os.path.join(
        cfg.PASTA_RAIZ, ".venv", "Scripts", "python.exe"
    )

    return venv if os.path.exists(venv) else sys.executable


def _contem_dentro(base, caminho):
    """True se `caminho` (resolvido) está dentro de `base`."""

    base = os.path.realpath(base)
    caminho = os.path.realpath(caminho)

    return caminho == base or caminho.startswith(base + os.sep)


# =========================================================
# NAVEGADOR DE PASTAS (somente leitura)
# =========================================================


def _drives():

    try:
        return [d for d in os.listdrives()]
    except AttributeError:
        import string
        return [
            f"{c}:\\" for c in string.ascii_uppercase
            if os.path.exists(f"{c}:\\")
        ]


def listar_pastas(caminho):

    if not caminho:

        return {
            "caminho": "",
            "pai": None,
            "pastas": [{"nome": d, "caminho": d, "midias": None}
                       for d in _drives()],
            "midias": 0,
        }

    caminho = os.path.abspath(caminho)

    if not os.path.isdir(caminho):
        raise ValueError("pasta não encontrada")

    pastas = []
    midias = 0

    try:

        for entrada in sorted(os.scandir(caminho), key=lambda e: e.name.lower()):

            try:

                if entrada.is_dir(follow_symlinks=False):

                    if not entrada.name.startswith((".", "$")):
                        pastas.append({
                            "nome": entrada.name,
                            "caminho": entrada.path,
                        })

                elif entrada.is_file():

                    if os.path.splitext(entrada.name)[1].lower() in (
                        cfg.AMOSTRAS_SUPORTADAS
                    ):
                        midias += 1

            except OSError:

                continue

    except PermissionError:

        raise ValueError("sem permissão para ler esta pasta")

    pai = os.path.dirname(caminho)

    return {
        "caminho": caminho,
        "pai": pai if pai and pai != caminho else "",
        "pastas": pastas,
        "midias": midias,
    }


def _listar_midias(origem, recursivo):

    achados = []

    if recursivo:

        for raiz, pastas, arquivos in os.walk(origem):

            pastas[:] = [p for p in pastas if not p.startswith((".", "$"))]

            for a in arquivos:
                achados.append(os.path.join(raiz, a))

    else:

        for a in os.listdir(origem):

            caminho = os.path.join(origem, a)

            if os.path.isfile(caminho):
                achados.append(caminho)

    return sorted(
        c for c in achados
        if os.path.splitext(c)[1].lower() in cfg.AMOSTRAS_SUPORTADAS
    )


# =========================================================
# PLANEJAMENTO
# =========================================================


def _tem_original_na_area(nome):

    for ext in cfg.VIDEOS_SUPORTADOS:

        caminho = os.path.join(cfg.VIDEOS_DIR, nome + ext)

        if os.path.exists(caminho):
            return caminho

    return None


def planejar(origem, etapas, recursivo=False):
    """Calcula, por arquivo da pasta e por etapa selecionada, o que vai
    acontecer: executar, pular (já existe) ou bloqueado (falta algo).
    Não altera nada em disco."""

    # A pasta de origem é opcional: dá para só continuar itens que ficaram
    # parados no meio do caminho na área de trabalho.
    if origem and not os.path.isdir(origem):
        raise ValueError("pasta de origem não encontrada")

    etapas = [e for e in cfg.ETAPAS_VALIDAS if e in set(etapas)]

    if not etapas:
        raise ValueError("selecione ao menos uma etapa")

    arquivos = _listar_midias(origem, recursivo) if origem else []

    por_nome = {}

    for caminho in arquivos:

        stem, ext = os.path.splitext(os.path.basename(caminho))
        nome = cfg.sanitizar_nome(stem)

        por_nome.setdefault(nome, []).append((caminho, ext.lower()))

    itens = []

    for nome in sorted(por_nome, key=str.lower):

        candidatos = por_nome[nome]

        item = {
            "nome": nome,
            "origem": candidatos[0][0],
            "ext": candidatos[0][1],
            "tamanho": os.path.getsize(candidatos[0][0]),
            "copiar": None,
            "excluido": None,
            "estagios": {},
        }

        if len(candidatos) > 1:

            item["excluido"] = (
                "nome repetido na pasta: "
                + ", ".join(os.path.basename(c[0]) for c in candidatos)
            )

        elif os.path.isdir(os.path.join(cfg.DONE_DIR, nome)):

            item["excluido"] = "já concluído em 6_Concluidos"

        if not item["excluido"]:
            _planejar_item(item, etapas)

        itens.append(item)

    # Itens parados no meio do caminho (já na área de trabalho, não
    # concluídos). Se o nome coincide com um arquivo da origem, a linha da
    # origem já mostra o que existe — não repete.
    nomes_origem = {i["nome"] for i in itens}

    parados = []

    for p in listar_parados():

        if p["nome"] in nomes_origem:
            continue

        _planejar_item(p, etapas)

        parados.append(p)

    return {
        "origem": origem or "",
        "etapas": etapas,
        "itens": itens,
        "parados": parados,
    }


def _ultima_parada(nome):
    """Onde e por quê o item parou, segundo a execução mais recente que o
    incluiu. None se nenhuma execução do portal o tocou."""

    if not os.path.isdir(EXECUCOES_DIR):
        return None

    for rid in sorted(os.listdir(EXECUCOES_DIR), reverse=True)[:40]:

        params = obter_params(rid)

        if not params or nome not in [i["nome"] for i in params["itens"]]:
            continue

        estado = montar_estado(rid)

        if not estado:
            continue

        item = estado["itens"].get(nome)

        if not item:
            continue

        for etapa in estado["etapas"]:

            st = item["etapas"].get(etapa, {})

            if st.get("estado") not in ("ok", "pulado"):

                return {
                    "run": rid,
                    "criado": params.get("criado"),
                    "etapa": etapa,
                    "estado": st.get("estado"),
                    "motivo": st.get("motivo"),
                }

        return {
            "run": rid,
            "criado": params.get("criado"),
            "etapa": None,
            "estado": "ok",
            "motivo": None,
            "etapas": estado["etapas"],
        }

    return None


def listar_parados():
    """Itens que já estão na área de trabalho e NÃO foram concluídos (sem
    pasta em 6_Concluidos), com o que já existe de cada um e onde pararam."""

    itens = {}

    def registrar(nome, chave, caminho):

        d = itens.setdefault(nome, {
            "nome": nome, "origem": None, "ext": ".mp3", "tamanho": 0,
            "copiar": None, "excluido": None, "estagios": {},
            "parado": True, "feitas": [], "modificado": "",
            "_m": 0.0, "_chaves": set(),
        })

        d["_chaves"].add(chave)

        try:
            d["_m"] = max(d["_m"], os.path.getmtime(caminho))
        except OSError:
            pass

        return d

    def varrer(pasta):

        if not os.path.isdir(pasta):
            return

        for a in os.listdir(pasta):

            if a.endswith((".parcial", ".copiando")):
                continue

            yield a, os.path.join(pasta, a)

    for a, caminho in varrer(cfg.VIDEOS_DIR):

        stem, ext = os.path.splitext(a)

        if ext.lower() in cfg.VIDEOS_SUPORTADOS:

            d = registrar(cfg.sanitizar_nome(stem), "original", caminho)
            d["ext"] = ext.lower()

            try:
                d["tamanho"] = os.path.getsize(caminho)
            except OSError:
                pass

    for a, caminho in varrer(cfg.AUDIOS_DIR):

        stem, ext = os.path.splitext(a)

        if ext.lower() == ".mp3":
            registrar(cfg.sanitizar_nome(stem), "audio", caminho)

        elif ext.lower() in cfg.VIDEOS_SUPORTADOS:
            registrar(cfg.sanitizar_nome(stem), "original", caminho)

    for a, caminho in varrer(cfg.TRANS_DIR):

        if a.endswith(".txt") and not a.endswith(("_diarizado.txt", "_resumo.txt")):
            registrar(cfg.sanitizar_nome(a[: -len(".txt")]), "transcricao", caminho)

    for a, caminho in varrer(cfg.DIARIZ_DIR):

        if a.endswith("_diarizado.txt"):
            registrar(cfg.sanitizar_nome(a[: -len("_diarizado.txt")]), "diarizacao", caminho)

    for a, caminho in varrer(cfg.RESUMOS_DIR):

        if a.endswith("_resumo.txt"):
            registrar(cfg.sanitizar_nome(a[: -len("_resumo.txt")]), "resumo", caminho)

    rotulos = {
        "original": "vídeo/áudio original", "audio": "áudio (mp3)",
        "transcricao": "transcrição", "diarizacao": "diarização",
        "resumo": "resumo",
    }

    saida = []

    for nome, d in itens.items():

        # já concluído: o resumo em 8_Resumos é a cópia permanente
        if os.path.isdir(os.path.join(cfg.DONE_DIR, nome)):
            continue

        d["feitas"] = [rotulos[c] for c in rotulos if c in d["_chaves"]]
        d["modificado"] = time.strftime(
            "%Y-%m-%dT%H:%M:%S", time.localtime(d["_m"]))
        d["parou"] = _ultima_parada(nome)

        del d["_m"], d["_chaves"]

        saida.append(d)

    saida.sort(key=lambda i: i["modificado"], reverse=True)

    return saida


def _planejar_item(item, etapas):

    nome = item["nome"]
    ext = item["ext"]

    e_audio = ext == ".mp3"

    audio_path = os.path.join(cfg.AUDIOS_DIR, nome + ".mp3")

    existe = {
        "audio": os.path.exists(audio_path),
        "trans": os.path.exists(os.path.join(cfg.TRANS_DIR, nome + ".txt")),
        "diar": os.path.exists(
            os.path.join(cfg.DIARIZ_DIR, nome + "_diarizado.txt")
        ),
        "resumo": os.path.exists(
            os.path.join(cfg.RESUMOS_DIR, nome + "_resumo.txt")
        ),
    }

    original_na_area = _tem_original_na_area(nome)

    # Já existe na área de trabalho um arquivo com este nome mas tamanho
    # diferente? É outro arquivo — não sobrescrevemos.
    destino = (
        audio_path if e_audio
        else os.path.join(cfg.VIDEOS_DIR, nome + ext)
    )

    if (
        item["origem"] is not None
        and os.path.exists(destino)
        and os.path.getsize(destino) != item["tamanho"]
    ):

        item["excluido"] = (
            "já existe um arquivo diferente com este nome na área de "
            "trabalho"
        )

        return

    est = item["estagios"]

    produz_audio = False
    tem_audio = existe["audio"]
    tem_trans = existe["trans"]
    tem_resumo = existe["resumo"]

    for etapa in etapas:

        if etapa == "mp3":

            if tem_audio:
                est[etapa] = {"acao": "pular", "motivo": "áudio já existe"}
            elif e_audio:
                est[etapa] = {"acao": "pular", "motivo": "o arquivo já é áudio"}
                produz_audio = True
            else:
                est[etapa] = {"acao": "executar"}
                produz_audio = True

        elif etapa == "transcricao":

            if tem_trans:
                est[etapa] = {"acao": "pular", "motivo": "transcrição já existe"}
            elif tem_audio or produz_audio or e_audio:
                est[etapa] = {"acao": "executar"}
                tem_trans = True
            else:
                est[etapa] = {
                    "acao": "bloqueado",
                    "motivo": "falta o áudio — marque 'Gerar áudio'",
                    "sugerir": "mp3",
                }

        elif etapa == "diarizacao":

            if existe["diar"]:
                est[etapa] = {"acao": "pular", "motivo": "diarização já existe"}
            elif tem_audio or produz_audio or e_audio:
                est[etapa] = {"acao": "executar"}
            else:
                est[etapa] = {
                    "acao": "bloqueado",
                    "motivo": "falta o áudio — marque 'Gerar áudio'",
                    "sugerir": "mp3",
                }

        elif etapa == "resumo":

            if tem_resumo:
                est[etapa] = {"acao": "pular", "motivo": "resumo já existe"}
            elif tem_trans:
                est[etapa] = {"acao": "executar"}
                tem_resumo = True
            else:
                est[etapa] = {
                    "acao": "bloqueado",
                    "motivo": "falta a transcrição — marque 'Transcrição'",
                    "sugerir": "transcricao",
                }

        elif etapa == "consolidar":

            if tem_trans and tem_resumo:
                est[etapa] = {"acao": "executar"}
            else:
                faltando = "o resumo" if tem_trans else "a transcrição"
                est[etapa] = {
                    "acao": "bloqueado",
                    "motivo": f"falta {faltando} — marque a etapa antes",
                    "sugerir": "resumo" if tem_trans else "transcricao",
                }

    # Item que já está na área de trabalho (parado): nada a copiar.
    if item["origem"] is None:

        item["copiar"] = None

        return

    # Precisa copiar o original da pasta de origem?
    if e_audio:

        precisa = any(
            e in etapas for e in ("mp3", "transcricao", "diarizacao", "consolidar")
        ) and not existe["audio"]

        item["copiar"] = (
            {"para": audio_path, "area": "2_Audios"} if precisa else None
        )

    else:

        precisa = (
            est.get("mp3", {}).get("acao") == "executar"
            or est.get("consolidar", {}).get("acao") == "executar"
        ) and not original_na_area

        item["copiar"] = (
            {"para": os.path.join(cfg.VIDEOS_DIR, nome + ext),
             "area": "1_Videos"}
            if precisa else None
        )


# =========================================================
# CÓPIA PARA A ÁREA DE TRABALHO
# =========================================================


def _copiar_arquivo(origem, destino, progresso):

    os.makedirs(os.path.dirname(destino), exist_ok=True)

    # Mesmo arquivo já está lá (mesmo tamanho): reaproveita
    if (
        os.path.exists(destino)
        and os.path.getsize(destino) == os.path.getsize(origem)
    ):
        return "reaproveitado"

    tmp = destino + ".copiando"

    if cfg.CONFIG.get("portal_hardlink"):

        try:

            os.link(origem, tmp)
            os.replace(tmp, destino)

            return "hardlink"

        except OSError:

            pass

    total = os.path.getsize(origem) or 1
    copiado = 0
    ultimo = -1

    with open(origem, "rb") as fo, open(tmp, "wb") as fd:

        while True:

            bloco = fo.read(8 * 1024 * 1024)

            if not bloco:
                break

            fd.write(bloco)
            copiado += len(bloco)

            pct = int(copiado * 100 / total)

            if pct != ultimo:
                ultimo = pct
                progresso(pct)

    shutil.copystat(origem, tmp)
    os.replace(tmp, destino)

    return "copiado"


def _preparar_e_iniciar(run_id, run_dir, params, plano_itens):
    """Roda em thread: copia o que for preciso e dispara o pipeline."""

    try:

        escrever_evento(run_dir, "run_prep")

        for item in plano_itens:

            copia = item.get("copiar")

            if not copia:
                continue

            nome = item["nome"]

            escrever_evento(run_dir, "copiar", nome=nome, estado="rodando",
                            pct=0)

            try:

                ultimo = {"t": 0}

                def progresso(pct, nome=nome, ultimo=ultimo):

                    agora = time.time()

                    if agora - ultimo["t"] >= 1.0:
                        ultimo["t"] = agora
                        escrever_evento(run_dir, "copiar", nome=nome,
                                        estado="rodando", pct=pct)

                modo = _copiar_arquivo(item["origem"], copia["para"],
                                       progresso)

                escrever_evento(run_dir, "copiar", nome=nome, estado="ok",
                                pct=100, nota=modo)

            except Exception as e:

                escrever_evento(run_dir, "copiar", nome=nome,
                                estado="falhou", motivo=str(e))

                raise RuntimeError(f"falha ao copiar '{nome}': {e}")

        _iniciar_pipeline(run_id, run_dir, params)

    except Exception as e:

        escrever_evento(run_dir, "erro_fatal", msg=str(e))
        escrever_evento(run_dir, "run_fim", resultado="erro", falhas=[])

    finally:

        _preparando.discard(run_id)


def _iniciar_pipeline(run_id, run_dir, params):

    env = dict(os.environ)

    env["PYTHONUTF8"] = "1"
    env["PYTHONUNBUFFERED"] = "1"
    env["TRANSCRITOR_EVENTOS"] = os.path.join(run_dir, "eventos.jsonl")
    env["TRANSCRITOR_PARAR"] = os.path.join(run_dir, "parar.flag")

    cmd = [
        python_do_pipeline(), "-u", "-X", "utf8", PIPELINE_SCRIPT,
        "--etapas", ",".join(params["etapas"]),
        "--itens", os.path.join(run_dir, "itens.json"),
    ]

    if params.get("modelo"):
        cmd += ["--modelo", params["modelo"]]

    if params.get("device"):
        cmd += ["--device", params["device"]]

    saida = open(os.path.join(run_dir, "saida.log"), "ab")

    proc = subprocess.Popen(
        cmd,
        cwd=cfg.PASTA_SCRIPTS,
        env=env,
        stdin=subprocess.DEVNULL,
        stdout=saida,
        stderr=subprocess.STDOUT,
        creationflags=(
            subprocess.CREATE_NO_WINDOW | subprocess.CREATE_NEW_PROCESS_GROUP
        ),
    )

    _escrever_json(os.path.join(run_dir, "proc.json"), {"pid": proc.pid})
    _escrever_json(ATIVA_JSON, {"id": run_id, "pid": proc.pid})


# =========================================================
# CRIAR / CONTROLAR EXECUÇÕES
# =========================================================


def execucao_ativa():
    """Id da execução em andamento (preparando ou com processo vivo)."""

    for rid in list(_preparando):
        return rid

    ativa = _ler_json(ATIVA_JSON)

    if ativa and processo_vivo(ativa.get("pid")):
        return ativa.get("id")

    return None


def criar_execucao(origem, etapas, itens_escolhidos, recursivo=False,
                   modelo=None, device=None, retomada_de=None):

    with _trava:

        ativo = execucao_ativa()

        if ativo:
            raise PermissionError(f"já existe uma execução em andamento ({ativo})")

        plano = planejar(origem, etapas, recursivo)

        escolhidos = set(itens_escolhidos or [])

        itens = [
            i for i in plano["itens"] + plano["parados"]
            if i["nome"] in escolhidos and not i["excluido"]
        ]

        if not itens:
            raise ValueError("nenhum arquivo válido selecionado")

        bloqueados = [
            {"nome": i["nome"], "etapa": e, "motivo": s["motivo"]}
            for i in itens for e, s in i["estagios"].items()
            if s["acao"] == "bloqueado"
        ]

        if bloqueados:

            raise ValueError(
                "há etapas bloqueadas: "
                + "; ".join(
                    f"{b['nome']} ({b['etapa']}): {b['motivo']}"
                    for b in bloqueados[:3]
                )
            )

        run_id = time.strftime("%Y%m%d_%H%M%S")
        run_dir = os.path.join(EXECUCOES_DIR, run_id)
        os.makedirs(run_dir, exist_ok=False)

        params = {
            "id": run_id,
            "criado": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "origem": origem or "",
            "recursivo": bool(recursivo),
            "etapas": plano["etapas"],
            "itens": [
                {"nome": i["nome"], "tamanho": i["tamanho"],
                 "parado": bool(i.get("parado")),
                 "estagios": {e: s["acao"] for e, s in i["estagios"].items()}}
                for i in itens
            ],
            "modelo": modelo or "",
            "device": device or "",
            "retomada_de": retomada_de,
        }

        _escrever_json(os.path.join(run_dir, "params.json"), params)
        _escrever_json(
            os.path.join(run_dir, "itens.json"), [i["nome"] for i in itens]
        )

        open(os.path.join(run_dir, "eventos.jsonl"), "a").close()

        _preparando.add(run_id)

        threading.Thread(
            target=_preparar_e_iniciar,
            args=(run_id, run_dir, params, itens),
            daemon=True,
        ).start()

        return run_id


def retomar_execucao(run_id):

    params = obter_params(run_id)

    if not params:
        raise ValueError("execução não encontrada")

    return criar_execucao(
        params["origem"],
        params["etapas"],
        [i["nome"] for i in params["itens"]],
        params.get("recursivo", False),
        params.get("modelo") or None,
        params.get("device") or None,
        retomada_de=run_id,
    )


def pasta_execucao(run_id):

    # id só com dígitos e "_" (nunca vem caminho do cliente)
    if not run_id or not all(c.isdigit() or c == "_" for c in run_id):
        return None

    run_dir = os.path.join(EXECUCOES_DIR, run_id)

    return run_dir if os.path.isdir(run_dir) else None


def obter_params(run_id):

    run_dir = pasta_execucao(run_id)

    return _ler_json(os.path.join(run_dir, "params.json")) if run_dir else None


def parar_execucao(run_id):
    """Parada suave: o pipeline termina o arquivo atual e encerra."""

    run_dir = pasta_execucao(run_id)

    if not run_dir:
        raise ValueError("execução não encontrada")

    with open(os.path.join(run_dir, "parar.flag"), "w") as f:
        f.write("parar")


def _limpar_interrompidos(run_dir=None, tentativas=15):
    """Remove o que uma execução interrompida deixou pela metade (só a saída
    da etapa que estava em andamento). Repete por alguns segundos porque,
    logo após matar o processo, o Windows ainda pode estar segurando o
    arquivo. Cada item limpo vira um evento `limpeza` na execução."""

    def registrar(r):

        if run_dir:
            escrever_evento(run_dir, "limpeza", **r)

    total = []

    for _ in range(tentativas):

        removidos, falhas = cfg.limpar_interrompidos(registrar)

        total += removidos

        if not falhas:
            break

        time.sleep(0.4)

    return total


def _limpar_se_preciso(run_dir):
    """Execução que morreu por fora (sem run_fim): limpa uma única vez,
    desde que nenhuma outra execução esteja ativa."""

    marca = os.path.join(run_dir, "limpo.flag")

    if os.path.exists(marca) or execucao_ativa():
        return

    try:

        open(marca, "w").close()

        _limpar_interrompidos(run_dir, tentativas=3)

    except OSError:

        pass


def cancelar_execucao(run_id):
    """Cancelamento imediato (mata a árvore de processos). Durante a
    consolidação (só renomeia arquivos) faz parada suave."""

    run_dir = pasta_execucao(run_id)

    if not run_dir:
        raise ValueError("execução não encontrada")

    estado = montar_estado(run_id)

    if estado["estado_run"] not in ("rodando", "parando", "preparando"):
        raise ValueError("a execução não está em andamento")

    if estado.get("fase_atual") == "consolidar":

        parar_execucao(run_id)

        return "suave"

    proc = _ler_json(os.path.join(run_dir, "proc.json"), {})

    pid = proc.get("pid")

    if pid and processo_vivo(pid):

        subprocess.run(
            ["taskkill", "/PID", str(pid), "/T", "/F"],
            capture_output=True,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )

        # espera o Windows soltar os arquivos antes de varrer
        for _ in range(20):

            if not processo_vivo(pid):
                break

            time.sleep(0.25)

    _limpar_interrompidos(run_dir)

    escrever_evento(run_dir, "cancelado", modo="duro")
    escrever_evento(run_dir, "run_fim", resultado="cancelada", falhas=[])

    return "duro"


# =========================================================
# ESTADO (reducer dos eventos)
# =========================================================

_cache_estado = {}


def _ler_eventos(run_dir):

    eventos = []

    caminho = os.path.join(run_dir, "eventos.jsonl")

    try:

        with open(caminho, "r", encoding="utf-8") as f:

            for linha in f:

                try:
                    eventos.append(json.loads(linha))
                except ValueError:
                    # linha parcial (última, ainda sendo escrita): ignora
                    pass

    except OSError:

        pass

    return eventos


def _encerrar_itens(estado, resultado):
    """Execução terminou: o que não foi concluído não pode continuar
    aparecendo como 'rodando' ou 'aguardando'."""

    for item in estado["itens"].values():

        for e in item["etapas"].values():

            if e["estado"] in ("rodando", "aguardando_cpu"):

                e["estado"] = "cancelado" if resultado in (
                    "cancelada", "interrompida"
                ) else "falhou"

                e.setdefault("motivo", "execução interrompida")

            elif e["estado"] == "pendente":

                e["estado"] = "nao_executado"


def dobrar_eventos(params, eventos):
    """Função pura: monta o estado da execução a partir dos eventos."""

    etapas = params["etapas"]

    itens = {}

    for i in params["itens"]:

        itens[i["nome"]] = {
            "nome": i["nome"],
            "tamanho": i.get("tamanho"),
            "copia": None,
            "etapas": {e: {"estado": "pendente"} for e in etapas},
        }

        # etapas que o plano já sabe que serão puladas
        for e, acao in i["estagios"].items():

            if acao == "pular":
                itens[i["nome"]]["etapas"][e] = {
                    "estado": "pulado", "motivo": "ja_existe",
                }

    estado = {
        "id": params["id"],
        "criado": params.get("criado"),
        "origem": params.get("origem"),
        "etapas": etapas,
        "itens": itens,
        "estado_run": "preparando",
        "fase_atual": None,
        "pausa_termica": None,
        "ollama": None,
        "pedido_parada": False,
        "limpezas": [],
        "falhas": [],
        "erro": None,
        "dispositivo": None,
        "inicio": None,
        "fim": None,
        "log": None,
        "pid": None,
    }

    for ev in eventos:

        tipo = ev.get("ev")
        nome = ev.get("nome")
        etapa = ev.get("etapa")

        if tipo == "copiar" and nome in itens:

            itens[nome]["copia"] = {
                "estado": ev.get("estado"),
                "pct": ev.get("pct"),
                "nota": ev.get("nota"),
                "motivo": ev.get("motivo"),
            }

        elif tipo == "run_inicio":

            estado["estado_run"] = "rodando"
            estado["inicio"] = ev.get("ts")
            estado["dispositivo"] = ev.get("device")
            estado["log"] = ev.get("log")
            estado["pid"] = ev.get("pid")

        elif tipo == "fase_inicio":

            estado["fase_atual"] = etapa

        elif tipo == "fase_fim":

            # o que ficou sem ser tocado na fase vira "sem_entrada"
            for item in itens.values():

                e = item["etapas"].get(etapa)

                if e and e["estado"] == "pendente":

                    # após um pedido de parada, o que sobrou não "ficou sem
                    # entrada": simplesmente não chegou a ser executado
                    e["estado"] = (
                        "nao_executado" if estado["pedido_parada"]
                        else "sem_entrada"
                    )

            estado["fase_atual"] = None

        elif tipo == "item" and nome in itens and etapa in itens[nome]["etapas"]:

            e = itens[nome]["etapas"][etapa]

            e["estado"] = ev.get("estado", e["estado"])

            for campo in ("dispositivo", "tentativa", "dur", "motivo", "nota"):

                if campo in ev:
                    e[campo] = ev[campo]

            if ev.get("estado") == "ok":
                e["pct"] = 100

        elif tipo == "progresso" and nome in itens and etapa in itens[nome]["etapas"]:

            itens[nome]["etapas"][etapa]["pct"] = ev.get("pct")

        elif tipo == "pausa_termica":

            estado["pausa_termica"] = (
                {"temp": ev.get("temp"),
                 "retomar_abaixo": ev.get("retomar_abaixo")}
                if ev.get("estado") == "inicio" else None
            )

        elif tipo == "ollama":

            estado["ollama"] = ev.get("estado")

        elif tipo == "limpeza":

            estado["limpezas"].append({
                "etapa": ev.get("etapa"),
                "nome": ev.get("nome"),
                "arquivo": ev.get("arquivo"),
            })

        elif tipo == "cancelado":

            estado["pedido_parada"] = True

        elif tipo == "erro_fatal":

            estado["erro"] = ev.get("msg")

        elif tipo == "run_fim":

            estado["fim"] = ev.get("ts")
            estado["falhas"] = ev.get("falhas") or []

            estado["estado_run"] = {
                "ok": "concluida",
                "com_falhas": "concluida_com_falhas",
                "cancelada": "cancelada",
                "erro": "erro",
            }.get(ev.get("resultado"), "concluida")

            estado["fase_atual"] = None

            _encerrar_itens(estado, ev.get("resultado"))

    return estado


def montar_estado(run_id):

    run_dir = pasta_execucao(run_id)

    if not run_dir:
        return None

    params = _ler_json(os.path.join(run_dir, "params.json"))

    if not params:
        return None

    caminho_ev = os.path.join(run_dir, "eventos.jsonl")

    try:
        st = os.stat(caminho_ev)
        chave = (st.st_mtime_ns, st.st_size)
    except OSError:
        chave = None

    flag = os.path.exists(os.path.join(run_dir, "parar.flag"))
    proc = _ler_json(os.path.join(run_dir, "proc.json"), {})
    vivo = processo_vivo(proc.get("pid"))
    prep = run_id in _preparando

    cache = _cache_estado.get(run_id)

    if cache and cache[0] == chave:
        base = cache[1]
    else:
        base = dobrar_eventos(params, _ler_eventos(run_dir))
        _cache_estado[run_id] = (chave, base)

    estado = json.loads(json.dumps(base))  # cópia

    terminal = estado["estado_run"] in (
        "concluida", "concluida_com_falhas", "cancelada", "erro"
    )

    if not terminal:

        if prep and estado["estado_run"] == "preparando":
            pass
        elif vivo:
            estado["estado_run"] = "parando" if flag else "rodando"
        elif prep:
            pass
        else:
            # sem run_fim e sem processo: foi interrompida por fora
            estado["estado_run"] = "interrompida"
            estado["fase_atual"] = None

            _encerrar_itens(estado, "interrompida")

            _limpar_se_preciso(run_dir)

    estado["flag_parar"] = flag
    estado["pid"] = proc.get("pid") or estado.get("pid")

    return estado


def listar_execucoes():

    saida = []

    if not os.path.isdir(EXECUCOES_DIR):
        return saida

    for rid in sorted(os.listdir(EXECUCOES_DIR), reverse=True):

        params = obter_params(rid)

        if not params:
            continue

        estado = montar_estado(rid)

        contagem = {}

        for item in estado["itens"].values():

            for e in item["etapas"].values():
                contagem[e["estado"]] = contagem.get(e["estado"], 0) + 1

        saida.append({
            "id": rid,
            "criado": params.get("criado"),
            "origem": params.get("origem"),
            "etapas": params["etapas"],
            "arquivos": len(params["itens"]),
            "estado_run": estado["estado_run"],
            "contagem": contagem,
        })

    return saida


def ler_log(run_id, linhas=200):

    run_dir = pasta_execucao(run_id)

    if not run_dir:
        return []

    caminho = os.path.join(run_dir, "saida.log")

    try:

        with open(caminho, "r", encoding="utf-8", errors="replace") as f:
            return [l.rstrip("\n") for l in f.readlines()[-linhas:]]

    except OSError:

        return []


# =========================================================
# RESULTADOS
# =========================================================

_TIPOS_ARQUIVO = {
    "resumo": "{nome}_resumo.txt",
    "transcricao": "{nome}.txt",
    "diarizado": "{nome}_diarizado.txt",
    "log": "pipeline.log",
}


def _nome_valido(nome):

    return bool(nome) and nome not in (".", "..") and not any(
        c in nome for c in '\\/:*?"<>|'
    )


def listar_resultados(aba, busca=""):

    busca = (busca or "").lower()

    itens = []

    if aba == "concluidos":

        if os.path.isdir(cfg.DONE_DIR):

            for nome in os.listdir(cfg.DONE_DIR):

                pasta = os.path.join(cfg.DONE_DIR, nome)

                if not os.path.isdir(pasta) or busca not in nome.lower():
                    continue

                arquivos = os.listdir(pasta)

                itens.append({
                    "nome": nome,
                    "modificado": time.strftime(
                        "%Y-%m-%dT%H:%M:%S",
                        time.localtime(os.path.getmtime(pasta))),
                    "resumo": f"{nome}_resumo.txt" in arquivos,
                    "transcricao": f"{nome}.txt" in arquivos,
                    "diarizado": f"{nome}_diarizado.txt" in arquivos,
                    "log": "pipeline.log" in arquivos,
                })

    else:

        nomes = {}

        for pasta, sufixo, chave in (
            (cfg.AUDIOS_DIR, ".mp3", "audio"),
            (cfg.TRANS_DIR, ".txt", "transcricao"),
            (cfg.DIARIZ_DIR, "_diarizado.txt", "diarizado"),
            (cfg.RESUMOS_DIR, "_resumo.txt", "resumo"),
        ):

            if not os.path.isdir(pasta):
                continue

            for a in os.listdir(pasta):

                if a.endswith(".parcial") or not a.endswith(sufixo):
                    continue

                # transcricao ".txt" não pode casar com "_resumo.txt"
                if chave == "transcricao" and (
                    a.endswith("_diarizado.txt") or a.endswith("_resumo.txt")
                ):
                    continue

                nome = a[: -len(sufixo)]

                d = nomes.setdefault(nome, {"nome": nome})
                d[chave] = True
                d["modificado"] = time.strftime(
                    "%Y-%m-%dT%H:%M:%S",
                    time.localtime(os.path.getmtime(os.path.join(pasta, a))))

        for nome, d in nomes.items():

            if busca in nome.lower() and not os.path.isdir(
                os.path.join(cfg.DONE_DIR, nome)
            ):
                itens.append(d)

    itens.sort(key=lambda i: i.get("modificado", ""), reverse=True)

    return itens


def caminho_arquivo(nome, tipo, aba):

    if not _nome_valido(nome) or tipo not in _TIPOS_ARQUIVO:
        return None

    arquivo = _TIPOS_ARQUIVO[tipo].format(nome=nome)

    if aba == "concluidos":
        caminho = os.path.join(cfg.DONE_DIR, nome, arquivo)
        base = cfg.DONE_DIR
    else:
        pasta = {
            "resumo": cfg.RESUMOS_DIR,
            "transcricao": cfg.TRANS_DIR,
            "diarizado": cfg.DIARIZ_DIR,
        }.get(tipo)

        if not pasta:
            return None

        caminho = os.path.join(pasta, arquivo)
        base = pasta

    if not _contem_dentro(base, caminho) or not os.path.isfile(caminho):
        return None

    return caminho


def pasta_resultado(nome, aba):

    if not _nome_valido(nome):
        return None

    caminho = (
        os.path.join(cfg.DONE_DIR, nome) if aba == "concluidos"
        else cfg.BASE_DIR
    )

    return caminho if os.path.isdir(caminho) else None
