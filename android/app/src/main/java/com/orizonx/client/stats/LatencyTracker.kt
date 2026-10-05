package com.orizonx.client.stats

import kotlin.math.ceil

/**
 * Clock sync (offset of the smallest-RTT sample among recent ping/pongs) and per-frame latency stats.
 * Times are microseconds; the offset converts PC time to tablet time. Latency is recorded only after
 * [minClockSamples] PONGs, so warm-up frames stay out of the session percentiles. Thread-safe.
 */
class LatencyTracker(private val clockSamples: Int = 16, private val minClockSamples: Int = 4) {

    init {
        require(clockSamples >= 1 && minClockSamples in 1..clockSamples) { "clockSamples >= 1 et 1 <= minClockSamples <= clockSamples requis" }
    }

    data class Window(
        val fps: Int,
        val latencyAvgUs: Long,
        val latencyMaxUs: Long,
        val dropped: Long,
        val rttUs: Long,
        val p50Ms: Int,
        val p99Ms: Int,
        val offsetUs: Long?,
    )

    private class ClockSample(val rttUs: Long, val offsetUs: Long)

    private val samples = ArrayDeque<ClockSample>()
    private val histogram = IntArray(HISTOGRAM_MAX_MS + 1)
    private var histogramCount = 0L
    private var pongCount = 0
    private var offsetUs: Long? = null
    private var lastRttUs = 0L
    private var frames = 0
    private var latencyCount = 0
    private var latencySumUs = 0L
    private var latencyMaxUs = 0L
    private var dropped = 0L

    @Synchronized
    fun onPong(tTabSentUs: Long, tPcUs: Long, tTabReceivedUs: Long) {
        val rtt = tTabReceivedUs - tTabSentUs
        if (rtt < 0) return // stale or foreign timestamp
        samples.addLast(ClockSample(rtt, tTabSentUs + rtt / 2 - tPcUs))
        if (samples.size > clockSamples) samples.removeFirst()
        pongCount++
        offsetUs = samples.minBy { it.rttUs }.offsetUs
        lastRttUs = rtt
    }

    @Synchronized
    fun onFrameRendered(ptsUs: Long, renderedUs: Long) {
        frames++
        if (pongCount < minClockSamples) return // clock not settled yet: keep warm-up frames out of the session percentiles
        val offset = offsetUs ?: return
        val latency = renderedUs - (ptsUs + offset)
        latencyCount++
        latencySumUs += latency
        latencyMaxUs = maxOf(latencyMaxUs, latency)
        histogram[(latency / 1000).coerceIn(0, HISTOGRAM_MAX_MS.toLong()).toInt()]++
        histogramCount++
    }

    @Synchronized
    fun onFrameDropped() {
        dropped++
    }

    /** Stats since the previous call (percentiles cover the whole session), then resets the window. */
    @Synchronized
    fun takeWindow(): Window {
        val window = Window(
            fps = frames,
            latencyAvgUs = if (latencyCount > 0) latencySumUs / latencyCount else 0,
            latencyMaxUs = latencyMaxUs,
            dropped = dropped,
            rttUs = lastRttUs,
            p50Ms = percentileMs(0.50),
            p99Ms = percentileMs(0.99),
            offsetUs = offsetUs,
        )
        frames = 0
        latencyCount = 0
        latencySumUs = 0
        latencyMaxUs = 0
        dropped = 0
        return window
    }

    private fun percentileMs(quantile: Double): Int {
        if (histogramCount == 0L) return 0
        val target = ceil(quantile * histogramCount).toLong().coerceAtLeast(1)
        var cumulative = 0L
        for (ms in histogram.indices) {
            cumulative += histogram[ms]
            if (cumulative >= target) return ms
        }
        return HISTOGRAM_MAX_MS
    }

    companion object {
        const val HISTOGRAM_MAX_MS = 500
    }
}
