"""Configuração e utilitários LEVES compartilhados pelo pipeline e pelo portal.

Este módulo NÃO importa torch, whisperx, numpy nem nada pesado — o portal
(servidor web) precisa dele sem carregar a pilha de IA. O pipeline_comum.py
importa tudo daqui, então os nomes `pc.BASE_DIR`, `pc.evento` etc. continuam
funcionando como antes.
"""

import json
import os
import shutil
import time

# Pasta onde estão os scripts (src/) — NÃO muda com o base_dir do config.json.
PASTA_SCRIPTS = os.path.dirname(os.path.abspath(__file__))

# Raiz do projeto/instalação: onde ficam config.json, .venv e dados/.
PASTA_RAIZ = os.path.dirname(PASTA_SCRIPTS)

# =========================================================
# CONFIGURAÇÃO POR MÁQUINA (config.json na raiz do projeto)
# =========================================================
# Nenhum valor sensível ou específico desta máquina fica no código — o
# token da Hugging Face, em particular, nunca deve ser escrito aqui.

CONFIG_PADRAO = {
    "base_dir": "",
    "hf_token": "",
    "modelo_whisper": "small",
    "device": "cuda",
    "ollama_modelo": "qwen2.5:3b-instruct",
    "portal_porta": 8765,
    "portal_hardlink": False,
    "ca_bundle": "",
}


def carregar_config():

    config = dict(CONFIG_PADRAO)

    caminho = os.path.join(PASTA_RAIZ, "config.json")

    if os.path.exists(caminho):

        with open(caminho, "r", encoding="utf-8") as f:
            config.update(json.load(f))

    # Variável de ambiente tem prioridade sobre o arquivo
    if os.environ.get("HF_TOKEN"):
        config["hf_token"] = os.environ["HF_TOKEN"]

    return config


CONFIG = carregar_config()

# Rede corporativa que reassina o HTTPS: se o config.json aponta um arquivo
# .pem com o certificado raiz da empresa, todo código Python (inclusive os
# workers, que herdam o ambiente) passa a confiar nele.
if CONFIG.get("ca_bundle"):

    for _var in ("SSL_CERT_FILE", "REQUESTS_CA_BUNDLE", "CURL_CA_BUNDLE"):
        os.environ[_var] = CONFIG["ca_bundle"]


def pasta_cache_hf():
    """Pasta onde o Hugging Face guarda os modelos baixados."""

    if os.environ.get("HF_HUB_CACHE"):
        return os.environ["HF_HUB_CACHE"]

    if os.environ.get("HF_HOME"):
        return os.path.join(os.environ["HF_HOME"], "hub")

    return os.path.join(os.path.expanduser("~"), ".cache", "huggingface", "hub")


def modelo_em_cache(modelo):
    """True se o modelo de transcrição já está neste computador (então a
    transcrição não precisa de internet). `modelo` pode ser o nome
    (small, medium…) ou o caminho de uma pasta com o modelo."""

    if not modelo:
        return False

    if os.path.isdir(modelo):
        return True

    pasta = os.path.join(
        pasta_cache_hf(), f"models--Systran--faster-whisper-{modelo}",
        "snapshots"
    )

    if not os.path.isdir(pasta):
        return False

    return any(
        os.path.exists(os.path.join(pasta, snap, "model.bin"))
        for snap in os.listdir(pasta)
    )



def _base_padrao():
    """Onde ficam as pastas de trabalho (1_Videos … 8_Resumos).

    Padrão: <raiz>/dados. Instalações antigas guardavam tudo direto na raiz;
    se já existe 6_Concluidos na raiz e ainda não existe dados/, mantém o
    layout antigo para o usuário não "perder" os dados que já tem."""

    dados = os.path.join(PASTA_RAIZ, "dados")
    legado = os.path.join(PASTA_RAIZ, "6_Concluidos")

    if os.path.isdir(legado) and not os.path.isdir(dados):
        return PASTA_RAIZ

    return dados


BASE_DIR = CONFIG["base_dir"] or _base_padrao()

VIDEOS_DIR = os.path.join(BASE_DIR, "1_Videos")
AUDIOS_DIR = os.path.join(BASE_DIR, "2_Audios")
TRANS_DIR = os.path.join(BASE_DIR, "3_Transcricoes")
DIARIZ_DIR = os.path.join(BASE_DIR, "4_Diarizacoes")
LOGS_DIR = os.path.join(BASE_DIR, "5_Logs")
DONE_DIR = os.path.join(BASE_DIR, "6_Concluidos")
PERFIS_VOZ_DIR = os.path.join(BASE_DIR, "7_Perfis_Voz")
RESUMOS_DIR = os.path.join(BASE_DIR, "8_Resumos")

# Dados do portal (execuções, eventos, logs de cada execução)
PORTAL_DIR = os.path.join(BASE_DIR, "_portal")

