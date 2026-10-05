"""Testes do estado (reducer) e do planejamento. Rodar: python -m unittest portal.teste_portal"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import execucoes as ex  # noqa: E402

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


class TesteNomes(unittest.TestCase):

    def test_resultado_rejeita_caminhos(self):
        for ruim in ("..", "a/b", r"a\b", "", "x:y"):
            self.assertIsNone(ex.caminho_arquivo(ruim, "resumo", "concluidos"))

    def test_id_de_execucao_so_digitos(self):
        self.assertIsNone(ex.pasta_execucao(r"..\..\x"))
        self.assertIsNone(ex.pasta_execucao("2026abc"))


if __name__ == "__main__":
    unittest.main()
