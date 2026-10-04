#!/usr/bin/python3
"""Orbe: configurações do orbe de voz (Qt Quick, desenho na GPU).

Janela pequena e flutuante, vidro fosco (o blur vem da regra do niri para o
app-id io.hermes.Orbe; a janela só pinta fundo translúcido). O processo sai
quando a janela fecha: nada fica residente.

A interface é QML (orbe-qt/app); as figuras do topo, dos cartões e do botão
do tamanho são os mesmos componentes do orbe (orbe-qt/comum), em shaders.
Este arquivo é a ponte: lê e grava ~/.config/hermes-voice/config.json
(hermes_voice_config.py), troca o atalho em ~/.config/niri/dms/binds.kdl,
consulta agentes e sessões do Claude e reinicia o hermes-voice ao aplicar.

  hermes_voice_app.py              abre o app
  hermes_voice_app.py --captura P [páginas]  PNG de cada página em P_<página>.png
      (renderizado offscreen pela GPU, sem janela)
"""
import ctypes
import ctypes.util
import json
import os
import re
import subprocess
import sys
import threading
from pathlib import Path

from PySide6.QtCore import (QEvent, QObject, Property, QTimer, QUrl, Qt, Signal, Slot)
from PySide6.QtGui import QColor, QFont, QGuiApplication, QIcon, QPainter, QPixmap
from PySide6.QtNetwork import QLocalServer, QLocalSocket
from PySide6.QtQml import QQmlApplicationEngine
from PySide6.QtQuick import QQuickImageProvider, QQuickWindow

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import hermes_voice_acp as acp  # noqa: E402
import hermes_voice_canal as canal  # noqa: E402
import hermes_voice_config as vcfg  # noqa: E402

APP_ID = "io.hermes.Orbe"
SERVICO = "hermes-voice"
QML_DIR = Path(__file__).resolve().parent / "orbe-qt" / "app"
BINDS = Path.home() / ".config" / "niri" / "dms" / "binds.kdl"
DANK_CSS = Path.home() / ".config" / "gtk-4.0" / "dank-colors.css"
ACCENT_CSS = Path("/home/davi/Projetos/Docs_rice_sistema/main.css")
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
NOMES_SKIN = {"ofanim": "Ophanim", "ofanim_alado": "Ophanim com asas", "serafim": "Seraphim",
              "anel": "Anel de energia"}


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


# Nome da tecla no formato do niri: o keysym do xkb, como o GDK dava. No
# Wayland o Qt entrega o keysym em nativeVirtualKey.
try:
    _XKB = ctypes.CDLL(ctypes.util.find_library("xkbcommon") or "libxkbcommon.so.0")
except OSError:
    _XKB = None


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


def _orbe_gtk_vivo() -> bool:
    """O orbe GTK (daemon antigo) não segue o config.json ao vivo."""
    r = subprocess.run(["pgrep", "-f", "hermes_voice_orb.py"], capture_output=True)
    return r.returncode == 0


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
    return tema


class Icones(QQuickImageProvider):
    """image://icone/<nome>?<cor>: ícone simbólico do tema pintado na cor dada."""

    def __init__(self):
        super().__init__(QQuickImageProvider.ImageType.Pixmap)

    def requestPixmap(self, ident, size, pedido):
        nome, _, cor = ident.partition("?")
        lado = max(pedido.width(), pedido.height(), 16)
        pm = QIcon.fromTheme(nome).pixmap(lado, lado)
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


