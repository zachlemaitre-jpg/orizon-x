package com.orizonx.client.protocol

import org.junit.Assert.assertArrayEquals
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
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

    private fun jsonFrame(type: Int, payload: ByteArray): String =
        "%02x000000%08x".format(type, payload.size) + payload.toHex()

    private fun jsonFrame(type: Int, text: String): String = jsonFrame(type, text.toByteArray(Charsets.UTF_8))

    @Test
    fun decodesActionsStateAsJson() {
        val message = read(jsonFrame(Protocol.TYPE_ACTIONS_STATE, """{"v":1,"wifi":{"ssid":"Café"}}""")) as ActionsStateMessage
        assertEquals(1, message.json.getInt("v"))
        assertEquals("Café", message.json.getJSONObject("wifi").getString("ssid"))
    }

    @Test
    fun actionsStateIsFollowedByNextMessage() {
        val reader = FrameReader(ByteArrayInputStream(hex(jsonFrame(Protocol.TYPE_ACTIONS_STATE, """{"v":1}""") + pongHex)))
        assertTrue(reader.read() is ActionsStateMessage)
        assertEquals(PcMessage.Pong(123456789, 987654321), reader.read())
    }

    @Test(expected = ProtocolException::class)
    fun rejectsInvalidActionsStateJson() {
        read(jsonFrame(Protocol.TYPE_ACTIONS_STATE, "{not json"))
    }

    @Test(expected = ProtocolException::class)
    fun rejectsEmptyActionsState() {
        read(jsonFrame(Protocol.TYPE_ACTIONS_STATE, ""))
    }

    @Test(expected = ProtocolException::class)
    fun rejectsActionsStateThatIsNotAnObject() {
        read(jsonFrame(Protocol.TYPE_ACTIONS_STATE, "[1,2]"))
    }

    @Test(expected = ProtocolException::class)
    fun rejectsActionsStateWithInvalidUtf8() {
        read(jsonFrame(Protocol.TYPE_ACTIONS_STATE, byteArrayOf('{'.code.toByte(), '"'.code.toByte(), 0xFF.toByte(), '"'.code.toByte(), '}'.code.toByte())))
    }

    @Test(expected = ProtocolException::class)
    fun rejectsActionsStateOverSixtyFourKib() {
        val big = """{"v":1,"pad":"${"x".repeat(Protocol.MAX_JSON)}"}"""
        read(jsonFrame(Protocol.TYPE_ACTIONS_STATE, big))
    }

    @Test
    fun acceptsActionsStateOfExactlySixtyFourKib() {
        val head = """{"pad":""""
        val tail = """"}"""
        val text = head + "x".repeat(Protocol.MAX_JSON - head.length - tail.length) + tail
        assertEquals(Protocol.MAX_JSON, text.length)
        assertTrue(read(jsonFrame(Protocol.TYPE_ACTIONS_STATE, text)) is ActionsStateMessage)
    }

    // --- MEDIA_ARTWORK (0x05) ---

    private val artworkId = "0123456789abcdef0123456789abcdef01234567"

    private fun artworkPayload(id: String, image: ByteArray): ByteArray =
        byteArrayOf(id.length.toByte()) + id.toByteArray(Charsets.US_ASCII) + image

    @Test
    fun decodesMediaArtwork() {
        val image = byteArrayOf(1, 2, 3, 0xFF.toByte())
        val message = read(jsonFrame(Protocol.TYPE_MEDIA_ARTWORK, artworkPayload(artworkId, image))) as MediaArtworkMessage
        assertEquals(artworkId, message.id)
        assertArrayEquals(image, message.bytes)
    }

    @Test
    fun mediaArtworkIsFollowedByNextMessage() {
        val frame = jsonFrame(Protocol.TYPE_MEDIA_ARTWORK, artworkPayload(artworkId, byteArrayOf(9, 9)))
        val reader = FrameReader(ByteArrayInputStream(hex(frame + pongHex)))
        assertTrue(reader.read() is MediaArtworkMessage)
        assertEquals(PcMessage.Pong(123456789, 987654321), reader.read())
    }

    @Test
    fun acceptsMediaArtworkOfExactlyMaxArtwork() {
        val image = ByteArray(Protocol.MAX_ARTWORK - 1 - artworkId.length) { 7 }
        val message = read(jsonFrame(Protocol.TYPE_MEDIA_ARTWORK, artworkPayload(artworkId, image))) as MediaArtworkMessage
        assertEquals(image.size, message.bytes.size)
    }

    @Test(expected = ProtocolException::class)
    fun rejectsMediaArtworkOverMaxArtwork() {
        val image = ByteArray(Protocol.MAX_ARTWORK - artworkId.length) { 7 } // payload = MAX_ARTWORK + 1
        read(jsonFrame(Protocol.TYPE_MEDIA_ARTWORK, artworkPayload(artworkId, image)))
    }

    @Test(expected = ProtocolException::class)
    fun rejectsMediaArtworkWithEmptyPayload() {
        read(jsonFrame(Protocol.TYPE_MEDIA_ARTWORK, ByteArray(0)))
    }

    @Test(expected = ProtocolException::class)
    fun rejectsMediaArtworkWithZeroIdLength() {
        read(jsonFrame(Protocol.TYPE_MEDIA_ARTWORK, byteArrayOf(0, 1, 2, 3)))
    }

    @Test(expected = ProtocolException::class)
    fun rejectsMediaArtworkWhoseIdOverrunsThePayload() {
        read(jsonFrame(Protocol.TYPE_MEDIA_ARTWORK, byteArrayOf(40) + "abc".toByteArray() + byteArrayOf(1)))
    }

    @Test(expected = ProtocolException::class)
    fun rejectsMediaArtworkWithoutImageBytes() {
        read(jsonFrame(Protocol.TYPE_MEDIA_ARTWORK, artworkPayload(artworkId, ByteArray(0))))
    }

    @Test(expected = ProtocolException::class)
    fun rejectsMediaArtworkWithNonAsciiId() {
        read(jsonFrame(Protocol.TYPE_MEDIA_ARTWORK, byteArrayOf(2, 0xC3.toByte(), 0xA9.toByte(), 1, 2)))
    }
}
