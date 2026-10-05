package com.orizonx.client

import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import com.orizonx.client.protocol.PcMessage
import com.orizonx.client.stats.LatencyTracker

sealed interface ConnectionState {
    data class Waiting(val reason: String?) : ConnectionState
    data class Streaming(val width: Int, val height: Int) : ConnectionState
}

data class HudData(
    val fps: Int,
    val avgMs: Double,
    val maxMs: Double,
    val p50Ms: Int,
    val p99Ms: Int,
    val offsetMs: Double?,
    val decoder: String,
)

/** Compose-observable app state. Written from background threads, read by the UI. */
class UiModel : Session.Listener {
    var state by mutableStateOf<ConnectionState>(ConnectionState.Waiting(null))
        private set
    var hud by mutableStateOf<HudData?>(null)
        private set
    var hudVisible by mutableStateOf(false)
        private set

    /** Last reason shown on the waiting screen; kept while the screen fades out. */
    var waitingReason by mutableStateOf<String?>(null)
        private set

    /** Size of the last stream; kept after a disconnect so the letterbox doesn't jump. */
    var lastStream by mutableStateOf<ConnectionState.Streaming?>(null)
        private set

    /** Incremented each time a new streaming session starts (not on a mid-session CONFIG). */
    var streamGeneration by mutableIntStateOf(0)
        private set

    @Volatile private var decoderName = ""

    fun showWaiting(reason: String?) {
        waitingReason = reason
        state = ConnectionState.Waiting(reason)
        hud = null
    }

    fun toggleHud() {
        hudVisible = !hudVisible
    }

    override fun onStreaming(config: PcMessage.Config, decoder: String) {
        decoderName = decoder
        val streaming = ConnectionState.Streaming(config.width, config.height)
        lastStream = streaming
        if (state !is ConnectionState.Streaming) streamGeneration++
        state = streaming
    }

    override fun onStats(window: LatencyTracker.Window) {
        hud = HudData(
            fps = window.fps,
            avgMs = window.latencyAvgUs / 1000.0,
            maxMs = window.latencyMaxUs / 1000.0,
            p50Ms = window.p50Ms,
            p99Ms = window.p99Ms,
            offsetMs = window.offsetUs?.let { it / 1000.0 },
            decoder = decoderName,
        )
    }
}
