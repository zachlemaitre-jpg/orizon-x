package com.orizonx.client.claude

import com.orizonx.client.i18n.Lang
import com.orizonx.client.i18n.S
import com.orizonx.client.i18n.Strings
import kotlin.math.roundToLong

/** Display strings of the Claude Code screen, in the interface language. Pure, so they are unit-tested. */
object ClaudeFormat {
    /**
     * How long ago [updatedSeconds] was, at [nowSeconds] (both epoch seconds on the same clock): "just now" under a
     * minute (also for times slightly in the future), then "3 min", "2 h", "yesterday" (24 to 48 h) and "N d".
     */
    fun age(updatedSeconds: Long, nowSeconds: Long, lang: Lang): String {
        val seconds = nowSeconds - updatedSeconds
        return when {
            seconds < 60 -> Strings.get(S.CLAUDE_AGE_NOW, lang)
            seconds < 3_600 -> Strings.get(S.CLAUDE_AGE_MINUTES, lang, "n" to seconds / 60)
            seconds < 86_400 -> Strings.get(S.CLAUDE_AGE_HOURS, lang, "n" to seconds / 3_600)
            seconds < 172_800 -> Strings.get(S.CLAUDE_AGE_YESTERDAY, lang)
            else -> Strings.get(S.CLAUDE_AGE_DAYS, lang, "n" to seconds / 86_400)
        }
    }

    /**
     * A context size for a label: "842", "561 k", "1.2 M" ("1,2 M" in French). Thousands are rounded to the nearest k,
     * millions keep one decimal.
     */
    fun tokens(count: Long, lang: Lang): String {
        val n = count.coerceAtLeast(0L)
        if (n < 1_000L) return n.toString()
        val thousands = (n / 1000.0).roundToLong()
        if (thousands < 1_000L) return "$thousands k"
        val tenths = (n / 100_000.0).roundToLong() // 1_234_567 -> 12
        val separator = if (lang == Lang.FR) "," else "."
        return "${tenths / 10}$separator${tenths % 10} M"
    }

    /** "14:32": the PC wall-clock time of [epochSeconds] in the PC's zone (fixed [utcOffsetMin]), for "seen at". */
    fun clockTime(epochSeconds: Long, utcOffsetMin: Int): String {
        val local = Math.floorMod(epochSeconds + utcOffsetMin * 60L, 86_400L)
        return String.format(java.util.Locale.ROOT, "%02d:%02d", local / 3_600, local % 3_600 / 60)
    }

    /** 0..1 for a progress bar from a percentage; out-of-range values are clamped. */
    fun fraction(percent: Int?): Float = ((percent ?: 0).coerceIn(0, 100)) / 100f
}
