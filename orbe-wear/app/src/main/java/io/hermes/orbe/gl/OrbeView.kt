package io.hermes.orbe.gl

import android.annotation.SuppressLint
import android.content.Context
import android.graphics.Rect
import android.graphics.SurfaceTexture
import android.view.TextureView
import android.view.ViewTreeObserver
import io.hermes.orbe.orbe.Cena
import io.hermes.orbe.orbe.MiniCena
import io.hermes.orbe.orbe.Skin

/**
 * Um orbe na tela: a superfície onde o Motor desenha a [cena]. Transparente,
 * para ficar sobre o fundo do app como o item do Qt Quick fica sobre o vidro.
 */
@SuppressLint("ViewConstructor")
class OrbeView(ctx: Context, cenaInicial: Cena = MiniCena(Skin.OFANIM)) :
    TextureView(ctx), TextureView.SurfaceTextureListener, ViewTreeObserver.OnPreDrawListener {

    @Volatile var cena: Cena = cenaInicial
    /** O orbe grande: a resolução da máscara dele baixa quando a GPU do relógio não dá conta. */
    @Volatile var adaptar = false
    /** Fica no último quadro (a miniatura com a tela rolando, a página que entra na lista). */
    @Volatile var parado = false
    /** Fora da tela (rolado para fora, outra página) o Motor pula este orbe. */
    @Volatile var aVista = true
        private set
    val densidade: Float = ctx.resources.displayMetrics.density

    private val visivel = Rect()

    init {
        isOpaque = false
        surfaceTextureListener = this
    }

    override fun onAttachedToWindow() {
        super.onAttachedToWindow()
        viewTreeObserver.addOnPreDrawListener(this)
    }

    override fun onDetachedFromWindow() {
        viewTreeObserver.removeOnPreDrawListener(this)
        super.onDetachedFromWindow()
    }

    override fun onPreDraw(): Boolean {
        aVista = isShown && getGlobalVisibleRect(visivel)
        return true
    }

    override fun onSurfaceTextureAvailable(st: SurfaceTexture, w: Int, h: Int) = Motor.ligar(this, st, w, h)

    override fun onSurfaceTextureSizeChanged(st: SurfaceTexture, w: Int, h: Int) = Motor.redimensionar(this, w, h)

    override fun onSurfaceTextureDestroyed(st: SurfaceTexture): Boolean {
        Motor.desligar(this, st)
        return false                 // quem solta a SurfaceTexture é o Motor, depois da superfície EGL
    }

    override fun onSurfaceTextureUpdated(st: SurfaceTexture) {}
}
