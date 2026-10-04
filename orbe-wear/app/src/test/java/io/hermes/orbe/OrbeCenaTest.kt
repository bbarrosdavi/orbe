package io.hermes.orbe

import io.hermes.orbe.orbe.Celula
import io.hermes.orbe.orbe.Estado
import io.hermes.orbe.orbe.OrbeCena
import io.hermes.orbe.orbe.Retrato
import io.hermes.orbe.orbe.Skin
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

/** O protocolo do daemon, com a semântica do OrbeConteudo.qml. */
class OrbeCenaTest {
    private fun cena(vistos: MutableList<Retrato> = ArrayList()) = OrbeCena().apply { aoMudar = { vistos.add(it) } }

    @Test
    fun showAbreNoEstadoEHideFecha() {
        val vistos = ArrayList<Retrato>()
        val c = cena(vistos)
        assertFalse(c.retratoAtual.visivel)
        c.comando("show thinking")
        assertEquals(Retrato(true, Estado.THINKING), c.retratoAtual)
        c.comando("show")                          // sem estado: ouvindo
        assertEquals(Estado.LISTENING, c.retratoAtual.estado)
        c.comando("show lixo")                     // estado desconhecido: fica o que estava
        assertEquals(Estado.LISTENING, c.retratoAtual.estado)
        c.comando("hide")
        assertFalse(c.retratoAtual.visivel)
        assertEquals(3, vistos.size)               // só o que muda chega à tela
    }

    @Test
    fun stateMostraOOrbeEscondido() {
        val c = cena()
        c.comando("state speaking")
        assertEquals(Retrato(true, Estado.SPEAKING), c.retratoAtual)
    }

    @Test
    fun linhasEntramLimpasEViramFerramentas() {
        val c = cena()
        c.comando("show listening")
        c.comando("line   Pedido:   resumir  as mensagens ")
        assertEquals(listOf("Pedido: resumir as mensagens"), c.retratoAtual.linhas)
        assertEquals(Estado.TOOLS, c.retratoAtual.estado)
        // pensando, a linha não troca o estado
        c.comando("state thinking")
        c.comando("line segunda 😀 linha [?25l")
        assertEquals(Estado.THINKING, c.retratoAtual.estado)
        assertEquals("segunda linha", c.retratoAtual.linhas.last())
        // só as seis últimas ficam; show e clear limpam
        repeat(8) { c.comando("line l$it") }
        assertEquals(listOf("l2", "l3", "l4", "l5", "l6", "l7"), c.retratoAtual.linhas)
        c.comando("clear")
        assertTrue(c.retratoAtual.linhas.isEmpty())
        c.comando("line a")
        c.comando("show listening")
        assertTrue(c.retratoAtual.linhas.isEmpty())
    }

    @Test
    fun nivelDaVozPoeOOrbeParaFalar() {
        val c = cena()
        c.comando("show thinking")
        c.comando("level 0.05 0.5")                // baixo demais: não é fala ainda
        assertEquals(Estado.THINKING, c.retratoAtual.estado)
        c.comando("level 0.4 0.7")
        assertEquals(Estado.SPEAKING, c.retratoAtual.estado)
        c.comando("level abc")                     // lixo não derruba nada
        c.comando("mic 0.3")
        assertEquals(Estado.SPEAKING, c.retratoAtual.estado)
    }

    @Test
    fun holdTravaEDestrava() {
        val c = cena()
        c.comando("hold 1")
        assertTrue(c.retratoAtual.travado)
        for (desliga in listOf("hold 0", "hold false", "hold off", "hold")) {
            c.comando("hold 1")
            c.comando(desliga)
            assertFalse(desliga, c.retratoAtual.travado)
        }
    }

    @Test
    fun cadaSkinMontaOsUniformsDoSeuShader() {
        for (skin in Skin.entries) {
            val c = cena()
            c.skin = skin
            c.comando("show speaking")
            c.comando("level 0.6 0.5")
            var arte = c.passo(1.0 / 30, 192.0, 192.0)
            repeat(30) { arte = c.passo(1.0 / 30, 192.0, 192.0) }
            assertEquals(skin, arte.skin)
            for (u in listOf("tam", "centro")) assertTrue("${skin.id}: $u", arte.fx[u] != null && arte.pos[u] != null)
            for (u in listOf("cor", "corA", "corB", "glt", "geo2", "sombra", "corSombra", "modo"))
                assertTrue("${skin.id}: $u", arte.pos[u] != null)
            // a figura fica dentro do mostrador redondo
            val recorte = arte.recorte
            assertEquals(96.0, recorte[0], 1e-6)
            assertTrue(skin.id, recorte[2] <= 96.0)
            for ((nome, v) in arte.fx.mapa + arte.pos.mapa) for (x in v) assertFalse("${skin.id}: $nome", x.isNaN() || x.isInfinite())
        }
    }

    @Test
    fun comTextoACelulaSobeEEncolhe() {
        val cheia = Celula.para(192.0, 192.0, 1.0, comTexto = false)
        val texto = Celula.para(192.0, 192.0, 1.0, comTexto = true)
        assertEquals(192.0, cheia.lado, 1e-9)
        assertEquals(96.0, cheia.cy, 1e-9)
        assertTrue(texto.lado < cheia.lado && texto.cy < cheia.cy)
        // o pé da figura fica acima do meio de baixo da tela, onde o texto começa
        for (skin in Skin.entries) assertTrue(skin.id, texto.cy + texto.lado * skin.pe < 192 * 0.68)
    }
}
