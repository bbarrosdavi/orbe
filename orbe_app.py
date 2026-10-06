#!/usr/bin/python3
"""Orbe: configurações do orbe de voz (Qt Quick, desenho na GPU).

Janela pequena e flutuante, vidro fosco (o blur vem da regra do niri para o
app-id io.orbe.Orbe; a janela só pinta fundo translúcido). O processo sai
quando a janela fecha: nada fica residente.

A interface é QML (orbe-qt/app); as figuras do topo, dos cartões e do botão
do tamanho são os mesmos componentes do orbe (orbe-qt/comum), em shaders.
Este arquivo é a ponte: lê e grava ~/.config/orbe/config.json
(orbe_config.py), troca o atalho em ~/.config/niri/dms/binds.kdl,
consulta agentes e sessões do Claude e reinicia o orbe ao aplicar.
No macOS o atalho fica só no config (o orbe registra a tecla), o serviço é
um LaunchAgent e a pré-visualização é o orbe_mac.py.

  orbe_app.py              abre o app
  orbe_app.py --previa     abre o app com a pré-visualização do orbe ligada
  orbe_app.py --captura P [páginas]  PNG de cada página em P_<página>.png
      (renderizado offscreen pela GPU, sem janela)
"""
import ctypes
import ctypes.util
import json
import math
import os
import random
import re
import socket
import subprocess
import sys
import threading
import time
from pathlib import Path

from PySide6.QtCore import (QEvent, QObject, QProcess, QProcessEnvironment, Property, QTimer,
                            QUrl, Qt, Signal, Slot)
from PySide6.QtGui import (QColor, QFont, QGuiApplication, QIcon, QPainter,
                           QPainterPath, QPalette, QPen, QPixmap)
from PySide6.QtNetwork import QLocalServer, QLocalSocket
from PySide6.QtQml import QJSValue, QQmlApplicationEngine
from PySide6.QtQuick import QQuickImageProvider, QQuickWindow

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import orbe_acp as acp  # noqa: E402
import orbe_canal as canal  # noqa: E402
import orbe_config as vcfg  # noqa: E402
import orbe_relogio as relogio  # noqa: E402

APP_ID = "io.orbe.Orbe"
SERVICO = vcfg.SERVICO
MAC = vcfg.MAC
QML_DIR = Path(__file__).resolve().parent / "orbe-qt" / "app"
ORBE_QML = Path(__file__).resolve().parent / "orbe-qt" / "orbe.qml"
ORBE_MAC = Path(__file__).resolve().parent / "orbe-qt" / "orbe_mac.py"
# Pré-visualização: uma instância do orbe ao lado da do daemon, com socket e
# config próprios. O toque vai para um socket sem ouvinte, longe do daemon.
RUNTIME = vcfg.RUNTIME
PREVIA_SOCK = RUNTIME / "orbe-previa.sock"
PREVIA_CFG = RUNTIME / "orbe-previa.json"
PREVIA_CTL = RUNTIME / "orbe-previa-ctl.sock"
# Ciclo da prévia: todos os estados, com som simulado onde o orbe reage a ele
# (mic ao ouvir, nível e tom da voz ao responder). Nenhum áudio é tocado.
PREVIA_CICLO = [("idle", "idle", 4.0), ("listening", "ouvindo", 5.0),
                ("thinking", "pensando", 5.0), ("speaking", "respondendo", 6.0)]
PREVIA_LINHAS = [
    "Pedido: resumir as mensagens não lidas de hoje.",
    "Começo pelas conversas com menções diretas.",
    "São três threads; a mais longa trata do prazo da entrega.",
    "Junto um resumo de uma frase por thread e respondo.",
]
BINDS = Path.home() / ".config" / "niri" / "dms" / "binds.kdl"
DANK_CSS = Path.home() / ".config" / "gtk-4.0" / "dank-colors.css"
ACCENT_CSS = Path.home() / "Projetos/Docs_rice_sistema/main.css"
WAKE_DIR = vcfg.dado("ativacao", "cache/wakewords")
PIPER_DIR = vcfg.dado("piper", "piper_models")
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
NOMES_SKIN = {"ofanim": "Ophanim", "ofanim_alado": "Ophanim com asas", "serafim_gravura": "Seraphim (gravura)",
              "olho": "Olho", "humana": "Humana", "anel": "Anel de energia"}


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
    if MAC:
        return vcfg.carregar()["ativacao"]["atalho"]
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
    if MAC:
        return ""   # o aplicar grava no config e o orbe re-registra a tecla
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


# Nome da tecla no formato do niri: o keysym do xkb, como o GDK dava. No
# Wayland o Qt entrega o keysym em nativeVirtualKey.
try:
    _XKB = ctypes.CDLL(ctypes.util.find_library("xkbcommon") or "libxkbcommon.so.0")
except OSError:
    _XKB = None


