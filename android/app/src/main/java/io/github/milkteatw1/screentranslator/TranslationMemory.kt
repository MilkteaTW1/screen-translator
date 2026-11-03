package io.github.milkteatw1.screentranslator

import org.json.JSONArray
import java.io.File
import java.io.IOException

/** Google's translations kept in a file, so text read again (today or next week) is not sent again. Only Google's:
 *  a translation from the small offline model should not outlive the moment Google is back. */
class TranslationMemory(private val file: File, private val max: Int = 50_000, private val keep: Int = 30_000) {
    private var items: LinkedHashMap<String, String>? = null  // loaded on first use

    private fun key(scope: String, text: String) = scope + "|" + text.trim().replace(SPACES, " ")  // OCR's spacing is not other text

    private fun loaded(): LinkedHashMap<String, String> {
        items?.let { return it }
        val map = LinkedHashMap<String, String>()
        try {
            file.forEachLine { line ->
                try {
                    val a = JSONArray(line)
                    map[a.getString(0)] = a.getString(1)
                } catch (e: org.json.JSONException) {
                    // a line cut off by a crash: the rest is still good
                }
            }
        } catch (e: IOException) {
            // nothing remembered yet
        }
        items = map
        return map
    }

    @Synchronized
    fun get(scope: String, text: String): String? = loaded()[key(scope, text)]

    @Synchronized
    fun put(scope: String, text: String, translation: String) {
        val map = loaded()
        val k = key(scope, text)
        map[k] = translation
        try {
            file.parentFile?.mkdirs()
            if (map.size > max) {
                val newest = map.entries.toList().takeLast(keep)
                map.clear()
                newest.forEach { map[it.key] = it.value }
                file.writeText(map.entries.joinToString("") { line(it.key, it.value) })
            } else {
                file.appendText(line(k, translation))
            }
        } catch (e: IOException) {
            // no room: it still works, just without remembering
        }
    }

    @Synchronized
    fun clear() {
        items = LinkedHashMap()
        file.delete()
    }

    private fun line(key: String, value: String) = JSONArray().put(key).put(value).toString() + "\n"

    companion object {
        private val SPACES = Regex("""\s+""")

        /** Not backed up: this is what was on the screen, and it should stay on this phone. */
        fun fileIn(context: android.content.Context) = File(context.noBackupFilesDir, "translations.jsonl")
    }
}
