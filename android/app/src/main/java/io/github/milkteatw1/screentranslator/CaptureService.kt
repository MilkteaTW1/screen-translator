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
import android.os.SystemClock
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
import java.util.concurrent.Executors
import java.util.concurrent.TimeUnit

/** Reads the text on the screen and/or the speech being played, translates it and keeps the overlay up to date. */
class CaptureService : Service() {
    companion object {
        @Volatile var running = false
        @Volatile var screenOn = false  // translating the text on the screen
        @Volatile var speechOn = false  // translating what is heard
        @Volatile var hasProjection = false  // screen capture was granted (needed for screen text and phone audio)
        const val ACTION_STOP = "stop"
        const val ACTION_FEATURES = "features"  // switch screen / speech on or off while running
        const val EXTRA_SCREEN = "screen"
        const val EXTRA_SPEECH = "speech"
        const val EXTRA_CODE = "code"
        const val EXTRA_DATA = "data"
        const val EXTRA_TEST_WAV = "testWav"  // feed a WAV file to the speech engine instead of live audio (testing)
        private const val CHANNEL = "capture"
        private const val TAG = "ScreenTranslator"
        private const val MAX_NEW_PER_SCAN = 80
        private const val TRANSLATE_THREADS = 6
        private const val BATCH = 8  // blocks per translation request
        private const val MAX_REREADS = 4
        private const val MAX_CAPTIONS = 4
        private const val COVER_SETTLE_MS = 400L
        private const val JUMP = 8.0  // a sudden change of this size (app switch, scroll start) means everything shown is out of date
        private const val COVER_CHANGE = 2.5  // mean brightness change under a cover that means the text there changed
    }

    /** A text block followed from scan to scan, so what is on screen stays steady. */
    private class Track(var rect: RectF, var lineHeight: Float, val text: String) {
        @Volatile var translation: String? = null
        @Volatile var done = false
        @Volatile var queued = false
        @Volatile var mode = -1  // where the translation goes; decided once, so it never hops around
        var seen = 1
        var missed = 0
        /** What the screen looked like under our own cover once it was drawn; while it stays the same the text is unchanged. */
        var sig: IntArray? = null
        var stale = false  // the screen under the cover changed: read it again
        var shownAt = 0L  // when it became visible (the captured frame lags the overlay by a moment)
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
    private var pool = Executors.newFixedThreadPool(TRANSLATE_THREADS)
    private var speech: SpeechEngine? = null
    private val captions = ArrayList<Pair<String, String>>()
    private var width = 0
    private var height = 0
    @Volatile private var tracks = listOf<Track>()
    private var previous: IntArray? = null
    private var staticScreen = false
    private var lastScreenDiff = 0.0
    private var forceScan = false  // read the next frame even if the screen looks unchanged
    private var glossary = listOf<String>()
    private val cache = java.util.concurrent.ConcurrentHashMap<String, String>()
    @Volatile private var shown = listOf<String>()
    private var luma = IntArray(0)
    private var lumaCols = 0
    private var chip: android.widget.TextView? = null
    private var hansHant: android.icu.text.Transliterator? = null
    private val metrics = DisplayMetrics()
    private var frame: Bitmap? = null  // the latest screen picture (reused), read again while nothing new arrives
    private var rereads = 0  // times the same picture was read again to confirm text
    private val rowBuffer = IntArray(4096)

    override fun attachBaseContext(base: Context) = super.attachBaseContext(Ui.localized(base))

    override fun onBind(intent: Intent?): IBinder? = null

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        if (intent == null || intent.action == ACTION_STOP) {
            stopSelf()
            return START_NOT_STICKY
        }
        if (running) {
            if (intent.action == ACTION_FEATURES) {
                val screen = intent.getBooleanExtra(EXTRA_SCREEN, screenOn)
                val speech = intent.getBooleanExtra(EXTRA_SPEECH, speechOn)
                handler.post { setFeatures(screen, speech) }
            }
            return START_NOT_STICKY
        }
        prefs = Prefs(this)
        src = prefs.sourceLang
        tgt = prefs.targetLang
        glossary = prefs.glossary.lines().map { it.trim() }.filter { it.isNotEmpty() }
        val hasProjection = intent.hasExtra(EXTRA_DATA)
        startInForeground(hasProjection, prefs.speech && prefs.speechMic)
        handler = Handler(thread.looper)
        try {
            setUp(intent, hasProjection)
        } catch (e: Exception) {
            Log.e(TAG, "set-up failed", e)
            stopSelf()
            return START_NOT_STICKY
        }
        running = true
        Companion.hasProjection = projection != null
        screenOn = prefs.screenText && projection != null
        speechOn = prefs.speech
        if (screenOn) handler.post(::tick)
        return START_NOT_STICKY
    }

