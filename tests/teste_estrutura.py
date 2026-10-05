"""Garante que rodar o programa não espalha arquivos pela raiz do projeto.

Copia src/ para uma raiz temporária (como numa instalação nova), roda o pipeline
pela linha de comando e confere que tudo o que foi gerado foi parar em dados/.
Rodar (na raiz): python -m unittest discover tests
"""
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _copiar_src(destino):
    shutil.copytree(os.path.join(RAIZ, "src"), os.path.join(destino, "src"),
                    ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))


def _rodar_pipeline(raiz, *args):
    env = {**os.environ, "PYTHONUTF8": "1", "PYTHONDONTWRITEBYTECODE": "1"}
    env.pop("TRANSCRITOR_EVENTOS", None)
    env.pop("TRANSCRITOR_PARAR", None)
    return subprocess.run(
        [sys.executable, os.path.join(raiz, "src", "pipeline.py"), *args],
        cwd=raiz, env=env, capture_output=True, text=True, encoding="utf-8",
        errors="replace", timeout=120)


class TesteEstrutura(unittest.TestCase):

    def setUp(self):
        self.raiz = tempfile.mkdtemp(prefix="estrutura_")
        _copiar_src(self.raiz)
        self.addCleanup(shutil.rmtree, self.raiz, True)

    def _raiz_sem_src(self):
        return sorted(os.listdir(self.raiz))

    def test_instalacao_nova_usa_dados(self):
        r = _rodar_pipeline(self.raiz, "--etapas", "mp3")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(self._raiz_sem_src(), ["dados", "src"],
                         "a execução deixou algo na raiz do projeto")
        self.assertTrue(os.path.isdir(os.path.join(self.raiz, "dados", "6_Concluidos")))

    def test_nao_gera_bytecode_na_arvore(self):
        _rodar_pipeline(self.raiz, "--etapas", "mp3")
        achados = [os.path.join(r, d) for r, ds, _ in os.walk(self.raiz) for d in ds if d == "__pycache__"]
        self.assertEqual(achados, [])

    def test_layout_antigo_continua_funcionando(self):
        # quem ainda tem as pastas na raiz não deve ganhar uma dados/ vazia ao lado
        os.makedirs(os.path.join(self.raiz, "6_Concluidos"))
        r = _rodar_pipeline(self.raiz, "--etapas", "mp3")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertNotIn("dados", self._raiz_sem_src())
        self.assertTrue(os.path.isdir(os.path.join(self.raiz, "1_Videos")))

    def test_pacote_nao_inclui_artefatos_nem_segredos(self):
        import zipfile
        pacote = os.path.join(RAIZ, "dist", "Transcritor_pacote.zip")
        if not os.path.exists(pacote):
            self.skipTest("pacote ainda não gerado (ferramentas/gerar_pacote.py)")
        with zipfile.ZipFile(pacote) as z:
            nomes = z.namelist()
        proibidos = [n for n in nomes
                     if n.endswith(("config.json", ".zip", ".log", ".parcial"))
                     or "__pycache__" in n or n.startswith(("dados/", "dist/", ".venv/", "tests/"))]
        self.assertEqual(proibidos, [])


if __name__ == "__main__":
    unittest.main()
