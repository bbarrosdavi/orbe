#!/usr/bin/python3
"""Orbe: configurações do orbe de voz (GTK4 + libadwaita).

Janela pequena e flutuante, vidro fosco (o blur vem da regra do niri para o
app-id io.hermes.Orbe; a janela só pinta fundo translúcido). O processo sai
quando a janela fecha: nada fica residente.

Grava ~/.config/hermes-voice/config.json (hermes_voice_config.py), o atalho
em ~/.config/niri/dms/binds.kdl, e reinicia o hermes-voice ao aplicar.

O desenho do topo é um ophanim ("rodas dentro de rodas, os aros cheios de
olhos", Ezequiel 1:16-18 e 10:12): anéis girando em eixos diferentes, olhos
nos aros, com glitch errático (hermes_voice_avatares.py, o mesmo do orbe).

  hermes_voice_app.py              abre o app
  hermes_voice_app.py --captura P [páginas]  PNG de cada página em P_<página>.png
      (rodar com GDK_BACKEND=broadway num gtk4-broadwayd: nada aparece na tela)
"""
import json
import math
import os
import random
import re
import subprocess
import sys
import threading
import time
from pathlib import Path

import cairo

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
gi.require_version("Gsk", "4.0")
gi.require_version("Graphene", "1.0")
from gi.repository import Adw, Gdk, Gio, GLib, Graphene, Gsk, Gtk  # noqa: E402

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import hermes_voice_acp as acp  # noqa: E402
import hermes_voice_canal as canal  # noqa: E402
import hermes_voice_config as vcfg  # noqa: E402
import hermes_voice_avatares as avatares  # noqa: E402

APP_ID = "io.hermes.Orbe"
SERVICO = "hermes-voice"
BINDS = Path.home() / ".config" / "niri" / "dms" / "binds.kdl"
WAKE_DIR = Path.home() / ".hermes" / "cache" / "wakewords"
PIPER_DIR = Path.home() / ".hermes" / "piper_models"
JARVIS_CFG = Path.home() / ".hermes" / "profiles" / "jarvis" / "config.yaml"
# Linha do bind do orbe: só a tecla muda, o resto do bloco fica.
BIND_RE = re.compile(r'^(\s*)(\S+)(\s+hotkey-overlay-title="Voice Assistant \(Orb\)".*)$', re.M)

GEMINI_VOZES = [
    "Kore", "Puck", "Charon", "Fenrir", "Aoede", "Leda", "Orus", "Zephyr",
    "Callirrhoe", "Autonoe", "Enceladus", "Iapetus", "Umbriel", "Algieba",
    "Despina", "Erinome", "Algenib", "Rasalgethi", "Laomedeia", "Achernar",
    "Alnilam", "Schedar", "Gacrux", "Pulcherrima", "Achird", "Zubenelgenubi",
    "Vindemiatrix", "Sadachbia", "Sadaltager", "Sulafat",
]

CSS = """
window.orbe {
  background-color: alpha(@window_bg_color, 0.58);
  border-radius: 18px;
}
window.orbe headerbar {
  background: transparent;
  box-shadow: none;
  min-height: 34px;
}
window.orbe .legenda {
  font-family: monospace;
  font-size: 10px;
  letter-spacing: 3px;
  opacity: 0.6;
}
window.orbe preferencespage,
window.orbe preferencespage > scrolledwindow,
window.orbe preferencespage > scrolledwindow > viewport {
  background: transparent;
}
window.orbe list.boxed-list {
  background-color: alpha(@view_bg_color, 0.30);
  border: 1px solid alpha(@accent_bg_color, 0.16);
  box-shadow: none;
  border-radius: 12px;
}
window.orbe list.boxed-list > row {
  background: transparent;
}
window.orbe list.boxed-list > row:hover {
  background-color: alpha(@accent_bg_color, 0.07);
}
window.orbe .menu button {
  border-radius: 10px;
  padding: 4px 10px;
}
window.orbe .menu button:checked {
  background-color: alpha(@accent_bg_color, 0.20);
  color: @accent_bg_color;
}
window.orbe .menu button:focus:not(:checked) {
  background-color: transparent;
}
window.orbe .ofanim {
  color: @accent_bg_color;
}
window.orbe .cartao {
  padding: 6px 6px 8px 6px;
  border-radius: 14px;
  background-color: alpha(@window_fg_color, 0.04);
  border: 1px solid alpha(@window_fg_color, 0.08);
}
window.orbe .cartao:hover {
  background-color: alpha(@window_fg_color, 0.07);
}
window.orbe .cartao:checked {
  background-color: alpha(@accent_bg_color, 0.14);
  border-color: alpha(@accent_bg_color, 0.55);
  color: @accent_bg_color;
}
window.orbe .cartao label {
  font-size: 12px;
}
window.orbe .rodape {
  border-top: 1px solid alpha(@accent_bg_color, 0.12);
  padding: 8px 14px 10px 14px;
}
window.orbe .estado {
  font-family: monospace;
  font-size: 10px;
  opacity: 0.6;
}
window.orbe .tecla {
  font-family: monospace;
  font-weight: bold;
  padding: 3px 9px;
  border-radius: 7px;
  background-color: alpha(@accent_bg_color, 0.14);
  border: 1px solid alpha(@accent_bg_color, 0.30);
}
window.orbe textview, window.orbe textview text {
  background: transparent;
  font-size: 12px;
}
"""


