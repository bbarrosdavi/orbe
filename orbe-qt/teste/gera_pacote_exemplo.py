#!/usr/bin/python3
"""Gera um pacote de skin de exemplo (formas simples) para testar o Pacote.qml.

Uso: gera_pacote_exemplo.py <pasta de skins>
Cria <pasta>/exemplo/skin.json e os PNGs, e <pasta>/solto.png (PNG solto).
A arte é geométrica de propósito: o teste é do carregador, não do desenho.
"""
import json
import math
import sys
from pathlib import Path

from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QColor, QGuiApplication, QImage, QPainter, QPainterPath, QPen, QPolygonF

Q = 1024


def nova():
    im = QImage(Q, Q, QImage.Format.Format_ARGB32_Premultiplied)
    im.fill(Qt.GlobalColor.transparent)
    return im


def pintor(im):
    p = QPainter(im)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    return p


def asa(lado, elev, comp, raiz):
    """Asa de penas: polígono com lóbulos, saindo da raiz na elevação dada."""
    im = nova()
    p = pintor(im)
    p.translate(*raiz)
    p.scale(lado, 1)
    p.rotate(-elev)
    path = QPainterPath(QPointF(0, 0))
    n = 7
    for i in range(n + 1):
        f = i / n
        x = comp * f
        y = -40 * math.sin(math.pi * f) - 10 * f
        path.lineTo(x, y)
    for i in range(n, -1, -1):
        f = i / n
        x = comp * f + 10
        y = 90 * (0.5 + 0.5 * f) * (1 - 0.3 * abs(math.sin(f * n * math.pi)))
        path.lineTo(x, y)
    path.closeSubpath()
    p.setPen(QPen(QColor("white"), 6))
    p.setBrush(QColor(255, 255, 255, 70))
    p.drawPath(path)
    for i in range(1, n):
        f = i / n
        p.drawLine(QPointF(comp * f, -8), QPointF(comp * f + 6, 85 * (0.5 + 0.5 * f)))
    p.end()
    return im


def disco(r, cx, cy, espessura, cheio):
    im = nova()
    p = pintor(im)
    p.setPen(QPen(QColor("white"), espessura))
    # só o alfa conta: um disco opaco esconderia o olho desenhado por cima
    p.setBrush(QColor(255, 255, 255, 50) if cheio else Qt.BrushStyle.NoBrush)
    p.drawEllipse(QPointF(cx, cy), r, r)
    p.end()
    return im


def olho_branco(cx, cy, w, h):
    im = nova()
    p = pintor(im)
    path = QPainterPath(QPointF(cx - w, cy))
    path.quadTo(cx, cy - h * 2, cx + w, cy)
    path.quadTo(cx, cy + h * 2, cx - w, cy)
    p.setPen(QPen(QColor("white"), 8))
    p.setBrush(QColor(255, 255, 255, 60))
    p.drawPath(path)
    p.end()
    return im


def chamas(cx, cy):
    im = nova()
    p = pintor(im)
    p.setPen(QPen(QColor("white"), 5))
    p.setBrush(Qt.BrushStyle.NoBrush)
    for j in range(16):
        a = j / 16 * 2 * math.pi
        r0, r1 = 150, 230 + 40 * ((j * 7) % 3)
        pts = []
        for k in range(6):
            u = k / 5
            r = r0 + (r1 - r0) * u
            da = 0.12 * math.sin(u * 6 + j)
            pts.append(QPointF(cx + math.cos(a + da) * r, cy + math.sin(a + da) * r))
        p.drawPolyline(QPolygonF(pts))
    p.end()
    return im


def main():
    QGuiApplication([])
    base = Path(sys.argv[1])
    d = base / "exemplo"
    d.mkdir(parents=True, exist_ok=True)
    cx = cy = Q / 2
    camadas = []
    for nome, lado, elev, comp, ry, fase in [
        ("asa_cima_esq", -1, 55, 330, cy - 60, 0.0), ("asa_cima_dir", 1, 55, 330, cy - 60, 0.0),
        ("asa_meio_esq", -1, 5, 400, cy, 0.8), ("asa_meio_dir", 1, 5, 400, cy, 0.8),
        ("asa_baixo_esq", -1, -50, 340, cy + 70, 1.6), ("asa_baixo_dir", 1, -50, 340, cy + 70, 1.6),
    ]:
        asa(lado, elev, comp, (cx, ry)).save(str(d / f"{nome}.png"))
        camadas.append({"arquivo": f"{nome}.png", "anim": "bater", "pivo": [cx, ry],
                        "lado": lado, "amplitude": 9, "fase": fase})
    chamas(cx, cy).save(str(d / "chamas.png"))
    camadas.append({"arquivo": "chamas.png", "anim": "pulsar", "amplitude": 0.08})
    disco(150, cx, cy, 6, True).save(str(d / "fundo.png"))
    camadas.append({"arquivo": "fundo.png", "anim": "respirar", "amplitude": 0.02})
    olho_branco(cx, cy, 120, 50).save(str(d / "olho_branco.png"))
    camadas.append({"arquivo": "olho_branco.png"})
    disco(44, cx, cy, 10, False).save(str(d / "olho_iris.png"))
    camadas.append({"arquivo": "olho_iris.png", "anim": "olhar", "mascara": "olho_branco.png", "alcance": 60})
    (d / "skin.json").write_text(json.dumps(
        {"nome": "Exemplo de camadas", "quadro": Q, "escala": 0.95, "camadas": camadas},
        ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    # PNG solto: uma camada só
    disco(300, cx, cy, 40, False).save(str(base / "solto.png"))
    print(d)


if __name__ == "__main__":
    main()
