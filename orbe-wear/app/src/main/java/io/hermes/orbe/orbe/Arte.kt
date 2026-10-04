package io.hermes.orbe.orbe

import kotlin.math.sin
import kotlin.random.Random

/** Valores de uniform por nome; o Pintor os entrega ao programa a cada quadro. */
class Uniformes {
    val mapa = HashMap<String, FloatArray>()

    fun v1(nome: String, a: Double) {
        mapa.getOrPut(nome) { FloatArray(1) }[0] = a.toFloat()
    }

    fun v2(nome: String, a: Double, b: Double) {
        val v = mapa.getOrPut(nome) { FloatArray(2) }
        v[0] = a.toFloat(); v[1] = b.toFloat()
    }

    fun v4(nome: String, a: Double, b: Double, c: Double, d: Double) {
        val v = mapa.getOrPut(nome) { FloatArray(4) }
        v[0] = a.toFloat(); v[1] = b.toFloat(); v[2] = c.toFloat(); v[3] = d.toFloat()
    }

    fun zero4(nome: String) = v4(nome, 0.0, 0.0, 0.0, 0.0)

    operator fun get(nome: String): FloatArray? = mapa[nome]
}

/**
 * O que desenha o orbe: a Figura (avatares) ou o Anel (rotoscope). Guarda o que
 * tem memória entre quadros e monta os uniforms dos dois passes; o desenho é
 * dos shaders do orbe-qt.
 */
interface Arte {
    val skin: Skin
    /** primeiro passe: a máscara da figura */
    val fx: Uniformes
    /** segundo passe (pos.frag): cor, glitch e sombra */
    val pos: Uniformes
    /** a célula da figura no item (cx, cy, meia largura, meia altura): fora dela a máscara é vazia */
    val recorte: DoubleArray

    fun avancar(dt: Double)

    /** [w] x [h] é o item inteiro; a figura cabe na célula [cw] x [ch] centrada em ([cx], [cy]). */
    fun montar(w: Double, h: Double, cx: Double, cy: Double, cw: Double, ch: Double)
}

internal const val TAU = 2 * Math.PI

internal fun lim01(v: Double) = if (v < 0) 0.0 else if (v > 1) 1.0 else v
internal fun suave(p: Double): Double { val q = lim01(p); return q * q * (3 - 2 * q) }
internal fun uni(a: Double, b: Double) = a + Random.nextDouble() * (b - a)
internal fun sorteia(n: Int) = Random.nextInt(n)
internal fun ruido(t: Double, s: Double) =
    sin(t * 1.31 + s) * 0.5 + sin(t * 2.17 + s * 1.7) * 0.3 + sin(t * 0.53 + s * 2.9) * 0.2
