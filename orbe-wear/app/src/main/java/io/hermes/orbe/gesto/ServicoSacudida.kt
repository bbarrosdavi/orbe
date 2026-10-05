package io.hermes.orbe.gesto

import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.app.Service
import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.content.IntentFilter
import android.database.ContentObserver
import android.hardware.Sensor
import android.hardware.SensorEvent
import android.hardware.SensorEventListener
import android.hardware.SensorManager
import android.os.Handler
import android.os.IBinder
import android.os.Looper
import android.os.PowerManager
import android.os.SystemClock
import android.provider.Settings
import android.util.Log
import androidx.core.content.ContextCompat
import io.hermes.orbe.MainActivity
import io.hermes.orbe.R
import io.hermes.orbe.dados.Cofre
import kotlin.math.sqrt
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.cancel
import kotlinx.coroutines.launch

/**
 * Serviço em primeiro plano que escuta a sacudida (o mesmo desenho do
 * GestureService do HinaWatch).
 *
 * O giroscópio e o acelerômetro do relógio não acordam a CPU: a janela de
 * leitura abre quando a tela acende e fecha quando ela apaga, com teto de
 * [JANELA_MS]. O detector de inclinação do pulso (wrist_tilt_gesture, que
 * acorda a CPU) também a abre, inclusive com a tela apagada (o relógio que só
 * acende o LCD secundário ao inclinar): aí a janela dura [JANELA_ESCURA_MS] e o
 * orbe abre acendendo a tela. Uma sacudida abre o orbe já ouvindo; duas são do
 * HinaWatch e passam. Com a chave do menu desligada o serviço se encerra.
 */
class ServicoSacudida : Service(), SensorEventListener {
    private lateinit var sensores: SensorManager
    private lateinit var energia: PowerManager
    private val maos = Handler(Looper.getMainLooper())
    private var giro: Sensor? = null
    private var acel: Sensor? = null
    private var inclinacao: Sensor? = null
    private var acordado: PowerManager.WakeLock? = null
    private var janelaAberta = false
    private var fimJanela = 0L            // uptime em que a janela aberta fecha
    private var avisouArmado = false
    private var gy = 0f
    private var gz = 0f
    private val sacudida = Sacudida()
    private val escopo = CoroutineScope(SupervisorJob() + Dispatchers.Main.immediate)

    private val fechar = Runnable { fecharJanela() }

    private val tela = object : BroadcastReceiver() {
        override fun onReceive(context: Context, intent: Intent) {
            when (intent.action) {
                Intent.ACTION_SCREEN_ON -> {
                    sincronizarInclinacao()
                    abrirJanela("tela acesa")
                }
                Intent.ACTION_SCREEN_OFF -> {
                    fecharJanela()
                    sincronizarInclinacao()
                }
            }
        }
    }

    private val pulso = object : SensorEventListener {
        override fun onSensorChanged(event: SensorEvent) {
            if (energia.isInteractive) abrirJanela("pulso") else abrirJanela("pulso com a tela apagada", JANELA_ESCURA_MS)
        }

        override fun onAccuracyChanged(sensor: Sensor?, accuracy: Int) = Unit
    }

    // No modo "inclinar acende só o LCD", o LCD só acende se nenhum app estiver
    // inscrito no detector de inclinação no instante em que a tela apaga: com
    // um inscrito, o processador auxiliar entrega o gesto ao Android e não
    // acende a luz. Quem se inscreve depois recebe a inclinação e o LCD acende
    // igual (medido no Pro 3 Ultra em 2026-10-05, a regra do HinaWatch).
    private var inclinacaoInscrita = false
    private val modoTela = object : ContentObserver(maos) {
        override fun onChange(selfChange: Boolean) = sincronizarInclinacao()
    }
    private val rearmar = Runnable {
        inscrever(true)
        if (!janelaAberta) acordado?.let { if (it.isHeld) it.release() }
    }

