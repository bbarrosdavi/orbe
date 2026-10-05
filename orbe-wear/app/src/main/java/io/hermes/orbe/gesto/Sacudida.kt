package io.hermes.orbe.gesto

import kotlin.math.abs

/** O que uma sequência de giros do pulso deu. */
enum class Gesto {
    /** uma sacudida fora→dentro: abre o orbe */
    UMA,
    /** duas na mesma sequência: são do HinaWatch (abrem a Hina), o orbe deixa passar */
    DUAS,
}

/** Fora e dentro de uma sacudida, em rad/s: o que a calibração mede. */
data class Picos(val fora: Float, val dentro: Float)

/**
 * Limiares a partir das tentativas da calibração: [MARGEM] da mais fraca em cada
 * metade, nunca abaixo do que já conta como pico forte.
 */
fun limiares(tentativas: List<Picos>): Picos {
    require(tentativas.isNotEmpty())
    return Picos(
        (tentativas.minOf { it.fora } * MARGEM).coerceAtLeast(Sacudida.FORTE_MIN),
        (tentativas.minOf { it.dentro } * MARGEM).coerceAtLeast(Sacudida.FORTE_MIN),
    )
}

/** O gesto precisa chegar a esta fração da tentativa mais fraca da calibração. */
const val MARGEM = 0.6f

/**
 * A sacudida do pulso: o mesmo detector do HinaWatch (FlickDetector, em
 * WristMotion.kt), para os dois apps contarem igual. Uma sacudida é do orbe,
 * duas são da Hina.
 *
 * Eixos do relógio: x ao longo do antebraço; girar o pulso para dentro ou para
 * fora é rotação em x. O sentido sai do sinal de ωx comparado com a postura:
 * olhando o relógio, a tela fica inclinada para o rosto e o sinal da gravidade
 * em y no começo da sequência diz qual borda sobe. "Para dentro" é ωx com o
 * mesmo sinal de gy; com a tela quase plana vale o último sentido conhecido e,
 * sem nenhum, o gz que cresce.
 *
 * Só arma depois de o relógio ficar parado por [paradoMs] (o levantar do pulso
 * para acender a tela não conta) e decide depois de [QUIETO_MS] sem movimento,
 * para saber se a sacudida se repetiu. O rebote do pulso ao parar um giro
 * rápido é descartado.
 */
