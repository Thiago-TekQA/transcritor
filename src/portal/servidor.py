"""Portal local do Transcritor — servidor web (aiohttp) em 127.0.0.1.

Só mostra/inicia/controla execuções. Nunca importa torch/whisperx: o
processamento roda num subprocesso separado (o próprio pipeline), que
continua mesmo se este servidor for fechado.
"""

import asyncio
import json
import os
import secrets
import sys
import threading
import urllib.request
import webbrowser

PASTA_PORTAL = os.path.dirname(os.path.abspath(__file__))
PASTA_SRC = os.path.dirname(PASTA_PORTAL)

sys.path.insert(0, PASTA_SRC)
sys.path.insert(0, PASTA_PORTAL)

from aiohttp import web  # noqa: E402

import pipeline_config as cfg  # noqa: E402
import execucoes as ex  # noqa: E402
import ambiente as amb  # noqa: E402

PORTA = int(cfg.CONFIG.get("portal_porta") or 8765)
HOSTS_OK = {f"127.0.0.1:{PORTA}", f"localhost:{PORTA}"}
ORIGENS_OK = {f"http://127.0.0.1:{PORTA}", f"http://localhost:{PORTA}"}

# Token aleatório por processo, embutido no index.html: prova que o POST
# veio da página servida por nós (e não de outro site no navegador).
TOKEN = secrets.token_urlsafe(24)

PASTA_STATIC = os.path.join(PASTA_PORTAL, "static")
LIMITE_ARQUIVO = 3 * 1024 * 1024


def _json(dados, status=200):

    return web.json_response(
        dados, status=status, dumps=lambda d: json.dumps(d, ensure_ascii=False)
    )


def _erro(msg, status=400):

    return _json({"erro": msg}, status)


async def _bloqueante(func, *args):

    return await asyncio.get_running_loop().run_in_executor(None, func, *args)


async def _corpo(request):

    try:
        dados = await request.json()
    except Exception:
        return {}

    return dados if isinstance(dados, dict) else {}


# =========================================================
# SEGURANÇA
# =========================================================


@web.middleware
async def seguranca(request, handler):

    # DNS rebinding: só aceita o nosso próprio endereço
    if request.headers.get("Host", "") not in HOSTS_OK:
        return _erro("host não permitido", 403)

    if request.method not in ("GET", "HEAD"):

        if request.headers.get("X-Token") != TOKEN:
            return _erro("token inválido", 403)

        origem = request.headers.get("Origin")

        if origem and origem not in ORIGENS_OK:
            return _erro("origem não permitida", 403)

        if not request.headers.get("Content-Type", "").startswith(
            "application/json"
        ):
            return _erro("use application/json", 415)

    resposta = await handler(request)

    resposta.headers["Cache-Control"] = "no-store"
    resposta.headers["X-Content-Type-Options"] = "nosniff"

    return resposta


# =========================================================
# PÁGINA E ESTÁTICOS
# =========================================================


async def pagina(request):

    with open(
        os.path.join(PASTA_STATIC, "index.html"), "r", encoding="utf-8"
    ) as f:
        html = f.read().replace("__TOKEN__", TOKEN)

    return web.Response(text=html, content_type="text/html")


async def estatico(request):

    nome = request.match_info["nome"]

    # só arquivos que existem diretamente em portal/static
    if nome not in os.listdir(PASTA_STATIC) or nome == "index.html":
        return _erro("não encontrado", 404)

    return web.FileResponse(os.path.join(PASTA_STATIC, nome))


# =========================================================
# API
# =========================================================


async def ping(request):

    return _json({"ok": True, "portal": "transcritor"})


async def config(request):

    c = cfg.CONFIG

    return _json({
        "modelo_whisper": c.get("modelo_whisper"),
        "device": c.get("device"),
        "ollama_modelo": c.get("ollama_modelo"),
        "tem_token_hf": bool(c.get("hf_token")),
        "modelo_em_cache": cfg.modelo_em_cache(c.get("modelo_whisper")),
        "base_dir": cfg.BASE_DIR,
        "hardlink": bool(c.get("portal_hardlink")),
        "etapas": [
            {"chave": e, "rotulo": ex.ROTULOS_ETAPAS[e]}
            for e in cfg.ETAPAS_VALIDAS
        ],
    })


async def ambiente_verificar(request):

    return _json(await _bloqueante(amb.verificar))


async def ambiente_acao(request):

    d = await _corpo(request)

    try:
        await _bloqueante(amb.iniciar_acao, d.get("acao", ""), d.get("caminho"))
        return _json({"ok": True})
    except PermissionError as e:
        return _erro(str(e), 409)
    except ValueError as e:
        return _erro(str(e))


async def ambiente_tarefa(request):

    return _json(amb.estado_tarefa())


async def pastas(request):

    try:
        return _json(
            await _bloqueante(ex.listar_pastas, request.query.get("caminho", ""))
        )
    except ValueError as e:
        return _erro(str(e))


async def plano(request):

    d = await _corpo(request)

    try:
        return _json(await _bloqueante(
            ex.planejar, d.get("origem", ""), d.get("etapas", []),
            bool(d.get("recursivo"))
        ))
    except ValueError as e:
        return _erro(str(e))


async def execucoes_listar(request):

    return _json({
        "ativa": ex.execucao_ativa(),
        "execucoes": await _bloqueante(ex.listar_execucoes),
    })