# ═══════════════════════════════════════════
# Ofanim: rodas com olhos, com glitch
# ═══════════════════════════════════════════
def _cor_accent(widget) -> tuple[float, float, float]:
    """O CSS dá ao ofanim color: @accent_bg_color (matugen, vem do wallpaper)."""
    c = widget.get_color()
    return c.red, c.green, c.blue


class Ofanim(Gtk.DrawingArea):
    """Topo do app: o mesmo Ophanim do orbe. O olhar vem da janela inteira
    (ver Janela._seguir), não só de cima do desenho."""

    def __init__(self):
        super().__init__()
        self.set_content_height(196)
        self.set_hexpand(True)
        self.add_css_class("ofanim")
        self.set_draw_func(self._desenhar)
        self.arte = avatares.Ofanim()
        self._ultimo = None
        self._olhar = None            # ponteiro em coordenadas do widget
        self.add_tick_callback(self._tique)

    def _tique(self, _w, relogio):
        # 30 quadros/s com ou sem foco. O relógio de quadros do GTK para
        # sozinho com a janela escondida ou minimizada.
        agora = relogio.get_frame_time() / 1e6
        if self._ultimo is None:
            self._ultimo = agora
        dt = agora - self._ultimo
        if dt >= 1 / 30:
            self._ultimo = agora
            self.arte.avancar(min(dt, 0.1))
            self.queue_draw()
        return GLib.SOURCE_CONTINUE

    def _desenhar(self, _area, cr, w, h):
        self.arte.desenhar(cr, 0, 0, w, h, float(self.get_scale_factor()),
                           _cor_accent(self), self._olhar, R=min(h * 0.42, w * 0.32))


class Cartao(Gtk.ToggleButton):
    """Miniatura animada de um avatar no seletor da Aparência."""

    QUADROS_ANEL = os.path.join(os.path.dirname(os.path.abspath(__file__)), "orb_frames")

    def __init__(self, skin: str):
        super().__init__()
        self.skin = skin
        self.add_css_class("cartao")
        caixa = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        self.area = Gtk.DrawingArea(content_height=118, hexpand=True)
        self.area.add_css_class("ofanim")
        self.area.set_draw_func(self._desenhar)
        caixa.append(self.area)
        caixa.append(Gtk.Label(label=avatares.NOMES[skin]))
        self.set_child(caixa)
        self.arte = avatares.criar(skin)
        if self.arte is not None:
            self.arte.peso = 1.2
        self._quadros = None
        self._ultimo = None
        self._i = 0.0
        self.area.add_tick_callback(self._tique)

    def definir_glitch(self, ligado: bool):
        if self.arte is not None:
            self.arte.glitch = ligado

    def _tique(self, area, relogio):
        # Só anima com a página visível; 15 quadros/s bastam numa miniatura.
        if not area.get_mapped():
            self._ultimo = None
            return GLib.SOURCE_CONTINUE
        agora = relogio.get_frame_time() / 1e6
        if self._ultimo is None:
            self._ultimo = agora
        dt = agora - self._ultimo
        if dt >= 1 / 15:
            self._ultimo = agora
            if self.arte is not None:
                self.arte.avancar(min(dt, 0.1))
            self._i += dt * 20
            area.queue_draw()
        return GLib.SOURCE_CONTINUE

    def _desenhar(self, area, cr, w, h):
        cor = _cor_accent(area)
        if self.arte is not None:
            self.arte.desenhar(cr, 0, 0, w, h, float(self.get_scale_factor()), cor)
            return
        # anel: o rotoscope do orbe, 1 em cada 4 quadros, carregado só aqui
        if self._quadros is None:
            self._quadros = []
            for i in range(0, 62, 4):
                caminho = os.path.join(self.QUADROS_ANEL, f"f_{i:02d}.png")
                if os.path.exists(caminho):
                    self._quadros.append(cairo.ImageSurface.create_from_png(caminho))
        if not self._quadros:
            return
        q = self._quadros[int(self._i) % len(self._quadros)]
        lado = min(w, h) * 0.92
        e = lado / q.get_width()
        cr.translate((w - lado) / 2, (h - lado) / 2)
        cr.scale(e, e)
        cr.set_source_rgb(*cor)
        cr.mask_surface(q, 0, 0)


# ═══════════════════════════════════════════
# Linhas de configuração
# ═══════════════════════════════════════════
def _combo(titulo, itens, subtitulo="", busca=False):
    row = Adw.ComboRow(title=titulo, subtitle=subtitulo)
    row.set_model(Gtk.StringList.new([i[1] for i in itens]))
    row._ids = [i[0] for i in itens]
    if busca:
        row.set_enable_search(True)
        row.set_expression(Gtk.PropertyExpression.new(Gtk.StringObject, None, "string"))
    return row


def _combo_set(row, valor):
    ids = row._ids
    if valor in ids:
        row.set_selected(ids.index(valor))
    elif ids:
        row.set_selected(0)


def _combo_get(row):
    i = row.get_selected()
    return row._ids[i] if 0 <= i < len(row._ids) else ""


def _spin(titulo, lo, hi, passo, digitos=0, subtitulo=""):
    row = Adw.SpinRow.new_with_range(lo, hi, passo)
    row.set_title(titulo)
    row.set_digits(digitos)
    if subtitulo:
        row.set_subtitle(subtitulo)
    return row


