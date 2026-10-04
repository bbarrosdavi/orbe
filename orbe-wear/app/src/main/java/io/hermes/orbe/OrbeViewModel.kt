package io.hermes.orbe

import android.app.Application
import android.os.Build
import android.os.VibrationEffect
import android.os.Vibrator
import androidx.lifecycle.AndroidViewModel
import androidx.lifecycle.viewModelScope
import io.hermes.orbe.dados.Ajustes
import io.hermes.orbe.dados.AltoFalante
import io.hermes.orbe.dados.Cofre
import io.hermes.orbe.dados.Ligacao
import io.hermes.orbe.dados.Microfone
import io.hermes.orbe.dados.Ola
import io.hermes.orbe.dados.Ponte
import io.hermes.orbe.dados.Protocolo
import io.hermes.orbe.orbe.Estado
import io.hermes.orbe.orbe.OrbeCena
import io.hermes.orbe.orbe.Retrato
import io.hermes.orbe.orbe.Skin
import io.hermes.orbe.ui.Tema
import io.hermes.orbe.ui.rgb
import kotlin.math.PI
import kotlin.math.pow
import kotlin.math.sin
import kotlin.random.Random
import kotlinx.coroutines.Job
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.SharingStarted
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.flow.map
import kotlinx.coroutines.flow.stateIn
import kotlinx.coroutines.isActive
import kotlinx.coroutines.launch

/** O que vale na tela: os ajustes do relógio já cruzados com a aparência do PC. */
data class Aparencia(val skin: Skin = Skin.OFANIM, val glitch: Boolean = true, val tema: Tema = Tema.Padrao)

class OrbeViewModel(app: Application) : AndroidViewModel(app) {
    val cena = OrbeCena()
    private val cofre = Cofre(app)
    private val microfone = Microfone()
    private val vibrador = app.getSystemService(Vibrator::class.java)

    private val _ajustes = MutableStateFlow(Ajustes())
    val ajustes: StateFlow<Ajustes> = _ajustes
    private val _retrato = MutableStateFlow(Retrato())
    val retrato: StateFlow<Retrato> = _retrato
    /** rótulo do estado em cartaz na pré-visualização; null fora dela */
    private val _previa = MutableStateFlow<String?>(null)
    val previa: StateFlow<String?> = _previa

    /** o relógio tem alto-falante (ou fone pareado) para tocar a resposta */
    val temSaidaDeSom = AltoFalante.temSaida(app)
    private val altoFalante = AltoFalante(
        aoNivel = { nivel, tom -> if (_previa.value == null) cena.comando("level $nivel $tom") },
        aoAcabar = { ponte.enviar("voz acabou") },
    )
    private val ponte: Ponte = Ponte(
        viewModelScope, Build.MODEL ?: "relógio", ::linhaDaPonte, ::olaDaPonte, ::configDaPonte,
        aoVoz = ::vozDaPonte, aoAudio = { if (_previa.value == null) altoFalante.tocar(it) },
        querVoz = { temSaidaDeSom && _ajustes.value.voz },
    )
    val ligacao: StateFlow<Ligacao> = ponte.estado

    val aparencia: StateFlow<Aparencia> = ajustes.map(::aparenciaDe)
        .stateIn(viewModelScope, SharingStarted.Eagerly, Aparencia())

    private var carregado = false
    private var naTela = false
    private var cicloPrevia: Job? = null
    /** mudanças feitas antes de o disco responder */
    private val pendentes = ArrayList<(Ajustes) -> Ajustes>()

    init {
        cena.aoMudar = { _retrato.value = it }
        viewModelScope.launch {
            // o que mudou antes de o disco responder (o endereço vindo pelo adb) vale por cima
            _ajustes.value = pendentes.fold(cofre.fluxo.first()) { a, f -> f(a) }
            carregado = true
            aplicar(_ajustes.value)
            if (pendentes.isNotEmpty()) cofre.gravar(_ajustes.value)
            pendentes.clear()
            if (naTela) conectar()
        }
        viewModelScope.launch {
            // sem a ponte ninguém avisa que a sessão fechou: o orbe volta a esperar
            ligacao.collect {
                if (it !is Ligacao.Conectada) {
                    altoFalante.cortar()
                    if (_previa.value == null) adormecer()
                }
            }
        }
    }

