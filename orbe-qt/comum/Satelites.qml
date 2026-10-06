import QtQuick

// Os outros orbes em volta do principal (o que está no relógio), em 3D com
// perspectiva: passam por trás e pela frente da figura, menores quanto mais
// longe. Dois jeitos de andar (movimento, config orbe.luas):
//  - vagalumes (padrão): soltos, cada um com uma vontade que vagueia e uma
//    pressa que vai de pairar a arrancar, numa casca em volta do orbe;
//  - orbitas: elétrons, cada um numa elipse de perfil num plano seu (tirado do
//    id), com raio, velocidade e sentido próprios e o plano girando devagar.
// Os sem sessão andam também, apagados e mais devagar (fantasmas). O que pediu
// a vez de falar e não a pegou para e espera no canto de baixo à esquerda.
//
// lista: [{ id, skin, cor ("#rrggbb" ou "" = a do tema), tipo: "ativo" | "fantasma" | "espera" }]
// Quem usa chama passo(dt) a cada quadro. Fica dentro da célula do orbe
// (lado x lado), com o centro dela no centro da figura principal.
//
// Troca do principal (trocar): o que era o principal entra na órbita saindo
// do centro e encolhendo; o chamado sai da órbita dele crescendo até o centro
// (quem usa anima a arte principal a partir de onde() dele).
Item {
    id: sat
    property var lista: []
    property real lado: 148
    property color corTema: "white"
    property color corAnel: "#0087fc"
    property bool glitch: true
    property real alfa: 1                  // o envelope da entrada e da saída do orbe
    property real t: 0
    property int quadro: 0
    // quem entrou agora na órbita vindo do centro: id → { t0, s0 }
    property var entradas: ({})
    // o principal que acabou de sair, até a lista nova chegar com ele
    property var saindo: null
    readonly property var vista: {
        var l = lista.slice()
        if (saindo && !l.some(function (e) { return mesmo(e, saindo) })) l.push(saindo)
        return l
    }

    readonly property real tau: 2 * Math.PI
    readonly property real tamanho: lado * 0.36
    readonly property real duracao: 0.75   // a troca, em segundos

    function mesmo(a, b) {
        return a.skin === b.skin && (a.cor || "").toLowerCase() === (b.cor || "").toLowerCase()
    }

    // um número de 0 a 1 tirado do id e de uma semente: a órbita de cada um é sempre a mesma
    function sorte(id, k) {
        var h = 2166136261
        var s = String(id) + "#" + k
        for (var i = 0; i < s.length; i++) { h ^= s.charCodeAt(i); h = (h * 16777619) >>> 0 }
        return (h % 100000) / 100000
    }

    // a posição na órbita já projetada (dx, dy a partir do centro), a profundidade
    // (-1 atrás, 1 na frente) e a escala da perspectiva
    function orbita(e) {
        var id = e.id, fant = e.tipo === "fantasma"
        var r = lado * (0.25 + 0.08 * sorte(id, 1))
        // o plano quase de perfil (57° a 80° da tela), como os elétrons no desenho
        // do átomo: a elipse vista é fina e cruza o orbe, uma vez pela frente e
        // outra por trás. De frente para a tela, a lua só rodeava a borda.
        var inc = (1.0 + 0.4 * sorte(id, 2)) * (sorte(id, 10) < 0.5 ? -1 : 1)
        var no = sorte(id, 3) * tau + t * (0.06 + 0.1 * sorte(id, 4))   // o plano gira devagar
        var w = (0.55 + 0.6 * sorte(id, 5)) * (sorte(id, 6) < 0.5 ? -1 : 1) * (fant ? 0.45 : 1)
        var a = sorte(id, 7) * tau + w * t
        // um pouco de errância no raio: elétron, não planeta
        r *= 1 + 0.08 * Math.sin(t * (0.7 + sorte(id, 8)) + sorte(id, 9) * tau)
        var x = Math.cos(a) * r, y = Math.sin(a) * r
        var y2 = y * Math.cos(inc), z = y * Math.sin(inc)
        var c = Math.cos(no), s = Math.sin(no)
        // perspectiva: a câmera a uns 3 raios do centro; a lua da frente cresce e
        // se afasta do centro na tela, a de trás encolhe e se aproxima
        var p = camera / (camera - z)
        return { x: (x * c - y2 * s) * p, y: (x * s + y2 * c) * p, d: z / r, p: p }
    }
    // a câmera a 1,3 célula do centro: na casca, a perspectiva vai de 0,79 a 1,37
    readonly property real camera: lado * 1.3

    // vagalumes | orbitas (config orbe.luas): vagalumes andam soltos, vivos;
    // órbitas são as elipses fixas de perfil acima
    property string movimento: "vagalumes"
    // o estado de cada vagalume, pelo id (sobrevive à troca da lista):
    // posição e velocidade em 3D, em px a partir do centro
    property var enxame: ({})

    // uma vontade que muda devagar e nunca se repete: três senos de frequências
    // sem razão simples entre si, de -1 a 1
    function onda(id, k, f) {
        return 0.55 * Math.sin(t * f * 0.9 + sorte(id, k) * tau)
             + 0.30 * Math.sin(t * f * 2.31 + sorte(id, k + 1) * tau)
             + 0.15 * Math.sin(t * f * 5.17 + sorte(id, k + 2) * tau)
    }

    // um passo de vagalume: segue uma direção que vagueia, com pressa que vai de
    // quase parado a uma arrancada, numa casca em volta do orbe (nem grudado no
    // centro, nem longe), afastando-se dos outros. Devolve o mesmo que orbita().
    function vagalume(e, dt) {
        var id = e.id, fant = e.tipo === "fantasma"
        var rMin = lado * 0.17, rMax = lado * 0.35
        var s = enxame[id]
        if (!s) {
            // nasce num ponto da casca tirado do id
            var th = sorte(id, 11) * tau, ph = Math.acos(2 * sorte(id, 12) - 1), r0 = lado * 0.27
            s = { x: r0 * Math.sin(ph) * Math.cos(th), y: r0 * Math.sin(ph) * Math.sin(th),
                  z: r0 * Math.cos(ph), vx: 0, vy: 0, vz: 0 }
            enxame[id] = s
        }
        dt = Math.min(dt, 0.05)
        // a pressa: a maior parte do tempo devagar, às vezes uma arrancada; os
        // fantasmas, mais lentos
        var q = 0.5 + 0.5 * onda(id, 20, 0.6)
        var pressa = lado * (0.12 + 1.0 * q * q) * (fant ? 0.45 : 1)
        var dx = onda(id, 30, 1.2), dy = onda(id, 40, 1.11), dz = onda(id, 50, 1.29)
        var n = Math.sqrt(dx * dx + dy * dy + dz * dz) || 1
        dx /= n; dy /= n; dz /= n
        // a casca: na borda dela, a vontade perde a parte que sairia (por fora ou
        // por dentro) e o vagalume desliza em volta do orbe; quem passa ainda é
        // puxado de volta
        var r = Math.sqrt(s.x * s.x + s.y * s.y + s.z * s.z) || 1
        var ux = s.x / r, uy = s.y / r, uz = s.z / r
        var radial = dx * ux + dy * uy + dz * uz
        if ((r > rMax * 0.85 && radial > 0) || (r < rMin * 1.2 && radial < 0)) {
            dx -= radial * ux; dy -= radial * uy; dz -= radial * uz
        }
        var ax = (dx * pressa - s.vx) * 3.5, ay = (dy * pressa - s.vy) * 3.5, az = (dz * pressa - s.vz) * 3.5
        var f = r > rMax ? -(r - rMax) * 25 : r < rMin ? (rMin - r) * 25 : 0
        ax += f * ux; ay += f * uy; az += f * uz
        // os outros: cada um no seu espaço
        var perto = tamanho * 0.7
        for (var j = 0; j < vista.length; j++) {
            var o = enxame[vista[j].id]
            if (!o || o === s) continue
            var ex = s.x - o.x, ey = s.y - o.y, ez = s.z - o.z
            var dd = Math.sqrt(ex * ex + ey * ey + ez * ez) || 1
            if (dd < perto) {
                var k = (perto - dd) * 6 / dd
                ax += ex * k; ay += ey * k; az += ez * k
            }
        }
        s.vx += ax * dt; s.vy += ay * dt; s.vz += az * dt
        s.x += s.vx * dt; s.y += s.vy * dt; s.z += s.vz * dt
        var p = Math.max(0.7, Math.min(1.4, camera / (camera - s.z)))
        return { x: s.x * p, y: s.y * p, d: Math.max(-1, Math.min(1, s.z / rMax)), p: p }
    }

    // onde está agora (para a arte principal sair dali crescendo), ou null
    function onde(skin, cor) {
        for (var i = 0; i < rep.count; i++) {
            var it = rep.itemAt(i)
            if (it && mesmo(it.e, { skin: skin, cor: cor }) && it.e.id !== "_saindo")
                return { x: it.px, y: it.py, s: it.width * it.scale / lado }
        }
        return null
    }

    // o principal [de] vira satélite: entra na órbita saindo do centro
    function trocar(de) {
        saindo = { id: "_saindo", skin: de.skin, cor: de.cor || "", tipo: "ativo" }
        delete enxame["_saindo"]
        var en = entradas
        en["_saindo"] = { t0: t, s0: lado / tamanho * 0.85 }
        entradas = en
    }

    onListaChanged: {
        // quem saiu da lista leva o vagalume junto
        var vivos = {}
        for (var v = 0; v < lista.length; v++) vivos[lista[v].id] = true
        for (var idv in enxame) if (!vivos[idv] && idv !== "_saindo") delete enxame[idv]
        // a lista nova trouxe o que saiu: ele continua a entrada com o id de verdade
        if (saindo) {
            for (var i = 0; i < lista.length; i++) {
                if (mesmo(lista[i], saindo)) {
                    var en = entradas
                    if (en["_saindo"]) en[lista[i].id] = en["_saindo"]
                    delete en["_saindo"]
                    entradas = en
                    // o vagalume dele segue de onde estava, com o id de verdade
                    if (enxame["_saindo"]) enxame[lista[i].id] = enxame["_saindo"]
                    delete enxame["_saindo"]
                    saindo = null
                    break
                }
            }
        }
    }

    function passo(dt) {
        t += dt
        quadro++
        // as figuras das luas andam a cada 2 quadros (as fantasmas, a cada 6) com o
        // tempo somado: pequenas, ninguém vê a diferença, e o JS do quadro cai
        for (var j = 0; j < rep.count; j++) {
            var it = rep.itemAt(j)
            if (it) it.avancar(dt, quadro)
        }
        for (var id in entradas) if (t - entradas[id].t0 > duracao) delete entradas[id]
    }

    function suave(p) { p = Math.max(0, Math.min(1, p)); return p * p * (3 - 2 * p) }

    Repeater {
        id: rep
        model: sat.vista
        Item {
            id: lua
            readonly property var e: modelData
            property var pos: ({ x: 0, y: 0, d: 1, p: 1 })
            readonly property bool espera: e.tipo === "espera"
            readonly property bool fantasma: e.tipo === "fantasma"
            // entrando na órbita vindo do centro: 0 no centro, 1 na órbita
            property real entrando: 1
            property real s0: 1
            // a que espera vai para o canto de baixo à esquerda e respira
            readonly property real alvoX: espera ? -sat.lado * 0.36 : pos.x
            readonly property real alvoY: espera ? sat.lado * 0.36 : pos.y
            readonly property real px: alvoX * entrando
            readonly property real py: alvoY * entrando
            // o tamanho segue a perspectiva: de 0,35 lá atrás a 0,6 no ponto mais
            // perto. Na frente, a lua não passa do olho do Ophanim (o olho tem uns
            // 22% da célula; a lua de 0,6 fica em 13% a 19%, conforme a skin)
            readonly property real escNormal: espera ? 1.1 * (1 + 0.05 * Math.sin(sat.t * 3)) : 0.44 * pos.p
            width: sat.tamanho
            height: sat.tamanho
            x: sat.width / 2 + rx - width / 2
            y: sat.height / 2 + ry - height / 2
            property real rx: px
            property real ry: py
            Behavior on rx { enabled: lua.espera || lua.saiuDaEspera; SmoothedAnimation { velocity: sat.lado * 1.2 } }
            Behavior on ry { enabled: lua.espera || lua.saiuDaEspera; SmoothedAnimation { velocity: sat.lado * 1.2 } }
            property bool saiuDaEspera: false
            onEsperaChanged: if (!espera) { saiuDaEspera = true; soltar.restart() }
            Timer { id: soltar; interval: 900; onTriggered: lua.saiuDaEspera = false }
            // atrás da figura na metade de trás da órbita; entrando, na frente
            z: espera || entrando < 0.6 || pos.d > 0 ? 2 : -1
            scale: s0 + (escNormal - s0) * entrando
            opacity: sat.alfa * (fantasma ? 0.32 : espera ? 1 : 0.6 + 0.4 * (pos.d + 1) / 2)

            property real acumulado: 0
            function avancar(dt, quadro) {
                if (!espera) pos = sat.movimento === "orbitas" ? sat.orbita(e) : sat.vagalume(e, dt)
                var en = sat.entradas[e.id]
                if (en) {
                    entrando = sat.suave((sat.t - en.t0) / sat.duracao)
                    s0 = en.s0
                } else {
                    entrando = 1
                }
                acumulado += dt
                var cada = espera || entrando < 1 ? 1 : fantasma ? 6 : 2
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
                    peso: 1.6
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
