package io.hermes.orbe

import io.hermes.orbe.dados.Protocolo
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class ProtocoloTest {
    @Test
    fun enderecoDeCasaVaiPeloWifi() {
        // o que se digita no relógio, com e sem esquema e porta
        for (s in listOf("192.168.15.7", "ws://192.168.15.7:8777", "http://10.0.0.2/", "172.20.1.1:9000", "pc.lan", "pc.local:8777", "localhost")) {
            assertTrue(s, Protocolo.local(s))
        }
    }

    @Test
    fun tailnetEInternetSaemPeloCelular() {
        // a tailnet só responde pelo celular (o relógio não tem Tailscale)
        for (s in listOf("100.95.140.97", "wss://acer-server.tail664e38.ts.net", "8.8.8.8:8777", "172.32.0.1", "", "192.168.15")) {
            assertFalse(s, Protocolo.local(s))
        }
    }
}
