package io.github.milkteatw1.screentranslator

import org.junit.Assert.assertEquals
import org.junit.Test

class GoogleTranslateTest {
    @Test
    fun linesComeBackOneForOne() {
        assertEquals(listOf("你好", "再見"), GoogleTranslate.matchLines("你好\n再見", 2))
    }

    @Test
    fun aMismatchGivesNothingRatherThanTheWrongLine() {
        assertEquals(listOf(null, null, null), GoogleTranslate.matchLines("你好\n再見", 3))
        assertEquals(listOf(null, null), GoogleTranslate.matchLines(null, 2))
    }

    @Test
    fun anEmptyLineIsNoTranslation() {
        assertEquals(listOf("你好", null), GoogleTranslate.matchLines("你好\n  ", 2))
    }
}
