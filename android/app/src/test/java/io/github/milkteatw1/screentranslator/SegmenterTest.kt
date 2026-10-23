package io.github.milkteatw1.screentranslator

import org.junit.Assert.assertEquals
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test
import kotlin.math.sin

class SegmenterTest {
    private fun tone(level: Float) = FloatArray(1600) { (level * sin(it * 0.3)).toFloat() }
    private fun quiet() = FloatArray(1600) { 0.0003f * ((it % 7) - 3) }

    /** Feeds [chunks]; returns the lengths (in chunks of 0.1 s) of the sentences that came out. */
    private fun cut(chunks: List<FloatArray>): List<Int> {
        val seg = Segmenter()
        return chunks.mapNotNull { seg.feed(it) }.map { it.size / 1600 }
    }

    @Test
    fun aSentenceEndsAfterAShortQuiet() {
        val out = cut(List(10) { quiet() } + List(15) { tone(0.1f) } + List(10) { quiet() })
        assertEquals(1, out.size)
        assertTrue(out[0] in 15..25)
    }

    @Test
    fun talkWithoutAPauseIsCutSoCaptionsKeepComing() {
        val out = cut(List(5) { quiet() } + List(200) { tone(0.1f) })  // 20 s of talk, no pause
        assertTrue("long talk must be cut into several sentences, got $out", out.size >= 2)
        assertTrue(out.all { it <= 82 })  // never longer than MAX_SEGMENT (8 s) plus the pre-roll
    }

    @Test
    fun quietSpeechIsStillHeard() {
        val out = cut(List(20) { quiet() } + List(15) { tone(0.004f) } + List(10) { quiet() })
        assertEquals(1, out.size)
    }

    @Test
    fun aClickIsNotSpeech() {
        assertTrue(cut(List(10) { quiet() } + List(2) { tone(0.1f) } + List(10) { quiet() }).isEmpty())
    }

    @Test
    fun theSentenceSoFarIsAvailableWhileSpeaking() {
        val seg = Segmenter()
        repeat(5) { seg.feed(quiet()) }
        repeat(8) { assertNull(seg.feed(tone(0.1f))) }
        assertTrue(seg.speaking)
        assertNotNull(seg.snapshot())
    }

    @Test
    fun normalizeLiftsQuietSpeechButNotLoudSpeech() {
        val quietRms = normalize(FloatArray(1000) { 0.005f }).first()
        assertEquals(0.08f, quietRms, 0.001f)
        assertEquals(0.5f, normalize(FloatArray(1000) { 0.5f }).first(), 0.0001f)
    }
}