def _arquivos(pasta: Path, sufixos: tuple) -> list:
    try:
        return sorted(str(p) for p in pasta.iterdir() if p.suffix in sufixos and p.is_file())
    except OSError:
        return []


def _tts_do_perfil() -> str:
    try:
        for linha in JARVIS_CFG.read_text().splitlines():
            if linha.startswith("  provider:"):
                return linha.split(":", 1)[1].strip()
    except OSError:
        pass
    return "?"


def _atalho_atual() -> str:
    try:
        m = BIND_RE.search(BINDS.read_text())
        return m.group(2) if m else ""
    except OSError:
        return ""


def _gravar_atalho(novo: str) -> str:
    """Troca a tecla do bind do orbe. Devolve erro ('' = ok).

    Valida numa cópia do config do niri antes de tocar no arquivo real: o
    niri relê o binds.kdl a cada gravação e avisaria na tela se lesse um
    config inválido.
    """
    import shutil
    import tempfile
    try:
        texto = BINDS.read_text()
    except OSError as e:
        return str(e)
    m = BIND_RE.search(texto)
    if not m:
        return "bind do orbe não encontrado em binds.kdl"
    if m.group(2) == novo:
        return ""
    for outra in re.finditer(r"^[ \t]*(\S+)[ \t]+[^\n]*\{[ \t]*$", texto, re.M):
        if outra.group(1).lower() == novo.lower() and outra.start(1) != m.start(2):
            return f"{novo} já é usado por outro atalho"
    novo_texto = texto[:m.start(2)] + novo + texto[m.end(2):]
    raiz = BINDS.parent.parent
    with tempfile.TemporaryDirectory() as tmp:
        copia = Path(tmp) / "niri"
        shutil.copytree(raiz, copia, symlinks=True)
        (copia / BINDS.relative_to(raiz)).write_text(novo_texto)
        r = subprocess.run(["niri", "validate", "-c", str(copia / "config.kdl")],
                           capture_output=True, text=True)
    if r.returncode != 0:
        return "o niri recusou o atalho: " + (r.stderr or r.stdout).strip()[-200:]
    BINDS.write_text(novo_texto)
    return ""


def _nome_tecla(keyval, estado) -> str | None:
    nome = Gdk.keyval_name(Gdk.keyval_to_upper(keyval)) or ""
    if not nome or nome.startswith(("Super", "Control", "Alt", "Shift", "Meta", "ISO_", "Hyper")):
        return None
    partes = []
    if estado & Gdk.ModifierType.SUPER_MASK:
        partes.append("Mod")
    if estado & Gdk.ModifierType.CONTROL_MASK:
        partes.append("Ctrl")
    if estado & Gdk.ModifierType.ALT_MASK:
        partes.append("Alt")
    if estado & Gdk.ModifierType.SHIFT_MASK:
        partes.append("Shift")
    return "+".join(partes + [nome])


def _agente_carregado() -> tuple[str, int] | None:
    """(nome, MB) do processo de agente ACP filho do daemon, se houver."""
    marcas = (("acp --accept-hooks", "Hermes"), ("opencode acp", "OpenCode"), ("--acp", "Gemini CLI"))
    for pid in os.listdir("/proc"):
        if not pid.isdigit():
            continue
        try:
            cmd = open(f"/proc/{pid}/cmdline", "rb").read().replace(b"\0", b" ").decode("utf-8", "replace")
        except OSError:
            continue
        for marca, nome in marcas:
            if marca in cmd and "hermes_voice_app" not in cmd:
                try:
                    rss = int(next(l for l in open(f"/proc/{pid}/status") if l.startswith("VmRSS")).split()[1])
                except (OSError, StopIteration):
                    rss = 0
                return nome, rss // 1024
    return None


