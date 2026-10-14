package com.orizonx.client.protocol

import java.io.BufferedOutputStream
import java.io.ByteArrayOutputStream
import java.io.DataOutputStream
import org.json.JSONObject
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

    fun deviceInfo(role: String, kind: String, name: String, app: String, video: VideoCaps? = null, lang: String? = null) =
        write(TabletMessage.DeviceInfo(role, kind, name, app, video, lang))

    fun action(json: JSONObject) = write(TabletMessage.Action(json))

    companion object {
        private class RawJson(val text: String)

        private fun u32(value: Long): Int = value.coerceIn(0, 0xFFFF_FFFFL).toInt()

        /** Compact UTF-8 JSON object with the keys in the given order (org.json's own key order is not stable). */
        private fun jsonBytes(name: String, entries: List<Pair<String, Any?>>): ByteArray {
            val text = entries.joinToString(prefix = "{", postfix = "}", separator = ",") { (key, value) ->
                // A pre-rendered nested object (fixed key order) goes in as is.
                if (value is RawJson) return@joinToString JSONObject.quote(key) + ":" + value.text
                val single = JSONObject().put(key, value).toString()
                single.substring(1, single.length - 1)
            }
            val bytes = text.toByteArray(Charsets.UTF_8)
            require(bytes.size <= Protocol.MAX_JSON) { "$name trop gros : ${bytes.size} octets" }
            return bytes
        }

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
                is TabletMessage.Input -> {
                    val max = if (message.device == Protocol.DEVICE_PEN) 1 else Protocol.MAX_TOUCH_CONTACTS
                    val contacts = message.contacts.take(max)
                    out.writeByte(message.device)
                    out.writeByte(contacts.size)
                    for (contact in contacts) {
                        out.writeByte(contact.id)
                        out.writeByte(contact.flags)
                        out.writeShort(contact.x.coerceIn(0, 0xFFFF))
                        out.writeShort(contact.y.coerceIn(0, 0xFFFF))
                        out.writeShort(contact.pressure.coerceIn(0, 0xFFFF))
                        out.writeByte(contact.tiltX.coerceIn(-90, 90))
                        out.writeByte(contact.tiltY.coerceIn(-90, 90))
                    }
                    Protocol.TYPE_INPUT
                }
                is TabletMessage.DeviceInfo -> {
                    out.write(
                        jsonBytes(
                            "DEVICE_INFO",
                            listOfNotNull(
                                "role" to message.role,
                                "kind" to message.kind,
                                "name" to message.name,
                                "app" to message.app,
                                message.video?.let {
                                    "video" to RawJson("{\"width\":${it.width},\"height\":${it.height},\"fps\":${it.fps}}")
                                },
                                message.lang?.let { "lang" to it },
                            ),
                        ),
                    )
                    Protocol.TYPE_DEVICE_INFO
                }
                is TabletMessage.Action -> {
                    require(message.json.opt("id") is String) { "ACTION : \"id\" manquant ou pas une chaîne" }
                    val rest = message.json.keys().asSequence().filter { it != "id" }.sorted()
                    out.write(
                        jsonBytes(
                            "ACTION",
                            listOf("id" to message.json.getString("id")) + rest.map { it to message.json.get(it) }.toList(),
                        ),
                    )
                    Protocol.TYPE_ACTION
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
