package io.hermes.orbe.dados

import android.content.Context
import androidx.datastore.core.DataStore
import androidx.datastore.preferences.core.Preferences
import androidx.datastore.preferences.core.booleanPreferencesKey
import androidx.datastore.preferences.core.edit
import androidx.datastore.preferences.core.floatPreferencesKey
import androidx.datastore.preferences.core.stringPreferencesKey
import androidx.datastore.preferences.preferencesDataStore
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.map

/** O que o relógio guarda. A config do daemon (agente, voz, conversa) fica no PC, no app do Orbe. */
data class Ajustes(
    val servidor: String = "",
    val token: String = "",
    /** avatar e glitch vêm do orbe do PC; escolher um avatar aqui desliga */
    val seguirPc: Boolean = true,
    val skin: String = "ofanim",
    val glitch: Boolean = true,
    /** escala do orbe na tela: 1,0 enche o mostrador */
    val tamanho: Float = 1f,
    /** as linhas do raciocínio, abaixo do orbe */
    val texto: Boolean = true,
    /** segurando o orbe, a fala vem do microfone do relógio */
    val microfone: Boolean = true,
    /** a resposta toca no relógio, quando quem serve a ponte manda a voz para cá */
    val voz: Boolean = true,
    val vibrar: Boolean = true,
    /** a permissão do microfone já foi pedida uma vez (depois disso, só pela chave do menu) */
    val pediuMicrofone: Boolean = false,
    /** o último "ola" da ponte: o app abre com a aparência do PC antes de conectar */
    val pc: String = "",
) {
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
        val glitch = booleanPreferencesKey("glitch")
        val tamanho = floatPreferencesKey("tamanho")
        val texto = booleanPreferencesKey("texto")
        val microfone = booleanPreferencesKey("microfone")
        val voz = booleanPreferencesKey("voz")
        val vibrar = booleanPreferencesKey("vibrar")
        val pediuMicrofone = booleanPreferencesKey("pediu_microfone")
        val pc = stringPreferencesKey("pc")
    }

    val fluxo: Flow<Ajustes> = ctx.guardado.data.map { p ->
        val d = Ajustes()
        Ajustes(
            servidor = p[K.servidor] ?: d.servidor,
            token = p[K.token] ?: d.token,
            seguirPc = p[K.seguirPc] ?: d.seguirPc,
            skin = p[K.skin] ?: d.skin,
            glitch = p[K.glitch] ?: d.glitch,
            tamanho = (p[K.tamanho] ?: d.tamanho).coerceIn(Ajustes.TAMANHO_MIN, Ajustes.TAMANHO_MAX),
            texto = p[K.texto] ?: d.texto,
            microfone = p[K.microfone] ?: d.microfone,
            voz = p[K.voz] ?: d.voz,
            vibrar = p[K.vibrar] ?: d.vibrar,
            pediuMicrofone = p[K.pediuMicrofone] ?: d.pediuMicrofone,
            pc = p[K.pc] ?: d.pc,
        )
    }

    suspend fun gravar(a: Ajustes) {
        ctx.guardado.edit { p ->
            p[K.servidor] = a.servidor
            p[K.token] = a.token
            p[K.seguirPc] = a.seguirPc
            p[K.skin] = a.skin
            p[K.glitch] = a.glitch
            p[K.tamanho] = a.tamanho
            p[K.texto] = a.texto
            p[K.microfone] = a.microfone
            p[K.voz] = a.voz
            p[K.vibrar] = a.vibrar
            p[K.pediuMicrofone] = a.pediuMicrofone
            p[K.pc] = a.pc
        }
    }
}
