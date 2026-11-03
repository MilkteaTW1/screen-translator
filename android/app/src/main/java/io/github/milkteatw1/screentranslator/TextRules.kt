package io.github.milkteatw1.screentranslator

/** Text filtering and proper-noun protection. Plain Kotlin, so it is unit-tested on the JVM. */
object TextRules {
    private val urlish = Regex("""https?:|www\.|\.(com|org|net|io|tw|edu|gov|co)\b|[/\\@]|\w_\w""", RegexOption.IGNORE_CASE)
    private val latinWord = Regex("""[A-Za-z][A-Za-z0-9'’\-]*""")
    private val placeholder = Regex("""Z\s*(\d+)\s*Z""")
    private val camel = Regex("""[a-z][A-Z]""")
    private val spaces = Regex("""\s+""")
    private const val NOISE_RATIO = 0.15
    private const val ALLOWED = "。、，．！？「」『』（）()・…ー〜~:：;；.,!?'\"’“”‘-—–/%&@#$+=[]<>"
    private const val EDGE_CHARS = ".,!?:;()\"'“”‘’-—…"

    fun isKana(c: Char) = c in '぀'..'ヿ'
    fun isHan(c: Char) = c in '㐀'..'鿿'
    fun isHangul(c: Char) = c in '가'..'힯'
    fun isCjk(c: Char) = isKana(c) || isHan(c) || isHangul(c)

    private fun inScript(c: Char, script: Script) = when (script) {
        Script.LATIN -> Character.UnicodeScript.of(c.code) == Character.UnicodeScript.LATIN
        Script.CHINESE -> isHan(c)
        Script.JAPANESE -> isKana(c) || isHan(c)
        Script.KOREAN -> isHangul(c)
    }

    /** True when [text] really is in the chosen source language (not an icon, a URL, a name, the wrong script...). */
    fun looksLikeSource(text: String, src: Lang, skipNames: Boolean = true): Boolean {
        val letters = text.filter { it.isLetter() }
        if (letters.length < 2) return false
        val chars = text.filter { !it.isWhitespace() }
        val alnum = chars.filter { it.isLetterOrDigit() }.map { it.lowercaseChar() }
        if (alnum.size >= 6 && alnum.toSet().size <= 3) return false  // a row of dots or circles reads as "oooooooo"
        val noise = chars.count { !it.isLetterOrDigit() && it !in ALLOWED }
        if (noise.toDouble() / chars.length >= NOISE_RATIO) return false
        if (src.script == Script.JAPANESE) {
            val kana = letters.count { isKana(it) }
            if (kana < 2 || kana.toDouble() / letters.length < 0.25) return false
        }
        if (src.script == Script.CHINESE && letters.any { isKana(it) }) return false
        if (src.script == Script.LATIN) {
            if (letters.length < 3 || !Regex("[A-Za-z]{2,}").containsMatchIn(text)) return false
            if (src.code == "en" && !looksTranslatableLatin(text, skipNames)) return false
        }
        return letters.count { inScript(it, src.script) }.toDouble() / letters.length >= 0.7
    }

    private fun stripEdges(t: String) = t.trim { it in EDGE_CHARS }

    private fun wordlike(token: String): Boolean {
        val t = stripEdges(token)
        return t.isNotEmpty() && (t.all { it.isDigit() } || (t.all { it.isLetter() } && !camel.containsMatchIn(t)))
    }

    private val functionWords = setOf("the", "a", "an", "of", "to", "in", "on", "for", "and", "or", "is", "are", "was", "with",
        "at", "by", "from", "this", "that", "it", "be", "we", "you", "your", "our", "not", "as", "has", "have")

    /** Rejects URLs, @handles, ids, lone words, menu bars and (optionally) names. Judged on the words left once
     *  handles, hashtags and links are set aside, so a sentence that merely mentions one still counts as a sentence. */
    fun looksTranslatableLatin(text: String, skipNames: Boolean): Boolean {
        val tokens = text.split(spaces).filter { it.isNotEmpty() }
        if (tokens.isEmpty()) return false
        val words = tokens.filter { !urlish.containsMatchIn(it) && !it.startsWith("@") && !it.startsWith("#") }
        if (words.size < 2 && !(tokens.size >= 3 && words.isNotEmpty())) return false  // a link, a handle, or one word
        if (words.count { wordlike(it) }.toDouble() / words.size < 0.6) return false
        if (words.count { val s = stripEdges(it); s.length >= 3 && s.all { c -> c.isLetter() } } < 2) return false
        val endsSentence = text.trimEnd().let { it.endsWith(".") || it.endsWith("!") || it.endsWith("?") }
        val lowered = words.map { stripEdges(it).lowercase() }.toSet()
        if (words.size >= 5 && !endsSentence && lowered.none { it in functionWords } &&
            words.count { it.first().isUpperCase() }.toDouble() / words.size >= 0.8) return false
        val names = words.filter { !it.all { c -> c.isDigit() } }  // "Donald J. Trump @handle 2h"
        if (skipNames && names.size <= (if (words.size < tokens.size) 3 else 2) && names.all { it.first().isUpperCase() }) return false
        return true
    }

