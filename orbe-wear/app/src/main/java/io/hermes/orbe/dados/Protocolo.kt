package io.hermes.orbe.dados

import javax.crypto.SecretKeyFactory
import javax.crypto.spec.PBEKeySpec
import kotlinx.serialization.SerialName
import kotlinx.serialization.Serializable
import kotlinx.serialization.builtins.ListSerializer
import kotlinx.serialization.json.Json

/** A aparência do orbe no PC (config.json → orbe), como a ponte manda. */
@Serializable
data class OrbePc(val skin: String = "ofanim", val glitch: Boolean = true, val tamanho: Double = 1.0)

/** O "ola" e o "config" da ponte (hermes_voice_relogio.py). */
@Serializable
data class Ola(
    val v: Int = 1,
    val orbe: OrbePc = OrbePc(),
    /** cores do matugen: accent_bg_color, window_bg_color, ..., anel */
    val tema: Map<String, String> = emptyMap(),
    /** o papel de parede do PC atrás do app, em n x n cores (linha a linha, de cima); vazio sem ele */
    val papel: List<String> = emptyList(),
    /** a ponte aceita a fala do relógio */
    val microfone: Boolean = false,
    /** quem serve a ponte manda a voz para tocar aqui (o orbe de pulso, e o daemon na sessão do relógio) */
    val voz: Boolean = false,
    /** o PC também tem voz (o daemon): o relógio escolhe se ela toca lá junto */
    @SerialName("voz_pc") val vozPc: Boolean = false,
    /** os agentes instalados no PC, para cada orbe da lista ter o seu */
    val agentes: List<AgenteInfo> = emptyList(),
    /** as sessões abertas no PC dos agentes com instâncias; null: a ponte não as conta */
    val sessoes: List<SessaoInfo>? = null,
    /** falar numa instância sem sessão abre uma no PC (o daemon; o orbe de pulso não abre) */
    @SerialName("abre_claude") val abreClaude: Boolean = false,
)

/**
 * Um agente do PC. Com [instancias], cada instância do orbe dele é uma sessão
 * aberta no PC (o Claude, e os que rodam numa janela do terminal); sem, o orbe
 * fala com uma sessão só.
 */
@Serializable
data class AgenteInfo(val id: String = "", val nome: String = "", val instancias: Boolean = false)

/**
 * Uma sessão aberta no PC de um agente com instâncias, na [vaga] dela: a vaga
 * k é a k-ésima instância dos orbes do [agente] (Instancias) e não muda
 * enquanto ela vive.
 */
@Serializable
data class SessaoInfo(
    /** o agente dela (a ponte antiga só conta as do Claude) */
    val agente: String = "claude",
    val vaga: Int = 0,
    val pid: Int = 0,
    /** a pasta e o nome da sessão (a ponte antiga só manda este) */
    val rotulo: String = "",
    /** o título da conversa: o dado com /rename, ou o que o Claude Code deu (o do /resume) */
    val titulo: String = "",
    /** a pasta em que a sessão foi aberta */
    val pasta: String = "",
    /** "parada" ou "trabalhando" */
    val estado: String = "",
    /** aberta pelo orbe (claude-orbe): o canal dele responde */
    val canal: Boolean = false,
    /** ouve o orbe: o Claude aberto à mão, pelo hook (hermes_voice_sessao.py), e as janelas dos outros agentes */
    val ouve: Boolean = false,
)

/** Uma sessão passada de um agente, para retomar ("historico" da ponte). */
@Serializable
data class SessaoPassada(
    val id: String = "",
    val titulo: String = "",
    /** a pasta em que ela rodou */
    val pasta: String = "",
    /** a última atividade, em segundos desde 1970; 0 = não se sabe */
    val quando: Long = 0,
)

/** A resposta ao "historico": as sessões passadas do agente do orbe em tela, da mais nova para a mais velha. */
@Serializable
data class Historico(
    val agente: String = "",
    val sessoes: List<SessaoPassada> = emptyList(),
    /** o agente não lista o histórico, ou a lista falhou */
    val erro: String = "",
    /** só no relógio: pedido, a resposta ainda não veio */
    @kotlinx.serialization.Transient val carregando: Boolean = false,
)

/**
 * Os ajustes do app do relógio que o app do PC também edita ("ajustes" nos
 * dois sentidos, relogio.ajustes no config do PC): vale o [t] mais novo, em ms.
 */
@Serializable
data class Sincronia(
    val t: Long = 0,
    /** skin → agente; "" = o padrão (Claude Code) */
    val agentes: Map<String, String> = emptyMap(),
    val voz: Boolean = true,
    @SerialName("voz_pc") val vozPc: Boolean = false,
    val microfone: Boolean = true,
    val vibrar: Boolean = true,
    val texto: Boolean = true,
    val glitch: Boolean = true,
    val linhas: Boolean = true,
    val tamanho: Float = 1f,
    @SerialName("seguir_pc") val seguirPc: Boolean = true,
    /** a escala de cada orbe, pela skin; null (do PC): segue o [tamanho] */
    val tamanhos: Map<String, Float?> = emptyMap(),
    // Os de baixo o PC só conhece depois de o relógio mandar os dele: null (do
    // PC) é "não sei", e o relógio fica com o que tem.
    /** a ação de 1, 2, 3 e 4 toques ([AcaoToque]) */
    val toques: List<String>? = null,
    val live: Boolean? = null,
    val fundo: Boolean? = null,
    /** a ordem dos orbes na lista, pelas skins */
    val ordem: List<String>? = null,
    val sacudida: Boolean? = null,
    val sair: Boolean? = null,
    /** as calibrações, em rad/s; 0 (do PC) volta ao padrão */
    @SerialName("sacudida_fora") val sacudidaFora: Float? = null,
    @SerialName("sacudida_dentro") val sacudidaDentro: Float? = null,
    @SerialName("sair_fora") val sairFora: Float? = null,
)

