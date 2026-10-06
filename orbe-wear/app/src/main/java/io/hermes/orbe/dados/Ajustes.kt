package io.hermes.orbe.dados

import android.content.Context
import androidx.datastore.core.DataStore
import androidx.datastore.preferences.core.Preferences
import androidx.datastore.preferences.core.booleanPreferencesKey
import androidx.datastore.preferences.core.edit
import androidx.datastore.preferences.core.floatPreferencesKey
import androidx.datastore.preferences.core.intPreferencesKey
import androidx.datastore.preferences.core.longPreferencesKey
import androidx.datastore.preferences.core.stringPreferencesKey
import androidx.datastore.preferences.preferencesDataStore
import kotlinx.coroutines.flow.Flow
import io.hermes.orbe.gesto.Sacudida
import io.hermes.orbe.orbe.Skin
import kotlinx.coroutines.flow.map

/** O que um número de toques curtos no orbe faz. */
enum class AcaoToque(val id: String, val nome: String) {
    /** fechado, abre (ou já no live, com a opção); aberto, entra no live; no live, interrompe, e só ouvindo, fecha */
    ABRIR("abrir", "Abrir"),
    /** o live liga (abrindo, se precisar) ou, ligado, fecha */
    LIVE("live", "Live"),
    /** fecha a sessão e, com o Claude no orbe, a sessão dele no PC */
    ENCERRAR("encerrar", "Encerrar"),
    /** as sessões passadas do agente do orbe, para retomar uma */
    HISTORICO("historico", "Histórico"),
    NADA("nada", "Nada");

    companion object {
        fun de(id: String?): AcaoToque? = entries.firstOrNull { it.id == id }
        /** um, dois e três toques como sempre foram; quatro, nada */
        val PADRAO = listOf(ABRIR, LIVE, ENCERRAR, NADA)
    }
}

