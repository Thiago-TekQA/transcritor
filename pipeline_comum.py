import os
import sys
import json
import shutil
import tempfile
import subprocess
import time

import numpy as np
import soundfile as sf

# O PyAnnote (usado pela diarização) importa o SpeechBrain internamente
# por baixo dos panos quando ele está instalado (necessário pro
# extrair_embeddings_voz.py, que roda isolado em subprocesso). O
# SpeechBrain registra um submódulo opcional (k2_fsa) que levanta
# ImportError em vez de AttributeError quando não consegue carregar —
# isso quebra o contrato do hasattr() e derruba QUALQUER inspect.stack()
# feito depois em qualquer lugar do processo (inclusive dentro do
# carregamento do modelo de diarização via PyTorch Lightning), de forma
# intermitente. O patch abaixo corrige o tipo de exceção pra não
# propagar esse erro. Fica aqui pra ser aplicado em todo script que
# importar este módulo (pipeline principal e diarizar_arquivo.py).
try:

    import speechbrain.utils.importutils as _sb_importutils

    _lazy_module_ensure_original = _sb_importutils.LazyModule.ensure_module

    def _lazy_module_ensure_seguro(self, *a, **kw):

        try:
            return _lazy_module_ensure_original(self, *a, **kw)
        except ImportError as e:
            raise AttributeError(str(e)) from e

    _sb_importutils.LazyModule.ensure_module = _lazy_module_ensure_seguro

except ImportError:

    pass

# =========================================================
# CONFIGURAÇÕES COMPARTILHADAS
# =========================================================

# Configuração por máquina, caminhos, extensões, eventos e trava vivem em
# pipeline_config.py (módulo leve, usado também pelo portal). Reexportados
# aqui para que `pc.BASE_DIR`, `pc.evento` etc. continuem funcionando.
from pipeline_config import (  # noqa: E402,F401
    PASTA_SCRIPTS,
    CONFIG,
    BASE_DIR,
    VIDEOS_DIR,
    AUDIOS_DIR,
    TRANS_DIR,
    DIARIZ_DIR,
    LOGS_DIR,
    DONE_DIR,
    PERFIS_VOZ_DIR,
    RESUMOS_DIR,
    VIDEOS_SUPORTADOS,
    AMOSTRAS_SUPORTADAS,
    ETAPAS_VALIDAS,
    ETAPAS_POR_MODO,
    sanitizar_nome,
    evento,
    evento_progresso,
    parada_solicitada,
    definir_itens,
    item_selecionado,
    adquirir_trava,
)

HF_TOKEN = CONFIG["hf_token"]

MIN_FALANTES = 1
MAX_FALANTES = 15

PERFIS_VOZ_ARQUIVO = os.path.join(BASE_DIR, "perfis_voz.json")

# Limiar de similaridade (cosseno) para aceitar uma identificação de voz.
# Calibrado com um teste real: mesma pessoa ~0.72, pessoas diferentes ~0.59
# no mesmo ambiente/gravação. Ajustar conforme os resultados reais forem
# aparecendo — quanto mais amostras de voz cadastradas, mais confiável fica.
LIMIAR_IDENTIFICACAO_VOZ = 0.65

MODELOS_DIR = os.path.join(BASE_DIR, "_modelos")
SPEECHBRAIN_MODEL_DIR = os.path.join(MODELOS_DIR, "speechbrain_ecapa")

SCRIPT_EMBEDDING_VOZ = os.path.join(PASTA_SCRIPTS, "extrair_embeddings_voz.py")
SCRIPT_TRANSCRICAO = os.path.join(PASTA_SCRIPTS, "transcrever_arquivo.py")
SCRIPT_DIARIZACAO = os.path.join(PASTA_SCRIPTS, "diarizar_arquivo.py")

