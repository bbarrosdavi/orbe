package io.hermes.orbe.orbe

import io.hermes.orbe.orbe.Estado.LISTENING
import io.hermes.orbe.orbe.Estado.SPEAKING
import io.hermes.orbe.orbe.Estado.THINKING
import io.hermes.orbe.orbe.Estado.TOOLS
import kotlin.math.abs
import kotlin.math.cos
import kotlin.math.exp
import kotlin.math.floor
import kotlin.math.max
import kotlin.math.min
import kotlin.math.pow
import kotlin.math.sin
import kotlin.random.Random

/**
 * Anel de energia: a física do orbe-qt/comum/Anel.qml, portada linha a linha.
 * Molas das línguas, gotas, quique global, fases dos lóbulos, rajadas de glitch
 * do pensamento e a paleta por estado; o desenho é do anel.frag (quadros do
 * rotoscope num atlas, warp polar, línguas e gotas) e a cor, do pos.frag.
 */
class Anel : Arte {
    override val skin = Skin.ANEL
    override val fx = Uniformes()
    override val pos = Uniformes()
    override val recorte = DoubleArray(4)

    val mix = DoubleArray(5).also { it[LISTENING] = 1.0 }
    var estado = LISTENING
    var nivel = 0.0                      // nível cru do TTS (para detectar sílaba)
    var nivelS = 0.0                     // suavizado
    var tomS = 0.5
    var mic = 0.0
    var micS = 0.0
    var envEsc = 1.0                     // escala da entrada/saída e do toque
    var envAlfa = 1.0
    var glitch = true
    val corFundo = floatArrayOf(0.07f, 0.078f, 0.078f)

    private val artBox = 120.0
    private val artEdge = 100.0
    private val rLim = 70.0
    private val nW = 36
    private val nLingua = 10
    private val nGota = 7
    private val nQuadros = 62

    // ── paleta: accent do tema derivado por HSV, como no _system_palette ──
    private val tintBase = DoubleArray(3)
    private val tintThink = DoubleArray(3)
    private val tintTools = DoubleArray(3)
    private val tintDeep = DoubleArray(3)
    private val tintHigh = DoubleArray(3)
    /** cor do anel neste quadro (o ponto da sessão travada usa a mesma) */
    val corAnel = DoubleArray(3)

    init {
        accent(0f, 0.529f, 0.988f)       // #0087fc, o padrão do orbe.qml
    }

    fun accent(r: Float, g: Float, b: Float) {
        val mx = max(r, max(g, b)).toDouble()
        val mn = min(r, min(g, b)).toDouble()
        val d = mx - mn
        val sat = if (mx <= 0) 0.0 else d / mx
        // sem matiz (cinza), o anel fica no azul de sempre
        val hBase = if (d <= 1e-6) 0.58 else when (mx) {
            r.toDouble() -> (((g - b) / d) % 6.0) / 6.0
            g.toDouble() -> ((b - r) / d + 2.0) / 6.0
            else -> ((r - g) / d + 4.0) / 6.0
        }
        val sBase = max(sat, 0.60)
        hsv(hBase, sBase, 1.0, tintBase)
        hsv(hBase + 0.078, sBase, 1.0, tintThink)
        hsv(hBase - 0.078, sBase, 0.92, tintTools)
        hsv(hBase, sBase + 0.15, 0.80, tintDeep)
        hsv(hBase, sBase * 0.45, 1.0, tintHigh)
        tintBase.copyInto(corAnel)
    }

    private fun hsv(h0: Double, s0: Double, v0: Double, sai: DoubleArray) {
        val h = ((h0 % 1) + 1) % 1
        val s = min(1.0, max(0.0, s0))
        val v = min(1.0, v0)
        val i = floor(h * 6).toInt()
        val f = h * 6 - i
        val p = v * (1 - s)
        val q = v * (1 - f * s)
        val t = v * (1 - (1 - f) * s)
        when (i % 6) {
            0 -> { sai[0] = v; sai[1] = t; sai[2] = p }
            1 -> { sai[0] = q; sai[1] = v; sai[2] = p }
            2 -> { sai[0] = p; sai[1] = v; sai[2] = t }
            3 -> { sai[0] = p; sai[1] = q; sai[2] = v }
            4 -> { sai[0] = t; sai[1] = p; sai[2] = v }
            else -> { sai[0] = v; sai[1] = p; sai[2] = q }
        }
    }

