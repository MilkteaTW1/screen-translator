package io.github.milkteatw1.screentranslator

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class LineGrouperTest {
    private fun line(text: String, top: Int, left: Int = 36, right: Int = 600, h: Int = 40, tilt: Float = 0f) =
        LineGrouper.Line(left.toFloat(), top.toFloat(), right.toFloat(), (top + h).toFloat(), text, tilt)

    @Test
    fun linesOfOneParagraphAreJoined() {
        val out = LineGrouper.group(listOf(line("TIL the song Play That Funky Music", 100), line("by Wild Cherry came about when", 148), line("they were playing for a crowd", 196)))
        assertEquals(1, out.size)
        assertEquals("TIL the song Play That Funky Music by Wild Cherry came about when they were playing for a crowd", out[0].text)
        assertEquals(100f, out[0].top, 0f)
        assertEquals(236f, out[0].bottom, 0f)
    }

    @Test
    fun aLinkBelowTheTitleIsNotPartOfIt() {
        val out = LineGrouper.group(listOf(line("wrote up the song in 5 minutes.", 100), line("https://en.wikipedia.org/wiki/Play_That_Funky...", 150, h = 34)))
        assertEquals(1, out.size)
        assertEquals("wrote up the song in 5 minutes.", out[0].text)
    }

    @Test
    fun aGarbledLinkIsStillALink() {
        assertTrue(LineGrouper.isLink("https://en.wikipedia.org/wiki/ Play"))
        assertTrue(LineGrouper.isLink("https://en. wikipedia.org/wiki/ Pröduction _babies"))
        assertTrue(LineGrouper.isLink("www.example.com"))
        assertFalse(LineGrouper.isLink("I read it on wikipedia yesterday"))
        assertFalse(LineGrouper.isLink("Is this and/or that a good idea"))
    }

    @Test
    fun textBesideAPictureIsAnotherParagraph() {
        val body = listOf(line("Johnny Depp starred in this", 100, right = 500), line("and it lost a lot of money", 148, right = 500))
        val label = line("PLAY THAT FUNKY MUSIC", 110, left = 640, right = 860, h = 30)
        val out = LineGrouper.group(body + label)
        assertEquals(2, out.size)
        assertEquals("Johnny Depp starred in this and it lost a lot of money", out[0].text)
    }

    @Test
    fun slopedTextOnAPictureIsLeftOut() {
        val out = LineGrouper.group(listOf(line("STEREO 45 RPM", 100, tilt = 12f), line("A real sentence here", 300)))
        assertEquals(listOf("A real sentence here"), out.map { it.text })
    }

    @Test
    fun aBiggerHeadingIsNotMergedIntoTheTextBelow() {
        val out = LineGrouper.group(listOf(line("Big heading", 100, h = 70), line("small text under it", 180, h = 36)))
        assertEquals(2, out.size)
    }

    @Test
    fun separatePostsStayApart() {
        val out = LineGrouper.group(listOf(line("First post ends here.", 100, right = 300), line("Second post starts right below", 150)))
        assertEquals(2, out.size)
    }

    @Test
    fun aBigGapSeparatesParagraphs() {
        val out = LineGrouper.group(listOf(line("Upper paragraph text", 100), line("Lower paragraph text", 300)))
        assertEquals(2, out.size)
    }

    @Test
    fun lineHeightIsTheMedian() {
        val out = LineGrouper.group(listOf(line("aaaa bbbb cccc", 100, h = 40), line("dddd eeee ffff", 148, h = 44), line("gggg hhhh iiii", 200, h = 41)))
        assertEquals(41f, out[0].lineHeight, 0f)
    }

    @Test
    fun cjkLinesJoinWithoutSpaces() {
        val out = LineGrouper.group(listOf(line("這是第一行", 100), line("這是第二行", 148)), joiner = "")
        assertEquals("這是第一行這是第二行", out[0].text)
    }

    @Test
    fun tiltOfTheTopEdge() {
        assertEquals(0f, LineGrouper.tilt(0f, 10f, 100f, 10f), 0.01f)
        assertEquals(45f, LineGrouper.tilt(0f, 0f, 10f, 10f), 0.01f)
    }

    @Test
    fun aTinyLabelAmongBigTextIsLeftOut() {
        val out = LineGrouper.group(listOf(
            line("Some long title text goes here", 100, h = 44), line("and continues on this line", 150, h = 44),
            line("Another long paragraph start", 400, h = 44), line("with its second line", 450, h = 44),
            line("Third paragraph first line", 700, h = 44), line("Third paragraph second line", 750, h = 44),
            line("PLAY THAT FUNKY MUSIC", 900, left = 640, right = 860, h = 22)))
        assertEquals(3, out.size)
        assertTrue(out.none { it.text.contains("FUNKY") })
    }

    @Test
    fun smallTextAloneIsKept() {
        val out = LineGrouper.group(listOf(line("a small footnote on its own", 100, h = 22), line("another small note below it", 130, h = 22)))
        assertEquals(1, out.size)
    }

    @Test
    fun dropDownArrowsAreNotText() {
        assertEquals("Today", LineGrouper.dropChevrons("Today v"))
        assertEquals("Top Today", LineGrouper.dropChevrons("Top v Today v"))
        assertEquals("a v b c d e", LineGrouper.dropChevrons("a v b c d e"))
    }
}