    /** Turns screen translation and speech translation on or off on their own; stops when both are off. */
    private fun setFeatures(screen: Boolean, speech: Boolean) {
        prefs = Prefs(this)  // the settings may have changed since the start
        if (screen && !screenOn && projection != null) {
            if (reader == null) setUpScreen(metrics)
            val wm = getSystemService(WINDOW_SERVICE) as WindowManager
            main.post { if (chip == null) overlay?.let { addChip(wm, it) } }
            screenOn = true
            forceScan = true
            handler.post(::tick)
        } else if (!screen && screenOn) {
            screenOn = false
            tracks = emptyList()
            publish()
        }
        if (speech && !speechOn) {
            if (prefs.speechMic) startInForeground(projection != null, true)
            setUpSpeech(Intent())
            speechOn = true
        } else if (!speech && speechOn) {
            this.speech?.stop()
            this.speech = null
            synchronized(captions) { captions.clear() }
            overlay?.captions = emptyList()
            overlay?.partial = "" to ""
            speechOn = false
        }
        if (!screenOn && !speechOn) stopSelf()
    }

    private fun startInForeground(projection: Boolean, microphone: Boolean) {
        val nm = getSystemService(NOTIFICATION_SERVICE) as NotificationManager
        nm.createNotificationChannel(NotificationChannel(CHANNEL, getString(R.string.channel_name), NotificationManager.IMPORTANCE_LOW))
        val stop = PendingIntent.getService(
            this, 0, Intent(this, CaptureService::class.java).setAction(ACTION_STOP),
            PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT)
        val notification = Notification.Builder(this, CHANNEL)
            .setSmallIcon(android.R.drawable.ic_menu_search)
            .setContentTitle(getString(R.string.notification_title))
            .setContentText(getString(R.string.notification_text))
            .addAction(Notification.Action.Builder(null, getString(R.string.stop), stop).build())
            .setOngoing(true)
            .build()
        if (Build.VERSION.SDK_INT >= 29) {
            var type = 0
            if (projection) type = type or ServiceInfo.FOREGROUND_SERVICE_TYPE_MEDIA_PROJECTION
            if (microphone) type = type or ServiceInfo.FOREGROUND_SERVICE_TYPE_MICROPHONE
            startForeground(1, notification, type)
        } else {
            startForeground(1, notification)
        }
    }

    private fun setUp(intent: Intent, hasProjection: Boolean) {
        val dm = metrics
        val wm = getSystemService(WINDOW_SERVICE) as WindowManager
        @Suppress("DEPRECATION") wm.defaultDisplay.getRealMetrics(dm)
        width = dm.widthPixels
        height = dm.heightPixels

        if (hasProjection) {
            val mpm = getSystemService(Context.MEDIA_PROJECTION_SERVICE) as MediaProjectionManager
            @Suppress("DEPRECATION") val data = intent.getParcelableExtra<Intent>(EXTRA_DATA)!!
            val mp = mpm.getMediaProjection(intent.getIntExtra(EXTRA_CODE, 0), data)
            mp.registerCallback(object : MediaProjection.Callback() {
                override fun onStop() {
                    stopSelf()
                }
            }, handler)
            projection = mp
        }
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
        if (Build.VERSION.SDK_INT >= 31) {
            // Android 12+ blocks touches that pass through another app's window unless that window is at most this
            // opaque (0.8): at full opacity the page under the translations could not be scrolled or tapped.
            lp.alpha = (getSystemService(Context.INPUT_SERVICE) as android.hardware.input.InputManager)
                .maximumObscuringOpacityForTouch
        }
        main.post {
            wm.addView(view, lp)
            if (prefs.screenText) addChip(wm, view)
        }

        if (prefs.screenText) setUpScreen(dm)
        if (prefs.speech) setUpSpeech(intent)
    }

