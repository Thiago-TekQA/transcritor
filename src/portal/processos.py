"""Mapeamento (e encerramento) dos processos do transcritor na máquina.

Lista pipelines, workers, FFmpeg, Ollama e outros portais — inclusive de
OUTRAS instalações/cópias do projeto —, agrupados por quem iniciou quem, com
CPU/RAM/GPU, para o usuário ver quem está disputando a GPU e poder encerrar.

Segurança: só é possível encerrar um PID que apareça no mapeamento atual
(nunca um número arbitrário), nunca o próprio portal nem os "pais" dele.
"""

import json
import os
import re
import subprocess
import time

import pipeline_config as cfg
import execucoes as ex

# (tipo, rótulo, padrão no nome do script/linha de comando)
_SCRIPTS = [
    ("pipeline", "Pipeline",
     re.compile(r'(?:^|[\s"\\/])pipeline(?:_transcricao_reestruturado)?\.py\b', re.I)),
    ("worker", "Worker de transcrição",
     re.compile(r'(?:^|[\s"\\/])transcrever_arquivo\.py\b', re.I)),
    ("worker", "Worker de diarização",
     re.compile(r'(?:^|[\s"\\/])diarizar_arquivo\.py\b', re.I)),
    ("worker", "Worker de vozes",
     re.compile(r'(?:^|[\s"\\/])extrair_embeddings_voz\.py\b', re.I)),
    ("portal", "Portal",
     re.compile(r'(?:^|[\s"\\/])servidor\.py\b', re.I)),
    ("reparo", "Reparo de resumos",
     re.compile(r'(?:^|[\s"\\/])regenerar_resumos\w*\.py\b', re.I)),
]

# caminhos absolutos de .py/.bat na linha de comando (entre aspas ou sem espaço)
_CAMINHO_ENTRE_ASPAS = re.compile(r'"([A-Za-z]:\\[^"]+?\.(?:py|bat))"', re.I)
_CAMINHO_SEM_ASPAS = re.compile(
    r'(?<![\w"\\])([A-Za-z]:\\\S+?\.(?:py|bat))(?=\s|"|$)', re.I
)

_NOMES_SCRIPT = {
    "pipeline.py", "pipeline_transcricao_reestruturado.py",
    "transcrever_arquivo.py", "diarizar_arquivo.py",
    "extrair_embeddings_voz.py", "servidor.py",
}


def classificar(nome, cmd):
    """(tipo, rótulo) do processo, ou None se não for do transcritor."""

    n = (nome or "").lower()
    cmd = cmd or ""

    if n in ("python.exe", "pythonw.exe", "py.exe"):

        for tipo, rotulo, padrao in _SCRIPTS:
            if padrao.search(cmd):
                return tipo, rotulo

        return None

    if n == "ffmpeg.exe":
        return "ffmpeg", "FFmpeg"

    if n == "ollama.exe":
        return "ollama", "Ollama"

    if n.startswith("llama") and n.endswith(".exe"):
        return "ollama", "Ollama (modelo carregado)"

    return None


def _caminho_do_script(cmd, aceitar_bat=False):
    """Caminho absoluto do script do transcritor (ou de um .bat) na linha de
    comando; ignora outros caminhos, como o --audio de um worker."""

    achados = _CAMINHO_ENTRE_ASPAS.findall(cmd or "")

    achados += [
        c for c in _CAMINHO_SEM_ASPAS.findall(cmd or "") if c not in achados
    ]

    for c in achados:

        base = os.path.basename(c).lower()

        if (
            base in _NOMES_SCRIPT
            or base.startswith("regenerar_resumos")
            or (aceitar_bat and base.endswith(".bat"))
        ):
            return c

    return None


def _local_da_instalacao(proc, por_pid, filhos):
    """Pasta da instalação a que o processo pertence, quando dá para saber.

    Scripts chamados por caminho relativo (ex.: o .bat antigo faz
    `python pipeline_....py`) não revelam a pasta; nesses casos usa o caminho
    absoluto de um worker filho ou do .bat que o iniciou."""

    def pasta(caminho):

        d = os.path.dirname(caminho)

        # src\\algo.py ou src\\portal\\servidor.py → raiz da instalação
        partes = d.replace("/", "\\").split("\\")

        if "src" in [p.lower() for p in partes]:
            i = [p.lower() for p in partes].index("src")
            return "\\".join(partes[:i])

        return d

    caminho = _caminho_do_script(proc["cmd"])

    if caminho:
        return pasta(caminho)

    for f in filhos.get(proc["pid"], []):

        c = _caminho_do_script(f["cmd"])

        if c:
            return pasta(c)

    # ancestrais: cmd.exe /c "…\\Executar Pipeline.bat"
    atual = por_pid.get(proc["ppid"])
    saltos = 0

    while atual and saltos < 6:

        c = _caminho_do_script(atual["cmd"], aceitar_bat=True)

        if c and c.lower().endswith(".bat"):
            return pasta(c)

        atual = por_pid.get(atual["ppid"])
        saltos += 1

    return None


