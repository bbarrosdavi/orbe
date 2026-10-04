import QtQuick
import "."

// Botão de texto: chapado, ou em pílula na cor de destaque (o "Aplicar").
// `ligado` tinge o chapado de destaque, para botões que alternam.
Rectangle {
    id: b
    property string texto
    property bool destaque: false
    property bool ligado: false
    signal clicado()
    width: rotulo.implicitWidth + (destaque ? 64 : 24)
    height: destaque ? 42 : 32
    radius: height / 2
    color: destaque ? (hv.hovered ? Qt.lighter(Estilo.accent, 1.06) : Estilo.accent)
         : ligado ? Estilo.alfa(Estilo.accent, hv.hovered ? 0.28 : 0.20)
                  : Estilo.alfa(Estilo.texto, hv.hovered ? 0.12 : 0.0)
    Text {
        id: rotulo
        anchors.centerIn: parent
        text: b.texto
        color: b.destaque ? Estilo.accentFg : b.ligado ? Estilo.accent : Estilo.texto
        font.pointSize: 11
        font.bold: true
    }
    HoverHandler { id: hv }
    TapHandler { onTapped: b.clicado() }
}
