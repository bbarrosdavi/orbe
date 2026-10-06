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
    /** a captura anterior: a próxima só abre o microfone depois que ela o soltou */
    private var anterior: Thread? = null

    /**
     * Começa a captar; [aoBloco] roda na thread da captura. Exige a permissão de
     * áudio já dada. Nada aqui fala com o audioserver na thread de quem chama: com
     * ele lento ou caído, a tela travava junto.
     */
    @Synchronized
    fun iniciar(aoBloco: (ByteArray, Int) -> Unit) {
        parar()
        // cada captura tem o seu sinal: a anterior pode ainda estar fechando
        val vivo = AtomicBoolean(true)
        atual = vivo
        val antes = anterior
        anterior = thread(name = "orbe-mic") {
            // abrir com a anterior ainda soltando a entrada derrubou o audioserver do
            // relógio (RecordThread::setPreferredMicrophoneDirection numa entrada já fechada)
            try {
                antes?.join()
            } catch (e: InterruptedException) {
                return@thread
            }
            if (vivo.get()) captar(vivo, aoBloco)
        }
    }

    @SuppressLint("MissingPermission")
    private fun captar(vivo: AtomicBoolean, aoBloco: (ByteArray, Int) -> Unit) {
        val minimo = AudioRecord.getMinBufferSize(TAXA, AudioFormat.CHANNEL_IN_MONO, AudioFormat.ENCODING_PCM_16BIT)
        if (minimo <= 0) return
        val rec = try {
            AudioRecord(MediaRecorder.AudioSource.VOICE_RECOGNITION, TAXA, AudioFormat.CHANNEL_IN_MONO,
                AudioFormat.ENCODING_PCM_16BIT, maxOf(minimo, BLOCO * 8))
        } catch (e: Exception) {
            Log.w("Orbe", "microfone: ${e.message}")
            return
        }
        if (rec.state != AudioRecord.STATE_INITIALIZED) {
            rec.release()
            return
        }
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

    @Synchronized
    fun parar() {
        atual?.set(false)
        atual = null
    }
}
