package com.orizonx.client.backdrop

import com.orizonx.client.backdrop.BackdropMotion.PATCHES
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNotEquals
import org.junit.Assert.assertTrue
import org.junit.Test

class BackdropMotionTest {
    private val times = (0..3000).map { it * 0.5f } // 25 minutes in half-second steps

    @Test
    fun thereAreThreeToFiveUnevenPatches() {
        assertTrue(PATCHES.size in 3..5)
        assertTrue("sizes differ", PATCHES.map { it.baseRadius }.toSet().size > 2)
        assertTrue("places differ", PATCHES.map { it.baseX to it.baseY }.toSet().size == PATCHES.size)
    }

    @Test
    fun periodsAreBetween25And60Seconds() {
        for (p in PATCHES) {
            for (period in listOf(p.periodX, p.periodY, p.periodRadius)) assertTrue("$period", period in 25f..60f)
        }
    }

    @Test
    fun amplitudesAreAbout8To12PercentOfTheScreen() {
        for (p in PATCHES) {
            assertTrue(p.ampX in 0.08f..0.12f)
            assertTrue(p.ampY in 0.08f..0.12f)
        }
    }

    @Test
    fun positionsStayWithinTheirAmplitude() {
        for (p in PATCHES) {
            for (t in times) {
                assertEquals(p.baseX, BackdropMotion.x(p, t), p.ampX + 1e-4f)
                assertEquals(p.baseY, BackdropMotion.y(p, t), p.ampY + 1e-4f)
            }
        }
    }

    @Test
    fun radiusBreathesByAtMostFivePercent() {
        for (p in PATCHES) {
            for (t in times) {
                val r = BackdropMotion.radius(p, t)
                assertTrue(r >= p.baseRadius * 0.95f - 1e-4f && r <= p.baseRadius * 1.05f + 1e-4f)
            }
        }
    }

    @Test
    fun everyAxisIsPeriodic() {
        for (p in PATCHES) {
            for (t in listOf(0f, 3.7f, 12.5f, 40f)) {
                assertEquals(BackdropMotion.x(p, t), BackdropMotion.x(p, t + p.periodX), 1e-3f)
                assertEquals(BackdropMotion.y(p, t), BackdropMotion.y(p, t + p.periodY), 1e-3f)
                assertEquals(BackdropMotion.radius(p, t), BackdropMotion.radius(p, t + p.periodRadius), 1e-3f)
            }
        }
    }

    @Test
    fun motionIsSmoothSoItNeverJumps() {
        // Over one second, even the fastest patch moves under 2.5 % of the screen.
        for (p in PATCHES) {
            for (t in times) {
                assertTrue(Math.abs(BackdropMotion.x(p, t + 1f) - BackdropMotion.x(p, t)) < 0.025f)
                assertTrue(Math.abs(BackdropMotion.y(p, t + 1f) - BackdropMotion.y(p, t)) < 0.025f)
            }
        }
    }

    @Test
    fun patchesAreMovingNotFrozen() {
        for (p in PATCHES) {
            val xs = times.map { BackdropMotion.x(p, it) }
            assertTrue(xs.max() - xs.min() > p.ampX)
            assertNotEquals(BackdropMotion.x(p, 0f), BackdropMotion.x(p, p.periodX / 4), 1e-3f)
        }
    }

    @Test
    fun colourIsPureGreyAndDark() {
        for (p in PATCHES) {
            val r = (p.argb shr 16 and 0xFF).toInt()
            val g = (p.argb shr 8 and 0xFF).toInt()
            val b = (p.argb and 0xFF).toInt()
            assertTrue("hue in ${p.argb.toString(16)}", maxOf(r, g, b) - minOf(r, g, b) <= 4)
            assertTrue(maxOf(r, g, b) <= 0x30)
        }
    }
}
