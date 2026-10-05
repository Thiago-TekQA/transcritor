"""Migra as pastas de trabalho do layout antigo (direto na raiz do projeto)
para a pasta dados/ — deixando a raiz limpa.

Move (mesmo disco, é só renomear; instantâneo e sem copiar nada):
  1_Videos … 8_Resumos, _portal, _modelos, perfis_voz.json

Uso (na raiz do projeto):
  python ferramentas\\migrar_para_dados.py              # só mostra o que faria
  python ferramentas\\migrar_para_dados.py --executar   # faz a migração

Segurança: não roda se houver pipeline/portal em execução, nem se dados/ já
tiver conteúdo; se algo falhar no meio, desfaz o que já tinha movido.
"""

import os
import sys

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

sys.path.insert(0, os.path.join(RAIZ, "src"))
sys.path.insert(0, os.path.join(RAIZ, "src", "portal"))

ITENS = [
    "1_Videos", "2_Audios", "3_Transcricoes", "4_Diarizacoes", "5_Logs",
    "6_Concluidos", "7_Perfis_Voz", "8_Resumos",
    "_portal", "_modelos", "perfis_voz.json",
]

DESTINO = os.path.join(RAIZ, "dados")


def itens_para_mover():

    return [i for i in ITENS if os.path.exists(os.path.join(RAIZ, i))]


def processos_em_uso():
    """Descrições dos pipelines/workers/portais em execução (vazio = livre)."""

    try:

        import processos

        mapa = processos.listar()

    except Exception as e:

        return [f"não consegui verificar os processos ({e})"]

    achados = []

    def percorrer(raizes):

        for r in raizes:

            if r["tipo"] in ("pipeline", "worker", "portal", "reparo", "ffmpeg") and not r["proprio"]:
                achados.append(f"{r['rotulo']} (PID {r['pid']})")

            percorrer(r["filhos"])

    percorrer(mapa["raizes"])

    return achados


def migrar(executar=False, verificar_processos=True):
    """Devolve (código de saída, mensagens)."""

    msgs = []

    mover = itens_para_mover()

    if not mover:
        return 0, ["Nada a migrar: não há pastas de trabalho na raiz."]

    if os.path.isdir(DESTINO) and os.listdir(DESTINO):
        return 1, [
            "A pasta dados/ já existe e não está vazia — nada foi feito.",
            "Mova o conteúdo dela manualmente ou apague-a se for sobra.",
        ]

    if verificar_processos:

        em_uso = processos_em_uso()

        if em_uso:
            return 1, ["Feche antes o que está em execução:"] + [f"  - {e}" for e in em_uso]

    msgs.append(f"Vai mover para {DESTINO}:")
    msgs += [f"  {i}" for i in mover]

    if not executar:
        msgs.append("")
        msgs.append("(simulação) Rode com --executar para migrar de verdade.")
        return 0, msgs

    os.makedirs(DESTINO, exist_ok=True)

    movidos = []

    try:

        for i in mover:

            os.replace(os.path.join(RAIZ, i), os.path.join(DESTINO, i))
            movidos.append(i)

    except OSError as e:

        # desfaz o que já tinha sido movido
        for i in reversed(movidos):

            try:
                os.replace(os.path.join(DESTINO, i), os.path.join(RAIZ, i))
            except OSError:
                pass

        return 1, msgs + [f"ERRO ao mover: {e}", "O que já tinha sido movido foi desfeito."]

    # a trava de execução única é recriada sozinha no novo lugar
    sobra = os.path.join(RAIZ, ".pipeline.lock")

    try:
        if os.path.exists(sobra):
            os.remove(sobra)
    except OSError:
        pass

    msgs.append("")
    msgs.append(f"Pronto: {len(movidos)} item(ns) movido(s) para dados/.")

    return 0, msgs


def main():

    codigo, msgs = migrar(executar="--executar" in sys.argv)

    print("\n".join(msgs))

    sys.exit(codigo)


if __name__ == "__main__":
    main()
