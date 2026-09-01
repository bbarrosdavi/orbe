#!/usr/bin/python3
"""Anel de energia — rotoscope do mp4 deformado fisicamente pela voz (GTK4 + Cairo).

A geometria É o vídeo de referência (62 máscaras alpha em orb_frames/, chroma-key
de saturação sobre o energy-circle-loader), e a física deforma o próprio desenho:

- warp polar: o frame é desenhado em N_W fatias angulares, cada uma com escala
  radial própria; o campo vem de molas (bounce global + bojos de sílaba) e de
  harmônicos baixos animados — graves incham o anel em ondas largas, o desenho
  inteiro quica com a voz. Campo plano (idle) = um blit só, custo mínimo.
- chamas procedurais chapadas NA MESMA cor plana, coladas na borda externa nos
  ângulos das línguas de mola: sílabas agudas disparam espinhos finos, graves
  labaredas largas — indistinguíveis do traço do vídeo. Gotas nos picos.
- velocidade do loop, rotação, caos de fase, brilho e cor por estado, em
  crossfade contínuo de pesos (seamless).

Cor herdada do sistema: lê --colorAccentBg do CSS do matugen (vem do wallpaper)
no startup e deriva os estados por HSV; o orb renasce a cada sessão de voz,
então acompanha a troca de wallpaper. Fallback: azul do vídeo.

Nível+tom do TTS chegam do daemon ("level L T", envelope+centroide do arquivo);
monitor do sink é fallback com FFT própria; monitor do mic anima o listening.
Texto do agente: 3 linhas, coluna fixa à esquerda, glifos sem cobertura da
fonte são filtrados e o truncamento é por largura em pixels com reticências.

Rebuild dos frames:
  ffmpeg -i energy-circle-loaders-animation-gif-download-10913911.mp4 \
    -vf "crop=1500:1500:616:0,scale=256:256,format=rgba,geq=r='r(X,Y)':\
g='g(X,Y)':b='b(X,Y)':a='clip((b(X,Y)-r(X,Y)-20)*1.4,0,255)'" \
    -start_number 0 orb_frames/f_%02d.png

Modos: produção (daemon, socket padrão) · --preview (socket/app-id/namespace
-live e janela 136px abaixo, para testar ao lado da produção; sink promovido a
fonte prioritária e gerador silábico sintético quando não há áudio).
Backups: hermes_voice_orb_rotoscope.py (sem física) · hermes_voice_orb_dots.py.
"""
import colorsys
import math
import os
import random
import re
import socket
import struct
import subprocess
import sys
import threading
import time

PREVIEW = "--preview" in sys.argv
SFX = "-live" if PREVIEW else ""
SOCK = os.path.join(os.environ.get("XDG_RUNTIME_DIR", "/run/user/1000"),
                    f"hermes-voice-orb{SFX}.sock")
# ART_BOX é o tamanho VISUAL da arte; ORB_BOX é a célula que o overlay reserva
# para ela. Os dois eram a mesma constante, e por isso aumentar a janela nunca
# resolvia o recorte: crescia a arte junto. Medido antes de separar, com o raio
# externo = ART_EDGE * (ART_BOX/256) * env_sc * pulse * s_warp:
#   repouso 46.9px · thinking no pico 55.6px
#   speaking lv=0.9 64.3px · speaking durante o pop de entrada 67.9px
# Contra 60px de meia-altura na janela antiga: em fala alta o anel batia na
# bounding box e aparecia a borda quadrada. 148 dá 74px de meia-altura.
ART_BOX = 120
ORB_BOX = 148
PANEL = 296   # coluna de texto larga: reasoning legível
SIZE_W = ORB_BOX + PANEL
SIZE_H = ORB_BOX
# A folga é descontada das margens para o anel não mudar de lugar na tela: a
# célula cresce, o centro da arte fica onde estava.
_FOLGA = (ORB_BOX - ART_BOX) // 2
MARGIN_TOP = max(0, 14 - _FOLGA) + (136 if PREVIEW else 0)
MARGIN_RIGHT = max(0, 14 - _FOLGA)
LOG = f"/tmp/hermes-voice-orb{SFX}.log"
STATES = frozenset({"listening", "thinking", "speaking", "tools"})
FRAME_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "orb_frames")
F_CX, F_CY = 128.0, 134.0    # centro do anel no frame 256x256
ART_EDGE = 100.0             # raio externo do núcleo do anel, em px da arte
ACCENT_CSS = "/home/davi/Projetos/Docs_rice_sistema/main.css"

# Aberração cromática do glitch. Ciano e magenta fixos de propósito, não
# derivados do accent: o efeito só lê como "canal de cor separado" se as duas
# cópias forem quase complementares. Desenhadas em ADD, então a sobreposição
# volta ao claro, como na referência.
GL_CYAN = (0.00, 0.95, 0.95)
GL_MAG = (1.00, 0.08, 0.55)
GL_HALF_W = ORB_BOX / 2.0    # meia-largura da célula do orbe, em px de tela

N_W = 36                     # fatias do warp polar
N_TONGUE = 10
N_DROP = 7
SPRING_K = 55.0
SPRING_C = 6.5
# Teto das línguas e gotas. Sobe junto com ORB_BOX: em 57 elas ficavam
# DENTRO do anel quando ele passava de 57px em fala alta, e as chamas
# sumiam justamente no pico. 70 fica abaixo dos 74px de meia-altura.
R_LIM = 70.0                 # teto absoluto em px de tela

def _log(msg):
    try:
        with open(LOG, "a") as f:
            f.write(msg + "\n")
    except OSError:
        pass

def _preload():
    lib = "/usr/lib/libgtk4-layer-shell.so"
    if os.path.exists(lib) and "libgtk4-layer-shell" not in os.environ.get("LD_PRELOAD", ""):
        os.environ["LD_PRELOAD"] = lib
        os.environ["HERMES_ORB_PRELOAD"] = "1"
        os.execvp(sys.executable, [sys.executable] + sys.argv)

if __name__ == "__main__" and os.environ.get("HERMES_ORB_PRELOAD") != "1":
    _preload()

import cairo
import gi
gi.require_version("Gtk", "4.0")
from gi.repository import Gtk, GLib, Gdk

try:
    gi.require_version("Gtk4LayerShell", "1.0")
    from gi.repository import Gtk4LayerShell as LayerShell
    HAVE_LS = True
