package dev.tabx.client.input

import dev.tabx.client.protocol.InputContact
import dev.tabx.client.protocol.Protocol
import dev.tabx.client.protocol.TabletMessage
import kotlin.math.atan
import kotlin.math.cos
import kotlin.math.hypot
import kotlin.math.roundToInt
import kotlin.math.sin
import kotlin.math.tan

enum class Tool { FINGER, PEN }

/** One Android pointer, in video-view pixels. Angles in radians (MotionEvent AXIS_TILT / AXIS_ORIENTATION). */
data class PointerSample(
    val pointerId: Int,
    val tool: Tool,
    val x: Float,
    val y: Float,
    val pressure: Float = 0f,
    val tiltRad: Float = 0f,
    val orientationRad: Float = 0f,
    val barrel: Boolean = false,
    val inContact: Boolean = true,
)

data class MapperOutput(val messages: List<TabletMessage.Input>, val toggleHud: Boolean = false)

/**
 * Android pointer snapshots → TABX INPUT frames (spec phase 4 §4.2): normalisation, stable finger slots,
 * palm rejection while the pen is in range, and the 4-finger long-press that toggles the HUD
 * instead of reaching the PC. Not thread-safe: call from the UI thread.
 */
class InputMapper(private val hudSlopPx: Float, private val hudHoldMs: Long = HUD_HOLD_MS) {
    private val slots = mutableMapOf<Int, Int>()
    private var lastTouch = EMPTY_TOUCH
    private var lastPen = EMPTY_PEN
    private var touchSuppressed = false
    private var hudStartMs: Long? = null
    private var hudOrigins: Map<Int, Pair<Float, Float>> = emptyMap()
    private var hudDisqualified = false
    private var hudFired = false

    /** When the pending 4-finger hold completes; the caller must call [tick] then. */
    val hudDeadlineMs: Long?
        get() = hudStartMs?.takeIf { !hudDisqualified && !hudFired }?.plus(hudHoldMs)

    fun process(samples: List<PointerSample>, width: Float, height: Float, nowMs: Long): MapperOutput {
        val out = mutableListOf<TabletMessage.Input>()
        val pens = samples.filter { it.tool == Tool.PEN }
        val fingers = samples.filter { it.tool == Tool.FINGER }

        emit(TabletMessage.Input(Protocol.DEVICE_PEN, pens.take(1).map { penContact(it, width, height) }), out)

        when {
            fingers.isEmpty() -> {
                emit(EMPTY_TOUCH, out)
                resetGesture()
            }
            pens.isNotEmpty() -> { // paume : le stylet est en portée
                cancelTouches(out)
                touchSuppressed = true
            }
            touchSuppressed || fingers.size >= HUD_FINGERS -> {
                if (!touchSuppressed) {
                    cancelTouches(out)
                    touchSuppressed = true
                }
                trackHud(fingers, nowMs)
            }
            else -> emit(TabletMessage.Input(Protocol.DEVICE_TOUCH, fingerContacts(fingers, width, height)), out)
        }
        return MapperOutput(out, toggleHud = checkHud(nowMs))
    }

    /** Called at [hudDeadlineMs]: true once when the 4-finger hold completes. */
    fun tick(nowMs: Long): Boolean = checkHud(nowMs)

    /** Cancels every transmitted contact (Android ACTION_CANCEL). */
    fun cancelAll(): List<TabletMessage.Input> {
        val out = mutableListOf<TabletMessage.Input>()
        cancelTouches(out)
        if (lastPen.contacts.isNotEmpty()) {
            out += TabletMessage.Input(Protocol.DEVICE_PEN, lastPen.contacts.map { it.copy(flags = it.flags or Protocol.CONTACT_CANCELED) })
        }
        lastPen = EMPTY_PEN
        resetGesture()
        return out
    }

    /** Forgets everything (new session: the PC starts from scratch). */
    fun reset() {
        lastTouch = EMPTY_TOUCH
        lastPen = EMPTY_PEN
        resetGesture()
    }