async def execucoes_criar(request):

    d = await _corpo(request)

    try:

        run_id = await _bloqueante(
            ex.criar_execucao,
            d.get("origem", ""), d.get("etapas", []), d.get("itens", []),
            bool(d.get("recursivo")), d.get("modelo"), d.get("device"),
        )

        return _json({"id": run_id})

    except PermissionError as e:
        return _erro(str(e), 409)
    except ValueError as e:
        return _erro(str(e))


async def execucao_estado(request):

    estado = await _bloqueante(ex.montar_estado, request.match_info["id"])

    return _json(estado) if estado else _erro("execução não encontrada", 404)


async def execucao_log(request):

    try:
        linhas = max(1, min(1000, int(request.query.get("linhas", 200))))
    except ValueError:
        linhas = 200

    return _json({
        "linhas": await _bloqueante(ex.ler_log, request.match_info["id"], linhas)
    })


async def execucao_parar(request):

    try:
        await _bloqueante(ex.parar_execucao, request.match_info["id"])
        return _json({"ok": True})
    except ValueError as e:
        return _erro(str(e), 404)


async def execucao_cancelar(request):

    try:
        modo = await _bloqueante(ex.cancelar_execucao, request.match_info["id"])
        return _json({"ok": True, "modo": modo})
    except ValueError as e:
        return _erro(str(e))


async def execucao_retomar(request):

    try:
        novo = await _bloqueante(ex.retomar_execucao, request.match_info["id"])
        return _json({"id": novo})
    except PermissionError as e:
        return _erro(str(e), 409)
    except ValueError as e:
        return _erro(str(e))


async def resultados(request):

    aba = "parciais" if request.query.get("aba") == "parciais" else "concluidos"

    return _json({
        "itens": await _bloqueante(
            ex.listar_resultados, aba, request.query.get("busca", "")
        )
    })


async def resultado_arquivo(request):

    aba = "parciais" if request.query.get("aba") == "parciais" else "concluidos"

    caminho = ex.caminho_arquivo(
        request.match_info["nome"], request.query.get("tipo", ""), aba
    )

    if not caminho:
        return _erro("arquivo não encontrado", 404)

    def ler():

        with open(caminho, "rb") as f:
            dados = f.read(LIMITE_ARQUIVO + 1)

        return dados

    dados = await _bloqueante(ler)

    truncado = len(dados) > LIMITE_ARQUIVO

    return _json({
        "texto": dados[:LIMITE_ARQUIVO].decode("utf-8", errors="replace"),
        "truncado": truncado,
    })


async def resultado_abrir_pasta(request):

    d = await _corpo(request)

    aba = "parciais" if d.get("aba") == "parciais" else "concluidos"

    pasta = ex.pasta_resultado(request.match_info["nome"], aba)

    if not pasta:
        return _erro("pasta não encontrada", 404)

    os.startfile(pasta)  # abre no Explorer (somente leitura)

    return _json({"ok": True})


# =========================================================
# APP
# =========================================================


def criar_app():

    app = web.Application(middlewares=[seguranca])

    app.router.add_get("/", pagina)
    app.router.add_get("/static/{nome}", estatico)

    app.router.add_get("/api/ping", ping)
    app.router.add_get("/api/config", config)
    app.router.add_get("/api/ambiente", ambiente_verificar)
    app.router.add_post("/api/ambiente/acao", ambiente_acao)
    app.router.add_get("/api/ambiente/tarefa", ambiente_tarefa)
    app.router.add_get("/api/pastas", pastas)
    app.router.add_post("/api/plano", plano)

    app.router.add_get("/api/execucoes", execucoes_listar)
    app.router.add_post("/api/execucoes", execucoes_criar)
    app.router.add_get("/api/execucoes/{id}", execucao_estado)
    app.router.add_get("/api/execucoes/{id}/log", execucao_log)
    app.router.add_post("/api/execucoes/{id}/parar", execucao_parar)
    app.router.add_post("/api/execucoes/{id}/cancelar", execucao_cancelar)
    app.router.add_post("/api/execucoes/{id}/retomar", execucao_retomar)

    app.router.add_get("/api/resultados", resultados)
    app.router.add_get("/api/resultados/{nome}/arquivo", resultado_arquivo)
    app.router.add_post(
        "/api/resultados/{nome}/abrir-pasta", resultado_abrir_pasta
    )

    return app


def ja_esta_rodando():

    try:

        with urllib.request.urlopen(
            f"http://127.0.0.1:{PORTA}/api/ping", timeout=2
        ) as r:
            return json.loads(r.read()).get("portal") == "transcritor"

    except Exception:

        return False


def main():

    url = f"http://127.0.0.1:{PORTA}/"

    if ja_esta_rodando():

        print(f"O portal já está aberto em {url} — abrindo o navegador.")
        webbrowser.open(url)

        return

    print("=" * 60)
    print("  PORTAL DO TRANSCRITOR")
    print(f"  Endereço: {url}")
    print("  Fechar esta janela NÃO interrompe uma execução em andamento.")
    print("  Para encerrar só o portal: Ctrl+C.")
    print("=" * 60)

    if "--sem-navegador" not in sys.argv:
        threading.Timer(1.5, webbrowser.open, args=(url,)).start()

    web.run_app(
        criar_app(), host="127.0.0.1", port=PORTA, print=None,
        access_log=None,
    )


if __name__ == "__main__":
    main()