except (ValueError, ImportError) as e:
    HAVE_LS = False
    _log(f"layer-shell import failed: {e}")

try:
    import numpy as np
    HAVE_NP = True
except ImportError:
    HAVE_NP = False
    _log("numpy ausente: sem glow pré-borrado, tom fixo")


def _system_palette():
    """Accent do tema (matugen, vem do wallpaper) → paleta de estados por HSV."""
    base = (0.00, 0.53, 0.99)
    try:
        m = re.search(r"--colorAccentBg:\s*#([0-9a-fA-F]{6})", open(ACCENT_CSS).read())
        if m:
            v = m.group(1)
            base = tuple(int(v[i:i + 2], 16) / 255.0 for i in (0, 2, 4))
            _log(f"accent do sistema #{v}")
    except OSError:
        pass
    h, s, _v = colorsys.rgb_to_hsv(*base)
    s = max(s, 0.60)

    def mk(hh, ss, vv):
        return colorsys.hsv_to_rgb(hh % 1.0, min(1.0, max(0.0, ss)), min(1.0, vv))

    return (mk(h, s, 1.0),                    # base (listening)
            mk(h + 0.078, s, 1.0),            # thinking (+28 graus)
            mk(h - 0.078, s, 0.92),           # tools (-28 graus)
            mk(h, s + 0.15, 0.80),            # speaking graves
            mk(h, s * 0.45, 1.0))             # speaking agudos


TINT_BASE, TINT_THINK, TINT_TOOLS, TINT_DEEP, TINT_HIGH = _system_palette()


def _refresh_palette():
    """Relê o accent do matugen e regenera a paleta de estados.

    O docstring do módulo promete que o orbe acompanha a troca de wallpaper
    porque "renasce a cada sessão de voz". Isso deixou de valer quando o
    processo passou a ficar quente entre sessões: a paleta era lida uma única
    vez, no import, e um orbe de horas atrás carregava um accent velho.
    Chamado no 'show', que é o começo de cada sessão — mesma intenção, sem
    depender de o processo morrer.
    """
    global TINT_BASE, TINT_THINK, TINT_TOOLS, TINT_DEEP, TINT_HIGH
    antes = TINT_BASE
    TINT_BASE, TINT_THINK, TINT_TOOLS, TINT_DEEP, TINT_HIGH = _system_palette()
    if TINT_BASE != antes:
        _log(f"paleta atualizada: {antes} -> {TINT_BASE}")


def _accent_watcher():
    """Segue a troca de wallpaper enquanto o orbe está na tela.

    O `show` já relê a paleta, o que cobre "trocou o wallpaper entre sessões".
    Isto cobre o outro caso: trocar com o orbe visível. Vigia a mtime do CSS do
    matugen em vez de usar inotify, porque é uma statvez por segundo contra uma
    dependência a mais, e a troca de wallpaper não é evento de latência.
    """
    try:
        ultima = os.path.getmtime(ACCENT_CSS)
    except OSError:
        ultima = 0.0
    while True:
        time.sleep(1.0)
        try:
            agora = os.path.getmtime(ACCENT_CSS)
        except OSError:
            continue
        if agora != ultima:
            ultima = agora
            GLib.idle_add(_refresh_palette)


def _load_frames():
    frames = []
    i = 0
    while True:
        p = os.path.join(FRAME_DIR, f"f_{i:02d}.png")
        if not os.path.exists(p):
            break
        frames.append(cairo.ImageSurface.create_from_png(p))
        i += 1
    return frames


def _box_blur(a, r, axis):
    n = a.shape[axis]
    c = np.cumsum(a, axis=axis, dtype=np.float32)
    zero = np.zeros_like(np.take(c, [0], axis=axis))
    c = np.concatenate([zero, c], axis=axis)
    hi = np.clip(np.arange(n) + r + 1, 0, n)
    lo = np.clip(np.arange(n) - r, 0, n)
    shape = [1, 1]
    shape[axis] = n
    div = (hi - lo).astype(np.float32).reshape(shape)
    return (np.take(c, hi, axis=axis) - np.take(c, lo, axis=axis)) / div


