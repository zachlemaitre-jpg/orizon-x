package com.orizonx.client.actions

import kotlin.math.max
import kotlin.math.min

/** How the "now playing" block is laid out: the cover's side (dp) and whether the cover sits above the text. */
data class NowPlayingPlan(val coverSide: Float, val vertical: Boolean)

/**
 * Sizes the cover of the now-playing block from the room the block gives it (the inner size, padding already taken off).
 * Pure, in dp, so it is unit-tested.
 */
object NowPlayingLayout {
    /** Today's cover side: the smallest it gets. */
    const val MIN_COVER = 112f

    /** The text column (title, artist, app and the media keys) keeps at least this much width beside the cover. */
    const val TEXT_MIN_WIDTH = 180f

    const val GAP = 16f

    /** Side of the Spotify icon shown in the block's top-right corner. */
    const val APP_ICON_DP = 22f

    /** The media comes from Spotify when the source app's name says so (case ignored). */
    fun isSpotify(app: String): Boolean = app.contains("spotify", ignoreCase = true)

    /** In the vertical layout the cover takes at most this share of the height, the text and keys need the rest. */
    const val VERTICAL_COVER_SHARE = 0.6f

    /**
     * - Beside the text (the usual layout): the cover is as tall as the block's inner height, but never so wide that the
     *   text column drops under [TEXT_MIN_WIDTH]; never under [MIN_COVER].
     * - Taller than wide (as soon as the height exceeds the width) and room for a cover of at least [MIN_COVER]: a square
     *   cover above the text, as wide as the block (at most [VERTICAL_COVER_SHARE] of its height).
     */
    fun plan(innerWidth: Float, innerHeight: Float): NowPlayingPlan {
        val width = max(innerWidth, 0f)
        val height = max(innerHeight, 0f)
        if (height > width) {
            val cover = min(width, height * VERTICAL_COVER_SHARE)
            if (cover >= MIN_COVER) return NowPlayingPlan(cover, vertical = true)
        }
        val widthCap = width - GAP - TEXT_MIN_WIDTH
        return NowPlayingPlan(max(MIN_COVER, min(height, widthCap)), vertical = false)
    }
}
