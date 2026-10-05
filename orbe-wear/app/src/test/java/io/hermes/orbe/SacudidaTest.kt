package io.hermes.orbe

import io.hermes.orbe.gesto.Gesto
import io.hermes.orbe.gesto.Picos
import io.hermes.orbe.gesto.Sacudida
import io.hermes.orbe.gesto.limiarSair
import io.hermes.orbe.gesto.limiares
import org.junit.Assert.assertEquals
import org.junit.Test

class SacudidaTest {
    /** Leituras a cada 10 ms: parado, depois os giros (ωx, duração), depois quieto; devolve o que saiu. */
    private fun sequencia(vararg giros: Pair<Float, Int>, parado: Int = 400, s: Sacudida = Sacudida()): List<Gesto> {
        s.gravidade(5f, 7f)      // olhando o relógio: para dentro é ωx positivo
        val saiu = ArrayList<Gesto>()
        var t = 0L
        fun ler(w: Float) {
            s.ler(t, w, kotlin.math.abs(w))?.let(saiu::add)
            t += 10
        }
        repeat(parado / 10) { ler(0f) }
        for ((w, ms) in giros) repeat(ms / 10) { ler(w) }
        repeat(80) { ler(0f) }
        return saiu
    }

    @Test
    fun umaSacudidaAbreOOrbe() {
        assertEquals(listOf(Gesto.UMA), sequencia(-6f to 60, 12f to 60))
    }

    @Test
    fun duasSaoDoHinaWatch() {
        assertEquals(listOf(Gesto.DUAS), sequencia(-6f to 60, 12f to 60, -6f to 60, 12f to 60))
    }

    @Test
    fun levantarOPulsoAntesDeArmarNaoConta() {
        // sem a parada antes, o giro é o levantar do pulso para acender a tela
        assertEquals(emptyList<Gesto>(), sequencia(-6f to 60, 12f to 60, parado = 100))
    }

    @Test
    fun soParaDentroNaoEGesto() {
        assertEquals(emptyList<Gesto>(), sequencia(12f to 60))
    }

    /** O detector do orbe aberto: o sair na hora, com a parada de 600 ms antes de armar. */
    private fun aberto(foraSair: Float = 0f) = Sacudida(paradoMs = Sacudida.PARADO_MS).apply {
        sairNaHora = true
        sairForaMin = foraSair
    }

    @Test
    fun comOOrbeAbertoParaForaSaiNaHora() {
        // a volta do pulso depois não vira outro gesto
        assertEquals(listOf(Gesto.SAIR), sequencia(-6f to 60, 12f to 60, parado = 700, s = aberto()))
    }

    @Test
    fun semOSairParaForaNaoEGesto() {
        assertEquals(emptyList<Gesto>(), sequencia(-6f to 60, parado = 700))
    }

    @Test
    fun foraFracoNaoSai() {
        assertEquals(emptyList<Gesto>(), sequencia(-3f to 60, parado = 700, s = aberto()))
    }

    @Test
    fun oForaCalibradoVale() {
        assertEquals(emptyList<Gesto>(), sequencia(-6f to 60, parado = 700, s = aberto(foraSair = 8f)))
        assertEquals(listOf(Gesto.SAIR), sequencia(-10f to 60, parado = 700, s = aberto(foraSair = 8f)))
    }

    @Test
    fun comecarParaDentroNaoSai() {
        assertEquals(emptyList<Gesto>(), sequencia(12f to 60, -6f to 60, parado = 700, s = aberto()))
    }

    @Test
    fun aCalibracaoDoSairMedeOFora() {
        val s = Sacudida(paradoMs = Sacudida.PARADO_MS)
        sequencia(-9f to 60, 2f to 40, parado = 700, s = s)
        assertEquals(9f, s.tirarFora()!!, 1e-4f)
        assertEquals(null, s.tirarFora())
        assertEquals(6f, limiarSair(listOf(12f, 10f, 14f)), 1e-4f)
        assertEquals(Sacudida.FORTE_MIN, limiarSair(listOf(1f)), 1e-6f)
    }

    @Test
    fun calibracaoPegaAMaisFracaComMargem() {
        val l = limiares(listOf(Picos(10f, 20f), Picos(6f, 15f), Picos(8f, 18f)))
        assertEquals(3.6f, l.fora, 1e-4f)
        assertEquals(9f, l.dentro, 1e-4f)
        // nunca abaixo do pico forte
        assertEquals(Sacudida.FORTE_MIN, limiares(listOf(Picos(1f, 1f))).fora, 1e-6f)
    }
}
