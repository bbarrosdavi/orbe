"""Orbes em paralelo no daemon, sem áudio nem agentes de verdade.

Dois orbes do Claude no live: o turno do primeiro segue em segundo plano
quando o relógio passa ao segundo, o do segundo também quando ele passa a um
terceiro, e as respostas esperam a vez na ordem de chegada; com o daemon livre,
cada uma toma o lugar (o relógio e o orbe do PC passam a ela) e fala com a voz
do orbe dela.

    ~/.local/share/orbe/.venv/bin/python -m unittest testes/test_paralelo.py
"""
import json
import os
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path

# config, sockets e caches num lugar descartável: nada do orbe instalado
_TMP = tempfile.mkdtemp(prefix="orbe-paralelo-")
for _v in ("XDG_CONFIG_HOME", "XDG_RUNTIME_DIR", "XDG_CACHE_HOME", "XDG_DATA_HOME"):
    os.environ[_v] = str(Path(_TMP) / _v.lower())
    Path(os.environ[_v]).mkdir(parents=True, exist_ok=True)
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import orbe_daemon as od      # noqa: E402
import orbe_relogio as rel    # noqa: E402


class AgenteFalso:
    """Responde [resposta] depois de [demora] segundos, palavra a palavra."""

    def __init__(self, nome: str, demora: float, resposta: str):
        self.nome, self.demora, self.resposta = nome, demora, resposta
        self.sessao = "sessao-" + nome
        self.fechado = False
        self.cancelado = False

    def perguntar(self, pedido, ao_texto, ao_pensamento, a_ferramenta, parar=None, teto=0.0, a_etapa=None):
        t0 = time.monotonic()
        while time.monotonic() - t0 < self.demora:
            if parar is not None and parar.is_set():
                self.cancelado = True
                return "cancelled"
            time.sleep(0.01)
        for palavra in self.resposta.split(" "):
            ao_texto(palavra + " ")
        return "end_turn"

    def vivo(self):
        return True

    def fechar(self):
        self.fechado = True


class PonteFalsa:
    """O que o daemon lê e manda à ponte do relógio; os satélites são os de verdade."""
    satelites = rel.PonteRelogio.satelites

    def __init__(self):
        self._agente, self._vaga, self._orbe = "claude", 0, ("ofanim", "")
        self._agentes = [{"id": "claude", "instancias": True}]
        # com os seis orbes do Claude, a vaga v é do orbe v % 6
        self._sessoes = [{"agente": "claude", "vaga": 0, "pid": 100}, {"agente": "claude", "vaga": 1, "pid": 101},
                         {"agente": "claude", "vaga": 3, "pid": 103}]
        self.focos, self.filas = [], []

    def ir(self, skin: str, vaga: int):
        """O relógio rolou até outro orbe."""
        self._orbe, self._vaga = (skin, ""), vaga

    def agente(self):
        return self._agente

    def vaga(self):
        return self._vaga

    def orbe(self):
        return self._orbe

    def sessao_da_vaga(self, vaga, tipo="claude"):
        return next((s["pid"] for s in self._sessoes if s["vaga"] == vaga and s["agente"] == tipo), 0)

    def focar(self, skin, agente, vaga, cor):
        self._orbe, self._vaga, self._agente = (skin, cor), vaga, agente
        self.focos.append((skin, vaga))

    def esperas(self, lista):
        self.filas.append([(e["skin"], e["vaga"]) for e in lista])

    def quer_voz(self):
        return False

    def conectado(self):
        return True

    def publicar(self, linha):
        pass


