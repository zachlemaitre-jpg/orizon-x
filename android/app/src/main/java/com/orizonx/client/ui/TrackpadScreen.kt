package com.orizonx.client.ui

import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.gestures.awaitEachGesture
import androidx.compose.foundation.gestures.awaitFirstDown
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.BasicText
import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberUpdatedState
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.input.pointer.changedToDown
import androidx.compose.ui.input.pointer.changedToUp
import androidx.compose.ui.input.pointer.pointerInput
import androidx.compose.ui.input.pointer.positionChanged
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.text.TextStyle
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.orizonx.client.i18n.Lang
import com.orizonx.client.i18n.LocalLang
import com.orizonx.client.i18n.S
import com.orizonx.client.i18n.tr
import com.orizonx.client.trackpad.TrackpadActions
import com.orizonx.client.trackpad.TrackpadEffect
import com.orizonx.client.trackpad.TrackpadGestures
import com.orizonx.client.trackpad.TrackpadSensitivity
import kotlinx.coroutines.delay
import org.json.JSONObject

private val PadShape = RoundedCornerShape(24.dp)
private val PadButtonHeight = 64.dp
private val PadButtonShape = RoundedCornerShape(18.dp)

/**
 * The PC mouse on the device: a big glass pad under the header and two 64 dp buttons below it. The pad recognises the
 * gestures of a laptop touchpad ([TrackpadGestures]); every finger is tracked, so multi-touch works. Moves, scrolls and
 * zooms are sent once per 16 ms frame. The buttons hold their mouse button while pressed (to drag with another finger on
 * the pad). Leaving the screen releases the buttons on the PC.
 */
@Composable
fun TrackpadScreen(
    sensitivity: Float,
    onSensitivity: (Float) -> Unit,
    onAction: (JSONObject) -> Unit,
    onClose: () -> Unit,
    tap: () -> Unit,
    modifier: Modifier = Modifier,
) {
    val send by rememberUpdatedState(onAction)
    val latestTap by rememberUpdatedState(tap)
    val latestSensitivity by rememberUpdatedState(sensitivity)
    val gestures = remember { TrackpadGestures(android.os.SystemClock::elapsedRealtime) }

    fun emit(effects: List<TrackpadEffect>) {
        for (effect in effects) {
            if (effect is TrackpadEffect.Button && effect.down) latestTap()
            send(TrackpadActions.of(effect))
        }
    }

    // One batch per frame: the gesture machine sums what moved in between.
    LaunchedEffect(gestures) {
        while (true) {
            delay(TrackpadGestures.FRAME_MS)
            gestures.sensitivity = latestSensitivity
            emit(gestures.flush())
        }
    }
    DisposableEffect(gestures) {
        onDispose {
            gestures.reset()
            send(TrackpadActions.release())
        }
    }

    Column(modifier.fillMaxSize()) {
        Row(Modifier.fillMaxWidth().height(40.dp), horizontalArrangement = Arrangement.End, verticalAlignment = Alignment.CenterVertically) {
            val closeDescription = tr(S.TRACKPAD_CLOSE_DESC)
            Box(
                Modifier
                    .size(40.dp)
                    .clip(RoundedCornerShape(20.dp))
                    .clickable { tap(); onClose() }
                    .semantics { contentDescription = closeDescription },
                contentAlignment = Alignment.Center,
            ) {
                BasicText("✕", style = TextStyle(color = Color.White, fontSize = 20.sp))
            }
        }
        Box(Modifier.weight(1f).fillMaxWidth().padding(horizontal = 12.dp)) {
            Box(
                Modifier
                    .fillMaxSize()
                    .clip(PadShape)
                    .background(Color.White.copy(alpha = 0.10f))
                    .border(1.dp, Color.White.copy(alpha = 0.30f), PadShape)
                    .pointerInput(gestures) {
                        val density = density
                        awaitPointerEventScope {
                            while (true) {
                                val event = awaitPointerEvent()
                                for (change in event.changes) {
                                    val id = change.id.value
                                    val x = change.position.x / density
                                    val y = change.position.y / density
                                    when {
                                        change.changedToDown() -> emit(gestures.pointerDown(id, x, y))
                                        change.changedToUp() -> emit(gestures.pointerUp(id))
                                        change.positionChanged() -> emit(gestures.pointerMove(id, x, y))
                                    }
                                    change.consume()
                                }
                            }
                        }
                    },
            )
            // A sibling above the pad, so a tap on − / + never reaches the gesture machine.
            SensitivityControl(
                sensitivity,
                onSensitivity,
                tap,
                Modifier.align(Alignment.BottomStart).padding(14.dp),
            )
        }
        Row(
            Modifier.fillMaxWidth().padding(12.dp).height(PadButtonHeight),
            horizontalArrangement = Arrangement.spacedBy(12.dp),
        ) {
            PadButton(S.TRACKPAD_LEFT_DESC, right = false, send = { send(it) }, tap = tap, modifier = Modifier.weight(1f))
            PadButton(S.TRACKPAD_RIGHT_DESC, right = true, send = { send(it) }, tap = tap, modifier = Modifier.weight(1f))
        }
    }
}

