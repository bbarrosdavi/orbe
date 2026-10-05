package io.hermes.orbe

import io.hermes.orbe.orbe.Quebra
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * A quebra roda na thread da tela, e cada medida de texto custa perto de um
 * milissegundo no relógio: um caminho de arquivo longo com poucas fileiras
 * chegou a pedir 11 mil medidas e travou a tela por 16 s.
 */
class QuebraCustoTest {
    private fun medidas(linhas: List<String>, larguras: List<Float>): Int {
        var n = 0
        Quebra.quebrar(linhas, larguras) { n++; it.length * 14f }
        return n
    }

    @Test
    fun umCaminhoLongoNaoTravaATela() {
        val caminho = "/home/davi/Projetos/orbe-relogio/orbe-wear/app/src/main/java/io/hermes/orbe/ui/TelaOrbe.kt:123"
        val frase = "Lendo o arquivo e conferindo o que mudou desde a ultima versao do relogio com calma"
        assertTrue(medidas(listOf(caminho, caminho + caminho), listOf(300f, 250f)) < 200)
        assertTrue(medidas(List(3) { "$frase $caminho" }, listOf(280f)) < 200)
        assertTrue(medidas(List(6) { "x".repeat(220) }, listOf(300f, 250f)) < 200)
    }
}
