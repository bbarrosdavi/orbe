package io.hermes.orbe.orbe

/**
 * As skins do orbe, com o que o orbe-qt guarda espalhado: o shader de cada uma
 * e a variante do build.sh, o atlas das skins de imagem e as medidas tiradas
 * dos renders (Figura.qml e OrbeConteudo.qml).
 */
enum class Skin(
    val id: String,
    val nome: String,
    /** arquivo em orbe-qt/shaders e o -D que o build.sh passa ao qsb */
    val shader: String,
    val definicoes: Map<String, Int>,
    /** atlas em orbe-qt/arte (ou comum, no anel); null nas figuras desenhadas */
    val arte: String?,
    /** quanto a figura alcança, em raios: para os lados, para cima e baixo, e num disco */
    val alcance: FloatArray,
    /** pé da figura abaixo do centro, em fração da célula: onde o texto começa */
    val pe: Float,
    /** topo da figura acima do centro: o ponto da sessão travada fica logo acima */
    val topo: Float,
    /** o atlas é lido com esta redução: a figura no relógio é bem menor que o recorte */
    val reducao: Int = 1,
) {
    OFANIM("ofanim", "Ophanim", "figura.frag", mapOf("SKIN" to 0), null, floatArrayOf(1.55f, 1.55f, 1.25f), 0.39f, 0.345f),
    OFANIM_ALADO("ofanim_alado", "Ophanim com asas", "figura.frag", mapOf("SKIN" to 1), null, floatArrayOf(2.1f, 1.55f, 2.08f), 0.29f, 0.277f),
    SHOGGOTH("shoggoth", "Shoggoth", "figura.frag", mapOf("SKIN" to 3), null, floatArrayOf(1.6f, 1.6f, 1.4f), 0.42f, 0.365f),
    SERAFIM_GRAVURA("serafim_gravura", "Seraphim (gravura)", "imagem.frag", mapOf("IMG" to 1), "serafim_gravura.png", floatArrayOf(1.15f, 1.3f, 1.4f), 0.38f, 0.355f),
    ENTIDADE("entidade", "Entidade", "imagem.frag", mapOf("IMG" to 2), "entidade.png", floatArrayOf(0.85f, 1.03f, 1.12f), 0.47f, 0.486f, reducao = 2),
    ANEL("anel", "Anel de energia", "anel.frag", emptyMap(), "anel_atlas.png", floatArrayOf(1f, 1f, 1f), 0.35f, 0.412f);

    /**
     * No mostrador redondo a figura cabe no disco, e algumas saem menores que
     * o maior raio da célula quadrada (em que [pe] e [topo] foram medidos).
     */
    fun encolheNoDisco(lado: Double): Double {
        if (!avatar) return 1.0
        val quadrado = minOf(lado / 2 / alcance[0], lado / 2 / alcance[1])
        return minOf(1.0, (lado / 2 - 2) / alcance[2] / quadrado)
    }

    /** Figura (avatar desenhado ou de imagem); o anel de energia tem física própria. */
    val avatar: Boolean get() = this != ANEL
    val imagem: Boolean get() = this == SERAFIM_GRAVURA || this == ENTIDADE

    companion object {
        /** O Seraphim desenhado saiu; quem o tinha fica com o da gravura, como no orbe.qml. */
        fun de(id: String?): Skin = when (id) {
            "serafim" -> SERAFIM_GRAVURA
            else -> entries.firstOrNull { it.id == id } ?: OFANIM
        }
    }
}

/** Estados do orbe, na ordem dos pesos do mix. */
object Estado {
    const val IDLE = 0
    const val LISTENING = 1
    const val THINKING = 2
    const val SPEAKING = 3
    const val TOOLS = 4
    val nomes = arrayOf("idle", "listening", "thinking", "speaking", "tools")
    val rotulos = arrayOf("parado", "ouvindo", "pensando", "respondendo", "trabalhando")
    fun de(nome: String): Int = nomes.indexOf(nome)
}
