package com.orizonx.client.trackpad

import com.orizonx.client.protocol.FrameWriter
import com.orizonx.client.protocol.TabletMessage
import org.junit.Assert.assertEquals
import org.junit.Test

class TrackpadActionsTest {
    private fun wire(json: org.json.JSONObject) =
        String(FrameWriter.encode(TabletMessage.Action(json)).drop(8).toByteArray(), Charsets.UTF_8)

    @Test
    fun move() {
        assertEquals("""{"id":"trackpad.move","dx":12.5,"dy":-3}""", wire(TrackpadActions.move(12.5f, -3f)))
        assertEquals("""{"id":"trackpad.move","dx":0.333,"dy":1}""", wire(TrackpadActions.move(1f / 3, 1f)))
    }

    @Test
    fun button() {
        assertEquals("""{"id":"trackpad.button","button":"left","down":true}""", wire(TrackpadActions.button(right = false, down = true)))
        assertEquals("""{"id":"trackpad.button","button":"right","down":false}""", wire(TrackpadActions.button(right = true, down = false)))
    }

    @Test
    fun scroll() {
        assertEquals("""{"id":"trackpad.scroll","dx":0,"dy":7.25}""", wire(TrackpadActions.scroll(0f, 7.25f)))
    }

    @Test
    fun zoom() {
        assertEquals("""{"id":"trackpad.zoom","steps":-2}""", wire(TrackpadActions.zoom(-2)))
    }

    @Test
    fun gesture() {
        assertEquals("""{"id":"trackpad.gesture","name":"task_view"}""", wire(TrackpadActions.gesture("task_view")))
    }

    @Test
    fun release() {
        assertEquals("""{"id":"trackpad.release"}""", wire(TrackpadActions.release()))
    }

    @Test
    fun everyEffectHasItsJson() {
        assertEquals(TrackpadActions.move(1f, 2f).toString(), TrackpadActions.of(TrackpadEffect.Move(1f, 2f)).toString())
        assertEquals(TrackpadActions.scroll(1f, 2f).toString(), TrackpadActions.of(TrackpadEffect.Scroll(1f, 2f)).toString())
        assertEquals(TrackpadActions.zoom(3).toString(), TrackpadActions.of(TrackpadEffect.Zoom(3)).toString())
        assertEquals(TrackpadActions.button(true, true).toString(), TrackpadActions.of(TrackpadEffect.Button(true, true)).toString())
        assertEquals(TrackpadActions.gesture("desktop").toString(), TrackpadActions.of(TrackpadEffect.Gesture("desktop")).toString())
    }
}
