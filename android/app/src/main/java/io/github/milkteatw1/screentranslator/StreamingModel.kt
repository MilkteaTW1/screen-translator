package io.github.milkteatw1.screentranslator

import android.content.Context
import android.net.ConnectivityManager
import com.k2fsa.sherpa.onnx.EndpointConfig
import com.k2fsa.sherpa.onnx.EndpointRule
import com.k2fsa.sherpa.onnx.OnlineModelConfig
import com.k2fsa.sherpa.onnx.OnlineRecognizer
import com.k2fsa.sherpa.onnx.OnlineRecognizerConfig
import com.k2fsa.sherpa.onnx.OnlineStream
import com.k2fsa.sherpa.onnx.OnlineTransducerModelConfig
import java.io.File
import java.io.IOException
import java.net.URL
import kotlin.concurrent.thread

/**
 * The fast speech models (sherpa-onnx streaming zipformer transducers, the same ones as on the desktop): the words
 * come out while they are still being spoken, instead of after a whole sentence has been read. Each one hears only a
 * few languages, so "Auto" and the languages without one stay with Whisper. Downloaded once, after the user agrees.
 */
object StreamingModel {
    /** One downloadable model: [files] are encoder, decoder, joiner, tokens (in that order). */
    class Spec(val key: String, val repo: String, val megabytes: Int, val files: List<String>, val langs: List<String>) {
        fun url(file: String) = "https://huggingface.co/$repo/resolve/main/$file"
    }

    val models = listOf(
        Spec("zh-en", "csukuangfj/sherpa-onnx-streaming-zipformer-bilingual-zh-en-2023-02-20", 200,
            listOf("encoder-epoch-99-avg-1.int8.onnx", "decoder-epoch-99-avg-1.int8.onnx",
                "joiner-epoch-99-avg-1.int8.onnx", "tokens.txt"), listOf("zh", "en")),
        Spec("en", "csukuangfj/sherpa-onnx-streaming-zipformer-en-2023-06-26", 72,
            listOf("encoder-epoch-99-avg-1-chunk-16-left-128.int8.onnx", "decoder-epoch-99-avg-1-chunk-16-left-128.int8.onnx",
                "joiner-epoch-99-avg-1-chunk-16-left-128.int8.onnx", "tokens.txt"), listOf("en")),
        Spec("ko", "k2-fsa/sherpa-onnx-streaming-zipformer-korean-2024-06-16", 132,
            listOf("encoder-epoch-99-avg-1.int8.onnx", "decoder-epoch-99-avg-1.int8.onnx",
                "joiner-epoch-99-avg-1.int8.onnx", "tokens.txt"), listOf("ko")),
        Spec("multi", "csukuangfj/sherpa-onnx-streaming-zipformer-ar_en_id_ja_ru_th_vi_zh-2025-02-10", 340,
            listOf("encoder-epoch-75-avg-11-chunk-16-left-128.int8.onnx", "decoder-epoch-75-avg-11-chunk-16-left-128.onnx",
                "joiner-epoch-75-avg-11-chunk-16-left-128.int8.onnx", "tokens.txt"),
            listOf("ja", "ru", "th", "vi", "ar", "id")),
    )

    /**
     * The streaming model that reads [language] (a code), or null when only Whisper can: "auto" always goes to
     * Whisper, because each streaming model hears only a few languages (the desktop does the same). English has its
     * own small model; Chinese uses the bilingual one.
     */
    fun specFor(language: String): Spec? {
        if (language == "auto" || language.isBlank()) return null
        val code = language.lowercase()
        if (code == "en") return models.first { it.key == "en" }
        if (code == "zh") return models.first { it.key == "zh-en" }
        return models.firstOrNull { it.key != "zh-en" && code in it.langs }
    }

    /** Fast captions are used when the user chose them and a streaming model reads the spoken language. */
    fun useFor(fast: Boolean, language: String): Spec? = if (fast) specFor(language) else null

    fun folder(context: Context, spec: Spec) = File(context.filesDir, "stream/${spec.key}")

    fun isInstalled(context: Context, spec: Spec) = missingFiles(spec, folder(context, spec)).isEmpty()

    /** Files of [spec] not yet in [folder] (or empty): what a download still has to fetch. */
    fun missingFiles(spec: Spec, folder: File): List<String> =
        spec.files.filter { File(folder, it).length() <= 0L }

    /** Download progress 0..99 from the bytes read so far and the model's nominal size (the real size is not known up front). */
    fun percent(bytes: Long, megabytes: Int): Int =
        (bytes * 100 / (megabytes * 1_000_000L).coerceAtLeast(1)).toInt().coerceIn(0, 99)

