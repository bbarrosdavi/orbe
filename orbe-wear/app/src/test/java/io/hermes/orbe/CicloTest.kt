package io.hermes.orbe

import io.hermes.orbe.orbe.Ciclo
import io.hermes.orbe.orbe.Skin
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

class CicloTest {
    @Test
    fun cadaPaginaVoltaASiMesma() {
        // a página de (skin, cor) dá de volta a mesma skin e a mesma cor, perto de onde se está
        for (s in Skin.entries) for (c in Ciclo.cores.indices) {
            val p = Ciclo.pagina(s, c, 12_345)
            assertEquals(s, Ciclo.skin(p))
            assertEquals(c, Ciclo.cor(p))
            assertTrue(kotlin.math.abs(p - 12_345) <= Skin.entries.size * Ciclo.cores.size)
        }
    }

    @Test
    fun depoisDaUltimaSkinVemACorSeguinte() {
        val ultima = Ciclo.pagina(Skin.entries.last(), 0)
        assertEquals(Skin.entries.first(), Ciclo.skin(ultima + 1))
        assertEquals(1, Ciclo.cor(ultima + 1))
        // e para trás: antes da primeira skin na cor do tema vem a última na última cor
        val primeira = Ciclo.pagina(Skin.entries.first(), 0)
        assertEquals(Skin.entries.last(), Ciclo.skin(primeira - 1))
        assertEquals(Ciclo.cores.size - 1, Ciclo.cor(primeira - 1))
    }

    @Test
    fun nasceNoMeioDoPager() {
        val p = Ciclo.pagina(Skin.OFANIM, 0)
        assertTrue(p in Ciclo.PAGINAS / 4 until Ciclo.PAGINAS * 3 / 4)
    }
}
