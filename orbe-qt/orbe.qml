import QtQuick
import Quickshell
import Quickshell.Io
import Quickshell.Wayland
import "comum"
import "orbe"

// Orbe de voz do Hermes no Quickshell: substitui o hermes_voice_orb.py.
//
// Mesmo protocolo e mesmos sockets do orbe GTK. O daemon fala por
// $XDG_RUNTIME_DIR/hermes-voice-orb.sock (show, state, level, mic, line,
// hold, hide, clear, warm, quit) e o toque vai para hermes-voice-ctl.sock
// (touch down / touch up). O desenho roda na GPU (Figura/Anel), a animação
// anda no vsync da janela e para quando o orbe some.
ShellRoot {
    id: raiz

    readonly property string runtime: Quickshell.env("XDG_RUNTIME_DIR") || "/run/user/1000"
    readonly property string home: Quickshell.env("HOME") || "/home/davi"
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
        conteudo.skin = String(o.skin || "ofanim")
        conteudo.glitch = o.glitch === undefined ? true : !!o.glitch
        conteudo.vidro = !!o.vidro
        var tam = parseFloat(o.tamanho)
        conteudo.tamanho = isNaN(tam) ? 1.0 : Math.min(1.6, Math.max(0.6, tam))
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
    FileView {
        // @accent_bg_color (avatares) e @window_bg_color (vidro), do matugen
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
    readonly property real origemX: tela ? tela.x + tela.width - janela.width : 0
    readonly property real origemY: tela ? tela.y : 0
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
        implicitWidth: conteudo.width
        implicitHeight: conteudo.height
        exclusionMode: ExclusionMode.Normal
        exclusiveZone: 0
        WlrLayershell.layer: WlrLayer.Overlay
        WlrLayershell.namespace: "hermes-voice-orb"
        WlrLayershell.keyboardFocus: WlrKeyboardFocus.None

        // só o quadrado da arte recebe toque; a coluna de texto deixa passar
        mask: Region { item: alvo }

        BackgroundEffect.blurRegion: conteudo.vidro && conteudo.raioVidro > 1 ? desfoque : null
        VidroRegiao {
            id: desfoque
            cx: conteudo.cx
            cy: conteudo.cy
            raio: conteudo.raioVidro
            raioMax: conteudo.orbBox / 2 - 3
        }

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
                anchors.fill: parent
                hoverEnabled: true
                onPressed: raiz.tocar(true)
                onReleased: raiz.tocar(false)
                onCanceled: raiz.tocar(false)
                onPositionChanged: mouse => {
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
