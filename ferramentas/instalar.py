"""Instalador do Pipeline de Transcrição (Windows).

Rodado pelo Instalar.bat. Faz, em ordem: checa Python/FFmpeg/GPU, cria o
ambiente virtual (.venv), instala o PyTorch (CUDA ou CPU) e as demais
dependências, instala o Ollama + modelo de resumo, grava o config.json e
cria as pastas de trabalho. Pode ser rodado de novo sem estragar nada.
"""

import json
import os
import shutil
import subprocess
import sys
import time
import urllib.request

PASTA = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # raiz
sys.path.insert(0, os.path.join(PASTA, "src"))

import pipeline_config as cfg  # noqa: E402  (só stdlib; seguro antes do venv)

VENV = os.path.join(PASTA, ".venv")
VENV_PYTHON = os.path.join(VENV, "Scripts", "python.exe")
CONFIG = os.path.join(PASTA, "config.json")

TORCH_INDEX_CUDA = "https://download.pytorch.org/whl/cu128"
TORCH_VERSOES = ["torch==2.8.0", "torchaudio==2.8.0", "torchvision==0.23.0"]

PASTAS = [
    "1_Videos", "2_Audios", "3_Transcricoes", "4_Diarizacoes",
    "5_Logs", "6_Concluidos", "7_Perfis_Voz", "8_Resumos",
]

ICONE = os.path.join(PASTA, "assets", "icone.ico")
PORTAL_BAT = os.path.join(PASTA, "Portal.bat")


def titulo(texto):
    print()
    print("=" * 60)
    print(f"  {texto}")
    print("=" * 60)


def rodar(cmd, **kw):
    return subprocess.run(cmd, **kw).returncode


def tem_gpu_nvidia():
    if not shutil.which("nvidia-smi"):
        return False
    try:
        r = subprocess.run(
            ["nvidia-smi", "--query-gpu=name,memory.total",
             "--format=csv,noheader"],
            capture_output=True, text=True, timeout=15,
        )
        if r.returncode == 0 and r.stdout.strip():
            print(f"  GPU encontrada: {r.stdout.strip().splitlines()[0]}")
            return True
    except Exception:
        pass
    return False


def winget_instalar(pacote_id, nome):
    if not shutil.which("winget"):
        print(f"  winget indisponível — instale {nome} manualmente e rode "
              "o Instalar.bat de novo.")
        return False
    print(f"  Instalando {nome} via winget (pode pedir confirmação)...")
    rodar(["winget", "install", "-e", "--id", pacote_id,
           "--accept-source-agreements", "--accept-package-agreements"])
    return True


def etapa_python():
    titulo("1/9  Python")
    v = sys.version_info
    print(f"  Python {v.major}.{v.minor}.{v.micro}")
    if (v.major, v.minor) < (3, 10) or (v.major, v.minor) > (3, 13):
        print("  AVISO: versão validada é a 3.13 (aceitas: 3.10 a 3.13). "
              "Fora disso o PyTorch pode não instalar.")


def etapa_ffmpeg():
    titulo("2/9  FFmpeg")
    if shutil.which("ffmpeg"):
        print("  FFmpeg encontrado.")
        return
    print("  FFmpeg não encontrado.")
    winget_instalar("Gyan.FFmpeg", "FFmpeg")
    if not shutil.which("ffmpeg"):
        print()
        print("  >>> FFmpeg instalado, mas o Windows só enxerga depois de "
              "reabrir o terminal.")
        print("  >>> FECHE esta janela e execute o Instalar.bat de novo.")
        sys.exit(2)


def etapa_venv():
    titulo("3/9  Ambiente virtual (.venv)")
    if os.path.exists(VENV_PYTHON):
        print("  .venv já existe — reaproveitando.")
        return
    if rodar([sys.executable, "-m", "venv", VENV]) != 0:
        print("  ERRO ao criar o ambiente virtual.")
        sys.exit(1)


def etapa_dependencias(gpu):
    titulo("4/9  Dependências Python (pode levar vários minutos)")
    rodar([VENV_PYTHON, "-m", "pip", "install", "--upgrade", "pip"])

    if gpu:
        print("  Instalando PyTorch com CUDA...")
        cmd = [VENV_PYTHON, "-m", "pip", "install", *TORCH_VERSOES,
               "--index-url", TORCH_INDEX_CUDA]
    else:
        print("  Sem GPU NVIDIA: instalando PyTorch versão CPU...")
        cmd = [VENV_PYTHON, "-m", "pip", "install", *TORCH_VERSOES]
    if rodar(cmd) != 0:
        print("  ERRO ao instalar o PyTorch.")
        sys.exit(1)

    req = os.path.join(PASTA, "requirements.txt")
    if rodar([VENV_PYTHON, "-m", "pip", "install", "-r", req]) != 0:
        print("  ERRO ao instalar requirements.txt.")
        sys.exit(1)


def ollama_no_ar():
    try:
        urllib.request.urlopen("http://localhost:11434/api/version", timeout=3)
        return True
    except Exception:
        return False


