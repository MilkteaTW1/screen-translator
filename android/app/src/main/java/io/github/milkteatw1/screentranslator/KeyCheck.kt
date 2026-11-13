package io.github.milkteatw1.screentranslator

import org.json.JSONArray
import org.json.JSONObject
import java.net.HttpURLConnection
import java.net.URL

/** Tests an API key right after it is entered: one real request for one short translation. The settings screen shows
 *  the outcome as a green tick or a red cross. Nothing here touches the translators' own error state or back-off. */
object KeyCheck {
    sealed class Verdict {
        /** It translated: [sample] is what came back. */
        data class Works(val sample: String) : Verdict()
        /** The key was refused or something else is wrong: [why] is for the user. */
        data class Fails(val why: String) : Verdict()
        /** Only Gemini: this model is not available to this key, so the next one is worth a try. */
        data class ModelUnavailable(val why: String) : Verdict()
    }

    private const val SAMPLE = "Hello world."

    /** A different language from the English sample, whatever the screen's target is. */
    fun sampleTarget(target: Lang): Lang = if (target.code == "en") Lang("Français", "fr") else target

    /** What a Gemini answer (HTTP [code], [body]) says about the key. */
    fun geminiVerdict(code: Int, body: String): Verdict {
        if (code != 200) {
            val why = GeminiTranslate.errorText(code, body)
            return if (GeminiTranslate.modelUnavailable(code, why)) Verdict.ModelUnavailable(why) else Verdict.Fails(why)
        }
        return try {
            val content = JSONObject(body).getJSONArray("choices").getJSONObject(0).getJSONObject("message").getString("content")
            val line = GeminiTranslate.parse(content, 1)?.get(0)?.trim()
            if (line.isNullOrEmpty()) Verdict.Fails("the answer had no translation in it") else Verdict.Works(line)
        } catch (e: Exception) {
            Verdict.Fails("the answer could not be read")
        }
    }

    /** What a DeepL answer (HTTP [code], [body]) says about the key. */
    fun deeplVerdict(code: Int, body: String): Verdict {
        if (code != 200) {
            val hint = if (code == 403) " (is the key right? free keys end in :fx)" else ""
            return Verdict.Fails("HTTP $code " + body.trim().take(160) + hint)
        }
        val line = DeeplTranslate.parse(body, 1)?.get(0)?.trim()
        return if (line.isNullOrEmpty()) Verdict.Fails("the answer had no translation in it") else Verdict.Works(line)
    }

    private fun post(url: String, auth: String, body: String): Pair<Int, String> {
        val conn = URL(url).openConnection() as HttpURLConnection
        conn.requestMethod = "POST"
        conn.connectTimeout = 8000
        conn.readTimeout = 20_000
        conn.doOutput = true
        conn.setRequestProperty("Content-Type", "application/json")
        conn.setRequestProperty("Authorization", auth)
        conn.outputStream.use { it.write(body.toByteArray()) }
        val code = conn.responseCode
        val text = (if (code == 200) conn.inputStream else conn.errorStream ?: conn.inputStream).bufferedReader().use { it.readText() }
        return code to text
    }

    /** Blocking: call it off the main thread. */
    fun gemini(key: String, target: Lang, models: List<String> = GeminiTranslate.MODELS): Verdict {
        var last: Verdict = Verdict.Fails("no model to ask")
        for (model in models) {
            last = try {
                val body = JSONObject().put("model", model).put("temperature", 0).put("stream", false)
                    .put("messages", JSONArray().put(JSONObject().put("role", "user")
                        .put("content", GeminiTranslate.prompt(listOf(SAMPLE), sampleTarget(target))))).toString()
                val (code, text) = post(GeminiTranslate.URL_BASE, "Bearer ${key.trim()}", body)
                geminiVerdict(code, text)
            } catch (e: Exception) {
                return Verdict.Fails("${e.javaClass.simpleName}: ${e.message}")
            }
            if (last !is Verdict.ModelUnavailable) return last
        }
        return Verdict.Fails((last as Verdict.ModelUnavailable).why)
    }

    /** Blocking: call it off the main thread. */
    fun deepl(key: String, target: Lang): Verdict = try {
        val (code, text) = post(DeeplTranslate.endpoint(key), "DeepL-Auth-Key ${key.trim()}",
            DeeplTranslate.body(listOf(SAMPLE), Lang("English", "en"), sampleTarget(target)))
        deeplVerdict(code, text)
    } catch (e: Exception) {
        Verdict.Fails("${e.javaClass.simpleName}: ${e.message}")
    }
}
