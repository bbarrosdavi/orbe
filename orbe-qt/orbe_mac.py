#!/usr/bin/env python3
"""Orbe de voz no macOS: o papel do Quickshell (orbe.qml) em PySide6.

Mesmo protocolo e mesmos sockets. O daemon fala por
<runtime>/hermes-voice-orb.sock (show, state, level, mic, line, hold, hide,
clear, warm, quit) e o toque vai para hermes-voice-ctl.sock (touch down /
touch up), uma conexão por mensagem. O desenho é o OrbeConteudo na GPU
(Metal), a animação anda no vsync e para quando o orbe some.

O que o Linux resolvia fora daqui e o Mac resolve aqui dentro:
- olhar: a posição global do cursor vem do Qt (sem evdev);
- atalho de teclado: RegisterEventHotKey do Carbon, que não pede permissão
  de Acessibilidade; a tecla é a de ativacao.atalho no config;
- janela: painel não ativante, em todos os Spaces e sobre apps em tela
  cheia, sem ícone no Dock.

  orbe_mac.py [--sock S] [--ctl C] [--config F] [--pai PID]

--sock/--ctl/--config apontam para outra instância (a pré-visualização do
app); --pai encerra o orbe quando aquele processo morre.
"""
import argparse
import ctypes
import os
import signal
import socket
import sys
from pathlib import Path

AQUI = Path(__file__).resolve().parent
sys.path.insert(0, str(AQUI.parent))
import hermes_voice_config as vcfg  # noqa: E402

from PySide6.QtCore import (QFileSystemWatcher, QObject, QPointF, QRect, QTimer, QUrl,  # noqa: E402
                            Property, Signal, Slot)
from PySide6.QtGui import QColor, QCursor, QFont, QGuiApplication, QPalette, QRegion  # noqa: E402
from PySide6.QtNetwork import QLocalServer  # noqa: E402
from PySide6.QtQml import QQmlApplicationEngine  # noqa: E402
from PySide6.QtQuick import QQuickWindow  # noqa: E402


# ── Objective-C mínimo, por ctypes (sem pyobjc) ─────────────────────────────

_objc = ctypes.cdll.LoadLibrary("/usr/lib/libobjc.A.dylib")
_objc.objc_getClass.restype = ctypes.c_void_p
_objc.objc_getClass.argtypes = [ctypes.c_char_p]
_objc.sel_registerName.restype = ctypes.c_void_p
_objc.sel_registerName.argtypes = [ctypes.c_char_p]
_MSG = ctypes.cast(_objc.objc_msgSend, ctypes.c_void_p).value


def _msg(obj, sel: str, *args, res=ctypes.c_void_p, tipos=()):
    f = ctypes.CFUNCTYPE(res, ctypes.c_void_p, ctypes.c_void_p, *tipos)(_MSG)
    return f(obj, _objc.sel_registerName(sel.encode()), *args)


def _app_acessorio():
    """Sem ícone no Dock nem menu: NSApplicationActivationPolicyAccessory."""
    app = _msg(_objc.objc_getClass(b"NSApplication"), "sharedApplication")
    _msg(app, "setActivationPolicy:", 1, res=ctypes.c_bool, tipos=(ctypes.c_long,))


def _ajustar_nswindow(win_id: int):
    view = ctypes.c_void_p(win_id)
    w = _msg(view, "window")
    if not w:
        return
    # o Qt.Tool vira NSPanel, que some quando o app perde o foco; o orbe não
    _msg(w, "setHidesOnDeactivate:", False, res=None, tipos=(ctypes.c_bool,))
    # NSWindowStyleMaskNonactivatingPanel: tocar não ativa o processo
    mask = _msg(w, "styleMask", res=ctypes.c_ulong)
    _msg(w, "setStyleMask:", mask | (1 << 7), res=None, tipos=(ctypes.c_ulong,))
    # canJoinAllSpaces | stationary | ignoresCycle | fullScreenAuxiliary
    _msg(w, "setCollectionBehavior:", 1 | 16 | 64 | 256, res=None, tipos=(ctypes.c_ulong,))
    _msg(w, "setLevel:", 25, res=None, tipos=(ctypes.c_long,))   # NSStatusWindowLevel
    _msg(w, "setHasShadow:", False, res=None, tipos=(ctypes.c_bool,))


