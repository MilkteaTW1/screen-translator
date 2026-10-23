package io.github.milkteatw1.screentranslator

import android.content.Context
import android.net.ConnectivityManager
import java.io.File
import java.io.IOException
import java.net.URL
import kotlin.concurrent.thread

/** A Whisper speech model (whisper.cpp, compressed q5_1): one model hears every language and says which it was. */
class WhisperModel private constructor(private var handle: Long) {
    /** One downloadable model. */
    class Spec(val name: String, val file: String, val megabytes: Int) {
        val url get() = "https://huggingface.co/ggerganov/whisper.cpp/resolve/main/$file"
    }

    companion object {
        init { System.loadLibrary("stwhisper") }

        val models = listOf(Spec("base", "ggml-base-q5_1.bin", 60), Spec("tiny", "ggml-tiny-q5_1.bin", 32))

        fun spec(name: String) = models.firstOrNull { it.name == name } ?: models[0]

        fun file(context: Context, spec: Spec) = File(context.filesDir, "whisper/${spec.file}")

        fun isInstalled(context: Context, spec: Spec) = file(context, spec).length() > 1_000_000

        /** Loads [spec]; null if it is missing or broken. */
        fun load(context: Context, spec: Spec): WhisperModel? {
            val f = file(context, spec)
            if (!f.isFile) return null
            val h = nativeLoadStatic(f.path)
            return if (h != 0L) WhisperModel(h) else null
        }

        private fun nativeLoadStatic(path: String) = WhisperModel(0).nativeLoad(path)

        /** Downloads [spec] once. [done] gets null on success or the error. Runs on its own thread. */
        fun download(context: Context, spec: Spec, wifiOnly: Boolean, progress: (Int) -> Unit, done: (Throwable?) -> Unit) {
            val app = context.applicationContext
            thread(name = "whisper-download") {
                val target = file(app, spec)
                val part = File(target.path + ".part")
                try {
                    val cm = app.getSystemService(Context.CONNECTIVITY_SERVICE) as ConnectivityManager
                    if (wifiOnly && cm.isActiveNetworkMetered) throw IOException("Not on Wi-Fi (an unmetered network)")
                    target.parentFile?.mkdirs()
                    val conn = URL(spec.url).openConnection()
                    val total = conn.contentLengthLong
                    conn.getInputStream().use { input ->
                        part.outputStream().use { out ->
                            val buf = ByteArray(1 shl 16)
                            var got = 0L
                            var last = -1
                            while (true) {
                                val n = input.read(buf)
                                if (n < 0) break
                                out.write(buf, 0, n)
                                got += n
                                val pct = if (total > 0) (got * 100 / total).toInt() else 0
                                if (pct != last) { last = pct; progress(pct) }
                            }
                            if (total > 0 && got < total) throw IOException("download was cut off")
                        }
                    }
                    if (!part.renameTo(target)) throw IOException("could not save the model")
                    done(null)
                } catch (e: Throwable) {
                    part.delete()
                    done(e)
                }
            }
        }
    }

    /** (language code, text) of 16 kHz mono audio; [language] is a code or "auto". Null when nothing was said. */
    @Synchronized
    fun transcribe(audio: FloatArray, threads: Int, language: String = "auto"): Pair<String, String>? {
        if (handle == 0L) return null
        val raw = String(nativeTranscribe(handle, audio, threads, language), Charsets.UTF_8)
        val tab = raw.indexOf('\t')
        if (tab < 0) return null
        val text = raw.substring(tab + 1).trim()
        return if (text.isEmpty()) null else raw.substring(0, tab) to text
    }

    @Synchronized
    fun close() {
        if (handle != 0L) nativeFree(handle)
        handle = 0L
    }

    private external fun nativeLoad(path: String): Long
    private external fun nativeFree(handle: Long)
    private external fun nativeTranscribe(handle: Long, audio: FloatArray, threads: Int, language: String): ByteArray
}