# Resumo/ata via LLM local (Ollama), rodando depois que os modelos de
# transcrição/diarização já liberaram a GPU.
#
# Usamos o 3B (não o 7B) de propósito: o 7B não cabe inteiro nos 4GB de
# VRAM desta máquina (~42% GPU / 58% CPU), e isso faz o processo
# "llama-server" do Ollama consumir CPU/RAM pesado por horas em runs
# longos (visto na prática: 11.7GB de RAM, CPU saturada, GPU quase
# ociosa apesar de quente). O 3B roda 100% na GPU, sem esse problema —
# a qualidade da seção "Tarefas do Thiago" era pior nele, mas essa
# seção foi removida do prompt, e o restante (Resumo/Conclusões/
# TO-DOs/Pessoas citadas) saiu bom nos testes.
OLLAMA_URL = "http://localhost:11434/api/generate"
OLLAMA_MODELO = CONFIG["ollama_modelo"]

# 16384 dá folga confortável pra um bloco de até
# LIMITE_CHARS_RESUMO_DIRETO/TAMANHO_BLOCO_RESUMO chars + instrução +
# resposta, sem chegar perto do teto físico do modelo (32768).
OLLAMA_CONTEXTO = 16384

# =========================================================
# AUXILIARES
# =========================================================


def mover_se_existir(origem, destino):

    if not os.path.exists(origem):
        return False

    shutil.move(origem, destino)

    return True



def copiar_se_existir(origem, destino):

    if not os.path.exists(origem):
        return False

    shutil.copy2(origem, destino)

    return True



def encontrar_video_original(nome):

    for extensao in VIDEOS_SUPORTADOS:

        candidato = os.path.join(VIDEOS_DIR, f"{nome}{extensao}")

        if os.path.exists(candidato):
            return candidato

    for arquivo in os.listdir(VIDEOS_DIR):

        nome_original, extensao = os.path.splitext(arquivo)

        if (
            extensao.lower() in VIDEOS_SUPORTADOS
            and sanitizar_nome(nome_original) == nome
        ):
            return os.path.join(VIDEOS_DIR, arquivo)

    return None



def cosseno_similaridade(a, b):

    a = np.array(a)
    b = np.array(b)

    return float(
        np.dot(a, b) / (np.linalg.norm(a) * np.linalg.norm(b))
    )



def carregar_perfis_voz():

    if not os.path.exists(PERFIS_VOZ_ARQUIVO):
        return {}

    with open(PERFIS_VOZ_ARQUIVO, "r", encoding="utf-8") as f:
        return json.load(f)



def salvar_perfis_voz(perfis):

    with open(PERFIS_VOZ_ARQUIVO, "w", encoding="utf-8") as f:
        json.dump(perfis, f, ensure_ascii=False, indent=2)



def identificar_falante(embedding, perfis):

    melhor_nome = None
    melhor_similaridade = 0.0

    for nome, dados in perfis.items():

        similaridade = cosseno_similaridade(embedding, dados["embedding"])

        if similaridade > melhor_similaridade:
            melhor_similaridade = similaridade
            melhor_nome = nome

    if melhor_nome and melhor_similaridade >= LIMIAR_IDENTIFICACAO_VOZ:
        return melhor_nome, melhor_similaridade

    return None, melhor_similaridade



def fatiar_audio(audio, inicio, fim, duracao_maxima=30):

    sr = 16000

    i0 = max(0, int(inicio * sr))
    i1 = min(len(audio), int(fim * sr))

    if i1 - i0 > duracao_maxima * sr:
        i1 = i0 + int(duracao_maxima * sr)

    if i1 - i0 < int(sr * 0.3):
        return None

    return audio[i0:i1]



def maior_segmento_do_falante(diarize_df, falante):

    segmentos = diarize_df[diarize_df["speaker"] == falante].copy()

    segmentos["duracao"] = segmentos["end"] - segmentos["start"]

    return segmentos.loc[segmentos["duracao"].idxmax()]



