package com.orizonx.client.claude

/**
 * The two-tap confirmation of "Compact session": the first tap arms it ("Confirm?" is shown for [windowMs]), a second tap
 * inside that window is the one that sends. After the window, or after sending, the next tap arms it again.
 * [clock] is in milliseconds. Pure, so it is unit-tested.
 */
class CompactConfirm(private val clock: () -> Long, private val windowMs: Long = WINDOW_MS) {
    private var armedAt = NEVER

    /** True while the confirmation is showing. */
    fun isArmed(): Boolean = armedAt != NEVER && clock() - armedAt < windowMs

    /** A tap: returns true when it is the confirming second tap (send the action), false when it only armed the button. */
    fun tap(): Boolean {
        if (isArmed()) {
            armedAt = NEVER
            return true
        }
        armedAt = clock()
        return false
    }

    fun cancel() {
        armedAt = NEVER
    }

    companion object {
        const val WINDOW_MS = 3000L
        private const val NEVER = Long.MIN_VALUE
    }
}
