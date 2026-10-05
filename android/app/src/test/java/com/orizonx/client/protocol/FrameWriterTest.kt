package com.orizonx.client.protocol

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
}
