package dev.tabx.client.protocol

import java.io.IOException

/** TABX protocol v1 constants. Reference: protocol/PROTOCOL.md. */
object Protocol {
    const val VERSION = 1
    const val PORT = 27183
    const val HEADER_SIZE = 8
    const val MAX_PAYLOAD = 16 * 1024 * 1024
    val MAGIC: ByteArray = "TABX".toByteArray(Charsets.US_ASCII)

    // PC -> tablet
    const val TYPE_CONFIG = 0x01
    const val TYPE_VIDEO = 0x02
    const val TYPE_PONG = 0x03

    // tablet -> PC
    const val TYPE_HELLO = 0x81
    const val TYPE_PING = 0x82
    const val TYPE_KEYFRAME_REQ = 0x83
    const val TYPE_STATS = 0x84

    const val FLAG_KEY = 0x01
    const val FLAG_CODEC_CONFIG = 0x02
    const val CODEC_H264 = 1
}

class ProtocolException(message: String) : IOException(message)

/** Messages received from the PC. */
sealed interface PcMessage {
    data class Config(val codec: Int, val width: Int, val height: Int, val fps: Int) : PcMessage

    class Video(val ptsUs: Long, val flags: Int, val data: ByteArray) : PcMessage {
        val isKey: Boolean get() = (flags and Protocol.FLAG_KEY) != 0
        val isCodecConfig: Boolean get() = (flags and Protocol.FLAG_CODEC_CONFIG) != 0
    }

    data class Pong(val tTabUs: Long, val tPcUs: Long) : PcMessage
}

/** Messages sent to the PC. */
sealed interface TabletMessage {
    data class Hello(val width: Int, val height: Int, val dpi: Int, val version: Int = Protocol.VERSION) : TabletMessage

    data class Ping(val tTabUs: Long) : TabletMessage

    data object KeyframeRequest : TabletMessage

    data class Stats(
        val fps: Int,
        val latencyAvgUs: Long,
        val latencyMaxUs: Long,
        val dropped: Long,
        val rttUs: Long,
    ) : TabletMessage
}
