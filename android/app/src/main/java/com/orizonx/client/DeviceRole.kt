package com.orizonx.client

import android.content.SharedPreferences
import com.orizonx.client.i18n.Lang
import com.orizonx.client.protocol.TabletMessage
import com.orizonx.client.protocol.VideoCaps

/** What this device does for the PC: second screen, Actions remote or picture Frame. */
enum class DeviceRole(val wire: String) {
    SCREEN("screen"),
    ACTIONS("actions"),
    FRAME("frame"),
    ;

    companion object {
        /** Below this smallest width (dp) the device counts as a phone. */
        const val PHONE_MAX_DP_EXCLUSIVE = 600

        fun fromWire(value: String?): DeviceRole? = entries.firstOrNull { it.wire == value }

        /** Phone (smallest width < 600 dp) -> ACTIONS, tablet -> SCREEN. */
        fun defaultFor(smallestWidthDp: Int): DeviceRole = if (isPhone(smallestWidthDp)) ACTIONS else SCREEN

        fun isPhone(smallestWidthDp: Int): Boolean = smallestWidthDp < PHONE_MAX_DP_EXCLUSIVE

        /** DEVICE_INFO `kind` field: "phone" or "tablet" by the same width rule. */
        fun kindFor(smallestWidthDp: Int): String = if (isPhone(smallestWidthDp)) "phone" else "tablet"
    }
}

/** Builds the DEVICE_INFO announced right after HELLO. */
fun deviceInfoFor(
    role: DeviceRole,
    smallestWidthDp: Int,
    model: String,
    appVersion: String,
    video: VideoCaps? = null,
    lang: Lang? = null,
) =
    TabletMessage.DeviceInfo(
        role.wire,
        DeviceRole.kindFor(smallestWidthDp),
        model,
        appVersion,
        video.takeIf { role == DeviceRole.SCREEN }, // decoder limits only matter for the second-screen role
        lang?.wire,
    )

/** Persists the chosen [DeviceRole]; falls back to the width-based default until the user picks one. */
class RoleStore(private val prefs: SharedPreferences, private val smallestWidthDp: Int) {
    fun load(): DeviceRole = DeviceRole.fromWire(prefs.getString(KEY, null)) ?: DeviceRole.defaultFor(smallestWidthDp)

    fun save(role: DeviceRole) {
        prefs.edit().putString(KEY, role.wire).apply()
    }

    private companion object {
        const val KEY = "role"
    }
}
