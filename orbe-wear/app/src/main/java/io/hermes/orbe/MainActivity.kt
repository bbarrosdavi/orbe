package io.hermes.orbe

import android.Manifest
import android.app.RemoteInput
import android.content.Intent
import android.content.pm.PackageManager
import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.activity.result.contract.ActivityResultContracts
import androidx.activity.viewModels
import androidx.wear.input.RemoteInputIntentHelper
import io.hermes.orbe.gl.Motor
import io.hermes.orbe.ui.Campo
import io.hermes.orbe.ui.OrbeApp

/**
 * O Orbe no relógio: o mesmo orbe do desktop, desenhado aqui com os shaders do
 * orbe-qt, ligado ao daemon pela ponte (hermes_voice_relogio.py).
 *
 * O endereço e o token também entram pelo adb, para não digitar no pulso:
 *   adb shell am start -n io.hermes.orbe/.MainActivity --es servidor 192.168.0.10 --es token abcd2345
 */
class MainActivity : ComponentActivity() {
    private val vm: OrbeViewModel by viewModels()
    private var campo = Campo.SERVIDOR

    private val teclado = registerForActivityResult(ActivityResultContracts.StartActivityForResult()) { r ->
        val dados = r.data ?: return@registerForActivityResult
        val texto = RemoteInput.getResultsFromIntent(dados)?.getCharSequence(CHAVE)?.toString()?.trim().orEmpty()
        if (texto.isEmpty()) return@registerForActivityResult
        when (campo) {
            Campo.SERVIDOR -> vm.servidor(texto)
            Campo.TOKEN -> vm.token(texto)
        }
    }

    private val permissao = registerForActivityResult(ActivityResultContracts.RequestPermission()) {}

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        provisionar(intent)
        setContent {
            OrbeApp(
                vm,
                podeGravar = { checkSelfPermission(Manifest.permission.RECORD_AUDIO) == PackageManager.PERMISSION_GRANTED },
                pedirMicrofone = { permissao.launch(Manifest.permission.RECORD_AUDIO) },
                editar = ::editar,
            )
        }
    }

    override fun onNewIntent(intent: Intent) {
        super.onNewIntent(intent)
        provisionar(intent)
    }

    override fun onStart() {
        super.onStart()
        vm.entrou()
    }

    override fun onStop() {
        vm.saiu()
        super.onStop()
    }

    private fun provisionar(i: Intent?) {
        i?.getStringExtra("servidor")?.let(vm::servidor)
        i?.getStringExtra("token")?.let(vm::token)
        // para medir num relógio de verdade: --ef qualidade 0.75 trava a resolução da máscara
        i?.getFloatExtra("qualidade", -1f)?.takeIf { it >= 0f }?.let { Motor.qualidadeFixa = it }
    }

    /** O teclado do relógio (ou o ditado, ou o do celular pareado) para um campo de texto. */
    private fun editar(c: Campo) {
        campo = c
        val pedido = RemoteInputIntentHelper.createActionRemoteInputIntent()
        val entrada = RemoteInput.Builder(CHAVE).setLabel(c.rotulo).build()
        RemoteInputIntentHelper.putRemoteInputsExtra(pedido, listOf(entrada))
        teclado.launch(pedido)
    }

    private companion object {
        const val CHAVE = "texto"
    }
}
