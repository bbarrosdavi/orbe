import QtQuick
import Quickshell

// Região de blur do vidro: um disco de borda limpa, um pouco menor que a
// tintura.
//
// O niri borra uma região binária, sem pluma: cada pixel é borrado ou não.
// Um degradê por pontilhado (tentado em 2026-10-03) vira chuvisco sobre texto.
// Então o blur fica só no miolo (`fracao` do raio), onde a tintura (pos.frag)
// ainda é forte e encobre a transição; dali até a borda só a tintura, em
// degradê até zero, com o fundo aparecendo.
Region {
    id: raiz

    property real cx: 0
    property real cy: 0
    property real raio: 0          // raio da tintura (anima na entrada e na saída)
    property real fracao: 0.55     // onde o blur termina, em fração do raio

    readonly property real r: Math.round(raio * fracao)
    shape: RegionShape.Ellipse
    x: Math.round(cx - r)
    y: Math.round(cy - r)
    width: 2 * r
    height: 2 * r
}
