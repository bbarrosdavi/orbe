package io.hermes.orbe.ui

import androidx.activity.compose.BackHandler
import androidx.compose.foundation.focusable
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.pager.VerticalPager
import androidx.compose.foundation.pager.rememberPagerState
import androidx.compose.foundation.rememberScrollState
import androidx.compose.runtime.Composable
import androidx.compose.runtime.CompositionLocalProvider
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.SideEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.ui.Modifier
import androidx.compose.ui.focus.FocusRequester
import androidx.compose.ui.focus.focusRequester
import androidx.compose.ui.input.rotary.onRotaryScrollEvent
import androidx.compose.ui.platform.LocalConfiguration
import androidx.compose.ui.platform.LocalView
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import io.hermes.orbe.OrbeViewModel
import io.hermes.orbe.dados.Ligacao
import kotlinx.coroutines.launch

/**
 * As duas páginas do relógio, uma sobre a outra: o orbe e, arrastando para
 * cima (ou girando a coroa), o menu. Voltar do menu cai no orbe.
 */
@Composable
fun OrbeApp(
    vm: OrbeViewModel,
    podeGravar: () -> Boolean,
    pedirMicrofone: () -> Unit,
    editar: (Campo) -> Unit,
) {
    val aparencia by vm.aparencia.collectAsStateWithLifecycle()
    val ajustes by vm.ajustes.collectAsStateWithLifecycle()
    val retrato by vm.retrato.collectAsStateWithLifecycle()
    val ligacao by vm.ligacao.collectAsStateWithLifecycle()
    val previa by vm.previa.collectAsStateWithLifecycle()
    val redonda = LocalConfiguration.current.isScreenRound
    val paginas = rememberPagerState { 2 }
    val rolagem = rememberScrollState()
    val escopo = rememberCoroutineScope()
    val foco = remember { FocusRequester() }

    // com a sessão aberta a tela não apaga no meio da conversa
    val view = LocalView.current
    SideEffect { view.keepScreenOn = retrato.visivel || previa != null }

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
        LocalRolando provides (paginas.isScrollInProgress || rolagem.isScrollInProgress),
    ) {
        VerticalPager(
            state = paginas,
            modifier = Modifier
                .fillMaxSize()
                .onRotaryScrollEvent { e ->
                    val d = e.verticalScrollPixels
                    if (paginas.currentPage == 0) {
                        if (d > 0 && !paginas.isScrollInProgress) escopo.launch { paginas.animateScrollToPage(1) }
                    } else if (d < 0 && rolagem.value == 0) {
                        if (!paginas.isScrollInProgress) escopo.launch { paginas.animateScrollToPage(0) }
                    } else {
                        rolagem.dispatchRawDelta(d)
                    }
                    true
                }
                .focusRequester(foco)
                .focusable(),
            // as duas páginas ficam montadas: as miniaturas do menu não nascem no meio do arrasto
            beyondViewportPageCount = 1,
        ) { pagina ->
            if (pagina == 0) {
                TelaOrbe(vm, redonda, podeGravar, abrirAjustes = { escopo.launch { paginas.animateScrollToPage(1) } })
            } else {
                TelaAjustes(
                    vm, rolagem, redonda, editar, pedirMicrofone,
                    aoPrevia = { escopo.launch { paginas.animateScrollToPage(0) } },
                )
            }
        }
    }
    BackHandler(paginas.currentPage == 1) { escopo.launch { paginas.animateScrollToPage(0) } }
    LaunchedEffect(Unit) { foco.requestFocus() }
    // de volta ao orbe, o menu recomeça do alto na próxima visita
    LaunchedEffect(paginas.settledPage) { if (paginas.settledPage == 0) rolagem.scrollTo(0) }
}
