import QtQuick
import "../comum"

// Vitrine do README: cada skin (linha) em cada estado (coluna), com voz e
// microfone simulados para as animações que reagem ao som.
Rectangle {
    id: folha
    property int lado: 148
    property real t: 0
    readonly property var skins: [["ofanim", "Ophanim"], ["ofanim_alado", "Ophanim com asas"],
                                  ["serafim_gravura", "Seraphim (gravura)"], ["anel", "Anel de energia"]]
    readonly property var estados: [["listening", "ouvindo"], ["thinking", "pensando"], ["speaking", "respondendo"]]
    readonly property real syl: Math.abs(Math.sin(t * 4.6)) * (0.62 + 0.38 * Math.sin(t * 1.3))
    width: 130 + lado * 3
    height: 26 + lado * 4
    color: "#141819"

    Repeater {
        model: folha.estados
        Text {
            x: 130 + index * folha.lado; width: folha.lado; y: 6
            horizontalAlignment: Text.AlignHCenter
            text: modelData[1]; color: "#9aa7a8"; font.pixelSize: 12; font.family: "Sans"
        }
    }
    Repeater {
        model: folha.skins
        Text {
            x: 12; y: 26 + index * folha.lado + folha.lado / 2 - 8
            text: modelData[1]; color: "#c9d3d4"; font.pixelSize: 12; font.family: "Sans"
        }
    }
    Grid {
        id: grade
        x: 130; y: 26
        columns: 3
        Repeater {
            model: 12
            Loader {
                id: l
                width: folha.lado; height: folha.lado
                readonly property string skin: folha.skins[Math.floor(index / 3)][0]
                readonly property string est: folha.estados[index % 3][0]
                readonly property var mixEst: { var m = { idle: 0, listening: 0, thinking: 0, tools: 0, speaking: 0 }; m[est] = 1; return m }
                readonly property real voz: est === "speaking" ? Math.max(0, Math.min(1, 0.12 + 0.85 * folha.syl)) : 0
                readonly property real mic: est === "listening" ? 0.4 + 0.3 * Math.sin(folha.t * 5) : 0
                sourceComponent: skin === "anel" ? cAnel : cFig
                function avancar(dt) { if (item) item.avancar(dt) }
            }
        }
    }
    Component {
        id: cFig
        Figura {
            skin: parent.skin; peso: 1.4; mix: parent.mixEst
            voz: parent.voz; mic: parent.mic
        }
    }
    Component {
        id: cAnel
        Anel {
            estado: parent.est; mix: parent.mixEst; accent: "#f3b2e3"
            nivel: parent.voz; nivelS: parent.voz; tomS: 0.5 + 0.42 * Math.sin(folha.t * 0.8)
            mic: parent.mic; micS: parent.mic
        }
    }
    function passo(dt) {
        t += dt
        for (var i = 0; i < grade.children.length; i++)
            if (grade.children[i].avancar) grade.children[i].avancar(dt)
    }
}
