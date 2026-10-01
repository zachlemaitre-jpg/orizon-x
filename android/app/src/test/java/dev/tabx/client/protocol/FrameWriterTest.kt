package dev.tabx.client.protocol

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
}
