from pathlib import Path

import os
import sys
import shutil
import subprocess
import time
import argparse
import traceback
import gc
import json

from datetime import datetime

import numpy as np
import torch
import requests

import whisperx
from whisperx.diarize import DiarizationPipeline

import pipeline_comum as pc

# =========================================================
# ARGUMENTOS
# =========================================================

parser = argparse.ArgumentParser()

parser.add_argument(
    "--modo",
    choices=[
        "completo",
        "simples",
        "somente_mp3",
        "somente_transcricao",
        "diarizacao",
        "perfis_voz",
        "resumo"
    ],
    default="simples"
)

parser.add_argument(
    "--modelo",
    default=pc.CONFIG["modelo_whisper"]
)

parser.add_argument(
    "--device",
    default=pc.CONFIG["device"]
)

# Etapas a executar (combináveis). Quando informado, vale no lugar do que
# o --modo implicaria; sem ele, o --modo continua definindo as etapas
# (compatível com o Executar Pipeline.bat).
parser.add_argument(
    "--etapas",
    default=None,
    help="lista separada por vírgula: " + ",".join(pc.ETAPAS_VALIDAS)
)

# Arquivo JSON com a lista de itens (nomes sem extensão) a processar.
# Sem ele, processa tudo que encontrar nas pastas (comportamento legado).
parser.add_argument(
    "--itens",
    default=None
)

args = parser.parse_args()

if args.etapas:

    _etapas = [e.strip() for e in args.etapas.split(",") if e.strip()]

    _invalidas = [e for e in _etapas if e not in pc.ETAPAS_VALIDAS]

    if _invalidas:
        parser.error(f"etapas inválidas: {', '.join(_invalidas)}")

else:

    _etapas = list(pc.ETAPAS_POR_MODO[args.modo])

ETAPAS = set(_etapas)

if args.itens:

    with open(args.itens, "r", encoding="utf-8") as _f:
        pc.definir_itens(json.load(_f))

# Só uma execução por vez (a GPU é uma só) — vale também contra o .bat.
if not pc.adquirir_trava():

    print(
        "ERRO: já existe outra execução do pipeline em andamento "
        "(feche-a ou aguarde terminar)."
    )

    sys.exit(3)

# =========================================================
# CONFIGURAÇÕES
# =========================================================
# Constantes e pastas compartilhadas vivem em pipeline_comum.py, porque
# os workers isolados (transcrever_arquivo.py, diarizar_arquivo.py) também
# precisam delas. Aqui só criamos atalhos locais pra não reescrever
# "pc." em todo lugar.

VIDEOS_DIR = pc.VIDEOS_DIR
AUDIOS_DIR = pc.AUDIOS_DIR
TRANS_DIR = pc.TRANS_DIR
DIARIZ_DIR = pc.DIARIZ_DIR
LOGS_DIR = pc.LOGS_DIR
DONE_DIR = pc.DONE_DIR
PERFIS_VOZ_DIR = pc.PERFIS_VOZ_DIR
RESUMOS_DIR = pc.RESUMOS_DIR

VIDEOS_SUPORTADOS = pc.VIDEOS_SUPORTADOS
AMOSTRAS_SUPORTADAS = pc.AMOSTRAS_SUPORTADAS

MIN_FALANTES = pc.MIN_FALANTES
MAX_FALANTES = pc.MAX_FALANTES

for pasta in [
    VIDEOS_DIR,
    AUDIOS_DIR,
    TRANS_DIR,
    DIARIZ_DIR,
    LOGS_DIR,
    DONE_DIR,
    PERFIS_VOZ_DIR,
    RESUMOS_DIR
]:
    os.makedirs(pasta, exist_ok=True)

LOG_FILE = os.path.join(
    LOGS_DIR,
    f"pipeline_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"
)

# =========================================================
# LOG
# =========================================================


def log(mensagem):

    timestamp = datetime.now().strftime(
        "%Y-%m-%d %H:%M:%S"
    )

    linha = f"[{timestamp}] {mensagem}"

    print(linha, flush=True)

    with open(
        LOG_FILE,
        "a",
        encoding="utf-8"
    ) as f:

        f.write(linha + "\n")



def _capturar_erro_nao_tratado(tipo, valor, tb):
    """Garante que QUALQUER erro não tratado (em qualquer fase) vá pro
    log, não só pro console — a janela do .bat fecha e perde o traceback
    senão."""

    log("ERRO NÃO TRATADO — PIPELINE INTERROMPIDO:")
    log("".join(traceback.format_exception(tipo, valor, tb)))

    try:
        pc.limpar_interrompidos(_registrar_limpeza)
    except Exception:
        pass

    pc.evento("erro_fatal", msg=str(valor))
    pc.evento("run_fim", resultado="erro", falhas=[])

    sys.__excepthook__(tipo, valor, tb)


sys.excepthook = _capturar_erro_nao_tratado

# =========================================================
# AUXILIARES
# =========================================================


