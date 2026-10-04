import QtQuick
import "."

// Tamanho do orbe na tela. O botão do slider é a miniatura viva da skin
// escolhida.
Item {
    id: s
    property real valor: 1.0
    property real de: 0.6
    property real ate: 1.6
    property real passo: 0.05
    property string skin: "ofanim"
    property bool glitch: true
    readonly property int lado: 44
    readonly property real fracao: (valor - de) / (ate - de)
    function avancar(dt) { mini.avancar(dt) }
    function definir(v) {
        v = Math.min(ate, Math.max(de, de + Math.round((v - de) / passo) * passo))
        valor = parseFloat(v.toFixed(2))
    }
    width: parent ? parent.width : 300
    implicitHeight: 104
    height: visible ? implicitHeight : 0

    Rectangle {
        visible: s.y > 0
        width: parent.width
        height: 1
        color: Estilo.alfa(Estilo.texto, 0.08)
    }
    Column {
        x: 14
        y: 12
        spacing: 2
        Text {
            text: "Tamanho"
            color: Estilo.texto
            font.pointSize: 11
        }
        Text {
            text: "escala do orbe na tela"
            color: Estilo.texto
            opacity: 0.55
            font.pointSize: 9
        }
    }
    Text {
        anchors.right: parent.right
        anchors.rightMargin: 14
        y: 14
        text: Math.round(s.valor * 100) + "%"
        color: Estilo.accent
        font.pointSize: 11
        font.bold: true
    }

    Item {
        id: trilho
        x: 14 + s.lado / 2
        width: s.width - 28 - s.lado
        y: 72
        height: 6
        Rectangle {
            anchors.fill: parent
            radius: 3
            color: Estilo.alfa(Estilo.texto, 0.12)
        }
        Rectangle {
            width: s.fracao * parent.width
            height: parent.height
            radius: 3
            color: Estilo.alfa(Estilo.accent, 0.75)
        }
        Rectangle {
            // marca do tamanho original
            x: (1.0 - s.de) / (s.ate - s.de) * parent.width - 1
            y: -4
            width: 2
            height: parent.height + 8
            radius: 1
            color: Estilo.alfa(Estilo.texto, 0.35)
        }
    }
    Item {
        id: botao
        width: s.lado
        height: s.lado
        x: trilho.x + s.fracao * trilho.width - s.lado / 2
        y: trilho.y + trilho.height / 2 - s.lado / 2
        scale: arrasto.pressed ? 1.12 : (hv.hovered ? 1.05 : 1.0)
        Behavior on scale { NumberAnimation { duration: 120 } }
        Rectangle {
            anchors.fill: parent
            radius: width / 2
            color: Qt.rgba(Estilo.fundo.r, Estilo.fundo.g, Estilo.fundo.b, 0.92)
            border.width: 1.5
            border.color: Estilo.alfa(Estilo.accent, 0.7)
        }
        Miniatura {
            id: mini
            anchors.fill: parent
            anchors.margins: 3
            skin: s.skin
            glitch: s.glitch
            peso: 0.9
        }
    }
    HoverHandler { id: hv }
    MouseArea {
        id: arrasto
        x: 0
        y: trilho.y - s.lado / 2
        width: s.width
        height: s.lado
        preventStealing: true
        onPressed: mouse => s.definir(s.de + (mouse.x - trilho.x) / trilho.width * (s.ate - s.de))
        onPositionChanged: mouse => { if (pressed) s.definir(s.de + (mouse.x - trilho.x) / trilho.width * (s.ate - s.de)) }
        onWheel: wheel => s.definir(s.valor + (wheel.angleDelta.y > 0 ? s.passo : -s.passo))
    }
}