def extrair_embeddings_via_subprocesso(trechos, device, log=print):
    """trechos: lista de tuplas (identificador, waveform_16k)."""

    if not trechos:
        return {}

    pasta_temp = tempfile.mkdtemp(prefix="perfis_voz_")

    try:

        itens = []

        for identificador, waveform in trechos:

            wav_path = os.path.join(pasta_temp, f"{identificador}.wav")

            sf.write(wav_path, waveform, 16000)

            itens.append({"id": identificador, "wav": wav_path})

        entrada_path = os.path.join(pasta_temp, "entrada.json")
        saida_path = os.path.join(pasta_temp, "saida.json")

        with open(entrada_path, "w", encoding="utf-8") as f:
            json.dump(itens, f)

        device_sb = "cuda:0" if device == "cuda" else device

        cmd = [
            sys.executable,
            SCRIPT_EMBEDDING_VOZ,
            "--device", device_sb,
            "--entrada", entrada_path,
            "--saida", saida_path,
            "--modelo-dir", SPEECHBRAIN_MODEL_DIR
        ]

        resultado = subprocess.run(cmd, capture_output=True, text=True)

        if resultado.returncode != 0:

            log(
                f"ERRO NO SUBPROCESSO DE EMBEDDING DE VOZ: "
                f"{resultado.stderr[-2000:]}"
            )

            return {}

        with open(saida_path, "r", encoding="utf-8") as f:
            embeddings = json.load(f)

        return {chave: np.array(valor) for chave, valor in embeddings.items()}

    finally:

        shutil.rmtree(pasta_temp, ignore_errors=True)



# O modelo local (qwen2.5:7b-instruct) tem um teto físico de contexto de
# 32768 tokens. Transcrições de reuniões longas (~45min+) já ultrapassam
# isso quando somadas às instruções — quando o contexto estoura, o
# modelo "esquece" a instrução (que fica no início do prompt) e passa a
# responder em inglês e sem seguir o formato pedido. Acima desse limite
# de caracteres, dividimos a transcrição em blocos, resumimos cada um
# separadamente e consolidamos no final — assim funciona pra reunião de
# qualquer tamanho, não só as de hoje.
LIMITE_CHARS_RESUMO_DIRETO = 12000
TAMANHO_BLOCO_RESUMO = 12000


def montar_prompt_resumo(transcricao):

    return (
        "Você é um assistente que gera atas de reunião a partir de "
        "transcrições brutas (com marcação de tempo e, quando disponível, "
        "rótulo do falante).\n\n"
        "Baseie-se ESTRITAMENTE no conteúdo da transcrição abaixo. Não "
        "invente informações que não estejam no texto.\n\n"
        "Gere a saída em markdown, em português, com exatamente estas "
        "seções:\n\n"
        "## Resumo\n"
        "(parágrafo curto sobre o que foi discutido)\n\n"
        "## Conclusões\n"
        "(lista do que ficou decidido)\n\n"
        "## TO-DOs\n"
        "(lista de tarefas/ações levantadas, indicando o responsável "
        "quando for possível identificar pelo texto)\n\n"
        "## Pessoas citadas\n"
        "(lista de NOMES PRÓPRIOS reais de pessoas mencionadas no "
        "conteúdo da fala, mesmo que não estejam participando diretamente "
        "da conversa. IMPORTANTE: rótulos como SPEAKER_00, SPEAKER_01 etc. "
        "NÃO são nomes de pessoas — são apenas marcações de quem falou, e "
        "não devem aparecer nesta lista. Se nenhum nome próprio for "
        "mencionado, escreva \"Nenhuma pessoa nomeada foi identificada\".)"
        "\n\n"
        "TRANSCRIÇÃO:\n"
        f"{transcricao}\n"
    )



def dividir_transcricao_em_blocos(transcricao, tamanho_bloco=TAMANHO_BLOCO_RESUMO):

    linhas = transcricao.splitlines(keepends=True)

    blocos = []
    bloco_atual = []
    tamanho_atual = 0

    for linha in linhas:

        if tamanho_atual + len(linha) > tamanho_bloco and bloco_atual:

            blocos.append("".join(bloco_atual))
            bloco_atual = []
            tamanho_atual = 0

        bloco_atual.append(linha)
        tamanho_atual += len(linha)

    if bloco_atual:
        blocos.append("".join(bloco_atual))

    return blocos



