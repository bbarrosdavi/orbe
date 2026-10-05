package io.hermes.orbe

import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.app.Service
import android.content.Context
import android.content.Intent
import android.os.IBinder
import android.os.PowerManager
import android.provider.Settings
import android.util.Log
import androidx.core.content.ContextCompat

/**
 * Segura o relógio acordado enquanto um pedido espera a resposta com o orbe
 * fora da tela. A ponte continua no processo, pelo ViewModel; sem um serviço em
 * primeiro plano, o Android congela o processo e a CPU dorme com a tela
 * apagada, e a conexão para. Com a resposta, [trazer] acende a tela e põe o
 * orbe na frente, falando.
 */
class ServicoEspera : Service() {
    private var acordado: PowerManager.WakeLock? = null

    override fun onCreate() {
        super.onCreate()
        startForeground(NOTIFICACAO, notificacao())
        acordado = getSystemService(PowerManager::class.java)
            .newWakeLock(PowerManager.PARTIAL_WAKE_LOCK, "orbe:espera")
            .apply {
                setReferenceCounted(false)
                acquire(TETO_MS)
            }
    }

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int = START_NOT_STICKY

    override fun onBind(intent: Intent?): IBinder? = null

    private fun notificacao(): Notification {
        getSystemService(NotificationManager::class.java).createNotificationChannel(
            NotificationChannel(CANAL, "Resposta", NotificationManager.IMPORTANCE_MIN),
        )
        val abrir = PendingIntent.getActivity(this, 0, Intent(this, MainActivity::class.java), PendingIntent.FLAG_IMMUTABLE)
        return Notification.Builder(this, CANAL)
            .setSmallIcon(R.drawable.ic_launcher_monochrome)
            .setContentTitle("Esperando a resposta")
            .setContentIntent(abrir)
            .setOngoing(true)
            .build()
    }

    override fun onDestroy() {
        acordado?.let { if (it.isHeld) it.release() }
        super.onDestroy()
    }

    companion object {
        private const val TAG = "OrbeEspera"
        private const val CANAL = "espera"
        private const val NOTIFICACAO = 8
        /** O teto da espera: o mesmo do daemon esperando a resposta de um agente. */
        const val TETO_MS = 10 * 60_000L
        /** Quanto a tela fica acesa pela resposta, até o orbe abrir e segurar ela. */
        private const val TELA_MS = 2_000L

        fun ligar(c: Context) {
            ContextCompat.startForegroundService(c, Intent(c, ServicoEspera::class.java))
        }

        fun desligar(c: Context) {
            c.stopService(Intent(c, ServicoEspera::class.java))
        }

        /** A resposta chegou: acende a tela e traz o orbe para a frente. */
        fun trazer(c: Context) {
            if (!Settings.canDrawOverlays(c)) {
                Log.w(TAG, "sem permissão de sobreposição: o Android bloqueia abrir a tela a partir do serviço; a voz toca assim mesmo")
            }
            val energia = c.getSystemService(PowerManager::class.java)
            if (!energia.isInteractive) {
                // como na sacudida: o setTurnScreenOn da tela não acende este relógio
                @Suppress("DEPRECATION")
                energia.newWakeLock(PowerManager.SCREEN_BRIGHT_WAKE_LOCK or PowerManager.ACQUIRE_CAUSES_WAKEUP, "orbe:resposta")
                    .acquire(TELA_MS)
            }
            c.startActivity(
                Intent(c, MainActivity::class.java)
                    .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_CLEAR_TOP or Intent.FLAG_ACTIVITY_SINGLE_TOP),
            )
            Log.i(TAG, "resposta: orbe de volta à frente")
        }
    }
}
