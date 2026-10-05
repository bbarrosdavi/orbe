package io.hermes.orbe.ui

import androidx.compose.animation.AnimatedContent
import androidx.compose.animation.core.tween
import androidx.compose.animation.fadeIn
import androidx.compose.animation.fadeOut
import androidx.compose.animation.scaleIn
import androidx.compose.animation.togetherWith
import androidx.compose.foundation.gestures.awaitEachGesture
import androidx.compose.foundation.gestures.awaitFirstDown
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.BoxWithConstraints
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.runtime.Composable
import androidx.compose.runtime.CompositionLocalProvider
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberUpdatedState
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.input.pointer.pointerInput
import androidx.compose.ui.input.pointer.util.VelocityTracker
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.platform.LocalDensity
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import androidx.wear.compose.foundation.lazy.TransformingLazyColumnState
import io.hermes.orbe.OrbeViewModel
import io.hermes.orbe.R
import io.hermes.orbe.dados.AgenteInfo
import io.hermes.orbe.dados.Ajustes
import io.hermes.orbe.dados.Ligacao
import io.hermes.orbe.gesto.Sacudida
import io.hermes.orbe.orbe.Estado
import io.hermes.orbe.orbe.Retrato
import io.hermes.orbe.orbe.Skin
import kotlin.math.abs
import kotlinx.coroutines.delay

/** O que o teclado do relógio edita. */
enum class Campo(val rotulo: String) {
    SERVIDOR("Endereço do computador"),
    TOKEN("Token do relógio"),
}

/** As abas do menu, na ordem da gaveta; cada uma rola sozinha. */
enum class Aba(val nome: String, val icone: Int, val descricao: String) {
    CONEXAO("Conexão", R.drawable.ic_conexao, "O daemon do Orbe no computador, pela ponte do relógio."),
    SKINS("Skins", R.drawable.ic_skins, "A skin em tela, o tamanho de cada uma e a ordem da lista."),
    /** a sessão de voz e o agente de cada skin, em dois grupos */
    AGENTES("Agentes", R.drawable.ic_agentes, ""),
    APARENCIA("Aparência", R.drawable.ic_aparencia, ""),
    VOZ("Voz", R.drawable.ic_voz, ""),
    GESTOS(
        "Gestos", R.drawable.ic_gestos,
        "Com a tela acesa, uma sacudida do pulso para fora e de volta abre o orbe; duas são do HinaWatch. " +
            "Com o orbe aberto, uma sacudida só para fora sai dele.",
    ),
}

/** Altura da figura no cartão de avatar (a do app: 100 dp de cartão, menos o nome e a margem). */
private val ALTURA_CARTAO = 71.dp

/** Puxão que conta no menu: distância ou velocidade (as do HinaWatch). */
private val VOLTA_DISTANCIA = 40.dp
private val VOLTA_VELOCIDADE = 400.dp

/**
 * O menu: o app do Orbe no pulso. Mesmo desenho do desktop (o Ophanim no topo,
 * as linhas em caixas de vidro sobre o papel de parede, os cartões dos
 * avatares, o slider com o orbe de botão), só com o que cabe ao relógio; voz e
 * conversa continuam no app do computador, que também edita estes ajustes (a
 * aba Relógio).
 *
 * Entra-se pela gaveta, como no HinaWatch: um botão por aba, e cada aba é uma
 * lista que rola em roda. Puxar para a direita volta um nível (da aba à
 * gaveta, da gaveta ao orbe); para a esquerda, de qualquer lugar do menu,
 * volta ao orbe (a página do OrbeApp). O fundo não é desta tela: fica parado
 * atrás do orbe e do menu.
 */
