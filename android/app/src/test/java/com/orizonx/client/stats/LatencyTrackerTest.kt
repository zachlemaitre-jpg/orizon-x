package com.orizonx.client.stats

import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Test

class LatencyTrackerTest {

    @Test
    fun offsetFromSinglePong() {
        val tracker = LatencyTracker()
        tracker.onPong(tTabSentUs = 1_000, tPcUs = 50_000, tTabReceivedUs = 1_200) // rtt 200
        assertEquals(1_000L + 100 - 50_000, tracker.takeWindow().offsetUs)
    }

    @Test
    fun keepsOffsetOfSmallestRtt() {
        val tracker = LatencyTracker()
        tracker.onPong(1_000, 50_000, 1_200) // rtt 200 -> offset -48_900
        tracker.onPong(2_000, 51_000, 2_600) // rtt 600 -> ignored
        assertEquals(-48_900L, tracker.takeWindow().offsetUs)
        tracker.onPong(3_000, 52_000, 3_100) // rtt 100 -> offset -48_950
        assertEquals(-48_950L, tracker.takeWindow().offsetUs)
    }

    @Test
    fun oldClockSamplesLeaveTheWindow() {
        val tracker = LatencyTracker(clockSamples = 2, minClockSamples = 1)
        tracker.onPong(0, 0, 100) // rtt 100, sera évincé
        tracker.onPong(1_000, 0, 1_400) // rtt 400 -> offset 1_200
        tracker.onPong(2_000, 0, 2_300) // rtt 300 -> offset 2_150
        assertEquals(2_150L, tracker.takeWindow().offsetUs)
    }

    @Test
    fun latencyStatsAndPercentiles() {
        val tracker = LatencyTracker(minClockSamples = 1)
        tracker.onPong(0, 0, 0) // offset 0
        tracker.onFrameRendered(ptsUs = 1_000, renderedUs = 11_000) // 10 ms
        tracker.onFrameRendered(ptsUs = 2_000, renderedUs = 32_000) // 30 ms
        val window = tracker.takeWindow()
        assertEquals(2, window.fps)
        assertEquals(20_000L, window.latencyAvgUs)
        assertEquals(30_000L, window.latencyMaxUs)
        assertEquals(10, window.p50Ms)
        assertEquals(30, window.p99Ms)
    }

    @Test
    fun framesBeforeClockSyncCountForFpsOnly() {
        val tracker = LatencyTracker()
        tracker.onFrameRendered(0, 5_000)
        val window = tracker.takeWindow()
        assertEquals(1, window.fps)
        assertEquals(0L, window.latencyAvgUs)
        assertNull(window.offsetUs)
    }

    @Test
    fun windowResetsButPercentilesCoverSession() {
        val tracker = LatencyTracker(minClockSamples = 1)
        tracker.onPong(0, 0, 0)
        tracker.onFrameRendered(0, 12_000)
        tracker.onFrameDropped()
        val first = tracker.takeWindow()
        assertEquals(1L, first.dropped)
        val second = tracker.takeWindow()
        assertEquals(0, second.fps)
        assertEquals(0L, second.dropped)
        assertEquals(12, second.p50Ms)
    }

    @Test
    fun latencyIgnoredUntilEnoughPongs() {
        val tracker = LatencyTracker(minClockSamples = 2)
        tracker.onPong(0, 0, 0)
        tracker.onFrameRendered(0, 10_000)
        assertEquals(0L, tracker.takeWindow().latencyAvgUs)
        tracker.onPong(0, 0, 0)
        tracker.onFrameRendered(0, 10_000)
        val window = tracker.takeWindow()
        assertEquals(10_000L, window.latencyAvgUs)
        assertEquals(10, window.p50Ms)
    }

    @Test
    fun negativeRttPongIsIgnored() {
        val tracker = LatencyTracker()
        tracker.onPong(1_000, 50_000, 1_200)
        tracker.onPong(5_000, 0, 4_000) // rtt -1000
        assertEquals(-48_900L, tracker.takeWindow().offsetUs)
    }

    @Test
    fun latencyAbove500MsIsClampedInPercentiles() {
        val tracker = LatencyTracker(minClockSamples = 1)
        tracker.onPong(0, 0, 0)
        tracker.onFrameRendered(0, 900_000)
        val window = tracker.takeWindow()
        assertEquals(900_000L, window.latencyMaxUs)
        assertEquals(500, window.p99Ms)
    }

    @Test
    fun rttIsTheLastMeasured() {
        val tracker = LatencyTracker()
        tracker.onPong(0, 0, 300)
        tracker.onPong(1_000, 0, 1_800)
        assertEquals(800L, tracker.takeWindow().rttUs)
    }
}