VIDEOS_SUPORTADOS = [
    ".mp4", ".mkv", ".avi", ".mov",
    ".ogg", ".wav", ".m4a", ".aac", ".flac"
]
AMOSTRAS_SUPORTADAS = VIDEOS_SUPORTADOS + [".mp3"]

# Etapas que o pipeline sabe executar (ordem de execução)
ETAPAS_VALIDAS = ["mp3", "transcricao", "diarizacao", "resumo", "consolidar"]

# Cada --modo equivale a um conjunto de etapas
ETAPAS_POR_MODO = {
    "completo": ["mp3", "transcricao", "diarizacao", "resumo", "consolidar"],
    "simples": ["mp3", "transcricao", "resumo", "consolidar"],
    "somente_mp3": ["mp3"],
    "somente_transcricao": ["transcricao"],
    "diarizacao": ["diarizacao"],
    "resumo": ["resumo"],
    "perfis_voz": [],
}


def sanitizar_nome(nome):

    caracteres_invalidos = '<>:"/\\|?*'

    for caractere in caracteres_invalidos:
        nome = nome.replace(caractere, "_")

    return nome.strip()


# =========================================================
# EVENTOS ESTRUTURADOS (lidos pelo portal)
# =========================================================
# O portal define TRANSCRITOR_EVENTOS=<arquivo .jsonl>. Cada evento é uma
# linha JSON gravada com UM write (append), então o leitor nunca vê uma
# linha pela metade a não ser a última. Sem a variável, evento() não faz
# nada — o pipeline roda igual pela linha de comando.

_CONTEXTO = {"etapa": None, "nome": None}


def evento(ev, **campos):

    caminho = os.environ.get("TRANSCRITOR_EVENTOS")

    if not caminho:
        return

    if ev == "item" and campos.get("estado") == "rodando":
        _CONTEXTO["etapa"] = campos.get("etapa")
        _CONTEXTO["nome"] = campos.get("nome")

    registro = {"v": 1, "ts": time.strftime("%Y-%m-%dT%H:%M:%S"), "ev": ev}
    registro.update(campos)

    try:

        with open(caminho, "a", encoding="utf-8") as f:
            f.write(json.dumps(registro, ensure_ascii=False) + "\n")

    except OSError:

        pass


def evento_progresso(pct):
    """Progresso (0-100) do item que está rodando agora."""

    evento(
        "progresso",
        etapa=_CONTEXTO["etapa"],
        nome=_CONTEXTO["nome"],
        pct=pct,
    )


def contexto_atual():

    return dict(_CONTEXTO)


# =========================================================
# PARADA SOLICITADA PELO PORTAL
# =========================================================


def parada_solicitada():

    caminho = os.environ.get("TRANSCRITOR_PARAR")

    return bool(caminho) and os.path.exists(caminho)


# =========================================================
# SELEÇÃO DE ITENS (--itens)
# =========================================================

_ITENS_SELECIONADOS = None


def definir_itens(lista):
    """None = sem filtro (comportamento legado: processa tudo que achar)."""

    global _ITENS_SELECIONADOS

    if lista is None:
        _ITENS_SELECIONADOS = None
    else:
        _ITENS_SELECIONADOS = {sanitizar_nome(n) for n in lista}


def item_selecionado(nome):

    if _ITENS_SELECIONADOS is None:
        return True

    return sanitizar_nome(nome) in _ITENS_SELECIONADOS


# =========================================================
# TRAVA DE EXECUÇÃO ÚNICA (a GPU é uma só)
# =========================================================

_ARQUIVO_TRAVA = None


def adquirir_trava():
    """Só uma execução do pipeline por vez (portal ou .bat). O Windows
    libera o lock sozinho quando o processo morre — não sobra trava velha.
    Devolve False se já existe outra execução."""

    global _ARQUIVO_TRAVA

    try:
        import msvcrt
    except ImportError:
        return True

    os.makedirs(BASE_DIR, exist_ok=True)

    caminho = os.path.join(BASE_DIR, ".pipeline.lock")

    f = open(caminho, "a+")

    try:

        f.seek(0)
        msvcrt.locking(f.fileno(), msvcrt.LK_NBLCK, 1)

    except OSError:

        f.close()
        return False

    _ARQUIVO_TRAVA = f

    return True


# =========================================================
# LIMPEZA DE EXECUÇÕES INTERROMPIDAS
# =========================================================
# Regra: ao interromper, apaga-se SÓ a saída da etapa que estava em
# andamento (os .parcial); vídeo, áudio e as saídas de etapas concluídas
# ficam. Toda saída é escrita num .parcial e renomeada só no fim.

MANIFESTO_CONSOLIDACAO = "_origem.json"


def _remover(caminho):

    try:
        os.remove(caminho)
        return True
    except OSError:
        return False


