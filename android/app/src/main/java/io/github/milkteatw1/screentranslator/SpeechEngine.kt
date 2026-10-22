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
    private val onPartial: (String) -> Unit,
    private val onLine: (said: String, translation: String) -> Unit,
    private val onStatus: (String) -> Unit,
) {
    companion object {
        private const val TAG = "ScreenTranslator"
        private const val RATE = 16000
        private const val CHUNK = RATE / 10  // 0.1 s
    }

    @Volatile private var running = false
    private var recorder: AudioRecord? = null
    private var translator: Translator? = null
    private val translating = Executors.newSingleThreadExecutor()
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
            val chunk = ShortArray(CHUNK)
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
                if (rec.acceptWaveForm(chunk, n)) {
                    handleFinal(text(rec.result, "text"))
                    lastPartial = ""
                    onPartial("")
                } else {
                    val partial = text(rec.partialResult, "partial")
                    if (partial != lastPartial) { lastPartial = partial; onPartial(partial) }
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
        }
    }

    private fun text(json: String, key: String): String {
        val t = JSONObject(json).optString(key).trim()
        return if (lang.script == Script.LATIN) t else t.replace(" ", "")
    }

    private fun handleFinal(said: String) {
        if (said.length < 2) return
        if (translator == null) { onLine(said, ""); return }
        translating.execute {
            val shown = try {
                val (protectedText, originals) = TextRules.protect(said, glossary, false)
                var out = Tasks.await(translator!!.translate(protectedText), 20, TimeUnit.SECONDS)
                out = TextRules.restore(out, originals)
                if (target.traditional) out = hansHant?.transliterate(out) ?: out
                out
            } catch (e: Exception) {
                Log.w(TAG, "speech translate failed: ${e.message}")
                ""
            }
            onLine(said, shown)
        }
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
