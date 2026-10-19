package com.orizonx.client.actions

/** Which Actions cards exist for a state; the screen and the keyboard header share these rules. */
object ControlRules {
    /** The media keys live in the "now playing" card when it is shown, in the Sound card otherwise. */
    fun soundKeys(state: ActionsState): Boolean = state.mediaAvailable && state.nowPlaying == null

    fun hasSound(state: ActionsState): Boolean = state.audio != null || soundKeys(state)
}

/**
 * What stays above the keyboard while it is open: the clock (with the date and the PC battery), the Sound card and the
 * Brightness card, each only when the PC reports it. Nothing else of the tiles.
 */
data class KeyboardTopCards(val clock: Boolean, val sound: Boolean, val brightness: Boolean) {
    val any: Boolean get() = clock || sound || brightness

    companion object {
        fun of(state: ActionsState) = KeyboardTopCards(
            clock = state.clock != null || state.battery != null,
            sound = ControlRules.hasSound(state),
            brightness = state.brightness != null,
        )
    }
}
