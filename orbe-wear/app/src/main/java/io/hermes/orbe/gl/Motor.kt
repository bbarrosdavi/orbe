package io.hermes.orbe.gl

import android.annotation.SuppressLint
import android.content.Context
import android.content.SharedPreferences
import android.graphics.SurfaceTexture
import android.opengl.EGL14
import android.opengl.EGLConfig
import android.opengl.EGLContext
import android.opengl.EGLDisplay
import android.opengl.EGLSurface
import android.opengl.GLES30
import android.os.Handler
import android.os.HandlerThread
import android.util.Log
import android.view.Choreographer
import io.hermes.orbe.orbe.Arte
import io.hermes.orbe.orbe.Skin
import java.nio.ByteBuffer
import java.nio.ByteOrder
import kotlin.math.max
import kotlin.math.min
import kotlin.math.roundToInt
import kotlin.math.sqrt

/**
 * A thread que desenha todos os orbes da tela (o grande e as miniaturas do
 * menu) num contexto GL só: uma superfície por OrbeView, os programas e os
 * atlas compartilhados.
 *
 * Cada orbe sai em dois passes, como no Qt Quick do desktop: o shader da figura
 * pinta a máscara num FBO (o "layer" do item) e o pos.frag lê a máscara e dá a
 * cor, a aberração e o glitch. A animação anda no vsync, a 30 quadros por
 * segundo (20 com o orbe à espera), e para quando não há orbe à vista.
 *
 * Diagnóstico num relógio de verdade: adb shell setprop log.tag.Orbe VERBOSE
 * mostra, a cada 2 s, os quadros por segundo, os atrasados e o custo do
 * primeiro passe.
 */
internal object Motor {
    private const val INTERVALO_NS = 30_000_000L          // um quadro sim, um não, num painel de 60 Hz
    private const val INTERVALO_CALMO_NS = 46_000_000L    // um em três: o orbe à espera gasta menos bateria
    // Miniaturas desenhadas por quadro, em rodízio. Medido no TicWatch Pro 5: com
    // as cinco do menu no mesmo quadro, a GPU ficava ocupada de uma vez só e a
    // rolagem da tela perdia quadros (90% deles acima de 150 ms).
    private const val MINIATURAS_POR_QUADRO = 2
    private const val EGL_OPENGL_ES3_BIT = 0x40

    private var handler: Handler? = null
    @SuppressLint("StaticFieldLeak")                         // guarda o contexto do app, não o de uma tela
    private var oficina: Oficina? = null
    private var tela: EGLDisplay = EGL14.EGL_NO_DISPLAY
    private var contexto: EGLContext = EGL14.EGL_NO_CONTEXT
    private var config: EGLConfig? = null
    private var reserva: EGLSurface = EGL14.EGL_NO_SURFACE   // 1x1, para ter o contexto sem janela
    private val alvos = ArrayList<Alvo>()
    private var rodando = false
    private var ultimoNs = 0L
    private var vez = 0                   // de quem é a vez no rodízio das miniaturas

    private class Alvo(val view: OrbeView, val st: SurfaceTexture, var w: Int, var h: Int) {
        var egl: EGLSurface = EGL14.EGL_NO_SURFACE
        var desenhadoEm = 0L         // cada orbe anda pelo tempo desde o próprio último quadro
        var fbo = 0
        var mascara = 0
        var fw = 0
        var fh = 0
    }

    /** Qualidade da máscara travada (0 = o Motor ajusta sozinho); para medir num relógio de verdade. */
    @Volatile var qualidadeFixa = 0f

    // ── a resolução da máscara do orbe grande, pelo que a GPU do relógio dá conta ──
    //
    // O critério são os quadros que perdem a vez, não o custo do primeiro passe:
    // a GPU baixa a frequência quando sobra tempo, e o custo medido engana.
    // Medido no TicWatch Pro 5 (Adreno 702, 466 px): o anel de energia roda a
    // 100% (25 a 30 quadros por segundo); o Ophanim leva 150 ms por quadro a
    // 100% e 25 a 40 ms a 50%, que é onde ele fica. Cada skin tem o seu shader,
    // então cada uma tem a sua qualidade, guardada entre uma abertura e outra.
    private const val JANELA_NS = 2_000_000_000L
    private const val QUALIDADE_MIN = 0.375f
    private var qualidade = 1f            // fração da resolução do primeiro passe
    private var teto = 1f                 // subir além disto já deu atraso nesta execução
    private var skinGrande: Skin? = null  // a skin do orbe grande neste quadro
    private var skinMedida: Skin? = null  // de qual skin é a qualidade em uso
    private var guardado: SharedPreferences? = null
    private var janelaDesde = 0L
    private var naJanela = 0
    private var atrasados = 0
    private var ruins = 0                 // janelas seguidas com a maioria dos quadros atrasada
    private var boas = 0
    private var subiuEm = 0L
    private var somaMascaraMs = 0f        // diagnóstico: custo do primeiro passe do orbe grande
    private var somaLacoMs = 0f
    private var desenhados = 0

