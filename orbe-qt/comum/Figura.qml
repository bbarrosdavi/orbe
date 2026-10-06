import QtQuick

// Ophanim e Ophanim com asas desenhados na GPU.
//
// O desenho mora em dois shaders: figura.frag pinta a máscara branca da
// figura (cada traço é uma função de distância) e pos.frag dá a cor e o
// glitch. Aqui fica só o que tem memória entre quadros, portado de
// avatares do orbe GTK (Cairo, aposentado em 2026-10-04): giro das rodas, travas em quarto de volta, ondas
// da voz, relâmpagos, batida das asas, rajadas de glitch. Quem usa chama avancar(dt) a cada quadro (FrameAnimation).
//
// Reações por estado (pesos de mix, os mesmos do anel de energia):
// ouvindo, as rodas quase param e todos os olhos se voltam para quem fala;
// pensando, turbilhão;
// ferramentas, rodas travadas nos eixos em quartos de volta, com relâmpagos;
// falando, ondas a cada sílaba; ao despertar, as rodas desdobram de um ponto.
// Skins de imagem (imagem.frag): a ilustração recortada em camadas num atlas
// (arte/<skin>.png); as asas giram em volta da raiz e as íris seguem o olhar.
// Seraphim (gravura): parado, meio recolhido; ouvindo, aberto como desenhado;
// pensando, as asas batem; falando, tremulam com a voz.
// Olho e Humana (peças recortadas, como num Live2D; ver imagem.frag): cada
// membro e cada raio é uma cadeia de juntas com molas, e a junta de fora
// recebe o contrário da velocidade da de dentro, o que dá o chicote dos
// tentáculos. Parado, uma onda lenta corre da base à ponta; ouvindo, os
// membros se esticam e acalmam, e o olho encara quem fala com a pupila
// aberta; pensando, se contorcem devagar (a figura não gira), e as pálpebras
// apertam; ferramentas, espasmos; falando, cada sílaba chuta as bases e o
// chute sobe até as pontas. Os corpos da Humana balançam em volta do pescoço,
// levando os membros. No Olho os raios ficam presos ao globo e fluem (uma
// ondulação que corre do olho para fora, chutada a cada sílaba); a íris anda
// para o olhar e o olho fica bem aberto.
Item {
    id: raiz

    property string skin: "ofanim"         // ofanim | ofanim_alado | serafim_gravura | olho | humana
    property bool glitch: true
    property real peso: 1.0                // traço mais grosso e opaco (o orbe usa mais)
    property color cor: "white"
    property color corOlhos: "transparent" // íris em cor própria; transparente = a do traço
    property real raioFixo: -1             // R explícito; -1 = o maior que cabe
    property real disco: -1                // > 0: cabe também num disco desse raio
    property real zoom: 1.0
    property real alfa: 1.0
    property var olharAlvo: null           // Qt.point no item, ou null (olhos vagam)
    property var mix: ({ idle: 1.0 })      // pesos por estado
    property real voz: 0
    property real mic: 0
    property real desperto: 1
    property bool repouso: false           // skins de imagem: pose desenhada, parada (teste pixel a pixel)

    // sombra atrás da figura, no passe de pós
    property bool sombraLigada: false
    property real sombraRaio: 0
    property real sombraAlfa: 0.45
    property color sombraCor: "#121414"

    readonly property real rRef: 82.0      // raio em que o glitch foi afinado
    readonly property var alcances: ({
        ofanim: [1.55, 1.55, 1.25],
        ofanim_alado: [2.1, 1.55, 2.08],
        serafim_gravura: [1.15, 1.3, 1.4],
        olho: [1.1, 1.36, 1.36],
        humana: [1.18, 1.13, 1.27]
    })
    // skins de imagem: o atlas mora em arte/<skin>.png
    readonly property var imagens: ({ serafim_gravura: true, olho: true, humana: true })
    // as de peças: quantas cadeias, quantas juntas em cada e quantos corpos (imagem.frag)
    readonly property var polares: ({ olho: true, humana: true })
    readonly property var partes: ({ olho: { cadeias: 0, juntas: 0, corpos: 0 }, humana: { cadeias: 27, juntas: 3, corpos: 8 } })

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
            faseAsa: 0,
            abreAsa: 0.2, ampAsa: 0,
            // olho e humana: as molas das peças (estadoPartes), a pupila que encara
            pc: null, encarar: 0
        }
    }

    function avancar(dt) {
        var s = st
        s.t += dt
        // ondas da voz, uma por sílaba, em qualquer skin
        var subida = voz - s.vozAnt
        if (p("speaking") > 0.3 && s.t - s.ultimaOnda > 0.12
                && (subida > 0.05 || (voz > 0.3 && s.t - s.ultimaOnda > 0.3))) {
            s.ondas.push([s.t, Math.min(1, 0.35 + voz)])
            s.ultimaOnda = s.t
        }
        s.ondas = s.ondas.filter(function (o) { return s.t - o[0] < 1.3 })
        if (skin === "serafim_gravura") evoluirGravura(dt)
        else if (skin in polares) evoluirPartes(dt)
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

        if (Math.random() < dt * (2.4 * ferr + 0.5 * pensar))
            s.relampagos.push([t, sorteia(4), uni(0, tau), sorteia(4), uni(0, tau), Math.random() * 100])
        s.relampagos = s.relampagos.filter(function (r) { return t - r[0] < 0.12 })
        s.clarao = s.relampagos.length ? 1.0 : s.clarao * Math.max(0, 1 - dt * 8)

        var alvoP = 1.0 + 0.25 * ouvir + 0.6 * ouvir * mic - 0.25 * pensar
        s.pupila += (alvoP - s.pupila) * Math.min(1, dt * 8)
    }

    function evoluirGravura(dt) {
        var s = st
        var falar = p("speaking") * voz
        // a pose desenhada é a de ouvir; parado, as asas se recolhem
        var ab = mistura({ idle: 0.55, listening: 1.0, thinking: 0.85, tools: 0.9, speaking: 0.95 })
        s.abreAsa += (ab - s.abreAsa) * Math.min(1, dt * 3)
        var amp = mistura({ idle: 0.06, listening: 0.0, thinking: 0.35, tools: 0.22, speaking: 0.12 }) + 0.3 * falar
        s.ampAsa += (amp - s.ampAsa) * Math.min(1, dt * 3)
        s.faseAsa += dt * tau * (mistura({ idle: 0.2, listening: 0.1, thinking: 0.9, tools: 1.6, speaking: 0.6 }) + 0.8 * falar)
    }

    function estadoPartes() {
        var s = st
        if (s.pc) return s.pc
        var d = partes[skin]
        var pc = { ang: [], vel: [], fase: [], sinal: [], sem: [], est: [], vest: [],
                   corpo: [], vcorpo: [], fcorpo: [], fluxo: 0, amp: 0, vamp: 0, brilho: 0 }
        for (var i = 0; i < d.cadeias; i++) {
            pc.ang.push([0, 0, 0]); pc.vel.push([0, 0, 0])
            pc.fase.push(uni(0, tau)); pc.sinal.push(Math.random() < 0.5 ? -1 : 1); pc.sem.push(uni(0, 100))
            pc.est.push(0); pc.vest.push(0)
        }
        for (var b = 0; b < d.corpos; b++) { pc.corpo.push(0); pc.vcorpo.push(0); pc.fcorpo.push(uni(0, tau)) }
        s.pc = pc
        return pc
    }

    function evoluirPartes(dt) {
        var s = st, t = s.t, pc = estadoPartes(), d = partes[skin]
        var ouvir = p("listening"), ferr = p("tools")
        var falar = p("speaking") * voz
        var dG = suave(desperto)
        var humana = skin === "humana"
        // a onda nascida neste quadro (uma por sílaba) chuta as bases
        var chute = s.ultimaOnda === s.t && s.ondas.length ? s.ondas[s.ondas.length - 1][1] : 0
        var amp = humana ? mistura({ idle: 0.16, listening: 0.06, thinking: 0.30, tools: 0.12, speaking: 0.18 })
                         : mistura({ idle: 0.13, listening: 0.05, thinking: 0.26, tools: 0.10, speaking: 0.17 })
        var fr = humana ? mistura({ idle: 0.32, listening: 0.20, thinking: 0.26, tools: 1.8, speaking: 0.7 })
                        : mistura({ idle: 0.55, listening: 0.40, thinking: 0.80, tools: 2.4, speaking: 1.2 })
        var ganho = humana ? [0.45, 1.0, 1.25] : [0.7, 1.25]
        var K = humana ? [26, 34, 42] : [30, 38], C = humana ? [4.2, 4.8, 5.4] : [4.6, 5.2]
        var lim = humana ? [0.32, 0.7, 0.8] : [0.5, 0.75]
        var nj = d.juntas
        // ao despertar, as peças vêm encolhidas e se abrem
        var enrola = (1 - dG) * 0.9
        // espasmo das ferramentas: uma junta qualquer leva um tranco
        if (ferr > 0.05 && Math.random() < ferr * dt * 4) {
            var ci = sorteia(d.cadeias)
            pc.vel[ci][sorteia(nj)] += uni(-4, 4)
        }
        if (chute > 0) {
            for (var c0 = 0; c0 < d.cadeias; c0++) {
                if (Math.random() < 0.7) pc.vel[c0][0] += pc.sinal[c0] * chute * uni(0.6, 1.6) * (humana ? 1.2 : 1.8)
                if (!humana) pc.vest[c0] += chute * uni(0.4, 1.2)
            }
        }
        var n = Math.max(1, Math.ceil(dt / 0.012)), h = dt / n
        for (var it = 0; it < n; it++) {
            for (var i = 0; i < d.cadeias; i++) {
                var a = pc.ang[i], v = pc.vel[i], sg = pc.sinal[i]
                for (var j = 0; j < nj; j++) {
                    var onda = Math.sin(tau * fr * t + pc.fase[i] - 1.1 * j)
                    var alvo = sg * (amp * ganho[j] * onda - enrola * ganho[j]) + amp * 0.35 * ruido(t * fr * 1.7, pc.sem[i] + j)
                    // o chicote: a junta de fora atrasa em relação à de dentro
                    var acc = K[j] * (alvo - a[j]) - C[j] * v[j] - (j > 0 ? 4.0 * v[j - 1] : 0)
                    v[j] += acc * h
                    a[j] = Math.max(-lim[j], Math.min(lim[j], a[j] + v[j] * h))
                }
                if (!humana) {
                    var ae = mistura({ idle: 0.0, listening: 0.06, thinking: -0.03, tools: 0.0, speaking: 0.04 }) - 0.55 * (1 - dG)
                    pc.vest[i] += (40 * (ae - pc.est[i]) - 6 * pc.vest[i]) * h
                    pc.est[i] = Math.max(-0.6, Math.min(0.5, pc.est[i] + pc.vest[i] * h))
                }
            }
            if (humana) {
                var ab = mistura({ idle: 0.04, listening: 0.02, thinking: 0.07, tools: 0.03, speaking: 0.05 })
                for (var b = 0; b < d.corpos; b++) {
                    var alvoB = ab * Math.sin(tau * 0.22 * t + pc.fcorpo[b]) + ab * 0.4 * ruido(t * 0.5, pc.fcorpo[b] * 7)
                    pc.vcorpo[b] += (14 * (alvoB - pc.corpo[b]) - 3.2 * pc.vcorpo[b]) * h
                    pc.corpo[b] = Math.max(-0.12, Math.min(0.12, pc.corpo[b] + pc.vcorpo[b] * h))
                }
            }
        }
        if (humana && chute > 0)
            for (var b2 = 0; b2 < d.corpos; b2++) pc.vcorpo[b2] += (Math.random() < 0.5 ? -1 : 1) * chute * 0.35
        if (!humana) {
            // os raios fluem presos ao olho: a ondulação corre do olho para fora,
            // com a amplitude numa mola que cada sílaba chuta
            var alvoA = mistura({ idle: 2.0, listening: 1.5, thinking: 3.5, tools: 2.5, speaking: 3.0 }) + 3 * falar - 2 * (1 - dG)
            if (chute > 0) pc.vamp += chute * 12
            pc.vamp += (30 * (alvoA - pc.amp) - 7 * pc.vamp) * dt
            pc.amp = Math.max(0, pc.amp + pc.vamp * dt)
            pc.fluxo += dt * (mistura({ idle: 1.4, listening: 1.0, thinking: 2.6, tools: 3.6, speaking: 2.0 }) + 1.5 * falar)
            pc.brilho = mistura({ idle: 0.25, listening: 0.15, thinking: 0.4, tools: 0.3, speaking: 0.45 }) + 0.5 * falar
        }
        // a pupila abre para ouvir e fecha para pensar; encarar a leva ao meio
        var dil = mistura({ idle: 1.0, listening: 1.15, thinking: 0.82, tools: 0.78, speaking: 1.04 }) + 0.12 * ouvir * mic
        s.pupila += (dil - s.pupila) * Math.min(1, dt * 5)
        s.encarar += (ouvir - s.encarar) * Math.min(1, dt * 4)
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

        // rajadas de glitch; pensando, na cadência do anel: curtas e em sequência
        var rajada = false, sep = 0
        if (glitch) {
            if (t >= s.proxGlitch) {
                var ag = agitacao()
                s.glitchAte = t + (ag > 0.25 ? uni(0.05, 0.20) : uni(0.08, 0.28))
                s.proxGlitch = s.glitchAte + (ag > 0.25 ? uni(0.06, 0.75) / (0.4 + ag) : uni(0.9, 3.6))
                if (Math.random() < 0.5)
                    s.salto[sorteia(4)] += (Math.random() < 0.5 ? -1 : 1) * uni(0.4, 1.4)
            }
            rajada = t < s.glitchAte
            sep = (rajada ? uni(4.0, 11.0) : 0.8 + 0.5 * Math.abs(ruido(t, 1))) * Math.max(0.6, k)
        }

        var R, gaze, i
if (skin in polares) {
            var dP = suave(desperto)
            R = Rb * (0.3 + 0.7 * dP)
            gaze = olharAlvo ? [olharAlvo.x, olharAlvo.y] : vagar(cx, cy, R)
            if (pensar > 0.05) {
                // pensando, a pupila vasculha para cima
                var vgP = [cx + ruido(t * 1.7, 21) * R * 2, cy - R * (0.6 + 0.6 * Math.abs(ruido(t * 1.1, 4)))]
                gaze = [gaze[0] * (1 - pensar) + vgP[0] * pensar, gaze[1] * (1 - pensar) + vgP[1] * pensar]
            }
            var pc = estadoPartes(), dd = partes[skin]
            if (repouso) {
                gaze = [cx, cy]
                fx.img = v4(0, 0, 0, 1)
                fx.img2 = zero4
                for (var mi = 0; mi < 48; mi++) fx["m" + mi] = zero4
            } else {
                if (skin === "olho") {
                    fx.img = v4(pc.amp, pc.fluxo, 0.025 * falar + 0.006 * Math.sin(t * 1.1) * dP, 1)
                    fx.img2 = v4(pc.brilho, s.encarar, 0, 0)
                } else {
                    fx.img = v4(0, 0, 0.025 * falar + 0.006 * Math.sin(t * 1.1) * dP, 1)
                    fx.img2 = zero4
                }
                for (var m = 0; m < 48; m++) {
                    if (m < dd.cadeias) {
                        var am = pc.ang[m]
                        fx["m" + m] = v4(am[0], am[1], dd.juntas > 2 ? am[2] : pc.est[m], 0)
                    } else if (m < dd.cadeias + dd.corpos) {
                        fx["m" + m] = v4(pc.corpo[m - dd.cadeias], 0, 0, 0)
                    } else {
                        fx["m" + m] = zero4
                    }
                }
            }
        } else if (skin === "serafim_gravura") {
            var dG = suave(desperto)
            R = Rb * (0.3 + 0.7 * dG)
            gaze = olharAlvo ? [olharAlvo.x, olharAlvo.y] : vagar(cx, cy, R)
            if (pensar > 0.05) {
                // pensando, o olho do meio vasculha para cima
                var vgG = [cx + ruido(t * 1.7, 21) * R * 2, cy - R * (0.6 + 0.6 * Math.abs(ruido(t * 1.1, 4)))]
                gaze = [gaze[0] * (1 - pensar) + vgG[0] * pensar, gaze[1] * (1 - pensar) + vgG[1] * pensar]
            }
            if (repouso) {
                gaze = [cx, cy]
                fx.img = v4(1, 0, 0, 0)
            } else {
                fx.img = v4(s.abreAsa * dG, s.ampAsa * Math.sin(s.faseAsa), 0.025 * falar, 0)
            }
        } else {
            var d = desperto
            R = Rb * (0.25 + 0.75 * suave(d))
            var comp = 1.25 + 0.45 * falar - 0.18 * ouvir + 0.10 * pensar
            fx.raios = v4(28, s.giroRaios, comp, (0.06 + 0.06 * pensar + 0.10 * falar + 0.15 * s.clarao) * suave(d))
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

        fx.geo = v4(R, lim, t, peso)
        fx.est = v4(ouvir, pensar, ferr, falar)
        fx.est2 = v4(voz, mic, desperto, skin === "ofanim_alado" ? 1 : 0)

        _centroPos = Qt.vector2d(w / 2, h / 2)
        _glt = v4(sep, rajada ? 1 : 0, rajada ? Math.random() * 1000 : 0, k)
        // linhas de varredura só nas desenhadas: na imagem elas riscam a hachura
        _geo2 = v4(Rb, lim, (t * 18) % 3, glitch && !(skin in imagens) ? 1 : 0)
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
        property vector4d img                 // skins de imagem: estado de cada uma (ver imagem.frag)
        property vector4d img2
        property vector4d m0
        property vector4d m1
        property vector4d m2
        property vector4d m3
        property vector4d m4
        property vector4d m5
        property vector4d m6
        property vector4d m7
        property vector4d m8
        property vector4d m9
        property vector4d m10
        property vector4d m11
        property vector4d m12
        property vector4d m13
        property vector4d m14
        property vector4d m15
        property vector4d m16
        property vector4d m17
        property vector4d m18
        property vector4d m19
        property vector4d m20
        property vector4d m21
        property vector4d m22
        property vector4d m23
        property vector4d m24
        property vector4d m25
        property vector4d m26
        property vector4d m27
        property vector4d m28
        property vector4d m29
        property vector4d m30
        property vector4d m31
        property vector4d m32
        property vector4d m33
        property vector4d m34
        property vector4d m35
        property vector4d m36
        property vector4d m37
        property vector4d m38
        property vector4d m39
        property vector4d m40
        property vector4d m41
        property vector4d m42
        property vector4d m43
        property vector4d m44
        property vector4d m45
        property vector4d m46
        property vector4d m47
        property var arte: arteImg
        property vector4d lacos: Qt.vector4d(30, 24, 10, raiz.skin === "ofanim_alado" ? 4 : 0)
    }

    Image {
        id: arteImg
        visible: false
        source: raiz.skin in raiz.imagens ? Qt.resolvedUrl("../arte/" + raiz.skin + ".png") : ""
        mipmap: true
        smooth: true
    }

    layer.enabled: true
    layer.effect: ShaderEffect {
        fragmentShader: Qt.resolvedUrl("../shaders/pos.frag.qsb")
        property vector2d tam: Qt.vector2d(raiz.width, raiz.height)
        property vector2d centro: raiz._centroPos
        property vector4d cor: Qt.vector4d(raiz.cor.r, raiz.cor.g, raiz.cor.b, raiz.alfa)
        // ciano e magenta do anel; na rajada, tão opacos quanto os dele
        readonly property real alfaGl: raiz._glt.y > 0.5 ? 0.60 : 0.40
        property vector4d corA: raiz.glitch ? Qt.vector4d(0.00, 0.95, 0.95, alfaGl) : Qt.vector4d(0, 0, 0, 0)
        property vector4d corB: raiz.glitch ? Qt.vector4d(1.00, 0.08, 0.55, alfaGl) : Qt.vector4d(0, 0, 0, 0)
        property vector4d glt: raiz._glt
        property vector4d geo2: raiz._geo2
        property vector4d sombra: Qt.vector4d(raiz.sombraRaio, raiz.sombraAlfa, 0, raiz.sombraLigada ? 1 : 0)
        // nas gravuras recortadas (Paranoia, Rei dos Ratos) a massa é preta, como no
        // desenho: no tom do fundo do tema ela levantava as sombras e lavava a imagem
        property vector4d corSombra: raiz.skin in raiz.polares ? Qt.vector4d(0, 0, 0, 1)
                                     : Qt.vector4d(raiz.sombraCor.r, raiz.sombraCor.g, raiz.sombraCor.b, 1)
        property vector4d modo: Qt.vector4d(0, 1, 0, 0)
        property vector4d banda0
        property vector4d banda1
        property vector4d banda2
        property vector4d banda3
        property vector4d olhos: Qt.vector4d(raiz.corOlhos.r, raiz.corOlhos.g, raiz.corOlhos.b, raiz.corOlhos.a)
    }
}
