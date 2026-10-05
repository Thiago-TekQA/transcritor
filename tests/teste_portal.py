"""Testes do estado (reducer) e do planejamento. Rodar (na raiz): python -m unittest discover tests"""
import os
import sys
import unittest

_SRC = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src")
sys.path.insert(0, _SRC)
sys.path.insert(0, os.path.join(_SRC, "portal"))

import execucoes as ex  # noqa: E402
import pipeline_config as cfg  # noqa: E402
import shutil  # noqa: E402
import tempfile  # noqa: E402

PARAMS = {
    "id": "20260101_000000",
    "etapas": ["mp3", "transcricao", "resumo"],
    "itens": [
        {"nome": "a", "tamanho": 1, "estagios": {"mp3": "executar", "transcricao": "executar", "resumo": "executar"}},
        {"nome": "b", "tamanho": 1, "estagios": {"mp3": "pular", "transcricao": "executar", "resumo": "executar"}},
    ],
}


def ev(tipo, **c):
    return {"ev": tipo, **c}


class TesteEstado(unittest.TestCase):

    def test_estado_inicial_e_pulos_planejados(self):
        s = ex.dobrar_eventos(PARAMS, [])
        self.assertEqual(s["estado_run"], "preparando")
        self.assertEqual(s["itens"]["a"]["etapas"]["mp3"]["estado"], "pendente")
        self.assertEqual(s["itens"]["b"]["etapas"]["mp3"]["estado"], "pulado")

    def test_fluxo_completo(self):
        eventos = [
            ev("run_inicio", device="cuda", pid=1),
            ev("fase_inicio", etapa="mp3"),
            ev("item", etapa="mp3", nome="a", estado="rodando"),
            ev("item", etapa="mp3", nome="a", estado="ok", dur=1.5),
            ev("fase_fim", etapa="mp3"),
            ev("item", etapa="transcricao", nome="a", estado="rodando", dispositivo="cuda"),
            ev("progresso", etapa="transcricao", nome="a", pct=40),
            ev("item", etapa="transcricao", nome="a", estado="aguardando_cpu", motivo="código 1"),
            ev("item", etapa="transcricao", nome="a", estado="rodando", dispositivo="cpu", tentativa=2),
            ev("item", etapa="transcricao", nome="a", estado="ok", nota="recuperado_cpu"),
            ev("run_fim", resultado="com_falhas", falhas=[{"etapa": "transcricao", "arquivo": "a", "resultado": "x"}]),
        ]
        s = ex.dobrar_eventos(PARAMS, eventos)
        self.assertEqual(s["estado_run"], "concluida_com_falhas")
        self.assertEqual(s["itens"]["a"]["etapas"]["mp3"]["dur"], 1.5)
        self.assertEqual(s["itens"]["a"]["etapas"]["transcricao"]["nota"], "recuperado_cpu")
        # nada fica "pendente" depois de terminar
        self.assertEqual(s["itens"]["b"]["etapas"]["resumo"]["estado"], "nao_executado")
        self.assertEqual(len(s["falhas"]), 1)

    def test_cancelamento_nao_deixa_rodando(self):
        eventos = [
            ev("run_inicio"),
            ev("item", etapa="transcricao", nome="a", estado="rodando"),
            ev("cancelado", modo="duro"),
            ev("run_fim", resultado="cancelada", falhas=[]),
        ]
        s = ex.dobrar_eventos(PARAMS, eventos)
        self.assertEqual(s["estado_run"], "cancelada")
        self.assertEqual(s["itens"]["a"]["etapas"]["transcricao"]["estado"], "cancelado")

    def test_parada_suave_marca_nao_executado(self):
        eventos = [
            ev("run_inicio"),
            ev("cancelado", modo="suave"),
            ev("fase_fim", etapa="transcricao"),
        ]
        s = ex.dobrar_eventos(PARAMS, eventos)
        self.assertEqual(s["itens"]["a"]["etapas"]["transcricao"]["estado"], "nao_executado")

    def test_pausa_termica_e_ollama(self):
        s = ex.dobrar_eventos(PARAMS, [
            ev("pausa_termica", estado="inicio", temp=81, retomar_abaixo=65),
            ev("ollama", estado="iniciado_por_nos"),
        ])
        self.assertEqual(s["pausa_termica"]["temp"], 81)
        self.assertEqual(s["ollama"], "iniciado_por_nos")
        s = ex.dobrar_eventos(PARAMS, [ev("pausa_termica", estado="inicio", temp=81), ev("pausa_termica", estado="fim")])
        self.assertIsNone(s["pausa_termica"])


