"""Gera Transcritor_pacote.zip para levar a outro computador.

Inclui só código, instalador e documentação (src/, ferramentas/, docs/,
assets/ e os arquivos da raiz). NUNCA inclui: config.json (token),
vídeos/áudios/transcrições/resumos (dados de reuniões), perfis de voz,
logs, .venv, modelos baixados, testes e caches.
"""

import os
import zipfile

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SAIDA = os.path.join(RAIZ, "Transcritor_pacote.zip")

ARQUIVOS_RAIZ = [
    "README.md",
    "Instalar.bat",
    "Portal.bat",
    "requirements.txt",
    "config.exemplo.json",
]

PASTAS = ["src", "ferramentas", "docs", "assets"]

IGNORAR_PASTAS = {"__pycache__"}
IGNORAR_SUFIXOS = (".pyc", ".log", ".zip")


def main():

    incluidos = []

    with zipfile.ZipFile(SAIDA, "w", zipfile.ZIP_DEFLATED) as z:

        for nome in ARQUIVOS_RAIZ:

            caminho = os.path.join(RAIZ, nome)

            if os.path.exists(caminho):
                z.write(caminho, os.path.join("Transcritor", nome))
                incluidos.append(nome)
            else:
                print(f"  (ignorado, não existe: {nome})")

        for pasta in PASTAS:

            for raiz, subpastas, arquivos in os.walk(os.path.join(RAIZ, pasta)):

                subpastas[:] = [p for p in subpastas if p not in IGNORAR_PASTAS]

                for a in arquivos:

                    if a.endswith(IGNORAR_SUFIXOS):
                        continue

                    caminho = os.path.join(raiz, a)
                    rel = os.path.relpath(caminho, RAIZ)

                    z.write(caminho, os.path.join("Transcritor", rel))
                    incluidos.append(rel)

    print(f"Pacote gerado: {SAIDA}")
    print(f"{len(incluidos)} arquivos incluídos.")


if __name__ == "__main__":
    main()
