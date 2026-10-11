package com.orizonx.client.protocol

import java.io.BufferedInputStream
import java.io.DataInputStream
import org.json.JSONException
import org.json.JSONObject
import java.io.InputStream
import java.nio.ByteBuffer
import java.nio.charset.CharacterCodingException
import java.nio.charset.CodingErrorAction

/** Reads PC -> tablet messages. Not thread-safe: use from a single reader thread. */
class FrameReader(input: InputStream) {
    private val stream = DataInputStream(BufferedInputStream(input, 64 * 1024))
    private val scratch = ByteArray(8 * 1024)

    /** Blocks until the next known message; unknown types are skipped. Throws EOFException at end of stream. */
    fun read(): PcMessage {
        while (true) {
            val type = stream.readUnsignedByte()
            val flags = stream.readUnsignedByte()
            stream.readUnsignedShort() // reserved
            val length = stream.readInt().toLong() and 0xFFFF_FFFFL
            if (length > Protocol.MAX_PAYLOAD) throw ProtocolException("payload trop gros : $length octets")
            val size = length.toInt()
            when (type) {
                Protocol.TYPE_CONFIG -> {
                    expectSize("CONFIG", size, 7)
                    return PcMessage.Config(
                        codec = stream.readUnsignedByte(),
                        width = stream.readUnsignedShort(),
                        height = stream.readUnsignedShort(),
                        fps = stream.readUnsignedShort(),
                    )
                }
                Protocol.TYPE_VIDEO -> {
                    if (size < 8) throw ProtocolException("VIDEO trop court : $size octets")
                    val ptsUs = stream.readLong()
                    val data = ByteArray(size - 8)
                    stream.readFully(data)
                    return PcMessage.Video(ptsUs, flags, data)
                }
                Protocol.TYPE_PONG -> {
                    expectSize("PONG", size, 16)
                    return PcMessage.Pong(stream.readLong(), stream.readLong())
                }
                Protocol.TYPE_ACTIONS_STATE -> {
                    if (size > Protocol.MAX_JSON) throw ProtocolException("ACTIONS_STATE trop gros : $size octets")
                    val bytes = ByteArray(size)
                    stream.readFully(bytes)
                    return ActionsStateMessage(parseJsonObject("ACTIONS_STATE", bytes))
                }
                else -> skip(size)
            }
        }
    }

    private fun parseJsonObject(name: String, bytes: ByteArray): JSONObject {
        val text = try {
            Charsets.UTF_8.newDecoder()
                .onMalformedInput(CodingErrorAction.REPORT)
                .onUnmappableCharacter(CodingErrorAction.REPORT)
                .decode(ByteBuffer.wrap(bytes))
                .toString()
        } catch (e: CharacterCodingException) {
            throw ProtocolException("$name : UTF-8 invalide")
        }
        try {
            return JSONObject(text)
        } catch (e: JSONException) {
            throw ProtocolException("$name : JSON invalide (${e.message})")
        }
    }

    private fun skip(size: Int) {
        var remaining = size
        while (remaining > 0) {
            val n = minOf(remaining, scratch.size)
            stream.readFully(scratch, 0, n)
            remaining -= n
        }
    }

    private fun expectSize(name: String, actual: Int, expected: Int) {
        if (actual != expected) throw ProtocolException("$name : $actual octets au lieu de $expected")
    }
}
