package io.hermes.orbe.ui

import android.view.View
import androidx.compose.animation.core.animateFloatAsState
import androidx.compose.animation.core.tween
import androidx.compose.foundation.Canvas
import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.gestures.awaitEachGesture
import androidx.compose.foundation.gestures.awaitFirstDown
import androidx.compose.foundation.interaction.MutableInteractionSource
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.BoxScope
import androidx.compose.foundation.layout.BoxWithConstraints
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.offset
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.text.BasicText
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.SideEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableLongStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.rememberUpdatedState
import androidx.compose.runtime.snapshotFlow
import androidx.compose.runtime.withFrameNanos
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.geometry.CornerRadius
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.GraphicsLayerScope
import androidx.compose.ui.graphics.Shadow
import androidx.compose.ui.graphics.graphicsLayer
import androidx.compose.ui.input.pointer.PointerEvent
import androidx.compose.ui.input.pointer.PointerInputScope
import androidx.compose.ui.input.pointer.pointerInput
import androidx.compose.ui.input.pointer.util.VelocityTracker
import androidx.compose.ui.platform.LocalDensity
import androidx.compose.ui.platform.LocalView
import androidx.compose.ui.text.TextStyle
import androidx.compose.ui.text.rememberTextMeasurer
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.style.TextOverflow
import androidx.wear.compose.foundation.CurvedDirection
import androidx.wear.compose.foundation.CurvedLayout
import androidx.wear.compose.foundation.CurvedModifier
import androidx.wear.compose.foundation.CurvedTextStyle
import androidx.wear.compose.foundation.basicCurvedText
import androidx.wear.compose.foundation.sizeIn
import androidx.compose.ui.util.lerp
import androidx.compose.ui.viewinterop.AndroidView
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import androidx.wear.compose.foundation.pager.PagerDefaults
import androidx.wear.compose.foundation.pager.VerticalPager
import androidx.wear.compose.foundation.pager.rememberPagerState
import io.hermes.orbe.Aparencia
import io.hermes.orbe.OrbeViewModel
import io.hermes.orbe.dados.Ligacao
import io.hermes.orbe.dados.SessaoInfo
import io.hermes.orbe.gl.OrbeView
import io.hermes.orbe.orbe.Celula
import io.hermes.orbe.orbe.Instancias
import io.hermes.orbe.orbe.OrbeCena
import io.hermes.orbe.orbe.Quebra
import io.hermes.orbe.orbe.Retrato
import io.hermes.orbe.orbe.Skin
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.channels.Channel
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.launch
import kotlin.math.abs
import kotlin.math.ceil
import kotlin.math.floor
import kotlin.math.max
import kotlin.math.min
import kotlin.math.roundToInt
import kotlin.math.sin
import kotlin.math.sqrt
import androidx.compose.foundation.pager.PagerState as EstadoFileira
import androidx.compose.foundation.pager.rememberPagerState as lembrarFileira
import androidx.compose.foundation.pager.VerticalPager as PaginasDaFileira

/** Mais que isto parado, o dedo está segurando para falar (o segurar_s do daemon). */
private const val SEGURAR_MS = 350L

// a mais nova inteira e as mais antigas esmaecendo, até quase sumir no pé da figura
private val ALFAS = floatArrayOf(0.10f, 0.24f, 0.42f, 0.66f, 0.92f)

// a roda dos avatares do HinaWatch (AvatarCards.kt): o orbe a uma página do
// centro encolhe a 0,7 e anda 18% da página para perto dele, e o vizinho
// parado fica logo fora da tela
private const val RODA_ESCALA = 0.7f
private const val RODA_PUXAO = 0.18f

/** Páginas de sobra para a lista girar sem fim nos dois sentidos; ela nasce no meio. */
private const val VOLTAS = 2_000

// os pontos da lista: o indicador de páginas do Wear a 0,6 do padrão, como nos
// avatares do HinaWatch (medido num screenshot do relógio, a 2 px por dp)
private val PILULA = 7.5.dp
private val PILULA_FOLGA = 2.dp
private val PONTO = 3.5.dp
private val PONTO_ACESO = 4.dp
private val PONTO_PASSO = 6.dp

/** Velocidade dos dois dedos, por segundo, que já passa à instância vizinha. */
private val ARREMESSO = 400.dp

