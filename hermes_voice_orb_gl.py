#!/usr/bin/python3
"""Orbe de voz — layer-shell transparente + GtkGLArea (partículas GPU)."""
import array
import ctypes
import math
import os
import socket
import struct
import subprocess
import sys
import threading

SOCK = os.path.join(os.environ.get("XDG_RUNTIME_DIR", "/run/user/1000"), "hermes-voice-orb.sock")
ORB = 148
PANEL = 86
SIZE_W = ORB + PANEL
SIZE_H = 148
MARGIN = 14
LOG = "/tmp/hermes-voice-orb.log"
STATES = frozenset({"listening", "thinking", "speaking", "tools"})
N_POINTS = 14000

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

from OpenGL.GL import (
    GL_ARRAY_BUFFER, GL_BLEND, GL_COLOR_BUFFER_BIT, GL_FALSE, GL_FLOAT,
    GL_FRAGMENT_SHADER, GL_ONE, GL_POINTS, GL_PROGRAM_POINT_SIZE,
    GL_SRC_ALPHA, GL_STATIC_DRAW, GL_VERTEX_SHADER, GL_COMPILE_STATUS, GL_LINK_STATUS,
    glAttachShader, glBindBuffer, glBindVertexArray, glBlendFunc, glBufferData,
    glClear, glClearColor, glCompileShader, glCreateProgram, glCreateShader,
    glDrawArrays, glEnable, glEnableVertexAttribArray, glGenBuffers,
    glGenVertexArrays, glGetUniformLocation, glLinkProgram, glShaderSource,
    glUniform1f, glUniform1i, glUseProgram, glVertexAttribPointer, glViewport,
    glGetShaderiv, glGetShaderInfoLog, glGetProgramiv, glGetProgramInfoLog,
)

VERT = """
#version 330
layout(location=0) in vec3 aPos;
layout(location=1) in vec3 aColor;
layout(location=2) in float aSeed;
uniform float uTime;
uniform float uLevel;
uniform int uState;
out vec3 vColor;
out float vAlpha;
void main() {
    float r = length(aPos);
    float ang = atan(aPos.y, aPos.x);
    float rim = smoothstep(0.62, 1.02, r);
    float e = uLevel;
    if (uState == 0) e = 0.12 + 0.08 * (0.5 + 0.5 * sin(uTime * 1.4));
    else if (uState == 1) e = 0.28 + 0.22 * (0.5 + 0.5 * sin(uTime * 2.1));
    else if (uState == 3) e = 0.40 + 0.28 * abs(sin(uTime * 3.4));
    float turb = rim * (0.04 + 0.22 * e) * (
        0.55 * sin(3.0 * ang + uTime * 2.8 + aSeed)
      + 0.30 * sin(7.0 * ang - uTime * 1.7)
      + 0.15 * sin(11.0 * ang + uTime)
    );
    float spin = uTime * (uState == 2 ? 0.55 : 0.12);
    float cs = cos(spin), sn = sin(spin);
    vec3 q = aPos * (1.0 + turb + 0.18 * e);
    vec3 rot = vec3(q.x * cs - q.z * sn, q.y, q.x * sn + q.z * cs);
    float s = 0.92;
    gl_Position = vec4(rot.x * s, rot.y * s, 0.0, 1.0);
    gl_PointSize = mix(1.2, 3.5, r) * (0.75 + 0.9 * e);
    vColor = aColor;
    vAlpha = (0.20 + 0.55 * r) * (0.45 + 0.55 * e);
    if (uState == 0) vAlpha *= 0.55;
}
"""

FRAG = """
#version 330
in vec3 vColor;
in float vAlpha;
out vec4 frag;
void main() {
    vec2 p = gl_PointCoord * 2.0 - 1.0;
    float d = dot(p, p);
    if (d > 1.0) discard;
    frag = vec4(vColor, exp(-d * 3.2) * vAlpha);
}
"""

