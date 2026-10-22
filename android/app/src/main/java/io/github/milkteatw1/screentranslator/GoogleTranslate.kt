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
    private const val RETRY_AFTER_MS = 30_000L  // after a failure (offline, blocked), leave Google alone for a while
    @Volatile private var downAt = -RETRY_AFTER_MS

    /** Google's code for a target language. */
    fun code(lang: Lang) = if (lang.code == "zh") (if (lang.traditional) "zh-TW" else "zh-CN") else lang.code

    /** The translation, or null when Google can't be reached (the caller falls back to offline translation). */
    fun translate(text: String, target: Lang): String? {
        if (SystemClock.uptimeMillis() - downAt < RETRY_AFTER_MS) return null
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
            if (conn.responseCode != 200) throw java.io.IOException("Google answered ${conn.responseCode}")
            val parts = JSONArray(conn.inputStream.bufferedReader().use { it.readText() }).getJSONArray(0)
            buildString {
                for (i in 0 until parts.length()) {
                    val part = parts.optJSONArray(i) ?: continue
                    if (!part.isNull(0)) append(part.getString(0))
                }
            }.ifEmpty { null }
        } catch (e: Exception) {
            Log.w(TAG, "Google Translate failed: ${e.message}")
            downAt = SystemClock.uptimeMillis()
            null
        }
    }
}
