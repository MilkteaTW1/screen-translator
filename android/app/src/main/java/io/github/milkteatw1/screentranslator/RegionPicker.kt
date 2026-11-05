package io.github.milkteatw1.screentranslator

import android.content.Context
import android.graphics.Canvas
import android.graphics.Color
import android.graphics.Paint
import android.graphics.Rect
import android.view.MotionEvent
import android.view.View

/** Full-screen layer for choosing the part of the screen that is translated: drag a rectangle. [onDone] gets the
 *  rectangle in screen pixels, or null for "the whole screen" (also when it is cancelled with the button). */
class RegionPicker(context: Context, private val whole: String, private val hint: String,
                   private val onDone: (Rect?) -> Unit) : View(context) {
    private val dim = Paint().apply { color = Color.argb(110, 0, 0, 0) }
    private val clear = Paint().apply { xfermode = android.graphics.PorterDuffXfermode(android.graphics.PorterDuff.Mode.CLEAR) }
    private val line = Paint(Paint.ANTI_ALIAS_FLAG).apply { color = Color.rgb(60, 140, 255); style = Paint.Style.STROKE; strokeWidth = 4f }
    private val text = Paint(Paint.ANTI_ALIAS_FLAG).apply { color = Color.WHITE; textSize = 16f * resources.displayMetrics.scaledDensity; textAlign = Paint.Align.CENTER }
    private val button = Paint(Paint.ANTI_ALIAS_FLAG).apply { color = Color.argb(220, 30, 90, 200) }
    private var x0 = 0f
    private var y0 = 0f
    private var x1 = 0f
    private var y1 = 0f
    private var dragging = false
    private val buttonRect = android.graphics.RectF()

    init { setLayerType(LAYER_TYPE_HARDWARE, null) }

    fun selection(): Rect? {
        val r = Rect(minOf(x0, x1).toInt(), minOf(y0, y1).toInt(), maxOf(x0, x1).toInt(), maxOf(y0, y1).toInt())
        return if (r.width() >= MIN && r.height() >= MIN) r else null
    }

    override fun onDraw(canvas: Canvas) {
        canvas.drawRect(0f, 0f, width.toFloat(), height.toFloat(), dim)
        val sel = if (dragging || x1 != x0) selection() else null
        if (sel != null) {
            canvas.drawRect(sel, clear)
            canvas.drawRect(sel, line)
        } else {
            canvas.drawText(hint, width / 2f, height * 0.4f, text)
        }
        val w = text.measureText(whole) + 48f
        buttonRect.set(width / 2f - w / 2, height * 0.5f, width / 2f + w / 2, height * 0.5f + text.textSize * 2.4f)
        if (sel == null) {
            canvas.drawRoundRect(buttonRect, 24f, 24f, button)
            canvas.drawText(whole, buttonRect.centerX(), buttonRect.centerY() + text.textSize / 3, text)
        }
    }

    override fun onTouchEvent(e: MotionEvent): Boolean {
        when (e.actionMasked) {
            MotionEvent.ACTION_DOWN -> {
                if (!dragging && x0 == x1 && buttonRect.contains(e.x, e.y)) { onDone(null); return true }
                x0 = e.x; y0 = e.y; x1 = e.x; y1 = e.y; dragging = true
            }
            MotionEvent.ACTION_MOVE -> { x1 = e.x; y1 = e.y; invalidate() }
            MotionEvent.ACTION_UP -> {
                x1 = e.x; y1 = e.y; dragging = false
                val sel = selection()
                if (sel != null) onDone(sel) else { x0 = 0f; y0 = 0f; x1 = 0f; y1 = 0f; invalidate() }
            }
        }
        return true
    }

    companion object { const val MIN = 80 }
}
