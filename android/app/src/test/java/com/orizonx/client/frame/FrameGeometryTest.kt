package com.orizonx.client.frame

import org.junit.Assert.assertEquals
import org.junit.Test

class FrameGeometryTest {
    @Test
    fun sampleSizeKeepsSmallImages() {
        assertEquals(1, FrameGeometry.sampleSize(1920, 1080, 3840, 2160))
    }

    @Test
    fun sampleSizeIsAPowerOfTwoThatFitsTheLimit() {
        assertEquals(2, FrameGeometry.sampleSize(4000, 3000, 3000, 3000))
        assertEquals(4, FrameGeometry.sampleSize(10_000, 2000, 3000, 3000))
        assertEquals(1, FrameGeometry.sampleSize(3000, 3000, 3000, 3000))
    }

    @Test
    fun sampleSizeToleratesBadInput() {
        assertEquals(1, FrameGeometry.sampleSize(0, 0, 100, 100))
        assertEquals(1, FrameGeometry.sampleSize(5000, 5000, 0, 0))
    }

    @Test
    fun cropScalesTheVideoUpToFillTheView() {
        // 16:9 video in a 1000x1000 view: the height fits, the width overflows
        val (sx, sy) = FrameGeometry.videoScale(1000, 1000, 1920, 1080, fit = false)
        assertEquals(1.7777f, sx, 0.001f)
        assertEquals(1f, sy, 0.001f)
    }

    @Test
    fun fitScalesTheVideoDownToBeSeenWhole() {
        val (sx, sy) = FrameGeometry.videoScale(1000, 1000, 1920, 1080, fit = true)
        assertEquals(1f, sx, 0.001f)
        assertEquals(0.5625f, sy, 0.001f)
    }

    @Test
    fun aVideoWithTheViewsAspectIsLeftAlone() {
        assertEquals(1f to 1f, FrameGeometry.videoScale(1920, 1080, 1280, 720, fit = false))
        assertEquals(1f to 1f, FrameGeometry.videoScale(1920, 1080, 1280, 720, fit = true))
    }

    @Test
    fun anUnknownSizeLeavesTheDefaultStretch() {
        assertEquals(1f to 1f, FrameGeometry.videoScale(0, 0, 1920, 1080, fit = true))
        assertEquals(1f to 1f, FrameGeometry.videoScale(1000, 1000, 0, 0, fit = false))
    }
}
