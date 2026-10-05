package io.hermes.orbe.ui

import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.BoxWithConstraints
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.runtime.Composable
import androidx.compose.runtime.CompositionLocalProvider
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.remember
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.platform.LocalDensity
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import androidx.wear.compose.foundation.lazy.TransformingLazyColumnState
import io.hermes.orbe.OrbeViewModel
import io.hermes.orbe.dados.Ajustes
import io.hermes.orbe.dados.Ligacao
import io.hermes.orbe.orbe.Estado
import io.hermes.orbe.orbe.Skin
import kotlinx.coroutines.delay

/** O que o teclado do relógio edita. */
enum class Campo(val rotulo: String) {
    SERVIDOR("Endereço do computador"),
    TOKEN("Token do relógio"),
}

/** Altura da figura no cartão de avatar (a do app: 100 dp de cartão, menos o nome e a margem). */
private val ALTURA_CARTAO = 71.dp

/**
 * O menu: o app do Orbe no pulso. Mesmo desenho do desktop (o Ophanim no topo,
 * as linhas em caixas de vidro sobre o papel de parede, os cartões dos
 * avatares, o slider com o orbe de botão), só com o que cabe ao relógio; voz e
 * conversa continuam no app do computador, que também edita estes ajustes (a
 * aba Relógio). A lista rola como as do HinaWatch: cada linha é um item da
 * roda do Wear, e só as que estão na tela existem.
 */
