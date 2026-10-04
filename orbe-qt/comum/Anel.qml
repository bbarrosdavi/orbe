import QtQuick

// Anel de energia: rotoscope do mp4 deformado fisicamente pela voz, portado
// do hermes_voice_orb.py. O desenho é do anel.frag (quadros num atlas, warp
// polar, línguas e gotas) e do pos.frag (cor e glitch); aqui fica a física:
// molas das línguas, gotas, quique global, fases dos lóbulos, rajadas de
// glitch do pensamento e a paleta por estado.
//
// As constantes por tique do original (30 Hz) foram convertidas para dt, então
// o anel anda igual a 60 Hz ou a 30 Hz.
Item {
    id: raiz

    // entradas do orbe
    property var mix: ({ listening: 1, thinking: 0, tools: 0, speaking: 0 })
    property string estado: "listening"
    property real nivel: 0          // nível cru do TTS (para detectar sílaba)
    property real nivelS: 0         // suavizado
    property real tomS: 0.5
    property real mic: 0
    property real micS: 0
    property real envEsc: 1         // escala da entrada/saída e do toque
    property real envAlfa: 1
    property real esc: 1            // tamanho do orbe (slider)
    property bool glitch: true
    property color accent: "#0087fc" // --colorAccentBg do matugen

    readonly property real artBox: 120
    readonly property real artEdge: 100
    readonly property real rLim: 70
    readonly property int nW: 36
    readonly property int nLingua: 10
    readonly property int nGota: 7
    readonly property int nQuadros: 62
    readonly property real tau: 2 * Math.PI

    // ── paleta: accent do tema derivado por HSV, como no _system_palette ──
    function hsv(h, s, v) { return Qt.hsva(((h % 1) + 1) % 1, Math.min(1, Math.max(0, s)), Math.min(1, v), 1) }
    readonly property real hBase: accent.hsvHue < 0 ? 0.58 : accent.hsvHue
    readonly property real sBase: Math.max(accent.hsvSaturation, 0.60)
    readonly property color tintBase: hsv(hBase, sBase, 1.0)
    readonly property color tintThink: hsv(hBase + 0.078, sBase, 1.0)
    readonly property color tintTools: hsv(hBase - 0.078, sBase, 0.92)
    readonly property color tintDeep: hsv(hBase, sBase + 0.15, 0.80)
    readonly property color tintHigh: hsv(hBase, sBase * 0.45, 1.0)

    // ── estado da física ──
    property var st: novo()
    function novo() {
        var s = {
            t: 0, rot: 0, framePos: 0, ph2: 0.9, ph3: 2.1, ampL: 0.5,
            tAng: [], tDrift: [], tH: [], tV: [], tW: [], tNext: 0,
            glAte: 0, glProx: 0.6, glLo: 0, glSpan: 0, glAmp: 0, glJump: 0, glShear: 0, glDx: 0, glBands: [],
            dE: [], dAng: [], dDist: [], dSpd: [], dNext: 0,
            rOff: 0, rVel: 0, rawAnt: 0, pb: null
        }
        for (var j = 0; j < nLingua; j++) {
            s.tAng.push(j * tau / nLingua)
            s.tDrift.push((((j * 37) % 100) / 100 - 0.5) * 0.30)
            s.tH.push(0); s.tV.push(0); s.tW.push(0.26)
        }
        for (var d = 0; d < nGota; d++) { s.dE.push(0); s.dAng.push(0); s.dDist.push(0); s.dSpd.push(0) }
        return s
    }
    function uni(a, b) { return a + Math.random() * (b - a) }

    function sorteia(n) { return Math.floor(Math.random() * n) }
    function wrap(a) { return ((a + Math.PI) % tau + tau) % tau - Math.PI }
    function lim(v, a, b) { return v < a ? a : (v > b ? b : v) }

    // (omega, caos, ampL, ganho da língua, vel. do loop, tinta, brilho, pulso)
    function params(e) {
        var t = st.t
        if (e === "thinking") {
            var osc = 0.5 + 0.5 * Math.sin(t * 3.1), resp = 0.5 + 0.5 * Math.sin(t * 2.2)
            return [0.9 * Math.sin(t * 0.45), 1.5 + 1.3 * resp, 1.6 + 3.6 * resp, 0.40, 1.8,
                    tintThink, 0.82 + 0.22 * osc, 1.0 + 0.03 * Math.sin(t * 2.6)]
        }
        if (e === "tools") {
            var pp = Math.abs(Math.sin(t * 3.4))
            return [-0.35, 1.0, 2.0, 0.55, 1.35, tintTools, 0.88 + 0.18 * pp, 1.0 + 0.025 * pp]
        }
        if (e === "speaking") {
            var lv = nivelS, tn = tomS
            var tint = Qt.rgba(tintDeep.r + (tintHigh.r - tintDeep.r) * tn,
                               tintDeep.g + (tintHigh.g - tintDeep.g) * tn,
                               tintDeep.b + (tintHigh.b - tintDeep.b) * tn, 1)
            return [0.15 + 1.6 * lv, 0.9 + 3.2 * lv, 1.5 + 6.0 * lv * (1.0 - 0.55 * tn),
                    0.5 + 1.7 * lv, 0.9 + 1.1 * lv, tint, 0.80 + 0.45 * lv, 1.0 + 0.08 * lv]
        }
        // listening: a expressividade é o único jeito de saber que o mic entra
        var m = micS, idle = 0.5 + 0.5 * Math.sin(t * 1.25)
        return [0.10 + 0.9 * m, 0.45 + 2.4 * m, 0.8 + 1.1 * idle + 5.5 * m, 0.35 + 1.4 * m,
                0.75 + 1.1 * m, tintBase, 0.82 + 0.55 * m, 1.0 + 0.02 * Math.sin(t * 1.6) + 0.10 * m]
    }
    function blend() {
        var tot = 0
        for (var e in mix) tot += mix[e]
        tot = tot || 1
        var o = [0, 0, 0, 0, 0, [0, 0, 0], 0, 0]
        for (var e2 in mix) {
            var w = mix[e2]
            if (w < 0.001) continue
            w /= tot
            var q = params(e2)
            for (var i = 0; i < 5; i++) o[i] += w * q[i]
            o[5][0] += w * q[5].r; o[5][1] += w * q[5].g; o[5][2] += w * q[5].b
            o[6] += w * q[6]; o[7] += w * q[7]
        }
        return o
    }

    function impulso(forca, tom) {
        var s = st
        var j = s.tNext % nLingua
        s.tNext++
        s.tV[j] += forca * (240 + 260 * tom)
        s.tW[j] = 0.38 - 0.22 * tom
        if (forca > 0.08) {
            var d = s.dNext % nGota
            s.dNext++
            s.dE[d] = 1.0
            s.dAng[d] = s.tAng[j] + Math.sin(s.t * 13.7 + j) * 0.25
            s.dDist[d] = 46
            s.dSpd[d] = 25 + 80 * forca
        }
    }

    function campo(th) {
        var s = st
        var f = s.rOff + s.ampL * (0.52 * Math.sin(2 * th + s.ph2) + 0.30 * Math.sin(3 * th + s.ph3)
                                   + 0.18 * Math.sin(5 * th - 1.7 * s.ph2))
        for (var j = 0; j < nLingua; j++) {
            var h = s.tH[j]
            if (h > 0.3) {
                var w = Math.max(s.tW[j] * 2.2, 0.60)
                var dth = wrap(th - s.tAng[j])
                if (Math.abs(dth) < 3 * w) f += 0.45 * h * Math.exp(-Math.pow(dth / w, 2))
            }
        }
        return f
    }

    function avancar(dt) {
        var s = st
        var k = dt / 0.033                       // tiques do original neste quadro
        s.t += dt
        var pb = blend()
        s.pb = pb
        var omega = pb[0], caos = pb[1], tgain = pb[3], fsp = pb[4]
        s.ampL = pb[2]

        var on = Math.max(0, nivel - s.rawAnt)
        s.rawAnt = nivel
        if (on > 0.03) impulso(on * Math.min(1, tgain), tomS)
        if (estado === "listening" && mic > micS + 0.10) impulso(0.35 * mic, 0.45)

        s.ph2 += 0.9 * (0.35 + 0.65 * caos) * dt
        s.ph3 += -1.3 * (0.35 + 0.65 * caos) * dt
        s.rot = (s.rot + omega * dt) % tau
        s.framePos = (s.framePos + fsp * k) % nQuadros

        // mola do raio global: voz no speaking, onda lenta no thinking, mic no listening
        var alvo = 8 * nivelS + 2.6 * (mix.thinking || 0) * Math.sin(s.t * 1.9) + 7 * (mix.listening || 0) * micS
        var forca = -40 * (s.rOff - alvo) - 7 * s.rVel
        s.rVel += forca * dt
        s.rOff += s.rVel * dt

        for (var j = 0; j < nLingua; j++) {
            s.tAng[j] = (s.tAng[j] + (omega * 0.6 + s.tDrift[j]) * dt) % tau
            var f = -55 * s.tH[j] - 6.5 * s.tV[j]
                    + nivelS * tgain * 420 * (0.35 + 0.65 * (0.5 + 0.5 * Math.sin(s.t * 3 + j * 2.1)))
            s.tV[j] += f * dt
            s.tH[j] = lim(s.tH[j] + s.tV[j] * dt, -3, 16)
        }

        // glitch do pensamento: rajadas curtas e irregulares, mais densas no fundo do raciocínio
        var wt = mix.thinking || 0
        if (wt > 0.25 && glitch) {
            if (s.t >= s.glProx) {
                s.glAte = s.t + uni(0.05, 0.20)
                s.glProx = s.glAte + uni(0.06, 0.75) / (0.4 + wt)
                s.glLo = sorteia(nW)
                s.glSpan = 2 + sorteia(Math.max(3, nW / 3) - 1)
                s.glAmp = uni(5, 15) * (Math.random() < 0.5 ? -1 : 1)
                s.glShear = uni(-0.09, 0.09)
                s.glJump = Math.random() < 0.34 ? 1 + sorteia(nQuadros - 1) : 0
                s.glDx = Math.random() < 0.75 ? uni(1.6, 5.5) : 0
                s.glBands = []
                var nb = sorteia(5)
                for (var b = 0; b < nb; b++)
                    s.glBands.push([uni(-46, 40), uni(2, 9), uni(5, 20) * (Math.random() < 0.5 ? -1 : 1)])
            }
        } else {
            s.glAte = 0
            s.glProx = s.t + 0.4
        }

        for (var d = 0; d < nGota; d++) {
            if (s.dE[d] > 0.04) {
                s.dDist[d] = Math.min(rLim, s.dDist[d] + s.dSpd[d] * dt)
                s.dSpd[d] *= Math.pow(0.97, k)
                s.dE[d] *= Math.pow(0.93, k)
            }
        }
        montar()
    }

    function v4(a, b, c, d) { return Qt.vector4d(a, b, c, d) }

    function montar() {
        var s = st, pb = s.pb
        if (!pb) return
        var tint = pb[5], bright = pb[6], pulse = pb[7]
        var lift = 0.25 * Math.max(0, bright - 1)
        corAnel = Qt.rgba(Math.min(1, tint[0] * bright + lift), Math.min(1, tint[1] * bright + lift),
                          Math.min(1, tint[2] * bright), 1)
        var glowk = envAlfa * Math.max(0, Math.min(1, 0.55 + (bright - 0.80)))
        var scb = (artBox / 256) * envEsc * pulse * esc

        var rajada = s.t < s.glAte
        var glk = rajada ? (mix.thinking || 0) : 0
        var idx = Math.floor(s.framePos) % nQuadros
        if (glk > 0 && s.glJump) idx = (idx + s.glJump) % nQuadros

        var dth = tau / nW, campos = [], fmax = 0
        for (var i = 0; i < nW; i++) campos.push(campo((i + 0.5) * dth))
        if (glk > 0) {
            for (var k = 0; k < s.glSpan; k++) {
                var ii = (s.glLo + k) % nW
                var borda = k === 0 || k === s.glSpan - 1
                campos[ii] += s.glAmp * glk * (borda ? 0.5 : 1)
            }
        }
        for (i = 0; i < nW; i++) fmax = Math.max(fmax, Math.abs(campos[i]))
        var esca = campos.map(function (f) { return lim(1 + f / 50, 0.84, 1.28) })
        for (i = 0; i < 9; i++) fx["campo" + i] = v4(esca[4 * i], esca[4 * i + 1], esca[4 * i + 2], esca[4 * i + 3])

        fx.geo = v4(scb, s.rot, idx, lim(1 + s.rOff / 50, 0.84, 1.28))
        fx.extra = v4(glowk, fmax < 0.8 ? 1 : 0, esc, rLim * esc)
        fx.gl = v4(s.glLo, glk > 0 && s.glShear ? s.glSpan : 0, s.glShear * glk, 0)
        fx.tempo = v4(s.t, envAlfa, 0, 0)

        for (var j = 0; j < nLingua; j++) {
            var h = s.tH[j]
            if (h < 1.2) { fx["lingua" + j] = v4(0, 0, 0, 0); continue }
            var a = s.tAng[j]
            var sa = lim(1 + campo(a) / 50, 0.84, 1.28)
            var rb = artEdge * scb * sa * 0.94
            fx["lingua" + j] = v4(a, rb, Math.min(rLim * esc, rb + h * 2 * esc), s.tW[j])
        }
        for (var d = 0; d < nGota; d++) {
            var e = s.dE[d]
            fx["gota" + d] = e <= 0.04 ? v4(0, 0, 0, 0)
                : v4(Math.cos(s.dAng[d]) * s.dDist[d] * esc, Math.sin(s.dAng[d]) * s.dDist[d] * esc, e, 0)
        }

        _glt = v4(s.glDx, 0, 0, glk)
        var bs = []
        for (var b = 0; b < 4; b++) {
            var bd = s.glBands[b]
            bs.push(bd && glk > 0 ? v4(bd[0], bd[1], bd[2], 1) : v4(0, 0, 0, 0))
        }
        _bandas = bs
    }

    property color corAnel: tintBase
    property vector4d _glt
    property var _bandas: [Qt.vector4d(0, 0, 0, 0), Qt.vector4d(0, 0, 0, 0), Qt.vector4d(0, 0, 0, 0), Qt.vector4d(0, 0, 0, 0)]

    Image {
        id: atlasImg
        source: Qt.resolvedUrl("anel_atlas.png")
        mipmap: true
        smooth: true
        visible: false
    }

    ShaderEffect {
        id: fx
        anchors.fill: parent
        fragmentShader: Qt.resolvedUrl("../shaders/anel.frag.qsb")
        property variant atlas: atlasImg
        property vector2d tam: Qt.vector2d(width, height)
        property vector2d centro: Qt.vector2d(width / 2, height / 2)
        property vector4d geo
        property vector4d extra
        property vector4d gl
        property vector4d campo0
        property vector4d campo1
        property vector4d campo2
        property vector4d campo3
        property vector4d campo4
        property vector4d campo5
        property vector4d campo6
        property vector4d campo7
        property vector4d campo8
        property vector4d lingua0
        property vector4d lingua1
        property vector4d lingua2
        property vector4d lingua3
        property vector4d lingua4
        property vector4d lingua5
        property vector4d lingua6
        property vector4d lingua7
        property vector4d lingua8
        property vector4d lingua9
        property vector4d gota0
        property vector4d gota1
        property vector4d gota2
        property vector4d gota3
        property vector4d gota4
        property vector4d gota5
        property vector4d gota6
        property vector4d tempo
    }

    // sombra atrás do anel, no passe de pós
    property bool sombraLigada: false
    property real sombraRaio: 0
    property real sombraAlfa: 0.45
    property color sombraCor: "#121414"

    layer.enabled: true
    layer.effect: ShaderEffect {
        fragmentShader: Qt.resolvedUrl("../shaders/pos.frag.qsb")
        property vector2d tam: Qt.vector2d(raiz.width, raiz.height)
        property vector2d centro: Qt.vector2d(raiz.width / 2, raiz.height / 2)
        property vector4d cor: Qt.vector4d(raiz.corAnel.r, raiz.corAnel.g, raiz.corAnel.b, raiz.envAlfa)
        // ciano e magenta fixos: só leem como canal separado se forem quase complementares
        property vector4d corA: Qt.vector4d(0.00, 0.95, 0.95, 0.60)
        property vector4d corB: Qt.vector4d(1.00, 0.08, 0.55, 0.60)
        property vector4d glt: raiz._glt
        property vector4d geo2: Qt.vector4d(0, 0, 0, 0)
        property vector4d sombra: Qt.vector4d(raiz.sombraRaio, raiz.sombraAlfa, 0, raiz.sombraLigada ? 1 : 0)
        property vector4d corSombra: Qt.vector4d(raiz.sombraCor.r, raiz.sombraCor.g, raiz.sombraCor.b, 1)
        property vector4d modo: Qt.vector4d(1, raiz.esc, 0, 0)
        property vector4d banda0: raiz._bandas[0]
        property vector4d banda1: raiz._bandas[1]
        property vector4d banda2: raiz._bandas[2]
        property vector4d banda3: raiz._bandas[3]
    }
}
