package io.github.milkteatw1.screentranslator

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Test
import java.io.File

class TranslationMemoryTest {
    private fun file() = File.createTempFile("memory", ".jsonl").apply { delete(); deleteOnExit() }

    @Test
    fun aTranslationSurvivesARestartAndOcrSpacingDoesNotMatter() {
        val f = file()
        TranslationMemory(f).put("en|zh-TW|1", "Hello there,  world.", "你好")
        assertEquals("你好", TranslationMemory(f).get("en|zh-TW|1", "Hello there,\nworld."))
    }

    @Test
    fun anotherLanguageOrGlossaryIsAnotherEntry() {
        val f = file()
        val m = TranslationMemory(f)
        m.put("en|zh-TW|1", "Hello", "你好")
        assertNull(m.get("en|ja|1", "Hello"))
        assertNull(m.get("en|zh-TW|2", "Hello"))
    }

    @Test
    fun aDamagedLineOnlyLosesThatLineAndClearDeletesTheFile() {
        val f = file()
        TranslationMemory(f).put("s", "Hello", "你好")
        f.appendText("[\"s|cut off")
        val m = TranslationMemory(f)
        assertEquals("你好", m.get("s", "Hello"))
        m.clear()
        assertFalse(f.exists())
        assertNull(m.get("s", "Hello"))
    }

    @Test
    fun theOldestAreDroppedPastTheLimit() {
        val f = file()
        val m = TranslationMemory(f, max = 3, keep = 2)
        for (i in 1..4) m.put("s", "text $i", "t$i")
        val again = TranslationMemory(f)
        assertNull(again.get("s", "text 1"))
        assertEquals("t4", again.get("s", "text 4"))
    }
}
