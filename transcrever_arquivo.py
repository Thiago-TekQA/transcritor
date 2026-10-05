import argparse
import os

from faster_whisper import WhisperModel


def main():

    parser = argparse.ArgumentParser()

    parser.add_argument("--audio", required=True)
    parser.add_argument("--saida", required=True)
    parser.add_argument("--modelo", required=True)
    parser.add_argument("--device", required=True)

    args = parser.parse_args()

    # Usa o modelo já baixado (sem acessar a internet); só vai à rede se
    # ainda não houver cópia local (primeira execução). Evita falhas de
    # SSL/proxy e mantém o processamento 100% offline no dia a dia.
    try:

        modelo = WhisperModel(
            args.modelo,
            device=args.device,
            compute_type="int8",
            local_files_only=True
        )

    except Exception:

        modelo = WhisperModel(
            args.modelo,
            device=args.device,
            compute_type="int8"
        )

    segments, info = modelo.transcribe(
        args.audio,
        beam_size=5
    )

    # Escreve num arquivo .parcial e só renomeia no fim: se o processo for
    # morto no meio (cancelamento, crash), nunca sobra um .txt incompleto
    # que a próxima execução confundiria com "transcrição pronta".
    parcial = args.saida + ".parcial"

    ultimo_pct = -1

    with open(parcial, "w", encoding="utf-8") as f:

        for segment in segments:

            linha = (
                f"[{segment.start:.2f}s -> "
                f"{segment.end:.2f}s] "
                f"{segment.text}\n"
            )

            f.write(linha)

            # Progresso pro portal (linha especial, interceptada pelo
            # pipeline; não vai pro log)
            if info.duration:

                pct = min(99, int(segment.end * 100 / info.duration))

                if pct >= ultimo_pct + 2:

                    ultimo_pct = pct
                    print(f"@@PROG {pct}", flush=True)

    os.replace(parcial, args.saida)


if __name__ == "__main__":
    main()
