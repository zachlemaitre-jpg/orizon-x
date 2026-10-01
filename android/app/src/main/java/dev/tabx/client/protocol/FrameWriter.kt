package dev.tabx.client.protocol

import java.io.BufferedOutputStream
import java.io.ByteArrayOutputStream
import java.io.DataOutputStream
import java.io.OutputStream
import java.nio.ByteBuffer

/** Writes tablet -> PC messages. Thread-safe. */
class FrameWriter(output: OutputStream) {
    private val stream = BufferedOutputStream(output)

    @Synchronized
    fun write(message: TabletMessage) {
        stream.write(encode(message))
        stream.flush()
    }

    companion object {
        private fun u32(value: Long): Int = value.coerceIn(0, 0xFFFF_FFFFL).toInt()

        fun encode(message: TabletMessage): ByteArray {
            val payload = ByteArrayOutputStream()
            val out = DataOutputStream(payload)
            val type = when (message) {
                is TabletMessage.Hello -> {
                    out.write(Protocol.MAGIC)
                    out.writeShort(message.version)
                    out.writeShort(message.width)
                    out.writeShort(message.height)
                    out.writeShort(message.dpi)
                    Protocol.TYPE_HELLO
                }
                is TabletMessage.Ping -> {
                    out.writeLong(message.tTabUs)
                    Protocol.TYPE_PING
                }
                TabletMessage.KeyframeRequest -> Protocol.TYPE_KEYFRAME_REQ
                is TabletMessage.Stats -> {
                    out.writeShort(message.fps.coerceIn(0, 0xFFFF))
                    out.writeInt(u32(message.latencyAvgUs))
                    out.writeInt(u32(message.latencyMaxUs))
                    out.writeInt(u32(message.dropped))
                    out.writeInt(u32(message.rttUs))
                    Protocol.TYPE_STATS
                }
            }
            val body = payload.toByteArray()
            return ByteBuffer.allocate(Protocol.HEADER_SIZE + body.size)
                .put(type.toByte())
                .put(0.toByte())
                .putShort(0.toShort())
                .putInt(body.size)
                .put(body)
                .array()
        }
    }
}
