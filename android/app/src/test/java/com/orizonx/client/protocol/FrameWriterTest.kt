package com.orizonx.client.protocol

import org.json.JSONObject
import org.junit.Assert.assertEquals
import org.junit.Test

class FrameWriterTest {
    @Test
    fun statsFieldsAreClampedToTheirWireRange() {
        val bytes = FrameWriter.encode(
            TabletMessage.Stats(fps = 70_000, latencyAvgUs = -5, latencyMaxUs = 1L shl 40, dropped = 3, rttUs = 0),
        )
        assertEquals("8400000000000012" + "ffff" + "00000000" + "ffffffff" + "00000003" + "00000000", bytes.toHex())
    }

    @Test
    fun inputFieldsAreClampedToTheirWireRange() {
        val bytes = FrameWriter.encode(
            TabletMessage.Input(Protocol.DEVICE_PEN, listOf(InputContact(0, 7, -1, 70_000, 2_000_000, -200, 200))),
        )
        assertEquals("850000000000000c" + "0201" + "0007" + "0000" + "ffff" + "ffff" + "a6" + "5a", bytes.toHex())
    }

    @Test
    fun inputContactCountIsCapped() {
        val pen = FrameWriter.encode(
            TabletMessage.Input(Protocol.DEVICE_PEN, listOf(InputContact(0, 2, 0, 0), InputContact(1, 2, 0, 0))),
        )
        assertEquals("01", pen.toHex().substring(18, 20)) // count = 1
        val fingers = (0 until 12).map { InputContact(it, 3, 0, 0) }
        val touch = FrameWriter.encode(TabletMessage.Input(Protocol.DEVICE_TOUCH, fingers))
        assertEquals(8 + 2 + 10 * Protocol.MAX_TOUCH_CONTACTS, touch.size)
    }

    @Test
    fun deviceInfoIsCompactJsonInFixedKeyOrder() {
        val bytes = FrameWriter.encode(TabletMessage.DeviceInfo("screen", "tablet", "Tab \"S9\" é", "0.5.0"))
        val json = """{"role":"screen","kind":"tablet","name":"Tab \"S9\" é","app":"0.5.0"}"""
        assertEquals(0x86, bytes[0].toInt() and 0xFF)
        assertEquals(json.toByteArray(Charsets.UTF_8).size, bytes.size - 8)
        assertEquals(json, String(bytes, 8, bytes.size - 8, Charsets.UTF_8))
    }

    @Test
    fun deviceInfoWithVideoAppendsItAfterAppInFixedOrder() {
        val bytes = FrameWriter.encode(
            TabletMessage.DeviceInfo("screen", "tablet", "Tab", "0.6.0", VideoCaps(2104, 1312, 60)),
        )
        val json = """{"role":"screen","kind":"tablet","name":"Tab","app":"0.6.0","video":{"width":2104,"height":1312,"fps":60}}"""
        assertEquals(json, String(bytes, 8, bytes.size - 8, Charsets.UTF_8))
    }

    @Test
    fun writerDeviceInfoCarriesVideo() {
        val sink = java.io.ByteArrayOutputStream()
        FrameWriter(sink).deviceInfo("screen", "tablet", "Tab", "0.6.0", VideoCaps(1920, 1200, 30))
        val expected = FrameWriter.encode(TabletMessage.DeviceInfo("screen", "tablet", "Tab", "0.6.0", VideoCaps(1920, 1200, 30)))
        assertEquals(expected.toHex(), sink.toByteArray().toHex())
    }

    @Test
    fun writerHelpersSendDeviceInfoAndAction() {
        val sink = java.io.ByteArrayOutputStream()
        val writer = FrameWriter(sink)
        writer.deviceInfo("actions", "phone", "Pixel 8", "0.5.0")
        writer.action(JSONObject().put("id", "wifi.set").put("value", true))
        val expected = FrameWriter.encode(TabletMessage.DeviceInfo("actions", "phone", "Pixel 8", "0.5.0")) +
            FrameWriter.encode(TabletMessage.Action(JSONObject().put("id", "wifi.set").put("value", true)))
        assertEquals(expected.toHex(), sink.toByteArray().toHex())
    }

    @Test
    fun actionPutsIdFirstThenSortedKeysWhateverTheInsertionOrder() {
        val a = JSONObject().put("value", 0.5).put("zeta", 1).put("id", "x.y").put("alpha", "é")
        val b = JSONObject().put("id", "x.y").put("alpha", "é").put("zeta", 1).put("value", 0.5)
        val bytesA = FrameWriter.encode(TabletMessage.Action(a))
        assertEquals(bytesA.toHex(), FrameWriter.encode(TabletMessage.Action(b)).toHex())
        assertEquals(
            """{"id":"x.y","alpha":"é","value":0.5,"zeta":1}""",
            String(bytesA, 8, bytesA.size - 8, Charsets.UTF_8),
        )
        assertEquals(0x87, bytesA[0].toInt() and 0xFF)
    }

    @Test(expected = IllegalArgumentException::class)
    fun actionWithoutStringIdIsRejected() {
        FrameWriter.encode(TabletMessage.Action(JSONObject().put("id", 3)))
    }

    @Test(expected = IllegalArgumentException::class)
    fun actionOverSixtyFourKibIsRejected() {
        FrameWriter.encode(TabletMessage.Action(JSONObject().put("id", "x").put("pad", "a".repeat(Protocol.MAX_JSON))))
    }

    @Test(expected = IllegalArgumentException::class)
    fun deviceInfoOverSixtyFourKibIsRejected() {
        FrameWriter.encode(TabletMessage.DeviceInfo("screen", "tablet", "a".repeat(Protocol.MAX_JSON), "1"))
    }
}
