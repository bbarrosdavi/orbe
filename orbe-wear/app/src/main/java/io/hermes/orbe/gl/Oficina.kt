package io.hermes.orbe.gl

import android.content.Context
import android.graphics.BitmapFactory
import android.opengl.GLES30
import android.opengl.GLUtils
import android.util.Log
import io.hermes.orbe.orbe.Skin
import io.hermes.orbe.orbe.Uniformes
import java.io.File
import java.nio.ByteBuffer
import java.nio.ByteOrder
import java.security.MessageDigest

internal const val TAG = "Orbe"

/** Um programa ligado, com os locais dos uniforms achados uma vez só. */
internal class Programa(val id: Int) {
    private val locais = HashMap<String, Int>()

    fun local(nome: String): Int = locais.getOrPut(nome) { GLES30.glGetUniformLocation(id, nome) }

    fun aplicar(u: Uniformes) {
        for ((nome, v) in u.mapa) {
            val l = local(nome)
            if (l < 0) continue          // a variante desta skin não usa este uniform
            when (v.size) {
                1 -> GLES30.glUniform1f(l, v[0])
                2 -> GLES30.glUniform2f(l, v[0], v[1])
                4 -> GLES30.glUniform4f(l, v[0], v[1], v[2], v[3])
            }
        }
    }

    fun v1(nome: String, a: Float) {
        val l = local(nome)
        if (l >= 0) GLES30.glUniform1f(l, a)
    }

    fun v4(nome: String, a: Float, b: Float, c: Float, d: Float) {
        val l = local(nome)
        if (l >= 0) GLES30.glUniform4f(l, a, b, c, d)
    }

    fun amostrador(nome: String, unidade: Int) {
        val l = local(nome)
        if (l >= 0) GLES30.glUniform1i(l, unidade)
    }
}

/**
 * Programas e texturas do orbe, feitos sob demanda no contexto do Motor: os
 * .frag do orbe-qt (assets/shaders) convertidos pelo Sombreador e os atlas das
 * skins de imagem e do anel (assets/arte).
 *
 * O figura.frag é grande: a primeira compilação pesa num relógio. O binário do
 * programa ligado fica em cache, e da segunda abertura em diante ele vem pronto.
 */
internal class Oficina(private val ctx: Context) {
    private val programas = HashMap<String, Programa?>()
    private val texturas = HashMap<String, Int>()
    private val pasta = File(ctx.cacheDir, "programas").apply { mkdirs() }
    private val gpu: String by lazy {
        listOf(GLES30.GL_VENDOR, GLES30.GL_RENDERER, GLES30.GL_VERSION).joinToString("|") { GLES30.glGetString(it) ?: "" }
    }
    // marca de que esta GPU não aceita de volta o binário que entrega (o tradutor do emulador)
    private val recusa: File by lazy { File(pasta, "recusa-" + sha1(gpu)) }
    private val temBinario: Boolean by lazy {
        val n = IntArray(1)
        GLES30.glGetIntegerv(GLES30.GL_NUM_PROGRAM_BINARY_FORMATS, n, 0)
        val tem = n[0] > 0 && !recusa.exists()
        if (!tem) Log.i(TAG, "sem cache de programas nesta GPU: os shaders compilam a cada abertura")
        tem
    }

    /** Primeiro passe da skin; null se o shader não compila nesta GPU. */
    fun figura(skin: Skin): Programa? = programa(skin.shader, skin.definicoes)

    /**
     * O primeiro passe das skins desenhadas por elemento (o Ophanim): o próprio
     * figura.frag é o vértice (VERTICE) e o fragmento (PRIMITIVAS); ver o fim do
     * arquivo. null nas outras skins ou se não compila nesta GPU.
     */
    fun primitivas(skin: Skin): Programa? =
        if (!skin.primitivas) null else programa(skin.shader, skin.definicoes + ("PRIMITIVAS" to 1), comVertice = true)

    /** Segundo passe: cor, glitch e sombra. */
    fun pos(): Programa? = programa("pos.frag", emptyMap())

    private fun programa(arquivo: String, definicoes: Map<String, Int>, comVertice: Boolean = false): Programa? {
        val chave = arquivo + definicoes
        if (programas.containsKey(chave)) return programas[chave]
        val p = try {
            val fonte = ctx.assets.open("shaders/$arquivo").bufferedReader().use { it.readText() }
            val vertice = if (comVertice) Sombreador.paraEs(fonte, definicoes + ("VERTICE" to 1)) else Sombreador.VERTICE
            montar(vertice, Sombreador.paraEs(fonte, definicoes), chave)
        } catch (e: Exception) {
            Log.e(TAG, "shader $chave: ${e.message}")
            null
        }
        programas[chave] = p
        return p
    }

    private fun montar(vertice: String, fragmento: String, nome: String): Programa {
        val t0 = System.nanoTime()
        val cache = File(pasta, sha1(vertice + fragmento + gpu) + ".bin")
        doCache(cache)?.let {
            Log.i(TAG, "programa $nome: do cache em ${(System.nanoTime() - t0) / 1_000_000} ms")
            return Programa(it)
        }
        val vs = compilar(GLES30.GL_VERTEX_SHADER, vertice)
        val fs = compilar(GLES30.GL_FRAGMENT_SHADER, fragmento)
        val id = GLES30.glCreateProgram()
        GLES30.glAttachShader(id, vs)
        GLES30.glAttachShader(id, fs)
        GLES30.glLinkProgram(id)
        GLES30.glDeleteShader(vs)
        GLES30.glDeleteShader(fs)
        val ok = IntArray(1)
        GLES30.glGetProgramiv(id, GLES30.GL_LINK_STATUS, ok, 0)
        if (ok[0] == 0) {
            val log = GLES30.glGetProgramInfoLog(id)
            GLES30.glDeleteProgram(id)
            error("link: $log")
        }
        Log.i(TAG, "programa $nome: compilado em ${(System.nanoTime() - t0) / 1_000_000} ms")
        paraCache(id, cache)
        return Programa(id)
    }

