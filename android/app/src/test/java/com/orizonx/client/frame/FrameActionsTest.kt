package com.orizonx.client.frame

import com.orizonx.client.frame.FramePlayer.Effect
import com.orizonx.client.i18n.Lang
import com.orizonx.client.protocol.FrameWriter
import com.orizonx.client.protocol.TabletMessage
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Test

class FrameActionsTest {
    private fun wire(json: org.json.JSONObject) =
        String(FrameWriter.encode(TabletMessage.Action(json)).drop(8).toByteArray(), Charsets.UTF_8)

    @Test
    fun theFiveActionsMatchTheProtocol() {
        assertEquals("""{"id":"frame.next"}""", wire(FrameActions.next()))
        assertEquals("""{"id":"frame.pause","paused":true}""", wire(FrameActions.pause(true)))
        assertEquals("""{"id":"frame.pause","paused":false}""", wire(FrameActions.pause(false)))
        assertEquals("""{"id":"frame.fit","fit":"fit"}""", wire(FrameActions.fit("fit")))
        assertEquals("""{"id":"frame.interval","interval_s":300}""", wire(FrameActions.interval(300)))
        assertEquals("""{"id":"frame.failed","file":7}""", wire(FrameActions.failed(7)))
    }

    @Test
    fun aFileIdAboveTheIntRangeIsKept() {
        assertEquals("""{"id":"frame.failed","file":4294967295}""", wire(FrameActions.failed(4_294_967_295L)))
    }

    @Test
    fun effectsMapToActions() {
        assertEquals("""{"id":"frame.next"}""", wire(Effect.SendNext.toAction()!!))
        assertEquals("""{"id":"frame.failed","file":3}""", wire(Effect.SendFailed(3).toAction()!!))
        assertEquals("""{"id":"frame.pause","paused":true}""", wire(Effect.SendPause(true).toAction()!!))
        assertEquals("""{"id":"frame.fit","fit":"crop"}""", wire(Effect.SendFit("crop").toAction()!!))
        assertEquals("""{"id":"frame.interval","interval_s":5}""", wire(Effect.SendInterval(5).toAction()!!))
        assertNull(Effect.Release(1).toAction())
        assertNull(Effect.Show(FrameItem(1, 1, java.io.File("x"))).toAction())
    }

    @Test
    fun intervalLabels() {
        assertEquals("5 s", FrameFormat.interval(5, Lang.EN))
        assertEquals("30 s", FrameFormat.interval(30, Lang.FR))
        assertEquals("1 min", FrameFormat.interval(60, Lang.EN))
        assertEquals("15 min", FrameFormat.interval(900, Lang.FR))
        assertEquals("1 h", FrameFormat.interval(3600, Lang.EN))
        assertEquals("90 s", FrameFormat.interval(90, Lang.EN))
    }
}
