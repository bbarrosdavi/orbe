import QtQuick
import "../comum"
// Orbes completos lado a lado: skin, estado, vidro, texto, ponto travado e
// tamanho. Cada um recebe o protocolo do daemon como o shell repassaria.
Rectangle {
    id: f
    width: 1000
    height: 800
    color: "#1d2324"
    property real t: 0
    property var casos: [
        { skin: "ofanim", cmds: ["show thinking", "line lendo o contexto do pedido", "line chamando a ferramenta de busca nos arquivos do projeto com um texto bem longo para quebrar"], vidro: false, tam: 1.0 },
        { skin: "serafim_gravura", cmds: ["show speaking", "hold 1"], vidro: true, tam: 1.0 },
        { skin: "ofanim_alado", cmds: ["show listening"], vidro: true, tam: 1.3 },
        { skin: "anel", cmds: ["show speaking", "hold 1"], vidro: true, tam: 0.8 },
        { skin: "anel", cmds: ["show tools", "line filtrando a saída"], vidro: false, tam: 1.0 }
    ]
    Column {
        spacing: 0
        Repeater {
            id: rep
            model: f.casos.length
            Rectangle {
                width: 1000; height: o.height + 4
                color: index % 2 ? "#1d2324" : "#3a4a4c"
                OrbeConteudo {
                    id: o
                    x: 1000 - width
                    skin: f.casos[index].skin
                    vidro: f.casos[index].vidro
                    tamanho: f.casos[index].tam
                    Component.onCompleted: f.casos[index].cmds.forEach(function (c) { o.comando(c) })
                }
                property alias orbe: o
            }
        }
    }
    function passo(dt) {
        t += dt
        var syl = Math.abs(Math.sin(t * 4.6)) * (0.62 + 0.38 * Math.sin(t * 1.3))
        for (var i = 0; i < rep.count; i++) {
            var o = rep.itemAt(i).orbe
            if (o.estado === "speaking") o.comando("level " + (0.12 + 0.85 * syl).toFixed(3) + " " + (0.5 + 0.42 * Math.sin(t * 0.8)).toFixed(3))
            if (o.estado === "listening") o.comando("mic " + (0.4 + 0.3 * Math.sin(t * 5)).toFixed(3))
            o.passo(dt)
        }
    }
}