    @Synchronized
    private fun fio(ctx: Context): Handler {
        handler?.let { return it }
        val t = HandlerThread("orbe-gl").apply { start() }
        val h = Handler(t.looper)
        val app = ctx.applicationContext
        h.post { abrir(app) }
        handler = h
        return h
    }

    fun ligar(view: OrbeView, st: SurfaceTexture, w: Int, h: Int) {
        fio(view.context).post {
            if (contexto == EGL14.EGL_NO_CONTEXT) return@post
            val a = Alvo(view, st, w, h)
            a.egl = EGL14.eglCreateWindowSurface(tela, config, st, intArrayOf(EGL14.EGL_NONE), 0)
            if (a.egl == EGL14.EGL_NO_SURFACE) {
                Log.e(TAG, "superfície: erro EGL 0x${Integer.toHexString(EGL14.eglGetError())}")
                return@post
            }
            alvos.add(a)
            if (!rodando) {
                rodando = true
                ultimoNs = 0L
                Choreographer.getInstance().postFrameCallback(::quadro)
            }
        }
    }

    fun redimensionar(view: OrbeView, w: Int, h: Int) {
        handler?.post {
            alvos.firstOrNull { it.view === view }?.let { it.w = w; it.h = h }
        }
    }

    /** A superfície vai embora; a SurfaceTexture é solta aqui, depois da superfície EGL. */
    fun desligar(view: OrbeView, st: SurfaceTexture) {
        val h = handler
        if (h == null) {
            st.release()
            return
        }
        h.post {
            val a = alvos.firstOrNull { it.view === view && it.st === st }
            if (a != null) {
                alvos.remove(a)
                EGL14.eglMakeCurrent(tela, reserva, reserva, contexto)
                if (a.fbo != 0) {
                    GLES30.glDeleteFramebuffers(1, intArrayOf(a.fbo), 0)
                    GLES30.glDeleteTextures(1, intArrayOf(a.mascara), 0)
                }
                EGL14.eglDestroySurface(tela, a.egl)
            }
            st.release()
        }
    }

    private fun abrir(app: Context) {
        tela = EGL14.eglGetDisplay(EGL14.EGL_DEFAULT_DISPLAY)
        val versao = IntArray(2)
        if (!EGL14.eglInitialize(tela, versao, 0, versao, 1)) {
            Log.e(TAG, "EGL não iniciou")
            return
        }
        val pedido = intArrayOf(
            EGL14.EGL_RED_SIZE, 8, EGL14.EGL_GREEN_SIZE, 8, EGL14.EGL_BLUE_SIZE, 8, EGL14.EGL_ALPHA_SIZE, 8,
            EGL14.EGL_RENDERABLE_TYPE, EGL_OPENGL_ES3_BIT,
            EGL14.EGL_SURFACE_TYPE, EGL14.EGL_WINDOW_BIT or EGL14.EGL_PBUFFER_BIT,
            EGL14.EGL_NONE,
        )
        val configs = arrayOfNulls<EGLConfig>(1)
        val n = IntArray(1)
        if (!EGL14.eglChooseConfig(tela, pedido, 0, configs, 0, 1, n, 0) || n[0] == 0) {
            Log.e(TAG, "sem config EGL para o OpenGL ES 3")
            return
        }
        config = configs[0]
        contexto = EGL14.eglCreateContext(tela, config, EGL14.EGL_NO_CONTEXT,
            intArrayOf(EGL14.EGL_CONTEXT_CLIENT_VERSION, 3, EGL14.EGL_NONE), 0)
        if (contexto == EGL14.EGL_NO_CONTEXT) {
            Log.e(TAG, "sem contexto OpenGL ES 3")
            return
        }
        reserva = EGL14.eglCreatePbufferSurface(tela, config,
            intArrayOf(EGL14.EGL_WIDTH, 1, EGL14.EGL_HEIGHT, 1, EGL14.EGL_NONE), 0)
        EGL14.eglMakeCurrent(tela, reserva, reserva, contexto)
        oficina = Oficina(app)
        guardado = app.getSharedPreferences("motor", Context.MODE_PRIVATE)

        // o quadrado dos dois passes
        val v = floatArrayOf(-1f, -1f, 1f, -1f, -1f, 1f, 1f, 1f)
        val buf = ByteBuffer.allocateDirect(v.size * 4).order(ByteOrder.nativeOrder()).asFloatBuffer().put(v)
        buf.position(0)
        val ids = IntArray(1)
        GLES30.glGenVertexArrays(1, ids, 0)
        GLES30.glBindVertexArray(ids[0])
        GLES30.glGenBuffers(1, ids, 0)
        GLES30.glBindBuffer(GLES30.GL_ARRAY_BUFFER, ids[0])
        GLES30.glBufferData(GLES30.GL_ARRAY_BUFFER, v.size * 4, buf, GLES30.GL_STATIC_DRAW)
        GLES30.glEnableVertexAttribArray(0)
        GLES30.glVertexAttribPointer(0, 2, GLES30.GL_FLOAT, false, 0, 0)
        Log.i(TAG, "GL: ${GLES30.glGetString(GLES30.GL_RENDERER)} / ${GLES30.glGetString(GLES30.GL_VERSION)}")
    }

