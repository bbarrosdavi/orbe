package io.hermes.orbe.ui

import androidx.activity.compose.BackHandler
import androidx.compose.foundation.background
import androidx.compose.foundation.focusable
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.pager.HorizontalPager
import androidx.compose.foundation.pager.rememberPagerState
import androidx.compose.runtime.Composable
import androidx.compose.runtime.CompositionLocalProvider
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.MutableState
import androidx.compose.runtime.SideEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.ui.Modifier
import androidx.compose.ui.focus.FocusRequester
import androidx.compose.ui.focus.focusRequester
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.graphicsLayer
import androidx.compose.ui.input.rotary.onRotaryScrollEvent
import androidx.compose.ui.platform.LocalConfiguration
import androidx.compose.ui.platform.LocalView
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import androidx.wear.compose.foundation.lazy.rememberTransformingLazyColumnState
import io.hermes.orbe.OrbeViewModel
import io.hermes.orbe.dados.Ligacao
import io.hermes.orbe.gesto.Picos
import kotlin.math.abs
import kotlin.math.sign
import kotlinx.coroutines.channels.BufferOverflow
import kotlinx.coroutines.flow.MutableSharedFlow
import kotlinx.coroutines.launch

/**
 * As duas páginas do relógio, lado a lado: o orbe e, arrastando para a
 * esquerda, o menu (a gaveta e as abas). Na vertical (dedo ou coroa) a lista
 * passa de orbe em orbe; no menu, a coroa rola a gaveta ou a aba. Voltar da aba
 * cai na gaveta, e da gaveta no orbe. No menu o pager não arrasta: puxar para a
 * direita volta um nível e para a esquerda volta ao orbe (TelaAjustes). O fundo
 * do menu fica parado atrás das duas páginas: só o conteúdo anda, sem a emenda
 * de um fundo no outro.
 */