def executar_subprocesso_com_log(cmd, prefixo=""):
    """Roda um worker isolado (transcrever_arquivo.py / diarizar_arquivo.py)
    e transmite a saída dele pro nosso log em tempo real, linha por linha.
    Isola crashes nativos (CUDA, etc.) — se o worker morrer, só ele morre,
    o orquestrador principal segue pro próximo arquivo."""

    processo = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1
    )

    saida_completa = []

    try:

        for linha in processo.stdout:

            linha = linha.rstrip()

            # Progresso emitido pelo worker (vira evento pro portal, não log)
            if linha.startswith("@@PROG "):

                try:
                    pc.evento_progresso(int(linha.split()[1]))
                except (ValueError, IndexError):
                    pass

                continue

            if linha:

                log(f"{prefixo}{linha}")
                saida_completa.append(linha)

        processo.wait()

    except BaseException:

        # Ctrl+C / erro no orquestrador: não deixa o worker órfão
        # escrevendo em arquivo parcial.
        processo.kill()

        raise

    return processo.returncode, "\n".join(saida_completa)



def liberar_gpu():

    gc.collect()

    if args.device == "cuda":

        try:

            torch.cuda.empty_cache()

            log(
                f"MEMÓRIA DA GPU LIBERADA "
                f"({round(torch.cuda.memory_allocated() / 1e9, 2)}GB em uso)"
            )

        except Exception as e:

            # Um erro de CUDA aqui não pode derrubar o pipeline inteiro —
            # a próxima fase ainda tenta rodar normalmente.
            log(f"AVISO: FALHA AO LIBERAR MEMÓRIA DA GPU: {e}")

# =========================================================
# INÍCIO
# =========================================================

inicio_pipeline = time.time()

# Cada entrada: {"arquivo": nome, "etapa": ..., "resultado": ...}. Vira o
# relatório final de falhas/retentativas, mostrado na FINALIZAÇÃO.
relatorio_falhas = []


_parada_avisada = False


def interrompido():
    """True se o portal pediu pra parar (a execução termina o arquivo
    atual e não começa o próximo)."""

    global _parada_avisada

    if pc.parada_solicitada():

        if not _parada_avisada:

            _parada_avisada = True

            log(
                "PARADA SOLICITADA PELO PORTAL — encerrando depois do "
                "arquivo atual"
            )

            pc.evento("cancelado", modo="suave")

        return True

    return False


def remover_parcial(caminho):
    """Apaga o .parcial de uma saída que não chegou a ser concluída."""

    parcial = caminho + ".parcial"

    if os.path.exists(parcial):

        try:
            os.remove(parcial)
        except OSError:
            pass


def registrar_falha(arquivo, etapa, resultado):

    relatorio_falhas.append({
        "arquivo": arquivo,
        "etapa": etapa,
        "resultado": resultado
    })


log("=" * 60)
log("INICIANDO PIPELINE")
log(f"MODO: {args.modo}")
log(f"MODELO: {args.modelo}")
log(f"DEVICE: {args.device}")
log(f"FALANTES (min/max): {MIN_FALANTES} / {MAX_FALANTES}")
log(f"ETAPAS: {', '.join(e for e in pc.ETAPAS_VALIDAS if e in ETAPAS) or '-'}")
log("=" * 60)

# Sobras de execuções interrompidas (arquivos .parcial, cópias .copiando e
# consolidações pela metade): nunca são saídas válidas. Só a saída da etapa
# que foi interrompida é descartada — vídeo, áudio e etapas já concluídas
# ficam. (Seguro: a trava garante que não há outra execução rodando.)


def _registrar_limpeza(r):

    log(
        f"LIMPEZA DE EXECUÇÃO INTERROMPIDA: {r['arquivo']} "
        f"({r['etapa']}) removido"
    )

    pc.evento("limpeza", **r)


pc.limpar_interrompidos(_registrar_limpeza)

pc.evento(
    "run_inicio",
    etapas=[e for e in pc.ETAPAS_VALIDAS if e in ETAPAS],
    device=args.device,
    modelo=args.modelo,
    pid=os.getpid(),
    log=LOG_FILE
)

# =========================================================
# CADASTRO DE PERFIS DE VOZ
# =========================================================