/** O rótulo da sessão, curvado: a folga da borda da tela e o arco máximo do alto e do pé (graus). */
private val BORDA_ROTULO = 6.dp
private const val ARCO_TITULO = 150f
private const val ARCO_ROTULO = 100f

/**
 * A tela do orbe: a figura no mostrador inteiro, as linhas do raciocínio
 * abaixo dela e o ponto da sessão travada acima, como no orbe do desktop com o
 * texto "abaixo". Um toque abre a sessão (ou já no live, com a opção), outro
 * com ela aberta entra no live (os turnos seguem sem tocar); no live, um toque
 * interrompe a fala, ou fecha se o orbe só ouve. Três toques encerram a sessão
 * e o Claude Code no PC. Segurar é segurar para falar.
 *
 * Os orbes ficam numa lista vertical, uma skin por página, que rola como os
 * avatares do HinaWatch: com inércia, o orbe encolhendo ao sair do centro e os
 * pontos à direita mostrando em que parte da lista se está; a coroa passa de
 * um em um. Cada orbe do Claude tem as instâncias dele, uma por sessão do
 * Claude Code aberta no PC, que passam com dois dedos na vertical ([Fileira]).
 * Com a sessão aberta, só o orbe de onde ela foi aberta mostra o estado dela.
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
    val dono by vm.dono.collectAsStateWithLifecycle()
    val agentesPc by vm.agentesPc.collectAsStateWithLifecycle()
    val ligacao by vm.ligacao.collectAsStateWithLifecycle()
    val sessoes by vm.sessoes.collectAsStateWithLifecycle()
    val abreClaude by vm.abreClaude.collectAsStateWithLifecycle()
    val claude = remember(ajustes.agentes, ajustes.ordem) { vm.skinsClaude(ajustes) }
    val pode by rememberUpdatedState(podeGravar)
    val podeAgora = remember { { pode() } }
    // rolado para outro orbe, a sessão segue, mas o texto e o ponto ficam com o dono
    val visto = if (dono == null || dono == (aparencia.skin to aparencia.instancia)) retrato else Retrato()
    val comTexto = ajustes.texto && visto.linhas.isNotEmpty()
    val skins = remember(ajustes.ordem) { ajustes.skins() }
    val nSkins = skins.size
    val vagas = sessoes.orEmpty().map { it.vaga }

    SideEffect {
        vm.cena.redonda = redonda
        vm.cena.comTexto = comTexto
        vm.cena.corFundo = aparencia.corFundo()
    }

    // sem fundo próprio: o do menu fica parado atrás das duas páginas (OrbeApp)
    BoxWithConstraints(modifier.fillMaxSize()) {
        val w = maxWidth.value
        val h = maxHeight.value

        // ── a lista dos orbes: na vertical (dedo ou coroa), uma skin por página; depois da última, a primeira ──
        val paginas = rememberPagerState(initialPage = pagina(skins, aparencia.skin, nSkins * VOLTAS / 2)) { nSkins * VOLTAS }
        val agora by rememberUpdatedState(aparencia)
        // a escolha veio de fora (o menu, o PC, os ajustes lidos do disco) ou a ordem
        // mudou no menu: vai até ela sem animar
        LaunchedEffect(aparencia.skin, skins) {
            val p = paginas.settledPage
            if (!paginas.isScrollInProgress && skins[p.mod(nSkins)] != aparencia.skin) paginas.scrollToPage(pagina(skins, aparencia.skin, p))
        }
        LaunchedEffect(paginas) {
            coroa.collect { passo -> if (!paginas.isScrollInProgress) paginas.animateScrollToPage(paginas.currentPage + passo) }
        }
        // assentou noutra skin pelo dedo: ela passa a ser o orbe do relógio
        val ordem by rememberUpdatedState(skins)
        LaunchedEffect(paginas) {
            snapshotFlow { paginas.settledPage }.collect { p ->
                val skin = ordem[p.mod(nSkins)]
                if (skin != agora.skin) vm.girar(skin)
            }
        }

        VerticalPager(
            state = paginas,
            modifier = Modifier.fillMaxSize(),
            beyondViewportPageCount = 0,
            // o arremesso passa vários orbes, com inércia, antes de parar num deles
            flingBehavior = PagerDefaults.snapFlingBehavior(paginas, maxFlingPages = nSkins),
            // a coroa vem pelo OrbeApp, que tem o foco (no menu ela rola a lista)
            rotaryScrollableBehavior = null,
        ) { pagina ->
            val skin = skins[pagina.mod(nSkins)]
            val emTela = pagina == paginas.settledPage
            val daPagina = if (skin == aparencia.skin) aparencia else aparencia.copy(skin = skin, instancia = 0)
            val agente = nomeAgente(ajustes, skin, agentesPc)
            Box(
                Modifier
                    .fillMaxSize()
                    // lido no desenho: a rolagem não recompõe as páginas
                    .graphicsLayer { roda(paginas.currentPage - pagina + paginas.currentPageOffsetFraction, vertical = true) },
            ) {
                val j = claude.indexOf(skin)
                if (j >= 0) {
                    // as vagas se alternam entre os orbes do Claude: cada um tem as suas
                    val m = claude.size
                    val n = Instancias.contar(Instancias.doOrbe(vagas, j, m), abreClaude)
                    Fileira(vm, daPagina, emTela, n, ajustes.tamanhoDe(skin), redonda, podeAgora) { k, atual ->
                        // a sessão desta instância, na cor dela; no orbe em tela o
                        // raciocínio ocupa o mesmo lugar e tem a vez
                        val cor = daPagina.copy(instancia = k).corFigura().let { Color(it[0], it[1], it[2]) }
                        val lista = sessoes
                        if (lista != null) {
                            RotuloSessao(
                                lista.firstOrNull { it.vaga == Instancias.vaga(k, j, m) }, abreClaude, agente, cor,
                                comPe = !(atual && comTexto),
                                Modifier.fillMaxSize(),
                            )
                        } else {
                            Rotulo(agente, "", cor, Modifier.fillMaxSize())
                        }
                    }
                } else {
                    Orbe(vm, daPagina, emTela, ajustes.tamanhoDe(skin), redonda, podeAgora)
                    Rotulo(agente, "", daPagina.corFigura().let { Color(it[0], it[1], it[2]) }, Modifier.fillMaxSize())
                }
            }
        }
        // por cima da tela, sem tirar largura dos orbes (o scaffold do Wear reservava uma faixa e os tirava do centro)
        PontosDaLista(nSkins, { paginas.currentPage + paginas.currentPageOffsetFraction }, Modifier.align(Alignment.CenterEnd).padding(end = 2.dp))

        // ── o raciocínio: as últimas fileiras, a mais nova embaixo ──
        // o texto espera a figura subir antes de aparecer embaixo dela
        val alfaTexto by animateFloatAsState(
            if (comTexto) 1f else 0f, tween(220, delayMillis = if (comTexto) 160 else 0), label = "texto",
        )
        if (alfaTexto > 0.01f) {
            val cel = Celula.para(w.toDouble(), h.toDouble(), ajustes.tamanhoDe(aparencia.skin).toDouble(), true)
            val skin = aparencia.skin
            val y0 = (cel.cy + cel.lado * skin.pe * (if (redonda) skin.encolheNoDisco(cel.lado) else 1.0)).toFloat() + 3f
            val passo = 13f
            val estilo = remember {
                TextStyle(fontSize = 10.sp, lineHeight = 12.sp, textAlign = TextAlign.Center,
                    shadow = Shadow(Color.Black, Offset.Zero, 4f))
            }
            val nMax = min(5, floor((h * 0.95f - y0) / passo).toInt())
            val medidor = rememberTextMeasurer()
            val densidade = LocalDensity.current.density
            val fileiras = remember(visto.linhas, w, h, y0, nMax, redonda) {
                // cada fileira tem a largura da corda do mostrador na altura do pé dela
                val larguras = List(max(0, nMax)) { i ->
                    val yb = y0 + (i + 1) * passo
                    val corda = if (redonda) 2 * sqrt(max(0f, (h / 2) * (h / 2) - (yb - h / 2) * (yb - h / 2))) else w
                    max(0f, corda - 18f) * densidade
                }
                Quebra.quebrar(visto.linhas, larguras) { medidor.measure(it, estilo).size.width.toFloat() }
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
        if (visto.travado && visto.visivel) {
            val t = remember { mutableLongStateOf(0L) }
            LaunchedEffect(Unit) { while (true) withFrameNanos { t.longValue = it } }
            val cel = Celula.para(w.toDouble(), h.toDouble(), ajustes.tamanhoDe(aparencia.skin).toDouble(), comTexto)
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

        // ── rodapé: o estado da ponte ──
        val estado = when {
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
    }
}

/** A página de [skin] mais perto de [perto], na lista [skins] que gira. */
private fun pagina(skins: List<Skin>, skin: Skin, perto: Int): Int {
    val n = skins.size
    val base = perto - perto.mod(n)
    val i = skins.indexOf(skin).coerceAtLeast(0)
    return listOf(base - n, base, base + n).map { it + i }.minBy { abs(it - perto) }
}

