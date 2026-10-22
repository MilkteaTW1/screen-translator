package io.github.milkteatw1.screentranslator

import android.Manifest
import android.app.AlertDialog
import android.content.Context
import android.content.Intent
import android.content.pm.PackageManager
import android.media.projection.MediaProjectionManager
import android.net.Uri
import android.os.Build
import android.os.Bundle
import android.provider.Settings
import android.graphics.Color
import android.view.Gravity
import android.view.View
import android.view.ViewGroup
import android.widget.AdapterView
import android.widget.LinearLayout
import android.widget.ScrollView
import android.widget.TextView
import android.widget.Toast
import androidx.activity.ComponentActivity
import androidx.activity.result.contract.ActivityResultContracts
import com.google.mlkit.common.model.DownloadConditions
import com.google.mlkit.common.model.RemoteModelManager
import com.google.mlkit.nl.translate.TranslateRemoteModel
import io.github.milkteatw1.screentranslator.Ui.dp

/** Settings screen: pick the languages, decide how language data is downloaded, start and stop. */
class MainActivity : ComponentActivity() {
    private lateinit var prefs: Prefs
    private lateinit var screenButton: TextView
    private lateinit var speechButton: TextView
    private lateinit var status: TextView

    private val projectionLauncher = registerForActivityResult(ActivityResultContracts.StartActivityForResult()) { r ->
        val data = r.data
        if (r.resultCode == RESULT_OK && data != null) {
            val intent = Intent(this, CaptureService::class.java)
                .putExtra(CaptureService.EXTRA_CODE, r.resultCode).putExtra(CaptureService.EXTRA_DATA, data)
            startForegroundService(intent)
            status.postDelayed({ refresh() }, 600)
        } else {
            status.text = getString(R.string.capture_denied)
        }
    }
    private val notificationLauncher = registerForActivityResult(ActivityResultContracts.RequestPermission()) { askProjection() }
    private val micLauncher = registerForActivityResult(ActivityResultContracts.RequestPermission()) { ok ->
        when {
            !ok -> status.text = getString(R.string.mic_needed)
            pendingSpeechOn -> { pendingSpeechOn = false; setFeatures(CaptureService.screenOn, true) }
            else -> askNotification()
        }
    }
    private var pendingSpeechOn = false  // the microphone was asked for while the service already runs

    /** Switches screen / speech translation on or off in the running service. */
    private fun setFeatures(screen: Boolean, speech: Boolean) {
        startService(Intent(this, CaptureService::class.java).setAction(CaptureService.ACTION_FEATURES)
            .putExtra(CaptureService.EXTRA_SCREEN, screen).putExtra(CaptureService.EXTRA_SPEECH, speech))
        status.postDelayed({ refresh() }, 500)
    }

    /** Starts the service with these features (stopping it first if it runs): asks for screen capture again. */
    private fun restart(screen: Boolean, speech: Boolean) {
        prefs.screenText = screen
        prefs.speech = speech
        val go = { ensureLanguageData { ensureSpeechModel { startFlow() } } }
        if (CaptureService.running) {
            startService(Intent(this, CaptureService::class.java).setAction(CaptureService.ACTION_STOP))
            status.postDelayed({ go() }, 600)
        } else {
            go()
        }
    }

    override fun attachBaseContext(base: Context) = super.attachBaseContext(Ui.localized(base))

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        prefs = Prefs(this)
        if (Build.VERSION.SDK_INT >= 33) {  // the language may also have been changed in Android's own settings
            val tags = getSystemService(android.app.LocaleManager::class.java).applicationLocales.toLanguageTags()
            prefs.uiLanguage = when {
                tags.startsWith("zh") -> "zh-TW"
                tags.startsWith("en") -> "en"
                else -> ""
            }
        }
        window.statusBarColor = Ui.GROUND
        window.navigationBarColor = Ui.GROUND
        val ctx = this
        val pad = dp(18)