/** O que o relógio guarda. A config do daemon (agente, voz, conversa) fica no PC, no app do Orbe. */
data class Ajustes(
    val servidor: String = "",
    val token: String = "",
    /** avatar, glitch e linhas vêm do orbe do PC; escolher um avatar aqui desliga */
    val seguirPc: Boolean = true,
    val skin: String = "ofanim",
    /** a instância em tela no orbe do Claude: a sessão da vaga dela (Instancias); 0 = o próprio orbe */
    val instancia: Int = 0,
    val glitch: Boolean = true,
    /** as linhas de varredura (o tubo de TV), nas skins desenhadas */
    val linhas: Boolean = true,
    /** o fundo do menu (o papel de parede do PC borrado) também atrás dos orbes */
    val fundo: Boolean = true,
    /** escala do orbe na tela: 1,0 enche o mostrador. É a de cada orbe que ainda não tem a sua ([tamanhos]) */
    val tamanho: Float = 1f,
    /** a escala de cada orbe, pela skin: cada um guarda a sua */
    val tamanhos: Map<String, Float> = emptyMap(),
    /** as linhas do raciocínio, abaixo do orbe */
    val texto: Boolean = true,
    /** segurando o orbe, a fala vem do microfone do relógio */
    val microfone: Boolean = true,
    /** a resposta toca no relógio, quando quem serve a ponte manda a voz para cá */
    val voz: Boolean = true,
    /** tocando aqui, a resposta toca também no PC (quando a ponte é o daemon) */
    val vozPc: Boolean = false,
    val vibrar: Boolean = true,
    /** o orbe fala as etapas do agente enquanto ele trabalha (a descrição de cada ferramenta) */
    val etapas: Boolean = false,
    /** a língua das etapas: [IDIOMAS_ETAPAS] */
    val idiomaEtapas: String = "pt",
    /** a permissão do microfone já foi pedida uma vez (depois disso, só pela chave do menu) */
    val pediuMicrofone: Boolean = false,
    /** o último "ola" da ponte: o app abre com a aparência do PC antes de conectar */
    val pc: String = "",
    /** o agente de cada orbe da lista, pela skin; "" = o padrão (Claude Code) */
    val agentes: Map<String, String> = emptyMap(),
    /** quando os ajustes que o PC também edita mudaram aqui por último (ms; 0 = nunca) */
    val t: Long = 0,
    /** uma sacudida do pulso, com a tela acesa, abre o orbe já ouvindo (duas são do HinaWatch) */
    val sacudida: Boolean = true,
    /** um toque no orbe fechado abre já no modo live (os turnos seguem sem tocar); sem isto, o segundo toque entra */
    val live: Boolean = false,
    /** o que 1, 2, 3 e 4 toques curtos no orbe fazem */
    val toques: List<AcaoToque> = AcaoToque.PADRAO,
    /** limiares da sacudida em rad/s (fora e dentro); a calibração troca */
    val sacudidaFora: Float = Sacudida.FORA_MIN,
    val sacudidaDentro: Float = Sacudida.DENTRO_MIN,
    /** a ordem dos orbes na lista, pelas skins; vazia = a de [Skin.entries] */
    val ordem: List<String> = emptyList(),
    /** com o orbe aberto, uma sacudida do pulso só para fora sai dele (como no HinaWatch) */
    val sair: Boolean = true,
    /** o fora mínimo da sacudida de sair, em rad/s; 0 = sem calibrar, vale o padrão (o do HinaWatch, [Sacudida.FORA_MIN]) */
    val sairFora: Float = 0f,
) {
    /** A ação de [n] toques (1 a 4). */
    fun toque(n: Int): AcaoToque = toques.getOrNull(n - 1) ?: AcaoToque.NADA

    /** O maior número de toques que faz algo: chegou nele, não precisa esperar outro. */
    fun maisToques(): Int = (toques.size downTo 1).firstOrNull { toque(it) != AcaoToque.NADA } ?: 0

    /** A escala do orbe da [skin]. */
    fun tamanhoDe(skin: Skin): Float = tamanhos[skin.id] ?: tamanho

    /** As skins na ordem da lista: as de [ordem] e, depois delas, as que faltarem, na ordem de sempre. */
    fun skins(): List<Skin> {
        val escolhidas = ordem.mapNotNull { id -> Skin.entries.firstOrNull { it.id == id } }.distinct()
        return escolhidas + Skin.entries.filter { it !in escolhidas }
    }

    /** O que vai e volta com o PC (a [Sincronia]). */
    fun sincronia() = Sincronia(
        t, agentes, voz, vozPc, microfone, vibrar, texto, glitch, linhas, tamanho, seguirPc, tamanhos,
        toques = toques.map { it.id }, live = live, fundo = fundo, ordem = skins().map { it.id },
        sacudida = sacudida, sair = sair, sacudidaFora = sacudidaFora, sacudidaDentro = sacudidaDentro, sairFora = sairFora,
        etapas = etapas, idiomaEtapas = idiomaEtapas,
    )

    fun com(s: Sincronia) = copy(
        t = s.t, agentes = s.agentes, voz = s.voz, vozPc = s.vozPc, microfone = s.microfone, vibrar = s.vibrar,
        texto = s.texto, glitch = s.glitch, linhas = s.linhas, tamanho = s.tamanho.coerceIn(TAMANHO_MIN, TAMANHO_MAX), seguirPc = s.seguirPc,
        // o PC manda null no orbe que ainda segue o tamanho comum
        tamanhos = s.tamanhos.mapNotNull { (k, v) -> v?.let { k to it.coerceIn(TAMANHO_MIN, TAMANHO_MAX) } }.toMap(),
        // o que o PC ainda não conhece (null) fica como está aqui
        toques = s.toques?.let { l -> List(AcaoToque.PADRAO.size) { i -> AcaoToque.de(l.getOrNull(i)) ?: toques.getOrNull(i) ?: AcaoToque.NADA } } ?: toques,
        live = s.live ?: live,
        fundo = s.fundo ?: fundo,
        ordem = s.ordem ?: ordem,
        sacudida = s.sacudida ?: sacudida,
        sair = s.sair ?: sair,
        sacudidaFora = s.sacudidaFora?.let { if (it > 0f) it else Sacudida.FORA_MIN } ?: sacudidaFora,
        sacudidaDentro = s.sacudidaDentro?.let { if (it > 0f) it else Sacudida.DENTRO_MIN } ?: sacudidaDentro,
        sairFora = s.sairFora?.let { if (it > 0f) it else 0f } ?: sairFora,
        etapas = s.etapas,
        idiomaEtapas = s.idiomaEtapas.takeIf { it in IDIOMAS_ETAPAS } ?: idiomaEtapas,
    )

    companion object {
        const val TAMANHO_MIN = 0.6f
        const val TAMANHO_MAX = 1.3f
        /** "pt": traduzidas para o português; "original": como o agente escreve */
        val IDIOMAS_ETAPAS = listOf("pt", "original")
    }
}