def _mesma_pasta(a, b):

    if not a or not b:
        return False

    a = os.path.normcase(os.path.normpath(a))
    b = os.path.normcase(os.path.normpath(b))

    return a == b or a.startswith(b + os.sep)


def _e_orfao(proc, por_pid):
    """Processo que carrega o modelo do Ollama (llama-server) cujo servidor
    (`ollama serve`) já não existe: sobra de um desligamento incompleto, fica
    ocupando RAM sem servir ninguém."""

    if not (proc["nome"] or "").lower().startswith("llama"):
        return False

    pai = por_pid.get(proc["ppid"])

    return not pai or (pai["nome"] or "").lower() != "ollama.exe"


def montar_mapa(processos, gpu_por_pid, meu_pid, raiz_local, execucao_por_pid):
    """Função pura: transforma a lista bruta de processos do sistema no mapa
    mostrado na tela. `processos`: dicts com pid, ppid, nome, cmd, inicio
    (epoch), cpu_s, ram_mb. `execucao_por_pid`: {pid: id da execução do
    portal} das execuções desta instalação."""

    por_pid = {p["pid"]: p for p in processos}

    filhos = {}

    for p in processos:
        filhos.setdefault(p["ppid"], []).append(p)

    # ancestrais do próprio portal: nunca podem ser encerrados
    protegidos = set()
    atual = por_pid.get(meu_pid)

    while atual and atual["pid"] not in protegidos:
        protegidos.add(atual["pid"])
        atual = por_pid.get(atual["ppid"])

    relevantes = {}

    for p in processos:

        c = classificar(p["nome"], p["cmd"])

        if not c:
            continue

        tipo, rotulo = c

        local = _local_da_instalacao(p, por_pid, filhos) if tipo in (
            "pipeline", "worker", "portal", "reparo"
        ) else None

        relevantes[p["pid"]] = {
            "pid": p["pid"],
            "ppid": p["ppid"],
            "tipo": tipo,
            "rotulo": rotulo,
            "inicio": p["inicio"],
            "cpu_s": p["cpu_s"],
            "ram_mb": p["ram_mb"],
            "gpu_mb": gpu_por_pid.get(p["pid"]),
            "comando": (p["cmd"] or "")[:260],
            "local": local,
            "desta_instalacao": _mesma_pasta(local, raiz_local) if local else None,
            "execucao": execucao_por_pid.get(p["pid"]),
            "proprio": p["pid"] == meu_pid,
            "protegido": p["pid"] in protegidos,
            "orfao": _e_orfao(p, por_pid),
            "filhos": [],
        }

    # agrupa por "quem iniciou quem" entre os relevantes
    def pai_relevante(pid):

        atual = por_pid.get(por_pid[pid]["ppid"]) if pid in por_pid else None
        saltos = 0

        while atual and saltos < 8:

            if atual["pid"] in relevantes:
                return atual["pid"]

            atual = por_pid.get(atual["ppid"])
            saltos += 1

        return None

    raizes = []

    for pid, r in relevantes.items():

        pai = pai_relevante(pid)

        if pai is not None and pai != pid:
            relevantes[pai]["filhos"].append(r)
        else:
            raizes.append(r)

    for r in relevantes.values():
        r["filhos"].sort(key=lambda f: f["inicio"])

    raizes.sort(key=lambda r: r["inicio"])

    pipelines = [r for r in relevantes.values() if r["tipo"] == "pipeline"]
    portais = [r for r in relevantes.values() if r["tipo"] == "portal" and not r["proprio"]]

    alertas = []

    orfaos = [r for r in relevantes.values() if r["orfao"]]

    if orfaos:

        gb = sum(r["ram_mb"] for r in orfaos) / 1024

        alertas.append(
            f"{len(orfaos)} processo(s) do modelo do Ollama estão órfãos (sem "
            f"servidor) e ocupam cerca de {gb:.1f} GB de RAM à toa. Pode "
            "encerrá-los sem risco."
        )

    if len(pipelines) >= 2:

        alertas.append(
            f"{len(pipelines)} pipelines estão rodando ao mesmo tempo — eles "
            "disputam a GPU, a CPU e a memória (mais lentos e mais falhas de "
            "GPU). Considere encerrar um deles."
        )

    if portais:

        alertas.append(
            f"Há {len(portais)} outro(s) servidor(es) do portal em execução."
        )

    return {
        "raizes": raizes,
        "pipelines_ativos": len(pipelines),
        "orfaos": len(orfaos),
        "alertas": alertas,
    }


# ------------------------------------------------------------------ sistema

_PS = (
    "$ErrorActionPreference='SilentlyContinue';"
    "@(Get-CimInstance Win32_Process | ForEach-Object {"
    "[pscustomobject]@{"
    "pid=[int]$_.ProcessId;ppid=[int]$_.ParentProcessId;nome=$_.Name;"
    "cmd=$_.CommandLine;"
    "inicio=[int64]([DateTimeOffset]$_.CreationDate).ToUnixTimeSeconds();"
    "cpu_s=[math]::Round(([double]$_.KernelModeTime+[double]$_.UserModeTime)/1e7,1);"
    "ram_mb=[math]::Round($_.WorkingSetSize/1MB)}"
    "}) | ConvertTo-Json -Compress -Depth 3"
)


