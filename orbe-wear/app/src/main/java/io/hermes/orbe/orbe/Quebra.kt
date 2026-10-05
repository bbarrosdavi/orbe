package io.hermes.orbe.orbe

/**
 * As linhas do raciocínio em fileiras, como o quebrar() do OrbeConteudo.qml,
 * com uma diferença: no mostrador redondo cada fileira tem a sua largura (a
 * corda do círculo naquela altura), então a quebra depende de onde o texto cai.
 */
object Quebra {
    /**
     * [larguras] de cima para baixo, uma por fileira que cabe na tela. A linha
     * mais nova termina na última fileira ocupada; se tudo não cabe, some o
     * começo do texto mais antigo, como as fileiras de cima somem no desktop.
     * [medir] dá a largura de uma palavra (e do espaço).
     */
    fun quebrar(linhas: List<String>, larguras: List<Float>, medir: (String) -> Float): List<String> {
        if (larguras.isEmpty()) return emptyList()
        val vistas = HashMap<String, Float>()
        val larg = { p: String -> vistas.getOrPut(p) { medir(p) } }
        val msgs = linhas.map { l -> l.split(' ').filter { it.isNotEmpty() } }.filter { it.isNotEmpty() }
        if (msgs.isEmpty()) return emptyList()
        encaixar(msgs, larguras, larg)?.let { return it }
        // não coube: a linha mais antiga perde palavras do começo, uma a uma,
        // e sai inteira quando sobra só a última (as fileiras nunca ficam
        // ociosas). Cada tentativa é (a primeira linha, quantas palavras saíram
        // dela); quanto mais adiante, mais fácil caber, então a primeira que
        // cabe sai por busca binária: tentar uma a uma media o texto centenas
        // de vezes na thread da tela.
        val tentativas = msgs.indices.flatMap { i -> List(msgs[i].size) { d -> i to d } }
        val (_, cabe) = primeira(tentativas.size) { k ->
            val (i, d) = tentativas[k]
            val primeira = if (d > 0) listOf(listOf("…") + msgs[i].drop(d)) else listOf(msgs[i])
            encaixar(primeira + msgs.drop(i + 1), larguras, larg)
        }
        if (cabe != null) return cabe
        // uma palavra só, maior que a tela inteira: o fim dela
        val p = msgs.last().last()
        return primeira(p.length - 1) { k -> encaixar(listOf(listOf(p.substring(k + 1))), larguras, larg) }.second
            ?: emptyList()
    }

    /** A primeira de [n] tentativas que dá certo, supondo que depois dela todas dão (índice -1 e null se nenhuma). */
    private fun <T : Any> primeira(n: Int, tentar: (Int) -> T?): Pair<Int, T?> {
        var a = 0
        var b = n - 1
        var achada = -1
        var r: T? = null
        while (a <= b) {
            val m = (a + b) / 2
            val t = tentar(m)
            if (t != null) {
                achada = m
                r = t
                b = m - 1
            } else a = m + 1
        }
        return achada to r
    }

    /** Quebra de cima para baixo; null se passa do número de fileiras. */
    private fun encaixar(msgs: List<List<String>>, larguras: List<Float>, larg: (String) -> Float): List<String>? {
        val espaco = larg(" ")
        val fileiras = ArrayList<String>()
        for (m in msgs) {
            val cur = StringBuilder()
            var w = 0f
            for (palavra in m) {
                if (fileiras.size >= larguras.size) return null
                val lp = larg(palavra)
                if (cur.isEmpty() && lp <= larguras[fileiras.size]) {
                    cur.append(palavra)
                    w = lp
                    continue
                }
                if (cur.isNotEmpty() && w + espaco + lp <= larguras[fileiras.size]) {
                    cur.append(' ').append(palavra)
                    w += espaco + lp
                    continue
                }
                if (cur.isNotEmpty()) {
                    fileiras.add(cur.toString())
                    cur.setLength(0)
                    if (fileiras.size >= larguras.size) return null
                }
                // palavra maior que a fileira: parte onde couber
                var resto = palavra
                while (resto.length > 1 && larg(resto) > larguras[fileiras.size]) {
                    val n = corte(resto, larguras[fileiras.size], larg)
                    fileiras.add(resto.substring(0, n))
                    resto = resto.substring(n)
                    if (fileiras.size >= larguras.size) return null
                }
                cur.append(resto)
                w = larg(resto)
            }
            if (cur.isNotEmpty()) {
                if (fileiras.size >= larguras.size) return null
                fileiras.add(cur.toString())
            }
        }
        return fileiras
    }

    /**
     * O maior começo de [p] (ao menos um caractere, nunca a palavra toda) que cabe
     * em [largura]. Busca binária: medir cada começo, do maior ao menor, custava
     * milhares de medições num caminho de arquivo e travava a tela por segundos.
     */
    private fun corte(p: String, largura: Float, larg: (String) -> Float): Int {
        var cabe = 1
        var passa = p.length
        while (passa - cabe > 1) {
            val m = (cabe + passa) / 2
            if (larg(p.substring(0, m)) <= largura) cabe = m else passa = m
        }
        return cabe
    }
}
