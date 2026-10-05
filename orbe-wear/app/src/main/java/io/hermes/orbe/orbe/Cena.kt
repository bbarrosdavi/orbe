package io.hermes.orbe.orbe

import io.hermes.orbe.orbe.Estado.IDLE
import io.hermes.orbe.orbe.Estado.LISTENING
import io.hermes.orbe.orbe.Estado.SPEAKING
import io.hermes.orbe.orbe.Estado.THINKING
import io.hermes.orbe.orbe.Estado.TOOLS
import kotlin.math.min
import kotlin.math.pow

/** Uma cena viva: avança dt e devolve a arte com os uniforms do quadro. */
interface Cena {
    fun passo(dt: Double, w: Double, h: Double): Arte

    /** Parada à espera (sem sessão, sem toque): o Motor desenha menos quadros por segundo. */
    val calma: Boolean get() = false
}

/** O que a tela precisa saber do orbe além do desenho. */
data class Retrato(
    val visivel: Boolean = false,
    val estado: Int = LISTENING,
    val travado: Boolean = false,
    val linhas: List<String> = emptyList(),
)

/** Onde a figura fica na tela do relógio: o quadrado dela, em px lógicos. */
class Celula(val cx: Double, val cy: Double, val lado: Double) {
    companion object {
        /**
         * Sem texto, a célula é a tela inteira (a figura cabe no disco do
         * mostrador redondo); com o raciocínio na tela, sobe e encolhe para as
         * linhas caberem embaixo, como no "abaixo" do desktop.
         */
        fun para(w: Double, h: Double, tamanho: Double, comTexto: Boolean): Celula {
            val d = min(w, h)
            return if (comTexto) Celula(w / 2, h * 0.36, d * 0.62 * min(tamanho, 1.0))
            else Celula(w / 2, h / 2, d * tamanho)
        }
    }
}

/**
 * O orbe de voz: o OrbeConteudo.qml do orbe-qt no relógio. Mesmo protocolo do
 * daemon (show, state, level, mic, line, hold, hide, clear), mesma suavização
 * dos níveis e mesmos fatores por dt.
 *
 * Uma diferença de propósito: no desktop o orbe some quando a sessão fecha; no
 * relógio o app está na tela, então sem sessão ele fica parado ("idle"), mais
 * apagado, esperando o toque.
 */
/** [entrar]: o orbe desdobra ao nascer (o do app); a vizinha do carrossel já nasce aberta. */
class OrbeCena(entrar: Boolean = true) : Cena {
    // ── aparência; quem muda é a tela, quem lê é a thread do desenho ──
    @Volatile var skin = Skin.OFANIM
    @Volatile var glitch = true
    @Volatile var varredura = true                                   // as linhas de TV
    @Volatile var tamanho = 1.0
    @Volatile var redonda = true
    @Volatile var comTexto = false
    @Volatile var corTema = floatArrayOf(0.722f, 0.792f, 0.796f)     // #b8cacb
    @Volatile var accent = floatArrayOf(0f, 0.529f, 0.988f)          // #0087fc
    @Volatile var corFundo = floatArrayOf(0f, 0f, 0f)
    @Volatile var toque = false                                       // dedo no orbe agora
    @Volatile var olharX = Double.NaN                                 // para onde os olhos olham
    @Volatile var olharY = Double.NaN
    /** o orbe em tela não é o que abriu a sessão: ela segue, mas ele fica parado */
    @Volatile var alheia = false

    /** Chamado quando muda o que a tela mostra em volta do orbe (de qualquer thread). */
    @Volatile var aoMudar: ((Retrato) -> Unit)? = null

    // ── estado do protocolo (sob o cadeado) ──
    private var estado = LISTENING
    private var visivel = false
    private var travado = false
    private var linhas = emptyList<String>()
    private var nivel = 0.0
    private var tom = 0.5
    private var mic = 0.0
    private var recomecarAnel = false
    private var retrato = Retrato()

    // ── suavizados (só a thread do desenho) ──
    private val mix = DoubleArray(5).also { it[IDLE] = 1.0 }
    private var nivelS = 0.0
    private var tomS = 0.5
    private var micS = 0.0
    private var toqueS = 0.0              // sobe rápido, desce devagar
    private var sono = 1.0                // 1 sem sessão, 0 com ela aberta
    private var entrando = entrar         // o orbe desdobra ao abrir o app
    private var faseT = 0.0
    private var cel: DoubleArray? = null  // célula animada: cx, cy, lado
    private var accentPosto: FloatArray? = null

    private val figura = Figura(Skin.OFANIM).also { it.peso = 1.4 }   // o traço do menu some numa área pequena
    private val anel = Anel()

