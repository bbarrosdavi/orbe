import QtQuick
import "../comum"
// Mesma sequência do anel_gtk3.py (tique de 0.033, nível e tom sintéticos,
// suavização do step do GTK), para comparar quadro a quadro com o original.
Rectangle {
    id: f
    width: 148; height: 148
    color: "#1d2324"
    property int i: 0
    property string info
    property real levelS: 0
    property real toneS: 0.5
    Anel {
        id: a
        anchors.fill: parent
        estado: "speaking"
        mix: ({ listening: 0, thinking: 0, tools: 0, speaking: 1 })
        accent: "#f3b2e3"
    }
    function passo(dt) {
        var t = i * 0.033
        var syl = Math.abs(Math.sin(t * 4.6)) * (0.62 + 0.38 * Math.sin(t * 1.3))
        var lv = Math.max(0, Math.min(1, 0.12 + 0.85 * syl))
        var tn = 0.5 + 0.42 * Math.sin(t * 0.8)
        levelS += (lv - levelS) * (lv > levelS ? 0.55 : 0.16)
        toneS += (tn - toneS) * 0.25
        a.nivel = lv; a.nivelS = levelS; a.tomS = toneS
        a.avancar(dt)
        i++
        if (i === 99) info = "frame " + a.st.framePos + " rot " + a.st.rot + " roff " + a.st.rOff
    }
}