    /** A small button, shown only while a translation covers text: one tap hides or shows those covers. */
    private fun addChip(wm: WindowManager, view: OverlayView) {
        val d = resources.displayMetrics.density
        val button = android.widget.TextView(this).apply {
            text = "譯"
            textSize = 16f
            gravity = android.view.Gravity.CENTER
            setTextColor(android.graphics.Color.WHITE)
            background = android.graphics.drawable.GradientDrawable().apply {
                shape = android.graphics.drawable.GradientDrawable.OVAL
                setColor(android.graphics.Color.argb(200, 30, 90, 200))
            }
            visibility = android.view.View.GONE
            setOnClickListener {
                view.hideCovers = !view.hideCovers
                alpha = if (view.hideCovers) 0.5f else 1f
            }
        }
        val lp = WindowManager.LayoutParams((44 * d).toInt(), (44 * d).toInt(),
            WindowManager.LayoutParams.TYPE_APPLICATION_OVERLAY,
            WindowManager.LayoutParams.FLAG_NOT_FOCUSABLE or WindowManager.LayoutParams.FLAG_LAYOUT_NO_LIMITS,
            PixelFormat.TRANSLUCENT)
        lp.gravity = android.view.Gravity.TOP or android.view.Gravity.START
        lp.x = if (prefs.chipX >= 0) prefs.chipX else width - (52 * d).toInt()
        lp.y = if (prefs.chipY >= 0) prefs.chipY else height / 2
        // Drag it anywhere; a short touch that hardly moves is a tap.
        var downX = 0f
        var downY = 0f
        var startX = 0
        var startY = 0
        var dragging = false
        button.setOnTouchListener { v, e ->
            when (e.actionMasked) {
                android.view.MotionEvent.ACTION_DOWN -> {
                    downX = e.rawX; downY = e.rawY; startX = lp.x; startY = lp.y; dragging = false
                }
                android.view.MotionEvent.ACTION_MOVE -> {
                    val dx = e.rawX - downX
                    val dy = e.rawY - downY
                    if (dragging || dx * dx + dy * dy > 12 * d * 12 * d) {
                        dragging = true
                        lp.x = (startX + dx).toInt().coerceIn(0, width - v.width)
                        lp.y = (startY + dy).toInt().coerceIn(0, height - v.height)
                        wm.updateViewLayout(v, lp)
                    }
                }
                android.view.MotionEvent.ACTION_UP -> {
                    if (dragging) { prefs.chipX = lp.x; prefs.chipY = lp.y } else v.performClick()
                }
            }
            true
        }
        chip = button
        wm.addView(button, lp)
    }

    private fun setUpScreen(dm: DisplayMetrics) {
        val mp = projection ?: throw IllegalStateException("screen capture was not granted")
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
    }

    private fun setUpSpeech(intent: Intent) {
        val engine = SpeechEngine(
            this, prefs.speechLanguage, tgt, glossary, prefs.useGoogle,
            onPartial = { said, translation -> overlay?.partial = said to translation },
            onLine = { said, translated ->
                synchronized(captions) {
                    captions.add(said to translated)
                    while (captions.size > MAX_CAPTIONS) captions.removeAt(0)
                    overlay?.captions = captions.toList()
                }
            },
            onStatus = { Log.i(TAG, it) },
        )
        speech = engine
        val kind = if (prefs.speechMic) AudioKind.MICROPHONE else AudioKind.SYSTEM
        engine.start(kind, projection, intent.getStringExtra(EXTRA_TEST_WAV))
    }

    private fun tick() {
        if (!running || !screenOn) return
        var delay = prefs.intervalMs.toLong().coerceAtLeast(100)
        try {
            val unconfirmed = scan()
            if (unconfirmed) delay = minOf(delay, 300)  // look again soon to confirm new text
        } catch (e: Exception) {
            Log.w(TAG, "scan failed", e)
        }
        handler.postDelayed(::tick, delay)
    }

