import argparse
import json

import numpy as np
import torch
import soundfile as sf

from speechbrain.inference.speaker import EncoderClassifier
from speechbrain.utils.fetching import LocalStrategy


def main():

    parser = argparse.ArgumentParser()

    parser.add_argument("--device", default="cpu")
    parser.add_argument("--entrada", required=True)
    parser.add_argument("--saida", required=True)
    parser.add_argument("--modelo-dir", required=True)

    args = parser.parse_args()

    with open(args.entrada, "r", encoding="utf-8") as f:
        itens = json.load(f)

    classificador = EncoderClassifier.from_hparams(
        source="speechbrain/spkrec-ecapa-voxceleb",
        savedir=args.modelo_dir,
        run_opts={"device": args.device},
        local_strategy=LocalStrategy.COPY
    )

    resultado = {}

    for item in itens:

        sinal, sr = sf.read(item["wav"], dtype="float32")

        if sinal.ndim > 1:
            sinal = sinal.mean(axis=1)

        tensor = torch.from_numpy(sinal).float().unsqueeze(0)

        with torch.no_grad():
            embedding = classificador.encode_batch(tensor)

        resultado[item["id"]] = embedding.squeeze().detach().cpu().numpy().tolist()

    with open(args.saida, "w", encoding="utf-8") as f:
        json.dump(resultado, f)


if __name__ == "__main__":
    main()
