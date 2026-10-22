package io.github.milkteatw1.screentranslator

import android.content.Context
import android.content.res.ColorStateList
import android.content.res.Configuration
import android.graphics.Color
import android.graphics.Typeface
import android.graphics.drawable.GradientDrawable
import android.text.InputType
import android.view.Gravity
import android.view.View
import android.view.ViewGroup
import android.widget.ArrayAdapter
import android.widget.EditText
import android.widget.LinearLayout
import android.widget.Spinner
import android.widget.Switch
import android.widget.TextView
import java.util.Locale

/** The app's look (the same dark palette as the desktop app's overlay) and small builders for the settings screen. */
object Ui {
    const val GROUND = 0xFF0E1217.toInt()
    const val CARD = 0xFF171D24.toInt()
    const val LINE = 0xFF26303A.toInt()
    const val INK = 0xFFE9EEF3.toInt()
    const val MUTED = 0xFF8FA3B4.toInt()
    const val ACCENT = 0xFFFFE68C.toInt()
    const val ON_ACCENT = 0xFF0E1217.toInt()
    const val STOP = 0xFFE5736B.toInt()

    /** Interface languages the user can pick ("" follows the phone). */
    val uiLanguages = listOf("" to R.string.follow_system, "zh-TW" to R.string.lang_zh_tw, "en" to R.string.lang_en)

    /** Sets the interface language ("" follows the phone). */
    fun setLanguage(ctx: Context, code: String) {
        Prefs(ctx).uiLanguage = code
        if (android.os.Build.VERSION.SDK_INT >= 33) {
            ctx.getSystemService(android.app.LocaleManager::class.java).applicationLocales =
                if (code.isEmpty()) android.os.LocaleList.getEmptyLocaleList() else android.os.LocaleList.forLanguageTags(code)
        }
    }

    /** [base] showing the interface language chosen in the app (Android 12 and older; newer ones do it themselves). */
    fun localized(base: Context): Context {
        if (android.os.Build.VERSION.SDK_INT >= 33) return base
        val code = Prefs(base).uiLanguage
        if (code.isEmpty()) return base
        val config = Configuration(base.resources.configuration)
        config.setLocale(Locale.forLanguageTag(code))
        return base.createConfigurationContext(config)
    }

    fun Context.dp(v: Int) = (v * resources.displayMetrics.density).toInt()

    fun rounded(color: Int, radiusDp: Float, ctx: Context, stroke: Int? = null) = GradientDrawable().apply {
        setColor(color)
        cornerRadius = radiusDp * ctx.resources.displayMetrics.density
        if (stroke != null) setStroke(ctx.dp(1), stroke)
    }

    fun text(ctx: Context, s: CharSequence, sizeSp: Float = 15f, color: Int = INK, bold: Boolean = false) = TextView(ctx).apply {
        text = s
        textSize = sizeSp
        setTextColor(color)
        if (bold) typeface = Typeface.DEFAULT_BOLD
    }

    /** A card holding one group of settings, with a small heading. */
    fun card(ctx: Context, heading: String): LinearLayout = LinearLayout(ctx).apply {
        orientation = LinearLayout.VERTICAL
        background = rounded(CARD, 16f, ctx, LINE)
        setPadding(ctx.dp(18), ctx.dp(14), ctx.dp(18), ctx.dp(16))
        layoutParams = LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT)
            .apply { bottomMargin = ctx.dp(14) }
        addView(text(ctx, heading, 13f, ACCENT, bold = true).apply { letterSpacing = 0.06f; setPadding(0, 0, 0, ctx.dp(6)) })
    }

    fun label(ctx: Context, s: String) = text(ctx, s, 13f, MUTED).apply { setPadding(0, ctx.dp(10), 0, ctx.dp(4)) }

    fun switch(ctx: Context, s: String, on: Boolean) = Switch(ctx).apply {
        text = s
        textSize = 15f
        setTextColor(INK)
        isChecked = on
        setPadding(0, ctx.dp(8), 0, ctx.dp(8))
        val states = arrayOf(intArrayOf(android.R.attr.state_checked), intArrayOf())
        thumbTintList = ColorStateList(states, intArrayOf(ACCENT, 0xFFB8C4CF.toInt()))
        trackTintList = ColorStateList(states, intArrayOf(0x88FFE68C.toInt(), 0xFF3A4652.toInt()))
    }

    fun spinner(ctx: Context, items: List<String>, selected: Int) = Spinner(ctx).apply {
        adapter = object : ArrayAdapter<String>(ctx, android.R.layout.simple_spinner_item, items) {
            override fun getView(position: Int, convertView: View?, parent: ViewGroup) =
                (super.getView(position, convertView, parent) as TextView).apply { setTextColor(INK); textSize = 16f }
            override fun getDropDownView(position: Int, convertView: View?, parent: ViewGroup) =
                (super.getDropDownView(position, convertView, parent) as TextView).apply {
                    setTextColor(INK); textSize = 16f; setPadding(ctx.dp(16), ctx.dp(12), ctx.dp(16), ctx.dp(12))
                }
        }
        background = rounded(0xFF1F2730.toInt(), 10f, ctx, LINE)
        setPopupBackgroundDrawable(rounded(0xFF1F2730.toInt(), 10f, ctx))
        setPadding(ctx.dp(6), ctx.dp(4), ctx.dp(6), ctx.dp(4))
        setSelection(selected)
    }

    fun field(ctx: Context, value: String, number: Boolean = false, lines: Int = 1) = EditText(ctx).apply {
        setText(value)
        setTextColor(INK)
        setHintTextColor(0xFF5B6B7A.toInt())
        textSize = 16f
        background = rounded(0xFF1F2730.toInt(), 10f, ctx, LINE)
        setPadding(ctx.dp(12), ctx.dp(10), ctx.dp(12), ctx.dp(10))
        inputType = if (number) InputType.TYPE_CLASS_NUMBER or InputType.TYPE_NUMBER_FLAG_DECIMAL
        else InputType.TYPE_CLASS_TEXT or InputType.TYPE_TEXT_FLAG_MULTI_LINE
        if (lines > 1) { minLines = lines; gravity = Gravity.TOP or Gravity.START }
    }

    /** A pill-shaped button; [primary] is the yellow one. */
    fun pill(ctx: Context, s: String, primary: Boolean) = TextView(ctx).apply {
        text = s
        gravity = Gravity.CENTER
        textSize = if (primary) 18f else 14f
        typeface = Typeface.DEFAULT_BOLD
        setTextColor(if (primary) ON_ACCENT else INK)
        background = rounded(if (primary) ACCENT else Color.TRANSPARENT, 999f, ctx, if (primary) null else LINE)
        setPadding(ctx.dp(18), ctx.dp(if (primary) 15 else 9), ctx.dp(18), ctx.dp(if (primary) 15 else 9))
        isClickable = true
        isFocusable = true
    }
}
