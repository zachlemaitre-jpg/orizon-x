package dev.tabx.client.input

import android.annotation.SuppressLint
import android.os.SystemClock
import android.view.MotionEvent
import android.view.View
import dev.tabx.client.protocol.TabletMessage

/**
 * Android glue (spec phase 4 §4.3): reads touch and stylus-hover events on the video view,
 * feeds [InputMapper] and sends its INPUT frames, only while [isStreaming].
 */
class TouchForwarder(
    private val view: View,
    private val isStreaming: () -> Boolean,
    private val send: (TabletMessage.Input) -> Unit,
    private val onToggleHud: () -> Unit,
) {
    private val mapper = InputMapper(hudSlopPx = InputMapper.HUD_SLOP_DP * view.resources.displayMetrics.density)
    private var touchSamples: List<PointerSample> = emptyList()
    private var hoverPen: PointerSample? = null
    private var wasStreaming = false
    private val hudCheck = Runnable { if (mapper.tick(SystemClock.uptimeMillis())) onToggleHud() }

    // Android envoie HOVER_EXIT juste avant le DOWN du stylet, et UP juste avant HOVER_ENTER :
    // un court délai garde le stylet « en portée » entre deux traits (pas de sortie/entrée parasite côté Windows).
    private val penLeft = Runnable {
        hoverPen = null
        dispatch(SystemClock.uptimeMillis())
    }

    @SuppressLint("ClickableViewAccessibility") // la vue vidéo n'a pas d'action de clic propre
    fun attach() {
        view.setOnTouchListener { v, event ->
            if (event.actionMasked == MotionEvent.ACTION_DOWN) v.requestUnbufferedDispatch(event)
            if (event.actionMasked == MotionEvent.ACTION_CANCEL) {
                touchSamples = emptyList()
                hoverPen = null
                view.removeCallbacks(penLeft)
                if (streamingNow()) mapper.cancelAll().forEach(send)
            } else {
                touchSamples = touchSamplesOf(event)
                if (touchSamples.any { it.tool == Tool.PEN }) view.removeCallbacks(penLeft)
                liftedPenOf(event)?.let { lifted ->
                    hoverPen = lifted // le stylet quitte l'écran mais reste en survol le temps du délai
                    view.removeCallbacks(penLeft)
                    view.postDelayed(penLeft, PEN_EXIT_GRACE_MS)
                }
                dispatch(event.eventTime)
            }
            true
        }
        view.setOnGenericMotionListener { v, event ->
            when (event.actionMasked) {
                MotionEvent.ACTION_HOVER_ENTER, MotionEvent.ACTION_HOVER_MOVE -> {
                    if (event.actionMasked == MotionEvent.ACTION_HOVER_ENTER) v.requestUnbufferedDispatch(event)
                    view.removeCallbacks(penLeft)
                    hoverPen = hoverSampleOf(event)
                    dispatch(event.eventTime)
                }
                MotionEvent.ACTION_HOVER_EXIT -> {
                    view.removeCallbacks(penLeft)
                    view.postDelayed(penLeft, PEN_EXIT_GRACE_MS)
                }
                MotionEvent.ACTION_BUTTON_PRESS, MotionEvent.ACTION_BUTTON_RELEASE -> {
                    val pen = hoverPen ?: return@setOnGenericMotionListener false
                    hoverPen = pen.copy(barrel = (event.buttonState and MotionEvent.BUTTON_STYLUS_PRIMARY) != 0)
                    dispatch(event.eventTime)
                }
                else -> return@setOnGenericMotionListener false
            }
            true
        }
    }

    private fun dispatch(eventTimeMs: Long) {
        if (!streamingNow()) return
        val pen = hoverPen?.takeIf { touchSamples.none { it.tool == Tool.PEN } }
        val out = mapper.process(touchSamples + listOfNotNull(pen), view.width.toFloat(), view.height.toFloat(), eventTimeMs)
        out.messages.forEach(send)
        if (out.toggleHud) onToggleHud()
        view.removeCallbacks(hudCheck)
        mapper.hudDeadlineMs?.let { view.postDelayed(hudCheck, (it - SystemClock.uptimeMillis()).coerceAtLeast(0)) }
    }

    /** False outside a streaming session; resets the mapper when a new session starts. */
    private fun streamingNow(): Boolean {
        if (!isStreaming()) {
            wasStreaming = false
            view.removeCallbacks(hudCheck)
            view.removeCallbacks(penLeft)
            return false
        }
        if (!wasStreaming) {
            mapper.reset()
            wasStreaming = true
        }
        return true
    }

    private fun touchSamplesOf(event: MotionEvent): List<PointerSample> {
        val lifted = when (event.actionMasked) {
            MotionEvent.ACTION_UP, MotionEvent.ACTION_POINTER_UP -> event.actionIndex
            else -> -1
        }
        return (0 until event.pointerCount).filter { it != lifted }.map { sampleAt(event, it) }
    }

    /** The pen pointer that just left the screen in this event, as a hovering sample; null otherwise. */
    private fun liftedPenOf(event: MotionEvent): PointerSample? {
        val action = event.actionMasked
        if (action != MotionEvent.ACTION_UP && action != MotionEvent.ACTION_POINTER_UP) return null
        val index = event.actionIndex
        if (!isPen(event.getToolType(index))) return null
        return sampleAt(event, index).copy(pressure = 0f, inContact = false)
    }

    private fun sampleAt(event: MotionEvent, i: Int): PointerSample {
        val pen = isPen(event.getToolType(i))
        return PointerSample(
            pointerId = event.getPointerId(i),
            tool = if (pen) Tool.PEN else Tool.FINGER,
            x = event.getX(i),
            y = event.getY(i),
            pressure = event.getPressure(i),
            tiltRad = event.getAxisValue(MotionEvent.AXIS_TILT, i),
            orientationRad = event.getAxisValue(MotionEvent.AXIS_ORIENTATION, i),
            barrel = pen && (event.buttonState and MotionEvent.BUTTON_STYLUS_PRIMARY) != 0,
            inContact = true,
        )
    }

    private fun hoverSampleOf(event: MotionEvent): PointerSample? {
        if (!isPen(event.getToolType(0))) return null
        return sampleAt(event, 0).copy(pressure = 0f, inContact = false)
    }

    private fun isPen(toolType: Int) =
        toolType == MotionEvent.TOOL_TYPE_STYLUS || toolType == MotionEvent.TOOL_TYPE_ERASER

    private companion object {
        const val PEN_EXIT_GRACE_MS = 50L
    }
}
