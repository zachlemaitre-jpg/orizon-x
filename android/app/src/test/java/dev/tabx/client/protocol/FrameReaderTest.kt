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

    @Test(expected = ProtocolException::class)
    fun rejectsLengthWithHighBitSet() {
        read("99000000ffffffff")
    }

    @Test
    fun skipsLargeUnknownPayloadAcrossScratchBuffer() {
        val big = "99000000" + "%08x".format(20_000) + "ab".repeat(20_000)
        assertEquals(PcMessage.Pong(123456789, 987654321), read(big + pongHex))
    }

    @Test
    fun readsConsecutiveMessagesFromOneStream() {
        val reader = FrameReader(ByteArrayInputStream(hex(pongHex + "0100000000000007" + "0107800438003c")))
        assertEquals(PcMessage.Pong(123456789, 987654321), reader.read())
        assertEquals(PcMessage.Config(1, 1920, 1080, 60), reader.read())
    }

    @Test
    fun handlesOneByteReads() {
        val bytes = hex("9900000000000002" + "abcd" + pongHex)
        val trickle = object : java.io.InputStream() {
            private var pos = 0
            override fun read(): Int = if (pos < bytes.size) bytes[pos++].toInt() and 0xFF else -1
            override fun read(b: ByteArray, off: Int, len: Int): Int {
                if (len == 0) return 0
                val c = read()
                if (c < 0) return -1
                b[off] = c.toByte()
                return 1
            }
        }
        assertEquals(PcMessage.Pong(123456789, 987654321), FrameReader(trickle).read())
    }
}
