package dev.tabx.client.protocol

import org.json.JSONObject
import org.junit.Assert.assertArrayEquals
import org.junit.Assert.assertEquals
import org.junit.Assert.fail
import org.junit.Test
import java.io.ByteArrayInputStream
import java.io.File

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
                else -> error("type inattendu : ${vector.getString("type")}")
            }
            assertEquals(vector.getString("name"), vector.getString("hex"), FrameWriter.encode(message).toHex())
        }
    }
}