    private val toqueCresce = 0.12
    private val ansi = Regex("""\[\?[0-9;]*[A-Za-z]""")
    private val espacos = Regex("""\s+""")

    val retratoAtual: Retrato get() = synchronized(this) { retrato }

    @Volatile private var dormindo = true
    override val calma: Boolean get() = dormindo && !toque

    // ── comandos (mesma semântica do OrbWin) ──

    private fun mostrar(e: Int) {
        linhas = emptyList()
        if (e >= 0) estado = e
        if (!visivel) recomecarAnel = true
        visivel = true
    }

    private fun definirEstado(e: Int) {
        if (e >= 0) estado = e
        if (!visivel) mostrar(e)
    }

    private fun audio(lv: Double, tn: Double?) {
        nivel = lim01(lv)
        if (tn != null && !tn.isNaN()) tom = lim01(tn)
        if (estado != SPEAKING && nivel > 0.08) estado = SPEAKING
    }

    private fun esconder() {
        linhas = emptyList()
        visivel = false
    }

    private fun empurrarLinha(texto: String) {
        // tira glifos sem cobertura na fonte (emoji, nerd fonts, símbolos)
        val limpo = StringBuilder()
        for (c in texto) if (c.code in 0x20 until 0x2400) limpo.append(c)
        val s = ansi.replace(limpo, "").split(espacos).filter { it.isNotEmpty() }.joinToString(" ")
        if (s.isEmpty()) return
        linhas = (linhas + s.take(220)).takeLast(6)
    }

    /** Uma linha do protocolo do daemon (a ponte repassa as mesmas do socket do orbe). */
    fun comando(bruta: String) {
        val linha = bruta.trim()
        if (linha.isEmpty()) return
        val i = linha.indexOf(' ')
        val op = if (i < 0) linha else linha.substring(0, i)
        val arg = if (i < 0) "" else linha.substring(i + 1).trim()
        val novo: Retrato
        synchronized(this) {
            when (op) {
                "clear" -> linhas = emptyList()
                "show" -> mostrar(Estado.de(arg.ifEmpty { "listening" }))
                "state" -> definirEstado(Estado.de(arg.ifEmpty { "listening" }))
                "level" -> {
                    val v = arg.split(espacos)
                    val lv = v[0].toDoubleOrNull()
                    if (lv != null && !lv.isNaN()) audio(lv, v.getOrNull(1)?.toDoubleOrNull())
                }
                "mic" -> {
                    val m = arg.split(espacos)[0].toDoubleOrNull()
                    if (m != null && !m.isNaN()) mic = lim01(m)
                }
                "line" -> {
                    empurrarLinha(arg)
                    if (estado != TOOLS && estado != THINKING) definirEstado(TOOLS)
                }
                "hold" -> travado = arg !in arrayOf("", "0", "false", "off")
                "hide" -> esconder()
            }
            novo = Retrato(visivel, estado, travado, linhas)
            if (novo == retrato) return
            retrato = novo
        }
        aoMudar?.invoke(novo)
    }

    // ── um quadro ──

    private fun easeOutBack(p: Double): Double {
        val c = 1.70158
        val q = p - 1
        return 1 + (c + 1) * q * q * q + c * q * q
    }

    // fator por tique do original (30 Hz) convertido para este dt
    private fun fator(a: Double, k: Double) = 1 - (1 - a).pow(k)

