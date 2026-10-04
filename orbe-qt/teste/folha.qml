import QtQuick
import "../comum"

// Folha de contato: uma linha por figura, uma coluna por estado.
Rectangle {
    id: folha
    property int lado: 148
    property var skins: ["ofanim", "ofanim_alado", "serafim"]
    property var estados: ["listening", "thinking", "tools", "speaking"]
    property color fundo: "#1d2324"
    property bool vidro: false
    width: lado * estados.length
    height: lado * skins.length
    color: fundo

    Grid {
        id: grade
        columns: folha.estados.length
        Repeater {
            model: folha.skins.length * folha.estados.length
            Figura {
                width: folha.lado; height: folha.lado
                skin: folha.skins[Math.floor(index / folha.estados.length)]
                property string estado: folha.estados[index % folha.estados.length]
                mix: { var m = { listening: 0, thinking: 0, tools: 0, speaking: 0 }; m[estado] = 1; return m }
                peso: 1.4
                cor: "#b8cacb"
                voz: estado === "speaking" ? 0.8 : 0
                mic: estado === "listening" ? 0.3 : 0
                olharAlvo: Qt.point(-600, 400)
                sombraLigada: folha.vidro
                sombraRaio: folha.lado / 2 - 3
                disco: folha.vidro ? folha.lado / 2 - 5 : -1
            }
        }
    }

    function passo(dt) {
        for (var i = 0; i < grade.children.length; i++) {
            var f = grade.children[i]
            if (f.avancar) f.avancar(dt)
        }
    }
}
