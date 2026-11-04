package io.github.milkteatw1.screentranslator

import org.junit.Assert.assertEquals
import org.junit.Test

class GoogleBudgetTest {
    @Test fun requestsOverTheBudgetAreRefusedUntilTheWindowHasPassed() {
        GoogleTranslate.resetBudget()
        assertEquals(listOf(true, true, false), listOf(0L, 1L, 2L).map { GoogleTranslate.takeSlot(it, 2) })
        assertEquals(true, GoogleTranslate.takeSlot(60_000L, 2))
        GoogleTranslate.resetBudget()
    }
}