_STOPS = (
    (0.00, (0.40, 0.88, 1.00)),
    (0.16, (0.42, 0.38, 1.00)),
    (0.32, (0.90, 0.32, 0.78)),
    (0.50, (1.00, 0.32, 0.22)),
    (0.62, (1.00, 0.58, 0.12)),
    (0.78, (0.95, 0.38, 0.58)),
    (1.00, (0.40, 0.88, 1.00)),
)

def _lerp_color(u):
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


def _compile(src, kind):
    sh = glCreateShader(kind)
    glShaderSource(sh, src)
    glCompileShader(sh)
    if glGetShaderiv(sh, GL_COMPILE_STATUS) != 1:
        raise RuntimeError(glGetShaderInfoLog(sh).decode())
    return sh


def _make_points():
    data = array.array("f")
    golden = math.pi * (3.0 - 5.0 ** 0.5)
    remaining = N_POINTS
    shells = 16
    for si in range(1, shells + 1):
        radius = si / shells
        n = max(12, int(remaining * (si / (shells * (shells + 1) / 2))))
        n = min(n, remaining)
        remaining -= n
        for i in range(n):
            y = 1.0 - (i / max(n - 1, 1)) * 2.0
            rr = math.sqrt(max(0.0, 1.0 - y * y))
            th = golden * i
            x = math.cos(th) * rr * radius
            z = math.sin(th) * rr * radius
            yy = y * radius
            cr, cg, cb = _lerp_color((math.atan2(yy, x) / math.tau) + 0.25)
            seed = ((i * 17 + si * 13) % 100) / 100.0
            data.extend((x, yy, z, cr, cg, cb, seed))
    return data


class OrbGL(Gtk.GLArea):
    def __init__(self):
        super().__init__()
        self.set_size_request(ORB, ORB)
        self.set_hexpand(False)
        self.set_vexpand(False)
        self.set_has_depth_buffer(False)
        self.set_has_stencil_buffer(False)
        self.set_required_version(3, 3)
        try:
            self.set_allowed_apis(Gdk.GLAPI.GL)
        except Exception:
            pass
        self.connect("realize", self._realize)
        self.connect("render", self._render)
        self.state = "listening"
        self.level = 0.0
        self.level_s = 0.0
        self.t = 0.0
        self.lines = []
        self._ok = False
        self._n = 0

    def push_line(self, text: str):
        t = (text or "").strip()
        if not t:
            return
        self.lines.append(t[:18])
        self.lines = self.lines[-3:]

    def _realize(self, *_):
        self.make_current()
        try:
            vs = _compile(VERT, GL_VERTEX_SHADER)
            fs = _compile(FRAG, GL_FRAGMENT_SHADER)
            prog = glCreateProgram()
            glAttachShader(prog, vs)
            glAttachShader(prog, fs)
            glLinkProgram(prog)
            if glGetProgramiv(prog, GL_LINK_STATUS) != 1:
                raise RuntimeError(glGetProgramInfoLog(prog).decode())
            self.prog = prog
            self.uTime = glGetUniformLocation(prog, "uTime")
            self.uLevel = glGetUniformLocation(prog, "uLevel")
            self.uState = glGetUniformLocation(prog, "uState")
            pts = _make_points()
            self._n = len(pts) // 7
            vao = glGenVertexArrays(1)
            vbo = glGenBuffers(1)
            glBindVertexArray(vao)
            glBindBuffer(GL_ARRAY_BUFFER, vbo)
            glBufferData(GL_ARRAY_BUFFER, pts.tobytes(), GL_STATIC_DRAW)
            stride = 7 * 4
            glEnableVertexAttribArray(0)
            glVertexAttribPointer(0, 3, GL_FLOAT, GL_FALSE, stride, None)
            glEnableVertexAttribArray(1)
            glVertexAttribPointer(1, 3, GL_FLOAT, GL_FALSE, stride, ctypes.c_void_p(12))
            glEnableVertexAttribArray(2)
            glVertexAttribPointer(2, 1, GL_FLOAT, GL_FALSE, stride, ctypes.c_void_p(24))
            self.vao = vao
            glEnable(GL_PROGRAM_POINT_SIZE)
            glEnable(GL_BLEND)
            glBlendFunc(GL_SRC_ALPHA, GL_ONE)
            glClearColor(0.0, 0.0, 0.0, 0.0)
            self._ok = True
            _log(f"gl ok points={self._n}")
        except Exception as e:
            _log(f"gl realize failed: {e}")
            self._ok = False

    def _render(self, _area, _ctx):
        alloc = self.get_allocation()
        glViewport(0, 0, max(1, alloc.width), max(1, alloc.height))
        glClearColor(0.0, 0.0, 0.0, 0.0)
        glClear(GL_COLOR_BUFFER_BIT)
        if not self._ok:
            return True
        st = {"listening": 0, "thinking": 1, "speaking": 2, "tools": 3}.get(self.state, 0)
        glEnable(GL_BLEND)
        glBlendFunc(GL_SRC_ALPHA, GL_ONE)
        glUseProgram(self.prog)
        glUniform1f(self.uTime, self.t)
        glUniform1f(self.uLevel, self.level_s)
        glUniform1i(self.uState, st)
        glBindVertexArray(self.vao)
        glDrawArrays(GL_POINTS, 0, self._n)
        return True


