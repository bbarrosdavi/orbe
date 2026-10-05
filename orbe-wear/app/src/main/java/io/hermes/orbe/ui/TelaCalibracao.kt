package io.hermes.orbe.ui

import android.hardware.Sensor
import android.hardware.SensorEvent
import android.hardware.SensorEventListener
import android.hardware.SensorManager
import android.util.Log
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.BoxWithConstraints
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.mutableStateListOf
import androidx.compose.runtime.remember
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import io.hermes.orbe.gesto.Picos
import io.hermes.orbe.gesto.Sacudida
import io.hermes.orbe.gesto.ServicoSacudida
import io.hermes.orbe.gesto.limiares
import kotlin.math.sqrt

/**
 * Calibração da sacudida (a do HinaWatch): mede [TENTATIVAS] sacudidas
 * fora→dentro do jeito que o serviço vê, com a mesma espera parada antes de
 * cada uma, e propõe os limiares a partir da mais fraca. Enquanto a tela está
 * aberta, o serviço não abre o orbe.
 */
@Composable
fun TelaCalibracao(
    emUso: Picos,
    redonda: Boolean,
    salvar: (Picos) -> Unit,
    padrao: () -> Unit,
) {
    val tentativas = remember { mutableStateListOf<Picos>() }
    val sacudida = remember { Sacudida() }
    Sensores(sacudida) {
        val par = sacudida.tirarPar() ?: return@Sensores
        // um ajeitar do pulso entre as tentativas não é sacudida
        if (par.dentro < TENTATIVA_MIN || tentativas.size >= TENTATIVAS) return@Sensores
        tentativas += par
        // cada tentativa recomeça com a espera parada, como ao acender a tela
        sacudida.zerar()
    }
    val proposta = if (tentativas.size >= TENTATIVAS) limiares(tentativas) else null

    BoxWithConstraints(Modifier.fillMaxSize().background(Estilo.fundo)) {
        val margem = maxWidth * (if (redonda) 0.14f else 0.05f)
        Column(
            Modifier.fillMaxSize().verticalScroll(rememberScrollState()).padding(horizontal = margem),
            horizontalAlignment = Alignment.CenterHorizontally,
        ) {
            Vao(if (redonda) 30.dp else 12.dp)
            Texto("Calibrar a sacudida", Estilo.grupo, alinhar = TextAlign.Center)
            Vao(8.dp)
            Texto(
                if (proposta != null) "Fora ${um(proposta.fora)} · dentro ${um(proposta.dentro)} rad/s"
                else "Pulso parado, depois uma sacudida para fora e de volta. Tentativa ${tentativas.size + 1} de $TENTATIVAS.",
                Estilo.subtitulo, alinhar = TextAlign.Center,
            )
            Vao(10.dp)
            Grupo {
                tentativas.forEachIndexed { i, t ->
                    item { Linha("Tentativa ${i + 1}", subtitulo = "fora ${um(t.fora)} · dentro ${um(t.dentro)}") }
                }
                item {
                    Linha("Padrão", subtitulo = "fora ${um(Sacudida.FORA_MIN)} · dentro ${um(Sacudida.DENTRO_MIN)}", aoClicar = padrao)
                }
            }
            if (proposta != null) {
                Vao(10.dp)
                Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                    Botao("Refazer", Modifier.weight(1f)) { tentativas.clear() }
                    Botao("Salvar", Modifier.weight(1f), destaque = true) { salvar(proposta) }
                }
            }
            Vao(8.dp)
            Texto(
                "Em uso: fora ${um(emUso.fora)} · dentro ${um(emUso.dentro)}",
                Estilo.mono, cor = Estilo.texto.alfa(0.6f), alinhar = TextAlign.Center,
            )
            Vao(if (redonda) 40.dp else 16.dp)
        }
    }
}

/**
 * Liga acelerômetro e giroscópio à [sacudida] enquanto a tela está aberta;
 * [aoLer] roda depois de cada leitura do giroscópio, para tirar o que ela mediu.
 */
@Composable
private fun Sensores(sacudida: Sacudida, aoLer: () -> Unit) {
    val ctx = LocalContext.current
    val ler = remember { arrayOf(aoLer) }
    ler[0] = aoLer
    DisposableEffect(sacudida) {
        ServicoSacudida.calibrando = true
        val sensores = ctx.getSystemService(SensorManager::class.java)
        var gy = 0f
        var gz = 0f
        val ouvinte = object : SensorEventListener {
            override fun onSensorChanged(event: SensorEvent) {
                when (event.sensor.type) {
                    Sensor.TYPE_ACCELEROMETER -> {
                        gy += (event.values[1] - gy) * ALFA_GRAVIDADE
                        gz += (event.values[2] - gz) * ALFA_GRAVIDADE
                        sacudida.gravidade(gy, gz)
                    }
                    Sensor.TYPE_GYROSCOPE -> {
                        val (x, y, z) = event.values
                        sacudida.ler(event.timestamp / 1_000_000, x, sqrt(x * x + y * y + z * z))
                        sacudida.tirarResumo()?.let { Log.i("OrbeGesto", "calibração: $it") }
                        ler[0]()
                    }
                }
            }

            override fun onAccuracyChanged(sensor: Sensor?, accuracy: Int) = Unit
        }
        sensores?.getDefaultSensor(Sensor.TYPE_ACCELEROMETER)?.let { sensores.registerListener(ouvinte, it, SensorManager.SENSOR_DELAY_GAME) }
        sensores?.getDefaultSensor(Sensor.TYPE_GYROSCOPE)?.let { sensores.registerListener(ouvinte, it, SensorManager.SENSOR_DELAY_GAME) }
        onDispose {
            sensores?.unregisterListener(ouvinte)
            ServicoSacudida.calibrando = false
        }
    }
}

private fun um(v: Float) = "%.1f".format(v).replace('.', ',')

private const val TENTATIVAS = 3
private const val ALFA_GRAVIDADE = 0.2f

/** dentro mínimo para uma tentativa contar: abaixo disso é o pulso se ajeitando */
private const val TENTATIVA_MIN = 5f
