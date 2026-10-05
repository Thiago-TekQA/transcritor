"""Leva o modelo de transcrição (Whisper) de um computador para outro,
sem precisar de internet no destino.

  Origem:   python transferir_modelo.py exportar small    -> cria dist/modelo_small.zip
  Destino:  python transferir_modelo.py importar caminho\\para\\modelo_small.zip
"""

import os
import sys
import zipfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import pipeline_config as cfg  # noqa: E402


def exportar(modelo):

    pasta = os.path.join(
        cfg.pasta_cache_hf(), f"models--Systran--faster-whisper-{modelo}"
    )

    if not cfg.modelo_em_cache(modelo):
        sys.exit(f"O modelo '{modelo}' não está baixado neste computador "
                 f"({pasta}). Rode uma transcrição com internet antes.")

    # zips gerados ficam em dist/ (fora da raiz do projeto)
    os.makedirs(os.path.join(cfg.PASTA_RAIZ, "dist"), exist_ok=True)

    saida = os.path.join(cfg.PASTA_RAIZ, "dist", f"modelo_{modelo}.zip")
    base = os.path.dirname(pasta)

    with zipfile.ZipFile(saida, "w", zipfile.ZIP_STORED) as z:

        for raiz, _, arquivos in os.walk(pasta):

            for a in arquivos:

                caminho = os.path.join(raiz, a)
                z.write(caminho, os.path.relpath(caminho, base))

    print(f"Criado: {os.path.abspath(saida)} "
          f"({os.path.getsize(saida) / 1e6:.0f} MB)")
    print("Copie este arquivo para o outro computador e rode:")
    print(f"  python transferir_modelo.py importar {saida}")


def importar(arquivo):

    if not os.path.exists(arquivo):
        sys.exit(f"Arquivo não encontrado: {arquivo}")

    destino = cfg.pasta_cache_hf()
    os.makedirs(destino, exist_ok=True)

    with zipfile.ZipFile(arquivo) as z:

        nomes = z.namelist()

        # segurança: só aceita o formato do cache do Hugging Face, sem
        # caminhos que escapem da pasta de destino
        if not nomes or not all(
            n.replace("\\", "/").startswith("models--Systran--faster-whisper-")
            and ".." not in n.replace("\\", "/").split("/")
            for n in nomes
        ):
            sys.exit("Este zip não parece um modelo exportado por este script.")

        z.extractall(destino)

    print(f"Modelo instalado em: {destino}")
    print("Pronto — a transcrição agora funciona sem internet.")


def main():

    if len(sys.argv) != 3 or sys.argv[1] not in ("exportar", "importar"):
        sys.exit(__doc__)

    if sys.argv[1] == "exportar":
        exportar(sys.argv[2])
    else:
        importar(sys.argv[2])


if __name__ == "__main__":
    main()