def _classificar_parcial(arquivo):
    """(etapa, nome do item) a partir do nome de um arquivo .parcial."""

    base = arquivo[: -len(".parcial")]

    if base.endswith(".mp3"):
        return "mp3", base[: -len(".mp3")]

    if base.endswith("_resumo.txt"):
        return "resumo", base[: -len("_resumo.txt")]

    if base.endswith("_diarizado.txt"):
        return "diarizacao", base[: -len("_diarizado.txt")]

    if base.endswith(".txt"):
        return "transcricao", base[: -len(".txt")]

    return "outro", base


def restaurar_consolidacao(pasta_montagem):
    """Desfaz uma consolidação interrompida: os arquivos já movidos para
    `6_Concluidos/<nome>.parcial/` voltam ao lugar de origem (vídeo, áudio,
    transcrição, diarização); as cópias do resumo e do log são descartadas.
    Devolve True se tudo foi desfeito."""

    nome = os.path.basename(pasta_montagem)[: -len(".parcial")]

    caminho_manifesto = os.path.join(pasta_montagem, MANIFESTO_CONSOLIDACAO)

    try:
        with open(caminho_manifesto, "r", encoding="utf-8") as f:
            manifesto = json.load(f)
    except (OSError, ValueError):
        manifesto = {}

    padrao = {
        f"{nome}_diarizado.txt": DIARIZ_DIR,
        f"{nome}.txt": TRANS_DIR,
        f"{nome}.mp3": AUDIOS_DIR,
    }

    ok = True

    try:
        arquivos = os.listdir(pasta_montagem)
    except OSError:
        return False

    for arq in arquivos:

        if arq == MANIFESTO_CONSOLIDACAO:
            continue

        origem = os.path.join(pasta_montagem, arq)

        pasta = manifesto.get(arq) or padrao.get(arq)

        if not pasta and os.path.splitext(arq)[1].lower() in VIDEOS_SUPORTADOS:
            pasta = VIDEOS_DIR

        if not pasta:
            # cópia do resumo / pipeline.log: sem origem a restaurar
            ok = _remover(origem) and ok
            continue

        destino = os.path.join(pasta, arq)

        if os.path.exists(destino):
            ok = _remover(origem) and ok
            continue

        try:
            os.makedirs(pasta, exist_ok=True)
            shutil.move(origem, destino)
        except OSError:
            ok = False

    _remover(caminho_manifesto)

    try:
        os.rmdir(pasta_montagem)
    except OSError:
        ok = False

    return ok


def limpar_interrompidos(registrar=None):
    """Remove o que execuções interrompidas deixaram pela metade.
    `registrar(dict)` é chamado para cada item limpo (etapa, nome, arquivo).
    Devolve (lista_de_removidos, quantidade_que_nao_deu_para_remover)."""

    removidos = []
    falhas = 0

    def reg(etapa, nome, arquivo):

        r = {"etapa": etapa, "nome": nome, "arquivo": arquivo}
        removidos.append(r)

        if registrar:
            registrar(r)

    for pasta in (AUDIOS_DIR, TRANS_DIR, DIARIZ_DIR, RESUMOS_DIR):

        if not os.path.isdir(pasta):
            continue

        for a in os.listdir(pasta):

            if a.endswith(".parcial"):

                if _remover(os.path.join(pasta, a)):
                    etapa, nome = _classificar_parcial(a)
                    reg(etapa, nome, a)
                else:
                    falhas += 1

    for pasta in (VIDEOS_DIR, AUDIOS_DIR):

        if not os.path.isdir(pasta):
            continue

        for a in os.listdir(pasta):

            if a.endswith(".copiando"):

                if _remover(os.path.join(pasta, a)):
                    reg("copiar", os.path.splitext(a[: -len(".copiando")])[0], a)
                else:
                    falhas += 1

    if os.path.isdir(DONE_DIR):

        for a in os.listdir(DONE_DIR):

            caminho = os.path.join(DONE_DIR, a)

            if a.endswith(".parcial") and os.path.isdir(caminho):

                if restaurar_consolidacao(caminho):
                    reg("consolidar", a[: -len(".parcial")], a)
                else:
                    falhas += 1

    return removidos, falhas


# =========================================================
# ENCERRAR ÁRVORE DE PROCESSOS
# =========================================================


def encerrar_arvore(pid):
    """Encerra um processo E todos os filhos dele (taskkill /T /F).

    Necessário no Windows: `Popen.terminate()` mata só o processo, e o
    `ollama serve` deixa para trás o processo que carrega o modelo
    (llama-server, ~3 GB de RAM cada) — que ficava órfão ocupando memória."""

    import subprocess

    try:

        subprocess.run(
            ["taskkill", "/PID", str(pid), "/T", "/F"],
            capture_output=True,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )

        return True

    except Exception:

        return False
