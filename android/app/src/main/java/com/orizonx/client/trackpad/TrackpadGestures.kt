package com.orizonx.client.trackpad

import kotlin.math.abs
import kotlin.math.hypot
import kotlin.math.max

/** What the trackpad asks the PC to do (spec section 3). Moves, scrolls and zooms are sums over one frame. */
sealed interface TrackpadEffect {
    /** Relative mouse move in device pixels (dp times the sensitivity). */
    data class Move(val dx: Float, val dy: Float) : TrackpadEffect

    /** Raw movement of the two fingers' centre in dp, same axes as [Move]; the PC applies the natural scroll direction. */
    data class Scroll(val dx: Float, val dy: Float) : TrackpadEffect

    /** Pinch steps: positive spreads the fingers (zoom in), negative brings them together. */
    data class Zoom(val steps: Int) : TrackpadEffect

    data class Button(val right: Boolean, val down: Boolean) : TrackpadEffect

    /** One of [TrackpadGestures.TASK_VIEW], [TrackpadGestures.DESKTOP], [TrackpadGestures.APP_PREV], [TrackpadGestures.APP_NEXT]. */
    data class Gesture(val name: String) : TrackpadEffect
}

/**
 * The touchpad gestures of a laptop, without Android: fingers in (positions in dp, a clock in ms), [TrackpadEffect]s out.
 *
 * - One finger: moves after leaving a 2 dp dead zone. A short still touch (under 200 ms, under 8 dp) is a left click.
 *   Put a finger down again within 300 ms of a tap and move: the left button is held for the drag until the lift.
 * - Two fingers: a short still touch (down within 150 ms of each other, up within 250 ms, under 10 dp) is a right click.
 *   Otherwise the fingers either scroll (they move together) or zoom (their spread changes by more than 10 % before any
 *   scrolling); the first one to start excludes the other for the rest of the touch.
 * - Three or more fingers: a mean displacement over 60 dp fires one of four desktop gestures, once per touch.
 *
 * [move][Move], [scroll][Scroll] and [zoom][Zoom] are accumulated: call [flush] every frame (16 ms) to get one of each.
 * Everything else is returned at once, preceded by whatever was accumulated so the order is kept. Not thread-safe.
 */
class TrackpadGestures(private val clock: () -> Long) {
    /** Multiplier for [TrackpadEffect.Move]; set it from the persisted setting. */
    var sensitivity: Float = TrackpadSensitivity.DEFAULT

    private enum class Mode { ONE, TWO, SCROLL, ZOOM, THREE, DONE }

    private class Finger(val startX: Float, val startY: Float, var x: Float, var y: Float)

    private val fingers = LinkedHashMap<Long, Finger>()
    private var mode = Mode.ONE
    private var sessionStart = 0L
    private var maxCount = 0
    private var maxTravel = 0f
    private var moving = false
    private var dragging = false
    private var dragCandidate = false
    private var lastTapAt = NEVER
    private var secondDownGap = 0L

    // Two fingers.
    private var startSpread = 1f
    private var startCx = 0f
    private var startCy = 0f
    private var lastCx = 0f
    private var lastCy = 0f
    private var sentZoomSteps = 0

    // Three or more fingers.
    private var gestureFired = false

    // Accumulated for the next frame.
    private var pendingMoveX = 0f
    private var pendingMoveY = 0f
    private var pendingScrollX = 0f
    private var pendingScrollY = 0f
    private var pendingZoom = 0

    fun pointerDown(id: Long, x: Float, y: Float): List<TrackpadEffect> {
        val now = clock()
        if (fingers.isEmpty()) {
            sessionStart = now
            maxCount = 0
            maxTravel = 0f
            mode = Mode.ONE
            moving = false
            dragging = false
            gestureFired = false
            dragCandidate = lastTapAt != NEVER && now - lastTapAt < DRAG_AFTER_TAP_MS
        }
        fingers[id] = Finger(x, y, x, y)
        maxCount = max(maxCount, fingers.size)
        if (dragging) return emptyList() // other fingers are ignored while a drag is held
        when {
            fingers.size == 2 && mode == Mode.ONE -> {
                mode = Mode.TWO
                secondDownGap = now - sessionStart
                val (a, b) = fingers.values.toList()
                startSpread = max(MIN_SPREAD, hypot(a.x - b.x, a.y - b.y))
                startCx = (a.x + b.x) / 2
                startCy = (a.y + b.y) / 2
                lastCx = startCx
                lastCy = startCy
                sentZoomSteps = 0
            }
            fingers.size >= 3 -> {
                mode = Mode.THREE
                markThreeStart()
            }
        }
        return emptyList()
    }

