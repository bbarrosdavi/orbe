package io.hermes.orbe.dados

import java.util.concurrent.TimeUnit
import kotlinx.coroutines.CompletableDeferred
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Job
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.isActive
import kotlinx.coroutines.launch
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.Response
import okhttp3.WebSocket
import okhttp3.WebSocketListener
import okio.ByteString
import okio.ByteString.Companion.toByteString

/** Como está a conversa com a ponte do daemon. */
sealed interface Ligacao {
    /** falta o endereço ou o token nos ajustes */
    data object SemServidor : Ligacao
    data object Conectando : Ligacao
    /**
     * [microfone]: a ponte aceita a fala do relógio; [voz]: a resposta vem em
     * áudio para tocar aqui; [vozPc]: o PC também pode tocar a resposta
     */
    data class Conectada(val microfone: Boolean, val voz: Boolean = false, val vozPc: Boolean = false) : Ligacao
    /** [definitiva]: não adianta tentar de novo sem mexer nos ajustes (token errado) */
    data class Falha(val motivo: String, val definitiva: Boolean = false) : Ligacao
}

/**
 * O lado do relógio da ponte (hermes_voice_relogio.py): recebe as linhas do
 * protocolo do orbe e manda o toque, os comandos e a fala. Reconecta sozinha,
 * com espera crescente; token recusado para de tentar.
 */
class Ponte(
    private val escopo: CoroutineScope,
    private val nome: String,
    private val aoLinha: (String) -> Unit,
    /** conectou: a aparência do orbe do PC e, logo depois, o que ele está mostrando */
    private val aoOla: (Ola, bruto: String) -> Unit,
    /** a aparência ou o tema mudaram no PC */
    private val aoConfig: (Ola, bruto: String) -> Unit,
    /** a resposta em voz: "24000" (a taxa do áudio que vem), "fim", "corta" */
    private val aoVoz: (String) -> Unit,
    private val aoAudio: (ByteArray) -> Unit,
    /** o relógio toca a resposta (a chave do menu e ter por onde falar) */
    private val querVoz: () -> Boolean,
    /** tocando aqui, o PC toca junto (a chave "Voz também no PC") */
    private val querVozPc: () -> Boolean = { false },
    /** os ajustes que o app do PC também edita, vindos de lá */
    private val aoAjustes: (Sincronia) -> Unit = {},
    /** as sessões do Claude Code abertas no PC mudaram */
    private val aoSessoes: (List<SessaoInfo>) -> Unit = {},
) {
    private val cliente = OkHttpClient.Builder()
        .connectTimeout(6, TimeUnit.SECONDS)
        .pingInterval(20, TimeUnit.SECONDS)
        .build()

    private val _estado = MutableStateFlow<Ligacao>(Ligacao.SemServidor)
    val estado: StateFlow<Ligacao> = _estado

    private var laco: Job? = null
    @Volatile private var soquete: WebSocket? = null
    private var alvo = "" to ""

    /** Liga (ou religa, se o endereço ou o token mudaram). */
    fun ligar(servidor: String, token: String, forcar: Boolean = false) {
        if (!forcar && laco?.isActive == true && alvo == servidor to token) return
        desligar()
        alvo = servidor to token
        val url = Protocolo.url(servidor)
        if (url == null || token.isBlank()) {
            _estado.value = if (servidor.isBlank() || token.isBlank()) Ligacao.SemServidor
            else Ligacao.Falha("endereço inválido", definitiva = true)
            return
        }
        laco = escopo.launch {
            var espera = 1000L
            while (isActive) {
                _estado.value = Ligacao.Conectando
                val fim = sessao(url, token)
                soquete = null
                if (fim.conectou) espera = 1000L
                _estado.value = Ligacao.Falha(fim.motivo, fim.definitiva)
                if (fim.definitiva) return@launch
                delay(if (fim.codigo == 4429) 60_000L else espera)
                espera = (espera * 2).coerceAtMost(15_000L)
            }
        }
    }

    fun desligar() {
        laco?.cancel()
        laco = null
        soquete?.close(1000, null)
        soquete = null
        _estado.value = Ligacao.SemServidor
    }

    fun enviar(linha: String): Boolean = soquete?.send(linha) ?: false

    fun enviarAudio(pcm: ByteArray, n: Int): Boolean = soquete?.send(pcm.toByteString(0, n)) ?: false

    private class Fim(val motivo: String, val codigo: Int, val conectou: Boolean, val definitiva: Boolean)

    /** Uma conexão, do aperto de mão até cair. */
    private suspend fun sessao(url: String, token: String): Fim {
        val fim = CompletableDeferred<Fim>()
        var conectou = false
        val ouvinte = object : WebSocketListener() {
            override fun onMessage(webSocket: WebSocket, text: String) {
                when {
                    // a ponte desafia; a resposta prova o token sem mandá-lo
                    text.startsWith("desafio ") -> if (!conectou) {
                        Protocolo.apresentar(token, text.substring(8).trim(), nome, querVoz(), querVozPc())
                            ?.let(webSocket::send)
                    }
                    text.startsWith("ola ") -> Protocolo.ola(text.substring(4))?.let {
                        conectou = true
                        soquete = webSocket
                        _estado.value = Ligacao.Conectada(it.microfone, it.voz, it.vozPc)
                        aoOla(it, text.substring(4))
                    }
                    text.startsWith("voz ") -> if (conectou) aoVoz(text.substring(4).trim())
                    text.startsWith("config ") -> Protocolo.ola(text.substring(7))?.let {
                        aoConfig(it, text.substring(7))
                    }
                    text.startsWith("ajustes ") -> if (conectou) Protocolo.sincronia(text.substring(8))?.let(aoAjustes)
                    text.startsWith("sessoes ") -> if (conectou) Protocolo.sessoes(text.substring(8))?.let(aoSessoes)
                    conectou -> aoLinha(text)
                }
            }

            override fun onMessage(webSocket: WebSocket, bytes: ByteString) {
                if (conectou) aoAudio(bytes.toByteArray())
            }

            override fun onClosing(webSocket: WebSocket, code: Int, reason: String) {
                webSocket.close(1000, null)
                fim.complete(fechou(code))
            }

            override fun onClosed(webSocket: WebSocket, code: Int, reason: String) {
                fim.complete(fechou(code))
            }

            override fun onFailure(webSocket: WebSocket, t: Throwable, response: Response?) {
                fim.complete(Fim(if (conectou) "conexão caiu" else "sem resposta", 0, conectou, false))
            }

            private fun fechou(code: Int) = when (code) {
                4401 -> Fim("token recusado", code, conectou, definitiva = true)
                4429 -> Fim("muitas tentativas", code, conectou, false)
                else -> Fim("desconectado", code, conectou, false)
            }
        }
        val pedido = try {
            Request.Builder().url(url).build()
        } catch (e: IllegalArgumentException) {
            return Fim("endereço inválido", 0, conectou = false, definitiva = true)
        }
        val ws = cliente.newWebSocket(pedido, ouvinte)
        try {
            return fim.await()
        } finally {
            ws.cancel()
        }
    }
}