# Qt → nome do keysym do xkb, para o macOS (sem libxkbcommon). Letras e
# dígitos saem do próprio código da tecla.
_TECLAS_MAC = {
    Qt.Key.Key_Space: "space", Qt.Key.Key_Return: "Return", Qt.Key.Key_Enter: "Return",
    Qt.Key.Key_Tab: "Tab", Qt.Key.Key_Backspace: "BackSpace", Qt.Key.Key_Comma: "comma",
    Qt.Key.Key_Period: "period", Qt.Key.Key_Slash: "slash", Qt.Key.Key_Semicolon: "semicolon",
    Qt.Key.Key_Minus: "minus", Qt.Key.Key_Equal: "equal", Qt.Key.Key_QuoteLeft: "grave",
    Qt.Key.Key_Apostrophe: "apostrophe", Qt.Key.Key_BracketLeft: "bracketleft",
    Qt.Key.Key_BracketRight: "bracketright", Qt.Key.Key_Backslash: "backslash",
    Qt.Key.Key_Left: "Left", Qt.Key.Key_Right: "Right", Qt.Key.Key_Up: "Up", Qt.Key.Key_Down: "Down",
}


def _nome_tecla_mac(ev) -> str | None:
    k = ev.key()
    if Qt.Key.Key_A <= k <= Qt.Key.Key_Z or Qt.Key.Key_0 <= k <= Qt.Key.Key_9:
        nome = chr(k)
    elif Qt.Key.Key_F1 <= k <= Qt.Key.Key_F12:
        nome = f"F{k - Qt.Key.Key_F1 + 1}"
    else:
        nome = _TECLAS_MAC.get(Qt.Key(k))
    if not nome:
        return None
    # No Mac o Qt troca os nomes: ControlModifier é o Command e MetaModifier
    # é o Control. "Mod" segue sendo a tecla do sistema (Super / Command).
    mods = ev.modifiers()
    partes = []
    if mods & Qt.KeyboardModifier.ControlModifier:
        partes.append("Mod")
    if mods & Qt.KeyboardModifier.MetaModifier:
        partes.append("Ctrl")
    if mods & Qt.KeyboardModifier.AltModifier:
        partes.append("Alt")
    if mods & Qt.KeyboardModifier.ShiftModifier:
        partes.append("Shift")
    if not partes:
        return None    # tecla sozinha como atalho global roubaria a digitação
    return "+".join(partes + [nome])


def _nome_tecla(sym: int, mods) -> str | None:
    if _XKB is None or not sym:
        return None
    buf = ctypes.create_string_buffer(64)
    if _XKB.xkb_keysym_get_name(_XKB.xkb_keysym_to_upper(sym), buf, 64) <= 0:
        return None
    nome = buf.value.decode()
    if nome.startswith(("Super", "Control", "Alt", "Shift", "Meta", "ISO_", "Hyper")):
        return None
    partes = []
    if mods & Qt.KeyboardModifier.MetaModifier:
        partes.append("Mod")
    if mods & Qt.KeyboardModifier.ControlModifier:
        partes.append("Ctrl")
    if mods & Qt.KeyboardModifier.AltModifier:
        partes.append("Alt")
    if mods & Qt.KeyboardModifier.ShiftModifier:
        partes.append("Shift")
    return "+".join(partes + [nome])


def _agente_carregado() -> tuple[str, int] | None:
    """(nome, MB) do processo de agente ACP filho do daemon, se houver."""
    marcas = (("acp --accept-hooks", "Hermes"), ("opencode acp", "OpenCode"), ("--acp", "Gemini CLI"))
    if MAC or not os.path.isdir("/proc"):
        try:
            out = subprocess.check_output(["ps", "-axo", "rss=,command="], text=True, timeout=2)
        except Exception:
            return None
        for linha in out.splitlines():
            rss, _, cmd = linha.strip().partition(" ")
            for marca, nome in marcas:
                if marca in cmd and "orbe_app" not in cmd:
                    return nome, int(rss or 0) // 1024
        return None
    for pid in os.listdir("/proc"):
        if not pid.isdigit():
            continue
        try:
            cmd = open(f"/proc/{pid}/cmdline", "rb").read().replace(b"\0", b" ").decode("utf-8", "replace")
        except OSError:
            continue
        for marca, nome in marcas:
            if marca in cmd and "orbe_app" not in cmd:
                try:
                    rss = int(next(l for l in open(f"/proc/{pid}/status") if l.startswith("VmRSS")).split()[1])
                except (OSError, StopIteration):
                    rss = 0
                return nome, rss // 1024
    return None


def _tema() -> dict:
    cores = {}
    try:
        for m in re.finditer(r"@define-color\s+(\w+)\s+(#[0-9a-fA-F]{6})", DANK_CSS.read_text()):
            cores[m.group(1)] = m.group(2)
    except OSError:
        pass
    padrao = {"accent_bg_color": "#b8cacb", "accent_fg_color": "#233334", "window_bg_color": "#121414",
              "window_fg_color": "#e3e2e2", "view_bg_color": "#121414", "popover_bg_color": "#1f2020",
              "card_bg_color": "#1f2020"}
    tema = {k: cores.get(k, v) for k, v in padrao.items()}
    # o anel do orbe usa o accent do CSS do sistema, não o do GTK
    try:
        m = re.search(r"--colorAccentBg:\s*(#[0-9a-fA-F]{6})", ACCENT_CSS.read_text())
        tema["anel"] = m.group(1) if m else "#0087fc"
    except OSError:
        tema["anel"] = "#0087fc"
    # o fundo do app é translúcido porque o niri desfoca o que está atrás; no
    # Mac nada desfoca, então ele fica quase opaco para o texto ler bem
    tema["opacidade"] = 0.58
    if MAC:
        tema["opacidade"] = 0.95
        acc = QGuiApplication.palette().color(QPalette.ColorRole.Accent)
        if acc.isValid() and not ACCENT_CSS.exists():
            tema["anel"] = acc.name()
    return tema