class TesteLimpeza(unittest.TestCase):
    """Interrupção: só a saída da etapa em andamento some; vídeo/áudio ficam."""

    CAMPOS = ("VIDEOS_DIR", "AUDIOS_DIR", "TRANS_DIR", "DIARIZ_DIR", "RESUMOS_DIR", "DONE_DIR")

    def setUp(self):
        self.base = tempfile.mkdtemp(prefix="teste_limpeza_")
        self.orig = {c: getattr(cfg, c) for c in self.CAMPOS}
        for c in self.CAMPOS:
            pasta = os.path.join(self.base, c)
            os.makedirs(pasta)
            setattr(cfg, c, pasta)

    def tearDown(self):
        for c, v in self.orig.items():
            setattr(cfg, c, v)
        shutil.rmtree(self.base, ignore_errors=True)

    def _criar(self, pasta, nome, conteudo="x"):
        caminho = os.path.join(getattr(cfg, pasta), nome)
        with open(caminho, "w") as f:
            f.write(conteudo)
        return caminho

    def test_transcricao_interrompida_mantem_video_e_audio(self):
        video = self._criar("VIDEOS_DIR", "a.mp4")
        audio = self._criar("AUDIOS_DIR", "a.mp3")
        parcial = self._criar("TRANS_DIR", "a.txt.parcial")
        eventos = []
        removidos, falhas = cfg.limpar_interrompidos(eventos.append)
        self.assertEqual(falhas, 0)
        self.assertFalse(os.path.exists(parcial))
        self.assertTrue(os.path.exists(video) and os.path.exists(audio))
        self.assertEqual(eventos, [{"etapa": "transcricao", "nome": "a", "arquivo": "a.txt.parcial"}])

    def test_cada_etapa_e_classificada(self):
        self._criar("AUDIOS_DIR", "b.mp3.parcial")
        self._criar("DIARIZ_DIR", "b_diarizado.txt.parcial")
        self._criar("RESUMOS_DIR", "b_resumo.txt.parcial")
        self._criar("VIDEOS_DIR", "b.mp4.copiando")
        removidos, _ = cfg.limpar_interrompidos()
        self.assertEqual(
            sorted((r["etapa"], r["nome"]) for r in removidos),
            [("copiar", "b"), ("diarizacao", "b"), ("mp3", "b"), ("resumo", "b")],
        )

    def test_nao_toca_em_saidas_completas(self):
        txt = self._criar("TRANS_DIR", "c.txt")
        resumo = self._criar("RESUMOS_DIR", "c_resumo.txt")
        removidos, _ = cfg.limpar_interrompidos()
        self.assertEqual(removidos, [])
        self.assertTrue(os.path.exists(txt) and os.path.exists(resumo))

    def test_consolidacao_interrompida_volta_ao_lugar(self):
        # estado deixado por uma consolidação morta no meio: vídeo e mp3 já
        # estavam na pasta de montagem, a transcrição ainda não foi movida
        montagem = os.path.join(cfg.DONE_DIR, "d.parcial")
        os.makedirs(montagem)
        with open(os.path.join(montagem, "d.mp4"), "w") as f:
            f.write("v")
        with open(os.path.join(montagem, "d.mp3"), "w") as f:
            f.write("a")
        with open(os.path.join(montagem, "d_resumo.txt"), "w") as f:
            f.write("r")
        with open(os.path.join(montagem, "pipeline.log"), "w") as f:
            f.write("l")
        with open(os.path.join(montagem, cfg.MANIFESTO_CONSOLIDACAO), "w") as f:
            f.write('{"d.mp4": %s, "d.mp3": %s}' % (
                repr(cfg.VIDEOS_DIR).replace("'", '"').replace("\\", "\\\\"),
                repr(cfg.AUDIOS_DIR).replace("'", '"').replace("\\", "\\\\")))
        removidos, falhas = cfg.limpar_interrompidos()
        self.assertEqual(falhas, 0)
        self.assertFalse(os.path.exists(montagem))
        self.assertTrue(os.path.exists(os.path.join(cfg.VIDEOS_DIR, "d.mp4")))
        self.assertTrue(os.path.exists(os.path.join(cfg.AUDIOS_DIR, "d.mp3")))
        # cópias de resumo/log são descartadas; a pasta final não existe
        self.assertFalse(os.path.exists(os.path.join(cfg.DONE_DIR, "d")))
        self.assertEqual(removidos, [{"etapa": "consolidar", "nome": "d", "arquivo": "d.parcial"}])

    def test_consolidacao_sem_manifesto_usa_regras_padrao(self):
        montagem = os.path.join(cfg.DONE_DIR, "e.parcial")
        os.makedirs(montagem)
        for nome in ("e.mp4", "e.mp3", "e.txt", "e_diarizado.txt"):
            with open(os.path.join(montagem, nome), "w") as f:
                f.write("x")
        cfg.limpar_interrompidos()
        self.assertTrue(os.path.exists(os.path.join(cfg.VIDEOS_DIR, "e.mp4")))
        self.assertTrue(os.path.exists(os.path.join(cfg.AUDIOS_DIR, "e.mp3")))
        self.assertTrue(os.path.exists(os.path.join(cfg.TRANS_DIR, "e.txt")))
        self.assertTrue(os.path.exists(os.path.join(cfg.DIARIZ_DIR, "e_diarizado.txt")))

    def test_evento_limpeza_aparece_no_estado(self):
        s = ex.dobrar_eventos(PARAMS, [ev("limpeza", etapa="transcricao", nome="a", arquivo="a.txt.parcial")])
        self.assertEqual(s["limpezas"], [{"etapa": "transcricao", "nome": "a", "arquivo": "a.txt.parcial"}])


