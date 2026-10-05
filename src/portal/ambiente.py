"""Verificação e correção do ambiente (tela "Ambiente" do portal).

As verificações rodam `diagnostico_rede.py --json` com o MESMO Python do
pipeline (o .venv, quando existe), para refletir o que o pipeline vai
enfrentar de verdade. As correções rodam em subprocesso, uma por vez, com
a saída acompanhada pela tela.
"""

import json
import os
import re
import shutil
import subprocess
import sys
import threading
import time
import urllib.request

import pipeline_config as cfg
import execucoes as ex

_ANSI = re.compile(r"\x1b\[[0-9;?]*[A-Za-z]")

_tarefa = {"acao": None, "estado": "ocioso", "texto": "", "codigo": None}
_trava = threading.Lock()

ACOES = ("instalar_certs", "baixar_modelo", "importar_modelo", "baixar_ollama")


def _env():

    env = dict(os.environ)
    env["PYTHONUTF8"] = "1"
    env["PYTHONUNBUFFERED"] = "1"
    env["HF_HUB_DISABLE_SYMLINKS_WARNING"] = "1"

    return env


def verificar():
    """Diagnóstico completo (dicionário). Pode levar até ~30 s se a rede
    estiver bloqueando o Hugging Face."""

    cmd = [
        ex.python_do_pipeline(), "-X", "utf8",
        os.path.join(cfg.PASTA_SCRIPTS, "diagnostico_rede.py"), "--json",
    ]

    try:

        r = subprocess.run(
            cmd, capture_output=True, text=True, encoding="utf-8",
            errors="replace", timeout=90, env=_env(), cwd=cfg.PASTA_SCRIPTS,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )

    except subprocess.TimeoutExpired:

        return {"erro": "a verificação demorou demais (rede sem resposta)"}

    for linha in reversed(r.stdout.splitlines()):

        if linha.startswith("{"):

            try:
                return json.loads(linha)
            except ValueError:
                break

    return {"erro": (r.stderr or r.stdout or "sem resposta")[-300:]}


# ------------------------------------------------------------------ tarefas


def _acrescentar(texto):

    for parte in str(texto).replace("\r", "\n").split("\n"):

        parte = _ANSI.sub("", parte).strip()

        if parte:
            _tarefa["texto"] = (_tarefa["texto"] + "\n" + parte)[-4000:]


def _executar(cmd):

    proc = subprocess.Popen(
        cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        text=True, encoding="utf-8", errors="replace", bufsize=1,
        env=_env(), cwd=cfg.PASTA_SCRIPTS,
        creationflags=subprocess.CREATE_NO_WINDOW,
    )

    # ollama/pip escrevem progresso com \r: lê por pedaços, não por linha
    buffer = ""

    while True:

        pedaco = proc.stdout.read(1)

        if not pedaco:
            break

        if pedaco in ("\r", "\n"):
            if buffer.strip():
                _acrescentar(buffer)
            buffer = ""
        else:
            buffer += pedaco

    if buffer.strip():
        _acrescentar(buffer)

    return proc.wait()


def _ollama_no_ar():

    try:
        urllib.request.urlopen("http://localhost:11434/api/version", timeout=3)
        return True
    except Exception:
        return False


def _acao_ollama():

    modelo = cfg.CONFIG.get("ollama_modelo")

    if not shutil.which("ollama"):

        _acrescentar("Ollama não está instalado. Instale com: "
                     "winget install Ollama.Ollama (e reabra o portal).")
        return 1

    iniciado = None

    if not _ollama_no_ar():

        _acrescentar("Ligando o Ollama temporariamente...")

        iniciado = subprocess.Popen(
            ["ollama", "serve"], stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )

        for _ in range(30):

            if _ollama_no_ar():
                break

            time.sleep(1)

    try:

        _acrescentar(f"Baixando o modelo {modelo} (~2 GB)...")

        return _executar(["ollama", "pull", modelo])

    finally:

        if iniciado is not None:
            cfg.encerrar_arvore(iniciado.pid)


def _comando(acao, caminho):

    py = ex.python_do_pipeline()

    if acao == "instalar_certs":
        return [py, "-m", "pip", "install", "pip-system-certs"]

    if acao == "baixar_modelo":

        modelo = str(cfg.CONFIG.get("modelo_whisper") or "")

        if not re.fullmatch(r"[A-Za-z0-9._-]+", modelo):
            raise ValueError("nome de modelo inválido no config.json")

        return [py, "-c",
                "from faster_whisper.utils import download_model; "
                f"print(download_model('{modelo}'))"]

    if acao == "importar_modelo":

        caminho = os.path.abspath(str(caminho or "").strip().strip('"'))

        if not caminho.lower().endswith(".zip") or not os.path.isfile(caminho):
            raise ValueError("informe o caminho de um arquivo .zip existente")

        return [py, os.path.join(cfg.PASTA_SCRIPTS, "transferir_modelo.py"),
                "importar", caminho]

    return None


def iniciar_acao(acao, caminho=None):

    if acao not in ACOES:
        raise ValueError("ação desconhecida")

    with _trava:

        if _tarefa["estado"] == "rodando":
            raise PermissionError("já existe uma correção em andamento")

        cmd = None if acao == "baixar_ollama" else _comando(acao, caminho)

        _tarefa.update(acao=acao, estado="rodando", texto="", codigo=None)

    def rodar():

        try:

            codigo = _acao_ollama() if cmd is None else _executar(cmd)

        except Exception as e:

            _acrescentar(f"Erro: {e}")
            codigo = 1

        _tarefa["codigo"] = codigo
        _tarefa["estado"] = "ok" if codigo == 0 else "erro"

    threading.Thread(target=rodar, daemon=True).start()


def estado_tarefa():

    return dict(_tarefa)
