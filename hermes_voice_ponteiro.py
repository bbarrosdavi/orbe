"""Posição global do ponteiro no niri, para os olhos do orbe.

O Wayland só informa o ponteiro a quem está debaixo dele, e o niri não tem
consulta de posição. Este módulo lê os dispositivos de apontar em /dev/input
(o usuário está no grupo input; teclados nunca são abertos):

- caneta e tela de toque: coordenadas absolutas, mapeadas no eDP-1 com a mesma
  transformação do niri (exato);
- touchpad e mouse: deslocamentos relativos com aceleração aproximada
  (estimativa). Corrige ao bater nas bordas da tela e quando o ponteiro passa
  sobre o orbe (âncora exata, que também recalibra o ganho).

Só a stdlib; um fio de leitura com select, acordado apenas por eventos.
"""
from __future__ import annotations

import fcntl
import json
import math
import os
import select
import struct
import subprocess
import threading
import time

EV_SYN, EV_KEY, EV_REL, EV_ABS = 0, 1, 2, 3
SYN_REPORT, SYN_DROPPED = 0, 3
REL_X, REL_Y = 0, 1
ABS_X, ABS_Y = 0, 1
BTN_TOOL_PEN, BTN_TOOL_FINGER, BTN_TOUCH = 0x140, 0x145, 0x14A
BTN_TOOL_DOUBLETAP, BTN_TOOL_TRIPLETAP = 0x14D, 0x14E
PROP_POINTER, PROP_DIRECT = 0, 1
EVENTO = struct.Struct("llHHi")
SAIDA_TOQUE = "eDP-1"      # map-to-output da caneta e do toque no config do niri


def _bits(hexa: str) -> set[int]:
    """Bitmap de /proc/bus/input/devices (palavras longas, a mais alta antes)."""
    out = set()
    for i, palavra in enumerate(reversed(hexa.split())):
        v = int(palavra, 16)
        b = 0
        while v:
            if v & 1:
                out.add(i * 64 + b)
            v >>= 1
            b += 1
    return out


def _absinfo(fd: int, eixo: int) -> tuple[int, int, int]:
    """(mínimo, máximo, resolução em unidades/mm) via EVIOCGABS."""
    req = (2 << 30) | (24 << 16) | (ord("E") << 8) | (0x40 + eixo)
    buf = bytearray(24)
    fcntl.ioctl(fd, req, buf)
    _v, lo, hi, _fz, _fl, res = struct.unpack("6i", buf)
    return lo, hi, res


def _dispositivos() -> list[dict]:
    achados, cur = [], {}
    try:
        texto = open("/proc/bus/input/devices").read()
    except OSError:
        return []
    for linha in texto.splitlines() + [""]:
        if not linha.strip():
            if cur:
                achados.append(cur)
            cur = {}
            continue
        k, _, v = linha.partition(": ")
        if k == "N":
            cur["nome"] = v.partition("=")[2].strip('"')
        elif k == "H":
            ev = [h for h in v.partition("=")[2].split() if h.startswith("event")]
            if ev:
                cur["dev"] = "/dev/input/" + ev[0]
        elif k == "B":
            nome, _, hexa = v.partition("=")
            cur[nome] = _bits(hexa)
    out = []
    for d in achados:
        ev, prop = d.get("EV", set()), d.get("PROP", set())
        key, rel, ab = d.get("KEY", set()), d.get("REL", set()), d.get("ABS", set())
        if "dev" not in d:
            continue
        if EV_REL in ev and {REL_X, REL_Y} <= rel:
            d["tipo"] = "rel"
        elif EV_ABS in ev and {ABS_X, ABS_Y} <= ab and PROP_DIRECT in prop:
            d["tipo"] = "caneta" if BTN_TOOL_PEN in key else "toque"
        elif EV_ABS in ev and {ABS_X, ABS_Y} <= ab and (PROP_POINTER in prop or BTN_TOOL_FINGER in key):
            d["tipo"] = "touchpad"
        else:
            continue
        out.append(d)
    return out


def _transformar(t: str, x: float, y: float, w: float, h: float) -> tuple[float, float]:
    """Ponto nativo (área w×h do painel) para a saída transformada, como no smithay."""
    t = t.lstrip("_")
    return {
        "Normal": (x, y), "90": (h - y, x), "180": (w - x, h - y), "270": (y, w - x),
        "Flipped": (w - x, y), "Flipped90": (y, x), "Flipped180": (x, h - y),
        "Flipped270": (h - y, w - x),
    }.get(t, (x, y))


