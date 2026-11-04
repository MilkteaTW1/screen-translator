package io.github.milkteatw1.screentranslator

import android.content.Context

/** Why text was read but not translated: one likeliest reason, so the user gets one message. */
object Trouble {
    /** "refused" (Google says no), "network" (cannot reach Google) or "offline" (the offline model is the problem). */
    fun kind(useGoogle: Boolean, googleState: String): String = when {
        !useGoogle -> "offline"
        googleState == "refused" -> "refused"
        googleState == "unreachable" -> "network"
        else -> "offline"
    }

    fun text(context: Context, kind: String, detail: String): String = context.getString(
        when (kind) {
            "refused" -> R.string.problem_refused
            "network" -> R.string.problem_network
            else -> R.string.problem_offline
        }, detail)
}