object Protocolo {
    const val PORTA = 8777
    private val json = Json { ignoreUnknownKeys = true; isLenient = true }

    fun ola(texto: String): Ola? = try {
        json.decodeFromString(Ola.serializer(), texto)
    } catch (e: Exception) {
        null
    }

    // os ajustes vão inteiros: um campo no valor padrão omitido deixaria o do PC como estava
    private val inteiro = Json { ignoreUnknownKeys = true; isLenient = true; encodeDefaults = true }

    fun sincronia(texto: String): Sincronia? = try {
        inteiro.decodeFromString(Sincronia.serializer(), texto)
    } catch (e: Exception) {
        null
    }

    /** O "sessoes [...]" da ponte. */
    fun sessoes(texto: String): List<SessaoInfo>? = try {
        json.decodeFromString(ListSerializer(SessaoInfo.serializer()), texto)
    } catch (e: Exception) {
        null
    }

    /** O "historico {...}" da ponte. */
    fun historico(texto: String): Historico? = try {
        json.decodeFromString(Historico.serializer(), texto)
    } catch (e: Exception) {
        null
    }

    fun ajustes(s: Sincronia): String = "ajustes " + inteiro.encodeToString(Sincronia.serializer(), s)

    /** o custo da prova do token; o mesmo ITERACOES do hermes_voice_relogio.py */
    private const val ITERACOES = 60000

    /**
     * A resposta ao "desafio <sal>" da ponte: PBKDF2-HMAC-SHA256 do token com o
     * sal daquela conexão. O token em si nunca passa pela rede. Null se o sal
     * não é hexadecimal.
     */
    fun prova(token: String, salHex: String): String? {
        val sal = try {
            require(salHex.isNotEmpty() && salHex.length % 2 == 0)
            ByteArray(salHex.length / 2) { salHex.substring(it * 2, it * 2 + 2).toInt(16).toByte() }
        } catch (e: IllegalArgumentException) {
            return null
        }
        val chave = PBEKeySpec(token.trim().lowercase().toCharArray(), sal, ITERACOES, 256)
        return SecretKeyFactory.getInstance("PBKDF2WithHmacSHA256").generateSecret(chave).encoded
            .joinToString("") { "%02x".format(it) }
    }

    /**
     * A primeira mensagem do relógio, em resposta ao desafio; [voz]: o relógio
     * toca a resposta; [vozPc]: e o PC toca junto.
     */
    fun apresentar(token: String, salHex: String, nome: String, voz: Boolean, vozPc: Boolean = false): String? =
        prova(token, salHex)?.let {
            "ola " + json.encodeToString(Apresentacao.serializer(), Apresentacao(it, nome, voz, vozPc))
        }

    @Serializable
    private data class Apresentacao(
        val prova: String,
        val nome: String,
        val voz: Boolean,
        @SerialName("voz_pc") val vozPc: Boolean,
    )

    /**
     * O que se digita no relógio vira a URL da ponte: "192.168.0.10" ganha
     * ws:// e a porta padrão; http(s) vira ws(s); null se não dá um endereço.
     */
    fun url(servidor: String): String? {
        var s = servidor.trim()
        if (s.isEmpty() || s.any { it.isWhitespace() }) return null
        val esquema = when {
            s.startsWith("wss://", true) -> { s = s.substring(6); "wss://" }
            s.startsWith("ws://", true) -> { s = s.substring(5); "ws://" }
            s.startsWith("https://", true) -> { s = s.substring(8); "wss://" }
            s.startsWith("http://", true) -> { s = s.substring(7); "ws://" }
            "://" in s -> return null
            else -> "ws://"
        }
        val barra = s.indexOf('/')
        val destino = if (barra < 0) s else s.substring(0, barra)
        val caminho = if (barra < 0) "/" else s.substring(barra)
        if (destino.isEmpty()) return null
        // IPv6 vai entre colchetes: [fd7a::1]:8777
        val temPorta = if (destino.startsWith("[")) destino.substringAfterLast(']').startsWith(":")
        else destino.count { it == ':' } == 1
        if (!destino.startsWith("[") && destino.count { it == ':' } > 1) return null
        val porta = if (temPorta) destino.substringAfterLast(':') else ""
        if (temPorta && (porta.toIntOrNull() ?: 0) !in 1..65535) return null
        // wss sem porta fica na 443 do proxy; ws sem porta, na da ponte
        val comPorta = if (temPorta || esquema == "wss://") destino else "$destino:$PORTA"
        return esquema + comPorta + caminho
    }

    /** A ponte está na rede de casa (IP privado, .lan, .local): só o Wi-Fi do relógio chega bem nela. */
    fun local(servidor: String): Boolean {
        val host = url(servidor)?.let { runCatching { java.net.URI(it).host }.getOrNull() }
            ?.trim('[', ']')?.lowercase() ?: return false
        if (host == "localhost" || host.endsWith(".lan") || host.endsWith(".local") || host.endsWith(".home.arpa")) return true
        val p = host.split('.').map { it.toIntOrNull() ?: -1 }
        if (p.size != 4 || p.any { it !in 0..255 }) return false
        return p[0] == 10 || p[0] == 127 || (p[0] == 192 && p[1] == 168) || (p[0] == 172 && p[1] in 16..31) ||
            (p[0] == 169 && p[1] == 254)
    }
}