# ── atalho global (Carbon) ──────────────────────────────────────────────────

# nome da tecla no formato do app (keysym do xkb, como no niri) → keycode ANSI
TECLAS = {
    "a": 0, "s": 1, "d": 2, "f": 3, "h": 4, "g": 5, "z": 6, "x": 7, "c": 8, "v": 9,
    "b": 11, "q": 12, "w": 13, "e": 14, "r": 15, "y": 16, "t": 17, "1": 18, "2": 19,
    "3": 20, "4": 21, "6": 22, "5": 23, "equal": 24, "9": 25, "7": 26, "minus": 27,
    "8": 28, "0": 29, "bracketright": 30, "o": 31, "u": 32, "bracketleft": 33, "i": 34,
    "p": 35, "return": 36, "l": 37, "j": 38, "apostrophe": 39, "k": 40, "semicolon": 41,
    "backslash": 42, "comma": 43, "slash": 44, "n": 45, "m": 46, "period": 47, "tab": 48,
    "space": 49, "grave": 50, "backspace": 51, "escape": 53,
    "f1": 122, "f2": 120, "f3": 99, "f4": 118, "f5": 96, "f6": 97, "f7": 98, "f8": 100,
    "f9": 101, "f10": 109, "f11": 103, "f12": 111,
    "left": 123, "right": 124, "down": 125, "up": 126,
}
MODS = {"mod": 0x0100, "super": 0x0100, "cmd": 0x0100, "command": 0x0100, "meta": 0x0100,
        "shift": 0x0200, "alt": 0x0800, "option": 0x0800, "ctrl": 0x1000, "control": 0x1000}


def parse_atalho(texto: str):
    """'Ctrl+Alt+O' → (keycode, modificadores Carbon); None se não der."""
    partes = [p.strip().lower() for p in (texto or "").split("+") if p.strip()]
    if not partes or partes[-1] not in TECLAS:
        return None
    mods = 0
    for p in partes[:-1]:
        if p not in MODS:
            return None
        mods |= MODS[p]
    return TECLAS[partes[-1]], mods


class _EventTypeSpec(ctypes.Structure):
    _fields_ = [("eventClass", ctypes.c_uint32), ("eventKind", ctypes.c_uint32)]


class _EventHotKeyID(ctypes.Structure):
    _fields_ = [("signature", ctypes.c_uint32), ("id", ctypes.c_uint32)]


_HANDLER = ctypes.CFUNCTYPE(ctypes.c_int32, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p)


class AtalhoGlobal:
    """Uma tecla global, sem permissão de Acessibilidade (RegisterEventHotKey).

    O laço de eventos do Cocoa que o Qt roda entrega o evento do Carbon; o
    callback só chama `ao_apertar`.
    """

    def __init__(self, ao_apertar):
        self._ao_apertar = ao_apertar
        self._ref = ctypes.c_void_p()
        self._atual = None
        c = ctypes.cdll.LoadLibrary("/System/Library/Frameworks/Carbon.framework/Carbon")
        c.GetApplicationEventTarget.restype = ctypes.c_void_p
        c.InstallEventHandler.argtypes = [ctypes.c_void_p, _HANDLER, ctypes.c_ulong,
                                          ctypes.POINTER(_EventTypeSpec), ctypes.c_void_p,
                                          ctypes.c_void_p]
        c.RegisterEventHotKey.argtypes = [ctypes.c_uint32, ctypes.c_uint32, _EventHotKeyID,
                                          ctypes.c_void_p, ctypes.c_uint32,
                                          ctypes.POINTER(ctypes.c_void_p)]
        c.UnregisterEventHotKey.argtypes = [ctypes.c_void_p]
        self._c = c
        self._cb = _HANDLER(self._evento)      # referência viva enquanto o objeto viver
        tipo = _EventTypeSpec(int.from_bytes(b"keyb", "big"), 5)   # kEventHotKeyPressed
        c.InstallEventHandler(c.GetApplicationEventTarget(), self._cb, 1,
                              ctypes.byref(tipo), None, None)

    def _evento(self, _chamada, _evento, _dados):
        try:
            self._ao_apertar()
        except Exception as e:  # noqa: BLE001 - nunca propaga para o Carbon
            print(f"orbe: atalho: {e}", file=sys.stderr)
        return 0

    def definir(self, texto: str):
        alvo = parse_atalho(texto)
        if alvo == self._atual:
            return
        if self._ref:
            self._c.UnregisterEventHotKey(self._ref)
            self._ref = ctypes.c_void_p()
        self._atual = alvo
        if alvo is None:
            if texto:
                print(f"orbe: atalho não reconhecido: {texto!r}", file=sys.stderr)
            return
        st = self._c.RegisterEventHotKey(alvo[0], alvo[1],
                                         _EventHotKeyID(int.from_bytes(b"orbe", "big"), 1),
                                         self._c.GetApplicationEventTarget(), 0,
                                         ctypes.byref(self._ref))
        if st != 0:
            print(f"orbe: atalho {texto!r} recusado (OSStatus {st}); outro app usa a tecla?",
                  file=sys.stderr)


