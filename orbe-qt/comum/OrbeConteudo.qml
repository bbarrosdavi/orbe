import QtQuick

// Conteúdo do orbe de voz, sem nada de Quickshell, para rodar offscreen nos
// testes. Portado do Ring/OrbWin do hermes_voice_orb.py: fases de entrada e
// saída, suavização dos níveis, protocolo do daemon, painel de texto do
// raciocínio e ponto de sessão travada. O desenho é da Figura (avatares) ou do
// Anel (rotoscope), os dois na GPU.
//
// Os fatores por tique do original (30 Hz) viram fatores por dt, então o
// orbe anda igual em qualquer taxa de quadros.
Item {
    id: orbe

    // ── aparência (config.json → orbe; cores do matugen) ──
    property string skin: "ofanim"
    property bool glitch: true
    property bool vidro: false             // sombra atrás do orbe (chave antiga do config)
    property real tamanho: 1.0
    property string textoPos: "lado"       // lado | abaixo: onde fica o raciocínio
    property color corTema: "#b8cacb"      // @accent_bg_color: cor dos avatares
    property color accent: "#f3b2e3"       // --colorAccentBg: paleta do anel
    property color corFundo: "#121414"     // @window_bg_color: sombra e contorno do texto

    readonly property bool avatar: skin === "ofanim" || skin === "ofanim_alado" || skin === "shoggoth" || skin === "serafim_gravura" || skin === "entidade"
    // as skins de imagem saem 5/3 maiores: o 60% do slider delas é o 100% das
    // outras (reduzida demais, a gravura perde a hachura)
    readonly property real escala: tamanho * (skin === "serafim_gravura" || skin === "entidade" ? 5 / 3 : 1)
    // ART_BOX é o tamanho visual da arte; ORB_BOX, a célula reservada para ela
    readonly property int orbBox: Math.round(148 * escala)
    readonly property int artBox: Math.round(120 * escala)
    readonly property int painel: 296      // coluna de texto: o raciocínio legível
    readonly property real cx: painel + orbBox / 2
    readonly property real cy: orbBox / 2
    readonly property bool textoAbaixo: textoPos === "abaixo"
    // abaixo, o texto começa onde a figura termina (medido nos renders, em
    // fração da célula a partir do centro): a linha mais antiga some ali
    readonly property var pes: ({ ofanim: 0.39, ofanim_alado: 0.29, shoggoth: 0.42, serafim_gravura: 0.38, entidade: 0.47, anel: 0.35 })
    readonly property real yTexto: Math.round(cy + orbBox * (pes[skin] || 0.35))
    // topo da figura acima do centro, em fração da célula (medido nos renders,
    // na coluna do meio, ouvindo e parada): o ponto da sessão travada fica
    // logo acima dele, perto da figura e longe da borda de cima da tela
    readonly property var topo: ({ ofanim: 0.345, ofanim_alado: 0.277, shoggoth: 0.365, serafim_gravura: 0.355, entidade: 0.486, anel: 0.412 })
    // abaixo, o orbe fica no mesmo lugar e a janela desce até a 5ª linha
    width: painel + orbBox
    height: textoAbaixo ? Math.max(orbBox, yTexto + 5 * 17 + 4) : orbBox

    // ── estado ──
    readonly property var estados: ["idle", "listening", "thinking", "speaking", "tools"]
    property string estado: "listening"
    property var mix: ({ idle: 0, listening: 1, thinking: 0, speaking: 0, tools: 0 })
    property real nivel: 0
    property real nivelS: 0
    property real tom: 0.5
    property real tomS: 0.5
    property real mic: 0
    property real micS: 0
    property bool toque: false             // dedo no orbe agora
    property real toqueS: 0                // sobe rápido, desce devagar
    property bool travado: false           // sessão travada pelo Jarvis
    property var linhas: []
    property bool visivel: false
    property string fase: "run"            // in | run | out
    property real faseT: 0
    property real t: 0
    property var olhar: null               // Qt.point na célula do orbe, ou null

    // envelope da entrada/saída (o toque cresce a arte por cima)
    property real envEsc: 1
    property real envAlfa: 1
    readonly property real toqueCresce: 0.12

    readonly property real raioSombra: envAlfa < 0.05 ? 0 : (orbBox / 2 - 3) * Math.min(1, envEscBase)
    property real envEscBase: 1

    signal saiu()                          // a saída acabou: a janela pode sumir

    function lim01(v) { return v < 0 ? 0 : (v > 1 ? 1 : v) }
    function easeOutBack(p) { var c = 1.70158, q = p - 1; return 1 + (c + 1) * q * q * q + c * q * q }
    // fator por tique do original convertido para este dt
    function fator(a, k) { return 1 - Math.pow(1 - a, k) }

    // ── comandos (mesma semântica do OrbWin) ──
    function mostrar(e) {
        linhas = []
        if (estados.indexOf(e) >= 0) estado = e
        if (!visivel || fase === "out") {
            fase = "in"
            faseT = 0
            if (!avatar && arte.item) arte.item.st.framePos = 0
        }
        visivel = true
    }
    function definirEstado(e) {
        if (estados.indexOf(e) >= 0) estado = e
        if (!visivel) mostrar(e)
    }
    function audio(lv, tn) {
        nivel = lim01(lv)
        if (tn !== undefined && tn !== null && !isNaN(tn)) tom = lim01(tn)
        if (estado !== "speaking" && nivel > 0.08) estado = "speaking"
    }
    function esconder() {
        linhas = []
        if (visivel && fase !== "out") {
            fase = "out"
            faseT = 0
        } else {
            visivel = false
        }
    }
    function empurrarLinha(texto) {
        // tira glifos sem cobertura na fonte (emoji, nerd fonts, símbolos)
        var s = ""
        for (var i = 0; i < (texto || "").length; i++) {
            var c = texto.charCodeAt(i)
            if (c >= 0x20 && c < 0x2400) s += texto[i]
        }
        s = s.replace(/\[\?[0-9;]*[A-Za-z]/g, "").split(/\s+/).filter(function (w) { return w.length }).join(" ")
        if (!s) return
        var l = linhas.slice()
        l.push(s.slice(0, 220))
        linhas = l.slice(-6)
    }

    // Uma linha do protocolo do daemon. "quit" fica com o shell.
    function comando(linha) {
        linha = (linha || "").trim()
        if (!linha) return
        var i = linha.indexOf(" ")
        var op = i < 0 ? linha : linha.slice(0, i)
        var arg = i < 0 ? "" : linha.slice(i + 1).trim()
        if (op === "warm") {
        } else if (op === "clear") {
            linhas = []
        } else if (op === "show") {
            mostrar(arg || "listening")
        } else if (op === "state") {
            definirEstado(arg || "listening")
        } else if (op === "level") {
            var v = arg.split(/\s+/)
            var lv = parseFloat(v[0])
            if (!isNaN(lv)) audio(lv, v.length > 1 ? parseFloat(v[1]) : null)
        } else if (op === "mic") {
            var m = parseFloat(arg.split(/\s+/)[0])
            if (!isNaN(m)) mic = lim01(m)
        } else if (op === "line") {
            empurrarLinha(arg)
            if (estado !== "tools" && estado !== "thinking") definirEstado("tools")
        } else if (op === "hold") {
            travado = ["", "0", "false", "off"].indexOf(arg) < 0
        } else if (op === "hide") {
            esconder()
        }
    }

    // ── um quadro ──
    function passo(dt) {
        dt = Math.min(Math.max(dt, 0), 0.05)
        var k = dt / 0.033
        if (fase === "in" || fase === "out") {
            faseT += dt
            if (fase === "in" && faseT >= 0.35) {
                fase = "run"
            } else if (fase === "out" && faseT >= 0.25) {
                fase = "run"
                visivel = false
                saiu()
            }
        }
        t += dt

        var m = {}
        for (var e in mix) m[e] = mix[e] + ((e === estado ? 1 : 0) - mix[e]) * fator(0.16, k)
        mix = m

        nivelS += (nivel - nivelS) * fator(nivel > nivelS ? 0.55 : 0.16, k)
        var alvo = toque ? 1 : 0
        toqueS += (alvo - toqueS) * fator(alvo > toqueS ? 0.45 : 0.20, k)
        tomS += (tom - tomS) * fator(0.25, k)
        micS += (mic - micS) * fator(mic > micS ? 0.50 : 0.20, k)

        var p, sc = 1, a = 1, desp = 1
        if (fase === "in") {
            p = Math.min(1, faseT / 0.35)
            sc = 0.45 + 0.55 * easeOutBack(p)
            a = Math.min(1, p * 2.2)
            desp = p
        } else if (fase === "out") {
            p = Math.min(1, faseT / 0.25)
            sc = 1 - 0.35 * p * p
            a = 1 - p
            desp = 1 - p
        }
        envEscBase = sc
        envEsc = sc * (1 + toqueCresce * toqueS)
        envAlfa = a

        var it = arte.item
        if (it) {
            if (avatar) it.desperto = desp
            it.avancar(dt)
        }

        if (estado !== "speaking") nivel *= Math.pow(0.90, k)
        mic *= Math.pow(0.90, k)
    }

    // ── arte ──
    Item {
        id: celula
        x: orbe.painel
        width: orbe.orbBox
        height: orbe.orbBox

        Loader {
            id: arte
            anchors.fill: parent
            sourceComponent: orbe.avatar ? compFigura : compAnel
        }
    }

    Component {
        id: compFigura
        Figura {
            skin: orbe.skin
            glitch: orbe.glitch
            peso: 1.4                       // o traço do menu some numa área de 148 px
            cor: orbe.corTema
            disco: orbe.vidro ? orbe.orbBox / 2 - 5 : -1
            zoom: orbe.envEsc
            alfa: orbe.envAlfa
            olharAlvo: orbe.olhar
            mix: orbe.mix
            sombraLigada: orbe.vidro
            sombraRaio: orbe.raioSombra
            sombraCor: orbe.corFundo
            voz: orbe.nivelS
            mic: orbe.micS
        }
    }

    Component {
        id: compAnel
        Anel {
            mix: orbe.mix
            sombraLigada: orbe.vidro
            sombraRaio: orbe.raioSombra
            sombraCor: orbe.corFundo
            estado: orbe.estado
            nivel: orbe.nivel
            nivelS: orbe.nivelS
            tomS: orbe.tomS
            mic: orbe.mic
            micS: orbe.micS
            envEsc: orbe.envEsc
            envAlfa: orbe.envAlfa
            esc: orbe.tamanho
            glitch: orbe.glitch
            accent: orbe.accent
        }
    }

    // ── sessão travada: ponto logo acima da figura, fora do giro, com respiro lento ──
    Item {
        id: ponto
        visible: orbe.travado
        readonly property real pulso: 0.62 + 0.38 * (0.5 + 0.5 * Math.sin(orbe.t * 2.0))
        readonly property color cor: orbe.avatar ? orbe.corTema : (arte.item ? arte.item.corAnel : orbe.accent)
        x: orbe.cx
        // a entidade enche a célula: o ponto não passa da borda de cima
        y: Math.max(5, orbe.cy - orbe.orbBox * (orbe.topo[orbe.skin] || 0.35) - 8)
        Rectangle {
            x: -6; y: -6; width: 12; height: 12; radius: 6
            color: Qt.rgba(ponto.cor.r, ponto.cor.g, ponto.cor.b, 0.22 * ponto.pulso * orbe.envAlfa)
        }
        Rectangle {
            x: -3; y: -3; width: 6; height: 6; radius: 3
            color: Qt.rgba(ponto.cor.r, ponto.cor.g, ponto.cor.b, 0.90 * ponto.pulso * orbe.envAlfa)
        }
    }

    // ── painel de texto: as últimas 5 linhas quebradas, a mais nova embaixo ──
    FontMetrics {
        id: fm
        font.family: "Sans"
        font.pixelSize: 11
    }
    // ao lado: coluna fixa à esquerda do orbe (não respira com o anel);
    // abaixo: coluna da largura da imagem (a célula de orbBox), sob o orbe
    readonly property real larguraTexto: textoAbaixo ? orbBox - 8 : cx - 66 * escala - 4
    readonly property real textoDireita: textoAbaixo ? cx + larguraTexto / 2 : cx - 66 * escala
    readonly property var linhasQuebradas: quebrar(linhas, larguraTexto)
    function quebrar(ls, larg) {
        var rows = []
        for (var i = 0; i < ls.length; i++) {
            var cur = ""
            var palavras = ls[i].split(" ")
            for (var j = 0; j < palavras.length; j++) {
                var wd = palavras[j]
                var cand = cur ? cur + " " + wd : wd
                if (fm.advanceWidth(cand) <= larg) { cur = cand; continue }
                if (cur) rows.push(cur)
                while (wd.length > 1 && fm.advanceWidth(wd) > larg) {
                    var n = wd.length - 1
                    while (n > 1 && fm.advanceWidth(wd.slice(0, n)) > larg) n--
                    rows.push(wd.slice(0, n))
                    wd = wd.slice(n)
                }
                cur = wd
            }
            if (cur) rows.push(cur)
        }
        return rows.slice(-5)
    }
    Item {
        id: texto
        visible: orbe.linhasQuebradas.length > 0 && orbe.envAlfa >= 0.5
        // a mais nova inteira e as mais antigas esmaecendo; abaixo, em degradê
        // até quase sumir no pé da figura
        readonly property var alfas: orbe.textoAbaixo ? [0.10, 0.24, 0.42, 0.66, 0.92]
                                                      : [0.16, 0.28, 0.42, 0.62, 0.92]
        Repeater {
            model: orbe.linhasQuebradas
            Text {
                readonly property int n: orbe.linhasQuebradas.length
                readonly property real a: texto.alfas[5 - n + index] * orbe.envAlfa
                text: modelData
                font: fm.font
                renderType: Text.NativeRendering
                color: Qt.rgba(0.88, 0.84, 0.92, a)
                // o texto fica direto sobre o que estiver atrás (janela, foto):
                // contorno no tom do fundo do tema para não sumir no claro
                style: Text.Outline
                styleColor: Qt.rgba(orbe.corFundo.r, orbe.corFundo.g, orbe.corFundo.b, 0.8 * a)
                x: Math.max(2, orbe.textoDireita - fm.advanceWidth(modelData))
                y: orbe.textoAbaixo ? orbe.yTexto + index * 17
                                    : orbe.cy - (n - 1) * 8.5 + index * 17 - fm.ascent
            }
        }
    }
}
