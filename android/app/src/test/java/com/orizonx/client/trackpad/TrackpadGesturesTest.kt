package com.orizonx.client.trackpad

import com.orizonx.client.trackpad.TrackpadEffect.Button
import com.orizonx.client.trackpad.TrackpadEffect.Gesture
import com.orizonx.client.trackpad.TrackpadEffect.Move
import com.orizonx.client.trackpad.TrackpadEffect.Scroll
import com.orizonx.client.trackpad.TrackpadEffect.Zoom
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

class TrackpadGesturesTest {
    private var now = 0L
    private val g = TrackpadGestures { now }

    private val leftClick = listOf(Button(right = false, down = true), Button(right = false, down = false))
    private val rightClick = listOf(Button(right = true, down = true), Button(right = true, down = false))

    private fun move1(x: Float, y: Float) = g.pointerMove(1, x, y)

    // --- One finger ----------------------------------------------------------------------

    @Test
    fun fingerInsideTheDeadZoneDoesNotMoveThePointer() {
        g.pointerDown(1, 0f, 0f)
        move1(1f, 1f)
        move1(1.5f, 0f)
        assertTrue(g.flush().isEmpty())
    }

    @Test
    fun movementIsSentFromWhereTheFingerLeftTheDeadZone() {
        g.pointerDown(1, 0f, 0f)
        move1(5f, 0f) // leaves the dead zone: nothing is sent for the first 5 dp
        assertTrue(g.flush().isEmpty())
        move1(15f, 4f)
        assertEquals(listOf(Move(10f, 4f)), g.flush())
    }

    @Test
    fun sensitivityMultipliesTheMove() {
        g.sensitivity = 2.5f
        g.pointerDown(1, 0f, 0f)
        move1(5f, 0f)
        move1(9f, -2f)
        assertEquals(listOf(Move(10f, -5f)), g.flush())
    }

    @Test
    fun movesAreAccumulatedUntilTheFrameFlush() {
        g.pointerDown(1, 0f, 0f)
        move1(5f, 0f)
        move1(6f, 0f)
        move1(8f, 1f)
        move1(9f, 3f)
        assertEquals(listOf(Move(4f, 3f)), g.flush())
        assertTrue(g.flush().isEmpty())
        move1(10f, 3f)
        assertEquals(listOf(Move(1f, 0f)), g.flush())
    }

    @Test
    fun shortStillTouchIsALeftClick() {
        g.pointerDown(1, 50f, 50f)
        now = 120
        assertEquals(leftClick, g.pointerUp(1))
    }

    @Test
    fun slowTouchIsNotAClick() {
        g.pointerDown(1, 50f, 50f)
        now = 200
        assertTrue(g.pointerUp(1).isEmpty())
    }

    @Test
    fun touchThatTravelledTooFarIsNotAClick() {
        g.pointerDown(1, 0f, 0f)
        move1(9f, 0f)
        now = 100
        assertTrue(g.pointerUp(1).isEmpty())
    }

    @Test
    fun smallWobbleStillClicks() {
        g.pointerDown(1, 0f, 0f)
        move1(3f, 0f)
        move1(5f, 2f)
        g.flush()
        now = 100
        assertEquals(leftClick, g.pointerUp(1))
    }

    @Test
    fun pendingMoveIsSentBeforeTheClick() {
        g.pointerDown(1, 0f, 0f)
        move1(3f, 0f)
        move1(6f, 0f)
        now = 100
        assertEquals(listOf<TrackpadEffect>(Move(3f, 0f)) + leftClick, g.pointerUp(1))
    }

    // --- Drag ---------------------------------------------------------------------------------

    @Test
    fun dragSendsMovesAndReleasesOnLift() {
        g.pointerDown(1, 0f, 0f)
        now = 80
        g.pointerUp(1)
        now = 250
        g.pointerDown(1, 10f, 10f)
        assertEquals(listOf(Button(right = false, down = true)), move1(14f, 10f))
        move1(24f, 10f)
        move1(24f, 30f)
        assertEquals(listOf(Move(10f, 20f)), g.flush())
        now = 900
        assertEquals(listOf(Button(right = false, down = false)), g.pointerUp(1))
    }

    @Test
    fun dragIsNotStartedWhenTheSecondTouchComesTooLate() {
        g.pointerDown(1, 0f, 0f)
        now = 80
        g.pointerUp(1)
        now = 80 + 300
        g.pointerDown(1, 10f, 10f)
        assertTrue(move1(20f, 10f).isEmpty())
        move1(30f, 10f)
        assertEquals(listOf(Move(10f, 0f)), g.flush())
        now = 900
        assertTrue(g.pointerUp(1).isEmpty())
    }

