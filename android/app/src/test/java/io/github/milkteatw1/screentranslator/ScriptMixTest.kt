package io.github.milkteatw1.screentranslator

import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

class ScriptMixTest {
    private val zh = ScriptMix.ownLetter("zh")!!

    @Test fun targetScriptWordsAreNeverSent() {
        assertTrue(ScriptMix.foreignRuns("我今天去公司", zh).isEmpty())
        assertEquals("", ScriptMix.mix("我今天去公司", zh) { error("asked") })
    }

    @Test fun aRunOfForeignWordsIsTranslatedAsOneAndPutBack() {
        val asked = ArrayList<String>()
        val out = ScriptMix.mix("我覺得 this is really good 而且很便宜", zh) { asked.add(it); "這真的很好" }
        assertEquals(listOf("this is really good"), asked)
        assertEquals("我覺得 這真的很好 而且很便宜", out)
        assertEquals("我覺得 hello 很好", ScriptMix.mix("我覺得 hello 很好", zh) { "" })
    }

    @Test fun languagesWithoutAScriptOfTheirOwnAreLeftToTheLanguageGuess() {
        assertEquals(null, ScriptMix.ownLetter("en"))
    }
}
