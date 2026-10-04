import QtQuick
import "../comum"

// Texto abaixo de cada skin, com 5 linhas cheias: a de cima encosta na figura.
Rectangle {
    id: folha
    width: 4 * 148
    height: 240
    color: "#1d2324"
    Row {
        Repeater {
            id: rep
            model: ["ofanim", "ofanim_alado", "serafim_gravura", "anel"]
            Item {
                width: 148; height: 240
                clip: true
                OrbeConteudo {
                    id: o
                    x: -o.painel
                    skin: modelData
                    textoPos: "abaixo"
                    Component.onCompleted: {
                        comando("show thinking")
                        comando("line Pedido: resumir as mensagens não lidas de hoje.")
                        comando("line Começo pelas conversas com menções diretas.")
                        comando("line São três threads; a mais longa trata do prazo.")
                    }
                }
                function passo(dt) { o.passo(dt) }
            }
        }
    }
    function passo(dt) {
        for (var i = 0; i < rep.count; i++) rep.itemAt(i).passo(dt)
    }
}
