import QtQuick
import "../comum"

// Sombra sobre um fundo de texto claro, para ver o degradê.
Rectangle {
    id: f
    width: 444; height: 148
    color: "#2f7f7a"
    Column {
        y: 4; spacing: 2
        Repeater {
            model: 7
            Text { text: "el seguro ICE_TOKEN das para tocolo á dois Então... sifier commands"; color: "#dfe8e4"; font.pixelSize: 15; font.family: "monospace" }
        }
    }
    OrbeConteudo {
        id: o
        skin: "ofanim"; vidro: true
        Component.onCompleted: { o.comando("show listening"); o.faseT = 1 }
    }
    function passo(dt) { o.passo(dt) }
}
