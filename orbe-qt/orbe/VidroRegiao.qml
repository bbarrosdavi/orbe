import QtQuick
import Quickshell

// Região de blur do vidro, com a borda sumindo aos poucos.
//
// O niri borra uma região binária: cada pixel é borrado ou não, sem pluma.
// O degradê vem de um pontilhado ordenado (Bayer 4x4): o pixel (x, y) entra
// quando o limiar da matriz fica abaixo da força do vidro naquele raio, e a
// força cai em smoothstep de `inicio` até a borda. Cada um dos 16 cossets da
// rede 4x4 vira então um disco de raio próprio, recortado pelas listras da
// sua coluna e da sua linha. Na animação só mudam as 16 elipses; as listras
// (8 grupos, compartilhados entre os cossets) mudam quando muda o tamanho.
// O Quickshell reconstrói a região uma vez por quadro, no polish da janela.
Region {
    id: raiz

    property real cx: 0
    property real cy: 0
    property real raio: 0          // raio atual (anima na entrada e na saída)
    property real raioMax: 71      // maior raio possível: dimensiona as listras
    property real inicio: 0.45     // fração do raio em que o pontilhado começa

    readonly property var bayer: [[0, 8, 2, 10], [12, 4, 14, 6], [3, 11, 1, 9], [15, 7, 13, 5]]
    property var _grupos: []
    property var _cossets: []
    property var _fracoes: []

    // inline numa propriedade: o filho padrão de Region é a lista `regions`
    property Component comp: Component { Region {} }
    property bool _pronto: false

    // raio relativo em que sai o cosset de limiar v: força(r) > (v + 0.5)/16
    function fracao(v) {
        var y = 1 - (v + 0.5) / 16
        var q = 0.5 - Math.sin(Math.asin(1 - 2 * y) / 3)     // inversa do smoothstep
        return inicio + (1 - inicio) * q
    }

    function construir() {
        if (!_pronto) return
        regions = []
        for (var i = 0; i < _cossets.length; i++) _cossets[i].destroy()
        for (i = 0; i < _grupos.length; i++) _grupos[i].destroy()
        var R = Math.ceil(raioMax) + 2
        var x0 = Math.floor((cx - R) / 4) * 4, y0 = Math.floor((cy - R) / 4) * 4
        var x1 = Math.ceil(cx + R), y1 = Math.ceil(cy + R)
        var v = [], h = [], grupos = []
        for (var a = 0; a < 4; a++) {
            var gv = comp.createObject(raiz, { intersection: Intersection.Intersect })
            var lv = []
            for (var x = x0 + a; x < x1; x += 4)
                lv.push(comp.createObject(gv, { x: x, y: y0, width: 1, height: y1 - y0 }))
            gv.regions = lv
            var gh = comp.createObject(raiz, { intersection: Intersection.Intersect })
            var lh = []
            for (var y = y0 + a; y < y1; y += 4)
                lh.push(comp.createObject(gh, { x: x0, y: y, width: x1 - x0, height: 1 }))
            gh.regions = lh
            v.push(gv); h.push(gh); grupos.push(gv, gh)
        }
        var cs = [], fr = []
        for (var b = 0; b < 4; b++) {
            for (a = 0; a < 4; a++) {
                var c = comp.createObject(raiz, { shape: RegionShape.Ellipse })
                c.regions = [v[a], h[b]]
                cs.push(c)
                fr.push(fracao(bayer[b][a]))
            }
        }
        _grupos = grupos
        _cossets = cs
        _fracoes = fr
        regions = cs
        atualizar()
    }

    function atualizar() {
        for (var i = 0; i < _cossets.length; i++) {
            var r = Math.round(raio * _fracoes[i])
            var c = _cossets[i]
            c.x = Math.round(cx - r)
            c.y = Math.round(cy - r)
            c.width = 2 * r
            c.height = 2 * r
        }
    }

    onRaioChanged: atualizar()
    onCxChanged: construir()
    onCyChanged: construir()
    onRaioMaxChanged: construir()
    onInicioChanged: construir()
    Component.onCompleted: { _pronto = true; construir() }
}
