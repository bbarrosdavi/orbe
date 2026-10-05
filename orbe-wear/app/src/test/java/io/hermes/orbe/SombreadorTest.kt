package io.hermes.orbe

import io.hermes.orbe.gl.Sombreador
import io.hermes.orbe.orbe.Skin
import java.io.File
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

/** A conversão é feita sobre os .frag de verdade, os do orbe-qt. */
class SombreadorTest {
    private val shaders = File(System.getProperty("orbe.qt") ?: "../../orbe-qt", "shaders")

    private fun ler(nome: String) = File(shaders, nome).readText()

    @Test
    fun cabecalhoViraEs300() {
        for (skin in Skin.entries) {
            val es = Sombreador.paraEs(ler(skin.shader), skin.definicoes)
            assertTrue(skin.id, es.startsWith("#version 300 es\n"))
            assertFalse("${skin.id}: sobrou layout do Qt", Regex("""layout\s*\(\s*(std140|binding)""").containsMatchIn(es))
            assertFalse("${skin.id}: sobrou location na entrada", es.contains("layout(location = 0) in"))
            assertTrue(skin.id, es.contains("\nin vec2 qt_TexCoord0;"))
            assertTrue(skin.id, es.contains("\nout vec4 fragColor;"))
            for ((nome, valor) in skin.definicoes) assertTrue(skin.id, es.contains("#define $nome $valor\n"))
        }
    }

    /** Os shaders como vão para a GPU do relógio, para passar num validador de GLSL ES. */
    @Test
    fun despejaOsConvertidos() {
        // limpa antes: um shader de skin que saiu não pode sobrar na conta
        val pasta = File(System.getProperty("orbe.despejo") ?: return).apply { deleteRecursively(); mkdirs() }
        File(pasta, "quadrado.vert").writeText(Sombreador.VERTICE)
        File(pasta, "pos.frag").writeText(Sombreador.paraEs(ler("pos.frag")))
        for (skin in Skin.entries) File(pasta, "${skin.id}.frag").writeText(Sombreador.paraEs(ler(skin.shader), skin.definicoes))
        assertEquals(Skin.entries.size + 2, pasta.listFiles()!!.size)
    }

    @Test
    fun blocoViraUniformsSoltos() {
        val figura = Sombreador.uniformes(Sombreador.paraEs(ler("figura.frag"), mapOf("SKIN" to 0)))
        // várias declarações na mesma linha, com comentário no fim
        for (u in listOf("qt_Matrix", "qt_Opacity", "tam", "centro", "olhar", "nucleoDir", "geo", "est", "est2",
            "a0u", "a0v", "a3u", "a3v", "ondas0", "ondas3", "rel0", "rel1", "relInfo", "w0a", "w5b",
            "lacos")) assertTrue(u, u in figura)
        assertEquals(figura.size, figura.toSet().size)

        val anel = Sombreador.uniformes(Sombreador.paraEs(ler("anel.frag")))
        for (u in listOf("geo", "extra", "gl", "campo0", "campo8", "lingua0", "lingua9", "gota0", "gota6", "tempo", "atlas"))
            assertTrue(u, u in anel)

        val pos = Sombreador.uniformes(Sombreador.paraEs(ler("pos.frag")))
        for (u in listOf("cor", "corA", "corB", "glt", "geo2", "sombra", "corSombra", "modo", "banda0", "banda3", "source"))
            assertTrue(u, u in pos)

        val imagem = Sombreador.uniformes(Sombreador.paraEs(ler("imagem.frag"), mapOf("IMG" to 1)))
        for (u in listOf("tam", "centro", "olhar", "geo", "img", "arte")) assertTrue(u, u in imagem)
    }

    @Test
    fun oCorpoNaoMuda() {
        // tudo depois do bloco de uniforms sai igual ao arquivo do desktop
        val fonte = ler("pos.frag").replace("\r\n", "\n")
        val es = Sombreador.paraEs(fonte)
        val marca = "const float TAU"
        assertEquals(fonte.substring(fonte.indexOf(marca)), es.substring(es.indexOf(marca)))
    }
}
