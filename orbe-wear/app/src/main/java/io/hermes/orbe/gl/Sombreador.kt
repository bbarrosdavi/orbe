package io.hermes.orbe.gl

/**
 * Leva um .frag do orbe-qt (GLSL 440, no dialeto do Qt) para GLSL ES 3.00.
 *
 * O desenho do orbe mora em orbe-qt/shaders e o relógio usa os mesmos
 * arquivos: aqui só muda o cabeçalho. O bloco std140 vira uniforms soltos
 * (o ES 3.00 não tem binding, e uniform solto dispensa montar o buffer), os
 * layouts de entrada e de textura saem e as variantes que o build.sh passa
 * por -D (SKIN, IMG) viram #define, com RELOGIO a mais.
 */
object Sombreador {
    private val bloco = Regex("""layout\s*\(\s*std140[^)]*\)\s*uniform\s+\w+\s*\{(.*?)\}\s*;""", RegexOption.DOT_MATCHES_ALL)
    private val membro = Regex("""^\s*(\w+)\s+(\w+)\s*$""")
    private val amostrador = Regex("""layout\s*\(\s*binding\s*=\s*\d+\s*\)\s*uniform""")
    private val entrada = Regex("""layout\s*\(\s*location\s*=\s*\d+\s*\)\s*(in|out)\b""")
    private val versao = Regex("""^\s*#version[^\n]*\n""")

    const val CABECALHO = "#version 300 es\nprecision highp float;\nprecision highp int;\nprecision highp sampler2D;\n"

    /** Vértices de um quadrado; uvT inverte o y no passe que vai para a tela. */
    const val VERTICE = CABECALHO +
        "layout(location = 0) in vec2 pos;\n" +
        "uniform vec4 uvT;\n" +
        "out vec2 qt_TexCoord0;\n" +
        "void main() {\n" +
        "    qt_TexCoord0 = (pos * 0.5 + 0.5) * uvT.xy + uvT.zw;\n" +
        "    gl_Position = vec4(pos, 0.0, 1.0);\n" +
        "}\n"

    fun paraEs(fonte: String, definicoes: Map<String, Int> = emptyMap()): String {
        var s = fonte.replace("\r\n", "\n")
        require(versao.containsMatchIn(s)) { "shader sem #version" }
        // RELOGIO: os shaders podem ter um caminho próprio para a GPU do relógio
        val defs = (definicoes + ("RELOGIO" to 1)).entries.joinToString("") { "#define ${it.key} ${it.value}\n" }
        s = versao.replaceFirst(s, Regex.escapeReplacement(CABECALHO + defs))
        val achado = requireNotNull(bloco.find(s)) { "shader sem o bloco de uniforms do Qt" }
        s = s.replaceRange(achado.range, soltos(achado.groupValues[1]))
        s = amostrador.replace(s, "uniform")
        s = entrada.replace(s) { it.groupValues[1] }
        return s
    }

    /** Os membros do bloco, um uniform por linha (os comentários ficam para trás). */
    private fun soltos(corpo: String): String {
        val sai = StringBuilder()
        for (linha in corpo.lineSequence()) {
            for (decl in linha.substringBefore("//").split(';')) {
                val m = membro.find(decl) ?: continue
                sai.append("uniform ").append(m.groupValues[1]).append(' ').append(m.groupValues[2]).append(";\n")
            }
        }
        return sai.toString()
    }

    /** Nomes dos uniforms que o shader convertido declara (teste e diagnóstico). */
    fun uniformes(es: String): List<String> =
        Regex("""(?m)^uniform\s+\w+\s+(\w+)\s*;""").findAll(es).map { it.groupValues[1] }.toList()
}