if args.modo == "perfis_voz":

    log("=" * 60)
    log("CADASTRANDO PERFIS DE VOZ")
    log("=" * 60)

    log("CARREGANDO MODELO DE DIARIZAÇÃO")

    diarize_model = DiarizationPipeline(
        token=pc.HF_TOKEN,
        device=args.device
    )

    perfis = pc.carregar_perfis_voz()

    trechos_por_pessoa = {}
    trechos_para_extrair = []

    for nome_pessoa in os.listdir(PERFIS_VOZ_DIR):

        pasta_pessoa = os.path.join(PERFIS_VOZ_DIR, nome_pessoa)

        if not os.path.isdir(pasta_pessoa):
            continue

        indice_amostra = 0

        for arquivo in os.listdir(pasta_pessoa):

            _, extensao = os.path.splitext(arquivo)

            if extensao.lower() not in AMOSTRAS_SUPORTADAS:
                continue

            amostra_path = os.path.join(pasta_pessoa, arquivo)

            log(f"PROCESSANDO AMOSTRA: {nome_pessoa} / {arquivo}")

            try:

                audio = whisperx.load_audio(amostra_path)

                diarize_df = diarize_model(audio)

                if diarize_df is None or len(diarize_df) == 0:

                    log(f"[SKIP] Nenhuma fala detectada em {arquivo}")
                    continue

                diarize_df["duracao"] = (
                    diarize_df["end"] - diarize_df["start"]
                )

                falante_dominante = (
                    diarize_df.groupby("speaker")["duracao"]
                    .sum()
                    .idxmax()
                )

                maior_trecho = pc.maior_segmento_do_falante(
                    diarize_df,
                    falante_dominante
                )

                waveform = pc.fatiar_audio(
                    audio,
                    maior_trecho["start"],
                    maior_trecho["end"]
                )

                if waveform is None:

                    log(f"[SKIP] Trecho de fala curto demais em {arquivo}")
                    continue

                indice_amostra += 1

                identificador = f"{nome_pessoa}__{indice_amostra}"

                trechos_por_pessoa.setdefault(
                    nome_pessoa, []
                ).append(identificador)

                trechos_para_extrair.append((identificador, waveform))

                log(
                    f"  FALANTE DOMINANTE: {falante_dominante} "
                    f"(trecho de "
                    f"{maior_trecho['duracao']:.1f}s usado)"
                )

            except Exception as e:

                log(f"ERRO AO PROCESSAR AMOSTRA {arquivo}: {e}")

    del diarize_model

    liberar_gpu()

    log("EXTRAINDO EMBEDDINGS DE VOZ (SpeechBrain ECAPA-TDNN, subprocesso)")

    embeddings = pc.extrair_embeddings_via_subprocesso(
        trechos_para_extrair,
        args.device,
        log
    )

    for nome_pessoa, identificadores in trechos_por_pessoa.items():

        embeddings_pessoa = [
            embeddings[ident]
            for ident in identificadores
            if ident in embeddings
        ]

        if not embeddings_pessoa:

            log(f"[SKIP] Nenhum embedding válido para {nome_pessoa}")
            continue

        embedding_medio = np.mean(
            embeddings_pessoa,
            axis=0
        ).tolist()

        perfis[nome_pessoa] = {
            "embedding": embedding_medio,
            "amostras": len(embeddings_pessoa),
            "atualizado_em": datetime.now().strftime(
                "%Y-%m-%d %H:%M:%S"
            )
        }

        log(
            f"PERFIL ATUALIZADO: {nome_pessoa} "
            f"({len(embeddings_pessoa)} amostra(s))"
        )

    pc.salvar_perfis_voz(perfis)

    log(f"PERFIS SALVOS EM: {pc.PERFIS_VOZ_ARQUIVO}")

# =========================================================
# FASE 1 - GERAR TODOS OS MP3
# =========================================================

if "mp3" in ETAPAS and not interrompido():

    log("=" * 60)
    log("FASE 1 - GERANDO MP3")
    log("=" * 60)

    pc.evento("fase_inicio", etapa="mp3")

    for arquivo in os.listdir(VIDEOS_DIR):

        if interrompido():
            break

        nome_original, extensao = os.path.splitext(arquivo)

        if extensao.lower() not in VIDEOS_SUPORTADOS:
            continue

        nome = pc.sanitizar_nome(nome_original)

        if not pc.item_selecionado(nome):
            continue

        video_path = os.path.join(
            VIDEOS_DIR,
            arquivo
        )

        audio_path = os.path.join(
            AUDIOS_DIR,
            f"{nome}.mp3"
        )

        if os.path.exists(audio_path):

            log(f"[SKIP MP3] {audio_path}")

            pc.evento(
                "item", etapa="mp3", nome=nome,
                estado="pulado", motivo="ja_existe"
            )

            continue

        log(f"GERANDO MP3: {arquivo}")

        pc.evento("item", etapa="mp3", nome=nome, estado="rodando")

        inicio_item = time.time()

        try:

            # Grava em .parcial e só renomeia no fim — nunca sobra um mp3
            # incompleto que a próxima execução trataria como pronto.
            cmd = [
                "ffmpeg",
                "-y",
                "-i", video_path,
                "-vn",
                "-c:a", "libmp3lame",
                "-f", "mp3",
                audio_path + ".parcial"
            ]

            subprocess.run(cmd, check=True)

            os.replace(audio_path + ".parcial", audio_path)

            log(f"MP3 GERADO: {audio_path}")

            pc.evento(
                "item", etapa="mp3", nome=nome, estado="ok",
                dur=round(time.time() - inicio_item, 1)
            )

        except Exception as e:

            log(f"ERRO AO GERAR MP3: {arquivo} | {e}")

            remover_parcial(audio_path)

            registrar_falha(arquivo, "mp3", f"falhou: {e}")

            pc.evento(
                "item", etapa="mp3", nome=nome, estado="falhou",
                motivo=str(e)
            )

    pc.evento("fase_fim", etapa="mp3")

# =========================================================
# FASE 2 - TRANSCRIÇÕES
# =========================================================

