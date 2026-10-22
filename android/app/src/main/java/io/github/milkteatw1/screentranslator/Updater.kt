package io.github.milkteatw1.screentranslator

import android.content.Context
import android.content.Intent
import android.net.Uri
import android.os.Build
import android.provider.Settings
import androidx.core.content.FileProvider
import org.json.JSONArray
import java.io.File
import java.net.HttpURLConnection
import java.net.URL

/** Looks for a newer release on GitHub and installs its APK (Android always asks the user to confirm the install). */
object Updater {
    private const val RELEASES = "https://api.github.com/repos/MilkteaTW1/screen-translator/releases?per_page=10"
    private val APK = Regex("""^ScreenTranslator-.*-(arm64|x86_64)\.apk$""")

    class Update(val version: String, val url: String, val size: Long)

    fun versionOf(context: Context): String =
        context.packageManager.getPackageInfo(context.packageName, 0).versionName ?: "0"

    /** Newer release that has an APK for this phone, or null when this is the newest. Throws when GitHub cannot be reached. */
    fun check(current: String, abis: List<String> = Build.SUPPORTED_ABIS.toList()): Update? {
        val conn = URL(RELEASES).openConnection() as HttpURLConnection
        conn.connectTimeout = 10_000
        conn.readTimeout = 10_000
        conn.setRequestProperty("Accept", "application/vnd.github+json")
        conn.setRequestProperty("User-Agent", "ScreenTranslator")
        return conn.inputStream.use { find(it.readBytes().toString(Charsets.UTF_8), current, abis) }
    }

    /** Picks the newest non-pre-release whose assets include an APK for one of [abis] and which is newer than [current].
     *  A release without an APK (a Windows-only one) is skipped, so it never hides an older release that has one. */
    internal fun find(json: String, current: String, abis: List<String>): Update? {
        val releases = JSONArray(json)
        val tags = abis.mapNotNull { mapOf("arm64-v8a" to "arm64", "x86_64" to "x86_64")[it] }
        var best: Update? = null
        for (i in 0 until releases.length()) {
            val r = releases.getJSONObject(i)
            if (r.optBoolean("prerelease") || r.optBoolean("draft")) continue
            val version = r.getString("tag_name").removePrefix("v")
            if (!newer(version, current) || (best != null && !newer(version, best.version))) continue
            val assets = r.getJSONArray("assets")
            val found = (0 until assets.length()).map { assets.getJSONObject(it) }
                .mapNotNull { a -> APK.find(a.getString("name"))?.let { m -> m.groupValues[1] to a } }
            val pick = tags.firstNotNullOfOrNull { tag -> found.firstOrNull { it.first == tag }?.second } ?: continue
            best = Update(version, pick.getString("browser_download_url"), pick.optLong("size"))
        }
        return best
    }

    internal fun newer(a: String, b: String): Boolean {
        fun parts(v: String) = Regex("""\d+""").findAll(v).map { it.value.toInt() }.toList().take(3)
        val x = parts(a)
        val y = parts(b)
        for (i in 0 until 3) {
            val d = (x.getOrElse(i) { 0 }) - (y.getOrElse(i) { 0 })
            if (d != 0) return d > 0
        }
        return false
    }

    /** Downloads the APK into the app's cache folder. [progress] gets 0..100. Throws if it is cut off. */
    fun download(context: Context, update: Update, progress: (Int) -> Unit): File {
        val dir = File(context.cacheDir, "update").apply { mkdirs() }
        dir.listFiles()?.forEach { it.delete() }
        val file = File(dir, "ScreenTranslator-${update.version}.apk")
        val conn = URL(update.url).openConnection() as HttpURLConnection
        conn.connectTimeout = 15_000
        conn.readTimeout = 30_000
        conn.setRequestProperty("User-Agent", "ScreenTranslator")
        val total = conn.contentLengthLong
        var done = 0L
        conn.inputStream.use { input ->
            file.outputStream().use { out ->
                val buffer = ByteArray(64 * 1024)
                while (true) {
                    val n = input.read(buffer)
                    if (n < 0) break
                    out.write(buffer, 0, n)
                    done += n
                    if (total > 0) progress((done * 100 / total).toInt())
                }
            }
        }
        if (total > 0 && done < total) throw java.io.IOException("download was cut off")
        return file
    }

    /** Opens the system installer for [file]. Returns false when the user first has to allow installs from this
     *  app (their settings page is opened; coming back and tapping update again continues). */
    fun install(context: Context, file: File): Boolean {
        if (Build.VERSION.SDK_INT >= 26 && !context.packageManager.canRequestPackageInstalls()) {
            context.startActivity(Intent(Settings.ACTION_MANAGE_UNKNOWN_APP_SOURCES, Uri.parse("package:${context.packageName}"))
                .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK))
            return false
        }
        val uri = FileProvider.getUriForFile(context, "${context.packageName}.updates", file)
        context.startActivity(Intent(Intent.ACTION_VIEW)
            .setDataAndType(uri, "application/vnd.android.package-archive")
            .addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION or Intent.FLAG_ACTIVITY_NEW_TASK))
        return true
    }
}
