"""Diagnóstico de rede/certificados e dos modelos locais.

Uso pela linha de comando (Diagnostico_Rede.bat) ou pelo portal (tela
Ambiente, que roda `diagnostico_rede.py --json` no mesmo Python do pipeline).

Mostra por que o download do modelo de transcrição (Hugging Face) pode
falhar — em geral, um antivírus ou proxy que reassina o HTTPS com um
certificado que o Python não conhece — e o que fazer.
"""

import importlib.metadata
import json
import os
import shutil
import socket
import ssl
import sys
import tempfile
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import pipeline_config as cfg  # noqa: E402


def emissor_do_certificado(host):
    """Nome de quem emitiu o certificado que a rede entrega para `host`
    (revela o antivírus/proxy: Kaspersky, Zscaler, Netskope, Fortinet…)."""

    try:

        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE

        with socket.create_connection((host, 443), timeout=15) as s:
            with ctx.wrap_socket(s, server_hostname=host) as ss:
                der = ss.getpeercert(binary_form=True)

        pem = ssl.DER_cert_to_PEM_cert(der)

        with tempfile.NamedTemporaryFile("w", suffix=".pem", delete=False) as f:
            f.write(pem)
            caminho = f.name

        info = ssl._ssl._test_decode_cert(caminho)  # API interna, só p/ diagnóstico
        os.remove(caminho)

        partes = dict(x[0] for x in info.get("issuer", ()))

        return partes.get("organizationName") or partes.get("commonName") or str(partes)

    except Exception as e:

        return f"(não consegui ler: {e})"


def _ollama_modelo_no_disco(nome):

    if not nome:
        return False

    base = os.environ.get("OLLAMA_MODELS") or os.path.join(
        os.path.expanduser("~"), ".ollama", "models"
    )

    repo, _, tag = nome.partition(":")
    tag = tag or "latest"

    partes = repo.split("/")

    if len(partes) == 1:
        partes = ["library"] + partes

    return os.path.exists(os.path.join(
        base, "manifests", "registry.ollama.ai", *partes, tag
    ))


def coletar():
    """Verifica o ambiente e devolve tudo num dicionário."""

    d = {
        "python": sys.version.split()[0],
        "executavel": sys.executable,
        "venv": sys.prefix != sys.base_prefix,
        "ffmpeg": bool(shutil.which("ffmpeg")),
    }

    try:
        d["pip_system_certs"] = importlib.metadata.version("pip-system-certs")
    except importlib.metadata.PackageNotFoundError:
        d["pip_system_certs"] = None

    # layout das pastas de trabalho: direto na raiz (antigo) ou em dados/
    d["layout"] = {
        "base_dir": cfg.BASE_DIR,
        "legado": os.path.normcase(os.path.normpath(cfg.BASE_DIR))
        == os.path.normcase(os.path.normpath(cfg.PASTA_RAIZ)),
    }

    ca = cfg.CONFIG.get("ca_bundle")
    d["ca_bundle"] = {
        "caminho": ca or "",
        "existe": bool(ca) and os.path.exists(ca),
    }

    modelo = cfg.CONFIG.get("modelo_whisper")
    d["modelo"] = {
        "nome": modelo,
        "pasta": cfg.pasta_cache_hf(),
        "em_cache": cfg.modelo_em_cache(modelo),
    }

    # Acesso ao Hugging Face, do jeito que o pipeline acessa (requests)
    hf = {"ok": False, "ssl": False, "erro": "", "emissor": ""}

    try:

        import requests

        r = requests.get("https://huggingface.co", timeout=20)
        hf["ok"] = True
        hf["status"] = r.status_code

    except Exception as e:

        texto = str(e)

        hf["erro"] = texto[:240]

        if "CERTIFICATE_VERIFY_FAILED" in texto or "SSLError" in texto:
            hf["ssl"] = True
            hf["emissor"] = emissor_do_certificado("huggingface.co")

    d["huggingface"] = hf

    # Ollama
    oll = {
        "rodando": False,
        "modelos": [],
        "modelo_alvo": cfg.CONFIG.get("ollama_modelo"),
        "tem_modelo": False,
        "instalado": bool(shutil.which("ollama")),
    }

    try:

        with urllib.request.urlopen(
            "http://localhost:11434/api/tags", timeout=5
        ) as r:
            oll["modelos"] = [m["name"] for m in json.load(r).get("models", [])]

        oll["rodando"] = True
        oll["tem_modelo"] = oll["modelo_alvo"] in oll["modelos"]

    except Exception:

        # Servidor desligado: não dá pra listar, mas o modelo baixado deixa
        # um manifesto na pasta de modelos do Ollama.
        oll["tem_modelo"] = _ollama_modelo_no_disco(oll["modelo_alvo"])

    d["ollama"] = oll

    return d


