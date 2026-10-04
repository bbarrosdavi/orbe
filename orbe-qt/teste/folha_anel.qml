import QtQuick
import "../comum"

Rectangle {
    id: folha
    property int lado: 148
    property var estados: ["idle", "listening", "thinking", "speaking"]
    property bool soFala: false
    property real t: 0
    width: lado * estados.length
    height: lado * 2
    color: "#1d2324"
    Grid {
        id: grade
        columns: folha.estados.length
        Repeater {
            model: folha.estados.length * 2
            Anel {
                width: folha.lado; height: folha.lado
                property string est: folha.estados[index % folha.estados.length]
                estado: est
                mix: { var m = { idle: 0, listening: 0, thinking: 0, tools: 0, speaking: 0 }; m[est] = 1; return m }
                olharAlvo: Qt.point(-300, 260)
                accent: "#f3b2e3"
                vidroLigado: index >= folha.estados.length
                vidroRaio: folha.lado / 2 - 3
                property real syl: Math.abs(Math.sin(folha.t * 4.6)) * (0.62 + 0.38 * Math.sin(folha.t * 1.3))
                nivel: est === "speaking" ? Math.max(0, Math.min(1, 0.12 + 0.85 * syl)) : 0
                nivelS: nivel
                tomS: 0.5 + 0.42 * Math.sin(folha.t * 0.8)
                mic: est === "listening" ? 0.4 + 0.3 * Math.sin(folha.t * 5) : 0
                micS: mic
            }
        }
    }
    function passo(dt) {
        t += dt
        for (var i = 0; i < grade.children.length; i++)
            if (grade.children[i].avancar) grade.children[i].avancar(dt)
    }
}