    // ── estado da física ──
    private var t = 0.0
    private var rot = 0.0
    private var framePos = 0.0
    private var ph2 = 0.9
    private var ph3 = 2.1
    private var ampL = 0.5
    private val tAng = DoubleArray(nLingua) { it * TAU / nLingua }
    private val tDrift = DoubleArray(nLingua) { (((it * 37) % 100) / 100.0 - 0.5) * 0.30 }
    private val tH = DoubleArray(nLingua)
    private val tV = DoubleArray(nLingua)
    private val tW = DoubleArray(nLingua) { 0.26 }
    private var tNext = 0
    private var glAte = 0.0
    private var glProx = 0.6
    private var glLo = 0
    private var glSpan = 0
    private var glAmp = 0.0
    private var glJump = 0
    private var glShear = 0.0
    private var glDx = 0.0
    private val glBands = ArrayList<DoubleArray>()   // (y0, altura, deslocamento)
    private val dE = DoubleArray(nGota)
    private val dAng = DoubleArray(nGota)
    private val dDist = DoubleArray(nGota)
    private val dSpd = DoubleArray(nGota)
    private var dNext = 0
    private var rOff = 0.0
    private var rVel = 0.0
    private var rawAnt = 0.0

    // mistura do quadro: omega, caos, ampL, ganho da língua, vel. do loop, tinta (3), brilho, pulso
    private val pb = DoubleArray(10)
    private val q = DoubleArray(10)
    private var temPb = false

    /** O loop do rotoscope recomeça quando o orbe aparece. */
    fun reiniciarQuadro() {
        framePos = 0.0
    }

    private fun wrap(a: Double) = ((a + Math.PI) % TAU + TAU) % TAU - Math.PI
    private fun lim(v: Double, a: Double, b: Double) = if (v < a) a else if (v > b) b else v

    private fun params(e: Int) {
        val tinta: DoubleArray
        when (e) {
            THINKING -> {
                val osc = 0.5 + 0.5 * sin(t * 3.1)
                val resp = 0.5 + 0.5 * sin(t * 2.2)
                q[0] = 0.9 * sin(t * 0.45); q[1] = 1.5 + 1.3 * resp; q[2] = 1.6 + 3.6 * resp; q[3] = 0.40; q[4] = 1.8
                tinta = tintThink
                q[8] = 0.82 + 0.22 * osc; q[9] = 1.0 + 0.03 * sin(t * 2.6)
            }
            TOOLS -> {
                val pp = abs(sin(t * 3.4))
                q[0] = -0.35; q[1] = 1.0; q[2] = 2.0; q[3] = 0.55; q[4] = 1.35
                tinta = tintTools
                q[8] = 0.88 + 0.18 * pp; q[9] = 1.0 + 0.025 * pp
            }
            SPEAKING -> {
                val lv = nivelS
                val tn = tomS
                q[0] = 0.15 + 1.6 * lv; q[1] = 0.9 + 3.2 * lv; q[2] = 1.5 + 6.0 * lv * (1.0 - 0.55 * tn)
                q[3] = 0.5 + 1.7 * lv; q[4] = 0.9 + 1.1 * lv
                q[5] = tintDeep[0] + (tintHigh[0] - tintDeep[0]) * tn
                q[6] = tintDeep[1] + (tintHigh[1] - tintDeep[1]) * tn
                q[7] = tintDeep[2] + (tintHigh[2] - tintDeep[2]) * tn
                q[8] = 0.80 + 0.45 * lv; q[9] = 1.0 + 0.08 * lv
                return
            }
            else -> {
                // listening: a expressividade é o único jeito de saber que o mic entra
                val m = micS
                val idle = 0.5 + 0.5 * sin(t * 1.25)
                q[0] = 0.10 + 0.9 * m; q[1] = 0.45 + 2.4 * m; q[2] = 0.8 + 1.1 * idle + 5.5 * m
                q[3] = 0.35 + 1.4 * m; q[4] = 0.75 + 1.1 * m
                tinta = tintBase
                q[8] = 0.82 + 0.55 * m; q[9] = 1.0 + 0.02 * sin(t * 1.6) + 0.10 * m
            }
        }
        q[5] = tinta[0]; q[6] = tinta[1]; q[7] = tinta[2]
    }

