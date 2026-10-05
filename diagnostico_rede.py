"""Diagnóstico de rede/certificados e dos modelos locais.

Rode pelo Diagnostico_Rede.bat. Mostra por que o download do modelo de
transcrição (Hugging Face) falha — em geral, uma rede corporativa que
reassina o HTTPS com um certificado que o Python não conhece — e o que fazer.
"""

import importlib.metadata
import json
import os
import socket
import ssl
import sys
import tempfile
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import pipeline_config as cfg  # noqa: E402


def titulo(t):
    print()
    print("=" * 60)
    print(f"  {t}")
    print("=" * 60)


def emissor_do_certificado(host):
    """Nome de quem emitiu o certificado que a rede entrega para `host`
    (revela o proxy da empresa: Zscaler, Netskope, Fortinet etc.)."""

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


def main():

    problemas = []

    titulo("1. Ambiente")
    print(f"  Python: {sys.version.split()[0]}  ({sys.executable})")
    print(f"  Dentro de ambiente virtual: {sys.prefix != sys.base_prefix}")

    try:
        v = importlib.metadata.version("pip-system-certs")
        print(f"  pip-system-certs: instalado ({v})")
    except importlib.metadata.PackageNotFoundError:
        print("  pip-system-certs: NÃO instalado")
        problemas.append("pip-system-certs")

    for var in ("SSL_CERT_FILE", "REQUESTS_CA_BUNDLE", "HF_HUB_OFFLINE",
                "HTTPS_PROXY", "HTTP_PROXY"):
        if os.environ.get(var):
            print(f"  {var} = {os.environ[var]}")

    if cfg.CONFIG.get("ca_bundle"):
        ok = os.path.exists(cfg.CONFIG["ca_bundle"])
        print(f"  config.json ca_bundle = {cfg.CONFIG['ca_bundle']}"
              f"  ({'existe' if ok else 'ARQUIVO NÃO ENCONTRADO'})")

    titulo("2. Modelo de transcrição neste computador")
    modelo = cfg.CONFIG.get("modelo_whisper")
    em_cache = cfg.modelo_em_cache(modelo)
    print(f"  Modelo configurado: {modelo}")
    print(f"  Pasta de modelos:   {cfg.pasta_cache_hf()}")
    print(f"  Já está baixado:    "
          f"{'SIM (não precisa de internet)' if em_cache else 'NÃO'}")

    titulo("3. Acesso ao Hugging Face (download do modelo)")

    ssl_falhou = False

    try:

        import requests

        r = requests.get("https://huggingface.co", timeout=20)
        print(f"  huggingface.co: OK (HTTP {r.status_code})")

    except Exception as e:

        texto = str(e)

        if "CERTIFICATE_VERIFY_FAILED" in texto or "SSLError" in texto:
            ssl_falhou = True
            print("  huggingface.co: FALHOU — certificado não confiável")
            print(f"  Detalhe: {texto[:200]}")
            print(f"  Quem assina o certificado entregue pela rede: "
                  f"{emissor_do_certificado('huggingface.co')}")
            print("  Isso acontece quando um antivírus (Kaspersky, ESET, Avast,")
            print("  Bitdefender...) ou o proxy da empresa inspeciona o HTTPS e")
            print("  reassina os certificados. O nome acima mostra quem é.")
            problemas.append("ssl")
        else:
            print(f"  huggingface.co: FALHOU — {texto[:200]}")
            problemas.append("rede")

    titulo("4. Ollama (resumo)")

    try:

        with urllib.request.urlopen(
            "http://localhost:11434/api/tags", timeout=5
        ) as r:
            nomes = [m["name"] for m in json.load(r).get("models", [])]

        alvo = cfg.CONFIG.get("ollama_modelo")
        print(f"  Ollama no ar. Modelos: {', '.join(nomes) or '(nenhum)'}")

        if alvo not in nomes:
            print(f"  FALTA o modelo '{alvo}'  ->  ollama pull {alvo}")
            problemas.append("ollama_modelo")

    except Exception:

        print("  Ollama não está respondendo (o pipeline tenta ligá-lo "
              "sozinho na etapa de resumo).")

    titulo("O QUE FAZER")

    if not problemas and em_cache:
        print("  Tudo certo: nada a corrigir.")
        return

    if "pip-system-certs" in problemas:
        print("  [1] Instale o pacote que faz o Python usar os certificados do")
        print("      Windows (resolve a maioria das redes corporativas):")
        print(f'      "{sys.executable}" -m pip install pip-system-certs')
        print("      e rode este diagnóstico de novo.")
        print()

    if ssl_falhou:
        print("  [2] Se ainda falhar com pip-system-certs instalado, o certificado")
        print("      do antivírus/empresa não está no repositório do Windows. Exporte")
        print("      o certificado raiz dele (Base64, .pem/.cer) — ou peça ao TI — e")
        print('      informe o caminho no config.json:  "ca_bundle": "C:\\\\pasta\\\\empresa.pem"')
        print("      (outra saída: desativar a verificação de HTTPS do antivírus só")
        print("      para o domínio huggingface.co, nas configurações dele).")
        print()

    if not em_cache:
        print("  [3] Alternativa sem internet: leve o modelo de outro computador que")
        print("      já o tenha baixado.")
        print(f"      Computador de origem:  python transferir_modelo.py exportar {modelo}")
        print(f"      Este computador:       python transferir_modelo.py importar modelo_{modelo}.zip")
        print("      Depois disso a transcrição funciona totalmente offline.")


if __name__ == "__main__":
    main()