    private fun emit(frame: TabletMessage.Input, out: MutableList<TabletMessage.Input>) {
        val last = if (frame.device == Protocol.DEVICE_PEN) lastPen else lastTouch
        if (frame == last) return
        out += frame
        if (frame.device == Protocol.DEVICE_PEN) lastPen = frame else lastTouch = frame
    }

    private fun cancelTouches(out: MutableList<TabletMessage.Input>) {
        if (lastTouch.contacts.isNotEmpty()) {
            out += TabletMessage.Input(
                Protocol.DEVICE_TOUCH,
                lastTouch.contacts.map { it.copy(flags = it.flags or Protocol.CONTACT_CANCELED) },
            )
        }
        lastTouch = EMPTY_TOUCH
    }

    private fun fingerContacts(fingers: List<PointerSample>, width: Float, height: Float): List<InputContact> {
        slots.keys.retainAll(fingers.map { it.pointerId }.toSet())
        val contacts = mutableListOf<InputContact>()
        for (finger in fingers) {
            val slot = slots[finger.pointerId] ?: freeSlot()?.also { slots[finger.pointerId] = it } ?: continue
            contacts += InputContact(slot, Protocol.CONTACT_CONTACT or Protocol.CONTACT_IN_RANGE, norm(finger.x, width), norm(finger.y, height))
        }
        return contacts.sortedBy { it.id }
    }

    private fun freeSlot(): Int? = (0 until Protocol.MAX_TOUCH_CONTACTS).firstOrNull { it !in slots.values }

    private fun penContact(pen: PointerSample, width: Float, height: Float): InputContact {
        var flags = Protocol.CONTACT_IN_RANGE
        if (pen.inContact) flags = flags or Protocol.CONTACT_CONTACT
        if (pen.barrel) flags = flags or Protocol.CONTACT_BARREL
        val tilt = tan(pen.tiltRad.toDouble().coerceIn(0.0, MAX_TILT_RAD))
        val orientation = pen.orientationRad.toDouble()
        return InputContact(
            id = 0,
            flags = flags,
            x = norm(pen.x, width),
            y = norm(pen.y, height),
            pressure = if (pen.inContact) (pen.pressure.coerceIn(0f, 1f) * 1024f).roundToInt() else 0,
            tiltX = degrees(atan(sin(orientation) * tilt)),
            tiltY = degrees(atan(-cos(orientation) * tilt)),
        )
    }

    private fun trackHud(fingers: List<PointerSample>, nowMs: Long) {
        if (hudDisqualified || hudFired) return
        val start = hudStartMs
        if (fingers.size < HUD_FINGERS) {
            if (start != null) hudDisqualified = true
            return
        }
        if (start == null) {
            hudStartMs = nowMs
            hudOrigins = fingers.associate { it.pointerId to (it.x to it.y) }
            return
        }
        val moved = fingers.any { finger ->
            val origin = hudOrigins[finger.pointerId] ?: return@any true
            hypot(finger.x - origin.first, finger.y - origin.second) > hudSlopPx
        }
        if (moved) hudDisqualified = true
    }

    private fun checkHud(nowMs: Long): Boolean {
        val start = hudStartMs ?: return false
        if (hudDisqualified || hudFired || nowMs - start < hudHoldMs) return false
        hudFired = true
        return true
    }

    private fun resetGesture() {
        slots.clear()
        touchSuppressed = false
        hudStartMs = null
        hudOrigins = emptyMap()
        hudDisqualified = false
        hudFired = false
    }

    companion object {
        const val HUD_FINGERS = 4
        const val HUD_HOLD_MS = 2000L
        const val HUD_SLOP_DP = 48f
        private const val MAX_TILT_RAD = 1.5533430342749532 // 89° : évite tan(90°)
        private val EMPTY_TOUCH = TabletMessage.Input(Protocol.DEVICE_TOUCH, emptyList())
        private val EMPTY_PEN = TabletMessage.Input(Protocol.DEVICE_PEN, emptyList())

        fun norm(value: Float, size: Float): Int =
            if (size <= 0f) 0 else ((value / size).coerceIn(0f, 1f) * 65535f).roundToInt()

        private fun degrees(rad: Double): Int = Math.toDegrees(rad).roundToInt().coerceIn(-90, 90)
    }
}
