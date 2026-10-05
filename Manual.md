# Comandos do Pipeline de Transcrição

## Atalho rápido (duplo clique)

Pra rodar o pipeline sem abrir terminal, dá dois cliques em:

```text
X:\Transcricao\Executar Pipeline.lnk
```

Ele já roda com `--modo simples --modelo small --device cuda` (GPU), entra
sozinho na pasta certa e mantém a janela aberta no final pra você ver o
resultado (ou o erro, se der algum). O ícone customizado é o
[pipeline_icone.ico](pipeline_icone.ico); o `.bat` por trás dele é o
[Executar Pipeline.bat](Executar%20Pipeline.bat), caso queira editar os
parâmetros padrão.

Os comandos abaixo continuam valendo — o atalho é só uma forma mais rápida
de disparar o `--modo simples` padrão.

---

## Execução padrão (sem diarização)

Executa:

* geração de MP3
* transcrição simples
* resumo/ata
* consolidação de entregáveis
* limpeza

**Não executa diarização** — desde que os perfis de voz ainda não estão
cadastrados, a diarização só produz rótulos genéricos (`SPEAKER_00`,
`SPEAKER_01`...) que às vezes trocam de pessoa, e o resumo/ata não depende
dela pra funcionar bem (ele raciocina sobre o conteúdo da fala, não sobre
o rótulo de quem falou). Isso deixa o processamento mais rápido e evita o
ponto mais pesado/arriscado do pipeline. Quando os perfis de voz forem
cadastrados (ver seção "Cadastrar perfis de voz"), vale voltar a usar o
`--modo completo` pra ter diarização com nomes reais.

```bash
python pipeline_transcricao_reestruturado.py
```
ou
```bash
python pipeline_transcricao_reestruturado.py --modo simples
```

---

# Modos de execução

## 1. Pipeline completo (com diarização)

Executa todas as etapas, incluindo diarização. Use quando quiser saber
quem falou o quê — mais lento e é a etapa historicamente mais sujeita a
falha nativa/CUDA em reuniões longas (já mitigado com isolamento por
processo, mas ainda a etapa mais pesada).

```bash
python pipeline_transcricao_reestruturado.py --modo completo
```

---

## 2. Somente transcrição simples (padrão)

Executa:

* geração de MP3
* transcrição simples
* resumo/ata
* consolidação de entregáveis
* limpeza

Não executa diarização. É o modo padrão — ver "Execução padrão" acima.

```bash
python pipeline_transcricao_reestruturado.py --modo simples
```

---

## 3. Somente gerar MP3

Executa apenas:

* extração de áudio

```bash
python pipeline_transcricao_reestruturado.py --modo somente_mp3
```

---

## 4. Somente transcrição

Executa apenas:

* transcrição simples

Requer arquivos de áudio já existentes em (`.mp3` ou qualquer formato da lista em "Formatos aceitos"):

```text
2_Audios
```

```bash
python pipeline_transcricao_reestruturado.py --modo somente_transcricao
```

---

## 5. Somente diarização

Executa apenas:

* diarização

Requer arquivos de áudio já existentes em (`.mp3` ou qualquer formato da lista em "Formatos aceitos"):

```text
2_Audios
```

```bash
python pipeline_transcricao_reestruturado.py --modo diarizacao
```

---

## 6. Cadastrar perfis de voz

Executa apenas:

* leitura das amostras de voz em `7_Perfis_Voz\<Nome>\`
* geração/atualização do arquivo `perfis_voz.json` com a "voz de referência" de cada pessoa cadastrada

Não processa vídeos nem áudios da fila normal.

```bash
python pipeline_transcricao_reestruturado.py --modo perfis_voz
```

Como cadastrar uma pessoa:

1. Crie uma subpasta com o nome dela dentro de `7_Perfis_Voz` (ex.: `7_Perfis_Voz\Thiago\`).
2. Coloque ali dentro 2 a 4 amostras de 15-30s dessa pessoa falando (áudio ou vídeo, de preferência sem outras vozes junto).
3. Rode o comando acima.

A partir daí, toda diarização (`completo` ou `diarizacao`) passa a comparar
automaticamente cada falante detectado contra os perfis cadastrados. Quando a
confiança é suficiente, o rótulo genérico (`SPEAKER_00`) é substituído pelo
nome real da pessoa no `_diarizado.txt`. Quando não bate com ninguém
cadastrado, mantém o rótulo genérico normalmente.

---

## 7. Gerar resumo/ata

Executa apenas:

* geração do resumo em `8_Resumos\<nome>_resumo.txt`, a partir da transcrição já existente

Roda automaticamente também dentro de `completo` e `simples` (depois da
transcrição/diarização terminarem). Usa o `_diarizado.txt` como fonte quando
existe, senão cai para o `.txt` simples.

```bash
python pipeline_transcricao_reestruturado.py --modo resumo
```

Requer o **Ollama** instalado e rodando localmente
(`http://localhost:11434`), com o modelo `qwen2.5:7b-instruct` baixado
(`ollama pull qwen2.5:7b-instruct`). Roda 100% na máquina — nenhum dado da
transcrição sai para serviço externo. Se o Ollama não estiver rodando,
essa fase registra erro no log e o resto do pipeline segue normalmente.

