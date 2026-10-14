package com.orizonx.client.setup

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class SetupStateTest {
    private class FakeProbe(val dev: Boolean?, val adb: Boolean?, val usb: Boolean?) : SetupProbe {
        override fun devOptions() = dev
        override fun usbDebugging() = adb
        override fun usbPlugged() = usb
    }

    private fun steps(dev: Boolean?, adb: Boolean?, usb: Boolean?) = SetupSteps.read(FakeProbe(dev, adb, usb))

    @Test
    fun readCopiesTheProbeResults() {
        assertEquals(SetupSteps(true, false, null), steps(true, false, null))
    }

    @Test
    fun nothingDoneStartsAtStepOneAndOpensTheGuide() {
        val s = steps(false, false, false)
        assertEquals(1, s.current)
        assertTrue(s.autoOpen)
    }

    @Test
    fun devOptionsOnlyIsAtStepTwo() {
        val s = steps(true, false, false)
        assertEquals(2, s.current)
        assertTrue(s.autoOpen)
    }

    @Test
    fun devAndAdbIsAtStepThreeAndStaysClosed() {
        val s = steps(true, true, false)
        assertEquals(3, s.current)
        assertFalse(s.autoOpen)
    }

    @Test
    fun allThreeDoneMovesToTheTip() {
        val s = steps(true, true, true)
        assertEquals(4, s.current)
        assertFalse(s.autoOpen)
    }

    @Test
    fun nullProbesCountAsNotDoneAndOpenTheGuide() {
        val s = steps(null, null, null)
        assertEquals(1, s.current)
        assertTrue(s.autoOpen)
    }

    @Test
    fun aNullStepIsNotDoneForTheHighlight() {
        assertEquals(1, steps(null, true, true).current)
        assertEquals(2, steps(true, null, true).current)
        assertEquals(3, steps(true, true, null).current)
    }

    @Test
    fun autoOpenOnlyDependsOnUsbDebugging() {
        assertFalse(steps(false, true, false).autoOpen)
        assertTrue(steps(true, null, true).autoOpen)
    }

    @Test
    fun aStepAfterAnUndoneOneStillIsNotCurrent() {
        assertEquals(1, steps(false, true, true).current)
    }
}