@Composable
fun TelaAjustes(
    vm: OrbeViewModel,
    gaveta: TransformingLazyColumnState,
    lista: TransformingLazyColumnState,
    /** a aba aberta; null = a gaveta */
    aba: Aba?,
    abrir: (Aba?) -> Unit,
    redonda: Boolean,
    /** o menu está na tela (ou entrando): as miniaturas andam */
    visivel: Boolean,
    editar: (Campo) -> Unit,
    pedirMicrofone: () -> Unit,
    /** a permissão do microfone já foi dada */
    podeGravar: () -> Boolean,
    /** volta à página do orbe */
    aoOrbe: () -> Unit,
    calibrar: (Calibracao) -> Unit,
    modifier: Modifier = Modifier,
) {
    val ajustes by vm.ajustes.collectAsStateWithLifecycle()
    val aparencia by vm.aparencia.collectAsStateWithLifecycle()
    val retrato by vm.retrato.collectAsStateWithLifecycle()
    val ligacao by vm.ligacao.collectAsStateWithLifecycle()
    val agentesPc by vm.agentesPc.collectAsStateWithLifecycle()
    val tema = LocalTema.current

    val passo = remember { mutableIntStateOf(0) }
    LaunchedEffect(visivel) {
        while (visivel) {
            delay(Previas.PASSO_MS)
            passo.intValue++
        }
    }

    // lidos na hora do gesto: o detector nasce uma vez só
    val abaAgora by rememberUpdatedState(aba)
    val abrirAgora by rememberUpdatedState(abrir)
    val orbeAgora by rememberUpdatedState(aoOrbe)

    BoxWithConstraints(
        modifier
            .fillMaxSize()
            .puxar(
                esquerda = { orbeAgora() },
                direita = { if (abaAgora != null) abrirAgora(null) else orbeAgora() },
            ),
    ) {
        // no mostrador redondo o conteúdo fica na faixa do meio, onde o círculo é largo
        val margem = maxWidth * (if (redonda) 0.12f else 0.05f)
        val largura = maxWidth - margem * 2
        val topo = ChavePrevia(Papel.TOPO, Skin.OFANIM, largura, 84.dp, glitch = true, linhas = true, tema.accent, tema.anel, tema.fundo)
        val cartao = { skin: Skin ->
            ChavePrevia(
                Papel.CARTAO, skin, larguraCartao(largura), ALTURA_CARTAO,
                aparencia.glitch, aparencia.linhas, tema.accent, tema.anel, tema.fundo,
            )
        }
        // todas pedidas de saída: a lista só monta o item quando ele rola para a
        // tela, e aí desenhar a prévia já disputaria a GPU com a rolagem
        val ctx = LocalContext.current
        val densidade = LocalDensity.current.density
        LaunchedEffect(largura, aparencia.glitch, aparencia.linhas, tema) {
            Previas.pedir(ctx, topo, densidade)
            Skin.entries.forEach { Previas.pedir(ctx, cartao(it), densidade) }
        }

        CompositionLocalProvider(LocalQuadro provides passo) {
            AnimatedContent(
                aba,
                transitionSpec = { (fadeIn(tween(180)) + scaleIn(tween(180), initialScale = 0.94f)) togetherWith fadeOut(tween(120)) },
                label = "aba",
            ) { a ->
                if (a == null) {
                    Menu(gaveta, margem) {
                        item {
                            Column(horizontalAlignment = Alignment.CenterHorizontally) {
                                Miniatura(topo, Modifier.size(largura, 84.dp))
                                Texto("ORBE", Estilo.mono.copy(letterSpacing = 3.sp), cor = Estilo.texto.alfa(0.6f))
                            }
                        }
                        Aba.entries.chunked(3).forEach { fileira ->
                            item {
                                Row(
                                    Modifier.fillMaxWidth(),
                                    horizontalArrangement = Arrangement.spacedBy(4.dp, Alignment.CenterHorizontally),
                                ) { fileira.forEach { b -> BotaoGaveta(b.icone, b.nome) { abrir(b) } } }
                            }
                        }
                    }
                } else {
                    Menu(lista, margem) {
                        item {
                            Column(Modifier.fillMaxWidth(), horizontalAlignment = Alignment.CenterHorizontally) {
                                Icone(a.icone, Estilo.accent, Modifier.size(20.dp))
                                Texto(a.nome, Estilo.grupo.copy(fontSize = 13.sp), alinhar = TextAlign.Center)
                                if (a.descricao.isNotEmpty()) {
                                    Texto(
                                        a.descricao, Estilo.subtitulo, Modifier.padding(top = 4.dp, start = 4.dp, end = 4.dp),
                                        cor = Estilo.texto.alfa(0.55f), alinhar = TextAlign.Center,
                                    )
                                }
                            }
                        }
                        when (a) {
                            Aba.CONEXAO -> conexao(ajustes, ligacao, editar)
                            Aba.SKINS -> skins(vm, ajustes, aparencia.skin, cartao)
                            Aba.AGENTES -> {
                                sessao(vm, ajustes, retrato, ligacao is Ligacao.Conectada, podeGravar)
                                agentes(vm, ajustes, agentesPc)
                            }
                            Aba.APARENCIA -> aparencia(vm, ajustes, aparencia.glitch, aparencia.linhas)
                            Aba.VOZ -> voz(vm, ajustes, ligacao as? Ligacao.Conectada, pedirMicrofone)
                            Aba.GESTOS -> gestos(vm, ajustes, pedirMicrofone, calibrar)
                        }
                    }
                }
            }
        }
    }
}