    override fun onCreate() {
        super.onCreate()
        sensores = getSystemService(SensorManager::class.java)
        energia = getSystemService(PowerManager::class.java)
        giro = sensores.getDefaultSensor(Sensor.TYPE_GYROSCOPE)
        acel = sensores.getDefaultSensor(Sensor.TYPE_ACCELEROMETER)
        inclinacao = sensores.getDefaultSensor(TIPO_INCLINACAO, true) ?: sensores.getDefaultSensor(TIPO_INCLINACAO)
        acordado = energia.newWakeLock(PowerManager.PARTIAL_WAKE_LOCK, "orbe:sacudida").apply { setReferenceCounted(false) }
        startForeground(NOTIFICACAO, notificacao())
        escopo.launch {
            Cofre(applicationContext).fluxo.collect {
                if (!it.sacudida) {
                    stopSelf()
                    return@collect
                }
                sacudida.foraMin = it.sacudidaFora
                sacudida.dentroMin = it.sacudidaDentro
            }
        }
        // trocar o modo nos Ajustes do relógio vale na hora
        runCatching {
            contentResolver.registerContentObserver(Settings.Secure.getUriFor("low_power_screen"), false, modoTela)
            contentResolver.registerContentObserver(Settings.Global.getUriFor("ambient_tilt_to_wake"), false, modoTela)
        }
        sincronizarInclinacao()
        ContextCompat.registerReceiver(
            this, tela,
            IntentFilter(Intent.ACTION_SCREEN_ON).apply { addAction(Intent.ACTION_SCREEN_OFF) },
            ContextCompat.RECEIVER_NOT_EXPORTED,
        )
        Log.i(TAG, "ativo: giroscópio=${giro != null} inclinação=${inclinacao?.name}")
    }

    /**
     * Fora do modo só LCD, inscrito sempre. Nele: fora do detector com a tela
     * acesa (a janela abre pelo SCREEN_ON), e inscrito [REARMAR_MS] depois de a
     * tela apagar; a tela que acende antes cancela a inscrição pendente.
     */
    private fun sincronizarInclinacao() {
        maos.removeCallbacks(rearmar)
        when {
            !lcdAcendeNaInclinacao() -> inscrever(true)
            energia.isInteractive -> inscrever(false)
            !inclinacaoInscrita -> {
                // sem a trava a CPU dorme antes e a inscrição só sairia no próximo despertar
                acordado?.acquire(REARMAR_MS + 1_000)
                maos.postDelayed(rearmar, REARMAR_MS)
            }
        }
    }

    private fun inscrever(sim: Boolean) {
        val sensor = inclinacao ?: return
        if (sim == inclinacaoInscrita) return
        if (sim) sensores.registerListener(pulso, sensor, SensorManager.SENSOR_DELAY_NORMAL)
        else sensores.unregisterListener(pulso, sensor)
        inclinacaoInscrita = sim
        Log.d(TAG, "detector de inclinação ${if (sim) "inscrito" else "solto"}")
    }

    /**
     * O modo dos Ajustes do relógio (PowerSaverScreenManager): tela de economia
     * ligada e inclinar sem acender a principal. Chaves fora do SDK; sem
     * leitura, fica como antes (inscrito).
     */
    private fun lcdAcendeNaInclinacao(): Boolean = runCatching {
        Settings.Secure.getInt(contentResolver, "low_power_screen", 0) == 1 &&
            Settings.Global.getInt(contentResolver, "ambient_tilt_to_wake", 1) == 0
    }.getOrDefault(false)

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int = START_STICKY

    override fun onBind(intent: Intent?): IBinder? = null

    /** Abre a janela ou a estende por [ms]; uma janela aberta nunca encurta. */
    private fun abrirJanela(motivo: String, ms: Long = JANELA_MS) {
        val g = giro ?: return
        if (!janelaAberta) {
            sacudida.zerar()
            avisouArmado = false
            sensores.registerListener(this, g, SensorManager.SENSOR_DELAY_GAME)
            acel?.let { sensores.registerListener(this, it, SensorManager.SENSOR_DELAY_GAME) }
            janelaAberta = true
            fimJanela = 0L
            Log.d(TAG, "janela aberta ($motivo)")
        }
        val fim = SystemClock.uptimeMillis() + ms
        if (fim <= fimJanela) return
        fimJanela = fim
        acordado?.acquire(ms + 2_000)
        maos.removeCallbacks(fechar)
        maos.postAtTime(fechar, fim)
    }

    private fun fecharJanela() {
        if (!janelaAberta) return
        if (!sacudida.armado) Log.d(TAG, "não armou; maior pico ignorado: %.1f".format(sacudida.maxAntesDeArmar))
        sensores.unregisterListener(this)
        janelaAberta = false
        fimJanela = 0L
        maos.removeCallbacks(fechar)
        acordado?.let { if (it.isHeld) it.release() }
        Log.d(TAG, "janela fechada")
    }

