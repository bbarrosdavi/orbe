import QtQuick
import "."

// Miniatura animada de uma skin no seletor da Aparência.
Rectangle {
    id: c
    property string skin
    property string nome
    property bool marcado: false
    property bool glitch: true
    signal escolhido()
    function avancar(dt) { mini.avancar(dt) }
    height: 150
    radius: 14
    color: c.marcado ? Estilo.alfa(Estilo.accent, 0.14) : Estilo.alfa(Estilo.texto, hv.hovered ? 0.07 : 0.04)
    border.width: 1
    border.color: c.marcado ? Estilo.alfa(Estilo.accent, 0.55) : Estilo.alfa(Estilo.texto, 0.08)
    HoverHandler { id: hv }
    TapHandler { onTapped: c.escolhido() }
    Miniatura {
        id: mini
        x: 6
        y: 6
        width: parent.width - 12
        height: 118
        skin: c.skin
        glitch: c.glitch
    }
    Text {
        anchors.horizontalCenter: parent.horizontalCenter
        anchors.bottom: parent.bottom
        anchors.bottomMargin: 8
        text: c.nome
        color: c.marcado ? Estilo.accent : Estilo.texto
        font.pointSize: 9
        font.bold: true
    }
}
