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
            status.text = "Screen capture was not allowed"
        }
    }
    private val notificationLauncher = registerForActivityResult(ActivityResultContracts.RequestPermission()) { askProjection() }
    private val micLauncher = registerForActivityResult(ActivityResultContracts.RequestPermission()) { ok ->
        if (ok) askNotification() else status.text = "Microphone permission is needed for speech"
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        prefs = Prefs(this)
        val pad = (16 * resources.displayMetrics.density).toInt()
        val column = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            setPadding(pad, pad * 2, pad, pad)
        }
        fun label(text: String) = TextView(this).apply { this.text = text; setPadding(0, pad / 2, 0, 0) }

        column.addView(TextView(this).apply { text = "Screen Translator"; textSize = 24f })
        column.addView(label("Screen language"))
        val source = Spinner(this)
        source.adapter = ArrayAdapter(this, android.R.layout.simple_spinner_dropdown_item, Langs.sources.map { it.label })
        source.setSelection(prefs.source)
        column.addView(source)
        column.addView(label("Translate to"))
        val target = Spinner(this)
        target.adapter = ArrayAdapter(this, android.R.layout.simple_spinner_dropdown_item, Langs.targets.map { it.label })
        target.setSelection(prefs.target)
        column.addView(target)

        column.addView(label("Refresh interval (seconds)"))
        val interval = EditText(this).apply {
            inputType = InputType.TYPE_CLASS_NUMBER or InputType.TYPE_NUMBER_FLAG_DECIMAL
            setText((prefs.intervalMs / 1000.0).toString())
        }
        column.addView(interval)

        val skip = CheckBox(this).apply { text = "Skip names and one-word labels"; isChecked = prefs.skipNames }
        column.addView(skip)
        column.addView(label("Never translate these (one per line)"))
        val glossary = EditText(this).apply {
            inputType = InputType.TYPE_CLASS_TEXT or InputType.TYPE_TEXT_FLAG_MULTI_LINE
            minLines = 3
            setText(prefs.glossary)
            hint = "Hatsune Miku\nNVIDIA"
        }
        column.addView(glossary)

        column.addView(label("What to translate"))
        val screenBox = CheckBox(this).apply { text = "Text on the screen"; isChecked = prefs.screenText }
        column.addView(screenBox)
        val speechBox = CheckBox(this).apply { text = "Speech (list what is heard at the bottom)"; isChecked = prefs.speech }
        column.addView(speechBox)
        val micBox = CheckBox(this).apply { text = "Listen to the microphone instead of phone audio"; isChecked = prefs.speechMic }
        column.addView(micBox)
        column.addView(label("Spoken language"))
        val speechLang = Spinner(this)
        speechLang.adapter = ArrayAdapter(this, android.R.layout.simple_spinner_dropdown_item, VoskModels.languages.map { it.label })
        speechLang.setSelection(prefs.speechLang)
        column.addView(speechLang)

        toggle = Button(this)
        status = TextView(this).apply { setPadding(0, pad / 2, 0, 0) }
        column.addView(toggle)
        column.addView(status)
        setContentView(ScrollView(this).apply { addView(column) })

        fun save() {
            prefs.source = source.selectedItemPosition
            prefs.target = target.selectedItemPosition
            prefs.intervalMs = ((interval.text.toString().toDoubleOrNull() ?: 1.0) * 1000).toInt().coerceAtLeast(100)
            prefs.skipNames = skip.isChecked
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
                ensureLanguageData { status.text = "Language data ready" }
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
                status.text = "Choose screen text, speech, or both"
            } else if (prefs.screenText && prefs.sourceLang.code == prefs.targetLang.code) {
                status.text = "Pick two different languages"
            } else {
                ensureLanguageData { ensureSpeechModel { startFlow() } }
            }
        }
    }

    override fun onResume() {
        super.onResume()
        refresh()
    }

    private fun refresh() {
        toggle.text = if (CaptureService.running) "Stop" else "Start"
        status.text = if (CaptureService.running) "Running" else "Stopped"
    }

    private fun startFlow() {
        if (!Settings.canDrawOverlays(this)) {
            Toast.makeText(this, "Allow \"Display over other apps\", then press Start again", Toast.LENGTH_LONG).show()
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
            .setTitle("Download speech model?")
            .setMessage("Listening in ${prefs.speechLanguage.label} needs an offline speech model (about ${model.megabytes} MB, downloaded once). How do you want to download?")
            .setPositiveButton("Wi-Fi only") { _, _ -> downloadModel(model, true, onReady) }
            .setNeutralButton("Any network") { _, _ -> downloadModel(model, false, onReady) }
            .setNegativeButton("Not now") { _, _ -> status.text = "Speech model needed for ${prefs.speechLanguage.label}" }
            .show()
    }

    private fun downloadModel(model: VoskModel, wifiOnly: Boolean, onReady: () -> Unit) {
        status.text = "Downloading speech model ..."
        VoskModels.download(this, model, wifiOnly,
            progress = { pct -> runOnUiThread { status.text = "Downloading speech model $pct%" } },
            done = { err -> runOnUiThread {
                if (err == null) { status.text = "Speech model ready"; onReady() }
                else status.text = "Download failed: ${err.message}"
            } })
    }

    /** Translation needs a language-data file per non-English language (about 30 MB). The user decides how to get it. */
    private fun ensureLanguageData(onReady: () -> Unit) {
        val langs = mutableListOf(prefs.targetLang.code)
        if (prefs.screenText) langs += prefs.sourceLang.code
        if (prefs.speech) langs += prefs.speechLanguage.code
        val needed = langs.filter { it != "en" }.distinct()
        val manager = RemoteModelManager.getInstance()
        manager.getDownloadedModels(TranslateRemoteModel::class.java).addOnSuccessListener { have ->
            val haveCodes = have.map { it.language }.toSet()
            val missing = needed.filter { it !in haveCodes }
            if (missing.isEmpty()) onReady() else askDownload(missing, onReady)
        }.addOnFailureListener { status.text = "Could not check language data: ${it.message}" }
    }

    private fun askDownload(missing: List<String>, onReady: () -> Unit) {
        AlertDialog.Builder(this)
            .setTitle("Download language data?")
            .setMessage("Offline translation needs: ${missing.joinToString { name(it) }} (about 30 MB each, downloaded once). How do you want to download?")
            .setPositiveButton("Wi-Fi only") { _, _ -> download(missing, true, onReady) }
            .setNeutralButton("Any network") { _, _ -> download(missing, false, onReady) }
            .setNegativeButton("Not now") { _, _ -> status.text = "Language data needed: ${missing.joinToString { name(it) }}" }
            .show()
    }

    private fun name(code: String) = (Langs.sources + Langs.targets).firstOrNull { it.code == code }?.label ?: code

    private fun download(codes: List<String>, wifiOnly: Boolean, onReady: () -> Unit) {
        val conditions = DownloadConditions.Builder().apply { if (wifiOnly) requireWifi() }.build()
        val manager = RemoteModelManager.getInstance()
        var left = codes.size
        status.text = "Downloading ${codes.joinToString { name(it) }} ..."
        for (code in codes) {
            manager.download(TranslateRemoteModel.Builder(code).build(), conditions)
                .addOnSuccessListener { if (--left == 0) { status.text = "Language data downloaded"; onReady() } }
                .addOnFailureListener { status.text = "Download failed: ${it.message}" }
        }
    }
}
