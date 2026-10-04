import QtQuick
import "../comum"

// Texto do raciocínio ao lado e abaixo, com o orbe pensando.
Rectangle {
    id: folha
    width: 444
    height: 148 + 241 + 30
    color: "#1d2324"
    Column {
        spacing: 30
        Repeater {
            id: rep
            model: [["serafim_gravura", "lado"], ["anel", "abaixo"]]
            OrbeConteudo {
                skin: modelData[0]
                textoPos: modelData[1]
                Component.onCompleted: {
                    comando("show thinking")
                    comando("line Pedido: resumir as mensagens não lidas de hoje.")
                    comando("line Começo pelas conversas com menções diretas.")
                    comando("line São três threads; a mais longa trata do prazo da entrega.")
                }
                Rectangle { anchors.fill: parent; color: "transparent"; border.color: "#40ffffff" }
            }
        }
    }
    function passo(dt) {
        for (var i = 0; i < rep.count; i++) rep.itemAt(i).passo(dt)
    }
}
