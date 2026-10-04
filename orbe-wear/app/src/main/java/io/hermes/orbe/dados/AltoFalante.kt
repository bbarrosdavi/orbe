package io.hermes.orbe.dados

import android.annotation.SuppressLint
import android.content.Context
import android.media.AudioAttributes
import android.media.AudioDeviceInfo
import android.media.AudioFormat
import android.media.AudioManager
import android.media.AudioTrack
import android.util.Log
import java.util.concurrent.LinkedBlockingQueue
import java.util.concurrent.atomic.AtomicInteger
import kotlin.concurrent.thread
import kotlin.math.min
import kotlin.math.sqrt

/**
 * A voz da resposta, tocada no relógio: PCM s16le mono na taxa que a ponte
 * anuncia ("voz 24000"), em pedaços, conforme a síntese entrega.
 *
 * O nível e o tom que mexem o orbe saem do próprio áudio, na hora em que ele
 * toca (o daemon manda "level" para o orbe do desktop; aqui quem toca é o
 * relógio, então é ele que mede).
 */
class AltoFalante(
    /** nível (0 a 1) e tom (0 grave, 1 agudo) do trecho que está tocando */
    private val aoNivel: (Float, Float) -> Unit,
    /** tocou tudo até o "voz fim" */
    private val aoAcabar: () -> Unit,
) {
    private sealed interface Item
    private class Abrir(val taxa: Int) : Item
    private class Pcm(val bytes: ByteArray) : Item
    private data object Fim : Item

    private val fila = LinkedBlockingQueue<Pair<Int, Item>>()
    /** muda a cada corte: o que estava na fila e o que está tocando se calam */
    private val cortes = AtomicInteger()
    private val geracao: Int get() = cortes.get()
    @Volatile private var trilha: AudioTrack? = null
    private var fio: Thread? = null

    fun abrir(taxa: Int) = por(Abrir(taxa))

    fun tocar(pcm: ByteArray) = por(Pcm(pcm))

    /** O que falta toca até o fim, e então avisa. */
    fun fim() = por(Fim)

    /** Cala já (toque no orbe, sessão dispensada, relógio saiu da tela). */
    fun cortar() {
        cortes.incrementAndGet()
        fila.clear()
        try {
            trilha?.let {
                it.pause()
                it.flush()
            }
        } catch (e: IllegalStateException) {
            // a trilha já foi solta pela thread que toca
        }
        aoNivel(0f, 0.5f)
    }

    private fun por(item: Item) {
        fila.put(geracao to item)
        if (fio?.isAlive != true) fio = thread(name = "orbe-voz", isDaemon = true) { tocarFila() }
    }

    private fun tocarFila() {
        var taxa = 0
        var tocados = 0L                 // bytes desde o último "voz fim"
        var contada = geracao
        try {
            while (true) {
                val (ger, item) = fila.take()
                if (ger != geracao) continue
                if (ger != contada) {        // houve corte: a conta recomeça
                    contada = ger
                    tocados = 0
                }
                when (item) {
                    is Abrir -> if (item.taxa != taxa || trilha == null) {
                        soltar()
                        taxa = item.taxa
                        trilha = nova(taxa)
                    } else if (trilha?.playState != AudioTrack.PLAYSTATE_PLAYING) trilha?.play()
                    is Pcm -> {
                        escrever(item.bytes, taxa, ger)
                        tocados += item.bytes.size
                    }
                    Fim -> {
                        // o que ainda está no buffer da trilha termina de tocar
                        val t = trilha
                        if (t != null && taxa > 0) Thread.sleep((t.bufferSizeInFrames * 1000L / taxa).coerceAtMost(400))
                        if (taxa > 0) Log.i("Orbe", "voz: %.1f s a %d Hz".format(tocados / 2.0 / taxa, taxa))
                        tocados = 0
                        if (ger == geracao) {
                            aoNivel(0f, 0.5f)
                            aoAcabar()
                        }
                    }
                }
            }
        } catch (e: InterruptedException) {
            // app saindo
        } catch (e: Exception) {
            Log.w("Orbe", "voz: ${e.message}")
        } finally {
            soltar()
        }
    }

    private fun nova(taxa: Int): AudioTrack? = try {
        val minimo = AudioTrack.getMinBufferSize(taxa, AudioFormat.CHANNEL_OUT_MONO, AudioFormat.ENCODING_PCM_16BIT)
        AudioTrack.Builder()
            .setAudioAttributes(
                AudioAttributes.Builder().setUsage(AudioAttributes.USAGE_ASSISTANT)
                    .setContentType(AudioAttributes.CONTENT_TYPE_SPEECH).build(),
            )
            .setAudioFormat(
                AudioFormat.Builder().setSampleRate(taxa).setEncoding(AudioFormat.ENCODING_PCM_16BIT)
                    .setChannelMask(AudioFormat.CHANNEL_OUT_MONO).build(),
            )
            // buffer curto: o nível medido na escrita anda perto do que se ouve
            .setBufferSizeInBytes(maxOf(minimo, taxa * 2 / 10))
            .setTransferMode(AudioTrack.MODE_STREAM)
            .build().also { it.play() }
    } catch (e: Exception) {
        Log.w("Orbe", "voz: ${e.message}")
        null
    }

    /** Escreve em janelas de 40 ms, medindo cada uma (o LEVEL_WIN_MS do worker de voz). */
    private fun escrever(pcm: ByteArray, taxa: Int, ger: Int) {
        val t = trilha ?: return
        val janela = (taxa * 40 / 1000) * 2
        var i = 0
        while (i < pcm.size && ger == geracao) {
            val n = min(janela, pcm.size - i)
            medir(pcm, i, n)
            if (t.write(pcm, i, n) < 0) return
            i += n
        }
    }

    private fun medir(pcm: ByteArray, de: Int, n: Int) {
        val amostras = n / 2
        if (amostras < 8) return
        var soma = 0.0
        var cruzamentos = 0
        var anterior = 0
        for (k in 0 until amostras) {
            val v = (pcm[de + 2 * k + 1].toInt() shl 8) or (pcm[de + 2 * k].toInt() and 0xff)
            soma += v.toDouble() * v
            if (k > 0 && (v >= 0) != (anterior >= 0)) cruzamentos++
            anterior = v
        }
        val rms = sqrt(soma / amostras) / 32768.0
        // cruzamentos por amostra: ~0,02 em vogal, ~0,20 em fricativa
        val tom = (cruzamentos.toDouble() / amostras / 0.15).coerceIn(0.0, 1.0)
        aoNivel(min(1.0, rms * 6.5).toFloat(), tom.toFloat())
    }

    private fun soltar() {
        val t = trilha
        trilha = null
        try {
            t?.stop()
        } catch (e: IllegalStateException) {
            // nunca chegou a tocar
        }
        t?.release()
    }

    companion object {
        /** O relógio tem por onde falar (alto-falante, ou fone pareado)? */
        @SuppressLint("InlinedApi")      // os tipos BLE são do Android 12: antes dele, só não aparecem na lista
        fun temSaida(ctx: Context): Boolean {
            val am = ctx.getSystemService(AudioManager::class.java) ?: return false
            return am.getDevices(AudioManager.GET_DEVICES_OUTPUTS).any {
                it.type == AudioDeviceInfo.TYPE_BUILTIN_SPEAKER || it.type == AudioDeviceInfo.TYPE_BLUETOOTH_A2DP ||
                    it.type == AudioDeviceInfo.TYPE_BLE_HEADSET || it.type == AudioDeviceInfo.TYPE_BLE_SPEAKER
            }
        }
    }
}
