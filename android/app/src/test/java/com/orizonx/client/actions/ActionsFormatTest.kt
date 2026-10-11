package com.orizonx.client.actions

import org.junit.Assert.assertEquals
import org.junit.Test

class ActionsFormatTest {
    private val saturday = 1760185920000L // 2025-10-11 12:32:00 UTC

    @Test
    fun clockIsShownInThePcZone() {
        assertEquals("14:32", ActionsFormat.hoursMinutes(saturday, 120))
        assertEquals("12:32", ActionsFormat.hoursMinutes(saturday, 0))
        assertEquals("05", ActionsFormat.seconds(saturday + 5_000, 120))
    }

    @Test
    fun dateIsInFrench() {
        assertEquals("Samedi 11 octobre", ActionsFormat.date(saturday, 120))
    }

    @Test
    fun offsetCanCrossMidnight() {
        // 23:00 UTC Saturday is already Sunday 01:00 at +120.
        val lateSaturday = saturday + (10 * 60 + 28) * 60_000L
        assertEquals("Dimanche 12 octobre", ActionsFormat.date(lateSaturday, 120))
        assertEquals("Samedi 11 octobre", ActionsFormat.date(lateSaturday, 0))
        assertEquals("01:00", ActionsFormat.hoursMinutes(lateSaturday, 120))
    }

    @Test
    fun negativeOffsets() {
        assertEquals("07:32", ActionsFormat.hoursMinutes(saturday, -300))
    }

    @Test
    fun accentedMonths() {
        // 2025-12-25 and 2025-08-15 (UTC noon)
        assertEquals("Jeudi 25 décembre", ActionsFormat.date(1766664000000L, 0))
        assertEquals("Vendredi 15 août", ActionsFormat.date(1755259200000L, 0))
    }

    @Test
    fun batteryLine() {
        assertEquals("PC 76 % · en charge", ActionsFormat.battery(BatteryState(76, true)))
        assertEquals("PC 40 %", ActionsFormat.battery(BatteryState(40, false)))
    }

    @Test
    fun freeSpace() {
        assertEquals("12 Go libres", ActionsFormat.freeSpace(12884901888L))
        assertEquals("1,5 Go libres", ActionsFormat.freeSpace(1610612736L))
        assertEquals("2 Go libres", ActionsFormat.freeSpace(2147483648L))
        assertEquals("512 Mo libres", ActionsFormat.freeSpace(536870912L))
        assertEquals("0 Mo libres", ActionsFormat.freeSpace(0))
    }

    @Test
    fun noticeTexts() {
        assertEquals("La clé est utilisée, ferme les fichiers ouverts", ActionsFormat.notice("usb_busy"))
        assertEquals("Impossible d'éjecter la clé", ActionsFormat.notice("usb_failed"))
        assertEquals("Windows refuse de changer cette radio", ActionsFormat.notice("radio_denied"))
        assertEquals("Action impossible", ActionsFormat.notice("action_failed"))
        assertEquals("Action impossible", ActionsFormat.notice("something_new"))
    }
}
