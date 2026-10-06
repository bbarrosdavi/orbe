import QtQuick

// Os outros orbes em volta do principal (o que está no relógio): os com sessão
// ativa orbitam como luas, numa órbita inclinada que passa por trás e pela
// frente da figura; os sem sessão orbitam também, apagados e mais devagar
// (fantasmas); o que pediu a vez de falar e não a pegou para de orbitar e
// espera no canto de baixo à esquerda.
//
// lista: [{ id, skin, cor ("#rrggbb" ou "" = a do tema), tipo: "ativo" | "fantasma" | "espera" }]
// Quem usa chama passo(dt) a cada quadro. Fica dentro da célula do orbe
// (lado x lado), com o centro dela no centro da figura principal.
Item {
    id: sat
    property var lista: []
    property real lado: 148
    property color corTema: "white"
    property color corAnel: "#0087fc"
    property bool glitch: true
    property real alfa: 1                  // o envelope da entrada e da saída do orbe
    property real t: 0
    // a fase de cada satélite, pelo id: a lista muda sem eles pularem de lugar
    property var fases: ({})
    property int quadro: 0

    readonly property real tau: 2 * Math.PI
    // a órbita: elipse inclinada, larga e baixa; o tamanho de cada lua
    readonly property real rx: lado * 0.41
    readonly property real ry: lado * 0.13
    readonly property real inclina: -0.31
    readonly property real tamanho: lado * 0.20
    readonly property var velocidade: ({ ativo: 0.35, fantasma: 0.15 })

    function fase(id, i, n, tipo) {
        var f = fases[id]
        if (f === undefined) {
            // entra no lugar vago do anel: as do mesmo tipo ficam espaçadas
            f = (tipo === "fantasma" ? 0.5 : 0) + i / Math.max(1, n)
            fases[id] = f
        }
        return f
    }

    // posição (dx, dy a partir do centro), profundidade (-1 atrás, 1 na frente)
    function orbita(f, tipo) {
        var a = tau * f
        var x = Math.cos(a) * rx * (tipo === "fantasma" ? 1.08 : 1)
        var y = Math.sin(a) * ry
        var c = Math.cos(inclina), s = Math.sin(inclina)
        return { x: x * c - y * s, y: x * s + y * c, d: Math.sin(a) }
    }

    function passo(dt) {
        t += dt
        var n = { ativo: 0, fantasma: 0 }
        for (var i = 0; i < lista.length; i++) if (n[lista[i].tipo] !== undefined) n[lista[i].tipo]++
        // as figuras das luas andam a cada 2 quadros (as fantasmas, a cada 6) com o
        // tempo somado: pequenas, ninguém vê a diferença, e o JS do quadro cai
        quadro++
        for (var j = 0; j < rep.count; j++) {
            var it = rep.itemAt(j)
            if (it) it.avancar(dt, quadro)
        }
        // as fases andam fora dos delegates: sobrevivem a eles
        var vistos = {}
        for (var k = 0; k < lista.length; k++) {
            var e = lista[k]
            vistos[e.id] = true
            if (e.tipo !== "espera" && fases[e.id] !== undefined)
                fases[e.id] = (fases[e.id] + dt * (velocidade[e.tipo] || 0.3) / tau) % 1
        }
        for (var id in fases) if (!vistos[id]) delete fases[id]
    }

    Repeater {
        id: rep
        model: sat.lista
        Item {
            id: lua
            readonly property var e: modelData
            readonly property int noTipo: {
                var c = 0
                for (var i = 0; i < index; i++) if (sat.lista[i].tipo === e.tipo) c++
                return c
            }
            readonly property int doTipo: {
                var c = 0
                for (var i = 0; i < sat.lista.length; i++) if (sat.lista[i].tipo === e.tipo) c++
                return c
            }
            property var pos: ({ x: 0, y: 0, d: 1 })
            readonly property bool espera: e.tipo === "espera"
            readonly property bool fantasma: e.tipo === "fantasma"
            // a que espera vai para o canto de baixo à esquerda e respira
            readonly property real alvoX: espera ? -sat.lado * 0.36 : pos.x
            readonly property real alvoY: espera ? sat.lado * 0.36 : pos.y
            readonly property real esc: espera ? 1.15 * (1 + 0.05 * Math.sin(sat.t * 3)) : 0.85 + 0.15 * pos.d
            width: sat.tamanho
            height: sat.tamanho
            x: sat.width / 2 + px - width / 2
            y: sat.height / 2 + py - height / 2
            property real px: alvoX
            property real py: alvoY
            Behavior on px { enabled: lua.espera || lua.saiuDaEspera; SmoothedAnimation { velocity: sat.lado * 1.2 } }
            Behavior on py { enabled: lua.espera || lua.saiuDaEspera; SmoothedAnimation { velocity: sat.lado * 1.2 } }
            property bool saiuDaEspera: false
            onEsperaChanged: if (!espera) { saiuDaEspera = true; soltar.restart() }
            Timer { id: soltar; interval: 900; onTriggered: lua.saiuDaEspera = false }
            // atrás da figura na metade de trás da órbita
            z: espera || pos.d > 0 ? 2 : -1
            scale: esc
            opacity: sat.alfa * (fantasma ? 0.30 : espera ? 1 : 0.55 + 0.45 * (pos.d + 1) / 2)

            property real acumulado: 0
            function avancar(dt, quadro) {
                if (!espera) pos = sat.orbita(sat.fase(e.id, noTipo, doTipo, e.tipo), e.tipo)
                acumulado += dt
                var cada = espera ? 1 : fantasma ? 6 : 2
                if (quadro % cada === 0 && fig.item) {
                    fig.item.avancar(acumulado)
                    acumulado = 0
                }
            }

            Loader {
                id: fig
                anchors.fill: parent
                sourceComponent: lua.e.skin === "anel" ? compAnel : compFigura
            }
            Component {
                id: compFigura
                Figura {
                    skin: lua.e.skin
                    glitch: false
                    peso: 1.8
                    cor: lua.e.cor ? lua.e.cor : sat.corTema
                    mix: lua.espera ? ({ idle: 0, listening: 0, thinking: 0, tools: 0, speaking: 1 })
                                    : ({ idle: 1, listening: 0, thinking: 0, tools: 0, speaking: 0 })
                    voz: lua.espera ? 0.35 + 0.3 * Math.abs(Math.sin(sat.t * 4.6)) : 0
                }
            }
            Component {
                id: compAnel
                Anel {
                    anchors.centerIn: parent
                    esc: sat.tamanho / 120
                    glitch: false
                    accent: lua.e.cor ? lua.e.cor : sat.corAnel
                    estado: lua.espera ? "speaking" : "listening"
                    mix: lua.espera ? ({ listening: 0, thinking: 0, tools: 0, speaking: 1 }) : ({ listening: 1, thinking: 0, tools: 0, speaking: 0 })
                    nivelS: lua.espera ? 0.4 : 0
                }
            }
        }
    }
}