    private fun compilar(tipo: Int, fonte: String): Int {
        val s = GLES30.glCreateShader(tipo)
        GLES30.glShaderSource(s, fonte)
        GLES30.glCompileShader(s)
        val ok = IntArray(1)
        GLES30.glGetShaderiv(s, GLES30.GL_COMPILE_STATUS, ok, 0)
        if (ok[0] == 0) {
            val log = GLES30.glGetShaderInfoLog(s)
            GLES30.glDeleteShader(s)
            error("compilação: $log")
        }
        return s
    }

    private fun doCache(arq: File): Int? {
        if (!temBinario || recusa.exists() || !arq.isFile) return null
        return try {
            val bruto = arq.readBytes()
            val buf = ByteBuffer.wrap(bruto).order(ByteOrder.LITTLE_ENDIAN)
            val formato = buf.int
            val dados = ByteBuffer.allocateDirect(bruto.size - 4).put(bruto, 4, bruto.size - 4)
            dados.position(0)
            val id = GLES30.glCreateProgram()
            GLES30.glProgramBinary(id, formato, dados, bruto.size - 4)
            val ok = IntArray(1)
            GLES30.glGetProgramiv(id, GLES30.GL_LINK_STATUS, ok, 0)
            val erro = GLES30.glGetError()
            // ligado e com a interface de sempre (todo shader do orbe tem o uniform tam)
            if (ok[0] == 0 || erro != GLES30.GL_NO_ERROR || GLES30.glGetUniformLocation(id, "tam") < 0) {
                Log.i(TAG, "binário recusado (link ${ok[0]}, erro 0x${Integer.toHexString(erro)}): recompila")
                GLES30.glDeleteProgram(id)
                arq.delete()
                // gravado por esta mesma GPU e recusado: não adianta guardar de novo
                recusa.createNewFile()
                null
            } else id
        } catch (e: Exception) {
            arq.delete()
            null
        }
    }

    private fun paraCache(id: Int, arq: File) {
        if (!temBinario || recusa.exists()) return
        try {
            val tam = IntArray(1)
            GLES30.glGetProgramiv(id, GLES30.GL_PROGRAM_BINARY_LENGTH, tam, 0)
            if (tam[0] <= 0) {
                Log.i(TAG, "programa sem binário (tamanho ${tam[0]})")
                return
            }
            val dados = ByteBuffer.allocateDirect(tam[0])
            val lido = IntArray(1)
            val formato = IntArray(1)
            GLES30.glGetProgramBinary(id, tam[0], lido, 0, formato, 0, dados)
            val erro = GLES30.glGetError()
            if (erro != GLES30.GL_NO_ERROR || lido[0] <= 0) {
                Log.i(TAG, "binário não saiu (erro 0x${Integer.toHexString(erro)}, ${lido[0]} bytes)")
                return
            }
            val bytes = ByteArray(lido[0])
            dados.position(0)
            dados.get(bytes)
            val cab = ByteBuffer.allocate(4).order(ByteOrder.LITTLE_ENDIAN).putInt(formato[0]).array()
            val tmp = File(arq.path + ".tmp")
            tmp.outputStream().use { it.write(cab); it.write(bytes) }
            tmp.renameTo(arq)
        } catch (e: Exception) {
            Log.w(TAG, "cache do programa: ${e.message}")
        }
    }

    private fun sha1(s: String): String =
        MessageDigest.getInstance("SHA-1").digest(s.toByteArray()).joinToString("") { "%02x".format(it) }

    /** Atlas da skin (0 se ela não tem), com mipmap: o glow do anel e a redução das gravuras leem os níveis baixos. */
    fun textura(skin: Skin): Int {
        val nome = skin.arte ?: return 0
        texturas[nome]?.let { return it }
        var id = 0
        try {
            val op = BitmapFactory.Options().apply { inSampleSize = skin.reducao; inScaled = false }
            val bmp = ctx.assets.open("arte/$nome").use { BitmapFactory.decodeStream(it, null, op) }
                ?: error("não decodificou")
            val ids = IntArray(1)
            GLES30.glGenTextures(1, ids, 0)
            id = ids[0]
            GLES30.glBindTexture(GLES30.GL_TEXTURE_2D, id)
            GLUtils.texImage2D(GLES30.GL_TEXTURE_2D, 0, bmp, 0)
            bmp.recycle()
            GLES30.glGenerateMipmap(GLES30.GL_TEXTURE_2D)
            GLES30.glTexParameteri(GLES30.GL_TEXTURE_2D, GLES30.GL_TEXTURE_MIN_FILTER, GLES30.GL_LINEAR_MIPMAP_LINEAR)
            GLES30.glTexParameteri(GLES30.GL_TEXTURE_2D, GLES30.GL_TEXTURE_MAG_FILTER, GLES30.GL_LINEAR)
            GLES30.glTexParameteri(GLES30.GL_TEXTURE_2D, GLES30.GL_TEXTURE_WRAP_S, GLES30.GL_CLAMP_TO_EDGE)
            GLES30.glTexParameteri(GLES30.GL_TEXTURE_2D, GLES30.GL_TEXTURE_WRAP_T, GLES30.GL_CLAMP_TO_EDGE)
        } catch (e: Exception) {
            Log.e(TAG, "atlas $nome: ${e.message}")
        }
        texturas[nome] = id
        return id
    }
}
