#!/usr/bin/python3
"""Anel de energia — GTK4 + Cairo, layer-shell transparente no Niri.

Rotoscope do vídeo de referência (energy-circle-loader): os 62 frames foram
extraídos com chroma-key de saturação (só o azul sobrevive; fundo branco e
marca d'água caem) e viram máscaras alpha em orb_frames/. O Cairo pinta a
máscara com a cor do estado — anel idêntico ao vídeo, recolorível de graça.
Um segundo conjunto de máscaras borradas (blur separável, pré-computado no
load) é desenhado por baixo em modo aditivo: glow que segue cada segmento.

Rebuild dos frames:
  ffmpeg -i energy-circle-loaders-animation-gif-download-10913911.mp4 \
    -vf "crop=1500:1500:616:0,scale=256:256,format=rgba,geq=r='r(X,Y)':\
g='g(X,Y)':b='b(X,Y)':a='clip((b(X,Y)-r(X,Y)-20)*1.4,0,255)'" \
    -start_number 0 orb_frames/f_%02d.png

Estados com crossfade contínuo (pesos deslizam, nada salta): aparecer (pop
com overshoot) · listening (respira, reage ao mic) · thinking (gira rápido,
violeta) · speaking (nível do TTS escala/acelera; tom espectral desloca a
cor grave→azul, agudo→ciano) · tools (pulso duplo) · desaparecer (esvai).
Nível+tom do TTS chegam do daemon ("level L T", envelope do arquivo); o
monitor do sink é fallback quando o daemon não está transmitindo.
"""
import colorsys
import math
import os
import re
import socket
import struct
import subprocess
import sys
import threading
import time

SOCK = os.path.join(os.environ.get("XDG_RUNTIME_DIR", "/run/user/1000"), "hermes-voice-orb.sock")
ORB = 120
PANEL = 106
SIZE_W = ORB + PANEL
SIZE_H = ORB
MARGIN = 14
LOG = "/tmp/hermes-voice-orb.log"
STATES = frozenset({"listening", "thinking", "speaking", "tools"})
FRAME_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "orb_frames")
# centro do anel dentro do frame 256x256 (o crop deixou o núcleo ~6px abaixo)
F_CX, F_CY = 128.0, 134.0

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
    _log("numpy ausente: sem glow, tom fixo em 0.5")

ACCENT_CSS = "/home/davi/Projetos/Docs_rice_sistema/main.css"


def _system_palette():
    """Accent do tema (matugen, vem do wallpaper) → paleta de estados por HSV.

    Fallback: azul do vídeo (mediana dos pixels opacos). Lido no startup: o
    orb renasce a cada sessão de voz, então acompanha a troca de wallpaper.
    """
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
    """Máscara borrada por frame: glow que abraça cada segmento de energia."""
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
GLOWS = _build_glows(FRAMES)
NF = len(FRAMES)
if not NF:
    _log(f"sem frames em {FRAME_DIR}")


