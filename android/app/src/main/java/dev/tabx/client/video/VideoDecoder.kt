package dev.tabx.client.video

import android.media.MediaCodec
import android.media.MediaCodecInfo
import android.media.MediaFormat
import android.os.Build
import android.os.Handler
import android.os.HandlerThread
import android.os.Process
import android.util.Log
import android.view.Surface
import dev.tabx.client.protocol.PcMessage
import java.util.concurrent.LinkedBlockingQueue
import java.util.concurrent.TimeUnit

/** Raised when the decoder must be recreated (codec error, stalled input, oversized frame). */
class DecoderFailure(message: String, cause: Throwable? = null) : Exception(message, cause)

/** Raised when no decoder can be created or configured. Deliberately not an IOException: it is not a network error. */
class DecoderUnavailable(message: String, cause: Throwable? = null) : Exception(message, cause)

/**
 * Hardware H.264 decoder rendering straight to [surface], in async mode.
 * [submit] and [release] must be called from the same thread (the network reader).
 * [onFrameRendered] receives the pts (µs) and the System.nanoTime() of actual display.
 */
class VideoDecoder(
    config: PcMessage.Config,
    surface: Surface,
    onFrameRendered: (ptsUs: Long, renderedNanos: Long) -> Unit,
) {
    private val thread = HandlerThread("codec", Process.THREAD_PRIORITY_DISPLAY).apply { start() }
    private val handler = Handler(thread.looper)
    private val freeInputs = LinkedBlockingQueue<Int>()
    private val codec: MediaCodec = try {
        MediaCodec.createDecoderByType(MIME)
    } catch (e: Exception) {
        thread.quitSafely()
        throw DecoderUnavailable("aucun décodeur H.264 disponible", e)
    }
    @Volatile private var failure: MediaCodec.CodecException? = null
    private var waitingForKey = true

    /** Codec name and low-latency status, shown in the HUD. */
    val description: String = try {
        start(config, surface, onFrameRendered)
    } catch (e: Exception) {
        codec.release()
        thread.quitSafely()
        throw DecoderUnavailable("configuration du décodeur impossible : ${e.message ?: e.javaClass.simpleName}", e)
    }

    private fun start(
        config: PcMessage.Config,
        surface: Surface,
        onFrameRendered: (ptsUs: Long, renderedNanos: Long) -> Unit,
    ): String {
        val lowLatency = codec.codecInfo.getCapabilitiesForType(MIME)
            .isFeatureSupported(MediaCodecInfo.CodecCapabilities.FEATURE_LowLatency)
        val format = MediaFormat.createVideoFormat(MIME, config.width, config.height).apply {
            setInteger(MediaFormat.KEY_PRIORITY, 0) // temps réel
            setInteger(MediaFormat.KEY_FRAME_RATE, config.fps) // cible de débit pour le mode temps réel
            setInteger(MediaFormat.KEY_MAX_INPUT_SIZE, maxOf(config.width * config.height, MIN_INPUT_SIZE))
            // Demandés même sans FEATURE_LowLatency : les décodeurs qui ne les gèrent pas les ignorent.
            setInteger(MediaFormat.KEY_LOW_LATENCY, 1)
            setInteger(EXYNOS_LOW_LATENCY, 1)
        }
        codec.setCallback(object : MediaCodec.Callback() {
            override fun onInputBufferAvailable(codec: MediaCodec, index: Int) {
                freeInputs.offer(index)
            }

            override fun onOutputBufferAvailable(codec: MediaCodec, index: Int, info: MediaCodec.BufferInfo) {
                try {
                    // Heure de présentation = maintenant : prochain vsync, la frame la plus récente gagne.
                    // (Avec `true`, le pts, horloge du PC, servirait d'heure de présentation.)
                    codec.releaseOutputBuffer(index, System.nanoTime())
                } catch (e: IllegalStateException) {
                    Log.w(TAG, "sortie ignorée (codec arrêté ou en erreur)", e)
                }
            }

            override fun onError(codec: MediaCodec, e: MediaCodec.CodecException) {
                if (e.isTransient) {
                    Log.w(TAG, "erreur transitoire du décodeur", e)
                    return
                }
                failure = e
                freeInputs.offer(WAKE_UP) // réveille submit() s'il attend un buffer
            }

            override fun onOutputFormatChanged(codec: MediaCodec, format: MediaFormat) {
                Log.i(TAG, "format de sortie : $format")
            }
        }, handler)
        codec.setOnFrameRenderedListener({ _, ptsUs, nanos -> onFrameRendered(ptsUs, nanos) }, handler)
        codec.configure(format, surface, null, 0)
        codec.start()
        val description = codec.name + if (lowLatency) " (low-latency)" else ""
        val vendorParameters = if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.S) codec.supportedVendorParameters else emptyList()
        Log.i(TAG, "décodeur $description, ${config.width}x${config.height}@${config.fps}, paramètres vendeur : $vendorParameters")
        return description
    }

    /** Queues one frame, blocking until an input buffer is free. Returns false if the frame was skipped. */
    fun submit(frame: PcMessage.Video): Boolean {
        checkFailure()
        if (waitingForKey && !frame.isKey && !frame.isCodecConfig) return false
        val index = freeInputs.poll(INPUT_TIMEOUT_MS, TimeUnit.MILLISECONDS)
            ?: throw DecoderFailure("décodeur bloqué : aucun buffer libre depuis $INPUT_TIMEOUT_MS ms")
        checkFailure() // réveillé par onError
        val flags = when {
            frame.isCodecConfig -> MediaCodec.BUFFER_FLAG_CODEC_CONFIG
            frame.isKey -> MediaCodec.BUFFER_FLAG_KEY_FRAME
            else -> 0
        }
        try {
            val buffer = codec.getInputBuffer(index) ?: throw DecoderFailure("buffer d'entrée $index indisponible")
            if (frame.data.size > buffer.capacity()) {
                throw DecoderFailure("frame de ${frame.data.size} octets > buffer de ${buffer.capacity()}")
            }
            buffer.clear()
            buffer.put(frame.data)
            codec.queueInputBuffer(index, 0, frame.data.size, frame.ptsUs, flags)
        } catch (e: IllegalStateException) {
            throw DecoderFailure("décodeur dans un état invalide", e)
        }
        if (frame.isKey) waitingForKey = false
        return true
    }

    fun release() {
        runCatching { codec.stop() }
        runCatching { codec.release() }
        thread.quitSafely()
    }

    private fun checkFailure() {
        failure?.let { throw DecoderFailure("erreur du décodeur : ${it.diagnosticInfo}", it) }
    }

    private companion object {
        const val MIME = MediaFormat.MIMETYPE_VIDEO_AVC
        const val INPUT_TIMEOUT_MS = 500L
        const val MIN_INPUT_SIZE = 2 * 1024 * 1024
        const val WAKE_UP = -1
        const val EXYNOS_LOW_LATENCY = "vendor.rtc-ext-dec-low-latency.enable" // clé vendeur Exynos, ignorée ailleurs
        const val TAG = "VideoDecoder"
    }
}
