# Instalação (Windows 10/11)

Tudo roda na própria máquina — nenhum áudio ou texto é enviado para a internet
(só os modelos são baixados uma vez).

## Antes de começar
- **Python 3.13** (python.org) — marque *Add python.exe to PATH*.
- ~15 GB livres em disco (PyTorch, modelos, Ollama).
- Recomendado: placa NVIDIA com driver atualizado (4 GB de VRAM ou mais). Sem
  placa NVIDIA funciona em CPU, bem mais devagar.

## Instalar
1. Extraia o projeto (zip gerado por `ferramentas/gerar_pacote.py` ou o download
   do repositório) numa pasta, ex.: `C:\Transcritor`.
2. Dê duplo clique em **`Instalar Transcritor`** (ícone com a seta verde) e
   acompanhe (8 etapas):
   Python, FFmpeg, GPU, ambiente `.venv`, dependências (versões fixadas),
   Ollama + modelo de resumo, `config.json`, modelo de transcrição, pasta
   `dados/` e atalho **Transcritor** na Área de Trabalho.
   - Instala FFmpeg e Ollama via winget se faltarem. Se pedir para fechar e
     abrir de novo (para o Windows reconhecer), feche a janela e rode o
     `Instalar.bat` outra vez — ele retoma de onde parou.
   - `Instalar Transcritor.exe` e `Transcritor.exe` são só lançadores com
     ícone: cada um chama o `.bat` ao lado (`Instalar.bat` / `Portal.bat`).
     Se o Windows ou o antivírus barrar o `.exe` ("O Windows protegeu o
     computador"), abra o `.bat` direto — faz exatamente o mesmo.
3. Token da Hugging Face: **opcional** (só para diarização, que vem desligada).
   Para usá-la, aceite os termos do modelo `pyannote/speaker-diarization-community-1`
   com a mesma conta do token.

## Usar
Abra o atalho **Transcritor** (ou o `Transcritor` da pasta, ou `Portal.bat`).
Resultados em
`dados\6_Concluidos\<reunião>\` (transcrição + resumo); cópia dos resumos em
`dados\8_Resumos`. Sem portal: `ferramentas\Executar Pipeline (sem portal).bat`.

## Ajustes
Edite `config.json` (criado pelo instalador): `device` (`cuda`/`cpu`),
`modelo_whisper`, `ollama_modelo`, `base_dir`… (tabela no README).
**Não compartilhe o `config.json`** — ele guarda o seu token.

## Problemas comuns

### `self-signed certificate in certificate chain` ao baixar o modelo
A primeira transcrição baixa o modelo (~500 MB) de huggingface.co. Se um
**antivírus** (Kaspersky, ESET, Avast…) ou o **proxy da empresa** inspeciona o
HTTPS, ele reassina o certificado e o Python não confia nele. Abra a tela
**Ambiente** do portal (ou rode `ferramentas\Diagnostico_Rede.bat`): ela mostra
quem assina o certificado e oferece a correção. Da mais simples à mais manual:

1. **`pip-system-certs`** (já no `requirements.txt`) faz o Python usar os
   certificados do Windows. Se faltar: botão *Instalar suporte a certificados*
   na tela Ambiente, ou
   `.venv\Scripts\python.exe -m pip install pip-system-certs`.
2. **Certificado raiz da empresa/antivírus**: exporte-o em Base64 (`.pem`) e
   informe em `config.json`: `"ca_bundle": "C:\\pasta\\empresa.pem"`.
3. **Sem internet no destino**: leve o modelo de um computador que já o tenha.
   Na origem: `python src\transferir_modelo.py exportar small` (gera
   `dist\modelo_small.zip`); no destino:
   `python src\transferir_modelo.py importar caminho\para\modelo_small.zip`. A partir daí a
   transcrição roda 100% offline (o worker usa o modelo local primeiro).

### Falha na GPU
O arquivo é retentado automaticamente na CPU; o motivo aparece no portal.

### Versões de pacotes
O `requirements.txt` fixa as versões validadas (a pilha de IA já quebrou por
atualização, ex.: `av`). Não atualize sem testar.

## Atualizando uma instalação antiga
Versões anteriores guardavam as pastas de trabalho (`1_Videos`…`8_Resumos`)
direto na raiz e tinham os `.py` soltos nela. Para atualizar sem perder dados:

1. Extraia a versão nova **numa pasta nova**.
2. Copie o `config.json` antigo para a raiz da pasta nova e acrescente
   `"base_dir": "C:\\caminho\\da\\pasta\\antiga"` — assim os dados antigos
   continuam sendo usados. (Se a pasta antiga for a própria raiz da nova
   instalação, o layout antigo é detectado sozinho.)
3. Rode `Instalar.bat` (recria o `.venv`; o pip reaproveita o cache).

### Organizando as pastas antigas em `dados/`
Se as pastas numeradas (`1_Videos`…`8_Resumos`, `_portal`) estão soltas na raiz,
a tela **Ambiente** mostra "Pastas de trabalho: layout antigo". Para organizá-las:
**feche o portal** e execute `ferramentas\Migrar_para_dados.bat` — ele mostra o
que vai mover, pede confirmação e só então move (é renomear, instantâneo, sem
copiar). Recusa-se a rodar com pipeline/portal em execução ou se `dados/` já
tiver conteúdo e, se algo falhar no meio, desfaz o que já tinha movido.
Linha de comando: `python ferramentas\migrar_para_dados.py [--executar]`.

Alternativa: extrair por cima e apagar da raiz antiga os `.py`/`.bat` soltos
(`pipeline_*.py`, `transcrever_arquivo.py`, `diarizar_arquivo.py`,
`extrair_embeddings_voz.py`, `instalar.py`, `Executar Pipeline.bat`…).
