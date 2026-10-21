package io.github.milkteatw1.screentranslator

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class TextRulesTest {
    private val en = Lang("English", "en")
    private val ja = Lang("Japanese", "ja", Script.JAPANESE)
    private val zh = Lang("Chinese", "zh", Script.CHINESE)

    @Test fun englishSentenceIsSource() =
        assertTrue(TextRules.looksLikeSource("This is a normal sentence about cats.", en))

    @Test fun urlsHandlesAndSingleWordsAreNot() {
        for (t in listOf("https://example.com/page", "@someone_else", "Premium", "a1b2c3d4e5"))
            assertFalse(t, TextRules.looksLikeSource(t, en))
    }

    @Test fun chineseIsNotJapanese() = assertFalse(TextRules.looksLikeSource("這是一段中文內容", ja))

    @Test fun kanaTextIsJapanese() = assertTrue(TextRules.looksLikeSource("これは日本語の文章です", ja))

    @Test fun hanTextIsChinese() = assertTrue(TextRules.looksLikeSource("這是一段中文內容", zh))

    @Test fun properNounsRoundTrip() {
        val text = "I met Hatsune Miku at the NVIDIA event"
        val (protectedText, originals) = TextRules.protect(text, listOf("Hatsune Miku"), true)
        assertFalse(protectedText.contains("Hatsune"))
        assertEquals(text, TextRules.restore(protectedText, originals))
    }
}