    private fun blend() {
        var tot = 0.0
        for (w in mix) tot += w
        if (tot == 0.0) tot = 1.0
        pb.fill(0.0)
        for (e in mix.indices) {
            var w = mix[e]
            if (w < 0.001) continue
            w /= tot
            params(e)
            for (i in 0 until 10) pb[i] += w * q[i]
        }
        temPb = true
    }

    private fun impulso(forca: Double, tom: Double) {
        val j = tNext % nLingua
        tNext++
        tV[j] += forca * (240 + 260 * tom)
        tW[j] = 0.38 - 0.22 * tom
        if (forca > 0.08) {
            val d = dNext % nGota
            dNext++
            dE[d] = 1.0
            dAng[d] = tAng[j] + sin(t * 13.7 + j) * 0.25
            dDist[d] = 46.0
            dSpd[d] = 25 + 80 * forca
        }
    }

    private fun campo(th: Double): Double {
        var f = rOff + ampL * (0.52 * sin(2 * th + ph2) + 0.30 * sin(3 * th + ph3) + 0.18 * sin(5 * th - 1.7 * ph2))
        for (j in 0 until nLingua) {
            val h = tH[j]
            if (h > 0.3) {
                val w = max(tW[j] * 2.2, 0.60)
                val dth = wrap(th - tAng[j])
                if (abs(dth) < 3 * w) f += 0.45 * h * exp(-(dth / w).pow(2))
            }
        }
        return f
    }

    override fun avancar(dt: Double) {
        val k = dt / 0.033                       // tiques do original neste quadro
        t += dt
        blend()
        val omega = pb[0]
        val caos = pb[1]
        val tgain = pb[3]
        val fsp = pb[4]
        ampL = pb[2]

        val on = max(0.0, nivel - rawAnt)
        rawAnt = nivel
        if (on > 0.03) impulso(on * min(1.0, tgain), tomS)
        if (estado == LISTENING && mic > micS + 0.10) impulso(0.35 * mic, 0.45)

        ph2 += 0.9 * (0.35 + 0.65 * caos) * dt
        ph3 += -1.3 * (0.35 + 0.65 * caos) * dt
        rot = (rot + omega * dt) % TAU
        framePos = (framePos + fsp * k) % nQuadros

        // mola do raio global: voz no speaking, onda lenta no thinking, mic no listening
        val alvo = 8 * nivelS + 2.6 * mix[THINKING] * sin(t * 1.9) + 7 * mix[LISTENING] * micS
        val forca = -40 * (rOff - alvo) - 7 * rVel
        rVel += forca * dt
        rOff += rVel * dt

        for (j in 0 until nLingua) {
            tAng[j] = (tAng[j] + (omega * 0.6 + tDrift[j]) * dt) % TAU
            val f = -55 * tH[j] - 6.5 * tV[j] +
                nivelS * tgain * 420 * (0.35 + 0.65 * (0.5 + 0.5 * sin(t * 3 + j * 2.1)))
            tV[j] += f * dt
            tH[j] = lim(tH[j] + tV[j] * dt, -3.0, 16.0)
        }

        // glitch do pensamento: rajadas curtas e irregulares, mais densas no fundo do raciocínio
        val wt = mix[THINKING]
        if (wt > 0.25 && glitch) {
            if (t >= glProx) {
                glAte = t + uni(0.05, 0.20)
                glProx = glAte + uni(0.06, 0.75) / (0.4 + wt)
                glLo = sorteia(nW)
                glSpan = 2 + sorteia(max(3, nW / 3) - 1)
                glAmp = uni(5.0, 15.0) * (if (Random.nextDouble() < 0.5) -1 else 1)
                glShear = uni(-0.09, 0.09)
                glJump = if (Random.nextDouble() < 0.34) 1 + sorteia(nQuadros - 1) else 0
                glDx = if (Random.nextDouble() < 0.75) uni(1.6, 5.5) else 0.0
                glBands.clear()
                repeat(sorteia(5)) {
                    glBands.add(doubleArrayOf(uni(-46.0, 40.0), uni(2.0, 9.0), uni(5.0, 20.0) * (if (Random.nextDouble() < 0.5) -1 else 1)))
                }
            }
        } else {
            glAte = 0.0
            glProx = t + 0.4
        }

        for (d in 0 until nGota) {
            if (dE[d] > 0.04) {
                dDist[d] = min(rLim, dDist[d] + dSpd[d] * dt)
                dSpd[d] *= 0.97.pow(k)
                dE[d] *= 0.93.pow(k)
            }
        }
    }

