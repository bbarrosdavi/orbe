import QtQuick
import "../comum"

// Os orbes em paralelo: o principal (o do relógio) com as sessões ativas
// orbitando, os orbes sem sessão como fantasmas mais lentos e, no segundo
// quadro, um que pediu a vez e espera no canto de baixo à esquerda.
Rectangle {
    id: folha
    width: 2 * (296 + 247) + 20
    height: 280
    color: "#1d2324"
    property real t: 0
    readonly property var ativos: [
        { id: "ofanim_alado/0", skin: "ofanim_alado", cor: "", tipo: "ativo" },
        { id: "ofanim/1", skin: "ofanim", cor: "#4DD0E1", tipo: "ativo" },
        { id: "anel/0", skin: "anel", cor: "", tipo: "ativo" }]
    readonly property var fantasmas: [
        { id: "anel", skin: "anel", cor: "", tipo: "fantasma" },
        { id: "serafim_gravura", skin: "serafim_gravura", cor: "", tipo: "fantasma" }]
    Row {
        spacing: 20
        Repeater {
            id: rep
            model: 2
            OrbeConteudo {
                skin: "serafim_gravura"
                Component.onCompleted: {
                    comando("show " + (index === 0 ? "listening" : "speaking"))
                    var l = folha.ativos.concat(folha.fantasmas)
                    if (index === 1) l[1] = { id: "ofanim/1", skin: "ofanim", cor: "#4DD0E1", tipo: "espera" }
                    comando("satelites " + JSON.stringify(l))
                }
            }
        }
    }
    function passo(dt) {
        t += dt
        for (var i = 0; i < rep.count; i++) {
            var o = rep.itemAt(i)
            if (i === 1) o.comando("level " + (0.12 + 0.85 * Math.abs(Math.sin(t * 4.6))).toFixed(3))
            o.passo(dt)
        }
    }
}
