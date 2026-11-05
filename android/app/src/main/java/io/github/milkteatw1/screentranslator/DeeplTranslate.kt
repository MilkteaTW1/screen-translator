package io.github.milkteatw1.screentranslator

import android.util.Log
import org.json.JSONArray
import org.json.JSONObject
import java.net.HttpURLConnection
import java.net.URL

/** DeepL with the user's own key (free keys end in ":fx" and use another address). Tried after Gemini, before Google. */
object DeeplTranslate {
    private const val TAG = "ScreenTranslator"
    const val KEY_PAGE = "https://www.deepl.com/your-account/keys"

    @Volatile var lastError: String? = null
    @Volatile private var retryAt = 0L

    fun endpoint(key: String) = (if (key.trim().endsWith(":fx")) "https://api-free.deepl.com" else "https://api.deepl.com") + "/v2/translate"

    /** DeepL's name for the language it translates into. */
    fun targetCode(lang: Lang): String = when {
        lang.code == "zh" && lang.traditional -> "ZH-HANT"
        lang.code == "zh" -> "ZH-HANS"
        lang.code == "en" -> "EN-US"
        lang.code == "pt" -> "PT-BR"
        else -> lang.code.uppercase()
    }

    /** ... and for the language it translates from. */
    fun sourceCode(lang: Lang): String = lang.code.uppercase()

    fun body(texts: List<String>, source: Lang?, target: Lang): String {
        val json = JSONObject()
            .put("text", JSONArray(texts.map { it.replace(Regex("\\s+"), " ").trim() }))
            .put("target_lang", targetCode(target))
        if (source != null) json.put("source_lang", sourceCode(source))
        return json.toString()
    }

    /** One translation per text in DeepL's answer, or null unless it has [count] of them. */
    fun parse(answer: String, count: Int): List<String>? = try {
        val list = JSONObject(answer).getJSONArray("translations")
        if (list.length() != count) null else List(count) { list.getJSONObject(it).getString("text") }
    } catch (e: Exception) {
        null
    }

    /** One translation per text, or nulls for all of them when DeepL could not do it ([lastError] says why). */
    fun translateMany(key: String, texts: List<String>, source: Lang?, target: Lang): List<String?> {
        val none = List<String?>(texts.size) { null }
        if (texts.isEmpty() || android.os.SystemClock.uptimeMillis() < retryAt) return none
        return try {
            val conn = URL(endpoint(key)).openConnection() as HttpURLConnection
            conn.requestMethod = "POST"
            conn.connectTimeout = 8000
            conn.readTimeout = 20_000
            conn.doOutput = true
            conn.setRequestProperty("Content-Type", "application/json")
            conn.setRequestProperty("Authorization", "DeepL-Auth-Key ${key.trim()}")
            conn.outputStream.use { it.write(body(texts, source, target).toByteArray()) }
            val code = conn.responseCode
            if (code != 200) {
                val said = (conn.errorStream ?: conn.inputStream).bufferedReader().use { it.readText() }
                lastError = "HTTP $code " + said.trim().take(200)
                retryAt = android.os.SystemClock.uptimeMillis() + if (code == 429 || code == 456) 60_000L else 30_000L
                Log.w(TAG, "DeepL: $lastError")
                return none
            }
            val lines = parse(conn.inputStream.bufferedReader().use { it.readText() }, texts.size)
            if (lines == null) {
                lastError = "the answer did not have one line for each text"
                retryAt = android.os.SystemClock.uptimeMillis() + 10_000L
                none
            } else {
                lastError = null
                lines
            }
        } catch (e: Exception) {
            lastError = "${e.javaClass.simpleName}: ${e.message}"
            retryAt = android.os.SystemClock.uptimeMillis() + 10_000L
            Log.w(TAG, "DeepL failed: $lastError")
            none
        }
    }
}
