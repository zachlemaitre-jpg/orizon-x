package com.orizonx.client.frame

/** Pure sizing helpers for the Frame screen. */
object FrameGeometry {
    /**
     * Power-of-two `inSampleSize` for an image of [width] x [height] so that the decoded bitmap fits in [maxWidth] x [maxHeight]
     * (the largest size worth keeping). 1 when it already fits or when a size is unknown.
     */
    fun sampleSize(width: Int, height: Int, maxWidth: Int, maxHeight: Int): Int {
        if (width <= 0 || height <= 0 || maxWidth <= 0 || maxHeight <= 0) return 1
        var sample = 1
        while ((width / sample > maxWidth || height / sample > maxHeight) && sample < MAX_SAMPLE) sample *= 2
        return sample
    }

    /**
     * Scale to apply to a `TextureView` (around its centre) so that a video of [videoWidth] x [videoHeight] covers the
     * [viewWidth] x [viewHeight] view ([fit] false: Crop) or is seen whole inside it ([fit] true: Fit). A TextureView
     * stretches the video over the whole view, so (1, 1) shows it stretched; the returned (x, y) undo that. Unknown sizes give (1, 1).
     */
    fun videoScale(viewWidth: Int, viewHeight: Int, videoWidth: Int, videoHeight: Int, fit: Boolean): Pair<Float, Float> {
        if (viewWidth <= 0 || viewHeight <= 0 || videoWidth <= 0 || videoHeight <= 0) return 1f to 1f
        val view = viewWidth.toDouble() / viewHeight
        val video = videoWidth.toDouble() / videoHeight
        val videoIsWider = video > view
        // Crop of a wide video, or Fit of a narrow one: the width is scaled; otherwise the height.
        return if (videoIsWider != fit) (video / view).toFloat() to 1f else 1f to (view / video).toFloat()
    }

    private const val MAX_SAMPLE = 64
}
