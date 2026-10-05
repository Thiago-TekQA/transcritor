# Transcritor

Transcrição, resumo e (opcionalmente) identificação de falantes de reuniões
gravadas, **100% local**: nenhum áudio, vídeo ou texto sai da máquina — nem na
etapa de resumo, que usa um modelo de linguagem local (Ollama).

Você aponta uma pasta com vídeos/áudios, escolhe as etapas e acompanha cada
arquivo, etapa por etapa, num **portal no navegador** (servido só em
`127.0.0.1`).

## O que faz

| Etapa | O que acontece | Ferramenta |
|---|---|---|
| Gerar áudio | extrai o MP3 do vídeo | FFmpeg |
| Transcrição | fala → texto com marcações de tempo | faster-whisper (CUDA ou CPU) |
| Diarização *(opcional)* | quem falou cada trecho | WhisperX + PyAnnote |
| Resumo | Resumo, Conclusões, TO-DOs e Pessoas citadas, em português | Ollama (`qwen2.5:3b-instruct`) |
| Consolidar | junta os entregáveis em `6_Concluidos/<reunião>/` e limpa temporários | — |

As etapas são **combináveis** (só áudio, só transcrição, tudo ou qualquer
combinação). O que já foi feito é pulado automaticamente.

## Início rápido (Windows 10/11)

1. Instale o **Python 3.13** (python.org, marcando *Add to PATH*).
2. **[⬇ Baixe o zip do projeto](https://github.com/Thiago-TekQA/transcritor/archive/refs/heads/main.zip)**,
   extraia numa pasta e dê duplo clique em **`Instalar Transcritor`**
   (o ícone com a seta verde; equivale ao `Instalar.bat`). Ele instala
   FFmpeg e Ollama (via winget), cria o ambiente `.venv` com as versões
   fixadas, baixa os modelos, cria a pasta `dados/` e um atalho
   **Transcritor** na Área de Trabalho.
3. Abra o atalho (ou o **`Transcritor`** da pasta): o navegador abre em
   <http://127.0.0.1:8765>. O portal roda em segundo plano, sem janela;
   para desligá-lo, use **Encerrar portal** no topo da página.

Requisitos, rede corporativa/antivírus e atualização de instalações antigas:
[`docs/instalacao.md`](docs/instalacao.md).

## Usando o portal

1. **Nova execução**: informe/escolha a pasta de origem, marque as etapas (Tudo,
   Só áudio, Só transcrição, Só resumo, Personalizado) e clique em *Analisar*.
   O portal mostra, por arquivo e etapa, o que será executado, o que já existe
   e o que está bloqueado. Itens que ficaram **parados no meio do caminho** em
   execuções anteriores aparecem numa lista à parte, **desmarcados** — você marca
   os que devem continuar. Cada item tem dois botões, que só agem quando você
   clica: **Remover da lista** (apenas esconde o item; dá para trazê-lo de volta
   em "ocultos") e **Deletar arquivos** (apaga os arquivos intermediários dele na
   área de trabalho, depois de uma confirmação que lista o que será apagado).
2. **Execução**: estado ao vivo de cada arquivo/etapa (progresso, falhas,
   retentativa na CPU, pausa térmica, log). Botões: *Parar após o arquivo
   atual*, *Cancelar agora* e *Retomar*.
3. **Resultados**: reuniões concluídas e parciais; abre resumo, transcrição e log.
4. **Ambiente**: verifica o que o computador precisa (FFmpeg, certificados do
   Windows, acesso ao Hugging Face, modelos) e **corrige com um clique**.
5. **Processos**: mapa de tudo o que o transcritor está rodando no computador —
   pipelines, workers, FFmpeg, Ollama e outros portais, inclusive de **outras
   instalações** —, com CPU, RAM, GPU e de qual instalação é cada um. Avisa
   quando há **pipelines concorrentes** (disputam a GPU) ou processos do Ollama
   **órfãos** ocupando memória, e permite encerrá-los com confirmação. A tela
   *Nova execução* também avisa antes de iniciar se já há outro pipeline rodando.

A pasta de origem **nunca é alterada**: os arquivos são copiados para a área de
trabalho. Fechar o portal **não interrompe** uma execução; ao reabrir, ele
reconecta. Se uma etapa for interrompida, só a saída dela é descartada — vídeo,
áudio e etapas já concluídas ficam.

Sem o portal: [`docs/linha-de-comando.md`](docs/linha-de-comando.md).

## Estrutura do repositório

```
README.md  Instalar.bat  Portal.bat  requirements.txt  config.exemplo.json
src/          código do programa
  pipeline.py                  orquestrador das etapas
  pipeline_config.py           configuração, caminhos, eventos, trava
  pipeline_comum.py            utilitários de IA (Ollama, GPU, vozes)
  transcrever_arquivo.py  diarizar_arquivo.py  extrair_embeddings_voz.py   workers isolados
  diagnostico_rede.py  transferir_modelo.py                               usados pela tela Ambiente
  portal/                      servidor web (aiohttp) + interface (HTML/CSS/JS puro)
ferramentas/  instalar.py, gerar_pacote.py, migrar_para_dados.py e .bat auxiliares
docs/         instalação, linha de comando, arquitetura
tests/        testes unitários     assets/  ícone
```

Na máquina de quem usa (nada disso vai para o Git): `config.json`, `.venv/`,
`dados/` (`1_Videos` … `8_Resumos`, `_portal`, `_modelos`, `perfis_voz.json`) e
`dist/` (pacote `.zip` e modelo exportado, quando gerados).

**A raiz fica limpa ao trabalhar:** tudo o que o programa produz vai para
`dados/` ou `dist/`; `__pycache__` não é criado (`PYTHONDONTWRITEBYTECODE`);
`tests/teste_estrutura.py` verifica isso. Se a sua instalação ainda tem as
pastas numeradas soltas na raiz, a tela **Ambiente** avisa e
`ferramentas\Migrar_para_dados.bat` as move para `dados/` (com simulação antes).

## Configuração (`config.json`)

Criado pelo instalador (modelo em `config.exemplo.json`). **Nunca é versionado
nem entra no pacote** — guarda o token da Hugging Face.

| Chave | Padrão | Significado |
|---|---|---|
| `base_dir` | `""` (→ `dados/`) | onde ficam as pastas de trabalho |
| `hf_token` | `""` | token Hugging Face (só diarização) |
| `modelo_whisper` | `small` | `small` rápido; `medium` mais preciso |
| `device` | `cuda` | `cuda` ou `cpu` |
| `ollama_modelo` | `qwen2.5:3b-instruct` | modelo do resumo |
| `portal_porta` | `8765` | porta do portal |
| `portal_hardlink` | `false` | atalho em vez de cópia, se na mesma unidade |
| `ca_bundle` | `""` | `.pem` com o certificado raiz do antivírus/empresa |

## Segurança

- O servidor escuta só em `127.0.0.1`, valida o `Host`, exige token por sessão e
  `Origin` correto nos POSTs, não serve `config.json` e nunca altera a sua pasta
  de origem. A única exclusão é a de arquivos intermediários da área de trabalho
  (botão *Deletar arquivos*), só com confirmação e nunca de itens já concluídos.
- Dados de reuniões e `config.json` estão no `.gitignore`. Nunca coloque tokens
  no código.

## Mais

[`docs/arquitetura.md`](docs/arquitetura.md) descreve etapas, eventos, trava e
tratamento de interrupções. Testes: `python -m unittest discover tests`.
