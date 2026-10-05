import QtQuick
import "."

// Chave de API na própria linha, escondida enquanto não está em edição. Vazia,
// a linha diz o que vale no lugar ([herda]: a do Hermes, a do ambiente ou nada).
Item {
    id: r
    property string titulo
    property string herda
    property alias texto: campo.text
    width: parent ? parent.width : 300
    implicitHeight: 58
    height: visible ? implicitHeight : 0
    readonly property bool cheio: campo.text.length > 0 || campo.activeFocus

    Rectangle {
        visible: r.y > 0
        width: parent.width
        height: 1
        color: Estilo.alfa(Estilo.texto, 0.08)
    }
    Rectangle {
        anchors.fill: parent
        anchors.margins: 1
        radius: 11
        color: Estilo.alfa(Estilo.accent, hv.hovered ? 0.07 : 0)
    }
    HoverHandler { id: hv }
    TapHandler { onTapped: campo.forceActiveFocus() }
    Text {
        x: 14
        y: r.cheio ? 9 : (r.height - height) / 2
        text: r.titulo
        color: r.cheio && campo.activeFocus ? Estilo.accent : Estilo.texto
        opacity: r.cheio ? 0.7 : 0.55
        font.pointSize: r.cheio ? 9 : 11
        Behavior on y { NumberAnimation { duration: 120 } }
    }
    Text {
        // vazia: o que vale no lugar dela
        visible: !r.cheio
        anchors.right: parent.right
        anchors.rightMargin: 14
        anchors.verticalCenter: parent.verticalCenter
        text: r.herda
        color: Estilo.texto
        opacity: 0.45
        font.pointSize: 9
    }
    TextInput {
        id: campo
        x: 14
        y: 28
        width: r.width - 28
        color: Estilo.texto
        selectionColor: Estilo.alfa(Estilo.accent, 0.4)
        font.pointSize: 11
        font.family: "monospace"
        clip: true
        selectByMouse: true
        echoMode: activeFocus ? TextInput.Normal : TextInput.Password
        opacity: r.cheio ? 1 : 0
    }
}
