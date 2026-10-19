package com.orizonx.client.keyboard

import com.orizonx.client.protocol.FrameWriter
import com.orizonx.client.protocol.TabletMessage
import org.junit.Assert.assertEquals
import org.junit.Test

class KeyboardActionsTest {
    private fun wire(json: org.json.JSONObject) =
        String(FrameWriter.encode(TabletMessage.Action(json)).drop(8).toByteArray(), Charsets.UTF_8)

    @Test
    fun keyDownAndUp() {
        assertEquals("""{"id":"keyboard.key","down":true,"ext":false,"sc":30}""", wire(KeyboardActions.key(0x1E, false, true)))
        assertEquals("""{"id":"keyboard.key","down":false,"ext":true,"sc":83}""", wire(KeyboardActions.key(KeyEvent(0x53, true, false))))
    }

    @Test
    fun release() {
        assertEquals("""{"id":"keyboard.release"}""", wire(KeyboardActions.release()))
    }
}
