package com.orizonx.client.actions

/**
 * Rate-limits a slider's values: at most one send per [minIntervalMs] while dragging
 * (50 ms = 20 Hz), and the final value is always sent on release. Pure; time comes from [clock] (ms).
 * Not thread-safe: use from the UI thread.
 */
class ActionThrottle(
    private val minIntervalMs: Long = 50,
    private val clock: () -> Long,
    private val send: (Float) -> Unit,
) {
    private var lastSentAt: Long? = null

    /** A value during the drag: sent only if the last send is old enough, otherwise dropped (a later one supersedes it). */
    fun onChange(value: Float) {
        val now = clock()
        val last = lastSentAt
        if (last == null || now - last >= minIntervalMs) {
            lastSentAt = now
            send(value)
        }
    }

    /** The finger was lifted: always sends [value], then re-arms for the next drag. */
    fun onRelease(value: Float) {
        send(value)
        lastSentAt = null
    }
}
