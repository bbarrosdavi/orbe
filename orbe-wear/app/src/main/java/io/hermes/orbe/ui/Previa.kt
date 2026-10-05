package io.hermes.orbe.ui

import android.content.Context
import androidx.compose.foundation.Canvas
import androidx.compose.runtime.Composable
import androidx.compose.runtime.IntState
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.mutableStateMapOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.staticCompositionLocalOf
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.FilterQuality
import androidx.compose.ui.graphics.ImageBitmap
import androidx.compose.ui.graphics.asImageBitmap
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.platform.LocalDensity
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.IntOffset
import androidx.compose.ui.unit.IntSize
import io.hermes.orbe.gl.Motor
import io.hermes.orbe.orbe.MiniCena
import io.hermes.orbe.orbe.Skin
import kotlin.math.min
import kotlin.math.roundToInt

// As miniaturas do menu em quadros prontos, como os bustos do HinaWatch: o
// Motor desenha cada uma fora da tela, uma vez, e o menu só troca de imagem.
// Com uma superfície GL viva por miniatura, a rolagem do menu disputava a GPU
// do relógio com elas e perdia quadros.

/** Onde a miniatura aparece: o traço de cada lugar (Miniatura.qml). */
enum class Papel(val peso: Double) { TOPO(1.0), CARTAO(1.2) }

/** Tudo que muda o desenho de uma miniatura: outra chave, outros quadros. */
data class ChavePrevia(
    val papel: Papel,
    val skin: Skin,
    val largura: Dp,
    val altura: Dp,
    val glitch: Boolean,
    val linhas: Boolean,
    val cor: Color,
    val anel: Color,
    val fundo: Color,
)

internal object Previas {
    /** Quadros de cada miniatura, em vai e volta: sem emenda no fim do laço. */
    private const val QUADROS = 16
    /** Entre um quadro e outro: o ritmo das miniaturas vivas no rodízio do Motor. */
    const val PASSO_MS = 100L
    /** Prévias guardadas: as do menu (6 cartões e o topo) e as que estão saindo. */
    private const val GUARDADAS = 10

    private val prontas = mutableStateMapOf<ChavePrevia, List<ImageBitmap>>()
    private val ordem = ArrayDeque<ChavePrevia>()
    private val pedidas = HashMap<Pair<Papel, Skin>, Pair<ChavePrevia, Motor.Pedido>>()

    fun quadros(chave: ChavePrevia): List<ImageBitmap>? = prontas[chave]

    /** Na thread principal. Cada lugar (papel e skin) tem um pedido só: o novo desiste do velho. */
    fun pedir(ctx: Context, chave: ChavePrevia, densidade: Float) {
        if (chave in prontas) return
        val vaga = chave.papel to chave.skin
        val antes = pedidas[vaga]
        if (antes?.first == chave) return
        antes?.second?.cancelar()
        val cena = MiniCena(chave.skin).apply {
            glitch = chave.glitch
            varredura = chave.linhas
            peso = chave.papel.peso
            // o topo do app: o Ophanim no raio do cabeçalho, não o maior que cabe
            raio = if (chave.papel == Papel.TOPO) min(chave.altura.value * 0.42f, chave.largura.value * 0.32f).toDouble() else -1.0
            cor = chave.cor.rgb()
            accent = chave.anel.rgb()
            corFundo = chave.fundo.rgb()
        }
        val w = (chave.largura.value * densidade).roundToInt()
        val h = (chave.altura.value * densidade).roundToInt()
        val pedido = Motor.previa(ctx, cena, w, h, densidade, QUADROS, PASSO_MS / 1000.0) { bitmaps ->
            if (pedidas[vaga]?.first == chave) pedidas.remove(vaga)
            prontas[chave] = bitmaps.map { it.asImageBitmap() }
            ordem.addLast(chave)
            while (ordem.size > GUARDADAS) prontas.remove(ordem.removeFirst())
        }
        pedidas[vaga] = chave to pedido
    }
}

/** O passo das miniaturas: anda só com o menu na tela (TelaAjustes). */
val LocalQuadro = staticCompositionLocalOf<IntState> { mutableIntStateOf(0) }

/** O quadro do passo [passo] em vai e volta: 0, 1, …, n-1, n-2, …, 1, 0, … */
fun vaiEVolta(passo: Int, n: Int): Int {
    if (n <= 1) return 0
    val ciclo = 2 * n - 2
    val i = passo.mod(ciclo)
    return if (i < n) i else ciclo - i
}

/**
 * A figura de uma skin em miniatura (Miniatura.qml), dos quadros prontos.
 * Cabe no [modifier] sem deformar; trocou o glitch ou o tema, fica a anterior
 * até a nova sair.
 */
@Composable
fun Miniatura(chave: ChavePrevia, modifier: Modifier = Modifier) {
    val ctx = LocalContext.current
    val densidade = LocalDensity.current.density
    LaunchedEffect(chave) { Previas.pedir(ctx, chave, densidade) }
    val quadros = Previas.quadros(chave)
    val ultima = remember { arrayOfNulls<List<ImageBitmap>>(1) }
    if (quadros != null) ultima[0] = quadros
    val mostrar = quadros ?: ultima[0]
    val passo = LocalQuadro.current
    Canvas(modifier) {
        val q = mostrar ?: return@Canvas
        // o passo é lido só no desenho: trocar de quadro não recompõe nada
        val img = q[vaiEVolta(passo.intValue, q.size)]
        val e = min(size.width / img.width, size.height / img.height)
        val w = (img.width * e).roundToInt()
        val h = (img.height * e).roundToInt()
        drawImage(
            img,
            dstOffset = IntOffset(((size.width - w) / 2).roundToInt(), ((size.height - h) / 2).roundToInt()),
            dstSize = IntSize(w, h),
            filterQuality = FilterQuality.Low,
        )
    }
}
