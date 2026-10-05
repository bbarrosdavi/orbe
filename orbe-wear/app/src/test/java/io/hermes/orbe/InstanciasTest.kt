package io.hermes.orbe

import io.hermes.orbe.orbe.Instancias
import io.hermes.orbe.orbe.Skin
import org.junit.Assert.assertEquals
import org.junit.Test

class InstanciasTest {
    @Test
    fun aFileiraVaiAteAUltimaVagaOcupada() {
        // sem sessão, só o próprio orbe; com a vaga 2 ocupada, as três (a 1 livre no meio)
        assertEquals(1, Instancias.contar(emptyList(), abre = false))
        assertEquals(1, Instancias.contar(listOf(0), abre = false))
        assertEquals(3, Instancias.contar(listOf(0, 2), abre = false))
    }

    @Test
    fun quemAbreSessaoGanhaUmaLivreNoFim() {
        // o próprio orbe já é a livre quando não há sessão
        assertEquals(1, Instancias.contar(emptyList(), abre = true))
        assertEquals(2, Instancias.contar(listOf(0), abre = true))
        assertEquals(4, Instancias.contar(listOf(2, 0), abre = true))
    }

    @Test
    fun cadaInstanciaTemACorDela() {
        // a 0 (o orbe) na cor do tema; as seguintes no ciclo, que recomeça depois da última cor
        assertEquals(0, Instancias.cor(0))
        assertEquals(1, Instancias.cor(1))
        assertEquals(0, Instancias.cor(Instancias.cores.size))
    }

    @Test
    fun aListaComecaPeloAnelEPeloSeraphim() {
        assertEquals(listOf(Skin.ANEL, Skin.SERAFIM_GRAVURA), Skin.entries.take(2))
    }
}
