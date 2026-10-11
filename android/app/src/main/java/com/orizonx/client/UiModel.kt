package com.orizonx.client

import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import androidx.compose.ui.graphics.ImageBitmap
import com.orizonx.client.actions.ArtworkDecoder
import com.orizonx.client.protocol.PcMessage
import com.orizonx.client.stats.LatencyTracker
import org.json.JSONObject
import java.util.concurrent.Executors

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

    /** Role chosen on the waiting screen (persisted by the activity). */
    var role by mutableStateOf(DeviceRole.SCREEN)
        private set

    /** Role announced to the PC on the open connection; null while no PC is connected. */
    var connectedRole by mutableStateOf<DeviceRole?>(null)
        private set

    /** Latest ACTIONS_STATE payload from the PC (consumed by the Actions UI); null until received or after a disconnect. */
    var actionsState by mutableStateOf<JSONObject?>(null)
        private set

    /** Last cover art received, decoded and keyed by the id the PC announced in `now_playing.artwork`. */
    var artwork by mutableStateOf<Pair<String, ImageBitmap>?>(null)
        private set

    @Volatile private var decoderName = ""

    /** Bumped on each disconnect so a decode still in flight cannot resurrect the previous session's cover. */
    @Volatile private var artworkEpoch = 0
    private val artworkDecoder = Executors.newSingleThreadExecutor { runnable ->
        Thread(runnable, "artwork-decoder").apply { isDaemon = true }
    }

    fun chooseRole(value: DeviceRole) {
        role = value
    }

    override fun onConnected(role: DeviceRole) {
        connectedRole = role
    }

    override fun onActionsState(json: JSONObject) {
        actionsState = json
    }

    override fun onMediaArtwork(id: String, bytes: ByteArray) {
        val epoch = artworkEpoch
        runCatching {
            artworkDecoder.execute {
                val bitmap = runCatching { ArtworkDecoder.decode(bytes) }.getOrNull() ?: return@execute
                if (epoch == artworkEpoch) artwork = id to bitmap
            }
        }
    }

    fun showWaiting(reason: String?) {
        connectedRole = null
        actionsState = null
        artworkEpoch++
        artwork = null
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
