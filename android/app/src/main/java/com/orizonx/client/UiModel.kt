package com.orizonx.client

import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import androidx.compose.ui.graphics.ImageBitmap
import com.orizonx.client.actions.ArtworkDecoder
import com.orizonx.client.actions.ImageLru
import com.orizonx.client.frame.FrameController
import com.orizonx.client.i18n.Lang
import com.orizonx.client.i18n.LangPref
import com.orizonx.client.i18n.Msg
import com.orizonx.client.protocol.PcMessage
import com.orizonx.client.stats.LatencyTracker
import org.json.JSONObject
import java.util.concurrent.Executors

sealed interface ConnectionState {
    data class Waiting(val reason: Msg?) : ConnectionState
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
class UiModel(val frame: FrameController) : Session.Listener {
    var state by mutableStateOf<ConnectionState>(ConnectionState.Waiting(null))
        private set
    var hud by mutableStateOf<HudData?>(null)
        private set
    var hudVisible by mutableStateOf(false)
        private set

    /** Last reason shown on the waiting screen; kept while the screen fades out. */
    var waitingReason by mutableStateOf<Msg?>(null)
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

    /** Language choice made with the pill (persisted by the activity). */
    var langPref by mutableStateOf(LangPref.SYSTEM)
        private set

    /** Language code of the system (first locale), refreshed on configuration change. */
    var systemLanguage by mutableStateOf("en")
        private set

    /** Interface language in use: the choice, or the system language while the choice is "system". */
    val lang: Lang get() = LangPref.effective(langPref, systemLanguage)

    /** Role announced to the PC on the open connection; null while no PC is connected. */
    var connectedRole by mutableStateOf<DeviceRole?>(null)
        private set

    /** Latest ACTIONS_STATE payload from the PC (consumed by the Actions UI); null until received or after a disconnect. */
    var actionsState by mutableStateOf<JSONObject?>(null)
        private set

    /**
     * Decoded images received over MEDIA_ARTWORK, keyed by the sha1 id the PC announced (`now_playing.artwork` for covers,
     * `context.icon` for app icons): an immutable view of an [ImageLru] of 16 entries.
     */
    var images by mutableStateOf<Map<String, ImageBitmap>>(emptyMap())
        private set

    @Volatile private var decoderName = ""

    private val imageCache = ImageLru<ImageBitmap>()

    /** Bumped on each disconnect so a decode still in flight cannot resurrect the previous session's images. */
    @Volatile private var artworkEpoch = 0
    private val artworkDecoder = Executors.newSingleThreadExecutor { runnable ->
        Thread(runnable, "artwork-decoder").apply { isDaemon = true }
    }

    fun chooseRole(value: DeviceRole) {
        role = value
    }

    fun chooseLangPref(value: LangPref) {
        langPref = value
    }

    fun updateSystemLanguage(value: String) {
        systemLanguage = value
    }

    override fun onConnected(role: DeviceRole) {
        frame.reset() // session start: no leftover file of a previous run
        connectedRole = role
    }

    override fun onFrameState(state: PcMessage.FrameState) = frame.onState(state)

    override fun onFrameFile(chunk: PcMessage.FrameFile) = frame.onFile(chunk)

    override fun onActionsState(json: JSONObject) {
        actionsState = json
    }

    override fun onMediaArtwork(id: String, bytes: ByteArray) {
        val epoch = artworkEpoch
        runCatching {
            artworkDecoder.execute {
                val bitmap = runCatching { ArtworkDecoder.decode(bytes) }.getOrNull() ?: return@execute
                synchronized(imageCache) {
                    if (epoch == artworkEpoch) {
                        imageCache.put(id, bitmap)
                        images = imageCache.snapshot()
                    }
                }
            }
        }
    }

    fun showWaiting(reason: Msg?) {
        connectedRole = null
        frame.reset() // session end: forget the queue and empty the cache
        actionsState = null
        synchronized(imageCache) {
            artworkEpoch++
            imageCache.clear()
            images = emptyMap()
        }
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