def _build_glows(frames):
    if not HAVE_NP:
        return []
    glows = []
    for s in frames:
        s.flush()
        w, h, stride = s.get_width(), s.get_height(), s.get_stride()
        a = np.frombuffer(s.get_data(), np.uint8).reshape(h, stride // 4, 4)[:, :w, 3]
        a = a.astype(np.float32)
        for _ in range(3):
            a = _box_blur(_box_blur(a, 4, 0), 4, 1)
        g = cairo.ImageSurface(cairo.FORMAT_A8, w, h)
        gbuf = np.frombuffer(g.get_data(), np.uint8).reshape(h, g.get_stride())
        gbuf[:, :w] = np.clip(a, 0, 255).astype(np.uint8)
        g.mark_dirty()
        glows.append(g)
    return glows


FRAMES = _load_frames()
GLOWS = []
NF = len(FRAMES)
if not NF:
    _log(f"sem frames em {FRAME_DIR}")


def _glow_worker():
    # blur pré-computado em background: o primeiro present não espera por ele
    GLOWS.extend(_build_glows(FRAMES))


threading.Thread(target=_glow_worker, daemon=True).start()


def _ease_out_back(p: float) -> float:
    c = 1.70158
    q = p - 1.0
    return 1.0 + (c + 1.0) * q * q * q + c * q * q


def _wrap(a: float) -> float:
    return (a + math.pi) % math.tau - math.pi


def _catmull_path(cr, pts):
    n = len(pts)
    cr.move_to(*pts[0])
    for i in range(n):
        p0 = pts[(i - 1) % n]
        p1 = pts[i]
        p2 = pts[(i + 1) % n]
        p3 = pts[(i + 2) % n]
        cr.curve_to(p1[0] + (p2[0] - p0[0]) / 6.0, p1[1] + (p2[1] - p0[1]) / 6.0,
                    p2[0] - (p3[0] - p1[0]) / 6.0, p2[1] - (p3[1] - p1[1]) / 6.0,
                    p2[0], p2[1])
    cr.close_path()


class Ring(Gtk.DrawingArea):
    def __init__(self):
        super().__init__()
        self.set_content_width(SIZE_W)
        self.set_content_height(SIZE_H)
        self.set_draw_func(self._draw)
        self.set_can_target(False)
        self.state = "listening"
        self.mix = {"listening": 1.0, "thinking": 0.0, "speaking": 0.0, "tools": 0.0}
        self.t = 0.0
        self.rot = 0.0
        self.frame_pos = 0.0
        self.phase = "in"
        self.phase_t = 0.0
        self.level = 0.0
        self.level_s = 0.0
        self.tone = 0.5
        self.tone_s = 0.5
        self.mic = 0.0
        self.mic_s = 0.0
        # Sessão travada pelo Jarvis: sem isto não há como distinguir "ele
        # continua me ouvindo" de "ele esqueceu de fechar".
        self.held = False
        self.lines = []
        self._rows = None    # cache das linhas quebradas por largura
        # física (convenção de ângulo do cairo: y para baixo, +sin)
        self._ph2 = 0.9
        self._ph3 = 2.1
        self._ampL = 0.5
        self._t_ang = [j * math.tau / N_TONGUE for j in range(N_TONGUE)]
        self._t_drift = [(((j * 37) % 100) / 100.0 - 0.5) * 0.30 for j in range(N_TONGUE)]
        self._t_h = [0.0] * N_TONGUE
        self._t_v = [0.0] * N_TONGUE
        self._t_w = [0.26] * N_TONGUE
        self._t_next = 0
        # glitch do pensamento: rajadas curtas e aleatórias que rasgam um setor
        # contíguo do anel e pulam o frame do vídeo. Só existe no thinking, e
        # a intensidade é ponderada por mix["thinking"], então nasce e morre
        # junto com o crossfade em vez de aparecer cortado.
        self._gl_until = 0.0     # fim da rajada atual
        self._gl_next = 0.6      # quando a próxima começa
        self._gl_lo = 0          # primeira fatia rasgada
        self._gl_span = 0        # quantas fatias
        self._gl_amp = 0.0       # deslocamento radial em px
        self._gl_jump = 0        # salto no índice do frame
        self._gl_shear = 0.0     # torção angular do setor
        self._gl_dx = 0.0        # separação da aberração cromática, px
        self._gl_bands = []      # (y0, altura, deslocamento_x) das fatias
        self._d_e = [0.0] * N_DROP
        self._d_ang = [0.0] * N_DROP
        self._d_dist = [0.0] * N_DROP
        self._d_spd = [0.0] * N_DROP
        self._d_next = 0
        self._r_off = 0.0
        self._r_vel = 0.0
        self._raw_prev = 0.0
        self._max_r = 50.0
        self._pb = self._params("listening")

    def clear_lines(self):
        self.lines = []
        self._rows = None

    def push_line(self, text: str):
        # remove glifos sem cobertura na fonte (emoji, nerd fonts, símbolos)
        t = "".join(ch for ch in (text or "") if 0x20 <= ord(ch) < 0x2400)
        t = re.sub(r"\[\?[0-9;]*[A-Za-z]", "", t)
        t = " ".join(t.split())
        if not t:
            return
        self.lines.append(t[:220])
        self.lines = self.lines[-6:]
        self._rows = None

    def _params(self, st):
        """(omega, caos, ampL_px, ganho_lingua, vel_loop, tinta, brilho, pulso)"""
        t = self.t
        if st == "thinking":
            # ampL fixo em 2.4 dava ±5% de escala — 17% da faixa que o clamp
            # do warp permite, ou seja, um anel parado vibrando. Agora a
            # amplitude respira entre 1.6 e 5.8 num período de ~2.9s, e o
            # chaos acompanha, então as fases dos lóbulos aceleram junto com a
            # inspiração em vez de correrem a velocidade constante.
            osc = 0.5 + 0.5 * math.sin(t * 3.1)
            resp = 0.5 + 0.5 * math.sin(t * 2.2)
            return (0.9 * math.sin(t * 0.45), 1.5 + 1.3 * resp,
                    1.6 + 3.6 * resp, 0.40, 1.8,
                    TINT_THINK, 0.82 + 0.22 * osc, 1.0 + 0.03 * math.sin(t * 2.6))
        if st == "tools":
            p = abs(math.sin(t * 3.4))
            return (-0.35, 1.0, 2.0, 0.55, 1.35,
                    TINT_TOOLS, 0.88 + 0.18 * p, 1.0 + 0.025 * p)
        if st == "speaking":
            lv, tn = self.level_s, self.tone_s
            tint = (TINT_DEEP[0] + (TINT_HIGH[0] - TINT_DEEP[0]) * tn,
                    TINT_DEEP[1] + (TINT_HIGH[1] - TINT_DEEP[1]) * tn,
                    TINT_DEEP[2] + (TINT_HIGH[2] - TINT_DEEP[2]) * tn)
            # A amplitude aqui já encosta no teto do clamp em nível alto, então
            # subir ampL só faria recortar. O que dá mais vida é fase: chaos
            # mais alto acelera as fases dos lóbulos, e o campo ganhou um
            # harmônico de 5 lóbulos, então o mesmo deslocamento radial vira
            # movimento mais articulado em vez de um bojo só inchando.
            return (0.15 + 1.6 * lv, 0.9 + 3.2 * lv,
                    1.5 + 6.0 * lv * (1.0 - 0.55 * tn),
                    0.5 + 1.7 * lv, 0.9 + 1.1 * lv,
                    tint, 0.80 + 0.45 * lv, 1.0 + 0.08 * lv)
        # listening. Aqui a expressividade não é enfeite: é o único jeito de
        # o Davi saber que o mic está entrando. ampL ia só até 3.1 (±6% de
        # escala, contra os 0.44 que o clamp do warp permite) e a voz dele
        # mal mexia o anel. Agora vai a 7.4, e chaos, brilho e pulso também
        # seguem o microfone, então falar produz reação inequívoca.
        #
        # A respiração ociosa é de propósito: com mic em zero o anel continua
        # inflando devagar, dizendo "estou ligado e escutando" em vez de
        # parecer travado — que é o que dava a dúvida.
        m = self.mic_s
        idle = 0.5 + 0.5 * math.sin(t * 1.25)
        return (0.10 + 0.9 * m, 0.45 + 2.4 * m,
                0.8 + 1.1 * idle + 5.5 * m,
                0.35 + 1.4 * m,
                0.75 + 1.1 * m, TINT_BASE, 0.82 + 0.55 * m,
                1.0 + 0.02 * math.sin(t * 1.6) + 0.10 * m)

    def blend(self):
        tot = sum(self.mix.values()) or 1.0
        om = ch = aL = tg = fs = br = pu = 0.0
        tint = [0.0, 0.0, 0.0]
        for st, wgt in self.mix.items():
            if wgt < 0.001:
                continue
            w = wgt / tot
            o, c, a, g, f, tn, b, p = self._params(st)
            om += w * o
            ch += w * c
            aL += w * a
            tg += w * g
            fs += w * f
            tint[0] += w * tn[0]
            tint[1] += w * tn[1]
            tint[2] += w * tn[2]
            br += w * b
            pu += w * p
        return om, ch, aL, tg, fs, tuple(tint), br, pu

    def _impulse(self, strength: float, tone: float):
        """Sílaba nova chuta uma língua: agudo = fina e forte, grave = larga."""
        j = self._t_next % N_TONGUE
        self._t_next += 1
        self._t_v[j] += strength * (240.0 + 260.0 * tone)
        self._t_w[j] = 0.38 - 0.22 * tone
        if strength > 0.08:
            d = self._d_next % N_DROP
            self._d_next += 1
            self._d_e[d] = 1.0
            self._d_ang[d] = self._t_ang[j] + math.sin(self.t * 13.7 + j) * 0.25
            self._d_dist[d] = 46.0
            self._d_spd[d] = 25.0 + 80.0 * strength

    def step(self, dt: float):
        self.t += dt
        for st in self.mix:
            tgt = 1.0 if st == self.state else 0.0
            self.mix[st] += (tgt - self.mix[st]) * 0.16
        pb = self.blend()
        self._pb = pb
        omega, chaos, ampL, tgain, fsp, _tint, _br, _pu = pb
        self._ampL = ampL

        self.level_s += (self.level - self.level_s) * (0.55 if self.level > self.level_s else 0.16)
        self.tone_s += (self.tone - self.tone_s) * 0.25
        self.mic_s += (self.mic - self.mic_s) * (0.50 if self.mic > self.mic_s else 0.20)

        on = max(0.0, self.level - self._raw_prev)
        self._raw_prev = self.level
        if on > 0.03:
            self._impulse(on * min(1.0, tgain), self.tone_s)
        if self.state == "listening" and self.mic > self.mic_s + 0.10:
            self._impulse(0.35 * self.mic, 0.45)

        if self.state != "speaking":
            self.level *= 0.90
        self.mic *= 0.90

        self._ph2 += 0.9 * (0.35 + 0.65 * chaos) * dt
        self._ph3 += -1.3 * (0.35 + 0.65 * chaos) * dt
        self.rot = (self.rot + omega * dt) % math.tau
        self.frame_pos = (self.frame_pos + fsp) % NF if NF else 0.0

        # Alvo da mola do raio global. No speaking segue o nível de áudio; no
        # thinking ganha uma onda lenta própria, senão o anel fica cravado no
        # raio de repouso justamente no estado em que deveria parecer ocupado.
        # Pesado por mix["thinking"], então entra e sai junto com o crossfade.
        alvo = (8.0 * self.level_s
                + 2.6 * self.mix.get("thinking", 0.0) * math.sin(self.t * 1.9)
                # No listening o anel inteiro infla com a voz do Davi. Sem
                # isto só os lóbulos mexiam, e o sinal de "te ouvi" ficava
                # fraco demais para ser lido de canto de olho.
                + 7.0 * self.mix.get("listening", 0.0) * self.mic_s)
        force = -40.0 * (self._r_off - alvo) - 7.0 * self._r_vel
        self._r_vel += force * dt
        self._r_off += self._r_vel * dt

        for j in range(N_TONGUE):
            self._t_ang[j] = (self._t_ang[j] + (omega * 0.6 + self._t_drift[j]) * dt) % math.tau
            f = (-SPRING_K * self._t_h[j] - SPRING_C * self._t_v[j]
                 + self.level_s * tgain * 420.0 * (0.35 + 0.65 * (0.5 + 0.5 * math.sin(self.t * 3.0 + j * 2.1))))
            self._t_v[j] += f * dt
            self._t_h[j] = max(-3.0, min(16.0, self._t_h[j] + self._t_v[j] * dt))

        # ── glitch aleatório do pensamento ──
        # Rajadas curtas (60-190ms) separadas por intervalos irregulares. O
        # intervalo encurta conforme o thinking domina o mix, então o anel
        # "trava" mais quando está fundo no raciocínio.
        w_think = self.mix.get("thinking", 0.0)
        if w_think > 0.25:
            if self.t >= self._gl_next:
                self._gl_until = self.t + random.uniform(0.05, 0.20)
                self._gl_next = self._gl_until + random.uniform(0.06, 0.75) / (0.4 + w_think)
                self._gl_lo = random.randrange(N_W)
                self._gl_span = random.randint(2, max(3, N_W // 3))
                self._gl_amp = random.uniform(5.0, 15.0) * random.choice((-1.0, 1.0))
                self._gl_shear = random.uniform(-0.09, 0.09)
                # 1 em 3 rajadas também pula o frame do vídeo: o desenho inteiro
                # salta, que é o que dá a leitura de "quadro perdido".
                self._gl_jump = random.randrange(1, NF) if (NF and random.random() < 0.34) else 0
                # Separação dos canais de cor e fatias horizontais escorregando.
                # Nem toda rajada leva as duas: variar quais artefatos aparecem
                # é o que impede a repetição de virar padrão reconhecível.
                self._gl_dx = random.uniform(1.6, 5.5) if random.random() < 0.75 else 0.0
                self._gl_bands = [
                    (random.uniform(-46.0, 40.0),          # y do topo da fatia
                     random.uniform(2.0, 9.0),             # altura
                     random.uniform(5.0, 20.0) * random.choice((-1.0, 1.0)))
                    for _ in range(random.randint(0, 4))
                ]
        else:
            self._gl_until = 0.0
            self._gl_next = self.t + 0.4

        for d in range(N_DROP):
            if self._d_e[d] > 0.04:
                self._d_dist[d] = min(R_LIM, self._d_dist[d] + self._d_spd[d] * dt)
                self._d_spd[d] *= 0.97
                self._d_e[d] *= 0.93

    def _field(self, th):
        """Campo de deformação radial (px de tela) no ângulo local th."""
        # Coeficientes somam ~1.0 de propósito: o terceiro harmônico acrescenta
        # detalhe angular sem aumentar o pico, que já bate no clamp do warp.
        f = self._r_off + self._ampL * (0.52 * math.sin(2.0 * th + self._ph2)
                                        + 0.30 * math.sin(3.0 * th + self._ph3)
                                        + 0.18 * math.sin(5.0 * th - 1.7 * self._ph2))
        for j in range(N_TONGUE):
            h = self._t_h[j]
            if h > 0.3:
                w = max(self._t_w[j] * 2.2, 0.60)
                dth = _wrap(th - self._t_ang[j])
                if abs(dth) < 3.0 * w:
                    f += 0.45 * h * math.exp(-(dth / w) ** 2)
        return f

    def _draw_glitch(self, cr, frame, scb, env_a, k, r, g, b):
        """Aberração cromática e fatias horizontais escorregando.

        O anel é desenhado como máscara de cor chapada, então basta repetir a
        máscara deslocada em outra cor. Duas cópias quase complementares em
        OPERATOR_ADD: onde elas se sobrepõem a soma volta ao claro, que é o
        núcleo branco da referência, e onde não se sobrepõem sobra a franja
        ciano de um lado e magenta do outro.

        Tudo aqui é desenhado com a rotação do anel desfeita: as fatias
        precisam ser horizontais em relação à TELA, como varredura de vídeo.
        Se acompanhassem o giro do anel virariam outra coisa.

        O recorte é preso à coluna do orbe (±GL_HALF_W) porque à esquerda
        fica o painel de texto do raciocínio, e franja de glitch por cima
        das linhas atrapalharia a leitura.
        """
        cr.save()
        cr.rotate(-self.rot)
        cr.set_operator(cairo.OPERATOR_ADD)

        if self._gl_dx:
            for dx, (cc, cg, cb) in ((-self._gl_dx, GL_CYAN), (self._gl_dx, GL_MAG)):
                cr.save()
                cr.rectangle(-GL_HALF_W, -GL_HALF_W, 2 * GL_HALF_W, 2 * GL_HALF_W)
                cr.clip()
                cr.translate(dx * k, 0.0)
                cr.scale(scb, scb)
                cr.translate(-F_CX, -F_CY)
                cr.set_source_rgba(cc, cg, cb, 0.60 * k * env_a)
                cr.mask_surface(frame, 0, 0)
                cr.restore()

        for y0, hh, sx in self._gl_bands:
            cr.save()
            cr.rectangle(-GL_HALF_W, y0, 2 * GL_HALF_W, hh)
            cr.clip()
            cr.translate(sx * k, 0.0)
            cr.scale(scb, scb)
            cr.translate(-F_CX, -F_CY)
            cr.set_source_rgba(r, g, b, 0.85 * k * env_a)
            cr.mask_surface(frame, 0, 0)
            cr.restore()

        cr.set_operator(cairo.OPERATOR_OVER)
        cr.restore()

    def _draw(self, _a, cr, w, h):
        cr.set_operator(cairo.OPERATOR_SOURCE)
        cr.set_source_rgba(0, 0, 0, 0)
        cr.paint()
        cr.set_operator(cairo.OPERATOR_OVER)
        if not NF:
            return

        if self.phase == "in":
            p = min(1.0, self.phase_t / 0.35)
            env_sc = 0.45 + 0.55 * _ease_out_back(p)
            env_a = min(1.0, p * 2.2)
        elif self.phase == "out":
            p = min(1.0, self.phase_t / 0.25)
            env_sc = 1.0 - 0.35 * (p * p)
            env_a = 1.0 - p
        else:
            env_sc, env_a = 1.0, 1.0

        _om, _ch, _aL, _tg, _fs, tint, bright, pulse = self._pb
        cx = PANEL + (w - PANEL) * 0.50
        cy = h * 0.50
        scb = (ART_BOX / 256.0) * env_sc * pulse
        lift = 0.25 * max(0.0, bright - 1.0)
        r = min(1.0, tint[0] * bright + lift)
        g = min(1.0, tint[1] * bright + lift)
        b = min(1.0, tint[2] * bright)
        glow_k = env_a * max(0.0, min(1.0, 0.55 + (bright - 0.80)))

        # Rajada de glitch ativa: salta o frame e rasga um setor contíguo.
        # A intensidade é ponderada pelo peso do thinking no mix, então a
        # rajada some suavemente quando o estado troca no meio dela.
        gl = self.t < self._gl_until
        gl_k = self.mix.get("thinking", 0.0) if gl else 0.0

        idx = int(self.frame_pos) % NF
        if gl_k > 0.0 and self._gl_jump:
            idx = (idx + self._gl_jump) % NF
        frame = FRAMES[idx]
        glow = GLOWS[idx] if GLOWS else None
        dth = math.tau / N_W
        fields = [self._field((i + 0.5) * dth) for i in range(N_W)]
        if gl_k > 0.0:
            amp = self._gl_amp * gl_k
            for k in range(self._gl_span):
                i = (self._gl_lo + k) % N_W
                # Bordas do setor com metade do deslocamento: o rasgo tem
                # degrau nas pontas em vez de um salto único, que lê melhor.
                borda = k == 0 or k == self._gl_span - 1
                fields[i] += amp * (0.5 if borda else 1.0)
        fmax = max(abs(f) for f in fields)
        smax = 1.0

        cr.save()
        cr.translate(cx, cy)
        cr.rotate(self.rot)

        # glow em um blit só: borrado por natureza, segue apenas o bounce global
        if glow is not None:
            sg = max(0.84, min(1.28, 1.0 + self._r_off / 50.0))
            cr.save()
            cr.scale(scb * sg, scb * sg)
            cr.translate(-F_CX, -F_CY)
            cr.set_operator(cairo.OPERATOR_ADD)
            cr.set_source_rgba(r, g, b, 0.30 * glow_k)
            cr.mask_surface(glow, 0, 0)
            cr.set_operator(cairo.OPERATOR_OVER)
            cr.restore()

        if fmax < 0.8:
            # campo quase plano: desenho inteiro em um blit (custo mínimo)
            s = max(0.84, min(1.28, 1.0 + fields[0] / 50.0))
            smax = s
            cr.save()
            cr.scale(scb * s, scb * s)
            cr.translate(-F_CX, -F_CY)
            cr.set_source_rgba(r, g, b, env_a)
            cr.mask_surface(frame, 0, 0)
            cr.restore()
        else:
            # warp polar: cada fatia do vídeo com escala radial própria
            for i in range(N_W):
                s = 1.0 + fields[i] / 50.0
                s = max(0.84, min(1.28, s))
                smax = max(smax, s)
                a0 = i * dth
                cr.save()
                cr.move_to(0, 0)
                cr.arc(0, 0, 82.0, a0 - 0.006, a0 + dth + 0.006)
                cr.close_path()
                cr.clip()
                # Torção angular do setor rasgado: gira o DESENHO dentro da
                # cunha, não a cunha. Girar o recorte deixaria buraco vazio;
                # girar o desenho mostra outro trecho do anel no mesmo lugar,
                # que é a leitura de banda deslocada.
                if gl_k > 0.0 and self._gl_shear:
                    ini = (i - self._gl_lo) % N_W
                    if ini < self._gl_span:
                        cr.rotate(self._gl_shear * gl_k)
                cr.scale(scb * s, scb * s)
                cr.translate(-F_CX, -F_CY)
                cr.set_source_rgba(r, g, b, env_a)
                cr.mask_surface(frame, 0, 0)
                cr.restore()

        if gl_k > 0.0:
            self._draw_glitch(cr, frame, scb, env_a, gl_k, r, g, b)

        if self.held:
            # Sessão travada: ponto fixo no topo, fora do giro do anel, com um
            # respiro lento. Fixo porque precisa ser lido de canto de olho como
            # estado, e não confundido com a animação; com respiro porque um
            # ponto parado lê como travamento, e é o oposto do que ele diz.
            cr.save()
            cr.rotate(-self.rot)
            pulso = 0.62 + 0.38 * (0.5 + 0.5 * math.sin(self.t * 2.0))
            rp = ORB_BOX / 2.0 - 7.0
            cr.arc(0.0, -rp, 3.0, 0.0, math.tau)
            cr.set_source_rgba(r, g, b, 0.90 * pulso * env_a)
            cr.fill()
            cr.set_operator(cairo.OPERATOR_ADD)
            cr.arc(0.0, -rp, 6.0, 0.0, math.tau)
            cr.set_source_rgba(r, g, b, 0.22 * pulso * env_a)
            cr.fill()
            cr.set_operator(cairo.OPERATOR_OVER)
            cr.restore()

        max_ext = ART_EDGE * scb * smax

        # chamas chapadas na cor da arte, coladas na borda nos ângulos das molas
        for j in range(N_TONGUE):
            hj = self._t_h[j]
            if hj < 1.2:
                continue
            a = self._t_ang[j]
            s_a = max(0.84, min(1.28, 1.0 + self._field(a) / 50.0))
            rb = ART_EDGE * scb * s_a * 0.94
            tip = min(R_LIM, rb + hj * 2.0)
            max_ext = max(max_ext, tip)
            wj = self._t_w[j]
            lean = 0.10 * math.sin(self.t * 2.3 + j)
            pts = [(math.cos(a - wj * 0.85) * rb * 0.98, math.sin(a - wj * 0.85) * rb * 0.98),
                   (math.cos(a + lean) * tip, math.sin(a + lean) * tip),
                   (math.cos(a + wj * 0.85) * rb * 0.98, math.sin(a + wj * 0.85) * rb * 0.98),
                   (math.cos(a) * rb * 0.90, math.sin(a) * rb * 0.90)]
            cr.set_operator(cairo.OPERATOR_ADD)
            _catmull_path(cr, pts)
            cr.set_source_rgba(r, g, b, 0.16 * glow_k)
            cr.set_line_width(5.0)
            cr.stroke_preserve()
            cr.set_operator(cairo.OPERATOR_OVER)
            cr.set_source_rgba(r, g, b, env_a)
            cr.fill()

        # gotas
        for d in range(N_DROP):
            e = self._d_e[d]
            if e <= 0.04:
                continue
            dx = math.cos(self._d_ang[d]) * self._d_dist[d]
            dy = math.sin(self._d_ang[d]) * self._d_dist[d]
            cr.set_operator(cairo.OPERATOR_ADD)
            cr.set_source_rgba(r, g, b, 0.12 * e * env_a)
            cr.arc(dx, dy, (1.5 + 3.0 * e) * 2.0, 0, math.tau)
            cr.fill()
            cr.set_operator(cairo.OPERATOR_OVER)
            cr.set_source_rgba(r, g, b, 0.9 * e * env_a)
            cr.arc(dx, dy, 1.5 + 3.0 * e, 0, math.tau)
            cr.fill()
        cr.restore()

        self._max_r = max_ext

        if not self.lines or env_a < 0.5:
            return
        cr.select_font_face("Sans", cairo.FONT_SLANT_NORMAL, cairo.FONT_WEIGHT_NORMAL)
        cr.set_font_size(11)
        right = cx - 66.0        # coluna fixa: não respira com o anel
        avail = right - 4.0
        if self._rows is None:
            rows = []
            for txt in self.lines:
                cur = ""
                for wd in txt.split(" "):
                    cand = (cur + " " + wd) if cur else wd
                    if cr.text_extents(cand).width <= avail:
                        cur = cand
                        continue
                    if cur:
                        rows.append(cur)
                    while len(wd) > 1 and cr.text_extents(wd).width > avail:
                        k = len(wd) - 1
                        while k > 1 and cr.text_extents(wd[:k]).width > avail:
                            k -= 1
                        rows.append(wd[:k])
                        wd = wd[k:]
                    cur = wd
                if cur:
                    rows.append(cur)
            self._rows = rows[-5:]
        rows = self._rows
        n = len(rows)
        alphas = (0.16, 0.28, 0.42, 0.62, 0.92)[-n:]
        y0 = cy - (n - 1) * 8.5
        for i, txt in enumerate(rows):
            ext = cr.text_extents(txt)
            cr.set_source_rgba(0.88, 0.84, 0.92, alphas[i] * env_a)
            cr.move_to(max(2.0, right - ext.width), y0 + i * 17)
            cr.show_text(txt)


class OrbWin(Gtk.ApplicationWindow):
    def __init__(self, app):
        super().__init__(application=app)
        self.set_title(f"hermes-voice-orb{SFX}")
        self.set_decorated(False)
        self.set_resizable(False)
        self.set_default_size(SIZE_W, SIZE_H)
        self._hiding = False
        self._idle_id = 0
        self._mapped = False
        self._ext_t = 0.0
        self.ring = Ring()
        self.set_child(self.ring)

        css = Gtk.CssProvider()
        css.load_from_data(
            b"window, drawing { background-color: transparent; background-image: none; }"
        )
        Gtk.StyleContext.add_provider_for_display(
            Gdk.Display.get_default(), css, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION
        )

        if HAVE_LS:
            LayerShell.init_for_window(self)
            LayerShell.set_layer(self, LayerShell.Layer.OVERLAY)
            LayerShell.set_anchor(self, LayerShell.Edge.TOP, True)
            LayerShell.set_anchor(self, LayerShell.Edge.RIGHT, True)
            LayerShell.set_margin(self, LayerShell.Edge.TOP, MARGIN_TOP)
            LayerShell.set_margin(self, LayerShell.Edge.RIGHT, MARGIN_RIGHT)
            LayerShell.set_keyboard_mode(self, LayerShell.KeyboardMode.NONE)
            LayerShell.set_namespace(self, f"hermes-voice-orb{SFX}")
            LayerShell.set_exclusive_zone(self, 0)
            self._pin_laptop()
            _log("layer-shell ok")
        self.connect("realize", self._on_realize)
        GLib.timeout_add(33, self._tick)

    def _pin_laptop(self):
        display = Gdk.Display.get_default()
        if display is None:
            return
        mons = display.get_monitors()
        for i in range(mons.get_n_items()):
            m = mons.get_item(i)
            if (m.get_connector() or "") == "eDP-1":
                LayerShell.set_monitor(self, m)
                return

    def _on_realize(self, *_):
        self._mapped = True
        surf = self.get_surface()
        if surf is not None:
            try:
                surf.set_input_region(cairo.Region())
            except Exception as e:
                _log(f"input_region: {e}")
        _log("realized")

    def _tick(self):
        o = self.ring
        if o.phase in ("in", "out"):
            o.phase_t += 0.033
            if o.phase == "in" and o.phase_t >= 0.35:
                o.phase = "run"
            elif o.phase == "out" and o.phase_t >= 0.25:
                o.phase = "run"
                self.set_visible(False)
                self._arm_idle(400)
        o.step(0.033)
        o.queue_draw()
        return True

    def show_orb(self, state="listening"):
        self._hiding = False
        self.ring.clear_lines()
        if state in STATES:
            self.ring.state = state
        if not self.is_visible() or self.ring.phase == "out":
            self.ring.phase = "in"
            self.ring.phase_t = 0.0
            self.ring.frame_pos = 0.0
        self.present()
        _log(f"present {self.ring.state}")
        if PREVIEW:
            self._arm_idle(180000)
        else:
            self._cancel_idle()
        return False

    def set_state(self, state):
        if state in STATES:
            self.ring.state = state
        if not self.is_visible() or not self._mapped:
            self.show_orb(state)
            return False
        self._cancel_idle()
        return False

    def set_audio(self, lv, tone):
        self.ring.level = max(0.0, min(1.0, float(lv)))
        if tone is not None:
            self.ring.tone = max(0.0, min(1.0, float(tone)))
        if self.ring.state != "speaking" and self.ring.level > 0.08:
            self.ring.state = "speaking"
        return False

    def set_daemon_level(self, lv, tone):
        self._ext_t = time.monotonic()
        return self.set_audio(lv, tone)

    def daemon_quiet(self) -> bool:
        return time.monotonic() - self._ext_t > 0.30

    def set_mic(self, v):
        self.ring.mic = max(0.0, min(1.0, float(v)))
        return False

    def hide_orb(self):
        self._hiding = True
        self.ring.clear_lines()
        if self.is_visible() and self.ring.phase != "out":
            self.ring.phase = "out"
            self.ring.phase_t = 0.0
        else:
            self.set_visible(False)
            self._arm_idle(400)
        return False

    def _arm_idle(self, ms):
        if self._idle_id:
            GLib.source_remove(self._idle_id)
        self._idle_id = GLib.timeout_add(ms, self._idle_hide)

    def _cancel_idle(self):
        if self._idle_id:
            GLib.source_remove(self._idle_id)
            self._idle_id = 0

    def _idle_hide(self):
        self._idle_id = 0
        if self.ring.state == "listening":
            _log("idle 10s hide")
            self.hide_orb()
        return False


def _read_chunk(stream, nbytes):
    buf = b""
    while len(buf) < nbytes:
        part = stream.read(nbytes - len(buf))
        if not part:
            return buf
        buf += part
    return buf


def _rms(buf):
    n = len(buf) // 2
    if n == 0:
        return 0.0
    if HAVE_NP:
        x = np.frombuffer(buf[: n * 2], dtype="<i2").astype(np.float32) / 32768.0
        return float(np.sqrt(np.mean(x * x)))
    samples = struct.unpack("<" + "h" * n, buf[: n * 2])
    return math.sqrt(sum(s * s for s in samples) / n) / 32768.0


def _sink_monitor(win: OrbWin):
    """TTS via sink. Produção: fallback do daemon. Preview: fonte prioritária."""
    try:
        sink = subprocess.check_output(["pactl", "get-default-sink"], text=True).strip()
        mon = sink + ".monitor"
        proc = subprocess.Popen(
            ["parec", "--format=s16le", "--rate=16000", "--channels=1", "-d", mon],
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
        )
        _log(f"monitor sink {mon}")
        nsamp = 800
        if HAVE_NP:
            hann = np.hanning(nsamp)
            freqs = np.fft.rfftfreq(nsamp, 1.0 / 16000)
            band = (freqs >= 90) & (freqs <= 5000)
            fb = freqs[band]
            lo, span = math.log(110.0), math.log(3500.0 / 110.0)
        while True:
            buf = _read_chunk(proc.stdout, nsamp * 2)
            if len(buf) < nsamp * 2:
                break
            if not PREVIEW and not win.daemon_quiet():
                continue
            rms = _rms(buf)
            tone = None
            if HAVE_NP and rms > 0.004:
                x = np.frombuffer(buf, dtype="<i2").astype(np.float32) / 32768.0
                mag = np.abs(np.fft.rfft(x * hann))[band]
                s = float(mag.sum())
                if s > 1e-6:
                    cen = float((mag * fb).sum()) / s
                    tone = min(1.0, max(0.0, (math.log(max(cen, 110.0)) - lo) / span))
            lv = min(1.0, rms * 10.0)
            if PREVIEW and lv > 0.05:
                GLib.idle_add(win.set_daemon_level, lv, tone)
            else:
                GLib.idle_add(win.set_audio, lv, tone)
    except Exception as e:
        _log(f"monitor sink fail: {e}")


def _mic_monitor(win: OrbWin):
    """Anima o listening com o nível do microfone.

    Reconecta quando a fonte padrão muda. A versão anterior resolvia a fonte
    uma única vez, no start; como o orbe fica quente entre sessões, ele
    seguia preso ao microfone de horas atrás. Depois que o cancelamento de
    eco entrou, isso passou a significar monitorar o mic CRU enquanto o
    daemon escutava a fonte filtrada: o anel reagia ao próprio TTS.
    """
    atual = None
    proc = None
    nsamp = 800
    prox_check = 0.0
    src = None
    while True:
        # Só reconsulta a fonte padrão a cada 3s. Consultar por leitura seria
        # spawnar pactl ~20x por segundo, que é caro à toa: a fonte muda
        # raramente (troca de perfil, fone plugado).
        agora = time.monotonic()
        if src is None or agora >= prox_check:
            prox_check = agora + 3.0
            try:
                src = subprocess.check_output(
                    ["pactl", "get-default-source"], text=True, timeout=5).strip()
            except Exception as e:
                _log(f"monitor source: sem fonte padrão ({e})")
                src = None
                time.sleep(3.0)
                continue
        if src != atual:
            if proc is not None:
                try:
                    proc.kill()
                except OSError:
                    pass
            proc = subprocess.Popen(
                ["parec", "--format=s16le", "--rate=16000", "--channels=1", "-d", src],
                stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
            )
            atual = src
            _log(f"monitor source {src}")
        try:
            buf = _read_chunk(proc.stdout, nsamp * 2)
        except Exception as e:
            _log(f"monitor source read fail: {e}")
            buf = b""
        if len(buf) < nsamp * 2:
            # parec caiu (troca de perfil, fone plugado): recomeça do zero.
            try:
                proc.kill()
            except (OSError, AttributeError):
                pass
            proc, atual = None, None
            time.sleep(0.5)
            continue
        GLib.idle_add(win.set_mic, min(1.0, _rms(buf) * 12.0))


class App(Gtk.Application):
    def __init__(self):
        super().__init__(application_id=f"dev.hermes.voiceorb{SFX.replace('-', '.')}")
        self.win = None
        self._ci = 0
        self.hold()

    def do_activate(self):
        if self.win is None:
            self.win = OrbWin(self)
            threading.Thread(target=self._sock_loop, daemon=True).start()
            # Os dois monitores estavam definidos e nunca iniciados: nenhuma
            # thread os lançava no arquivo. Com isso self.mic ficava fixo em
            # zero e TODO o listening — que é inteiro função do microfone —
            # ficava multiplicado por zero. O orbe não reagia à voz porque
            # nunca soube que havia voz.
            threading.Thread(target=_mic_monitor, args=(self.win,),
                             daemon=True).start()
            threading.Thread(target=_sink_monitor, args=(self.win,),
                             daemon=True).start()
            threading.Thread(target=_accent_watcher, daemon=True).start()
            if PREVIEW:
                self.win.show_orb("listening")
                for t in ("lendo contexto", "chamando tool", "filtrando saida"):
                    self.win.ring.push_line(t)
                GLib.timeout_add(5000, self._preview_cycle)
                GLib.timeout_add(50, self._preview_synth)

    def _preview_cycle(self):
        seq = ("thinking", "tools", "speaking", "listening")
        st = seq[self._ci % len(seq)]
        self._ci += 1
        self.win.set_state(st)
        _log(f"preview state {st}")
        return True

    def _preview_synth(self):
        if self.win.ring.state == "speaking" and self.win.daemon_quiet():
            t = self.win.ring.t
            syl = abs(math.sin(t * 4.6)) * (0.62 + 0.38 * math.sin(t * 1.3))
            lv = max(0.0, min(1.0, 0.12 + 0.85 * syl))
            tn = 0.5 + 0.42 * math.sin(t * 0.8)
            self.win.set_audio(lv, tn)
        return True

    def _sock_loop(self):
        try:
            os.unlink(SOCK)
        except OSError:
            pass
        srv = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        srv.bind(SOCK)
        srv.listen(4)
        _log(f"listen {SOCK}")
        while True:
            conn, _ = srv.accept()
            try:
                data = conn.recv(1024).decode("utf-8", "replace")
            except OSError:
                conn.close()
                continue
            conn.close()
            for raw in data.splitlines():
                GLib.idle_add(self._cmd, raw.strip())

    def _cmd(self, line):
        if not line or self.win is None:
            return False
        parts = line.split(None, 1)
        op = parts[0]
        arg = parts[1] if len(parts) > 1 else ""
        if op == "warm":
            pass
        elif op == "clear":
            self.win.ring.clear_lines()
        elif op == "show":
            _refresh_palette()
            self.win.show_orb(arg or "listening")
        elif op == "state":
            self.win.set_state(arg or "listening")
        elif op == "level":
            try:
                vals = arg.split()
                lv = float(vals[0])
                tn = float(vals[1]) if len(vals) > 1 else None
                self.win.set_daemon_level(lv, tn)
            except (ValueError, IndexError):
                pass
        elif op == "line":
            self.win.ring.push_line(arg)
            if self.win.ring.state not in ("tools", "thinking"):
                self.win.set_state("tools")
        elif op == "hold":
            self.win.ring.held = arg.strip() not in ("", "0", "false", "off")
        elif op == "hide":
            self.win.hide_orb()
        elif op == "quit":
            self.quit()
        return False


if __name__ == "__main__":
    _log(f"start warp-ring ({NF} frames)")
    App().run(None)