    @Test
    fun secondTapRightAfterTheFirstIsAnotherClick() {
        g.pointerDown(1, 0f, 0f)
        now = 80
        assertEquals(leftClick, g.pointerUp(1))
        now = 200
        g.pointerDown(1, 0f, 0f)
        now = 270
        assertEquals(leftClick, g.pointerUp(1))
    }

    @Test
    fun cancelLiftsAHeldDrag() {
        g.pointerDown(1, 0f, 0f)
        now = 80
        g.pointerUp(1)
        now = 200
        g.pointerDown(1, 0f, 0f)
        move1(10f, 0f)
        assertEquals(listOf(Button(right = false, down = false)), g.cancel())
        assertTrue(g.cancel().isEmpty())
    }

    // --- Two fingers --------------------------------------------------------------------------

    @Test
    fun twoFingerTapIsARightClick() {
        g.pointerDown(1, 100f, 100f)
        now = 60
        g.pointerDown(2, 160f, 100f)
        now = 180
        assertTrue(g.pointerUp(1).isEmpty())
        assertEquals(rightClick, g.pointerUp(2))
    }

    @Test
    fun twoFingerTapNeedsBothFingersDownWithin150ms() {
        g.pointerDown(1, 100f, 100f)
        now = 151
        g.pointerDown(2, 160f, 100f)
        now = 200
        g.pointerUp(1)
        assertTrue(g.pointerUp(2).isEmpty())
    }

    @Test
    fun twoFingerTapMustBeShortAndStill() {
        g.pointerDown(1, 100f, 100f)
        g.pointerDown(2, 160f, 100f)
        now = 250
        g.pointerUp(1)
        assertTrue(g.pointerUp(2).isEmpty()) // 250 ms is too slow

        now = 1000
        g.pointerDown(1, 100f, 100f)
        g.pointerDown(2, 160f, 100f)
        g.pointerMove(2, 160f, 111f) // 11 dp
        now = 1100
        g.pointerUp(1)
        assertTrue(g.pointerUp(2).isEmpty())
    }

    @Test
    fun twoFingerTapDoesNotMoveThePointer() {
        g.pointerDown(1, 100f, 100f)
        g.pointerDown(2, 160f, 100f)
        g.pointerMove(1, 100f, 105f)
        g.pointerMove(2, 160f, 105f)
        assertTrue(g.flush().isEmpty())
    }

    @Test
    fun twoFingersMovingTogetherScrollByTheirRawMovement() {
        g.pointerDown(1, 0f, 0f)
        g.pointerDown(2, 100f, 0f)
        g.pointerMove(1, 0f, 10f)
        g.pointerMove(2, 100f, 10f)
        // Raw finger movement after the decision (5 dp down): the PC makes it the natural direction.
        assertEquals(listOf(Scroll(0f, 5f)), g.flush())
        g.pointerMove(1, 20f, 10f)
        g.pointerMove(2, 120f, 10f)
        assertEquals(listOf(Scroll(20f, 0f)), g.flush())
    }

    @Test
    fun scrollIsAccumulatedPerFrame() {
        g.pointerDown(1, 0f, 0f)
        g.pointerDown(2, 100f, 0f)
        g.pointerMove(1, 0f, 10f)
        g.pointerMove(2, 100f, 10f)
        g.flush()
        g.pointerMove(1, 0f, 14f)
        g.pointerMove(2, 100f, 14f)
        g.pointerMove(1, 0f, 20f)
        g.pointerMove(2, 100f, 20f)
        assertEquals(listOf(Scroll(0f, 10f)), g.flush())
    }

    @Test
    fun spreadingTheFingersZoomsOneStepPerTwelvePercent() {
        g.pointerDown(1, 0f, 0f)
        g.pointerDown(2, 100f, 0f)
        g.pointerMove(2, 108f, 0f) // 8 %: not a zoom yet
        assertTrue(g.flush().isEmpty())
        g.pointerMove(2, 115f, 0f) // 15 %: one step
        assertEquals(listOf(Zoom(1)), g.flush())
        g.pointerMove(2, 140f, 0f) // 40 %: three steps in all
        assertEquals(listOf(Zoom(2)), g.flush())
        g.pointerMove(2, 125f, 0f) // back to 25 %: two steps in all
        assertEquals(listOf(Zoom(-1)), g.flush())
    }

    @Test
    fun pinchingInZoomsOut() {
        g.pointerDown(1, 0f, 0f)
        g.pointerDown(2, 100f, 0f)
        g.pointerMove(2, 80f, 0f) // -20 %
        assertEquals(listOf(Zoom(-1)), g.flush())
        g.pointerMove(2, 45f, 0f) // -55 %: four steps in all
        assertEquals(listOf(Zoom(-3)), g.flush())
    }

