package io.hermes.orbe.gesto

import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import io.hermes.orbe.dados.Cofre
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.runBlocking

/**
 * Religa o serviço da sacudida depois do boot e de uma atualização do app (que
 * mata o processo), se a chave estiver ligada. Sem isso o gesto só voltava ao
 * abrir o orbe.
 */
class Partida : BroadcastReceiver() {
    override fun onReceive(context: Context, intent: Intent) {
        if (intent.action != Intent.ACTION_BOOT_COMPLETED && intent.action != Intent.ACTION_MY_PACKAGE_REPLACED) return
        if (runBlocking { Cofre(context.applicationContext).fluxo.first().sacudida }) ServicoSacudida.ligar(context)
    }
}
