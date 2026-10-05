# Transcritor

Transcrição, resumo e (opcionalmente) identificação de falantes de reuniões
gravadas, **100% local**: nenhum áudio, vídeo ou texto sai da máquina — nem
na etapa de resumo, que usa um modelo de linguagem local (Ollama).

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
| Consolidar | move os entregáveis para `6_Concluidos/<reunião>/` e limpa temporários | — |

As etapas são **combináveis** (só áudio, só transcrição, tudo, ou qualquer
combinação). Etapas que já foram feitas são puladas automaticamente.

## Recursos de robustez

- Cada transcrição/diarização roda em **processo isolado**: um crash nativo
  de CUDA derruba só aquele arquivo, não o lote.
- Se falhar na GPU, o arquivo é **retentado na CPU** automaticamente.
- **Pausa térmica**: a GPU é pausada acima de 78 °C e retomada abaixo de
  65 °C, evitando throttling em lotes longos.
- Resumos de transcrições longas são feitos em blocos e consolidados.
- Saídas gravadas de forma atômica (`.parcial` → renomeia no fim): um
  cancelamento nunca deixa arquivo incompleto passando por "pronto".
- O Ollama só é desligado se foi o próprio pipeline que o ligou.
- Uma execução por vez (trava de arquivo) — vale também para o `.bat`.

## Instalação (Windows 10/11)

Requisitos: **Python 3.13** (python.org, marcando *Add to PATH*), ~15 GB livres
e, de preferência, placa NVIDIA (sem ela roda em CPU, mais devagar).

1. Gere o pacote (`python gerar_pacote.py`) ou clone este repositório.
2. Dê duplo clique em **`Instalar.bat`**. Ele instala FFmpeg e Ollama (winget),
   cria o ambiente `.venv` com as versões fixadas, baixa os modelos e cria
   `config.json`.
3. O token da Hugging Face é **opcional** (só para diarização).

Detalhes em [`LEIA-ME_INSTALACAO.md`](LEIA-ME_INSTALACAO.md).

## Uso

### Portal (recomendado)

Duplo clique em **`Portal.bat`** (ou `python portal/servidor.py`) e abra
<http://127.0.0.1:8765>.

1. **Nova execução**: informe/escolha a pasta de origem, marque as etapas
   (Tudo, Só áudio, Só transcrição, Só resumo, Personalizado) e clique em
   *Analisar*. O portal mostra, por arquivo e etapa, o que será executado,
   o que já existe e o que está bloqueado (ex.: transcrição sem áudio).
2. **Execução**: estado de cada arquivo/etapa ao vivo (progresso da
   transcrição, falhas, retentativa na CPU, pausa térmica, log). Botões:
   *Parar após o arquivo atual*, *Cancelar agora* e *Retomar*.
3. **Resultados**: reuniões concluídas e parciais; abre resumo, transcrição
   e log.

A pasta de origem **nunca é alterada**: os arquivos são copiados para a área
de trabalho. Fechar o portal **não interrompe** uma execução em andamento; ao
reabrir, ele reconecta.

### Linha de comando

```bash
python pipeline_transcricao_reestruturado.py --modo simples           # mp3 → transcrição → resumo → consolidar
python pipeline_transcricao_reestruturado.py --modo completo          # + diarização
python pipeline_transcricao_reestruturado.py --etapas transcricao,resumo
python pipeline_transcricao_reestruturado.py --etapas mp3 --itens itens.json
```

`--itens` recebe um JSON com a lista de nomes (sem extensão) a processar.
Referência completa em [`Manual.md`](Manual.md).

## Configuração (`config.json`)

Criado pelo instalador (modelo em `config.exemplo.json`). **Nunca é versionado
nem entra no pacote** — guarda o token da Hugging Face.

| Chave | Padrão | Significado |
|---|---|---|
| `base_dir` | `""` (pasta dos scripts) | onde ficam `1_Videos` … `8_Resumos` |
| `hf_token` | `""` | token Hugging Face (só diarização) |
| `modelo_whisper` | `small` | `small` rápido; `medium` mais preciso |
| `device` | `cuda` | `cuda` ou `cpu` |
| `ollama_modelo` | `qwen2.5:3b-instruct` | modelo do resumo |
| `portal_porta` | `8765` | porta do portal |
| `portal_hardlink` | `false` | usa atalho em vez de copiar, se na mesma unidade |
| `ca_bundle` | `""` | caminho de um `.pem` com o certificado raiz do antivírus/empresa |

## Estrutura

```
pipeline_config.py                     config, caminhos, eventos, trava (leve)
pipeline_comum.py                      utilitários de IA (Ollama, GPU, vozes)
pipeline_transcricao_reestruturado.py  orquestrador das etapas
transcrever_arquivo.py / diarizar_arquivo.py / extrair_embeddings_voz.py   workers isolados
portal/servidor.py                     API + páginas (aiohttp, só 127.0.0.1)
portal/execucoes.py                    plano, cópia, execução, estado
portal/static/                         interface (HTML/CSS/JS puro)
instalar.py, Instalar.bat, requirements.txt, gerar_pacote.py   instalação e pacote
```

Pastas de trabalho (criadas na instalação): `1_Videos`, `2_Audios`,
`3_Transcricoes`, `4_Diarizacoes`, `5_Logs`, `6_Concluidos`, `7_Perfis_Voz`,
`8_Resumos` e `_portal` (execuções do portal). Nada disso vai para o Git.

## Segurança

- O servidor escuta apenas em `127.0.0.1`, valida o `Host`, exige token por
  sessão e `Origin` correto nos POSTs, não serve `config.json` e não tem
  endpoint que apague ou escreva na sua pasta.
- Dados de reuniões e o `config.json` estão no `.gitignore`. Nunca coloque
  tokens no código.

## Problemas comuns

### `self-signed certificate in certificate chain` ao baixar o modelo

A primeira transcrição baixa o modelo (~500 MB) de huggingface.co. Se um
**antivírus** (Kaspersky, ESET, Avast…) ou o **proxy da empresa** inspeciona o
HTTPS, ele reassina o certificado e o Python não confia nele. Rode
**`Diagnostico_Rede.bat`**: ele mostra quem assina o certificado e o que fazer.
Soluções, da mais simples à mais manual:

1. **`pip-system-certs`** (já no `requirements.txt`) faz o Python usar os
   certificados do Windows. Se faltar:
   `.venv\Scripts\python.exe -m pip install pip-system-certs`
2. **Certificado raiz da empresa/antivírus**: exporte-o em Base64 (`.pem`) e
   informe em `config.json`: `"ca_bundle": "C:\pasta\empresa.pem"`.
3. **Sem internet no destino**: leve o modelo de um computador que já o tenha.
   Na origem: `python transferir_modelo.py exportar small` (gera
   `modelo_small.zip`); no destino: `python transferir_modelo.py importar modelo_small.zip`.
   A partir daí a transcrição roda 100% offline (o worker usa o modelo local
   primeiro e só vai à rede se ele não existir).

O portal avisa na tela *Nova execução* quando o modelo ainda não está no
computador.

### Outros

- **Falha na GPU**: o arquivo é retentado na CPU; o motivo aparece no portal.
- **Versões de pacotes**: o `requirements.txt` fixa as versões validadas
  (a pilha de IA já quebrou por atualização, ex.: `av`). Não atualize sem testar.
