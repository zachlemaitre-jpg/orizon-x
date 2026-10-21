package com.orizonx.client.actions

import com.orizonx.client.i18n.Lang
import java.util.Locale

/** Display strings and small rules for the performance blocks. Pure, so they are unit-tested. */
object PerfFormat {
    private fun point(lang: Lang) = if (lang == Lang.FR) ',' else '.'

    /** "23 %" / "23%" */
    fun percent(v: Int, lang: Lang): String = if (lang == Lang.FR) "$v %" else "$v%"

    /** One decimal, dropped when it is zero: 12.3 -> "12,3", 32.0 -> "32". */
    private fun amount(v: Float, lang: Lang): String =
        String.format(Locale.ROOT, "%.1f", v).replace('.', point(lang)).removeSuffix("${point(lang)}0")

    /** "12,3 / 32 Go" / "12.3 / 32 GB" */
    fun gb(used: Float, total: Float, lang: Lang): String =
        "${amount(used, lang)} / ${amount(total, lang)} ${if (lang == Lang.FR) "Go" else "GB"}"

    /** "4,1 GHz" / "4.1 GHz" */
    fun ghz(v: Float, lang: Lang): String =
        String.format(Locale.ROOT, "%.1f", v).replace('.', point(lang)) + " GHz"

    /**
     * "500 o/s", "80 Ko/s", "1,2 Mo/s" (B/s, KB/s, MB/s in English). Base 1024; one decimal from 1 Mo/s up, none below.
     */
    fun rate(bytesPerS: Long, lang: Lang): String {
        val fr = lang == Lang.FR
        val v = bytesPerS.coerceAtLeast(0L)
        val kb = Math.round(v / 1024.0)
        return when {
            v < 1024L -> "$v ${if (fr) "o" else "B"}/s"
            kb < 1024L -> "$kb ${if (fr) "Ko" else "KB"}/s"
            else -> String.format(Locale.ROOT, "%.1f", v / (1024.0 * 1024.0)).replace('.', point(lang)) +
                " ${if (fr) "Mo" else "MB"}/s"
        }
    }

    /** The top of the Wi-Fi graph: the next of 1, 2, 5 x 10^n at or above [maxValue], and at least 1024 bytes/s. */
    fun netScale(maxValue: Long): Long {
        if (maxValue <= 1024L) return 1024L
        var magnitude = 1L
        while (magnitude <= Long.MAX_VALUE / 10 && magnitude * 10 < maxValue) magnitude *= 10
        for (step in longArrayOf(1, 2, 5, 10)) {
            val scale = step * magnitude
            if (scale >= maxValue) return maxOf(scale, 1024L)
        }
        return magnitude * 10
    }

    /** A 1x1 block shows only the icon, the name and the value. */
    fun compact(cols: Int, rows: Int): Boolean = cols < 2 && rows < 2
}
