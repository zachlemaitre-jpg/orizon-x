package com.orizonx.client.ui

import android.os.SystemClock
import androidx.compose.foundation.Canvas
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.gestures.awaitEachGesture
import androidx.compose.foundation.gestures.awaitFirstDown
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.BoxWithConstraints
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.offset
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.BasicText
import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.rememberUpdatedState
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.geometry.CornerRadius
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.geometry.Size
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.Shape
import androidx.compose.ui.input.pointer.pointerInput
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.text.TextStyle
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.orizonx.client.actions.GamepadInfo
import com.orizonx.client.actions.GamepadProblem
import com.orizonx.client.gamepad.DoubleTapDetector
import com.orizonx.client.gamepad.GamepadActions
import com.orizonx.client.gamepad.GamepadControls
import com.orizonx.client.gamepad.GamepadMath
import com.orizonx.client.gamepad.GamepadReport
import com.orizonx.client.gamepad.GamepadThrottle
import com.orizonx.client.gamepad.XboxButton
import com.orizonx.client.i18n.S
import com.orizonx.client.i18n.tr
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch
import org.json.JSONObject
import kotlin.math.max
import kotlin.math.min

private val XboxGreen = Color(0xFF3DAE3D)
private val XboxRed = Color(0xFFD8453B)
private val XboxBlue = Color(0xFF3C7FD6)
private val XboxYellow = Color(0xFFE3B126)

// The Xbox layout is drawn on a 1000 x 500 canvas and scaled to the screen (to its width in portrait).
private const val CANVAS_W = 1000f
private const val CANVAS_H = 500f

/**
 * Full-screen virtual Xbox controller, without the Actions header; a small ✕ at the top centre closes it. While it is on
 * screen the PC has a virtual pad: `gamepad.open` when it appears, a neutral report then `gamepad.close` when it goes
 * (close, mode switch, disconnect). If the PC cannot provide a pad, a message replaces the controls.
 */
@Composable
fun GamepadScreen(
    info: GamepadInfo,
    onAction: (JSONObject) -> Unit,
    onClose: () -> Unit,
    tap: () -> Unit,
    modifier: Modifier = Modifier,
) {
    Box(modifier.fillMaxSize()) {
        if (info.available) {
            GamepadPad(onAction, tap)
        } else {
            val message = tr(if (info.problem == GamepadProblem.DRIVER_MISSING) S.GAMEPAD_DRIVER_MISSING else S.GAMEPAD_ERROR)
            Box(Modifier.fillMaxSize().padding(horizontal = 48.dp), contentAlignment = Alignment.Center) {
                BasicText(
                    message,
                    style = TextStyle(color = Color.White.copy(alpha = 0.9f), fontSize = 18.sp, textAlign = TextAlign.Center),
                )
            }
        }
        val closeDescription = tr(S.GAMEPAD_CLOSE_DESC)
        Box(
            Modifier
                .align(Alignment.TopCenter)
                .padding(top = 6.dp)
                .size(36.dp)
                .clip(CircleShape)
                .background(Color.White.copy(alpha = 0.12f))
                .clickable { tap(); onClose() }
                .semantics { contentDescription = closeDescription },
            contentAlignment = Alignment.Center,
        ) {
            BasicText("✕", style = TextStyle(color = Color.White, fontSize = 16.sp))
        }
    }
}