def _ease_out_back(p: float) -> float:
    c = 1.70158
    q = p - 1.0
    return 1.0 + (c + 1.0) * q * q * q + c * q * q


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
        self.frame_pos = 0.0
        self.rot = 0.0
        self.phase = "in"        # in | run | out
        self.phase_t = 0.0
        self.level = 0.0         # nível do TTS (daemon ou sink monitor)
        self.level_s = 0.0
        self.tone = 0.5          # tom do TTS, 0=grave 1=agudo
        self.tone_s = 0.5
        self.mic = 0.0           # fala do usuário (source)
        self.mic_s = 0.0
        self.lines = []

    def push_line(self, text: str):
        t = (text or "").strip()
        if not t:
            return
        self.lines.append(t[:16])
        self.lines = self.lines[-3:]

    def _params(self, st):
        """(pulso, brilho, tinta, vel. do loop, vel. angular) de um estado."""
        t = self.t
        if st == "thinking":
            osc = 0.5 + 0.5 * math.sin(t * 3.1)
            return (1.0 + 0.035 * math.sin(t * 2.6), 0.82 + 0.22 * osc,
                    TINT_THINK, 1.8, 0.55)
        if st == "tools":
            p = abs(math.sin(t * 3.4))
            return (1.0 + 0.03 * p, 0.88 + 0.18 * p, TINT_TOOLS, 1.35, 0.25)
        if st == "speaking":
            lv, tn = self.level_s, self.tone_s
            tint = (TINT_DEEP[0] + (TINT_HIGH[0] - TINT_DEEP[0]) * tn,
                    TINT_DEEP[1] + (TINT_HIGH[1] - TINT_DEEP[1]) * tn,
                    TINT_DEEP[2] + (TINT_HIGH[2] - TINT_DEEP[2]) * tn)
            return (1.0 + 0.16 * lv, 0.80 + 0.45 * lv, tint,
                    0.9 + 1.1 * lv, 0.10 + 0.75 * lv)
        return (1.0 + 0.02 * math.sin(t * 1.6) + 0.14 * self.mic_s,
                0.85 + 0.45 * self.mic_s, TINT_BASE,
                0.75 + 0.8 * self.mic_s, 0.06 + 0.30 * self.mic_s)

    def blend(self):
        """Crossfade: soma dos parâmetros ponderada pelos pesos de estado."""
        tot = sum(self.mix.values()) or 1.0
        pulse = bright = fsp = rotv = 0.0
        tint = [0.0, 0.0, 0.0]
        for st, wgt in self.mix.items():
            if wgt < 0.001:
                continue
            w = wgt / tot
            p, b, tn, f, rv = self._params(st)
            pulse += w * p
            bright += w * b
            fsp += w * f
            rotv += w * rv
            tint[0] += w * tn[0]
            tint[1] += w * tn[1]
            tint[2] += w * tn[2]
        return pulse, bright, tuple(tint), fsp, rotv

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

        pulse, bright, tint, _, _ = self.blend()
        cx = PANEL + (w - PANEL) * 0.50
        cy = h * 0.50
        sc = (ORB / 256.0) * env_sc * pulse
        lift = 0.25 * max(0.0, bright - 1.0)
        r = min(1.0, tint[0] * bright + lift)
        g = min(1.0, tint[1] * bright + lift)
        b = min(1.0, tint[2] * bright)

        idx = int(self.frame_pos) % NF
        cr.save()
        cr.translate(cx, cy)
        cr.rotate(self.rot)
        cr.scale(sc, sc)
        cr.translate(-F_CX, -F_CY)
        if GLOWS:
            glow_a = env_a * max(0.0, min(0.50, 0.30 + 0.25 * (bright - 0.80)))
            cr.set_operator(cairo.OPERATOR_ADD)
            cr.set_source_rgba(r, g, b, glow_a)
            cr.mask_surface(GLOWS[idx], 0, 0)
            cr.set_operator(cairo.OPERATOR_OVER)
        cr.set_source_rgba(r, g, b, env_a)
        cr.mask_surface(FRAMES[idx], 0, 0)
        cr.restore()

        lines = self.lines
        if not lines or env_a < 0.5:
            return
        cr.select_font_face("Sans", cairo.FONT_SLANT_NORMAL, cairo.FONT_WEIGHT_NORMAL)
        cr.set_font_size(11)
        n = len(lines)
        alphas = (0.22, 0.50, 0.92)[-n:]
        y0 = cy - (n - 1) * 8.5
        ring_left = cx - 118.0 * sc - 4
        for i, txt in enumerate(lines):
            cr.set_source_rgba(0.88, 0.84, 0.92, alphas[i] * env_a)
            ext = cr.text_extents(txt)
            cr.move_to(max(2, ring_left - ext.width), y0 + i * 17)
            cr.show_text(txt)


