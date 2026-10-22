package io.github.milkteatw1.screentranslator

import android.content.Context

/** The user's choices, shared between the settings screen and the capture service. */
class Prefs(context: Context) {
    private val sp = context.getSharedPreferences("settings", Context.MODE_PRIVATE)

    var source: Int
        get() = sp.getInt("source", 0).coerceIn(0, Langs.sources.lastIndex)
        set(v) = sp.edit().putInt("source", v).apply()
    var target: Int
        get() = sp.getInt("target", 0).coerceIn(0, Langs.targets.lastIndex)
        set(v) = sp.edit().putInt("target", v).apply()
    var intervalMs: Int
        get() = sp.getInt("interval", 1000)
        set(v) = sp.edit().putInt("interval", v).apply()
    var glossary: String
        get() = sp.getString("glossary", "") ?: ""
        set(v) = sp.edit().putString("glossary", v).apply()
    var skipNames: Boolean
        get() = sp.getBoolean("skipNames", true)
        set(v) = sp.edit().putBoolean("skipNames", v).apply()

    var useGoogle: Boolean
        get() = sp.getBoolean("useGoogle", true)
        set(v) = sp.edit().putBoolean("useGoogle", v).apply()

    var screenText: Boolean
        get() = sp.getBoolean("screenText", true)
        set(v) = sp.edit().putBoolean("screenText", v).apply()
    var speech: Boolean
        get() = sp.getBoolean("speech", false)
        set(v) = sp.edit().putBoolean("speech", v).apply()
    var speechMic: Boolean
        get() = sp.getBoolean("speechMic", false)
        set(v) = sp.edit().putBoolean("speechMic", v).apply()
    var speechLang: Int
        get() = sp.getInt("speechLang", 0).coerceIn(0, VoskModels.languages.lastIndex)
        set(v) = sp.edit().putInt("speechLang", v).apply()

    var lastUpdateCheck: Long
        get() = sp.getLong("lastUpdateCheck", 0)
        set(v) = sp.edit().putLong("lastUpdateCheck", v).apply()

    val speechLanguage get() = VoskModels.languages[speechLang]
    val sourceLang get() = Langs.sources[source]
    val targetLang get() = Langs.targets[target]
}