# ═══════════════════════════════════════════
# Janela
# ═══════════════════════════════════════════
class Janela(Adw.ApplicationWindow):
    def __init__(self, app):
        super().__init__(application=app, title="Orbe")
        self.add_css_class("orbe")
        self.set_default_size(500, 700)
        self.cfg = vcfg.carregar()
        self.atalho = _atalho_atual() or self.cfg["ativacao"]["atalho"]

        topo = Adw.HeaderBar(decoration_layout=":close")
        topo.set_title_widget(Gtk.Box())

        self.anjo = Ofanim()
        mov = Gtk.EventControllerMotion()
        mov.connect("motion", self._seguir)
        mov.connect("leave", lambda _c: setattr(self.anjo, "_olhar", None))
        self.add_controller(mov)
        self.legenda = Gtk.Label(label="ORBE")
        self.legenda.add_css_class("legenda")
        self.legenda.set_margin_bottom(4)

        self.pilha = Adw.ViewStack()
        self.pilha.set_vexpand(True)
        # Menu próprio: o Adw.ViewSwitcher reparte a largura em partes iguais
        # e corta "Ativação"/"Conversa" numa janela de 500 px.
        menu = Gtk.Box(spacing=2, halign=Gtk.Align.CENTER)
        menu.add_css_class("menu")
        menu.set_margin_top(2)
        menu.set_margin_bottom(6)
        self.menu = menu
        self._botoes = {}

        self._pagina_agente()
        self._pagina_ativacao()
        self._pagina_voz()
        self._pagina_conversa()
        self._pagina_aparencia()

        self.estado = Gtk.Label(xalign=0, hexpand=True)
        self.estado.add_css_class("estado")
        self.estado.set_ellipsize(3)
        aplicar = Gtk.Button(label="Aplicar")
        aplicar.add_css_class("suggested-action")
        aplicar.add_css_class("pill")
        aplicar.connect("clicked", self._aplicar)
        rodape = Gtk.Box(spacing=10)
        rodape.add_css_class("rodape")
        rodape.append(self.estado)
        rodape.append(aplicar)

        corpo = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        corpo.append(self.anjo)
        corpo.append(self.legenda)
        corpo.append(menu)
        corpo.append(self.pilha)

        vista = Adw.ToolbarView()
        vista.add_top_bar(topo)
        vista.set_content(corpo)
        vista.add_bottom_bar(rodape)
        self.toasts = Adw.ToastOverlay(child=vista)
        self.set_content(self.toasts)

        # Sem foco inicial no menu: o tema pinta o botão focado como marcado.
        self.connect("map", lambda *_: GLib.idle_add(lambda: self.set_focus(None)))
        self._carregar()
        self._atualizar_estado()
        GLib.timeout_add_seconds(3, self._atualizar_estado)

    # ── páginas ──

    def _seguir(self, _ctl, x, y):
        """Ponteiro em qualquer ponto da janela, nas coordenadas do herói."""
        ok, p = self.compute_point(self.anjo, Graphene.Point().init(x, y))
        self.anjo._olhar = (p.x, p.y) if ok else None

    def _pagina(self, nome, titulo, icone):
        pag = Adw.PreferencesPage()
        self.pilha.add_named(pag, nome)
        conteudo = Gtk.Box(spacing=6)
        conteudo.append(Gtk.Image(icon_name=icone))
        conteudo.append(Gtk.Label(label=titulo))
        b = Gtk.ToggleButton(child=conteudo)
        b.add_css_class("flat")
        if self._botoes:
            b.set_group(next(iter(self._botoes.values())))
        else:
            b.set_active(True)
        b.connect("toggled", lambda bt, n=nome: bt.get_active() and self.pilha.set_visible_child_name(n))
        self._botoes[nome] = b
        self.menu.append(b)
        return pag

    def _pagina_agente(self):
        pag = self._pagina("agente", "Agente", "network-server-symbolic")
        g = Adw.PreferencesGroup(description="Quem responde: um agente ACP ou o Claude aberto no terminal.")
        itens = [(t, acp.NOMES[t] + ("" if acp.disponivel(t) else " (não instalado)"))
                 for t in ("hermes", "opencode", "gemini", "claude", "comando")]
        self.r_agente = _combo("Agente", itens)
        self.r_perfil = _combo("Perfil do Hermes", [(p, p) for p in acp.perfis_hermes()])
        self.r_comando = Adw.EntryRow(title="Comando ACP")
        self.r_modelo = _combo("Modelo", [("", "Padrão do agente")], busca=True)
        consultar = Gtk.Button(icon_name="view-refresh-symbolic", valign=Gtk.Align.CENTER,
                               tooltip_text="Consultar os modelos que o agente oferece")
        consultar.add_css_class("flat")
        consultar.connect("clicked", self._consultar_modelos)
        self.b_consultar = consultar
        self.r_modelo.add_suffix(consultar)
        self.r_claude = Adw.ActionRow(title="Sessão do Claude")
        rever = Gtk.Button(icon_name="view-refresh-symbolic", valign=Gtk.Align.CENTER,
                           tooltip_text="Procurar sessões abertas")
        rever.add_css_class("flat")
        rever.connect("clicked", lambda *_: self._sessoes_claude())
        self.r_claude.add_suffix(rever)
        for r in (self.r_agente, self.r_perfil, self.r_comando, self.r_modelo, self.r_claude):
            g.add(r)
        self.r_agente.connect("notify::selected", lambda *_: self._mudou_agente())
        self.r_perfil.connect("notify::selected", lambda *_: self._mudou_agente())
        pag.add(g)

        g2 = Adw.PreferencesGroup(title="Memória")
        self.r_manter = _spin("Descarregar o agente após", 0, 240, 5,
                              subtitulo="minutos sem sessão de voz; 0 mantém sempre carregado")
        g2.add(self.r_manter)
        pag.add(g2)

        g3 = Adw.PreferencesGroup(title="Instrução de voz",
                                  description="Vai no primeiro pedido de cada conversa, para agentes "
                                              "sem perfil de voz. O Hermes usa o SOUL do perfil; "
                                              "o Claude recebe junto do canal, ao abrir a sessão.")
        self.t_instrucao = Gtk.TextView(wrap_mode=Gtk.WrapMode.WORD_CHAR, top_margin=10,
                                        bottom_margin=10, left_margin=12, right_margin=12)
        quadro = Gtk.Frame(child=self.t_instrucao)
        quadro.add_css_class("card")
        quadro.set_size_request(-1, 96)
        g3.add(quadro)
        pag.add(g3)

    def _pagina_ativacao(self):
        pag = self._pagina("ativacao", "Ativação", "audio-input-microphone-symbolic")
        g = Adw.PreferencesGroup(title="Atalho")
        self.r_atalho = Adw.ActionRow(title="Abrir o orbe")
        self.l_atalho = Gtk.Label(valign=Gtk.Align.CENTER)
        self.l_atalho.add_css_class("tecla")
        gravar = Gtk.Button(label="Gravar", valign=Gtk.Align.CENTER)
        gravar.add_css_class("flat")
        gravar.connect("clicked", self._capturar_atalho)
        self.r_atalho.add_suffix(self.l_atalho)
        self.r_atalho.add_suffix(gravar)
        g.add(self.r_atalho)
        pag.add(g)

        g2 = Adw.PreferencesGroup(title="Palavra de ativação")
        self.r_wake = _combo("Provedor", [
            ("nenhum", "Nenhum (atalho e toque)"),
            ("openwakeword", "openWakeWord"),
            ("sherpa", "sherpa-onnx (frase livre)"),
            ("microwakeword", "microWakeWord"),
        ])
        self.r_frase = Adw.EntryRow(title="Frase")
        oww = _arquivos(WAKE_DIR, (".onnx",))
        mww = _arquivos(WAKE_DIR, (".tflite",))
        self.r_oww = _combo("Modelo", [(p, Path(p).name) for p in oww] or [("", "nenhum .onnx")])
        self.r_mww = _combo("Modelo", [(p, Path(p).name) for p in mww] or [("", "nenhum .tflite")])
        self.r_limiar = _spin("Limiar", 0.05, 0.99, 0.01, 2, "mais alto = mais exigente")
        self.r_confirma = _spin("Confirmação", 1, 10, 1, subtitulo="quadros seguidos acima do limiar")
        for r in (self.r_wake, self.r_frase, self.r_oww, self.r_mww, self.r_limiar, self.r_confirma):
            g2.add(r)
        self.r_wake.connect("notify::selected", lambda *_: self._mudou_wake())
        pag.add(g2)

    def _pagina_voz(self):
        pag = self._pagina("voz", "Voz", "audio-speakers-symbolic")
        g = Adw.PreferencesGroup(title="Transcrição", description="Groq Whisper")
        self.r_stt = _combo("Modelo", [("whisper-large-v3-turbo", "whisper-large-v3-turbo"),
                                       ("whisper-large-v3", "whisper-large-v3")])
        self.r_idioma = Adw.EntryRow(title="Idioma (código ISO)")
        g.add(self.r_stt)
        g.add(self.r_idioma)
        pag.add(g)

        g2 = Adw.PreferencesGroup(title="Síntese")
        self.r_tts = _combo("Provedor", [
            ("", f"O do perfil jarvis ({_tts_do_perfil()})"),
            ("gemini", "Gemini"), ("xai", "xAI"), ("piper", "Piper (local)"),
        ])
        self.r_gvoz = _combo("Voz Gemini", [("", "A do perfil")] + [(v, v) for v in GEMINI_VOZES], busca=True)
        self.r_xvoz = Adw.EntryRow(title="Voz xAI (vazio = a do perfil)")
        piper = _arquivos(PIPER_DIR, (".onnx",))
        self.r_pvoz = _combo("Voz Piper", [("", "A do perfil")] + [(p, Path(p).stem) for p in piper])
        for r in (self.r_tts, self.r_gvoz, self.r_xvoz, self.r_pvoz):
            g2.add(r)
        self.r_tts.connect("notify::selected", lambda *_: self._mudou_tts())
        pag.add(g2)

    def _pagina_conversa(self):
        pag = self._pagina("conversa", "Conversa", "user-available-symbolic")
        g = Adw.PreferencesGroup(title="Interrupção")
        self.r_barge = Adw.SwitchRow(title="Interromper pela voz",
                                     subtitle="falar por cima corta a fala e o raciocínio")
        self.r_bq = _spin("Voz sustentada", 2, 60, 1, subtitulo="quadros de 30 ms")
        self.r_brms = _spin("Piso de volume", 300, 12000, 100, subtitulo="RMS")
        for r in (self.r_barge, self.r_bq, self.r_brms):
            g.add(r)
        pag.add(g)

        g2 = Adw.PreferencesGroup(title="Fala")
        self.r_sil = _spin("Silêncio que fecha a fala", 0.3, 3.0, 0.05, 2, "segundos")
        self.r_frms = _spin("Piso de fala", 300, 12000, 100, subtitulo="RMS")
        self.r_fq = _spin("Voz para abrir gravação", 2, 60, 1, subtitulo="quadros de 30 ms")
        self.r_gmax = _spin("Gravação máxima", 3, 120, 1, subtitulo="segundos")
        self.r_ocio = _spin("Sessão ociosa fecha em", 3, 600, 1, subtitulo="segundos")
        for r in (self.r_sil, self.r_frms, self.r_fq, self.r_gmax, self.r_ocio):
            g2.add(r)
        pag.add(g2)

        g3 = Adw.PreferencesGroup(title="Toque no orbe")
        self.r_segurar = _spin("Segurar para gravar", 0.1, 2.0, 0.05, 2, "segundos; menos que isso só interrompe")
        self.r_tmax = _spin("Gravação máxima segurando", 10, 300, 5, subtitulo="segundos")
        g3.add(self.r_segurar)
        g3.add(self.r_tmax)
        pag.add(g3)

        g4 = Adw.PreferencesGroup(title="Diagnóstico")
        self.r_rastro = Adw.SwitchRow(title="Rastro de níveis no log", subtitle="uma linha por segundo no journal")
        g4.add(self.r_rastro)
        pag.add(g4)

    def _pagina_aparencia(self):
        pag = self._pagina("aparencia", "Aparência", "applications-graphics-symbolic")
        g = Adw.PreferencesGroup(title="Avatar do orbe")
        grade = Gtk.Grid(column_spacing=10, row_spacing=10, column_homogeneous=True)
        self.cartoes = {}
        primeiro = None
        for i, sk in enumerate(("ofanim", "ofanim_alado", "serafim", "anel")):
            c = Cartao(sk)
            if primeiro is None:
                primeiro = c
            else:
                c.set_group(primeiro)
            grade.attach(c, i % 2, i // 2, 1, 1)
            self.cartoes[sk] = c
        g.add(grade)
        pag.add(g)

        g2 = Adw.PreferencesGroup()
        self.r_glitch = Adw.SwitchRow(title="Glitch",
                                      subtitle="aberração cromática, faixas arrancadas e linhas de varredura")
        self.r_glitch.connect("notify::active", lambda *_: [
            c.definir_glitch(self.r_glitch.get_active()) for c in self.cartoes.values()])
        self.r_vidro = Adw.SwitchRow(title="Fundo de vidro fosco",
                                     subtitle="disco translúcido com blur atrás do orbe, como esta janela")
        g2.add(self.r_glitch)
        g2.add(self.r_vidro)
        pag.add(g2)

    # ── carregar / coletar ──

    def _carregar(self):
        a, at, v, c, t = (self.cfg[k] for k in ("agente", "ativacao", "voz", "conversa", "toque"))
        _combo_set(self.r_agente, a["tipo"])
        _combo_set(self.r_perfil, a["perfil"])
        self.r_comando.set_text(a["comando"])
        self.r_manter.set_value(float(a["manter_carregado_min"]))
        self.t_instrucao.get_buffer().set_text(a["instrucao_voz"])
        self._modelos_do_estado()
        _combo_set(self.r_modelo, a["modelo"])

        self.l_atalho.set_label(self.atalho)
        _combo_set(self.r_wake, at["provedor"])
        self.r_frase.set_text(at["frase"])
        _combo_set(self.r_oww, at["oww_modelo"])
        _combo_set(self.r_mww, at["mww_modelo"])
        self.r_confirma.set_value(at["confirmacao"])

        _combo_set(self.r_stt, v["stt_modelo"])
        self.r_idioma.set_text(v["stt_idioma"])
        _combo_set(self.r_tts, v["tts_provedor"])
        _combo_set(self.r_gvoz, v["gemini_voz"])
        self.r_xvoz.set_text(v["xai_voz"])
        _combo_set(self.r_pvoz, v["piper_voz"])

        self.r_barge.set_active(bool(c["barge_in"]))
        self.r_bq.set_value(c["barge_quadros"])
        self.r_brms.set_value(c["barge_rms"])
        self.r_sil.set_value(c["silencio_fim_s"])
        self.r_frms.set_value(c["fala_rms"])
        self.r_fq.set_value(c["fala_quadros"])
        self.r_gmax.set_value(c["gravacao_max_s"])
        self.r_ocio.set_value(c["sessao_ociosa_s"])
        self.r_segurar.set_value(t["segurar_s"])
        self.r_tmax.set_value(t["gravacao_max_s"])
        self.r_rastro.set_active(bool(self.cfg["diagnostico"]["rastro_niveis"]))
        o = self.cfg["orbe"]
        (self.cartoes.get(o["skin"]) or self.cartoes["ofanim"]).set_active(True)
        self.r_glitch.set_active(bool(o["glitch"]))
        self.r_vidro.set_active(bool(o["vidro"]))
        self._mudou_agente(inicial=True)
        self._mudou_wake()
        self._mudou_tts()

    def _coletar(self) -> dict:
        cfg = json.loads(json.dumps(self.cfg))
        a, at, v, c, t = (cfg[k] for k in ("agente", "ativacao", "voz", "conversa", "toque"))
        a["tipo"] = _combo_get(self.r_agente)
        a["perfil"] = _combo_get(self.r_perfil)
        a["comando"] = self.r_comando.get_text().strip()
        a["modelo"] = _combo_get(self.r_modelo)
        a["manter_carregado_min"] = int(self.r_manter.get_value())
        buf = self.t_instrucao.get_buffer()
        a["instrucao_voz"] = buf.get_text(buf.get_start_iter(), buf.get_end_iter(), False).strip()
        at["provedor"] = _combo_get(self.r_wake)
        at["frase"] = self.r_frase.get_text().strip() or at["frase"]
        if _combo_get(self.r_oww):
            at["oww_modelo"] = _combo_get(self.r_oww)
        if _combo_get(self.r_mww):
            at["mww_modelo"] = _combo_get(self.r_mww)
        chave = {"openwakeword": "limiar_oww", "sherpa": "limiar_sherpa",
                 "microwakeword": "limiar_mww"}.get(at["provedor"])
        if chave:
            at[chave] = round(self.r_limiar.get_value(), 2)
        at["confirmacao"] = int(self.r_confirma.get_value())
        at["atalho"] = self.atalho
        v["stt_modelo"] = _combo_get(self.r_stt)
        v["stt_idioma"] = self.r_idioma.get_text().strip() or "pt"
        v["tts_provedor"] = _combo_get(self.r_tts)
        v["gemini_voz"] = _combo_get(self.r_gvoz)
        v["xai_voz"] = self.r_xvoz.get_text().strip()
        v["piper_voz"] = _combo_get(self.r_pvoz)
        c["barge_in"] = self.r_barge.get_active()
        c["barge_quadros"] = int(self.r_bq.get_value())
        c["barge_rms"] = int(self.r_brms.get_value())
        c["silencio_fim_s"] = round(self.r_sil.get_value(), 2)
        c["fala_rms"] = int(self.r_frms.get_value())
        c["fala_quadros"] = int(self.r_fq.get_value())
        c["gravacao_max_s"] = int(self.r_gmax.get_value())
        c["sessao_ociosa_s"] = float(self.r_ocio.get_value())
        t["segurar_s"] = round(self.r_segurar.get_value(), 2)
        t["gravacao_max_s"] = float(self.r_tmax.get_value())
        cfg["diagnostico"]["rastro_niveis"] = self.r_rastro.get_active()
        cfg["orbe"]["skin"] = next((k for k, c in self.cartoes.items() if c.get_active()), "ofanim")
        cfg["orbe"]["glitch"] = self.r_glitch.get_active()
        cfg["orbe"]["vidro"] = self.r_vidro.get_active()
        return cfg

    # ── reações ──

    def _chave_agente(self) -> str:
        tipo = _combo_get(self.r_agente)
        return "|".join((tipo, _combo_get(self.r_perfil) if tipo == "hermes" else "",
                         self.r_comando.get_text().strip() if tipo == "comando" else ""))

    def _preencher_modelos(self, modelos, atual=""):
        escolhido = _combo_get(self.r_modelo) or self.cfg["agente"]["modelo"]
        itens = [("", "Padrão do agente" + (f" ({atual})" if atual else ""))]
        itens += [(m["id"], m["nome"] if m["nome"] == m["id"] else f'{m["nome"]}  ·  {m["id"]}')
                  for m in modelos]
        self.r_modelo.set_model(Gtk.StringList.new([i[1] for i in itens]))
        self.r_modelo._ids = [i[0] for i in itens]
        _combo_set(self.r_modelo, escolhido)

    def _modelos_do_estado(self):
        est = vcfg.ler_estado()
        if est.get("chave") == self._chave_agente() and est.get("modelos"):
            self._preencher_modelos(est["modelos"], est.get("modelo_atual", ""))
            self.r_modelo.set_subtitle(f'{len(est["modelos"])} modelos')
        else:
            self._preencher_modelos([])
            self.r_modelo.set_subtitle("consulte para listar os modelos")

    def _mudou_agente(self, inicial=False):
        tipo = _combo_get(self.r_agente)
        self.r_perfil.set_visible(tipo == "hermes")
        self.r_comando.set_visible(tipo == "comando")
        self.r_modelo.set_visible(tipo != "claude")
        self.r_claude.set_visible(tipo == "claude")
        if tipo == "claude":
            self._sessoes_claude()
        if not inicial:
            self._modelos_do_estado()

    def _sessoes_claude(self):
        s = canal.sessoes()
        if not s:
            self.r_claude.set_subtitle("nenhuma aberta com o canal; abra o Claude com claude-orbe")
            return
        cwd = s[0].get("cwd") or "?"
        cwd = cwd.replace(str(Path.home()), "~", 1)
        mais = f" (de {len(s)} abertas)" if len(s) > 1 else ""
        self.r_claude.set_subtitle(f"fala com a mais recente{mais}: {cwd}")

    def _consultar_modelos(self, _b):
        agente = {"tipo": _combo_get(self.r_agente), "perfil": _combo_get(self.r_perfil),
                  "comando": self.r_comando.get_text().strip()}
        self.b_consultar.set_sensitive(False)
        self.r_modelo.set_subtitle("consultando o agente…")

        def trabalho():
            rt = None
            if agente["tipo"] == "hermes":
                try:
                    rt = json.loads(subprocess.check_output(
                        [acp.HERMES_LAUNCHER, "--print-runtime-command", "--"], text=True, timeout=30))
                except Exception:
                    rt = None
            try:
                r = acp.sondar(agente, rt)
                GLib.idle_add(self._modelos_consultados, r, "")
            except Exception as e:
                GLib.idle_add(self._modelos_consultados, None, str(e))
        threading.Thread(target=trabalho, daemon=True).start()

    def _modelos_consultados(self, r, erro):
        self.b_consultar.set_sensitive(True)
        if r is None:
            self.r_modelo.set_subtitle("falhou: " + erro[:80])
            return False
        self._preencher_modelos(r["modelos"], r["atual"])
        self.r_modelo.set_subtitle(f'{len(r["modelos"])} modelos' if r["modelos"]
                                   else "o agente não oferece troca de modelo")
        return False

    def _mudou_wake(self):
        p = _combo_get(self.r_wake)
        at = self.cfg["ativacao"]
        self.r_frase.set_visible(p == "sherpa")
        self.r_oww.set_visible(p == "openwakeword")
        self.r_mww.set_visible(p == "microwakeword")
        self.r_limiar.set_visible(p != "nenhum")
        self.r_confirma.set_visible(p in ("openwakeword", "microwakeword"))
        custo = {"nenhum": "nenhum modelo carregado",
                 "openwakeword": "~130 MB no daemon",
                 "sherpa": "~95 MB no daemon",
                 "microwakeword": "~520 MB num processo à parte (TensorFlow)"}.get(p, "")
        self.r_wake.set_subtitle(custo)
        lim = {"openwakeword": at["limiar_oww"], "sherpa": at["limiar_sherpa"],
               "microwakeword": at["limiar_mww"]}.get(p)
        if lim is not None:
            self.r_limiar.set_value(float(lim))

    def _mudou_tts(self):
        p = _combo_get(self.r_tts) or _tts_do_perfil()
        self.r_gvoz.set_visible(p == "gemini")
        self.r_xvoz.set_visible(p in ("xai", "grok", "xai-oauth"))
        self.r_pvoz.set_visible(p == "piper")

    def _capturar_atalho(self, _b):
        dialogo = Adw.AlertDialog(heading="Novo atalho",
                                  body="Pressione a combinação de teclas. Esc cancela.")
        dialogo.add_response("cancelar", "Cancelar")
        teclas = Gtk.EventControllerKey()

        def pressionou(_c, keyval, _code, estado):
            if keyval == Gdk.KEY_Escape:
                dialogo.close()
                return True
            nome = _nome_tecla(keyval, estado)
            if nome:
                self.atalho = nome
                self.l_atalho.set_label(nome)
                dialogo.close()
            return True
        teclas.connect("key-pressed", pressionou)
        dialogo.add_controller(teclas)
        dialogo.present(self)

    def _atualizar_estado(self):
        try:
            ativo = subprocess.run(["systemctl", "--user", "is-active", SERVICO],
                                   capture_output=True, text=True, timeout=2).stdout.strip()
        except Exception:
            ativo = "?"
        ag = _agente_carregado()
        txt = "serviço " + ("ativo" if ativo == "active" else ativo)
        txt += f"  ·  {ag[0]} carregado, {ag[1]} MB" if ag else "  ·  agente descarregado"
        self.estado.set_label(txt)
        return GLib.SOURCE_CONTINUE

    def _aplicar(self, _b):
        novo = self._coletar()
        erro = ""
        if self.atalho != _atalho_atual():
            erro = _gravar_atalho(self.atalho)
            if erro:
                self.atalho = _atalho_atual()
                self.l_atalho.set_label(self.atalho)
                novo["ativacao"]["atalho"] = self.atalho
        sem_atalho = lambda c: {**c, "ativacao": {**c["ativacao"], "atalho": ""}}  # noqa: E731
        mudou = sem_atalho(novo) != sem_atalho(self.cfg)
        vcfg.salvar(novo)
        self.cfg = novo
        if erro:
            self.toasts.add_toast(Adw.Toast(title=erro, timeout=6))
            return
        if mudou:
            subprocess.Popen(["systemctl", "--user", "restart", SERVICO],
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            self.toasts.add_toast(Adw.Toast(title="Aplicado. Orbe reiniciado.", timeout=3))
        else:
            self.toasts.add_toast(Adw.Toast(title="Aplicado.", timeout=2))


class App(Adw.Application):
    def __init__(self, captura=None):
        flags = Gio.ApplicationFlags.NON_UNIQUE if captura else Gio.ApplicationFlags.DEFAULT_FLAGS
        super().__init__(application_id=APP_ID, flags=flags)
        self.captura = captura

    def do_activate(self):
        janela = self.props.active_window
        if janela is None:
            Adw.StyleManager.get_default().set_color_scheme(Adw.ColorScheme.PREFER_DARK)
            prov = Gtk.CssProvider()
            prov.load_from_string(CSS)
            Gtk.StyleContext.add_provider_for_display(
                Gdk.Display.get_default(), prov, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
            janela = Janela(self)
        janela.present()
        if self.captura:
            GLib.timeout_add(1500, self._capturar, janela, 0)

    def _capturar(self, j, i):
        """Modo --captura: um PNG por página, renderizado pelo próprio GTK."""
        destino, paginas = self.captura
        if i >= len(paginas):
            self.quit()
            return False
        j._botoes[paginas[i]].set_active(True)

        def tirar():
            gi.require_version("Graphene", "1.0")
            from gi.repository import Graphene
            w, h = j.get_width(), j.get_height()
            ret = Graphene.Rect().init(0, 0, w, h)
            snap = Gtk.Snapshot()
            # "papel de parede" atrás do vidro, para ver a translucidez
            fundo = Gtk.Snapshot()
            stops = []
            for pos, cor in ((0.0, "#1b2a3a"), (0.5, "#3a2236"), (1.0, "#14302c")):
                st = Gsk.ColorStop()
                st.offset = pos
                c = Gdk.RGBA()
                c.parse(cor)
                st.color = c
                stops.append(st)
            p0 = Graphene.Point().init(0, 0)
            p1 = Graphene.Point().init(w, h)
            fundo.append_linear_gradient(ret, p0, p1, stops)
            snap.append_node(fundo.to_node())
            Gtk.WidgetPaintable.new(j).snapshot(snap, w, h)
            tex = j.get_renderer().render_texture(snap.to_node(), ret)
            tex.save_to_png(f"{destino}_{paginas[i]}.png")
            GLib.timeout_add(50, self._capturar, j, i + 1)
            return False
        GLib.timeout_add(400, tirar)
        return False


def main():
    if "--captura" in sys.argv:
        k = sys.argv.index("--captura")
        destino, paginas = sys.argv[k + 1], sys.argv[k + 2:] or ["agente"]
        App(captura=(destino, paginas)).run([sys.argv[0]])
        return
    App().run([sys.argv[0]])


if __name__ == "__main__":
    main()