private fun MenuEscopo.conexao(ajustes: Ajustes, ligacao: Ligacao, editar: (Campo) -> Unit) {
    linha {
        Linha("Servidor", subtitulo = ajustes.servidor.ifEmpty { "toque para informar" }, aoClicar = { editar(Campo.SERVIDOR) })
    }
    linha {
        Linha(
            "Token",
            subtitulo = if (ajustes.token.isEmpty()) "o que o hermes_voice_relogio.py mostra" else "•".repeat(ajustes.token.length.coerceAtMost(12)),
            aoClicar = { editar(Campo.TOKEN) },
        )
    }
    linha {
        Linha("Estado") {
            Etiqueta(
                when (ligacao) {
                    is Ligacao.Conectada -> "conectado"
                    is Ligacao.Conectando -> "conectando…"
                    is Ligacao.Falha -> ligacao.motivo
                    is Ligacao.SemServidor -> "sem servidor"
                },
            )
        }
    }
}

private fun MenuEscopo.sessao(vm: OrbeViewModel, ajustes: Ajustes, retrato: Retrato, conectada: Boolean, podeGravar: () -> Boolean) {
    grupo(
        "Sessão",
        "No orbe: um toque abre, outro entra no live, segurar manda uma gravação. " +
            "No live, um toque interrompe a fala ou, com o orbe ouvindo, fecha. Três toques encerram a sessão e o Claude Code no PC.",
    )
    linha {
        Linha(
            if (retrato.visivel) "Aberta" else "Fechada",
            subtitulo = if (retrato.visivel) Estado.rotulos[retrato.estado] else "tocar no orbe também abre",
            ativo = conectada,
        ) {
            Botao(if (retrato.visivel) "Fechar" else "Abrir", ligado = retrato.visivel, ativo = conectada) { vm.alternarSessao() }
        }
    }
    linha {
        LinhaSwitch(
            "Modo live", retrato.travado,
            subtitulo = "os turnos seguem sem tocar, até fechar",
            ativo = conectada && retrato.visivel,
        ) { vm.travar(it, podeGravar()) }
    }
    linha {
        LinhaSwitch("Abrir já no live", ajustes.live, subtitulo = "um toque no orbe abre direto no live") { vm.live(it) }
    }
}

