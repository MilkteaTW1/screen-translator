package io.github.milkteatw1.screentranslator

import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test
import java.util.Random

class ScrollTrackerTest {
    private val cols = 60
    private val rows = 600  // a 2400 px tall screen sampled every 4 px
    private val stepY = 4

    /** A page of "text": lines of strokes (a pattern across the columns, the same on every row of the line, a little
     *  noisy), with gaps between the lines. [seed] makes it different. */
    private fun page(seed: Long, length: Int = rows * 3): IntArray {
        val rnd = Random(seed)
        val out = IntArray(length * cols) { 20 }
        var y = 0
        while (y < length) {
            val lineRows = 3 + rnd.nextInt(3)
            val strokes = IntArray(cols) { if (rnd.nextInt(3) > 0) 90 + rnd.nextInt(160) else 20 }
            for (r in 0 until lineRows) if (y + r < length) for (x in 0 until cols) out[(y + r) * cols + x] = (strokes[x] + rnd.nextInt(9) - 4).coerceIn(0, 255)
            y += lineRows + 2 + rnd.nextInt(6)
        }
        return out
    }

    /** The screen showing rows [top] until [top] + [rows] of [page]. */
    private fun view(page: IntArray, top: Int) = ScrollTracker.Grid(cols, rows, 4, stepY, page.copyOfRange(top * cols, (top + rows) * cols))

    @Test
    fun aStillPictureIsNotAScroll() {
        val p = page(1)
        assertEquals(0, ScrollTracker.estimate(view(p, 100), view(p, 100)))
    }

    @Test
    fun theShiftOfAScrolledPageIsMeasuredExactly() {
        val p = page(2)
        // the page moves up on screen (we scroll down): content moves by a negative amount
        for (rowsMoved in listOf(3, 12, 40, 150, 330)) {
            val dy = ScrollTracker.estimate(view(p, 200), view(p, 200 + rowsMoved))
            assertEquals("scrolled $rowsMoved rows", -rowsMoved * stepY, dy)
        }
        // and back up
        assertEquals(90 * stepY, ScrollTracker.estimate(view(p, 500), view(p, 410)))
    }

    @Test
    fun anotherPageIsNotAShift() {
        assertNull(ScrollTracker.estimate(view(page(3), 0), view(page(4), 0)))
    }

    @Test
    fun ourOwnBoxesDoNotHideTheShift() {
        val p = page(5)
        val a = view(p, 100)
        val b = view(p, 130)
        // a translation box drawn at the same screen place in both pictures (it does not scroll)
        for (g in listOf(a, b)) for (y in 100 until 160) for (x in 5 until 55) g.v[y * cols + x] = 200
        val box = listOf(floatArrayOf(5f * 4, 100f * stepY, 55f * 4, 160f * stepY))
        a.mask(box); b.mask(box)
        assertEquals(-30 * stepY, ScrollTracker.estimate(a, b))
    }

    @Test
    fun aFixedHeaderStaysWhileThePageMoves() {
        val p = page(6)
        val a = view(p, 100)
        val b = view(p, 130)
        for (g in listOf(a, b)) for (y in 0 until 30) for (x in 0 until cols) g.v[y * cols + x] = if ((x + y) % 2 == 0) 230 else 40
        val dy = ScrollTracker.estimate(a, b)!!
        assertTrue(ScrollTracker.stayed(a, b, dy / stepY, 0, 30, 0, cols))
        assertTrue(!ScrollTracker.stayed(a, b, dy / stepY, 200, 260, 0, cols))
    }
}