def _icone_desenhado(nome: str, lado: int) -> QPixmap:
    """Os ícones simbólicos do app em traço, para quando não há tema de
    ícones (o macOS não tem Adwaita nem Qogir). A cor vem depois, por cima."""
    pm = QPixmap(lado, lado)
    pm.fill(Qt.GlobalColor.transparent)
    base = nome.removesuffix("-symbolic")
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.scale(lado / 16.0, lado / 16.0)
    caneta = QPen(QColor("white"), 1.5, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap,
                  Qt.PenJoinStyle.RoundJoin)
    p.setPen(caneta)
    cam = QPainterPath()
    if base == "window-close":
        cam.moveTo(4, 4); cam.lineTo(12, 12); cam.moveTo(12, 4); cam.lineTo(4, 12)
    elif base == "list-add":
        cam.moveTo(8, 3); cam.lineTo(8, 13); cam.moveTo(3, 8); cam.lineTo(13, 8)
    elif base == "list-remove":
        cam.moveTo(3, 8); cam.lineTo(13, 8)
    elif base == "pan-down":
        cam.moveTo(4, 6); cam.lineTo(8, 10); cam.lineTo(12, 6)
    elif base == "object-select":
        cam.moveTo(3, 8.5); cam.lineTo(6.5, 12); cam.lineTo(13, 4.5)
    elif base == "system-search":
        cam.addEllipse(2.5, 2.5, 8, 8); cam.moveTo(9.5, 9.5); cam.lineTo(13.5, 13.5)
    elif base == "view-refresh":
        cam.arcMoveTo(2.5, 2.5, 11, 11, 60); cam.arcTo(2.5, 2.5, 11, 11, 60, 300)
        cam.moveTo(13.5, 2.5); cam.lineTo(10.8, 3.4); cam.lineTo(13.2, 5.6)
    elif base == "network-server":
        cam.addRoundedRect(3, 2.5, 10, 4.5, 1, 1); cam.addRoundedRect(3, 9, 10, 4.5, 1, 1)
        cam.moveTo(5.5, 4.75); cam.lineTo(6, 4.75); cam.moveTo(5.5, 11.25); cam.lineTo(6, 11.25)
    elif base == "audio-input-microphone":
        cam.addRoundedRect(5.5, 1.5, 5, 8.5, 2.5, 2.5)
        cam.moveTo(3.5, 7.5); cam.arcTo(3.5, 3.5, 9, 9, 180, 180)
        cam.moveTo(8, 12.5); cam.lineTo(8, 14.5)
    elif base == "audio-speakers":
        cam.moveTo(2.5, 6); cam.lineTo(5, 6); cam.lineTo(8.5, 3); cam.lineTo(8.5, 13)
        cam.lineTo(5, 10); cam.lineTo(2.5, 10); cam.closeSubpath()
        cam.arcMoveTo(6, 4.5, 7, 7, -50); cam.arcTo(6, 4.5, 7, 7, -50, 100)
    elif base == "user-available":
        cam.moveTo(1.5, 3); cam.lineTo(14.5, 3); cam.lineTo(14.5, 11); cam.lineTo(7, 11)
        cam.lineTo(4, 14); cam.lineTo(4, 11); cam.lineTo(1.5, 11); cam.closeSubpath()
    elif base == "applications-graphics":
        cam.addEllipse(2, 2, 12, 12)
        cam.addEllipse(5, 4.5, 2, 2); cam.addEllipse(9, 4.5, 2, 2); cam.addEllipse(4.5, 8.5, 2, 2)
    else:
        p.end()
        return QPixmap()
    p.drawPath(cam)
    p.end()
    return pm


class Icones(QQuickImageProvider):
    """image://icone/<nome>?<cor>: ícone simbólico do tema pintado na cor dada."""

    def __init__(self):
        super().__init__(QQuickImageProvider.ImageType.Pixmap)

    def requestPixmap(self, ident, size, pedido):
        nome, _, cor = ident.partition("?")
        lado = max(pedido.width(), pedido.height(), 16)
        pm = QIcon.fromTheme(nome).pixmap(lado, lado)
        if pm.isNull():
            pm = _icone_desenhado(nome, lado)
        if pm.isNull():
            pm = QPixmap(lado, lado)
            pm.fill(Qt.GlobalColor.transparent)
        if cor:
            p = QPainter(pm)
            p.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceIn)
            p.fillRect(pm.rect(), QColor("#" + cor.lstrip("#")))
            p.end()
        if size is not None:
            size.setWidth(pm.width())
            size.setHeight(pm.height())
        return pm


