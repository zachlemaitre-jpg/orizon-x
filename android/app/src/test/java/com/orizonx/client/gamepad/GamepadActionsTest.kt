package com.orizonx.client.gamepad

import com.orizonx.client.protocol.FrameWriter
import com.orizonx.client.protocol.TabletMessage
import org.junit.Assert.assertEquals
import org.junit.Test

class GamepadActionsTest {
    private fun wire(json: org.json.JSONObject) =
        String(FrameWriter.encode(TabletMessage.Action(json)).drop(8).toByteArray(), Charsets.UTF_8)

    @Test
    fun openAndClose() {
        assertEquals("""{"id":"gamepad.open"}""", wire(GamepadActions.open()))
        assertEquals("""{"id":"gamepad.close"}""", wire(GamepadActions.close()))
    }

    @Test
    fun neutralState() {
        assertEquals(
            """{"id":"gamepad.state","buttons":0,"lt":0,"lx":0,"ly":0,"rt":0,"rx":0,"ry":0}""",
            wire(GamepadActions.state(GamepadReport.NEUTRAL)),
        )
    }

    @Test
    fun fullState() {
        val report = GamepadReport(buttons = 0x9001, lt = 255, rt = 0, lx = -32767, ly = 32767, rx = 12, ry = -3)
        assertEquals(
            """{"id":"gamepad.state","buttons":36865,"lt":255,"lx":-32767,"ly":32767,"rt":0,"rx":12,"ry":-3}""",
            wire(GamepadActions.state(report)),
        )
    }
}