@Composable
fun OrbeApp(
    vm: OrbeViewModel,
    podeGravar: () -> Boolean,
    pedirMicrofone: () -> Unit,
    editar: (Campo) -> Unit,
    /** o menu pedido pelo adb: "gaveta" ou o nome de uma aba; volta a null depois de abrir */
    menuPedido: MutableState<String?>,
) {
    val aparencia by vm.aparencia.collectAsStateWithLifecycle()
    val ajustes by vm.ajustes.collectAsStateWithLifecycle()
    val retrato by vm.retrato.collectAsStateWithLifecycle()
    val ligacao by vm.ligacao.collectAsStateWithLifecycle()
    val redonda = LocalConfiguration.current.isScreenRound
    val paginas = rememberPagerState { 2 }
    val gaveta = rememberTransformingLazyColumnState()
    val lista = rememberTransformingLazyColumnState()
    // a aba aberta no menu; null = a gaveta
    var aba by remember { mutableStateOf<Aba?>(null) }
    val escopo = rememberCoroutineScope()
    val foco = remember { FocusRequester() }
    // a coroa no orbe: um orbe da lista a cada tanto de giro
    val coroa = remember { MutableSharedFlow<Int>(extraBufferCapacity = 1, onBufferOverflow = BufferOverflow.DROP_OLDEST) }
    val giro = remember { floatArrayOf(0f) }
    // a calibração da sacudida cobre o menu até salvar ou voltar
    var calibrando by remember { mutableStateOf<Calibracao?>(null) }

    // com a sessão aberta a tela não apaga no meio da conversa
    val view = LocalView.current
    SideEffect { view.keepScreenOn = retrato.visivel }

    // a ponte aceita a fala do relógio: é a hora de pedir o microfone, uma vez só
    val aceitaFala = (ligacao as? Ligacao.Conectada)?.microfone == true
    LaunchedEffect(aceitaFala, ajustes.microfone, ajustes.pediuMicrofone) {
        if (aceitaFala && ajustes.microfone && !ajustes.pediuMicrofone) {
            vm.pediuMicrofone()
            if (!podeGravar()) pedirMicrofone()
        }
    }

    CompositionLocalProvider(
        LocalTema provides aparencia.tema,
        LocalRolando provides (paginas.isScrollInProgress || gaveta.isScrollInProgress || lista.isScrollInProgress),
    ) {
      Box(Modifier.fillMaxSize().background(Color.Black)) {
        // sem o fundo atrás do orbe, ele acende junto com a entrada do menu
        FundoVidro(
            Modifier.graphicsLayer {
                alpha = if (ajustes.fundo) 1f else (paginas.currentPage + paginas.currentPageOffsetFraction).coerceIn(0f, 1f)
            },
        )
        HorizontalPager(
            state = paginas,
            modifier = Modifier
                .fillMaxSize()
                .onRotaryScrollEvent { e ->
                    val d = e.verticalScrollPixels
                    if (paginas.currentPage == 0) {
                        giro[0] += d
                        if (abs(giro[0]) >= GIRO_POR_PASSO) {
                            coroa.tryEmit(giro[0].sign.toInt())
                            giro[0] = 0f
                        }
                    } else {
                        (if (aba == null) gaveta else lista).dispatchRawDelta(d)
                    }
                    true
                }
                .focusRequester(foco)
                .focusable(),
            // as duas páginas ficam montadas: o menu pede as prévias das miniaturas
            // já na abertura, e não nasce no meio do arrasto
            beyondViewportPageCount = 1,
            // assentado no menu, os puxões são da TelaAjustes: o pager não leva ao orbe por conta própria
            userScrollEnabled = paginas.settledPage == 0,
        ) { pagina ->
            if (pagina == 0) {
                TelaOrbe(vm, redonda, podeGravar, abrirAjustes = { escopo.launch { paginas.animateScrollToPage(1) } }, coroa = coroa)
            } else {
                TelaAjustes(
                    vm, gaveta, lista, aba,
                    abrir = { a ->
                        // cada aba abre do alto
                        if (a != null) escopo.launch { lista.scrollToItem(0) }
                        aba = a
                    },
                    redonda,
                    visivel = paginas.currentPage == 1 || paginas.targetPage == 1,
                    editar, pedirMicrofone, podeGravar,
                    aoOrbe = { escopo.launch { paginas.animateScrollToPage(0) } },
                    calibrar = { calibrando = it },
                )
            }
        }
        when (calibrando) {
            Calibracao.ABRIR -> TelaCalibracao(
                Picos(ajustes.sacudidaFora, ajustes.sacudidaDentro), redonda,
                salvar = {
                    vm.calibrarSacudida(it)
                    calibrando = null
                },
                padrao = {
                    vm.sacudidaPadrao()
                    calibrando = null
                },
            )
            Calibracao.SAIR -> TelaCalibracaoSair(
                ajustes.sairFora, redonda,
                salvar = {
                    vm.calibrarSair(it)
                    calibrando = null
                },
                padrao = {
                    vm.calibrarSair(0f)
                    calibrando = null
                },
            )
            null -> Unit
        }
      }
    }
    BackHandler(calibrando != null) { calibrando = null }
    BackHandler(calibrando == null && paginas.currentPage == 1) {
        if (aba != null) aba = null else escopo.launch { paginas.animateScrollToPage(0) }
    }
    LaunchedEffect(Unit) { foco.requestFocus() }
    LaunchedEffect(menuPedido.value) {
        val m = menuPedido.value ?: return@LaunchedEffect
        menuPedido.value = null
        paginas.scrollToPage(1)
        aba = Aba.entries.firstOrNull { it.name.equals(m, ignoreCase = true) }
    }
    // de volta ao orbe, o menu recomeça da gaveta, do alto, na próxima visita
    LaunchedEffect(paginas.settledPage) {
        if (paginas.settledPage == 0) {
            aba = null
            gaveta.scrollToItem(0)
        }
    }
}

/** Pixels de giro da coroa por orbe da lista. */
private const val GIRO_POR_PASSO = 90f