@Composable
fun TelaAjustes(
    vm: OrbeViewModel,
    lista: TransformingLazyColumnState,
    redonda: Boolean,
    /** o menu está na tela (ou entrando): as miniaturas andam */
    visivel: Boolean,
    editar: (Campo) -> Unit,
    pedirMicrofone: () -> Unit,
    /** a permissão do microfone já foi dada */
    podeGravar: () -> Boolean,
    aoPrevia: () -> Unit,
    calibrar: () -> Unit,
    modifier: Modifier = Modifier,
) {
    val ajustes by vm.ajustes.collectAsStateWithLifecycle()
    val aparencia by vm.aparencia.collectAsStateWithLifecycle()
    val retrato by vm.retrato.collectAsStateWithLifecycle()
    val ligacao by vm.ligacao.collectAsStateWithLifecycle()
    val previa by vm.previa.collectAsStateWithLifecycle()
    val agentesPc by vm.agentesPc.collectAsStateWithLifecycle()
    val conectada = ligacao is Ligacao.Conectada
    val tema = LocalTema.current

    val passo = remember { mutableIntStateOf(0) }
    LaunchedEffect(visivel) {
        while (visivel) {
            delay(Previas.PASSO_MS)
            passo.intValue++
        }
    }

    BoxWithConstraints(modifier.fillMaxSize()) {
        FundoVidro()
        // no mostrador redondo o conteúdo fica na faixa do meio, onde o círculo é largo
        val margem = maxWidth * (if (redonda) 0.12f else 0.05f)
        val largura = maxWidth - margem * 2
        val topo = ChavePrevia(Papel.TOPO, Skin.OFANIM, largura, 84.dp, glitch = true, linhas = true, tema.accent, tema.anel, tema.fundo)
        fun cartao(skin: Skin) = ChavePrevia(
            Papel.CARTAO, skin, larguraCartao(largura), ALTURA_CARTAO,
            aparencia.glitch, aparencia.linhas, tema.accent, tema.anel, tema.fundo,
        )
        // todas pedidas de saída: a lista só monta o item quando ele rola para a
        // tela, e aí desenhar a prévia já disputaria a GPU com a rolagem
        val ctx = LocalContext.current
        val densidade = LocalDensity.current.density
        LaunchedEffect(largura, aparencia.glitch, aparencia.linhas, tema) {
            Previas.pedir(ctx, topo, densidade)
            Skin.entries.forEach { Previas.pedir(ctx, cartao(it), densidade) }
        }

        CompositionLocalProvider(LocalQuadro provides passo) {
            Menu(lista, margem) {
                item {
                    Column(horizontalAlignment = Alignment.CenterHorizontally) {
                        Miniatura(topo, Modifier.size(largura, 84.dp))
                        Texto("ORBE", Estilo.mono.copy(letterSpacing = 3.sp), cor = Estilo.texto.alfa(0.6f))
                    }
                }

                grupo("Conexão", "O daemon do Orbe no computador, pela ponte do relógio.")
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
                            when (val l = ligacao) {
                                is Ligacao.Conectada -> "conectado"
                                is Ligacao.Conectando -> "conectando…"
                                is Ligacao.Falha -> l.motivo
                                is Ligacao.SemServidor -> "sem servidor"
                            },
                        )
                    }
                }

                grupo(
                    "Sessão de voz",
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

                grupo(
                    "Agente de cada orbe",
                    "Rolar a lista troca de orbe e, com ele, de agente. Toque para trocar. À direita de cada orbe do Claude, " +
                        "com dois dedos, ficam as sessões abertas no PC, cada uma numa cor e com a pasta embaixo.",
                )
                Skin.entries.forEach { skin ->
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

                grupo("Avatar do orbe")
                Skin.entries.chunked(2).forEach { par ->
                    item {
                        Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                            par.forEach { skin ->
                                Cartao(cartao(skin), marcado = aparencia.skin == skin, modifier = Modifier.weight(1f)) { vm.skin(skin) }
                            }
                        }
                    }
                }
                linha {
                    SliderOrbe(ajustes.tamanhoDe(aparencia.skin), Ajustes.TAMANHO_MIN, Ajustes.TAMANHO_MAX, cartao(aparencia.skin)) { vm.tamanho(it) }
                }
                linha {
                    LinhaSwitch("Glitch", aparencia.glitch, subtitulo = "aberração cromática e faixas arrancadas") { vm.glitch(it) }
                }
                linha {
                    LinhaSwitch("Linhas de TV", aparencia.linhas, subtitulo = "linhas de varredura, como num tubo") { vm.linhas(it) }
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

                grupo("Voz")
                linha {
                    LinhaSwitch("Microfone do relógio", ajustes.microfone, subtitulo = "segurando o orbe, a fala vem daqui e não do computador") {
                        vm.microfone(it)
                        if (it) pedirMicrofone()
                    }
                }
                if (vm.temSaidaDeSom) {
                    // o orbe de pulso fala só por aqui; o daemon do desktop também tem a voz do PC
                    val ponte = ligacao as? Ligacao.Conectada
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

                grupo("Sacudida", "Com a tela acesa, uma sacudida do pulso para fora e de volta. Duas são do HinaWatch.")
                linha {
                    LinhaSwitch("Uma sacudida abre o orbe", ajustes.sacudida, subtitulo = "já ouvindo, pelo microfone do relógio") {
                        vm.sacudida(it)
                        if (it) pedirMicrofone()
                    }
                }
                linha {
                    Linha(
                        "Calibrar",
                        subtitulo = "fora %.1f · dentro %.1f rad/s".format(ajustes.sacudidaFora, ajustes.sacudidaDentro).replace('.', ','),
                        ativo = ajustes.sacudida,
                        aoClicar = calibrar,
                    )
                }

                // ── rodapé ──
                item {
                    Column(Modifier.fillMaxWidth().padding(top = 10.dp), horizontalAlignment = Alignment.CenterHorizontally) {
                        Box(Modifier.fillMaxWidth().height(1.dp).background(Estilo.accent.alfa(0.12f)))
                        Vao(10.dp)
                        Botao(if (previa != null) "Fechar prévia" else "Pré-visualizar", ligado = previa != null) {
                            vm.alternarPrevia()
                            aoPrevia()
                        }
                        Vao(8.dp)
                        Texto(
                            if (previa != null) "prévia: $previa" else "o orbe passa por todos os estados",
                            Estilo.mono, cor = Estilo.texto.alfa(0.6f), alinhar = TextAlign.Center,
                        )
                    }
                }
            }
        }
    }
}

/** A largura da figura num cartão de avatar: dois cartões por fileira, 8 dp entre eles e 4 de margem dentro. */
private fun larguraCartao(largura: Dp): Dp = (largura - 8.dp) / 2 - 8.dp