class TextLayer(Gtk.DrawingArea):
    def __init__(self, glw: OrbGL):
        super().__init__()
        self.glw = glw
        self.set_size_request(PANEL, SIZE_H)
        self.set_draw_func(self._draw)
        self.set_can_target(False)

    def _draw(self, _a, cr, w, h):
        import cairo
        cr.set_operator(cairo.OPERATOR_CLEAR)
        cr.paint()
        cr.set_operator(cairo.OPERATOR_OVER)
        lines = self.glw.lines
        if not lines:
            return
        cr.select_font_face("Sans", cairo.FONT_SLANT_NORMAL, cairo.FONT_WEIGHT_NORMAL)
        cr.set_font_size(9)
        n = len(lines)
        alphas = (0.22, 0.50, 0.92)[-n:]
        y0 = h / 2.0 - (n - 1) * 7.0
        for i, txt in enumerate(lines):
            cr.set_source_rgba(0.88, 0.84, 0.92, alphas[i])
            ext = cr.text_extents(txt)
            cr.move_to(max(2, w - 6 - ext.width), y0 + i * 14)
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
        self.gl = OrbGL()
        self.text = TextLayer(self.gl)
        box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=0)
        box.append(self.text)
        box.append(self.gl)
        self.set_child(box)

        css = Gtk.CssProvider()
        css.load_from_data(b"window, box, glarea, drawing { background: transparent; }")
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
        GLib.timeout_add(16, self._tick)

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
                import cairo
                surf.set_input_region(cairo.Region())
            except Exception as e:
                _log(f"input_region: {e}")
        _log("realized")

    def _tick(self):
        o = self.gl
        o.t += 0.016
        o.level_s += (o.level - o.level_s) * 0.28
        if o.state != "speaking":
            o.level *= 0.92
        o.queue_render()
        self.text.queue_draw()
        return True

    def show_orb(self, state="listening"):
        self._hiding = False
        if state in STATES:
            self.gl.state = state
        self.present()
        _log(f"present {self.gl.state}")
        self._arm_idle(180000 if "--preview" in sys.argv else 25000)
        return False

    def set_state(self, state):
        if state in STATES:
            self.gl.state = state
        if not self.is_visible() or not self._mapped:
            self.show_orb(state)
        return False

    def set_level(self, v):
        self.gl.level = max(0.0, min(1.0, float(v)))
        if self.gl.state != "speaking" and self.gl.level > 0.08:
            self.gl.state = "speaking"
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
                    self.win.gl.push_line(t)

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
            self.win.gl.push_line(arg)
            if self.win.gl.state not in ("tools", "thinking"):
                self.win.set_state("tools")
        elif op == "hide":
            self.win.hide_orb()
        elif op == "quit":
            self.quit()
        return False


if __name__ == "__main__":
    _log("start gl")
    App().run(None)
