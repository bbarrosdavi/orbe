package io.hermes.orbe.dados

import android.content.Context
import android.net.ConnectivityManager
import android.net.Network
import android.net.NetworkCapabilities
import android.net.NetworkRequest

/**
 * Prende o app ao Wi-Fi enquanto a ponte mora num endereço da rede de casa.
 *
 * Com o celular por perto, o Wear OS manda o tráfego pelo proxy Bluetooth dele
 * (o PC vê o IP do celular, não o do relógio) e a ponte cai a cada ~20 s. Pedir
 * a rede Wi-Fi mantém o rádio do relógio ligado, e o vínculo põe a ponte nela.
 * Perdeu o Wi-Fi, solta: pelo celular ainda chega, mesmo caindo. O mesmo que o
 * HinaWatch faz para servidor em IP privado.
 *
 * [aoTrocar] vem na thread do ConnectivityManager com o Wi-Fi que chegou (true)
 * ou caiu (false): a conexão aberta ficou na rede velha.
 */
class RedeLocal(contexto: Context, private val aoTrocar: (wifi: Boolean) -> Unit) {
    private val cm = contexto.getSystemService(ConnectivityManager::class.java)
    @Volatile private var pedido: ConnectivityManager.NetworkCallback? = null
    @Volatile private var presa: Network? = null

    /** o app já está preso ao Wi-Fi */
    val noWifi: Boolean get() = presa != null

    fun prender() {
        if (pedido != null || cm == null) return
        val cb = object : ConnectivityManager.NetworkCallback() {
            override fun onAvailable(network: Network) {
                if (pedido !== this || presa == network) return
                presa = network
                cm.bindProcessToNetwork(network)
                aoTrocar(true)
            }

            override fun onLost(network: Network) {
                if (pedido !== this || presa != network) return
                presa = null
                cm.bindProcessToNetwork(null)
                aoTrocar(false)
            }
        }
        pedido = cb
        try {
            cm.requestNetwork(NetworkRequest.Builder().addTransportType(NetworkCapabilities.TRANSPORT_WIFI).build(), cb)
        } catch (_: SecurityException) {
            pedido = null
        }
    }

    fun soltar() {
        val cb = pedido ?: return
        pedido = null
        try {
            cm?.unregisterNetworkCallback(cb)
        } catch (_: IllegalArgumentException) {
        }
        if (presa != null) {
            presa = null
            cm?.bindProcessToNetwork(null)
        }
    }
}