@Composable
private fun GamepadPad(onAction: (JSONObject) -> Unit, tap: () -> Unit) {
    val send by rememberUpdatedState(onAction)
    val latestTap by rememberUpdatedState(tap)
    val controls = remember { GamepadControls() }
    var report by remember { mutableStateOf(GamepadReport.NEUTRAL) }
    val throttle = remember { GamepadThrottle(SystemClock::elapsedRealtime) { send(GamepadActions.state(it)) } }
    val scope = rememberCoroutineScope()

    fun changed() {
        report = controls.report()
        throttle.submit(report)
    }

    LaunchedEffect(throttle) {
        send(GamepadActions.open())
        // Waits that the 8 ms rate allowed for are flushed here.
        while (true) {
            delay(4)
            throttle.tick()
        }
    }
    DisposableEffect(throttle) {
        onDispose {
            controls.reset()
            throttle.sendNow(GamepadReport.NEUTRAL)
            send(GamepadActions.close())
        }
    }

    fun button(bit: Int): (Boolean) -> Unit = { down ->
        controls.setButton(bit, down)
        changed()
    }

    fun clickStick(bit: Int): () -> Unit = {
        controls.setButton(bit, true)
        changed()
        scope.launch {
            delay(DoubleTapDetector.CLICK_MS)
            controls.setButton(bit, false)
            changed()
        }
    }

    val buttons = report.buttons
    BoxWithConstraints(Modifier.fillMaxSize()) {
        val scale = min(maxWidth.value / CANVAS_W, maxHeight.value / CANVAS_H)
        val at = { x: Float, y: Float, w: Float, h: Float ->
            Modifier.offset((x * scale).dp, (y * scale).dp).size((w * scale).dp, (h * scale).dp)
        }
        Box(Modifier.align(Alignment.Center).size((CANVAS_W * scale).dp, (CANVAS_H * scale).dp)) {
            val shoulder = RoundedCornerShape(14.dp)
            // Top corners: triggers outside, bumpers inside.
            PadKey(at(20f, 10f, 140f, 56f), "LT", null, report.lt > 0, shoulder, { controls.setLeftTrigger(it); changed() }, latestTap)
            PadKey(at(170f, 10f, 140f, 56f), "LB", null, buttons and XboxButton.LEFT_SHOULDER != 0, shoulder, button(XboxButton.LEFT_SHOULDER), latestTap)
            PadKey(at(690f, 10f, 140f, 56f), "RB", null, buttons and XboxButton.RIGHT_SHOULDER != 0, shoulder, button(XboxButton.RIGHT_SHOULDER), latestTap)
            PadKey(at(840f, 10f, 140f, 56f), "RT", null, report.rt > 0, shoulder, { controls.setRightTrigger(it); changed() }, latestTap)

            // Centre: View, Xbox, Menu.
            val small = RoundedCornerShape(20.dp)
            PadKey(at(392f, 170f, 70f, 40f), "▭", null, buttons and XboxButton.BACK != 0, small, button(XboxButton.BACK), latestTap)
            PadKey(at(468f, 152f, 64f, 64f), "⊗", null, buttons and XboxButton.GUIDE != 0, CircleShape, button(XboxButton.GUIDE), latestTap, bold = true)
            PadKey(at(538f, 170f, 70f, 40f), "≡", null, buttons and XboxButton.START != 0, small, button(XboxButton.START), latestTap)

            // Face buttons, Xbox colours: Y top, A bottom, X left, B right.
            PadKey(at(804f, 99f, 72f, 72f), "Y", XboxYellow, buttons and XboxButton.Y != 0, CircleShape, button(XboxButton.Y), latestTap, bold = true)
            PadKey(at(804f, 229f, 72f, 72f), "A", XboxGreen, buttons and XboxButton.A != 0, CircleShape, button(XboxButton.A), latestTap, bold = true)
            PadKey(at(739f, 164f, 72f, 72f), "X", XboxBlue, buttons and XboxButton.X != 0, CircleShape, button(XboxButton.X), latestTap, bold = true)
            PadKey(at(869f, 164f, 72f, 72f), "B", XboxRed, buttons and XboxButton.B != 0, CircleShape, button(XboxButton.B), latestTap, bold = true)

            // Sticks: left at the top, right at the bottom; the D-pad is under the left stick.
            StickPad(
                at(55f, 100f, 190f, 190f),
                onValue = { x, y -> controls.setLeftStick(x, y); changed() },
                onClick = clickStick(XboxButton.LEFT_THUMB),
            )
            DpadPad(
                at(180f, 305f, 180f, 180f),
                bits = buttons and XboxButton.DPAD_MASK,
                onBits = { controls.setDpad(it); changed() },
                tap = latestTap,
            )
            StickPad(
                at(640f, 305f, 180f, 180f),
                onValue = { x, y -> controls.setRightStick(x, y); changed() },
                onClick = clickStick(XboxButton.RIGHT_THUMB),
            )
        }
    }
}

/** A key held by one finger: `onChange(true)` when pressed, `onChange(false)` when released (or if the screen goes away). */
@Composable
private fun PadKey(
    modifier: Modifier,
    label: String,
    color: Color?,
    pressed: Boolean,
    shape: Shape,
    onChange: (Boolean) -> Unit,
    tap: () -> Unit,
    bold: Boolean = false,
) {
    val latestChange by rememberUpdatedState(onChange)
    val latestTap by rememberUpdatedState(tap)
    val base = color ?: Color.White
    Box(
        modifier
            .clip(shape)
            .background(base.copy(alpha = if (pressed) 0.85f else if (color != null) 0.45f else 0.12f))
            .border(1.dp, base.copy(alpha = if (pressed) 1f else 0.5f), shape)
            .pointerInput(Unit) {
                awaitEachGesture {
                    val first = awaitFirstDown(requireUnconsumed = false)
                    first.consume()
                    latestTap()
                    latestChange(true)
                    try {
                        do {
                            val event = awaitPointerEvent()
                            event.changes.forEach { it.consume() }
                        } while (event.changes.any { it.id == first.id && it.pressed })
                    } finally {
                        latestChange(false)
                    }
                }
            },
        contentAlignment = Alignment.Center,
    ) {
        BasicText(
            label,
            style = TextStyle(
                color = Color.White,
                fontSize = 18.sp,
                fontWeight = if (bold) FontWeight.Bold else FontWeight.Normal,
                textAlign = TextAlign.Center,
            ),
        )
    }
}

