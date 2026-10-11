package com.orizonx.client.actions

import org.json.JSONObject
import kotlin.math.roundToLong

/** Builders for the ACTION payloads of spec section 2.2. */
object ActionMessages {
    private fun id(name: String) = JSONObject().put("id", name)

    /** 3 decimals are plenty for a 0..1 slider and keep the JSON small. */
    private fun unit(value: Float): Double = (value.coerceIn(0f, 1f) * 1000.0).roundToLong() / 1000.0

    fun volumeSet(value: Float): JSONObject = id("volume.set").put("value", unit(value))
    fun volumeMute(muted: Boolean): JSONObject = id("volume.mute").put("value", muted)
    fun mediaPlayPause(): JSONObject = id("media.play_pause")
    fun mediaNext(): JSONObject = id("media.next")
    fun mediaPrevious(): JSONObject = id("media.previous")
    fun brightnessSet(value: Float): JSONObject = id("brightness.set").put("value", unit(value))
    fun wifiSet(on: Boolean): JSONObject = id("wifi.set").put("value", on)
    fun bluetoothSet(on: Boolean): JSONObject = id("bluetooth.set").put("value", on)
    fun airplaneSet(on: Boolean): JSONObject = id("airplane.set").put("value", on)
    fun usbOpen(drive: String): JSONObject = id("usb.open").put("drive", drive)
    fun usbEject(drive: String): JSONObject = id("usb.eject").put("drive", drive)
}