    private val campos = DoubleArray(nW)

    override fun montar(w: Double, h: Double, cx: Double, cy: Double, cw: Double, ch: Double) {
        if (!temPb) return
        recorte[0] = cx; recorte[1] = cy; recorte[2] = cw / 2; recorte[3] = ch / 2
        // a célula de 148 px do orbe é a referência de tamanho (Miniatura.qml)
        val esc = min(cw, ch) / 148.0
        val bright = pb[8]
        val pulse = pb[9]
        val lift = 0.25 * max(0.0, bright - 1)
        corAnel[0] = min(1.0, pb[5] * bright + lift)
        corAnel[1] = min(1.0, pb[6] * bright + lift)
        corAnel[2] = min(1.0, pb[7] * bright)
        val glowk = envAlfa * max(0.0, min(1.0, 0.55 + (bright - 0.80)))
        val scb = (artBox / 256) * envEsc * pulse * esc

        val rajada = t < glAte
        val glk = if (rajada) mix[THINKING] else 0.0
        var idx = floor(framePos).toInt() % nQuadros
        if (glk > 0 && glJump != 0) idx = (idx + glJump) % nQuadros

        val dth = TAU / nW
        var fmax = 0.0
        for (i in 0 until nW) campos[i] = campo((i + 0.5) * dth)
        if (glk > 0) {
            for (k in 0 until glSpan) {
                val ii = (glLo + k) % nW
                val borda = k == 0 || k == glSpan - 1
                campos[ii] += glAmp * glk * (if (borda) 0.5 else 1.0)
            }
        }
        for (i in 0 until nW) fmax = max(fmax, abs(campos[i]))
        for (i in 0 until 9) {
            fx.v4("campo$i", lim(1 + campos[4 * i] / 50, 0.84, 1.28), lim(1 + campos[4 * i + 1] / 50, 0.84, 1.28),
                lim(1 + campos[4 * i + 2] / 50, 0.84, 1.28), lim(1 + campos[4 * i + 3] / 50, 0.84, 1.28))
        }

        fx.v2("tam", w, h)
        fx.v2("centro", cx, cy)
        fx.v4("geo", scb, rot, idx.toDouble(), lim(1 + rOff / 50, 0.84, 1.28))
        fx.v4("extra", glowk, if (fmax < 0.8) 1.0 else 0.0, esc, rLim * esc)
        fx.v4("gl", glLo.toDouble(), if (glk > 0 && glShear != 0.0) glSpan.toDouble() else 0.0, glShear * glk, 0.0)
        fx.v4("tempo", t, envAlfa, 0.0, 0.0)

        for (j in 0 until nLingua) {
            val hj = tH[j]
            if (hj < 1.2) {
                fx.zero4("lingua$j")
                continue
            }
            val a = tAng[j]
            val sa = lim(1 + campo(a) / 50, 0.84, 1.28)
            val rb = artEdge * scb * sa * 0.94
            fx.v4("lingua$j", a, rb, min(rLim * esc, rb + hj * 2 * esc), tW[j])
        }
        for (d in 0 until nGota) {
            val e = dE[d]
            if (e <= 0.04) fx.zero4("gota$d")
            else fx.v4("gota$d", cos(dAng[d]) * dDist[d] * esc, sin(dAng[d]) * dDist[d] * esc, e, 0.0)
        }

        // segundo passe
        pos.v2("tam", w, h)
        pos.v2("centro", cx, cy)
        pos.v4("cor", corAnel[0], corAnel[1], corAnel[2], envAlfa)
        // ciano e magenta fixos: só leem como canal separado se forem quase complementares
        pos.v4("corA", 0.00, 0.95, 0.95, 0.60)
        pos.v4("corB", 1.00, 0.08, 0.55, 0.60)
        pos.v4("glt", glDx, 0.0, 0.0, glk)
        pos.zero4("geo2")
        pos.zero4("sombra")
        pos.v4("corSombra", corFundo[0].toDouble(), corFundo[1].toDouble(), corFundo[2].toDouble(), 1.0)
        pos.v4("modo", 1.0, esc, 0.0, 0.0)
        for (b in 0 until 4) {
            val bd = glBands.getOrNull(b)
            if (bd != null && glk > 0) pos.v4("banda$b", bd[0], bd[1], bd[2], 1.0) else pos.zero4("banda$b")
        }
    }
}