    override fun onSensorChanged(event: SensorEvent) {
        when (event.sensor.type) {
            Sensor.TYPE_ACCELEROMETER -> {
                gy += (event.values[1] - gy) * ALFA_GRAVIDADE
                gz += (event.values[2] - gz) * ALFA_GRAVIDADE
                sacudida.gravidade(gy, gz)
            }
            Sensor.TYPE_GYROSCOPE -> {
                val (x, y, z) = event.values
                val gesto = sacudida.ler(event.timestamp / 1_000_000, x, sqrt(x * x + y * y + z * z))
                if (sacudida.armado && !avisouArmado) {
                    avisouArmado = true
                    Log.d(TAG, "armado; maior pico ignorado antes: %.1f".format(sacudida.maxAntesDeArmar))
                }
                sacudida.tirarResumo()?.let { Log.i(TAG, "sequência: $it") }
                // durante a calibração o gesto é medido pela tela e não abre nada
                if (gesto == Gesto.UMA && !calibrando) {
                    abrirOrbe()
                    fecharJanela()
                }
            }
        }
    }

    override fun onAccuracyChanged(sensor: Sensor?, accuracy: Int) = Unit

    private fun abrirOrbe() {
        if (!Settings.canDrawOverlays(this)) {
            Log.w(TAG, "sem permissão de sobreposição: o Android bloqueia abrir a tela a partir do serviço")
        }
        if (!energia.isInteractive) {
            // A sacudida chegou com a tela apagada (pela inclinação). Ela acende
            // antes de o orbe abrir: o setTurnScreenOn da tela não acendeu neste
            // relógio, e a pausa da abertura no escuro contava como apagar a tela.
            @Suppress("DEPRECATION")
            energia.newWakeLock(PowerManager.SCREEN_BRIGHT_WAKE_LOCK or PowerManager.ACQUIRE_CAUSES_WAKEUP, "orbe:gesto-tela")
                .acquire(TELA_MS)
            Log.i(TAG, "abrindo o orbe com a tela apagada")
        }
        startActivity(
            Intent(this, MainActivity::class.java)
                .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_CLEAR_TOP or Intent.FLAG_ACTIVITY_SINGLE_TOP)
                .putExtra(MainActivity.EXTRA_OUVIR, true),
        )
    }

    private fun notificacao(): Notification {
        getSystemService(NotificationManager::class.java).createNotificationChannel(
            NotificationChannel(CANAL, "Sacudida", NotificationManager.IMPORTANCE_MIN),
        )
        val abrir = PendingIntent.getActivity(this, 0, Intent(this, MainActivity::class.java), PendingIntent.FLAG_IMMUTABLE)
        return Notification.Builder(this, CANAL)
            .setSmallIcon(R.drawable.ic_launcher_monochrome)
            .setContentTitle("Uma sacudida abre o orbe")
            .setContentIntent(abrir)
            .setOngoing(true)
            .build()
    }

    override fun onDestroy() {
        fecharJanela()
        escopo.cancel()
        maos.removeCallbacks(rearmar)
        inclinacao?.let { sensores.unregisterListener(pulso, it) }
        inclinacaoInscrita = false
        runCatching { contentResolver.unregisterContentObserver(modoTela) }
        runCatching { unregisterReceiver(tela) }
        super.onDestroy()
    }

    companion object {
        private const val TAG = "OrbeGesto"
        private const val CANAL = "sacudida"
        private const val NOTIFICACAO = 7
        /** Sensor.TYPE_WRIST_TILT_GESTURE é @hide no SDK; o valor é estável desde o Android 7 */
        private const val TIPO_INCLINACAO = 26
        private const val JANELA_MS = 10_000L
        /**
         * A janela aberta pela inclinação com a tela apagada: dá para a parada e a
         * sacudida. Mais curta que a da tela acesa porque abre a cada levantar de pulso.
         */
        private const val JANELA_ESCURA_MS = 6_000L
        /** Espera entre a tela apagar e a inscrição no detector, no modo só LCD (o valor testado). */
        private const val REARMAR_MS = 2_000L
        /** Quanto a tela fica acesa pela sacudida, até o orbe abrir e segurar ela. */
        private const val TELA_MS = 2_000L
        private const val ALFA_GRAVIDADE = 0.2f

        /** a tela de calibração está aberta: o gesto não abre o orbe */
        @Volatile var calibrando = false

        fun ligar(context: Context) {
            ContextCompat.startForegroundService(context, Intent(context, ServicoSacudida::class.java))
        }

        fun desligar(context: Context) {
            context.stopService(Intent(context, ServicoSacudida::class.java))
        }
    }
}