O resumo gerado tem estas seções: Resumo, Conclusões, TO-DOs e Pessoas
citadas. Por rodar num modelo pequeno (pra caber na GPU de 4GB desta
máquina), vale conferir o resumo contra a transcrição em decisões
importantes — não é 100% confiável em atribuir responsável às tarefas.

Transcrições muito longas (~12000 caracteres pra cima) são divididas em
blocos automaticamente antes de resumir, e depois consolidadas num resumo
final — o modelo local tem um teto de contexto (32768 tokens) que
reuniões longas ultrapassam facilmente. Isso deixa o processo mais lento
pra reuniões longas (uma reunião de ~1h20 chegou a levar ~40min só nessa
etapa), mas evita o problema de sair em inglês/fora do formato quando o
contexto estoura.

O resumo fica salvo em **dois lugares de propósito**: uma cópia dentro da
pasta do job em `6_Concluidos` (junto com os outros entregáveis) e o
original permanece em `8_Resumos` — essa pasta não é apagada pela
limpeza automática, justamente pra dar acesso rápido a todos os resumos
num lugar só, sem precisar entrar pasta por pasta.

Se algum resumo sair quebrado (formato errado, idioma errado) depois que
o job já foi movido pra `6_Concluidos`, use o script de reparo — ele só
gera o que estiver faltando, sem mexer no que já está correto:

```bash
python regenerar_resumos.py
```

---

# Modelos

## Alterar modelo Whisper

Exemplo usando modelo small:

```bash
python pipeline_transcricao_reestruturado.py --modelo small
```

Exemplo usando modelo medium:

```bash
python pipeline_transcricao_reestruturado.py --modelo medium
```

Exemplo usando modelo large-v3:

```bash
python pipeline_transcricao_reestruturado.py --modelo large-v3
```

---

# Device

O padrão do script é `cuda` (GPU) — não precisa passar `--device cuda`
explicitamente, já roda na GPU mesmo sem informar nada.

## Rodar em CUDA (GPU NVIDIA) — padrão

```bash
python pipeline_transcricao_reestruturado.py
```
ou, se preferir deixar explícito:
```bash
python pipeline_transcricao_reestruturado.py --device cuda
```

---

## Forçar CPU

Só necessário se quiser rodar sem GPU por algum motivo (ex.: GPU ocupada
com outra coisa):

```bash
python pipeline_transcricao_reestruturado.py --device cpu
```

---

# Exemplos completos

## Completo usando CPU

```bash
python pipeline_transcricao_reestruturado.py --modo completo --modelo medium --device cpu
```

---

## Completo usando GPU NVIDIA

```bash
python pipeline_transcricao_reestruturado.py --modo completo --modelo medium --device cuda
```

---

## Somente transcrição usando modelo small

```bash
python pipeline_transcricao_reestruturado.py --modo simples --modelo small
```

---

## Apenas gerar MP3

```bash
python pipeline_transcricao_reestruturado.py --modo somente_mp3
```

---

## Apenas diarização

```bash
python pipeline_transcricao_reestruturado.py --modo diarizacao --device cpu
```

---

# Estrutura esperada

```text
X:\Transcricao

├── 1_Videos
├── 2_Audios
├── 3_Transcricoes
├── 4_Diarizacoes
├── 5_Logs
├── 6_Concluidos
├── 7_Perfis_Voz
├── 8_Resumos
├── perfis_voz.json          (gerado pelo --modo perfis_voz)
├── Executar Pipeline.bat / .lnk
```