    fun pointerMove(id: Long, x: Float, y: Float): List<TrackpadEffect> {
        val finger = fingers[id] ?: return emptyList()
        val dx = x - finger.x
        val dy = y - finger.y
        finger.x = x
        finger.y = y
        maxTravel = max(maxTravel, hypot(x - finger.startX, y - finger.startY))
        return when (mode) {
            Mode.ONE -> moveOne(finger, dx, dy)
            Mode.TWO, Mode.SCROLL, Mode.ZOOM -> {
                if (fingers.size >= 2) moveTwo()
                emptyList()
            }
            Mode.THREE -> moveThree()
            Mode.DONE -> emptyList()
        }
    }

    fun pointerUp(id: Long): List<TrackpadEffect> {
        if (fingers.remove(id) == null) return emptyList()
        if (fingers.isNotEmpty()) {
            // A finger left a multi-finger touch: it is over as far as moving goes.
            if (mode == Mode.SCROLL || mode == Mode.ZOOM) mode = Mode.DONE
            if (mode == Mode.THREE) markThreeStart()
            return emptyList()
        }
        val now = clock()
        val out = mutableListOf<TrackpadEffect>()
        var tapped = false
        when {
            dragging -> {
                out += drain()
                out += TrackpadEffect.Button(right = false, down = false)
            }
            maxCount == 1 && mode == Mode.ONE && now - sessionStart < TAP_MS && maxTravel < TAP_SLOP_DP -> {
                out += drain()
                out += TrackpadEffect.Button(right = false, down = true)
                out += TrackpadEffect.Button(right = false, down = false)
                tapped = true
            }
            maxCount == 2 && mode == Mode.TWO && secondDownGap <= TWO_FINGER_DOWN_GAP_MS &&
                now - sessionStart < TWO_FINGER_TAP_MS && maxTravel < TWO_FINGER_SLOP_DP -> {
                out += drain()
                out += TrackpadEffect.Button(right = true, down = true)
                out += TrackpadEffect.Button(right = true, down = false)
            }
            else -> out += drain()
        }
        lastTapAt = if (tapped) now else NEVER
        dragging = false
        mode = Mode.ONE
        return out
    }

    /** One batch of what moved since the last call: at most a [TrackpadEffect.Move], a Scroll and a Zoom. */
    fun flush(): List<TrackpadEffect> = drain()

    /** The touch was cancelled (screen left, system gesture): lift a held drag and forget the fingers. */
    fun cancel(): List<TrackpadEffect> {
        val out = mutableListOf<TrackpadEffect>()
        if (dragging) out += TrackpadEffect.Button(right = false, down = false)
        reset()
        return out
    }

    /** Forget everything without sending anything. */
    fun reset() {
        fingers.clear()
        mode = Mode.ONE
        moving = false
        dragging = false
        dragCandidate = false
        lastTapAt = NEVER
        pendingMoveX = 0f
        pendingMoveY = 0f
        pendingScrollX = 0f
        pendingScrollY = 0f
        pendingZoom = 0
    }

    private fun moveOne(finger: Finger, dx: Float, dy: Float): List<TrackpadEffect> {
        if (!moving) {
            if (hypot(finger.x - finger.startX, finger.y - finger.startY) <= MOVE_DEAD_ZONE_DP) return emptyList()
            moving = true
            // The dead zone itself is not sent: the pointer starts from where the finger is now.
            if (dragCandidate && fingers.size == 1) {
                dragging = true
                return drain() + TrackpadEffect.Button(right = false, down = true)
            }
            return emptyList()
        }
        pendingMoveX += dx * sensitivity
        pendingMoveY += dy * sensitivity
        return emptyList()
    }

