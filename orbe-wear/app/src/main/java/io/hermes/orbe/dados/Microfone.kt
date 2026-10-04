package io.hermes.orbe.dados

import android.annotation.SuppressLint
import android.media.AudioFormat
import android.media.AudioRecord
import android.media.MediaRecorder
import android.util.Log
import java.util.concurrent.atomic.AtomicBoolean
import kotlin.concurrent.thread

/**
 * A fala captada pelo relógio, no formato que o daemon consome: PCM s16le
 * mono a 16 kHz, em blocos de 30 ms (o quadro do VAD dele).
 */
class Microfone {
    companion object {
        const val TAXA = 16000
        const val BLOCO = 960        // 30 ms
    }

    private var atual: AtomicBoolean? = null

    /** Começa a captar; [aoBloco] roda na thread da captura. Exige a permissão de áudio já dada. */
    @SuppressLint("MissingPermission")
    fun iniciar(aoBloco: (ByteArray, Int) -> Unit): Boolean {
        parar()
        val minimo = AudioRecord.getMinBufferSize(TAXA, AudioFormat.CHANNEL_IN_MONO, AudioFormat.ENCODING_PCM_16BIT)
        if (minimo <= 0) return false
        val rec = try {
            AudioRecord(MediaRecorder.AudioSource.VOICE_RECOGNITION, TAXA, AudioFormat.CHANNEL_IN_MONO,
                AudioFormat.ENCODING_PCM_16BIT, maxOf(minimo, BLOCO * 8))
        } catch (e: Exception) {
            Log.w("Orbe", "microfone: ${e.message}")
            return false
        }
        if (rec.state != AudioRecord.STATE_INITIALIZED) {
            rec.release()
            return false
        }
        // cada captura tem o seu sinal: uma nova pode começar com a anterior ainda fechando
        val vivo = AtomicBoolean(true)
        atual = vivo
        thread(name = "orbe-mic") {
            val bloco = ByteArray(BLOCO)
            try {
                rec.startRecording()
                while (vivo.get()) {
                    // o bloco inteiro: o daemon remonta os quadros, mas assim nenhum chega partido
                    var lido = 0
                    while (vivo.get() && lido < BLOCO) {
                        val n = rec.read(bloco, lido, BLOCO - lido)
                        if (n <= 0) break
                        lido += n
                    }
                    if (lido < BLOCO) break
                    aoBloco(bloco, lido)
                }
            } catch (e: Exception) {
                Log.w("Orbe", "microfone: ${e.message}")
            } finally {
                try {
                    rec.stop()
                } catch (e: Exception) {
                    // nunca chegou a gravar
                }
                rec.release()
            }
        }
        return true
    }

    fun parar() {
        atual?.set(false)
        atual = null
    }
}
