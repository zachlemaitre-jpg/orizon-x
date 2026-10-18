package com.orizonx.client.protocol

import org.json.JSONArray
import org.json.JSONObject
import org.junit.Assert.assertArrayEquals
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Assert.fail
import org.junit.Test
import java.io.ByteArrayInputStream
import java.io.File

/** Structural JSON equality (the android.jar stub of org.json has no JSONObject.similar). */
private fun jsonEquals(a: Any?, b: Any?): Boolean = when {
    a is JSONObject && b is JSONObject ->
        a.length() == b.length() && a.keys().asSequence().all { b.has(it) && jsonEquals(a.get(it), b.get(it)) }
    a is JSONArray && b is JSONArray ->
        a.length() == b.length() && (0 until a.length()).all { jsonEquals(a.get(it), b.get(it)) }
    a is Number && b is Number -> a.toDouble() == b.toDouble()
    else -> a == b
}

class ProtocolVectorsTest {
    private val vectors = JSONObject(File(System.getProperty("tabx.vectors")!!).readText())

    @Test
    fun decodesPcToTabletVectors() {
        val list = vectors.getJSONArray("pc_to_tablet")
        for (i in 0 until list.length()) {
            val vector = list.getJSONObject(i)
            val f = vector.getJSONObject("fields")
            val message = FrameReader(ByteArrayInputStream(hex(vector.getString("hex")))).read()
            when (vector.getString("type")) {
                "CONFIG" -> assertEquals(
                    PcMessage.Config(f.getInt("codec"), f.getInt("width"), f.getInt("height"), f.getInt("fps")),
                    message,
                )
                "VIDEO" -> {
                    message as PcMessage.Video
                    assertEquals(f.getLong("pts_us"), message.ptsUs)
                    assertEquals(f.getInt("flags"), message.flags)
                    assertArrayEquals(hex(f.getString("data")), message.data)
                }
                "PONG" -> assertEquals(PcMessage.Pong(f.getLong("t_tab_us"), f.getLong("t_pc_us")), message)
                "ACTIONS_STATE" -> {
                    message as ActionsStateMessage
                    val expected = f.getJSONObject("state")
                    assertTrue(vector.getString("name"), jsonEquals(expected, message.json))
                }
                "MEDIA_ARTWORK" -> {
                    message as MediaArtworkMessage
                    assertEquals(f.getString("id"), message.id)
                    assertArrayEquals(hex(f.getString("data")), message.bytes)
                }
                "FRAME_STATE" -> assertEquals(
                    vector.getString("name"),
                    PcMessage.FrameState(
                        epoch = f.getLong("epoch"),
                        status = f.getString("status"),
                        folder = if (f.isNull("folder")) null else f.getString("folder"),
                        intervalS = f.getInt("interval_s"),
                        fit = f.getString("fit"),
                        paused = f.getBoolean("paused"),
                    ),
                    message,
                )
                "FRAME_FILE" -> assertEquals(
                    vector.getString("name"),
                    PcMessage.FrameFile(
                        f.getLong("epoch"), f.getLong("id"), f.getInt("kind"),
                        f.getLong("total"), f.getLong("offset"), hex(f.getString("data")),
                    ),
                    message,
                )
                else -> fail("type inattendu : ${vector.getString("type")}")
            }
        }
    }

    @Test
    fun encodesTabletToPcVectors() {
        val list = vectors.getJSONArray("tablet_to_pc")
        for (i in 0 until list.length()) {
            val vector = list.getJSONObject(i)
            val f = vector.getJSONObject("fields")
            val message = when (vector.getString("type")) {
                "HELLO" -> TabletMessage.Hello(f.getInt("width"), f.getInt("height"), f.getInt("dpi"), f.getInt("version"))
                "PING" -> TabletMessage.Ping(f.getLong("t_tab_us"))
                "KEYFRAME_REQ" -> TabletMessage.KeyframeRequest
                "STATS" -> TabletMessage.Stats(
                    f.getInt("fps"), f.getLong("latency_avg_us"), f.getLong("latency_max_us"),
                    f.getLong("dropped"), f.getLong("rtt_us"),
                )
                "INPUT" -> {
                    val contacts = f.getJSONArray("contacts")
                    TabletMessage.Input(
                        f.getInt("device"),
                        (0 until contacts.length()).map { j ->
                            val c = contacts.getJSONObject(j)
                            InputContact(
                                c.getInt("id"), c.getInt("flags"), c.getInt("x"), c.getInt("y"),
                                c.getInt("pressure"), c.getInt("tilt_x"), c.getInt("tilt_y"),
                            )
                        },
                    )
                }
                "DEVICE_INFO" -> TabletMessage.DeviceInfo(
                    f.getString("role"), f.getString("kind"), f.getString("name"), f.getString("app"),
                )
                "ACTION" -> TabletMessage.Action(f)
                else -> error("type inattendu : ${vector.getString("type")}")
            }
            assertEquals(vector.getString("name"), vector.getString("hex"), FrameWriter.encode(message).toHex())
        }
    }
}
