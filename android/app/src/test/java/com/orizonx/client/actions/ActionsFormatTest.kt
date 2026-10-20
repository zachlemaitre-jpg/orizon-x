package com.orizonx.client.actions

import com.orizonx.client.i18n.Lang
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
        assertEquals("Samedi 11 octobre", ActionsFormat.date(saturday, 120, Lang.FR))
    }

    @Test
    fun dateIsInEnglish() {
        assertEquals("Saturday, October 11", ActionsFormat.date(saturday, 120, Lang.EN))
        assertEquals("Thursday, December 25", ActionsFormat.date(1766664000000L, 0, Lang.EN))
    }

    @Test
    fun offsetCanCrossMidnight() {
        // 23:00 UTC Saturday is already Sunday 01:00 at +120.
        val lateSaturday = saturday + (10 * 60 + 28) * 60_000L
        assertEquals("Dimanche 12 octobre", ActionsFormat.date(lateSaturday, 120, Lang.FR))
        assertEquals("Samedi 11 octobre", ActionsFormat.date(lateSaturday, 0, Lang.FR))
        assertEquals("Sunday, October 12", ActionsFormat.date(lateSaturday, 120, Lang.EN))
        assertEquals("01:00", ActionsFormat.hoursMinutes(lateSaturday, 120))
    }

    @Test
    fun negativeOffsets() {
        assertEquals("07:32", ActionsFormat.hoursMinutes(saturday, -300))
    }

    @Test
    fun accentedMonths() {
        // 2025-12-25 and 2025-08-15 (UTC noon)
        assertEquals("Jeudi 25 décembre", ActionsFormat.date(1766664000000L, 0, Lang.FR))
        assertEquals("Vendredi 15 août", ActionsFormat.date(1755259200000L, 0, Lang.FR))
    }

    @Test
    fun batteryLine() {
        assertEquals("PC 76 % · en charge", ActionsFormat.battery(BatteryState(76, true), Lang.FR))
        assertEquals("PC 40 %", ActionsFormat.battery(BatteryState(40, false), Lang.FR))
        assertEquals("PC 76% · charging", ActionsFormat.battery(BatteryState(76, true), Lang.EN))
        assertEquals("PC 40%", ActionsFormat.battery(BatteryState(40, false), Lang.EN))
    }

    @Test
    fun freeSpace() {
        assertEquals("12 Go libres", ActionsFormat.freeSpace(12884901888L, Lang.FR))
        assertEquals("1,5 Go libres", ActionsFormat.freeSpace(1610612736L, Lang.FR))
        assertEquals("2 Go libres", ActionsFormat.freeSpace(2147483648L, Lang.FR))
        assertEquals("512 Mo libres", ActionsFormat.freeSpace(536870912L, Lang.FR))
        assertEquals("0 Mo libres", ActionsFormat.freeSpace(0, Lang.FR))
    }

    @Test
    fun freeSpaceInEnglishUsesGbMbAndADecimalPoint() {
        assertEquals("12 GB free", ActionsFormat.freeSpace(12884901888L, Lang.EN))
        assertEquals("1.5 GB free", ActionsFormat.freeSpace(1610612736L, Lang.EN))
        assertEquals("2 GB free", ActionsFormat.freeSpace(2147483648L, Lang.EN))
        assertEquals("512 MB free", ActionsFormat.freeSpace(536870912L, Lang.EN))
        assertEquals("0 MB free", ActionsFormat.freeSpace(0, Lang.EN))
    }

    @Test
    fun batteryLevelThresholds() {
        assertEquals(BatteryLevel.NORMAL, ActionsFormat.batteryLevel(100))
        assertEquals(BatteryLevel.NORMAL, ActionsFormat.batteryLevel(21))
        assertEquals(BatteryLevel.LOW, ActionsFormat.batteryLevel(20))
        assertEquals(BatteryLevel.LOW, ActionsFormat.batteryLevel(11))
        assertEquals(BatteryLevel.CRITICAL, ActionsFormat.batteryLevel(10))
        assertEquals(BatteryLevel.CRITICAL, ActionsFormat.batteryLevel(0))
    }

    @Test
    fun batteryFillIsClamped() {
        assertEquals(0.76f, ActionsFormat.batteryFill(76), 0.0001f)
        assertEquals(0f, ActionsFormat.batteryFill(-5), 0f)
        assertEquals(1f, ActionsFormat.batteryFill(140), 0f)
    }

    @Test
    fun noticeTexts() {
        assertEquals("La clé est utilisée, ferme les fichiers ouverts", ActionsFormat.notice("usb_busy", Lang.FR))
        assertEquals("Impossible d'éjecter la clé", ActionsFormat.notice("usb_failed", Lang.FR))
        assertEquals("Windows refuse de changer cette radio", ActionsFormat.notice("radio_denied", Lang.FR))
        assertEquals("Claude n'est pas lancé sur le PC", ActionsFormat.notice("claude_not_running", Lang.FR))
        assertEquals("Introuvable dans l'app Claude", ActionsFormat.notice("claude_ui_not_found", Lang.FR))
        assertEquals("Couldn't find that in the Claude app", ActionsFormat.notice("claude_ui_not_found", Lang.EN))
        assertEquals("Action impossible", ActionsFormat.notice("action_failed", Lang.FR))
        assertEquals("Action impossible", ActionsFormat.notice("something_new", Lang.FR))
    }

    @Test
    fun noticeTextsInEnglish() {
        assertEquals("The drive is in use, close any open files", ActionsFormat.notice("usb_busy", Lang.EN))
        assertEquals("Cannot eject the drive", ActionsFormat.notice("usb_failed", Lang.EN))
        assertEquals("Windows won't change this radio", ActionsFormat.notice("radio_denied", Lang.EN))
        assertEquals("Action failed", ActionsFormat.notice("action_failed", Lang.EN))
        assertEquals("Action failed", ActionsFormat.notice("something_new", Lang.EN))
    }
}
