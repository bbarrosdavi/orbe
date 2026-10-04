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
        val msgs = ArrayList(linhas.map { l -> l.split(' ').filter { it.isNotEmpty() } }.filter { it.isNotEmpty() })
        if (msgs.isEmpty()) return emptyList()
        // não coube: a linha mais antiga perde palavras do começo, uma a uma,
        // e sai inteira quando sobra só a última (as fileiras nunca ficam ociosas)
        var cortada = false
        while (true) {
            val tentativa = if (cortada) listOf(listOf("…") + msgs[0]) + msgs.drop(1) else msgs
            encaixar(tentativa, larguras, larg)?.let { return it }
            if (msgs[0].size > 1) {
                msgs[0] = msgs[0].drop(1)
                cortada = true
            } else if (msgs.size > 1) {
                msgs.removeAt(0)
                cortada = false
            } else break
        }
        // uma palavra só, maior que a tela inteira: o fim dela
        var p = msgs[0][0]
        while (p.length > 1) {
            p = p.substring(1)
            encaixar(listOf(listOf(p)), larguras, larg)?.let { return it }
        }
        return emptyList()
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
                    var n = resto.length - 1
                    while (n > 1 && larg(resto.substring(0, n)) > larguras[fileiras.size]) n--
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
}
