package com.orizonx.client.actions

import java.time.LocalDateTime
import java.time.ZoneOffset
import java.util.Locale

/** How alarming the battery pictogram should look. */
enum class BatteryLevel { NORMAL, LOW, CRITICAL }

/** French display strings for the Actions screen. Pure, so they are unit-tested. */
object ActionsFormat {
    private val DAYS = listOf("Lundi", "Mardi", "Mercredi", "Jeudi", "Vendredi", "Samedi", "Dimanche")
    private val MONTHS = listOf(
        "janvier", "février", "mars", "avril", "mai", "juin",
        "juillet", "août", "septembre", "octobre", "novembre", "décembre",
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

    /** "Samedi 11 octobre" */
    fun date(epochMs: Long, utcOffsetMin: Int): String {
        val t = local(epochMs, utcOffsetMin)
        return "${DAYS[t.dayOfWeek.value - 1]} ${t.dayOfMonth} ${MONTHS[t.monthValue - 1]}"
    }

    /** "PC 76 % · en charge" */
    fun battery(b: BatteryState): String = "PC ${b.percent} %" + if (b.charging) " · en charge" else ""

    /** Green above 20 %, amber at 20 % or less, red at 10 % or less. */
    fun batteryLevel(percent: Int): BatteryLevel = when {
        percent <= 10 -> BatteryLevel.CRITICAL
        percent <= 20 -> BatteryLevel.LOW
        else -> BatteryLevel.NORMAL
    }

    /** Filled share of the battery body, 0..1. */
    fun batteryFill(percent: Int): Float = percent.coerceIn(0, 100) / 100f

    /** "12 Go libres", "1,5 Go libres", "512 Mo libres". */
    fun freeSpace(bytes: Long): String {
        val gib = bytes / (1024.0 * 1024 * 1024)
        val body = when {
            gib >= 10 -> "${Math.round(gib)} Go"
            gib >= 1 -> String.format(Locale.ROOT, "%.1f", gib).replace('.', ',').removeSuffix(",0") + " Go"
            else -> "${Math.round(bytes / (1024.0 * 1024))} Mo"
        }
        return "$body libres"
    }

    fun notice(code: String): String = when (code) {
        "usb_busy" -> "La clé est utilisée, ferme les fichiers ouverts"
        "usb_failed" -> "Impossible d'éjecter la clé"
        "radio_denied" -> "Windows refuse de changer cette radio"
        else -> "Action impossible"
    }
}