    private fun quadro(agoraNs: Long) {
        if (alvos.isEmpty()) {
            rodando = false          // nada à vista: a thread dorme até o próximo ligar()
            return
        }
        Choreographer.getInstance().postFrameCallback(::quadro)
        var calmo = true
        for (i in alvos.indices) if (alvos[i].view.aVista && !alvos[i].view.cena.calma) calmo = false
        val intervalo = if (calmo) INTERVALO_CALMO_NS else INTERVALO_NS
        if (ultimoNs != 0L && agoraNs - ultimoNs < intervalo) return
        val passou = if (ultimoNs == 0L) 0L else agoraNs - ultimoNs
        ultimoNs = agoraNs
        val t0 = System.nanoTime()
        var grande = false
        var n = 0
        var miniaturas = 0
        val primeiro = vez
        for (k in alvos.indices) {
            val i = (primeiro + k) % alvos.size
            val a = alvos[i]
            if (!a.view.aVista || a.view.parado || a.w <= 0 || a.h <= 0) continue
            if (!a.view.adaptar) {
                if (miniaturas >= MINIATURAS_POR_QUADRO) continue
                miniaturas++
                vez = i + 1
            }
            try {
                desenhar(a, if (a.desenhadoEm == 0L) 1.0 / 30 else (agoraNs - a.desenhadoEm) / 1e9)
                a.desenhadoEm = agoraNs
                n++
                if (a.view.adaptar) grande = true
            } catch (e: Exception) {
                Log.e(TAG, "quadro: ${e.message}")
            }
        }
        somaLacoMs += (System.nanoTime() - t0) / 1e6f
        desenhados += n
        // só as janelas com o orbe grande na tela contam para a qualidade dele
        if (grande) avaliar(agoraNs, passou, intervalo) else janelaDesde = 0L
    }

