# Arquitetura

Visão rápida de como as peças se encaixam — útil para quem for mexer no código.

## Camadas

```
navegador ──HTTP/JSON──▶ src/portal/servidor.py ──▶ execucoes.py / ambiente.py
                                                        │ subprocesso destacado
                                                        ▼
                                  src/pipeline.py  ──▶  workers isolados (transcrever/diarizar)
                                         │                  │
                                         └──── eventos.jsonl ◀──┘   (lido pelo portal)
```

- O **portal** só mostra, inicia e controla; nunca importa torch/whisperx.
- Cada execução é um **subprocesso destacado** do `pipeline.py`: continua se o
  portal for fechado e o portal reconecta lendo o arquivo de eventos.
- O **pipeline** roda as etapas em sequência por fase (todos os MP3, depois
  todas as transcrições…) e usa processos isolados para o que pode derrubar o
  processo (CUDA).

## Módulos (`src/`)

| Arquivo | Papel |
|---|---|
| `pipeline_config.py` | config (`config.json`), caminhos, extensões, `evento()`, trava, parada, seleção de itens. Só stdlib — o portal importa sem carregar a pilha de IA. |
| `pipeline_comum.py` | Ollama, pausa térmica, perfis de voz, resumo em blocos. Reexporta o de `pipeline_config`. |
| `pipeline.py` | orquestrador: `--etapas`, `--itens`, portas por etapa, eventos, retentativa CPU, relatório de falhas. |
| `transcrever_arquivo.py`, `diarizar_arquivo.py`, `extrair_embeddings_voz.py` | workers isolados. |
| `diagnostico_rede.py`, `transferir_modelo.py` | usados pela tela Ambiente (e pela linha de comando). |
| `portal/servidor.py` | aiohttp em `127.0.0.1`; API e estáticos. |
| `portal/execucoes.py` | planejar, copiar, iniciar/parar/cancelar, montar estado a partir dos eventos, resultados. |
| `portal/processos.py` | mapa de processos do transcritor (inclusive de outras instalações), detecção de pipelines concorrentes e órfãos do Ollama, encerramento seguro. |
| `portal/ambiente.py` | verificação do ambiente e correções (instalar certificados, baixar/importar modelo, Ollama). |

## Etapas e dependências

`mp3` → `transcricao` → `resumo` → `consolidar` (+ `diarizacao` a partir do
áudio). O planejamento do portal calcula por item/etapa: *executar*, *pular*
(já existe) ou *bloqueado* (falta uma etapa anterior). `consolidar` exige
transcrição e resumo.

## Eventos (`eventos.jsonl`)

Uma linha JSON por evento (`v`, `ts`, `ev`…), gravada com um único `write` em
modo append — o leitor só pode ver parcialmente a última linha, que ignora.
Principais: `run_inicio`, `fase_inicio/fim`, `item` (`etapa`, `nome`, `estado`,
`dispositivo`, `tentativa`, `dur`, `motivo`, `nota`), `progresso` (`pct`),
`pausa_termica`, `ollama`, `limpeza`, `cancelado`, `erro_fatal`, `run_fim`.
Estados de item: `pendente`, `rodando`, `ok`, `pulado`, `falhou`,
`aguardando_cpu`, `sem_entrada`, `nao_executado`, `cancelado`. O estado exibido
é calculado por uma função pura (`dobrar_eventos`) — fácil de testar.

## Execução única, parar e cancelar

- **Trava**: `msvcrt.locking` em `<base>/.pipeline.lock` (o Windows solta ao
  morrer o processo) + `ativa.json` do portal. Vale também para o `.bat`.
- **Parar após o arquivo atual**: o portal cria `parar.flag`; o pipeline checa
  entre arquivos (e durante a espera térmica).
- **Cancelar agora**: `taskkill /T /F` na árvore de processos, depois limpeza das
  saídas parciais. Durante `consolidar` faz parada suave.

## Interrupções

Toda saída é escrita em `.parcial` e renomeada só no fim (mp3, transcrição,
diarização, resumo); a consolidação monta `6_Concluidos/<nome>.parcial/` e
renomeia a pasta no fim. A limpeza remove **só** a saída da etapa interrompida;
vídeo, áudio e etapas concluídas permanecem. Roda ao cancelar, ao detectar
execução interrompida e no início de toda execução.

## Pasta de origem e área de trabalho

O pipeline nunca conhece a pasta do usuário. O portal copia (ou cria atalho, se
`portal_hardlink`) o necessário para `dados/1_Videos` ou `dados/2_Audios`,
gravando em `.copiando` e renomeando no fim. Itens que ficaram a meio caminho
são listados na tela *Nova execução* (desmarcados) para continuar ou deixar.
Duas ações por item, **sempre iniciadas pelo usuário**: *Remover da lista*
(grava o nome em `_portal/ocultos.json`; nenhum arquivo é tocado) e *Deletar
arquivos* (`deletar_parado`: apaga só os artefatos do item nas pastas de
trabalho — localizados por varredura, nunca montando caminho a partir do nome —,
exige `confirmar:true` no POST e recusa itens já concluídos ou com execução em
andamento).

## Processos

`portal/processos.py` lê os processos do Windows (PowerShell/CIM) e a GPU
(`nvidia-smi`) e monta uma árvore: pipeline → workers/FFmpeg/Ollama. A pasta da
instalação vem do caminho do script, do worker filho ou do `.bat` que iniciou o
pipeline (o `.bat` antigo chama o script por caminho relativo). `montar_mapa` é
uma função pura (testada com listas sintéticas). Encerrar só aceita um PID que
esteja no mapa **naquele momento**, nunca o próprio portal nem quem o iniciou; uma
execução desta instalação é cancelada pelo fluxo completo (limpa só a saída
parcial); o resto recebe `taskkill /T /F`.

O Ollama é sempre encerrado pela **árvore** (`encerrar_arvore`): matar só o
`ollama serve` deixava o processo que carrega o modelo (llama-server, ~3 GB)
órfão, ocupando RAM.

## Segurança do portal

Só `127.0.0.1`; `Host` validado (anti DNS-rebinding); POST exige JSON, `Origin`
próprio e token aleatório por processo; sem CORS; estáticos só de
`portal/static`; `config.json` nunca servido; nenhum endpoint apaga/escreve na
pasta do usuário; resultados só de filhos diretos de `6_Concluidos`/área de
trabalho, com tipo de arquivo por enum.
