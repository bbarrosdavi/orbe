package io.hermes.orbe.ui

import androidx.compose.animation.animateColorAsState
import androidx.compose.animation.core.animateDpAsState
import androidx.compose.animation.core.animateFloatAsState
import androidx.compose.animation.core.tween
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.gestures.detectHorizontalDragGestures
import androidx.compose.foundation.gestures.detectTapGestures
import androidx.compose.foundation.interaction.MutableInteractionSource
import androidx.compose.foundation.interaction.collectIsPressedAsState
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.BoxWithConstraints
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.RowScope
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.defaultMinSize
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.offset
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.BasicText
import androidx.compose.runtime.Composable
import androidx.compose.runtime.compositionLocalOf
import androidx.compose.runtime.getValue
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberUpdatedState
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.alpha
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.graphicsLayer
import androidx.compose.ui.input.pointer.pointerInput
import androidx.compose.ui.platform.LocalDensity
import androidx.compose.ui.text.TextStyle
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.IntOffset
import androidx.compose.ui.unit.dp
import androidx.compose.ui.viewinterop.AndroidView
import io.hermes.orbe.gl.OrbeView
import io.hermes.orbe.orbe.MiniCena
import io.hermes.orbe.orbe.Skin
import kotlin.math.abs
import kotlin.math.roundToInt

// Os componentes do app do Orbe (orbe-qt/app/*.qml) na medida do relógio:
// mesmos nomes, mesmas cores e mesmas proporções.

@Composable
fun Texto(
    texto: String,
    estilo: TextStyle,
    modifier: Modifier = Modifier,
    cor: Color = Estilo.texto,
    alinhar: TextAlign? = null,
    linhas: Int = Int.MAX_VALUE,
) {
    BasicText(
        text = texto,
        modifier = modifier,
        style = estilo.copy(color = cor, textAlign = alinhar ?: TextAlign.Unspecified),
        maxLines = linhas,
        overflow = TextOverflow.Ellipsis,
    )
}

/** Verdadeiro enquanto a tela rola: as miniaturas esperam paradas (a GPU do relógio é pouca para as duas coisas). */
val LocalRolando = compositionLocalOf { false }

/**
 * A figura de uma skin em miniatura viva (Miniatura.qml): Figura para os
 * avatares, Anel no estado de escuta para o anel de energia.
 */
@Composable
fun Miniatura(
    skin: Skin,
    modifier: Modifier = Modifier,
    glitch: Boolean = true,
    peso: Double = 1.2,
    /** raio da figura em fração da altura e da largura (o do topo do app); null = o maior que cabe */
    raio: Pair<Float, Float>? = null,
) {
    val tema = LocalTema.current
    val rolando = LocalRolando.current
    BoxWithConstraints(modifier) {
        val r = raio?.let { minOf(maxHeight.value * it.first, maxWidth.value * it.second).toDouble() } ?: -1.0
        AndroidView(
            factory = { OrbeView(it, MiniCena(skin)) },
            modifier = Modifier.fillMaxSize(),
            update = { v ->
                v.parado = rolando
                (v.cena as MiniCena).let { c ->
                    c.skin = skin
                    c.glitch = glitch
                    c.peso = peso
                    c.raio = r
                    c.cor = tema.accent.rgb()
                    c.accent = tema.anel.rgb()
                    c.corFundo = tema.fundo.rgb()
                }
            },
        )
    }
}

/** Botão de texto: chapado, ou em pílula na cor de destaque. `ligado` tinge o chapado, para os que alternam. */
@Composable
fun Botao(
    texto: String,
    modifier: Modifier = Modifier,
    destaque: Boolean = false,
    ligado: Boolean = false,
    ativo: Boolean = true,
    aoClicar: () -> Unit,
) {
    val fonte = remember { MutableInteractionSource() }
    val apertado by fonte.collectIsPressedAsState()
    val fundo = when {
        destaque -> if (apertado) Estilo.accent.alfa(0.85f) else Estilo.accent
        ligado -> Estilo.accent.alfa(if (apertado) 0.28f else 0.20f)
        else -> Estilo.texto.alfa(if (apertado) 0.16f else 0.08f)
    }
    Box(
        modifier
            .alpha(if (ativo) 1f else 0.4f)
            .height(if (destaque) 36.dp else 30.dp)
            .clip(CircleShape)
            .background(fundo)
            .clickable(fonte, indication = null, enabled = ativo, onClick = aoClicar)
            .padding(horizontal = if (destaque) 22.dp else 12.dp),
        contentAlignment = Alignment.Center,
    ) {
        Texto(texto, Estilo.botao, cor = if (destaque) Estilo.accentFg else if (ligado) Estilo.accent else Estilo.texto, linhas = 1)
    }
}

