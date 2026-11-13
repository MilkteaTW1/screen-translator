package io.github.milkteatw1.screentranslator

/** How the speech captions look; every value is the user's choice and is kept inside its range. */
data class CaptionLook(
    val widthPct: Int = 94,       // share of the screen width
    val fontSp: Int = 26,         // translation text size; the original is two thirds of it
    val opacityPct: Int = 88,     // background: 0 see-through ... 100 solid
    val top: Boolean = false,     // at the top of the screen instead of the bottom
    val lines: Int = 4,           // most captions shown at once
    val showOriginal: Boolean = true,
) {
    val originalSp: Int get() = maxOf(10, Math.round(fontSp * 2f / 3f))
    val backgroundAlpha: Int get() = Math.round(255 * opacityPct / 100f)

    companion object {
        val WIDTH = 30..100
        val FONT = 14..48
        val OPACITY = 0..100
        val LINES = 1..8

        fun of(widthPct: Int, fontSp: Int, opacityPct: Int, top: Boolean, lines: Int, showOriginal: Boolean) = CaptionLook(
            widthPct.coerceIn(WIDTH), fontSp.coerceIn(FONT), opacityPct.coerceIn(OPACITY), top, lines.coerceIn(LINES), showOriginal)

        fun from(prefs: Prefs) = of(prefs.captionWidth, prefs.captionFont, prefs.captionOpacity, prefs.captionTop,
            prefs.captionLines, prefs.captionShowOriginal)
    }
}