def daemon_falso(ponte: PonteFalsa, agentes: dict):
    """O Daemon sem o __init__ (microfone, VAD, TTS): só o estado que os turnos usam."""
    d = od.Daemon.__new__(od.Daemon)
    d.state, d.rec, d._processing_thread = "listening", None, None
    d._tts_playing, d._tts_gen, d._tts_turn_n = False, 0, 0
    d._interrupted = threading.Event()
    d.agente, d._agente_viva, d._agente_lock = None, "", threading.Lock()
    d._origem, d._espelho = "relogio", "espelho"
    d._turno, d._turnos_fundo, d._falas, d._falas_lock = None, [], [], threading.Lock()
    d._skin_falante, d._paralelo_t, d._satelites, d._esperas = "", 0.0, "", ""
    d.expecting_command = d.allow_interrupt = True
    d.speech_frames, d._continuando, d._pedido_aberto = 0, False, ""
    d._voice_session, d._instruido, d._agente_uso = "s", True, 0.0
    d.falado = []

    def pronto():
        with d._agente_lock:
            chave = d._agente_chave()
            if d.agente is None or d._agente_viva != chave:
                d.agente, d._agente_viva = agentes[(ponte._orbe[0], ponte._vaga)], chave
            return d.agente

    def push(texto, gen=None, etapa=False):
        d._tts_turn_n += 1
        d.falado.append((d._skin_falante, texto.strip()))
    d._agente_pronto = pronto
    d._tts_push = push
    d._tts_drain = d._tts_worker_warm = d._touch_session = d._abrir_mic = lambda *a, **k: None
    d._guardar_pedido = lambda *a, **k: None
    return d


