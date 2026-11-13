package io.github.milkteatw1.screentranslator

import org.junit.Assert.assertEquals
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test
import java.io.File

class StreamingModelTest {
    @Test
    fun autoStartsOnTheEightLanguageModel() {
        assertEquals("multi", StreamingModel.specFor("auto")!!.key)
        assertEquals("multi", StreamingModel.useFor(true, "auto")!!.key)
        assertNull(StreamingModel.useFor(false, "auto"))
    }

    @Test
    fun autoTakesADownloadedModelBeforeAskingForTheBigOne() {
        val zhEn = StreamingModel.models.first { it.key == "zh-en" }
        assertEquals("zh-en", StreamingModel.usable("auto") { it.key == "zh-en" }!!.key)
        assertEquals("multi", StreamingModel.usable("auto") { true }!!.key)  // both there: the eight-language one
        assertEquals("multi", StreamingModel.usable("auto") { false }!!.key)  // none: that one has to be downloaded
        assertEquals("en", StreamingModel.usable("en") { it == zhEn }!!.key)  // a chosen language ignores what is there
    }

    @Test
    fun autoMovesToALanguagesOwnModelOnlyWhenItIsDownloaded() {
        assertEquals("ko", StreamingModel.readerFor("ko") { true }!!.key)
        assertNull(StreamingModel.readerFor("ko") { false })  // Whisper then
        assertNull(StreamingModel.readerFor("fr") { true })  // no streaming model for French
    }

    @Test
    fun eachLanguageGetsTheModelThatReadsIt() {
        assertEquals("en", StreamingModel.specFor("en")!!.key)
        assertEquals("zh-en", StreamingModel.specFor("zh")!!.key)
        assertEquals("ko", StreamingModel.specFor("ko")!!.key)
        for (code in listOf("ja", "vi", "id", "ru", "th", "ar")) assertEquals(code, "multi", StreamingModel.specFor(code)!!.key)
    }

    @Test
    fun languagesWithoutAStreamingModelUseWhisper() {
        for (code in listOf("fr", "de", "es", "it", "pt")) assertNull(code, StreamingModel.specFor(code))
    }

    @Test
    fun accurateModeNeverStreams() {
        assertNull(StreamingModel.useFor(false, "en"))
        assertNotNull(StreamingModel.useFor(true, "en"))
    }

    @Test
    fun everyModelListsFourFilesAndTokensLast() {
        for (m in StreamingModel.models) {
            assertEquals(m.key, 4, m.files.size)
            assertEquals("tokens.txt", m.files[3])
            assertTrue(m.url(m.files[0]).startsWith("https://huggingface.co/${m.repo}/resolve/main/"))
        }
    }

    @Test
    fun missingFilesAreTheOnesNotYetDownloaded() {
        val spec = StreamingModel.specFor("en")!!
        val dir = kotlin.io.path.createTempDirectory("stream").toFile()
        try {
            assertEquals(spec.files, StreamingModel.missingFiles(spec, dir))
            File(dir, spec.files[0]).writeText("x")
            File(dir, spec.files[3]).writeText("")  // empty: a broken file counts as missing
            assertEquals(listOf(spec.files[1], spec.files[2], spec.files[3]), StreamingModel.missingFiles(spec, dir))
            for (f in spec.files) File(dir, f).writeText("x")
            assertTrue(StreamingModel.missingFiles(spec, dir).isEmpty())
        } finally { dir.deleteRecursively() }
    }

    @Test
    fun progressStaysBelowOneHundredUntilDone() {
        assertEquals(0, StreamingModel.percent(0, 72))
        assertEquals(50, StreamingModel.percent(36_000_000, 72))
        assertEquals(99, StreamingModel.percent(500_000_000, 72))
    }

    @Test
    fun capitalsBecomeASentence() {
        assertEquals("Hello world", StreamingModel.tidy("HELLO WORLD"))
        assertEquals("I think I am", StreamingModel.tidy("I THINK I AM"))
        assertEquals("你好 world", StreamingModel.tidy("你好  world"))
        assertEquals("iPhone", StreamingModel.tidy(" iPhone "))
        assertEquals("", StreamingModel.tidy("   "))
    }

    @Test
    fun languageIsGuessedOnlyForAuto() {
        assertEquals("ja", StreamingModel.guessLanguage("こんにちは", "ja"))
        assertEquals("zh", StreamingModel.guessLanguage("你好", "auto"))
        assertEquals("en", StreamingModel.guessLanguage("hello", "auto"))
        assertEquals("ja", StreamingModel.guessLanguage("今日はいい天気です", "auto"))  // kana wins over Han
        assertEquals("th", StreamingModel.guessLanguage("สวัสดีครับ", "auto"))
        assertEquals("ru", StreamingModel.guessLanguage("привет мир", "auto"))
        assertEquals("ar", StreamingModel.guessLanguage("مرحبا", "auto"))
        assertEquals("vi", StreamingModel.guessLanguage("Xin chào các bạn", "auto"))
    }
}
