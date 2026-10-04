import QtQuick
import "."

// Botão redondo e chapado com um ícone (o "flat" do libadwaita).
Rectangle {
    id: b
    property string icone
    property int lado: 30
    property bool ativo: true
    property bool fundo: false
    signal clicado()
    width: lado
    height: lado
    radius: lado / 2
    anchors.verticalCenter: parent ? parent.verticalCenter : undefined
    opacity: ativo ? 1 : 0.4
    color: Estilo.alfa(Estilo.texto, hv.hovered && ativo ? 0.12 : (fundo ? 0.08 : 0))
    Icone {
        anchors.centerIn: parent
        nome: b.icone
    }
    HoverHandler { id: hv }
    TapHandler {
        enabled: b.ativo
        onTapped: b.clicado()
    }
}