/** A mouse button under the pad: `down` when pressed, `up` when released, even if the screen is left meanwhile. */
@Composable
private fun PadButton(label: S, right: Boolean, send: (JSONObject) -> Unit, tap: () -> Unit, modifier: Modifier) {
    var held by remember { mutableStateOf(false) }
    val latestSend by rememberUpdatedState(send)
    val latestTap by rememberUpdatedState(tap)
    Box(
        modifier
            .fillMaxSize()
            .clip(PadButtonShape)
            .background(Color.White.copy(alpha = if (held) 0.34f else 0.12f))
            .border(1.dp, Color.White.copy(alpha = if (held) 0.8f else 0.30f), PadButtonShape)
            .pointerInput(right) {
                awaitEachGesture {
                    val first = awaitFirstDown(requireUnconsumed = false)
                    first.consume()
                    held = true
                    latestTap()
                    latestSend(TrackpadActions.button(right, down = true))
                    try {
                        do {
                            val event = awaitPointerEvent()
                            event.changes.forEach { it.consume() }
                        } while (event.changes.any { it.id == first.id && it.pressed })
                    } finally {
                        held = false
                        latestSend(TrackpadActions.button(right, down = false))
                    }
                }
            },
        contentAlignment = Alignment.Center,
    ) {
        BasicText(
            tr(label),
            style = TextStyle(color = Color.White.copy(alpha = 0.85f), fontSize = 15.sp, textAlign = TextAlign.Center),
        )
    }
}

/** "− x1.0 +": the pointer speed, 0.5 to 3.0 in steps of 0.25. */
@Composable
private fun SensitivityControl(sensitivity: Float, onChange: (Float) -> Unit, tap: () -> Unit, modifier: Modifier) {
    val shape = RoundedCornerShape(22.dp)
    val slower = tr(S.TRACKPAD_SLOWER_DESC)
    val faster = tr(S.TRACKPAD_FASTER_DESC)
    Row(
        modifier
            .clip(shape)
            .background(Color.White.copy(alpha = 0.14f))
            .border(1.dp, Color.White.copy(alpha = 0.30f), shape),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        SensitivityKey("−", enabled = TrackpadSensitivity.canDecrease(sensitivity), description = slower) {
            tap()
            onChange(TrackpadSensitivity.step(sensitivity, -1))
        }
        Box(Modifier.width(64.dp), contentAlignment = Alignment.Center) {
            BasicText(
                TrackpadSensitivity.label(sensitivity, comma = LocalLang.current == Lang.FR),
                style = TextStyle(color = Color.White, fontSize = 15.sp, fontWeight = FontWeight.SemiBold),
            )
        }
        SensitivityKey("+", enabled = TrackpadSensitivity.canIncrease(sensitivity), description = faster) {
            tap()
            onChange(TrackpadSensitivity.step(sensitivity, +1))
        }
    }
}

@Composable
private fun SensitivityKey(symbol: String, enabled: Boolean, description: String, onClick: () -> Unit) {
    Box(
        Modifier
            .size(44.dp)
            .clickable(enabled = enabled, onClick = onClick)
            .semantics { contentDescription = description },
        contentAlignment = Alignment.Center,
    ) {
        BasicText(symbol, style = TextStyle(color = Color.White.copy(alpha = if (enabled) 1f else 0.35f), fontSize = 22.sp))
    }
}