def montar_prompt_bloco(bloco, indice, total):

    return (
        f"Esta é a parte {indice} de {total} da transcrição de uma "
        "reunião em português (dividida em partes por ser muito longa). "
        "Responda em português.\n\n"
        "Liste em tópicos curtos, direto ao ponto, sem introdução: o que "
        "foi discutido nesta parte, decisões tomadas, tarefas/ações "
        "levantadas (com responsável quando possível identificar) e "
        "nomes próprios de pessoas mencionadas (não conte SPEAKER_00, "
        "SPEAKER_01 etc. como nome).\n\n"
        f"PARTE {indice}/{total}:\n"
        f"{bloco}\n"
    )



def montar_prompt_consolidacao(resumos_parciais):

    partes = "\n\n".join(
        f"--- Anotações da parte {i + 1} ---\n{resumo}"
        for i, resumo in enumerate(resumos_parciais)
    )

    return (
        "Abaixo estão anotações extraídas de várias partes de uma mesma "
        "reunião longa, em português. Baseie-se ESTRITAMENTE nelas, sem "
        "inventar informação nova, e sem repetir a mesma informação "
        "duas vezes caso apareça em mais de uma parte.\n\n"
        "Consolide tudo em UM ÚNICO resumo final, em markdown, em "
        "português, com exatamente estas seções:\n\n"
        "## Resumo\n"
        "(parágrafo curto sobre o que foi discutido)\n\n"
        "## Conclusões\n"
        "(lista do que ficou decidido)\n\n"
        "## TO-DOs\n"
        "(lista de tarefas/ações levantadas, indicando o responsável "
        "quando for possível identificar)\n\n"
        "## Pessoas citadas\n"
        "(lista de NOMES PRÓPRIOS reais de pessoas mencionadas. "
        "SPEAKER_00, SPEAKER_01 etc. NÃO são nomes de pessoas e não "
        "devem aparecer nesta lista. Se nenhum, escreva \"Nenhuma pessoa "
        "nomeada foi identificada\".)\n\n"
        f"ANOTAÇÕES DAS PARTES:\n{partes}\n"
    )



def temperatura_gpu():
    """Temperatura da GPU (°C) via nvidia-smi, ou None se não der pra
    ler (sem GPU NVIDIA, nvidia-smi indisponível, etc.)."""

    try:

        resultado = subprocess.run(
            [
                "nvidia-smi",
                "--query-gpu=temperature.gpu",
                "--format=csv,noheader,nounits"
            ],
            capture_output=True,
            text=True,
            timeout=5
        )

        if resultado.returncode == 0:
            return int(resultado.stdout.strip().splitlines()[0])

    except Exception:

        pass

    return None



# Rodar horas seguidas sem pausa aquece a GPU até ela entrar em
# throttling térmico (clock reduzido pela metade ou mais — visto na
# prática: 80°C, clock caindo de 1785MHz pra 780MHz). Uma pausa curta
# ANTES de chegar nesse ponto normalmente termina o trabalho mais rápido
# no total do que deixar rodar travado em clock baixo.
LIMITE_TEMP_PAUSA = 78
LIMITE_TEMP_RETOMAR = 65


def aguardar_gpu_esfriar(log=print, checar_a_cada=30, tempo_maximo_espera=1800):

    temp = temperatura_gpu()

    if temp is None or temp < LIMITE_TEMP_PAUSA:
        return

    log(
        f"GPU QUENTE ({temp}°C) — pausando processamento até esfriar "
        f"abaixo de {LIMITE_TEMP_RETOMAR}°C (evita throttling térmico "
        f"prolongado)"
    )

    evento(
        "pausa_termica", estado="inicio",
        temp=temp, retomar_abaixo=LIMITE_TEMP_RETOMAR
    )

    esperado = 0

    while esperado < tempo_maximo_espera:

        # Dorme em passos curtos pra reagir rápido a um pedido de parada
        # vindo do portal (não espera os 30s inteiros).
        for _ in range(int(checar_a_cada)):

            if parada_solicitada():

                evento("pausa_termica", estado="fim", temp=temp)

                return

            time.sleep(1)

        esperado += checar_a_cada

        temp = temperatura_gpu()

        if temp is None or temp <= LIMITE_TEMP_RETOMAR:

            log(f"GPU ESFRIOU ({temp}°C) — retomando processamento")

            evento("pausa_termica", estado="fim", temp=temp)

            return

    log(
        f"AVISO: GPU CONTINUA QUENTE ({temp}°C) APÓS ESPERAR "
        f"{tempo_maximo_espera}s — retomando mesmo assim"
    )

    evento("pausa_termica", estado="fim", temp=temp)