    private fun moveTwo() {
        val (a, b) = fingers.values.toList()
        val spread = hypot(a.x - b.x, a.y - b.y)
        val cx = (a.x + b.x) / 2
        val cy = (a.y + b.y) / 2
        if (mode == Mode.TWO) {
            if (abs(spread / startSpread - 1f) > ZOOM_START_RATIO) {
                mode = Mode.ZOOM
            } else {
                val travel = hypot(cx - startCx, cy - startCy)
                // Moving together: the centre travels and the spread hardly changes.
                if (travel > SCROLL_START_DP && abs(spread - startSpread) < travel) {
                    mode = Mode.SCROLL
                    lastCx = cx
                    lastCy = cy
                }
            }
        }
        when (mode) {
            Mode.SCROLL -> {
                // Raw finger movement (x right, y down): the PC turns it into the natural direction (content follows the fingers).
                pendingScrollX += cx - lastCx
                pendingScrollY += cy - lastCy
                lastCx = cx
                lastCy = cy
            }
            Mode.ZOOM -> {
                val steps = ((spread / startSpread - 1f) / ZOOM_STEP_RATIO).toInt()
                pendingZoom += steps - sentZoomSteps
                sentZoomSteps = steps
            }
            else -> Unit
        }
    }

    private var threeStartX = 0f
    private var threeStartY = 0f

    private fun markThreeStart() {
        if (fingers.size < 3) return
        threeStartX = fingers.values.map { it.x }.average().toFloat()
        threeStartY = fingers.values.map { it.y }.average().toFloat()
    }

    private fun moveThree(): List<TrackpadEffect> {
        if (gestureFired || fingers.size < 3) return emptyList()
        val dx = fingers.values.map { it.x }.average().toFloat() - threeStartX
        val dy = fingers.values.map { it.y }.average().toFloat() - threeStartY
        if (max(abs(dx), abs(dy)) <= THREE_FINGER_DP) return emptyList()
        gestureFired = true
        val name = if (abs(dy) >= abs(dx)) {
            if (dy < 0) TASK_VIEW else DESKTOP
        } else {
            if (dx < 0) APP_PREV else APP_NEXT
        }
        return drain() + TrackpadEffect.Gesture(name)
    }

    private fun drain(): List<TrackpadEffect> {
        val out = ArrayList<TrackpadEffect>(3)
        if (pendingMoveX != 0f || pendingMoveY != 0f) out += TrackpadEffect.Move(pendingMoveX, pendingMoveY)
        if (pendingScrollX != 0f || pendingScrollY != 0f) out += TrackpadEffect.Scroll(pendingScrollX, pendingScrollY)
        if (pendingZoom != 0) out += TrackpadEffect.Zoom(pendingZoom)
        pendingMoveX = 0f
        pendingMoveY = 0f
        pendingScrollX = 0f
        pendingScrollY = 0f
        pendingZoom = 0
        return out
    }

    companion object {
        const val TASK_VIEW = "task_view"
        const val DESKTOP = "desktop"
        const val APP_PREV = "app_prev"
        const val APP_NEXT = "app_next"

        const val MOVE_DEAD_ZONE_DP = 2f
        const val TAP_MS = 200L
        const val TAP_SLOP_DP = 8f
        const val TWO_FINGER_DOWN_GAP_MS = 150L
        const val TWO_FINGER_TAP_MS = 250L
        const val TWO_FINGER_SLOP_DP = 10f
        const val DRAG_AFTER_TAP_MS = 300L
        const val SCROLL_START_DP = 4f
        const val ZOOM_START_RATIO = 0.10f
        const val ZOOM_STEP_RATIO = 0.12f
        const val THREE_FINGER_DP = 60f
        const val FRAME_MS = 16L

        private const val NEVER = Long.MIN_VALUE
        private const val MIN_SPREAD = 1f
    }
}
