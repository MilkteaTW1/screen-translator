package io.github.milkteatw1.screentranslator

import org.junit.Assert.assertEquals
import org.junit.Test

class CoverAlignTest {
    private fun e(x: Float, w: Float, y: Float = 0f) = CoverAlign.Edges(x, y, x + w, y + 20f)

    @Test fun followsTheNeighbouringBlocks() {
        assertEquals(CoverAlign.LEFT, CoverAlign.of(e(100f, 300f), 20f, listOf(e(100f, 200f, 25f), e(100f, 250f, -25f))))
        assertEquals(CoverAlign.CENTER, CoverAlign.of(e(200f, 200f), 20f, listOf(e(150f, 300f, 25f), e(250f, 100f, -25f))))
        assertEquals(CoverAlign.RIGHT, CoverAlign.of(e(300f, 100f), 20f, listOf(e(200f, 200f, 25f), e(250f, 150f, -25f))))
    }

    @Test fun aloneOrFarFromOthersIsLeft() {
        assertEquals(CoverAlign.LEFT, CoverAlign.of(e(300f, 100f), 20f, emptyList()))
        assertEquals(CoverAlign.LEFT, CoverAlign.of(e(300f, 100f), 20f, listOf(e(300f, 100f, 900f))))
    }
}