if "transcricao" in ETAPAS and not interrompido():

    log("=" * 60)
    log("FASE 2 - TRANSCRIÇÕES")
    log("=" * 60)

    pc.evento("fase_inicio", etapa="transcricao")

    falhas_gpu_transcricao = []

    for arquivo in os.listdir(AUDIOS_DIR):

        if interrompido():
            break

        nome, extensao = os.path.splitext(arquivo)

        if extensao.lower() not in AMOSTRAS_SUPORTADAS:
            continue

        if not pc.item_selecionado(nome):
            continue

        audio_path = os.path.join(
            AUDIOS_DIR,
            arquivo
        )

        txt_path = os.path.join(
            TRANS_DIR,
            f"{nome}.txt"
        )

        if os.path.exists(txt_path):

            log(f"[SKIP TRANSCRIÇÃO] {txt_path}")

            pc.evento(
                "item", etapa="transcricao", nome=nome,
                estado="pulado", motivo="ja_existe"
            )

            continue

        if args.device == "cuda":
            pc.aguardar_gpu_esfriar(log)

        log(f"TRANSCREVENDO: {arquivo}")

        pc.evento(
            "item", etapa="transcricao", nome=nome, estado="rodando",
            dispositivo=args.device, tentativa=1
        )

        inicio = time.time()

        cmd = [
            sys.executable,
            pc.SCRIPT_TRANSCRICAO,
            "--audio", audio_path,
            "--saida", txt_path,
            "--modelo", args.modelo,
            "--device", args.device
        ]

        codigo, _ = executar_subprocesso_com_log(
            cmd,
            prefixo="  [transcricao] "
        )

        fim = time.time()

        if codigo != 0:

            if os.path.exists(txt_path):
                os.remove(txt_path)

            remover_parcial(txt_path)

            if args.device == "cuda":

                log(
                    f"ERRO NA TRANSCRIÇÃO: {arquivo} | "
                    f"processo isolado saiu com código {codigo} "
                    f"(provável falha nativa/CUDA) — "
                    f"guardado pra tentar de novo na CPU no final"
                )

                falhas_gpu_transcricao.append(
                    (arquivo, audio_path, txt_path)
                )

                pc.evento(
                    "item", etapa="transcricao", nome=nome,
                    estado="aguardando_cpu",
                    motivo=f"código {codigo}"
                )

            else:

                log(
                    f"ERRO NA TRANSCRIÇÃO: {arquivo} | "
                    f"processo isolado saiu com código {codigo} "
                    f"(pulando pro próximo arquivo)"
                )

                registrar_falha(
                    arquivo,
                    "transcrição",
                    f"falhou na CPU (código {codigo})"
                )

                pc.evento(
                    "item", etapa="transcricao", nome=nome,
                    estado="falhou", motivo=f"código {codigo}"
                )

            continue

        log(
            f"TRANSCRIÇÃO FINALIZADA: "
            f"{txt_path} "
            f"({fim - inicio:.2f}s)"
        )

        pc.evento(
            "item", etapa="transcricao", nome=nome, estado="ok",
            dur=round(fim - inicio, 1)
        )

    if falhas_gpu_transcricao and not pc.parada_solicitada():

        log(
            f"REPROCESSANDO {len(falhas_gpu_transcricao)} ARQUIVO(S) "
            f"QUE FALHARAM NA GPU, AGORA NA CPU"
        )

        for arquivo, audio_path, txt_path in falhas_gpu_transcricao:

            if interrompido():
                break

            nome = os.path.splitext(arquivo)[0]

            log(f"TRANSCREVENDO (CPU, nova tentativa): {arquivo}")

            pc.evento(
                "item", etapa="transcricao", nome=nome, estado="rodando",
                dispositivo="cpu", tentativa=2
            )

            inicio = time.time()

            cmd_cpu = [
                sys.executable,
                pc.SCRIPT_TRANSCRICAO,
                "--audio", audio_path,
                "--saida", txt_path,
                "--modelo", args.modelo,
                "--device", "cpu"
            ]

            codigo, _ = executar_subprocesso_com_log(
                cmd_cpu,
                prefixo="  [transcricao-cpu] "
            )

            fim = time.time()

            if codigo != 0:

                log(
                    f"ERRO NA TRANSCRIÇÃO (CPU): {arquivo} | "
                    f"processo saiu com código {codigo} — "
                    f"esse arquivo continua pendente pra próxima execução"
                )

                registrar_falha(
                    arquivo,
                    "transcrição",
                    f"falhou na GPU e na CPU (código {codigo}) — "
                    f"pendente pra próxima execução"
                )

                if os.path.exists(txt_path):
                    os.remove(txt_path)

                remover_parcial(txt_path)

                pc.evento(
                    "item", etapa="transcricao", nome=nome,
                    estado="falhou",
                    motivo=f"falhou na GPU e na CPU (código {codigo})"
                )

                continue

            log(
                f"TRANSCRIÇÃO FINALIZADA (CPU): "
                f"{txt_path} "
                f"({fim - inicio:.2f}s)"
            )

            registrar_falha(
                arquivo,
                "transcrição",
                "falhou na GPU, recuperado na CPU"
            )

            pc.evento(
                "item", etapa="transcricao", nome=nome, estado="ok",
                dur=round(fim - inicio, 1), nota="recuperado_cpu"
            )

    pc.evento("fase_fim", etapa="transcricao")

    liberar_gpu()