    private val termSplit = Regex("""\s*(?:=|＝|->|→)\s*""")

    /** A glossary line: "NVIDIA" is never translated; "thread = 執行緒" is always translated that way.
     *  Returns the term and the chosen translation (null: none). */
    fun splitTerm(line: String): Pair<String, String?> {
        val parts = line.trim().split(termSplit, 2)
        return if (parts.size == 2 && parts[0].isNotEmpty() && parts[1].isNotEmpty()) parts[0] to parts[1] else line.trim() to null
    }

    private class Span(val first: Int, val last: Int, val forced: String?)

    /** Swaps proper nouns and chosen terms for placeholders ("Z0Z") so the translator leaves them alone. */
    fun protect(text: String, glossary: List<String>, latin: Boolean): Pair<String, List<String>> {
        val spans = mutableListOf<Span>()
        for (line in glossary.sortedByDescending { it.length }) {
            val (term, forced) = splitTerm(line)
            if (term.isBlank()) continue
            // a chosen translation matches whole words (and a plural), so "thread" does not hit "threading"
            val pattern = if (forced != null && term.all { it.code < 128 }) {
                "(?<![A-Za-z0-9])" + Regex.escape(term) + "(?:e?s)?(?![A-Za-z0-9])"
            } else Regex.escape(term)
            Regex(pattern, RegexOption.IGNORE_CASE).findAll(text).forEach { spans += Span(it.range.first, it.range.last, forced) }
        }
        if (latin) {
            val words = latinWord.findAll(text).toList()
            val titleCase = words.size >= 3 && words.count { it.value[0].isUpperCase() }.toDouble() / words.size >= 0.6
            for (m in words) {
                val w = m.value
                val before = text.substring(0, m.range.first).trimEnd()
                val sentenceStart = before.isEmpty() || before.last() in ".!?:\"“"
                val isCamel = camel.containsMatchIn(w)
                val allCaps = w.length >= 2 && w.none { it.isLowerCase() } && w.any { it.isLetter() }
                val capitalMid = w[0].isUpperCase() && !sentenceStart && w.length > 1 && !titleCase
                if (isCamel || allCaps || capitalMid) spans += Span(m.range.first, m.range.last, null)
            }
        }
        spans.sortWith(compareBy({ it.first }, { -it.last }))
        class Group(val first: Int, var last: Int, val chosen: MutableList<Span>)
        val merged = mutableListOf<Group>()
        for (s in spans) {
            val group = merged.lastOrNull()
            if (group != null && (s.first <= group.last || text.substring(group.last + 1, s.first).isBlank())) {
                group.last = maxOf(group.last, s.last)
                if (s.forced != null && group.chosen.none { it.first <= s.last && s.first <= it.last }) group.chosen += s
            } else merged += Group(s.first, s.last, if (s.forced != null) mutableListOf(s) else mutableListOf())
        }
        val originals = mutableListOf<String>()
        val out = StringBuilder()
        var pos = 0
        for (s in merged) {
            out.append(text, pos, s.first).append(" Z${originals.size}Z ")
            val shown = StringBuilder(text.substring(s.first, s.last + 1))
            for (c in s.chosen.sortedByDescending { it.first }) {  // the chosen translations replace their source words
                shown.replace(c.first - s.first, c.last - s.first + 1, c.forced!!)
            }
            originals += shown.toString()
            pos = s.last + 1
        }
        out.append(text.substring(pos))
        return out.toString().replace(spaces, " ").trim() to originals
    }

    fun restore(text: String, originals: List<String>): String =
        placeholder.replace(text) { m -> originals.getOrNull(m.groupValues[1].toInt()) ?: m.value }
            .replace(spaces, " ").trim()

    /** True if nothing translatable is left once the placeholders are removed. */
    fun onlyPlaceholders(protectedText: String) = protectedText.replace(placeholder, "").none { it.isLetter() }

    /** Letters and digits only, lowercased: for comparing OCR text with our own translations. */
    fun normalize(text: String) = text.filter { it.isLetterOrDigit() }.lowercase()
}
