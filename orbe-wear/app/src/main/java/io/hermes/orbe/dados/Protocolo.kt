package io.hermes.orbe.dados

import javax.crypto.SecretKeyFactory
import javax.crypto.spec.PBEKeySpec
import kotlinx.serialization.SerialName
import kotlinx.serialization.Serializable
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
    /** a ponte aceita a fala do relógio */
    val microfone: Boolean = false,
    /** quem serve a ponte manda a voz para tocar aqui (o orbe de pulso, e o daemon na sessão do relógio) */
    val voz: Boolean = false,
    /** o PC também tem voz (o daemon): o relógio escolhe se ela toca lá junto */
    @SerialName("voz_pc") val vozPc: Boolean = false,
    /** os agentes instalados no PC, para cada orbe do carrossel ter o seu */
    val agentes: List<AgenteInfo> = emptyList(),
)

@Serializable
data class AgenteInfo(val id: String = "", val nome: String = "")

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
    val tamanho: Float = 1f,
    @SerialName("seguir_pc") val seguirPc: Boolean = true,
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
}