        // Header: name, one line on what it does, and the interface language.
        val header = LinearLayout(ctx).apply {
            orientation = LinearLayout.HORIZONTAL
            gravity = Gravity.CENTER_VERTICAL
            setPadding(pad, dp(22), pad, dp(10))
        }
        val titles = LinearLayout(ctx).apply { orientation = LinearLayout.VERTICAL }
        titles.addView(Ui.text(ctx, "Screen Translator", 24f, Ui.INK, bold = true))
        titles.addView(Ui.text(ctx, getString(R.string.app_subtitle), 14f, Ui.MUTED))
        header.addView(titles, LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.WRAP_CONTENT, 1f))
        val langButton = Ui.pill(ctx, "🌐 " + getString(R.string.lang_short), false)
        header.addView(langButton)

        // Settings, sorted into the same four tabs as on the desktop.
        val pages = listOf(R.string.tab_translate, R.string.tab_speech, R.string.tab_quality, R.string.tab_general)
            .map { LinearLayout(ctx).apply { orientation = LinearLayout.VERTICAL; setPadding(pad, dp(6), pad, dp(16)) } }
        val tabRow = LinearLayout(ctx).apply { orientation = LinearLayout.HORIZONTAL; setPadding(pad - dp(4), 0, pad - dp(4), dp(8)) }
        val tabs = listOf(R.string.tab_translate, R.string.tab_speech, R.string.tab_quality, R.string.tab_general).map { id ->
            Ui.pill(ctx, getString(id), false).also { tab ->
                tab.textSize = 13f
                tab.maxLines = 1
                tab.setPadding(dp(4), dp(9), dp(4), dp(9))
                tabRow.addView(tab, LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.WRAP_CONTENT, 1f)
                    .apply { marginStart = dp(4); marginEnd = dp(4) })
            }
        }
        val scroll = ScrollView(ctx)
        fun showTab(i: Int) {
            prefs.lastTab = i
            tabs.forEachIndexed { j, tab ->
                val on = i == j
                tab.background = Ui.rounded(if (on) Ui.LINE else Color.TRANSPARENT, 999f, ctx, if (on) null else Ui.LINE)
                tab.setTextColor(if (on) Ui.ACCENT else Ui.MUTED)
            }
            scroll.removeAllViews()
            scroll.addView(pages[i])
        }
        tabs.forEachIndexed { i, tab -> tab.setOnClickListener { showTab(i) } }

        // Translate: languages.
        val languages = Ui.card(ctx, getString(R.string.section_languages))
        languages.addView(Ui.label(ctx, getString(R.string.screen_language)))
        val source = Ui.spinner(ctx, Langs.sources.map { it.label }, prefs.source)
        languages.addView(source)
        languages.addView(Ui.label(ctx, getString(R.string.translate_to)))
        val target = Ui.spinner(ctx, Langs.targets.map { it.label }, prefs.target)
        languages.addView(target)
        pages[0].addView(languages)

        // Speech.
        val speechCard = Ui.card(ctx, getString(R.string.section_speech))
        speechCard.addView(Ui.label(ctx, getString(R.string.sound_source)))
        val soundSource = Ui.spinner(ctx, listOf(getString(R.string.source_phone), getString(R.string.source_mic)),
            if (prefs.speechMic) 1 else 0)
        speechCard.addView(soundSource)
        speechCard.addView(Ui.text(ctx, getString(R.string.source_note), 12f, Ui.MUTED).apply { setPadding(0, dp(8), 0, 0) })
        speechCard.addView(Ui.label(ctx, getString(R.string.spoken_language)))
        val speechLang = Ui.spinner(ctx, VoskModels.languages.map { it.label }, prefs.speechLang)
        speechCard.addView(speechLang)
        pages[1].addView(speechCard)

        // Quality: the engine, names, speed.
        val engine = Ui.card(ctx, getString(R.string.section_engine))
        val google = Ui.switch(ctx, getString(R.string.use_google), prefs.useGoogle)
        engine.addView(google)
        pages[2].addView(engine)
        val names = Ui.card(ctx, getString(R.string.section_names))
        val skip = Ui.switch(ctx, getString(R.string.skip_names), prefs.skipNames)
        names.addView(skip)
        names.addView(Ui.label(ctx, getString(R.string.glossary_label)))
        val glossary = Ui.field(ctx, prefs.glossary, lines = 3).apply { hint = "Hatsune Miku\nNVIDIA" }
        names.addView(glossary)
        pages[2].addView(names)
        val speed = Ui.card(ctx, getString(R.string.section_speed))
        speed.addView(Ui.label(ctx, getString(R.string.refresh_interval)))
        val interval = Ui.field(ctx, (prefs.intervalMs / 1000.0).toString(), number = true)
        speed.addView(interval)
        pages[2].addView(speed)

        // General: interface language, version and updates.
        val look = Ui.card(ctx, getString(R.string.ui_language))
        val uiLang = Ui.spinner(ctx, Ui.uiLanguages.map { getString(it.second) },
            Ui.uiLanguages.indexOfFirst { it.first == prefs.uiLanguage }.coerceAtLeast(0))
        look.addView(uiLang)
        pages[3].addView(look)
        val about = Ui.card(ctx, getString(R.string.section_app))
        about.addView(Ui.text(ctx, getString(R.string.version, Updater.versionOf(this)), 15f))
        about.addView(Ui.pill(ctx, getString(R.string.check_updates_short), false).apply {
            setOnClickListener { checkForUpdates(manual = true) }
            layoutParams = LinearLayout.LayoutParams(ViewGroup.LayoutParams.WRAP_CONTENT, ViewGroup.LayoutParams.WRAP_CONTENT)
                .apply { topMargin = dp(12) }
        })
        pages[3].addView(about)

        // The start button and what is happening, always in reach at the bottom.
        val bottom = LinearLayout(ctx).apply {
            orientation = LinearLayout.VERTICAL
            setPadding(pad, dp(10), pad, dp(18))
            background = Ui.rounded(Ui.CARD, 0f, ctx)
        }
        status = Ui.text(ctx, "", 14f, Ui.MUTED).apply { gravity = Gravity.CENTER; setPadding(0, 0, 0, dp(10)) }
        bottom.addView(status)
        // Screen and speech translation start and stop on their own, as on the desktop.
        val buttons = LinearLayout(ctx).apply { orientation = LinearLayout.HORIZONTAL }
        screenButton = Ui.pill(ctx, "", true).apply { textSize = 16f }
        speechButton = Ui.pill(ctx, "", true).apply { textSize = 16f }
        buttons.addView(screenButton, LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.WRAP_CONTENT, 1f).apply { marginEnd = dp(6) })
        buttons.addView(speechButton, LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.WRAP_CONTENT, 1f).apply { marginStart = dp(6) })
        bottom.addView(buttons)

        val rootView = LinearLayout(ctx).apply {
            orientation = LinearLayout.VERTICAL
            setBackgroundColor(Ui.GROUND)
            fitsSystemWindows = true
            addView(header)
            addView(tabRow)
            addView(scroll, LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, 0, 1f))
            addView(bottom)
        }
        setContentView(rootView)
        showTab(prefs.lastTab.coerceIn(0, pages.lastIndex))

        fun save() {
            prefs.source = source.selectedItemPosition
            prefs.target = target.selectedItemPosition
            prefs.intervalMs = ((interval.text.toString().toDoubleOrNull() ?: 1.0) * 1000).toInt().coerceAtLeast(100)
            prefs.skipNames = skip.isChecked
            prefs.useGoogle = google.isChecked
            prefs.glossary = glossary.text.toString()
            prefs.speechMic = soundSource.selectedItemPosition == 1
            prefs.speechLang = speechLang.selectedItemPosition
        }
        for (s in listOf(google, skip)) s.setOnCheckedChangeListener { _, _ -> save() }
        soundSource.onItemSelectedListener = object : AdapterView.OnItemSelectedListener {
            var first = 1
            override fun onItemSelected(p: AdapterView<*>?, v: View?, pos: Int, id: Long) {
                if (first > 0) { first--; return }
                save()
            }
            override fun onNothingSelected(p: AdapterView<*>?) {}
        }
        val onPick = object : AdapterView.OnItemSelectedListener {
            var first = 2  // ignore the two initial callbacks
            override fun onItemSelected(p: AdapterView<*>?, v: View?, pos: Int, id: Long) {
                if (first > 0) { first--; return }
                save()
                ensureLanguageData { status.text = getString(R.string.language_data_ready) }
            }
            override fun onNothingSelected(p: AdapterView<*>?) {}
        }
        source.onItemSelectedListener = onPick
        target.onItemSelectedListener = onPick
        fun setUiLanguage(code: String) {
            if (code == prefs.uiLanguage) return
            save()
            Ui.setLanguage(this, code)
            if (Build.VERSION.SDK_INT < 33) recreate()  // every text again, in the new language (newer Android does it)
        }
        uiLang.onItemSelectedListener = object : AdapterView.OnItemSelectedListener {
            var first = 1
            override fun onItemSelected(p: AdapterView<*>?, v: View?, pos: Int, id: Long) {
                if (first > 0) { first--; return }
                setUiLanguage(Ui.uiLanguages[pos].first)
            }
            override fun onNothingSelected(p: AdapterView<*>?) {}
        }
        langButton.setOnClickListener { v ->
            val menu = android.widget.PopupMenu(ctx, v)
            Ui.uiLanguages.forEachIndexed { i, (_, label) -> menu.menu.add(0, i, i, getString(label)) }
            menu.setOnMenuItemClickListener { setUiLanguage(Ui.uiLanguages[it.itemId].first); true }
            menu.show()
        }

        screenButton.setOnClickListener {
            save()
            when {
                CaptureService.running && CaptureService.screenOn -> setFeatures(screen = false, speech = CaptureService.speechOn)
                prefs.sourceLang.code == prefs.targetLang.code -> status.text = getString(R.string.pick_two_languages)
                CaptureService.running && CaptureService.hasProjection ->
                    ensureLanguageData { setFeatures(screen = true, speech = CaptureService.speechOn) }
                else -> {  // not running, or only listening to the microphone (no screen capture yet): start afresh
                    val keepSpeech = CaptureService.running && CaptureService.speechOn
                    restart(screen = true, speech = keepSpeech)
                }
            }
        }
        speechButton.setOnClickListener {
            save()
            when {
                CaptureService.running && CaptureService.speechOn -> setFeatures(screen = CaptureService.screenOn, speech = false)
                CaptureService.running && (CaptureService.hasProjection || prefs.speechMic) -> ensureLanguageData {
                    ensureSpeechModel {
                        // Recording, of the microphone or of what the phone plays, both need this permission.
                        if (checkSelfPermission(Manifest.permission.RECORD_AUDIO) != PackageManager.PERMISSION_GRANTED) {
                            pendingSpeechOn = true
                            micLauncher.launch(Manifest.permission.RECORD_AUDIO)
                        } else {
                            setFeatures(screen = CaptureService.screenOn, speech = true)
                        }
                    }
                }
                else -> restart(screen = CaptureService.running && CaptureService.screenOn, speech = true)
            }
        }
    }

    override fun onResume() {
        super.onResume()
        refresh()
        if (System.currentTimeMillis() - prefs.lastUpdateCheck > 12 * 3600_000L) checkForUpdates(manual = false)
    }

    private var downloaded: java.io.File? = null

    /** Asks GitHub for a newer release; offers it if there is one. A manual check also says when there is none. */
    private fun checkForUpdates(manual: Boolean) {
        val pending = downloaded
        if (manual && pending != null && pending.isFile) {  // already downloaded: the user came back from the settings page
            if (Updater.install(this, pending)) return
        }
        Thread {
            val update = try { Updater.check(Updater.versionOf(this)) } catch (e: Exception) {
                runOnUiThread { if (manual) status.text = getString(R.string.update_no_connection) }
                return@Thread  // not recorded as a check: the next start-up tries again
            }
            prefs.lastUpdateCheck = System.currentTimeMillis()
            runOnUiThread {
                when {
                    update != null -> offerUpdate(update)
                    manual -> status.text = getString(R.string.up_to_date)
                }
            }
        }.start()
    }

    private fun offerUpdate(update: Updater.Update) {
        val mb = if (update.size > 0) " (${update.size / 1_000_000} MB)" else ""
        AlertDialog.Builder(this)
            .setTitle(R.string.update_title)
            .setMessage(getString(R.string.update_text, update.version, mb))
            .setPositiveButton(R.string.update) { _, _ -> downloadUpdate(update) }
            .setNegativeButton(R.string.later, null)
            .show()
    }

    private fun downloadUpdate(update: Updater.Update) {
        status.text = getString(R.string.update_progress, 0)
        Thread {
            try {
                val file = Updater.download(this, update) { pct -> runOnUiThread { status.text = getString(R.string.update_progress, pct) } }
                downloaded = file
                runOnUiThread {
                    status.text = if (Updater.install(this, file)) getString(R.string.update_downloaded)
                    else getString(R.string.allow_installs)
                }
            } catch (e: Exception) {
                runOnUiThread { status.text = getString(R.string.update_failed, e.message ?: "") }
            }
        }.start()
    }

    private fun refresh() {
        val screen = CaptureService.running && CaptureService.screenOn
        val speech = CaptureService.running && CaptureService.speechOn
        for ((button, on, start, stop) in listOf(
            Quad(screenButton, screen, R.string.screen_start, R.string.screen_stop),
            Quad(speechButton, speech, R.string.speech_start, R.string.speech_stop))) {
            button.text = getString(if (on) stop else start)
            button.background = Ui.rounded(if (on) Ui.LINE else Ui.ACCENT, 999f, this)
            button.setTextColor(if (on) Ui.INK else Ui.ON_ACCENT)
        }
        status.text = getString(when {
            screen && speech -> R.string.status_both
            screen -> R.string.status_screen
            speech -> R.string.status_speech
            else -> R.string.stopped
        })
    }

    private fun startFlow() {
        if (!Settings.canDrawOverlays(this)) {
            Toast.makeText(this, R.string.allow_overlay, Toast.LENGTH_LONG).show()
            startActivity(Intent(Settings.ACTION_MANAGE_OVERLAY_PERMISSION, Uri.parse("package:$packageName")))
            return
        }
        if (prefs.speech && checkSelfPermission(Manifest.permission.RECORD_AUDIO) != PackageManager.PERMISSION_GRANTED) {
            micLauncher.launch(Manifest.permission.RECORD_AUDIO)
            return
        }
        askNotification()
    }

    private fun askNotification() {
        if (Build.VERSION.SDK_INT >= 33 &&
            checkSelfPermission(Manifest.permission.POST_NOTIFICATIONS) != PackageManager.PERMISSION_GRANTED) {
            notificationLauncher.launch(Manifest.permission.POST_NOTIFICATIONS)
        } else {
            askProjection()
        }
    }

    private fun askProjection() {
        // Only speech from the microphone needs no screen sharing; what the phone plays can only be heard with it.
        if (!prefs.screenText && prefs.speechMic) {
            startForegroundService(Intent(this, CaptureService::class.java))
            status.postDelayed({ refresh() }, 600)
            return
        }
        val mpm = getSystemService(Context.MEDIA_PROJECTION_SERVICE) as MediaProjectionManager
        projectionLauncher.launch(mpm.createScreenCaptureIntent())
    }

    /** Speech recognition needs an offline model (about 40 MB); the user decides whether and how to download it. */
    private fun ensureSpeechModel(onReady: () -> Unit) {
        if (!prefs.speech) { onReady(); return }
        val model = VoskModels.forLang(prefs.speechLanguage)
        if (VoskModels.isInstalled(this, model)) { onReady(); return }
        AlertDialog.Builder(this)
            .setTitle(R.string.speech_model_title)
            .setMessage(getString(R.string.speech_model_text, prefs.speechLanguage.label, model.megabytes))
            .setPositiveButton(R.string.wifi_only) { _, _ -> downloadModel(model, true, onReady) }
            .setNeutralButton(R.string.any_network) { _, _ -> downloadModel(model, false, onReady) }
            .setNegativeButton(R.string.not_now) { _, _ -> status.text = getString(R.string.speech_model_needed, prefs.speechLanguage.label) }
            .show()
    }

    private fun downloadModel(model: VoskModel, wifiOnly: Boolean, onReady: () -> Unit) {
        status.text = getString(R.string.speech_model_downloading)
        VoskModels.download(this, model, wifiOnly,
            progress = { pct -> runOnUiThread { status.text = getString(R.string.speech_model_progress, pct) } },
            done = { err -> runOnUiThread {
                if (err == null) { status.text = getString(R.string.speech_model_ready); onReady() }
                else status.text = getString(R.string.download_failed, err.message ?: "")
            } })
    }

    /** Translation needs a language-data file per non-English language (about 30 MB). The user decides how to get it. */
    private fun ensureLanguageData(onReady: () -> Unit) {
        // Needed even with Google on: it is what translates when Google can't (no internet, or "too many requests").
        val langs = mutableListOf(prefs.targetLang.code)
        if (prefs.screenText) langs += prefs.sourceLang.code
        if (prefs.speech) langs += prefs.speechLanguage.code
        val needed = langs.filter { it != "en" }.distinct()
        val manager = RemoteModelManager.getInstance()
        manager.getDownloadedModels(TranslateRemoteModel::class.java).addOnSuccessListener { have ->
            val haveCodes = have.map { it.language }.toSet()
            val missing = needed.filter { it !in haveCodes }
            if (missing.isEmpty()) onReady() else askDownload(missing, onReady)
        }.addOnFailureListener { status.text = getString(R.string.language_data_check_failed, it.message ?: "") }
    }

    private fun askDownload(missing: List<String>, onReady: () -> Unit) {
        AlertDialog.Builder(this)
            .setTitle(R.string.language_data_title)
            .setMessage(getString(R.string.language_data_text, missing.joinToString { name(it) }))
            .setPositiveButton(R.string.wifi_only) { _, _ -> download(missing, true, onReady) }
            .setNeutralButton(R.string.any_network) { _, _ -> download(missing, false, onReady) }
            .setNegativeButton(R.string.not_now) { _, _ -> status.text = getString(R.string.language_data_needed, missing.joinToString { name(it) }) }
            .show()
    }

    private fun name(code: String) = (Langs.sources + Langs.targets).firstOrNull { it.code == code }?.label ?: code

    private fun download(codes: List<String>, wifiOnly: Boolean, onReady: () -> Unit) {
        val conditions = DownloadConditions.Builder().apply { if (wifiOnly) requireWifi() }.build()
        val manager = RemoteModelManager.getInstance()
        var left = codes.size
        status.text = getString(R.string.language_data_downloading, codes.joinToString { name(it) })
        for (code in codes) {
            manager.download(TranslateRemoteModel.Builder(code).build(), conditions)
                .addOnSuccessListener { if (--left == 0) { status.text = getString(R.string.language_data_downloaded); onReady() } }
                .addOnFailureListener { status.text = getString(R.string.download_failed, it.message ?: "") }
        }
    }
}

private data class Quad(val button: TextView, val on: Boolean, val start: Int, val stop: Int)