class OrbesEmParalelo(unittest.TestCase):
    def setUp(self):
        self.ponte = PonteFalsa()
        self.ordens = []
        od._RELOGIO = self.ponte
        od.orb_cmd = lambda linha, relogio=True: self.ordens.append(linha)
        od.VCFG["relogio"]["seguir"] = True
        self.agentes = {("ofanim", 0): AgenteFalso("A", 0.6, "Resposta do Ophanim."),
                        ("ofanim_alado", 1): AgenteFalso("B", 0.9, "Resposta do alado."),
                        ("olho", 3): AgenteFalso("C", 1.6, "Resposta do olho.")}
        self.d = daemon_falso(self.ponte, self.agentes)

    def turno(self, pedido):
        """Como o _handle: o pedido vai ao agente do orbe em tela, num thread."""
        d = self.d
        d.state = "processing"
        d._processing_thread = threading.Thread(target=d._responder, args=(pedido, d._tts_gen), daemon=True)
        d._processing_thread.start()
        time.sleep(0.05)

    def tique(self, segundos):
        """O laço do daemon: fecha o turno que acabou e chama os orbes em paralelo."""
        fim = time.monotonic() + segundos
        while time.monotonic() < fim:
            d = self.d
            if d.state == "processing" and d._processing_thread and not d._processing_thread.is_alive():
                d._processing_thread, d.state = None, "listening"
            d._paralelo_t = 0.0
            d._orbes_paralelos()
            time.sleep(0.03)

    def test_turno_que_perde_o_foco_segue_e_as_respostas_esperam_a_vez(self):
        p, d = self.ponte, self.d
        self.turno("pedido ao Ophanim")
        p.ir("ofanim_alado", 1)                  # o relógio passa ao segundo orbe com o primeiro pensando
        self.tique(0.1)
        self.assertIsNone(d._processing_thread, "o turno do Ophanim devia ter ido para o fundo")
        self.turno("pedido ao alado")
        p.ir("olho", 3)                          # e a um terceiro, com o segundo pensando
        self.tique(0.1)
        self.turno("pedido ao olho")
        # A (0,6 s) e B (0,9 s) acabam com o olho ainda pensando: esperam, na ordem de chegada
        self.tique(1.0)
        self.assertEqual([("ofanim", 0), ("ofanim_alado", 1)], [(f["turno"]["skin"], f["turno"]["vaga"]) for f in d._falas])
        sat = {s["id"]: s["tipo"] for s in json.loads(d._satelites)}
        self.assertEqual("espera", sat["ofanim/0"])
        self.assertEqual("espera", sat["ofanim_alado/1"])
        self.assertNotIn("olho/3", sat, "o orbe em tela não é satélite")
        self.assertEqual("fantasma", sat["serafim_gravura"])
        self.assertIn([("ofanim", 0), ("ofanim_alado", 1)], p.filas)
        # o olho responde; depois cada um toma o lugar e fala com a voz dele
        self.tique(1.5)
        self.assertEqual([("olho", "Resposta do olho."), ("ofanim", "Resposta do Ophanim."),
                          ("ofanim_alado", "Resposta do alado.")], d.falado)
        self.assertEqual([("ofanim", 0), ("ofanim_alado", 1)], p.focos)
        self.assertIn("espelho ofanim -", self.ordens)
        self.assertIn("espelho ofanim_alado -", self.ordens)
        self.assertEqual([], p.filas[-1], "a fila esvaziou")
        # nenhum turno foi cancelado no caminho, e o último a falar ficou como agente da sessão
        self.assertFalse(any(a.cancelado for a in self.agentes.values()))
        self.assertIs(self.agentes[("ofanim_alado", 1)], d.agente)

    def test_fixo_o_principal_do_pc_nao_troca(self):
        """relogio.seguir desligado: o relógio rola até quem fala, o orbe do PC
        fica no dele, e quem sai da órbita é o do PC, não o em tela no relógio."""
        p, d = self.ponte, self.d
        skin_pc = od.VCFG["orbe"]["skin"]
        self.addCleanup(lambda: od.VCFG["orbe"].__setitem__("skin", skin_pc))
        od.VCFG["relogio"]["seguir"] = False
        od.VCFG["orbe"]["skin"] = "serafim_gravura"
        self.turno("pedido ao Ophanim")
        p.ir("olho", 3)                          # o relógio passa a outro orbe com o Ophanim pensando
        self.tique(0.1)
        self.turno("pedido ao olho")
        self.tique(2.5)
        self.assertEqual([("olho", "Resposta do olho."), ("ofanim", "Resposta do Ophanim.")], d.falado)
        self.assertEqual([("ofanim", 0)], p.focos, "o relógio rola até quem toma a vez")
        self.assertEqual([], [o for o in self.ordens if o.startswith("espelho ")], "fixo, o orbe do PC não troca")
        sat = {s["id"] for s in json.loads(d._satelites)}
        self.assertNotIn("serafim_gravura", sat, "o principal do PC não orbita")
        self.assertIn("olho/3", sat, "o em tela no relógio orbita o do PC")

    def test_seguindo_o_relogio_desconectar_nao_troca(self):
        """Seguindo o relógio, o orbe do PC é o último escolhido lá: o Wi-Fi do
        relógio dormir não devolve o PC ao orbe dele."""
        p, d = self.ponte, self.d
        p.ir("olho", 3)
        self.tique(0.1)
        self.assertEqual("espelho olho -", d._espelho)
        n = len(self.ordens)
        p.conectado = lambda: False
        self.tique(0.3)
        self.assertEqual("espelho olho -", d._espelho)
        self.assertEqual([], [o for o in self.ordens[n:] if o.startswith("espelho")])
        p.ir("ofanim_alado", 1)                  # de novo no ar, outro agente: aí troca
        p.conectado = lambda: True
        self.tique(0.1)
        self.assertEqual("espelho ofanim_alado -", d._espelho)

    def test_seguindo_o_relogio_o_pc_fala_com_o_agente_de_la(self):
        """A fala no microfone do PC vai para o agente escolhido no relógio
        (a vaga da instância) seguindo ele; fixo, para o agente do PC."""
        p, d = self.ponte, self.d
        d._origem = "pc"
        p.ir("olho", 3)
        self.assertEqual(3, d._agente_cfg()["vaga"])
        self.assertEqual(("olho", True), (d._orbe_em_foco()["skin"], d._orbe_em_foco()["do_relogio"]))
        od.VCFG["relogio"]["seguir"] = False
        self.assertEqual(-1, d._agente_cfg().get("vaga", -1))
        self.assertEqual((od.VCFG["orbe"]["skin"], False), (d._orbe_em_foco()["skin"], d._orbe_em_foco()["do_relogio"]))

    def test_mesmo_orbe_continua_interrompendo_como_antes(self):
        p, d = self.ponte, self.d
        self.turno("pedido ao Ophanim")
        self.tique(0.1)                          # o foco não mudou: nada vai para o fundo
        self.assertIsNotNone(d._processing_thread)
        d._interrupted.set()                     # o toque no mesmo orbe corta, como sempre
        self.tique(0.3)
        self.assertTrue(self.agentes[("ofanim", 0)].cancelado)
        self.assertEqual([], d._falas)


if __name__ == "__main__":
    unittest.main()
