package com.orizonx.client.protocol

import com.orizonx.client.i18n.Msg
import org.json.JSONObject
import java.io.IOException

/** TABX protocol v1 constants. Reference: protocol/PROTOCOL.md. */
object Protocol {
    const val VERSION = 1
    const val PORT = 27183
    const val HEADER_SIZE = 8
    const val MAX_PAYLOAD = 16 * 1024 * 1024

    /** Largest JSON payload (DEVICE_INFO, ACTION, ACTIONS_STATE). */
    const val MAX_JSON = 64 * 1024

    /** Largest MEDIA_ARTWORK payload: id length byte + id + raw image (JPEG or PNG). */
    const val MAX_ARTWORK = 512 * 1024
    val MAGIC: ByteArray = "TABX".toByteArray(Charsets.US_ASCII)

    // PC -> tablet
    const val TYPE_CONFIG = 0x01
    const val TYPE_VIDEO = 0x02
    const val TYPE_PONG = 0x03
    const val TYPE_ACTIONS_STATE = 0x04
    const val TYPE_MEDIA_ARTWORK = 0x05

    // tablet -> PC
    const val TYPE_HELLO = 0x81
    const val TYPE_PING = 0x82
    const val TYPE_KEYFRAME_REQ = 0x83
    const val TYPE_STATS = 0x84
    const val TYPE_INPUT = 0x85
    const val TYPE_DEVICE_INFO = 0x86
    const val TYPE_ACTION = 0x87

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

/** [reason] is the same problem as a translatable text, for the waiting screen; [message] stays a diagnostic for the logs. */
class ProtocolException(message: String, val reason: Msg? = null) : IOException(message)

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

/** The complete Actions state broadcast by the PC (ACTIONS_STATE, JSON). Parsing into a model is up to the UI layer. */
class ActionsStateMessage(val json: JSONObject) : PcMessage

/** Cover art of the "now playing" block: [id] (sha1 hex, as referenced by `now_playing.artwork`) and the raw JPEG/PNG [bytes]. */
class MediaArtworkMessage(val id: String, val bytes: ByteArray) : PcMessage {
    override fun equals(other: Any?): Boolean =
        other is MediaArtworkMessage && other.id == id && other.bytes.contentEquals(bytes)

    override fun hashCode(): Int = 31 * id.hashCode() + bytes.contentHashCode()

    override fun toString(): String = "MediaArtworkMessage(id=$id, bytes=${bytes.size})"
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

    /** Role and identity of this device, sent right after Hello. [role] is "screen" or "actions"; [kind] "phone" or "tablet". */
    data class DeviceInfo(
        val role: String,
        val kind: String,
        val name: String,
        val app: String,
        /** Best size/rate the hardware decoder handles (screen role); null = unknown, the PC keeps its defaults. */
        val video: VideoCaps? = null,
        /** Effective interface language ("en" or "fr"): the PC labels its context bar with it; null = not announced (PC assumes "fr"). */
        val lang: String? = null,
    ) : TabletMessage

    /** One user action for the PC; [json] must carry a string "id" (spec actions-mode §2.2). */
    class Action(val json: JSONObject) : TabletMessage
}

/** Announced in DEVICE_INFO: the largest landscape size the device decodes at [fps] (60 or 30). */
data class VideoCaps(val width: Int, val height: Int, val fps: Int) {
    data class Size(val width: Int, val height: Int)
}