    private fun aparenciaDe(a: Ajustes): Aparencia {
        val pc = a.pc.takeIf { it.isNotEmpty() }?.let(Protocolo::ola)
        val tema = pc?.let { Tema.de(it.tema) } ?: Tema.Padrao
        return if (a.seguirPc && pc != null) Aparencia(Skin.de(pc.orbe.skin), pc.orbe.glitch, tema)
        else Aparencia(Skin.de(a.skin), a.glitch, tema)
    }

    /** Leva os ajustes para a cena (quem desenha lê dela). */
    private fun aplicar(a: Ajustes) {
        val ap = aparenciaDe(a)
        cena.skin = ap.skin
        cena.glitch = ap.glitch
        cena.tamanho = a.tamanho.toDouble()
        cena.corTema = ap.tema.accent.rgb()
        cena.accent = ap.tema.anel.rgb()
    }

    // a ponte também muda os ajustes (a aparência do PC chega na thread da rede)
    @Synchronized
    private fun mudar(f: (Ajustes) -> Ajustes) {
        if (!carregado) pendentes.add(f)
        val novo = f(_ajustes.value)
        if (novo == _ajustes.value) return
        _ajustes.value = novo
        aplicar(novo)
        if (carregado) viewModelScope.launch { cofre.gravar(novo) }
    }

    private fun adormecer() {
        cena.comando("hold 0")
        cena.comando("hide")
    }

    // ── ajustes ──

    fun servidor(v: String) {
        mudar { it.copy(servidor = v.trim()) }
        if (naTela) conectar()
    }

    fun token(v: String) {
        mudar { it.copy(token = v.trim().lowercase()) }
        if (naTela) conectar()
    }

    /** Escolher o avatar no relógio solta o orbe do PC: fica o que o relógio escolheu. */
    fun skin(s: Skin) = mudar { it.copy(seguirPc = false, skin = s.id, glitch = aparencia.value.glitch) }

    fun glitch(v: Boolean) = mudar { it.copy(seguirPc = false, glitch = v, skin = aparencia.value.skin.id) }

    fun seguirPc(v: Boolean) = mudar { it.copy(seguirPc = v) }

    fun tamanho(v: Float) = mudar { it.copy(tamanho = v.coerceIn(Ajustes.TAMANHO_MIN, Ajustes.TAMANHO_MAX)) }

    fun texto(v: Boolean) = mudar { it.copy(texto = v) }

    fun microfone(v: Boolean) = mudar { it.copy(microfone = v) }

    /** A ponte fica sabendo ao conectar se o relógio toca a resposta: mudou, reconecta. */
    fun voz(v: Boolean) {
        mudar { it.copy(voz = v) }
        if (!v) altoFalante.cortar()
        if (naTela) conectar(forcar = true)
    }

    fun vibrar(v: Boolean) = mudar { it.copy(vibrar = v) }

    fun pediuMicrofone() = mudar { it.copy(pediuMicrofone = true) }

    // ── ponte ──

    fun entrou() {
        naTela = true
        if (carregado) conectar()
    }

    fun saiu() {
        naTela = false
        toqueCancelado()
        altoFalante.cortar()
        pararPrevia()
        ponte.desligar()        // a sessão continua no PC; na volta, a ponte conta em que pé está
    }

    private fun conectar(forcar: Boolean = false) {
        val a = _ajustes.value
        ponte.ligar(a.servidor, a.token, forcar)
    }

    private fun linhaDaPonte(linha: String) {
        if (_previa.value == null) cena.comando(linha)
    }

    private fun olaDaPonte(ola: Ola, bruto: String) {
        // a ponte repete em seguida o que o orbe do PC está mostrando
        if (_previa.value == null) adormecer()
        mudar { it.copy(pc = bruto) }
    }