    override fun passo(dt: Double, w: Double, h: Double): Arte {
        // o teto de 50 ms do desktop; à espera, o Motor cai para 20 quadros por segundo
        val d = dt.coerceIn(0.0, if (dormindo) 0.08 else 0.05)
        val k = d / 0.033
        val e: Int
        val nv: Double
        val tn: Double
        val mc: Double
        val desperta: Boolean
        val fora = alheia
        synchronized(this) {
            e = if (visivel && !fora) estado else IDLE
            nv = if (fora) 0.0 else nivel
            tn = tom
            mc = if (fora) 0.0 else mic
            desperta = visivel && !fora
            if (recomecarAnel) {
                recomecarAnel = false
                anel.reiniciarQuadro()
            }
            if (estado != SPEAKING) nivel *= 0.90.pow(k)
            mic *= 0.90.pow(k)
        }
        if (entrando) {
            faseT += d
            if (faseT >= 0.35) entrando = false
        }

        for (i in mix.indices) mix[i] += ((if (i == e) 1.0 else 0.0) - mix[i]) * fator(0.16, k)
        nivelS += (nv - nivelS) * fator(if (nv > nivelS) 0.55 else 0.16, k)
        val alvoToque = if (toque) 1.0 else 0.0
        toqueS += (alvoToque - toqueS) * fator(if (alvoToque > toqueS) 0.45 else 0.20, k)
        tomS += (tn - tomS) * fator(0.25, k)
        micS += (mc - micS) * fator(if (mc > micS) 0.50 else 0.20, k)
        sono += ((if (desperta) 0.0 else 1.0) - sono) * fator(0.10, k)
        dormindo = !desperta && sono > 0.97 && !entrando

        var sc = 1.0
        var a = 1.0
        var desp = 1.0
        if (entrando) {
            val p = min(1.0, faseT / 0.35)
            sc = 0.45 + 0.55 * easeOutBack(p)
            a = min(1.0, p * 2.2)
            desp = p
        }
        val envEsc = sc * (1 - 0.08 * sono) * (1 + toqueCresce * toqueS)
        val envAlfa = a * (1 - 0.38 * sono)

        // a célula anda sem salto quando o texto entra ou sai
        val alvo = Celula.para(w, h, tamanho, comTexto)
        val c = cel ?: doubleArrayOf(alvo.cx, alvo.cy, alvo.lado).also { cel = it }
        val f = fator(0.22, k)
        c[0] += (alvo.cx - c[0]) * f
        c[1] += (alvo.cy - c[1]) * f
        c[2] += (alvo.lado - c[2]) * f

        val sk = skin
        val arte: Arte
        if (sk.avatar) {
            figura.skin = sk
            figura.glitch = glitch
            figura.varredura = varredura
            corTema.copyInto(figura.cor)
            corFundo.copyInto(figura.corFundo)
            // no mostrador redondo a figura cabe no disco, não só no quadrado
            figura.disco = if (redonda) c[2] / 2 - 2 else -1.0
            figura.zoom = envEsc
            figura.alfa = envAlfa
            figura.olharX = olharX
            figura.olharY = olharY
            mix.copyInto(figura.mix)
            figura.voz = nivelS
            figura.mic = micS
            figura.desperto = desp
            arte = figura
        } else {
            val ac = accent
            if (ac !== accentPosto) {
                accentPosto = ac
                anel.accent(ac[0], ac[1], ac[2])
            }
            mix.copyInto(anel.mix)
            anel.estado = e
            anel.nivel = nv
            anel.nivelS = nivelS
            anel.tomS = tomS
            anel.mic = mc
            anel.micS = micS
            anel.envEsc = envEsc
            anel.envAlfa = envAlfa
            anel.glitch = glitch
            corFundo.copyInto(anel.corFundo)
            arte = anel
        }
        arte.avancar(d)
        arte.montar(w, h, c[0], c[1], c[2], c[2])
        return arte
    }
}

/**
 * A figura de uma skin em miniatura (Miniatura.qml): parada nos avatares, no
 * estado de escuta e sem voz no anel de energia.
 */
class MiniCena(skinInicial: Skin) : Cena {
    @Volatile var skin = skinInicial
    @Volatile var glitch = true
    @Volatile var varredura = true                                   // as linhas de TV
    @Volatile var peso = 1.2
    @Volatile var raio = -1.0                                          // -1 = o maior que cabe
    @Volatile var cor = floatArrayOf(0.722f, 0.792f, 0.796f)
    @Volatile var accent = floatArrayOf(0f, 0.529f, 0.988f)
    @Volatile var corFundo = floatArrayOf(0.07f, 0.078f, 0.078f)

    private val figura = Figura(skinInicial)
    private var anel: Anel? = null
    private var accentPosto: FloatArray? = null

    override fun passo(dt: Double, w: Double, h: Double): Arte {
        // no rodízio do menu, cada miniatura sai a cada dois ou três quadros
        val d = dt.coerceIn(0.0, 0.12)
        val sk = skin
        if (sk.avatar) {
            figura.skin = sk
            figura.glitch = glitch
            figura.varredura = varredura
            figura.peso = peso
            figura.raioFixo = raio
            cor.copyInto(figura.cor)
            corFundo.copyInto(figura.corFundo)
            figura.avancar(d)
            figura.montar(w, h, w / 2, h / 2, w, h)
            return figura
        }
        val a = anel ?: Anel().also { anel = it }
        val ac = accent
        if (ac !== accentPosto) {
            accentPosto = ac
            a.accent(ac[0], ac[1], ac[2])
        }
        a.glitch = glitch
        corFundo.copyInto(a.corFundo)
        a.avancar(d)
        val lado = min(w, h)
        a.montar(w, h, w / 2, h / 2, lado, lado)
        return a
    }
}
