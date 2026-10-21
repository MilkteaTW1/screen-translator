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

    val sourceLang get() = Langs.sources[source]
    val targetLang get() = Langs.targets[target]
}