class TesteParados(unittest.TestCase):
    """Itens que ficaram a meio caminho na área de trabalho."""

    CAMPOS = ("VIDEOS_DIR", "AUDIOS_DIR", "TRANS_DIR", "DIARIZ_DIR", "RESUMOS_DIR", "DONE_DIR")

    def setUp(self):
        self.base = tempfile.mkdtemp(prefix="teste_parados_")
        self.orig = {c: getattr(cfg, c) for c in self.CAMPOS}
        self.orig_exec = ex.EXECUCOES_DIR
        for c in self.CAMPOS:
            pasta = os.path.join(self.base, c)
            os.makedirs(pasta)
            setattr(cfg, c, pasta)
        ex.EXECUCOES_DIR = os.path.join(self.base, "execucoes")

    def tearDown(self):
        for c, v in self.orig.items():
            setattr(cfg, c, v)
        ex.EXECUCOES_DIR = self.orig_exec
        shutil.rmtree(self.base, ignore_errors=True)

    def _criar(self, pasta, nome):
        with open(os.path.join(getattr(cfg, pasta), nome), "w") as f:
            f.write("x")

    def test_lista_o_que_ja_existe_de_cada_item(self):
        self._criar("VIDEOS_DIR", "a.mp4")
        self._criar("AUDIOS_DIR", "a.mp3")
        self._criar("TRANS_DIR", "a.txt")
        parados = ex.listar_parados()
        self.assertEqual([p["nome"] for p in parados], ["a"])
        self.assertEqual(parados[0]["feitas"], ["vídeo/áudio original", "áudio (mp3)", "transcrição"])
        self.assertIsNone(parados[0]["parou"])  # nenhuma execução do portal o tocou

    def test_concluido_parcial_e_copiando_nao_entram(self):
        os.makedirs(os.path.join(cfg.DONE_DIR, "b"))
        self._criar("RESUMOS_DIR", "b_resumo.txt")      # cópia permanente de um concluído
        self._criar("AUDIOS_DIR", "c.mp3.parcial")      # saída incompleta
        self._criar("VIDEOS_DIR", "d.mp4.copiando")     # cópia incompleta
        self.assertEqual(ex.listar_parados(), [])

    def test_transcricao_nao_se_confunde_com_resumo_nem_diarizacao(self):
        self._criar("TRANS_DIR", "e.txt")
        self._criar("DIARIZ_DIR", "e_diarizado.txt")
        self._criar("RESUMOS_DIR", "e_resumo.txt")
        (p,) = ex.listar_parados()
        self.assertEqual(p["feitas"], ["transcrição", "diarização", "resumo"])

    def test_plano_sem_pasta_de_origem_traz_so_os_parados(self):
        self._criar("VIDEOS_DIR", "a.mp4")
        self._criar("AUDIOS_DIR", "a.mp3")
        self._criar("TRANS_DIR", "a.txt")
        plano = ex.planejar("", ["mp3", "transcricao", "resumo", "consolidar"])
        self.assertEqual(plano["itens"], [])
        (p,) = plano["parados"]
        est = p["estagios"]
        self.assertEqual(est["mp3"]["acao"], "pular")
        self.assertEqual(est["transcricao"]["acao"], "pular")
        self.assertEqual(est["resumo"]["acao"], "executar")
        self.assertEqual(est["consolidar"]["acao"], "executar")
        self.assertIsNone(p["copiar"])  # já está na área de trabalho

    def test_parado_so_com_audio_pode_continuar(self):
        self._criar("AUDIOS_DIR", "f.mp3")
        plano = ex.planejar("", ["transcricao", "resumo"])
        (p,) = plano["parados"]
        self.assertEqual(p["estagios"]["transcricao"]["acao"], "executar")
        self.assertEqual(p["estagios"]["resumo"]["acao"], "executar")

    def test_etapa_sem_pre_requisito_aparece_bloqueada(self):
        self._criar("VIDEOS_DIR", "g.mp4")
        plano = ex.planejar("", ["resumo"])
        (p,) = plano["parados"]
        self.assertEqual(p["estagios"]["resumo"]["acao"], "bloqueado")

    def test_mesmo_nome_da_origem_aparece_uma_vez_so(self):
        self._criar("VIDEOS_DIR", "a.mp4")
        origem = os.path.join(self.base, "origem")
        os.makedirs(origem)
        with open(os.path.join(origem, "a.mp4"), "w") as f:
            f.write("x")
        plano = ex.planejar(origem, ["mp3"])
        self.assertEqual([i["nome"] for i in plano["itens"]], ["a"])
        self.assertEqual(plano["parados"], [])

    def test_origem_invalida_continua_dando_erro(self):
        with self.assertRaises(ValueError):
            ex.planejar(os.path.join(self.base, "nao_existe"), ["mp3"])


class TesteNomes(unittest.TestCase):

    def test_resultado_rejeita_caminhos(self):
        for ruim in ("..", "a/b", r"a\b", "", "x:y"):
            self.assertIsNone(ex.caminho_arquivo(ruim, "resumo", "concluidos"))

    def test_id_de_execucao_so_digitos(self):
        self.assertIsNone(ex.pasta_execucao(r"..\..\x"))
        self.assertIsNone(ex.pasta_execucao("2026abc"))


if __name__ == "__main__":
    unittest.main()
