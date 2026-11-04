package io.github.milkteatw1.screentranslator

import org.junit.Assert.assertEquals
import org.junit.Test

class TaiwanWordsTest {
    private val table = TaiwanWords.parse(listOf("內存\t記憶體", "設置\t設定", "應用程序\t應用程式", "程序\t程式", "bad line"))

    @Test fun mainlandWordsBecomeTaiwanOnes() {
        assertEquals("在設定裡增加記憶體", TaiwanWords.apply("在設置裡增加內存", table))
    }

    @Test fun theLongestMatchWins() {
        assertEquals("應用程式和程式", TaiwanWords.apply("應用程序和程序", table))
    }

    @Test fun textWithoutThemAndAnEmptyTableStayAsTheyAre() {
        assertEquals("你好", TaiwanWords.apply("你好", table))
        assertEquals("內存", TaiwanWords.apply("內存", emptyMap()))
    }
}