def _chamar_ollama(prompt):

    import requests

    aguardar_gpu_esfriar()

    resposta = requests.post(
        OLLAMA_URL,
        json={
            "model": OLLAMA_MODELO,
            "prompt": prompt,
            "stream": False,
            "options": {
                "num_ctx": OLLAMA_CONTEXTO,
                "temperature": 0.2,
                "num_predict": 700
            }
        },
        timeout=5400
    )

    resposta.raise_for_status()

    return resposta.json()["response"].strip()



def gerar_resumo_ollama(transcricao, log=print):

    if len(transcricao) <= LIMITE_CHARS_RESUMO_DIRETO:
        return _chamar_ollama(montar_prompt_resumo(transcricao))

    blocos = dividir_transcricao_em_blocos(transcricao)

    log(
        f"  TRANSCRIÇÃO LONGA ({len(transcricao)} chars) — "
        f"dividindo em {len(blocos)} parte(s) pro resumo"
    )

    resumos_parciais = []

    for indice, bloco in enumerate(blocos, start=1):

        log(f"  RESUMINDO PARTE {indice}/{len(blocos)}")

        resumo_parcial = _chamar_ollama(
            montar_prompt_bloco(bloco, indice, len(blocos))
        )

        resumos_parciais.append(resumo_parcial)

    log("  CONSOLIDANDO RESUMO FINAL")

    return _chamar_ollama(montar_prompt_consolidacao(resumos_parciais))



def _ollama_esta_rodando():

    import requests

    try:

        requests.get(
            "http://localhost:11434/api/version",
            timeout=3
        )

        return True

    except requests.exceptions.RequestException:

        return False



def garantir_ollama_rodando(log=print, tentativas=30):
    """Garante que o Ollama está no ar antes de gerar resumos. Se já
    estava rodando (ex.: subindo junto com o Windows), não mexe em nada
    e devolve None — assim o pipeline sabe que não fomos nós que
    ligamos, e não deve desligar depois. Se não estava, inicia e devolve
    o processo, pra ser encerrado no final pelo próprio pipeline."""

    if _ollama_esta_rodando():

        log("OLLAMA JÁ ESTAVA RODANDO (deixado como está)")

        evento("ollama", estado="ja_rodando")

        return None

    log("OLLAMA NÃO ESTÁ RODANDO — INICIANDO")

    try:

        processo = subprocess.Popen(
            ["ollama", "serve"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL
        )

    except FileNotFoundError:

        log(
            "AVISO: comando 'ollama' não encontrado — o Ollama está "
            "instalado e no PATH? Resumos vão falhar nesta execução."
        )

        evento("ollama", estado="indisponivel")

        return None

    for _ in range(tentativas):

        time.sleep(1)

        if _ollama_esta_rodando():

            log(f"OLLAMA INICIADO PELO PIPELINE (PID {processo.pid})")

            evento("ollama", estado="iniciado_por_nos", pid=processo.pid)

            return processo

    log(
        "AVISO: OLLAMA NÃO RESPONDEU A TEMPO APÓS TENTAR INICIAR "
        "— resumos podem falhar nesta execução"
    )

    evento("ollama", estado="indisponivel")

    return processo



def parar_ollama_se_iniciado_por_nos(processo, log=print):

    if processo is None:
        return

    log(
        f"ENCERRANDO OLLAMA (PID {processo.pid}, iniciado por este "
        f"pipeline) — libera memória/GPU quando o script termina"
    )

    try:

        processo.terminate()
        processo.wait(timeout=15)

    except Exception:

        try:
            processo.kill()
        except Exception as e:
            log(f"AVISO: NÃO CONSEGUI ENCERRAR O OLLAMA: {e}")

    evento("ollama", estado="parado")