class Ponte(QObject):
    modelosConsultados = Signal("QVariant", str)
    atalhoCapturado = Signal(str)
    atalhoCancelado = Signal()
    estadoMudou = Signal()
    apresentar = Signal()

    def __init__(self):
        super().__init__()
        self._cfg = vcfg.carregar()
        self._atalho = _atalho_atual() or self._cfg["ativacao"]["atalho"]
        self._tema = _tema()
        self._estado = ""
        self._capturando = False
        self._relogio = QTimer(self)
        self._relogio.timeout.connect(self._atualizar_estado)

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
    def nomesSkin(self):
        return NOMES_SKIN

    @Property(str, notify=estadoMudou)
    def estado(self):
        return self._estado

    def _atualizar_estado(self):
        try:
            ativo = subprocess.run(["systemctl", "--user", "is-active", SERVICO],
                                   capture_output=True, text=True, timeout=2).stdout.strip()
        except Exception:
            ativo = "?"
        ag = _agente_carregado()
        txt = "serviço " + ("ativo" if ativo == "active" else ativo)
        txt += f"  ·  {ag[0]} carregado, {ag[1]} MB" if ag else "  ·  agente descarregado"
        if txt != self._estado:
            self._estado = txt
            self.estadoMudou.emit()

    # ── agente ──

    @Slot(str, result="QVariant")
    def modelosDoEstado(self, chave):
        est = vcfg.ler_estado()
        if est.get("chave") == chave and est.get("modelos"):
            return {"modelos": est["modelos"], "atual": est.get("modelo_atual", "")}
        return None

    @Slot("QVariant")
    def consultarModelos(self, agente):
        agente = dict(agente or {})

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
            return "nenhuma aberta com o canal; abra o Claude com claude-orbe"
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
            nome = _nome_tecla(ev.nativeVirtualKey(), ev.modifiers())
            if nome:
                self.cancelarCaptura()
                self.atalhoCapturado.emit(nome)
            return True
        return False

    # ── aplicar ──

    @Slot("QVariant", str, result="QVariant")
    def aplicar(self, novo, atalho):
        novo = json.loads(json.dumps(novo))
        erro = ""
        if atalho != _atalho_atual():
            erro = _gravar_atalho(atalho)
            if erro:
                atalho = _atalho_atual()
        novo["ativacao"]["atalho"] = atalho
        self._atalho = atalho

        def sem(c, *chaves):
            c = json.loads(json.dumps(c))
            c["ativacao"]["atalho"] = ""
            for k in chaves:
                c.pop(k, None)
            return c
        mudou = sem(novo) != sem(self._cfg)
        # O orbe em Quickshell segue o config.json ao vivo: mudar só a
        # aparência dispensa reiniciar o daemon (e recarregar o agente).
        so_orbe = mudou and sem(novo, "orbe") == sem(self._cfg, "orbe") and not _orbe_gtk_vivo()
        vcfg.salvar(novo)
        self._cfg = novo
        if erro:
            return {"mensagem": erro, "atalho": atalho, "tempo": 6}
        if mudou and not so_orbe:
            subprocess.Popen(["systemctl", "--user", "restart", SERVICO],
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            return {"mensagem": "Aplicado. Orbe reiniciado.", "atalho": atalho, "tempo": 3}
        return {"mensagem": "Aplicado.", "atalho": atalho, "tempo": 2}


def _preparar_app(argv):
    QGuiApplication.setDesktopFileName(APP_ID)    # vira o app-id do Wayland
    QQuickWindow.setDefaultAlphaBuffer(True)
    from PySide6.QtQuickControls2 import QQuickStyle
    QQuickStyle.setStyle("Basic")
    app = QGuiApplication(argv)
    app.setApplicationName("Orbe")
    app.setFont(QFont("Adwaita Sans", 11))
    QIcon.setThemeName("Qogir")
    QIcon.setFallbackThemeName("Adwaita")
    return app


def _instancia_unica(ponte) -> QLocalServer | None:
    """Segundo lançamento só traz a janela da primeira para a frente."""
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
    srv.newConnection.connect(lambda: (srv.nextPendingConnection(), ponte.apresentar.emit()))
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
    rc = app.exec()
    del eng
    sys.exit(rc)


def _capturar(destino, paginas):
    """PNG de cada página, renderizado offscreen pela GPU (QQuickRenderControl)."""
    os.environ.setdefault("QT_QPA_PLATFORM", "wayland")
    import time
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
