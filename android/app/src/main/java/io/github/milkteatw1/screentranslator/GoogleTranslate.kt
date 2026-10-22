package io.github.milkteatw1.screentranslator

import android.os.SystemClock
import android.util.Log
import org.json.JSONArray
import java.net.HttpURLConnection
import java.net.URL
import java.net.URLEncoder

/** Google Translate (the free web endpoint): the text is sent to Google. Offline ML Kit is the backup. */
object GoogleTranslate {
    private const val TAG = "ScreenTranslator"
    private const val RETRY_AFTER_MS = 30_000L  // after a failure (offline), leave Google alone for a while
    private const val RATE_LIMITED_MS = 600_000L  // Google said "too many requests": ten minutes
    @Volatile private var retryAt = 0L

    /** Google's code for a target language. */
    fun code(lang: Lang) = if (lang.code == "zh") (if (lang.traditional) "zh-TW" else "zh-CN") else lang.code

    /** Several short texts in one request, one per line: far fewer round trips than one request each. Null for
     *  every text Google could not do (unreachable, or the lines did not come back one for one). */
    fun translateMany(texts: List<String>, target: Lang): List<String?> {
        if (texts.isEmpty()) return emptyList()
        if (texts.size == 1) return listOf(translate(texts[0], target))
        val joined = texts.joinToString("\n") { it.replace(Regex("\\s+"), " ").trim() }
        return matchLines(translate(joined, target), texts.size)
    }

    /** The answer to a one-text-per-line request, split back into one translation per text (all null unless the
     *  line count matches: then we cannot tell which line belongs to which text). */
    fun matchLines(out: String?, count: Int): List<String?> {
        val lines = out?.split("\n")
        return if (lines != null && lines.size == count) lines.map { it.trim().ifEmpty { null } } else List(count) { null }
    }

    /** The translation, or null when Google can't be reached (the caller falls back to offline translation). */
    fun translate(text: String, target: Lang): String? {
        if (SystemClock.uptimeMillis() < retryAt) return null
        return try {
            val url = URL("https://translate.googleapis.com/translate_a/single?client=gtx&sl=auto&dt=t&tl=" +
                URLEncoder.encode(code(target), "UTF-8"))
            val conn = url.openConnection() as HttpURLConnection
            conn.requestMethod = "POST"
            conn.connectTimeout = 5000
            conn.readTimeout = 8000
            conn.doOutput = true
            conn.setRequestProperty("User-Agent", "Mozilla/5.0")
            conn.setRequestProperty("Content-Type", "application/x-www-form-urlencoded")
            conn.outputStream.use { it.write(("q=" + URLEncoder.encode(text, "UTF-8")).toByteArray()) }
            val code = conn.responseCode
            if (code == 429) {
                retryAt = SystemClock.uptimeMillis() + RATE_LIMITED_MS
                Log.w(TAG, "Google Translate is rate-limited: offline translation for ten minutes")
                return null
            }
            if (code != 200) throw java.io.IOException("Google answered $code")
            val parts = JSONArray(conn.inputStream.bufferedReader().use { it.readText() }).getJSONArray(0)
            buildString {
                for (i in 0 until parts.length()) {
                    val part = parts.optJSONArray(i) ?: continue
                    if (!part.isNull(0)) append(part.getString(0))
                }
            }.ifEmpty { null }
        } catch (e: Exception) {
            Log.w(TAG, "Google Translate failed: ${e.message}")
            retryAt = SystemClock.uptimeMillis() + RETRY_AFTER_MS
            null
        }
    }
}
