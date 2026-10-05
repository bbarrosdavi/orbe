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
import android.hardware.Sensor
import android.hardware.SensorEvent
import android.hardware.SensorEventListener
import android.hardware.SensorManager
import android.os.Handler
import android.os.IBinder
import android.os.Looper
import android.os.PowerManager
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
 * [JANELA_MS]; o detector de inclinação do pulso (wrist_tilt_gesture) só a
 * reabre com a tela já acesa. Uma sacudida abre o orbe já ouvindo; duas são do
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
    private var avisouArmado = false
    private var gy = 0f
    private var gz = 0f
    private val sacudida = Sacudida()
    private val escopo = CoroutineScope(SupervisorJob() + Dispatchers.Main.immediate)

    private val fechar = Runnable { fecharJanela() }

    private val tela = object : BroadcastReceiver() {
        override fun onReceive(context: Context, intent: Intent) {
            when (intent.action) {
                Intent.ACTION_SCREEN_ON -> abrirJanela("tela acesa")
                Intent.ACTION_SCREEN_OFF -> fecharJanela()
            }
        }
    }

    private val pulso = object : SensorEventListener {
        override fun onSensorChanged(event: SensorEvent) {
            if (energia.isInteractive) abrirJanela("pulso")
        }

        override fun onAccuracyChanged(sensor: Sensor?, accuracy: Int) = Unit
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
        inclinacao?.let { sensores.registerListener(pulso, it, SensorManager.SENSOR_DELAY_NORMAL) }
        ContextCompat.registerReceiver(
            this, tela,
            IntentFilter(Intent.ACTION_SCREEN_ON).apply { addAction(Intent.ACTION_SCREEN_OFF) },
            ContextCompat.RECEIVER_NOT_EXPORTED,
        )
        Log.i(TAG, "ativo: giroscópio=${giro != null} inclinação=${inclinacao?.name}")
    }

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int = START_STICKY

    override fun onBind(intent: Intent?): IBinder? = null

    private fun abrirJanela(motivo: String) {
        val g = giro ?: return
        acordado?.acquire(JANELA_MS + 2_000)
        if (!janelaAberta) {
            sacudida.zerar()
            avisouArmado = false
            sensores.registerListener(this, g, SensorManager.SENSOR_DELAY_GAME)
            acel?.let { sensores.registerListener(this, it, SensorManager.SENSOR_DELAY_GAME) }
            janelaAberta = true
            Log.d(TAG, "janela aberta ($motivo)")
        }
        maos.removeCallbacks(fechar)
        maos.postDelayed(fechar, JANELA_MS)
    }

    private fun fecharJanela() {
        if (!janelaAberta) return
        if (!sacudida.armado) Log.d(TAG, "não armou; maior pico ignorado: %.1f".format(sacudida.maxAntesDeArmar))
        sensores.unregisterListener(this)
        janelaAberta = false
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
        inclinacao?.let { sensores.unregisterListener(pulso, it) }
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