---

# Formatos aceitos

Vídeo ou áudio, tanto faz — o pipeline aceita:

```text
.mp4  .mkv  .avi  .mov
.ogg  .wav  .m4a  .aac  .flac
```

Duas formas de usar:

* **Vídeo ou áudio em `1_Videos`** (recomendado, fluxo padrão): passa pela
  extração/conversão da FASE 1 normalmente antes de seguir pro resto.
* **Áudio direto em `2_Audios`** (atalho): pula a FASE 1, vai direto pra
  transcrição/diarização. Útil pra áudio que já chega pronto (ex.: nota de
  voz do WhatsApp), sem precisar passar por conversão.

Nos dois casos o resultado final e a consolidação em `6_Concluidos`
funcionam igual.

---

# Fluxo do pipeline

## Pipeline completo

```text
1. Detecta vídeos/áudios novos
2. Extrai TODOS os MP3 (o que veio de 1_Videos)
3. Gera TODAS transcrições simples
4. Gera TODAS diarizações
   - usa o áudio do vídeo original quando existe (evita recomprimir)
   - compara cada falante contra os perfis de voz cadastrados
5. Gera TODOS os resumos/ata (via Ollama local)
6. Cria pasta final do job
7. Move entregáveis
8. Gera log final
9. Limpa temporários
```

---

# Regras importantes

## Skip automático

O pipeline ignora automaticamente:

* MP3 já existentes
* transcrições já existentes
* diarizações já existentes
* resumos já existentes

---

## Recuperação de falha nativa/CUDA (crash isolado)

Transcrição e diarização rodam cada uma isolada num processo separado por
arquivo. Isso existe porque, ocasionalmente, o driver CUDA/ctranslate2 tem
uma falha nativa (fora do alcance de qualquer `try/except` em Python) —
sem isso, um arquivo problemático derrubava o pipeline inteiro.

Quando isso acontece hoje:

1. O processo isolado daquele arquivo morre, o pipeline principal detecta
   pelo código de saída e segue pro próximo arquivo normalmente.
2. Se estava rodando em GPU (`--device cuda`), o arquivo que falhou é
   guardado e, **depois que todos os outros terminarem**, o pipeline
   tenta esse(s) arquivo(s) de novo, mas forçando `--device cpu` — mais
   lento, porém sem o risco de falha nativa da GPU.
3. Se ainda assim falhar na CPU, o arquivo fica pendente (mp3/vídeo
   preservados em `1_Videos`/`2_Audios`, nada é apagado) pra ser
   tentado de novo automaticamente na próxima execução.

Um arquivo só é considerado "concluído" (movido pra `6_Concluidos`) se a
transcrição dele realmente existir — falha isolada não move nada
incompleto pra lá.

---

## Entregáveis finais

Cada vídeo gera uma pasta própria dentro de:

```text
6_Concluidos
```

Exemplo:

```text
6_Concluidos
    └── Reuniao_ABC
            ├── Reuniao_ABC.mp4
            ├── Reuniao_ABC.mp3
            ├── Reuniao_ABC.txt
            ├── Reuniao_ABC_diarizado.txt
            ├── Reuniao_ABC_resumo.txt
            └── pipeline.log
```

No `_diarizado.txt`, o falante aparece como `SPEAKER_00`, `SPEAKER_01` etc.
por padrão — ou com o nome real, se a pessoa estiver cadastrada em
`7_Perfis_Voz` (ver seção "Cadastrar perfis de voz").

O `_resumo.txt` só é gerado se o Ollama estiver rodando no momento do
processamento (ver seção "Gerar resumo/ata").

---

# Observações

## Primeira execução

A primeira execução pode demorar bastante porque:

* modelos serão baixados
* cache será criado
* diarização baixa modelos grandes

---

## Performance esperada

### CPU

Mais lento.

### GPU NVIDIA CUDA

Muito mais rápido. É o modo padrão do atalho de duplo clique — já testado
e configurado nesta máquina (GTX 1650, 4GB VRAM). Com modelos maiores
(`medium`/`large-v3`) rodando junto com diarização, fique de olho no uso
de VRAM pelo Gerenciador de Tarefas; se faltar memória, o modelo `small`
é o que já sabemos que cabe com folga.

---

# Logs

Os logs são gerados em:

```text
5_Logs
```

E copiados para cada entregável final.
