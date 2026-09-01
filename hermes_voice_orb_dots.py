#!/usr/bin/python3
"""Anel de energia — GTK4 + Cairo, layer-shell transparente no Niri.

Não é esfera preenchida. Só o perímetro (anel oco). Sem WebKit, sem GLArea.
"""
import math
import os
import socket
import struct
import subprocess
import sys
import threading

SOCK = os.path.join(os.environ.get("XDG_RUNTIME_DIR", "/run/user/1000"), "hermes-voice-orb.sock")
ORB = 120
PANEL = 88
SIZE_W = ORB + PANEL
SIZE_H = ORB
MARGIN = 14
LOG = "/tmp/hermes-voice-orb.log"
STATES = frozenset({"listening", "thinking", "speaking", "tools"})

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

_STOPS = (
    (0.00, (0.40, 0.88, 1.00)),
    (0.16, (0.42, 0.38, 1.00)),
    (0.32, (0.90, 0.32, 0.78)),
    (0.50, (1.00, 0.32, 0.22)),
    (0.62, (1.00, 0.58, 0.12)),
    (0.78, (0.95, 0.38, 0.58)),
    (1.00, (0.40, 0.88, 1.00)),
)


def _lerp_color(u: float):
    u = u % 1.0
    for i in range(len(_STOPS) - 1):
        a, ca = _STOPS[i]
        b, cb = _STOPS[i + 1]
        if a <= u <= b:
            t = 0.0 if b == a else (u - a) / (b - a)
            return (ca[0] + (cb[0] - ca[0]) * t,
                    ca[1] + (cb[1] - ca[1]) * t,
                    ca[2] + (cb[2] - ca[2]) * t)
    return _STOPS[0][1]


_LUT = tuple(_lerp_color(i / 256.0) for i in range(256))
_INV_TAU = 1.0 / math.tau
# fase que põe ciano no topo (th=pi/2) e laranja/vermelho embaixo, como na referência
_HUE_PHASE = 0.75


def _pack_ring():
    """Anel oco: só a coroa 0.78–1.04. Centro vazio de propósito."""
    pts = []
    radii = (0.78, 0.83, 0.88, 0.93, 0.97, 1.01, 1.04)
    for ri, r in enumerate(radii):
        n = max(28, int(2.35 * math.pi * r * 42))
        off = 0.5 if ri % 2 else 0.0
        rim = (r - 0.78) / 0.26
        for k in range(n):
            th = (k + off) * math.tau / n
            seed = ((k * 17 + ri * 13) % 100) / 100.0
            pts.append((th, r, seed, rim))
    return pts


def _pack_spray():
    """Respingos esparsos além da coroa: borda irregular da referência."""
    pts = []
    for k in range(160):
        th = (k * 2.399963) % math.tau
        seed = ((k * 29) % 100) / 100.0
        r = 1.06 + 0.16 * (((k * 37) % 100) / 100.0)
        pts.append((th, r, seed))
    return pts


POINTS = _pack_ring()
SPRAY = _pack_spray()


