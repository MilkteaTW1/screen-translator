package io.github.milkteatw1.screentranslator

import com.google.mlkit.nl.translate.TranslateLanguage

/** Which on-device text recognizer reads a language. */
enum class Script { LATIN, CHINESE, JAPANESE, KOREAN }

/** [code] is the ML Kit translation code; [traditional] asks for Traditional Chinese output. */
data class Lang(val label: String, val code: String, val script: Script = Script.LATIN, val traditional: Boolean = false)

object Langs {
    /** Languages the screen can be in (what the recognizers can read). */
    val sources = listOf(
        Lang("English", TranslateLanguage.ENGLISH),
        Lang("日本語 Japanese", TranslateLanguage.JAPANESE, Script.JAPANESE),
        Lang("中文 Chinese", TranslateLanguage.CHINESE, Script.CHINESE),
        Lang("한국어 Korean", TranslateLanguage.KOREAN, Script.KOREAN),
        Lang("Français", TranslateLanguage.FRENCH),
        Lang("Deutsch", TranslateLanguage.GERMAN),
        Lang("Español", TranslateLanguage.SPANISH),
        Lang("Italiano", TranslateLanguage.ITALIAN),
        Lang("Português", TranslateLanguage.PORTUGUESE),
        Lang("Bahasa Indonesia", TranslateLanguage.INDONESIAN),
        Lang("Tiếng Việt", TranslateLanguage.VIETNAMESE),
    )

    val targets = listOf(
        Lang("繁體中文 Traditional Chinese", TranslateLanguage.CHINESE, Script.CHINESE, traditional = true),
        Lang("简体中文 Simplified Chinese", TranslateLanguage.CHINESE, Script.CHINESE),
        Lang("English", TranslateLanguage.ENGLISH),
        Lang("日本語 Japanese", TranslateLanguage.JAPANESE, Script.JAPANESE),
        Lang("한국어 Korean", TranslateLanguage.KOREAN, Script.KOREAN),
        Lang("Français", TranslateLanguage.FRENCH),
        Lang("Deutsch", TranslateLanguage.GERMAN),
        Lang("Español", TranslateLanguage.SPANISH),
        Lang("Italiano", TranslateLanguage.ITALIAN),
        Lang("Português", TranslateLanguage.PORTUGUESE),
        Lang("Русский Russian", TranslateLanguage.RUSSIAN),
        Lang("Bahasa Indonesia", TranslateLanguage.INDONESIAN),
        Lang("Tiếng Việt", TranslateLanguage.VIETNAMESE),
        Lang("ไทย Thai", TranslateLanguage.THAI),
        Lang("العربية Arabic", TranslateLanguage.ARABIC),
    )
}
