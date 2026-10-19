package com.orizonx.client.gamepad

import org.json.JSONObject

/** Builders for the `gamepad.*` ACTION payloads (spec section 4). On the wire `id` comes first, then the rest alphabetically. */
object GamepadActions {
    fun open(): JSONObject = JSONObject().put("id", "gamepad.open")

    fun close(): JSONObject = JSONObject().put("id", "gamepad.close")

    fun state(report: GamepadReport): JSONObject = JSONObject()
        .put("id", "gamepad.state")
        .put("buttons", report.buttons)
        .put("lt", report.lt)
        .put("rt", report.rt)
        .put("lx", report.lx)
        .put("ly", report.ly)
        .put("rx", report.rx)
        .put("ry", report.ry)
}