/**
 * Os pontos da lista, à direita: o indicador de páginas do Wear que os
 * avatares do HinaWatch usam, um ponto por orbe e o da vez aceso. A lista
 * gira, então do último para o primeiro um apaga enquanto o outro acende.
 * [posicao] é lida no desenho: a rolagem não recompõe a tela.
 */
@Composable
private fun PontosDaLista(n: Int, posicao: () -> Float, modifier: Modifier = Modifier) {
    Canvas(modifier.size(PILULA, PONTO_PASSO * (n - 1) + PONTO_ACESO + PILULA_FOLGA * 2)) {
        val raio = size.width / 2
        drawRoundRect(Color.Black.copy(alpha = 0.88f), cornerRadius = CornerRadius(raio))
        val p = posicao().mod(n.toFloat())
        val i = floor(p).toInt()
        val f = p - i
        for (k in 0 until n) {
            val aceso = when (k) {
                i -> 1f - f
                (i + 1) % n -> f
                else -> 0f
            }
            val y = (PILULA_FOLGA + PONTO_ACESO / 2 + PONTO_PASSO * k).toPx()
            drawCircle(
                Color.White.copy(alpha = lerp(0.31f, 1f, aceso)),
                radius = lerp(PONTO.toPx(), PONTO_ACESO.toPx(), aceso) / 2,
                center = Offset(raio, y),
            )
        }
    }
}

