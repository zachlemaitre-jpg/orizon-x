package com.orizonx.client.actions

import org.json.JSONObject

data class ClockState(val epochMs: Long, val utcOffsetMin: Int)

data class BatteryState(val percent: Int, val charging: Boolean)

data class AudioState(val volume: Float, val muted: Boolean)

data class BrightnessState(val value: Float)

data class WifiState(val on: Boolean, val ssid: String?)

data class BluetoothState(val on: Boolean, val connected: List<String>)

data class AirplaneState(val on: Boolean)

/** [freeBytes] / [totalBytes] are null when the PC did not report them. */
data class UsbDrive(val drive: String, val label: String, val freeBytes: Long?, val totalBytes: Long?)

data class Notice(val code: String, val drive: String?)

/**
 * Immutable view of an ACTIONS_STATE payload. A section is null when the PC reports it unavailable
 * (`available` not true), when it is absent, or when its mandatory fields are missing or invalid:
 * the UI then hides the matching control.
 */
data class ActionsState(
    val clock: ClockState? = null,
    val battery: BatteryState? = null,
    val audio: AudioState? = null,
    val mediaAvailable: Boolean = false,
    val brightness: BrightnessState? = null,
    val wifi: WifiState? = null,
    val bluetooth: BluetoothState? = null,
    val airplane: AirplaneState? = null,
    val usb: List<UsbDrive> = emptyList(),
    val notice: Notice? = null,
) {
    companion object {
        /** Never throws: anything unreadable simply makes the matching section absent. */
        fun parse(json: JSONObject): ActionsState = ActionsState(
            clock = clock(json),
            battery = available(json, "battery")?.let { b ->
                val percent = b.optInt("percent", -1)
                if (percent in 0..100) BatteryState(percent, b.optBoolean("charging", false)) else null
            },
            audio = available(json, "audio")?.let { a ->
                val volume = a.optDouble("volume", Double.NaN)
                if (volume.isNaN()) null else AudioState(volume.toFloat().coerceIn(0f, 1f), a.optBoolean("muted", false))
            },
            mediaAvailable = available(json, "media") != null,
            brightness = available(json, "brightness")?.let { b ->
                val value = b.optDouble("value", Double.NaN)
                if (value.isNaN()) null else BrightnessState(value.toFloat().coerceIn(0f, 1f))
            },
            wifi = available(json, "wifi")?.let { WifiState(it.optBoolean("on", false), text(it, "ssid")) },
            bluetooth = available(json, "bluetooth")?.let { b ->
                val names = b.optJSONArray("connected")
                val connected = if (names == null) {
                    emptyList()
                } else {
                    (0 until names.length()).mapNotNull { i -> names.optString(i, "").takeIf { it.isNotBlank() } }
                }
                BluetoothState(b.optBoolean("on", false), connected)
            },
            airplane = available(json, "airplane")?.let { AirplaneState(it.optBoolean("on", false)) },
            usb = drives(json),
            notice = json.optJSONObject("notice")?.let { n ->
                text(n, "code")?.let { Notice(it, text(n, "drive")) }
            },
        )

        /** The section object when the PC reports it with `available: true`, else null. */
        private fun available(json: JSONObject, key: String): JSONObject? =
            json.optJSONObject(key)?.takeIf { it.optBoolean("available", false) }

        private fun text(obj: JSONObject, key: String): String? =
            if (obj.isNull(key)) null else obj.optString(key, "").takeIf { it.isNotBlank() }

        private fun clock(json: JSONObject): ClockState? {
            val c = json.optJSONObject("clock") ?: return null
            if (c.isNull("epoch_ms")) return null
            val epoch = c.optLong("epoch_ms", -1)
            if (epoch < 0) return null
            return ClockState(epoch, c.optInt("utc_offset_min", 0))
        }

        private fun drives(json: JSONObject): List<UsbDrive> {
            val array = json.optJSONArray("usb") ?: return emptyList()
            return (0 until array.length()).mapNotNull { i ->
                val d = array.optJSONObject(i) ?: return@mapNotNull null
                val letter = text(d, "drive") ?: return@mapNotNull null
                UsbDrive(
                    drive = letter,
                    label = text(d, "label") ?: "",
                    freeBytes = d.optLong("free_bytes", -1).takeIf { it >= 0 },
                    totalBytes = d.optLong("total_bytes", -1).takeIf { it >= 0 },
                )
            }
        }
    }
}