class _Fala:
    """Envelope de fala sintético: sílabas de 120 a 240 ms, pausas entre
    palavras e um tom que anda por sílaba."""

    def __init__(self):
        self.r = random.Random()
        self.t = self.ini = self.fim = 0.0
        self.pico = 0.0
        self.tom = 0.5

    def passo(self, dt):
        self.t += dt
        if self.t >= self.fim:
            self.ini = self.t
            if self.r.random() < 0.2:
                self.pico, dur = 0.0, self.r.uniform(0.12, 0.35)
            else:
                self.pico, dur = self.r.uniform(0.45, 1.0), self.r.uniform(0.12, 0.24)
                self.tom = min(1.0, max(0.0, self.tom + self.r.uniform(-0.25, 0.25)))
            self.fim = self.t + dur
        u = (self.t - self.ini) / max(1e-3, self.fim - self.ini)
        return self.pico * math.sin(math.pi * min(1.0, u)) ** 0.8, self.tom


def _do_js(v) -> dict:
    """Cópia Python de um objeto vindo do QML (um objeto JS guardado numa
    propriedade `var` chega como QJSValue, não como dict)."""
    if isinstance(v, QJSValue):
        v = v.toVariant()
    return json.loads(json.dumps(v or {}))


class Ponte(QObject):
    modelosConsultados = Signal("QVariant", str)
    atalhoCapturado = Signal(str)
    atalhoCancelado = Signal()
    estadoMudou = Signal()
    ajustesRelogioMudou = Signal("QVariant")
    apresentar = Signal()
    previaMudou = Signal()

    def __init__(self):
        super().__init__()
        self._cfg = vcfg.carregar()
        self._atalho = _atalho_atual() or self._cfg["ativacao"]["atalho"]
        self._tema = _tema()
        self._estado = ""
        self._capturando = False
        self._relogio = QTimer(self)
        self._relogio.timeout.connect(self._atualizar_estado)
        self._previa = None
        self._previa_sock = None
        self._previa_tentativas = 0
        self._previa_espera = QTimer(self)
        self._previa_espera.setInterval(100)
        self._previa_espera.timeout.connect(self._previa_conectar)
        self._previa_ciclo = QTimer(self)
        self._previa_ciclo.setInterval(33)
        self._previa_ciclo.timeout.connect(self._previa_tique)
        self._previa_fase = 0
        self._previa_t = 0.0
        self._previa_rel = 0.0
        self._previa_linha = 0
        self._previa_estado = ""
        self._fala = _Fala()

    def iniciar_relogio(self):
        self._atualizar_estado()
        self._relogio.start(3000)

    # ── dados para a interface ──

    @Property("QVariant", constant=True)
    def cfg(self):
        return self._cfg

    @Property("QVariant", constant=True)
    def tema(self):
        return self._tema

    @Property(str, constant=True)
    def atalho(self):
        return self._atalho

    @Property("QVariant", constant=True)
    def agentes(self):
        return [{"id": t, "nome": acp.NOMES[t] + ("" if acp.disponivel(t) else " (não instalado)")}
                for t in ("hermes", "opencode", "gemini", "claude", "comando")]

    @Property("QVariant", constant=True)
    def agentesModo(self):
        """Os agentes que rodam num terminal ou em segundo plano (agente.modos)."""
        return [{"id": t, "nome": acp.NOMES[t]} for t in vcfg.MODOS_TERMINAL if acp.disponivel(t)]

    @Property("QVariant", constant=True)
    def perfis(self):
        return [{"id": p, "nome": p} for p in acp.perfis_hermes()]

    @Property("QVariant", constant=True)
    def owwModelos(self):
        return [{"id": p, "nome": Path(p).name} for p in _arquivos(WAKE_DIR, (".onnx",))] \
            or [{"id": "", "nome": "nenhum .onnx"}]

    @Property("QVariant", constant=True)
    def mwwModelos(self):
        return [{"id": p, "nome": Path(p).name} for p in _arquivos(WAKE_DIR, (".tflite",))] \
            or [{"id": "", "nome": "nenhum .tflite"}]

    @Property("QVariant", constant=True)
    def piperVozes(self):
        return [{"id": "", "nome": "A do perfil"}] + \
            [{"id": p, "nome": Path(p).stem} for p in _arquivos(PIPER_DIR, (".onnx",))]

    @Property("QVariant", constant=True)
    def geminiVozes(self):
        return [{"id": "", "nome": "A do perfil"}] + [{"id": v, "nome": v} for v in GEMINI_VOZES]

    @Property(str, constant=True)
    def ttsPerfil(self):
        return _tts_do_perfil()

    @Property("QVariant", constant=True)
    def chaves(self):
        """As chaves do orbe e o que vale quando a própria está vazia."""
        proprias, hermes = vcfg.chaves_proprias(), vcfg.ler_env(vcfg.HERMES_ENV)
        out = []
        for k, nome in vcfg.CHAVES:
            if hermes.get(k):
                herda = "vazia: a do Hermes (…" + hermes[k][-4:] + ")"
            elif os.environ.get(k):
                herda = "vazia: a do ambiente"
            else:
                herda = "sem chave"
            out.append({"id": k, "nome": nome, "propria": proprias.get(k, ""), "herda": herda})
        return out

    @Property("QVariant", constant=True)
    def nomesSkin(self):
        return NOMES_SKIN

    @Property("QVariant", constant=True)
    def agentesRelogio(self):
        """O que cada orbe do relógio pode ter: o Claude (padrão) e os ACP instalados."""
        perfil = self._cfg["agente"]["perfil"]
        # o comando ACP só existe no PC: o relógio não o oferece, mas um orbe que o tenha o mostra
        comando = [{"id": "comando", "nome": acp.NOMES["comando"]}] if self._cfg["agente"]["comando"] else []
        return [{"id": "", "nome": "Claude Code (padrão)"}] + [
            {"id": t, "nome": acp.NOMES[t] + (f" ({perfil})" if t == "hermes" else "")}
            for t in ("hermes", "opencode", "gemini") if acp.disponivel(t)] + comando

    @Slot(result=str)
    def trocarTokenRelogio(self):
        """Token novo: o relógio pareado com o velho para de entrar."""
        tok = relogio.token_da_config(trocar=True)
        self._cfg["relogio"]["token"] = tok
        vcfg.servico_iniciar(reiniciar=True)
        return tok

    @Slot(result=str)
    def firewallRelogio(self):
        """Se o firewalld deixa o relógio chegar à porta da ponte; vazio sem firewalld.

        Lê a zona padrão dos arquivos de /etc/firewalld (legíveis por todos):
        o firewall-cmd, mesmo só para listar, pode pedir a senha pelo polkit.
        """
        porta = int(self._cfg["relogio"]["porta"])
        try:
            ativo = subprocess.run(["systemctl", "is-active", "firewalld"],
                                   capture_output=True, text=True, timeout=2).stdout.strip()
        except (OSError, subprocess.SubprocessError):
            return ""
        if ativo != "active":
            return ""
        zona = "public"
        try:
            for linha in Path("/etc/firewalld/firewalld.conf").read_text().splitlines():
                if linha.startswith("DefaultZone="):
                    zona = linha.split("=", 1)[1].strip() or zona
        except OSError:
            pass
        xml = ""
        for base in ("/etc/firewalld/zones", "/usr/lib/firewalld/zones"):
            try:
                xml = (Path(base) / f"{zona}.xml").read_text()
                break
            except OSError:
                continue
        if f'port="{porta}"' in xml:
            return "a porta está liberada no firewall"
        return (f"o firewall bloqueia a porta {porta}: sudo firewall-cmd --zone={zona} --permanent "
                f"--add-port={porta}/tcp && sudo firewall-cmd --reload")

    @Property(str, constant=True)
    def enderecoRelogio(self):
        """O que se digita no relógio para achar este computador."""
        return (relogio.enderecos() or ["o IP deste computador"])[0]

    @Property(str, notify=estadoMudou)
    def estado(self):
        return self._estado

    def _atualizar_estado(self):
        ativo = vcfg.servico_estado()
        ag = _agente_carregado()
        txt = "serviço " + {"active": "ativo", "inactive": "parado"}.get(ativo, ativo)
        txt += f"  ·  {ag[0]} carregado, {ag[1]} MB" if ag else "  ·  agente descarregado"
        if txt != self._estado:
            self._estado = txt
            self.estadoMudou.emit()
        # o relógio mudou os ajustes dele pela ponte: a aba do relógio acompanha
        disco = relogio.ajustes_relogio()
        if disco != self._cfg["relogio"]["ajustes"]:
            self._cfg["relogio"]["ajustes"] = disco
            self.ajustesRelogioMudou.emit(disco)

    # ── agente ──

    @Slot(str, result="QVariant")
    def modelosDoEstado(self, chave):
        est = vcfg.ler_estado()
        if est.get("chave") == chave and est.get("modelos"):
            return {"modelos": est["modelos"], "atual": est.get("modelo_atual", "")}
        return None

    @Slot("QVariant")
    def consultarModelos(self, agente):
        agente = _do_js(agente)

        def trabalho():
            rt = None
            if agente.get("tipo") == "hermes":
                try:
                    rt = json.loads(subprocess.check_output(
                        [acp.HERMES_LAUNCHER, "--print-runtime-command", "--"], text=True, timeout=30))
                except Exception:
                    rt = None
            try:
                r = acp.sondar(agente, rt)
                self.modelosConsultados.emit(r, "")
            except Exception as e:
                self.modelosConsultados.emit(None, str(e))
        threading.Thread(target=trabalho, daemon=True).start()

    @Slot(result=str)
    def sessoesClaude(self):
        s = canal.sessoes()
        if not s:
            return "nenhuma aberta com o canal: o orbe abre uma no terminal ao ser chamado"
        cwd = (s[0].get("cwd") or "?").replace(str(Path.home()), "~", 1)
        mais = f" (de {len(s)} abertas)" if len(s) > 1 else ""
        return f"fala com a mais recente{mais}: {cwd}"

    # ── atalho ──

    @Slot()
    def capturarAtalho(self):
        if not self._capturando:
            self._capturando = True
            QGuiApplication.instance().installEventFilter(self)

    @Slot()
    def cancelarCaptura(self):
        if self._capturando:
            self._capturando = False
            QGuiApplication.instance().removeEventFilter(self)

    def eventFilter(self, obj, ev):
        if self._capturando and ev.type() == QEvent.Type.KeyPress and isinstance(obj, QQuickWindow):
            if ev.key() == Qt.Key.Key_Escape:
                self.cancelarCaptura()
                self.atalhoCancelado.emit()
                return True
            nome = (_nome_tecla_mac(ev) if MAC
                    else _nome_tecla(ev.nativeVirtualKey(), ev.modifiers()))
            if nome:
                self.cancelarCaptura()
                self.atalhoCapturado.emit(nome)
            return True
        return False

    # ── pré-visualização ──

    @Property(bool, notify=previaMudou)
    def previa(self):
        return self._previa is not None

    @Property(str, notify=previaMudou)
    def previaEstado(self):
        return self._previa_estado

    @Slot("QVariant")
    def ligarPrevia(self, aparencia):
        if self._previa is not None:
            return
        self.atualizarPrevia(aparencia)
        env = QProcessEnvironment.systemEnvironment()
        env.insert("ORBE_SOCK", str(PREVIA_SOCK))
        env.insert("ORBE_CTL_SOCK", str(PREVIA_CTL))
        env.insert("ORBE_CONFIG", str(PREVIA_CFG))
        p = QProcess(self)
        p.setProcessEnvironment(env)
        if MAC:
            # --pai faz o papel do pdeathsig: o orbe da prévia sai com o app
            p.setProgram(sys.executable)
            p.setArguments([str(ORBE_MAC), "--sock", str(PREVIA_SOCK), "--ctl", str(PREVIA_CTL),
                            "--config", str(PREVIA_CFG), "--pai", str(os.getpid())])
        else:
            # pdeathsig: o orbe da prévia morre junto com o app, mesmo num kill
            p.setProgram("/usr/bin/setpriv")
            p.setArguments(["--pdeathsig", "TERM", "--", "/usr/bin/qs", "-p", str(ORBE_QML)])
        p.setStandardOutputFile(QProcess.nullDevice())
        p.setStandardErrorFile(QProcess.nullDevice())
        p.finished.connect(self._previa_saiu)
        self._previa = p
        self._previa_tentativas = 0
        p.start()
        self._previa_espera.start()
        self.previaMudou.emit()

    def _previa_conectar(self):
        self._previa_tentativas += 1
        s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        s.settimeout(0.2)
        try:
            s.connect(str(PREVIA_SOCK))
        except OSError:
            s.close()
            if self._previa_tentativas >= 50:      # 5 s sem o socket subir
                self.desligarPrevia()
            return
        self._previa_espera.stop()
        self._previa_sock = s
        self._previa_enviar("show idle")
        self._previa_entrar(0)
        self._previa_rel = time.monotonic()
        self._previa_ciclo.start()

    def _previa_enviar(self, *linhas):
        if self._previa_sock is None:
            return
        try:
            self._previa_sock.sendall("".join(l + "\n" for l in linhas).encode())
        except OSError:
            pass

    def _previa_entrar(self, fase):
        self._previa_fase = fase
        self._previa_t = 0.0
        self._previa_linha = 0
        estado, rotulo, _dur = PREVIA_CICLO[fase]
        if fase == 0:
            self._previa_enviar("level 0", "mic 0", "clear")
        self._previa_enviar(f"state {estado}")
        self._previa_estado = rotulo
        self.previaMudou.emit()

    def _previa_tique(self):
        agora = time.monotonic()
        dt = min(0.1, agora - self._previa_rel)
        self._previa_rel = agora
        self._previa_t += dt
        estado, _rotulo, dur = PREVIA_CICLO[self._previa_fase]
        if estado == "listening":
            env, _tom = self._fala.passo(dt)
            self._previa_enviar(f"mic {0.03 + 0.75 * env:.3f}")
        elif estado == "speaking":
            env, tom = self._fala.passo(dt)
            self._previa_enviar(f"level {0.9 * env:.3f} {tom:.2f}")
        elif estado == "thinking":
            if self._previa_linha < len(PREVIA_LINHAS) and self._previa_t >= 0.3 + self._previa_linha:
                self._previa_enviar("line " + PREVIA_LINHAS[self._previa_linha])
                self._previa_linha += 1
        if self._previa_t >= dur:
            self._previa_entrar((self._previa_fase + 1) % len(PREVIA_CICLO))

    @Slot("QVariant")
    def atualizarPrevia(self, aparencia):
        orbe = _do_js(aparencia)
        tmp = PREVIA_CFG.with_suffix(".tmp")
        tmp.write_text(json.dumps({"orbe": orbe}), encoding="utf-8")
        os.replace(tmp, PREVIA_CFG)

    @Slot()
    def desligarPrevia(self):
        p = self._previa
        if p is None:
            return
        self._previa_espera.stop()
        self._previa_ciclo.stop()
        if self._previa_sock is not None:
            try:
                self._previa_sock.sendall(b"quit\n")
            except OSError:
                pass
        QTimer.singleShot(1000, p.terminate)

    def _previa_saiu(self, *_):
        self._previa_espera.stop()
        self._previa_ciclo.stop()
        self._previa_estado = ""
        if self._previa_sock is not None:
            self._previa_sock.close()
        self._previa_sock = None
        self._previa = None
        for f in (PREVIA_CFG, PREVIA_SOCK):
            try:
                f.unlink()
            except OSError:
                pass
        self.previaMudou.emit()

    def encerrar(self):
        """Fecha a prévia antes de o app sair."""
        p = self._previa
        if p is not None:
            p.finished.disconnect(self._previa_saiu)
            p.terminate()
            p.waitForFinished(1000)
            self._previa = p = None
            self._previa_saiu()

    # ── aplicar ──

    @Slot("QVariant", str, result="QVariant")
    def aplicar(self, novo, atalho):
        novo = _do_js(novo)
        erro = ""
        # as chaves vão para o chaves.env; o daemon as lê ao subir
        chaves = {k: v for k, v in (novo.pop("chaves", None) or {}).items() if v}
        chaves_mudaram = chaves != vcfg.chaves_proprias()
        if chaves_mudaram:
            vcfg.gravar_chaves(chaves)
        if atalho != _atalho_atual():
            erro = _gravar_atalho(atalho)
            if erro:
                atalho = _atalho_atual()
        novo["ativacao"]["atalho"] = atalho
        self._atalho = atalho
        # o token é daqui (o botão de trocar grava direto): a cópia da interface pode ser velha
        novo["relogio"]["token"] = self._cfg["relogio"]["token"]
        # a ponte do relógio precisa de um token; nasce na primeira vez que ela é ligada
        if novo["relogio"]["ligado"] and not novo["relogio"]["token"]:
            novo["relogio"]["token"] = relogio.novo_token()
        token = novo["relogio"]["token"]

        def sem(c, *chaves):
            c = json.loads(json.dumps(c))
            c["ativacao"]["atalho"] = ""
            for k in chaves:
                c.pop(k, None)
            return c
        # Os ajustes do relógio vão e voltam pela ponte: mexidos aqui, ganham
        # um "t" novo e a ponte os leva; intocados, fica o que o relógio mandou
        # enquanto o app estava aberto.
        aj, aj_antes = dict(novo["relogio"]["ajustes"]), dict(self._cfg["relogio"]["ajustes"])
        aj.pop("t", None)
        aj_antes.pop("t", None)
        if aj != aj_antes:
            novo["relogio"]["ajustes"]["t"] = int(time.time() * 1000)
        else:
            novo["relogio"]["ajustes"] = relogio.ajustes_relogio()

        def sem_relogio(c, *chaves):
            c = sem(c, *chaves)
            c["relogio"].pop("ajustes", None)
            return c
        mudou = sem(novo) != sem(self._cfg) or chaves_mudaram
        # O orbe em Quickshell segue o config.json ao vivo, e a ponte leva os
        # ajustes do relógio: mudar só isso dispensa reiniciar o daemon (e
        # recarregar o agente).
        so_orbe = (mudou and not chaves_mudaram
                   and sem_relogio(novo, "orbe") == sem_relogio(self._cfg, "orbe"))
        vcfg.salvar(novo)
        self._cfg = novo
        if erro:
            return {"mensagem": erro, "atalho": atalho, "tempo": 6, "token": token}
        if mudou and not so_orbe:
            vcfg.servico_iniciar(reiniciar=True)
            return {"mensagem": "Aplicado. Orbe reiniciado.", "atalho": atalho, "tempo": 3, "token": token}
        return {"mensagem": "Aplicado.", "atalho": atalho, "tempo": 2, "token": token}