/**
 * As instâncias de um orbe do Claude, uma embaixo da outra: a 0 é o próprio
 * orbe e as seguintes são as vagas dele de sessão do Claude Code no PC, e por
 * fim uma livre quando falar nela abre uma sessão. Dois dedos na vertical
 * passam de uma a outra, com a mesma roda da lista; um dedo continua sendo da
 * lista (de um orbe a outro), do menu e do voltar do sistema.
 */
@Composable
private fun Fileira(
    vm: OrbeViewModel,
    /** a aparência do orbe desta página (a instância em uso, se é o orbe em tela) */
    aparencia: Aparencia,
    /** a página desta skin assentou na lista */
    emTela: Boolean,
    n: Int,
    tamanho: Float,
    redonda: Boolean,
    pode: () -> Boolean,
    rotulo: @Composable BoxScope.(instancia: Int, atual: Boolean) -> Unit,
) {
    val fileira = lembrarFileira(initialPage = if (emTela) aparencia.instancia.coerceIn(0, n - 1) else 0) { n }
    val escopo = rememberCoroutineScope()
    val view = LocalView.current
    val agora by rememberUpdatedState(aparencia)
    if (emTela) {
        // a instância veio de fora (os ajustes lidos do disco, a sessão que fechou): vai até ela sem animar
        LaunchedEffect(aparencia.instancia, n) {
            val k = aparencia.instancia.coerceIn(0, n - 1)
            if (!fileira.isScrollInProgress && fileira.settledPage != k) fileira.scrollToPage(k)
        }
        // assentou noutra pelos dedos (ou a fileira encurtou): é a instância do relógio
        LaunchedEffect(fileira) {
            snapshotFlow { fileira.settledPage }.collect { k -> if (k != agora.instancia) vm.instancia(k) }
        }
    }
    Box(Modifier.fillMaxSize().pointerInput(fileira) { doisDedos(fileira, escopo, view) }) {
        PaginasDaFileira(
            state = fileira,
            modifier = Modifier.fillMaxSize(),
            beyondViewportPageCount = 0,
            userScrollEnabled = false,           // um dedo é da lista e do menu; dois, daqui
        ) { k ->
            val atual = emTela && k == fileira.settledPage
            Box(
                Modifier
                    .fillMaxSize()
                    .graphicsLayer { roda(fileira.currentPage - k + fileira.currentPageOffsetFraction, vertical = true) },
            ) {
                Orbe(vm, aparencia.copy(instancia = k), atual, tamanho, redonda, pode)
                rotulo(k, atual)
            }
        }
    }
}

