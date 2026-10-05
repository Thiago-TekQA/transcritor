# Linha de comando

O jeito recomendado é o [portal](../README.md). Este guia é para quem prefere o
terminal ou o `.bat` simples. Rode sempre a partir da raiz do projeto, de
preferência com o ambiente do instalador: `.venv\Scripts\python.exe src\pipeline.py …`
(ou `python src\pipeline.py …` se não houver `.venv`).

## Execução padrão (sem portal)

Coloque vídeos/áudios em `dados\1_Videos` e dê duplo clique em
`ferramentas\Executar Pipeline (sem portal).bat` — equivale a
`python src\pipeline.py --modo simples`: áudio → transcrição → resumo →
consolidar, **sem** diarização.

## Etapas e modos

As etapas são: `mp3`, `transcricao`, `diarizacao`, `resumo`, `consolidar`.

```bash
# Escolher as etapas livremente (combináveis; vale no lugar do --modo)
python src/pipeline.py --etapas mp3,transcricao
python src/pipeline.py --etapas resumo

# Só alguns itens (JSON com a lista de nomes, sem extensão)
python src/pipeline.py --etapas transcricao --itens itens.json
```

`--modo` continua funcionando como atalho para um conjunto de etapas:

| `--modo` | Etapas |
|---|---|
| `simples` (padrão) | mp3, transcricao, resumo, consolidar |
| `completo` | + diarizacao |
| `somente_mp3` | mp3 |
| `somente_transcricao` | transcricao |
| `diarizacao` | diarizacao |
| `resumo` | resumo |
| `perfis_voz` | cadastra perfis de voz (ver abaixo) |

Outras opções: `--modelo small|medium|large-v3` (padrão do `config.json`),
`--device cuda|cpu` (padrão do `config.json`).

Só uma execução roda por vez (a GPU é uma só): uma segunda sai com código 3.

## Diarização e perfis de voz

A diarização identifica quem falou cada trecho (`SPEAKER_00`, `SPEAKER_01`…).
Vem **desligada por padrão**: sem perfis de voz cadastrados ela pode trocar de
pessoa em fala rápida ou sobreposta. Precisa do token da Hugging Face no
`config.json`.

Para trocar o rótulo genérico pelo nome real:

1. Crie `dados\7_Perfis_Voz\<Nome>\` e coloque 2 a 4 amostras de 15–30 s da
   pessoa falando (áudio ou vídeo, de preferência sem outras vozes).
2. Rode `python src/pipeline.py --modo perfis_voz` (gera `dados\perfis_voz.json`).

Depois, toda diarização compara cada falante com os perfis cadastrados.

## Resumo/ata

Gera `dados\8_Resumos\<nome>_resumo.txt` com **Resumo, Conclusões, TO-DOs e
Pessoas citadas**, em português, a partir da transcrição. Requer o **Ollama**
com o modelo configurado (`ollama pull qwen2.5:3b-instruct`); roda 100% local.
O pipeline liga o Ollama se necessário e só o desliga se foi ele quem ligou.

- Transcrições longas (~12 000 caracteres+) são divididas em blocos e depois
  consolidadas (o modelo tem teto de contexto), o que torna reuniões longas mais
  lentas.
- O resumo fica em **dois lugares**: cópia em `6_Concluidos\<reunião>\` e original
  em `8_Resumos` (que a limpeza nunca apaga).
- É um modelo pequeno: confira o resumo contra a transcrição em decisões
  importantes, principalmente nos responsáveis dos TO-DOs.

## Formatos aceitos

`.mp4 .mkv .avi .mov .ogg .wav .m4a .aac .flac` (e `.mp3`).
Vídeo/áudio em `1_Videos` passa pela extração da etapa `mp3`; áudio direto em
`2_Audios` pula essa etapa.

## Regras importantes

**Skip automático** — não refaz o que já existe: MP3, transcrição, diarização e
resumo.

**Falha isolada e retentativa** — transcrição e diarização rodam cada uma num
processo separado por arquivo; um crash nativo da GPU derruba só aquele arquivo.
Quem falhou na GPU é retentado na CPU no fim; se ainda falhar, fica pendente
para a próxima execução (nada é apagado). Ao final há um relatório de falhas e
retentativas.

**Pausa térmica** — acima de 78 °C a GPU é pausada e só retoma abaixo de 65 °C.

**Só consolida o que está completo** — um item vai para `6_Concluidos` apenas se
tiver transcrição **e** resumo.

**Interrupção** — saídas são gravadas em `.parcial` e renomeadas só no fim. Se a
execução for interrompida, apenas a saída da etapa em andamento é descartada;
vídeo, áudio e etapas já concluídas ficam.

## Entregáveis

```text
dados\6_Concluidos\Reuniao_ABC\
    Reuniao_ABC.mp4  Reuniao_ABC.mp3  Reuniao_ABC.txt
    Reuniao_ABC_diarizado.txt   (se houve diarização)
    Reuniao_ABC_resumo.txt      pipeline.log
```

## Pastas e logs

`dados\` contém `1_Videos`, `2_Audios`, `3_Transcricoes`, `4_Diarizacoes`,
`5_Logs`, `6_Concluidos`, `7_Perfis_Voz`, `8_Resumos`, `_portal` (execuções do
portal) e `_modelos`. Logs: `dados\5_Logs` (e cópia em cada entregável). Em
instalações antigas as pastas ficam direto na raiz (layout detectado sozinho;
`ferramentas\Migrar_para_dados.bat` move para `dados\`). Arquivos gerados
(pacote, modelo exportado) vão para `dist\`.

## Primeira execução

Demora mais: baixa modelos e cria caches (veja `docs/instalacao.md` se a rede
bloquear o download). Com GPU NVIDIA é muito mais rápido que CPU; com
`medium`/`large-v3` junto da diarização, acompanhe a VRAM — o `small` cabe com
folga numa placa de 4 GB.
