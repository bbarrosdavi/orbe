package io.hermes.orbe

import io.hermes.orbe.dados.Ajustes
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
    fun asVagasSeAlternamEntreOsOrbesDoClaude() {
        // dois orbes do Claude: o primeiro tem as vagas 0, 2, 4…; o segundo, 1, 3, 5…
        assertEquals(0, Instancias.vaga(0, 0, 2))
        assertEquals(1, Instancias.vaga(0, 1, 2))
        assertEquals(2, Instancias.vaga(1, 0, 2))
        assertEquals(5, Instancias.vaga(2, 1, 2))
        // um só orbe do Claude: a instância é a vaga
        assertEquals(3, Instancias.vaga(3, 0, 1))
    }

    @Test
    fun cadaOrbeVeSoAsSessoesDasVagasDele() {
        val vagas = listOf(0, 1, 3, 4)
        assertEquals(listOf(0, 2), Instancias.doOrbe(vagas, 0, 2))
        assertEquals(listOf(0, 1), Instancias.doOrbe(vagas, 1, 2))
        // a mesma conversa não aparece em dois orbes
        assertEquals(emptyList<Int>(), Instancias.doOrbe(listOf(1), 0, 2))
        // a fileira do segundo orbe vai até a vaga 3 (a instância 1 dele) e ganha a livre
        assertEquals(3, Instancias.contar(Instancias.doOrbe(vagas, 1, 2), abre = true))
    }

    @Test
    fun cadaInstanciaTemACorDela() {
        // a 0 (o orbe) na cor do tema; as seguintes no ciclo, que recomeça depois da última cor
        assertEquals(0, Instancias.cor(0))
        assertEquals(1, Instancias.cor(1))
        assertEquals(0, Instancias.cor(Instancias.cores.size))
    }

    @Test
    fun aCorQueOOrbeDoPcSegueEstaEmHex() {
        // a 0 fica com a do tema, no PC também
        assertEquals("-", Instancias.corHex(0))
        assertEquals("#4DD0E1", Instancias.corHex(1))
        assertEquals("#B39DDB", Instancias.corHex(4))
        assertEquals("-", Instancias.corHex(Instancias.cores.size))
    }

    @Test
    fun aListaComecaPeloAnelEPeloSeraphim() {
        assertEquals(listOf(Skin.ANEL, Skin.SERAFIM_GRAVURA), Skin.entries.take(2))
    }

    @Test
    fun aOrdemEscolhidaVemPrimeiroEAsOutrasDepois() {
        assertEquals(Skin.entries, Ajustes().skins())
        assertEquals(
            listOf(Skin.OFANIM, Skin.ANEL, Skin.SERAFIM_GRAVURA, Skin.OFANIM_ALADO),
            Ajustes(ordem = listOf("ofanim", "nao_existe", "ofanim")).skins(),
        )
    }
}
