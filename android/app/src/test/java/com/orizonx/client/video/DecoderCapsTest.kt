package com.orizonx.client.video

import com.orizonx.client.protocol.VideoCaps
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Test

class DecoderCapsTest {
    private val nativeW = 2800
    private val nativeH = 1752

    @Test
    fun candidatesStartAtNativeThenScaleDownOnMultiplesOfEightKeepingAspect() {
        val expected = listOf(
            VideoCaps.Size(2800, 1752), // native, as is
            VideoCaps.Size(2384, 1488), // x0.85
            VideoCaps.Size(2104, 1312), // x0.75
            VideoCaps.Size(1864, 1168), // x2/3
            VideoCaps.Size(1400, 880), //  x0.5
        )
        assertEquals(expected, DecoderCaps.candidates(nativeW, nativeH))
    }

    @Test
    fun nativeSizeIsKeptAsIsEvenWhenNotAMultipleOfEight() {
        assertEquals(VideoCaps.Size(1920, 1080), DecoderCaps.candidates(1920, 1080).first())
    }

    @Test
    fun nativeSizeIsKeptWhenSupportedAtSixtyFps() {
        val caps = DecoderCaps.best(nativeW, nativeH) { _, _, _ -> true }
        assertEquals(VideoCaps(nativeW, nativeH, 60), caps)
    }

    @Test
    fun fallsBackToTheFirstCandidateSupportedAtSixtyFps() {
        val caps = DecoderCaps.best(nativeW, nativeH) { w, _, fps -> fps == 60 && w <= 2200 }
        assertEquals(VideoCaps(2104, 1312, 60), caps)
    }

    @Test
    fun usesThirtyFpsOnlyWhenNoSizeDoesSixty() {
        val caps = DecoderCaps.best(nativeW, nativeH) { w, _, fps -> fps == 30 && w <= 1920 }
        assertEquals(VideoCaps(1864, 1168, 30), caps)
    }

    @Test
    fun sixtyFpsAtASmallerSizeBeatsThirtyFpsAtNative() {
        val caps = DecoderCaps.best(nativeW, nativeH) { w, _, fps -> fps == 30 || w <= 1400 }
        assertEquals(VideoCaps(1400, 880, 60), caps)
    }

    @Test
    fun noSupportedSizeOmitsTheField() {
        assertNull(DecoderCaps.best(nativeW, nativeH) { _, _, _ -> false })
    }

    @Test
    fun anExceptionOmitsTheField() {
        assertNull(DecoderCaps.best(nativeW, nativeH) { _, _, _ -> throw IllegalStateException("codec") })
    }

    @Test
    fun noDecoderOmitsTheField() {
        assertNull(DecoderCaps.best(nativeW, nativeH, null))
    }

    @Test
    fun hardwareRuleFallsBackToTheNameWhenNotFlaggedAccelerated() {
        assertEquals(false, DecoderCaps.isHardware(accelerated = false, softwareOnly = false, name = "c2.android.avc.decoder"))
        assertEquals(false, DecoderCaps.isHardware(accelerated = false, softwareOnly = false, name = "OMX.google.h264.decoder"))
        assertEquals(true, DecoderCaps.isHardware(accelerated = false, softwareOnly = false, name = "c2.qti.avc.decoder"))
        assertEquals(true, DecoderCaps.isHardware(accelerated = true, softwareOnly = false, name = "c2.exynos.h264.decoder"))
        assertEquals(false, DecoderCaps.isHardware(accelerated = true, softwareOnly = true, name = "c2.qti.avc.decoder"))
    }
}
