package com.orizonx.client.actions

import org.junit.Assert.assertEquals
import org.junit.Test

class ActionThrottleTest {
    private var now = 1_000L
    private val sent = mutableListOf<Float>()
    private val throttle = ActionThrottle(minIntervalMs = 50, clock = { now }, send = { sent += it })

    @Test
    fun firstValueIsSentImmediately() {
        throttle.onChange(0.1f)
        assertEquals(listOf(0.1f), sent)
    }

    @Test
    fun valuesInsideTheIntervalAreDropped() {
        throttle.onChange(0.1f)
        now += 10
        throttle.onChange(0.2f)
        now += 39
        throttle.onChange(0.3f)
        assertEquals(listOf(0.1f), sent)
    }

    @Test
    fun valueIsSentOnceTheIntervalHasElapsed() {
        throttle.onChange(0.1f)
        now += 50
        throttle.onChange(0.2f)
        assertEquals(listOf(0.1f, 0.2f), sent)
    }

    @Test
    fun rateNeverExceedsTwentyPerSecond() {
        for (i in 0 until 1000) { // a value every ms for one second
            throttle.onChange(i / 1000f)
            now += 1
        }
        assertEquals(20, sent.size)
    }

    @Test
    fun releaseAlwaysSendsTheFinalValue() {
        throttle.onChange(0.1f)
        now += 5
        throttle.onChange(0.5f) // dropped
        throttle.onRelease(0.5f)
        assertEquals(listOf(0.1f, 0.5f), sent)
    }

    @Test
    fun releaseSendsEvenWithoutAnyPriorChange() {
        throttle.onRelease(0.9f)
        assertEquals(listOf(0.9f), sent)
    }

    @Test
    fun nextDragStartsFreshAfterRelease() {
        throttle.onChange(0.1f)
        throttle.onRelease(0.2f)
        throttle.onChange(0.3f) // same millisecond, but a new gesture
        assertEquals(listOf(0.1f, 0.2f, 0.3f), sent)
    }
}