    /** One pass over the screen. Returns true if some text has been seen only once so far. */
    private fun scan(): Boolean {
        val image = reader?.acquireLatestImage()
        val bitmap: Bitmap
        if (image == null) {
            // Android sends no new frame while nothing on the screen moves. Text seen only once must be read again
            // anyway, or a still page is never fully shown: read the last frame again (a few times at most; what is
            // still unconfirmed after that is OCR noise, not text).
            bitmap = frame ?: return false
            if (!forceScan && tracks.none { it.seen < 2 }) return false  // translations still on their way need no new read
            if (!forceScan && ++rereads > MAX_REREADS) return false
        } else {
            try {
                // One picture, reused for every frame: a new full-screen bitmap each time (about 10 MB) kept the
                // garbage collector busy. The row padding stays on the right, outside the screen, and is never read.
                val plane = image.planes[0]
                val stride = plane.rowStride / plane.pixelStride
                var f = frame
                if (f == null || f.width != stride || f.height != height) {
                    f?.recycle()
                    f = Bitmap.createBitmap(stride, height, Bitmap.Config.ARGB_8888)
                    frame = f
                }
                plane.buffer.rewind()
                f!!.copyPixelsFromBuffer(plane.buffer)
                bitmap = f
            } finally {
                image.close()
            }
            rereads = 0
        }
        run {
            val both = frameDiff(bitmap)
            val screenDiff = both?.second  // without our own overlay
            staticScreen = screenDiff != null && screenDiff < 2.0
            val jumped = screenDiff != null && screenDiff > JUMP && lastScreenDiff < 3.0
            if (screenDiff != null) lastScreenDiff = screenDiff
            if (jumped && tracks.isNotEmpty()) {
                // Our old translations are still on screen and would be read together with the new text.
                // Take them all down and read the next frame clean. (Not on every large change: a video keeps changing.)
                tracks = emptyList()
                forceScan = true
                publish()
                return true
            }
            val unconfirmed = tracks.any { it.seen < 2 }
            val pending = tracks.any { !it.done }
            val released = watchCovers(bitmap, screenDiff)
            if (released) {  // a cover no longer matches its text: take it down, and read the next frame without it
                forceScan = true
                publish()
                return true
            }
            if (screenDiff != null && screenDiff <= 0.6 && !unconfirmed && !pending && !forceScan) return false
            forceScan = false
            sampleLuma(bitmap)
            return process(bitmap)
        }
    }

    /** The area a cover occupies: the text block, a little wider and taller when the translation needs the room. */
    private fun coverRect(t: Track): RectF {
        val w = t.rect.width() * 1.6f
        return RectF(maxOf(0f, t.rect.centerX() - w / 2), t.rect.top,
            minOf(width.toFloat(), t.rect.centerX() + w / 2), minOf(height.toFloat(), t.rect.top + t.rect.height() * 1.4f))
    }

    private fun signature(bitmap: Bitmap, r: RectF): IntArray {
        val step = 8
        val x0 = r.left.toInt().coerceIn(0, width - 1); val x1 = r.right.toInt().coerceIn(x0 + 1, width)
        val y0 = r.top.toInt().coerceIn(0, height - 1); val y1 = r.bottom.toInt().coerceIn(y0 + 1, height)
        val out = ArrayList<Int>()
        var y = y0
        while (y < y1) {
            var x = x0
            while (x < x1) {
                val p = bitmap.getPixel(x, y)
                out.add(((p shr 16 and 0xFF) + (p shr 8 and 0xFF) + (p and 0xFF)) / 3)
                x += step
            }
            y += step
        }
        return out.toIntArray()
    }

