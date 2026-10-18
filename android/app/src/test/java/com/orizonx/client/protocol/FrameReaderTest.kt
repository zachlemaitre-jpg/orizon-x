package com.orizonx.client.protocol

import org.junit.Assert.assertArrayEquals
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Assert.fail
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

    // --- FRAME_STATE (0x06) ---

    private fun stateJson(
        epoch: String = "3",
        status: String = "\"ok\"",
        folder: String = "\"Photos\"",
        interval: String = "30",
        fit: String = "\"crop\"",
        paused: String = "false",
    ) = """{"epoch":$epoch,"status":$status,"folder":$folder,"interval_s":$interval,"fit":$fit,"paused":$paused}"""

    private fun readState(json: String) = read(jsonFrame(Protocol.TYPE_FRAME_STATE, json)) as PcMessage.FrameState

    @Test
    fun decodesFrameState() {
        assertEquals(PcMessage.FrameState(3, "ok", "Photos", 30, "crop", false), readState(stateJson()))
    }

    @Test
    fun decodesFrameStateWithNoFolderAndAccents() {
        assertEquals(
            PcMessage.FrameState(0xFFFF_FFFFL, "no_folder", null, 5, "fit", true),
            readState(stateJson(epoch = "4294967295", status = "\"no_folder\"", folder = "null", interval = "5", fit = "\"fit\"", paused = "true")),
        )
        assertEquals("Été", readState(stateJson(folder = "\"Été\"")).folder)
    }

    @Test
    fun frameStateIgnoresUnknownFields() {
        val json = stateJson().dropLast(1) + ""","future":{"a":[1]}}"""
        assertEquals(PcMessage.FrameState(3, "ok", "Photos", 30, "crop", false), readState(json))
    }

    @Test
    fun frameStateKnowsEveryStatusAndMapsAnUnknownOneToUnreadable() {
        for (status in listOf("ok", "no_folder", "empty", "unreadable")) {
            assertEquals(status, readState(stateJson(status = "\"$status\"")).status)
        }
        for (bad in listOf("\"bogus\"", "\"OK\"", "\"\"", "null", "3", "true")) {
            assertEquals(bad, "unreadable", readState(stateJson(status = bad)).status)
        }
        assertEquals("unreadable", readState("""{"epoch":3,"interval_s":30}""").status)
    }

    @Test
    fun frameStateIsTolerantForFolderFitAndPaused() {
        assertEquals(null, readState(stateJson(folder = "3")).folder)
        assertEquals("crop", readState(stateJson(fit = "\"stretch\"")).fit)
        assertEquals("crop", readState(stateJson(fit = "null")).fit)
        assertEquals(false, readState(stateJson(paused = "\"yes\"")).paused)
        assertEquals(false, readState(stateJson(paused = "1")).paused)
    }

    @Test
    fun frameStateIsFollowedByNextMessage() {
        val reader = FrameReader(ByteArrayInputStream(hex(jsonFrame(Protocol.TYPE_FRAME_STATE, stateJson()) + pongHex)))
        assertTrue(reader.read() is PcMessage.FrameState)
        assertEquals(PcMessage.Pong(123456789, 987654321), reader.read())
    }

    @Test
    fun rejectsFrameStateWithInvalidEpochOrInterval() {
        for (epoch in listOf("-1", "4294967296", "1.5", "\"3\"", "null", "true")) {
            try {
                readState(stateJson(epoch = epoch))
                fail("epoch $epoch accepted")
            } catch (_: ProtocolException) {
            }
        }
        for (interval in listOf("0", "-5", "2.5", "\"30\"", "null", "true")) {
            try {
                readState(stateJson(interval = interval))
                fail("interval_s $interval accepted")
            } catch (_: ProtocolException) {
            }
        }
        try {
            readState("""{"status":"ok","interval_s":30}""")
            fail("missing epoch accepted")
        } catch (_: ProtocolException) {
        }
    }

    @Test
    fun rejectsMalformedFrameState() {
        for (payload in listOf("", "{not json", "[1,2]", "\"ok\"")) {
            try {
                read(jsonFrame(Protocol.TYPE_FRAME_STATE, payload))
                fail("payload $payload accepted")
            } catch (_: ProtocolException) {
            }
        }
    }

    @Test(expected = ProtocolException::class)
    fun rejectsFrameStateWithInvalidUtf8() {
        read(jsonFrame(Protocol.TYPE_FRAME_STATE, byteArrayOf('{'.code.toByte(), '"'.code.toByte(), 0xFF.toByte(), '"'.code.toByte(), '}'.code.toByte())))
    }

    @Test(expected = ProtocolException::class)
    fun rejectsFrameStateOverSixtyFourKib() {
        read(jsonFrame(Protocol.TYPE_FRAME_STATE, stateJson(folder = "\"${"x".repeat(Protocol.MAX_JSON)}\"")))
    }

    // --- FRAME_FILE (0x07) ---

    private fun filePayload(
        epoch: Long = 3, id: Long = 7, kind: Int = 1, total: Long = 10, offset: Long = 0, data: ByteArray = byteArrayOf(1, 2, 3, 4, 5),
    ): ByteArray = java.nio.ByteBuffer.allocate(25 + data.size)
        .putInt(epoch.toInt()).putInt(id.toInt()).put(kind.toByte()).putLong(total).putLong(offset).put(data).array()

    private fun readFile(payload: ByteArray) = read(jsonFrame(Protocol.TYPE_FRAME_FILE, payload)) as PcMessage.FrameFile

    private fun assertFileRejected(label: String, payload: ByteArray) {
        try {
            read(jsonFrame(Protocol.TYPE_FRAME_FILE, payload))
            fail("$label accepted")
        } catch (_: ProtocolException) {
        }
    }

    @Test
    fun decodesFrameFile() {
        val message = readFile(filePayload(offset = 5, data = byteArrayOf(6, 7, 8, 9, 10)))
        assertEquals(PcMessage.FrameFile(3, 7, 1, 10, 5, byteArrayOf(6, 7, 8, 9, 10)), message)
        assertEquals(10L, message.total)
    }

    @Test
    fun frameFileReadsUnsignedFields() {
        val message = readFile(filePayload(epoch = 0xFFFF_FFFFL, id = 0x8000_0001L, kind = 2, total = 1, data = byteArrayOf(-1)))
        assertEquals(0xFFFF_FFFFL, message.epoch)
        assertEquals(0x8000_0001L, message.id)
        assertEquals(2, message.kind)
        assertArrayEquals(byteArrayOf(-1), message.data)
    }

    @Test
    fun frameFileIsFollowedByNextMessage() {
        val reader = FrameReader(ByteArrayInputStream(hex(jsonFrame(Protocol.TYPE_FRAME_FILE, filePayload()) + pongHex)))
        assertTrue(reader.read() is PcMessage.FrameFile)
        assertEquals(PcMessage.Pong(123456789, 987654321), reader.read())
    }

    @Test
    fun acceptsFrameFileChunkOfExactlyOneMiB() {
        val data = ByteArray(Protocol.MAX_FRAME_CHUNK) { 7 }
        val message = readFile(filePayload(kind = 2, total = data.size.toLong(), data = data))
        assertEquals(Protocol.MAX_FRAME_CHUNK, message.data.size)
    }

    @Test
    fun acceptsFrameFileChunkEndingExactlyAtTotal() {
        assertEquals(9L, readFile(filePayload(total = 10, offset = 9, data = byteArrayOf(1))).offset)
    }

    @Test
    fun rejectsFrameFileOverOneMiB() {
        val data = ByteArray(Protocol.MAX_FRAME_CHUNK + 1)
        assertFileRejected("1 MiB + 1", filePayload(total = 2L * Protocol.MAX_FRAME_CHUNK, data = data))
    }

    @Test
    fun rejectsFrameFileWithoutData() {
        assertFileRejected("empty data", filePayload(data = ByteArray(0)))
        assertFileRejected("short header", filePayload().copyOf(24))
        assertFileRejected("empty payload", ByteArray(0))
    }

    @Test
    fun rejectsFrameFileWithUnknownKind() {
        for (kind in listOf(0, 3, 255)) assertFileRejected("kind $kind", filePayload(kind = kind))
    }

    @Test
    fun rejectsFrameFileRunningPastTotal() {
        assertFileRejected("past total", filePayload(total = 10, offset = 6, data = ByteArray(5)))
        assertFileRejected("shorter total", filePayload(total = 4, offset = 0, data = ByteArray(5)))
        assertFileRejected("at total", filePayload(total = 10, offset = 10, data = ByteArray(1)))
        assertFileRejected("zero total", filePayload(total = 0, offset = 0, data = ByteArray(1)))
    }

    @Test
    fun rejectsFrameFileWithNegativeOrHugeOffsetAndTotal() {
        // u64 values with the high bit set read as negative longs: never valid here.
        assertFileRejected("huge total", filePayload(total = Long.MIN_VALUE, offset = 0))
        assertFileRejected("huge offset", filePayload(total = Long.MAX_VALUE, offset = Long.MIN_VALUE))
        assertFileRejected("overflowing offset", filePayload(total = Long.MAX_VALUE, offset = Long.MAX_VALUE))
    }
}
