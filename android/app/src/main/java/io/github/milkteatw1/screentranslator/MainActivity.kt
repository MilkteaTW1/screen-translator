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
import android.text.InputType
import android.view.View
import android.widget.AdapterView
import android.widget.ArrayAdapter
import android.widget.Button
import android.widget.CheckBox
import android.widget.EditText
import android.widget.LinearLayout
import android.widget.ScrollView
import android.widget.Spinner
import android.widget.TextView
import android.widget.Toast
import androidx.activity.ComponentActivity
import androidx.activity.result.contract.ActivityResultContracts
import com.google.mlkit.common.model.DownloadConditions
import com.google.mlkit.common.model.RemoteModelManager
import com.google.mlkit.nl.translate.TranslateRemoteModel

/** Settings screen: pick the languages, decide how language data is downloaded, start and stop. */
class MainActivity : ComponentActivity() {
    private lateinit var prefs: Prefs
    private lateinit var toggle: Button
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
        if (ok) askNotification() else status.text = getString(R.string.mic_needed)
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        prefs = Prefs(this)
        val pad = (16 * resources.displayMetrics.density).toInt()
        val column = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            setPadding(pad, pad * 2, pad, pad)
        }
        fun label(id: Int) = TextView(this).apply { text = getString(id); setPadding(0, pad / 2, 0, 0) }

        column.addView(TextView(this).apply { text = getString(R.string.app_title); textSize = 24f })
        column.addView(label(R.string.screen_language))
        val source = Spinner(this)
        source.adapter = ArrayAdapter(this, android.R.layout.simple_spinner_dropdown_item, Langs.sources.map { it.label })
        source.setSelection(prefs.source)
        column.addView(source)
        column.addView(label(R.string.translate_to))
        val target = Spinner(this)
        target.adapter = ArrayAdapter(this, android.R.layout.simple_spinner_dropdown_item, Langs.targets.map { it.label })
        target.setSelection(prefs.target)
        column.addView(target)

        column.addView(label(R.string.refresh_interval))
        val interval = EditText(this).apply {
            inputType = InputType.TYPE_CLASS_NUMBER or InputType.TYPE_NUMBER_FLAG_DECIMAL
            setText((prefs.intervalMs / 1000.0).toString())
        }
        column.addView(interval)

        val skip = CheckBox(this).apply { text = getString(R.string.skip_names); isChecked = prefs.skipNames }
        column.addView(skip)
        column.addView(label(R.string.glossary_label))
        val glossary = EditText(this).apply {
            inputType = InputType.TYPE_CLASS_TEXT or InputType.TYPE_TEXT_FLAG_MULTI_LINE
            minLines = 3
            setText(prefs.glossary)
            hint = "Hatsune Miku\nNVIDIA"
        }
        column.addView(glossary)
        val google = CheckBox(this).apply { text = getString(R.string.use_google); isChecked = prefs.useGoogle }
        column.addView(google)

        column.addView(label(R.string.what_to_translate))
        val screenBox = CheckBox(this).apply { text = getString(R.string.screen_text); isChecked = prefs.screenText }
        column.addView(screenBox)
        val speechBox = CheckBox(this).apply { text = getString(R.string.speech); isChecked = prefs.speech }
        column.addView(speechBox)
        val micBox = CheckBox(this).apply { text = getString(R.string.speech_mic); isChecked = prefs.speechMic }
        column.addView(micBox)
        column.addView(label(R.string.spoken_language))
        val speechLang = Spinner(this)
        speechLang.adapter = ArrayAdapter(this, android.R.layout.simple_spinner_dropdown_item, VoskModels.languages.map { it.label })
        speechLang.setSelection(prefs.speechLang)
        column.addView(speechLang)

        toggle = Button(this)
        status = TextView(this).apply { setPadding(0, pad / 2, 0, 0) }
        column.addView(toggle)
        column.addView(status)
        column.addView(Button(this).apply {
            text = getString(R.string.check_updates, Updater.versionOf(this@MainActivity))
            setOnClickListener { checkForUpdates(manual = true) }
        })
        setContentView(ScrollView(this).apply { addView(column) })

        fun save() {
            prefs.source = source.selectedItemPosition
            prefs.target = target.selectedItemPosition
            prefs.intervalMs = ((interval.text.toString().toDoubleOrNull() ?: 1.0) * 1000).toInt().coerceAtLeast(100)
            prefs.skipNames = skip.isChecked
            prefs.useGoogle = google.isChecked
            prefs.glossary = glossary.text.toString()
            prefs.screenText = screenBox.isChecked
            prefs.speech = speechBox.isChecked
            prefs.speechMic = micBox.isChecked
            prefs.speechLang = speechLang.selectedItemPosition
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

        toggle.setOnClickListener {
            save()
            if (CaptureService.running) {
                startService(Intent(this, CaptureService::class.java).setAction(CaptureService.ACTION_STOP))
                status.postDelayed({ refresh() }, 400)
            } else if (!prefs.screenText && !prefs.speech) {
                status.text = getString(R.string.choose_something)
            } else if (prefs.screenText && prefs.sourceLang.code == prefs.targetLang.code) {
                status.text = getString(R.string.pick_two_languages)
            } else {
                ensureLanguageData { ensureSpeechModel { startFlow() } }
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
        toggle.text = getString(if (CaptureService.running) R.string.stop else R.string.start)
        status.text = getString(if (CaptureService.running) R.string.running else R.string.stopped)
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
        // Only listening to the microphone needs no screen capture at all.
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
        if (prefs.useGoogle) { onReady(); return }  // Google Translate needs no download; offline data is only the backup
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