# ── ponte com o QML ─────────────────────────────────────────────────────────

class Ponte(QObject):
    linha = Signal(str)
    configMudou = Signal()
    areaMudou = Signal()

    def __init__(self, app, sock_ctl: str, arq_config: Path):
        super().__init__()
        self._app = app
        self._ctl = sock_ctl
        self._arq = arq_config
        self._config = ""
        self._area = QRect()
        self._tela_vigiada = None
        self._ajustadas = set()
        self._vigia = QFileSystemWatcher(self)
        # o config é trocado por os.replace: vigia a pasta, não só o arquivo
        self._arq.parent.mkdir(parents=True, exist_ok=True)
        self._vigia.addPath(str(self._arq.parent))
        self._vigia.directoryChanged.connect(self._reler)
        self._vigia.fileChanged.connect(self._reler)
        self._reler()
        app.primaryScreenChanged.connect(self._tela)
        self._tela()

    # configuração
    def _reler(self, *_):
        try:
            texto = self._arq.read_text(encoding="utf-8")
        except OSError:
            texto = ""
        if self._arq.exists() and str(self._arq) not in self._vigia.files():
            self._vigia.addPath(str(self._arq))
        if texto != self._config:
            self._config = texto
            self.configMudou.emit()

    @Property(str, notify=configMudou)
    def config(self):
        return self._config

    # cor de destaque do sistema para a paleta do anel
    @Property(QColor, constant=True)
    def accent(self):
        cor = QGuiApplication.palette().color(QPalette.ColorRole.Accent)
        return cor if cor.isValid() else QColor("#0087fc")

    # área útil da tela principal (sem a barra de menus nem o Dock)
    def _tela(self, *_):
        tela = self._app.primaryScreen()
        if tela is None:
            return
        if tela is not self._tela_vigiada:
            if self._tela_vigiada is not None:
                self._tela_vigiada.availableGeometryChanged.disconnect(self._tela)
            tela.availableGeometryChanged.connect(self._tela)
            self._tela_vigiada = tela
        area = tela.availableGeometry()
        if area != self._area:
            self._area = area
            self.areaMudou.emit()

    @Property(QRect, notify=areaMudou)
    def area(self):
        return self._area

    @Slot(result=QPointF)
    def cursor(self):
        return QPointF(QCursor.pos())

    @Slot(bool)
    def tocar(self, dentro: bool):
        """Uma conexão por mensagem, como o daemon espera (lê até EOF)."""
        s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        s.settimeout(0.3)
        try:
            s.connect(self._ctl)
            s.sendall(b"touch down\n" if dentro else b"touch up\n")
        except OSError:
            pass
        finally:
            s.close()

    @Slot()
    def saiu(self):
        pass

    @Slot(QObject, float, float, float, float)
    def mascara(self, janela, x, y, w, h):
        if isinstance(janela, QQuickWindow):
            janela.setMask(QRegion(QRect(int(x), int(y), int(w), int(h)), QRegion.RegionType.Ellipse))

    @Slot(QObject)
    def ajustarJanela(self, janela):
        """Ajustes do NSWindow, uma vez por janela nativa (criada no 1º show)."""
        if not isinstance(janela, QQuickWindow):
            return
        wid = int(janela.winId())
        if wid in self._ajustadas:
            return
        self._ajustadas.add(wid)
        try:
            _ajustar_nswindow(wid)
        except Exception as e:  # noqa: BLE001
            print(f"orbe: ajuste do NSWindow falhou: {e}", file=sys.stderr)