    /** The models write English in capitals: sentence case instead (Chinese and the like are left as they are). */
    fun tidy(text: String): String {
        var t = text.trim().split(Regex("\\s+")).filter { it.isNotEmpty() }.joinToString(" ")
        if (t.isNotEmpty() && t == t.uppercase() && t.any { it in 'A'..'Z' }) {
            t = t.lowercase().replace(Regex("\\bi\\b"), "I")
            t = t.substring(0, 1).uppercase() + t.substring(1)
        }
        return t
    }

    /** The language code of what was recognised: the chosen one, or (should "auto" ever be used) Chinese when it has Chinese letters. */
    fun guessLanguage(text: String, spoken: String): String {
        if (spoken != "auto") return spoken
        return if (text.any { it in '㐀'..'鿿' }) "zh" else "en"
    }

    /** Downloads what [spec] is missing. [done] gets null on success or the error. Runs on its own thread. */
    fun download(context: Context, spec: Spec, wifiOnly: Boolean, progress: (Int) -> Unit, done: (Throwable?) -> Unit) {
        val app = context.applicationContext
        thread(name = "stream-download") {
            val dir = folder(app, spec)
            var current: File? = null
            try {
                val cm = app.getSystemService(Context.CONNECTIVITY_SERVICE) as ConnectivityManager
                if (wifiOnly && cm.isActiveNetworkMetered) throw IOException("Not on Wi-Fi (an unmetered network)")
                dir.mkdirs()
                val have = spec.files.filter { it !in missingFiles(spec, dir) }.sumOf { File(dir, it).length() }
                var bytes = have
                var last = -1
                for (name in missingFiles(spec, dir)) {
                    val target = File(dir, name)
                    val part = File(dir, "$name.part")
                    current = part
                    val conn = URL(spec.url(name)).openConnection()
                    val total = conn.contentLengthLong
                    var got = 0L
                    conn.getInputStream().use { input ->
                        part.outputStream().use { out ->
                            val buf = ByteArray(1 shl 16)
                            while (true) {
                                val n = input.read(buf)
                                if (n < 0) break
                                out.write(buf, 0, n)
                                got += n
                                val pct = percent(bytes + got, spec.megabytes)
                                if (pct != last) { last = pct; progress(pct) }
                            }
                        }
                    }
                    if (total > 0 && got < total) throw IOException("download was cut off")
                    if (!part.renameTo(target)) throw IOException("could not save the model")
                    bytes += got
                }
                done(null)
            } catch (e: Throwable) {
                current?.delete()
                done(e)
            }
        }
    }
}

/** One live recogniser (sherpa-onnx): feed 0.1 s chunks, get the text so far and whether the sentence just ended. */
class StreamRecognizer(context: Context, spec: StreamingModel.Spec, threads: Int) {
    private val recognizer: OnlineRecognizer
    private val stream: OnlineStream

    init {
        val dir = StreamingModel.folder(context, spec)
        fun path(i: Int) = File(dir, spec.files[i]).path
        val model = OnlineModelConfig(
            transducer = OnlineTransducerModelConfig(encoder = path(0), decoder = path(1), joiner = path(2)),
            tokens = path(3),
            numThreads = threads,
        )
        val config = OnlineRecognizerConfig(
            modelConfig = model,
            endpointConfig = EndpointConfig(
                EndpointRule(false, 0.8f, 0.0f),   // nothing recognised yet and this much quiet: reset
                EndpointRule(true, 0.5f, 0.0f),    // a sentence was said and this much quiet: it is over
                EndpointRule(false, 0.0f, 10.0f),  // long talk without a pause is cut here
            ),
            enableEndpoint = true,
        )
        recognizer = OnlineRecognizer(null, config)
        stream = recognizer.createStream("")
    }

    /** (text so far, true when the sentence ended). After an end the stream starts over. */
    fun feed(chunk: FloatArray): Pair<String, Boolean> {
        stream.acceptWaveform(chunk, 16000)
        while (recognizer.isReady(stream)) recognizer.decode(stream)
        val text = StreamingModel.tidy(recognizer.getResult(stream).text)
        val ended = recognizer.isEndpoint(stream)
        if (ended) recognizer.reset(stream)
        return text to ended
    }

    fun close() {
        try { stream.release() } catch (_: Throwable) {}
        try { recognizer.release() } catch (_: Throwable) {}
    }
}