    /**
     * Perdeu a vez o quadro que saiu mais de um vsync depois do combinado. Com a
     * maioria deles atrasada por duas janelas seguidas (abaixo de uns 22 por
     * segundo), a máscara desce até onde os quadros cabem; meio minuto sem
     * atraso, volta um degrau. Se a volta atrasa de novo, aquele fica sendo o teto.
     */
    private fun avaliar(agoraNs: Long, passou: Long, intervalo: Long) {
        val skin = skinGrande
        if (skin != skinMedida) {
            // outra skin, outro shader: vale o que se aprendeu dela, ou começa inteira
            skinMedida = skin
            qualidade = guardado?.getFloat("qualidade_${skin?.id}", 1f)?.coerceIn(QUALIDADE_MIN, 1f) ?: 1f
            teto = 1f
            ruins = 0
            boas = 0
            janelaDesde = 0L
        }
        if (janelaDesde == 0L) {
            janelaDesde = agoraNs
            zerarJanela()
            return
        }
        naJanela++
        if (passou > intervalo * 16 / 10) atrasados++
        if (agoraNs - janelaDesde < JANELA_NS) return
        val fracao = atrasados.toFloat() / naJanela
        if (Log.isLoggable(TAG, Log.VERBOSE)) {
            Log.v(TAG, "%.1f quadros/s, %d%% atrasados; máscara a %d%%, %.1f ms; %.1f orbes, laço de %.1f ms".format(
                naJanela * 1e9f / (agoraNs - janelaDesde), (fracao * 100).roundToInt(), (qualidade * 100).roundToInt(),
                somaMascaraMs / naJanela, desenhados.toFloat() / naJanela, somaLacoMs / naJanela))
        }
        if (qualidadeFixa > 0f) {
            qualidade = qualidadeFixa
        } else {
            when {
                fracao > 0.6f -> { ruins++; boas = 0 }
                fracao < 0.1f -> { boas++; ruins = 0 }
                else -> { ruins = 0; boas = 0 }
            }
            val antes = qualidade
            if (ruins >= 2 && qualidade > QUALIDADE_MIN) {
                if (agoraNs - subiuEm < 20_000_000_000L) teto = qualidade - 0.125f
                // o custo acompanha a área: desce de uma vez até onde os quadros cabem
                val qps = naJanela * 1e9f / (agoraNs - janelaDesde)
                val cabe = qualidade * sqrt(qps / (0.9f * 1e9f / (intervalo * 10 / 9)))
                qualidade = ((cabe * 8).roundToInt() / 8f).coerceIn(QUALIDADE_MIN, qualidade - 0.125f)
                ruins = 0
                Log.i(TAG, "máscara a ${(qualidade * 100).roundToInt()}%: saíam ${qps.roundToInt()} quadros por segundo")
            } else if (boas >= 15 && qualidade < teto) {
                qualidade += 0.125f
                boas = 0
                subiuEm = agoraNs
                Log.i(TAG, "máscara a ${(qualidade * 100).roundToInt()}%")
            }
            if (qualidade != antes) guardado?.edit()?.putFloat("qualidade_${skin?.id}", qualidade)?.apply()
        }
        janelaDesde = agoraNs
        zerarJanela()
    }

    private fun zerarJanela() {
        naJanela = 0
        atrasados = 0
        somaMascaraMs = 0f
        somaLacoMs = 0f
        desenhados = 0
    }

    private fun desenhar(a: Alvo, dt: Double) {
        val of = oficina ?: return
        if (!EGL14.eglMakeCurrent(tela, a.egl, a.egl, contexto)) return
        val dens = a.view.densidade
        val wl = (a.w / dens).toDouble()
        val hl = (a.h / dens).toDouble()
        val arte = a.view.cena.passo(dt, wl, hl)
        if (a.view.adaptar) skinGrande = arte.skin
        val figura = of.figura(arte.skin)
        val pos = of.pos()

        GLES30.glBindFramebuffer(GLES30.GL_FRAMEBUFFER, 0)
        GLES30.glViewport(0, 0, a.w, a.h)
        GLES30.glDisable(GLES30.GL_SCISSOR_TEST)
        GLES30.glClearColor(0f, 0f, 0f, 0f)
        if (figura == null || pos == null) {
            GLES30.glClear(GLES30.GL_COLOR_BUFFER_BIT)
            EGL14.eglSwapBuffers(tela, a.egl)
            return
        }

        // ── primeiro passe: a máscara, no FBO (o "layer" do item no Qt) ──
        val t0 = System.nanoTime()
        mascara(a)
        GLES30.glBindFramebuffer(GLES30.GL_FRAMEBUFFER, a.fbo)
        GLES30.glViewport(0, 0, a.fw, a.fh)
        GLES30.glClear(GLES30.GL_COLOR_BUFFER_BIT)
        recortar(a, arte, wl, hl)
        GLES30.glDisable(GLES30.GL_BLEND)
        GLES30.glUseProgram(figura.id)
        figura.aplicar(arte.fx)
        figura.v1("qt_Opacity", 1f)
        figura.v4("uvT", 1f, 1f, 0f, 0f)
        val atlas = of.textura(arte.skin)
        if (atlas != 0) {
            GLES30.glActiveTexture(GLES30.GL_TEXTURE0)
            GLES30.glBindTexture(GLES30.GL_TEXTURE_2D, atlas)
            figura.amostrador("arte", 0)
            figura.amostrador("atlas", 0)
        }
        GLES30.glDrawArrays(GLES30.GL_TRIANGLE_STRIP, 0, 4)      // o quadrado ficou ligado no abrir()
        GLES30.glDisable(GLES30.GL_SCISSOR_TEST)
        if (a.view.adaptar && Log.isLoggable(TAG, Log.VERBOSE)) {
            GLES30.glFinish()            // só no diagnóstico: esperar a GPU a cada quadro custa quadros
            somaMascaraMs += (System.nanoTime() - t0) / 1e6f
        }

        // ── segundo passe: cor, aberração e glitch, direto na superfície ──
        GLES30.glBindFramebuffer(GLES30.GL_FRAMEBUFFER, 0)
        GLES30.glViewport(0, 0, a.w, a.h)
        GLES30.glClear(GLES30.GL_COLOR_BUFFER_BIT)
        GLES30.glEnable(GLES30.GL_BLEND)
        GLES30.glBlendFunc(GLES30.GL_ONE, GLES30.GL_ONE_MINUS_SRC_ALPHA)   // cor pré-multiplicada
        GLES30.glUseProgram(pos.id)
        pos.aplicar(arte.pos)
        pos.v1("qt_Opacity", 1f)
        pos.v4("uvT", 1f, -1f, 0f, 1f)                                      // a tela tem o y para baixo
        GLES30.glActiveTexture(GLES30.GL_TEXTURE0)
        GLES30.glBindTexture(GLES30.GL_TEXTURE_2D, a.mascara)
        pos.amostrador("source", 0)
        GLES30.glDrawArrays(GLES30.GL_TRIANGLE_STRIP, 0, 4)
        EGL14.eglSwapBuffers(tela, a.egl)
    }