/** Uma etiqueta em caixa, como a tecla do atalho na aba Ativação. */
@Composable
fun Etiqueta(texto: String, modifier: Modifier = Modifier) {
    Box(
        modifier
            .clip(RoundedCornerShape(7.dp))
            .background(Estilo.accent.alfa(0.14f))
            .border(1.dp, Estilo.accent.alfa(0.30f), RoundedCornerShape(7.dp))
            .padding(horizontal = 7.dp, vertical = 3.dp),
    ) {
        Texto(texto, Estilo.mono.copy(fontWeight = androidx.compose.ui.text.font.FontWeight.Bold), linhas = 1)
    }
}

class GrupoEscopo internal constructor() {
    internal val itens = ArrayList<@Composable () -> Unit>()

    /** Uma linha da caixa; a divisória entre as linhas é do grupo. */
    fun item(conteudo: @Composable () -> Unit) {
        itens.add(conteudo)
    }
}

/** Grupo de preferências: título, descrição e as linhas numa caixa arredondada. */
@Composable
fun Grupo(
    modifier: Modifier = Modifier,
    titulo: String = "",
    descricao: String = "",
    caixa: Boolean = true,
    conteudo: GrupoEscopo.() -> Unit,
) {
    val escopo = GrupoEscopo().apply(conteudo)
    Column(modifier.fillMaxWidth(), verticalArrangement = Arrangement.spacedBy(6.dp)) {
        if (titulo.isNotEmpty()) Texto(titulo, Estilo.grupo, Modifier.padding(start = 4.dp))
        if (descricao.isNotEmpty()) Texto(descricao, Estilo.subtitulo, Modifier.padding(horizontal = 4.dp), cor = Estilo.texto.alfa(0.55f))
        val forma = RoundedCornerShape(12.dp)
        Column(
            if (caixa) Modifier.fillMaxWidth().clip(forma).background(Estilo.vista.alfa(0.30f)).border(1.dp, Estilo.accent.alfa(0.16f), forma)
            else Modifier.fillMaxWidth(),
        ) {
            escopo.itens.forEachIndexed { i, item ->
                if (i > 0 && caixa) Box(Modifier.fillMaxWidth().height(1.dp).background(Estilo.texto.alfa(0.08f)))
                item()
            }
        }
    }
}

/** Linha de uma caixa de preferências: título, subtítulo e o que vier à direita. */
@Composable
fun Linha(
    titulo: String,
    modifier: Modifier = Modifier,
    subtitulo: String = "",
    ativo: Boolean = true,
    aoClicar: (() -> Unit)? = null,
    sufixo: @Composable RowScope.() -> Unit = {},
) {
    val fonte = remember { MutableInteractionSource() }
    val apertado by fonte.collectIsPressedAsState()
    Row(
        modifier
            .fillMaxWidth()
            .alpha(if (ativo) 1f else 0.4f)
            .defaultMinSize(minHeight = 40.dp)
            .background(Estilo.accent.alfa(if (apertado) 0.07f else 0f))
            .then(if (aoClicar != null) Modifier.clickable(fonte, indication = null, enabled = ativo, onClick = aoClicar) else Modifier)
            .padding(start = 11.dp, end = 9.dp, top = 7.dp, bottom = 7.dp),
        verticalAlignment = Alignment.CenterVertically,
        horizontalArrangement = Arrangement.spacedBy(6.dp),
    ) {
        Column(Modifier.weight(1f), verticalArrangement = Arrangement.spacedBy(1.dp)) {
            Texto(titulo, Estilo.titulo, linhas = 2)
            if (subtitulo.isNotEmpty()) Texto(subtitulo, Estilo.subtitulo, cor = Estilo.texto.alfa(0.55f))
        }
        sufixo()
    }
}

/** A chave do app: trilho de destaque quando ligada, botão que desliza. */
@Composable
fun LinhaSwitch(
    titulo: String,
    ligado: Boolean,
    modifier: Modifier = Modifier,
    subtitulo: String = "",
    ativo: Boolean = true,
    aoMudar: (Boolean) -> Unit,
) {
    Linha(titulo, modifier, subtitulo, ativo, aoClicar = { aoMudar(!ligado) }) {
        val trilho by animateColorAsState(if (ligado) Estilo.accent else Estilo.texto.alfa(0.16f), tween(120), label = "trilho")
        val x by animateDpAsState(if (ligado) 19.dp else 3.dp, tween(120), label = "botão")
        Box(Modifier.size(38.dp, 22.dp).clip(CircleShape).background(trilho)) {
            Box(
                Modifier.offset { IntOffset(x.roundToPx(), 3.dp.roundToPx()) }.size(16.dp).clip(CircleShape)
                    .background(if (ligado) Estilo.accentFg else Estilo.texto),
            )
        }
    }
}

