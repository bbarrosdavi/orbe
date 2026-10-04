import QtQuick

// Ophanim, Ophanim com asas e Seraphim desenhados na GPU.
//
// O desenho mora em dois shaders: figura.frag pinta a máscara branca da
// figura (cada traço é uma função de distância) e pos.frag dá a cor, o glitch
// e o vidro. Aqui fica só o que tem memória entre quadros, portado de
// hermes_voice_avatares.py: giro das rodas, travas em quarto de volta, ondas
// da voz, relâmpagos, batida das asas, fogo e brasa do serafim, rajadas de
// glitch. Quem usa chama avancar(dt) a cada quadro (FrameAnimation).
//
// Reações por estado (pesos de mix, os mesmos do anel de energia):
// ouvindo, as rodas quase param e todos os olhos se voltam para quem fala;
// pensando, turbilhão, fogo entre as rodas e pulso triplo no serafim;
// ferramentas, rodas travadas nos eixos em quartos de volta, com relâmpagos;
// falando, ondas a cada sílaba; ao despertar, as rodas desdobram de um ponto.
Item {
    id: raiz

    property string skin: "ofanim"         // ofanim | ofanim_alado | serafim
    property bool glitch: true
    property real peso: 1.0                // traço mais grosso e opaco (o orbe usa mais)
    property color cor: "white"
    property real raioFixo: -1             // R explícito; -1 = o maior que cabe
    property real disco: -1                // > 0: cabe também num disco desse raio
    property real zoom: 1.0
    property real alfa: 1.0
    property var olharAlvo: null           // Qt.point no item, ou null (olhos vagam)
    // Seraphim: 0 só o olho de cima, 1 só o do meio, 2 os dois, 3 só o do
    // meio na vertical, 4 os dois com o do meio na vertical
    property int olhosSerafim: 3
    property bool penasEncorpadas: true
    property var mix: ({ idle: 1.0 })      // pesos por estado
    property real voz: 0
    property real mic: 0
    property real desperto: 1

    // vidro fosco pintado atrás da figura, no passe de pós
    property bool vidroLigado: false
    property real vidroRaio: 0
    property real vidroAlfa: 0.58
    property real vidroInicio: 0.30
    property color vidroCor: "#121414"

    readonly property real rRef: 82.0      // raio em que o glitch foi afinado
    readonly property var alcances: ({
        ofanim: [1.55, 1.55, 1.25],
        ofanim_alado: [2.1, 1.55, 2.08],
        serafim: [2.0, 1.6, 1.95]
    })

    function raioQueCabe(w, h, d) {
        var al = alcances[skin] || alcances.ofanim
        var r = Math.min(w / 2 / al[0], h / 2 / al[1])
        return d > 0 ? Math.min(r, d / al[2]) : r
    }

    // ── utilidades ──
    readonly property real tau: 2 * Math.PI
    function ruido(t, s) {
        return Math.sin(t * 1.31 + s) * 0.5 + Math.sin(t * 2.17 + s * 1.7) * 0.3 + Math.sin(t * 0.53 + s * 2.9) * 0.2
    }
    function lim01(v) { return v < 0 ? 0 : (v > 1 ? 1 : v) }
    function suave(p) { p = lim01(p); return p * p * (3 - 2 * p) }
    function uni(a, b) { return a + Math.random() * (b - a) }
    function sorteia(n) { return Math.floor(Math.random() * n) }
    function p(e) { return mix[e] || 0 }
    function mistura(v) {
        var tot = 0, acc = 0
        for (var e in mix) {
            var w = mix[e]
            if (v[e] !== undefined && w > 0) { acc += w * v[e]; tot += w }
        }
        if (tot <= 0) return v.idle !== undefined ? v.idle : (v.listening || 0)
        return acc / tot
    }
    function agitacao() { return lim01(p("thinking") + 0.6 * p("tools")) }

    // ── estado ──
    property var st: novoEstado()
    onSkinChanged: st = novoEstado()

    function novoEstado() {
        return {
            t: 0, fase: 0, vozAnt: 0,
            glitchAte: 0, proxGlitch: 1.2, sem: 0,
            salto: [0, 0, 0, 0],
            semente: [uni(0, 100), uni(0, 100), uni(0, 100), uni(0, 100)],
            foco: 0.3, trava: 0, quarto: 0, quartoAlvo: 0, proxQuarto: 0,
            ondas: [], ultimaOnda: -1, relampagos: [],
            giroRaios: 0, pupila: 1, clarao: 0,
            faseAsa: 0, fogo: 1, tri: 0, abre: 0, brasaAng: 0, brasa: 0
        }
    }

    function avancar(dt) {
        var s = st
        s.t += dt
        if (skin === "serafim") evoluirSerafim(dt)
        else {
            evoluirOfanim(dt)
            if (skin === "ofanim_alado") {
                var falar = p("speaking") * voz
                s.faseAsa += dt * tau * (mistura({ idle: 0.3, listening: 0.3, thinking: 2.6, tools: 6.0, speaking: 1.6 }) + 1.2 * falar)
            }
        }
        montar()
        s.vozAnt = voz
    }

    function evoluirOfanim(dt) {
        var s = st, t = s.t
        var ouvir = p("listening"), pensar = p("thinking"), ferr = p("tools")
        var falar = p("speaking") * voz
        var giro = mistura({ idle: 1.0, listening: 0.45, thinking: 3.4, tools: 1.4, speaking: 1.1 }) + 1.8 * falar
        giro += (1 - desperto) * 5.0          // desdobrando: as rodas giram soltas
        s.fase += dt * giro
        s.giroRaios += dt * (0.07 + 0.5 * pensar + 0.25 * falar)
        var foco = mistura({ idle: 0.3, listening: 1.0, thinking: 0.0, tools: 0.55, speaking: 0.85 })
        s.foco += (foco - s.foco) * Math.min(1, dt * 5)
        s.trava += (ferr - s.trava) * Math.min(1, dt * 4)
        if (ferr > 0.4 && t >= s.proxQuarto) {
            s.quartoAlvo += [1, 1, -1][sorteia(3)] * Math.PI / 2
            s.proxQuarto = t + uni(0.45, 0.9)
        }
        s.quarto += (s.quartoAlvo - s.quarto) * Math.min(1, dt * 9)

        var subida = voz - s.vozAnt
        if (p("speaking") > 0.3 && t - s.ultimaOnda > 0.12
                && (subida > 0.05 || (voz > 0.3 && t - s.ultimaOnda > 0.3))) {
            s.ondas.push([t, Math.min(1, 0.35 + voz)])
            s.ultimaOnda = t
        }
        s.ondas = s.ondas.filter(function (o) { return t - o[0] < 1.3 })

        if (Math.random() < dt * (2.4 * ferr + 0.5 * pensar))
            s.relampagos.push([t, sorteia(4), uni(0, tau), sorteia(4), uni(0, tau), Math.random() * 100])
        s.relampagos = s.relampagos.filter(function (r) { return t - r[0] < 0.12 })
        s.clarao = s.relampagos.length ? 1.0 : s.clarao * Math.max(0, 1 - dt * 8)

        var alvoP = 1.0 + 0.25 * ouvir + 0.6 * ouvir * mic - 0.25 * pensar
        s.pupila += (alvoP - s.pupila) * Math.min(1, dt * 8)
    }

    function evoluirSerafim(dt) {
        var s = st, t = s.t
        var ouvir = p("listening"), pensar = p("thinking"), ferr = p("tools")
        var falar = p("speaking") * voz
        s.faseAsa += dt * tau * (mistura({ idle: 0.5, listening: 0.3, thinking: 2.2, tools: 1.4, speaking: 1.2 }) + 0.8 * falar)
        // "Santo, santo, santo": três pulsos de luz a cada ciclo, pensando
        var ciclo = t % 2.6
        var g = 0
        for (var c of [0.2, 0.55, 0.9]) g = Math.max(g, Math.exp(-Math.pow((ciclo - c) / 0.07, 2)))
        s.tri = pensar * g
        var alvo = mistura({ idle: 1.0, listening: 0.85, thinking: 1.4, tools: 1.15, speaking: 1.0 }) + 0.6 * falar + 0.5 * s.tri
        s.fogo += (alvo - s.fogo) * Math.min(1, dt * (alvo > s.fogo ? 10 : 3))
        s.abre += (ouvir - s.abre) * Math.min(1, dt * 4)
        s.brasaAng += dt * 2.4
        s.brasa += (ferr - s.brasa) * Math.min(1, dt * 4)
    }

    // base (u, v) do plano do anel i, girando em eixos diferentes
    readonly property var eixos: [[1, 0, 0], [0, 1, 0], [0, 0, 1], [0.577, 0.577, 0.577]]
    function base(i) {
        var s = st, t = s.t, sm = s.semente[i]
        var a = s.fase * (0.35 + 0.17 * i) * (i % 2 ? 1 : -1) + ruido(t * 0.4, sm) * 0.6 + s.salto[i]
        var b = 0.9 + i * 0.55 + ruido(t * 0.25, sm + 7) * 0.5
        var n = [Math.cos(a) * Math.sin(b), Math.sin(a) * Math.sin(b), Math.cos(b)]
        if (s.trava > 0.01) {
            // travadas nos eixos, girando em quartos de volta (Ez 1:17)
            var ex = eixos[i]
            var c = Math.cos(s.quarto), sn = Math.sin(s.quarto)
            ex = [ex[0] * c - ex[1] * sn, ex[0] * sn + ex[1] * c, ex[2]]
            c = Math.cos(0.55); sn = Math.sin(0.55)          // inclinação para ler em 3D
            ex = [ex[0], ex[1] * c - ex[2] * sn, ex[1] * sn + ex[2] * c]
            c = Math.cos(0.45); sn = Math.sin(0.45)
            ex = [ex[0] * c + ex[2] * sn, ex[1], -ex[0] * sn + ex[2] * c]
            var w = s.trava
            n = [(1 - w) * n[0] + w * ex[0], (1 - w) * n[1] + w * ex[1], (1 - w) * n[2] + w * ex[2]]
            var nl = Math.hypot(n[0], n[1], n[2]) || 1
            n = [n[0] / nl, n[1] / nl, n[2] / nl]
        }
        var ref = Math.abs(n[2]) < 0.9 ? [0, 0, 1] : [1, 0, 0]
        var u = [n[1] * ref[2] - n[2] * ref[1], n[2] * ref[0] - n[0] * ref[2], n[0] * ref[1] - n[1] * ref[0]]
        var nu = Math.hypot(u[0], u[1], u[2]) || 1
        u = [u[0] / nu, u[1] / nu, u[2] / nu]
        var v = [n[1] * u[2] - n[2] * u[1], n[2] * u[0] - n[0] * u[2], n[0] * u[1] - n[1] * u[0]]
        return [u, v]
    }
    function ponto(u, v, r, th, cx, cy) {
        var c = Math.cos(th), s = Math.sin(th)
        var z = c * u[2] + s * v[2]
        var k = r * (1 + z / 5)
        return [cx + (c * u[0] + s * v[0]) * k, cy + (c * u[1] + s * v[1]) * k]
    }
    function vagar(cx, cy, R) {
        var t = st.t
        return [cx + ruido(t * 0.6, 3) * R * 1.4, cy + ruido(t * 0.5, 9) * R * 0.8]
    }
    function v4(a, b, c, d) { return Qt.vector4d(a, b, c, d) }
    readonly property vector4d zero4: Qt.vector4d(0, 0, 0, 0)
    // o efeito da camada é um Component: não se alcança por id, só por estas
    property vector2d _centroPos
    property vector4d _glt
    property vector4d _geo2

    function asaVec(slot, rx, ry, ang, L, lado, abert, olhos, ocultar) {
        fx["w" + slot + "a"] = v4(rx, ry, ang, L)
        fx["w" + slot + "b"] = v4(lado, abert, olhos, ocultar ? 1 : 0)
    }

    // monta os uniforms do quadro
    function montar() {
        var w = width, h = height
        if (w < 10 || h < 10) return
        var s = st, t = s.t
        var Rb = (raioFixo > 0 ? raioFixo : raioQueCabe(w, h, disco)) * zoom
        var cx = w / 2, cy = h / 2
        var lim = Math.min(w, h) / 2 - 1
        var k = Rb / rRef
        var ouvir = p("listening"), pensar = p("thinking"), ferr = p("tools")
        var falar = p("speaking") * voz

        // rajadas de glitch
        var rajada = false, sep = 0
        if (glitch) {
            if (t >= s.proxGlitch) {
                s.glitchAte = t + uni(0.08, 0.28)
                s.proxGlitch = t + uni(0.9, 3.6) / (1 + 3 * agitacao())
                if (Math.random() < 0.5 && skin !== "serafim")
                    s.salto[sorteia(4)] += (Math.random() < 0.5 ? -1 : 1) * uni(0.4, 1.4)
            }
            rajada = t < s.glitchAte
            sep = (rajada ? uni(2.5, 6.0) : 0.8 + 0.5 * Math.abs(ruido(t, 1))) * Math.max(0.6, k)
        }

        var R, gaze, i
        if (skin === "serafim") {
            var de = suave(desperto)
            R = Rb * (0.3 + 0.7 * de)
            var kk = R / 40
            // "os umbrais tremeram à voz" (Is 6:4)
            cx += ruido(t * 40, 1) * 2.2 * kk * falar
            cy += ruido(t * 37, 5) * 2.2 * kk * falar
            gaze = olharAlvo ? [olharAlvo.x, olharAlvo.y] : vagar(cx, cy, R)
            fx.raios = v4(24, t * 0.05, 1.35 + 0.4 * falar, (0.05 + 0.10 * s.tri + 0.06 * falar) * de)
            var ele = mistura({ idle: 0.20, listening: 0.10, thinking: 0.35, tools: 0.25, speaking: 0.30 })
            var amp = mistura({ idle: 0.16, listening: 0.05, thinking: 0.38, tools: 0.25, speaking: 0.18 }) + 0.3 * falar
            var abert = mistura({ idle: 0.75, listening: 0.6, thinking: 1.0, tools: 0.9, speaking: 0.9 }) * de
            var bat = Math.sin(s.faseAsa)
            asaVec(0, cx - 0.22 * R, cy - 0.02 * R, ele + amp * bat, R * de, -1, abert, 3, false)
            asaVec(1, cx + 0.22 * R, cy - 0.02 * R, ele + amp * bat, R * de, 1, abert, 3, false)
            var respira = 0.04 * Math.sin(s.faseAsa * 0.5)
            asaVec(2, cx + 0.10 * R, cy + 0.34 * R, -0.95 + respira, 0.72 * R * de, -1, 0.85 * de, 0, true)
            asaVec(3, cx - 0.10 * R, cy + 0.34 * R, -0.95 + respira, 0.72 * R * de, 1, 0.85 * de, 0, true)
            // Fechadas, as penas pendem para dentro, sobre o rosto; abertas, para
            // fora. A troca de lado acontece com a asa em pé: lê como leque.
            var a = suave(s.abre)
            for (var lado of [-1, 1]) {
                var ang, para, ab, q
                if (a < 0.5) {
                    q = a / 0.5
                    ang = 1.05 + (Math.PI / 2 - 1.05) * q; para = lado; ab = 0.85 - 0.75 * q
                } else {
                    q = (a - 0.5) / 0.5
                    ang = Math.PI / 2 - 0.55 * q; para = -lado; ab = 0.10 + 0.65 * q
                }
                asaVec(lado < 0 ? 4 : 5, cx - lado * (0.10 + 0.12 * a) * R, cy - 0.30 * R, ang + respira,
                       0.85 * R * de, para, ab * de, 0, true)
            }
            fx.sera = v4(s.fogo, s.tri, s.abre, s.brasa)
            fx.sera2 = v4(s.brasaAng, olhosSerafim, penasEncorpadas ? 1 : 0, 0)
            fx.ofa2 = v4(0, de, 6, 0)
        } else {
            var d = desperto
            R = Rb * (0.25 + 0.75 * suave(d))
            var comp = 1.25 + 0.45 * falar - 0.18 * ouvir + 0.10 * pensar
            fx.raios = v4(28, s.giroRaios, comp, (0.06 + 0.06 * pensar + 0.10 * falar + 0.15 * s.clarao) * suave(d))
            // ondas da voz: "o ruído das suas asas, como o de muitas águas"
            var on = []
            for (var o of s.ondas) {
                var idade = (t - o[0]) / 1.3
                var r = R * (0.55 + idade * 1.2)
                if (r >= lim) continue
                on.push(r, o[1] * (1 - idade) * (1 - r / lim) * 0.55)
            }
            while (on.length < 16) on.push(0, 0)
            fx.ondas0 = v4(on[0], on[1], on[2], on[3])
            fx.ondas1 = v4(on[4], on[5], on[6], on[7])
            fx.ondas2 = v4(on[8], on[9], on[10], on[11])
            fx.ondas3 = v4(on[12], on[13], on[14], on[15])
            gaze = olharAlvo ? [olharAlvo.x, olharAlvo.y] : vagar(cx, cy, R)

            if (skin === "ofanim_alado") {
                // "quando paravam, abaixavam as asas" (Ez 1:24); abertas para
                // ouvir e batendo no turbilhão; retas e vibrando nas ferramentas
                var deA = suave(desperto)
                var sup = mistura({ idle: -0.22, listening: 0.32, thinking: 0.55, tools: 0.10, speaking: 0.40 })
                var inf = mistura({ idle: -1.05, listening: -0.80, thinking: -0.62, tools: -0.75, speaking: -0.72 })
                var ampA = mistura({ idle: 0.04, listening: 0.02, thinking: 0.32, tools: 0.07, speaking: 0.10 }) + 0.30 * falar
                var abA = mistura({ idle: 0.25, listening: 0.7, thinking: 1.0, tools: 0.9, speaking: 0.85 }) * deA
                var batA = Math.sin(s.faseAsa)
                var slot = 0
                for (var ld of [-1, 1]) {
                    asaVec(slot++, cx + ld * 0.52 * R, cy - 0.22 * R, sup + ampA * batA, 0.88 * R * deA, ld, abA, 3, false)
                    asaVec(slot++, cx + ld * 0.46 * R, cy + 0.30 * R, inf - 0.5 * ampA * batA, 0.66 * R * deA, ld, abA * 0.8, 2, false)
                }
            } else {
                for (i = 0; i < 4; i++) fx["w" + i + "a"] = zero4
            }

            // aros
            var geo = []
            for (i = 0; i < 4; i++) {
                var uv = base(i)
                var rr = R * (1 - i * 0.075) * (1 - 0.06 * ouvir * mic)
                        * (1 + 0.09 * falar * Math.sin(t * 9 + i * 1.7))
                        * (1 + 0.025 * pensar * Math.sin(t * 2.2 + i))
                geo.push([uv[0], uv[1], rr])
                fx["a" + i + "u"] = v4(uv[0][0], uv[0][1], uv[0][2], rr)
                fx["a" + i + "v"] = v4(uv[1][0], uv[1][1], uv[1][2], 0)
            }
            // relâmpagos entre os olhos dos aros (Ez 1:14)
            var info = [0, 0, 0, 0]
            for (var j = 0; j < 2; j++) {
                var rl = s.relampagos[j]
                if (!rl) { fx["rel" + j] = zero4; continue }
                var g0 = geo[rl[1]], g1 = geo[rl[3]]
                var p0 = ponto(g0[0], g0[1], g0[2], rl[2], cx, cy)
                var p1 = ponto(g1[0], g1[1], g1[2], rl[4], cx, cy)
                fx["rel" + j] = v4(p0[0], p0[1], p1[0], p1[1])
                info[2 * j] = 1 - (t - rl[0]) / 0.12
                info[2 * j + 1] = rl[5]
            }
            fx.relInfo = v4(info[0], info[1], info[2], info[3])

            // olho central: pálpebra pelo estado, vasculha para cima quando pensa
            var abre = mistura({ idle: 1.0, listening: 1.15, thinking: 0.55, tools: 0.7, speaking: 1.0 })
            abre *= ((t % 6.3) > 0.18 ? 1.0 : 0.1) * lim01((d - 0.3) / 0.3)
            var gz = gaze
            if (pensar > 0.05) {
                var vg = [cx + ruido(t * 1.7, 21) * R * 2, cy - R * (0.6 + 0.6 * Math.abs(ruido(t * 1.1, 4)))]
                gz = [gaze[0] * (1 - pensar) + vg[0] * pensar, gaze[1] * (1 - pensar) + vg[1] * pensar]
            }
            var dx = gz[0] - cx, dy = gz[1] - cy, dl = Math.hypot(dx, dy) || 1
            fx.nucleoDir = Qt.vector2d(dx / dl, dy / dl)
            fx.ofa = v4(s.foco, s.pupila, s.clarao, abre)
            fx.ofa2 = v4(s.fase, suave(d), skin === "ofanim_alado" ? 4 : 0, 0)
        }

        fx.centro = Qt.vector2d(cx, cy)
        fx.olhar = Qt.vector2d(gaze[0], gaze[1])
        fx.geo = v4(R, lim, t, peso)
        fx.est = v4(ouvir, pensar, ferr, falar)
        fx.est2 = v4(voz, mic, desperto, skin === "serafim" ? 2 : (skin === "ofanim_alado" ? 1 : 0))

        _centroPos = Qt.vector2d(w / 2, h / 2)
        _glt = v4(sep, rajada ? 1 : 0, rajada ? Math.random() * 1000 : 0, k)
        _geo2 = v4(Rb, lim, (t * 18) % 3, glitch ? 1 : 0)
    }

    ShaderEffect {
        id: fx
        anchors.fill: parent
        fragmentShader: Qt.resolvedUrl("../shaders/figura_" + (raiz.skin in raiz.alcances ? raiz.skin : "ofanim") + ".frag.qsb")
        property vector2d tam: Qt.vector2d(width, height)
        property vector2d centro
        property vector2d olhar
        property vector2d nucleoDir: Qt.vector2d(1, 0)
        property vector4d geo
        property vector4d est
        property vector4d est2
        property vector4d ofa: Qt.vector4d(0.3, 1, 0, 1)
        property vector4d ofa2
        property vector4d raios
        property vector4d a0u
        property vector4d a0v
        property vector4d a1u
        property vector4d a1v
        property vector4d a2u
        property vector4d a2v
        property vector4d a3u
        property vector4d a3v
        property vector4d ondas0
        property vector4d ondas1
        property vector4d ondas2
        property vector4d ondas3
        property vector4d rel0
        property vector4d rel1
        property vector4d relInfo
        property vector4d w0a
        property vector4d w0b
        property vector4d w1a
        property vector4d w1b
        property vector4d w2a
        property vector4d w2b
        property vector4d w3a
        property vector4d w3b
        property vector4d w4a
        property vector4d w4b
        property vector4d w5a
        property vector4d w5b
        property vector4d sera
        property vector4d sera2
        property vector4d lacos: Qt.vector4d(30, 24, 10, raiz.skin === "serafim" ? 6 : (raiz.skin === "ofanim_alado" ? 4 : 0))
    }

    layer.enabled: true
    layer.effect: ShaderEffect {
        fragmentShader: Qt.resolvedUrl("../shaders/pos.frag.qsb")
        property vector2d tam: Qt.vector2d(raiz.width, raiz.height)
        property vector2d centro: raiz._centroPos
        property vector4d cor: Qt.vector4d(raiz.cor.r, raiz.cor.g, raiz.cor.b, raiz.alfa)
        property vector4d corA: raiz.glitch ? Qt.vector4d(1.0, 0.18, 0.32, 0.40) : Qt.vector4d(0, 0, 0, 0)
        property vector4d corB: raiz.glitch ? Qt.vector4d(0.15, 0.85, 1.0, 0.40) : Qt.vector4d(0, 0, 0, 0)
        property vector4d glt: raiz._glt
        property vector4d geo2: raiz._geo2
        property vector4d vidro: Qt.vector4d(raiz.vidroRaio, raiz.vidroAlfa, raiz.vidroInicio, raiz.vidroLigado ? 1 : 0)
        property vector4d corVidro: Qt.vector4d(raiz.vidroCor.r, raiz.vidroCor.g, raiz.vidroCor.b, 1)
        property vector4d modo: Qt.vector4d(0, 1, 0, 0)
        property vector4d banda0
        property vector4d banda1
        property vector4d banda2
        property vector4d banda3
    }
}
