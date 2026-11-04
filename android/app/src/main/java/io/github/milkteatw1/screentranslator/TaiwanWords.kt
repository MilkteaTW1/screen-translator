package io.github.milkteatw1.screentranslator

import android.content.Context

/** The offline translator writes mainland wording ("內存", "設置"): Traditional characters, but not what people in Taiwan say. */
object TaiwanWords {
    @Volatile private var words: Map<String, String>? = null

    fun parse(lines: List<String>): Map<String, String> =
        lines.mapNotNull { line -> line.split('\t').takeIf { it.size == 2 && it[0].isNotEmpty() }?.let { it[0] to it[1] } }.toMap()

    /** [text] with every word in [table] replaced, the longest match first. */
    fun apply(text: String, table: Map<String, String>): String {
        val longest = table.keys.maxOfOrNull { it.length } ?: return text
        val out = StringBuilder()
        var i = 0
        while (i < text.length) {
            var n = minOf(longest, text.length - i)
            var hit: String? = null
            while (n > 0) {
                hit = table[text.substring(i, i + n)]
                if (hit != null) break
                n--
            }
            if (hit != null) {
                out.append(hit)
                i += n
            } else {
                out.append(text[i])
                i++
            }
        }
        return out.toString()
    }

    fun convert(context: Context, text: String): String {
        val table = words ?: try {
            context.assets.open("tw_words.tsv").bufferedReader(Charsets.UTF_8).useLines { parse(it.toList()) }
        } catch (e: Exception) {
            emptyMap()
        }.also { words = it }
        return apply(text, table)
    }
}
