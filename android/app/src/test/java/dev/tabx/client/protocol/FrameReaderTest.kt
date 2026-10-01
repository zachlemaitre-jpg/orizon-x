package dev.tabx.client.protocol

import org.junit.Assert.assertEquals
import org.junit.Test
import java.io.ByteArrayInputStream
import java.io.EOFException

class FrameReaderTest {
    private val pongHex = "030000000000001000000000075bcd15000000003ade68b1"

    private fun read(hexText: String) = FrameReader(ByteArrayInputStream(hex(hexText))).read()

    @Test
    fun skipsUnknownTypes() {
        assertEquals(PcMessage.Pong(123456789, 987654321), read("9900000000000003" + "010203" + pongHex))
    }

    @Test(expected = ProtocolException::class)
    fun rejectsOversizedPayload() {
        read("0200000001000001")
    }

    @Test(expected = EOFException::class)
    fun truncatedStreamThrowsEof() {
        read(pongHex.dropLast(2))
    }

    @Test(expected = ProtocolException::class)
    fun rejectsConfigWithWrongSize() {
        read("0100000000000006" + "010780043800")
    }

    @Test(expected = ProtocolException::class)
    fun rejectsVideoShorterThanTimestamp() {
        read("0200000000000004" + "00000000")
    }
}
