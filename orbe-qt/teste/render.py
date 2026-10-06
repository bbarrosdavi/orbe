"""Renderiza uma cena QML offscreen pela GPU (QQuickRenderControl + FBO), sem janela.

Uso: render.py cena.qml saida.png [quadros] [prop=valor ...]
A cena pode ter passo(dt): é chamada antes de cada quadro, a 60 Hz (ou dt=).
"""
import sys, time
from PySide6.QtCore import QUrl, QSize, QMetaObject, Q_ARG, Qt
from PySide6.QtGui import QColor, QGuiApplication, QOpenGLContext, QOffscreenSurface, QSurfaceFormat
from PySide6.QtOpenGL import QOpenGLFramebufferObject, QOpenGLFramebufferObjectFormat
from PySide6.QtQml import QQmlEngine, QQmlComponent
from PySide6.QtQuick import QQuickRenderControl, QQuickWindow, QQuickGraphicsDevice, QQuickRenderTarget

cena, saida = sys.argv[1], sys.argv[2]
quadros = int(sys.argv[3]) if len(sys.argv) > 3 else 90
props = dict(a.split("=", 1) for a in sys.argv[4:])
app = QGuiApplication(sys.argv[:1])
fmt = QSurfaceFormat(); fmt.setAlphaBufferSize(8)
ctx = QOpenGLContext(); ctx.setFormat(fmt); ctx.create()
surf = QOffscreenSurface(); surf.setFormat(ctx.format()); surf.create()
ctx.makeCurrent(surf)
rc = QQuickRenderControl()
win = QQuickWindow(rc)
win.setColor(QColor(0, 0, 0, 0))     # fora de um Rectangle raiz, o fundo sai transparente
win.setGraphicsDevice(QQuickGraphicsDevice.fromOpenGLContext(ctx))
eng = QQmlEngine()
comp = QQmlComponent(eng, QUrl.fromLocalFile(cena))
root = comp.create()
if root is None:
    print(comp.errorString()); sys.exit(1)
for k, v in props.items():
    root.setProperty(k, {"true": True, "false": False}.get(v, v))
root.setParentItem(win.contentItem())
dpr = float(props.get("dpr", 1.25))
passo_dt = float(props.get("dt", 1 / 60))
W, H = int(root.width()), int(root.height())
win.resize(W, H); win.contentItem().setSize(root.size())
rc.initialize()
pw, ph = int(W * dpr), int(H * dpr)
ff = QOpenGLFramebufferObjectFormat(); ff.setAttachment(QOpenGLFramebufferObject.CombinedDepthStencil)
fbo = QOpenGLFramebufferObject(QSize(pw, ph), ff)
rt = QQuickRenderTarget.fromOpenGLTexture(fbo.texture(), QSize(pw, ph))
rt.setDevicePixelRatio(dpr)
win.setRenderTarget(rt)
tem_passo = root.metaObject().indexOfMethod("passo(QVariant)") >= 0
gl = ctx.functions()
tempos = []
tempos_js = []
for i in range(quadros):
    if tem_passo:
        tj = time.perf_counter()
        QMetaObject.invokeMethod(root, "passo", Q_ARG("QVariant", passo_dt))
        tempos_js.append(time.perf_counter() - tj)
    t0 = time.perf_counter()
    rc.polishItems(); rc.beginFrame(); rc.sync(); rc.render(); rc.endFrame()
    gl.glFinish()
    tempos.append(time.perf_counter() - t0)
info = root.property("info")
if info:
    print(info)
img = fbo.toImage()
img.save(saida)
med = sorted(tempos[5:])[len(tempos[5:]) // 2] * 1000 if len(tempos) > 6 else tempos[-1] * 1000
js = sorted(tempos_js[5:])[len(tempos_js[5:]) // 2] * 1000 if len(tempos_js) > 6 else 0.0
print(f"{pw}x{ph}  quadro (mediana, CPU+GPU): {med:.2f} ms  passo JS: {js:.2f} ms  primeiro: {tempos[0]*1000:.0f} ms")
# solta na ordem certa: a render control antes do contexto (senão o teardown cai)
del rt, fbo
win.setRenderTarget(QQuickRenderTarget())
root.deleteLater(); del root, comp
rc.invalidate(); del win, rc
ctx.doneCurrent()
