package com.orizonx.client.trackpad

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class TrackpadSensitivityTest {
    @Test
    fun rangeAndStep() {
        assertEquals(0.5f, TrackpadSensitivity.MIN, 0f)
        assertEquals(3.0f, TrackpadSensitivity.MAX, 0f)
        assertEquals(0.25f, TrackpadSensitivity.STEP, 0f)
        assertEquals(1.0f, TrackpadSensitivity.DEFAULT, 0f)
    }

    @Test
    fun clampKeepsValuesInRangeOnTheStepGrid() {
        assertEquals(0.5f, TrackpadSensitivity.clamp(0.1f), 0f)
        assertEquals(0.5f, TrackpadSensitivity.clamp(-4f), 0f)
        assertEquals(3.0f, TrackpadSensitivity.clamp(9f), 0f)
        assertEquals(1.25f, TrackpadSensitivity.clamp(1.3f), 0f)
        assertEquals(1.0f, TrackpadSensitivity.clamp(1.0f), 0f)
        assertEquals(1.0f, TrackpadSensitivity.clamp(Float.NaN), 0f)
        assertEquals(1.0f, TrackpadSensitivity.clamp(Float.POSITIVE_INFINITY), 0f)
    }

    @Test
    fun stepMovesByAQuarterAndStopsAtTheBounds() {
        assertEquals(1.25f, TrackpadSensitivity.step(1.0f, +1), 0f)
        assertEquals(0.75f, TrackpadSensitivity.step(1.0f, -1), 0f)
        assertEquals(3.0f, TrackpadSensitivity.step(3.0f, +1), 0f)
        assertEquals(0.5f, TrackpadSensitivity.step(0.5f, -1), 0f)
        assertEquals(0.5f, TrackpadSensitivity.step(0.75f, -1), 0f)
    }

    @Test
    fun fullRangeIsTenStepsFromTheMinimum() {
        var value = TrackpadSensitivity.MIN
        var steps = 0
        while (TrackpadSensitivity.canIncrease(value)) {
            value = TrackpadSensitivity.step(value, +1)
            steps++
        }
        assertEquals(3.0f, value, 0f)
        assertEquals(10, steps)
    }

    @Test
    fun canDecreaseAndIncrease() {
        assertFalse(TrackpadSensitivity.canDecrease(0.5f))
        assertTrue(TrackpadSensitivity.canDecrease(0.75f))
        assertTrue(TrackpadSensitivity.canIncrease(2.75f))
        assertFalse(TrackpadSensitivity.canIncrease(3.0f))
    }

    @Test
    fun labelUsesADotInEnglishAndACommaInFrench() {
        assertEquals("x1.0", TrackpadSensitivity.label(1.0f, comma = false))
        assertEquals("x1,0", TrackpadSensitivity.label(1.0f, comma = true))
        assertEquals("x1.25", TrackpadSensitivity.label(1.25f, comma = false))
        assertEquals("x0,5", TrackpadSensitivity.label(0.5f, comma = true))
        assertEquals("x2.75", TrackpadSensitivity.label(2.75f, comma = false))
        assertEquals("x3.0", TrackpadSensitivity.label(3.0f, comma = false))
    }
}
