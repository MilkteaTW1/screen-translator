package io.github.milkteatw1.screentranslator

import android.annotation.SuppressLint
import android.content.Context
import android.media.AudioAttributes
import android.media.AudioFormat
import android.media.AudioPlaybackCaptureConfiguration
import android.media.AudioRecord
import android.media.MediaRecorder
import android.media.projection.MediaProjection
import android.os.SystemClock
import android.util.Log
import com.google.android.gms.tasks.Tasks
import com.google.mlkit.nl.translate.TranslateLanguage
import com.google.mlkit.nl.translate.Translation
import com.google.mlkit.nl.translate.Translator
import com.google.mlkit.nl.translate.TranslatorOptions
import java.io.File
import java.util.concurrent.Executors
import java.util.concurrent.TimeUnit

enum class AudioKind { SYSTEM, MICROPHONE }

/**
 * Listens (what the phone plays, or the microphone), recognises speech offline with Whisper, which also says which
 * language it is, and translates each sentence. The sentence being spoken is shown live and replaced once it ends.
 */
class SpeechEngine(
    private val context: Context,
    private val language: String,  // "auto" or a language code
    private val model: WhisperModel.Spec,
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
        private const val LIVE_STEP = 2.0  // seconds of new speech between live updates of the sentence being spoken
        private const val MAX_BACKLOG = 3  // finished sentences waiting; more are dropped to stay real-time
    }

    @Volatile private var running = false
    private var recorder: AudioRecord? = null
    private val worker = Executors.newSingleThreadExecutor()  // all Whisper work, one piece at a time
    @Volatile private var backlog = 0
    @Volatile private var liveBusy = false
    @Volatile private var sentence = 0  // counts finished sentences: a late live update of an old one is dropped
    private val translators = HashMap<String, Translator>()  // offline translators by spoken language
    private var hansHant: android.icu.text.Transliterator? = null
    private val threads = (Runtime.getRuntime().availableProcessors() - 1).coerceIn(2, 4)
    @Volatile private var whisper: WhisperModel? = null

    /** [testFile]: a 16 kHz mono 16-bit WAV to feed instead of live audio (used to check the pipeline). */
    fun start(kind: AudioKind, projection: MediaProjection?, testFile: String? = null) {
        running = true
        if (target.traditional) {
            hansHant = try { android.icu.text.Transliterator.getInstance("Hans-Hant") } catch (e: Exception) { null }
        }
        Thread({ run(kind, projection, testFile) }, "speech").start()
    }

    fun stop() {
        running = false
    }

    private fun run(kind: AudioKind, projection: MediaProjection?, testFile: String?) {
        try {
            onStatus("Loading speech model...")
            whisper = WhisperModel.load(context, model) ?: throw IllegalStateException("speech model missing")
            val source = if (testFile != null) null else openRecord(kind, projection)
            recorder = source
            source?.startRecording()
            onStatus("Listening...")
            onPartial("🎧", "")  // listening: shown until something is heard
            val shorts = ShortArray(CHUNK)
            val wav = testFile?.let { File(it).readBytes().drop(44).toByteArray() }
            var wavPos = 0
            val seg = Segmenter(RATE)
            var heardAt = SystemClock.uptimeMillis()  // last time the sound was not pure silence
            var warned = false
            var listening = true
            while (running) {
                val n: Int
                if (wav != null) {
                    val left = (wav.size - wavPos) / 2
                    if (left <= 0) break
                    n = minOf(CHUNK, left)
                    for (i in 0 until n) {
                        shorts[i] = ((wav[wavPos + 2 * i + 1].toInt() shl 8) or (wav[wavPos + 2 * i].toInt() and 0xFF)).toShort()
                    }
                    wavPos += n * 2
                    Thread.sleep(30)
                } else {
                    n = source!!.read(shorts, 0, CHUNK)
                    if (n <= 0) continue
                }
                val chunk = FloatArray(n) { shorts[it] / 32768f }
                val now = SystemClock.uptimeMillis()
                if (chunk.any { it != 0f }) {
                    heardAt = now
                    if (warned) { warned = false; onPartial("", "") }
                } else if (!warned && now - heardAt > 10_000) {
                    // Nothing at all, not even noise: the playing app does not allow its sound to be recorded
                    // (some streaming apps), or nothing is playing.
                    warned = true
                    onStatus("🔇 " + context.getString(if (kind == AudioKind.SYSTEM) R.string.speech_silent_phone else R.string.speech_silent_mic))
                }
                val done = seg.feed(chunk)
                if (done != null) {
                    sentence++
                    finish(done)
                } else if (seg.speaking && seg.fresh >= LIVE_STEP && !liveBusy && backlog == 0) {
                    seg.snapshot()?.let { live(it) }
                }
                if (listening && seg.speaking) { listening = false; onPartial("", "") }
            }
        } catch (e: Throwable) {
            Log.e(TAG, "speech failed", e)
            onStatus("⚠ " + context.getString(R.string.speech_error, e.message ?: e.javaClass.simpleName))
        } finally {
            recorder?.let { try { it.stop() } catch (_: Exception) {}; it.release() }
            worker.shutdown()  // what is queued still finishes; then the model is freed
            Thread {
                worker.awaitTermination(60, TimeUnit.SECONDS)
                whisper?.close()
                synchronized(translators) { translators.values.forEach { it.close() } }
            }.start()
            if (testFile == null) onPartial("", "")
        }
    }

    /** A finished sentence: transcribed again in full, and it replaces the live line. */
    private fun finish(audio: FloatArray) {
        if (backlog >= MAX_BACKLOG) return  // the phone can't keep up: skip rather than fall further behind
        backlog++
        val forSentence = sentence
        worker.execute {
            try {
                val heard = whisper?.transcribe(normalize(audio), threads, language)
                if (heard != null) {
                    val (code, text) = heard
                    onLine(text, translate(text, code))
                }
                if (forSentence == sentence) onPartial("", "")
            } catch (e: Throwable) {
                Log.w(TAG, "speech sentence failed: ${e.message}")
            } finally {
                backlog--
            }
        }
    }

    /** The sentence still being spoken: shown (and translated) right away, replaced when it ends. */
    private fun live(audio: FloatArray) {
        liveBusy = true
        val forSentence = sentence
        worker.execute {
            try {
                val heard = whisper?.transcribe(normalize(audio), threads, language)
                if (heard != null && forSentence == sentence) {
                    val (code, text) = heard
                    onPartial(text, "")
                    val out = translate(text, code)
                    if (forSentence == sentence && out.isNotEmpty()) onPartial(text, out)
                }
            } catch (e: Throwable) {
                Log.w(TAG, "live speech failed: ${e.message}")
            } finally {
                liveBusy = false
            }
        }
    }

    /** The translation of [said], spoken in [code]: "" when it is already the target language or nothing works. */
    private fun translate(said: String, code: String): String {
        val spoken = code.lowercase()
        if (spoken == target.code) return ""
        return try {
            val (protectedText, originals) = TextRules.protect(said, glossary, false)
            var out = (if (useGoogle) GoogleTranslate.translate(protectedText, target) else null)
                ?: offline(spoken)?.let { Tasks.await(it.translate(protectedText), 20, TimeUnit.SECONDS) }
                ?: return ""
            out = TextRules.restore(out, originals)
            if (target.traditional) out = hansHant?.transliterate(out) ?: out
            out
        } catch (e: Exception) {
            Log.w(TAG, "speech translate failed: ${e.message}")
            ""
        }
    }

    /** The offline translator from [spoken] to the target, if ML Kit knows that language. */
    private fun offline(spoken: String): Translator? {
        val from = TranslateLanguage.fromLanguageTag(spoken) ?: return null
        return synchronized(translators) {
            translators.getOrPut(from) {
                Translation.getClient(TranslatorOptions.Builder().setSourceLanguage(from).setTargetLanguage(target.code).build())
            }
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
