package com.orizonx.client.actions

import org.json.JSONArray
import org.json.JSONObject

data class ClockState(val epochMs: Long, val utcOffsetMin: Int)

data class BatteryState(val percent: Int, val charging: Boolean)

data class AudioState(val volume: Float, val muted: Boolean)

data class BrightnessState(val value: Float)

/** [signal] is the connection quality 0..100, null when Wi-Fi is not connected (or the PC does not report it). */
data class WifiState(val on: Boolean, val ssid: String?, val signal: Int? = null)

data class BluetoothState(val on: Boolean, val connected: List<String>)

data class AirplaneState(val on: Boolean)

/** Kind of removable drive; drives the chip pictogram. */
enum class UsbKind { STICK, DISK }

/** [freeBytes] / [totalBytes] are null when the PC did not report them. [kind] is STICK when the PC does not say. */
data class UsbDrive(
    val drive: String,
    val label: String,
    val freeBytes: Long?,
    val totalBytes: Long?,
    val kind: UsbKind = UsbKind.STICK,
)

/** [artworkId] (sha1 hex) names the MEDIA_ARTWORK image of the track, null when it has no cover. */
data class NowPlaying(
    val app: String,
    val title: String,
    val artist: String,
    val album: String,
    val playing: Boolean,
    val artworkId: String?,
)

data class Notice(val code: String, val drive: String?)

/** [icon] is a name from the spec list (see [ContextIcons]); it may be unknown, the UI then shows a dot. */
data class ContextButton(val id: String, val icon: String, val label: String)

/** One page of the bar (Tools, Edit, View...): at most [ContextBar.MAX_BUTTONS] buttons, never empty once parsed. */
data class ContextPage(val id: String, val label: String, val buttons: List<ContextButton>)

/**
 * Contextual bar for the PC's foreground app: [app] is the display name, [profile] changes with the app.
 * [buttons] is page 1 (what an old PC sends alone); [pages] holds every page, at least one.
 * [icon] is the sha1 id of the app or site icon (an image received like cover art), null when the PC has none yet.
 */
data class ContextBar(
    val app: String,
    val profile: String,
    val buttons: List<ContextButton>,
    val pages: List<ContextPage> = listOf(ContextPage(MAIN_PAGE, "", buttons)),
    val icon: String? = null,
) {
    companion object {
        const val MAX_BUTTONS = 8
        const val MAX_PAGES = 4
        const val MAIN_PAGE = "main"
    }
}

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
    val nowPlaying: NowPlaying? = null,
    val notice: Notice? = null,
    val context: ContextBar? = null,
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
            wifi = available(json, "wifi")?.let { WifiState(it.optBoolean("on", false), text(it, "ssid"), signal(it)) },
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
            nowPlaying = available(json, "now_playing")?.let { n ->
                NowPlaying(
                    app = text(n, "app") ?: "",
                    title = text(n, "title") ?: "",
                    artist = text(n, "artist") ?: "",
                    album = text(n, "album") ?: "",
                    playing = n.optBoolean("playing", false),
                    artworkId = text(n, "artwork"),
                )
            },
            notice = json.optJSONObject("notice")?.let { n ->
                text(n, "code")?.let { Notice(it, text(n, "drive")) }
            },
            context = context(json),
        )

        /**
         * Null (bar hidden) when absent, unavailable or without any usable button. Without `pages` (or with an empty list)
         * the legacy `buttons` make a single page; otherwise at most [ContextBar.MAX_PAGES] non-empty pages of
         * [ContextBar.MAX_BUTTONS] buttons, and `buttons` is taken from page 1.
         */
        private fun context(json: JSONObject): ContextBar? {
            val c = available(json, "context") ?: return null
            val app = text(c, "app") ?: ""
            val profile = text(c, "profile") ?: ""
            val icon = (c.opt("icon") as? String)?.takeIf { it.isNotBlank() }
            val pagesArray = c.optJSONArray("pages")
            if (pagesArray == null || pagesArray.length() == 0) {
                val buttons = buttons(c.optJSONArray("buttons"))
                if (buttons.isEmpty()) return null
                return ContextBar(app, profile, buttons, icon = icon)
            }
            val pages = (0 until pagesArray.length()).mapNotNull { i ->
                val p = pagesArray.optJSONObject(i) ?: return@mapNotNull null
                val buttons = buttons(p.optJSONArray("buttons"))
                if (buttons.isEmpty()) return@mapNotNull null
                val id = text(p, "id") ?: "page${i + 1}"
                ContextPage(id, text(p, "label") ?: id, buttons)
            }.take(ContextBar.MAX_PAGES)
            if (pages.isEmpty()) return null
            return ContextBar(app, profile, pages[0].buttons, pages, icon)
        }

        private fun buttons(array: JSONArray?): List<ContextButton> {
            if (array == null) return emptyList()
            return (0 until array.length()).mapNotNull { i ->
                val b = array.optJSONObject(i) ?: return@mapNotNull null
                val id = text(b, "id") ?: return@mapNotNull null
                ContextButton(id, text(b, "icon") ?: "", text(b, "label") ?: "")
            }.take(ContextBar.MAX_BUTTONS)
        }

        /** The section object when the PC reports it with `available: true`, else null. */
        private fun available(json: JSONObject, key: String): JSONObject? =
            json.optJSONObject(key)?.takeIf { it.optBoolean("available", false) }

        private fun text(obj: JSONObject, key: String): String? =
            if (obj.isNull(key)) null else obj.optString(key, "").takeIf { it.isNotBlank() }

        /** Wi-Fi quality 0..100 (clamped); null when absent, null, or not a number. */
        private fun signal(wifi: JSONObject): Int? {
            val value = when (val raw = wifi.opt("signal")) {
                is Number -> raw.toDouble()
                is String -> raw.trim().toDoubleOrNull()
                else -> null
            }
            return if (value == null || value.isNaN()) null else Math.round(value.coerceIn(0.0, 100.0)).toInt()
        }

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
                    kind = if (text(d, "kind")?.lowercase() == "disk") UsbKind.DISK else UsbKind.STICK,
                )
            }
        }
    }
}
