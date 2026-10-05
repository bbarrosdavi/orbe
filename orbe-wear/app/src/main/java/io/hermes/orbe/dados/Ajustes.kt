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
import kotlinx.coroutines.flow.map

/** O que o relógio guarda. A config do daemon (agente, voz, conversa) fica no PC, no app do Orbe. */
data class Ajustes(
    val servidor: String = "",
    val token: String = "",
    /** avatar e glitch vêm do orbe do PC; escolher um avatar aqui desliga */
    val seguirPc: Boolean = true,
    val skin: String = "ofanim",
    /** a cor do orbe no ciclo da rolagem (Ciclo.cores); 0 = a do tema */
    val cor: Int = 0,
    val glitch: Boolean = true,
    /** escala do orbe na tela: 1,0 enche o mostrador */
    val tamanho: Float = 1f,
    /** as linhas do raciocínio, abaixo do orbe */
    val texto: Boolean = true,
    /** segurando o orbe, a fala vem do microfone do relógio */
    val microfone: Boolean = true,
    /** a resposta toca no relógio, quando quem serve a ponte manda a voz para cá */
    val voz: Boolean = true,
    /** tocando aqui, a resposta toca também no PC (quando a ponte é o daemon) */
    val vozPc: Boolean = false,
    val vibrar: Boolean = true,
    /** a permissão do microfone já foi pedida uma vez (depois disso, só pela chave do menu) */
    val pediuMicrofone: Boolean = false,
    /** o último "ola" da ponte: o app abre com a aparência do PC antes de conectar */
    val pc: String = "",
    /** o agente de cada orbe do carrossel, pela skin; "" = o padrão (Claude Code) */
    val agentes: Map<String, String> = emptyMap(),
    /** quando os ajustes que o PC também edita mudaram aqui por último (ms; 0 = nunca) */
    val t: Long = 0,
    /** uma sacudida do pulso, com a tela acesa, abre o orbe já ouvindo (duas são do HinaWatch) */
    val sacudida: Boolean = true,
    /** limiares da sacudida em rad/s (fora e dentro); a calibração troca */
    val sacudidaFora: Float = Sacudida.FORA_MIN,
    val sacudidaDentro: Float = Sacudida.DENTRO_MIN,
) {
    /** O que vai e volta com o PC (a [Sincronia]). */
    fun sincronia() = Sincronia(t, agentes, voz, vozPc, microfone, vibrar, texto, glitch, tamanho, seguirPc)

    fun com(s: Sincronia) = copy(
        t = s.t, agentes = s.agentes, voz = s.voz, vozPc = s.vozPc, microfone = s.microfone, vibrar = s.vibrar,
        texto = s.texto, glitch = s.glitch, tamanho = s.tamanho.coerceIn(TAMANHO_MIN, TAMANHO_MAX), seguirPc = s.seguirPc,
    )

    companion object {
        const val TAMANHO_MIN = 0.6f
        const val TAMANHO_MAX = 1.3f
    }
}

private val Context.guardado: DataStore<Preferences> by preferencesDataStore("ajustes")

class Cofre(private val ctx: Context) {
    private object K {
        val servidor = stringPreferencesKey("servidor")
        val token = stringPreferencesKey("token")
        val seguirPc = booleanPreferencesKey("seguir_pc")
        val skin = stringPreferencesKey("skin")
        val cor = intPreferencesKey("cor")
        val glitch = booleanPreferencesKey("glitch")
        val tamanho = floatPreferencesKey("tamanho")
        val texto = booleanPreferencesKey("texto")
        val microfone = booleanPreferencesKey("microfone")
        val voz = booleanPreferencesKey("voz")
        val vozPc = booleanPreferencesKey("voz_pc")
        val vibrar = booleanPreferencesKey("vibrar")
        val pediuMicrofone = booleanPreferencesKey("pediu_microfone")
        val pc = stringPreferencesKey("pc")
        val agentes = stringPreferencesKey("agentes")      // "skin=agente;skin=agente"
        val t = longPreferencesKey("t")
        val sacudida = booleanPreferencesKey("sacudida")
        val sacudidaFora = floatPreferencesKey("sacudida_fora")
        val sacudidaDentro = floatPreferencesKey("sacudida_dentro")
    }

    private fun lerAgentes(s: String?): Map<String, String> =
        s.orEmpty().split(';').mapNotNull { par ->
            par.split('=', limit = 2).takeIf { it.size == 2 && it[0].isNotEmpty() }?.let { it[0] to it[1] }
        }.toMap()

    val fluxo: Flow<Ajustes> = ctx.guardado.data.map { p ->
        val d = Ajustes()
        Ajustes(
            servidor = p[K.servidor] ?: d.servidor,
            token = p[K.token] ?: d.token,
            seguirPc = p[K.seguirPc] ?: d.seguirPc,
            skin = p[K.skin] ?: d.skin,
            cor = p[K.cor] ?: d.cor,
            glitch = p[K.glitch] ?: d.glitch,
            tamanho = (p[K.tamanho] ?: d.tamanho).coerceIn(Ajustes.TAMANHO_MIN, Ajustes.TAMANHO_MAX),
            texto = p[K.texto] ?: d.texto,
            microfone = p[K.microfone] ?: d.microfone,
            voz = p[K.voz] ?: d.voz,
            vozPc = p[K.vozPc] ?: d.vozPc,
            vibrar = p[K.vibrar] ?: d.vibrar,
            pediuMicrofone = p[K.pediuMicrofone] ?: d.pediuMicrofone,
            pc = p[K.pc] ?: d.pc,
            agentes = lerAgentes(p[K.agentes]),
            t = p[K.t] ?: d.t,
            sacudida = p[K.sacudida] ?: d.sacudida,
            sacudidaFora = p[K.sacudidaFora] ?: d.sacudidaFora,
            sacudidaDentro = p[K.sacudidaDentro] ?: d.sacudidaDentro,
        )
    }

    suspend fun gravar(a: Ajustes) {
        ctx.guardado.edit { p ->
            p[K.servidor] = a.servidor
            p[K.token] = a.token
            p[K.seguirPc] = a.seguirPc
            p[K.skin] = a.skin
            p[K.cor] = a.cor
            p[K.glitch] = a.glitch
            p[K.tamanho] = a.tamanho
            p[K.texto] = a.texto
            p[K.microfone] = a.microfone
            p[K.voz] = a.voz
            p[K.vozPc] = a.vozPc
            p[K.vibrar] = a.vibrar
            p[K.pediuMicrofone] = a.pediuMicrofone
            p[K.pc] = a.pc
            p[K.agentes] = a.agentes.entries.joinToString(";") { "${it.key}=${it.value}" }
            p[K.t] = a.t
            p[K.sacudida] = a.sacudida
            p[K.sacudidaFora] = a.sacudidaFora
            p[K.sacudidaDentro] = a.sacudidaDentro
        }
    }
}
