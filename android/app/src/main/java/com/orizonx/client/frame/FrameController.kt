package com.orizonx.client.frame

import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import com.orizonx.client.protocol.PcMessage
import org.json.JSONObject

/** What the Frame screen draws. */
data class FrameView(
    val current: FrameItem? = null,
    val status: String = "ok",
    val folder: String? = null,
    val intervalS: Int = 30,
    val fit: String = "crop",
    val paused: Boolean = false,
)

/**
 * Glue between the network thread, the [FrameStore], the [FramePlayer] and the Frame screen. Methods may be called from any
 * thread; [view] is Compose state. [send] must not block (it queues the ACTION on the writer thread).
 */
class FrameController(private val store: FrameStore, private val send: (JSONObject) -> Unit) {
    private var player = FramePlayer()
    private var epoch: Long? = null
    private var folder: String? = null

    var view by mutableStateOf(FrameView())
        private set

    /** FRAME_STATE from the PC. */
    fun onState(state: PcMessage.FrameState) {
        synchronized(this) {
            if (epoch != state.epoch) {
                epoch = state.epoch
                store.begin(state.epoch) // before the player forgets its items: the store drops the old epoch's files
            }
            folder = state.folder
            run(player.onState(state))
        }
    }

    /** FRAME_FILE chunk from the PC. The disk write happens outside the lock so a tap never waits for it. */
    fun onFile(chunk: PcMessage.FrameFile) {
        val result = store.onChunk(chunk)
        synchronized(this) {
            when (result) {
                is FrameStore.Result.Complete -> run(player.onItemReady(result.item))
                is FrameStore.Result.Rejected -> run(player.onFileRejected(result.id))
                FrameStore.Result.Partial, FrameStore.Result.Stale -> Unit
            }
        }
    }

    /** Session start and end: forget everything and empty the cache. */
    fun reset() {
        synchronized(this) {
            store.clear()
            player = FramePlayer()
            epoch = null
            folder = null
            publish()
        }
    }

    fun tick(dtMs: Long) = locked { it.onTick(dtMs) }

    /** The video of [id] reached its end; ignored when it is no longer the one shown (e.g. the faded-out one). */
    fun videoEnded(id: Long) = locked { if (it.current?.id == id) it.onVideoEnded() else emptyList() }

    /** The item [id] cannot be shown; ignored when it is no longer the current one. */
    fun playbackFailed(id: Long) = locked { if (it.current?.id == id) it.onPlaybackFailed() else emptyList() }

    fun next() = locked { it.onNextTapped() }
    fun togglePause() = locked { it.onPauseTapped() }
    fun toggleFit() = locked { it.onFitTapped() }
    fun stepInterval(delta: Int) = locked { it.onIntervalStep(delta) }

    private fun locked(event: (FramePlayer) -> List<FramePlayer.Effect>) {
        synchronized(this) { run(event(player)) }
    }

    private fun run(effects: List<FramePlayer.Effect>) {
        for (effect in effects) {
            when (effect) {
                is FramePlayer.Effect.Release -> store.release(effect.id)
                is FramePlayer.Effect.Show -> Unit // the screen reads the current item from [view]
                else -> effect.toAction()?.let(send)
            }
        }
        publish()
    }

    private fun publish() {
        view = FrameView(player.current, player.status, folder, player.intervalS, player.fit, player.paused)
    }
}
