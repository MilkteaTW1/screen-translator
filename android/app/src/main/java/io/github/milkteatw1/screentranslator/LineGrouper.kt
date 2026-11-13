package io.github.milkteatw1.screentranslator

import kotlin.math.abs
import kotlin.math.max
import kotlin.math.min

/**
 * Builds paragraphs from the text lines OCR found. ML Kit's own "blocks" often glue unrelated things together (a post's
 * title and the link below it, a caption and the picture beside it); the lines themselves are reliable, so the
 * paragraphs are built here from their geometry: a line continues the paragraph above it when it is about as tall, sits
 * right below it and lines up with it. Links and sloped text (labels printed on pictures) are left out. Pure logic.
 */
object LineGrouper {
    /** One OCR line: its box in screen pixels, its text, and how many degrees its baseline slopes. */
    class Line(val left: Float, val top: Float, val right: Float, val bottom: Float, val text: String, val tilt: Float = 0f) {
        val height get() = bottom - top
        val width get() = right - left
    }

    /** A paragraph: the box around its lines, the text and the height of one line. */
    class Paragraph(val left: Float, val top: Float, val right: Float, val bottom: Float, val text: String, val lineHeight: Float)

    private const val MAX_TILT = 4f  // degrees; text on a record label or a banner is curved or sloped, UI text is straight
    private const val MAX_GAP = 0.9f  // lines apart by more than this many line heights are not one paragraph
    private val spaces = Regex("""\s+""")
    private val linkToken = Regex("""^(https?:|www\.)|^[\w-]+(\.[\w-]+)+/|\.(com|org|net|io|tw|edu|gov|co|jp|uk|de)(/|$)""", RegexOption.IGNORE_CASE)

    /** True for a line that is a web address (or a piece of one): nothing to translate. */
    fun isLink(text: String): Boolean {
        val tokens = text.trim().split(spaces).filter { it.isNotEmpty() }
        if (tokens.isEmpty()) return false
        val sure = tokens.count { linkToken.containsMatchIn(it) }
        val likely = tokens.count { linkToken.containsMatchIn(it) || it.contains('_') || it.contains('/') }
        return likely == tokens.size || (sure >= 1 && likely * 2 >= tokens.size)
    }

    private fun endsSentence(t: String) = t.trimEnd().let { it.endsWith(".") || it.endsWith("!") || it.endsWith("?") || it.endsWith("。") || it.endsWith("！") || it.endsWith("？") }

    private class Open(var left: Float, var top: Float, var right: Float, var bottom: Float, val lines: MutableList<Line>) {
        val last get() = lines.last()
        val widest get() = lines.maxOf { it.width }
    }

    private fun continues(p: Open, l: Line): Boolean {
        val prev = p.last
        val lh = max(prev.height, l.height)
        val ratio = l.height / max(1f, prev.height)
        if (ratio < 0.7f || ratio > 1.45f) return false  // another size of text: another thing
        val gap = l.top - prev.bottom
        if (gap > MAX_GAP * lh || gap < -0.6f * lh) return false
        val overlap = min(prev.right, l.right) - max(prev.left, l.left)
        if (overlap <= 0.3f * min(prev.width, l.width)) return false  // beside it, not below it
        val aligned = abs(prev.left - l.left) <= 1.5f * lh || abs(prev.right - l.right) <= 1.5f * lh ||
            abs((prev.left + prev.right) / 2 - (l.left + l.right) / 2) <= 1.5f * lh
        if (!aligned) return false
        // A short last line that ends a sentence closes the paragraph (list items, one-line comments).
        if (endsSentence(prev.text) && prev.width < 0.6f * max(p.widest, l.width) && l.left - prev.left < 0.5f * lh && prev.left - p.left < 0.5f * lh) return false
        return true
    }

    fun group(lines: List<Line>, joiner: String = " "): List<Paragraph> {
        val usable = lines.filter { it.text.isNotBlank() && it.height > 0f && abs(it.tilt) <= MAX_TILT && !isLink(it.text) }
            .sortedWith(compareBy({ it.top }, { it.left }))
        val open = ArrayList<Open>()
        for (l in usable) {
            val target = open.filter { continues(it, l) }.minByOrNull { l.top - it.last.bottom }
            if (target == null) {
                open += Open(l.left, l.top, l.right, l.bottom, mutableListOf(l))
            } else {
                target.lines += l
                target.left = min(target.left, l.left); target.top = min(target.top, l.top)
                target.right = max(target.right, l.right); target.bottom = max(target.bottom, l.bottom)
            }
        }
        val all = open.map { p ->
            val heights = p.lines.map { it.height }.sorted()
            val text = p.lines.joinToString(joiner) { it.text.trim() }.replace(spaces, " ").trim()
            Paragraph(p.left, p.top, p.right, p.bottom, if (p.lines.size == 1) dropChevrons(text) else text, heights[heights.size / 2]) to p.lines.size
        }
        // A single small line among much bigger text is a label printed on a picture (a record, a logo, a thumbnail
        // caption), not part of the page: it is not read.
        val sizes = all.filter { it.second >= 2 || it.first.right - it.first.left > 250f }.map { it.first.lineHeight }.sorted()
        val body = if (sizes.size >= 3) sizes[sizes.size * 3 / 4] else 0f
        return all.filter { (p, n) -> p.text.isNotBlank() && !(n == 1 && body > 0f && p.lineHeight < 0.62f * body && p.right - p.left < 0.45f * body * 12) }
            .map { it.first }.sortedWith(compareBy({ it.top }, { it.left }))
    }

    private val chevron = Regex("""(^|\s)[vV^<>›‹»«](?=\s|$)""")

    /** A drop-down arrow is read as a letter "v": in a short label it is dropped. */
    fun dropChevrons(text: String): String =
        if (text.split(spaces).size <= 4) chevron.replace(text, " ").replace(spaces, " ").trim() else text

    /** Degrees the top edge of a box slopes, from its first two corner points (the corners come clockwise from top-left). */
    fun tilt(x0: Float, y0: Float, x1: Float, y1: Float): Float =
        Math.toDegrees(Math.atan2((y1 - y0).toDouble(), (x1 - x0).toDouble())).toFloat()
}
