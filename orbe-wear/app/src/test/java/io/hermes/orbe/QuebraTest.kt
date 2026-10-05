package io.hermes.orbe

import io.hermes.orbe.dados.Protocolo
import io.hermes.orbe.orbe.Quebra
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

class QuebraTest {
    // uma letra = 1 de largura: a conta fica à vista
    private val medir = { s: String -> s.length.toFloat() }

    @Test
    fun cadaLinhaComecaNumaFileira() {
        assertEquals(listOf("um dois", "três", "quatro"), Quebra.quebrar(listOf("um dois três", "quatro"), listOf(8f, 8f, 8f), medir))
    }

    @Test
    fun fileirasDeLargurasDiferentes() {
        // mostrador redondo: em cima cabe mais do que embaixo
        assertEquals(listOf("aaa bbb ccc", "ddd eee", "fff"), Quebra.quebrar(listOf("aaa bbb ccc ddd eee fff"), listOf(11f, 7f, 3f), medir))
    }

    @Test
    fun semEspacoSomeOComecoDoMaisAntigo() {
        val linhas = listOf("primeira linha comprida demais", "segunda linha", "terceira")
        val r = Quebra.quebrar(linhas, listOf(14f, 14f, 14f), medir)
        // a mais nova fica inteira e embaixo; da mais antiga sobra o fim, marcado
        assertEquals("terceira", r.last())
        assertEquals("segunda linha", r[r.size - 2])
        assertEquals(3, r.size)
        assertTrue(r[0], r[0].startsWith("…") && r[0].endsWith("demais"))
    }

    @Test
    fun umaLinhaMaiorQueTudoFicaComOFim() {
        val r = Quebra.quebrar(listOf("um dois três quatro cinco seis sete"), listOf(10f, 10f), medir)
        assertEquals(2, r.size)
        assertTrue(r[0].startsWith("…"))
        assertTrue(r.joinToString(" ").endsWith("seis sete"))
        for (f in r) assertTrue(f, f.length <= 10)
    }

    @Test
    fun palavraMaiorQueAFileiraEPartida() {
        assertEquals(listOf("abcde", "fghij", "kl"), Quebra.quebrar(listOf("abcdefghijkl"), listOf(5f, 5f, 5f), medir))
        // e, sem fileiras que cheguem, fica o fim dela
        assertEquals(listOf("hijkl"), Quebra.quebrar(listOf("abcdefghijkl"), listOf(5f), medir))
    }

    @Test
    fun nadaParaMostrar() {
        assertTrue(Quebra.quebrar(emptyList(), listOf(10f), medir).isEmpty())
        assertTrue(Quebra.quebrar(listOf("texto"), emptyList(), medir).isEmpty())
        assertTrue(Quebra.quebrar(listOf("   "), listOf(10f), medir).isEmpty())
    }

    @Test
    fun enderecoDaPonte() {
        assertEquals("ws://192.168.0.10:8777/", Protocolo.url("192.168.0.10"))
        assertEquals("ws://192.168.0.10:9000/", Protocolo.url(" 192.168.0.10:9000 "))
        assertEquals("ws://pc.local:8777/", Protocolo.url("http://pc.local"))
        assertEquals("ws://[fd7a::1]:8777/", Protocolo.url("[fd7a::1]"))
        assertEquals("ws://[fd7a::1]:9000/", Protocolo.url("[fd7a::1]:9000"))
        // atrás de um proxy com TLS, a porta é a dele
        assertEquals("wss://orbe.exemplo.net/", Protocolo.url("https://orbe.exemplo.net"))
        assertEquals("wss://orbe.exemplo.net:8443/relogio", Protocolo.url("wss://orbe.exemplo.net:8443/relogio"))
        for (ruim in listOf("", "   ", "ftp://x", "pc:abc", "pc:0", "fd7a::1", "dois nomes"))
            assertNull(ruim, Protocolo.url(ruim))
    }

    @Test
    fun olaDaPonte() {
        val ola = Protocolo.ola("""{"v": 1, "orbe": {"skin": "ofanim_alado", "glitch": false, "tamanho": 1.3}, "tema": {"accent_bg_color": "#f3b2e3", "anel": "#0087fc"}, "microfone": true, "novo": 1}""")!!
        assertEquals("ofanim_alado", ola.orbe.skin)
        assertEquals(false, ola.orbe.glitch)
        assertEquals("#f3b2e3", ola.tema["accent_bg_color"])
        assertTrue(ola.microfone)
        assertNull(Protocolo.ola("isto não é json"))
    }

    @Test
    fun provaDoToken() {
        // o mesmo vetor do hashlib.pbkdf2_hmac do Python, que é quem confere na ponte
        val sal = "000102030405060708090a0b0c0d0e0f"
        val esperada = "04ffa2357b1f005c3caf5c1f64a232cb661ba1afb502c997368d4cec2d17fe51"
        assertEquals(esperada, Protocolo.prova("abcd2345", sal))
        // o token vale como foi mostrado, sem maiúsculas nem espaços de quem digitou
        assertEquals(esperada, Protocolo.prova(" ABCD2345 ", sal))
        assertEquals("""ola {"prova":"$esperada","nome":"TicWatch","voz":true,"voz_pc":false}""", Protocolo.apresentar("abcd2345", sal, "TicWatch", voz = true))
        // tocando aqui, o relógio pode pedir o PC tocando junto (a ponte do daemon)
        assertEquals("""ola {"prova":"$esperada","nome":"TicWatch","voz":true,"voz_pc":true}""", Protocolo.apresentar("abcd2345", sal, "TicWatch", voz = true, vozPc = true))
        // sal novo, prova nova: escutar uma conexão não serve para a seguinte
        assertTrue(Protocolo.prova("abcd2345", "ff" + sal.substring(2)) != esperada)
        assertNull(Protocolo.prova("abcd2345", "não é hex"))
        assertNull(Protocolo.apresentar("abcd2345", "", "TicWatch", voz = false))
    }
}
