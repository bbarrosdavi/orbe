import QtQuick
import QtQuick.Window
import "comum"

// Orbe de voz no macOS: o orbe.qml sem Quickshell. A ponte (orbe_mac.py) faz
// o que o Quickshell fazia: socket do daemon, toque no ctl, config ao vivo,
// cor de destaque e posição do cursor. O desenho é o mesmo OrbeConteudo.
Window {
    id: janela

    // painel flutuante, sem foco: tocar no orbe não rouba o teclado do app
    // da frente (o resto vem do NSWindow, ajustado em orbe_mac.py)
    flags: Qt.Tool | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint
           | Qt.WindowDoesNotAcceptFocus | Qt.NoDropShadowWindowHint
    color: "transparent"
    visible: conteudo.visivel
    width: conteudo.width
    height: conteudo.height
    // canto superior direito da área útil (abaixo da barra de menus)
    x: ponte.area.x + ponte.area.width - width
    y: ponte.area.y

    // ── configuração (mesma leitura do orbe.qml) ──
    function lerConfig(texto) {
        var o = {}
        try { o = (JSON.parse(texto) || {}).orbe || {} } catch (e) { o = {} }
        // o Seraphim desenhado saiu; quem o tinha fica com o da gravura (o
        // Shoggoth e a Entidade também saíram: Ophanim)
        var sk = o.skin === "serafim" ? "serafim_gravura" : String(o.skin || "ofanim")
        conteudo.skin = ["ofanim", "ofanim_alado", "serafim_gravura", "anel"].indexOf(sk) >= 0 ? sk : "ofanim"
        conteudo.glitch = o.glitch === undefined ? true : !!o.glitch
        conteudo.vidro = !!o.vidro
        var som = parseFloat(o.sombra)
        conteudo.sombra = isNaN(som) ? 0.45 : Math.min(1.0, Math.max(0.1, som))
        // cada skin guarda o seu tamanho; sem o dela, vale o comum
        var proprio = (o.tamanhos || {})[conteudo.skin]
        var tam = parseFloat(proprio === undefined || proprio === null ? o.tamanho : proprio)
        conteudo.tamanho = isNaN(tam) ? 1.0 : Math.min(1.6, Math.max(0.6, tam))
        conteudo.textoPos = o.texto === "abaixo" ? "abaixo" : "lado"
        conteudo.textoSombra = o.texto_sombra === undefined ? true : !!o.texto_sombra
        var fs = parseFloat(o.texto_sombra_forca)
        conteudo.textoSombraForca = isNaN(fs) ? 0.7 : Math.min(1.0, Math.max(0.1, fs))
        conteudo.luasMovimento = o.luas === "orbitas" ? "orbitas" : "vagalumes"
        conteudo.luasLigadas = o.luas_ligadas === undefined ? true : !!o.luas_ligadas
        conteudo.luasSoAtivas = !!o.luas_so_ativas
    }

    Connections {
        target: ponte
        function onLinha(l) { conteudo.comando(l) }
        function onConfigMudou() { janela.lerConfig(ponte.config) }
    }
    Component.onCompleted: lerConfig(ponte.config)

    OrbeConteudo {
        id: conteudo
        accent: ponte.accent
        onSaiu: ponte.saiu()
        // a máscara de toque acompanha o quadrado da arte
        onArtBoxChanged: janela.mascarar()
        onWidthChanged: janela.mascarar()
    }
    function mascarar() {
        ponte.mascara(janela, alvo.x, alvo.y, alvo.width, alvo.height)
    }
    onVisibleChanged: if (visible) { ponte.ajustarJanela(janela); mascarar() }

    // ── toque: só o quadrado da arte; a coluna de texto deixa passar ──
    Item {
        id: alvo
        x: conteudo.cx - width / 2
        y: conteudo.cy - height / 2
        width: conteudo.artBox
        height: conteudo.artBox
        MouseArea {
            anchors.fill: parent
            // a rodinha em cima do orbe troca o orbe do PC: um passo por entalhe,
            // no máximo um a cada 250 ms (o trackpad manda muitos eventos)
            property real roda: 0
            property real rodaEm: 0
            onWheel: wheel => {
                roda += wheel.angleDelta.y !== 0 ? wheel.angleDelta.y : wheel.angleDelta.x
                var agora = Date.now()
                if (Math.abs(roda) >= 120 && agora - rodaEm > 250) {
                    ponte.trocarOrbe(roda < 0 ? 1 : -1)
                    roda = 0
                    rodaEm = agora
                }
                wheel.accepted = true
            }
            onPressed: tocar(true)
            onReleased: tocar(false)
            onCanceled: tocar(false)
            function tocar(dentro) {
                if (dentro === conteudo.toque) return
                conteudo.toque = dentro
                ponte.tocar(dentro)
            }
        }
    }

    // ── olhar: o macOS dá a posição global do cursor a qualquer hora, então
    //    não há evdev nem âncora; 30 Hz bastam, os olhos suavizam ──
    Timer {
        interval: 33
        repeat: true
        running: janela.visible && conteudo.avatar
        onTriggered: {
            var p = ponte.cursor()
            conteudo.olhar = Qt.point(p.x - janela.x - conteudo.painel, p.y - janela.y)
        }
        onRunningChanged: if (!running) conteudo.olhar = null
    }

    FrameAnimation {
        running: janela.visible
        onTriggered: conteudo.passo(frameTime)
    }
}