def imprimir(d):

    def titulo(t):
        print()
        print("=" * 60)
        print(f"  {t}")
        print("=" * 60)

    problemas = []

    titulo("1. Ambiente")
    print(f"  Python: {d['python']}  ({d['executavel']})")
    print(f"  Dentro de ambiente virtual: {d['venv']}")
    print(f"  FFmpeg: {'encontrado' if d['ffmpeg'] else 'NÃO encontrado'}")

    if d["pip_system_certs"]:
        print(f"  pip-system-certs: instalado ({d['pip_system_certs']})")
    else:
        print("  pip-system-certs: NÃO instalado")
        problemas.append("pip-system-certs")

    if d["ca_bundle"]["caminho"]:
        print(f"  config.json ca_bundle = {d['ca_bundle']['caminho']}"
              f"  ({'existe' if d['ca_bundle']['existe'] else 'ARQUIVO NÃO ENCONTRADO'})")

    m = d["modelo"]

    titulo("2. Modelo de transcrição neste computador")
    print(f"  Modelo configurado: {m['nome']}")
    print(f"  Pasta de modelos:   {m['pasta']}")
    print(f"  Já está baixado:    "
          f"{'SIM (não precisa de internet)' if m['em_cache'] else 'NÃO'}")

    hf = d["huggingface"]

    titulo("3. Acesso ao Hugging Face (download do modelo)")

    if hf["ok"]:
        print(f"  huggingface.co: OK (HTTP {hf.get('status')})")
    elif hf["ssl"]:
        problemas.append("ssl")
        print("  huggingface.co: FALHOU — certificado não confiável")
        print(f"  Detalhe: {hf['erro']}")
        print(f"  Quem assina o certificado entregue pela rede: {hf['emissor']}")
        print("  Isso acontece quando um antivírus (Kaspersky, ESET, Avast,")
        print("  Bitdefender...) ou o proxy da empresa inspeciona o HTTPS e")
        print("  reassina os certificados. O nome acima mostra quem é.")
    else:
        problemas.append("rede")
        print(f"  huggingface.co: FALHOU — {hf['erro']}")

    o = d["ollama"]

    titulo("4. Ollama (resumo)")

    if o["rodando"]:
        print(f"  Ollama no ar. Modelos: {', '.join(o['modelos']) or '(nenhum)'}")
        if not o["tem_modelo"]:
            print(f"  FALTA o modelo '{o['modelo_alvo']}'  ->  ollama pull {o['modelo_alvo']}")
    else:
        print("  Ollama não está respondendo (o pipeline tenta ligá-lo "
              "sozinho na etapa de resumo).")

    titulo("O QUE FAZER")

    if not problemas and m["em_cache"]:
        print("  Tudo certo: nada a corrigir.")
        return

    if "pip-system-certs" in problemas:
        print("  [1] Instale o pacote que faz o Python usar os certificados do")
        print("      Windows (resolve a maioria das redes corporativas):")
        print(f'      "{d["executavel"]}" -m pip install pip-system-certs')
        print("      e rode este diagnóstico de novo.")
        print("      (No portal: tela Ambiente > Instalar suporte a certificados.)")
        print()

    if "ssl" in problemas:
        print("  [2] Se ainda falhar com pip-system-certs instalado, o certificado")
        print("      do antivírus/empresa não está no repositório do Windows. Exporte")
        print("      o certificado raiz dele (Base64, .pem/.cer) — ou peça ao TI — e")
        print('      informe o caminho no config.json:  "ca_bundle": "C:\\\\pasta\\\\empresa.pem"')
        print("      (outra saída: desativar a verificação de HTTPS do antivírus só")
        print("      para o domínio huggingface.co, nas configurações dele).")
        print()

    if not m["em_cache"]:
        print("  [3] Alternativa sem internet: leve o modelo de outro computador que")
        print("      já o tenha baixado.")
        print(f"      Computador de origem:  python transferir_modelo.py exportar {m['nome']}")
        print(f"      Este computador:       python transferir_modelo.py importar <caminho>\\modelo_{m['nome']}.zip")
        print("      Depois disso a transcrição funciona totalmente offline.")


def main():

    dados = coletar()

    if "--json" in sys.argv:
        print(json.dumps(dados, ensure_ascii=False))
    else:
        imprimir(dados)


if __name__ == "__main__":
    main()
