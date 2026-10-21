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
            } else if (prefs.sourceLang.code == prefs.targetLang.code) {
                status.text = "Pick two different languages"
            } else {
                ensureLanguageData { startFlow() }
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
        if (Build.VERSION.SDK_INT >= 33 &&
            checkSelfPermission(Manifest.permission.POST_NOTIFICATIONS) != PackageManager.PERMISSION_GRANTED) {
            notificationLauncher.launch(Manifest.permission.POST_NOTIFICATIONS)
        } else {
            askProjection()
        }
    }

    private fun askProjection() {
        val mpm = getSystemService(Context.MEDIA_PROJECTION_SERVICE) as MediaProjectionManager
        projectionLauncher.launch(mpm.createScreenCaptureIntent())
    }

    /** Translation needs a language-data file per non-English language (about 30 MB). The user decides how to get it. */
    private fun ensureLanguageData(onReady: () -> Unit) {
        val needed = listOf(prefs.sourceLang.code, prefs.targetLang.code).filter { it != "en" }.distinct()
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
