"""Renderiza a skin de imagem na pose desenhada a 1:1 e compara com o atlas.

Uso: repouso.py <skin>   (olho | humana)
A saída do passe da máscara é (A, E): A = traço, E = massa por baixo dele
(imagem.frag). Do atlas (R = traço, G = cobertura) sai o esperado:
A = R, E = (G - R) / (1 - R).
"""
import subprocess, sys, tempfile
from pathlib import Path
import numpy as np
from PySide6.QtGui import QImage

AQUI = Path(__file__).resolve().parent
# recorte, ponto OLHO e RIMG de cada uma (os do imagem.frag), e o disco que o
# shader desenha por cima do recorte (a íris do Olho), fora da conta
SKINS = {"olho": ((505, 609), (260.0, 284.5), 270.0, (285.5, 279.6, 43.5)), "humana": ((517, 492), (258.5, 246.0), 255.0, None)}

def ler(caminho):
    im = QImage(str(caminho)).convertToFormat(QImage.Format.Format_RGBA8888_Premultiplied)
    a = np.frombuffer(im.constBits(), np.uint8).reshape(im.height(), im.bytesPerLine())[:, :im.width() * 4]
    return a.reshape(im.height(), im.width(), 4).astype(np.float64) / 255

skin = sys.argv[1]
(tw, th), (ox, oy), rimg, desenhado = SKINS[skin]
W = round(2 * max(ox, tw - ox)); H = round(2 * max(oy, th - oy))
x0, y0 = round(W / 2 - ox), round(H / 2 - oy)
with tempfile.TemporaryDirectory() as d:
    saida = Path(d) / "saida.png"
    subprocess.run([sys.executable, str(AQUI / "render.py"), str(AQUI / "repouso.qml"), str(saida), "3", "dpr=1",
                    f"skin={skin}", f"rimg={rimg}", f"width={W}", f"height={H}"], check=True)
    out = ler(saida)[y0:y0 + th, x0:x0 + tw]
atlas = ler(AQUI.parent / "arte" / f"{skin}.png")
R, G = atlas[..., 0], atlas[..., 1]
A = R
E = np.where(G > A, np.minimum((G - A) / np.maximum(1 - A, 1e-4), 1), 0)
dA = np.abs(out[..., 0] - A) * 255
dE = np.abs(out[..., 1] - E) * 255
if desenhado:
    yy, xx = np.mgrid[0:th, 0:tw]
    fora = np.hypot(xx + 0.5 - desenhado[0], yy + 0.5 - desenhado[1]) > desenhado[2]
    dA, dE = dA * fora, dE * fora
print(f"{skin}: {tw}x{th} px; traço: dif máx {dA.max():.1f}, média {dA.mean():.3f}, pixels com dif > 1: {(dA > 1.01).sum()}; "
      f"massa: dif máx {dE.max():.1f}, pixels com dif > 1: {(dE > 1.01).sum()}")
