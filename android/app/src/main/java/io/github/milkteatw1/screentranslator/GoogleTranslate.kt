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
    private const val RETRY_AFTER_MS = 30_000L  // longest wait after failures; one slow answer costs only a few seconds
    private const val RATE_LIMITED_MS = 600_000L  // longest wait after refusals, reached only if Google keeps refusing
    private val REFUSED = setOf(301, 302, 303, 307, 403, 429, 503)
    @Volatile private var retryAt = 0L
    @Volatile private var fails = 0  // failures in a row
    @Volatile private var refusals = 0  // refusals in a row

    /** The network is fine but Google does not want to answer: "too many requests", or its "unusual traffic" page. */
    fun isRefusal(code: Int) = code in REFUSED

    /** Whether Google is being asked right now: "ok", "refused" (it said no; waiting) or "unreachable" (waiting). */
    fun state(): String = when {
        SystemClock.uptimeMillis() >= retryAt -> "ok"
        refusals > 0 -> "refused"
        else -> "unreachable"
    }

    fun waitAfterFailure(inARow: Int) = minOf(RETRY_AFTER_MS, 5_000L * inARow)

    fun waitAfterRefusal(inARow: Int) = minOf(RATE_LIMITED_MS, 60_000L shl (inARow - 1).coerceIn(0, 10))

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

    private const val BUDGET = 24  // requests allowed per BUDGET_WINDOW_MS: more than that and Google starts refusing this phone
    private const val BUDGET_WINDOW_MS = 60_000L
    private val sent = ArrayDeque<Long>()

    /** Whether one more request fits in the budget at [now] (and counts it as made); what does not goes offline. */
    @Synchronized fun takeSlot(now: Long = SystemClock.uptimeMillis(), budget: Int = BUDGET): Boolean {
        while (sent.isNotEmpty() && now - sent.first() >= BUDGET_WINDOW_MS) sent.removeFirst()
        if (sent.size >= budget) return false
        sent.addLast(now)
        return true
    }

    @Synchronized fun resetBudget() = sent.clear()

    /** The translation, or null when Google can't be reached (the caller falls back to offline translation). */
    fun translate(text: String, target: Lang): String? {
        if (SystemClock.uptimeMillis() < retryAt) return null
        if (!takeSlot()) return null
        return try {
            val url = URL("https://translate.googleapis.com/translate_a/single?client=gtx&sl=auto&dt=t&tl=" +
                URLEncoder.encode(code(target), "UTF-8"))
            val conn = url.openConnection() as HttpURLConnection
            conn.requestMethod = "POST"
            conn.instanceFollowRedirects = false  // a redirect is Google's "unusual traffic" page: a refusal to see, not to follow
            conn.connectTimeout = 5000
            conn.readTimeout = 8000
            conn.doOutput = true
            conn.setRequestProperty("User-Agent", "Mozilla/5.0")
            conn.setRequestProperty("Content-Type", "application/x-www-form-urlencoded")
            conn.outputStream.use { it.write(("q=" + URLEncoder.encode(text, "UTF-8")).toByteArray()) }
            val code = conn.responseCode
            if (isRefusal(code)) {
                refusals++
                val wait = waitAfterRefusal(refusals)
                retryAt = SystemClock.uptimeMillis() + wait
                Log.w(TAG, "Google refused ($code): offline translation for ${wait / 1000} s")
                return null
            }
            if (code != 200) throw java.io.IOException("Google answered $code")
            val parts = JSONArray(conn.inputStream.bufferedReader().use { it.readText() }).getJSONArray(0)
            fails = 0
            refusals = 0
            buildString {
                for (i in 0 until parts.length()) {
                    val part = parts.optJSONArray(i) ?: continue
                    if (!part.isNull(0)) append(part.getString(0))
                }
            }.ifEmpty { null }
        } catch (e: Exception) {
            Log.w(TAG, "Google Translate failed: ${e.message}")
            fails++
            retryAt = SystemClock.uptimeMillis() + waitAfterFailure(fails)
            null
        }
    }
}
