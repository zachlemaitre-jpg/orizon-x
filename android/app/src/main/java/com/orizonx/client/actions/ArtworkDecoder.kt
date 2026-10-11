package com.orizonx.client.actions

import android.graphics.Bitmap
import android.graphics.BitmapFactory
import androidx.compose.ui.graphics.ImageBitmap
import androidx.compose.ui.graphics.asImageBitmap

/** Decodes the JPEG/PNG of a MEDIA_ARTWORK message, downsampled so its largest side is at most [MAX_EDGE] px. */
object ArtworkDecoder {
    const val MAX_EDGE = 512

    /** Smallest power of two that brings the largest side of a [width] x [height] image to [maxEdge] px or less. */
    fun sampleSize(width: Int, height: Int, maxEdge: Int): Int {
        if (width <= 0 || height <= 0 || maxEdge <= 0) return 1
        val largest = maxOf(width, height)
        var sample = 1
        while ((largest + sample - 1) / sample > maxEdge) sample *= 2
        return sample
    }

    /** Null when the bytes are not a decodable image. Call off the UI thread. */
    fun decode(bytes: ByteArray): ImageBitmap? {
        val bounds = BitmapFactory.Options().apply { inJustDecodeBounds = true }
        BitmapFactory.decodeByteArray(bytes, 0, bytes.size, bounds)
        if (bounds.outWidth <= 0 || bounds.outHeight <= 0) return null
        val options = BitmapFactory.Options().apply {
            inSampleSize = sampleSize(bounds.outWidth, bounds.outHeight, MAX_EDGE)
            inPreferredConfig = Bitmap.Config.ARGB_8888
        }
        return BitmapFactory.decodeByteArray(bytes, 0, bytes.size, options)?.asImageBitmap()
    }
}