# =========================================================
# FASE 3 - DIARIZAÇÕES
# =========================================================

if "diarizacao" in ETAPAS and not interrompido():

    log("=" * 60)
    log("FASE 3 - DIARIZAÇÕES")
    log("=" * 60)

    pc.evento("fase_inicio", etapa="diarizacao")

    falhas_gpu_diarizacao = []

    for arquivo in os.listdir(AUDIOS_DIR):

        if interrompido():
            break

        nome, extensao = os.path.splitext(arquivo)

        if extensao.lower() not in AMOSTRAS_SUPORTADAS:
            continue

        if not pc.item_selecionado(nome):
            continue

        audio_path = os.path.join(
            AUDIOS_DIR,
            arquivo
        )

        diarizado_path = os.path.join(
            DIARIZ_DIR,
            f"{nome}_diarizado.txt"
        )

        if os.path.exists(diarizado_path):

            log(f"[SKIP DIARIZAÇÃO] {diarizado_path}")

            pc.evento(
                "item", etapa="diarizacao", nome=nome,
                estado="pulado", motivo="ja_existe"
            )

            continue

        video_original = pc.encontrar_video_original(nome)

        if video_original:

            log(
                f"USANDO ÁUDIO DO VÍDEO ORIGINAL "
                f"(evita recompressão do MP3): {video_original}"
            )

            fonte_audio = video_original

        else:

            log(
                f"VÍDEO ORIGINAL NÃO ENCONTRADO, "
                f"USANDO MP3: {audio_path}"
            )

            fonte_audio = audio_path

        if args.device == "cuda":
            pc.aguardar_gpu_esfriar(log)

        log(f"DIARIZANDO: {arquivo}")

        pc.evento(
            "item", etapa="diarizacao", nome=nome, estado="rodando",
            dispositivo=args.device, tentativa=1
        )

        inicio = time.time()

        cmd = [
            sys.executable,
            pc.SCRIPT_DIARIZACAO,
            "--fonte-audio", fonte_audio,
            "--saida", diarizado_path,
            "--device", args.device,
            "--min-falantes", str(MIN_FALANTES),
            "--max-falantes", str(MAX_FALANTES)
        ]

        codigo, _ = executar_subprocesso_com_log(
            cmd,
            prefixo="  [diarizacao] "
        )

        fim = time.time()

        if codigo != 0:

            if os.path.exists(diarizado_path):
                os.remove(diarizado_path)

            remover_parcial(diarizado_path)

            if args.device == "cuda":

                log(
                    f"ERRO NA DIARIZAÇÃO: {arquivo} | "
                    f"processo isolado saiu com código {codigo} "
                    f"(provável falha nativa/CUDA) — "
                    f"guardado pra tentar de novo na CPU no final"
                )

                falhas_gpu_diarizacao.append(
                    (arquivo, fonte_audio, diarizado_path)
                )

                pc.evento(
                    "item", etapa="diarizacao", nome=nome,
                    estado="aguardando_cpu",
                    motivo=f"código {codigo}"
                )

            else:

                log(
                    f"ERRO NA DIARIZAÇÃO: {arquivo} | "
                    f"processo isolado saiu com código {codigo} "
                    f"(pulando pro próximo arquivo)"
                )

                registrar_falha(
                    arquivo,
                    "diarização",
                    f"falhou na CPU (código {codigo})"
                )

                pc.evento(
                    "item", etapa="diarizacao", nome=nome,
                    estado="falhou", motivo=f"código {codigo}"
                )

            continue

        log(
            f"DIARIZAÇÃO FINALIZADA: "
            f"{diarizado_path} "
            f"({fim - inicio:.2f}s)"
        )

        pc.evento(
            "item", etapa="diarizacao", nome=nome, estado="ok",
            dur=round(fim - inicio, 1)
        )

    if falhas_gpu_diarizacao and not pc.parada_solicitada():

        log(
            f"REPROCESSANDO {len(falhas_gpu_diarizacao)} ARQUIVO(S) "
            f"QUE FALHARAM NA GPU, AGORA NA CPU "
            f"(bem mais lento, mas só afeta quem falhou)"
        )

        for arquivo, fonte_audio, diarizado_path in falhas_gpu_diarizacao:

            if interrompido():
                break

            nome = os.path.splitext(arquivo)[0]

            log(f"DIARIZANDO (CPU, nova tentativa): {arquivo}")

            pc.evento(
                "item", etapa="diarizacao", nome=nome, estado="rodando",
                dispositivo="cpu", tentativa=2
            )

            inicio = time.time()

            cmd_cpu = [
                sys.executable,
                pc.SCRIPT_DIARIZACAO,
                "--fonte-audio", fonte_audio,
                "--saida", diarizado_path,
                "--device", "cpu",
                "--min-falantes", str(MIN_FALANTES),
                "--max-falantes", str(MAX_FALANTES)
            ]

            codigo, _ = executar_subprocesso_com_log(
                cmd_cpu,
                prefixo="  [diarizacao-cpu] "
            )

            fim = time.time()

            if codigo != 0:

                log(
                    f"ERRO NA DIARIZAÇÃO (CPU): {arquivo} | "
                    f"processo saiu com código {codigo} — "
                    f"esse arquivo continua pendente pra próxima execução"
                )

                registrar_falha(
                    arquivo,
                    "diarização",
                    f"falhou na GPU e na CPU (código {codigo}) — "
                    f"pendente pra próxima execução"
                )

                if os.path.exists(diarizado_path):
                    os.remove(diarizado_path)

                remover_parcial(diarizado_path)

                pc.evento(
                    "item", etapa="diarizacao", nome=nome,
                    estado="falhou",
                    motivo=f"falhou na GPU e na CPU (código {codigo})"
                )

                continue

            log(
                f"DIARIZAÇÃO FINALIZADA (CPU): "
                f"{diarizado_path} "
                f"({fim - inicio:.2f}s)"
            )

            registrar_falha(
                arquivo,
                "diarização",
                "falhou na GPU, recuperado na CPU"
            )

            pc.evento(
                "item", etapa="diarizacao", nome=nome, estado="ok",
                dur=round(fim - inicio, 1), nota="recuperado_cpu"
            )

    pc.evento("fase_fim", etapa="diarizacao")

    liberar_gpu()

