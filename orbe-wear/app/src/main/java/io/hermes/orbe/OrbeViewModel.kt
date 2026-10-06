package io.hermes.orbe

import android.app.Application
import android.os.Build
import android.os.VibrationEffect
import android.os.Vibrator
import androidx.lifecycle.AndroidViewModel
import androidx.lifecycle.viewModelScope
import io.hermes.orbe.dados.AcaoToque
import io.hermes.orbe.dados.AgenteInfo
import io.hermes.orbe.dados.Ajustes
import io.hermes.orbe.dados.AltoFalante
import io.hermes.orbe.dados.Cofre
import io.hermes.orbe.dados.Historico
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
import kotlinx.coroutines.flow.combine
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
    /** a instância em tela, num orbe de agente com instâncias (Instancias); 0 nos outros */
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
     * O orbe (skin e instância) que estava em tela quando a sessão abriu; null
     * sem sessão. Rolando para outro, a sessão segue, mas só o dono a mostra.
     */
    private val _dono = MutableStateFlow<Pair<Skin, Int>?>(null)

    /** O histórico aberto pela ação Histórico dos toques; null fechado. */
    private val _historico = MutableStateFlow<Historico?>(null)
    val historico: StateFlow<Historico?> = _historico
    val dono: StateFlow<Pair<Skin, Int>?> = _dono

    /**
     * as sessões do Claude Code abertas no PC, cada uma na vaga dela (com mais de
     * um orbe do Claude, as vagas se alternam entre eles: [Instancias.vaga]);
     * null sem ponte, ou com uma que não as conta
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
        aoAcabar = {
            ponte.enviar("voz acabou")
            // a resposta tocou com o orbe fora da tela (a tela não pôde abrir): a
            // espera acabou. Uma etapa dita no meio do trabalho não acaba nada.
            if (aoFundo && !naTela && !pcTrabalhando()) viewModelScope.launch { largarFundo() }
        },
    )
    private val ponte: Ponte = Ponte(
        viewModelScope, Build.MODEL ?: "relógio", ::linhaDaPonte, ::olaDaPonte, ::configDaPonte,
        aoVoz = ::vozDaPonte, aoAudio = { altoFalante.tocar(it) },
        querVoz = { temSaidaDeSom && _ajustes.value.voz },
        querVozPc = { _ajustes.value.vozPc },
        aoAjustes = ::ajustesDaPonte,
        aoSessoes = { _sessoes.value = it },
        aoHistorico = { h -> if (_historico.value != null) _historico.value = h },
    )
    val ligacao: StateFlow<Ligacao> = ponte.estado
    /** a ponte em casa vai pelo Wi-Fi do relógio, não pelo celular */
    private val rede = RedeLocal(app) { wifi -> viewModelScope.launch { redeMudou(wifi) } }
    private var esperaWifi: Job? = null

    /** os agentes instalados no PC (vêm no "ola"): cada orbe da lista tem um deles */
    private val _agentesPc = MutableStateFlow<List<AgenteInfo>>(emptyList())
    val agentesPc: StateFlow<List<AgenteInfo>> = _agentesPc

    // os agentes do PC dizem quais orbes têm instâncias
    val aparencia: StateFlow<Aparencia> = combine(ajustes, _agentesPc) { a, _ -> aparenciaDe(a) }
        .stateIn(viewModelScope, SharingStarted.Eagerly, Aparencia())

    private var carregado = false
    private var naTela = false
    /** mudanças feitas antes de o disco responder */
    private val pendentes = ArrayList<(Ajustes) -> Ajustes>()

    init {
        cena.aoMudar = {
            if (!it.visivel) _dono.value = null
            else if (_dono.value == null) aparenciaDe(_ajustes.value).let { ap -> _dono.value = ap.skin to ap.instancia }
            acertarDono(aparenciaDe(_ajustes.value))
            _retrato.value = it
            seguirEscuta(it)
            if (aoFundo) acompanharFundo(it)
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
        val instancia = if (temInstancias(agenteDe(skin, a))) a.instancia.coerceAtLeast(0) else 0
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
        acertarDono(ap)
    }

    /** O orbe em tela mostra a sessão só se foi dele que ela abriu. */
    private fun acertarDono(ap: Aparencia) {
        val d = _dono.value
        cena.alheia = d != null && d != (ap.skin to ap.instancia)
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
        if (s.t <= _ajustes.value.t) return
        val sacudia = _ajustes.value.sacudida
        mudar { it.com(s) }
        // a chave da sacudida mexida no PC liga e desliga o serviço daqui
        val sacode = _ajustes.value.sacudida
        if (sacode != sacudia) {
            if (sacode) ServicoSacudida.ligar(getApplication()) else ServicoSacudida.desligar(getApplication())
        }
    }

    // o último "agente", a última "vaga" e o último "orbe" que a ponte desta conexão recebeu; null = mandar de novo
    private var agenteEnviado: String? = null
    private var vagaEnviada: Int? = null
    private var orbeEnviado: String? = null

    /**
     * A ponte fica sabendo do agente do orbe em tela (a sessão aberta daqui usa
     * ele), num agente com instâncias da vaga dele (a sessão que ele mostra), e
     * da skin e da cor dele (o orbe do PC pode seguir o daqui).
     */
    private fun enviarAgente() {
        if (ligacao.value !is Ligacao.Conectada) return
        val a = _ajustes.value
        val ap = aparenciaDe(a)
        val id = a.agentes[ap.skin.id].orEmpty()
        if (id != agenteEnviado && ponte.enviar("agente $id".trim())) agenteEnviado = id
        val grupo = skinsDoAgente(agenteDe(ap.skin, a), a)
        val j = grupo.indexOf(ap.skin)
        val vaga = if (j >= 0) Instancias.vaga(ap.instancia, j, grupo.size) else -1
        if (vaga != vagaEnviada && ponte.enviar(if (vaga < 0) "vaga" else "vaga $vaga")) vagaEnviada = vaga
        val orbe = "orbe ${ap.skin.id} ${Instancias.corHex(ap.instancia)}"
        if (orbe != orbeEnviado && ponte.enviar(orbe)) orbeEnviado = orbe
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

    /** O fundo do menu atrás dos orbes. */
    fun fundo(v: Boolean) = mudarSinc { it.copy(fundo = v) }

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

    /** O agente do orbe da [skin]: o escolhido, ou o Claude (o padrão). */
    fun agenteDe(skin: Skin, a: Ajustes = _ajustes.value): String = a.agentes[skin.id].orEmpty().ifEmpty { "claude" }

    /** O agente tem uma sessão por instância do orbe: o Claude, e os que o PC roda numa janela do terminal. */
    fun temInstancias(agente: String): Boolean =
        agente == "claude" || _agentesPc.value.any { it.id == agente && it.instancias }

    /** As skins cujos orbes são do [agente], na ordem da lista; vazia se ele não tem instâncias. */
    fun skinsDoAgente(agente: String, a: Ajustes = _ajustes.value): List<Skin> =
        if (!temInstancias(agente)) emptyList() else a.skins().filter { agenteDe(it, a) == agente }

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
        mudarSinc { it.copy(sacudida = v) }
        if (v) ServicoSacudida.ligar(getApplication()) else ServicoSacudida.desligar(getApplication())
    }

    fun calibrarSacudida(p: Picos) = mudarSinc { it.copy(sacudidaFora = p.fora, sacudidaDentro = p.dentro) }

    fun sacudidaPadrao() = calibrarSacudida(Picos(Sacudida.FORA_MIN, Sacudida.DENTRO_MIN))

    /** Com o orbe aberto, a sacudida só para fora sai dele. */
    fun sair(v: Boolean) = mudarSinc { it.copy(sair = v) }

    /** O fora mínimo de sair, da calibração; 0 volta ao padrão. */
    fun calibrarSair(fora: Float) = mudarSinc { it.copy(sairFora = fora) }

    /** Leva a [skin] um lugar para cima (-1) ou para baixo (+1) na lista dos orbes. */
    fun mover(skin: Skin, passo: Int) = mudarSinc { a ->
        val lista = a.skins().toMutableList()
        val i = lista.indexOf(skin)
        val j = i + passo
        if (i < 0 || j !in lista.indices) return@mudarSinc a
        lista[i] = lista[j].also { lista[j] = skin }
        a.copy(ordem = lista.map { it.id })
    }

    // ── ponte ──

    fun entrou() {
        naTela = true
        if (aoFundo) {
            aoFundo = false
            tetoFundo?.cancel()
            ServicoEspera.desligar(getApplication())
        }
        if (carregado) conectar()
    }

    fun saiu() {
        naTela = false
        pararEscuta()
        toqueCancelado()
        // com um pedido esperando a resposta, a ponte fica: a resposta traz o orbe de volta
        if (pedidoNoAr()) esperarAoFundo() else soltarPonte()
    }

    private fun soltarPonte() {
        altoFalante.cortar()
        esperaWifi?.cancel()
        ponte.desligar()        // a sessão continua no PC; na volta, a ponte conta em que pé está
        rede.soltar()
    }

    // ── a resposta com o orbe fora da tela ──
    //
    // Saiu do orbe (o botão, a sacudida para fora, a tela que apagou) com o
    // agente pensando: o ServicoEspera segura o relógio acordado e a ponte
    // segue. A resposta (a voz que chega, ou a sessão que volta a ouvir) acende
    // a tela e traz o orbe para a frente, falando. A sessão que fecha sem
    // resposta, a voz que acaba sem a tela ter vindo ou o teto encerram a espera.

    @Volatile private var aoFundo = false
    private var tetoFundo: Job? = null

    /** O agente está pensando num pedido: a resposta ainda vem. */
    private fun pedidoNoAr(): Boolean =
        ligacao.value is Ligacao.Conectada && _retrato.value.visivel && pcTrabalhando()

    /**
     * O estado que o PC mandou por último ("show", "state", "line"). O do
     * retrato não serve aqui: a voz tocada no relógio o põe em "speaking" pelo
     * nível, e as etapas ditas no meio do trabalho também tocam.
     */
    @Volatile private var estadoPc = Estado.IDLE

    private fun pcTrabalhando() = estadoPc == Estado.THINKING || estadoPc == Estado.TOOLS

    private fun acompanharPc(linha: String) {
        val l = linha.trim()
        val op = l.substringBefore(' ')
        val arg = l.substringAfter(' ', "").trim()
        when (op) {
            "show", "state" -> {
                val e = Estado.de(arg.ifEmpty { "listening" })
                if (e < 0) return
                estadoPc = e
            }
            "line" -> {
                if (estadoPc != Estado.THINKING) estadoPc = Estado.TOOLS
                return
            }
            "hide" -> {
                estadoPc = Estado.IDLE
                return
            }
            else -> return
        }
        // a resposta: o PC passou a falar ou voltou a ouvir (as etapas vêm em "tools")
        if (aoFundo && !pcTrabalhando()) trazer()
    }

    private fun esperarAoFundo() {
        aoFundo = true
        trouxe = false
        ServicoEspera.ligar(getApplication())
        tetoFundo?.cancel()
        tetoFundo = viewModelScope.launch {
            delay(ServicoEspera.TETO_MS)
            if (aoFundo && !naTela) largarFundo()
        }
    }

    private fun largarFundo() {
        aoFundo = false
        tetoFundo?.cancel()
        ServicoEspera.desligar(getApplication())
        if (!naTela) soltarPonte()
    }

    private fun acompanharFundo(r: Retrato) {
        // a ponte que cai ou reconecta esconde o orbe e logo repete o que o PC
        // mostra: só a sessão que segue fechada encerra a espera
        if (!r.visivel) viewModelScope.launch {
            delay(CONFIRMA_FECHOU)
            if (aoFundo && !_retrato.value.visivel && ligacao.value is Ligacao.Conectada) largarFundo()
        }
    }

    /** A resposta chegou: a tela acende e o orbe vem para a frente (uma vez por espera). */
    @Volatile private var trouxe = false
    private fun trazer() {
        if (trouxe) return
        trouxe = true
        ServicoEspera.trazer(getApplication())
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
        acompanharPc(linha)
    }

    private fun olaDaPonte(ola: Ola, bruto: String) {
        // a ponte repete em seguida o que o orbe do PC está mostrando
        adormecer()
        _agentesPc.value = ola.agentes
        _sessoes.value = ola.sessoes
        _abreClaude.value = ola.abreClaude
        agenteEnviado = null
        vagaEnviada = null
        orbeEnviado = null
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

    fun live(v: Boolean) = mudarSinc { it.copy(live = v) }

    /** A ação seguinte, em roda, para [n] toques (1 a 4). */
    fun proximaAcao(n: Int) = mudarSinc { a ->
        val l = a.toques.toMutableList()
        if (n - 1 !in l.indices) return@mudarSinc a
        l[n - 1] = AcaoToque.entries[(l[n - 1].ordinal + 1) % AcaoToque.entries.size]
        a.copy(toques = l)
    }

    /** Pede à ponte as sessões passadas do agente do orbe em tela. */
    private fun abrirHistorico() {
        if (ligacao.value !is Ligacao.Conectada) return
        enviarAgente()
        _historico.value = Historico(carregando = true)
        if (!ponte.enviar("historico")) _historico.value = Historico(erro = "sem a ponte")
        tremer()
    }

    fun fecharHistorico() {
        _historico.value = null
    }

    /**
     * Retoma uma sessão passada no orbe em tela. Num agente com instâncias ela
     * vai para uma instância sem sessão: a em tela, se está livre, ou a do fim.
     */
    fun retomar(id: String) {
        _historico.value = null
        val a = _ajustes.value
        val ap = aparenciaDe(a)
        val agente = agenteDe(ap.skin, a)
        val grupo = skinsDoAgente(agente, a)
        val j = grupo.indexOf(ap.skin)
        if (j >= 0) {
            val vagas = _sessoes.value.orEmpty().filter { it.agente == agente }.map { it.vaga }
            val ocupadas = Instancias.doOrbe(vagas, j, grupo.size)
            if (ap.instancia in ocupadas) instancia((ocupadas.maxOrNull() ?: -1) + 1)
        }
        enviarAgente()
        ponte.enviar("retomar $id")
        tremer()
    }

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
        // chegou ao maior número de toques que faz algo: não espera outro
        val teto = _ajustes.value.maisToques()
        if (teto == 0) {
            toques = 0
            return
        }
        if (++toques >= teto) {
            val n = toques
            toques = 0
            toquesCurtos(n, podeGravar)
            return
        }
        contagem = viewModelScope.launch {
            delay(JANELA_TOQUES)
            val n = toques
            toques = 0
            toquesCurtos(n, podeGravar)
        }
    }

    /** [n] toques curtos: a ação escolhida para eles ([Ajustes.toques]). */
    private fun toquesCurtos(n: Int, podeGravar: Boolean) {
        when (_ajustes.value.toque(n)) {
            AcaoToque.ABRIR -> toqueSessao(live = false, podeGravar)
            AcaoToque.LIVE -> toqueSessao(live = true, podeGravar)
            AcaoToque.ENCERRAR -> encerrar()
            AcaoToque.HISTORICO -> abrirHistorico()
            AcaoToque.NADA -> Unit
        }
    }

    /**
     * Cada ação faz só a sua, sem invadir a dos outros toques: fechar é só do
     * Encerrar. Abrir: fechada, abre (ou já no live, com a opção); aberta,
     * interrompe a fala ou o raciocínio, e ouvindo não faz nada. Live: liga o
     * live (abrindo, se precisar) ou, ligado, desliga, e a sessão segue.
     */
    private fun toqueSessao(live: Boolean, podeGravar: Boolean) {
        if (ligacao.value !is Ligacao.Conectada) return
        val r = _retrato.value
        val aberta = r.visivel || escutando
        when {
            !aberta -> abrir(live || _ajustes.value.live, podeGravar)
            live && r.travado -> {
                ponte.enviar("release")
                tremer()
            }
            live -> entrarNoLive(podeGravar)
            r.estado == Estado.SPEAKING || r.estado == Estado.THINKING || r.estado == Estado.TOOLS -> {
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

    /** Encerrar: fecha a sessão e, com o Claude no orbe, a sessão dele no PC. */
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
        if (aoFundo) ServicoEspera.desligar(getApplication())
        microfone.parar()
        altoFalante.cortar()
        ponte.desligar()
        rede.soltar()
    }

    private companion object {
        /** quanto a ponte em casa espera o Wi-Fi acordar antes de sair pelo celular */
        const val ESPERA_WIFI = 4_000L
        /** toques curtos dentro disto contam juntos; cada número tem a sua ação ([Ajustes.toques]) */
        const val JANELA_TOQUES = 400L
        /** com o orbe fora da tela, quanto a sessão escondida espera para contar como fechada */
        const val CONFIRMA_FECHOU = 2_000L
    }
}
