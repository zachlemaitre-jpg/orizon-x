package com.orizonx.client.frame

import com.orizonx.client.protocol.PcMessage
import kotlin.math.abs

/**
 * Frame mode decisions, with no Android type so they can be tested on the JVM. Not thread-safe: the owner serialises calls.
 *
 * Every event returns the [Effect]s the owner must carry out (send an action, delete a file...). What is shown is read from
 * [current]. The PC keeps one file ahead: finishing an item asks for the next one, and the queue normally already holds it.
 */
class FramePlayer {
    sealed interface Effect {
        data object SendNext : Effect
        data class SendFailed(val file: Long) : Effect
        data class SendPause(val paused: Boolean) : Effect
        data class SendFit(val fit: String) : Effect
        data class SendInterval(val seconds: Int) : Effect

        /** The file was shown (or failed): delete it. */
        data class Release(val id: Long) : Effect

        /** [item] is now the one on screen. */
        data class Show(val item: FrameItem) : Effect
    }

    var current: FrameItem? = null
        private set
    var queue: List<FrameItem> = emptyList()
        private set
    var status: String = "ok"
        private set
    var intervalS: Int = 30
        private set
    var fit: String = "crop"
        private set
    var paused: Boolean = false
        private set

    /** Time the current image has been shown (not counting pauses). */
    var elapsedMs: Long = 0
        private set

    private var epoch: Long? = null

    /** The current item is finished but the next one has not arrived: it stays on screen until it does. */
    private var awaitingNext = false

    /** FRAME_STATE: the PC's settings and status. A new epoch (folder change) forgets what was shown and queued. */
    fun onState(state: PcMessage.FrameState): List<Effect> {
        if (epoch != state.epoch) {
            current = null
            queue = emptyList()
            elapsedMs = 0
            awaitingNext = false
        }
        epoch = state.epoch
        status = state.status
        intervalS = state.intervalS
        fit = state.fit
        paused = state.paused
        return emptyList()
    }

    /** A file was completely received. */
    fun onItemReady(item: FrameItem): List<Effect> {
        val old = current
        if (old == null) {
            show(item)
            return listOf(Effect.Show(item))
        }
        if (awaitingNext) {
            show(item)
            return listOf(Effect.Release(old.id), Effect.Show(item))
        }
        queue = queue + item
        return emptyList()
    }

    /** The store dropped a file (out of order): tell the PC, which then sends the next one. */
    fun onFileRejected(id: Long): List<Effect> = listOf(Effect.SendFailed(id))

    /** Time passed; only an unpaused image counts. */
    fun onTick(dtMs: Long): List<Effect> {
        val item = current ?: return emptyList()
        if (!item.isImage || paused || awaitingNext) return emptyList()
        elapsedMs += dtMs
        return if (elapsedMs >= intervalS * 1000L) finish() else emptyList()
    }

    fun onVideoEnded(): List<Effect> = if (current?.isVideo == true) finish() else emptyList()

    fun onNextTapped(): List<Effect> = finish()

    /** The current item cannot be shown: report it, drop it and move on (the PC sends a replacement on `frame.failed`). */
    fun onPlaybackFailed(): List<Effect> {
        val old = current ?: return emptyList()
        val effects = mutableListOf<Effect>(Effect.SendFailed(old.id), Effect.Release(old.id))
        awaitingNext = false
        val next = queue.firstOrNull()
        if (next == null) {
            current = null
            elapsedMs = 0
        } else {
            queue = queue.drop(1)
            show(next)
            effects += Effect.Show(next)
        }
        return effects
    }

    fun onPauseTapped(): List<Effect> {
        paused = !paused
        return listOf(Effect.SendPause(paused))
    }

    fun onFitTapped(): List<Effect> {
        fit = if (fit == "fit") "crop" else "fit"
        return listOf(Effect.SendFit(fit))
    }

    /** Moves the interval one step along [INTERVALS] (+1 longer, -1 shorter), staying inside the list. */
    fun onIntervalStep(delta: Int): List<Effect> {
        val at = INTERVALS.indexOf(intervalS).takeIf { it >= 0 }
            ?: INTERVALS.indices.minBy { abs(INTERVALS[it] - intervalS) }
        val target = INTERVALS[(at + delta).coerceIn(0, INTERVALS.lastIndex)]
        if (target == intervalS) return emptyList()
        intervalS = target
        return listOf(Effect.SendInterval(target))
    }

    private fun show(item: FrameItem) {
        current = item
        elapsedMs = 0
        awaitingNext = false
    }

    /** The shown item is done (timer, end of video or Next): move to the next one, or wait for it while keeping the old one. */
    private fun finish(): List<Effect> {
        val old = current ?: return emptyList()
        if (awaitingNext) return emptyList()
        val next = queue.firstOrNull()
        if (next == null) {
            awaitingNext = true
            return listOf(Effect.SendNext)
        }
        queue = queue.drop(1)
        show(next)
        return listOf(Effect.Release(old.id), Effect.SendNext, Effect.Show(next))
    }

    companion object {
        /** Display times offered by the PC window and the control bar, in seconds. */
        val INTERVALS = listOf(5, 10, 30, 60, 300, 900, 3600)
    }
}
