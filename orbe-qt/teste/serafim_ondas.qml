import QtQuick
import "../comum"

// Seraphim respondendo com voz em sílabas: as ondas devem sair como no Ophanim.
Rectangle {
    id: folha
    property real t: 0
    width: 900; height: 450
    color: "#1d2324"
    Row {
        Repeater {
            id: rep
            model: ["serafim", "ofanim"]
            Figura {
                width: 450; height: 450
                skin: modelData
                glitch: false
                mix: ({ idle: 0, listening: 0, thinking: 0, tools: 0, speaking: 1 })
                peso: 1.4
                cor: "#b8cacb"
                property real syl: Math.abs(Math.sin(folha.t * 4.6)) * (0.62 + 0.38 * Math.sin(folha.t * 1.3))
                voz: Math.max(0, Math.min(1, 0.1 + 0.85 * syl))
                olharAlvo: Qt.point(-300, 500)
            }
        }
    }
    property string info: ""
    function passo(dt) {
        t += dt
        for (var i = 0; i < rep.count; i++) rep.itemAt(i).avancar(dt)
        info = "ondas serafim=" + rep.itemAt(0).st.ondas.length + " ofanim=" + rep.itemAt(1).st.ondas.length
    }
}
