package com.orizonx.client.trackpad

import org.json.JSONObject
import kotlin.math.roundToLong

/** Builders for the `trackpad.*` ACTION payloads (spec section 3). On the wire `id` comes first, then the rest alphabetically. */
object TrackpadActions {
    /** 3 decimals keep the JSON small; the PC keeps the sub-pixel remainders itself. */
    private fun round(value: Float): Double = (value * 1000.0).roundToLong() / 1000.0

    fun move(dx: Float, dy: Float): JSONObject =
        JSONObject().put("id", "trackpad.move").put("dx", round(dx)).put("dy", round(dy))

    fun button(right: Boolean, down: Boolean): JSONObject =
        JSONObject().put("id", "trackpad.button").put("button", if (right) "right" else "left").put("down", down)

    fun scroll(dx: Float, dy: Float): JSONObject =
        JSONObject().put("id", "trackpad.scroll").put("dx", round(dx)).put("dy", round(dy))

    fun zoom(steps: Int): JSONObject = JSONObject().put("id", "trackpad.zoom").put("steps", steps)

    fun gesture(name: String): JSONObject = JSONObject().put("id", "trackpad.gesture").put("name", name)

    fun release(): JSONObject = JSONObject().put("id", "trackpad.release")

    fun of(effect: TrackpadEffect): JSONObject = when (effect) {
        is TrackpadEffect.Move -> move(effect.dx, effect.dy)
        is TrackpadEffect.Scroll -> scroll(effect.dx, effect.dy)
        is TrackpadEffect.Zoom -> zoom(effect.steps)
        is TrackpadEffect.Button -> button(effect.right, effect.down)
        is TrackpadEffect.Gesture -> gesture(effect.name)
    }
}
