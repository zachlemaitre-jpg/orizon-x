package com.orizonx.client

import android.util.Log
import android.view.Surface
import com.orizonx.client.protocol.ActionsStateMessage
import com.orizonx.client.protocol.FrameReader
import com.orizonx.client.protocol.FrameWriter
import com.orizonx.client.protocol.PcMessage
import com.orizonx.client.protocol.Protocol
import com.orizonx.client.protocol.ProtocolException
import com.orizonx.client.protocol.TabletMessage
import com.orizonx.client.stats.LatencyTracker
import com.orizonx.client.video.DecoderFailure
import com.orizonx.client.video.DecoderUnavailable
import com.orizonx.client.video.VideoDecoder
import java.io.IOException
import java.net.Socket
import java.net.SocketException
import java.util.concurrent.Executors
import java.util.concurrent.ScheduledExecutorService
import java.util.concurrent.TimeUnit
import java.util.concurrent.atomic.AtomicReference

/** Physical screen in landscape, sent in HELLO. */
data class ScreenInfo(val width: Int, val height: Int, val dpi: Int)

/** One PC connection: handshake, decode loop, ping and stats timers. [run] blocks until the connection ends. */
class Session(
    private val socket: Socket,
    private val surface: Surface,
    private val screen: ScreenInfo,
    private val listener: Listener,
) {
    interface Listener {
        fun onStreaming(config: PcMessage.Config, decoder: String)
        fun onStats(window: LatencyTracker.Window)
    }

    private val tracker = LatencyTracker()
    private val timerFailure = AtomicReference<Exception?>(null)

    @Volatile private var inputSink: ((TabletMessage.Input) -> Unit)? = null

    /** Queues an INPUT frame on the net-writer thread (never blocks the caller); no-op outside [run]. */
    fun sendInput(message: TabletMessage.Input) {
        inputSink?.invoke(message)
    }

    fun run() {
        socket.tcpNoDelay = true
        socket.soTimeout = READ_TIMEOUT_MS // le PC répond aux PING toutes les 500 ms : 5 s de silence = PC figé
        val reader = FrameReader(socket.getInputStream())
        val writer = FrameWriter(socket.getOutputStream())
        val timers = Executors.newSingleThreadScheduledExecutor { Thread(it, "net-writer") }
        inputSink = { message -> runCatching { timers.execute { runCatching { writer.write(message) } } } }
        var decoder: VideoDecoder? = null
        var config: PcMessage.Config? = null
        try {
            writer.write(TabletMessage.Hello(screen.width, screen.height, screen.dpi))
            timers.every(PING_INTERVAL_MS, initialDelayMs = 0) { writer.write(TabletMessage.Ping(nowUs())) }
            timers.every(STATS_INTERVAL_MS, initialDelayMs = STATS_INTERVAL_MS) { sendStats(writer) }
            try {
                while (true) {
                    when (val message = reader.read()) {
                        is PcMessage.Config -> {
                            validate(message)
                            decoder?.release()
                            decoder = null
                            val fresh = createDecoder(message)
                            decoder = fresh
                            config = message
                            writer.write(TabletMessage.KeyframeRequest)
                            listener.onStreaming(message, fresh.description)
                        }
                        is PcMessage.Video -> {
                            val current = decoder ?: continue // vidéo reçue avant CONFIG : ignorée
                            try {
                                if (!current.submit(message)) tracker.onFrameDropped()
                            } catch (e: DecoderFailure) {
                                Log.w(TAG, "recréation du décodeur", e)
                                current.release()
                                decoder = null
                                val fresh = createDecoder(config!!)
                                decoder = fresh
                                writer.write(TabletMessage.KeyframeRequest)
                                // Une keyframe perdue = écran noir jusqu'à la suivante : on la redonne au nouveau décodeur.
                                if (message.isKey || message.isCodecConfig) {
                                    try {
                                        fresh.submit(message)
                                    } catch (e2: DecoderFailure) {
                                        throw DecoderUnavailable("échec juste après recréation : ${e2.message}", e2)
                                    }
                                } else {
                                    tracker.onFrameDropped()
                                }
                            }
                        }
                        is PcMessage.Pong -> tracker.onPong(message.tTabUs, message.tPcUs, nowUs())
                        is ActionsStateMessage -> Unit // Actions role: handled by the Actions UI (later task)
                    }
                }
            } catch (e: SocketException) {
                // Une tâche périodique a fermé la socket : remonter sa vraie cause si ce n'est pas une erreur réseau.
                timerFailure.get()?.let { if (it !is IOException) throw it }
                throw e
            }
        } finally {
            inputSink = null
            timers.shutdownNow()
            runCatching { timers.awaitTermination(TIMER_STOP_MS, TimeUnit.MILLISECONDS) }
            try {
                decoder?.release()
            } catch (e: Exception) {
                Log.w(TAG, "libération du décodeur", e)
            } finally {
                runCatching { socket.close() }
            }
        }
    }

    private fun validate(config: PcMessage.Config) {
        if (config.codec != Protocol.CODEC_H264) throw ProtocolException("codec non supporté : ${config.codec}")
        if (config.width <= 0 || config.height <= 0 || config.fps <= 0) {
            throw ProtocolException("CONFIG invalide : $config")
        }
    }

    private fun createDecoder(config: PcMessage.Config) =
        VideoDecoder(config, surface) { ptsUs, renderedNanos -> tracker.onFrameRendered(ptsUs, renderedNanos / 1000) }

    private fun sendStats(writer: FrameWriter) {
        val window = tracker.takeWindow()
        listener.onStats(window)
        writer.write(
            TabletMessage.Stats(
                fps = window.fps,
                latencyAvgUs = window.latencyAvgUs,
                latencyMaxUs = window.latencyMaxUs,
                dropped = window.dropped,
                rttUs = window.rttUs,
            ),
        )
    }

    /** Runs [action] at a fixed rate; any failure is recorded and closes the socket so the reader loop ends. */
    private fun ScheduledExecutorService.every(periodMs: Long, initialDelayMs: Long, action: () -> Unit) {
        scheduleAtFixedRate({
            try {
                action()
            } catch (e: Exception) {
                Log.w(TAG, "tâche périodique en échec, fermeture de la session", e)
                timerFailure.compareAndSet(null, e)
                runCatching { socket.close() }
            }
        }, initialDelayMs, periodMs, TimeUnit.MILLISECONDS)
    }

    private companion object {
        const val TAG = "Session"
        const val READ_TIMEOUT_MS = 5000
        const val PING_INTERVAL_MS = 500L
        const val STATS_INTERVAL_MS = 1000L
        const val TIMER_STOP_MS = 100L
        fun nowUs() = System.nanoTime() / 1000
    }
}
