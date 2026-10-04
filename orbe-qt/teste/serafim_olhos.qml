import QtQuick
import "../comum"

// Seraphim: uma linha por arranjo de olhos, uma coluna por estado.
Rectangle {
    id: folha
    property int lado: 200
    readonly property var modos: [["só o de cima", 0], ["só o do meio", 1], ["os dois", 2],
                                  ["só o do meio,\nvertical", 3], ["os dois, o do\nmeio vertical", 4]]
    readonly property var estados: [["idle", "idle"], ["ouvindo", "listening"], ["pensando", "thinking"], ["respondendo", "speaking"]]
    width: 130 + lado * estados.length
    height: 24 + lado * modos.length
    color: "#1d2324"

    Repeater {
        model: folha.estados.length
        Text {
            x: 130 + index * folha.lado; width: folha.lado; y: 4
            horizontalAlignment: Text.AlignHCenter
            text: folha.estados[index][0]; color: "#c8d0d0"; font.pixelSize: 13
        }
    }
    Repeater {
        model: folha.modos.length
        Text {
            x: 8; y: 24 + index * folha.lado + folha.lado / 2 - height / 2
            text: folha.modos[index][0]; color: "#c8d0d0"; font.pixelSize: 13
        }
    }
    Grid {
        id: grade
        x: 130; y: 24
        columns: folha.estados.length
        Repeater {
            model: folha.modos.length * folha.estados.length
            Figura {
                width: folha.lado; height: folha.lado
                skin: "serafim"
                olhosSerafim: folha.modos[Math.floor(index / folha.estados.length)][1]
                property string estado: folha.estados[index % folha.estados.length][1]
                mix: { var m = { idle: 0, listening: 0, thinking: 0, tools: 0, speaking: 0 }; m[estado] = 1; return m }
                peso: 1.4
                cor: "#b8cacb"
                voz: estado === "speaking" ? 0.7 : 0
                mic: estado === "listening" ? 0.4 : 0
                olharAlvo: Qt.point(-300, 260)
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
