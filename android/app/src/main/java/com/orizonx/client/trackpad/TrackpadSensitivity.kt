package com.orizonx.client.trackpad

import android.content.SharedPreferences
import kotlin.math.roundToInt

/** Pointer speed multiplier of the trackpad: 0.5 to 3.0 by steps of 0.25. */
object TrackpadSensitivity {
    const val MIN = 0.5f
    const val MAX = 3.0f
    const val STEP = 0.25f
    const val DEFAULT = 1.0f

    /** [value] snapped to the nearest step inside the range; [DEFAULT] when it is not a finite number. */
    fun clamp(value: Float): Float {
        if (value.isNaN() || value.isInfinite()) return DEFAULT
        val snapped = (value / STEP).roundToInt() * STEP
        return snapped.coerceIn(MIN, MAX)
    }

    /** One step up ([direction] > 0) or down, stopping at the bounds. */
    fun step(value: Float, direction: Int): Float = clamp(clamp(value) + direction.coerceIn(-1, 1) * STEP)

    fun canDecrease(value: Float) = clamp(value) > MIN

    fun canIncrease(value: Float) = clamp(value) < MAX

    /** "x1.0" (or "x1,0" with [comma], for French). */
    fun label(value: Float, comma: Boolean): String {
        val hundredths = (clamp(value) * 100).roundToInt() // 1.25 -> 125
        val whole = hundredths / 100
        val decimals = (hundredths % 100).toString().padStart(2, '0').trimEnd('0').ifEmpty { "0" }
        return "x$whole${if (comma) "," else "."}$decimals"
    }
}

/** Persists the sensitivity next to the role and the language, in the same SharedPreferences. */
class TrackpadStore(private val prefs: SharedPreferences) {
    fun load(): Float = TrackpadSensitivity.clamp(prefs.getFloat(KEY, TrackpadSensitivity.DEFAULT))

    fun save(value: Float) {
        prefs.edit().putFloat(KEY, TrackpadSensitivity.clamp(value)).apply()
    }

    private companion object {
        const val KEY = "trackpad_sensitivity"
    }
}
