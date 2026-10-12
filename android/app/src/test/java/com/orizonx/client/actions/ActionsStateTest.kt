package com.orizonx.client.actions

import org.json.JSONObject
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

class ActionsStateTest {
    private val full = """
        {"v":1,
         "clock":{"epoch_ms":1760185920000,"utc_offset_min":120},
         "battery":{"available":true,"percent":76,"charging":true},
         "audio":{"available":true,"volume":0.42,"muted":false},
         "media":{"available":true},
         "brightness":{"available":true,"value":0.70},
         "wifi":{"available":true,"on":true,"ssid":"Maison"},
         "bluetooth":{"available":true,"on":true,"connected":["Casque","Souris"]},
         "airplane":{"available":true,"on":false},
         "usb":[{"drive":"E:","label":"KINGSTON","free_bytes":12884901888,"total_bytes":31914983424}],
         "notice":{"code":"usb_busy","drive":"E:"}}
    """.trimIndent()

    private fun parse(text: String) = ActionsState.parse(JSONObject(text))

    @Test
    fun fullStateIsParsed() {
        val s = parse(full)
        assertEquals(ClockState(1760185920000L, 120), s.clock)
        assertEquals(BatteryState(76, true), s.battery)
        assertEquals(AudioState(0.42f, false), s.audio)
        assertTrue(s.mediaAvailable)
        assertEquals(BrightnessState(0.70f), s.brightness)
        assertEquals(WifiState(true, "Maison"), s.wifi)
        assertEquals(BluetoothState(true, listOf("Casque", "Souris")), s.bluetooth)
        assertEquals(AirplaneState(false), s.airplane)
        assertEquals(listOf(UsbDrive("E:", "KINGSTON", 12884901888L, 31914983424L)), s.usb)
        assertEquals(Notice("usb_busy", "E:"), s.notice)
    }

    @Test
    fun emptyObjectGivesAnEmptyState() {
        assertEquals(ActionsState(), parse("{}"))
    }

    @Test
    fun unavailableSectionsAreNull() {
        val s = parse(
            """{"battery":{"available":false},"audio":{"available":false,"volume":0.5},"media":{"available":false},
               "brightness":{"available":false},"wifi":{"available":false,"on":true},
               "bluetooth":{"available":false},"airplane":{"available":false}}""",
        )
        assertNull(s.battery)
        assertNull(s.audio)
        assertFalse(s.mediaAvailable)
        assertNull(s.brightness)
        assertNull(s.wifi)
        assertNull(s.bluetooth)
        assertNull(s.airplane)
    }

    @Test
    fun sectionWithoutAvailableFlagIsHidden() {
        assertNull(parse("""{"audio":{"volume":0.5,"muted":false}}""").audio)
    }

    @Test
    fun missingMandatoryFieldsHideTheSection() {
        val s = parse(
            """{"clock":{"utc_offset_min":60},"battery":{"available":true,"charging":true},
               "audio":{"available":true,"muted":true},"brightness":{"available":true}}""",
        )
        assertNull(s.clock)
        assertNull(s.battery)
        assertNull(s.audio)
        assertNull(s.brightness)
    }

    @Test
    fun optionalFieldsDefault() {
        val s = parse(
            """{"clock":{"epoch_ms":5},"wifi":{"available":true},"bluetooth":{"available":true,"on":true},
               "audio":{"available":true,"volume":0.1}}""",
        )
        assertEquals(ClockState(5L, 0), s.clock)
        assertEquals(WifiState(false, null), s.wifi)
        assertEquals(BluetoothState(true, emptyList()), s.bluetooth)
        assertEquals(AudioState(0.1f, false), s.audio)
    }

    @Test
    fun valuesAreClampedAndInvalidOnesIgnored() {
        val s = parse(
            """{"audio":{"available":true,"volume":3.5},"brightness":{"available":true,"value":-1},
               "battery":{"available":true,"percent":255,"charging":false}}""",
        )
        assertEquals(1f, s.audio!!.volume, 0f)
        assertEquals(0f, s.brightness!!.value, 0f)
        assertNull(s.battery) // 255 = unknown on Windows
    }

    @Test
    fun nullAndBlankSsidMeansNoSsid() {
        assertNull(parse("""{"wifi":{"available":true,"on":true,"ssid":null}}""").wifi!!.ssid)
        assertNull(parse("""{"wifi":{"available":true,"on":true,"ssid":""}}""").wifi!!.ssid)
    }

