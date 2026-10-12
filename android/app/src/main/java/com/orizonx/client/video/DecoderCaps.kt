package com.orizonx.client.video

import android.media.MediaCodecInfo
import android.media.MediaCodecList
import android.media.MediaFormat
import com.orizonx.client.protocol.VideoCaps
import kotlin.math.roundToInt

/** Whether the device's H.264 decoder handles [width]x[height] at [fps]. Injectable so the selection is testable. */
fun interface DecoderCapabilities {
    fun supports(width: Int, height: Int, fps: Int): Boolean
}

/** Finds the biggest size (and rate) the hardware AVC decoder can play, to announce it in DEVICE_INFO. */
object DecoderCaps {
    private val SCALES = doubleArrayOf(0.85, 0.75, 2.0 / 3.0, 0.5)
    private val RATES = intArrayOf(60, 30)

    /** Native size first, then scaled copies on multiples of 8 (aspect kept, duplicates dropped). */
    fun candidates(nativeWidth: Int, nativeHeight: Int): List<VideoCaps.Size> {
        val scaled = SCALES.map { scale ->
            VideoCaps.Size(roundToEight(nativeWidth * scale), roundToEight(nativeHeight * scale))
        }
        return (listOf(VideoCaps.Size(nativeWidth, nativeHeight)) + scaled).distinct()
    }

    private fun roundToEight(value: Double): Int = (value / 8).roundToInt().coerceAtLeast(1) * 8

    /**
     * First candidate supported at 60 fps, else the first supported at 30 fps; null when there is none, no decoder
     * ([capabilities] null) or the check throws (the field is then omitted and the PC keeps its defaults).
     */
    fun best(nativeWidth: Int, nativeHeight: Int, capabilities: DecoderCapabilities?): VideoCaps? {
        if (capabilities == null) return null
        return try {
            val sizes = candidates(nativeWidth, nativeHeight)
            for (fps in RATES) {
                val size = sizes.firstOrNull { capabilities.supports(it.width, it.height, fps) }
                if (size != null) return VideoCaps(size.width, size.height, fps)
            }
            null
        } catch (_: Exception) {
            null
        }
    }

    /** Hardware decoder: flagged accelerated, or (if the platform does not say so) not one of the known software codecs. */
    fun isHardware(accelerated: Boolean, softwareOnly: Boolean, name: String): Boolean =
        !softwareOnly && (accelerated || !(name.startsWith("OMX.google.") || name.startsWith("c2.android.")))

    /** The device's own hardware AVC decoders (any of them may satisfy a size); null when there is none. */
    fun system(): DecoderCapabilities? {
        val infos = try {
            MediaCodecList(MediaCodecList.REGULAR_CODECS).codecInfos.filter { info ->
                !info.isEncoder &&
                    info.supportedTypes.any { it.equals(MediaFormat.MIMETYPE_VIDEO_AVC, ignoreCase = true) } &&
                    isHardware(info.isHardwareAccelerated, info.isSoftwareOnly, info.name)
            }
        } catch (_: Exception) {
            emptyList<MediaCodecInfo>()
        }
        if (infos.isEmpty()) return null
        return DecoderCapabilities { width, height, fps ->
            infos.any { info ->
                try {
                    info.getCapabilitiesForType(MediaFormat.MIMETYPE_VIDEO_AVC).videoCapabilities
                        ?.areSizeAndRateSupported(width, height, fps.toDouble()) == true
                } catch (_: Exception) {
                    false
                }
            }
        }
    }
}
