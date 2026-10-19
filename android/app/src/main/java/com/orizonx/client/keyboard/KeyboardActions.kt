package com.orizonx.client.keyboard

import org.json.JSONObject

/** Builders for the `keyboard.*` ACTION payloads (spec section 3). On the wire `id` comes first, then the rest alphabetically. */
object KeyboardActions {
    fun key(event: KeyEvent): JSONObject = key(event.sc, event.ext, event.down)

    fun key(sc: Int, ext: Boolean, down: Boolean): JSONObject =
        JSONObject().put("id", "keyboard.key").put("sc", sc).put("ext", ext).put("down", down)

    fun release(): JSONObject = JSONObject().put("id", "keyboard.release")
}
