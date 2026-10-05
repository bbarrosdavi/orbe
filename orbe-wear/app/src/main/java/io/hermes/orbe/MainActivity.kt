package io.hermes.orbe

import android.Manifest
import android.app.RemoteInput
import android.content.Intent
import android.content.pm.PackageManager
import android.hardware.Sensor
import android.hardware.SensorEvent
import android.hardware.SensorEventListener
import android.hardware.SensorManager
import android.os.Bundle
import android.os.SystemClock
import android.util.Log
import android.view.WindowManager
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.activity.result.contract.ActivityResultContracts
import androidx.activity.viewModels
import androidx.compose.runtime.mutableStateOf
import androidx.lifecycle.Lifecycle
import androidx.lifecycle.lifecycleScope
import androidx.lifecycle.repeatOnLifecycle
import androidx.wear.input.RemoteInputIntentHelper
import io.hermes.orbe.gesto.Gesto
import io.hermes.orbe.gesto.Sacudida
import io.hermes.orbe.gesto.ServicoSacudida
import io.hermes.orbe.gl.Motor
import io.hermes.orbe.ui.Campo
import io.hermes.orbe.ui.OrbeApp
import kotlin.math.sqrt
import kotlinx.coroutines.flow.distinctUntilChanged
import kotlinx.coroutines.flow.map
import kotlinx.coroutines.launch

/**
 * O Orbe no relógio: o mesmo orbe do desktop, desenhado aqui com os shaders do
 * orbe-qt, ligado ao daemon pela ponte (hermes_voice_relogio.py).
 *
 * O endereço e o token também entram pelo adb, para não digitar no pulso:
 *   adb shell am start -n io.hermes.orbe/.MainActivity --es servidor 192.168.0.10 --es token abcd2345
 * Com --ez ouvir true (o que a sacudida manda), abre já numa sessão de voz
 * pelo microfone do relógio. Aberto, uma sacudida do pulso só para fora o
 * manda para trás, como a Hina aberta no HinaWatch.
 */
class MainActivity : ComponentActivity() {
    private val vm: OrbeViewModel by viewModels()
    private var campo = Campo.SERVIDOR

    private val teclado = registerForActivityResult(ActivityResultContracts.StartActivityForResult()) { r ->
        val dados = r.data ?: return@registerForActivityResult
        val texto = RemoteInput.getResultsFromIntent(dados)?.getCharSequence(CHAVE)?.toString()?.trim().orEmpty()
        if (texto.isEmpty()) return@registerForActivityResult
        when (campo) {
            Campo.SERVIDOR -> vm.servidor(texto)
            Campo.TOKEN -> vm.token(texto)
        }
    }

    private val permissao = registerForActivityResult(ActivityResultContracts.RequestPermission()) {}

    /** O menu pedido pelo adb (--es menu gaveta, ou o nome de uma aba), para conferir sem tocar no relógio. */
    private val menuPedido = mutableStateOf<String?>(null)

    private val sensores by lazy { getSystemService(SensorManager::class.java) }

    /** Com o orbe aberto, o primeiro pico forte para fora sai na hora, sem esperar a volta do pulso. */
    private val sair = object : SensorEventListener {
        val sacudida = Sacudida(paradoMs = Sacudida.PARADO_MS).apply { sairNaHora = true }
        var gy = 0f
        var gz = 9.8f

        override fun onSensorChanged(event: SensorEvent) {
            // calibrando, as sacudidas são de propósito e não saem
            if (ServicoSacudida.calibrando) {
                sacudida.zerar()
                return
            }
            when (event.sensor.type) {
                Sensor.TYPE_ACCELEROMETER -> {
                    gy += (event.values[1] - gy) * ALFA_GRAVIDADE
                    gz += (event.values[2] - gz) * ALFA_GRAVIDADE
                    sacudida.gravidade(gy, gz)
                }
                Sensor.TYPE_GYROSCOPE -> {
                    // o fora calibrado vale na próxima sacudida, sem religar os sensores
                    sacudida.sairForaMin = vm.ajustes.value.sairFora
                    val (x, y, z) = event.values
                    val gesto = sacudida.ler(event.timestamp / 1_000_000, x, sqrt(x * x + y * y + z * z))
                    sacudida.tirarResumo()?.let { Log.d(TAG, "na tela: $it") }
                    if (gesto == Gesto.SAIR) {
                        Log.i(TAG, "sair: sacudida para fora")
                        ServicoSacudida.saiuEm = SystemClock.uptimeMillis()
                        // o relógio volta ao mostrador; o onStop fecha a ponte e corta a voz
                        moveTaskToBack(true)
                    }
                }
            }
        }

        override fun onAccuracyChanged(sensor: Sensor?, accuracy: Int) = Unit
    }

