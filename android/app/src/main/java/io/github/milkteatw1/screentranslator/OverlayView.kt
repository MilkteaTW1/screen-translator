package io.github.milkteatw1.screentranslator

import android.content.Context
import android.graphics.Canvas
import android.graphics.Color
import android.graphics.Paint
import android.graphics.RectF
import android.text.Layout
import android.text.StaticLayout
import android.text.TextPaint
import android.view.View

/** Full-screen, touch-through layer. Each translation is drawn directly above its text block, centred on it. */
class OverlayView(context: Context) : View(context) {
    /** [lineHeight] is the height of one source text line, in pixels. */
    class Box(val src: RectF, val text: String, val lineHeight: Float, val mode: Int = ABOVE)

    companion object {
        const val ABOVE = 0
        const val BELOW = 1
        const val COVER = 2  // no free space near the text: the translation is laid over it
        private const val MIN_COVER_SP = 10f  // smallest text size when fitting a translation over its original
    }

    @Volatile
    var boxes: List<Box> = emptyList()
        set(value) {
            field = value
            boxesAt = android.os.SystemClock.uptimeMillis()
            postInvalidate()
        }

    /** The page is scrolling at this many px/s (down positive): between two updates the boxes are carried along at that
     *  speed, so they glide with their text instead of jumping once per update. 0: not scrolling. */
    @Volatile var glide = 0f
    private var boxesAt = 0L

    /** What was just heard and its translation, newest last; [partial] is the sentence still being spoken. */
    @Volatile
    var captions: List<Pair<String, String>> = emptyList()
        set(value) {
            field = value
            postInvalidate()
        }

    @Volatile
    var partial: Pair<String, String> = "" to ""  // what is being said, and its translation so far
        set(value) {
            field = value
            postInvalidate()
        }

    private val density = resources.displayMetrics.density
    private val fill = Paint(Paint.ANTI_ALIAS_FLAG).apply { color = Color.argb(225, 20, 20, 20) }
    private val cover = Paint(Paint.ANTI_ALIAS_FLAG).apply { color = Color.argb(245, 20, 20, 20) }
    private val ink =TextPaint(Paint.ANTI_ALIAS_FLAG).apply { color = Color.rgb(255, 235, 140) }

    /** Translations laid over long text can be hidden with one tap on the floating button. */
    @Volatile
    var hideCovers = false
        set(value) {
            field = value
            postInvalidate()
        }

    private fun layoutFor(b: Box, maxWidth: Float, textSize: Float): StaticLayout {
        ink.textSize = textSize
        return StaticLayout.Builder.obtain(b.text, 0, b.text.length, ink, (maxWidth - 12).toInt().coerceAtLeast(1))
            .setAlignment(Layout.Alignment.ALIGN_NORMAL).build()
    }

    private fun idealSize(b: Box) = (b.lineHeight * 0.85f).coerceIn(14 * density, 26 * density)

    private fun sideWidth(b: Box) = maxOf(b.src.width(), width * 0.5f).coerceAtMost(width - 16f)

    /** Size (width, height) the translation needs next to its text, so the service can look for room. */
    fun measure(b: Box): Pair<Float, Float> {
        val layout = layoutFor(b, sideWidth(b), idealSize(b))
        var w = 12f
        for (i in 0 until layout.lineCount) w = maxOf(w, layout.getLineWidth(i) + 12)
        return w to layout.height + 8f
    }

    override fun onDraw(canvas: Canvas) {
        drawCaptions(canvas)
        val carried = if (glide != 0f) glide * ((android.os.SystemClock.uptimeMillis() - boxesAt) / 1000f).coerceIn(0f, 0.25f) else 0f
        canvas.save()
        canvas.translate(0f, carried)
        for (b in boxes) {
            if (b.mode == COVER) {
                if (!hideCovers) drawCover(canvas, b)
                continue
            }
            val layout = layoutFor(b, sideWidth(b), idealSize(b))
            var boxWidth = 12f
            for (i in 0 until layout.lineCount) boxWidth = maxOf(boxWidth, layout.getLineWidth(i) + 12)
            val boxHeight = layout.height + 8f
            // Position depends only on the block itself, so it never hops around.
            val left = (b.src.centerX() - boxWidth / 2).coerceIn(0f, maxOf(0f, width - boxWidth))
            val top = if (b.mode == BELOW) b.src.bottom + 2 else (b.src.top - boxHeight - 2).coerceAtLeast(0f)
            canvas.drawRoundRect(RectF(left, top, left + boxWidth, top + boxHeight), 8f, 8f, fill)
            canvas.save()
            canvas.translate(left + 6, top + 4)
            layout.draw(canvas)
            canvas.restore()
        }
        canvas.restore()
        if (glide != 0f) postInvalidateOnAnimation()
    }

