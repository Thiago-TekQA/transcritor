import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import pipeline_comum as pc

import whisperx
from whisperx.diarize import DiarizationPipeline


def main():

    parser = argparse.ArgumentParser()

    parser.add_argument("--fonte-audio", required=True)
    parser.add_argument("--saida", required=True)
    parser.add_argument("--device", required=True)
    parser.add_argument("--min-falantes", type=int, default=pc.MIN_FALANTES)
    parser.add_argument("--max-falantes", type=int, default=pc.MAX_FALANTES)

    args = parser.parse_args()

    def log(mensagem):
        print(mensagem, flush=True)

    log("CARREGANDO MODELO WHISPERX")

    wx_model = whisperx.load_model(
        "small",
        args.device,
        compute_type="int8"
    )

    log("CARREGANDO MODELO DE DIARIZAÇÃO")

    diarize_model = DiarizationPipeline(
        token=pc.HF_TOKEN,
        device=args.device
    )

    perfis_voz = pc.carregar_perfis_voz()

    audio = whisperx.load_audio(args.fonte_audio)

    result = wx_model.transcribe(audio)

    model_a, metadata = whisperx.load_align_model(
        language_code=result["language"],
        device=args.device
    )

    result = whisperx.align(
        result["segments"],
        model_a,
        metadata,
        audio,
        args.device
    )

    diarize_segments = diarize_model(
        audio,
        min_speakers=args.min_falantes,
        max_speakers=args.max_falantes
    )

    mapa_nomes = {}

    if (
        perfis_voz
        and diarize_segments is not None
        and len(diarize_segments) > 0
    ):

        trechos_falantes = []

        for speaker in diarize_segments["speaker"].unique():

            maior_trecho = pc.maior_segmento_do_falante(
                diarize_segments,
                speaker
            )

            waveform = pc.fatiar_audio(
                audio,
                maior_trecho["start"],
                maior_trecho["end"]
            )

            if waveform is not None:
                trechos_falantes.append((speaker, waveform))

        embeddings_falantes = pc.extrair_embeddings_via_subprocesso(
            trechos_falantes,
            args.device,
            log
        )

        for speaker, embedding in embeddings_falantes.items():

            nome_identificado, similaridade = pc.identificar_falante(
                embedding,
                perfis_voz
            )

            if nome_identificado:

                mapa_nomes[speaker] = nome_identificado

                log(
                    f"  {speaker} IDENTIFICADO COMO "
                    f"'{nome_identificado}' "
                    f"(similaridade {similaridade:.2f})"
                )

            else:

                log(
                    f"  {speaker} NÃO IDENTIFICADO "
                    f"(melhor similaridade {similaridade:.2f})"
                )

    result = whisperx.assign_word_speakers(
        diarize_segments,
        result
    )

    # .parcial + renomeação no fim: nunca sobra saída incompleta se o
    # processo for morto no meio.
    parcial = args.saida + ".parcial"

    with open(parcial, "w", encoding="utf-8") as f:

        for segment in result["segments"]:

            speaker = segment.get("speaker", "UNKNOWN")
            speaker = mapa_nomes.get(speaker, speaker)

            text = segment["text"]
            start = segment["start"]
            end = segment["end"]

            linha = (
                f"[{start:.2f}s -> "
                f"{end:.2f}s] "
                f"{speaker}: {text}\n"
            )

            f.write(linha)

    os.replace(parcial, args.saida)


if __name__ == "__main__":
    main()
