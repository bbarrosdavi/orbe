import QtQuick
import QtQuick.Dialogs
import QtQuick.Controls.Basic
import QtQuick.Layouts
import "../comum"
import "."

// Corpo do app: cabeçalho, o Ophanim do topo, o menu das páginas, as páginas,
// o rodapé e os avisos. A lógica de carregar, coletar e reagir é a do
// orbe_app.py GTK; o que mexe no sistema fica na ponte em Python.
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

    // ── fundo de vidro (o blur é do niri; no Mac fica quase opaco) ──
    Rectangle {
        anchors.fill: parent
        radius: 18
        color: Estilo.alfa(Estilo.fundo, ponte.tema.opacidade || 0.58)
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
                    descricao: "Quem responde: o agente, numa janela do terminal ou em segundo plano (abaixo). Cada orbe tem o seu, "
                               + "o mesmo no PC e no relógio: trocar a skin na Aparência troca o agente do atalho e "
                               + "da palavra de ativação. A lista com todos os orbes fica na aba Relógio."
                    LinhaCombo {
                        id: rAgente
                        titulo: "Agente do orbe em uso"
                        subtitulo: ponte.nomesSkin[raiz.skin] || raiz.skin
                        itens: ponte.agentes
                        onEscolhido: {
                            raiz.empurrarAgenteDaSkin()
                            raiz.mudouAgente(false)
                        }
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
                    titulo: "Onde cada agente roda"
                    descricao: "Num terminal, sem sessão aberta o orbe abre uma janela no PC com o agente, e o pedido "
                               + "de voz aparece no chat dela; do relógio, cada instância do orbe é uma janela. Em segundo "
                               + "plano, roda sem janela: o Claude com claude --bg, ouvindo pelo hook do orbe, e os outros por ACP."
                    Repeater {
                        id: rModos
                        model: ponte.agentesModo
                        LinhaCombo {
                            readonly property string agente: modelData.id
                            titulo: modelData.nome
                            itens: [{ id: "terminal", nome: "Num terminal" }, { id: "fundo", nome: "Em segundo plano" }]
                            valor: (ponte.cfg.agente.modos || {})[modelData.id] || "terminal"
                        }
                    }
                    LinhaEntrada {
                        id: rTerminal
                        titulo: "Terminal (roda <terminal> -e <agente>)"
                    }
                    LinhaEntrada {
                        id: rClaudePasta
                        titulo: "Pasta das janelas (vazio = a pasta do usuário)"
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
                    titulo: "Voz de cada orbe"
                    descricao: "Com vários orbes conversando ao mesmo tempo, cada um fala com a sua. "
                               + "Vale para o provedor de cima; sem uma escolhida, o orbe usa a voz de cima."
                    // Gemini e Piper têm lista; xAI e ElevenLabs, o nome ou o voice_id
                    Repeater {
                        id: rVozesLista
                        model: raiz.skinsTodas
                        LinhaCombo {
                            readonly property string skin: modelData
                            titulo: ponte.nomesSkin[modelData] || modelData
                            busca: raiz.ttsEfetivo === "gemini"
                            visible: raiz.ttsEfetivo === "gemini" || raiz.ttsEfetivo === "piper"
                            itens: [{ id: "", nome: "A de cima" }].concat(
                                (raiz.ttsEfetivo === "piper" ? ponte.piperVozes : ponte.geminiVozes).filter(function (v) { return v.id }))
                            valor: ((raiz.vozesOrbes[raiz.ttsEfetivo] || {})[modelData]) || ""
                        }
                    }
                    Repeater {
                        id: rVozesTexto
                        model: raiz.skinsTodas
                        LinhaEntrada {
                            readonly property string skin: modelData
                            titulo: (ponte.nomesSkin[modelData] || modelData) + " (vazio = a de cima)"
                            visible: !(raiz.ttsEfetivo === "gemini" || raiz.ttsEfetivo === "piper")
                            texto: ((raiz.vozesOrbes[raiz.ttsEfetivo] || {})[modelData]) || ""
                        }
                    }
                }
                Grupo {
                    titulo: "Chaves de API"
                    descricao: "Vazia, vale a do Hermes. Preencha para usar o orbe com outro agente ou numa máquina sem o Hermes. Ficam em ~/.config/orbe/chaves.env, legível só por você."
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
                    titulo: "Etapas"
                    descricao: "Enquanto o agente trabalha, o orbe fala o que ele está fazendo: a descrição de cada ferramenta. É a mesma chave da aba Voz do relógio e vale nos dois."
                    LinhaSwitch {
                        id: rwEtapas
                        titulo: "Falar as etapas"
                    }
                    LinhaCombo {
                        id: rwIdiomaEtapas
                        titulo: "Idioma das etapas"
                        itens: [{ id: "pt", nome: "Português (traduzidas pelo Groq)" },
                                { id: "original", nome: "Como o agente escreve" }]
                        visible: rwEtapas.ligado
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
                            model: ["ofanim", "ofanim_alado", "serafim_gravura", "olho", "humana", "anel"]
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
                        subtitulo: "a deste orbe: cada um guarda a sua"
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
                        // o mesmo botão do tamanho: só o orbe
                        skin: raiz.skin
                        glitch: rGlitch.ligado
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
                    LinhaSwitch {
                        id: rSeguir
                        titulo: "Seguir o relógio"
                        subtitulo: "a sessão aberta no relógio aparece no orbe do PC com o orbe de lá, a skin e a cor da instância"
                        visible: rRelogio.ligado
                    }
                }
                Grupo {
                    titulo: "Agente de cada orbe"
                    descricao: "Rolar a lista do relógio troca de orbe e, com ele, de agente; no PC vale o da skin "
                               + "em uso. Cada agente roda onde a aba Agente diz, numa janela do terminal ou em segundo plano."
                    Repeater {
                        id: agentesOrbe
                        model: raiz.skinsRelogio
                        LinhaCombo {
                            readonly property string skin: modelData
                            titulo: ponte.nomesSkin[modelData] || modelData
                            itens: ponte.agentesRelogio
                            onEscolhido: if (skin === raiz.skin) raiz.puxarAgenteDaSkin()
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
                        subtitulo: "só no relógio: as linhas do agente abaixo do orbe de lá (o daqui segue o ajuste da Aparência)"
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
                    LinhaSwitch {
                        id: rwFundo
                        titulo: "Fundo atrás do orbe"
                        subtitulo: "o fundo do menu também atrás dos orbes"
                        visible: raiz.relogioConhecido
                    }
                    LinhaCombo {
                        id: rwPapel
                        titulo: "Plano de fundo"
                        subtitulo: efetivo !== "imagem" ? "o papel de parede do PC, borrado como o fundo deste app"
                                 : raiz.papelRelogio ? raiz.papelRelogio.split("/").pop() : "escolha a imagem"
                        itens: [{ id: "pc", nome: "O do computador" }, { id: "imagem", nome: "Uma imagem" }]
                        extra: Botao {
                            texto: "Escolher…"
                            visible: rwPapel.efetivo === "imagem"
                            onClicado: dialogoPapel.open()
                        }
                    }
                    // cada orbe do relógio guarda o seu tamanho
                    Repeater {
                        id: rwTamanhos
                        model: raiz.skinsRelogio
                        LinhaSpin {
                            readonly property string skin: modelData
                            titulo: "Tamanho: " + (ponte.nomesSkin[modelData] || modelData)
                            subtitulo: "1,00 enche o mostrador"
                            de: 0.6; ate: 1.3; passo: 0.05; casas: 2
                        }
                    }
                }
                // os de baixo só aparecem depois de o relógio mandar os dele
                Grupo {
                    titulo: "Toques no orbe"
                    descricao: "O que cada número de toques faz no relógio: todos curtos, ou o último segurado."
                    visible: raiz.relogioConhecido
                    Repeater {
                        id: rwToques
                        model: 4
                        LinhaCombo {
                            titulo: index === 0 ? "1 toque" : (index + 1) + " toques"
                            subtitulo: raiz.descricaoToque[efetivo] || ""
                            itens: raiz.acoesToque
                        }
                    }
                    Repeater {
                        id: rwSegurar
                        model: 4
                        LinhaCombo {
                            // os toques antes, o último segurado
                            titulo: index === 0 ? "Segura" : index === 1 ? "Toca e segura" : index + " toques e segura"
                            subtitulo: raiz.descricaoToque[efetivo] || ""
                            itens: raiz.acoesSegurar
                        }
                    }
                    LinhaSwitch {
                        id: rwLive
                        titulo: "Abrir já no live"
                        subtitulo: "o toque que abre o orbe fechado já entra no live"
                    }
                }
                Grupo {
                    titulo: "Gestos"
                    descricao: "Sacudidas do pulso. A calibração se faz no relógio."
                    visible: raiz.relogioConhecido
                    LinhaSwitch {
                        id: rwSacudida
                        titulo: "Uma sacudida abre o orbe"
                        subtitulo: "já ouvindo"
                    }
                    Linha {
                        titulo: "Calibração do abrir"
                        subtitulo: raiz.calibracao.sacudida_fora > 0
                                   ? "fora " + raiz.um(raiz.calibracao.sacudida_fora) + " · dentro "
                                     + raiz.um(raiz.calibracao.sacudida_dentro) + " rad/s"
                                   : "padrão do relógio"
                        visible: rwSacudida.ligado
                        Botao {
                            texto: "Padrão"
                            visible: raiz.calibracao.sacudida_fora > 0
                            onClicado: raiz.calibracao = Object.assign({}, raiz.calibracao, { sacudida_fora: 0, sacudida_dentro: 0 })
                        }
                    }
                    LinhaSwitch {
                        id: rwSair
                        titulo: "Sacudida para fora sai do orbe"
                    }
                    Linha {
                        titulo: "Calibração do sair"
                        subtitulo: raiz.calibracao.sair_fora > 0 ? "fora " + raiz.um(raiz.calibracao.sair_fora) + " rad/s"
                                                                : "padrão do relógio"
                        visible: rwSair.ligado
                        Botao {
                            texto: "Padrão"
                            visible: raiz.calibracao.sair_fora > 0
                            onClicado: raiz.calibracao = Object.assign({}, raiz.calibracao, { sair_fora: 0 })
                        }
                    }
                }
                Grupo {
                    titulo: "Ordem da lista"
                    descricao: "A ordem dos orbes no relógio."
                    visible: raiz.relogioConhecido
                    Repeater {
                        model: raiz.ordemRelogio
                        Linha {
                            titulo: (index + 1) + ". " + (ponte.nomesSkin[modelData] || modelData)
                            BotaoIcone {
                                icone: "go-up-symbolic"
                                ativo: index > 0
                                onClicado: raiz.moverOrbe(index, -1)
                            }
                            BotaoIcone {
                                icone: "go-down-symbolic"
                                ativo: index < raiz.ordemRelogio.length - 1
                                onClicado: raiz.moverOrbe(index, 1)
                            }
                        }
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
    // todos os orbes, e a voz de cada um por provedor (voz.orbes)
    readonly property var skinsTodas: ["ofanim", "ofanim_alado", "serafim_gravura", "olho", "humana", "anel"]
    property var vozesOrbes: ({})
    function coletarVozesOrbes() {
        var m = JSON.parse(JSON.stringify(vozesOrbes || {}))
        var prov = ttsEfetivo
        var lista = prov === "gemini" || prov === "piper"
        var d = {}
        for (var i = 0; i < skinsTodas.length; i++) {
            var v = lista ? rVozesLista.itemAt(i).efetivo : rVozesTexto.itemAt(i).texto.trim()
            if (v) d[skinsTodas[i]] = v
        }
        m[prov] = d
        return m
    }
    // a imagem do fundo do relógio (relogio.papel); vazio: o papel de parede do PC
    property string papelRelogio: ""
    FileDialog {
        id: dialogoPapel
        title: "Plano de fundo do relógio"
        nameFilters: ["Imagens (*.png *.jpg *.jpeg *.webp *.bmp)"]
        onAccepted: raiz.papelRelogio = decodeURIComponent(String(selectedFile).replace(/^file:\/\//, ""))
    }
    // os orbes do relógio, na ordem da lista de lá
    readonly property var skinsRelogio: ["anel", "serafim_gravura", "ofanim", "ofanim_alado", "olho", "humana"]
    // o relógio já mandou os ajustes que só ele conhecia (os toques, a ordem, os gestos);
    // antes disso, essas linhas não aparecem e nada delas vai para lá
    property bool relogioConhecido: false
    readonly property var camposDoRelogio: ["toques", "segurar", "live", "fundo", "ordem", "sacudida", "sair",
                                            "sacudida_fora", "sacudida_dentro", "sair_fora"]
    property var ordemRelogio: []
    // as calibrações das sacudidas, em rad/s; 0 volta ao padrão do relógio
    property var calibracao: ({ sacudida_fora: 0, sacudida_dentro: 0, sair_fora: 0 })
    readonly property var acoesToque: [
        { id: "abrir", nome: "Abrir" }, { id: "live", nome: "Live" }, { id: "encerrar", nome: "Encerrar" },
        { id: "historico", nome: "Histórico" }, { id: "nada", nome: "Nada" }
    ]
    readonly property var acoesSegurar: acoesToque.slice(0, 4).concat([{ id: "falar", nome: "Falar" }, { id: "nada", nome: "Nada" }])
    readonly property var descricaoToque: ({
        abrir: "fechado, abre; aberto, entra no live; no live, interrompe",
        live: "liga o live, abrindo se precisar; ligado, fecha",
        encerrar: "fecha a sessão e, com o Claude, a sessão dele no PC",
        historico: "as sessões passadas do agente, para retomar uma",
        falar: "a fala vai enquanto o dedo fica no orbe"
    })
    function um(v) { return Number(v).toFixed(1).replace(".", ",") }
    function moverOrbe(i, passo) {
        var l = ordemRelogio.slice()
        var j = i + passo
        if (j < 0 || j >= l.length) return
        var x = l[i]
        l[i] = l[j]
        l[j] = x
        ordemRelogio = l
    }
    // o tamanho de cada skin (orbe.tamanhos); a que não tem o seu usa o comum (orbe.tamanho).
    // O slider mostra o da skin escolhida; trocar de skin guarda o dela antes
    property var tamanhos: ({})
    property real tamanhoComum: 1.0
    property string skinDoTamanho: ""
    function tamanhoDe(s) { var t = tamanhos[s]; return t === undefined || t === null ? tamanhoComum : t }
    function guardarTamanho() {
        if (skinDoTamanho && Math.abs(tamanho.valor - tamanhoDe(skinDoTamanho)) > 0.001)
            tamanhos[skinDoTamanho] = tamanho.valor
    }
    onSkinChanged: {
        guardarTamanho()
        skinDoTamanho = skin
        tamanho.definir(tamanhoDe(skin))
        puxarAgenteDaSkin()
    }
    // O agente de cada skin mora na lista "Agente de cada orbe" (o mapa que o
    // relógio também edita); a linha do agente na aba Agente é a da skin em
    // uso. Sem escolha ("" = o padrão), o relógio usa o Claude, e o PC também
    // quando o relógio está ligado; sem ele, o agente do config, como antes.
    function linhaDaSkin(sk) {
        for (var i = 0; i < agentesOrbe.count; i++)
            if (agentesOrbe.itemAt(i).skin === sk) return agentesOrbe.itemAt(i)
        return null
    }
    function agenteDaSkin(sk) {
        var l = linhaDaSkin(sk)
        if (l && l.efetivo) return l.efetivo
        return rRelogio.ligado ? "claude" : ponte.cfg.agente.tipo
    }
    function puxarAgenteDaSkin() {
        var tipo = agenteDaSkin(skin)
        if (rAgente.efetivo === tipo) return
        rAgente.valor = tipo
        mudouAgente(false)
    }
    function empurrarAgenteDaSkin() {
        var l = linhaDaSkin(skin)
        if (l) l.valor = rAgente.efetivo === "claude" ? "" : rAgente.efetivo
    }
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
        rwEtapas.ligado = !!aj.etapas
        rwIdiomaEtapas.valor = aj.idioma_etapas || "pt"
        rwTexto.ligado = !!aj.texto
        rwSeguir.ligado = !!aj.seguir_pc
        rwGlitch.ligado = !!aj.glitch
        rwLinhas.ligado = aj.linhas === undefined ? true : !!aj.linhas
        for (var j = 0; j < rwTamanhos.count; j++) {
            var t = rwTamanhos.itemAt(j)
            var proprio = (aj.tamanhos || {})[t.skin]
            t.valor = proprio === undefined || proprio === null ? (aj.tamanho === undefined ? 1.0 : aj.tamanho) : proprio
        }
        for (var i = 0; i < agentesOrbe.count; i++) {
            var l = agentesOrbe.itemAt(i)
            l.valor = (aj.agentes && aj.agentes[l.skin]) || ""
        }
        // o relógio manda todos de uma vez: sem algum, nenhum aparece
        relogioConhecido = camposDoRelogio.every(function (k) { return aj[k] !== null && aj[k] !== undefined })
        if (relogioConhecido) {
            for (var k = 0; k < rwToques.count; k++)
                rwToques.itemAt(k).valor = aj.toques[k] || "nada"
            for (var s = 0; s < rwSegurar.count; s++)
                rwSegurar.itemAt(s).valor = aj.segurar[s] || "nada"
            rwLive.ligado = !!aj.live
            rwFundo.ligado = !!aj.fundo
            rwSacudida.ligado = !!aj.sacudida
            rwSair.ligado = !!aj.sair
            ordemRelogio = aj.ordem
            calibracao = { sacudida_fora: aj.sacudida_fora, sacudida_dentro: aj.sacudida_dentro, sair_fora: aj.sair_fora }
        }
        ajustesVistos = JSON.stringify(coletarAjustes(aj))
        puxarAgenteDaSkin()
    }
    function coletarAjustes(base) {
        var aj = JSON.parse(JSON.stringify(base))
        aj.voz = rwVoz.ligado
        aj.voz_pc = rwVozPc.ligado
        aj.microfone = rwMic.ligado
        aj.vibrar = rwVibrar.ligado
        aj.etapas = rwEtapas.ligado
        aj.idioma_etapas = rwIdiomaEtapas.efetivo
        aj.texto = rwTexto.ligado
        aj.seguir_pc = rwSeguir.ligado
        aj.glitch = rwGlitch.ligado
        aj.linhas = rwLinhas.ligado
        aj.tamanhos = aj.tamanhos || {}
        for (var j = 0; j < rwTamanhos.count; j++) {
            var t = rwTamanhos.itemAt(j)
            aj.tamanhos[t.skin] = Math.round(t.valor * 100) / 100
        }
        aj.agentes = aj.agentes || {}
        for (var i = 0; i < agentesOrbe.count; i++) {
            var l = agentesOrbe.itemAt(i)
            aj.agentes[l.skin] = l.efetivo
        }
        if (relogioConhecido) {
            aj.toques = []
            for (var k = 0; k < rwToques.count; k++)
                aj.toques.push(rwToques.itemAt(k).efetivo)
            aj.segurar = []
            for (var s = 0; s < rwSegurar.count; s++)
                aj.segurar.push(rwSegurar.itemAt(s).efetivo)
            aj.live = rwLive.ligado
            aj.fundo = rwFundo.ligado
            aj.sacudida = rwSacudida.ligado
            aj.sair = rwSair.ligado
            aj.ordem = ordemRelogio.slice()
            aj.sacudida_fora = calibracao.sacudida_fora
            aj.sacudida_dentro = calibracao.sacudida_dentro
            aj.sair_fora = calibracao.sair_fora
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
        rSeguir.ligado = !!c.relogio.seguir
        papelRelogio = c.relogio.papel || ""
        rwPapel.valor = papelRelogio ? "imagem" : "pc"
        carregarAjustes(c.relogio.ajustes)
        rTerminal.texto = a.terminal
        rClaudePasta.texto = a.claude_pasta
        for (var m = 0; m < rModos.count; m++) {
            var lm = rModos.itemAt(m)
            lm.valor = (a.modos || {})[lm.agente] || "terminal"
        }

        rStt.valor = v.stt_modelo
        rIdioma.texto = v.stt_idioma
        rTts.valor = v.tts_provedor
        rGvoz.valor = v.gemini_voz
        rXvoz.texto = v.xai_voz
        rEvoz.texto = v.elevenlabs_voz
        rPvoz.valor = v.piper_voz
        vozesOrbes = v.orbes || {}

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
        // antes da skin: trocá-la já põe o tamanho dela no slider
        skinDoTamanho = ""
        tamanhoComum = o.tamanho === undefined ? 1.0 : o.tamanho
        tamanhos = JSON.parse(JSON.stringify(o.tamanhos || {}))
        // o Seraphim desenhado saiu; quem o tinha fica com o da gravura (o
        // Shoggoth e a Entidade também saíram: Ophanim)
        var sk = o.skin === "serafim" ? "serafim_gravura" : o.skin
        skin = ["ofanim", "ofanim_alado", "serafim_gravura", "olho", "humana", "anel"].indexOf(sk) >= 0 ? sk : "ofanim"
        rGlitch.ligado = !!o.glitch
        rVidro.ligado = !!o.vidro
        rSombra.definir(o.sombra === undefined ? 0.45 : o.sombra)
        rTexto.valor = o.texto || "lado"
        rMover.ligado = !!o.mover
        skinDoTamanho = skin
        tamanho.definir(tamanhoDe(skin))
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
        cfg.relogio.seguir = rSeguir.ligado
        cfg.relogio.papel = rwPapel.efetivo === "imagem" ? papelRelogio : ""
        cfg.relogio.ajustes = coletarAjustes(raiz.ajustesBase)
        a.terminal = rTerminal.texto.trim() || "ghostty"
        a.claude_pasta = rClaudePasta.texto.trim()
        a.modos = Object.assign({}, a.modos || {})
        for (var m = 0; m < rModos.count; m++)
            a.modos[rModos.itemAt(m).agente] = rModos.itemAt(m).efetivo
        v.stt_modelo = rStt.efetivo
        v.stt_idioma = rIdioma.texto.trim() || "pt"
        v.tts_provedor = rTts.efetivo
        v.gemini_voz = rGvoz.efetivo
        v.xai_voz = rXvoz.texto.trim()
        v.elevenlabs_voz = rEvoz.texto.trim()
        v.piper_voz = rPvoz.efetivo
        v.orbes = coletarVozesOrbes()
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
        guardarTamanho()
        cfg.orbe.tamanhos = cfg.orbe.tamanhos || {}
        for (var s in raiz.tamanhos) {
            if (raiz.tamanhos[s] !== null && raiz.tamanhos[s] !== undefined)
                cfg.orbe.tamanhos[s] = Math.round(raiz.tamanhos[s] * 100) / 100
        }
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