private val Context.guardado: DataStore<Preferences> by preferencesDataStore("ajustes")

class Cofre(private val ctx: Context) {
    private object K {
        val servidor = stringPreferencesKey("servidor")
        val token = stringPreferencesKey("token")
        val seguirPc = booleanPreferencesKey("seguir_pc")
        val skin = stringPreferencesKey("skin")
        val instancia = intPreferencesKey("instancia")
        val fundo = booleanPreferencesKey("fundo")
        val glitch = booleanPreferencesKey("glitch")
        val linhas = booleanPreferencesKey("linhas")
        val tamanho = floatPreferencesKey("tamanho")
        val tamanhos = stringPreferencesKey("tamanhos")    // "skin=1.0;skin=0.8"
        val texto = booleanPreferencesKey("texto")
        val microfone = booleanPreferencesKey("microfone")
        val voz = booleanPreferencesKey("voz")
        val vozPc = booleanPreferencesKey("voz_pc")
        val vibrar = booleanPreferencesKey("vibrar")
        val etapas = booleanPreferencesKey("etapas")
        val idiomaEtapas = stringPreferencesKey("idioma_etapas")
        val pediuMicrofone = booleanPreferencesKey("pediu_microfone")
        val pc = stringPreferencesKey("pc")
        val agentes = stringPreferencesKey("agentes")      // "skin=agente;skin=agente"
        val t = longPreferencesKey("t")
        val sacudida = booleanPreferencesKey("sacudida")
        val live = booleanPreferencesKey("live")
        val toques = stringPreferencesKey("toques")        // "abrir,live,encerrar,nada"
        val historico = booleanPreferencesKey("historico")  // a chave antiga dos quatro toques
        val sacudidaFora = floatPreferencesKey("sacudida_fora")
        val sacudidaDentro = floatPreferencesKey("sacudida_dentro")
        val ordem = stringPreferencesKey("ordem")          // "anel,serafim_gravura,..."
        val sair = booleanPreferencesKey("sair")
        val sairFora = floatPreferencesKey("sair_fora")
    }

    private fun lerAgentes(s: String?): Map<String, String> =
        s.orEmpty().split(';').mapNotNull { par ->
            par.split('=', limit = 2).takeIf { it.size == 2 && it[0].isNotEmpty() }?.let { it[0] to it[1] }
        }.toMap()

    /** Sem a lista guardada, o padrão; com a chave antiga ligada, quatro toques abrem o histórico. */
    private fun lerToques(s: String?, historico: Boolean): List<AcaoToque> {
        if (s == null) return if (historico) AcaoToque.PADRAO.dropLast(1) + AcaoToque.HISTORICO else AcaoToque.PADRAO
        val l = s.split(',')
        return List(AcaoToque.PADRAO.size) { i -> AcaoToque.de(l.getOrNull(i)) ?: AcaoToque.PADRAO[i] }
    }

