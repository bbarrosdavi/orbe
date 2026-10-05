package io.hermes.orbe.ui

import androidx.compose.foundation.layout.BoxWithConstraints
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.input.pointer.pointerInput
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.sp
import androidx.wear.compose.foundation.lazy.TransformingLazyColumnState
import io.hermes.orbe.dados.Historico
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale

/**
 * O histórico de sessões do agente do orbe em tela, aberto por quatro toques
 * (com a opção na aba Ativação): escolher uma retoma a conversa no PC e o orbe
 * passa a falar com ela. O voltar do sistema fecha sem escolher.
 */
@Composable
fun TelaHistorico(
    historico: Historico,
    agente: String,
    lista: TransformingLazyColumnState,
    redonda: Boolean,
    retomar: (String) -> Unit,
    modifier: Modifier = Modifier,
) {
    BoxWithConstraints(
        modifier
            .fillMaxSize()
            // por cima do orbe: o toque que a lista não usa não chega nele
            .pointerInput(Unit) { awaitPointerEventScope { while (true) awaitPointerEvent().changes.forEach { it.consume() } } },
    ) {
        FundoVidro()
        val margem = maxWidth * (if (redonda) 0.12f else 0.05f)
        Menu(lista, margem) {
            item {
                Column(Modifier.fillMaxWidth(), horizontalAlignment = Alignment.CenterHorizontally) {
                    Texto("Histórico", Estilo.grupo.copy(fontSize = 13.sp), alinhar = TextAlign.Center)
                    if (agente.isNotEmpty()) Texto(agente, Estilo.subtitulo, cor = Estilo.texto.alfa(0.55f), alinhar = TextAlign.Center)
                }
            }
            when {
                historico.carregando -> linha { Linha("Buscando as sessões…") }
                historico.erro.isNotEmpty() -> linha { Linha(historico.erro) }
                historico.sessoes.isEmpty() -> linha { Linha("Nenhuma sessão") }
                else -> historico.sessoes.forEach { s ->
                    linha {
                        Linha(
                            s.titulo.ifEmpty { s.id.take(8) },
                            subtitulo = listOf(pasta(s.pasta), quando(s.quando)).filter { it.isNotEmpty() }.joinToString(" · "),
                            aoClicar = { retomar(s.id) },
                        )
                    }
                }
            }
        }
    }
}

/** A pasta como no rótulo da sessão: com a barra na frente. */
private fun pasta(p: String): String = if (p.isEmpty() || p.startsWith("/")) p else "/$p"

/** Há quanto tempo, curto: "há 5 min", "ontem", "3 out". */
private fun quando(s: Long): String {
    if (s <= 0) return ""
    val d = System.currentTimeMillis() / 1000 - s
    return when {
        d < 60 -> "agora"
        d < 3600 -> "há ${d / 60} min"
        d < 86400 -> "há ${d / 3600} h"
        d < 2 * 86400 -> "ontem"
        else -> SimpleDateFormat("d MMM", Locale.forLanguageTag("pt-BR")).format(Date(s * 1000)).trimEnd('.')
    }
}
