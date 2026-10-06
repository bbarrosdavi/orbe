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
# recorte, ponto OLHO e RIMG de cada uma (os do imagem.frag) e, no Olho, a peça
# guardada num canto (o disco da íris: canto, centro do canto, centro no olho,
# lado): na pose desenhada ela volta ao lugar, e o canto fica vazio
SKINS = {"olho": ((505, 609), (260.0, 284.5), 270.0, ((0, 514), (47.5, 561.5), (285.5, 279.6), 95)),
         "humana": ((517, 492), (258.5, 246.0), 255.0, None)}

def ler(caminho):
    im = QImage(str(caminho)).convertToFormat(QImage.Format.Format_RGBA8888_Premultiplied)
    a = np.frombuffer(im.constBits(), np.uint8).reshape(im.height(), im.bytesPerLine())[:, :im.width() * 4]
    return a.reshape(im.height(), im.width(), 4).astype(np.float64) / 255

skin = sys.argv[1]
(tw, th), (ox, oy), rimg, guardada = SKINS[skin]
W = round(2 * max(ox, tw - ox)); H = round(2 * max(oy, th - oy))
x0, y0 = round(W / 2 - ox), round(H / 2 - oy)
with tempfile.TemporaryDirectory() as d:
    saida = Path(d) / "saida.png"
    subprocess.run([sys.executable, str(AQUI / "render.py"), str(AQUI / "repouso.qml"), str(saida), "3", "dpr=1",
                    f"skin={skin}", f"rimg={rimg}", f"width={W}", f"height={H}"], check=True)
    out = ler(saida)[y0:y0 + th, x0:x0 + tw]
atlas = ler(AQUI.parent / "arte" / f"{skin}.png")
R, G = atlas[..., 0].copy(), atlas[..., 1].copy()
if guardada:
    (cx, cy), (sx, sy), (px, py), lado = guardada
    sR, sG = R[cy:cy + lado, cx:cx + lado].copy(), G[cy:cy + lado, cx:cx + lado].copy()
    R[cy:cy + lado, cx:cx + lado] = 0
    G[cy:cy + lado, cx:cx + lado] = 0
    dx, dy = round(px - sx), round(py - sy)
    y0, x0 = cy + dy, cx + dx
    R[y0:y0 + lado, x0:x0 + lado] = sR + R[y0:y0 + lado, x0:x0 + lado] * (1 - sG)
    G[y0:y0 + lado, x0:x0 + lado] = sG + G[y0:y0 + lado, x0:x0 + lado] * (1 - sG)
A = R
E = np.where(G > A, np.minimum((G - A) / np.maximum(1 - A, 1e-4), 1), 0)
dA = np.abs(out[..., 0] - A) * 255
dE = np.abs(out[..., 1] - E) * 255
if guardada:
    # o disco volta reamostrado (fração de pixel): fora da conta exata, com o erro médio à parte
    yy, xx = np.mgrid[0:th, 0:tw]
    no_disco = np.hypot(xx + 0.5 - guardada[2][0], yy + 0.5 - guardada[2][1]) <= 46
    print(f"  no disco da íris: dif média {dA[no_disco].mean():.2f}, máx {dA[no_disco].max():.0f}")
    dA, dE = dA * ~no_disco, dE * ~no_disco
print(f"{skin}: {tw}x{th} px; traço: dif máx {dA.max():.1f}, média {dA.mean():.3f}, pixels com dif > 1: {(dA > 1.01).sum()}; "
      f"massa: dif máx {dE.max():.1f}, pixels com dif > 1: {(dE > 1.01).sum()}")