def _preparar_app(argv):
    QGuiApplication.setDesktopFileName(APP_ID)    # vira o app-id do Wayland
    QQuickWindow.setDefaultAlphaBuffer(True)
    from PySide6.QtQuickControls2 import QQuickStyle
    QQuickStyle.setStyle("Basic")
    app = QGuiApplication(argv)
    app.setApplicationName("Orbe")
    if MAC:
        # a fonte do sistema; 13 pt no Mac tem o corpo dos 11 pt do GNOME
        f = app.font()
        f.setPointSize(13)
        app.setFont(f)
        QFont.insertSubstitution("Sans", f.family())
        app.setWindowIcon(QIcon(str(Path(__file__).resolve().parent / "orbe.svg")))
        return app
    app.setFont(QFont("Adwaita Sans", 11))
    QIcon.setThemeName("Qogir")
    QIcon.setFallbackThemeName("Adwaita")
    return app


def _trazer_para_ca():
    """Leva a janela do app para a área de trabalho em foco (no niri, ativar uma
    janela de outro workspace troca de workspace em vez de trazê-la)."""
    def niri(*args):
        return subprocess.run(["niri", "msg", *args], capture_output=True, text=True, timeout=2)
    try:
        wss = json.loads(niri("-j", "workspaces").stdout)
        foco = next(w for w in wss if w["is_focused"])
        jan = next(w for w in json.loads(niri("-j", "windows").stdout) if w.get("pid") == os.getpid())
    except (OSError, ValueError, StopIteration, subprocess.SubprocessError):
        return
    if jan.get("workspace_id") == foco["id"]:
        return
    onde = next((w for w in wss if w["id"] == jan.get("workspace_id")), None)
    if onde is None or onde["output"] != foco["output"]:
        # noutro monitor: vai para o workspace ativo dele, que é o em foco
        niri("action", "move-window-to-monitor", "--id", str(jan["id"]), foco["output"])
    else:
        niri("action", "move-window-to-workspace", "--window-id", str(jan["id"]),
             "--focus", "false", str(foco["idx"]))


