import QtQuick
import "../comum"
import "."

// A figura de uma skin em tamanho de miniatura: Figura para os avatares,
// Anel (no estado de escuta, sem voz) para o anel de energia, Pacote para
// uma skin de camadas.
Item {
    id: m
    property string skin: "ofanim"
    property bool glitch: true
    property real peso: 1.2
    property real raio: -1                 // -1 = o maior que cabe
    property var olhar: null
    readonly property bool anel: skin === "anel"
    readonly property var pacote: ["ofanim", "ofanim_alado", "serafim", "anel"].indexOf(skin) < 0 ? ponte.pacote(skin) : null
    function avancar(dt) { if (arte.item) arte.item.avancar(dt) }

    Loader {
        id: arte
        anchors.centerIn: parent
        width: m.anel ? Math.min(m.width, m.height) : m.width
        height: m.anel ? width : m.height
        sourceComponent: m.anel ? compAnel : (m.pacote ? compPacote : compFigura)
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
        id: compPacote
        Pacote {
            dir: m.pacote ? m.pacote.dir : ""
            manifesto: m.pacote ? m.pacote.manifesto : ({})
            glitch: m.glitch
            cor: Estilo.accent
            olharAlvo: m.olhar
            zoom: m.raio > 0 ? Math.min(1, m.raio * 2.2 / Math.min(width, height)) : 1
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
