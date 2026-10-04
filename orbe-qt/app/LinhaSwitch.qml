import QtQuick
import "."

Linha {
    id: r
    property bool ligado: false
    clicavel: true
    onClicado: ligado = !ligado
    Rectangle {
        anchors.verticalCenter: parent.verticalCenter
        width: 46
        height: 26
        radius: 13
        color: r.ligado ? Estilo.accent : Estilo.alfa(Estilo.texto, 0.16)
        Behavior on color { ColorAnimation { duration: 120 } }
        Rectangle {
            width: 20
            height: 20
            radius: 10
            y: 3
            x: r.ligado ? 23 : 3
            color: r.ligado ? Estilo.accentFg : Estilo.texto
            Behavior on x { NumberAnimation { duration: 120; easing.type: Easing.OutCubic } }
        }
    }
}
