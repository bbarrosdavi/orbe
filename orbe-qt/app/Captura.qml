import QtQuick
import "."

// Modo --captura: o corpo do app sobre um "papel de parede", para ver a
// translucidez no PNG.
Item {
    width: 500
    height: 700
    property alias pagina: conteudo.pagina
    Rectangle {
        anchors.fill: parent
        radius: 18
        gradient: Gradient {
            GradientStop { position: 0.0; color: "#1b2a3a" }
            GradientStop { position: 0.5; color: "#3a2236" }
            GradientStop { position: 1.0; color: "#14302c" }
        }
    }
    Conteudo {
        id: conteudo
        anchors.fill: parent
    }
    function passo(dt) { conteudo.passo(dt) }
}
