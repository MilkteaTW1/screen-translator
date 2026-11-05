package io.github.milkteatw1.screentranslator

import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

class DeeplTranslateTest {
    private val traditional = Lang("中文(繁體)", "zh", Script.CHINESE, traditional = true)
    private val simplified = Lang("中文", "zh", Script.CHINESE)
    private val english = Lang("English", "en")

    @Test fun freeKeysUseTheFreeAddress() {
        assertTrue(DeeplTranslate.endpoint("abc:fx").startsWith("https://api-free.deepl.com"))
        assertTrue(DeeplTranslate.endpoint("abc").startsWith("https://api.deepl.com"))
    }

    @Test fun languagesAreNamedTheWayDeeplWantsThem() {
        assertEquals("ZH-HANT", DeeplTranslate.targetCode(traditional))
        assertEquals("ZH-HANS", DeeplTranslate.targetCode(simplified))
        assertEquals("EN-US", DeeplTranslate.targetCode(english))
        assertEquals("JA", DeeplTranslate.targetCode(Lang("日本語", "ja")))
        assertEquals("EN", DeeplTranslate.sourceCode(english))
    }

    @Test fun theRequestListsTheTextsAndTheLanguages() {
        val body = org.json.JSONObject(DeeplTranslate.body(listOf("Hello   there", "Bye"), english, traditional))
        assertEquals("Hello there", body.getJSONArray("text").getString(0))
        assertEquals("ZH-HANT", body.getString("target_lang"))
        assertEquals("EN", body.getString("source_lang"))
        assertTrue(!org.json.JSONObject(DeeplTranslate.body(listOf("x"), null, traditional)).has("source_lang"))
    }

    @Test fun theAnswerMustHaveOneTranslationForEachText() {
        val answer = """{"translations":[{"text":"你好"},{"text":"再見"}]}"""
        assertEquals(listOf("你好", "再見"), DeeplTranslate.parse(answer, 2))
        assertNull(DeeplTranslate.parse(answer, 3))
        assertNull(DeeplTranslate.parse("nonsense", 1))
    }
}