    /** Our own covers are part of the captured screen, so OCR reads scraps of the original around them and the text
     *  looks new on every scan. While the screen under a cover is unchanged we keep its track and ignore those
     *  scraps; once it changes the track is released and read afresh. Returns true if some cover was released. */
    private fun watchCovers(bitmap: Bitmap, frameDiff: Double?): Boolean {
        var released = false
        for (t in tracks) {
            if (t.mode != OverlayView.COVER || !t.done || t.translation == null || t.seen < 2 || t.stale) continue
            val inner = RectF(t.rect).apply { inset(width() * 0.1f, height() * 0.15f) }
            val now = signature(bitmap, inner)
            val was = t.sig
            if (was == null) {
                if (t.shownAt == 0L || SystemClock.uptimeMillis() - t.shownAt < COVER_SETTLE_MS) continue  // is it in the captured frame yet?
                // First look since the cover was drawn. If the whole screen moved on in the meantime, what is
                // under the cover is no longer what was translated.
                if (frameDiff != null && frameDiff > 2.0) { t.stale = true; released = true } else t.sig = now
            } else if (was.size != now.size || was.indices.sumOf { Math.abs(was[it] - now[it]) }.toDouble() / was.size > COVER_CHANGE) {
                t.sig = null
                t.stale = true
                released = true
            }
        }
        return released
    }

    /** One row of the screen picture (its first [width] pixels), in a buffer that is reused. */
    private fun row(bitmap: Bitmap, y: Int): IntArray {
        bitmap.getPixels(rowBuffer, 0, width, 0, y, width, 1)
        return rowBuffer
    }

    /** A coarse brightness map of the screen, used to find empty space (of any colour) for translations. */
    private fun sampleLuma(bitmap: Bitmap) {
        val step = 4
        val cols = width / step
        val rows = height / step
        val out = IntArray(cols * rows)
        for (r in 0 until rows) {
            val row = row(bitmap, r * step)
            for (c in 0 until cols) {
                val p = row[c * step]
                out[r * cols + c] = (299 * (p shr 16 and 0xFF) + 587 * (p shr 8 and 0xFF) + 114 * (p and 0xFF)) / 1000
            }
        }
        luma = out
        lumaCols = cols
    }

    /** True if [r] is on the screen and is one flat colour (nothing drawn there), whatever that colour is. */
    private fun isBlank(r: RectF): Boolean {
        if (r.left < 0 || r.top < 0 || r.right > width || r.bottom > height || lumaCols == 0) return false
        val step = 4
        val rows = luma.size / lumaCols
        val x0 = (r.left / step).toInt(); val x1 = minOf(lumaCols - 1, (r.right / step).toInt())
        val y0 = (r.top / step).toInt(); val y1 = minOf(rows - 1, (r.bottom / step).toInt())
        var sum = 0L; var n = 0
        for (y in y0..y1) for (x in x0..x1) { sum += luma[y * lumaCols + x]; n++ }
        if (n < 4) return false
        val mean = sum / n
        var off = 0
        for (y in y0..y1) for (x in x0..x1) if (Math.abs(luma[y * lumaCols + x] - mean) > 14) off++
        return off <= n * 0.03
    }

    /** Empty space next to the text if there is some (above first, then below), otherwise lay the translation over the text. */
    private fun place(t: Track, all: List<Track>): Int {
        val view = overlay ?: return OverlayView.ABOVE
        val (w, h) = view.measure(OverlayView.Box(t.rect, t.translation ?: "", t.lineHeight))
        val left = (t.rect.centerX() - w / 2).coerceIn(0f, maxOf(0f, width - w))
        val above = RectF(left, t.rect.top - h - 2, left + w, t.rect.top - 2)
        val below = RectF(left, t.rect.bottom + 2, left + w, t.rect.bottom + 2 + h)
        fun free(r: RectF) = isBlank(r) && all.none { o -> o !== t && (RectF.intersects(o.rect, r) ||
            (o.mode != OverlayView.COVER && o.mode >= 0 && RectF.intersects(sideRect(o), r))) }
        return when {
            free(above) -> OverlayView.ABOVE
            free(below) -> OverlayView.BELOW
            else -> OverlayView.COVER
        }
    }

    private fun sideRect(t: Track): RectF {
        val view = overlay ?: return t.rect
        val (w, h) = view.measure(OverlayView.Box(t.rect, t.translation ?: "", t.lineHeight))
        val left = (t.rect.centerX() - w / 2).coerceIn(0f, maxOf(0f, width - w))
        return if (t.mode == OverlayView.BELOW) RectF(left, t.rect.bottom + 2, left + w, t.rect.bottom + 2 + h)
        else RectF(left, t.rect.top - h - 2, left + w, t.rect.top - 2)
    }

