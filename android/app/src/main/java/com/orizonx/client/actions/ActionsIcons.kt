package com.orizonx.client.actions

import kotlin.math.roundToInt

/** Speaker pictogram: muted, then one to three sound bars by volume. */
enum class VolumeIcon { MUTE, LOW, MEDIUM, HIGH }

/** Sun pictogram: crossed out at 0 %, then a small, medium and big sun. */
enum class BrightnessIcon { NONE, LOW, MEDIUM, HIGH }

/** Wi-Fi pictogram: one, two or three lit arcs. */
enum class WifiIcon { WEAK, MEDIUM, STRONG }

/**
 * Which pictogram each level shows. Pure and unit-tested; the UI maps the enums to drawables.
 * Percentages are the displayed (rounded) ones, so the icon never disagrees with the "34 %" next to it.
 */
object ActionsIcons {
    private fun percent(value: Float): Int = (value.coerceIn(0f, 1f) * 100).roundToInt()

    /** Muted -> MUTE; else below 34 % LOW, below 67 % MEDIUM, otherwise HIGH. */
    fun volume(volume: Float, muted: Boolean): VolumeIcon = when {
        muted -> VolumeIcon.MUTE
        percent(volume) < 34 -> VolumeIcon.LOW
        percent(volume) < 67 -> VolumeIcon.MEDIUM
        else -> VolumeIcon.HIGH
    }

    /** 0 % -> NONE; else below 34 % LOW, below 67 % MEDIUM, otherwise HIGH. */
    fun brightness(value: Float): BrightnessIcon = when {
        percent(value) == 0 -> BrightnessIcon.NONE
        percent(value) < 34 -> BrightnessIcon.LOW
        percent(value) < 67 -> BrightnessIcon.MEDIUM
        else -> BrightnessIcon.HIGH
    }

    /**
     * Wi-Fi off -> STRONG (the tile dims it); on but not connected (no [signal]) -> WEAK;
     * otherwise above 66 STRONG, above 33 MEDIUM, else WEAK.
     */
    fun wifi(on: Boolean, signal: Int?): WifiIcon = when {
        !on -> WifiIcon.STRONG
        signal == null -> WifiIcon.WEAK
        signal > 66 -> WifiIcon.STRONG
        signal > 33 -> WifiIcon.MEDIUM
        else -> WifiIcon.WEAK
    }
}
