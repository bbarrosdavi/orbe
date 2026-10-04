import QtQuick
import "../comum"
Rectangle {
    id: f
    width: 148; height: 148
    color: "#1d2324"
    property real t: 0
    Anel {
        id: a
        anchors.fill: parent
        estado: "speaking"
        mix: ({ listening: 0, thinking: 0, tools: 0, speaking: 1 })
        accent: "#f3b2e3"
        property real syl: Math.abs(Math.sin(f.t * 4.6)) * (0.62 + 0.38 * Math.sin(f.t * 1.3))
        nivel: Math.max(0, Math.min(1, 0.12 + 0.85 * syl))
        nivelS: nivel
        tomS: 0.5 + 0.42 * Math.sin(f.t * 0.8)
    }
    function passo(dt) { t += dt; a.avancar(dt) }
}