/** Miniatura animada de uma skin no seletor de avatar. */
@Composable
fun Cartao(
    skin: Skin,
    marcado: Boolean,
    glitch: Boolean,
    modifier: Modifier = Modifier,
    aoEscolher: () -> Unit,
) {
    val fonte = remember { MutableInteractionSource() }
    val apertado by fonte.collectIsPressedAsState()
    val forma = RoundedCornerShape(12.dp)
    Column(
        modifier
            .height(100.dp)
            .clip(forma)
            .background(if (marcado) Estilo.accent.alfa(0.14f) else Estilo.texto.alfa(if (apertado) 0.07f else 0.04f))
            .border(1.dp, if (marcado) Estilo.accent.alfa(0.55f) else Estilo.texto.alfa(0.08f), forma)
            .clickable(fonte, indication = null, onClick = aoEscolher)
            .padding(4.dp),
        horizontalAlignment = Alignment.CenterHorizontally,
    ) {
        Miniatura(skin, Modifier.fillMaxWidth().weight(1f), glitch = glitch)
        // os nomes compridos ("Ophanim com asas") quebram em duas linhas; a caixa reserva as duas
        Box(Modifier.fillMaxWidth().height(21.dp), contentAlignment = Alignment.Center) {
            Texto(skin.nome, Estilo.cartao, cor = if (marcado) Estilo.accent else Estilo.texto, alinhar = TextAlign.Center, linhas = 2)
        }
    }
}

/** Tamanho do orbe na tela. O botão do slider é a miniatura viva da skin escolhida. */
@Composable
fun SliderOrbe(
    valor: Float,
    de: Float,
    ate: Float,
    skin: Skin,
    glitch: Boolean,
    modifier: Modifier = Modifier,
    passo: Float = 0.05f,
    aoMudar: (Float) -> Unit,
) {
    val lado = 44.dp
    val mudar by rememberUpdatedState(aoMudar)
    val fracao = ((valor - de) / (ate - de)).coerceIn(0f, 1f)
    Column(modifier.fillMaxWidth().padding(start = 11.dp, end = 11.dp, top = 9.dp, bottom = 4.dp)) {
        Row(verticalAlignment = Alignment.Top) {
            Column(Modifier.weight(1f), verticalArrangement = Arrangement.spacedBy(1.dp)) {
                Texto("Tamanho", Estilo.titulo)
                Texto("escala do orbe na tela", Estilo.subtitulo, cor = Estilo.texto.alfa(0.55f))
            }
            Texto("${(valor * 100).roundToInt()}%", Estilo.botao, cor = Estilo.accent)
        }
        BoxWithConstraints(Modifier.fillMaxWidth().height(lado + 6.dp).padding(top = 6.dp)) {
            val densidade = LocalDensity.current
            val trilho = maxWidth - lado
            val pos = trilho * fracao
            val vao = lado / 2 + 2.dp          // o trilho abre um vão ao redor do botão
            val definir = { xPx: Float ->
                val larg = with(densidade) { trilho.toPx() }
                val meio = with(densidade) { (lado / 2).toPx() }
                val v = de + ((xPx - meio) / larg).coerceIn(0f, 1f) * (ate - de)
                val arred = de + ((v - de) / passo).roundToInt() * passo
                mudar((arred * 100).roundToInt() / 100f)
            }
            Box(
                Modifier.fillMaxSize()
                    .pointerInput(de, ate) { detectTapGestures { definir(it.x) } }
                    // a rolagem é da página: o slider só muda arrastando de lado
                    .pointerInput(de, ate) {
                        detectHorizontalDragGestures { change, _ ->
                            change.consume()
                            definir(change.position.x)
                        }
                    },
            ) {
                val y = Modifier.align(Alignment.CenterStart)
                // trecho percorrido, até o vão
                Box(y.offset(x = lado / 2).width((pos - vao).coerceAtLeast(0.dp)).height(5.dp).clip(CircleShape).background(Estilo.accent.alfa(0.75f)))
                // trecho restante, depois do vão
                val resto = (trilho - pos - vao).coerceAtLeast(0.dp)
                Box(y.offset(x = lado / 2 + trilho - resto).width(resto).height(5.dp).clip(CircleShape).background(Estilo.texto.alfa(0.12f)))
                // marca do tamanho original (some dentro do vão)
                val marca = trilho * ((1f - de) / (ate - de))
                if (abs((marca - pos).value) > vao.value) {
                    Box(y.offset(x = lado / 2 + marca - 1.dp).width(2.dp).height(12.dp).clip(CircleShape).background(Estilo.texto.alfa(0.35f)))
                }
                // o botão é só o orbe, sem aro nem disco
                Miniatura(skin, y.offset(x = pos).size(lado), glitch = glitch, peso = 0.9)
            }
        }
    }
}

/** Um ponto de espaço entre grupos, para a conta ficar no chamador. */
@Composable
fun Vao(altura: Dp) = Spacer(Modifier.height(altura))

/** Escala suave para o que aparece e some (o aviso do rodapé, a linha de estado). */
@Composable
fun Sumir(visivel: Boolean, modifier: Modifier = Modifier, conteudo: @Composable () -> Unit) {
    val a by animateFloatAsState(if (visivel) 1f else 0f, tween(160), label = "sumir")
    if (a > 0.01f) Box(modifier.graphicsLayer { alpha = a }) { conteudo() }
}
