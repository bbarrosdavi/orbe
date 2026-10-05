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
import io.hermes.orbe.dados.SessaoInfo
import io.hermes.orbe.dados.Sincronia
import io.hermes.orbe.gesto.Picos
import io.hermes.orbe.gesto.Sacudida
import io.hermes.orbe.gesto.ServicoSacudida
import io.hermes.orbe.orbe.Estado
import io.hermes.orbe.orbe.Instancias
import io.hermes.orbe.orbe.OrbeCena
import io.hermes.orbe.orbe.Retrato
import io.hermes.orbe.orbe.Skin
import io.hermes.orbe.ui.Tema
import io.hermes.orbe.ui.rgb
import kotlinx.coroutines.Job
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.SharingStarted
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.flow.map
import kotlinx.coroutines.flow.stateIn
import kotlinx.coroutines.launch

/** O que vale na tela: os ajustes do relógio já cruzados com a aparência do PC. */
data class Aparencia(
    val skin: Skin = Skin.OFANIM,
    val glitch: Boolean = true,
    val linhas: Boolean = true,
    val tema: Tema = Tema.Padrao,
    /** a instância em tela, num orbe do Claude (Instancias); 0 nos outros */
    val instancia: Int = 0,
    /** o fundo do menu também atrás dos orbes */
    val fundo: Boolean = true,
) {
    /** A cor da figura e a do anel: a da instância, ou as do tema. */
    fun corFigura(): FloatArray = Instancias.cores[Instancias.cor(instancia)] ?: tema.accent.rgb()
    fun corAnel(): FloatArray = Instancias.cores[Instancias.cor(instancia)] ?: tema.anel.rgb()
    /** O tom da massa escura da figura: o fundo do tema sobre o vidro, como nas miniaturas do menu; preto sem ele. */
    fun corFundo(): FloatArray = if (fundo) tema.fundo.rgb() else floatArrayOf(0f, 0f, 0f)
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

    /**
     * as sessões do Claude Code abertas no PC, cada uma na vaga dela: a
     * instância de mesmo número dos orbes do Claude; null sem ponte, ou com uma que não as conta
     */
    private val _sessoes = MutableStateFlow<List<SessaoInfo>?>(null)
    val sessoes: StateFlow<List<SessaoInfo>?> = _sessoes
    /** falar num orbe do Claude sem sessão abre uma no PC */
    private val _abreClaude = MutableStateFlow(false)
    val abreClaude: StateFlow<Boolean> = _abreClaude

    /** o relógio tem alto-falante (ou fone pareado) para tocar a resposta */
    val temSaidaDeSom = AltoFalante.temSaida(app)
    private val altoFalante = AltoFalante(
        aoNivel = { nivel, tom -> cena.comando("level $nivel $tom") },
        aoAcabar = { ponte.enviar("voz acabou") },
    )
    private val ponte: Ponte = Ponte(
        viewModelScope, Build.MODEL ?: "relógio", ::linhaDaPonte, ::olaDaPonte, ::configDaPonte,
        aoVoz = ::vozDaPonte, aoAudio = { altoFalante.tocar(it) },
        querVoz = { temSaidaDeSom && _ajustes.value.voz },
        querVozPc = { _ajustes.value.vozPc },
        aoAjustes = ::ajustesDaPonte,
        aoSessoes = { _sessoes.value = it },
    )
    val ligacao: StateFlow<Ligacao> = ponte.estado
    /** a ponte em casa vai pelo Wi-Fi do relógio, não pelo celular */
    private val rede = RedeLocal(app) { wifi -> viewModelScope.launch { redeMudou(wifi) } }
    private var esperaWifi: Job? = null

    /** os agentes instalados no PC (vêm no "ola"): cada orbe da lista tem um deles */
    private val _agentesPc = MutableStateFlow<List<AgenteInfo>>(emptyList())
    val agentesPc: StateFlow<List<AgenteInfo>> = _agentesPc

    val aparencia: StateFlow<Aparencia> = ajustes.map(::aparenciaDe)
        .stateIn(viewModelScope, SharingStarted.Eagerly, Aparencia())

    private var carregado = false
    private var naTela = false
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
                    _sessoes.value = null
                    altoFalante.cortar()
                    pararEscuta()
                    adormecer()
                } else if (querOuvir) {
                    iniciarEscuta()
                }
            }
        }
    }

    private fun aparenciaDe(a: Ajustes): Aparencia {
        val pc = a.pc.takeIf { it.isNotEmpty() }?.let(Protocolo::ola)
        val tema = pc?.let { Tema.de(it.tema, it.papel) } ?: Tema.Padrao
        val skin = Skin.de(if (a.seguirPc && pc != null) pc.orbe.skin else a.skin)
        val instancia = if (skin in skinsClaude(a)) a.instancia.coerceAtLeast(0) else 0
        return if (a.seguirPc && pc != null) Aparencia(skin, pc.orbe.glitch, pc.orbe.glitch, tema, instancia, a.fundo)   // no PC as linhas vêm com o glitch
        else Aparencia(skin, a.glitch, a.linhas, tema, instancia, a.fundo)
    }

    /** Leva os ajustes para a cena (quem desenha lê dela). */
    private fun aplicar(a: Ajustes) {
        val ap = aparenciaDe(a)
        cena.skin = ap.skin
        cena.glitch = ap.glitch
        cena.varredura = ap.linhas
        cena.tamanho = a.tamanhoDe(ap.skin).toDouble()
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

    // o último "agente" e a última "vaga" que a ponte desta conexão recebeu; null = mandar de novo
    private var agenteEnviado: String? = null
    private var vagaEnviada: Int? = null

    /**
     * A ponte fica sabendo do agente do orbe em tela (a sessão aberta daqui usa
     * ele) e, num orbe do Claude, da vaga dele: a sessão do Claude Code que ele mostra.
     */
    private fun enviarAgente() {
        if (ligacao.value !is Ligacao.Conectada) return
        val a = _ajustes.value
        val ap = aparenciaDe(a)
        val id = a.agentes[ap.skin.id].orEmpty()
        if (id != agenteEnviado && ponte.enviar("agente $id".trim())) agenteEnviado = id
        val vaga = if (ap.skin in skinsClaude(a)) ap.instancia else -1
        if (vaga != vagaEnviada && ponte.enviar(if (vaga < 0) "vaga" else "vaga $vaga")) vagaEnviada = vaga
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
    fun skin(s: Skin) = mudarSinc { it.copy(seguirPc = false, skin = s.id, instancia = 0, glitch = aparencia.value.glitch, linhas = aparencia.value.linhas) }

    fun glitch(v: Boolean) = mudarSinc { it.copy(seguirPc = false, glitch = v, linhas = aparencia.value.linhas, skin = aparencia.value.skin.id) }

    fun linhas(v: Boolean) = mudarSinc { it.copy(seguirPc = false, linhas = v, glitch = aparencia.value.glitch, skin = aparencia.value.skin.id) }

    fun seguirPc(v: Boolean) = mudarSinc { it.copy(seguirPc = v) }

    /** Rolou a lista para outra skin: como escolher no menu, solta o orbe do PC; o orbe novo entra pela instância 0. */
    fun girar(s: Skin) {
        val a = _ajustes.value
        if (a.seguirPc) mudarSinc { it.copy(seguirPc = false, skin = s.id, instancia = 0, glitch = aparencia.value.glitch, linhas = aparencia.value.linhas) }
        else mudar { it.copy(skin = s.id, instancia = 0) }        // a skin em tela não vai ao PC, só o agente dela
    }

    /** Dois dedos levaram a outra instância do orbe do Claude: a sessão do PC que ele mostra. */
    fun instancia(k: Int) = mudar { it.copy(instancia = k.coerceAtLeast(0)) }

    /** O fundo do menu atrás dos orbes; só aqui no relógio. */
    fun fundo(v: Boolean) = mudar { it.copy(fundo = v) }

    /** O tamanho do orbe em tela: cada skin guarda o seu. */
    fun tamanho(v: Float) {
        val skin = aparencia.value.skin.id
        mudarSinc { it.copy(tamanhos = it.tamanhos + (skin to v.coerceIn(Ajustes.TAMANHO_MIN, Ajustes.TAMANHO_MAX))) }
    }

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

    /** As skins cujos orbes são do Claude (o agente padrão), na ordem da lista. */
    fun skinsClaude(a: Ajustes = _ajustes.value): List<Skin> =
        a.skins().filter { a.agentes[it.id].orEmpty().let { id -> id.isEmpty() || id == "claude" } }

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

    /** Com o orbe aberto, a sacudida só para fora sai dele. */
    fun sair(v: Boolean) = mudar { it.copy(sair = v) }

    /** O fora mínimo de sair, da calibração; 0 volta ao padrão. */
    fun calibrarSair(fora: Float) = mudar { it.copy(sairFora = fora) }

    /** Leva a [skin] um lugar para cima (-1) ou para baixo (+1) na lista dos orbes; só aqui no relógio. */
    fun mover(skin: Skin, passo: Int) = mudar { a ->
        val lista = a.skins().toMutableList()
        val i = lista.indexOf(skin)
        val j = i + passo
        if (i < 0 || j !in lista.indices) return@mudar a
        lista[i] = lista[j].also { lista[j] = skin }
        a.copy(ordem = lista.map { it.id })
    }

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
        cena.comando(linha)
    }

    private fun olaDaPonte(ola: Ola, bruto: String) {
        // a ponte repete em seguida o que o orbe do PC está mostrando
        adormecer()
        _agentesPc.value = ola.agentes
        _sessoes.value = ola.sessoes
        _abreClaude.value = ola.abreClaude
        agenteEnviado = null
        vagaEnviada = null
        mudar { it.copy(pc = bruto) }
        // os ajustes daqui vão ao PC; se os de lá forem mais novos, a ponte devolve os dela
        ponte.enviar(Protocolo.ajustes(_ajustes.value.sincronia()))
        enviarAgente()
    }

    private fun configDaPonte(ola: Ola, bruto: String) = mudar { it.copy(pc = bruto) }

    /** A resposta em voz: a taxa do áudio que vem, o fim dela, ou o corte. */
    private fun vozDaPonte(arg: String) {
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

    /** A chave do menu: o live é a sessão travada, com o microfone daqui acompanhando. */
    fun travar(v: Boolean, podeGravar: Boolean) {
        if (v) entrarNoLive(podeGravar) else ponte.enviar("release")
    }

    fun live(v: Boolean) = mudar { it.copy(live = v) }

    // ── toque no orbe ──
    //
    // Segurar é segurar para falar: o "touch down" vai quando fica claro que o
    // dedo não está só arrastando a tela para o menu (como o orbe.qml faz
    // destravado para mover), e o daemon fecha a fala no "touch up". Os toques
    // curtos são contados aqui, numa janela, e viram comandos (toquesCurtos).

    private val preRolo = ArrayList<ByteArray>()     // a fala desde que o dedo encostou
    private var transmitindo = false
    private var segurando = false                    // "touch down" enviado, falta o "touch up"
    private var dedo = false                         // dedo no orbe: a escuta espera ele sair

    /** Dedo encostou: os olhos vão para ele e o microfone já começa a guardar. */
    fun toqueBaixo(x: Float, y: Float, podeGravar: Boolean) {
        dedo = true
        desligarMicDaEscuta()           // o dedo assume a fala; a escuta volta quando ele sair
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

    private var toques = 0
    private var contagem: Job? = null

    /** Solto antes de andar e antes do tempo de segurar: toque curto, contado. */
    fun toqueCurto(podeGravar: Boolean) {
        largar()
        // o dedo já saiu: o orbe ainda cresce um instante, para o toque ser visto
        cena.toque = true
        viewModelScope.launch {
            delay(140)
            if (!segurando) cena.toque = false
        }
        contagem?.cancel()
        if (++toques >= 3) {
            toques = 0
            encerrar()
            return
        }
        contagem = viewModelScope.launch {
            delay(JANELA_TOQUES)
            val n = toques
            toques = 0
            toquesCurtos(n, podeGravar)
        }
    }

    /**
     * Um toque: fechado, abre (ou já no live, com a opção); aberto, entra no
     * live; no live, interrompe a fala ou o raciocínio, e só ouvindo, fecha.
     * Dois: o live liga (abrindo, se precisar) ou, ligado, fecha.
     */
    private fun toquesCurtos(n: Int, podeGravar: Boolean) {
        if (ligacao.value !is Ligacao.Conectada) return
        val r = _retrato.value
        val aberta = r.visivel || escutando
        when {
            !aberta -> abrir(n >= 2 || _ajustes.value.live, podeGravar)
            !r.travado -> entrarNoLive(podeGravar)
            n >= 2 || r.estado == Estado.LISTENING -> fecharSessao()
            else -> {
                altoFalante.cortar()
                ponte.enviar("interromper")
            }
        }
    }

    private fun abrir(live: Boolean, podeGravar: Boolean) {
        if (!iniciarEscuta(podeGravar)) {
            ponte.enviar("trigger")         // sem o microfone daqui, ouve o do PC
            tremer()
        }
        if (live) ponte.enviar("hold")
    }

    /** O live é a sessão travada; a fala passa a vir daqui se a sessão ainda não ouvia o relógio. */
    private fun entrarNoLive(podeGravar: Boolean) {
        if (escutando || !iniciarEscuta(podeGravar)) {
            if (!escutando && !_retrato.value.visivel) ponte.enviar("trigger")
            tremer()
        }
        ponte.enviar("hold")
    }

    private fun fecharSessao() {
        altoFalante.cortar()
        pararEscuta()
        ponte.enviar("dismiss")
        tremer()
    }

    /** Três toques: fecha a sessão e, com o Claude no orbe, a sessão dele no PC. */
    private fun encerrar() {
        contagem?.cancel()
        altoFalante.cortar()
        pararEscuta()
        ponte.enviar("encerrar")
        tremer()
        viewModelScope.launch {
            delay(120)
            tremer()
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
        dedo = false
        seguirEscuta(_retrato.value)    // a sessão aberta sem dedo volta a ouvir daqui
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
        if (ligacao.value is Ligacao.Conectada) iniciarEscuta(podeGravar)
    }

    /** "trigger" com o microfone daqui acompanhando a sessão; false se não dá para ouvir daqui. */
    private fun iniciarEscuta(podeGravar: Boolean = true): Boolean {
        querOuvir = false
        val lig = ligacao.value
        if (!podeGravar || !_ajustes.value.microfone || lig !is Ligacao.Conectada || !lig.microfone) return false
        synchronized(trava) {
            escutando = true
            sessaoVista = false
        }
        ponte.enviar("trigger")
        ligarMicDaEscuta()
        tremer()
        return true
    }

    private fun ligarMicDaEscuta() {
        synchronized(trava) {
            if (!escutando || micDaEscuta || dedo) return
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
        if (!escutando || segurando || dedo) return
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

    override fun onCleared() {
        microfone.parar()
        altoFalante.cortar()
        ponte.desligar()
        rede.soltar()
    }

    private companion object {
        /** quanto a ponte em casa espera o Wi-Fi acordar antes de sair pelo celular */
        const val ESPERA_WIFI = 4_000L
        /** toques curtos dentro disto contam juntos (um abre, dois ligam o live, três encerram) */
        const val JANELA_TOQUES = 400L
    }
}