# =========================================================
# FASE 3.5 - RESUMOS / ATA (via LLM local, Ollama)
# =========================================================

if "resumo" in ETAPAS and not interrompido():

    log("=" * 60)
    log("FASE 3.5 - RESUMOS")
    log("=" * 60)

    pc.evento("fase_inicio", etapa="resumo")

    processo_ollama = pc.garantir_ollama_rodando(log)

    for arquivo in os.listdir(TRANS_DIR):

        if interrompido():
            break

        nome, extensao = os.path.splitext(arquivo)

        if extensao.lower() != ".txt":
            continue

        if not pc.item_selecionado(nome):
            continue

        resumo_path = os.path.join(
            RESUMOS_DIR,
            f"{nome}_resumo.txt"
        )

        if os.path.exists(resumo_path):

            log(f"[SKIP RESUMO] {resumo_path}")

            pc.evento(
                "item", etapa="resumo", nome=nome,
                estado="pulado", motivo="ja_existe"
            )

            continue

        diarizado_path = os.path.join(
            DIARIZ_DIR,
            f"{nome}_diarizado.txt"
        )

        if os.path.exists(diarizado_path):

            fonte_texto = diarizado_path

        else:

            fonte_texto = os.path.join(TRANS_DIR, arquivo)

        log(
            f"GERANDO RESUMO: {nome} "
            f"(fonte: {os.path.basename(fonte_texto)})"
        )

        pc.evento("item", etapa="resumo", nome=nome, estado="rodando")

        inicio = time.time()

        try:

            with open(fonte_texto, "r", encoding="utf-8") as f:
                transcricao = f.read()

            resumo = pc.gerar_resumo_ollama(transcricao, log)

            # .parcial + renomeação: nunca sobra um resumo pela metade que
            # a próxima execução trataria como pronto.
            with open(resumo_path + ".parcial", "w", encoding="utf-8") as f:
                f.write(resumo)

            os.replace(resumo_path + ".parcial", resumo_path)

            fim = time.time()

            log(
                f"RESUMO FINALIZADO: {resumo_path} "
                f"({fim - inicio:.2f}s)"
            )

            pc.evento(
                "item", etapa="resumo", nome=nome, estado="ok",
                dur=round(fim - inicio, 1)
            )

        except requests.exceptions.ConnectionError:

            remover_parcial(resumo_path)

            log(
                "ERRO NO RESUMO: não foi possível conectar ao Ollama "
                "em http://localhost:11434 — o serviço está rodando?"
            )

            registrar_falha(
                nome,
                "resumo",
                "falhou: não conseguiu conectar ao Ollama"
            )

            pc.evento(
                "item", etapa="resumo", nome=nome, estado="falhou",
                motivo="não conseguiu conectar ao Ollama"
            )

        except Exception as e:

            remover_parcial(resumo_path)

            log(f"ERRO NO RESUMO: {nome} | {e}")

            registrar_falha(nome, "resumo", f"falhou: {e}")

            pc.evento(
                "item", etapa="resumo", nome=nome, estado="falhou",
                motivo=str(e)
            )

    pc.parar_ollama_se_iniciado_por_nos(processo_ollama, log)

    pc.evento("fase_fim", etapa="resumo")

# =========================================================
# FASE 4 - CONSOLIDAR ENTREGÁVEIS
# =========================================================

nomes_para_consolidar = {}

# Itens cuja consolidação falhou e foi desfeita (não podem ser limpos)
consolidacao_falhou = set()

