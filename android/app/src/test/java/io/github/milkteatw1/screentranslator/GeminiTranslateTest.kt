package io.github.milkteatw1.screentranslator

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

class GeminiTranslateTest {
    private val traditional = Lang("中文(繁體)", "zh", Script.CHINESE, traditional = true)

    @Test fun theAnswerMayComeInACodeFence() {
        assertEquals(listOf("你好", "再見"), GeminiTranslate.parse("```json\n[\"你好\", \"再見\"]\n```", 2))
    }

    @Test fun anAnswerWithTheWrongNumberOfLinesIsRefused() {
        assertNull(GeminiTranslate.parse("[\"一個\"]", 2))
        assertNull(GeminiTranslate.parse("not json at all", 1))
        assertNull(GeminiTranslate.parse("[1, 2]", 2))
    }

    @Test fun theServersReasonIsPassedOnInBothShapes() {
        val wrapped = "[{\"error\": {\"code\": 400, \"message\": \"Please pass a valid API key\"}}]"
        assertEquals("HTTP 400 Please pass a valid API key", GeminiTranslate.errorText(400, wrapped))
        assertEquals("HTTP 429 slow down", GeminiTranslate.errorText(429, "{\"error\": {\"message\": \"slow down\"}}"))
        assertEquals("HTTP 500 oops", GeminiTranslate.errorText(500, "oops"))
    }

    @Test fun thePromptNamesTheLanguageAndKeepsTheOrder() {
        val prompt = GeminiTranslate.prompt(listOf("Hello  there", "Bye"), traditional)
        assertTrue(prompt.contains("Traditional Chinese"))
        assertTrue(prompt.endsWith("[\"Hello there\",\"Bye\"]"))
    }

    @Test fun aRetiredModelIsReplacedButAWrongKeyIsNot() {
        assertTrue(GeminiTranslate.modelUnavailable(404, "HTTP 404 models/x is not found"))
        assertTrue(GeminiTranslate.modelUnavailable(429, "HTTP 429 quota exceeded"))
        assertFalse(GeminiTranslate.modelUnavailable(400, "HTTP 400 API key not valid. Please pass a valid API key."))
        assertFalse(GeminiTranslate.modelUnavailable(500, "HTTP 500 oops"))
        assertEquals("gemini-3.5-flash-lite", GeminiTranslate.MODELS.first())
    }
}