class Ring(Gtk.DrawingArea):
    def __init__(self):
        super().__init__()
        self.set_content_width(SIZE_W)
        self.set_content_height(SIZE_H)
        self.set_draw_func(self._draw)
        self.set_can_target(False)
        self.state = "listening"
        self.level = 0.0
        self.level_s = 0.0
        self.t = 0.0
        self.lines = []

    def push_line(self, text: str):
        t = (text or "").strip()
        if not t:
            return
        self.lines.append(t[:18])
        self.lines = self.lines[-3:]

    def _energy(self) -> float:
        e = self.level_s
        if self.state == "listening":
            e = 0.12 + 0.08 * (0.5 + 0.5 * math.sin(self.t * 1.4))
        elif self.state == "thinking":
            e = 0.28 + 0.22 * (0.5 + 0.5 * math.sin(self.t * 2.1))
        elif self.state == "tools":
            e = 0.40 + 0.28 * abs(math.sin(self.t * 3.4))
        else:
            e = 0.22 + 0.78 * e
        return max(0.0, min(1.0, e))

    def _draw(self, _a, cr, w, h):
        cr.set_operator(cairo.OPERATOR_SOURCE)
        cr.set_source_rgba(0, 0, 0, 0)
        cr.paint()
        cr.set_operator(cairo.OPERATOR_ADD)

        e = self._energy()
        cx = PANEL + (w - PANEL) * 0.50
        cy = h * 0.50
        base = 35.0 + 9.0 * e
        spin = self.t * (0.55 if self.state == "speaking" else 0.12)
        t = self.t

        for th0, r, seed, rim in POINTS:
            th = th0 + spin
            turb = rim * (0.035 + 0.15 * e) * (
                0.55 * math.sin(3.0 * th0 + t * 2.8 + seed * 6.0)
                + 0.30 * math.sin(7.0 * th0 - t * 1.7)
            )
            rr = base * (r + turb)
            x = cx + math.cos(th) * rr
            y = cy - math.sin(th) * rr
            red, gre, blu = _LUT[int((th * _INV_TAU + _HUE_PHASE) * 256.0) % 256]
            clump = 0.30 + 0.70 * (0.5 + 0.5 * math.sin(2.0 * th0 + t * 0.4)) * (
                0.5 + 0.5 * math.sin(5.0 * th0 - t * 0.9)
            )
            a = (0.16 + 0.72 * rim) * (0.38 + 0.62 * e) * clump
            sz = 0.55 + 1.15 * rim * (0.5 + e)
            cr.set_source_rgba(red, gre, blu, a)
            cr.arc(x, y, sz, 0, math.tau)
            cr.fill()

        for th0, r, seed in SPRAY:
            th = th0 + spin
            rr = base * (r + 0.05 * math.sin(t * 1.9 + seed * 9.0) + 0.08 * e)
            x = cx + math.cos(th) * rr
            y = cy - math.sin(th) * rr
            red, gre, blu = _LUT[int((th * _INV_TAU + _HUE_PHASE) * 256.0) % 256]
            a = (0.06 + 0.34 * e) * (0.35 + 0.65 * seed)
            cr.set_source_rgba(red, gre, blu, a)
            cr.arc(x, y, 0.5 + 0.9 * seed, 0, math.tau)
            cr.fill()

        cr.set_operator(cairo.OPERATOR_OVER)
        lines = self.lines
        if not lines:
            return
        cr.select_font_face("Sans", cairo.FONT_SLANT_NORMAL, cairo.FONT_WEIGHT_NORMAL)
        cr.set_font_size(9)
        n = len(lines)
        alphas = (0.22, 0.50, 0.92)[-n:]
        y0 = cy - (n - 1) * 7.0
        ring_left = cx - base * 1.22 - 6
        for i, txt in enumerate(lines):
            cr.set_source_rgba(0.88, 0.84, 0.92, alphas[i])
            ext = cr.text_extents(txt)
            cr.move_to(max(2, ring_left - ext.width), y0 + i * 14)
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
        o.level_s += (o.level - o.level_s) * 0.28
        if o.state != "speaking":
            o.level *= 0.92
        o.queue_draw()
        return True

    def show_orb(self, state="listening"):
        self._hiding = False
        if state in STATES:
            self.ring.state = state
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

    def set_level(self, v):
        self.ring.level = max(0.0, min(1.0, float(v)))
        if self.ring.state != "speaking" and self.ring.level > 0.08:
            self.ring.state = "speaking"
        return False

    def hide_orb(self):
        self._hiding = True
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


def _sink_monitor(win: OrbWin):
    try:
        sink = subprocess.check_output(["pactl", "get-default-sink"], text=True).strip()
        mon = sink + ".monitor"
        proc = subprocess.Popen(
            ["parec", "--format=s16le", "--rate=16000", "--channels=1", "-d", mon],
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
        )
        _log(f"monitor {mon}")
        nbytes = 16000 * 2 // 20
        while True:
            buf = proc.stdout.read(nbytes)
            if not buf:
                break
            n = len(buf) // 2
            samples = struct.unpack("<" + "h" * n, buf[: n * 2])
            acc = sum(s * s for s in samples) / max(n, 1)
            rms = math.sqrt(acc) / 32768.0
            GLib.idle_add(win.set_level, min(1.0, rms * 10.0))
    except Exception as e:
        _log(f"monitor fail: {e}")


class App(Gtk.Application):
    def __init__(self):
        super().__init__(application_id="dev.hermes.voiceorb")
        self.win = None
        self.hold()

    def do_activate(self):
        if self.win is None:
            self.win = OrbWin(self)
            threading.Thread(target=self._sock_loop, daemon=True).start()
            threading.Thread(target=_sink_monitor, args=(self.win,), daemon=True).start()
            if "--preview" in sys.argv:
                self.win.show_orb("speaking")
                for t in ("lendo contexto", "chamando ferramenta", "filtrando saida"):
                    self.win.ring.push_line(t)

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
                self.win.set_level(float(arg))
            except ValueError:
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
    _log("start cairo-ring")
    App().run(None)
