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

    @Test fun sentencesThatMentionAHandleOrUseCapitalsAreStillSource() {
        for (t in listOf(
            "We've been improving the #JetpackCompose documentation with loads of small fixes, but also new docs in general!",
            "Donald J. Trump TO THE GREAT PEOPLE OF ALABAMA, MAKE A PLAN TO VOTE FOR:",
            "Katherine Robertson for Attorney General",
            "LIVE: President Trump Holds a Rally in Sioux City, IA 10/22/26",
            "grok @bot 0.75.2 is out!"))
            assertTrue(t, TextRules.looksLikeSource(t, en))
    }

    @Test fun linksHandlesCountersAndNamesAreStillNotSource() {
        for (t in listOf("developer.android.com/develop/ui/com...", "@real... CJ", "Donald J. Trump @realDonal... 2",
            "249 754 2.8K 579K", "Rebecca Franks"))
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

    @Test
    fun rowsOfDotsReadAsLettersAreNotText() {
        val en = Langs.sources.first { it.code == "en" }
        assertFalse(TextRules.looksLikeSource("oooooooooooooooooooo oooooooooooooooooooo", en))
        assertFalse(TextRules.looksLikeSource("oOo0o oo0oo OOOo0", en))
        assertTrue(TextRules.looksLikeSource("The river trail is closed north of the old bridge", en))
    }

    @Test
    fun aChosenTranslationReplacesTheTermAndKeepsTheSentence() {
        val (p, originals) = TextRules.protect("Share one thread, so every live update waited.", listOf("thread = 執行緒", "live update=即時更新"), false)
        assertFalse(p.contains("thread") || p.contains("live update"))
        assertEquals(listOf("執行緒", "即時更新"), originals)
    }

    @Test
    fun aChosenTranslationMatchesWholeWordsAndPluralsOnly() {
        val (p, originals) = TextRules.protect("Threading and threads", listOf("thread=執行緒"), false)
        assertEquals(listOf("執行緒"), originals)
        assertTrue(p.contains("Threading"))
    }

    @Test fun daysAndMonthsAreTranslatedNotKeptAsNames() {
        val (_, originals) = TextRules.protect("The museum reopened on Saturday after a long break in March.", emptyList(), true, "en")
        assertEquals(emptyList<String>(), originals)
    }

    @Test fun germanNounsAreNotTakenForNames() {
        val (_, originals) = TextRules.protect("Wir haben gestern den Bericht an die Firma geschickt.", emptyList(), true, "de")
        assertEquals(emptyList<String>(), originals)
    }

    @Test fun aLineInCapitalsIsWordsAndChosenTermsKeepTheirForm() {
        val (plain, none) = TextRules.protect("FREE SHIPPING ON ALL ORDERS", emptyList(), true)
        assertEquals("free shipping on all orders", plain)
        assertEquals(emptyList<String>(), none)
        val (_, chosen) = TextRules.protect("NVIDIA DRIVERS ARE READY", listOf("NVIDIA"), true)
        assertEquals(listOf("NVIDIA"), chosen)
        assertEquals(listOf("NASA"), TextRules.protect("The NASA team", emptyList(), true).second)
    }

    @Test fun twoWordButtonsAreNotTakenForNames() {
        for (label in listOf("Sign In", "Log Out", "Read More", "Contact Us"))
            assertEquals(label, emptyList<String>(), TextRules.protect(label, emptyList(), true).second)
    }

    @Test
    fun tilIsSpelledOutSoItIsNotCarriedOverAsAName() {
        assertEquals("Today I learned Pixar did this", TextRules.expandAbbreviations("TIL Pixar did this"))
        assertEquals("Today I learned the song was made", TextRules.expandAbbreviations("TIL: the song was made"))
        assertEquals("Until later", TextRules.expandAbbreviations("Until later"))
    }
}
