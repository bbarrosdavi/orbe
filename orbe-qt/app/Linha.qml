import QtQuick
import "."

// Linha de uma caixa de preferências: título, subtítulo e o que vier à direita.
Item {
    id: l
    property string titulo
    property string subtitulo
    property bool clicavel: false
    signal clicado()
    default property alias sufixo: caixa.data
    width: parent ? parent.width : 300
    implicitHeight: Math.max(52, textos.implicitHeight + 20)
    height: visible ? implicitHeight : 0

    Rectangle {
        visible: l.y > 0
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
    TapHandler {
        enabled: l.clicavel
        onTapped: l.clicado()
    }
    Column {
        id: textos
        anchors.left: parent.left
        anchors.leftMargin: 14
        anchors.right: caixa.left
        anchors.rightMargin: 10
        anchors.verticalCenter: parent.verticalCenter
        spacing: 2
        Text {
            width: parent.width
            text: l.titulo
            color: Estilo.texto
            font.pointSize: 11
            elide: Text.ElideRight
        }
        Text {
            width: parent.width
            text: l.subtitulo
            visible: text !== ""
            color: Estilo.texto
            opacity: 0.55
            font.pointSize: 9
            wrapMode: Text.Wrap
        }
    }
    Row {
        id: caixa
        anchors.right: parent.right
        anchors.rightMargin: 12
        anchors.verticalCenter: parent.verticalCenter
        spacing: 6
    }
}