    /** No free space near the text: the translation is laid over it, shrunk to fit the same area. */
    private fun drawCover(canvas: Canvas, b: Box) {
        // A short label (a button, a menu item) gets some room to the sides, so its translation does not
        // wrap one character per line; the box stays centred on the original.
        val natural = measure(b).first
        val w = maxOf(b.src.width(), minOf(natural, b.src.width() * 1.6f, width - 16f)).coerceAtLeast(40 * density)
        val left = if (w <= b.src.width() + 1f) b.src.left else (b.src.centerX() - w / 2).coerceIn(0f, maxOf(0f, width - w))
        var size = idealSize(b)
        var layout = layoutFor(b, w, size)
        // Small screens leave little room: shrink the text to fit the original's area...
        while (layout.height + 8 > b.src.height() && size > MIN_COVER_SP * density) {
            size -= density / 2
            layout = layoutFor(b, w, size)
        }
        // ...and never grow past 1.4x its height, so one translation cannot bury the lines below it.
        val maxHeight = b.src.height() * 1.4f
        if (layout.height + 8 > maxHeight) {
            val lines = ((maxHeight - 8) / (layout.height.toFloat() / layout.lineCount)).toInt().coerceAtLeast(1)
            ink.textSize = size
            layout = StaticLayout.Builder.obtain(b.text, 0, b.text.length, ink, (w - 12).toInt().coerceAtLeast(1))
                .setAlignment(Layout.Alignment.ALIGN_NORMAL).setMaxLines(lines)
                .setEllipsize(android.text.TextUtils.TruncateAt.END).build()
        }
        val h = maxOf(b.src.height(), layout.height + 8f)
        canvas.drawRoundRect(RectF(left, b.src.top, left + w, b.src.top + h), 8f, 8f, cover)
        canvas.save()
        canvas.translate(left + 6, b.src.top + 4)
        layout.draw(canvas)
        canvas.restore()
    }

    /** The speech strip: a list at the bottom of the screen, newest line lowest. */
    private fun drawCaptions(canvas: Canvas) {
        val lines = captions.takeLast(4)
        val live = partial
        if (lines.isEmpty() && live.first.isEmpty()) return
        val boxWidth = width * 0.94f
        val left = (width - boxWidth) / 2
        val said = TextPaint(Paint.ANTI_ALIAS_FLAG).apply { color = Color.rgb(210, 210, 210); textSize = 18 * density }
        val spoken = TextPaint(Paint.ANTI_ALIAS_FLAG).apply { color = Color.rgb(255, 235, 140); textSize = 26 * density; isFakeBoldText = true }
        var bottom = height - 72 * density
        // The sentence being spoken shows its last words only, so a long one never fills the screen.
        val rows = lines + (if (live.first.isNotEmpty()) listOf(live.first.takeLast(160) to live.second.takeLast(120)) else emptyList())
        for ((heard, translated) in rows.reversed()) {
            val layouts = listOf(translated to spoken, heard to said).filter { it.first.isNotEmpty() }.map { (t, p) ->
                StaticLayout.Builder.obtain(t, 0, t.length, p, (boxWidth - 24).toInt()).build()
            }
            val live = heard == rows.last().first && translated == rows.last().second && this.partial.first.isNotEmpty()
            val boxHeight = maxOf(layouts.sumOf { it.height } + 16f, if (live) 2f * (spoken.fontSpacing + said.fontSpacing) * 0.75f + 16f else 0f)  // the live row does not jump as it grows
            val top = bottom - boxHeight
            canvas.drawRoundRect(RectF(left, top, left + boxWidth, bottom), 12f, 12f, fill)
            var y = top + 8
            for (layout in layouts) {
                canvas.save()
                canvas.translate(left + 12, y)
                layout.draw(canvas)
                canvas.restore()
                y += layout.height
            }
            bottom = top - 6
        }
    }
}
