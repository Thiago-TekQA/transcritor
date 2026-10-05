# Instalação em outro computador (Windows 10/11)

Pipeline local de transcrição e resumo de reuniões. Tudo roda na própria
máquina — nenhum áudio ou texto é enviado para a internet.

## Antes de começar
- **Python 3.13** (python.org) — marque *Add python.exe to PATH*.
- ~15 GB livres em disco (PyTorch, modelos, Ollama).
- Recomendado: placa NVIDIA com driver atualizado (4 GB de VRAM ou mais).
  Sem placa NVIDIA funciona em CPU, bem mais devagar.

## Instalar
1. Extraia o `Transcritor_pacote.zip` numa pasta (ex.: `C:\Transcritor`).
2. Dê duplo clique em **Instalar.bat** e acompanhe.
   - Ele instala FFmpeg e Ollama (via winget) se faltarem, cria o ambiente
     `.venv`, baixa o modelo de resumo e cria as pastas.
   - Se pedir para fechar e abrir de novo (para o Windows reconhecer
     FFmpeg/Ollama), feche a janela e execute o Instalar.bat outra vez.
3. Token da Hugging Face: **opcional**. Só é necessário para a diarização
   (identificar quem falou), que vem desligada por padrão.

## Usar

**Pelo portal (recomendado):** duplo clique em **Portal.bat**. O navegador abre
em `http://127.0.0.1:8765`: informe a pasta com os vídeos/áudios, escolha as
etapas (tudo, só áudio, só transcrição, só resumo ou combinações) e acompanhe
cada arquivo. A sua pasta de origem não é alterada. Fechar a janela do portal
não interrompe uma execução em andamento.

**Sem portal:** coloque os arquivos em `1_Videos` e dê duplo clique em
**Executar Pipeline.bat**.

Resultados em `6_Concluidos\<reunião>\` (transcrição + resumo); cópia dos
resumos em `8_Resumos`.

## Ajustes
Edite `config.json` (criado pelo instalador): `device` (`cuda` ou `cpu`),
`modelo_whisper` (`small` é o padrão; `medium` é mais preciso e mais lento),
`ollama_modelo`. **Não compartilhe o config.json** — ele guarda o seu token.
