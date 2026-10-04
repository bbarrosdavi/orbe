import QtQuick
import Quickshell

// Região de blur do vidro: um disco de borda limpa, um pouco menor que a
// tintura.
//
// O niri borra uma região binária, sem pluma: cada pixel é borrado ou não.
// Um degradê por pontilhado (tentado em 2026-10-03) vira chuvisco sobre texto.
// Então o blur para em `fracao` do raio e a tintura (pos.frag) fica cheia até
// aí e esmaece dali até a borda: a transição do blur cai onde a tintura ainda
// é forte e lê como a borda do disco.
Region {
    id: raiz

    property real cx: 0
    property real cy: 0
    property real raio: 0          // raio da tintura (anima na entrada e na saída)
    property real fracao: 0.82     // onde o blur termina, em fração do raio

    readonly property real r: Math.round(raio * fracao)
    shape: RegionShape.Ellipse
    x: Math.round(cx - r)
    y: Math.round(cy - r)
    width: 2 * r
    height: 2 * r
}