def etapa_ollama(modelo):
    titulo("5/9  Ollama + modelo de resumo")
    if not shutil.which("ollama"):
        winget_instalar("Ollama.Ollama", "Ollama")
    if not shutil.which("ollama"):
        print()
        print("  >>> Ollama instalado, mas só é reconhecido após reabrir "
              "o terminal.")
        print("  >>> FECHE esta janela e execute o Instalar.bat de novo.")
        sys.exit(2)

    processo = None
    if not ollama_no_ar():
        print("  Iniciando o Ollama temporariamente para baixar o modelo...")
        processo = subprocess.Popen(
            ["ollama", "serve"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        for _ in range(30):
            if ollama_no_ar():
                break
            time.sleep(1)

    print(f"  Baixando o modelo {modelo} (~2 GB)...")
    codigo = rodar(["ollama", "pull", modelo])

    if processo is not None:
        cfg.encerrar_arvore(processo.pid)

    if codigo != 0:
        print(f"  ERRO ao baixar o modelo. Tente depois: ollama pull {modelo}")


def etapa_config(gpu):
    titulo("6/9  Configuração (config.json)")
    config = {
        "base_dir": "",
        "hf_token": "",
        "modelo_whisper": "small",
        "device": "cuda" if gpu else "cpu",
        "ollama_modelo": "qwen2.5:3b-instruct",
        "portal_porta": 8765,
        "portal_hardlink": False,
    }
    if os.path.exists(CONFIG):
        with open(CONFIG, "r", encoding="utf-8") as f:
            config.update(json.load(f))
        print("  config.json já existe — mantendo seus valores.")
    else:
        print("  O token da Hugging Face só é necessário para a diarização")
        print("  (identificar quem falou). O modo padrão não usa. ")
        token = input("  Cole o token (ou Enter para pular): ").strip()
        config["hf_token"] = token

    with open(CONFIG, "w", encoding="utf-8") as f:
        json.dump(config, f, indent=2, ensure_ascii=False)
    print(f"  Dispositivo configurado: {config['device']}")
    return config


def etapa_modelo_whisper(modelo):
    titulo("7/9  Modelo de transcrição (Whisper)")
    print(f"  Baixando o modelo '{modelo}' (~500 MB, só na primeira vez)...")
    codigo = rodar([
        VENV_PYTHON, "-c",
        "from faster_whisper.utils import download_model; "
        f"print(download_model('{modelo}'))",
    ])
    if codigo != 0:
        print()
        print("  AVISO: não foi possível baixar o modelo agora.")
        print("  Causa comum: antivírus (Kaspersky, ESET...) ou proxy da empresa")
        print("  inspecionando o HTTPS (erro 'self-signed certificate').")
        print("  Rode o Diagnostico_Rede.bat: ele mostra a causa e o que fazer.")
        print("  Saída sem internet: leve o modelo de outro computador com")
        print("  'python src\transferir_modelo.py importar <caminho>\modelo_small.zip'.")


def etapa_pastas():
    titulo("8/9  Pastas de trabalho")
    for nome in PASTAS:
        os.makedirs(os.path.join(cfg.BASE_DIR, nome), exist_ok=True)
    print(f"  Pastas criadas em: {cfg.BASE_DIR}")


def _ps(texto):
    """Escapa um texto para literal entre aspas simples do PowerShell."""

    return "'" + str(texto).replace("'", "''") + "'"


def criar_atalho(pasta_destino=None):
    """Cria o atalho "Transcritor" (abre o Portal.bat) com o ícone do
    projeto. Sem `pasta_destino`, usa a Área de Trabalho do usuário (o
    Windows informa o caminho certo, mesmo com OneDrive). Devolve o caminho
    do atalho ou None se não conseguiu."""

    if not os.path.exists(PORTAL_BAT):
        return None

    destino = (
        _ps(pasta_destino) if pasta_destino
        else "[Environment]::GetFolderPath('Desktop')"
    )

    script = (
        f"$d = {destino}; "
        "if (-not (Test-Path $d)) { New-Item -ItemType Directory -Path $d | Out-Null }; "
        "$lnk = Join-Path $d 'Transcritor.lnk'; "
        "$s = (New-Object -ComObject WScript.Shell).CreateShortcut($lnk); "
        f"$s.TargetPath = {_ps(PORTAL_BAT)}; "
        f"$s.WorkingDirectory = {_ps(PASTA)}; "
        f"$s.IconLocation = {_ps(ICONE)}; "
        "$s.Description = 'Portal do Transcritor'; "
        "$s.Save(); Write-Output $lnk"
    )

    try:

        r = subprocess.run(
            ["powershell", "-NoProfile", "-Command", script],
            capture_output=True, text=True, timeout=60,
        )

        if r.returncode == 0 and r.stdout.strip():
            return r.stdout.strip().splitlines()[-1]

    except Exception:

        pass

    return None


def etapa_atalho():
    titulo("9/9  Atalho na Área de Trabalho")
    caminho = criar_atalho()
    if caminho:
        print(f"  Atalho criado: {caminho}")
    else:
        print("  Não foi possível criar o atalho (sem problema: use o Portal.bat).")


def main():
    print("INSTALADOR DO PIPELINE DE TRANSCRIÇÃO")
    etapa_python()
    etapa_ffmpeg()
    print()
    gpu = tem_gpu_nvidia()
    if not gpu:
        print("  Nenhuma GPU NVIDIA detectada — vai rodar em CPU "
              "(funciona, mas é bem mais lento).")
    etapa_venv()
    etapa_dependencias(gpu)
    etapa_ollama("qwen2.5:3b-instruct")
    config = etapa_config(gpu)
    etapa_modelo_whisper(config["modelo_whisper"])
    etapa_pastas()
    etapa_atalho()

    titulo("INSTALAÇÃO CONCLUÍDA")
    print("  Como usar (recomendado): abra o atalho 'Transcritor' (ou o")
    print("  Portal.bat), aponte a pasta com os vídeos/áudios e acompanhe cada")
    print("  etapa no navegador.")
    print("  Alternativa sem portal: ferramentas\\Executar Pipeline (sem portal).bat")
    if config["hf_token"]:
        print()
        print("  Para usar diarização, aceite os termos do modelo")
        print("  pyannote/speaker-diarization-community-1 na Hugging Face")
        print("  com a mesma conta do token.")


if __name__ == "__main__":
    main()