    private fun lerTamanhos(s: String?): Map<String, Float> =
        s.orEmpty().split(';').mapNotNull { par ->
            val p = par.split('=', limit = 2)
            val v = p.getOrNull(1)?.toFloatOrNull() ?: return@mapNotNull null
            p[0].takeIf { it.isNotEmpty() }?.let { it to v.coerceIn(Ajustes.TAMANHO_MIN, Ajustes.TAMANHO_MAX) }
        }.toMap()

    val fluxo: Flow<Ajustes> = ctx.guardado.data.map { p ->
        val d = Ajustes()
        Ajustes(
            servidor = p[K.servidor] ?: d.servidor,
            token = p[K.token] ?: d.token,
            seguirPc = p[K.seguirPc] ?: d.seguirPc,
            skin = p[K.skin] ?: d.skin,
            instancia = p[K.instancia] ?: d.instancia,
            fundo = p[K.fundo] ?: d.fundo,
            glitch = p[K.glitch] ?: d.glitch,
            linhas = p[K.linhas] ?: d.linhas,
            tamanho = (p[K.tamanho] ?: d.tamanho).coerceIn(Ajustes.TAMANHO_MIN, Ajustes.TAMANHO_MAX),
            tamanhos = lerTamanhos(p[K.tamanhos]),
            texto = p[K.texto] ?: d.texto,
            microfone = p[K.microfone] ?: d.microfone,
            voz = p[K.voz] ?: d.voz,
            vozPc = p[K.vozPc] ?: d.vozPc,
            vibrar = p[K.vibrar] ?: d.vibrar,
            etapas = p[K.etapas] ?: d.etapas,
            idiomaEtapas = p[K.idiomaEtapas]?.takeIf { it in Ajustes.IDIOMAS_ETAPAS } ?: d.idiomaEtapas,
            pediuMicrofone = p[K.pediuMicrofone] ?: d.pediuMicrofone,
            pc = p[K.pc] ?: d.pc,
            agentes = lerAgentes(p[K.agentes]),
            t = p[K.t] ?: d.t,
            sacudida = p[K.sacudida] ?: d.sacudida,
            live = p[K.live] ?: d.live,
            toques = lerToques(p[K.toques], p[K.historico] == true),
            sacudidaFora = p[K.sacudidaFora] ?: d.sacudidaFora,
            sacudidaDentro = p[K.sacudidaDentro] ?: d.sacudidaDentro,
            ordem = p[K.ordem].orEmpty().split(',').filter { it.isNotEmpty() },
            sair = p[K.sair] ?: d.sair,
            sairFora = p[K.sairFora] ?: d.sairFora,
        )
    }

    suspend fun gravar(a: Ajustes) {
        ctx.guardado.edit { p ->
            p[K.servidor] = a.servidor
            p[K.token] = a.token
            p[K.seguirPc] = a.seguirPc
            p[K.skin] = a.skin
            p[K.instancia] = a.instancia
            p[K.fundo] = a.fundo
            p[K.glitch] = a.glitch
            p[K.linhas] = a.linhas
            p[K.tamanho] = a.tamanho
            p[K.tamanhos] = a.tamanhos.entries.joinToString(";") { "${it.key}=${it.value}" }
            p[K.texto] = a.texto
            p[K.microfone] = a.microfone
            p[K.voz] = a.voz
            p[K.vozPc] = a.vozPc
            p[K.vibrar] = a.vibrar
            p[K.etapas] = a.etapas
            p[K.idiomaEtapas] = a.idiomaEtapas
            p[K.pediuMicrofone] = a.pediuMicrofone
            p[K.pc] = a.pc
            p[K.agentes] = a.agentes.entries.joinToString(";") { "${it.key}=${it.value}" }
            p[K.t] = a.t
            p[K.sacudida] = a.sacudida
            p[K.live] = a.live
            p[K.toques] = a.toques.joinToString(",") { it.id }
            p.remove(K.historico)
            p[K.sacudidaFora] = a.sacudidaFora
            p[K.sacudidaDentro] = a.sacudidaDentro
            p[K.ordem] = a.ordem.joinToString(",")
            p[K.sair] = a.sair
            p[K.sairFora] = a.sairFora
        }
    }
}