class Ponteiro:
    def __init__(self):
        self.x = self.y = 0.0
        self.valido = False          # já houve âncora ou movimento absoluto
        self.toque: tuple[float, float] | None = None   # dedo na tela, enquanto dura
        self.saidas: dict[str, dict] = {}
        self._ganho = {"rel": 1.0, "touchpad": 1.0}
        self._desde = {"rel": [0.0, 0.0], "touchpad": [0.0, 0.0]}
        self._ancora: tuple[float, float] | None = None
        self._trava = threading.Lock()
        self._vivo = True

    def iniciar(self):
        threading.Thread(target=self._rodar, daemon=True, name="ponteiro").start()

    def parar(self):
        self._vivo = False

    # ── geometria ──

    def _ler_saidas(self):
        try:
            js = json.loads(subprocess.run(["niri", "msg", "-j", "outputs"], capture_output=True,
                                           text=True, timeout=2).stdout)
        except Exception:
            return
        saidas = {}
        for nome, o in js.items():
            lg = o.get("logical")
            if lg:
                saidas[nome] = lg
        if saidas:
            self.saidas = saidas
            if not self.valido and SAIDA_TOQUE in saidas:
                s = saidas[SAIDA_TOQUE]
                self.x, self.y = s["x"] + s["width"] / 2, s["y"] + s["height"] / 2

    def _prender(self):
        """Mantém o ponto dentro da união das saídas, como o compositor."""
        if not self.saidas:
            return
        melhor, dist = None, None
        for s in self.saidas.values():
            cx = min(max(self.x, s["x"]), s["x"] + s["width"] - 1)
            cy = min(max(self.y, s["y"]), s["y"] + s["height"] - 1)
            d = (cx - self.x) ** 2 + (cy - self.y) ** 2
            if dist is None or d < dist:
                melhor, dist = (cx, cy), d
        if melhor is not None:
            self.x, self.y = melhor

    # ── âncora exata (ponteiro sobre o orbe) ──

    def ancorar(self, x: float, y: float):
        with self._trava:
            if self._ancora is not None:
                verdade = math.hypot(x - self._ancora[0], y - self._ancora[1])
                tipo = max(self._desde, key=lambda k: math.hypot(*self._desde[k]))
                est = math.hypot(*self._desde[tipo])
                # Recalibra o ganho pelo trajeto desde a âncora anterior.
                if est > 150 and verdade > 150:
                    r = min(2.0, max(0.5, verdade / est))
                    self._ganho[tipo] = min(4.0, max(0.25, self._ganho[tipo] * r ** 0.5))
            self.x, self.y = x, y
            self._ancora = (x, y)
            self._desde = {"rel": [0.0, 0.0], "touchpad": [0.0, 0.0]}
            self.valido = True

    def posicao(self) -> tuple[float, float] | None:
        if self.toque is not None:
            return self.toque
        return (self.x, self.y) if self.valido else None

    # ── leitura ──

    def _mover(self, tipo: str, dx: float, dy: float):
        with self._trava:
            g = self._ganho[tipo]
            self.x += dx * g
            self.y += dy * g
            self._desde[tipo][0] += dx * g
            self._desde[tipo][1] += dy * g
            self._prender()
            self.valido = True

    def _absoluto(self, d: dict, nx: float, ny: float) -> tuple[float, float] | None:
        s = self.saidas.get(SAIDA_TOQUE)
        if s is None:
            return None
        t = s.get("transform", "Normal")
        w, h = s["width"], s["height"]
        if t.lstrip("_").endswith(("90", "270")):
            w, h = h, w
        lx, ly = _transformar(t, nx * w, ny * h, w, h)
        return s["x"] + lx, s["y"] + ly

    def _abrir(self, d: dict) -> dict | None:
        try:
            fd = os.open(d["dev"], os.O_RDONLY | os.O_NONBLOCK)
        except OSError:
            return None
        e = {"fd": fd, "tipo": d["tipo"], "nome": d.get("nome", ""), "dx": 0, "dy": 0,
             "ax": None, "ay": None, "px": None, "py": None, "dedo": False, "dois": False,
             "toca": False, "perto": False, "t": time.monotonic()}
        if d["tipo"] != "rel":
            try:
                e["xr"] = _absinfo(fd, ABS_X)
                e["yr"] = _absinfo(fd, ABS_Y)
            except OSError:
                os.close(fd)
                return None
        return e

    def _quadro(self, e: dict):
        tipo = e["tipo"]
        agora = time.monotonic()
        dt = max(1e-3, agora - e["t"])
        e["t"] = agora
        if tipo == "rel":
            dx, dy = e["dx"], e["dy"]
            e["dx"] = e["dy"] = 0
            if dx or dy:
                v = math.hypot(dx, dy) / (dt * 1000.0)       # contagens/ms
                self._mover("rel", *(c * min(2.5, max(0.6, 0.6 + 0.9 * v)) for c in (dx, dy)))
            return
        if e["ax"] is None or e["ay"] is None:
            return
        (x0, x1, xres), (y0, y1, yres) = e["xr"], e["yr"]
        if tipo == "touchpad":
            if not e["dedo"] or e["dois"]:
                e["px"] = e["py"] = None
                return
            if e["px"] is not None:
                mx = (e["ax"] - e["px"]) / (xres or 30)
                my = (e["ay"] - e["py"]) / (yres or 30)
                v = math.hypot(mx, my) / dt                   # mm/s
                f = 9.0 * min(3.0, max(0.45, 0.45 + v / 110.0))
                self._mover("touchpad", mx * f, my * f)
            e["px"], e["py"] = e["ax"], e["ay"]
            return
        nx = (e["ax"] - x0) / max(1, x1 - x0)
        ny = (e["ay"] - y0) / max(1, y1 - y0)
        p = self._absoluto(e, nx, ny)
        if p is None:
            return
        if tipo == "caneta" and e["perto"]:
            self.ancorar(*p)         # a caneta move o cursor do niri
        elif tipo == "toque":
            self.toque = p if e["toca"] else None

    def _evento(self, e: dict, tipo: int, cod: int, val: int):
        if tipo == EV_REL:
            if cod == REL_X:
                e["dx"] += val
            elif cod == REL_Y:
                e["dy"] += val
        elif tipo == EV_ABS:
            if cod == ABS_X:
                e["ax"] = val
            elif cod == ABS_Y:
                e["ay"] = val
        elif tipo == EV_KEY:
            if cod == BTN_TOOL_FINGER:
                e["dedo"] = bool(val)
            elif cod in (BTN_TOOL_DOUBLETAP, BTN_TOOL_TRIPLETAP):
                e["dois"] = bool(val)
            elif cod == BTN_TOOL_PEN:
                e["perto"] = bool(val)
            elif cod == BTN_TOUCH:
                e["toca"] = bool(val)
                if not val and e["tipo"] == "toque":
                    self.toque = None
        elif tipo == EV_SYN:
            if cod == SYN_REPORT:
                self._quadro(e)
            elif cod == SYN_DROPPED:
                e["px"] = e["py"] = None

    def _rodar(self):
        abertos: dict[int, dict] = {}
        assinatura = None
        prox_saidas = 0.0
        while self._vivo:
            agora = time.monotonic()
            if agora >= prox_saidas:
                self._ler_saidas()
                prox_saidas = agora + 5.0
            try:
                st = os.stat("/dev/input")
                nova = (st.st_mtime_ns, st.st_nlink)
            except OSError:
                nova = None
            if nova != assinatura:
                assinatura = nova
                for e in abertos.values():
                    os.close(e["fd"])
                abertos = {}
                for d in _dispositivos():
                    e = self._abrir(d)
                    if e is not None:
                        abertos[e["fd"]] = e
            if not abertos:
                time.sleep(2.0)
                continue
            try:
                prontos, _, _ = select.select(list(abertos), [], [], 2.0)
            except OSError:
                assinatura = None
                continue
            for fd in prontos:
                e = abertos.get(fd)
                if e is None:
                    continue
                try:
                    dados = os.read(fd, EVENTO.size * 64)
                except BlockingIOError:
                    continue
                except OSError:
                    assinatura = None       # dispositivo saiu; reabre tudo
                    continue
                for _s, _us, tipo, cod, val in EVENTO.iter_unpack(dados[: len(dados) // EVENTO.size * EVENTO.size]):
                    self._evento(e, tipo, cod, val)