    private fun ligarSair(ligar: Boolean) {
        val s = sensores ?: return
        s.unregisterListener(sair)
        if (!ligar) return
        sair.sacudida.zerar()
        s.getDefaultSensor(Sensor.TYPE_ACCELEROMETER)?.let { s.registerListener(sair, it, SensorManager.SENSOR_DELAY_UI) }
        s.getDefaultSensor(Sensor.TYPE_GYROSCOPE)?.let { s.registerListener(sair, it, SensorManager.SENSOR_DELAY_GAME) }
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        // Na frente, a tela não apaga pelo tempo sem toque. Abaixar ou virar o
        // pulso ainda apaga: o ungaze do Wear OS põe o relógio para dormir como
        // o botão ("Going to sleep due to sleep_button" junto do GESTURE UNGAZE
        // no log), e isso passa por cima desta trava.
        window.addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON)
        provisionar(intent)
        setContent {
            OrbeApp(
                vm,
                podeGravar = { checkSelfPermission(Manifest.permission.RECORD_AUDIO) == PackageManager.PERMISSION_GRANTED },
                pedirMicrofone = { permissao.launch(Manifest.permission.RECORD_AUDIO) },
                editar = ::editar,
                menuPedido = menuPedido,
            )
        }
        // os sensores do sair só com o orbe na frente e a chave ligada
        lifecycleScope.launch {
            repeatOnLifecycle(Lifecycle.State.RESUMED) {
                try {
                    vm.ajustes.map { it.sair }.distinctUntilChanged().collect(::ligarSair)
                } finally {
                    ligarSair(false)
                }
            }
        }
    }

    override fun onNewIntent(intent: Intent) {
        super.onNewIntent(intent)
        provisionar(intent)
    }

    override fun onStart() {
        super.onStart()
        vm.entrou()
    }

    override fun onStop() {
        vm.saiu()
        super.onStop()
    }

    private fun provisionar(i: Intent?) {
        i?.getStringExtra("servidor")?.let(vm::servidor)
        i?.getStringExtra("token")?.let(vm::token)
        // a sacudida do HinaWatch abre o orbe já ouvindo
        if (i?.getBooleanExtra(EXTRA_OUVIR, false) == true) {
            vm.ouvir(checkSelfPermission(Manifest.permission.RECORD_AUDIO) == PackageManager.PERMISSION_GRANTED)
        }
        // para medir num relógio de verdade: --ef qualidade 0.75 trava a resolução da máscara
        i?.getFloatExtra("qualidade", -1f)?.takeIf { it >= 0f }?.let { Motor.qualidadeFixa = it }
        i?.getStringExtra("menu")?.let { menuPedido.value = it }
    }

    /** O teclado do relógio (ou o ditado, ou o do celular pareado) para um campo de texto. */
    private fun editar(c: Campo) {
        campo = c
        val pedido = RemoteInputIntentHelper.createActionRemoteInputIntent()
        val entrada = RemoteInput.Builder(CHAVE).setLabel(c.rotulo).build()
        RemoteInputIntentHelper.putRemoteInputsExtra(pedido, listOf(entrada))
        teclado.launch(pedido)
    }

    companion object {
        private const val CHAVE = "texto"
        private const val TAG = "OrbeGesto"
        private const val ALFA_GRAVIDADE = 0.2f
        /** abre já numa sessão de voz: a sacudida (do orbe ou do HinaWatch) */
        const val EXTRA_OUVIR = "ouvir"
    }
}
