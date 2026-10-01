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
    const val TYPE_INPUT = 0x85

    const val DEVICE_TOUCH = 1
    const val DEVICE_PEN = 2
    const val MAX_TOUCH_CONTACTS = 10

    // bits de InputContact.flags
    const val CONTACT_CONTACT = 0x01
    const val CONTACT_IN_RANGE = 0x02
    const val CONTACT_BARREL = 0x04
    const val CONTACT_CANCELED = 0x08

    const val FLAG_KEY = 0x01
    const val FLAG_CODEC_CONFIG = 0x02
    const val CODEC_H264 = 1
}

class ProtocolException(message: String) : IOException(message)

/** One finger or the pen in an INPUT frame. Coordinates 0..65535 over the video image (spec phase 4 §3). */
data class InputContact(
    val id: Int,
    val flags: Int,
    val x: Int,
    val y: Int,
    val pressure: Int = 0,
    val tiltX: Int = 0,
    val tiltY: Int = 0,
)

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

    /** Complete state of one device (touch or pen) right after an event. */
    data class Input(val device: Int, val contacts: List<InputContact>) : TabletMessage
}