class Servidor(QObject):
    """Socket do daemon: uma linha por comando, várias conexões."""

    def __init__(self, caminho: str, ponte: Ponte, app):
        super().__init__()
        self._ponte = ponte
        self._app = app
        self._srv = QLocalServer(self)
        QLocalServer.removeServer(caminho)
        try:
            os.unlink(caminho)
        except OSError:
            pass
        if not self._srv.listen(caminho):
            sys.exit(f"orbe: não abriu {caminho}: {self._srv.errorString()}")
        self._srv.newConnection.connect(self._nova)
        self.caminho = caminho
        self.inode = os.stat(caminho).st_ino

    def remover(self):
        """Apaga o socket só se ainda for o nosso: num reinício o orbe novo
        já pode ter criado outro no mesmo caminho."""
        try:
            if os.stat(self.caminho).st_ino == self.inode:
                os.unlink(self.caminho)
        except OSError:
            pass

    def _nova(self):
        while self._srv.hasPendingConnections():
            c = self._srv.nextPendingConnection()
            c.readyRead.connect(lambda c=c: self._ler(c))
            # sem isto cada conexão do orb_control ficaria na memória
            c.disconnected.connect(c.deleteLater)

    def _ler(self, c):
        while c.canReadLine():
            linha = bytes(c.readLine()).decode("utf-8", "replace").strip()
            if not linha:
                continue
            if linha == "quit":
                self._app.quit()
                return
            self._ponte.linha.emit(linha)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sock", default=str(vcfg.RUNTIME / "hermes-voice-orb.sock"))
    ap.add_argument("--ctl", default=str(vcfg.RUNTIME / "hermes-voice-ctl.sock"))
    ap.add_argument("--config", default=str(vcfg.CONFIG_PATH))
    ap.add_argument("--pai", type=int, default=0)
    args = ap.parse_args()
    previa = args.config != str(vcfg.CONFIG_PATH)

    QQuickWindow.setDefaultAlphaBuffer(True)
    app = QGuiApplication(sys.argv[:1])
    app.setApplicationName("Orbe")
    app.setQuitOnLastWindowClosed(False)
    # o texto do raciocínio pede "Sans" (fontconfig); no Mac é a do sistema
    QFont.insertSubstitution("Sans", app.font().family())
    try:
        _app_acessorio()
    except Exception as e:  # noqa: BLE001
        print(f"orbe: sem política de acessório: {e}", file=sys.stderr)

    ponte = Ponte(app, args.ctl, Path(args.config))
    servidor = Servidor(args.sock, ponte, app)

    # atalho global só na instância do daemon, nunca na pré-visualização
    atalho = None
    if not previa:
        cmd = vcfg.RUNTIME / "hermes-voice.cmd"

        def alternar():
            cmd.write_text("toggle\n")
        try:
            atalho = AtalhoGlobal(alternar)

            def reler_atalho():
                try:
                    atalho.definir(vcfg.carregar()["ativacao"]["atalho"])
                except Exception as e:  # noqa: BLE001
                    print(f"orbe: atalho: {e}", file=sys.stderr)
            ponte.configMudou.connect(reler_atalho)
            reler_atalho()
        except OSError as e:
            print(f"orbe: Carbon indisponível, sem atalho global: {e}", file=sys.stderr)

    eng = QQmlApplicationEngine()
    eng.rootContext().setContextProperty("ponte", ponte)
    eng.load(QUrl.fromLocalFile(str(AQUI / "orbe_mac.qml")))
    if not eng.rootObjects():
        sys.exit(1)

    # morre junto com o daemon ou com o app da pré-visualização
    if args.pai:
        vigia_pai = QTimer(app)
        vigia_pai.timeout.connect(lambda: os.getppid() != args.pai and app.quit())
        vigia_pai.start(1000)
    # Ctrl+C e SIGTERM saem limpo (o Python só vê sinais entre eventos)
    signal.signal(signal.SIGTERM, lambda *_: app.quit())
    signal.signal(signal.SIGINT, lambda *_: app.quit())
    tique = QTimer(app)
    tique.timeout.connect(lambda: None)
    tique.start(500)

    rc = app.exec()
    servidor.remover()
    del eng
    sys.exit(rc)


if __name__ == "__main__":
    main()
