package io.github.milkteatw1.screentranslator

import android.content.Context
import android.net.ConnectivityManager
import java.io.File
import java.io.IOException
import java.net.URL
import java.util.zip.ZipInputStream
import kotlin.concurrent.thread

/** An offline Vosk speech model. Downloaded once, only after the user agrees. */
class VoskModel(val name: String, val megabytes: Int) {
    val url get() = "https://alphacephei.com/vosk/models/$name.zip"
}

object VoskModels {
    private val byCode = mapOf(
        "en" to VoskModel("vosk-model-small-en-us-0.15", 41),
        "zh" to VoskModel("vosk-model-small-cn-0.22", 44),
        "ja" to VoskModel("vosk-model-small-ja-0.22", 50),
        "ko" to VoskModel("vosk-model-small-ko-0.22", 87),
        "fr" to VoskModel("vosk-model-small-fr-0.22", 42),
        "de" to VoskModel("vosk-model-small-de-0.15", 46),
        "es" to VoskModel("vosk-model-small-es-0.42", 40),
        "it" to VoskModel("vosk-model-small-it-0.22", 50),
        "pt" to VoskModel("vosk-model-small-pt-0.3", 32),
        "vi" to VoskModel("vosk-model-small-vn-0.4", 34),
    )

    /** Languages speech can be recognised in. */
    val languages: List<Lang> = Langs.sources.filter { it.code in byCode }

    fun forLang(lang: Lang): VoskModel = byCode.getValue(lang.code)

    fun dir(context: Context, model: VoskModel) = File(context.filesDir, "vosk/${model.name}")

    fun isInstalled(context: Context, model: VoskModel) = File(dir(context, model), "am").isDirectory

    /** Downloads and unpacks [model]. [done] gets null on success or the error. Runs on its own thread. */
    fun download(context: Context, model: VoskModel, wifiOnly: Boolean, progress: (Int) -> Unit, done: (Throwable?) -> Unit) {
        val app = context.applicationContext
        thread(name = "vosk-download") {
            val zip = File(app.cacheDir, "${model.name}.zip")
            try {
                val cm = app.getSystemService(Context.CONNECTIVITY_SERVICE) as ConnectivityManager
                if (wifiOnly && cm.isActiveNetworkMetered) throw IOException("Not on Wi-Fi (an unmetered network)")
                val conn = URL(model.url).openConnection()
                val total = conn.contentLengthLong
                conn.getInputStream().use { input ->
                    zip.outputStream().use { out ->
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
                    }
                }
                val base = File(app.filesDir, "vosk").apply { mkdirs() }
                ZipInputStream(zip.inputStream()).use { zin ->
                    while (true) {
                        val entry = zin.nextEntry ?: break
                        val target = File(base, entry.name).canonicalFile
                        if (!target.path.startsWith(base.canonicalPath + File.separator)) continue  // zip-slip guard
                        if (entry.isDirectory) target.mkdirs() else {
                            target.parentFile?.mkdirs()
                            target.outputStream().use { zin.copyTo(it) }
                        }
                    }
                }
                done(null)
            } catch (e: Throwable) {
                dir(app, model).deleteRecursively()
                done(e)
            } finally {
                zip.delete()
            }
        }
    }
}