if "consolidar" in ETAPAS and not interrompido():

    log("=" * 60)
    log("FASE 4 - CONSOLIDANDO ENTREGÁVEIS")
    log("=" * 60)

    pc.evento("fase_inicio", etapa="consolidar")

    def item_pronto(nome):
        # Um item só está de verdade "concluído" se a transcrição E o
        # resumo existirem. Se qualquer um dos dois falhou (crash
        # isolado, Ollama fora do ar, etc.), o item fica de fora da
        # consolidação de propósito — continua em 1_Videos/2_Audios pra
        # ser tentado de novo automaticamente na próxima execução, em
        # vez de ir pra 6_Concluidos incompleto e nunca mais ser
        # revisitado (a fase de resumo só varre a pasta temporária
        # 3_Transcricoes — uma vez consolidado, nunca mais seria visto).
        # A diarização fica de fora dessa checagem de propósito: é
        # opcional (só roda quando a etapa "diarizacao" é selecionada).
        transcricao_existe = os.path.exists(
            os.path.join(TRANS_DIR, f"{nome}.txt")
        )

        resumo_existe = os.path.exists(
            os.path.join(RESUMOS_DIR, f"{nome}_resumo.txt")
        )

        return transcricao_existe and resumo_existe

    for arquivo in os.listdir(VIDEOS_DIR):

        nome_original, extensao = os.path.splitext(arquivo)

        if extensao.lower() not in VIDEOS_SUPORTADOS:
            continue

        nome = pc.sanitizar_nome(nome_original)

        if not pc.item_selecionado(nome):
            continue

        if not item_pronto(nome):

            log(
                f"[SKIP CONSOLIDAÇÃO] {nome} — sem transcrição e/ou "
                f"resumo ainda (provável falha isolada numa fase "
                f"anterior); mantido em 1_Videos pra nova tentativa"
            )

            pc.evento(
                "item", etapa="consolidar", nome=nome, estado="pulado",
                motivo="sem_transcricao_ou_resumo"
            )

            continue

        nomes_para_consolidar[nome] = os.path.join(VIDEOS_DIR, arquivo)

    # Áudio solto direto em 2_Audios (sem vídeo de origem em 1_Videos)
    # não passa pela FASE 1, então precisa ser considerado aqui também —
    # senão a FASE 5 apaga o áudio e a transcrição sem nunca movê-los
    # para 6_Concluidos. (Inclui .mp3 solto: se houvesse vídeo de origem
    # pronto, o nome já estaria em nomes_para_consolidar acima.)
    for arquivo in os.listdir(AUDIOS_DIR):

        nome_original, extensao = os.path.splitext(arquivo)

        if extensao.lower() not in AMOSTRAS_SUPORTADAS:
            continue

        nome = pc.sanitizar_nome(nome_original)

        if not pc.item_selecionado(nome):
            continue

        if nome in nomes_para_consolidar:
            continue

        if not item_pronto(nome):

            log(
                f"[SKIP CONSOLIDAÇÃO] {nome} — sem transcrição e/ou "
                f"resumo ainda (provável falha isolada numa fase "
                f"anterior); mantido em 2_Audios pra nova tentativa"
            )

            pc.evento(
                "item", etapa="consolidar", nome=nome, estado="pulado",
                motivo="sem_transcricao_ou_resumo"
            )

            continue

        nomes_para_consolidar[nome] = os.path.join(AUDIOS_DIR, arquivo)

    for nome, arquivo_origem in nomes_para_consolidar.items():

        pc.evento("item", etapa="consolidar", nome=nome, estado="rodando")

        erro_mover = None

        pasta_final = os.path.join(
            DONE_DIR,
            nome
        )

        # Monta tudo em 6_Concluidos/<nome>.parcial e só renomeia a pasta no
        # fim: assim um item "meio consolidado" nunca parece concluído. Se
        # a pasta final já existe (execução antiga), usa-a direto.
        pasta_montagem = pasta_final + ".parcial"

        usar_montagem = not os.path.isdir(pasta_final)

        destino_dir = pasta_montagem if usar_montagem else pasta_final

        os.makedirs(
            destino_dir,
            exist_ok=True
        )

        arquivos_para_mover = list(dict.fromkeys([

            arquivo_origem,

            os.path.join(
                AUDIOS_DIR,
                f"{nome}.mp3"
            ),

            os.path.join(
                TRANS_DIR,
                f"{nome}.txt"
            ),

            os.path.join(
                DIARIZ_DIR,
                f"{nome}_diarizado.txt"
            )
        ]))

        arquivos_para_mover = [
            i for i in arquivos_para_mover if os.path.exists(i)
        ]

        if usar_montagem:

            # De onde cada arquivo veio, para poder desfazer se for
            # interrompido no meio.
            with open(
                os.path.join(pasta_montagem, pc.MANIFESTO_CONSOLIDACAO),
                "w",
                encoding="utf-8"
            ) as f:

                json.dump(
                    {
                        os.path.basename(i): os.path.dirname(i)
                        for i in arquivos_para_mover
                    },
                    f,
                    ensure_ascii=False
                )

        for item in arquivos_para_mover:

            destino = os.path.join(
                destino_dir,
                os.path.basename(item)
            )

            try:

                shutil.move(
                    item,
                    destino
                )

                log(f"ARQUIVO MOVIDO: {destino}")

            except Exception as e:

                log(f"ERRO AO MOVER {item}: {e}")

                erro_mover = str(e)

        # O resumo fica duplicado de propósito: uma cópia dentro da pasta
        # do job em 6_Concluidos (junto com o resto dos entregáveis) e o
        # original continua em 8_Resumos, pra acesso rápido a todos os
        # resumos num lugar só sem precisar entrar pasta por pasta.
        resumo_path = os.path.join(
            RESUMOS_DIR,
            f"{nome}_resumo.txt"
        )

        if pc.copiar_se_existir(
            resumo_path,
            os.path.join(destino_dir, os.path.basename(resumo_path))
        ):

            log(f"RESUMO COPIADO PARA: {pasta_final}")

        pc.copiar_se_existir(
            LOG_FILE,
            os.path.join(
                destino_dir,
                "pipeline.log"
            )
        )

        if usar_montagem:

            if erro_mover:

                # Desfaz: tudo volta ao lugar de origem
                pc.restaurar_consolidacao(pasta_montagem)

                log(
                    f"CONSOLIDAÇÃO DESFEITA (arquivos voltaram ao lugar): "
                    f"{nome}"
                )

                consolidacao_falhou.add(nome)

            else:

                try:
                    os.remove(
                        os.path.join(
                            pasta_montagem,
                            pc.MANIFESTO_CONSOLIDACAO
                        )
                    )
                except OSError:
                    pass

                os.replace(pasta_montagem, pasta_final)

        if erro_mover:

            pc.evento(
                "item", etapa="consolidar", nome=nome, estado="falhou",
                motivo=erro_mover
            )

        else:

            pc.evento("item", etapa="consolidar", nome=nome, estado="ok")

    for _n in consolidacao_falhou:
        nomes_para_consolidar.pop(_n, None)

