import QtQuick
import "../comum"

// Pacote de camadas nos quatro estados, com e sem glitch.
Rectangle {
    id: folha
    property int lado: 220
    property url dir
    property var manifesto: ({})
    readonly property var estados: ["idle", "listening", "thinking", "speaking"]
    width: lado * estados.length
    height: lado * 2
    color: "#1d2324"
    Grid {
        id: grade
        columns: folha.estados.length
        Repeater {
            model: folha.estados.length * 2
            Pacote {
                width: folha.lado; height: folha.lado
                dir: folha.dir
                manifesto: folha.manifesto
                property string est: folha.estados[index % folha.estados.length]
                mix: { var m = { idle: 0, listening: 0, thinking: 0, tools: 0, speaking: 0 }; m[est] = 1; return m }
                glitch: index >= folha.estados.length
                cor: "#b8cacb"
                voz: est === "speaking" ? 0.7 : 0
                mic: est === "listening" ? 0.5 : 0
                olharAlvo: Qt.point(-200, 300)
            }
        }
    }
    function passo(dt) {
        for (var i = 0; i < grade.children.length; i++)
            if (grade.children[i].avancar) grade.children[i].avancar(dt)
    }
}
