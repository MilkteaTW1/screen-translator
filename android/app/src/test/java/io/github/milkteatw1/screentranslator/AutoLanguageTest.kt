package io.github.milkteatw1.screentranslator

import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

class AutoLanguageTest {
    @Test
    fun movesOnOnlyForAClearOtherLanguage() {
        var w = AutoLanguage()
        assertNull(w.add("en", 0.99f)); assertNull(w.add("zh", 0.9f)); assertNull(w.add("yue", 0.9f))
        assertNull(w.add("ja", 0.99f)); assertNull(w.add("ru", 0.99f))  // the auto model reads them already
        assertNull(w.add("fr", 0.4f))  // too unsure
        assertNull(w.add("fr", 0.7f))  // once and not sure: wait
        assertEquals("fr", w.add("fr", 0.7f))  // twice in a row
        w = AutoLanguage()
        assertEquals("ko", w.add("ko", 0.95f))  // once but very sure
        w = AutoLanguage()
        assertNull(w.add("fr", 0.7f)); assertNull(w.add("en", 0.9f)); assertNull(w.add("fr", 0.7f))  // English in between: start over
    }

    @Test
    fun differentOtherLanguagesDoNotAddUp() {
        val w = AutoLanguage()
        assertNull(w.add("fr", 0.7f)); assertNull(w.add("de", 0.7f)); assertNull(w.add("fr", 0.7f))
    }

    @Test
    fun cantoneseCountsAsChinese() {
        val w = AutoLanguage()
        assertNull(w.add("yue", 0.99f))
    }

    @Test
    fun checksTheFirstSentencesThenOneInFour() {
        val w = AutoLanguage()
        val due = List(12) { w.due() }
        assertEquals(listOf(true, true, true), due.take(3))
        assertEquals(listOf(true, false, false, false, true), due.subList(3, 8))
        assertEquals(6, due.count { it })
    }

    @Test
    fun theAutoLanguagesAreEnglishChineseAndTheMultiModelsOnes() {
        assertEquals(setOf("en", "zh", "ja", "ru", "th", "vi", "ar", "id"), StreamingModel.AUTO_LANGS)
        assertTrue("ko" !in StreamingModel.AUTO_LANGS)
    }
}
