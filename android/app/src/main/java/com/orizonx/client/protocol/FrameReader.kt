package com.orizonx.client.protocol

import java.io.BufferedInputStream
import java.io.DataInputStream
import java.io.InputStream

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
                else -> skip(size)
            }
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