    @Test
    fun wrongTypesDoNotThrow() {
        val s = parse("""{"clock":5,"battery":"x","usb":{"a":1},"notice":[],"bluetooth":{"available":true,"connected":"Casque"}}""")
        assertNull(s.clock)
        assertNull(s.battery)
        assertTrue(s.usb.isEmpty())
        assertNull(s.notice)
        assertEquals(emptyList<String>(), s.bluetooth!!.connected)
    }

    @Test
    fun usbListKeepsOrderAndSkipsEntriesWithoutDrive() {
        val s = parse(
            """{"usb":[{"drive":"E:","label":"A","free_bytes":1,"total_bytes":2},
                        {"label":"no letter"},
                        42,
                        {"drive":"F:"}]}""",
        )
        assertEquals(listOf(UsbDrive("E:", "A", 1L, 2L), UsbDrive("F:", "", null, null)), s.usb)
    }

    @Test
    fun emptyUsbList() {
        assertTrue(parse("""{"usb":[]}""").usb.isEmpty())
    }

    @Test
    fun noticeWithoutDriveAndWithoutCode() {
        assertEquals(Notice("action_failed", null), parse("""{"notice":{"code":"action_failed"}}""").notice)
        assertNull(parse("""{"notice":{"drive":"E:"}}""").notice)
    }

    @Test
    fun nowPlayingIsParsed() {
        val s = parse(
            """{"now_playing":{"available":true,"app":"Spotify","title":"Song","artist":"Artist","album":"Album",
               "playing":true,"artwork":"0123456789abcdef0123456789abcdef01234567"}}""",
        )
        assertEquals(
            NowPlaying("Spotify", "Song", "Artist", "Album", true, "0123456789abcdef0123456789abcdef01234567"),
            s.nowPlaying,
        )
    }

    @Test
    fun nowPlayingWithoutArtworkOrOptionalTexts() {
        assertEquals(
            NowPlaying("Chrome", "Video", "", "", false, null),
            parse("""{"now_playing":{"available":true,"app":"Chrome","title":"Video","artwork":null}}""").nowPlaying,
        )
        assertNull(parse("""{"now_playing":{"available":true,"artwork":""}}""").nowPlaying!!.artworkId)
    }

    @Test
    fun nowPlayingIsNullWhenAbsentOrUnavailable() {
        assertNull(parse("{}").nowPlaying)
        assertNull(parse("""{"now_playing":{"available":false,"title":"x","playing":true}}""").nowPlaying)
        assertNull(parse("""{"now_playing":{"title":"x"}}""").nowPlaying)
        assertNull(parse("""{"now_playing":"x"}""").nowPlaying)
        assertNull(parse("""{"now_playing":null}""").nowPlaying)
    }

    @Test
    fun nowPlayingNullTextsBecomeEmpty() {
        val n = parse("""{"now_playing":{"available":true,"app":null,"title":null,"artist":null,"album":null}}""").nowPlaying!!
        assertEquals(NowPlaying("", "", "", "", false, null), n)
    }

    @Test
    fun wifiSignalIsParsedClampedAndTolerant() {
        fun signal(raw: String) = parse("""{"wifi":{"available":true,"on":true,"signal":$raw}}""").wifi!!.signal
        assertEquals(72, signal("72"))
        assertEquals(0, signal("0"))
        assertEquals(100, signal("250"))
        assertEquals(0, signal("-5"))
        assertEquals(58, signal("57.6"))
        assertEquals(40, signal("\"40\""))
        assertNull(signal("null"))
        assertNull(signal("\"strong\""))
        assertNull(signal("true"))
        assertNull(signal("[]"))
        assertNull(parse("""{"wifi":{"available":true,"on":true}}""").wifi!!.signal)
    }

    @Test
    fun usbKindDefaultsToStick() {
        val s = parse(
            """{"usb":[{"drive":"E:","kind":"stick"},{"drive":"F:","kind":"disk"},{"drive":"G:"},
                        {"drive":"H:","kind":"weird"},{"drive":"I:","kind":null},{"drive":"J:","kind":5},
                        {"drive":"K:","kind":"DISK"}]}""",
        )
        assertEquals(
            listOf(UsbKind.STICK, UsbKind.DISK, UsbKind.STICK, UsbKind.STICK, UsbKind.STICK, UsbKind.STICK, UsbKind.DISK),
            s.usb.map { it.kind },
        )
    }
}
