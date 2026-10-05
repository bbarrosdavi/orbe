import QtQuick
import Quickshell
import Quickshell.Io
import Quickshell.Wayland
import "comum"

// Orbe de voz do Hermes no Quickshell (substituiu o hermes_voice_orb.py em GTK em 2026-10-04).
//
// Mesmo protocolo e mesmos sockets do orbe GTK. O daemon fala por
// $XDG_RUNTIME_DIR/hermes-voice-orb.sock (show, state, level, mic, line,
// hold, hide, clear, olhos, warm, quit) e o toque vai para hermes-voice-ctl.sock
// (touch down / touch up). O desenho roda na GPU (Figura/Anel), a animação
// anda no vsync da janela e para quando o orbe some.
ShellRoot {
    id: raiz

    readonly property string runtime: Quickshell.env("XDG_RUNTIME_DIR")
    readonly property string home: Quickshell.env("HOME")
    // ajudante do ponteiro na pasta acima desta, onde quer que ela esteja
    // (no arquivo raiz o Qt.resolvedUrl do Quickshell dá qrc:/qs-blackhole)
    readonly property string ponteiroPy: Quickshell.shellPath("../hermes_voice_ponteiro.py")
    // sobrescrevíveis para uma instância ao lado do orbe em uso (teste e a
    // pré-visualização do app, que aponta o config para um arquivo próprio)
    readonly property string sockOrbe: Quickshell.env("HERMES_ORB_SOCK") || runtime + "/hermes-voice-orb.sock"
    readonly property string sockCtl: Quickshell.env("HERMES_CTL_SOCK") || runtime + "/hermes-voice-ctl.sock"
    readonly property string arqConfig: Quickshell.env("HERMES_ORB_CONFIG") || home + "/.config/hermes-voice/config.json"
    readonly property var tela: {
        var ts = Quickshell.screens
        for (var i = 0; i < ts.length; i++)
            if (ts[i].name === "eDP-1") return ts[i]
        return ts.length ? ts[0] : null
    }

    // ── configuração e cores do tema ──
    function lerConfig(texto) {
        var o = {}
        try { o = (JSON.parse(texto) || {}).orbe || {} } catch (e) { o = {} }
        // o Seraphim desenhado saiu; quem o tinha fica com o da gravura
        conteudo.skin = o.skin === "serafim" ? "serafim_gravura" : String(o.skin || "ofanim")
        conteudo.glitch = o.glitch === undefined ? true : !!o.glitch
        conteudo.vidro = !!o.vidro
        var tam = parseFloat(o.tamanho)
        conteudo.tamanho = isNaN(tam) ? 1.0 : Math.min(1.6, Math.max(0.6, tam))
        conteudo.textoPos = o.texto === "abaixo" ? "abaixo" : "lado"
        raiz.mover = !!o.mover
    }
    function corCss(texto, re, padrao) {
        var m = re.exec(texto || "")
        return m ? "#" + m[1] : padrao
    }

    FileView {
        path: raiz.arqConfig
        watchChanges: true
        printErrors: false
        onFileChanged: reload()
        onLoaded: raiz.lerConfig(text())
        onLoadFailed: raiz.lerConfig("")
    }
    // ── posição: travado (padrão), o orbe fica onde está, no canto se nunca
    //    foi movido; destravado, arrastar move. Só o orbe de verdade lembra a
    //    posição (a prévia do app e os testes ficam no canto) ──
    property bool mover: false
    property real margemX: 0               // distância da borda direita
    property real margemY: 0               // distância do topo
    readonly property bool lembraPosicao: !Quickshell.env("HERMES_ORB_SOCK")
    function limitar() {
        if (!tela) return
        margemX = Math.max(0, Math.min(tela.width - janela.width, margemX))
        margemY = Math.max(0, Math.min(tela.height - janela.height, margemY))
    }
    FileView {
        id: arqPosicao
        path: raiz.lembraPosicao ? raiz.home + "/.config/hermes-voice/orbe-posicao.json" : ""
        printErrors: false
        atomicWrites: true
        onLoaded: {
            try {
                var o = JSON.parse(text()) || {}
                raiz.margemX = parseFloat(o.x) || 0
                raiz.margemY = parseFloat(o.y) || 0
                raiz.limitar()
            } catch (e) {}
        }
    }
    function salvarPosicao() {
        if (lembraPosicao)
            arqPosicao.setText(JSON.stringify({ x: Math.round(margemX), y: Math.round(margemY) }) + "\n")
    }

    FileView {
        // @accent_bg_color (avatares) e @window_bg_color (sombra e texto), do matugen
        path: raiz.home + "/.config/gtk-4.0/dank-colors.css"
        watchChanges: true
        printErrors: false
        onFileChanged: reload()
        onLoaded: {
            conteudo.corTema = raiz.corCss(text(), /@define-color\s+accent_bg_color\s+#([0-9a-fA-F]{6})/, "#b8cacb")
            conteudo.corFundo = raiz.corCss(text(), /@define-color\s+window_bg_color\s+#([0-9a-fA-F]{6})/, "#121414")
        }
    }
    FileView {
        // accent da paleta do anel, o mesmo do _system_palette
        path: raiz.home + "/Projetos/Docs_rice_sistema/main.css"
        watchChanges: true
        printErrors: false
        onFileChanged: reload()
        onLoaded: conteudo.accent = raiz.corCss(text(), /--colorAccentBg:\s*#([0-9a-fA-F]{6})/, "#0087fc")
    }

    // ── socket do daemon ──
    property int conexoes: 0
    SocketServer {
        id: servidor
        active: true
        path: raiz.sockOrbe
        handler: Socket {
            Component.onCompleted: raiz.conexoes++
            parser: SplitParser {
                onRead: linha => raiz.comando(linha)
            }
        }
    }
    function comando(linha) {
        if (linha.trim() === "quit") {
            Qt.quit()
            return
        }
        conteudo.comando(linha)
    }
    // O Quickshell 0.3 só solta o objeto de cada conexão quando o servidor
    // desliga. O daemon mantém uma conexão só, mas cliente avulso (orb_control)
    // abre uma por mensagem: com o orbe escondido, recicla o servidor.
    function reciclar() {
        if (conexoes < 200) return
        servidor.active = false
        servidor.active = true
        conexoes = 0
    }

    // ── toque: uma conexão por mensagem, como o daemon espera (lê até EOF) ──
    Socket {
        id: ctl
        path: raiz.sockCtl
        property var fila: []
        onConnectionStateChanged: {
            if (connected) {
                write(fila.join(""))
                fila = []
                flush()
                connected = false
            } else if (fila.length) {
                connected = true
            }
        }
        onError: fila = []
        function enviar(msg) {
            fila = fila.concat([msg + "\n"])
            if (!connected) connected = true
        }
    }
    function tocar(dentro) {
        if (dentro === conteudo.toque) return
        conteudo.toque = dentro
        ctl.enviar(dentro ? "touch down" : "touch up")
    }

    // ── olhar: sobre o orbe a posição é exata (e vira âncora); fora, vem do
    //    hermes_voice_ponteiro (evdev), só enquanto o orbe está na tela ──
    property var olharLocal: null
    property var olharGlobal: null
    readonly property real origemX: tela ? tela.x + tela.width - janela.width - margemX : 0
    readonly property real origemY: tela ? tela.y + margemY : 0
    Process {
        id: ponteiro
        running: janela.visible && conteudo.avatar
        command: ["/usr/bin/python3", raiz.ponteiroPy, "--stdio"]
        stdinEnabled: true
        stdout: SplitParser {
            onRead: linha => {
                var v = linha.split(" ")
                if (v.length < 2) return
                raiz.olharGlobal = Qt.point(parseFloat(v[0]) - raiz.origemX - conteudo.painel,
                                            parseFloat(v[1]) - raiz.origemY)
            }
        }
        onRunningChanged: if (!running) raiz.olharGlobal = null
    }

    PanelWindow {
        id: janela
        screen: raiz.tela
        visible: conteudo.visivel
        color: "transparent"
        anchors.top: true
        anchors.right: true
        margins.top: raiz.margemY
        margins.right: raiz.margemX
        implicitWidth: conteudo.width
        implicitHeight: conteudo.height
        exclusionMode: ExclusionMode.Normal
        exclusiveZone: 0
        WlrLayershell.layer: WlrLayer.Overlay
        WlrLayershell.namespace: "hermes-voice-orb"
        WlrLayershell.keyboardFocus: WlrKeyboardFocus.None

        // só o quadrado da arte recebe toque; a coluna de texto deixa passar
        mask: Region { item: alvo }

        OrbeConteudo {
            id: conteudo
            olhar: raiz.olharLocal !== null ? raiz.olharLocal : raiz.olharGlobal
            onSaiu: raiz.reciclar()
        }

        Item {
            id: alvo
            x: conteudo.cx - width / 2
            y: conteudo.cy - height / 2
            width: conteudo.artBox
            height: conteudo.artBox
            MouseArea {
                id: area
                anchors.fill: parent
                hoverEnabled: true
                // destravado, o toque só vai ao daemon quando fica claro que
                // não é arrasto: solto antes de andar, toque curto; parado
                // além do tempo de segurar, segurar para falar
                property point inicio
                property bool arrastando: false
                // a margem nova só vale no próximo commit da superfície; até lá
                // os eventos ainda vêm na posição velha e somariam o mesmo
                // deslocamento de novo (1 cm de dedo mandava o orbe ao outro lado)
                property bool assentando: false
                Timer {
                    id: assentar
                    interval: 50
                    onTriggered: area.assentando = false
                }
                Timer {
                    id: segurar
                    interval: 350
                    onTriggered: if (area.pressed && !area.arrastando) raiz.tocar(true)
                }
                onPressed: mouse => {
                    if (!raiz.mover) { raiz.tocar(true); return }
                    inicio = Qt.point(mouse.x, mouse.y)
                    arrastando = false
                    assentando = false
                    segurar.restart()
                }
                onReleased: {
                    if (!raiz.mover) { raiz.tocar(false); return }
                    segurar.stop()
                    if (arrastando) {
                        arrastando = false
                        raiz.salvarPosicao()
                    } else if (conteudo.toque) {
                        raiz.tocar(false)
                    } else {
                        raiz.tocar(true)
                        raiz.tocar(false)
                    }
                }
                onCanceled: {
                    segurar.stop()
                    if (arrastando) raiz.salvarPosicao()
                    arrastando = false
                    raiz.tocar(false)
                }
                onPositionChanged: mouse => {
                    if (raiz.mover && pressed && !conteudo.toque) {
                        var dx = mouse.x - inicio.x, dy = mouse.y - inicio.y
                        if (!arrastando && dx * dx + dy * dy > 36) {
                            arrastando = true
                            segurar.stop()
                        }
                        if (arrastando) {
                            // a janela anda com o dedo, e o ponto tocado volta
                            // para baixo dele: o delta é sempre desde o início,
                            // contado depois que a janela assentou na margem
                            if (assentando) return
                            raiz.margemX -= dx
                            raiz.margemY += dy
                            raiz.limitar()
                            assentando = true
                            assentar.restart()
                            return
                        }
                    }
                    var x = mouse.x + alvo.x, y = mouse.y + alvo.y
                    raiz.olharLocal = Qt.point(x - conteudo.painel, y)
                    if (ponteiro.running)
                        ponteiro.write("ancora " + (raiz.origemX + x).toFixed(1) + " " + (raiz.origemY + y).toFixed(1) + "\n")
                }
                onExited: raiz.olharLocal = null
            }
        }

        FrameAnimation {
            running: janela.visible
            onTriggered: conteudo.passo(frameTime)
        }
    }
}