private fun MenuEscopo.skins(vm: OrbeViewModel, ajustes: Ajustes, emTela: Skin, cartao: (Skin) -> ChavePrevia) {
    val skins = ajustes.skins()
    skins.chunked(2).forEach { par ->
        item {
            Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                par.forEach { skin ->
                    Cartao(cartao(skin), marcado = emTela == skin, modifier = Modifier.weight(1f)) { vm.skin(skin) }
                }
            }
        }
    }
    linha {
        SliderOrbe(ajustes.tamanhoDe(emTela), Ajustes.TAMANHO_MIN, Ajustes.TAMANHO_MAX, cartao(emTela)) { vm.tamanho(it) }
    }
    grupo("Ordem da lista", "De cima para baixo, como a lista do orbe rola; depois do último vem o primeiro. Só aqui no relógio.")
    skins.forEachIndexed { i, skin ->
        linha {
            Linha("${i + 1}. ${skin.nome}") {
                BotaoIcone(R.drawable.ic_subir, ativo = i > 0) { vm.mover(skin, -1) }
                BotaoIcone(R.drawable.ic_descer, ativo = i < skins.lastIndex) { vm.mover(skin, +1) }
            }
        }
    }
}

private fun MenuEscopo.agentes(vm: OrbeViewModel, ajustes: Ajustes, agentesPc: List<AgenteInfo>) {
    grupo(
        "Agente de cada skin",
        "Rolar a lista troca de orbe e, com ele, de agente. Toque para trocar. À direita de cada orbe do Claude, " +
            "com dois dedos, ficam as sessões abertas no PC, cada uma numa cor, com o título no alto e a pasta embaixo.",
    )
    ajustes.skins().forEach { skin ->
        linha {
            val id = ajustes.agentes[skin.id].orEmpty()
            val nome = when {
                id.isEmpty() || id == "claude" -> agentesPc.firstOrNull { it.id == "claude" }?.nome ?: "Claude Code"
                else -> agentesPc.firstOrNull { it.id == id }?.nome ?: id
            }
            Linha(
                skin.nome, subtitulo = nome,
                ativo = agentesPc.size > 1,
                aoClicar = { vm.proximoAgente(skin) },
            )
        }
    }
}

private fun MenuEscopo.aparencia(vm: OrbeViewModel, ajustes: Ajustes, glitch: Boolean, linhas: Boolean) {
    linha {
        LinhaSwitch("Glitch", glitch, subtitulo = "aberração cromática e faixas arrancadas") { vm.glitch(it) }
    }
    linha {
        LinhaSwitch("Linhas de TV", linhas, subtitulo = "linhas de varredura, como num tubo") { vm.linhas(it) }
    }
    linha {
        LinhaSwitch("Fundo atrás do orbe", ajustes.fundo, subtitulo = "só aqui no relógio: o mesmo do menu, o papel de parede do PC") { vm.fundo(it) }
    }
    linha {
        LinhaSwitch("Texto do raciocínio", ajustes.texto, subtitulo = "só aqui no relógio: as linhas do agente, abaixo do orbe") { vm.texto(it) }
    }
    linha {
        LinhaSwitch("Seguir o orbe do PC", ajustes.seguirPc, subtitulo = "o avatar e o glitch vêm do computador") { vm.seguirPc(it) }
    }
}

private fun MenuEscopo.voz(vm: OrbeViewModel, ajustes: Ajustes, ponte: Ligacao.Conectada?, pedirMicrofone: () -> Unit) {
    linha {
        LinhaSwitch("Microfone do relógio", ajustes.microfone, subtitulo = "segurando o orbe, a fala vem daqui e não do computador") {
            vm.microfone(it)
            if (it) pedirMicrofone()
        }
    }
    if (vm.temSaidaDeSom) {
        // o orbe de pulso fala só por aqui; o daemon do desktop também tem a voz do PC
        linha {
            LinhaSwitch(
                "Voz no relógio", ajustes.voz,
                subtitulo = when {
                    ponte?.voz == false -> "esta ponte fala pelo computador"
                    ponte?.vozPc == true -> "a resposta toca aqui; desligada, toca no computador"
                    else -> "a resposta toca aqui; desligada, vem em texto"
                },
            ) { vm.voz(it) }
        }
        if (ponte?.vozPc == true && ajustes.voz) {
            linha {
                LinhaSwitch("Voz também no PC", ajustes.vozPc, subtitulo = "a resposta toca nos dois") { vm.vozPc(it) }
            }
        }
    }
    linha {
        LinhaSwitch("Vibrar", ajustes.vibrar, subtitulo = "ao segurar e ao soltar o orbe") { vm.vibrar(it) }
    }
}

