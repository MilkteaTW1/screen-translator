package io.github.milkteatw1.screentranslator

/** How a text block is lined up on the page, read from the blocks just above and below it, so a translation laid
 *  over it can be lined up the same way. */
object CoverAlign {
    const val LEFT = 0
    const val CENTER = 1
    const val RIGHT = 2

    class Edges(val left: Float, val top: Float, val right: Float, val bottom: Float) {
        val centerX get() = (left + right) / 2
        val centerY get() = (top + bottom) / 2
        val width get() = right - left
        val height get() = bottom - top
    }

    /** Left, centre or right: whichever edge the neighbours agree with most (left wins a tie, as justified text does).
     *  A block with no neighbour to compare with is taken to be left-aligned. */
    fun of(src: Edges, lineHeight: Float, others: List<Edges>): Int {
        val tol = maxOf(4f, lineHeight * 0.4f)
        var left = 0
        var right = 0
        var centre = 0
        for (o in others) {
            if (Math.abs(o.centerY - src.centerY) > src.height / 2 + o.height / 2 + lineHeight * 2.5f) continue
            if (minOf(o.right, src.right) - maxOf(o.left, src.left) < 0.3f * minOf(o.width, src.width)) continue
            if (Math.abs(o.left - src.left) <= tol) left++
            if (Math.abs(o.right - src.right) <= tol) right++
            if (Math.abs(o.centerX - src.centerX) <= tol) centre++
        }
        return when {
            centre > left && centre >= right -> CENTER
            right > left -> RIGHT
            else -> LEFT
        }
    }
}
