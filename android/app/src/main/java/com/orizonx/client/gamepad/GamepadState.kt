package com.orizonx.client.gamepad

import kotlin.math.atan2
import kotlin.math.hypot
import kotlin.math.min
import kotlin.math.roundToInt

/** XUSB_GAMEPAD_* button bits of the `gamepad.state` report (spec section 4). */
object XboxButton {
    const val DPAD_UP = 0x0001
    const val DPAD_DOWN = 0x0002
    const val DPAD_LEFT = 0x0004
    const val DPAD_RIGHT = 0x0008
    const val START = 0x0010
    const val BACK = 0x0020
    const val LEFT_THUMB = 0x0040
    const val RIGHT_THUMB = 0x0080
    const val LEFT_SHOULDER = 0x0100
    const val RIGHT_SHOULDER = 0x0200
    const val GUIDE = 0x0400
    const val A = 0x1000
    const val B = 0x2000
    const val X = 0x4000
    const val Y = 0x8000

    const val DPAD_MASK = DPAD_UP or DPAD_DOWN or DPAD_LEFT or DPAD_RIGHT
}

/** The whole controller as the PC wants it: [buttons] bits, triggers 0 or 255, sticks -32767..32767 with Y up. */
data class GamepadReport(
    val buttons: Int = 0,
    val lt: Int = 0,
    val rt: Int = 0,
    val lx: Int = 0,
    val ly: Int = 0,
    val rx: Int = 0,
    val ry: Int = 0,
) {
    companion object {
        val NEUTRAL = GamepadReport()
    }
}

/** Maths of the thumbsticks and the D-pad: touch offsets from the centre of a control in, controller values out. */
object GamepadMath {
    const val AXIS_MAX = 32767
    const val DEAD_ZONE = 0.10f
    const val DPAD_DEAD_ZONE = 0.20f
    const val TRIGGER_ON = 255

    /**
     * Stick value for a finger [dx], [dy] away from the centre (screen axes: y grows downwards) of a stick of [radius].
     * The offset is clamped to the radius; inside the 10 % dead zone the stick is centred; otherwise each axis is
     * `round(fraction × 32767)` with Y inverted (up is positive, as in XInput). Returns (x, y).
     */
    fun stick(dx: Float, dy: Float, radius: Float): Pair<Int, Int> {
        if (radius <= 0f) return 0 to 0
        val distance = hypot(dx, dy)
        if (distance == 0f || !distance.isFinite()) return 0 to 0
        val fraction = min(distance, radius) / radius
        if (fraction < DEAD_ZONE) return 0 to 0
        val x = (dx / distance * fraction * AXIS_MAX).roundToInt()
        val y = (-dy / distance * fraction * AXIS_MAX).roundToInt()
        return x.coerceIn(-AXIS_MAX, AXIS_MAX) to y.coerceIn(-AXIS_MAX, AXIS_MAX)
    }

    /**
     * D-pad bits for a finger [dx], [dy] away from the centre of a pad of [radius]: eight 45 degree sectors, so the
     * diagonals press two directions. Too close to the centre presses nothing.
     */
    fun dpad(dx: Float, dy: Float, radius: Float): Int {
        if (radius <= 0f || hypot(dx, dy) < radius * DPAD_DEAD_ZONE) return 0
        // Degrees, counter-clockwise from the right, 0..360.
        var angle = Math.toDegrees(atan2(-dy.toDouble(), dx.toDouble()))
        if (angle < 0) angle += 360.0
        return when (((angle + 22.5) / 45.0).toInt() % 8) {
            0 -> XboxButton.DPAD_RIGHT
            1 -> XboxButton.DPAD_UP or XboxButton.DPAD_RIGHT
            2 -> XboxButton.DPAD_UP
            3 -> XboxButton.DPAD_UP or XboxButton.DPAD_LEFT
            4 -> XboxButton.DPAD_LEFT
            5 -> XboxButton.DPAD_DOWN or XboxButton.DPAD_LEFT
            6 -> XboxButton.DPAD_DOWN
            else -> XboxButton.DPAD_DOWN or XboxButton.DPAD_RIGHT
        }
    }
}

/** What every control of the screen currently holds; [report] merges them into one [GamepadReport]. */
class GamepadControls {
    private var held = 0
    private var dpad = 0
    private var lt = 0
    private var rt = 0
    private var lx = 0
    private var ly = 0
    private var rx = 0
    private var ry = 0

    /** A face, shoulder, centre or stick-click button ([XboxButton] bit). */
    fun setButton(bit: Int, down: Boolean) {
        held = if (down) held or bit else held and bit.inv()
    }

    fun setDpad(bits: Int) {
        dpad = bits and XboxButton.DPAD_MASK
    }

    fun setLeftTrigger(down: Boolean) {
        lt = if (down) GamepadMath.TRIGGER_ON else 0
    }

    fun setRightTrigger(down: Boolean) {
        rt = if (down) GamepadMath.TRIGGER_ON else 0
    }

    fun setLeftStick(x: Int, y: Int) {
        lx = x
        ly = y
    }

    fun setRightStick(x: Int, y: Int) {
        rx = x
        ry = y
    }

    fun report() = GamepadReport(held or dpad, lt, rt, lx, ly, rx, ry)

    fun reset() {
        held = 0
        dpad = 0
        lt = 0
        rt = 0
        lx = 0
        ly = 0
        rx = 0
        ry = 0
    }
}

/**
 * Sends reports at most every [intervalMs] (8 ms): a change that comes too soon waits, and a newer one replaces it, so
 * the last state always wins. Identical reports are not repeated. [tick] must be called often (every few ms).
 */
class GamepadThrottle(
    private val clock: () -> Long,
    private val intervalMs: Long = DEFAULT_INTERVAL_MS,
    private val send: (GamepadReport) -> Unit,
) {
    private var pending: GamepadReport? = null
    private var lastSent: GamepadReport? = null
    private var lastSentAt = Long.MIN_VALUE

    fun submit(report: GamepadReport) {
        pending = report
        flushIfDue()
    }

    fun tick() = flushIfDue()

    /** Sends [report] now whatever the rate (the neutral report when the screen closes). */
    fun sendNow(report: GamepadReport) {
        pending = null
        lastSent = report
        lastSentAt = clock()
        send(report)
    }

    private fun flushIfDue() {
        val report = pending ?: return
        val now = clock()
        if (lastSentAt != Long.MIN_VALUE && now - lastSentAt < intervalMs) return
        pending = null
        if (report == lastSent) return
        lastSent = report
        lastSentAt = now
        send(report)
    }

    companion object {
        const val DEFAULT_INTERVAL_MS = 8L
    }
}

/** Two quick taps on a stick click it (L3 / R3). A touch that was not a short still tap resets the detector. */
class DoubleTapDetector(private val clock: () -> Long, private val windowMs: Long = DEFAULT_WINDOW_MS) {
    private var lastTapAt = Long.MIN_VALUE

    /** Call when a touch ends; [wasTap] is true for a short touch that hardly moved. True on the second tap. */
    fun onTouchEnd(wasTap: Boolean): Boolean {
        if (!wasTap) {
            lastTapAt = Long.MIN_VALUE
            return false
        }
        val now = clock()
        if (lastTapAt != Long.MIN_VALUE && now - lastTapAt < windowMs) {
            lastTapAt = Long.MIN_VALUE
            return true
        }
        lastTapAt = now
        return false
    }

    companion object {
        const val DEFAULT_WINDOW_MS = 300L
        const val CLICK_MS = 100L
        const val TAP_MS = 200L
        const val TAP_SLOP_FRACTION = 0.15f
    }
}

