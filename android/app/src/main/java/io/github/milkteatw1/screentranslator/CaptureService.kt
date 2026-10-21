package io.github.milkteatw1.screentranslator

import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.app.Service
import android.content.Context
import android.content.Intent
import android.content.pm.ServiceInfo
import android.graphics.Bitmap
import android.graphics.PixelFormat
import android.graphics.RectF
import android.hardware.display.DisplayManager
import android.hardware.display.VirtualDisplay
import android.media.ImageReader
import android.media.projection.MediaProjection
import android.media.projection.MediaProjectionManager
import android.os.Build
import android.os.Handler
import android.os.HandlerThread
import android.os.IBinder
import android.os.Looper
import android.util.DisplayMetrics
import android.util.Log
import android.view.WindowManager
import com.google.android.gms.tasks.Tasks
import com.google.mlkit.nl.translate.Translation
import com.google.mlkit.nl.translate.Translator
import com.google.mlkit.nl.translate.TranslatorOptions
import com.google.mlkit.vision.common.InputImage
import com.google.mlkit.vision.text.TextRecognition
import com.google.mlkit.vision.text.TextRecognizer
import com.google.mlkit.vision.text.chinese.ChineseTextRecognizerOptions
import com.google.mlkit.vision.text.japanese.JapaneseTextRecognizerOptions
import com.google.mlkit.vision.text.korean.KoreanTextRecognizerOptions
import com.google.mlkit.vision.text.latin.TextRecognizerOptions
import java.util.concurrent.TimeUnit

/** Captures the screen, reads the text on it, translates it and keeps the overlay up to date. */
class CaptureService : Service() {
    companion object {
        @Volatile var running = false
        const val ACTION_STOP = "stop"
        const val EXTRA_CODE = "code"
        const val EXTRA_DATA = "data"
        private const val CHANNEL = "capture"
        private const val TAG = "ScreenTranslator"
        private const val MAX_NEW_PER_SCAN = 30
        private const val BATCH = 5
    }

    /** A text block followed from scan to scan, so what is on screen stays steady. */
    private class Track(var rect: RectF, var lineHeight: Float, val text: String) {
        var translation: String? = null
        var done = false
        var seen = 1
        var missed = 0
    }

    private class Block(val rect: RectF, val text: String, val lineHeight: Float)

    private val main = Handler(Looper.getMainLooper())
    private val thread = HandlerThread("capture").apply { start() }
    private lateinit var handler: Handler
    private lateinit var prefs: Prefs
    private lateinit var src: Lang
    private lateinit var tgt: Lang
    private var overlay: OverlayView? = null
    private var projection: MediaProjection? = null
    private var reader: ImageReader? = null
    private var display: VirtualDisplay? = null
    private var recognizer: TextRecognizer? = null
    private var translator: Translator? = null
    private var width = 0
    private var height = 0
    private var tracks = listOf<Track>()
    private var previous: IntArray? = null
    private var staticScreen = false
    private var glossary = listOf<String>()
    private val cache = HashMap<String, String>()
    private var shown = listOf<String>()
    private var hansHant: android.icu.text.Transliterator? = null

