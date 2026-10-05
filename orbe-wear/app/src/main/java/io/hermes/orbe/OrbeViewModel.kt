package io.hermes.orbe

import android.app.Application
import android.os.Build
import android.os.VibrationEffect
import android.os.Vibrator
import androidx.lifecycle.AndroidViewModel
import androidx.lifecycle.viewModelScope
import io.hermes.orbe.dados.AgenteInfo
import io.hermes.orbe.dados.Ajustes
import io.hermes.orbe.dados.AltoFalante
import io.hermes.orbe.dados.Cofre
import io.hermes.orbe.dados.Ligacao
import io.hermes.orbe.dados.Microfone
import io.hermes.orbe.dados.Ola
import io.hermes.orbe.dados.Ponte
import io.hermes.orbe.dados.Protocolo
import io.hermes.orbe.dados.RedeLocal
import io.hermes.orbe.dados.Sincronia
import io.hermes.orbe.gesto.Picos
import io.hermes.orbe.gesto.Sacudida
import io.hermes.orbe.gesto.ServicoSacudida
import io.hermes.orbe.orbe.Ciclo
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
data class Aparencia(
    val skin: Skin = Skin.OFANIM,
    val glitch: Boolean = true,
    val tema: Tema = Tema.Padrao,
    /** a cor do ciclo do carrossel (Ciclo.cores); 0 = a do tema */
    val cor: Int = 0,
) {
    /** A cor da figura e a do anel: a do ciclo, ou as do tema. */
    fun corFigura(): FloatArray = Ciclo.cores.getOrNull(cor) ?: tema.accent.rgb()
    fun corAnel(): FloatArray = Ciclo.cores.getOrNull(cor) ?: tema.anel.rgb()
}