    @Test
    fun onceZoomingTheCentreMovingDoesNotScroll() {
        g.pointerDown(1, 0f, 0f)
        g.pointerDown(2, 100f, 0f)
        g.pointerMove(2, 120f, 0f)
        g.flush()
        g.pointerMove(1, 0f, 40f)
        g.pointerMove(2, 120f, 40f)
        assertTrue(g.flush().isEmpty())
    }

    @Test
    fun onceScrollingTheSpreadChangingDoesNotZoom() {
        g.pointerDown(1, 0f, 0f)
        g.pointerDown(2, 100f, 0f)
        g.pointerMove(1, 0f, 10f)
        g.pointerMove(2, 100f, 10f)
        g.flush()
        g.pointerMove(2, 160f, 10f)
        val effects = g.flush()
        assertTrue(effects.none { it is Zoom })
    }

    @Test
    fun liftingOneFingerEndsTheScrollUntilAllFingersAreUp() {
        g.pointerDown(1, 0f, 0f)
        g.pointerDown(2, 100f, 0f)
        g.pointerMove(1, 0f, 10f)
        g.pointerMove(2, 100f, 10f)
        g.flush()
        g.pointerUp(1)
        g.pointerMove(2, 100f, 50f)
        assertTrue(g.flush().isEmpty())
        now = 1000
        assertTrue(g.pointerUp(2).isEmpty())
    }

    // --- Three fingers ------------------------------------------------------------------------

    private fun threeFingers() {
        g.pointerDown(1, 100f, 300f)
        g.pointerDown(2, 200f, 300f)
        g.pointerDown(3, 300f, 300f)
    }

    private fun moveAll(dx: Float, dy: Float) {
        val base = mapOf(1L to (100f to 300f), 2L to (200f to 300f), 3L to (300f to 300f))
        val out = mutableListOf<TrackpadEffect>()
        for ((id, p) in base) out += g.pointerMove(id, p.first + dx, p.second + dy)
        lastThree = out
    }

    private var lastThree: List<TrackpadEffect> = emptyList()

    @Test
    fun threeFingersUpIsTaskView() {
        threeFingers()
        moveAll(0f, -70f)
        assertEquals(listOf<TrackpadEffect>(Gesture("task_view")), lastThree)
    }

    @Test
    fun threeFingersDownIsDesktop() {
        threeFingers()
        moveAll(0f, 70f)
        assertEquals(listOf<TrackpadEffect>(Gesture("desktop")), lastThree)
    }

    @Test
    fun threeFingersLeftAndRightSwitchApps() {
        threeFingers()
        moveAll(-70f, 0f)
        assertEquals(listOf<TrackpadEffect>(Gesture("app_prev")), lastThree)
        g.cancel()
        threeFingers()
        moveAll(70f, 0f)
        assertEquals(listOf<TrackpadEffect>(Gesture("app_next")), lastThree)
    }

    @Test
    fun threeFingerGestureNeedsMoreThanSixtyDp() {
        threeFingers()
        moveAll(0f, -60f)
        assertTrue(lastThree.isEmpty())
    }

    @Test
    fun threeFingerGestureFiresOnlyOncePerTouch() {
        threeFingers()
        moveAll(0f, -70f)
        assertEquals(1, lastThree.size)
        moveAll(0f, -150f)
        assertTrue(lastThree.isEmpty())
        moveAll(100f, -150f)
        assertTrue(lastThree.isEmpty())
        // Lifting and touching again is a new touch.
        g.pointerUp(1)
        g.pointerUp(2)
        g.pointerUp(3)
        threeFingers()
        moveAll(0f, 70f)
        assertEquals(listOf<TrackpadEffect>(Gesture("desktop")), lastThree)
    }

    @Test
    fun threeFingerTouchNeverClicksOrScrolls() {
        threeFingers()
        now = 100
        assertTrue(g.pointerUp(1).isEmpty())
        assertTrue(g.pointerUp(2).isEmpty())
        assertTrue(g.pointerUp(3).isEmpty())
        assertTrue(g.flush().isEmpty())
    }

    @Test
    fun liftingAFingerDoesNotFakeAThreeFingerSwipe() {
        threeFingers()
        g.pointerUp(3) // the centre jumps by 50 dp
        g.pointerDown(3, 300f, 300f)
        moveAll(0f, -10f)
        assertTrue(lastThree.isEmpty())
    }

    @Test
    fun unknownPointersAreIgnored() {
        assertTrue(g.pointerMove(9, 1f, 1f).isEmpty())
        assertTrue(g.pointerUp(9).isEmpty())
    }
}