class Sacudida(
    /** fora mínimo de cada sacudida; a calibração troca */
    var foraMin: Float = FORA_MIN,
    /** dentro mínimo de cada sacudida; a calibração troca */
    var dentroMin: Float = DENTRO_MIN,
    private val paradoMs: Long = PARADO_ABRIR_MS,
) {
    private class Pico(
        val iniMs: Long,
        var fimMs: Long,
        var max: Float,
        val gyIni: Float,
        val gzIni: Float,
        var gzFim: Float,
        val positivo: Boolean,
    )

    private val picos = ArrayList<Pico>(4)
    private var atual: Pico? = null
    private var ultimoMovMs = -1L
    private var paradoDesdeMs = -1L
    private var gy = 0f
    private var gz = 0f

    /** sinal de gy da última postura inclinada o bastante; 0 enquanto não houve nenhuma */
    private var sinalTela = 0

    /** já houve a parada que arma o detector desde o último [zerar] */
    var armado = false
        private set

    /** maior |ωx| antes de armar: o que foi ignorado, para o log */
    var maxAntesDeArmar = 0f
        private set

    private var resumo: String? = null
    private var par: Picos? = null

    /** A última leitura filtrada da gravidade em y e em z (m/s²). */
    fun gravidade(y: Float, z: Float) {
        gy = y
        gz = z
    }

    /** Recebe ωx e a rotação total |ω| (rad/s); devolve o gesto quando a sequência fecha. */
    fun ler(agoraMs: Long, omegaX: Float, omegaTotal: Float = abs(omegaX)): Gesto? {
        if (!armado) {
            if (abs(omegaX) > maxAntesDeArmar) maxAntesDeArmar = abs(omegaX)
            if (omegaTotal < PARADO_MAX) {
                if (paradoDesdeMs < 0) paradoDesdeMs = agoraMs
                if (agoraMs - paradoDesdeMs >= paradoMs) armado = true
            } else {
                paradoDesdeMs = -1
            }
            return null
        }
        val mag = abs(omegaX)
        var cur = atual
        if (mag >= PICO_MIN) {
            ultimoMovMs = agoraMs
            val positivo = omegaX > 0
            // fora e dentro sem pausa no meio: o sinal troca e isso fecha o pico anterior
            if (cur != null && cur.positivo != positivo) {
                cur.gzFim = gz
                picos += cur
                cur = null
            }
            if (cur == null) {
                atual = Pico(agoraMs, agoraMs, mag, gy, gz, gz, positivo)
            } else {
                cur.fimMs = agoraMs
                cur.gzFim = gz
                if (mag > cur.max) cur.max = mag
            }
            return null
        }
        if (cur != null) {
            cur.gzFim = gz
            picos += cur
            atual = null
        }
        if (picos.isEmpty() || agoraMs - ultimoMovMs < QUIETO_MS) return null
        val sinal = sinalDaSequencia()
        val descrito = descrever(sinal)
        val fortes = fortes()
        par = foraDentro(fortes, sinal)?.let { (f, d) -> Picos(f.max, d.max) }
        val gesto = classificar(fortes, sinal)
        if (sinal != 0) sinalTela = sinal
        resumo = "$descrito -> ${gesto ?: "nenhum"}"
        picos.clear()
        return gesto
    }

    private fun sinalDaSequencia(): Int {
        val y = picos.first().gyIni
        return when {
            y >= POSTURA_MIN -> 1
            y <= -POSTURA_MIN -> -1
            else -> sinalTela
        }
    }

    private fun Pico.dentro(sinal: Int): Boolean = if (sinal != 0) positivo == (sinal > 0) else gzFim > gzIni

    /** Picos fortes da sequência, sem os rebotes; [manter] diz, pelo índice, quem fica mesmo parecendo rebote. */
    private fun fortes(manter: (Int) -> Boolean = { false }): List<Pico> {
        val ficam = ArrayList<Pico>(picos.size)
        for ((i, p) in picos.withIndex()) {
            val ant = ficam.lastOrNull()
            val rebote = ant != null && p.iniMs - ant.fimMs <= REBOTE_MS && p.max < ant.max * REBOTE_RAZAO
            if (!rebote || manter(i)) ficam += p
        }
        return ficam.filter { it.max >= FORTE_MIN }
    }

    /**
     * Quantas sacudidas fora→dentro a sequência tem: dentros acima do [dentroMin],
     * cada um com o fora acima do [foraMin] logo antes; 0 se algum desses dentros
     * ficar sem o fora. Repetindo, a volta do primeiro dentro já é o fora da
     * seguinte e pode parecer rebote; seguida de um dentro forte, ela conta.
     */
    private fun contagem(sinal: Int): Int {
        val ficam = fortes { i ->
            val prox = picos.getOrNull(i + 1)
            !picos[i].dentro(sinal) && prox != null && prox.dentro(sinal) && prox.max >= dentroMin
        }
        val dentros = ficam.indices.filter { ficam[it].dentro(sinal) && ficam[it].max >= dentroMin }
        val pareados = dentros.all { i -> ficam.getOrNull(i - 1)?.let { !it.dentro(sinal) && it.max >= foraMin } == true }
        return if (pareados) dentros.size else 0
    }

    /** O dentro mais forte e o pico forte logo antes dele, se esse for para fora. */
    private fun foraDentro(fortes: List<Pico>, sinal: Int): Pair<Pico, Pico>? {
        val iDentro = fortes.indices.filter { fortes[it].dentro(sinal) }.maxByOrNull { fortes[it].max } ?: return null
        val fora = fortes.getOrNull(iDentro - 1)?.takeIf { !it.dentro(sinal) } ?: return null
        return fora to fortes[iDentro]
    }

    private fun classificar(fortes: List<Pico>, sinal: Int): Gesto? {
        // duas são da Hina; três ou mais são repetição e não dão nada
        val n = contagem(sinal)
        if (n == 2) return Gesto.DUAS
        if (n > 2) return null
        val (fora, dentro) = foraDentro(fortes, sinal) ?: return null
        val repetiu = fortes.count { it.dentro(sinal) && it.max >= dentroMin } > 1
        return if (!repetiu && fora.max >= foraMin && dentro.max >= dentroMin) Gesto.UMA else null
    }

    /** O resumo da última sequência, uma vez só, para o log. */
    fun tirarResumo(): String? = resumo.also { resumo = null }

    /** O par fora→dentro da última sequência, uma vez só, para a calibração. */
    fun tirarPar(): Picos? = par.also { par = null }

    /** Recomeça a sequência e a parada que arma; o sentido aprendido da postura fica. */
    fun zerar() {
        picos.clear()
        atual = null
        ultimoMovMs = -1
        paradoDesdeMs = -1
        armado = false
        maxAntesDeArmar = 0f
        resumo = null
        par = null
    }

    private fun descrever(sinal: Int): String =
        "gy=%.1f: ".format(picos.first().gyIni) + picos.joinToString(" | ") {
            "%s max=%.1f dur=%dms".format(if (it.dentro(sinal)) "in" else "out", it.max, it.fimMs - it.iniMs)
        }

    companion object {
        // os valores do HinaWatch (calibrados pelo Davi nos logs de 03/10, issue #10)
        const val PICO_MIN = 1.5f
        const val DENTRO_MIN = 8f
        const val FORA_MIN = 3.5f
        const val FORTE_MIN = 2.5f
        const val QUIETO_MS = 450L
        /** parado de verdade: bem abaixo do limiar de pico, nos três eixos */
        const val PARADO_MAX = 0.5f
        const val PARADO_ABRIR_MS = 300L
        /** rebotes medidos: 16 a 18% do pico anterior, logo em seguida a ele */
        const val REBOTE_RAZAO = 0.35f
        const val REBOTE_MS = 150L
        /** tela inclinada uns 10° ou mais em torno do antebraço */
        const val POSTURA_MIN = 1.7f
    }
}
