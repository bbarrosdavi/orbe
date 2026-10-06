import QtQuick
import "../comum"
// Mede pe e topo de uma skin (OrbeConteudo.pes/topo): o orbe ouvindo, parado,
// sem glitch; medir_pe.py acha as linhas de cima e de baixo da figura.
Item {
    id: f
    width: o.width; height: o.height
    property string skin: "olho"
    OrbeConteudo {
        id: o
        skin: f.skin
        glitch: false
        Component.onCompleted: { o.comando("show listening"); o.faseT = 1 }
    }
    property string info: "orbBox=" + o.orbBox + " cx=" + o.cx + " cy=" + o.cy
    function passo(dt) { o.passo(dt) }
}