class OrbeViewModel(app: Application) : AndroidViewModel(app) {
    val cena = OrbeCena()
    private val cofre = Cofre(app)
    private val microfone = Microfone()
    // antes do init: o collect da ligação roda já na construção (Main.immediate) e passa por ela
    private val trava = Any()
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
        querVozPc = { _ajustes.value.vozPc },
        aoAjustes = ::ajustesDaPonte,
    )
    val ligacao: StateFlow<Ligacao> = ponte.estado
    /** a ponte em casa vai pelo Wi-Fi do relógio, não pelo celular */
    private val rede = RedeLocal(app) { wifi -> viewModelScope.launch { redeMudou(wifi) } }
    private var esperaWifi: Job? = null

    /** os agentes instalados no PC (vêm no "ola"): cada orbe do carrossel tem um deles */
    private val _agentesPc = MutableStateFlow<List<AgenteInfo>>(emptyList())
    val agentesPc: StateFlow<List<AgenteInfo>> = _agentesPc

    val aparencia: StateFlow<Aparencia> = ajustes.map(::aparenciaDe)
        .stateIn(viewModelScope, SharingStarted.Eagerly, Aparencia())

    private var carregado = false
    private var naTela = false
    private var cicloPrevia: Job? = null
    /** mudanças feitas antes de o disco responder */
    private val pendentes = ArrayList<(Ajustes) -> Ajustes>()

    init {
        cena.aoMudar = {
            _retrato.value = it
            seguirEscuta(it)
        }
        viewModelScope.launch {
            // o que mudou antes de o disco responder (o endereço vindo pelo adb) vale por cima
            _ajustes.value = pendentes.fold(cofre.fluxo.first()) { a, f -> f(a) }
            carregado = true
            aplicar(_ajustes.value)
            if (pendentes.isNotEmpty()) cofre.gravar(_ajustes.value)
            pendentes.clear()
            if (_ajustes.value.sacudida) ServicoSacudida.ligar(getApplication())
            if (naTela) conectar()
        }
        viewModelScope.launch {
            // sem a ponte ninguém avisa que a sessão fechou: o orbe volta a esperar
            ligacao.collect {
                if (it !is Ligacao.Conectada) {
                    altoFalante.cortar()
                    pararEscuta()
                    if (_previa.value == null) adormecer()
                } else if (querOuvir) {
                    iniciarEscuta()
                }
            }
        }
    }

    private fun aparenciaDe(a: Ajustes): Aparencia {
        val pc = a.pc.takeIf { it.isNotEmpty() }?.let(Protocolo::ola)
        val tema = pc?.let { Tema.de(it.tema) } ?: Tema.Padrao
        return if (a.seguirPc && pc != null) Aparencia(Skin.de(pc.orbe.skin), pc.orbe.glitch, tema)
        else Aparencia(Skin.de(a.skin), a.glitch, tema, a.cor.mod(Ciclo.cores.size))
    }

    /** Leva os ajustes para a cena (quem desenha lê dela). */
    private fun aplicar(a: Ajustes) {
        val ap = aparenciaDe(a)
        cena.skin = ap.skin
        cena.glitch = ap.glitch
        cena.tamanho = a.tamanho.toDouble()
        cena.corTema = ap.corFigura()
        cena.accent = ap.corAnel()
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
        enviarAgente()
    }

    /**
     * Mudança nos ajustes que o app do PC também edita: ganha a hora de agora
     * e vai para lá (vale a mais nova dos dois lados).
     */
    private fun mudarSinc(f: (Ajustes) -> Ajustes) {
        mudar { f(it).copy(t = System.currentTimeMillis()) }
        ponte.enviar(Protocolo.ajustes(_ajustes.value.sincronia()))
    }

    /** O PC mandou os ajustes: ficam se forem mais novos que os daqui. */
    private fun ajustesDaPonte(s: Sincronia) {
        if (s.t > _ajustes.value.t) mudar { it.com(s) }
    }

    // o último "agente" que a ponte desta conexão recebeu; null = mandar de novo
    private var agenteEnviado: String? = null

    /** A ponte fica sabendo do agente do orbe em tela (a sessão aberta daqui usa ele). */
    private fun enviarAgente() {
        if (ligacao.value !is Ligacao.Conectada) return
        val a = _ajustes.value
        val id = a.agentes[aparenciaDe(a).skin.id].orEmpty()
        if (id == agenteEnviado) return
        if (ponte.enviar("agente $id".trim())) agenteEnviado = id
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
    fun skin(s: Skin) = mudarSinc { it.copy(seguirPc = false, skin = s.id, glitch = aparencia.value.glitch) }

    fun glitch(v: Boolean) = mudarSinc { it.copy(seguirPc = false, glitch = v, skin = aparencia.value.skin.id) }

    fun seguirPc(v: Boolean) = mudarSinc { it.copy(seguirPc = v) }

    /** Rolou o carrossel para outra skin (e cor): como escolher no menu, solta o orbe do PC. */
    fun girar(s: Skin, cor: Int) {
        val a = _ajustes.value
        if (a.seguirPc) mudarSinc { it.copy(seguirPc = false, skin = s.id, cor = cor, glitch = aparencia.value.glitch) }
        else mudar { it.copy(skin = s.id, cor = cor) }        // a skin em tela não vai ao PC, só o agente dela
    }

    fun tamanho(v: Float) = mudarSinc { it.copy(tamanho = v.coerceIn(Ajustes.TAMANHO_MIN, Ajustes.TAMANHO_MAX)) }

    fun texto(v: Boolean) = mudarSinc { it.copy(texto = v) }

    fun microfone(v: Boolean) = mudarSinc { it.copy(microfone = v) }

    /** A ponte fica sabendo ao conectar se o relógio toca a resposta: mudou, reconecta. */
    fun voz(v: Boolean) {
        mudarSinc { it.copy(voz = v) }
        if (!v) altoFalante.cortar()
        if (naTela) conectar(forcar = true)
    }

    /** Também vai no "ola": mudou, reconecta. */
    fun vozPc(v: Boolean) {
        mudarSinc { it.copy(vozPc = v) }
        if (naTela) conectar(forcar = true)
    }

    fun vibrar(v: Boolean) = mudarSinc { it.copy(vibrar = v) }

    /** O agente seguinte para o orbe da [skin], em roda: o padrão (Claude) e os do PC. */
    fun proximoAgente(skin: Skin) {
        val ids = listOf("") + _agentesPc.value.map { it.id }.filter { it != "claude" }
        val atual = _ajustes.value.agentes[skin.id].orEmpty().let { if (it == "claude") "" else it }
        val prox = ids[(ids.indexOf(atual) + 1).mod(ids.size)]
        mudarSinc { it.copy(agentes = it.agentes + (skin.id to prox)) }
    }

    fun pediuMicrofone() = mudar { it.copy(pediuMicrofone = true) }

    /** A chave da sacudida liga e desliga o serviço que escuta o pulso. */
    fun sacudida(v: Boolean) {
        mudar { it.copy(sacudida = v) }
        if (v) ServicoSacudida.ligar(getApplication()) else ServicoSacudida.desligar(getApplication())
    }

    fun calibrarSacudida(p: Picos) = mudar { it.copy(sacudidaFora = p.fora, sacudidaDentro = p.dentro) }

    fun sacudidaPadrao() = calibrarSacudida(Picos(Sacudida.FORA_MIN, Sacudida.DENTRO_MIN))

    // ── ponte ──

    fun entrou() {
        naTela = true
        if (carregado) conectar()
    }

    fun saiu() {
        naTela = false
        pararEscuta()
        toqueCancelado()
        altoFalante.cortar()
        pararPrevia()
        esperaWifi?.cancel()
        ponte.desligar()        // a sessão continua no PC; na volta, a ponte conta em que pé está
        rede.soltar()
    }

    private fun conectar(forcar: Boolean = false) {
        val a = _ajustes.value
        val local = Protocolo.local(a.servidor)
        if (local) rede.prender() else rede.soltar()
        esperaWifi?.cancel()
        if (local && !rede.noWifi) {
            // o Wi-Fi do relógio dorme e leva uns segundos para voltar: espera por ele
            // antes de sair pelo celular, para a conexão não nascer na rede que cai
            esperaWifi = viewModelScope.launch {
                delay(ESPERA_WIFI)
                ponte.ligar(a.servidor, a.token, forcar)
            }
            return
        }
        ponte.ligar(a.servidor, a.token, forcar)
    }

    /**
     * O Wi-Fi chegou ou caiu e a conexão aberta ficou na rede velha. No meio de
     * uma sessão ela fica até cair sozinha (religar cortaria a escuta e a voz);
     * a próxima já nasce na rede nova.
     */
    private fun redeMudou(wifi: Boolean) {
        if (!naTela) return
        val ocupado = escutando || segurando || _retrato.value.visivel
        if (esperaWifi?.isActive == true || !wifi || !ocupado) conectar(forcar = true)
    }

    private fun linhaDaPonte(linha: String) {
        if (_previa.value == null) cena.comando(linha)
    }

    private fun olaDaPonte(ola: Ola, bruto: String) {
        // a ponte repete em seguida o que o orbe do PC está mostrando
        if (_previa.value == null) adormecer()
        _agentesPc.value = ola.agentes
        agenteEnviado = null
        mudar { it.copy(pc = bruto) }
        // os ajustes daqui vão ao PC; se os de lá forem mais novos, a ponte devolve os dela
        ponte.enviar(Protocolo.ajustes(_ajustes.value.sincronia()))
        enviarAgente()
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

    private val preRolo = ArrayList<ByteArray>()     // a fala desde que o dedo encostou
    private var transmitindo = false
    private var segurando = false                    // "touch down" enviado, falta o "touch up"

    /** Dedo encostou: os olhos vão para ele e o microfone já começa a guardar. */
    fun toqueBaixo(x: Float, y: Float, podeGravar: Boolean) {
        if (_previa.value != null) return
        pararEscuta()                   // o dedo assume a fala
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

    // ── aberto pela sacudida (HinaWatch): a sessão abre e o microfone fica com ela ──
    //
    // O "trigger" abre a sessão no PC como o atalho do teclado; a fala vai
    // inteira, sem dedo, e o daemon decide o fim pelo silêncio. O microfone
    // acompanha o orbe: ouvindo, transmite; pensando ou falando, descansa (a
    // voz da resposta no alto-falante do relógio não volta como fala).

    private var querOuvir = false
    private var escutando = false
    private var micDaEscuta = false
    private var sessaoVista = false             // a sessão já apareceu: sumir depois disso é fechar

    /** Pedido pela sacudida: abre a sessão assim que a ponte estiver conectada. */
    fun ouvir(podeGravar: Boolean) {
        if (!podeGravar || !_ajustes.value.microfone) return
        // já ouvindo, ou com a sessão aberta: outro "trigger" fecharia a sessão no PC
        if (querOuvir || escutando || _retrato.value.visivel) return
        querOuvir = true
        if (ligacao.value is Ligacao.Conectada) iniciarEscuta()
    }

    private fun iniciarEscuta() {
        querOuvir = false
        val lig = ligacao.value
        if (lig !is Ligacao.Conectada || !lig.microfone) return
        synchronized(trava) {
            escutando = true
            sessaoVista = false
        }
        ponte.enviar("trigger")
        ligarMicDaEscuta()
        tremer()
    }

    private fun ligarMicDaEscuta() {
        synchronized(trava) {
            if (!escutando || micDaEscuta) return
            micDaEscuta = true
            preRolo.clear()
            transmitindo = true
            microfone.iniciar(::blocoDoMicrofone)
        }
    }

    private fun desligarMicDaEscuta() {
        synchronized(trava) {
            if (!micDaEscuta) return
            micDaEscuta = false
            transmitindo = false
            microfone.parar()
        }
    }

    private fun pararEscuta() {
        querOuvir = false
        desligarMicDaEscuta()
        synchronized(trava) { escutando = false }
    }

    private fun seguirEscuta(r: Retrato) {
        if (!escutando || segurando) return
        when {
            r.visivel -> {
                sessaoVista = true
                if (r.estado == Estado.LISTENING) ligarMicDaEscuta() else desligarMicDaEscuta()
            }
            sessaoVista -> pararEscuta()        // a sessão fechou no PC
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
        rede.soltar()
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
        /** quanto a ponte em casa espera o Wi-Fi acordar antes de sair pelo celular */
        const val ESPERA_WIFI = 4_000L

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
