import QtQuick
import "../comum"

// Glitch dos anjos ao lado do anel, todos pensando: cinco cópias de cada,
// para pegar rajadas em quadros diferentes.
Rectangle {
    id: folha
    property int lado: 148
    readonly property var skins: ["ofanim", "ofanim_alado", "serafim"]
    readonly property var pensar: ({ idle: 0, listening: 0, thinking: 1, speaking: 0, tools: 0 })
    width: lado * 5
    height: lado * 4
    color: "#1d2324"
    Grid {
        id: grade
        columns: 5
        Repeater {
            model: 15
            Figura {
                width: folha.lado; height: folha.lado
                skin: folha.skins[Math.floor(index / 5)]
                peso: 1.4
                mix: folha.pensar
            }
        }
        Repeater {
            model: 5
            Anel {
                width: folha.lado; height: folha.lado
                estado: "thinking"
                mix: folha.pensar
                accent: "#f3b2e3"
            }
        }
    }
    // fração dos quadros em rajada, por skin (anjos: _glt.y; anel: _glt.w)
    property var emRajada: ({ ofanim: 0, ofanim_alado: 0, serafim: 0, anel: 0 })
    property int quadros: 0
    readonly property string info: {
        var r = [], n = Math.max(1, quadros * 5)
        for (var k in emRajada) r.push(k + " " + (100 * emRajada[k] / n).toFixed(0) + "%")
        return "quadros em rajada: " + r.join("  ")
    }
    function passo(dt) {
        var c = emRajada
        for (var i = 0; i < grade.children.length; i++) {
            var it = grade.children[i]
            if (!it.avancar) continue
            it.avancar(dt)
            if (it.skin !== undefined) { if (it._glt.y > 0.5) c[it.skin]++ }
            else if (it._glt.w > 0) c.anel++
        }
        quadros++
        emRajada = c
    }
}