    /** Mean brightness change of a sparse sample of pixels versus the previous scan (null on the first).
     *  Second value: the same without the places our own overlay occupies, i.e. how much the screen itself changed. */
    private fun frameDiff(bitmap: Bitmap): Pair<Double, Double>? {
        val stepX = 16
        val stepY = 16
        val cols = width / stepX
        val rows = height / stepY
        val sample = IntArray(cols * rows)
        for (r in 0 until rows) {
            val row = row(bitmap, r * stepY)
            for (c in 0 until cols) {
                val p = row[c * stepX]
                sample[r * cols + c] = ((p shr 16 and 0xFF) + (p shr 8 and 0xFF) + (p and 0xFF)) / 3
            }
        }
        val old = previous
        previous = sample
        if (old == null || old.size != sample.size) return null
        val own = tracks.filter { it.seen >= 2 && it.done && it.translation != null }
            .map { if (it.mode == OverlayView.COVER) coverRect(it) else sideRect(it) }
        var sum = 0L
        var outside = 0L
        var outsideCount = 0
        for (r in 0 until rows) for (c in 0 until cols) {
            val i = r * cols + c
            val d = Math.abs(sample[i] - old[i])
            sum += d
            val x = (c * stepX).toFloat()
            val y = (r * stepY).toFloat()
            if (own.none { it.contains(x, y) }) { outside += d; outsideCount++ }
        }
        return sum.toDouble() / sample.size to (if (outsideCount > 0) outside.toDouble() / outsideCount else 0.0)
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
        val old = tracks
        val used = HashSet<Track>()
        val fresh = ArrayList<Track>()
        val held = old.filter { it.mode == OverlayView.COVER && it.sig != null && !it.stale }  // text under our own cover, unchanged
        val heldRects = held.map { it to coverRect(it) }
        for (b in blocks) {
            val t = old.filter { it !in used }.firstOrNull { sameBlock(it, b) }
            if (t == null && heldRects.any { (_, r) -> r.contains(b.rect.centerX(), b.rect.centerY()) }) continue  // scraps around our own cover
            if (t != null) {
                used += t
                t.seen++
                t.missed = 0
                if (t.stale) { t.stale = false; t.shownAt = 0L }
                if (!samePlace(t.rect, b.rect, maxOf(t.lineHeight, b.lineHeight))) {
                    t.rect = b.rect
                    t.lineHeight = b.lineHeight
                }
                fresh += t
            } else {
                fresh += Track(b.rect, b.lineHeight, b.text)
            }
        }
        val carried = old.filter { it !in used }.onEach { it.missed++ }
            .filter { it in held || (staticScreen && it.seen >= 2 && it.missed <= 1) }
        tracks = fresh + carried
        Log.d(TAG, "scan blocks=${blocks.size} tracks=${tracks.size} unconfirmed=${tracks.count { it.seen < 2 }}")

        for (t in tracks) cache[t.text]?.let {
            t.translation = it.ifEmpty { null }
            t.done = true
            if (it.isNotEmpty()) t.seen = maxOf(t.seen, 2)  // read and translated before (it just moved): no need to confirm it
        }
        publish()
        // Translate in the background, top to bottom, so scanning never waits for the translator and
        // each result appears as soon as it is ready.
        for (group in tracks.filter { !it.done && !it.queued }.take(MAX_NEW_PER_SCAN).chunked(BATCH)) {
            group.forEach { it.queued = true }
            pool.execute {
                val live = group.filter { running && it in tracks }
                group.filter { it !in live }.forEach { it.queued = false }  // the screen moved on: queue again if it comes back
                if (live.isNotEmpty()) {
                    translateMany(live.map { it.text }).forEachIndexed { i, out ->
                        live[i].translation = out
                        live[i].done = true
                    }
                    publish()
                }
            }
        }
        return tracks.any { it.seen < 2 }
    }

