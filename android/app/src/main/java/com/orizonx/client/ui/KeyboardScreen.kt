package com.orizonx.client.ui

import android.os.SystemClock
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.gestures.awaitEachGesture
import androidx.compose.foundation.gestures.awaitFirstDown
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.BoxWithConstraints
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
import androidx.compose.ui.input.pointer.pointerInput
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.text.TextStyle
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.orizonx.client.i18n.S
import com.orizonx.client.i18n.tr
import com.orizonx.client.keyboard.Gap
import com.orizonx.client.keyboard.KeyEvent
import com.orizonx.client.keyboard.KeySpec
import com.orizonx.client.keyboard.KeyVisual
import com.orizonx.client.keyboard.KeyboardActions
import com.orizonx.client.keyboard.KeyboardGeometry
import com.orizonx.client.keyboard.KeyboardLayout
import com.orizonx.client.keyboard.KeyboardState
import kotlinx.coroutines.delay
import org.json.JSONObject

private val KeyShape = RoundedCornerShape(8.dp)
private const val TICK_MS = 11L
private val CloseRowHeight = 40.dp
private val KeyboardMargin = 6.dp
private val KeyGap = 4.dp

/**
 * The PC keyboard over the whole Actions body (the context bar stays above it): every key is a physical key sent by scan
 * code, so Windows applies its own layout. Each key tracks its own finger (several can be down at once); the behaviour
 * (latches, locks, auto-repeat) lives in [KeyboardState]. Leaving the screen releases every key on the PC.
 */
@Composable
fun KeyboardScreen(
    layout: KeyboardLayout,
    onAction: (JSONObject) -> Unit,
    onClose: () -> Unit,
    tap: () -> Unit,
    modifier: Modifier = Modifier,
) {
    val send by rememberUpdatedState(onAction)
    val state = remember { KeyboardState(SystemClock::elapsedRealtime) }
    var visuals by remember { mutableStateOf<Map<Int, KeyVisual>>(emptyMap()) }
    val pointerCounter = remember { LongArray(1) { 1L } }

    fun emit(events: List<KeyEvent>) {
        for (event in events) send(KeyboardActions.key(event))
        visuals = state.visuals()
    }

    // Auto-repeat: the automaton decides when a held key repeats, this only gives it the beat.
    LaunchedEffect(state) {
        while (true) {
            delay(TICK_MS)
            val events = state.tick()
            if (events.isNotEmpty()) emit(events)
        }
    }
    // Closing the keyboard (or leaving the screen) lets go of everything, here and on the PC.
    DisposableEffect(state) {
        onDispose {
            state.reset()
            send(KeyboardActions.release())
        }
    }

    BoxWithConstraints(modifier.fillMaxSize()) {
        // Square keys: the grid unit is what both the width and the height can hold, the block keeps its proportions.
        val unit = KeyboardGeometry.unit(
            maxWidth.value, (maxHeight - CloseRowHeight).value, KeyboardGeometry.COLUMNS, layout.rows.size, KeyboardMargin.value,
        )
        Column(Modifier.fillMaxSize()) {
            Row(Modifier.fillMaxWidth().height(CloseRowHeight), horizontalArrangement = Arrangement.End, verticalAlignment = Alignment.CenterVertically) {
                val closeDescription = tr(S.KEYBOARD_CLOSE_DESC)
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
            // Free space goes above the keyboard, which sits at the bottom, centred.
            Spacer(Modifier.weight(1f))
            Column(Modifier.align(Alignment.CenterHorizontally).padding(bottom = KeyboardMargin)) {
                for (row in layout.rows) {
                    Row(Modifier.height(unit.dp)) {
                        for (cell in row) {
                            when (cell) {
                                is Gap -> Spacer(Modifier.width((cell.width * unit).dp))
                                is KeySpec -> Box(
                                    Modifier
                                        .width((cell.width * unit).dp)
                                        .height(unit.dp)
                                        .padding(KeyGap / 2),
                                ) {
                                    KeyCap(
                                        cell,
                                        visuals[cell.id] ?: KeyVisual.UP,
                                        Modifier.fillMaxSize(),
                                        onDown = {
                                            val pointer = pointerCounter[0]++
                                            tap()
                                            emit(state.touchDown(pointer, cell))
                                            pointer
                                        },
                                        onUp = { pointer -> emit(state.touchUp(pointer)) },
                                    )
                                }
                            }
                        }
                    }
                }
            }
        }
    }
}

/** One key: big main label, Shift character top left and AltGr character bottom right, both small. */
@Composable
private fun KeyCap(
    key: KeySpec,
    visual: KeyVisual,
    modifier: Modifier,
    onDown: () -> Long,
    onUp: (Long) -> Unit,
) {
    val fill = when (visual) {
        KeyVisual.UP -> 0.10f
        KeyVisual.PRESSED -> 0.38f
        KeyVisual.LATCHED -> 0.24f
        KeyVisual.LOCKED -> 0.24f
    }
    val border = when (visual) {
        KeyVisual.UP -> Color.White.copy(alpha = 0.18f)
        KeyVisual.PRESSED -> Color.White.copy(alpha = 0.6f)
        KeyVisual.LATCHED -> Color.White.copy(alpha = 0.18f)
        KeyVisual.LOCKED -> Color.White.copy(alpha = 0.9f)
    }
    val latestDown by rememberUpdatedState(onDown)
    val latestUp by rememberUpdatedState(onUp)
    Box(
        modifier
            .clip(KeyShape)
            .background(Color.White.copy(alpha = fill))
            .border(if (visual == KeyVisual.LOCKED) 2.dp else 1.dp, border, KeyShape)
            .pointerInput(key.id) {
                awaitEachGesture {
                    val first = awaitFirstDown(requireUnconsumed = false)
                    first.consume()
                    val pointer = latestDown()
                    try {
                        // The key belongs to this finger until it lifts, wherever it slides.
                        do {
                            val event = awaitPointerEvent()
                            event.changes.forEach { it.consume() }
                        } while (event.changes.any { it.id == first.id && it.pressed })
                    } finally {
                        latestUp(pointer)
                    }
                }
            },
        contentAlignment = Alignment.Center,
    ) {
        val main = mainLabel(key)
        BasicText(
            main,
            style = TextStyle(
                color = Color.White,
                fontSize = if (main.length <= 1) 17.sp else 11.sp,
                fontWeight = if (key.modifier) FontWeight.SemiBold else FontWeight.Normal,
                textAlign = TextAlign.Center,
            ),
            maxLines = 1,
            overflow = TextOverflow.Clip,
            modifier = Modifier.padding(horizontal = 2.dp),
        )
        if (key.shift.isNotEmpty()) {
            BasicText(
                key.shift,
                style = TextStyle(color = Color.White.copy(alpha = 0.6f), fontSize = 9.sp),
                maxLines = 1,
                modifier = Modifier.align(Alignment.TopStart).padding(start = 4.dp, top = 2.dp),
            )
        }
        if (key.altGr.isNotEmpty()) {
            BasicText(
                key.altGr,
                style = TextStyle(color = Color(0xFFFAC775).copy(alpha = 0.85f), fontSize = 9.sp),
                maxLines = 1,
                modifier = Modifier.align(Alignment.BottomEnd).padding(end = 4.dp, bottom = 2.dp),
            )
        }
    }
}

/** Letters are shown as capitals, like a keycap; everything else as written. */
internal fun mainLabel(key: KeySpec): String =
    if (key.base.length == 1 && key.base[0].isLetter() && key.shift.isEmpty()) key.base.uppercase() else key.base