private fun MenuEscopo.gestos(vm: OrbeViewModel, ajustes: Ajustes, pedirMicrofone: () -> Unit, calibrar: (Calibracao) -> Unit) {
    linha {
        LinhaSwitch("Uma sacudida abre o orbe", ajustes.sacudida, subtitulo = "já ouvindo, pelo microfone do relógio") {
            vm.sacudida(it)
            if (it) pedirMicrofone()
        }
    }
    linha {
        Linha(
            "Calibrar o abrir",
            subtitulo = "fora ${um(ajustes.sacudidaFora)} · dentro ${um(ajustes.sacudidaDentro)} rad/s",
            ativo = ajustes.sacudida,
            aoClicar = { calibrar(Calibracao.ABRIR) },
        )
    }
    linha {
        LinhaSwitch("Sacudida para fora sai do orbe", ajustes.sair, subtitulo = "com o orbe aberto, como no HinaWatch") { vm.sair(it) }
    }
    linha {
        Linha(
            "Calibrar o sair",
            subtitulo = if (ajustes.sairFora > 0f) "fora ${um(ajustes.sairFora)} rad/s" else "padrão: fora ${um(Sacudida.FORA_MIN)} rad/s",
            ativo = ajustes.sair,
            aoClicar = { calibrar(Calibracao.SAIR) },
        )
    }
}

/**
 * Puxão na horizontal, solto no menu: para a esquerda ou para a direita. Olha o
 * gesto depois dos filhos e não consome nada; o que a lista (rolando) ou o
 * slider já tomaram não conta. No menu o pager do OrbeApp não arrasta: os dois
 * lados são daqui.
 */
private fun Modifier.puxar(esquerda: () -> Unit, direita: () -> Unit): Modifier = this.then(
    Modifier.pointerInput(Unit) {
        val distancia = VOLTA_DISTANCIA.toPx()
        val rapido = VOLTA_VELOCIDADE.toPx()
        awaitEachGesture {
            val baixo = awaitFirstDown(requireUnconsumed = false)
            val rastro = VelocityTracker()
            rastro.addPosition(baixo.uptimeMillis, baixo.position)
            var tomado = false
            var dx = 0f
            var dy = 0f
            while (true) {
                val e = awaitPointerEvent()
                val c = e.changes.firstOrNull { it.id == baixo.id } ?: break
                if (e.changes.size > 1 || (c.pressed && c.isConsumed)) tomado = true
                rastro.addPosition(c.uptimeMillis, c.position)
                dx = c.position.x - baixo.position.x
                dy = c.position.y - baixo.position.y
                if (!c.pressed) break
            }
            if (tomado || abs(dx) <= abs(dy)) return@awaitEachGesture
            val v = rastro.calculateVelocity().x
            when {
                dx < -distancia || v < -rapido -> esquerda()
                dx > distancia || v > rapido -> direita()
            }
        }
    },
)

private fun um(v: Float) = "%.1f".format(v).replace('.', ',')

/** A largura da figura num cartão de avatar: dois cartões por fileira, 8 dp entre eles e 4 de margem dentro. */
private fun larguraCartao(largura: Dp): Dp = (largura - 8.dp) / 2 - 8.dp