/**
 * Um orbe da lista, na skin e na cor de [aparencia]. Em tela ([atual]) é a
 * cena do relógio; a página que entra mostra o dela parado, até assentar.
 */
@Composable
private fun Orbe(vm: OrbeViewModel, aparencia: Aparencia, atual: Boolean, tamanho: Float, redonda: Boolean, pode: () -> Boolean) {
    val rolando = LocalRolando.current
    val densidade = LocalDensity.current.density
    val vizinha = remember { OrbeCena(entrar = false) }
    SideEffect {
        vizinha.skin = aparencia.skin
        vizinha.glitch = aparencia.glitch
        vizinha.varredura = aparencia.linhas
        vizinha.tamanho = tamanho.toDouble()
        vizinha.redonda = redonda
        vizinha.corFundo = aparencia.corFundo()
        vizinha.corTema = aparencia.corFigura()
        vizinha.accent = aparencia.corAnel()
    }
    AndroidView(
        factory = { OrbeView(it, if (atual) vm.cena else vizinha).apply { adaptar = true; parado = !atual || rolando } },
        update = {
            it.cena = if (atual) vm.cena else vizinha
            // a que entra é desenhada uma vez e congela: eram dois orbes
            // grandes por quadro no meio da rolagem. Arrastando para o menu,
            // o orbe também congela: a GPU fica para a tela que anda
            it.parado = !atual || rolando
        },
        modifier = Modifier.fillMaxSize().pointerInput(Unit) { tocar(vm, densidade, pode) },
    )
}