    /** O FBO da máscara: no tamanho da superfície; no orbe grande, vezes a qualidade. */
    private fun mascara(a: Alvo) {
        val q = if (a.view.adaptar) qualidade else 1f
        val fw = max(8, (a.w * q).roundToInt())
        val fh = max(8, (a.h * q).roundToInt())
        if (a.fbo != 0 && fw == a.fw && fh == a.fh) return
        val ids = IntArray(1)
        if (a.fbo == 0) {
            GLES30.glGenFramebuffers(1, ids, 0)
            a.fbo = ids[0]
            GLES30.glGenTextures(1, ids, 0)
            a.mascara = ids[0]
        }
        a.fw = fw
        a.fh = fh
        GLES30.glBindTexture(GLES30.GL_TEXTURE_2D, a.mascara)
        GLES30.glTexImage2D(GLES30.GL_TEXTURE_2D, 0, GLES30.GL_RGBA8, fw, fh, 0, GLES30.GL_RGBA, GLES30.GL_UNSIGNED_BYTE, null)
        GLES30.glTexParameteri(GLES30.GL_TEXTURE_2D, GLES30.GL_TEXTURE_MIN_FILTER, GLES30.GL_LINEAR)
        GLES30.glTexParameteri(GLES30.GL_TEXTURE_2D, GLES30.GL_TEXTURE_MAG_FILTER, GLES30.GL_LINEAR)
        GLES30.glTexParameteri(GLES30.GL_TEXTURE_2D, GLES30.GL_TEXTURE_WRAP_S, GLES30.GL_CLAMP_TO_EDGE)
        GLES30.glTexParameteri(GLES30.GL_TEXTURE_2D, GLES30.GL_TEXTURE_WRAP_T, GLES30.GL_CLAMP_TO_EDGE)
        GLES30.glBindFramebuffer(GLES30.GL_FRAMEBUFFER, a.fbo)
        GLES30.glFramebufferTexture2D(GLES30.GL_FRAMEBUFFER, GLES30.GL_COLOR_ATTACHMENT0, GLES30.GL_TEXTURE_2D, a.mascara, 0)
    }

    /** Só a célula da figura é pintada: fora dela a máscara é vazia de qualquer jeito. */
    private fun recortar(a: Alvo, arte: Arte, wl: Double, hl: Double) {
        val r = arte.recorte
        if (r[2] * 2 >= wl && r[3] * 2 >= hl) return
        val sx = a.fw / wl
        val sy = a.fh / hl
        val x0 = max(0.0, (r[0] - r[2]) * sx).toInt()
        val y0 = max(0.0, (r[1] - r[3]) * sy).toInt()      // no FBO o y lógico cresce para cima
        val x1 = min(a.fw.toDouble(), (r[0] + r[2]) * sx + 1).toInt()
        val y1 = min(a.fh.toDouble(), (r[1] + r[3]) * sy + 1).toInt()
        if (x1 <= x0 || y1 <= y0) return
        GLES30.glEnable(GLES30.GL_SCISSOR_TEST)
        GLES30.glScissor(x0, y0, x1 - x0, y1 - y0)
    }
}
