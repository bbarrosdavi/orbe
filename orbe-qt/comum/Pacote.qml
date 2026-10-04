import QtQuick

// Skin por pacote de camadas: a arte vem de PNGs (gerados fora, por quem
// quiser, inclusive outro modelo) e o orbe anima cada camada. A cor, o
// glitch, o vidro e a entrada/saída são os mesmos dos avatares (pos.frag),
// então um pacote se comporta como qualquer skin.
//
// Pasta do pacote: <skins>/<nome>/skin.json + PNGs. Também vale um PNG
// solto <skins>/<nome>.png (uma camada só, com pulso).
//
//   {
//     "nome": "Seraphim ilustrado",
//     "quadro": 1024,          // lado do quadro em que todas as camadas estão
//     "escala": 0.95,          // fração da célula que o quadro ocupa (opcional)
//     "camadas": [             // de trás para a frente
//       {"arquivo": "asa_cima_esq.png", "anim": "bater",
//        "pivo": [512, 470], "lado": -1, "amplitude": 10, "fase": 0.0},
//       {"arquivo": "chamas.png",       "anim": "pulsar",   "amplitude": 0.06},
//       {"arquivo": "fundo.png",        "anim": "respirar"},
//       {"arquivo": "olho_branco.png"},                       // fixa
//       {"arquivo": "olho_iris.png",    "anim": "olhar",
//        "mascara": "olho_branco.png", "alcance": 36}
//     ]
//   }
//
// Os PNGs são RGBA com fundo transparente, todos no mesmo quadro; só a forma
// (alfa) importa, a cor vem do tema. Não existe "preto": um elemento dentro
// de outro (o olho num disco) precisa de furo ou de alfa baixo no de baixo,
// senão branco sobre branco some. Animações: `bater` gira no pivô (px do
// quadro) com a frequência do estado e a voz; `pulsar` escala com a voz;
// `respirar` escala devagar; `olhar` desloca a camada na direção do olhar,
// recortada pela máscara; sem `anim`, fica parada.
Item {
    id: raiz

    property url dir                        // pasta do pacote (file://...)
    property var manifesto: ({})            // conteúdo do skin.json
    property bool glitch: true
    property color cor: "white"
    property real zoom: 1.0
    property real alfa: 1.0
    property var olharAlvo: null
    property var mix: ({ idle: 1.0 })
    property real voz: 0
    property real mic: 0
    property real desperto: 1

    property bool vidroLigado: false
    property real vidroRaio: 0
    property real vidroAlfa: 0.58
    property real vidroInicio: 0.30
    property color vidroCor: "#121414"

    readonly property var camadas: (manifesto && manifesto.camadas) ? manifesto.camadas : []
    readonly property real quadro: (manifesto && manifesto.quadro > 0) ? manifesto.quadro : 1024
    readonly property real escala: (manifesto && manifesto.escala > 0) ? manifesto.escala : 0.95
    // lado do quadro na tela
    readonly property real lado: Math.min(width, height) * escala * zoom * suave(desperto)
    readonly property real k: lado / quadro
    readonly property real cx: width / 2
    readonly property real cy: height / 2

    // ── estado por quadro ──
    property real t: 0
    property real faseAsa: 0
    property real respiro: 0
    property real pulso: 0
    property real olharX: 0
    property real olharY: 0
    property vector4d _glt
    property vector4d _geo2
    property var st: ({ glitchAte: 0, proxGlitch: 1.2 })

    function p(e) { return mix[e] || 0 }
    function mistura(v) {
        var tot = 0, acc = 0
        for (var e in mix) { tot += mix[e]; acc += mix[e] * (v[e] !== undefined ? v[e] : 0) }
        if (tot <= 0) return v.idle !== undefined ? v.idle : 0
        return acc / tot
    }
    function suave(x) { x = Math.min(1, Math.max(0, x)); return x * x * (3 - 2 * x) }
    function uni(a, b) { return a + Math.random() * (b - a) }
    function ruido(t, s) {
        return Math.sin(t * 1.31 + s) * 0.5 + Math.sin(t * 2.17 + s * 1.7) * 0.3 + Math.sin(t * 0.53 + s * 2.9) * 0.2
    }
    function v4(a, b, c, d) { return Qt.vector4d(a, b, c, d) }

    function avancar(dt) {
        t += dt
        var falar = p("speaking") * voz
        // batida das asas: a mesma tabela do Ophanim com asas
        faseAsa += dt * 2 * Math.PI * (mistura({ idle: 0.3, listening: 0.3, thinking: 2.2, tools: 1.4, speaking: 1.2 }) + 0.8 * falar)
        respiro = Math.sin(t * 1.1)
        var alvoPulso = 0.5 * voz + 0.25 * mic * p("listening")
        pulso += (alvoPulso - pulso) * Math.min(1, dt * 12)

        // olhar: para o alvo, ou vagando devagar
        var gx, gy
        if (olharAlvo) { gx = olharAlvo.x - cx; gy = olharAlvo.y - cy }
        else { gx = ruido(t * 0.6, 3) * lado * 0.6; gy = ruido(t * 0.5, 9) * lado * 0.35 }
        var gl = Math.hypot(gx, gy)
        var foco = mistura({ idle: 0.3, listening: 1.0, thinking: 0.2, tools: 0.55, speaking: 0.85 })
        var nx = gl > 1e-3 ? gx / gl : 0, ny = gl > 1e-3 ? gy / gl : 0
        var mag = Math.min(1, gl / (lado * 0.5)) * (0.5 + 0.5 * foco)
        olharX += (nx * mag - olharX) * Math.min(1, dt * 6)
        olharY += (ny * mag - olharY) * Math.min(1, dt * 6)

        // rajadas de glitch, como na Figura
        var rajada = false, sep = 0
        var kk = lado / 164
        if (glitch) {
            var agit = Math.min(1, p("thinking") + 0.6 * p("tools"))
            if (t >= st.proxGlitch) {
                st.glitchAte = t + uni(0.08, 0.28)
                st.proxGlitch = t + uni(0.9, 3.6) / (1 + 3 * agit)
            }
            rajada = t < st.glitchAte
            sep = (rajada ? uni(2.5, 6.0) : 0.8 + 0.5 * Math.abs(ruido(t, 1))) * Math.max(0.6, kk)
        }
        _glt = v4(sep, rajada ? 1 : 0, rajada ? Math.random() * 1000 : 0, kk)
        _geo2 = v4(lado * 0.4, Math.min(width, height) / 2 - 1, (t * 18) % 3, glitch ? 1 : 0)
    }

    // ── camadas ──
    Item {
        id: quadroItem
        x: raiz.cx - raiz.lado / 2
        y: raiz.cy - raiz.lado / 2
        width: raiz.lado
        height: raiz.lado
        Repeater {
            model: raiz.camadas
            delegate: Item {
                id: camada
                anchors.fill: parent
                readonly property var c: modelData
                readonly property string anim: c.anim || "fixa"
                readonly property real amp: c.amplitude !== undefined ? c.amplitude
                                          : (anim === "bater" ? 10 : anim === "pulsar" ? 0.06 : 0.015)
                readonly property real ladoAsa: c.lado !== undefined ? c.lado : 1
                readonly property real fase0: c.fase || 0
                readonly property real alcance: (c.alcance !== undefined ? c.alcance : 30) * raiz.k
                readonly property real px: c.pivo ? c.pivo[0] * raiz.k : width / 2
                readonly property real py: c.pivo ? c.pivo[1] * raiz.k : height / 2

                Image {
                    id: img
                    anchors.fill: parent
                    source: raiz.dir + "/" + camada.c.arquivo
                    sourceSize: Qt.size(raiz.quadro, raiz.quadro)
                    smooth: true
                    mipmap: true
                    visible: camada.anim !== "olhar"
                    transform: [
                        Rotation {
                            origin.x: camada.px; origin.y: camada.py
                            angle: camada.anim === "bater"
                                   ? camada.amp * camada.ladoAsa * Math.sin(raiz.faseAsa + camada.fase0) : 0
                        },
                        Scale {
                            origin.x: camada.px; origin.y: camada.py
                            xScale: camada.anim === "pulsar" ? 1 + camada.amp * raiz.pulso
                                  : camada.anim === "respirar" ? 1 + camada.amp * raiz.respiro : 1
                            yScale: xScale
                        }
                    ]
                }
                // olhar: a camada desloca e a máscara recorta
                Image {
                    id: masc
                    anchors.fill: parent
                    visible: false
                    source: camada.anim === "olhar" && camada.c.mascara ? raiz.dir + "/" + camada.c.mascara : ""
                    sourceSize: Qt.size(raiz.quadro, raiz.quadro)
                    smooth: true
                    mipmap: true
                }
                ShaderEffect {
                    anchors.fill: parent
                    visible: camada.anim === "olhar"
                    fragmentShader: Qt.resolvedUrl("../shaders/mascara.frag.qsb")
                    property variant source: img
                    property variant mascara: masc
                    property vector2d desloc: Qt.vector2d(raiz.olharX * camada.alcance / Math.max(1, width),
                                                          raiz.olharY * camada.alcance / Math.max(1, height))
                    property real usaMascara: camada.c.mascara ? 1 : 0
                }
            }
        }
    }

    // ── cor, glitch e vidro: o mesmo passe dos avatares ──
    layer.enabled: true
    layer.effect: ShaderEffect {
        fragmentShader: Qt.resolvedUrl("../shaders/pos.frag.qsb")
        property vector2d tam: Qt.vector2d(raiz.width, raiz.height)
        property vector2d centro: Qt.vector2d(raiz.cx, raiz.cy)
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
