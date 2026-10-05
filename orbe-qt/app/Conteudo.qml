import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Layouts
import "../comum"
import "."

// Corpo do app: cabeçalho, o Ophanim do topo, o menu das páginas, as páginas,
// o rodapé e os avisos. A lógica de carregar, coletar e reagir é a do
// hermes_voice_app.py GTK; o que mexe no sistema fica na ponte em Python.
Item {
    id: raiz
    width: 500
    height: 700
    property var janela: null
    property string pagina: "agente"
    property string atalho: ponte.atalho
    readonly property var paginas: [
        { id: "agente", nome: "Agente", icone: "network-server-symbolic" },
        { id: "ativacao", nome: "Ativação", icone: "audio-input-microphone-symbolic" },
        { id: "voz", nome: "Voz", icone: "audio-speakers-symbolic" },
        { id: "conversa", nome: "Conversa", icone: "user-available-symbolic" },
        { id: "aparencia", nome: "Aparência", icone: "applications-graphics-symbolic" },
        { id: "relogio", nome: "Relógio", icone: "preferences-system-time-symbolic" }
    ]
    property var olhar: null

    // um quadro: o topo sempre; cartões e slider só com a Aparência à vista
    function passo(dt) {
        heroi.avancar(dt)
        if (pagina === "aparencia") {
            for (var i = 0; i < cartoes.count; i++) cartoes.itemAt(i).avancar(dt)
            tamanho.avancar(dt)
            if (rSombra.visible) rSombra.avancar(dt)
        }
    }

    // ── fundo de vidro (o blur é do niri) ──
    Rectangle {
        anchors.fill: parent
        radius: 18
        color: Estilo.alfa(Estilo.fundo, 0.58)
    }
    HoverHandler {
        onPointChanged: {
            var p = heroi.mapFromItem(raiz, point.position.x, point.position.y)
            raiz.olhar = Qt.point(p.x, p.y)
        }
        onHoveredChanged: if (!hovered) raiz.olhar = null
    }

    // ── cabeçalho: arrasta a janela; só o botão de fechar ──
    Item {
        id: cabecalho
        width: parent.width
        height: 40
        DragHandler {
            target: null
            onActiveChanged: if (active && raiz.janela) raiz.janela.startSystemMove()
        }
        BotaoIcone {
            anchors.right: parent.right
            anchors.rightMargin: 10
            anchors.verticalCenter: parent.verticalCenter
            lado: 26
            fundo: true
            icone: "window-close-symbolic"
            onClicado: raiz.janela ? raiz.janela.close() : Qt.quit()
        }
    }

    ColumnLayout {
        anchors.fill: parent
        anchors.topMargin: cabecalho.height
        spacing: 0

        Miniatura {
            id: heroi
            Layout.fillWidth: true
            Layout.preferredHeight: 196
            skin: "ofanim"
            peso: 1.0
            raio: Math.min(height * 0.42, width * 0.32)
            olhar: raiz.olhar
        }
        Text {
            Layout.alignment: Qt.AlignHCenter
            Layout.bottomMargin: 6
            text: "ORBE"
            color: Estilo.texto
            opacity: 0.6
            font.family: "monospace"
            font.pixelSize: 10
            font.letterSpacing: 3
        }

        // menu próprio, como no GTK: rótulos inteiros numa janela de 500 px
        Row {
            Layout.alignment: Qt.AlignHCenter
            Layout.bottomMargin: 8
            spacing: 2
            Repeater {
                model: raiz.paginas
                Rectangle {
                    readonly property bool marcado: raiz.pagina === modelData.id
                    width: rotulo.width + 10
                    height: 32
                    radius: 10
                    color: marcado ? Estilo.alfa(Estilo.accent, 0.20)
                                   : Estilo.alfa(Estilo.texto, hvm.hovered ? 0.07 : 0)
                    HoverHandler { id: hvm }
                    TapHandler { onTapped: raiz.pagina = modelData.id }
                    Row {
                        id: rotulo
                        anchors.centerIn: parent
                        spacing: 5
                        Icone {
                            anchors.verticalCenter: parent.verticalCenter
                            nome: modelData.icone
                            cor: parent.parent.marcado ? Estilo.accent : Estilo.texto
                        }
                        Text {
                            anchors.verticalCenter: parent.verticalCenter
                            text: modelData.nome
                            color: parent.parent.marcado ? Estilo.accent : Estilo.texto
                            // seis abas na largura da janela
                            font.pointSize: 10
                            font.bold: true
                        }
                    }
                }
            }
        }

        StackLayout {
            Layout.fillWidth: true
            Layout.fillHeight: true
            currentIndex: {
                for (var i = 0; i < raiz.paginas.length; i++)
                    if (raiz.paginas[i].id === raiz.pagina) return i
                return 0
            }

            // ═══ Agente ═══
            Pagina {
                Grupo {
                    descricao: "Quem responde: um agente ACP ou o Claude aberto no terminal."
                    LinhaCombo {
                        id: rAgente
                        titulo: "Agente"
                        itens: ponte.agentes
                        onEscolhido: raiz.mudouAgente(false)
                    }
                    LinhaCombo {
                        id: rPerfil
                        titulo: "Perfil do Hermes"
                        itens: ponte.perfis
                        visible: rAgente.efetivo === "hermes"
                        onEscolhido: raiz.mudouAgente(false)
                    }
                    LinhaEntrada {
                        id: rComando
                        titulo: "Comando ACP"
                        visible: rAgente.efetivo === "comando"
                    }
                    LinhaCombo {
                        id: rModelo
                        titulo: "Modelo"
                        busca: true
                        itens: [{ id: "", nome: "Padrão do agente" }]
                        visible: rAgente.efetivo !== "claude"
                        extra: [
                            BotaoIcone {
                                id: bConsultar
                                icone: "view-refresh-symbolic"
                                onClicado: raiz.consultarModelos()
                            }
                        ]
                    }
                    Linha {
                        id: rClaude
                        titulo: "Sessão do Claude"
                        visible: rAgente.efetivo === "claude"
                        BotaoIcone {
                            icone: "view-refresh-symbolic"
                            onClicado: rClaude.subtitulo = ponte.sessoesClaude()
                        }
                    }
                }
                Grupo {
                    titulo: "Claude no terminal"
                    descricao: "O Claude não roda em segundo plano: sem sessão aberta, o orbe abre uma num terminal "
                               + "no PC, pelo atalho (com o Claude escolhido acima) ou por um orbe do relógio que use o Claude."
                    LinhaEntrada {
                        id: rTerminal
                        titulo: "Terminal (roda <terminal> -e claude-orbe)"
                    }
                    LinhaEntrada {
                        id: rClaudePasta
                        titulo: "Pasta da sessão (vazio = a pasta do usuário)"
                    }
                }
                Grupo {
                    titulo: "Memória"
                    LinhaSpin {
                        id: rManter
                        titulo: "Descarregar o agente após"
                        subtitulo: "minutos sem sessão de voz; 0 mantém sempre carregado"
                        de: 0; ate: 240; passo: 5
                    }
                }
                Grupo {
                    titulo: "Instrução de voz"
                    descricao: "Vai no primeiro pedido de cada conversa, para agentes sem perfil de voz. "
                               + "O Hermes usa o SOUL do perfil; o Claude recebe junto do canal, ao abrir a sessão."
                    Item {
                        width: parent.width
                        height: Math.max(96, tInstrucao.contentHeight + 22)
                        TextEdit {
                            id: tInstrucao
                            x: 12
                            y: 10
                            width: parent.width - 24
                            wrapMode: TextEdit.Wrap
                            color: Estilo.texto
                            selectionColor: Estilo.alfa(Estilo.accent, 0.4)
                            font.pointSize: 9
                            selectByMouse: true
                        }
                    }
                }
            }

            // ═══ Ativação ═══
            Pagina {
                Grupo {
                    titulo: "Atalho"
                    Linha {
                        titulo: "Abrir o orbe"
                        Rectangle {
                            anchors.verticalCenter: parent.verticalCenter
                            width: lTecla.width + 18
                            height: lTecla.height + 6
                            radius: 7
                            color: Estilo.alfa(Estilo.accent, 0.14)
                            border.color: Estilo.alfa(Estilo.accent, 0.30)
                            Text {
                                id: lTecla
                                anchors.centerIn: parent
                                text: raiz.atalho
                                color: Estilo.texto
                                font.family: "monospace"
                                font.bold: true
                                font.pointSize: 10
                            }
                        }
                        Botao {
                            anchors.verticalCenter: parent.verticalCenter
                            texto: "Gravar"
                            onClicado: dlgAtalho.open()
                        }
                    }
                }
                Grupo {
                    titulo: "Palavra de ativação"
                    LinhaCombo {
                        id: rWake
                        titulo: "Provedor"
                        itens: [
                            { id: "nenhum", nome: "Nenhum (atalho e toque)" },
                            { id: "openwakeword", nome: "openWakeWord" },
                            { id: "sherpa", nome: "sherpa-onnx (frase livre)" },
                            { id: "microwakeword", nome: "microWakeWord" }
                        ]
                        subtitulo: ({ nenhum: "nenhum modelo carregado",
                                      openwakeword: "~130 MB no daemon",
                                      sherpa: "~95 MB no daemon",
                                      microwakeword: "~520 MB num processo à parte (TensorFlow)" })[efetivo] || ""
                        onEscolhido: raiz.mudouWake()
                    }
                    LinhaEntrada {
                        id: rFrase
                        titulo: "Frase"
                        visible: rWake.efetivo === "sherpa"
                    }
                    LinhaCombo {
                        id: rOww
                        titulo: "Modelo"
                        itens: ponte.owwModelos
                        visible: rWake.efetivo === "openwakeword"
                    }
                    LinhaCombo {
                        id: rMww
                        titulo: "Modelo"
                        itens: ponte.mwwModelos
                        visible: rWake.efetivo === "microwakeword"
                    }
                    LinhaSpin {
                        id: rLimiar
                        titulo: "Limiar"
                        subtitulo: "mais alto = mais exigente"
                        de: 0.05; ate: 0.99; passo: 0.01; casas: 2
                        visible: rWake.efetivo !== "nenhum"
                    }
                    LinhaSpin {
                        id: rConfirma
                        titulo: "Confirmação"
                        subtitulo: "quadros seguidos acima do limiar"
                        de: 1; ate: 10; passo: 1
                        visible: rWake.efetivo === "openwakeword" || rWake.efetivo === "microwakeword"
                    }
                }
            }

            // ═══ Voz ═══
            Pagina {
                Grupo {
                    titulo: "Transcrição"
                    descricao: "Groq Whisper"
                    LinhaCombo {
                        id: rStt
                        titulo: "Modelo"
                        itens: [{ id: "whisper-large-v3-turbo", nome: "whisper-large-v3-turbo" },
                                { id: "whisper-large-v3", nome: "whisper-large-v3" }]
                    }
                    LinhaEntrada {
                        id: rIdioma
                        titulo: "Idioma (código ISO)"
                    }
                }
                Grupo {
                    titulo: "Síntese"
                    LinhaCombo {
                        id: rTts
                        titulo: "Provedor"
                        itens: [{ id: "", nome: "O do perfil jarvis (" + ponte.ttsPerfil + ")" },
                                { id: "gemini", nome: "Gemini" }, { id: "xai", nome: "xAI" },
                                { id: "elevenlabs", nome: "ElevenLabs" }, { id: "piper", nome: "Piper (local)" }]
                    }
                    LinhaCombo {
                        id: rGvoz
                        titulo: "Voz Gemini"
                        busca: true
                        itens: ponte.geminiVozes
                        visible: raiz.ttsEfetivo === "gemini"
                    }
                    LinhaEntrada {
                        id: rXvoz
                        titulo: "Voz xAI (vazio = a do perfil)"
                        visible: ["xai", "grok", "xai-oauth"].indexOf(raiz.ttsEfetivo) >= 0
                    }
                    LinhaEntrada {
                        id: rEvoz
                        titulo: "Voz ElevenLabs (voice_id da biblioteca da conta)"
                        visible: raiz.ttsEfetivo === "elevenlabs"
                    }
                    LinhaCombo {
                        id: rPvoz
                        titulo: "Voz Piper"
                        itens: ponte.piperVozes
                        visible: raiz.ttsEfetivo === "piper"
                    }
                }
                Grupo {
                    titulo: "Chaves de API"
                    descricao: "Vazia, vale a do Hermes. Preencha para usar o orbe com outro agente ou numa máquina sem o Hermes. Ficam em ~/.config/hermes-voice/chaves.env, legível só por você."
                    Repeater {
                        id: rChaves
                        model: ponte.chaves
                        LinhaChave {
                            required property var modelData
                            titulo: modelData.nome
                            herda: modelData.herda
                            texto: modelData.propria
                        }
                    }
                }
            }

            // ═══ Conversa ═══
            Pagina {
                Grupo {
                    titulo: "Interrupção"
                    LinhaSwitch {
                        id: rBarge
                        titulo: "Interromper pela voz"
                        subtitulo: "falar por cima corta a fala e o raciocínio"
                    }
                    LinhaSpin {
                        id: rBq
                        titulo: "Voz sustentada"
                        subtitulo: "quadros de 30 ms"
                        de: 2; ate: 60; passo: 1
                    }
                    LinhaSpin {
                        id: rBrms
                        titulo: "Piso de volume"
                        subtitulo: "RMS"
                        de: 300; ate: 12000; passo: 100
                    }
                }
                Grupo {
                    titulo: "Fala"
                    LinhaSpin {
                        id: rSil
                        titulo: "Silêncio que fecha a fala"
                        subtitulo: "segundos"
                        de: 0.3; ate: 3.0; passo: 0.05; casas: 2
                    }
                    LinhaSpin {
                        id: rFrms
                        titulo: "Piso de fala"
                        subtitulo: "RMS"
                        de: 300; ate: 12000; passo: 100
                    }
                    LinhaSpin {
                        id: rFq
                        titulo: "Voz para abrir gravação"
                        subtitulo: "quadros de 30 ms"
                        de: 2; ate: 60; passo: 1
                    }
                    LinhaSpin {
                        id: rGmax
                        titulo: "Gravação máxima"
                        subtitulo: "segundos"
                        de: 3; ate: 120; passo: 1
                    }
                    LinhaSpin {
                        id: rOcio
                        titulo: "Sessão ociosa fecha em"
                        subtitulo: "segundos"
                        de: 3; ate: 600; passo: 1
                    }
                }
                Grupo {
                    titulo: "Toque no orbe"
                    LinhaSpin {
                        id: rSegurar
                        titulo: "Segurar para gravar"
                        subtitulo: "segundos; menos que isso só interrompe"
                        de: 0.1; ate: 2.0; passo: 0.05; casas: 2
                    }
                    LinhaSpin {
                        id: rTmax
                        titulo: "Gravação máxima segurando"
                        subtitulo: "segundos"
                        de: 10; ate: 300; passo: 5
                    }
                }
                Grupo {
                    titulo: "Diagnóstico"
                    LinhaSwitch {
                        id: rRastro
                        titulo: "Rastro de níveis no log"
                        subtitulo: "uma linha por segundo no journal"
                    }
                }
            }

            // ═══ Aparência ═══
            Pagina {
                Grupo {
                    titulo: "Avatar do orbe"
                    caixa: false
                    Grid {
                        width: parent.width
                        columns: 2
                        spacing: 10
                        Repeater {
                            id: cartoes
                            model: ["ofanim", "ofanim_alado", "shoggoth", "serafim_gravura", "entidade", "anel"]
                            Cartao {
                                width: (parent.width - 10) / 2
                                skin: modelData
                                nome: ponte.nomesSkin[modelData]
                                marcado: raiz.skin === modelData
                                glitch: rGlitch.ligado
                                onEscolhido: raiz.skin = modelData
                            }
                        }
                    }
                }
                Grupo {
                    SliderOrbe {
                        id: tamanho
                        skin: raiz.skin
                        glitch: rGlitch.ligado
                    }
                    LinhaSwitch {
                        id: rGlitch
                        titulo: "Glitch"
                        subtitulo: "aberração cromática, faixas arrancadas e linhas de varredura"
                    }
                    LinhaSwitch {
                        id: rVidro
                        titulo: "Sombra atrás do orbe"
                        subtitulo: "degradê escuro que some até a borda, para a figura destacar do fundo"
                    }
                    SliderOrbe {
                        id: rSombra
                        visible: rVidro.ligado
                        titulo: "Intensidade da sombra"
                        subtitulo: "opacidade no centro"
                        de: 0.1; ate: 1.0; passo: 0.05
                        marca: 0.45
                        // o botão é o orbe sobre a própria sombra, no degradê do pos.frag
                        botao: Component {
                            Item {
                                function avancar(dt) { mini.avancar(dt) }
                                DiscoSombra {
                                    anchors.fill: parent
                                    alfa: rSombra.valor
                                }
                                Miniatura {
                                    id: mini
                                    anchors.fill: parent
                                    skin: raiz.skin
                                    glitch: rGlitch.ligado
                                    peso: 0.9
                                }
                            }
                        }
                    }
                    LinhaCombo {
                        id: rTexto
                        titulo: "Texto do raciocínio"
                        subtitulo: "onde aparecem as linhas do agente"
                        itens: [{ id: "lado", nome: "Ao lado do orbe" }, { id: "abaixo", nome: "Abaixo do orbe" }]
                    }
                    LinhaSwitch {
                        id: rMover
                        titulo: "Mover o orbe pela tela"
                        subtitulo: "destravado, arrastar o orbe muda o lugar dele; travado, ele fica onde está"
                    }
                }
            }

            // ═══ Relógio ═══
            Pagina {
                Grupo {
                    titulo: "Conexão"
                    descricao: "O orbe no pulso (orbe-wear): o app do relógio fala com este computador pela rede local."
                    LinhaSwitch {
                        id: rRelogio
                        titulo: "Ponte do relógio"
                        subtitulo: "abre a porta " + ponte.cfg.relogio.porta + " para o app do relógio"
                    }
                    Linha {
                        titulo: "Pareamento"
                        subtitulo: "no relógio, o servidor é " + ponte.enderecoRelogio + " e o token é este"
                        visible: rRelogio.ligado
                        Rectangle {
                            anchors.verticalCenter: parent.verticalCenter
                            width: lToken.width + 18
                            height: lToken.height + 6
                            radius: 7
                            color: Estilo.alfa(Estilo.accent, 0.14)
                            border.color: Estilo.alfa(Estilo.accent, 0.30)
                            Text {
                                id: lToken
                                anchors.centerIn: parent
                                text: raiz.tokenRelogio || "ao aplicar"
                                color: Estilo.texto
                                font.family: "monospace"
                                font.bold: true
                                font.pointSize: 10
                            }
                        }
                        BotaoIcone {
                            // token novo: o relógio pareado com o velho para de entrar
                            icone: "view-refresh-symbolic"
                            visible: raiz.tokenRelogio !== ""
                            onClicado: raiz.tokenRelogio = ponte.trocarTokenRelogio()
                        }
                    }
                    Linha {
                        id: rFirewall
                        titulo: "Firewall"
                        subtitulo: ponte.firewallRelogio()
                        visible: rRelogio.ligado && subtitulo !== ""
                        BotaoIcone {
                            icone: "view-refresh-symbolic"
                            onClicado: rFirewall.subtitulo = ponte.firewallRelogio()
                        }
                    }
                    LinhaSwitch {
                        id: rRelogioMic
                        titulo: "Aceitar a fala do relógio"
                        subtitulo: "segurando o orbe no relógio, a fala vem de lá e não do microfone do PC"
                        visible: rRelogio.ligado
                    }
                }
                Grupo {
                    titulo: "Agente de cada orbe"
                    descricao: "Rolar o carrossel do relógio troca de orbe e, com ele, de agente. "
                               + "O Claude abre num terminal no PC; os outros rodam em segundo plano."
                    Repeater {
                        id: agentesOrbe
                        model: ["ofanim", "ofanim_alado", "shoggoth", "serafim_gravura", "entidade", "anel"]
                        LinhaCombo {
                            readonly property string skin: modelData
                            titulo: ponte.nomesSkin[modelData] || modelData
                            itens: ponte.agentesRelogio
                        }
                    }
                }
                Grupo {
                    titulo: "No relógio"
                    descricao: "Os ajustes do app do relógio: valem lá e aqui, e o lado que mudou por último ganha."
                    LinhaSwitch {
                        id: rwVoz
                        titulo: "Voz no relógio"
                        subtitulo: "a resposta toca no relógio"
                    }
                    LinhaSwitch {
                        id: rwVozPc
                        titulo: "Voz também no PC"
                        subtitulo: "tocando no relógio, a resposta toca aqui junto"
                        visible: rwVoz.ligado
                    }
                    LinhaSwitch {
                        id: rwMic
                        titulo: "Microfone do relógio"
                        subtitulo: "segurando o orbe no relógio, a fala vem dele"
                    }
                    LinhaSwitch {
                        id: rwVibrar
                        titulo: "Vibrar"
                        subtitulo: "ao segurar e ao soltar o orbe"
                    }
                    LinhaSwitch {
                        id: rwTexto
                        titulo: "Texto do raciocínio"
                        subtitulo: "as linhas do agente, abaixo do orbe"
                    }
                    LinhaSwitch {
                        id: rwSeguir
                        titulo: "Seguir o orbe do PC"
                        subtitulo: "o avatar e o glitch vêm daqui; rolar o carrossel desliga"
                    }
                    LinhaSwitch {
                        id: rwGlitch
                        titulo: "Glitch"
                        subtitulo: "aberração cromática e faixas arrancadas"
                        visible: !rwSeguir.ligado
                    }
                    LinhaSwitch {
                        id: rwLinhas
                        titulo: "Linhas de TV"
                        subtitulo: "linhas de varredura, como num tubo"
                        visible: !rwSeguir.ligado
                    }
                    LinhaSpin {
                        id: rwTamanho
                        titulo: "Tamanho do orbe"
                        subtitulo: "1,00 enche o mostrador"
                        de: 0.6; ate: 1.3; passo: 0.05; casas: 2
                    }
                }
            }
        }

        // ── rodapé ──
        Item {
            Layout.fillWidth: true
            Layout.preferredHeight: 62
            Rectangle {
                width: parent.width
                height: 1
                color: Estilo.alfa(Estilo.accent, 0.12)
            }
            Text {
                anchors.left: parent.left
                anchors.leftMargin: 14
                anchors.right: bPrevia.left
                anchors.rightMargin: 10
                anchors.verticalCenter: parent.verticalCenter
                text: ponte.previa && ponte.previaEstado ? "prévia: " + ponte.previaEstado : ponte.estado
                color: Estilo.texto
                opacity: 0.6
                font.family: "monospace"
                font.pixelSize: 10
                elide: Text.ElideRight
            }
            Botao {
                id: bPrevia
                anchors.right: aplicar.left
                anchors.rightMargin: 8
                anchors.verticalCenter: parent.verticalCenter
                texto: ponte.previa ? "Fechar prévia" : "Pré-visualizar"
                ligado: ponte.previa
                onClicado: ponte.previa ? ponte.desligarPrevia() : ponte.ligarPrevia(raiz.aparencia)
            }
            Botao {
                id: aplicar
                anchors.right: parent.right
                anchors.rightMargin: 14
                anchors.verticalCenter: parent.verticalCenter
                texto: "Aplicar"
                destaque: true
                onClicado: raiz.aplicar()
            }
        }
    }

    // ── aviso no pé da janela ──
    Rectangle {
        id: aviso
        property alias texto: tAviso.text
        anchors.horizontalCenter: parent.horizontalCenter
        anchors.bottom: parent.bottom
        anchors.bottomMargin: 76
        width: Math.min(tAviso.implicitWidth + 32, parent.width - 40)
        height: tAviso.implicitHeight + 18
        radius: height / 2
        color: Estilo.alfa(Estilo.popover, 0.96)
        border.color: Estilo.alfa(Estilo.accent, 0.20)
        opacity: 0
        visible: opacity > 0
        Behavior on opacity { NumberAnimation { duration: 160 } }
        Text {
            id: tAviso
            anchors.centerIn: parent
            width: Math.min(implicitWidth, raiz.width - 72)
            color: Estilo.texto
            font.pointSize: 10
            wrapMode: Text.Wrap
            horizontalAlignment: Text.AlignHCenter
        }
        Timer {
            id: tempoAviso
            onTriggered: aviso.opacity = 0
        }
        function mostrar(t, s) {
            texto = t
            opacity = 1
            tempoAviso.interval = (s || 3) * 1000
            tempoAviso.restart()
        }
    }

    // ── gravar atalho ──
    Popup {
        id: dlgAtalho
        parent: raiz
        anchors.centerIn: parent
        width: 320
        modal: true
        padding: 20
        closePolicy: Popup.NoAutoClose
        background: Rectangle {
            color: Estilo.popover
            radius: 14
            border.color: Estilo.alfa(Estilo.accent, 0.18)
        }
        onOpened: ponte.capturarAtalho()
        onClosed: ponte.cancelarCaptura()
        contentItem: Column {
            spacing: 14
            Text {
                anchors.horizontalCenter: parent.horizontalCenter
                text: "Novo atalho"
                color: Estilo.texto
                font.pointSize: 13
                font.bold: true
            }
            Text {
                width: parent.width
                text: "Pressione a combinação de teclas. Esc cancela."
                color: Estilo.texto
                opacity: 0.75
                font.pointSize: 11
                wrapMode: Text.Wrap
                horizontalAlignment: Text.AlignHCenter
            }
            Botao {
                anchors.horizontalCenter: parent.horizontalCenter
                texto: "Cancelar"
                onClicado: dlgAtalho.close()
            }
        }
    }
    Connections {
        target: ponte
        // o relógio mudou os ajustes dele: entram aqui se ninguém mexeu nesta aba
        function onAjustesRelogioMudou(aj) {
            if (JSON.stringify(raiz.coletarAjustes(raiz.ajustesBase)) === raiz.ajustesVistos)
                raiz.carregarAjustes(aj)
        }
        function onAtalhoCapturado(nome) {
            raiz.atalho = nome
            dlgAtalho.close()
        }
        function onAtalhoCancelado() { dlgAtalho.close() }
        function onModelosConsultados(r, erro) {
            bConsultar.ativo = true
            if (!r) {
                rModelo.subtitulo = "falhou: " + erro.slice(0, 80)
                return
            }
            raiz.preencherModelos(r.modelos, r.atual)
            rModelo.subtitulo = r.modelos.length ? r.modelos.length + " modelos"
                                                 : "o agente não oferece troca de modelo"
        }
    }

    // ── estado que outras linhas leem ──
    property string skin: "ofanim"
    // nasce na primeira vez que a ponte do relógio é aplicada ligada
    property string tokenRelogio: ponte.cfg.relogio.token
    // aparência ainda não aplicada; a prévia do orbe acompanha cada mudança
    readonly property var aparencia: ({ skin: raiz.skin, glitch: rGlitch.ligado,
                                        vidro: rVidro.ligado, sombra: rSombra.valor,
                                        tamanho: tamanho.valor,
                                        texto: rTexto.efetivo })
    onAparenciaChanged: if (ponte.previa) ponte.atualizarPrevia(aparencia)
    readonly property string ttsEfetivo: rTts.efetivo || ponte.ttsPerfil

    // ── reações (mesma lógica do GTK) ──
    function chaveAgente() {
        var tipo = rAgente.efetivo
        return [tipo, tipo === "hermes" ? rPerfil.efetivo : "", tipo === "comando" ? rComando.texto.trim() : ""].join("|")
    }
    function preencherModelos(modelos, atual) {
        var escolhido = rModelo.efetivo || ponte.cfg.agente.modelo
        var itens = [{ id: "", nome: "Padrão do agente" + (atual ? " (" + atual + ")" : "") }]
        for (var i = 0; i < modelos.length; i++) {
            var m = modelos[i]
            itens.push({ id: m.id, nome: m.nome === m.id ? m.nome : m.nome + "  ·  " + m.id })
        }
        rModelo.itens = itens
        rModelo.valor = escolhido
    }
    function modelosDoEstado() {
        var est = ponte.modelosDoEstado(chaveAgente())
        if (est) {
            preencherModelos(est.modelos, est.atual)
            rModelo.subtitulo = est.modelos.length + " modelos"
        } else {
            preencherModelos([], "")
            rModelo.subtitulo = "consulte para listar os modelos"
        }
    }
    function mudouAgente(inicial) {
        if (rAgente.efetivo === "claude") rClaude.subtitulo = ponte.sessoesClaude()
        if (!inicial) modelosDoEstado()
    }
    function consultarModelos() {
        bConsultar.ativo = false
        rModelo.subtitulo = "consultando o agente…"
        ponte.consultarModelos({ tipo: rAgente.efetivo, perfil: rPerfil.efetivo, comando: rComando.texto.trim() })
    }
    function mudouWake() {
        var at = ponte.cfg.ativacao
        var lim = ({ openwakeword: at.limiar_oww, sherpa: at.limiar_sherpa, microwakeword: at.limiar_mww })[rWake.efetivo]
        if (lim !== undefined) rLimiar.valor = lim
    }

    // ── os ajustes do relógio: vêm do config e, com o app aberto, da ponte ──
    property var ajustesBase: ({})
    property string ajustesVistos: ""
    function carregarAjustes(aj) {
        ajustesBase = aj
        rwVoz.ligado = !!aj.voz
        rwVozPc.ligado = !!aj.voz_pc
        rwMic.ligado = !!aj.microfone
        rwVibrar.ligado = !!aj.vibrar
        rwTexto.ligado = !!aj.texto
        rwSeguir.ligado = !!aj.seguir_pc
        rwGlitch.ligado = !!aj.glitch
        rwLinhas.ligado = aj.linhas === undefined ? true : !!aj.linhas
        rwTamanho.valor = aj.tamanho === undefined ? 1.0 : aj.tamanho
        for (var i = 0; i < agentesOrbe.count; i++) {
            var l = agentesOrbe.itemAt(i)
            l.valor = (aj.agentes && aj.agentes[l.skin]) || ""
        }
        ajustesVistos = JSON.stringify(coletarAjustes(aj))
    }
    function coletarAjustes(base) {
        var aj = JSON.parse(JSON.stringify(base))
        aj.voz = rwVoz.ligado
        aj.voz_pc = rwVozPc.ligado
        aj.microfone = rwMic.ligado
        aj.vibrar = rwVibrar.ligado
        aj.texto = rwTexto.ligado
        aj.seguir_pc = rwSeguir.ligado
        aj.glitch = rwGlitch.ligado
        aj.linhas = rwLinhas.ligado
        aj.tamanho = Math.round(rwTamanho.valor * 100) / 100
        aj.agentes = aj.agentes || {}
        for (var i = 0; i < agentesOrbe.count; i++) {
            var l = agentesOrbe.itemAt(i)
            aj.agentes[l.skin] = l.efetivo
        }
        return aj
    }

    // ── carregar / coletar ──
    function carregar() {
        var c = ponte.cfg
        var a = c.agente, at = c.ativacao, v = c.voz, cv = c.conversa, t = c.toque
        rAgente.valor = a.tipo
        rPerfil.valor = a.perfil
        rComando.texto = a.comando
        rManter.valor = a.manter_carregado_min
        tInstrucao.text = a.instrucao_voz
        modelosDoEstado()
        rModelo.valor = a.modelo

        rWake.valor = at.provedor
        rFrase.texto = at.frase
        rOww.valor = at.oww_modelo
        rMww.valor = at.mww_modelo
        rConfirma.valor = at.confirmacao
        rRelogio.ligado = !!c.relogio.ligado
        rRelogioMic.ligado = !!c.relogio.microfone
        carregarAjustes(c.relogio.ajustes)
        rTerminal.texto = a.terminal
        rClaudePasta.texto = a.claude_pasta

        rStt.valor = v.stt_modelo
        rIdioma.texto = v.stt_idioma
        rTts.valor = v.tts_provedor
        rGvoz.valor = v.gemini_voz
        rXvoz.texto = v.xai_voz
        rEvoz.texto = v.elevenlabs_voz
        rPvoz.valor = v.piper_voz

        rBarge.ligado = !!cv.barge_in
        rBq.valor = cv.barge_quadros
        rBrms.valor = cv.barge_rms
        rSil.valor = cv.silencio_fim_s
        rFrms.valor = cv.fala_rms
        rFq.valor = cv.fala_quadros
        rGmax.valor = cv.gravacao_max_s
        rOcio.valor = cv.sessao_ociosa_s
        rSegurar.valor = t.segurar_s
        rTmax.valor = t.gravacao_max_s
        rRastro.ligado = !!c.diagnostico.rastro_niveis

        var o = c.orbe
        // o Seraphim desenhado saiu; quem o tinha fica com o da gravura
        var sk = o.skin === "serafim" ? "serafim_gravura" : o.skin
        skin = ["ofanim", "ofanim_alado", "shoggoth", "serafim_gravura", "entidade", "anel"].indexOf(sk) >= 0 ? sk : "ofanim"
        rGlitch.ligado = !!o.glitch
        rVidro.ligado = !!o.vidro
        rSombra.definir(o.sombra === undefined ? 0.45 : o.sombra)
        rTexto.valor = o.texto || "lado"
        rMover.ligado = !!o.mover
        tamanho.definir(o.tamanho === undefined ? 1.0 : o.tamanho)
        mudouAgente(true)
        mudouWake()
    }
    function coletar() {
        var cfg = JSON.parse(JSON.stringify(ponte.cfg))
        var a = cfg.agente, at = cfg.ativacao, v = cfg.voz, cv = cfg.conversa, t = cfg.toque
        a.tipo = rAgente.efetivo
        a.perfil = rPerfil.efetivo
        a.comando = rComando.texto.trim()
        a.modelo = rModelo.efetivo
        a.manter_carregado_min = Math.round(rManter.valor)
        a.instrucao_voz = tInstrucao.text.trim()
        at.provedor = rWake.efetivo
        at.frase = rFrase.texto.trim() || at.frase
        if (rOww.efetivo) at.oww_modelo = rOww.efetivo
        if (rMww.efetivo) at.mww_modelo = rMww.efetivo
        var chave = ({ openwakeword: "limiar_oww", sherpa: "limiar_sherpa", microwakeword: "limiar_mww" })[at.provedor]
        if (chave) at[chave] = Math.round(rLimiar.valor * 100) / 100
        at.confirmacao = Math.round(rConfirma.valor)
        at.atalho = raiz.atalho
        cfg.relogio.ligado = rRelogio.ligado
        cfg.relogio.microfone = rRelogioMic.ligado
        cfg.relogio.ajustes = coletarAjustes(raiz.ajustesBase)
        a.terminal = rTerminal.texto.trim() || "ghostty"
        a.claude_pasta = rClaudePasta.texto.trim()
        v.stt_modelo = rStt.efetivo
        v.stt_idioma = rIdioma.texto.trim() || "pt"
        v.tts_provedor = rTts.efetivo
        v.gemini_voz = rGvoz.efetivo
        v.xai_voz = rXvoz.texto.trim()
        v.elevenlabs_voz = rEvoz.texto.trim()
        v.piper_voz = rPvoz.efetivo
        cv.barge_in = rBarge.ligado
        cv.barge_quadros = Math.round(rBq.valor)
        cv.barge_rms = Math.round(rBrms.valor)
        cv.silencio_fim_s = Math.round(rSil.valor * 100) / 100
        cv.fala_rms = Math.round(rFrms.valor)
        cv.fala_quadros = Math.round(rFq.valor)
        cv.gravacao_max_s = Math.round(rGmax.valor)
        cv.sessao_ociosa_s = rOcio.valor
        t.segurar_s = Math.round(rSegurar.valor * 100) / 100
        t.gravacao_max_s = rTmax.valor
        cfg.diagnostico.rastro_niveis = rRastro.ligado
        cfg.orbe.skin = raiz.skin
        cfg.orbe.glitch = rGlitch.ligado
        cfg.orbe.vidro = rVidro.ligado
        cfg.orbe.sombra = rSombra.valor
        cfg.orbe.tamanho = tamanho.valor
        cfg.orbe.texto = rTexto.efetivo
        cfg.orbe.mover = rMover.ligado
        // vão à parte, para o chaves.env (o config.json não guarda chave)
        cfg.chaves = {}
        for (var i = 0; i < rChaves.count; i++)
            cfg.chaves[ponte.chaves[i].id] = rChaves.itemAt(i).texto.trim()
        return cfg
    }
    function aplicar() {
        var r = ponte.aplicar(coletar(), raiz.atalho)
        raiz.atalho = r.atalho
        raiz.tokenRelogio = r.token
        aviso.mostrar(r.mensagem, r.tempo)
    }
    Component.onCompleted: carregar()
}
