package io.github.milkteatw1.screentranslator

/**
 * For "auto" speech: the eight-language streaming model starts at once, and Whisper listens to the sentences it
 * finishes. This says when a language the captions cannot read is being spoken, so they can move to a reader that
 * knows it. Pure logic, so it is unit tested (the same rules as the desktop app).
 */
class AutoLanguage {
    companion object {
        const val MIN_PROB = 0.6f   // a guess weaker than this counts for nothing
        const val SURE_PROB = 0.9f  // one sentence this sure is enough; weaker ones must repeat
    }

    private var sentences = 0
    private var other: String? = null  // the language outside the captions' own of the last guess, and how often it came in a row
    private var times = 0

    /** True when this finished sentence should be checked: all of the first three, then one in four (Whisper costs CPU). */
    fun due(): Boolean {
        sentences++
        return sentences <= 3 || sentences % 4 == 0
    }

    /** Feed one guess; returns the language code to move to, or null to stay. */
    fun add(language: String, prob: Float): String? {
        val code = if (language == "yue") "zh" else language
        if (prob < MIN_PROB) return null
        if (code in StreamingModel.AUTO_LANGS) {  // the captions already read it
            other = null
            times = 0
            return null
        }
        times = if (code == other) times + 1 else 1
        other = code
        return if (prob >= SURE_PROB || times >= 2) code else null
    }
}
