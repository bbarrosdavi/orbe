package io.hermes.orbe.ui

import androidx.compose.foundation.ScrollState
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
import androidx.compose.foundation.verticalScroll
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalDensity
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import io.hermes.orbe.OrbeViewModel
import io.hermes.orbe.dados.Ajustes
import io.hermes.orbe.dados.Ligacao
import io.hermes.orbe.orbe.Estado
import io.hermes.orbe.orbe.Skin

/** O que o teclado do relógio edita. */
enum class Campo(val rotulo: String) {
    SERVIDOR("Endereço do computador"),
    TOKEN("Token do relógio"),
}

/**
 * O menu: o app do Orbe no pulso. Mesmo desenho do desktop (o Ophanim no topo,
 * grupos em caixas de vidro, cartões vivos dos avatares, o slider com o orbe
 * de botão), só com o que cabe ao relógio; voz e conversa continuam no app do
 * computador, que também edita estes ajustes (a aba Relógio).
 */
@Composable
fun TelaAjustes(
    vm: OrbeViewModel,
    rolagem: ScrollState,
    redonda: Boolean,
    editar: (Campo) -> Unit,
    pedirMicrofone: () -> Unit,
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

    BoxWithConstraints(modifier.fillMaxSize().background(Estilo.fundo)) {
        // ── fundo de vidro: no desktop é o papel de parede borrado; aqui, um clarão do tema ──
        val larguraPx = with(LocalDensity.current) { maxWidth.toPx() }
        Box(
            Modifier.fillMaxSize().background(
                Brush.radialGradient(
                    listOf(Estilo.accent.alfa(0.13f), Color.Transparent),
                    center = Offset(larguraPx / 2, larguraPx * 0.30f), radius = larguraPx * 0.62f,
                ),
            ),
        )
        // no mostrador redondo o conteúdo fica na faixa do meio, onde o círculo é largo
        val margem = maxWidth * (if (redonda) 0.12f else 0.05f)
        Column(
            Modifier.fillMaxSize().verticalScroll(rolagem).padding(horizontal = margem),
            horizontalAlignment = Alignment.CenterHorizontally,
        ) {
            Vao(12.dp)
            Miniatura(Skin.OFANIM, Modifier.fillMaxWidth().height(84.dp), peso = 1.0, raio = 0.42f to 0.32f)
            Texto("ORBE", Estilo.mono.copy(letterSpacing = 3.sp), cor = Estilo.texto.alfa(0.6f))
            Vao(12.dp)

            Grupo(titulo = "Conexão", descricao = "O daemon do Orbe no computador, pela ponte do relógio.") {
                item {
                    Linha("Servidor", subtitulo = ajustes.servidor.ifEmpty { "toque para informar" }, aoClicar = { editar(Campo.SERVIDOR) })
                }
                item {
                    Linha(
                        "Token",
                        subtitulo = if (ajustes.token.isEmpty()) "o que o hermes_voice_relogio.py mostra" else "•".repeat(ajustes.token.length.coerceAtMost(12)),
                        aoClicar = { editar(Campo.TOKEN) },
                    )
                }
                item {
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
            }
            Vao(18.dp)

            Grupo(titulo = "Sessão de voz") {
                item {
                    Linha(
                        if (retrato.visivel) "Aberta" else "Fechada",
                        subtitulo = if (retrato.visivel) Estado.rotulos[retrato.estado] else "tocar no orbe também abre",
                        ativo = conectada,
                    ) {
                        Botao(if (retrato.visivel) "Fechar" else "Abrir", ligado = retrato.visivel, ativo = conectada) { vm.alternarSessao() }
                    }
                }
                item {
                    LinhaSwitch(
                        "Travar a sessão", retrato.travado,
                        subtitulo = "dois toques no orbe também travam",
                        ativo = conectada && retrato.visivel,
                    ) { vm.travar(it) }
                }
            }
            Vao(18.dp)

            Grupo(titulo = "Agente de cada orbe", descricao = "Rolar o carrossel troca de orbe e, com ele, de agente. Toque para trocar.") {
                Skin.entries.forEach { skin ->
                    item {
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
            Vao(18.dp)

            Grupo(titulo = "Avatar do orbe", caixa = false) {
                Skin.entries.chunked(2).forEach { par ->
                    item {
                        Row(Modifier.fillMaxWidth().padding(bottom = 8.dp), horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                            par.forEach { skin ->
                                Cartao(skin, marcado = aparencia.skin == skin, glitch = aparencia.glitch, modifier = Modifier.weight(1f)) {
                                    vm.skin(skin)
                                }
                            }
                        }
                    }
                }
            }
            Vao(10.dp)

            Grupo {
                item {
                    SliderOrbe(ajustes.tamanho, Ajustes.TAMANHO_MIN, Ajustes.TAMANHO_MAX, aparencia.skin, aparencia.glitch) { vm.tamanho(it) }
                }
                item {
                    LinhaSwitch("Glitch", aparencia.glitch, subtitulo = "aberração cromática e faixas arrancadas") { vm.glitch(it) }
                }
                item {
                    LinhaSwitch("Texto do raciocínio", ajustes.texto, subtitulo = "as linhas do agente, abaixo do orbe") { vm.texto(it) }
                }
                item {
                    LinhaSwitch("Seguir o orbe do PC", ajustes.seguirPc, subtitulo = "o avatar e o glitch vêm do computador") { vm.seguirPc(it) }
                }
            }
            Vao(18.dp)

            Grupo(titulo = "Voz") {
                item {
                    LinhaSwitch("Microfone do relógio", ajustes.microfone, subtitulo = "segurando o orbe, a fala vem daqui e não do computador") {
                        vm.microfone(it)
                        if (it) pedirMicrofone()
                    }
                }
                if (vm.temSaidaDeSom) {
                    // o orbe de pulso fala só por aqui; o daemon do desktop também tem a voz do PC
                    val conectada = ligacao as? Ligacao.Conectada
                    item {
                        LinhaSwitch(
                            "Voz no relógio", ajustes.voz,
                            subtitulo = when {
                                conectada?.voz == false -> "esta ponte fala pelo computador"
                                conectada?.vozPc == true -> "a resposta toca aqui; desligada, toca no computador"
                                else -> "a resposta toca aqui; desligada, vem em texto"
                            },
                        ) { vm.voz(it) }
                    }
                    if (conectada?.vozPc == true && ajustes.voz) {
                        item {
                            LinhaSwitch("Voz também no PC", ajustes.vozPc, subtitulo = "a resposta toca nos dois") { vm.vozPc(it) }
                        }
                    }
                }
                item {
                    LinhaSwitch("Vibrar", ajustes.vibrar, subtitulo = "ao segurar e ao soltar o orbe") { vm.vibrar(it) }
                }
            }
            Vao(18.dp)

            Grupo(titulo = "Sacudida", descricao = "Com a tela acesa, uma sacudida do pulso para fora e de volta. Duas são do HinaWatch.") {
                item {
                    LinhaSwitch("Uma sacudida abre o orbe", ajustes.sacudida, subtitulo = "já ouvindo, pelo microfone do relógio") {
                        vm.sacudida(it)
                        if (it) pedirMicrofone()
                    }
                }
                item {
                    Linha(
                        "Calibrar",
                        subtitulo = "fora %.1f · dentro %.1f rad/s".format(ajustes.sacudidaFora, ajustes.sacudidaDentro).replace('.', ','),
                        ativo = ajustes.sacudida,
                        aoClicar = calibrar,
                    )
                }
            }
            Vao(16.dp)

            // ── rodapé ──
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
            Vao(if (redonda) 46.dp else 20.dp)
        }
        // no alto e no pé do mostrador redondo o conteúdo some no fundo, em vez de
        // ser cortado pela borda (a rolagem em roda do Wear, sem encolher as caixas)
        if (redonda) {
            val borda = maxHeight * 0.16f
            Box(Modifier.fillMaxWidth().height(borda).background(Brush.verticalGradient(listOf(Estilo.fundo, Estilo.fundo.alfa(0f)))))
            Box(
                Modifier.fillMaxWidth().height(borda).align(Alignment.BottomCenter)
                    .background(Brush.verticalGradient(listOf(Estilo.fundo.alfa(0f), Estilo.fundo))),
            )
        }
    }
}
