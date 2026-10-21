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
    class Box(val src: RectF, val text: String, val lineHeight: Float)

    @Volatile
    var boxes: List<Box> = emptyList()
        set(value) {
            field = value
            postInvalidate()
        }

    private val density = resources.displayMetrics.density
    private val fill = Paint(Paint.ANTI_ALIAS_FLAG).apply { color = Color.argb(225, 20, 20, 20) }
    private val ink = TextPaint(Paint.ANTI_ALIAS_FLAG).apply { color = Color.rgb(255, 235, 140) }

    override fun onDraw(canvas: Canvas) {
        for (b in boxes) {
            ink.textSize = (b.lineHeight * 0.85f).coerceIn(14 * density, 26 * density)
            val maxWidth = maxOf(b.src.width(), width * 0.5f).coerceAtMost(width - 16f)
            val layout = StaticLayout.Builder.obtain(b.text, 0, b.text.length, ink, (maxWidth - 12).toInt().coerceAtLeast(1))
                .setAlignment(Layout.Alignment.ALIGN_NORMAL).build()
            var boxWidth = 12f
            for (i in 0 until layout.lineCount) boxWidth = maxOf(boxWidth, layout.getLineWidth(i) + 12)
            val boxHeight = layout.height + 8f
            // Position depends only on the block itself, so it never hops between above and below.
            val left = (b.src.centerX() - boxWidth / 2).coerceIn(0f, maxOf(0f, width - boxWidth))
            val top = (b.src.top - boxHeight - 2).coerceAtLeast(0f)
            canvas.drawRoundRect(RectF(left, top, left + boxWidth, top + boxHeight), 8f, 8f, fill)
            canvas.save()
            canvas.translate(left + 6, top + 4)
            layout.draw(canvas)
            canvas.restore()
        }
    }
}
