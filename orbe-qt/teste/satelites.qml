import QtQuick
import "../comum"

// Os orbes em paralelo: o principal (o do relógio) com as sessões ativas
// orbitando como elétrons e os sem sessão como fantasmas mais lentos. Aos 4 s
// o relógio passa ao Ophanim ciano: ele cresce até o centro e o principal
// entra na órbita. Aos 9 s o alado pede a vez e espera no canto.
Rectangle {
    id: folha
    width: 296 + 247 + 40
    height: 287
    color: "#1d2324"
    property real t: 0
    property int etapa: 0
    readonly property var antes: [
        { id: "ofanim_alado/0", skin: "ofanim_alado", cor: "", tipo: "ativo" },
        { id: "ofanim/1", skin: "ofanim", cor: "#4DD0E1", tipo: "ativo" },
        { id: "anel/0", skin: "anel", cor: "", tipo: "ativo" },
        { id: "ofanim", skin: "ofanim", cor: "", tipo: "fantasma" }]
    readonly property var depois: [
        { id: "ofanim_alado/0", skin: "ofanim_alado", cor: "", tipo: "ativo" },
        { id: "serafim_gravura/0", skin: "serafim_gravura", cor: "", tipo: "ativo" },
        { id: "anel/0", skin: "anel", cor: "", tipo: "ativo" },
        { id: "ofanim", skin: "ofanim", cor: "", tipo: "fantasma" }]
    OrbeConteudo {
        id: o
        x: 20; y: 20
        skin: "serafim_gravura"
        Component.onCompleted: {
            comando("show listening")
            comando("satelites " + JSON.stringify(folha.antes))
        }
    }
    function passo(dt) {
        t += dt
        if (etapa === 0 && t > 4) {
            etapa = 1
            o.comando("espelho ofanim #4DD0E1")
            o.comando("satelites " + JSON.stringify(depois))
        } else if (etapa === 1 && t > 9) {
            etapa = 2
            var l = depois.slice(); l[0] = { id: "ofanim_alado/0", skin: "ofanim_alado", cor: "", tipo: "espera" }
            o.comando("satelites " + JSON.stringify(l))
        }
        o.passo(dt)
    }
}