# =========================================================
# FASE 5 - LIMPEZA
# =========================================================

if "consolidar" in ETAPAS:

    log("=" * 60)
    log("FASE 5 - LIMPEZA")
    log("=" * 60)

    def extrair_nome_base_temp(arquivo):

        nome, _ = os.path.splitext(arquivo)

        if nome.endswith("_diarizado"):
            nome = nome[: -len("_diarizado")]

        return nome

    for pasta in [
        AUDIOS_DIR,
        TRANS_DIR,
        DIARIZ_DIR
    ]:
        # RESUMOS_DIR fica de fora de propósito — o resumo é o único
        # entregável que também mora permanentemente em 8_Resumos.

        for arquivo in os.listdir(pasta):

            caminho = os.path.join(
                pasta,
                arquivo
            )

            if not os.path.isfile(caminho):
                continue

            # Itens fora da seleção desta execução não são tocados
            if not pc.item_selecionado(extrair_nome_base_temp(arquivo)):
                continue

            # Só limpa o que já foi consolidado com sucesso nesta
            # execução. Um item que ficou de fora (transcrição falhou,
            # por exemplo) precisa manter seu mp3/txt aqui pra ser
            # tentado de novo na próxima rodada — apagar isso faria a
            # próxima execução começar do zero também.
            if extrair_nome_base_temp(arquivo) not in nomes_para_consolidar:

                log(f"[MANTIDO PRA NOVA TENTATIVA] {caminho}")
                continue

            try:

                os.remove(caminho)

                log(f"TEMPORÁRIO REMOVIDO: {caminho}")

            except Exception as e:

                log(f"ERRO AO REMOVER {caminho}: {e}")

    pc.evento("fase_fim", etapa="consolidar")

# =========================================================
# FINALIZAÇÃO
# =========================================================

fim_pipeline = time.time()

log("=" * 60)
log(
    f"PIPELINE FINALIZADO "
    f"({fim_pipeline - inicio_pipeline:.2f}s)"
)
log("=" * 60)

log("=" * 60)
log("RELATÓRIO DE FALHAS E RETENTATIVAS")
log("=" * 60)

if not relatorio_falhas:

    log("Nenhuma falha nesta execução.")

else:

    recuperados = [
        f for f in relatorio_falhas
        if "recuperado" in f["resultado"]
    ]

    pendentes = [
        f for f in relatorio_falhas
        if "recuperado" not in f["resultado"]
    ]

    log(
        f"Total: {len(relatorio_falhas)} ocorrência(s) — "
        f"{len(recuperados)} recuperada(s), "
        f"{len(pendentes)} sem sucesso"
    )

    for item in relatorio_falhas:

        log(
            f"  [{item['etapa'].upper()}] {item['arquivo']} — "
            f"{item['resultado']}"
        )

log("=" * 60)

_pendentes_final = [
    f for f in relatorio_falhas
    if "recuperado" not in f["resultado"]
]

pc.evento(
    "run_fim",
    resultado=(
        "cancelada" if pc.parada_solicitada()
        else "com_falhas" if _pendentes_final
        else "ok"
    ),
    falhas=relatorio_falhas
)

print("PROCESSAMENTO FINALIZADO")
