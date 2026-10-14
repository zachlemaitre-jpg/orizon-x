package com.orizonx.client

import com.orizonx.client.i18n.Lang
import com.orizonx.client.protocol.FrameWriter
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Test

class DeviceRoleTest {
    @Test
    fun phoneWidthsDefaultToActions() {
        assertEquals(DeviceRole.ACTIONS, DeviceRole.defaultFor(360))
        assertEquals(DeviceRole.ACTIONS, DeviceRole.defaultFor(599))
        assertEquals("phone", DeviceRole.kindFor(599))
    }

    @Test
    fun tabletWidthsDefaultToScreen() {
        assertEquals(DeviceRole.SCREEN, DeviceRole.defaultFor(600))
        assertEquals(DeviceRole.SCREEN, DeviceRole.defaultFor(800))
        assertEquals("tablet", DeviceRole.kindFor(600))
    }

    @Test
    fun wireNamesRoundTrip() {
        assertEquals(DeviceRole.SCREEN, DeviceRole.fromWire("screen"))
        assertEquals(DeviceRole.ACTIONS, DeviceRole.fromWire("actions"))
        assertNull(DeviceRole.fromWire("bogus"))
        assertNull(DeviceRole.fromWire(null))
    }

    @Test
    fun deviceInfoCarriesChosenRoleAndWidthBasedKind() {
        // A phone the user switched to Screen: role follows the choice, kind follows the width.
        val bytes = FrameWriter.encode(deviceInfoFor(DeviceRole.SCREEN, 411, "Pixel 8", "0.1.0"))
        val json = """{"role":"screen","kind":"phone","name":"Pixel 8","app":"0.1.0"}"""
        assertEquals(0x86, bytes[0].toInt() and 0xFF)
        assertEquals(json, String(bytes, 8, bytes.size - 8, Charsets.UTF_8))

        val tablet = FrameWriter.encode(deviceInfoFor(DeviceRole.ACTIONS, 800, "SM-X710", "0.1.0"))
        assertEquals(
            """{"role":"actions","kind":"tablet","name":"SM-X710","app":"0.1.0"}""",
            String(tablet, 8, tablet.size - 8, Charsets.UTF_8),
        )
    }

    @Test
    fun deviceInfoForCarriesVideoOnlyForTheScreenRole() {
        val video = com.orizonx.client.protocol.VideoCaps(2104, 1312, 60)
        assertEquals(video, deviceInfoFor(DeviceRole.SCREEN, 800, "Tab", "0.6.0", video).video)
        assertNull(deviceInfoFor(DeviceRole.ACTIONS, 800, "Tab", "0.6.0", video).video)
        assertNull(deviceInfoFor(DeviceRole.SCREEN, 800, "Tab", "0.6.0").video)
    }

    @Test
    fun deviceInfoForAnnouncesTheEffectiveLanguage() {
        assertEquals("en", deviceInfoFor(DeviceRole.ACTIONS, 411, "Pixel 8", "0.7.0", lang = Lang.EN).lang)
        assertEquals("fr", deviceInfoFor(DeviceRole.SCREEN, 800, "Tab", "0.7.0", lang = Lang.FR).lang)
        val bytes = FrameWriter.encode(deviceInfoFor(DeviceRole.ACTIONS, 411, "Pixel 8", "0.7.0", lang = Lang.FR))
        assertEquals(
            """{"role":"actions","kind":"phone","name":"Pixel 8","app":"0.7.0","lang":"fr"}""",
            String(bytes, 8, bytes.size - 8, Charsets.UTF_8),
        )
    }
}
