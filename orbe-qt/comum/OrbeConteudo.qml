import QtQuick

// Conteúdo do orbe de voz, sem nada de Quickshell, para rodar offscreen nos
// testes. Portado do Ring/OrbWin do orbe GTK antigo: fases de entrada e
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
    property bool glitch: true             // o comum (orbe.glitch)
    // o de cada skin (orbe.glitches; null = o comum): vale o do orbe em uso
    property var glitches: ({})
    function glitchDe(sk) {
        var g = glitches ? glitches[sk] : undefined
        return g === undefined || g === null ? glitch : !!g
    }
    readonly property bool glitchEmUso: glitchDe(skinEmUso)
    property bool vidro: false             // sombra atrás do orbe (chave antiga do config)
    property real sombra: 0.45             // opacidade da sombra no centro
    property real tamanho: 1.0             // o comum (orbe.tamanho)
    // o de cada skin (orbe.tamanhos): vale o do orbe em uso, que pode ser o do
    // relógio (espelho) ou o novo da rodinha; antes valia sempre o do orbe do
    // PC, e o Seraphim vindo do relógio aparecia no tamanho de outro
    property var tamanhos: ({})
    readonly property real tamanhoEmUso: {
        var t = tamanhos ? tamanhos[skinEmUso] : undefined
        t = t === undefined || t === null ? tamanho : parseFloat(t)
        return isNaN(t) ? 1.0 : Math.min(1.6, Math.max(0.6, t))
    }
    property string textoPos: "lado"       // lado | abaixo: onde fica o raciocínio
    property bool textoSombra: true        // a nuvem no tom do fundo atrás do texto
    property real textoSombraForca: 0.7    // a opacidade dela no meio (0.1 a 1.0)
    property string luasMovimento: "vagalumes"   // vagalumes | orbitas: como os outros orbes andam
    property bool luasLigadas: true        // os outros orbes como mini orbes em volta deste
    property bool luasSoAtivas: false      // só os com sessão ativa (sem os fantasmas)
    // desligadas no meio de uma troca, a lua do principal que saía não fica parada na tela
    onLuasLigadasChanged: if (!luasLigadas) luas.saindo = null
    property color corTema: "#b8cacb"      // @accent_bg_color: cor dos avatares
    property color accent: "#f3b2e3"       // --colorAccentBg: paleta do anel
    property color corFundo: "#121414"     // @window_bg_color: sombra e contorno do texto
    property color corOlhos: "transparent" // "olhos <cor>": íris em cor própria (a sessão do relógio)
    // "espelho <skin> <#cor|->": a sessão do relógio aparece com o orbe de lá,
    // a skin e a cor da instância ("-": as do tema); "espelho" volta ao daqui
    property string espelhoSkin: ""
    property color espelhoCor: "transparent"
    property var espelhoDepois: null       // a volta pedida no meio da saída: espera ela acabar
    readonly property string skinEmUso: espelhoSkin || skin
    readonly property color corFigura: espelhoCor.a > 0 ? espelhoCor : corTema
    readonly property color corAccent: espelhoCor.a > 0 ? espelhoCor : accent

    readonly property bool avatar: skinEmUso !== "anel"
    // as skins de imagem saem 5/3 maiores: o 60% do slider delas é o 100% das
    // outras (reduzida demais, a gravura perde a hachura)
    readonly property real escalaAlvo: tamanhoEmUso * (({ serafim_gravura: 1, serafim_positivo: 1, olho: 1, humana: 1 })[skinEmUso] ? 5 / 3 : 1)
    // na troca do principal a célula cresce ou encolhe junto com a animação
    // (de uma gravura para um desenhado ela muda 5/3); fora dela, a do alvo
    property real escalaTroca: -1
    property real escalaDe: 1
    readonly property real escala: escalaTroca > 0 ? escalaTroca : escalaAlvo
    // ART_BOX é o tamanho visual da arte; ORB_BOX, a célula reservada para ela
    readonly property int orbBox: Math.round(148 * escala)
    readonly property int artBox: Math.round(120 * escala)
    readonly property int painel: 296      // coluna de texto: o raciocínio legível
    readonly property real cx: painel + orbBox / 2
    readonly property real cy: orbBox / 2
    readonly property bool textoAbaixo: textoPos === "abaixo"
    // abaixo, o texto começa onde a figura termina (medido nos renders, em
    // fração da célula a partir do centro): a linha mais antiga some ali
    readonly property var pes: ({ ofanim: 0.39, ofanim_alado: 0.29, serafim_gravura: 0.38, serafim_positivo: 0.38, olho: 0.46, humana: 0.43, anel: 0.35 })
    readonly property real yTexto: Math.round(cy + orbBox * (pes[skinEmUso] || 0.35))
    // topo da figura acima do centro, em fração da célula (medido nos renders,
    // na coluna do meio, ouvindo e parada): o ponto da sessão travada fica
    // logo acima dele, perto da figura e longe da borda de cima da tela
    readonly property var topo: ({ ofanim: 0.345, ofanim_alado: 0.277, serafim_gravura: 0.355, serafim_positivo: 0.355, olho: 0.38, humana: 0.40, anel: 0.412 })
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
    // os outros orbes (Satelites.qml): [{ id, skin, cor, tipo: ativo | fantasma | espera }]
    property var satelites: []
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
    // uma troca esperando o fim da saída: feita já (a fase segue a pedida)
    function concluirTroca() {
        if (!trocaPendente) return
        var f = trocaPendente
        trocaPendente = null
        f()
    }
    function mostrar(e) {
        concluirTroca()
        aplicarEspelho()
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
        concluirTroca()             // a saída da troca vira a saída de esconder
        // já saindo, a saída termina (encolhendo): o atalho de desativar manda
        // "hide" duas vezes seguidas (_kill_active e _end_session no daemon), e
        // o segundo sumia com o orbe na hora, sem a animação
        if (visivel && fase !== "out") {
            fase = "out"
            faseT = 0
        }
    }
    function espelhar(arg) {
        var v = arg.split(/\s+/)
        var sk = ["ofanim", "ofanim_alado", "serafim_gravura", "serafim_positivo", "olho", "humana", "anel"].indexOf(v[0]) >= 0 ? v[0] : ""
        var e = { skin: sk, cor: sk && /^#[0-9a-fA-F]{6}$/.test(v[1] || "") ? v[1] : "transparent" }
        espelhoDepois = e
        if (!(visivel && fase === "out")) aplicarEspelho()
    }
    function aplicarEspelho() {
        if (!espelhoDepois) return
        var novo = espelhoDepois
        espelhoDepois = null
        var de = { skin: skinEmUso, cor: espelhoCor.a > 0 ? espelhoCor.toString() : "" }
        var para = { skin: novo.skin || skin, cor: novo.cor !== "transparent" && novo.cor ? String(novo.cor) : "" }
        trocarPrincipal(de, para, function () {
            espelhoSkin = novo.skin
            espelhoCor = novo.cor
        })
    }
    // "base <skin>": o orbe do PC passou a outro (a rodinha em cima dele). Com o
    // PC mostrando o dele, troca de lugar com a lua como no espelho; mostrando o
    // do relógio, só guarda (o "espelho" de volta, que vem depois, anima)
    function trocarBase(sk) {
        if (["ofanim", "ofanim_alado", "serafim_gravura", "serafim_positivo", "olho", "humana", "anel"].indexOf(sk) < 0 || sk === skin) return
        if (espelhoSkin) { skin = sk; return }
        trocarPrincipal({ skin: skin, cor: "" }, { skin: sk, cor: "" }, function () { skin = sk })
    }
    // a troca do principal de [de] para [para]: [aplicar] faz a troca de fato
    // (a skin passa nela); antes, a lua do que sai e a partida do que chega
    // sem lua para trocar de lugar: o orbe sai como ao desativar e volta já o
    // outro, como ao ativar (o Meta+A); a troca de fato fica para o fim da saída
    property var trocaPendente: null
    function trocarPrincipal(de, para, aplicar) {
        var o = null
        var muda = de.skin !== para.skin || de.cor.toLowerCase() !== para.cor.toLowerCase()
        if (muda && visivel && fase === "run" && !(luas.lista.length && luasLigadas)) {
            trocaPendente = aplicar
            fase = "out"
            faseT = 0
            return
        }
        // com o orbe na tela e satélites em volta, os dois trocam de lugar: o
        // chamado sai de onde estava crescendo até o centro, e o principal
        // encolhe indo para onde o chamado estava (Satelites.trocar)
        if (muda && visivel && fase === "run" && luas.lista.length && luasLigadas) {
            o = luas.onde(para.skin, para.cor)
            // a lua do que sai começa do tamanho visível dele: o raio da figura
            // dele aqui (com a sombra, cabe no disco) sobre o raio na caixa de lua
            var s0 = -1
            if (avatar && arte.item && arte.item.raioQueCabe) {
                var rLua = arte.item.raioQueCabe(luas.tamanho, luas.tamanho, -1)
                if (rLua > 0) s0 = arte.item.raioQueCabe(arte.width, arte.height, arte.item.disco) / rLua
            }
            luas.trocar(de, o, avatar && arte.item ? arte.item.st : null, mix, s0)
            // o chamado chega no estado que tinha de lua e vai ao de agora pelo
            // passo, como qualquer mudança de estado
            mix = o && o.tipo === "espera" ? ({ idle: 0, listening: 0, thinking: 0, tools: 0, speaking: 1 })
                                           : ({ idle: 1, listening: 0, thinking: 0, tools: 0, speaking: 0 })
            trocaDe = o ? o : { x: 0, y: 0, s: 0.3 }
            escalaDe = escala
            escalaTroca = escala
            trocaT = 0
        }
        aplicar()
        // o chamado chega com a pose que tinha de lua (a Figura do principal é a
        // mesma; trocar de skin zerou o estado dela)
        if (o && o.id && luas.estados[o.id] && avatar && arte.item && arte.item.st !== undefined)
            arte.item.st = luas.estados[o.id]
        // e do tamanho visível que tinha: o raio da figura na caixa de lua sobre o
        // raio dela aqui (a célula ainda é a de antes; ela cresce com a troca)
        if (o && avatar && arte.item && arte.item.raioQueCabe) {
            var rAqui = arte.item.raioQueCabe(arte.width, arte.height, arte.item.disco)
            if (rAqui > 0)
                trocaDe = { x: o.x, y: o.y, a: o.a, id: o.id, tipo: o.tipo,
                            s: arte.item.raioQueCabe(o.s * orbBox, o.s * orbBox, -1) / rAqui }
        }
    }
    // a troca do principal: de onde o chamado estava (x, y a partir do centro, escala) até o centro
    property var trocaDe: ({ x: 0, y: 0, s: 1 })
    property real trocaT: 99               // segundos desde a troca (anda no passo, como o resto)
    // devagar no começo e no fim, sem passar do ponto: o mesmo tempo e a mesma
    // curva da lua que sai (Satelites.duracao, Satelites.suave)
    readonly property real trocaF: luas.suave(trocaT / luas.duracao)
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
        } else if (op === "olhos") {
            corOlhos = /^#[0-9a-fA-F]{6}$/.test(arg) ? arg : "transparent"
        } else if (op === "espelho") {
            espelhar(arg)
        } else if (op === "base") {
            trocarBase(arg.trim())
        } else if (op === "satelites") {
            try {
                var l = JSON.parse(arg || "[]")
                satelites = Array.isArray(l) ? l.filter(function (e) { return e && e.id !== undefined && e.skin }) : []
            } catch (err) {
                satelites = []
            }
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
                if (trocaPendente) {
                    // a saída era de uma troca: volta já o outro, entrando
                    concluirTroca()
                    fase = "in"
                    faseT = 0
                    aplicarEspelho()
                } else {
                    fase = "run"
                    visivel = false
                    aplicarEspelho()
                    saiu()
                }
            }
        }
        t += dt
        if (trocaT < luas.duracao) {
            trocaT += dt
            escalaTroca = trocaT < luas.duracao ? escalaDe + (escalaAlvo - escalaDe) * trocaF : -1
        }
        if (luasLigadas && (satelites.length || luas.saindo)) luas.passo(dt)

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

        // os outros orbes em volta deste: a arte é irmã deles, para as luas
        // passarem por trás e pela frente dela
        Satelites {
            id: luas
            anchors.fill: parent
            lado: orbe.orbBox
            lista: !orbe.luasLigadas ? []
                 : orbe.luasSoAtivas ? orbe.satelites.filter(function (e) { return e.tipo !== "fantasma" })
                 : orbe.satelites
            movimento: orbe.luasMovimento
            corTema: orbe.corTema
            corAnel: orbe.accent
            glitchDe: orbe.glitchDe
            alfa: orbe.envAlfa

            Loader {
                id: arte
                anchors.fill: parent
                z: 0
                sourceComponent: orbe.avatar ? compFigura : compAnel
                // o chamado chega com o brilho que tinha de lua e acende até o de principal
                opacity: orbe.trocaDe.a === undefined ? 1 : orbe.trocaDe.a + (1 - orbe.trocaDe.a) * orbe.trocaF
                transform: [
                    Scale {
                        origin.x: arte.width / 2; origin.y: arte.height / 2
                        xScale: orbe.trocaDe.s + (1 - orbe.trocaDe.s) * orbe.trocaF
                        yScale: xScale
                    },
                    Translate { x: orbe.trocaDe.x * (1 - orbe.trocaF); y: orbe.trocaDe.y * (1 - orbe.trocaF) }
                ]
            }
        }
    }

    Component {
        id: compFigura
        Figura {
            skin: orbe.skinEmUso
            glitch: orbe.glitchEmUso
            glitchForca: orbe.trocaF
            peso: 1.4                       // o traço do menu some numa área de 148 px
            cor: orbe.corFigura
            corOlhos: orbe.corOlhos
            disco: orbe.vidro ? orbe.orbBox / 2 - 5 : -1
            zoom: orbe.envEsc
            alfa: orbe.envAlfa
            olharAlvo: orbe.olhar
            mix: orbe.mix
            sombraLigada: orbe.vidro
            sombraRaio: orbe.raioSombra
            sombraAlfa: orbe.sombra
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
            sombraAlfa: orbe.sombra
            sombraCor: orbe.corFundo
            estado: orbe.estado
            nivel: orbe.nivel
            nivelS: orbe.nivelS
            tomS: orbe.tomS
            mic: orbe.mic
            micS: orbe.micS
            envEsc: orbe.envEsc
            envAlfa: orbe.envAlfa
            esc: orbe.tamanhoEmUso
            glitch: orbe.glitchEmUso
            accent: orbe.corAccent
        }
    }

    // ── sessão travada: ponto logo acima da figura, fora do giro, com respiro lento ──
    Item {
        id: ponto
        visible: orbe.travado
        readonly property real pulso: 0.62 + 0.38 * (0.5 + 0.5 * Math.sin(orbe.t * 2.0))
        readonly property color cor: orbe.avatar ? orbe.corFigura : (arte.item ? arte.item.corAnel : orbe.corAccent)
        x: orbe.cx
        // o ponto não passa da borda de cima
        y: Math.max(5, orbe.cy - orbe.orbBox * (orbe.topo[orbe.skinEmUso] || 0.35) - 8)
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
        function xLinha(l) { return Math.max(2, orbe.textoDireita - fm.advanceWidth(l)) }
        function yLinha(i, n) {
            return orbe.textoAbaixo ? orbe.yTexto + i * 17 : orbe.cy - (n - 1) * 8.5 + i * 17 - fm.ascent
        }
        // sombra atrás do texto, opcional (config: orbe.texto_sombra e a
        // intensidade em orbe.texto_sombra_forca): uma nuvem macia em volta do
        // bloco de linhas, para o texto destacar das janelas que estiverem atrás
        // (shaders/nuvem.frag)
        ShaderEffect {
            id: sombraTexto
            visible: orbe.textoSombra && orbe.textoSombraForca > 0
            x: 0; y: 0
            width: orbe.width; height: orbe.height
            fragmentShader: Qt.resolvedUrl("../shaders/nuvem.frag.qsb")
            readonly property var bloco: {
                var ls = orbe.linhasQuebradas, n = ls.length
                if (!n) return [0, 0, 0, 0]
                var x0 = 1e9, x1 = 0
                for (var i = 0; i < n; i++) {
                    var xl = texto.xLinha(ls[i])
                    x0 = Math.min(x0, xl)
                    x1 = Math.max(x1, xl + fm.advanceWidth(ls[i]))
                }
                return [x0 - 4, texto.yLinha(0, n) - 1, x1 + 4, texto.yLinha(n - 1, n) + fm.height + 1]
            }
            property vector2d tam: Qt.vector2d(width, height)
            property vector4d caixa: Qt.vector4d(bloco[0], bloco[1], bloco[2], bloco[3])
            property vector4d cor: Qt.vector4d(orbe.corFundo.r, orbe.corFundo.g, orbe.corFundo.b,
                                               orbe.textoSombraForca * orbe.envAlfa)
            // esmaecimento de 24 px para fora, cantos de 10 px; as linhas longas
            // encostam na borda da janela, e ali a nuvem vai a zero em 24 px
            // (em 10 ficava uma quina)
            property vector4d forma: Qt.vector4d(24, 10, 24, 0)
        }
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
                x: texto.xLinha(modelData)
                y: texto.yLinha(index, n)
            }
        }
    }
}
