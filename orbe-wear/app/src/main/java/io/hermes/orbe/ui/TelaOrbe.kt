package io.hermes.orbe.ui

import androidx.compose.animation.core.animateFloatAsState
import androidx.compose.animation.core.tween
import androidx.compose.foundation.Canvas
import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.gestures.awaitEachGesture
import androidx.compose.foundation.gestures.awaitFirstDown
import androidx.compose.foundation.interaction.MutableInteractionSource
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.BoxWithConstraints
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.offset
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.pager.VerticalPager
import androidx.compose.foundation.pager.rememberPagerState
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.text.BasicText
import androidx.compose.runtime.Composable
import androidx.compose.runtime.SideEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableLongStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberUpdatedState
import androidx.compose.runtime.snapshotFlow
import androidx.compose.runtime.withFrameNanos
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.Shadow
import androidx.compose.ui.graphics.TransformOrigin
import androidx.compose.ui.graphics.graphicsLayer
import androidx.compose.ui.input.pointer.pointerInput
import androidx.compose.ui.platform.LocalDensity
import androidx.compose.ui.text.TextStyle
import androidx.compose.ui.text.rememberTextMeasurer
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.compose.ui.viewinterop.AndroidView
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import io.hermes.orbe.OrbeViewModel
import io.hermes.orbe.dados.Ligacao
import io.hermes.orbe.gl.OrbeView
import io.hermes.orbe.orbe.Celula
import io.hermes.orbe.orbe.Ciclo
import io.hermes.orbe.orbe.OrbeCena
import io.hermes.orbe.orbe.Quebra
import kotlinx.coroutines.flow.Flow
import kotlin.math.floor
import kotlin.math.max
import kotlin.math.min
import kotlin.math.sin
import kotlin.math.sqrt

/** Mais que isto parado, o dedo está segurando para falar (o segurar_s do daemon). */
private const val SEGURAR_MS = 350L

// a mais nova inteira e as mais antigas esmaecendo, até quase sumir no pé da figura
private val ALFAS = floatArrayOf(0.10f, 0.24f, 0.42f, 0.66f, 0.92f)

/**
 * A tela do orbe: a figura no mostrador inteiro, as linhas do raciocínio
 * abaixo dela e o ponto da sessão travada acima, como no orbe do desktop com o
 * texto "abaixo". Um toque abre a sessão (ou já no live, com a opção), outro
 * com ela aberta entra no live (os turnos seguem sem tocar); no live, um toque
 * interrompe a fala, ou fecha se o orbe só ouve. Três toques encerram a sessão
 * e o Claude Code no PC. Segurar é segurar para falar. Arrastar para
 * cima ou para baixo (ou girar a coroa, nos relógios que têm) gira o orbe,
 * como a face de um cubo, até a skin seguinte; depois da última, a primeira
 * volta na cor seguinte (Ciclo).
 */
