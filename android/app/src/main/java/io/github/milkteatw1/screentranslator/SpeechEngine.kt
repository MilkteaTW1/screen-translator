package io.github.milkteatw1.screentranslator

import android.annotation.SuppressLint
import android.content.Context
import android.media.AudioAttributes
import android.media.AudioFormat
import android.media.AudioPlaybackCaptureConfiguration
import android.media.AudioRecord
import android.media.MediaRecorder
import android.media.projection.MediaProjection
import android.util.Log
import com.google.android.gms.tasks.Tasks
import com.google.mlkit.nl.translate.Translation
import com.google.mlkit.nl.translate.Translator
import com.google.mlkit.nl.translate.TranslatorOptions
import org.json.JSONObject
import org.vosk.LibVosk
import org.vosk.LogLevel
import org.vosk.Model
import org.vosk.Recognizer
import java.io.File
import java.util.concurrent.Executors
import java.util.concurrent.TimeUnit

enum class AudioKind { SYSTEM, MICROPHONE }

/** Listens (system audio or microphone), recognises speech offline with Vosk and translates each sentence. */
class SpeechEngine(
    private val context: Context,
    private val lang: Lang,
    private val target: Lang,
    private val glossary: List<String>,
    private val useGoogle: Boolean,
    private val onPartial: (said: String, translation: String) -> Unit,
    private val onLine: (said: String, translation: String) -> Unit,
    private val onStatus: (String) -> Unit,
) {
    companion object {
        private const val TAG = "ScreenTranslator"
        private const val RATE = 16000
        private const val CHUNK = RATE / 10  // 0.1 s
        private const val MAX_SENTENCE_MS = 7000L  // talk without a pause is cut here, so captions keep coming
        private const val PARTIAL_EVERY_MS = 1500L  // the sentence still being spoken is translated this often
    }

    @Volatile private var running = false
    private var recorder: AudioRecord? = null
    private var translator: Translator? = null
    private val translating = Executors.newSingleThreadExecutor()
    private val translatingPartial = Executors.newSingleThreadExecutor()
    @Volatile private var partialBusy = false
    @Volatile private var sentence = 0  // counts finished sentences: a late live translation of an old one is dropped
    private var hansHant: android.icu.text.Transliterator? = null

    /** [testFile]: a 16 kHz mono 16-bit WAV to feed instead of live audio (used to check the pipeline). */
    fun start(kind: AudioKind, projection: MediaProjection?, testFile: String? = null) {
        running = true
        if (lang.code != target.code) {
            translator = Translation.getClient(
                TranslatorOptions.Builder().setSourceLanguage(lang.code).setTargetLanguage(target.code).build())
        }
        if (target.traditional) {
            hansHant = try { android.icu.text.Transliterator.getInstance("Hans-Hant") } catch (e: Exception) { null }
        }
        Thread({ run(kind, projection, testFile) }, "speech").start()
    }

    fun stop() {
        running = false
    }

    private fun run(kind: AudioKind, projection: MediaProjection?, testFile: String?) {
        var model: Model? = null
        var rec: Recognizer? = null
        try {
            onStatus("Loading speech model...")
            LibVosk.setLogLevel(LogLevel.WARNINGS)
            model = Model(VoskModels.dir(context, VoskModels.forLang(lang)).path)
            rec = Recognizer(model, RATE.toFloat())
            val source = if (testFile != null) null else openRecord(kind, projection)
            recorder = source
            source?.startRecording()
            onStatus("Listening...")
            onPartial("🎧", "")  // listening: shown until something is heard
            val chunk = ShortArray(CHUNK)
            var startedAt = 0L  // when the sentence being spoken began
            var translatedAt = 0L
            val wav = testFile?.let { File(it).readBytes().drop(44).toByteArray() }
            var wavPos = 0
            var lastPartial = ""
            while (running) {
                val n: Int
                if (wav != null) {
                    val left = (wav.size - wavPos) / 2
                    if (left <= 0) break
                    n = minOf(CHUNK, left)
                    for (i in 0 until n) {
                        chunk[i] = ((wav[wavPos + 2 * i + 1].toInt() shl 8) or (wav[wavPos + 2 * i].toInt() and 0xFF)).toShort()
                    }
                    wavPos += n * 2
                    Thread.sleep(30)
                } else {
                    n = source!!.read(chunk, 0, CHUNK)
                    if (n <= 0) continue
                }
                val now = android.os.SystemClock.uptimeMillis()
                if (rec.acceptWaveForm(chunk, n)) {
                    handleFinal(text(rec.result, "text"))
                    lastPartial = ""
                    startedAt = 0L
                } else {
                    val partial = text(rec.partialResult, "partial")
                    if (partial.isNotEmpty() && startedAt == 0L) startedAt = now
                    if (startedAt != 0L && now - startedAt > MAX_SENTENCE_MS) {
                        // Someone talking without a pause (a video, a stream) never reaches the end of a sentence:
                        // close it here so it is translated and shown, and carry on with the next one.
                        handleFinal(text(rec.finalResult, "text"))
                        lastPartial = ""
                        startedAt = 0L
                    } else if (partial != lastPartial) {
                        lastPartial = partial
                        onPartial(partial, "")
                        if (now - translatedAt > PARTIAL_EVERY_MS) { translatedAt = now; translateLive(partial) }
                    }
                }
            }
            if (testFile != null) handleFinal(text(rec.finalResult, "text"))
        } catch (e: Throwable) {
            Log.e(TAG, "speech failed", e)
            onStatus("Speech error: ${e.message}")
        } finally {
            recorder?.let { try { it.stop() } catch (_: Exception) {}; it.release() }
            rec?.close()
            model?.close()
            if (testFile != null) { translating.shutdown(); translating.awaitTermination(30, TimeUnit.SECONDS) }
            translator?.close()
            translatingPartial.shutdown()
            onPartial("", "")
        }
    }

    private fun text(json: String, key: String): String {
        val t = JSONObject(json).optString(key).trim()
        return if (lang.script == Script.LATIN) t else t.replace(" ", "")
    }

    private fun handleFinal(said: String) {
        sentence++
        onPartial("", "")
        if (said.length < 2) return
        if (translator == null) { onLine(said, ""); return }
        translating.execute { onLine(said, translate(said)) }
    }

    /** The sentence still being spoken, translated now and then; only the newest is worked on. */
    private fun translateLive(said: String) {
        if (translator == null || said.length < 6 || partialBusy) return
        partialBusy = true
        val forSentence = sentence
        translatingPartial.execute {
            try {
                val out = translate(said)
                if (forSentence == sentence && out.isNotEmpty()) onPartial(said, out)
            } finally {
                partialBusy = false
            }
        }
    }

    private fun translate(said: String): String = try {
        val (protectedText, originals) = TextRules.protect(said, glossary, false)
        var out = (if (useGoogle) GoogleTranslate.translate(protectedText, target) else null)
            ?: Tasks.await(translator!!.translate(protectedText), 20, TimeUnit.SECONDS)
        out = TextRules.restore(out, originals)
        if (target.traditional) out = hansHant?.transliterate(out) ?: out
        out
    } catch (e: Exception) {
        Log.w(TAG, "speech translate failed: ${e.message}")
        ""
    }

    @SuppressLint("MissingPermission")
    private fun openRecord(kind: AudioKind, projection: MediaProjection?): AudioRecord {
        val format = AudioFormat.Builder().setEncoding(AudioFormat.ENCODING_PCM_16BIT)
            .setSampleRate(RATE).setChannelMask(AudioFormat.CHANNEL_IN_MONO).build()
        val min = AudioRecord.getMinBufferSize(RATE, AudioFormat.CHANNEL_IN_MONO, AudioFormat.ENCODING_PCM_16BIT)
        val builder = AudioRecord.Builder().setAudioFormat(format).setBufferSizeInBytes(maxOf(min, RATE * 2))
        if (kind == AudioKind.SYSTEM) {
            val config = AudioPlaybackCaptureConfiguration.Builder(projection!!)
                .addMatchingUsage(AudioAttributes.USAGE_MEDIA)
                .addMatchingUsage(AudioAttributes.USAGE_GAME)
                .addMatchingUsage(AudioAttributes.USAGE_UNKNOWN)
                .build()
            builder.setAudioPlaybackCaptureConfig(config)
        } else {
            builder.setAudioSource(MediaRecorder.AudioSource.VOICE_RECOGNITION)
        }
        return builder.build()
    }
}