/**
 * A thumbstick: the finger's offset from the centre of the disc, clamped to its radius, is the value; the knob follows it
 * and goes back to the centre on lift. Two quick still taps click the stick (L3 / R3).
 */
@Composable
private fun StickPad(modifier: Modifier, onValue: (Int, Int) -> Unit, onClick: () -> Unit) {
    val latestValue by rememberUpdatedState(onValue)
    val latestClick by rememberUpdatedState(onClick)
    var knob by remember { mutableStateOf(Offset.Zero) }
    val detector = remember { DoubleTapDetector(SystemClock::elapsedRealtime) }
    Box(
        modifier
            .clip(CircleShape)
            .background(Color.White.copy(alpha = 0.10f))
            .border(1.dp, Color.White.copy(alpha = 0.35f), CircleShape)
            .pointerInput(Unit) {
                awaitEachGesture {
                    val first = awaitFirstDown(requireUnconsumed = false)
                    first.consume()
                    val center = Offset(size.width / 2f, size.height / 2f)
                    val radius = size.width / 2f
                    val startedAt = SystemClock.elapsedRealtime()
                    var travel = 0f

                    fun apply(position: Offset) {
                        val d = position - center
                        val length = d.getDistance()
                        knob = if (length > radius && length > 0f) d * (radius / length) else d
                        val (x, y) = GamepadMath.stick(d.x, d.y, radius)
                        latestValue(x, y)
                        travel = max(travel, (position - first.position).getDistance())
                    }

                    apply(first.position)
                    try {
                        do {
                            val event = awaitPointerEvent()
                            for (change in event.changes) {
                                if (change.id == first.id) apply(change.position)
                                change.consume()
                            }
                        } while (event.changes.any { it.id == first.id && it.pressed })
                    } finally {
                        knob = Offset.Zero
                        latestValue(0, 0)
                    }
                    val wasTap = SystemClock.elapsedRealtime() - startedAt < DoubleTapDetector.TAP_MS &&
                        travel < radius * DoubleTapDetector.TAP_SLOP_FRACTION
                    if (detector.onTouchEnd(wasTap)) latestClick()
                }
            },
    ) {
        Canvas(Modifier.fillMaxSize()) {
            drawCircle(Color.White.copy(alpha = 0.55f), radius = size.minDimension * 0.28f, center = center + knob)
        }
    }
}

/** The directional pad: eight sectors, so a finger between two arms presses both. */
@Composable
private fun DpadPad(modifier: Modifier, bits: Int, onBits: (Int) -> Unit, tap: () -> Unit) {
    val latestBits by rememberUpdatedState(onBits)
    val latestTap by rememberUpdatedState(tap)
    Box(
        modifier
            .clip(CircleShape)
            .background(Color.White.copy(alpha = 0.06f))
            .pointerInput(Unit) {
                awaitEachGesture {
                    val first = awaitFirstDown(requireUnconsumed = false)
                    first.consume()
                    val center = Offset(size.width / 2f, size.height / 2f)
                    val radius = size.width / 2f
                    var current = 0

                    fun apply(position: Offset) {
                        val d = position - center
                        val next = GamepadMath.dpad(d.x, d.y, radius)
                        if (next == current) return
                        if ((next and current.inv()) != 0) latestTap()
                        current = next
                        latestBits(next)
                    }

                    apply(first.position)
                    try {
                        do {
                            val event = awaitPointerEvent()
                            for (change in event.changes) {
                                if (change.id == first.id) apply(change.position)
                                change.consume()
                            }
                        } while (event.changes.any { it.id == first.id && it.pressed })
                    } finally {
                        latestBits(0)
                    }
                }
            },
    ) {
        Canvas(Modifier.fillMaxSize()) {
            val arm = size.minDimension * 0.30f
            val length = size.minDimension * 0.86f
            val c = center
            val corner = CornerRadius(arm * 0.25f)
            fun draw(lit: Boolean, topLeft: Offset, size: Size) =
                drawRoundRect(Color.White.copy(alpha = if (lit) 0.80f else 0.28f), topLeft, size, corner)
            draw(bits and XboxButton.DPAD_UP != 0, Offset(c.x - arm / 2, c.y - length / 2), Size(arm, length / 2))
            draw(bits and XboxButton.DPAD_DOWN != 0, Offset(c.x - arm / 2, c.y), Size(arm, length / 2))
            draw(bits and XboxButton.DPAD_LEFT != 0, Offset(c.x - length / 2, c.y - arm / 2), Size(length / 2, arm))
            draw(bits and XboxButton.DPAD_RIGHT != 0, Offset(c.x, c.y - arm / 2), Size(length / 2, arm))
        }
    }
}
