package io.github.milkteatw1.screentranslator

import android.util.Log
import org.json.JSONArray
import org.json.JSONObject
import java.net.HttpURLConnection
import java.net.URL

/** Gemini with the user's own API key (from aistudio.google.com/apikey), through its OpenAI-compatible address.
 *  Tried before Google's free endpoint, which then only has to be the backup. */
object GeminiTranslate {
    private const val TAG = "ScreenTranslator"
    const val URL_BASE = "https://generativelanguage.googleapis.com/v1beta/openai/chat/completions"
    const val MODEL = "gemini-2.5-flash-lite"
    const val KEY_PAGE = "https://aistudio.google.com/apikey"

    /** Why the last request did not translate (null: it did, or none was made yet). Shown to the user once. */
    @Volatile var lastError: String? = null
    @Volatile private var retryAt = 0L  // after a failure Gemini is left alone for a while, not asked on every scan

    fun prompt(texts: List<String>, target: Lang): String =
        "Translate each string in this JSON array into ${languageName(target)}. Answer with only a JSON array of the same " +
            "length, in the same order, nothing else.\n" + JSONArray(texts.map { it.replace(Regex("\\s+"), " ").trim() }).toString()

    private fun languageName(lang: Lang) = when {
        lang.code == "zh" && lang.traditional -> "Traditional Chinese (Taiwan)"
        lang.code == "zh" -> "Simplified Chinese"
        else -> java.util.Locale.forLanguageTag(lang.code).getDisplayLanguage(java.util.Locale.ENGLISH).ifEmpty { lang.code }
    }

    /** The one-per-text answer inside [content] (it may be wrapped in a code fence), or null unless it has [count] texts. */
    fun parse(content: String, count: Int): List<String>? {
        val start = content.indexOf('[')
        val end = content.lastIndexOf(']')
        if (start < 0 || end <= start) return null
        return try {
            val array = JSONArray(content.substring(start, end + 1))
            if (array.length() != count) null else List(count) { array.get(it) as? String ?: return null }
        } catch (e: Exception) {
            null
        }
    }

    /** What the server said when it said no: {"error": {"message": ...}}, also inside a list (Gemini does that). */
    fun errorText(code: Int, body: String): String {
        val message = try {
            val json = if (body.trimStart().startsWith("[")) JSONArray(body).getJSONObject(0) else JSONObject(body)
            json.getJSONObject("error").getString("message")
        } catch (e: Exception) {
            body
        }
        return "HTTP $code " + message.trim().take(200)
    }

    /** One translation per text, or nulls for all of them when Gemini could not do it ([lastError] says why). */
    fun translateMany(key: String, texts: List<String>, target: Lang, model: String = MODEL): List<String?> {
        if (texts.isEmpty()) return emptyList()
        val none = List<String?>(texts.size) { null }
        if (android.os.SystemClock.uptimeMillis() < retryAt) return none
        return try {
            val conn = URL(URL_BASE).openConnection() as HttpURLConnection
            conn.requestMethod = "POST"
            conn.connectTimeout = 8000
            conn.readTimeout = 40_000
            conn.doOutput = true
            conn.setRequestProperty("Content-Type", "application/json")
            conn.setRequestProperty("Authorization", "Bearer $key")
            val body = JSONObject()
                .put("model", model).put("temperature", 0).put("stream", false)
                .put("messages", JSONArray().put(JSONObject().put("role", "user").put("content", prompt(texts, target))))
            conn.outputStream.use { it.write(body.toString().toByteArray()) }
            val code = conn.responseCode
            if (code != 200) {
                lastError = errorText(code, (conn.errorStream ?: conn.inputStream).bufferedReader().use { it.readText() })
                Log.w(TAG, "Gemini: $lastError")
                retryAt = android.os.SystemClock.uptimeMillis() + if (code == 429) 30_000L else 60_000L
                return none
            }
            val answer = JSONObject(conn.inputStream.bufferedReader().use { it.readText() })
            val content = answer.getJSONArray("choices").getJSONObject(0).getJSONObject("message").getString("content")
            val lines = parse(content, texts.size)
            if (lines == null) {
                lastError = "the answer did not have one line for each text"
                none
            } else {
                lastError = null
                lines
            }
        } catch (e: Exception) {
            lastError = "${e.javaClass.simpleName}: ${e.message}"
            Log.w(TAG, "Gemini failed: $lastError")
            retryAt = android.os.SystemClock.uptimeMillis() + 10_000L
            none
        }
    }
}