    private fun configDaPonte(ola: Ola, bruto: String) = mudar { it.copy(pc = bruto) }

    /** A resposta em voz: a taxa do áudio que vem, o fim dela, ou o corte. */
    private fun vozDaPonte(arg: String) {
        if (_previa.value != null) return
        val taxa = arg.toIntOrNull()
        when {
            taxa != null && taxa in 8000..48000 -> altoFalante.abrir(taxa)
            arg == "fim" -> altoFalante.fim()
            arg == "corta" -> altoFalante.cortar()
        }
    }

    /** Abre ou fecha a sessão de voz no PC (o atalho de teclado do orbe). */
    fun alternarSessao() {
        ponte.enviar("toggle")
    }

    fun travar(v: Boolean) {
        ponte.enviar(if (v) "hold" else "release")
    }

    // ── toque no orbe ──
    //
    // O daemon decide pelo tempo entre "touch down" e "touch up": curto só
    // interrompe (e deixa a sessão ouvindo), dois curtos travam, segurado é
    // segurar para falar. Aqui o dedo também pode estar só arrastando a tela
    // para o menu, então o "touch down" espera ficar claro que é toque, como o
    // orbe.qml faz quando o orbe está destravado para mover.

    private val trava = Any()
    private val preRolo = ArrayList<ByteArray>()     // a fala desde que o dedo encostou
    private var transmitindo = false
    private var segurando = false                    // "touch down" enviado, falta o "touch up"

    /** Dedo encostou: os olhos vão para ele e o microfone já começa a guardar. */
    fun toqueBaixo(x: Float, y: Float, podeGravar: Boolean) {
        if (_previa.value != null) return
        olhar(x, y)
        val lig = ligacao.value
        if (podeGravar && _ajustes.value.microfone && lig is Ligacao.Conectada && lig.microfone) {
            synchronized(trava) {
                preRolo.clear()
                transmitindo = false
            }
            microfone.iniciar(::blocoDoMicrofone)
        }
    }

    fun olhar(x: Float, y: Float) {
        cena.olharX = x.toDouble()
        cena.olharY = y.toDouble()
    }

    private fun blocoDoMicrofone(pcm: ByteArray, n: Int) {
        synchronized(trava) {
            if (transmitindo) ponte.enviarAudio(pcm, n)
            else {
                preRolo.add(pcm.copyOf(n))
                if (preRolo.size > 34) preRolo.removeAt(0)      // 1 s
            }
        }
    }

    /** Parado além do tempo de segurar: é segurar para falar. */
    fun toqueSegurou() {
        if (_previa.value != null) return
        altoFalante.cortar()            // quem fala por cima não espera a rede para o orbe calar
        segurando = true
        cena.toque = true
        tremer()
        synchronized(trava) {
            ponte.enviar("touch down")
            for (b in preRolo) ponte.enviarAudio(b, b.size)
            preRolo.clear()
            transmitindo = true
        }
    }

    /** Solto antes de andar e antes do tempo de segurar: toque curto. */
    fun toqueCurto() {
        if (_previa.value != null) {
            pararPrevia()
            return
        }
        largar()
        altoFalante.cortar()
        ponte.enviar("touch down")
        ponte.enviar("touch up")
        // o dedo já saiu: o orbe ainda cresce um instante, para o toque ser visto
        cena.toque = true
        viewModelScope.launch {
            delay(140)
            if (!segurando) cena.toque = false
        }
    }

    /** Dedo solto depois de segurar: fim da fala. */
    fun toqueSolto() = largar()

    /** Virou arrasto (ou o app saiu da tela): nada vai para o daemon além de fechar o que abriu. */
    fun toqueCancelado() = largar()

    private fun largar() {
        microfone.parar()
        synchronized(trava) {
            transmitindo = false
            preRolo.clear()
        }
        cena.toque = false
        cena.olharX = Double.NaN
        cena.olharY = Double.NaN
        if (segurando) {
            segurando = false
            ponte.enviar("touch up")
            tremer()
        }
    }

