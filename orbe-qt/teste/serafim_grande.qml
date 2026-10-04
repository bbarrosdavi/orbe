import QtQuick
import "../comum"

// Um Seraphim grande, para ver penas e olhos das asas de perto.
Rectangle {
    id: folha
    property int olhos: 2
    property bool encorpadas: true
    property string estado: "idle"
    width: 600; height: 600
    color: "#1d2324"
    Figura {
        id: f
        anchors.fill: parent
        skin: "serafim"
        glitch: false
        olhosSerafim: folha.olhos
        penasEncorpadas: folha.encorpadas
        mix: { var m = { idle: 0, listening: 0, thinking: 0, tools: 0, speaking: 0 }; m[folha.estado] = 1; return m }
        peso: 1.4
        cor: "#b8cacb"
        olharAlvo: Qt.point(-300, 500)
    }
    function passo(dt) { f.avancar(dt) }
}
