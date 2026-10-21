package com.orizonx.client.actions

import com.orizonx.client.i18n.Lang
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class PerfFormatTest {
    @Test
    fun percent() {
        assertEquals("23 %", PerfFormat.percent(23, Lang.FR))
        assertEquals("23%", PerfFormat.percent(23, Lang.EN))
    }

    @Test
    fun memory() {
        assertEquals("12,3 / 32 Go", PerfFormat.gb(12.3f, 32f, Lang.FR))
        assertEquals("12.3 / 32 GB", PerfFormat.gb(12.3f, 32f, Lang.EN))
        assertEquals("3 / 16 Go", PerfFormat.gb(3.0f, 16.0f, Lang.FR))
        assertEquals("0.5 / 7.9 GB", PerfFormat.gb(0.5f, 7.9f, Lang.EN))
    }

    @Test
    fun frequency() {
        assertEquals("4,1 GHz", PerfFormat.ghz(4.1f, Lang.FR))
        assertEquals("4.1 GHz", PerfFormat.ghz(4.1f, Lang.EN))
        assertEquals("3,0 GHz", PerfFormat.ghz(3.0f, Lang.FR))
    }

    @Test
    fun rates() {
        assertEquals("1,2 Mo/s", PerfFormat.rate(1_250_000, Lang.FR))
        assertEquals("1.2 MB/s", PerfFormat.rate(1_250_000, Lang.EN))
        assertEquals("80 Ko/s", PerfFormat.rate(82_000, Lang.FR))
        assertEquals("80 KB/s", PerfFormat.rate(82_000, Lang.EN))
        assertEquals("500 o/s", PerfFormat.rate(500, Lang.FR))
        assertEquals("500 B/s", PerfFormat.rate(500, Lang.EN))
        assertEquals("0 o/s", PerfFormat.rate(0, Lang.FR))
        assertEquals("0 o/s", PerfFormat.rate(-3, Lang.FR))
        assertEquals("1,0 Mo/s", PerfFormat.rate(1_048_576, Lang.FR))
        // Just under 1 Mo/s must not read "1024 Ko/s".
        assertEquals("1,0 Mo/s", PerfFormat.rate(1_048_575, Lang.FR))
        assertEquals("1023 Ko/s", PerfFormat.rate(1_048_000, Lang.FR))
    }

    @Test
    fun networkScale() {
        assertEquals(5_000_000L, PerfFormat.netScale(3_000_000))
        assertEquals(1024L, PerfFormat.netScale(0))
        assertEquals(1024L, PerfFormat.netScale(1000))
        assertEquals(2000L, PerfFormat.netScale(1500))
        assertEquals(5_000_000L, PerfFormat.netScale(5_000_000))
        assertEquals(10_000_000L, PerfFormat.netScale(5_000_001))
        assertEquals(20_000_000L, PerfFormat.netScale(12_000_000))
        assertEquals(100_000_000L, PerfFormat.netScale(100_000_000))
    }

    @Test
    fun compactOnlyAtOneByOne() {
        assertTrue(PerfFormat.compact(1, 1))
        assertFalse(PerfFormat.compact(2, 1))
        assertFalse(PerfFormat.compact(1, 2))
        assertFalse(PerfFormat.compact(3, 3))
    }

    @Test
    fun percentagesBecomeFractions() {
        assertEquals(listOf(0f, 0.5f, 1f), PerfFormat.fractions(listOf(0, 50, 100)))
        assertEquals(emptyList<Float>(), PerfFormat.fractions(emptyList()))
    }

    @Test
    fun bothNetworkCurvesShareOneScale() {
        // The scale is the next 1/2/5 step above the biggest point of either curve: 3 000 000 -> 5 000 000.
        val s = PerfFormat.netSeries(listOf(0L, 3_000_000L), listOf(500_000L, 1_000_000L))
        assertEquals(listOf(0f, 0.6f), s[0])
        assertEquals(listOf(0.1f, 0.2f), s[1])
        // Nothing moving: the minimum scale, flat curves.
        assertEquals(listOf(listOf(0f, 0f), listOf(0f)), PerfFormat.netSeries(listOf(0L, 0L), listOf(0L)))
        assertEquals(listOf(emptyList<Float>(), emptyList<Float>()), PerfFormat.netSeries(emptyList(), emptyList()))
    }
}
