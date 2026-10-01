package dev.tabx.client.video

import android.media.MediaCodec
import android.media.MediaCodecInfo
import android.media.MediaFormat
import android.os.Handler
import android.os.HandlerThread
import android.util.Log
import android.view.Surface
import dev.tabx.client.protocol.PcMessage
import java.util.concurrent.LinkedBlockingQueue
import java.util.concurrent.TimeUnit

/** Raised when the decoder must be recreated (codec error or stalled input). */
class DecoderFailure(message: String, cause: Throwable? = null) : Exception(message, cause)

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
    private val thread = HandlerThread("codec").apply { start() }
    private val handler = Handler(thread.looper)
    private val freeInputs = LinkedBlockingQueue<Int>()
    private val codec = MediaCodec.createDecoderByType(MIME)
    @Volatile private var failure: MediaCodec.CodecException? = null
    private var waitingForKey = true

    /** Codec name and low-latency status, shown in the HUD. */
    val description: String

    init {
        val lowLatency = codec.codecInfo.getCapabilitiesForType(MIME)
            .isFeatureSupported(MediaCodecInfo.CodecCapabilities.FEATURE_LowLatency)
        val format = MediaFormat.createVideoFormat(MIME, config.width, config.height).apply {
            setInteger(MediaFormat.KEY_PRIORITY, 0) // temps réel
            setInteger(MediaFormat.KEY_MAX_INPUT_SIZE, config.width * config.height)
            if (lowLatency) setInteger(MediaFormat.KEY_LOW_LATENCY, 1)
        }
        codec.setCallback(object : MediaCodec.Callback() {
            override fun onInputBufferAvailable(codec: MediaCodec, index: Int) {
                freeInputs.offer(index)
            }

            override fun onOutputBufferAvailable(codec: MediaCodec, index: Int, info: MediaCodec.BufferInfo) {
                codec.releaseOutputBuffer(index, true) // affichage immédiat, sans attendre le pts
            }

            override fun onError(codec: MediaCodec, e: MediaCodec.CodecException) {
                if (e.isTransient) Log.w(TAG, "erreur transitoire du décodeur", e) else failure = e
            }

            override fun onOutputFormatChanged(codec: MediaCodec, format: MediaFormat) {}
        }, handler)
        codec.setOnFrameRenderedListener({ _, ptsUs, nanos -> onFrameRendered(ptsUs, nanos) }, handler)
        codec.configure(format, surface, null, 0)
        codec.start()
        description = codec.name + if (lowLatency) " (low-latency)" else ""
    }

    /** Queues one frame, blocking until an input buffer is free. Returns false if the frame was skipped. */
    fun submit(frame: PcMessage.Video): Boolean {
        failure?.let { throw DecoderFailure("erreur du décodeur : ${it.diagnosticInfo}", it) }
        if (waitingForKey && !frame.isKey && !frame.isCodecConfig) return false
        if (frame.isKey) waitingForKey = false
        val index = freeInputs.poll(INPUT_TIMEOUT_MS, TimeUnit.MILLISECONDS)
            ?: throw DecoderFailure("décodeur bloqué : aucun buffer libre depuis $INPUT_TIMEOUT_MS ms")
        val flags = when {
            frame.isCodecConfig -> MediaCodec.BUFFER_FLAG_CODEC_CONFIG
            frame.isKey -> MediaCodec.BUFFER_FLAG_KEY_FRAME
            else -> 0
        }
        try {
            val buffer = codec.getInputBuffer(index) ?: throw DecoderFailure("buffer d'entrée $index indisponible")
            buffer.clear()
            buffer.put(frame.data)
            codec.queueInputBuffer(index, 0, frame.data.size, frame.ptsUs, flags)
        } catch (e: IllegalStateException) {
            throw DecoderFailure("décodeur dans un état invalide", e)
        }
        return true
    }

    fun release() {
        runCatching { codec.stop() }
        codec.release()
        thread.quitSafely()
    }

    private companion object {
        const val MIME = MediaFormat.MIMETYPE_VIDEO_AVC
        const val INPUT_TIMEOUT_MS = 500L
        const val TAG = "VideoDecoder"
    }
}
