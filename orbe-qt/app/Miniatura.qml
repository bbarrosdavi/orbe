import QtQuick
import "../comum"
import "."

// A figura de uma skin em tamanho de miniatura: Figura para os avatares,
// Anel (no estado de escuta, sem voz) para o anel de energia.
Item {
    id: m
    property string skin: "ofanim"
    property bool glitch: true
    property real peso: 1.2
    property real raio: -1                 // -1 = o maior que cabe
    property var olhar: null
    function avancar(dt) { if (arte.item) arte.item.avancar(dt) }

    Loader {
        id: arte
        anchors.centerIn: parent
        width: m.skin === "anel" ? Math.min(m.width, m.height) : m.width
        height: m.skin === "anel" ? width : m.height
        sourceComponent: m.skin === "anel" ? compAnel : compFigura
    }
    Component {
        id: compFigura
        Figura {
            skin: m.skin
            glitch: m.glitch
            peso: m.peso
            cor: Estilo.accent
            raioFixo: m.raio
            olharAlvo: m.olhar
        }
    }
    Component {
        id: compAnel
        Anel {
            esc: width / 148
            glitch: m.glitch
            accent: Estilo.anel
            olharAlvo: m.olhar ? Qt.point(m.olhar.x - arte.x, m.olhar.y - arte.y) : null
        }
    }
}