class OrbWin(Gtk.ApplicationWindow):
    def __init__(self, app):
        super().__init__(application=app)
        self.set_title("hermes-voice-orb")
        self.set_decorated(False)
        self.set_resizable(False)
        self.set_default_size(SIZE_W, SIZE_H)
        self._hiding = False
        self._idle_id = 0
        self._mapped = False
        self._ext_t = 0.0        # último "level" vindo do daemon
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
            LayerShell.set_margin(self, LayerShell.Edge.TOP, MARGIN)
            LayerShell.set_margin(self, LayerShell.Edge.RIGHT, MARGIN)
            LayerShell.set_keyboard_mode(self, LayerShell.KeyboardMode.NONE)
            LayerShell.set_namespace(self, "hermes-voice-orb")
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
        o.t += 0.033
        if o.phase in ("in", "out"):
            o.phase_t += 0.033
            if o.phase == "in" and o.phase_t >= 0.35:
                o.phase = "run"
            elif o.phase == "out" and o.phase_t >= 0.25:
                o.phase = "run"
                self.set_visible(False)
                self._arm_idle(400)
        for st in o.mix:
            tgt = 1.0 if st == o.state else 0.0
            o.mix[st] += (tgt - o.mix[st]) * 0.16
        _, _, _, fsp, rotv = o.blend()
        o.frame_pos = (o.frame_pos + fsp) % NF if NF else 0.0
        o.rot = (o.rot + rotv * 0.033) % math.tau
        # ataque rápido, decaimento lento: a boca abre mais rápido que fecha
        o.level_s += (o.level - o.level_s) * (0.55 if o.level > o.level_s else 0.16)
        o.tone_s += (o.tone - o.tone_s) * 0.25
        o.mic_s += (o.mic - o.mic_s) * (0.50 if o.mic > o.mic_s else 0.20)
        if o.state != "speaking":
            o.level *= 0.90
        o.mic *= 0.90
        o.queue_draw()
        return True

    def show_orb(self, state="listening"):
        self._hiding = False
        if state in STATES:
            self.ring.state = state
        if not self.is_visible() or self.ring.phase == "out":
            self.ring.phase = "in"
            self.ring.phase_t = 0.0
            self.ring.frame_pos = 0.0
        self.present()
        _log(f"present {self.ring.state}")
        self._arm_idle(180000 if "--preview" in sys.argv else 25000)
        return False

    def set_state(self, state):
        if state in STATES:
            self.ring.state = state
        if not self.is_visible() or not self._mapped:
            self.show_orb(state)
        return False

    def set_audio(self, lv, tone):
        self.ring.level = max(0.0, min(1.0, float(lv)))
        if tone is not None:
            self.ring.tone = max(0.0, min(1.0, float(tone)))
        if self.ring.state != "speaking" and self.ring.level > 0.08:
            self.ring.state = "speaking"
        return False

    def set_daemon_level(self, lv, tone):
        """'level L [T]' do daemon: fonte prioritária sobre o sink monitor."""
        self._ext_t = time.monotonic()
        return self.set_audio(lv, tone)

    def daemon_quiet(self) -> bool:
        return time.monotonic() - self._ext_t > 0.30

    def set_mic(self, v):
        self.ring.mic = max(0.0, min(1.0, float(v)))
        return False

    def hide_orb(self):
        self._hiding = True
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
        self._idle_id = GLib.timeout_add(ms, self._idle_quit)

    def _idle_quit(self):
        self._idle_id = 0
        if self._hiding or not self.is_visible():
            _log("quit")
            self.get_application().quit()
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
    """Fallback de TTS: RMS → nível; centroide espectral → tom. Só age
    quando o daemon não está transmitindo level (arbitragem por timestamp)."""
    try:
        sink = subprocess.check_output(["pactl", "get-default-sink"], text=True).strip()
        mon = sink + ".monitor"
        proc = subprocess.Popen(
            ["parec", "--format=s16le", "--rate=16000", "--channels=1", "-d", mon],
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
        )
        _log(f"monitor sink {mon}")
        nsamp = 800  # 50 ms
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
            if not win.daemon_quiet():
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
            GLib.idle_add(win.set_audio, min(1.0, rms * 10.0), tone)
    except Exception as e:
        _log(f"monitor sink fail: {e}")


def _mic_monitor(win: OrbWin):
    """Fala do usuário: RMS do source default anima o listening."""
    try:
        src = subprocess.check_output(["pactl", "get-default-source"], text=True).strip()
        proc = subprocess.Popen(
            ["parec", "--format=s16le", "--rate=16000", "--channels=1", "-d", src],
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
        )
        _log(f"monitor source {src}")
        nsamp = 800
        while True:
            buf = _read_chunk(proc.stdout, nsamp * 2)
            if len(buf) < nsamp * 2:
                break
            GLib.idle_add(win.set_mic, min(1.0, _rms(buf) * 12.0))
    except Exception as e:
        _log(f"monitor source fail: {e}")


class App(Gtk.Application):
    def __init__(self):
        super().__init__(application_id="dev.hermes.voiceorb")
        self.win = None
        self._ci = 0
        self.hold()

    def do_activate(self):
        if self.win is None:
            self.win = OrbWin(self)
            threading.Thread(target=self._sock_loop, daemon=True).start()
            threading.Thread(target=_sink_monitor, args=(self.win,), daemon=True).start()
            threading.Thread(target=_mic_monitor, args=(self.win,), daemon=True).start()
            if "--preview" in sys.argv:
                self.win.show_orb("listening")
                for t in ("lendo contexto", "chamando tool", "filtrando saida"):
                    self.win.ring.push_line(t)
                GLib.timeout_add(4000, self._preview_cycle)

    def _preview_cycle(self):
        seq = ("thinking", "tools", "speaking", "listening")
        st = seq[self._ci % len(seq)]
        self._ci += 1
        self.win.set_state(st)
        _log(f"preview state {st}")
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
        if op == "show":
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
        elif op == "hide":
            self.win.hide_orb()
        elif op == "quit":
            self.quit()
        return False


if __name__ == "__main__":
    _log(f"start rotoscope-ring ({NF} frames)")
    App().run(None)