/** Toque curto, segurar para falar e os olhos no dedo; dois dedos são da [Fileira]. */
private suspend fun PointerInputScope.tocar(vm: OrbeViewModel, densidade: Float, pode: () -> Boolean) {
    val folga = viewConfiguration.touchSlop
    awaitEachGesture {
        val baixo = awaitFirstDown(requireUnconsumed = false)
        vm.toqueBaixo(baixo.position.x / densidade, baixo.position.y / densidade, pode())
        // 1 = solto no lugar (toque curto), 2 = andou (é rolagem) ou chegou outro dedo, null = segurou
        val fim = withTimeoutOrNull(SEGURAR_MS) {
            var r = 0
            while (r == 0) {
                val e = awaitPointerEvent()
                val c = e.changes.firstOrNull { it.id == baixo.id }
                r = when {
                    e.changes.count { it.pressed } >= 2 -> 2
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
}

/**
 * Dois dedos na vertical passam de uma instância a outra. O segundo dedo tem
 * que chegar antes do tempo de segurar (depois disso o primeiro já está
 * falando); daí em diante o gesto é todo da fileira, e nem a lista, nem o
 * menu, nem o voltar do sistema o veem: a fileira trata os dedos antes da
 * lista e os consome. Soltos, a
 * fileira assenta na instância mais perto, ou na seguinte se o gesto foi rápido.
 */
private suspend fun PointerInputScope.doisDedos(fileira: EstadoFileira, escopo: CoroutineScope, view: View) {
    val arremesso = ARREMESSO.toPx()
    awaitEachGesture {
        val primeiro = awaitFirstDown(requireUnconsumed = false)
        var e: PointerEvent
        do {
            e = awaitPointerEvent()
            if (e.changes.none { it.pressed }) return@awaitEachGesture
        } while (e.changes.count { it.pressed } < 2)
        if (e.changes.maxOf { it.uptimeMillis } - primeiro.uptimeMillis > SEGURAR_MS) return@awaitEachGesture
        view.parent?.requestDisallowInterceptTouchEvent(true)
        val deltas = Channel<Float>(Channel.UNLIMITED)
        val arrasto = escopo.launch { fileira.scroll { for (d in deltas) scrollBy(d) } }
        val rastro = VelocityTracker()
        var dedos = pressionados(e)
        var antes = centro(e)
        e.changes.forEach { it.consume() }
        try {
            while (true) {
                e = awaitPointerEvent()
                val agora = pressionados(e)
                e.changes.forEach { it.consume() }
                if (agora.isEmpty()) break
                val c = centro(e)
                // um dedo que entra ou sai muda o centro sem que a mão ande
                if (agora == dedos) {
                    deltas.trySend(antes - c)
                    rastro.addPosition(e.changes.first { it.pressed }.uptimeMillis, Offset(0f, c))
                }
                dedos = agora
                antes = c
            }
        } finally {
            deltas.close()
            val v = rastro.calculateVelocity().y
            escopo.launch {
                arrasto.join()
                val pos = fileira.currentPage + fileira.currentPageOffsetFraction
                val alvo = when {
                    v < -arremesso -> floor(pos).toInt() + 1
                    v > arremesso -> ceil(pos).toInt() - 1
                    else -> pos.roundToInt()
                }
                fileira.animateScrollToPage(alvo.coerceIn(0, max(0, fileira.pageCount - 1)))
            }
        }
    }
}

private fun pressionados(e: PointerEvent) = e.changes.filter { it.pressed }.map { it.id }.toSet()

/** A altura média dos dedos na tela. */
private fun centro(e: PointerEvent): Float = e.changes.filter { it.pressed }.let { v -> v.sumOf { it.position.y.toDouble() }.toFloat() / v.size }

/** A roda: o orbe encolhe ao sair do centro e anda para perto dele, com a mesma folga em qualquer ponto da rolagem. */
private fun GraphicsLayerScope.roda(desvio: Float, vertical: Boolean) {
    val escala = lerp(1f, RODA_ESCALA, abs(desvio).coerceIn(0f, 1f))
    scaleX = escala
    scaleY = escala
    if (vertical) translationY = desvio * size.height * RODA_PUXAO
    else translationX = desvio * size.width * RODA_PUXAO
}

/**
 * A sessão do Claude Code de uma instância, discreta e curvada na borda da
 * tela: uma linha no alto com o agente e o título da conversa, na cor da
 * instância, e uma no pé com a pasta em que ela foi aberta e se ouve o orbe.
 * Com o raciocínio na tela, o pé é dele.
 */
@Composable
private fun RotuloSessao(sessao: SessaoInfo?, abreClaude: Boolean, agente: String, cor: Color, comPe: Boolean, modifier: Modifier = Modifier) {
    val titulo = sessao?.let { it.titulo.ifEmpty { it.rotulo } } ?: "livre"
    val pasta = sessao?.pasta.orEmpty().let { if (it.isEmpty() || it.startsWith("/")) it else "/$it" }
    val pe = when {
        sessao == null -> if (abreClaude) "falar aqui abre uma sessão" else ""
        sessao.canal || sessao.ouve -> listOf(pasta, "ouve o orbe").filter { it.isNotEmpty() }.joinToString(" · ")
        else -> listOf(pasta, "não ouve o orbe").filter { it.isNotEmpty() }.joinToString(" · ")
    }
    Rotulo(listOf(agente, titulo).filter { it.isNotEmpty() }.joinToString(" · "), if (comPe) pe else "", cor, modifier)
}

/** O rótulo curvado na borda: [alto] na [cor] do orbe, [pe] apagado embaixo. */
@Composable
private fun Rotulo(alto: String, pe: String, cor: Color, modifier: Modifier = Modifier) {
    val corTitulo = cor.alfa(0.75f)
    val corPe = Estilo.texto.alfa(0.45f)
    Box(modifier.padding(BORDA_ROTULO)) {
        if (alto.isNotEmpty()) {
            CurvedLayout(anchor = 270f) {
                basicCurvedText(
                    alto,
                    style = { CurvedTextStyle(color = corTitulo, fontSize = 10.sp) },
                    modifier = CurvedModifier.sizeIn(maxSweepDegrees = ARCO_TITULO),
                    overflow = TextOverflow.Ellipsis,
                )
            }
        }
        if (pe.isNotEmpty()) {
            // no pé a leitura é da esquerda para a direita: o sentido contrário ao do alto
            CurvedLayout(anchor = 90f, angularDirection = CurvedDirection.Angular.Reversed) {
                basicCurvedText(
                    pe,
                    style = { CurvedTextStyle(color = corPe, fontSize = 9.sp, fontFamily = FontFamily.Monospace) },
                    modifier = CurvedModifier.sizeIn(maxSweepDegrees = ARCO_ROTULO),
                    angularDirection = CurvedDirection.Angular.Reversed,
                    overflow = TextOverflow.Ellipsis,
                )
            }
        }
    }
}
