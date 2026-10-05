package io.hermes.orbe.gl

import android.opengl.GLES30
import io.hermes.orbe.orbe.TAU
import io.hermes.orbe.orbe.Uniformes
import kotlin.math.cos
import kotlin.math.min
import kotlin.math.roundToInt
import kotlin.math.sin

/**
 * O Ophanim por elemento (as primitivas do fim do figura.frag): cada elemento
 * num desenho só na área dele, na ordem do laço da tela inteira, misturado na
 * máscara com o "sobre" (src + (1 - a) dst). Na GPU de um relógio a figura por
 * pixel não cabe: cada pixel rodava o código dos 30 olhos, dos 4 aros e dos
 * raios, e quase nenhum passa por ele.
 *
 * Uma por contexto GL (o VAO sem atributos é do contexto que a criou).
 */
internal class Primitivas {
    private val vazio = IntArray(1).also { GLES30.glGenVertexArrays(1, it, 0) }[0]
    private val nomesAros = Array(4) { "a${it}u" to "a${it}v" }
    private val zOlhos = FloatArray(32)
    private val ordem = IntArray(32)

    /** No FBO da máscara já limpo (cor e estêncil); [aa] = px lógicos por px da máscara. Deixa o VAO vazio ligado. */
    fun desenhar(p: Programa, fx: Uniformes, aa: Float) {
        GLES30.glBindVertexArray(vazio)
        GLES30.glEnable(GLES30.GL_BLEND)
        GLES30.glBlendFunc(GLES30.GL_ONE, GLES30.GL_ONE_MINUS_SRC_ALPHA)
        GLES30.glUseProgram(p.id)
        p.aplicar(fx)
        p.v1("qt_Opacity", 1f)
        fun desenho(tipo: Int, indice: Int, vertices: Int, vezes: Int) {
            p.v4("prim", tipo.toFloat(), indice.toFloat(), aa, SEGMENTOS.toFloat())
            GLES30.glDrawArraysInstanced(GLES30.GL_TRIANGLE_STRIP, 0, vertices, vezes)
        }
        val lacos = fx["lacos"]
        val raios = fx["raios"]
        if (lacos != null && raios != null) {
            if (raios[3] > 0.001f && raios[0] >= 1f) desenho(0, 0, 4, raios[0].toInt())
            desenho(1, 0, 2 * SEGMENTOS + 2, 8)                        // ondas; o vértice pula as apagadas
            // cada asa em partes, na ordem de asa(); a da frente esconde o que veio antes
            for (i in 0 until lacos[3].roundToInt()) {
                desenho(2, i, 4, 1)                                      // sombra (só com ocultar)
                desenho(9, i, 4, 1)                                      // osso
                desenho(10, i, 4, 9)                                     // penas
                desenho(11, i, 4, 8)                                     // borda de fuga
                desenho(12, i, 4, 5)                                     // coberteiras
                desenho(8, i, 4, 3)                                      // olhos das penas
            }
            // aros: os retângulos dos segmentos se cruzam, e cada pixel pinta uma vez por aro
            GLES30.glEnable(GLES30.GL_STENCIL_TEST)
            GLES30.glStencilOp(GLES30.GL_KEEP, GLES30.GL_KEEP, GLES30.GL_REPLACE)
            for (i in 0 until 4) {
                GLES30.glStencilFunc(GLES30.GL_NOTEQUAL, i + 1, 0xFF)
                desenho(3, i, 4, 2 * SEGMENTOS)
            }
            GLES30.glDisable(GLES30.GL_STENCIL_TEST)
            val est = fx["est"]
            if (est != null && (16 * est[1] + 5 * est[2]) / 16 > 0.002f) desenho(4, 0, 4, lacos[1].roundToInt())
            desenho(5, 0, 4, 2)                                          // relâmpagos
            val n = ordenarOlhos(fx, min(lacos[0].roundToInt(), zOlhos.size))
            for (k in 0 until n) desenho(6, ordem[k], 4, 1)
            desenho(7, 0, 4, 1)                                          // núcleo
        }
    }

    /** Os olhos dos aros de trás para a frente (o z de olhoPos no figura.frag), em [ordem]. */
    private fun ordenarOlhos(fx: Uniformes, n: Int): Int {
        val fase = fx["ofa2"]?.get(0)?.toDouble() ?: 0.0
        for (idx in 0 until n) {
            // aros com 7, 8, 6 e 9 olhos (olhoDoAro)
            val aro = if (idx < 7) 0 else if (idx < 15) 1 else if (idx < 21) 2 else 3
            val ini = when (aro) { 0 -> 0; 1 -> 7; 2 -> 15; else -> 21 }
            val nAro = when (aro) { 0 -> 7; 1 -> 8; 2 -> 6; else -> 9 }
            val th = (idx - ini) * TAU / nAro + fase * 0.05 * (aro + 1)
            val u = fx[nomesAros[aro].first]
            val v = fx[nomesAros[aro].second]
            zOlhos[idx] = if (u == null || v == null) 0f else (cos(th) * u[2] + sin(th) * v[2]).toFloat()
            // inserção: estável, e são 30
            var j = idx
            while (j > 0 && zOlhos[ordem[j - 1]] > zOlhos[idx]) {
                ordem[j] = ordem[j - 1]
                j--
            }
            ordem[j] = idx
        }
        return n
    }

    private companion object {
        // segmentos de cada aro e de cada onda
        const val SEGMENTOS = 64
    }
}
