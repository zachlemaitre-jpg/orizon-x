package com.orizonx.client.actions

import com.orizonx.client.i18n.Lang
import com.orizonx.client.i18n.S
import com.orizonx.client.i18n.Strings
import java.time.LocalDateTime
import java.time.ZoneOffset
import java.util.Locale

/** How alarming the battery pictogram should look. */
enum class BatteryLevel { NORMAL, LOW, CRITICAL }

/** Display strings for the Actions screen, in the interface language. Pure, so they are unit-tested. */
object ActionsFormat {
    private val DAYS_FR = listOf("Lundi", "Mardi", "Mercredi", "Jeudi", "Vendredi", "Samedi", "Dimanche")
    private val MONTHS_FR = listOf(
        "janvier", "février", "mars", "avril", "mai", "juin",
        "juillet", "août", "septembre", "octobre", "novembre", "décembre",
    )
    private val DAYS_EN = listOf("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday")
    private val MONTHS_EN = listOf(
        "January", "February", "March", "April", "May", "June",
        "July", "August", "September", "October", "November", "December",
    )

    /** PC wall-clock time for [epochMs] in the PC's zone (fixed [utcOffsetMin]). */
    private fun local(epochMs: Long, utcOffsetMin: Int): LocalDateTime =
        LocalDateTime.ofEpochSecond(Math.floorDiv(epochMs, 1000L) + utcOffsetMin * 60L, 0, ZoneOffset.UTC)

    /** "14:32" */
    fun hoursMinutes(epochMs: Long, utcOffsetMin: Int): String {
        val t = local(epochMs, utcOffsetMin)
        return String.format(Locale.ROOT, "%02d:%02d", t.hour, t.minute)
    }

    /** "05" */
    fun seconds(epochMs: Long, utcOffsetMin: Int): String =
        String.format(Locale.ROOT, "%02d", local(epochMs, utcOffsetMin).second)

    /** "Samedi 11 octobre" / "Saturday, October 11" */
    fun date(epochMs: Long, utcOffsetMin: Int, lang: Lang): String {
        val t = local(epochMs, utcOffsetMin)
        val day = t.dayOfWeek.value - 1
        val month = t.monthValue - 1
        return when (lang) {
            Lang.FR -> "${DAYS_FR[day]} ${t.dayOfMonth} ${MONTHS_FR[month]}"
            Lang.EN -> "${DAYS_EN[day]}, ${MONTHS_EN[month]} ${t.dayOfMonth}"
        }
    }

    /** "PC 76 % · en charge" / "PC 76% · charging" */
    fun battery(b: BatteryState, lang: Lang): String =
        Strings.get(if (b.charging) S.BATTERY_CHARGING else S.BATTERY, lang, "percent" to b.percent)

    /** Green above 20 %, amber at 20 % or less, red at 10 % or less. */
    fun batteryLevel(percent: Int): BatteryLevel = when {
        percent <= 10 -> BatteryLevel.CRITICAL
        percent <= 20 -> BatteryLevel.LOW
        else -> BatteryLevel.NORMAL
    }

    /** Filled share of the battery body, 0..1. */
    fun batteryFill(percent: Int): Float = percent.coerceIn(0, 100) / 100f

    /** "12 Go libres", "1,5 Go libres", "512 Mo libres" / "12 GB free", "1.5 GB free", "512 MB free". */
    fun freeSpace(bytes: Long, lang: Lang): String {
        val gib = bytes / (1024.0 * 1024 * 1024)
        val point = if (lang == Lang.FR) ',' else '.'
        val size = when {
            gib >= 10 -> Strings.get(S.SIZE_GB, lang, "value" to Math.round(gib))
            gib >= 1 -> Strings.get(
                S.SIZE_GB, lang,
                "value" to String.format(Locale.ROOT, "%.1f", gib).replace('.', point).removeSuffix("${point}0"),
            )
            else -> Strings.get(S.SIZE_MB, lang, "value" to Math.round(bytes / (1024.0 * 1024)))
        }
        return Strings.get(S.FREE_SPACE, lang, "size" to size)
    }

    fun notice(code: String, lang: Lang): String = Strings.get(
        when (code) {
            "usb_busy" -> S.NOTICE_USB_BUSY
            "usb_failed" -> S.NOTICE_USB_FAILED
            "radio_denied" -> S.NOTICE_RADIO_DENIED
            "claude_not_running" -> S.NOTICE_CLAUDE_NOT_RUNNING
            else -> S.NOTICE_DEFAULT
        },
        lang,
    )
}
