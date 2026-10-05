"""Gera Transcritor_pacote.zip para levar a outro computador.

Inclui só código, instalador e documentação. NUNCA inclui: config.json
(token), vídeos/áudios/transcrições/resumos (dados de reuniões),
perfis de voz, logs, .venv, modelos baixados e a pasta OLD.
"""

import os
import zipfile

PASTA = os.path.dirname(os.path.abspath(__file__))
SAIDA = os.path.join(PASTA, "Transcritor_pacote.zip")

ARQUIVOS = [
    "pipeline_transcricao_reestruturado.py",
    "pipeline_comum.py",
    "pipeline_config.py",
    "transcrever_arquivo.py",
    "diarizar_arquivo.py",
    "extrair_embeddings_voz.py",
    "regenerar_resumos.py",
    "instalar.py",
    "Instalar.bat",
    "Executar Pipeline.bat",
    "Portal.bat",
    "README.md",
    "config.exemplo.json",
    "requirements.txt",
    "pipeline_icone.ico",
    "Manual.md",
    "LEIA-ME_INSTALACAO.md",
]


def main():
    incluidos = []
    with zipfile.ZipFile(SAIDA, "w", zipfile.ZIP_DEFLATED) as z:
        for nome in ARQUIVOS:
            caminho = os.path.join(PASTA, nome)
            if os.path.exists(caminho):
                z.write(caminho, os.path.join("Transcritor", nome))
                incluidos.append(nome)
            else:
                print(f"  (ignorado, não existe: {nome})")

    # Pasta do portal (código + estáticos), sem caches nem testes
    pasta_portal = os.path.join(PASTA, "portal")

    with zipfile.ZipFile(SAIDA, "a", zipfile.ZIP_DEFLATED) as z:
        for raiz, pastas, arquivos in os.walk(pasta_portal):
            pastas[:] = [p for p in pastas if p != "__pycache__"]
            for a in arquivos:
                if a.startswith("teste_") or a.endswith(".pyc"):
                    continue
                caminho = os.path.join(raiz, a)
                z.write(caminho, os.path.join(
                    "Transcritor", os.path.relpath(caminho, PASTA)))
                incluidos.append(os.path.relpath(caminho, PASTA))

    print(f"Pacote gerado: {SAIDA}")
    print(f"{len(incluidos)} arquivos incluídos.")


if __name__ == "__main__":
    main()
