"""Compila os lançadores com ícone da raiz: "Instalar Transcritor.exe" e
"Transcritor.exe" (cada um só chama o .bat correspondente, ao lado dele).

Usa o compilador C# que já vem no Windows (.NET Framework 4), sem instalar
nada. Os .exe gerados são versionados e vão no pacote; só é preciso rodar
isto de novo se o lancador.cs ou os ícones mudarem.
"""

import glob
import os
import subprocess
import sys

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FONTE = os.path.join(RAIZ, "ferramentas", "lancador.cs")

# (arquivo gerado, ícone, símbolo de compilação, tipo)
# exe = com janela de console (o instalador mostra o progresso nela);
# winexe = sem janela (o portal roda em segundo plano).
LANCADORES = [
    ("Instalar Transcritor.exe", "icone_instalar.ico", "INSTALAR", "exe"),
    ("Transcritor.exe", "icone.ico", "PORTAL", "winexe"),
]


def achar_csc():
    base = os.path.join(os.environ.get("WINDIR", r"C:\Windows"), "Microsoft.NET")
    for framework in ("Framework64", "Framework"):
        achados = sorted(glob.glob(os.path.join(base, framework, "v4*", "csc.exe")))
        if achados:
            return achados[-1]
    return None


def main():

    csc = achar_csc()

    if not csc:
        print("Compilador C# (.NET Framework 4) não encontrado.")
        sys.exit(1)

    for nome, icone, simbolo, tipo in LANCADORES:

        saida = os.path.join(RAIZ, nome)

        r = subprocess.run([
            csc, "/nologo", f"/target:{tipo}", "/optimize+", "/platform:anycpu",
            "/codepage:65001",
            f"/define:{simbolo}",
            f"/win32icon:{os.path.join(RAIZ, 'assets', icone)}",
            f"/out:{saida}", FONTE,
        ])

        if r.returncode != 0:
            print(f"ERRO ao compilar {nome}.")
            sys.exit(1)

        print(f"Gerado: {saida}")


if __name__ == "__main__":
    main()