    override fun onBind(intent: Intent?): IBinder? = null

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        if (intent == null || intent.action == ACTION_STOP) {
            stopSelf()
            return START_NOT_STICKY
        }
        if (running) return START_NOT_STICKY
        startInForeground()
        prefs = Prefs(this)
        src = prefs.sourceLang
        tgt = prefs.targetLang
        glossary = prefs.glossary.lines().map { it.trim() }.filter { it.isNotEmpty() }
        handler = Handler(thread.looper)
        try {
            setUp(intent)
        } catch (e: Exception) {
            Log.e(TAG, "set-up failed", e)
            stopSelf()
            return START_NOT_STICKY
        }
        running = true
        handler.post(::tick)
        return START_NOT_STICKY
    }

    private fun startInForeground() {
        val nm = getSystemService(NOTIFICATION_SERVICE) as NotificationManager
        nm.createNotificationChannel(NotificationChannel(CHANNEL, "Screen translation", NotificationManager.IMPORTANCE_LOW))
        val stop = PendingIntent.getService(
            this, 0, Intent(this, CaptureService::class.java).setAction(ACTION_STOP),
            PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT)
        val notification = Notification.Builder(this, CHANNEL)
            .setSmallIcon(android.R.drawable.ic_menu_search)
            .setContentTitle("Screen Translator is running")
            .setContentText("Tap Stop to turn translation off")
            .addAction(Notification.Action.Builder(null, "Stop", stop).build())
            .setOngoing(true)
            .build()
        if (Build.VERSION.SDK_INT >= 29) {
            startForeground(1, notification, ServiceInfo.FOREGROUND_SERVICE_TYPE_MEDIA_PROJECTION)
        } else {
            startForeground(1, notification)
        }
    }

    private fun setUp(intent: Intent) {
        val dm = DisplayMetrics()
        val wm = getSystemService(WINDOW_SERVICE) as WindowManager
        @Suppress("DEPRECATION") wm.defaultDisplay.getRealMetrics(dm)
        width = dm.widthPixels
        height = dm.heightPixels

        val mpm = getSystemService(Context.MEDIA_PROJECTION_SERVICE) as MediaProjectionManager
        @Suppress("DEPRECATION") val data = intent.getParcelableExtra<Intent>(EXTRA_DATA)!!
        val mp = mpm.getMediaProjection(intent.getIntExtra(EXTRA_CODE, 0), data)
        mp.registerCallback(object : MediaProjection.Callback() {
            override fun onStop() {
                stopSelf()
            }
        }, handler)
        projection = mp
        val ir = ImageReader.newInstance(width, height, PixelFormat.RGBA_8888, 2)
        reader = ir
        display = mp.createVirtualDisplay("screen-translator", width, height, dm.densityDpi,
            DisplayManager.VIRTUAL_DISPLAY_FLAG_AUTO_MIRROR, ir.surface, null, handler)

        recognizer = when (src.script) {
            Script.LATIN -> TextRecognition.getClient(TextRecognizerOptions.DEFAULT_OPTIONS)
            Script.CHINESE -> TextRecognition.getClient(ChineseTextRecognizerOptions.Builder().build())
            Script.JAPANESE -> TextRecognition.getClient(JapaneseTextRecognizerOptions.Builder().build())
            Script.KOREAN -> TextRecognition.getClient(KoreanTextRecognizerOptions.Builder().build())
        }
        translator = Translation.getClient(
            TranslatorOptions.Builder().setSourceLanguage(src.code).setTargetLanguage(tgt.code).build())
        if (tgt.traditional) {
            hansHant = try { android.icu.text.Transliterator.getInstance("Hans-Hant") } catch (e: Exception) { null }
        }

        val view = OverlayView(this)
        overlay = view
        val lp = WindowManager.LayoutParams(
            WindowManager.LayoutParams.MATCH_PARENT, WindowManager.LayoutParams.MATCH_PARENT,
            WindowManager.LayoutParams.TYPE_APPLICATION_OVERLAY,
            WindowManager.LayoutParams.FLAG_NOT_FOCUSABLE or WindowManager.LayoutParams.FLAG_NOT_TOUCHABLE or
                WindowManager.LayoutParams.FLAG_LAYOUT_IN_SCREEN or WindowManager.LayoutParams.FLAG_LAYOUT_NO_LIMITS,
            PixelFormat.TRANSLUCENT)
        if (Build.VERSION.SDK_INT >= 28) {
            lp.layoutInDisplayCutoutMode = WindowManager.LayoutParams.LAYOUT_IN_DISPLAY_CUTOUT_MODE_ALWAYS
        }
        main.post { wm.addView(view, lp) }
    }

    private fun tick() {
        if (!running) return
        var delay = prefs.intervalMs.toLong().coerceAtLeast(100)
        try {
            val unconfirmed = scan()
            if (unconfirmed) delay = minOf(delay, 400)  // look again soon to confirm new text
        } catch (e: Exception) {
            Log.w(TAG, "scan failed", e)
        }
        handler.postDelayed(::tick, delay)
    }

    /** One pass over the screen. Returns true if some text has been seen only once so far. */
    private fun scan(): Boolean {
        val image = reader?.acquireLatestImage() ?: return false
        val bitmap: Bitmap
        try {
            val plane = image.planes[0]
            val rowPadding = plane.rowStride - plane.pixelStride * width
            val padded = Bitmap.createBitmap(width + rowPadding / plane.pixelStride, height, Bitmap.Config.ARGB_8888)
            padded.copyPixelsFromBuffer(plane.buffer)
            bitmap = if (padded.width == width) padded else Bitmap.createBitmap(padded, 0, 0, width, height).also { padded.recycle() }
        } finally {
            image.close()
        }
        try {
            val diff = frameDiff(bitmap)
            staticScreen = diff != null && diff < 2.0
            val unconfirmed = tracks.any { it.seen < 2 }
            if (diff != null && diff <= 0.6 && !unconfirmed) return false
            return process(bitmap)
        } finally {
            bitmap.recycle()
        }
    }

    /** Mean brightness change of a sparse sample of pixels versus the previous scan (null on the first). */
    private fun frameDiff(bitmap: Bitmap): Double? {
        val stepX = 16
        val stepY = 16
        val cols = width / stepX
        val rows = height / stepY
        val sample = IntArray(cols * rows)
        for (r in 0 until rows) for (c in 0 until cols) {
            val p = bitmap.getPixel(c * stepX, r * stepY)
            sample[r * cols + c] = ((p shr 16 and 0xFF) + (p shr 8 and 0xFF) + (p and 0xFF)) / 3
        }
        val old = previous
        previous = sample
        if (old == null || old.size != sample.size) return null
        var sum = 0L
        for (i in sample.indices) sum += Math.abs(sample[i] - old[i])
        return sum.toDouble() / sample.size
    }

    private fun process(bitmap: Bitmap): Boolean {
        val result = Tasks.await(recognizer!!.process(InputImage.fromBitmap(bitmap, 0)), 15, TimeUnit.SECONDS)
        val joiner = if (src.script == Script.LATIN) " " else ""
        val blocks = result.textBlocks.mapNotNull { b ->
            val box = b.boundingBox ?: return@mapNotNull null
            val text = b.lines.joinToString(joiner) { it.text }.trim()
            Block(RectF(box), text, box.height().toFloat() / maxOf(1, b.lines.size))
        }.filter { TextRules.looksLikeSource(it.text, src, prefs.skipNames) && !isOwnOutput(it.text) }
            .sortedWith(compareBy({ it.rect.top }, { it.rect.left }))

        // Follow each block from scan to scan: matches keep their translation and position,
        // new blocks are shown only once seen twice, shown blocks survive one missed scan.
        val used = HashSet<Track>()
        val fresh = ArrayList<Track>()
        for (b in blocks) {
            val t = tracks.filter { it !in used }.firstOrNull { iou(it.rect, b.rect) > 0.5f && similar(it.text, b.text) }
            if (t != null) {
                used += t
                t.seen++
                t.missed = 0
                if (!samePlace(t.rect, b.rect)) {
                    t.rect = b.rect
                    t.lineHeight = b.lineHeight
                }
                fresh += t
            } else {
                fresh += Track(b.rect, b.lineHeight, b.text)
            }
        }
        val carried = tracks.filter { it !in used }.onEach { it.missed++ }
            .filter { staticScreen && it.seen >= 2 && it.missed <= 1 }
        tracks = fresh + carried

        for (t in tracks) cache[t.text]?.let { t.translation = it.ifEmpty { null }; t.done = true }
        publish()
        val todo = tracks.filter { !it.done }.take(MAX_NEW_PER_SCAN)
        for ((i, t) in todo.withIndex()) {
            t.translation = translate(t.text)
            t.done = true
            if ((i + 1) % BATCH == 0) publish()
        }
        publish()
        return tracks.any { it.seen < 2 }
    }

    private fun publish() {
        val visible = tracks.filter { it.seen >= 2 && it.done && it.translation != null }
        shown = visible.map { TextRules.normalize(it.translation!!) }
        overlay?.boxes = visible.map { OverlayView.Box(it.rect, it.translation!!, it.lineHeight) }
    }

    private fun translate(text: String): String? {
        cache[text]?.let { return it.ifEmpty { null } }
        val (protectedText, originals) = TextRules.protect(text, glossary, src.script == Script.LATIN)
        if (TextRules.onlyPlaceholders(protectedText)) {
            cache[text] = ""
            return null
        }
        val out = try {
            Tasks.await(translator!!.translate(protectedText), 20, TimeUnit.SECONDS)
        } catch (e: Exception) {
            Log.w(TAG, "translate failed: ${e.message}")
            return null  // e.g. the language data is not downloaded yet: don't cache
        }
        var result = TextRules.restore(out, originals)
        if (tgt.traditional) result = hansHant?.transliterate(result) ?: result
        val wantsCjk = tgt.code == "zh" || tgt.code == "ja" || tgt.code == "ko"
        if (result.isEmpty() || result.equals(text, ignoreCase = true) ||
            (wantsCjk && result.none { TextRules.isCjk(it) })) result = ""
        cache[text] = result
        return result.ifEmpty { null }
    }

    /** True if OCR picked up one of our own translations (it must not be translated again). */
    private fun isOwnOutput(text: String): Boolean {
        val norm = TextRules.normalize(text)
        if (norm.length < 4) return false
        return shown.any { it.contains(norm) || norm.contains(it) || similar(it, norm) }
    }

    private fun iou(a: RectF, b: RectF): Float {
        val ix = maxOf(0f, minOf(a.right, b.right) - maxOf(a.left, b.left))
        val iy = maxOf(0f, minOf(a.bottom, b.bottom) - maxOf(a.top, b.top))
        val inter = ix * iy
        val union = a.width() * a.height() + b.width() * b.height() - inter
        return if (union > 0) inter / union else 0f
    }

    private fun samePlace(a: RectF, b: RectF) =
        Math.abs(a.left - b.left) <= 8 && Math.abs(a.top - b.top) <= 8 &&
            Math.abs(a.width() - b.width()) <= 12 && Math.abs(a.height() - b.height()) <= 12

    /** Nearly the same text (OCR reads the same words slightly differently on every scan). */
    private fun similar(a: String, b: String, threshold: Double = 0.8): Boolean {
        if (a == b) return true
        val longest = maxOf(a.length, b.length)
        if (longest == 0 || longest > 400 || Math.abs(a.length - b.length) > longest * (1 - threshold)) return false
        var prev = IntArray(b.length + 1) { it }
        for (i in 1..a.length) {
            val cur = IntArray(b.length + 1)
            cur[0] = i
            for (j in 1..b.length) {
                cur[j] = minOf(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + if (a[i - 1] == b[j - 1]) 0 else 1)
            }
            prev = cur
        }
        return 1 - prev[b.length].toDouble() / longest >= threshold
    }

    override fun onDestroy() {
        running = false
        if (::handler.isInitialized) handler.removeCallbacksAndMessages(null)
        val view = overlay
        if (view != null) {
            main.post { (getSystemService(WINDOW_SERVICE) as WindowManager).removeView(view) }
        }
        display?.release()
        reader?.close()
        projection?.stop()
        recognizer?.close()
        translator?.close()
        thread.quitSafely()
        super.onDestroy()
    }
}