@Composable
fun TelaOrbe(
    vm: OrbeViewModel,
    redonda: Boolean,
    podeGravar: () -> Boolean,
    abrirAjustes: () -> Unit,
    /** passos da coroa: +1 o orbe seguinte, -1 o anterior */
    coroa: Flow<Int>,
    modifier: Modifier = Modifier,
) {
    val ajustes by vm.ajustes.collectAsStateWithLifecycle()
    val aparencia by vm.aparencia.collectAsStateWithLifecycle()
    val retrato by vm.retrato.collectAsStateWithLifecycle()
    val ligacao by vm.ligacao.collectAsStateWithLifecycle()
    val previa by vm.previa.collectAsStateWithLifecycle()
    val pode by rememberUpdatedState(podeGravar)
    val comTexto = ajustes.texto && retrato.linhas.isNotEmpty()

    SideEffect {
        vm.cena.redonda = redonda
        vm.cena.comTexto = comTexto
        vm.cena.corFundo = floatArrayOf(0f, 0f, 0f)
    }

    BoxWithConstraints(modifier.fillMaxSize().background(Color.Black)) {
        val w = maxWidth.value
        val h = maxHeight.value
        val densidade = LocalDensity.current.density

        // ── o carrossel: arrastar na vertical (ou a coroa) gira um cubo até o orbe seguinte ──
        val paginas = rememberPagerState(initialPage = Ciclo.pagina(aparencia.skin, aparencia.cor)) { Ciclo.PAGINAS }
        val agora by rememberUpdatedState(aparencia)
        // a escolha veio de fora (o menu, o PC, os ajustes lidos do disco): vai até ela sem animar
        LaunchedEffect(aparencia.skin, aparencia.cor) {
            val p = paginas.settledPage
            if (!paginas.isScrollInProgress && (Ciclo.skin(p) != aparencia.skin || Ciclo.cor(p) != aparencia.cor)) {
                paginas.scrollToPage(Ciclo.pagina(aparencia.skin, aparencia.cor, p))
            }
        }
        LaunchedEffect(paginas) {
            coroa.collect { passo ->
                if (!paginas.isScrollInProgress) paginas.animateScrollToPage(paginas.currentPage + passo)
            }
        }
        // assentou noutra combinação pelo dedo: ela passa a ser o orbe do relógio
        LaunchedEffect(paginas) {
            snapshotFlow { paginas.settledPage }.collect { p ->
                if (Ciclo.skin(p) != agora.skin || Ciclo.cor(p) != agora.cor) vm.girar(Ciclo.skin(p), Ciclo.cor(p))
            }
        }

        val rolando = LocalRolando.current
        VerticalPager(
            state = paginas,
            modifier = Modifier.fillMaxSize(),
            beyondViewportPageCount = 0,
        ) { pagina ->
            val atual = pagina == paginas.settledPage
            // a página que entra mostra o orbe dela parado, até assentar e virar o do relógio
            val vizinha = remember { OrbeCena(entrar = false) }
            SideEffect {
                vizinha.skin = Ciclo.skin(pagina)
                vizinha.glitch = aparencia.glitch
                vizinha.varredura = aparencia.linhas
                vizinha.tamanho = ajustes.tamanho.toDouble()
                vizinha.redonda = redonda
                vizinha.corFundo = floatArrayOf(0f, 0f, 0f)
                val cor = aparencia.copy(cor = Ciclo.cor(pagina))
                vizinha.corTema = cor.corFigura()
                vizinha.accent = cor.corAnel()
            }
            AndroidView(
                factory = { OrbeView(it, if (atual) vm.cena else vizinha).apply { adaptar = true; parado = !atual || rolando } },
                update = {
                    it.cena = if (atual) vm.cena else vizinha
                    // a que entra é desenhada uma vez e congela: eram dois orbes
                    // grandes por quadro no meio do giro. Arrastando para o menu,
                    // o orbe também congela: a GPU fica para a tela que anda
                    it.parado = !atual || rolando
                },
                modifier = Modifier
                    .fillMaxSize()
                    .graphicsLayer {
                        // 0 no centro, 1 uma página abaixo: cada orbe é uma face do cubo,
                        // que gira em torno da aresta que divide com a vizinha
                        val y = ((pagina - paginas.currentPage) - paginas.currentPageOffsetFraction).coerceIn(-1f, 1f)
                        cameraDistance = 9f * density
                        transformOrigin = TransformOrigin(0.5f, if (y < 0f) 1f else 0f)
                        rotationX = -90f * y
                    }
                    .pointerInput(Unit) {
                    val folga = viewConfiguration.touchSlop
                    awaitEachGesture {
                        val baixo = awaitFirstDown(requireUnconsumed = false)
                        vm.toqueBaixo(baixo.position.x / densidade, baixo.position.y / densidade, pode())
                        // 1 = solto no lugar (toque curto), 2 = andou (é rolagem), null = segurou
                        val fim = withTimeoutOrNull(SEGURAR_MS) {
                            var r = 0
                            while (r == 0) {
                                val c = awaitPointerEvent().changes.firstOrNull { it.id == baixo.id }
                                r = when {
                                    c == null || c.isConsumed -> 2
                                    !c.pressed -> 1
                                    (c.position - baixo.position).getDistance() > folga -> 2
                                    else -> 0
                                }
                            }
                            r
                        }
                        when (fim) {
                            1 -> vm.toqueCurto(pode())
                            2 -> vm.toqueCancelado()
                            else -> {
                                vm.toqueSegurou()
                                while (true) {
                                    val c = awaitPointerEvent().changes.firstOrNull { it.id == baixo.id } ?: break
                                    c.consume()          // segurando, o dedo não rola a tela
                                    if (!c.pressed) break
                                    vm.olhar(c.position.x / densidade, c.position.y / densidade)
                                }
                                vm.toqueSolto()
                            }
                        }
                    }
                },
            )
        }

        // ── o raciocínio: as últimas fileiras, a mais nova embaixo ──
        // o texto espera a figura subir antes de aparecer embaixo dela
        val alfaTexto by animateFloatAsState(
            if (comTexto) 1f else 0f, tween(220, delayMillis = if (comTexto) 160 else 0), label = "texto",
        )
        if (alfaTexto > 0.01f) {
            val cel = Celula.para(w.toDouble(), h.toDouble(), ajustes.tamanho.toDouble(), true)
            val skin = aparencia.skin
            val y0 = (cel.cy + cel.lado * skin.pe * (if (redonda) skin.encolheNoDisco(cel.lado) else 1.0)).toFloat() + 3f
            val passo = 13f
            val estilo = remember {
                TextStyle(fontSize = 10.sp, lineHeight = 12.sp, textAlign = TextAlign.Center,
                    shadow = Shadow(Color.Black, Offset.Zero, 4f))
            }
            val nMax = min(5, floor((h * 0.95f - y0) / passo).toInt())
            val medidor = rememberTextMeasurer()
            val fileiras = remember(retrato.linhas, w, h, y0, nMax, redonda) {
                // cada fileira tem a largura da corda do mostrador na altura do pé dela
                val larguras = List(max(0, nMax)) { i ->
                    val yb = y0 + (i + 1) * passo
                    val corda = if (redonda) 2 * sqrt(max(0f, (h / 2) * (h / 2) - (yb - h / 2) * (yb - h / 2))) else w
                    max(0f, corda - 18f) * densidade
                }
                Quebra.quebrar(retrato.linhas, larguras) { medidor.measure(it, estilo).size.width.toFloat() }
            }
            Box(Modifier.fillMaxSize().graphicsLayer { alpha = alfaTexto }) {
                fileiras.forEachIndexed { i, fileira ->
                    BasicText(
                        fileira,
                        Modifier.fillMaxWidth().offset(y = (y0 + i * passo).dp),
                        style = estilo.copy(color = Color(0.88f, 0.84f, 0.92f, ALFAS[ALFAS.size - fileiras.size + i])),
                        maxLines = 1,
                    )
                }
            }
        }

        // ── sessão travada: ponto logo acima da figura, com respiro lento ──
        if (retrato.travado && retrato.visivel) {
            val t = remember { mutableLongStateOf(0L) }
            LaunchedEffect(Unit) { while (true) withFrameNanos { t.longValue = it } }
            val cel = Celula.para(w.toDouble(), h.toDouble(), ajustes.tamanho.toDouble(), comTexto)
            val skin = aparencia.skin
            val topo = cel.lado * skin.topo * (if (redonda) skin.encolheNoDisco(cel.lado) else 1.0)
            val cor = if (skin.avatar) Estilo.accent else Estilo.anel
            Canvas(Modifier.fillMaxSize()) {
                val pulso = 0.62f + 0.38f * (0.5f + 0.5f * sin(t.longValue / 1e9 * 2.0).toFloat())
                val c = Offset(cel.cx.toFloat() * density, max(7.0, cel.cy - topo - 8).toFloat() * density)
                drawCircle(cor.copy(alpha = 0.22f * pulso), 6 * density, c)
                drawCircle(cor.copy(alpha = 0.90f * pulso), 3 * density, c)
            }
        }

        // ── rodapé: o estado da ponte (ou da prévia) e a alça do menu ──
        val estado = when {
            previa != null -> "prévia: $previa"
            ligacao is Ligacao.SemServidor -> if (ajustes.servidor.isBlank() || ajustes.token.isBlank()) "sem servidor" else ""
            ligacao is Ligacao.Conectando -> "conectando…"
            ligacao is Ligacao.Falha -> (ligacao as Ligacao.Falha).motivo
            else -> ""
        }
        Sumir(estado.isNotEmpty() && !comTexto, Modifier.align(Alignment.BottomCenter).padding(bottom = 22.dp)) {
            Texto(
                estado, Estilo.mono,
                Modifier.clickable(remember { MutableInteractionSource() }, indication = null, onClick = abrirAjustes),
                cor = Estilo.texto.alfa(0.6f), linhas = 1,
            )
        }
        // a alça do menu, que fica ao lado: arrastar para a esquerda
        Box(
            Modifier.align(Alignment.CenterEnd).padding(end = 7.dp).size(3.dp, 18.dp)
                .clip(CircleShape).background(Estilo.texto.alfa(if (comTexto) 0.10f else 0.25f)),
        )
    }
}
