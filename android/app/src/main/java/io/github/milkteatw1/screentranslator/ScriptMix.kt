package io.github.milkteatw1.screentranslator

/**
 * Speech in a language with a script of its own (Chinese, Korean, Russian...): words already in that script need no
 * translation, only the stretches in other scripts do (an English word inside a Chinese sentence).
 */
object ScriptMix {
    private fun scripts(code: String): Set<Character.UnicodeScript>? = when (code) {
        "zh" -> setOf(Character.UnicodeScript.HAN)
        "ja" -> setOf(Character.UnicodeScript.HAN, Character.UnicodeScript.HIRAGANA, Character.UnicodeScript.KATAKANA)
        "ko" -> setOf(Character.UnicodeScript.HANGUL)
        "ru", "uk", "bg" -> setOf(Character.UnicodeScript.CYRILLIC)
        "el" -> setOf(Character.UnicodeScript.GREEK)
        "ar" -> setOf(Character.UnicodeScript.ARABIC)
        "he" -> setOf(Character.UnicodeScript.HEBREW)
        "th" -> setOf(Character.UnicodeScript.THAI)
        "hi" -> setOf(Character.UnicodeScript.DEVANAGARI)
        else -> null
    }

    /** True for a letter of [code]'s own script; null when that language has no script of its own to tell by. */
    fun ownLetter(code: String): ((Int) -> Boolean)? {
        val own = scripts(code) ?: return null
        return { cp -> Character.UnicodeScript.of(cp) in own }
    }

    /** (start, end) of each stretch of letters not in the own script, with what lies between them but not what trails them. */
    fun foreignRuns(text: String, own: (Int) -> Boolean): List<IntRange> {
        val runs = ArrayList<IntRange>()
        var i = 0
        while (i < text.length) {
            val cp = text.codePointAt(i)
            if (Character.isLetter(cp) && !own(cp)) {
                var j = i + Character.charCount(cp)
                while (j < text.length && !own(text.codePointAt(j))) j += Character.charCount(text.codePointAt(j))
                var end = j
                while (end > i && !Character.isLetterOrDigit(text[end - 1])) end--
                runs.add(i until end)
                i = j
            } else i += Character.charCount(cp)
        }
        return runs
    }

    /** The sentence with each foreign stretch translated (kept as said when it does not translate); "" when there is none. */
    fun mix(text: String, own: (Int) -> Boolean, translateRun: (String) -> String): String {
        val runs = foreignRuns(text, own)
        if (runs.isEmpty()) return ""
        val out = StringBuilder()
        var pos = 0
        for (r in runs) {
            out.append(text, pos, r.first)
            val piece = text.substring(r.first, r.last + 1)
            out.append(translateRun(piece).ifEmpty { piece })
            pos = r.last + 1
        }
        out.append(text, pos, text.length)
        return out.toString()
    }
}
