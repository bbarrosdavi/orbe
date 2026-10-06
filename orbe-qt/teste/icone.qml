import QtQuick
import "../comum"

// O ícone do app: o Ophanim como o orbe desenha, olhando para quem olha,
// sobre fundo transparente. Renderizar com render.py (dpr=1) e compor o
// fundo depois (orbe.png do desktop, ic_launcher_foreground do relógio).
Item {
    id: f
    width: 512; height: 512
    property real t: 0
    Figura {
        id: fig
        anchors.centerIn: parent
        width: 430; height: 430
        skin: "ofanim"
        peso: 2.4
        mix: ({ idle: 0, listening: 1, thinking: 0, tools: 0, speaking: 0 })
        olharAlvo: Qt.point(width / 2, height / 2)
        mic: 0.3
    }
    function passo(dt) { t += dt; fig.avancar(dt) }
}
