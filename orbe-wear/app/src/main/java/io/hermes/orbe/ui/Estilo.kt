package io.hermes.orbe.ui

import androidx.compose.runtime.Composable
import androidx.compose.runtime.Immutable
import androidx.compose.runtime.ReadOnlyComposable
import androidx.compose.runtime.staticCompositionLocalOf
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.TextStyle
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.sp

/**
 * As cores do app do Orbe (orbe-qt/app/Estilo.qml): as do matugen no PC, que a
 * ponte manda no "ola". Sem ponte, os mesmos padrões do desktop.
 */
@Immutable
data class Tema(
    val accent: Color,
    val accentFg: Color,
    val fundo: Color,
    val texto: Color,
    val vista: Color,
    val popover: Color,
    /** accent do anel de energia (o do CSS do sistema, não o do GTK) */
    val anel: Color,
) {
    companion object {
        val Padrao = Tema(
            accent = Color(0xFFB8CACB), accentFg = Color(0xFF233334), fundo = Color(0xFF121414),
            texto = Color(0xFFE3E2E2), vista = Color(0xFF121414), popover = Color(0xFF1F2020),
            anel = Color(0xFF0087FC),
        )

        /** Do mapa da ponte (accent_bg_color, window_bg_color, ...); o que faltar fica no padrão. */
        fun de(m: Map<String, String>): Tema = Tema(
            accent = cor(m["accent_bg_color"]) ?: Padrao.accent,
            accentFg = cor(m["accent_fg_color"]) ?: Padrao.accentFg,
            fundo = cor(m["window_bg_color"]) ?: Padrao.fundo,
            texto = cor(m["window_fg_color"]) ?: Padrao.texto,
            vista = cor(m["view_bg_color"]) ?: Padrao.vista,
            popover = cor(m["popover_bg_color"]) ?: Padrao.popover,
            anel = cor(m["anel"]) ?: Padrao.anel,
        )

        private fun cor(hex: String?): Color? {
            val h = hex?.trim()?.removePrefix("#") ?: return null
            if (h.length != 6) return null
            return h.toLongOrNull(16)?.let { Color(0xFF000000 or it) }
        }
    }
}

val LocalTema = staticCompositionLocalOf { Tema.Padrao }

/** Estilo.accent, Estilo.texto...: como no QML. */
object Estilo {
    val accent: Color @Composable @ReadOnlyComposable get() = LocalTema.current.accent
    val accentFg: Color @Composable @ReadOnlyComposable get() = LocalTema.current.accentFg
    val fundo: Color @Composable @ReadOnlyComposable get() = LocalTema.current.fundo
    val texto: Color @Composable @ReadOnlyComposable get() = LocalTema.current.texto
    val vista: Color @Composable @ReadOnlyComposable get() = LocalTema.current.vista
    val popover: Color @Composable @ReadOnlyComposable get() = LocalTema.current.popover
    val anel: Color @Composable @ReadOnlyComposable get() = LocalTema.current.anel

    // os 11 pt e 9 pt do app numa janela de 500 px, na medida do pulso
    val titulo = TextStyle(fontSize = 12.sp, lineHeight = 14.sp)
    val subtitulo = TextStyle(fontSize = 9.sp, lineHeight = 11.sp)
    val grupo = TextStyle(fontSize = 11.sp, fontWeight = FontWeight.Bold)
    val botao = TextStyle(fontSize = 11.sp, fontWeight = FontWeight.Bold)
    val cartao = TextStyle(fontSize = 8.sp, fontWeight = FontWeight.Bold, lineHeight = 9.sp)
    /** o "ORBE" do topo e a linha de estado do rodapé */
    val mono = TextStyle(fontSize = 8.5.sp, fontFamily = FontFamily.Monospace)
}

fun Color.alfa(a: Float): Color = copy(alpha = a)

fun Color.rgb(): FloatArray = floatArrayOf(red, green, blue)
