package io.github.milkteatw1.screentranslator

import org.junit.Assert.assertEquals
import org.junit.Test

class CaptionLookTest {
    @Test fun valuesOutsideTheirRangeAreBroughtBack() {
        val look = CaptionLook.of(5000, 1, -20, true, 0, false)
        assertEquals(100, look.widthPct)
        assertEquals(14, look.fontSp)
        assertEquals(0, look.opacityPct)
        assertEquals(1, look.lines)
    }

    @Test fun theOriginalIsTwoThirdsOfTheTranslationAndTheBackgroundAlphaFollowsTheShare() {
        val look = CaptionLook(fontSp = 30, opacityPct = 50)
        assertEquals(20, look.originalSp)
        assertEquals(128, look.backgroundAlpha)
        assertEquals(255, CaptionLook(opacityPct = 100).backgroundAlpha)
        assertEquals(10, CaptionLook(fontSp = 14).originalSp.coerceAtLeast(10))
    }
}
