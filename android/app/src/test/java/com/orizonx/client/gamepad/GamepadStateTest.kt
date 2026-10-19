package com.orizonx.client.gamepad

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class GamepadStateTest {
    // --- Sticks -------------------------------------------------------------------------

    @Test
    fun centreAndDeadZoneGiveZero() {
        assertEquals(0 to 0, GamepadMath.stick(0f, 0f, 100f))
        assertEquals(0 to 0, GamepadMath.stick(9f, 0f, 100f))
        assertEquals(0 to 0, GamepadMath.stick(-6f, 7f, 100f)) // 9.2 % of the radius
        assertEquals(0 to 0, GamepadMath.stick(5f, 5f, 0f))
    }

    @Test
    fun justOutsideTheDeadZoneIsLive() {
        val (x, _) = GamepadMath.stick(10f, 0f, 100f)
        assertEquals(3277, x) // round(0.10 * 32767)
    }

    @Test
    fun edgesGiveTheFullAxisRange() {
        assertEquals(32767 to 0, GamepadMath.stick(100f, 0f, 100f))
        assertEquals(-32767 to 0, GamepadMath.stick(-100f, 0f, 100f))
    }

    @Test
    fun valueIsRoundedFractionOf32767() {
        assertEquals(16384, GamepadMath.stick(50f, 0f, 100f).first) // round(16383.5)
        assertEquals(24575, GamepadMath.stick(75f, 0f, 100f).first)
    }

    @Test
    fun offsetsPastTheRadiusAreClamped() {
        assertEquals(32767 to 0, GamepadMath.stick(250f, 0f, 100f))
        val (x, y) = GamepadMath.stick(300f, 400f, 100f) // 500 away, along (0.6, -0.8) once Y is inverted
        assertEquals(19660, x)
        assertEquals(-26214, y)
    }

    @Test
    fun yIsPositiveTowardsTheTopOfTheScreen() {
        assertEquals(0 to 32767, GamepadMath.stick(0f, -100f, 100f)) // finger above the centre
        assertEquals(0 to -32767, GamepadMath.stick(0f, 100f, 100f))
    }

    @Test
    fun theDeadZoneIsRadialNotPerAxis() {
        // 8 on each axis is 11.3 % of the radius: outside the zone, both axes are live.
        val (x, y) = GamepadMath.stick(8f, 8f, 100f)
        assertEquals(2621, x)
        assertEquals(-2621, y)
    }

    @Test
    fun diagonalNeverExceedsTheAxisRange() {
        val (x, y) = GamepadMath.stick(100f, -100f, 100f)
        assertTrue(x in 0..32767 && y in 0..32767)
    }

    // --- D-pad -------------------------------------------------------------------------------

    private val up = XboxButton.DPAD_UP
    private val down = XboxButton.DPAD_DOWN
    private val left = XboxButton.DPAD_LEFT
    private val right = XboxButton.DPAD_RIGHT

    @Test
    fun dpadHasEightDirections() {
        assertEquals(right, GamepadMath.dpad(100f, 0f, 100f))
        assertEquals(up or right, GamepadMath.dpad(70f, -70f, 100f))
        assertEquals(up, GamepadMath.dpad(0f, -100f, 100f))
        assertEquals(up or left, GamepadMath.dpad(-70f, -70f, 100f))
        assertEquals(left, GamepadMath.dpad(-100f, 0f, 100f))
        assertEquals(down or left, GamepadMath.dpad(-70f, 70f, 100f))
        assertEquals(down, GamepadMath.dpad(0f, 100f, 100f))
        assertEquals(down or right, GamepadMath.dpad(70f, 70f, 100f))
    }

    @Test
    fun dpadSectorsAre45DegreesWide() {
        // 20 degrees above the right axis is still plain right, 25 degrees is up-right.
        fun at(degrees: Double): Int {
            val r = Math.toRadians(degrees)
            return GamepadMath.dpad((100 * Math.cos(r)).toFloat(), (-100 * Math.sin(r)).toFloat(), 150f)
        }
        assertEquals(right, at(20.0))
        assertEquals(up or right, at(25.0))
        assertEquals(up or right, at(65.0))
        assertEquals(up, at(70.0))
        assertEquals(right, at(-20.0))
        assertEquals(down or right, at(-25.0))
    }

    @Test
    fun dpadCentreOrZeroRadiusPressesNothing() {
        assertEquals(0, GamepadMath.dpad(0f, 0f, 100f))
        assertEquals(0, GamepadMath.dpad(10f, 10f, 100f))
        assertEquals(0, GamepadMath.dpad(50f, 0f, 0f))
    }

    // --- Button bits -------------------------------------------------------------------------------

    @Test
    fun buttonBitsFollowXusb() {
        assertEquals(0x0001, XboxButton.DPAD_UP)
        assertEquals(0x0002, XboxButton.DPAD_DOWN)
        assertEquals(0x0004, XboxButton.DPAD_LEFT)
        assertEquals(0x0008, XboxButton.DPAD_RIGHT)
        assertEquals(0x0010, XboxButton.START)
        assertEquals(0x0020, XboxButton.BACK)
        assertEquals(0x0040, XboxButton.LEFT_THUMB)
        assertEquals(0x0080, XboxButton.RIGHT_THUMB)
        assertEquals(0x0100, XboxButton.LEFT_SHOULDER)
        assertEquals(0x0200, XboxButton.RIGHT_SHOULDER)
        assertEquals(0x0400, XboxButton.GUIDE)
        assertEquals(0x1000, XboxButton.A)
        assertEquals(0x2000, XboxButton.B)
        assertEquals(0x4000, XboxButton.X)
        assertEquals(0x8000, XboxButton.Y)
    }

    @Test
    fun controlsMergeIntoOneReport() {
        val c = GamepadControls()
        assertEquals(GamepadReport.NEUTRAL, c.report())
        c.setButton(XboxButton.A, true)
        c.setButton(XboxButton.LEFT_SHOULDER, true)
        c.setDpad(XboxButton.DPAD_UP or XboxButton.DPAD_LEFT)
        c.setLeftTrigger(true)
        c.setRightStick(100, -200)
        c.setLeftStick(-5, 6)
        assertEquals(
            GamepadReport(buttons = 0x1000 or 0x0100 or 0x0001 or 0x0004, lt = 255, rt = 0, lx = -5, ly = 6, rx = 100, ry = -200),
            c.report(),
        )
        c.setButton(XboxButton.A, false)
        c.setLeftTrigger(false)
        c.setRightTrigger(true)
        c.setDpad(0)
        assertEquals(GamepadReport(buttons = 0x0100, rt = 255, lx = -5, ly = 6, rx = 100, ry = -200), c.report())
    }

    @Test
    fun dpadBitsCannotCarryOtherButtons() {
        val c = GamepadControls()
        c.setDpad(0xFFFF)
        assertEquals(XboxButton.DPAD_MASK, c.report().buttons)
    }

    @Test
    fun resetGivesTheNeutralReport() {
        val c = GamepadControls()
        c.setButton(XboxButton.B, true)
        c.setLeftTrigger(true)
        c.setRightStick(1, 2)
        c.reset()
        assertEquals(GamepadReport.NEUTRAL, c.report())
    }

    @Test
    fun triggersAreZeroOr255() {
        val c = GamepadControls()
        c.setLeftTrigger(true)
        c.setRightTrigger(true)
        assertEquals(255, c.report().lt)
        assertEquals(255, c.report().rt)
    }

    // --- Throttle -----------------------------------------------------------------------------------

    private var now = 1000L
    private val sent = mutableListOf<GamepadReport>()
    private val throttle = GamepadThrottle({ now }) { sent += it }

    private fun report(buttons: Int) = GamepadReport(buttons = buttons)

    @Test
    fun firstReportGoesOutAtOnce() {
        throttle.submit(report(1))
        assertEquals(listOf(report(1)), sent)
    }

    @Test
    fun reportsCloserThan8msWaitAndTheLastOneWins() {
        throttle.submit(report(1))
        now += 3
        throttle.submit(report(2))
        now += 2
        throttle.submit(report(3))
        assertEquals(listOf(report(1)), sent)
        now += 2 // 7 ms after the first
        throttle.tick()
        assertEquals(listOf(report(1)), sent)
        now += 1 // 8 ms
        throttle.tick()
        assertEquals(listOf(report(1), report(3)), sent)
    }

    @Test
    fun aSubmitAfter8msGoesOutImmediately() {
        throttle.submit(report(1))
        now += 8
        throttle.submit(report(2))
        assertEquals(listOf(report(1), report(2)), sent)
    }

    @Test
    fun identicalReportsAreNotRepeated() {
        throttle.submit(report(1))
        now += 20
        throttle.submit(report(1))
        throttle.tick()
        assertEquals(listOf(report(1)), sent)
    }

    @Test
    fun aChangeThatIsRevertedWhileWaitingSendsNothing() {
        throttle.submit(report(1))
        now += 2
        throttle.submit(report(2))
        now += 2
        throttle.submit(report(1))
        now += 10
        throttle.tick()
        assertEquals(listOf(report(1)), sent)
    }

    @Test
    fun noPendingReportMeansTickDoesNothing() {
        throttle.tick()
        assertTrue(sent.isEmpty())
    }

    @Test
    fun sendNowBypassesTheRateAndDropsWhatWaits() {
        throttle.submit(report(1))
        now += 1
        throttle.submit(report(2))
        now += 1
        throttle.sendNow(GamepadReport.NEUTRAL)
        now += 20
        throttle.tick()
        assertEquals(listOf(report(1), GamepadReport.NEUTRAL), sent)
    }

    // --- Double tap -----------------------------------------------------------------------------------

    @Test
    fun twoTapsWithin300msClickTheStick() {
        val d = DoubleTapDetector({ now })
        assertFalse(d.onTouchEnd(wasTap = true))
        now += 150
        assertTrue(d.onTouchEnd(wasTap = true))
        // The pair is used up: a third tap starts over.
        now += 100
        assertFalse(d.onTouchEnd(wasTap = true))
    }

    @Test
    fun slowTapsOrDraggedTouchesDoNotClick() {
        val d = DoubleTapDetector({ now })
        d.onTouchEnd(true)
        now += 300
        assertFalse(d.onTouchEnd(true))
        now += 100
        assertFalse(d.onTouchEnd(false)) // a drag breaks the pair
        now += 100
        assertFalse(d.onTouchEnd(true))
    }
}
