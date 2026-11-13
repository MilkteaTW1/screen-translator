package io.github.milkteatw1.screentranslator

import org.junit.Assert.assertEquals
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

class SpokenLanguagesTest {
    private val codes = Langs.spoken.map { it.code }

    @Test
    fun pickerHasNoDuplicatesAndManyLanguages() {
        assertEquals(codes.size, codes.toSet().size)
        assertTrue("only ${codes.size} spoken languages", codes.size >= 24)
    }

    @Test
    fun pickerOffersEveryLanguageAScreenCanBeReadIn() {
        for (l in Langs.sources) assertTrue(l.code, l.code in codes)
    }

    @Test
    fun pickerOffersEveryLanguageAStreamingModelReads() {
        for (m in StreamingModel.models) for (code in m.langs) assertTrue("$code is not in the picker", code in codes)
    }

    @Test
    fun everyLanguageIsReadBySomething() {
        // fast where a streaming model reads it, otherwise Whisper (null): nothing is dropped, nothing is English-only
        for (code in codes) {
            val spec = StreamingModel.specFor(code)
            if (spec != null) assertTrue(code, code in spec.langs)
        }
        assertNull(StreamingModel.specFor("nl"))
        assertNull(StreamingModel.specFor("tr"))
        assertNotNull(StreamingModel.specFor("ru"))
    }

    @Test
    fun languagesTheAutoModelCannotReadStayWithWhisper() {
        for (code in listOf("fr", "de", "es", "nl", "tr")) assertTrue(code, code !in StreamingModel.AUTO_LANGS)
    }
}
