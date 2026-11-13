package io.github.milkteatw1.screentranslator

import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

class KeyCheckTest {
    private val gemini = KeyCheck::geminiVerdict
    private fun answer(content: String) =
        org.json.JSONObject().put("choices", org.json.JSONArray().put(org.json.JSONObject()
            .put("message", org.json.JSONObject().put("content", content)))).toString()

    @Test fun aGeminiAnswerWithOneLineIsAWorkingKey() {
        assertEquals(KeyCheck.Verdict.Works("你好,世界。"), gemini(200, answer("```json\n[\"你好,世界。\"]\n```")))
    }

    @Test fun anEmptyOrWrongShapedAnswerIsNotAWorkingKey() {
        assertTrue(gemini(200, answer("[\"  \"]")) is KeyCheck.Verdict.Fails)
        assertTrue(gemini(200, answer("[\"a\", \"b\"]")) is KeyCheck.Verdict.Fails)
        assertTrue(gemini(200, "not json") is KeyCheck.Verdict.Fails)
    }

    @Test fun aRefusedKeyFailsButAnUnavailableModelTriesTheNext() {
        val bad = gemini(400, """[{"error":{"message":"API key not valid. Please pass a valid API key."}}]""")
        assertTrue(bad is KeyCheck.Verdict.Fails && "API key not valid" in bad.why)
        assertTrue(gemini(404, """{"error":{"message":"models/x is not found"}}""") is KeyCheck.Verdict.ModelUnavailable)
    }

    @Test fun deeplIsReadFromItsTranslationsList() {
        assertEquals(KeyCheck.Verdict.Works("你好"), KeyCheck.deeplVerdict(200, """{"translations":[{"text":" 你好 "}]}"""))
        val denied = KeyCheck.deeplVerdict(403, "Forbidden")
        assertTrue(denied is KeyCheck.Verdict.Fails && ":fx" in denied.why)
        assertTrue(KeyCheck.deeplVerdict(200, """{"translations":[]}""") is KeyCheck.Verdict.Fails)
    }

    @Test fun theSampleIsNeverEnglishToEnglish() {
        assertEquals("fr", KeyCheck.sampleTarget(Lang("English", "en")).code)
        assertEquals("ja", KeyCheck.sampleTarget(Lang("日本語", "ja")).code)
    }
}