    private fun tremer() {
        if (!_ajustes.value.vibrar) return
        try {
            vibrador?.vibrate(VibrationEffect.createPredefined(VibrationEffect.EFFECT_CLICK))
        } catch (e: Exception) {
            // relógio sem motor: segue sem vibrar
        }
    }

    // ── pré-visualização: o ciclo da prévia do app do desktop, sem daemon ──

    fun alternarPrevia() {
        if (_previa.value != null) pararPrevia() else iniciarPrevia()
    }

    private fun iniciarPrevia() {
        cicloPrevia?.cancel()
        _previa.value = Estado.rotulos[Estado.IDLE]
        cicloPrevia = viewModelScope.launch {
            val fala = Fala()
            cena.comando("hold 0")
            cena.comando("show idle")
            var fase = 0
            var t = 0.0
            var nLinha = 0
            var ant = System.nanoTime()
            while (isActive) {
                delay(33)
                val agora = System.nanoTime()
                val dt = ((agora - ant) / 1e9).coerceAtMost(0.1)
                ant = agora
                t += dt
                val (estado, dur) = CICLO[fase]
                when (estado) {
                    "listening" -> cena.comando("mic ${0.03 + 0.75 * fala.passo(dt).first}")
                    "speaking" -> fala.passo(dt).let { (env, tom) -> cena.comando("level ${0.9 * env} $tom") }
                    "thinking" -> if (nLinha < LINHAS.size && t >= 0.3 + nLinha) cena.comando("line " + LINHAS[nLinha++])
                }
                if (t >= dur) {
                    fase = (fase + 1) % CICLO.size
                    t = 0.0
                    nLinha = 0
                    if (fase == 0) listOf("level 0", "mic 0", "clear").forEach(cena::comando)
                    cena.comando("state " + CICLO[fase].first)
                    _previa.value = Estado.rotulos[Estado.de(CICLO[fase].first)]
                }
            }
        }
    }

    private fun pararPrevia() {
        if (_previa.value == null) return
        cicloPrevia?.cancel()
        cicloPrevia = null
        _previa.value = null
        listOf("level 0", "mic 0").forEach(cena::comando)
        adormecer()
        // a ponte repete o estado de verdade a quem conecta
        if (naTela) conectar(forcar = true)
    }

    override fun onCleared() {
        microfone.parar()
        altoFalante.cortar()
        ponte.desligar()
    }

    /** Envelope de fala sintético: sílabas de 120 a 240 ms, pausas e um tom que anda por sílaba. */
    private class Fala {
        private var t = 0.0
        private var ini = 0.0
        private var fim = 0.0
        private var pico = 0.0
        private var tom = 0.5

        fun passo(dt: Double): Pair<Double, Double> {
            t += dt
            if (t >= fim) {
                ini = t
                val dur: Double
                if (Random.nextDouble() < 0.2) {
                    pico = 0.0
                    dur = Random.nextDouble(0.12, 0.35)
                } else {
                    pico = Random.nextDouble(0.45, 1.0)
                    dur = Random.nextDouble(0.12, 0.24)
                    tom = (tom + Random.nextDouble(-0.25, 0.25)).coerceIn(0.0, 1.0)
                }
                fim = t + dur
            }
            val u = (t - ini) / (fim - ini).coerceAtLeast(1e-3)
            return pico * sin(PI * u.coerceAtMost(1.0)).pow(0.8) to tom
        }
    }

    private companion object {
        // o ciclo e as linhas da prévia do hermes_voice_app.py
        val CICLO = listOf("idle" to 4.0, "listening" to 5.0, "thinking" to 5.0, "speaking" to 6.0)
        val LINHAS = listOf(
            "Pedido: resumir as mensagens não lidas de hoje.",
            "Começo pelas conversas com menções diretas.",
            "São três threads; a mais longa trata do prazo da entrega.",
            "Junto um resumo de uma frase por thread e respondo.",
        )
    }
}
