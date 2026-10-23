package io.github.milkteatw1.screentranslator

import kotlin.math.sqrt

/**
 * Cuts a stream of 0.1 s audio chunks (16 kHz, -1..1) into sentences: speech starts above the background noise, ends
 * after a short quiet, and long talk without a pause is cut anyway so captions keep coming (the same rules as the
 * desktop app). Pure logic, so it is unit tested.
 */
class Segmenter(private val rate: Int = 16000) {
    companion object {
        const val SILENCE_END = 0.6  // seconds of quiet that end a sentence
        const val SOFT_SEGMENT = 5.0  // after this, even a short pause ends it
        const val SOFT_PAUSE = 0.25
        const val MAX_SEGMENT = 8.0  // cut here whatever happens
        const val MIN_SPEECH = 0.4  // shorter sounds are clicks, not speech
        const val PRE_ROLL = 3  // chunks kept from before the speech started
    }

    private var floor = 0.002  // background noise level, followed slowly
    private val pre = ArrayDeque<FloatArray>()
    private val buf = ArrayList<FloatArray>()
    private var speech = 0.0
    private var quiet = 0.0
    var fresh = 0.0  // seconds heard since the last live update
        private set

    val speaking get() = buf.isNotEmpty()

    /** The sentence so far, or null when nobody is speaking. */
    fun snapshot(): FloatArray? = if (speech >= MIN_SPEECH) join(buf).also { fresh = 0.0 } else null

    /** Feeds one chunk; returns a finished sentence, or null. */
    fun feed(chunk: FloatArray): FloatArray? {
        val seconds = chunk.size.toDouble() / rate
        val level = rms(chunk)
        val onset = maxOf(0.0015, 3 * floor)
        val keep = maxOf(0.0008, 1.6 * floor)
        if (buf.isEmpty()) {
            floor = if (level < floor) level * 0.3 + floor * 0.7 else floor * 0.995 + level * 0.005
            floor = floor.coerceIn(0.0002, 0.05)
            if (level < onset) {
                pre.addLast(chunk)
                while (pre.size > PRE_ROLL) pre.removeFirst()
                return null
            }
            buf.addAll(pre)
            pre.clear()
            speech = 0.0
            quiet = 0.0
            fresh = 0.0
        }
        buf.add(chunk)
        fresh += seconds
        if (level >= keep) { speech += seconds; quiet = 0.0 } else quiet += seconds
        val length = buf.size * seconds
        val done = quiet >= SILENCE_END || (length >= SOFT_SEGMENT && quiet >= SOFT_PAUSE) || length >= MAX_SEGMENT
        if (!done) return null
        val out = if (speech >= MIN_SPEECH) join(buf) else null
        buf.clear()
        speech = 0.0
        quiet = 0.0
        return out
    }

    private fun rms(a: FloatArray): Double {
        var s = 0.0
        for (v in a) s += v * v
        return sqrt(s / maxOf(1, a.size))
    }

    private fun join(parts: List<FloatArray>): FloatArray {
        val out = FloatArray(parts.sumOf { it.size })
        var i = 0
        for (p in parts) { p.copyInto(out, i); i += p.size }
        return out
    }
}

/** Quiet speech is lifted to a steady level (at most 30x) so it is heard like normal speech. */
fun normalize(audio: FloatArray, target: Float = 0.08f, maxGain: Float = 30f): FloatArray {
    var s = 0.0
    for (v in audio) s += v * v
    val rms = sqrt(s / maxOf(1, audio.size)).toFloat()
    if (rms <= 0f) return audio
    val gain = minOf(maxGain, target / rms)
    if (gain <= 1f) return audio
    return FloatArray(audio.size) { (audio[it] * gain).coerceIn(-1f, 1f) }
}
