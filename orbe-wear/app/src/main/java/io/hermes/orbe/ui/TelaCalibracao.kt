package io.hermes.orbe.ui

import android.hardware.Sensor
import android.hardware.SensorEvent
import android.hardware.SensorEventListener
import android.hardware.SensorManager
import android.util.Log
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.BoxWithConstraints
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
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
import io.hermes.orbe.gesto.limiarSair
import io.hermes.orbe.gesto.limiares
import kotlin.math.sqrt

/** Qual sacudida a tela de calibração mede. */
enum class Calibracao { ABRIR, SAIR }

/**
 * Calibração da sacudida de abrir (a do HinaWatch): mede [TENTATIVAS] sacudidas
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
    Moldura(
        "Calibrar o abrir", redonda,
        aviso = if (proposta != null) "Fora ${um(proposta.fora)} · dentro ${um(proposta.dentro)} rad/s"
        else "Pulso parado, depois uma sacudida para fora e de volta. Tentativa ${tentativas.size + 1} de $TENTATIVAS.",
        tentativas = tentativas.map { "fora ${um(it.fora)} · dentro ${um(it.dentro)}" },
        padrao = "fora ${um(Sacudida.FORA_MIN)} · dentro ${um(Sacudida.DENTRO_MIN)}", aoPadrao = padrao,
        pronta = proposta != null, refazer = { tentativas.clear() }, salvar = { proposta?.let(salvar) },
        emUso = "fora ${um(emUso.fora)} · dentro ${um(emUso.dentro)}",
    )
}

/**
 * Calibração da sacudida de sair (a do fechar do HinaWatch): mede [TENTATIVAS]
 * sacudidas só para fora com o detector armado uma vez, como o orbe aberto vê
 * (sem a espera parada a cada uma), e propõe o fora a partir da mais fraca.
 * Com o orbe aberto a sacudida sai no pico para fora, então só o fora conta.
 */
@Composable
fun TelaCalibracaoSair(
    emUso: Float,
    redonda: Boolean,
    salvar: (Float) -> Unit,
    padrao: () -> Unit,
) {
    val foras = remember { mutableStateListOf<Float>() }
    val sacudida = remember { Sacudida(paradoMs = Sacudida.PARADO_MS) }
    Sensores(sacudida) {
        val fora = sacudida.tirarFora() ?: return@Sensores
        if (fora < TENTATIVA_MIN || foras.size >= TENTATIVAS) return@Sensores
        foras += fora
    }
    val proposta = if (foras.size >= TENTATIVAS) limiarSair(foras) else null
    Moldura(
        "Calibrar o sair", redonda,
        aviso = if (proposta != null) "Fora ${um(proposta)} rad/s"
        else "Pulso parado, depois uma sacudida só para fora. Tentativa ${foras.size + 1} de $TENTATIVAS.",
        tentativas = foras.map { "fora ${um(it)}" },
        padrao = "fora ${um(Sacudida.FORA_MIN)}", aoPadrao = padrao,
        pronta = proposta != null, refazer = { foras.clear() }, salvar = { proposta?.let(salvar) },
        emUso = if (emUso > 0f) "fora ${um(emUso)}" else "o padrão, fora ${um(Sacudida.FORA_MIN)}",
    )
}

/** A tela das duas calibrações, sobre o mesmo fundo do menu. */
@Composable
private fun Moldura(
    titulo: String,
    redonda: Boolean,
    aviso: String,
    tentativas: List<String>,
    padrao: String,
    aoPadrao: () -> Unit,
    pronta: Boolean,
    refazer: () -> Unit,
    salvar: () -> Unit,
    emUso: String,
) {
    BoxWithConstraints(Modifier.fillMaxSize()) {
        FundoVidro()
        val margem = maxWidth * (if (redonda) 0.14f else 0.05f)
        Column(
            Modifier.fillMaxSize().verticalScroll(rememberScrollState()).padding(horizontal = margem),
            horizontalAlignment = Alignment.CenterHorizontally,
        ) {
            Vao(if (redonda) 30.dp else 12.dp)
            Texto(titulo, Estilo.grupo, alinhar = TextAlign.Center)
            Vao(8.dp)
            Texto(aviso, Estilo.subtitulo, alinhar = TextAlign.Center)
            Vao(10.dp)
            Column(Modifier.caixa()) {
                tentativas.forEachIndexed { i, t ->
                    Linha("Tentativa ${i + 1}", subtitulo = t)
                    Box(Modifier.fillMaxWidth().height(1.dp).background(Estilo.texto.alfa(0.08f)))
                }
                Linha("Padrão", subtitulo = padrao, aoClicar = aoPadrao)
            }
            if (pronta) {
                Vao(10.dp)
                Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                    Botao("Refazer", Modifier.weight(1f), aoClicar = refazer)
                    Botao("Salvar", Modifier.weight(1f), destaque = true, aoClicar = salvar)
                }
            }
            Vao(8.dp)
            Texto("Em uso: $emUso", Estilo.mono, cor = Estilo.texto.alfa(0.6f), alinhar = TextAlign.Center)
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

/** pico mínimo para uma tentativa contar (o dentro no abrir, o fora no sair): abaixo disso é o pulso se ajeitando */
private const val TENTATIVA_MIN = 5f
