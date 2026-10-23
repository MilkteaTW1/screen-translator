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
    /** The spoken language: "auto" (Whisper detects it) or a language code. */
    var spokenLanguage: String
        get() = sp.getString("spokenLanguage", "auto") ?: "auto"
        set(v) = sp.edit().putString("spokenLanguage", v).apply()
    /** The Whisper model: "base" (better) or "tiny" (lighter). */
    var speechModel: String
        get() = sp.getString("speechModel", "base") ?: "base"
        set(v) = sp.edit().putString("speechModel", v).apply()

    /** Interface language ("" follows the phone). */
    var uiLanguage: String
        get() = sp.getString("uiLanguage", "") ?: ""
        set(v) = sp.edit().putString("uiLanguage", v).apply()
    /** Where the 譯 button was dragged to (-1: not moved yet). */
    var chipX: Int
        get() = sp.getInt("chipX", -1)
        set(v) = sp.edit().putInt("chipX", v).apply()
    var chipY: Int
        get() = sp.getInt("chipY", -1)
        set(v) = sp.edit().putInt("chipY", v).apply()
    var lastTab: Int
        get() = sp.getInt("lastTab", 0)
        set(v) = sp.edit().putInt("lastTab", v).apply()

    var lastUpdateCheck: Long
        get() = sp.getLong("lastUpdateCheck", 0)
        set(v) = sp.edit().putLong("lastUpdateCheck", v).apply()

    val whisperModel get() = WhisperModel.spec(speechModel)
    val sourceLang get() = Langs.sources[source]
    val targetLang get() = Langs.targets[target]
}
