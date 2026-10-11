package com.orizonx.client.actions

import org.junit.Assert.assertEquals
import org.junit.Test

class ArtworkDecoderTest {
    @Test
    fun smallImagesAreNotSubsampled() {
        assertEquals(1, ArtworkDecoder.sampleSize(300, 300, 512))
        assertEquals(1, ArtworkDecoder.sampleSize(512, 512, 512))
    }

    @Test
    fun sampleSizeIsThePowerOfTwoThatBringsTheLargestSideUnderTheLimit() {
        assertEquals(2, ArtworkDecoder.sampleSize(513, 100, 512))
        assertEquals(2, ArtworkDecoder.sampleSize(1024, 1024, 512))
        assertEquals(4, ArtworkDecoder.sampleSize(1025, 1025, 512))
        assertEquals(8, ArtworkDecoder.sampleSize(3000, 2000, 512))
    }

    @Test
    fun widthAndHeightBothCount() {
        assertEquals(2, ArtworkDecoder.sampleSize(100, 900, 512))
    }

    @Test
    fun invalidDimensionsGiveOne() {
        assertEquals(1, ArtworkDecoder.sampleSize(0, 0, 512))
        assertEquals(1, ArtworkDecoder.sampleSize(-1, 10, 512))
    }
}
