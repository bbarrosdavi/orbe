import QtQuick
import QtQuick.Window
import "."

// Janela do app: sem moldura, fundo translúcido (o blur é da regra do niri
// para io.orbe.Orbe). Fechar sai do processo.
Window {
    id: janela
    width: 500
    height: 700
    visible: true
    color: "transparent"
    flags: Qt.Window | Qt.FramelessWindowHint
    title: "Orbe"

    Conteudo {
        id: conteudo
        anchors.fill: parent
        janela: janela
    }
    // anda no vsync e para sozinho com a janela escondida
    FrameAnimation {
        running: janela.visible
        onTriggered: conteudo.passo(Math.min(frameTime, 0.1))
    }
    onClosing: Qt.quit()
    Connections {
        target: ponte
        function onApresentar() {
            janela.raise()
            janela.requestActivate()
        }
    }
}
