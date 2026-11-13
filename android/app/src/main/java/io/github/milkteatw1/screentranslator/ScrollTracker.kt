package io.github.milkteatw1.screentranslator

import kotlin.math.abs

/**
 * Follows a page that scrolls (vertically) without reading it again. A translation is made once; when the page moves
 * the whole picture shifts as one piece. That shift is measured between two screen pictures and the translations are
 * moved with it, so they glide along with their text instead of vanishing and reappearing.
 */
object ScrollTracker {
    /** A coarse brightness picture of the screen: [cols] x [rows] samples, one every [stepX] / [stepY] pixels.
     *  A value of -1 means "ignore this sample" (our own drawing on the screen). */
    class Grid(val cols: Int, val rows: Int, val stepX: Int, val stepY: Int, val v: IntArray) {
        fun copy() = Grid(cols, rows, stepX, stepY, v.copyOf())

        /** Marks the samples inside the given screen rectangles (left, top, right, bottom) as ignored. */
        fun mask(rects: List<FloatArray>) {
            for (r in rects) {
                val c0 = (r[0] / stepX).toInt().coerceIn(0, cols); val c1 = (r[2] / stepX).toInt().plus(1).coerceIn(0, cols)
                val r0 = (r[1] / stepY).toInt().coerceIn(0, rows); val r1 = (r[3] / stepY).toInt().plus(1).coerceIn(0, rows)
                for (y in r0 until r1) for (x in c0 until c1) v[y * cols + x] = -1
            }
        }

        /** Every [k] rows averaged into one (a sample is ignored if any of its rows is). */
        fun shrinkRows(k: Int): Grid {
            val n = rows / k
            val out = IntArray(n * cols)
            for (y in 0 until n) for (x in 0 until cols) {
                var sum = 0
                var bad = false
                for (j in 0 until k) {
                    val s = v[(y * k + j) * cols + x]
                    if (s < 0) { bad = true; break }
                    sum += s
                }
                out[y * cols + x] = if (bad) -1 else sum / k
            }
            return Grid(cols, n, stepX, stepY * k, out)
        }
    }

    private const val MIN_SAMPLES = 400  // fewest samples that can tell a shift from chance
    private const val MIN_OVERLAP = 0.3  // share of the screen that must still be in both pictures to compare them

    /** Mean absolute brightness difference between [a] and [b] when [b] is [a] moved down by [dy] rows, over the rows
     *  [r0] until [r1] of [a] (null: all) and columns [c0] until [c1]. [Double.MAX_VALUE] when too little is comparable. */
    fun difference(a: Grid, b: Grid, dy: Int, r0: Int = 0, r1: Int = a.rows, c0: Int = 0, c1: Int = a.cols): Double {
        var sum = 0L
        var n = 0
        var usable = 0  // samples of [a] that are not painted out: only those can be compared
        val from = maxOf(r0, -dy, 0)
        val to = minOf(r1, a.rows, b.rows - dy)
        for (y in from until to) {
            val ia = y * a.cols
            val ib = (y + dy) * b.cols
            for (x in c0 until c1) {
                val p = a.v[ia + x]
                if (p >= 0) usable++
                val q = b.v[ib + x]
                if (p < 0 || q < 0) continue
                sum += abs(p - q)
                n++
            }
        }
        // Our own boxes can paint out most of a busy screen; what is left is still a fair witness if it is enough
        // samples and still a good share of what is left of the screen (judging against the whole screen made every
        // scroll under big boxes look like "another page").
        val whole = (r1 - r0) * (c1 - c0)
        val enough = n >= MIN_SAMPLES && n >= MIN_OVERLAP * minOf(whole, maxOf(usable, 1) * 2)
        return if (!enough && n < MIN_OVERLAP * whole) Double.MAX_VALUE else sum.toDouble() / maxOf(n, 1)
    }

    /** How many pixels the content moved down between [prev] and [cur] (negative: up); 0 if it did not move;
     *  null if the picture did not simply shift (another page, a video). Pictures must have the same size. */
    fun estimate(prev: Grid, cur: Grid): Int? {
        if (prev.cols != cur.cols || prev.rows != cur.rows || prev.rows < 40) return null
        val k = 4
        val cp = prev.shrinkRows(k)
        val cc = cur.shrinkRows(k)
        val still = difference(cp, cc, 0)
        if (still < 1.5) return 0
        val limit = (cp.rows * 0.6).toInt()  // a longer jump is more likely a mismatch than one scroll step
        var best = Double.MAX_VALUE
        var bestDy = 0
        for (d in -limit..limit) {
            val m = difference(cp, cc, d)
            if (m < best - 0.05 || (abs(m - best) <= 0.05 && abs(d) < abs(bestDy))) { best = m; bestDy = d }
        }
        // The coarse picture only says roughly where to look; the exact shift, and whether this is a shift at all,
        // are decided on the fine picture (rows averaged four at a time blur a shift that is not a multiple of four).
        var fine = bestDy * k
        var fineBest = Double.MAX_VALUE
        for (d in bestDy * k - k..bestDy * k + k) {
            val m = difference(prev, cur, d)
            if (m < fineBest - 0.05 || (abs(m - fineBest) <= 0.05 && abs(d - bestDy * k) < abs(fine - bestDy * k))) { fineBest = m; fine = d }
        }
        val stillFine = difference(prev, cur, 0)
        if (fine == 0) return if (stillFine < 8) 0 else null
        if (fineBest == Double.MAX_VALUE || fineBest > 0.4 * stillFine || fineBest > 40) return null  // not a clean shift
        return fine * prev.stepY
    }

    /** A guess at the shift of a frame that could not be measured, for a page that was scrolling a moment ago:
     *  the speed of the last measured shift (px/s, down positive) over the time since, slowed down a little because a
     *  scroll that cannot be measured is usually one that is dying out. Better a box a few pixels off for one frame than
     *  every box thrown away. */
    fun predict(velocity: Float, seconds: Float): Int = (velocity * seconds.coerceIn(0f, 0.3f) * 0.6f).toInt()

    /** True if the picture inside rows [r0] until [r1] and columns [c0] until [c1] clearly stayed where it was while the
     *  rest moved by [dy] rows (a fixed header or toolbar). */
    fun stayed(prev: Grid, cur: Grid, dy: Int, r0: Int, r1: Int, c0: Int, c1: Int): Boolean {
        val stay = difference(prev, cur, 0, r0, r1, c0, c1)
        if (stay == Double.MAX_VALUE) return false
        val go = difference(prev, cur, dy, r0, r1, c0, c1)
        return stay < 6 && (go == Double.MAX_VALUE || stay < 0.7 * go)
    }
}
