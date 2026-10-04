import QtQuick
import "."

// Campo de texto na própria linha: o título vira rótulo pequeno ao preencher.
Item {
    id: r
    property string titulo
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
    TextInput {
        id: campo
        x: 14
        y: 28
        width: r.width - 28
        color: Estilo.texto
        selectionColor: Estilo.alfa(Estilo.accent, 0.4)
        font.pointSize: 11
        clip: true
        selectByMouse: true
        opacity: r.cheio ? 1 : 0
    }
}