    @Synchronized
    private fun publish() {
        val visible = tracks.filter { it.seen >= 2 && it.done && it.translation != null && !it.stale }
        // Top to bottom, not in the order the translations happened to finish: the same screen always gets the same layout.
        for (t in visible) if (t.shownAt == 0L) t.shownAt = SystemClock.uptimeMillis()
        for (t in visible.filter { it.mode < 0 }.sortedWith(compareBy({ it.rect.top }, { it.rect.left }))) t.mode = place(t, tracks)
        val covering = visible.any { it.mode == OverlayView.COVER }
        main.post { chip?.visibility = if (covering) android.view.View.VISIBLE else android.view.View.GONE }
        Log.d(TAG, "publish tracks=${tracks.size} visible=${visible.size} " +
            "above=${visible.count { it.mode == OverlayView.ABOVE }} below=${visible.count { it.mode == OverlayView.BELOW }} " +
            "cover=${visible.count { it.mode == OverlayView.COVER }}")
        shown = visible.map { TextRules.normalize(it.translation!!) }
        overlay?.boxes = visible.map { OverlayView.Box(it.rect, it.translation!!, it.lineHeight, it.mode) }
    }

    /** Translations of several blocks: Google takes them in one request; whatever it can't do goes offline one by one. */
    private fun translateMany(texts: List<String>): List<String?> {
        val todo = texts.filter { cache[it] == null }
        if (prefs.useGoogle && todo.size > 1) {
            val prepared = todo.map { it to TextRules.protect(it, glossary, src.script == Script.LATIN) }
                .filter { (_, p) -> !TextRules.onlyPlaceholders(p.first) }
            GoogleTranslate.translateMany(prepared.map { it.second.first }, tgt).forEachIndexed { i, out ->
                if (out != null) finish(prepared[i].first, out, prepared[i].second.second)
            }
        }
        return texts.map { translate(it) }  // cached by now, or done on its own
    }

    private fun translate(text: String): String? {
        cache[text]?.let { return it.ifEmpty { null } }
        val (protectedText, originals) = TextRules.protect(text, glossary, src.script == Script.LATIN)
        if (TextRules.onlyPlaceholders(protectedText)) {
            cache[text] = ""
            return null
        }
        val out = (if (prefs.useGoogle) GoogleTranslate.translate(protectedText, tgt) else null) ?: try {
            Tasks.await(translator!!.translate(protectedText), 20, TimeUnit.SECONDS)
        } catch (e: Exception) {
            Log.w(TAG, "translate failed: ${e.message}")
            return null  // e.g. the language data is not downloaded yet: don't cache
        }
        return finish(text, out, originals)
    }

    /** Puts the protected names back, checks the result and caches it. */
    private fun finish(text: String, out: String, originals: List<String>): String? {
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

    /** The block seen now is the earlier one: nearly the same text, and in (nearly) the same place. */
    private fun sameBlock(t: Track, b: Block): Boolean {
        val lh = maxOf(t.lineHeight, b.lineHeight)
        val near = iou(t.rect, b.rect) > 0.3f ||
            (Math.abs(t.rect.centerX() - b.rect.centerX()) <= 2 * lh && Math.abs(t.rect.centerY() - b.rect.centerY()) <= 1.5f * lh)
        return near && similar(t.text, b.text)
    }

    /** OCR boxes wobble by a few pixels from scan to scan, more on a dense phone screen: only a move of
     *  about half a text line counts, so a translation does not shiver while the screen is still. */
    private fun samePlace(a: RectF, b: RectF, lineHeight: Float): Boolean {
        val tol = maxOf(8f, 0.5f * lineHeight)
        return Math.abs(a.left - b.left) <= tol && Math.abs(a.top - b.top) <= tol &&
            Math.abs(a.width() - b.width()) <= 1.5f * tol && Math.abs(a.height() - b.height()) <= 1.5f * tol
    }

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
        screenOn = false
        speechOn = false
        hasProjection = false
        speech?.stop()
        pool.shutdownNow()
        if (::handler.isInitialized) handler.removeCallbacksAndMessages(null)
        val view = overlay
        val button = chip
        main.post {
            val wm = getSystemService(WINDOW_SERVICE) as WindowManager
            if (view != null) wm.removeView(view)
            if (button != null) wm.removeView(button)
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