def _instancia_unica(ponte) -> QLocalServer | None:
    """Segundo lançamento traz a janela da primeira para a área de trabalho
    atual e para a frente."""
    s = QLocalSocket()
    s.connectToServer(APP_ID)
    if s.waitForConnected(150):
        s.write(b"apresentar\n")
        s.flush()
        s.waitForBytesWritten(150)
        return None
    QLocalServer.removeServer(APP_ID)
    srv = QLocalServer()
    srv.listen(APP_ID)
    srv.newConnection.connect(lambda: (srv.nextPendingConnection(), _trazer_para_ca(), ponte.apresentar.emit()))
    return srv


def main():
    if "--captura" in sys.argv:
        k = sys.argv.index("--captura")
        destino, paginas = sys.argv[k + 1], sys.argv[k + 2:] or ["agente"]
        _capturar(destino, paginas)
        return
    app = _preparar_app(sys.argv[:1])
    ponte = Ponte()
    srv = _instancia_unica(ponte)
    if srv is None:
        return
    eng = QQmlApplicationEngine()
    eng.addImageProvider("icone", Icones())
    eng.rootContext().setContextProperty("ponte", ponte)
    eng.load(QUrl.fromLocalFile(str(QML_DIR / "Main.qml")))
    if not eng.rootObjects():
        sys.exit(1)
    ponte.iniciar_relogio()
    if "--previa" in sys.argv:
        ponte.ligarPrevia(ponte.cfg["orbe"])
    rc = app.exec()
    ponte.encerrar()
    del eng
    sys.exit(rc)