def _ler_processos():

    r = subprocess.run(
        ["powershell", "-NoProfile", "-Command", _PS],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
        timeout=45, creationflags=subprocess.CREATE_NO_WINDOW,
    )

    dados = json.loads(r.stdout or "[]")

    if isinstance(dados, dict):
        dados = [dados]

    return dados


def _ler_gpu():
    """({pid: MiB}, resumo da GPU). O Windows nem sempre informa a memória
    por processo; nesse caso o valor fica ausente."""

    por_pid = {}
    resumo = None

    try:

        r = subprocess.run(
            ["nvidia-smi", "--query-gpu=name,utilization.gpu,temperature.gpu,"
             "memory.used,memory.total", "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=10,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )

        if r.returncode == 0 and r.stdout.strip():

            nome, uso, temp, usada, total = [
                x.strip() for x in r.stdout.splitlines()[0].split(",")
            ]

            resumo = {
                "nome": nome, "uso_pct": int(uso), "temp_c": int(temp),
                "mem_usada_mb": int(usada), "mem_total_mb": int(total),
            }

        r = subprocess.run(
            ["nvidia-smi", "--query-compute-apps=pid,used_memory",
             "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=10,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )

        for linha in r.stdout.splitlines():

            partes = [x.strip() for x in linha.split(",")]

            if len(partes) == 2 and partes[0].isdigit() and partes[1].isdigit():
                por_pid[int(partes[0])] = int(partes[1])

    except Exception:

        pass

    return por_pid, resumo


def _execucoes_por_pid():
    """{pid do pipeline: id da execução} das execuções do portal ainda ativas."""

    mapa = {}

    if not os.path.isdir(ex.EXECUCOES_DIR):
        return mapa

    for rid in sorted(os.listdir(ex.EXECUCOES_DIR), reverse=True)[:15]:

        proc = ex._ler_json(
            os.path.join(ex.EXECUCOES_DIR, rid, "proc.json"), {}
        )

        pid = proc.get("pid")

        if pid and ex.processo_vivo(pid):
            mapa[int(pid)] = rid

    return mapa


def listar():

    brutos = _ler_processos()

    processos = [
        {
            "pid": p["pid"], "ppid": p["ppid"], "nome": p["nome"],
            "cmd": p.get("cmd"), "inicio": p.get("inicio") or 0,
            "cpu_s": p.get("cpu_s") or 0, "ram_mb": p.get("ram_mb") or 0,
        }
        for p in brutos
    ]

    gpu_pid, gpu = _ler_gpu()

    mapa = montar_mapa(
        processos, gpu_pid, os.getpid(), cfg.PASTA_RAIZ, _execucoes_por_pid()
    )

    mapa["gpu"] = gpu
    mapa["agora"] = int(time.time())

    return mapa


# ------------------------------------------------------------------ encerrar


def _achatar(raizes):

    for r in raizes:
        yield r
        yield from _achatar(r["filhos"])


def encerrar(pid):
    """Encerra um processo do mapa (com seus filhos). Devolve um texto com
    o que foi feito."""

    try:
        pid = int(pid)
    except (TypeError, ValueError):
        raise ValueError("PID inválido")

    mapa = listar()

    alvo = next((r for r in _achatar(mapa["raizes"]) if r["pid"] == pid), None)

    if not alvo:
        raise ValueError("este processo não está (mais) no mapa do transcritor")

    if alvo["proprio"] or alvo["protegido"]:
        raise ValueError("este é o próprio portal (ou quem o iniciou) — "
                         "feche a janela dele em vez de encerrá-lo por aqui")

    # execução desta instalação iniciada pelo portal: usa o cancelamento
    # completo (mata a árvore e limpa só a saída da etapa interrompida)
    if alvo["tipo"] == "pipeline" and alvo["execucao"]:

        modo = ex.cancelar_execucao(alvo["execucao"])

        return f"Execução {alvo['execucao']} cancelada ({modo})."

    subprocess.run(
        ["taskkill", "/PID", str(pid), "/T", "/F"],
        capture_output=True, creationflags=subprocess.CREATE_NO_WINDOW,
    )

    for _ in range(20):

        if not ex.processo_vivo(pid):
            break

        time.sleep(0.25)

    msg = f"Processo {pid} ({alvo['rotulo']}) encerrado."

    if alvo["tipo"] in ("pipeline", "worker") and alvo["desta_instalacao"]:

        # sobra de uma etapa pela metade nesta instalação: limpa
        removidos, _ = cfg.limpar_interrompidos()

        if removidos:
            msg += f" {len(removidos)} arquivo(s) parcial(is) removido(s)."

    elif alvo["tipo"] in ("pipeline", "worker"):

        msg += (" Era de outra instalação"
                + (f" ({alvo['local']})" if alvo["local"] else "")
                + ": o que ele estava processando pode ter deixado arquivos "
                  "parciais lá; eles são descartados na próxima execução dela.")

    return msg