def _capturar(destino, paginas):
    """PNG de cada página, renderizado offscreen pela GPU (QQuickRenderControl)."""
    if not MAC:
        os.environ.setdefault("QT_QPA_PLATFORM", "wayland")
    from PySide6.QtCore import QSize
    from PySide6.QtGui import QOffscreenSurface, QOpenGLContext, QSurfaceFormat
    from PySide6.QtOpenGL import QOpenGLFramebufferObject, QOpenGLFramebufferObjectFormat
    from PySide6.QtQml import QQmlComponent, QQmlEngine
    from PySide6.QtQuick import QQuickGraphicsDevice, QQuickRenderControl, QQuickRenderTarget

    app = _preparar_app(sys.argv[:1])
    ponte = Ponte()
    ponte.iniciar_relogio()
    fmt = QSurfaceFormat()
    fmt.setAlphaBufferSize(8)
    ctx = QOpenGLContext()
    ctx.setFormat(fmt)
    ctx.create()
    surf = QOffscreenSurface()
    surf.setFormat(ctx.format())
    surf.create()
    ctx.makeCurrent(surf)
    rc = QQuickRenderControl()
    win = QQuickWindow(rc)
    win.setGraphicsDevice(QQuickGraphicsDevice.fromOpenGLContext(ctx))
    eng = QQmlEngine()
    eng.addImageProvider("icone", Icones())
    eng.rootContext().setContextProperty("ponte", ponte)
    comp = QQmlComponent(eng, QUrl.fromLocalFile(str(QML_DIR / "Captura.qml")))
    raiz = comp.create()
    if raiz is None:
        print(comp.errorString())
        sys.exit(1)
    raiz.setProperty("height", int(os.environ.get("ORBE_CAPTURA_ALTO", "700")))
    raiz.setParentItem(win.contentItem())
    dpr = 1.25
    W, H = int(raiz.width()), int(raiz.height())
    win.resize(W, H)
    win.contentItem().setSize(raiz.size())
    rc.initialize()
    ff = QOpenGLFramebufferObjectFormat()
    ff.setAttachment(QOpenGLFramebufferObject.Attachment.CombinedDepthStencil)
    fbo = QOpenGLFramebufferObject(QSize(int(W * dpr), int(H * dpr)), ff)
    rt = QQuickRenderTarget.fromOpenGLTexture(fbo.texture(), QSize(int(W * dpr), int(H * dpr)))
    rt.setDevicePixelRatio(dpr)
    win.setRenderTarget(rt)
    for pag in paginas:
        raiz.setProperty("pagina", pag)
        for _ in range(45):
            raiz.passo(1 / 60)
            app.processEvents()
            rc.polishItems()
            rc.beginFrame()
            rc.sync()
            rc.render()
            rc.endFrame()
        ctx.functions().glFinish()
        fbo.toImage().save(f"{destino}_{pag}.png")
        time.sleep(0.01)
    del rt, fbo
    win.setRenderTarget(QQuickRenderTarget())
    raiz.deleteLater()
    del raiz, comp
    rc.invalidate()
    del win, rc
    ctx.doneCurrent()


if __name__ == "__main__":
    main()
