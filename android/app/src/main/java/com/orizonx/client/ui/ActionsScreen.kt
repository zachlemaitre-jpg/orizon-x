package com.orizonx.client.ui

import android.os.SystemClock
import androidx.compose.animation.AnimatedVisibility
import androidx.compose.animation.fadeIn
import androidx.compose.animation.fadeOut
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.gestures.detectHorizontalDragGestures
import androidx.compose.foundation.gestures.detectTapGestures
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.BoxWithConstraints
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.WindowInsets
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.safeDrawing
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.layout.windowInsetsPadding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.BasicText
import androidx.compose.foundation.verticalScroll
import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.mutableLongStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.rememberUpdatedState
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.hapticfeedback.HapticFeedbackType
import androidx.compose.ui.input.pointer.pointerInput
import androidx.compose.ui.platform.LocalHapticFeedback
import androidx.compose.ui.platform.LocalView
import androidx.compose.ui.text.TextStyle
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.orizonx.client.actions.ActionMessages
import com.orizonx.client.actions.ActionThrottle
import com.orizonx.client.actions.ActionsFormat
import com.orizonx.client.actions.ActionsState
import com.orizonx.client.actions.AirplaneState
import com.orizonx.client.actions.AudioState
import com.orizonx.client.actions.BatteryState
import com.orizonx.client.actions.BluetoothState
import com.orizonx.client.actions.BrightnessState
import com.orizonx.client.actions.ClockState
import com.orizonx.client.actions.UsbDrive
import com.orizonx.client.actions.WifiState
import kotlinx.coroutines.Job
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch
import org.json.JSONObject
import kotlin.math.roundToInt

private val Amber = Color(0xFFFAC775)
private val PillShape = RoundedCornerShape(24.dp)
private val TileShape = RoundedCornerShape(18.dp)

/**
 * The Actions remote: clock, PC battery and the controls reported by the PC's latest ACTIONS_STATE ([rawState]).
 * Actions update the displayed state immediately (optimistic); the next ACTIONS_STATE wins.
 */
@Composable
fun ActionsScreen(rawState: JSONObject?, onAction: (JSONObject) -> Unit, onSwitchMode: () -> Unit) {
    val view = LocalView.current
    DisposableEffect(view) {
        view.keepScreenOn = true
        onDispose { view.keepScreenOn = false }
    }
    val haptics = LocalHapticFeedback.current
    val tap: () -> Unit = { haptics.performHapticFeedback(HapticFeedbackType.ContextClick) }
    val send by rememberUpdatedState(onAction)

    val parsed = remember(rawState) { rawState?.let { ActionsState.parse(it) } }
    var shown by remember(parsed) { mutableStateOf(parsed) }
    val update: (ActionsState.() -> ActionsState) -> Unit = { change -> shown = shown?.change() }

    // A notice arrives in exactly one state: show it for ~3 s even though newer states keep coming.
    var noticeText by remember { mutableStateOf<String?>(null) }
    var noticeSeq by remember { mutableIntStateOf(0) }
    LaunchedEffect(parsed) {
        parsed?.notice?.let {
            noticeText = ActionsFormat.notice(it.code)
            noticeSeq++
        }
    }
    LaunchedEffect(noticeSeq) {
        if (noticeSeq > 0) {
            delay(NOTICE_MS)
            noticeText = null
        }
    }

    val volumeThrottle = remember { ActionThrottle(clock = SystemClock::elapsedRealtime) { send(ActionMessages.volumeSet(it)) } }
    val brightnessThrottle = remember { ActionThrottle(clock = SystemClock::elapsedRealtime) { send(ActionMessages.brightnessSet(it)) } }

    val controls = Controls(
        send = { send(it) },
        tap = tap,
        update = update,
        volumeThrottle = volumeThrottle,
        brightnessThrottle = brightnessThrottle,
    )

    BoxWithConstraints(Modifier.fillMaxSize()) {
        BlobBackground()
        val landscape = maxWidth > maxHeight
        Box(Modifier.fillMaxSize().windowInsetsPadding(WindowInsets.safeDrawing)) {
            Column(Modifier.fillMaxSize().padding(horizontal = 16.dp)) {
                Row(Modifier.fillMaxWidth().padding(top = 8.dp), horizontalArrangement = Arrangement.End) {
                    Pill("Changer de mode", selected = false, onClick = { tap(); onSwitchMode() })
                }
                val state = shown
                if (state == null) {
                    Box(Modifier.fillMaxSize(), contentAlignment = Alignment.Center) {
                        GlassText("Connexion au PC…", size = 16.sp, alpha = 0.8f)
                    }
                } else if (landscape) {
                    LandscapeLayout(state, controls)
                } else {
                    PortraitLayout(state, controls)
                }
            }
            AnimatedVisibility(
                visible = noticeText != null,
                modifier = Modifier.align(Alignment.BottomCenter).padding(bottom = 24.dp, start = 16.dp, end = 16.dp),
                enter = fadeIn(),
                exit = fadeOut(),
            ) {
                GlassPanel { GlassText(noticeText ?: "", size = 15.sp, color = Amber) }
            }
        }
    }
}

private const val NOTICE_MS = 3000L
private const val SLIDER_HOLD_MS = 700L

/** Everything a card needs to act: send, haptics, optimistic update and the slider throttles. */
private class Controls(
    val send: (JSONObject) -> Unit,
    val tap: () -> Unit,
    val update: (ActionsState.() -> ActionsState) -> Unit,
    val volumeThrottle: ActionThrottle,
    val brightnessThrottle: ActionThrottle,
)

@Composable
private fun PortraitLayout(state: ActionsState, c: Controls) {
    Column(
        Modifier.fillMaxSize().verticalScroll(rememberScrollState()),
        verticalArrangement = Arrangement.spacedBy(14.dp),
    ) {
        ClockBlock(state.clock, state.battery, Modifier.fillMaxWidth().padding(vertical = 8.dp), Alignment.CenterHorizontally)
        for (card in cards(state, c)) card()
        Spacer(Modifier.height(24.dp))
    }
}

@Composable
private fun LandscapeLayout(state: ActionsState, c: Controls) {
    Row(Modifier.fillMaxSize(), horizontalArrangement = Arrangement.spacedBy(16.dp)) {
        Box(Modifier.weight(0.35f).fillMaxSize(), contentAlignment = Alignment.Center) {
            ClockBlock(state.clock, state.battery, Modifier.fillMaxWidth(), Alignment.Start)
        }
        val all = cards(state, c)
        Row(
            Modifier.weight(0.65f).fillMaxSize().verticalScroll(rememberScrollState()),
            horizontalArrangement = Arrangement.spacedBy(14.dp),
        ) {
            for (parity in 0..1) {
                Column(Modifier.weight(1f), verticalArrangement = Arrangement.spacedBy(14.dp)) {
                    all.filterIndexed { i, _ -> i % 2 == parity }.forEach { it() }
                    Spacer(Modifier.height(24.dp))
                }
            }
        }
    }
}

/** The controls the PC reports as available, in display order. */
private fun cards(state: ActionsState, c: Controls): List<@Composable () -> Unit> {
    val list = mutableListOf<@Composable () -> Unit>()
    if (state.audio != null || state.mediaAvailable) list += { SoundCard(state, c) }
    state.brightness?.let { b -> list += { BrightnessCard(b, c) } }
    if (state.wifi != null || state.bluetooth != null || state.airplane != null) list += { RadioTiles(state, c) }
    for (drive in state.usb) list += { UsbCard(drive, c) }
    return list
}

// --- Clock ---------------------------------------------------------------------------------

/** Ticks locally from the PC's epoch_ms plus the time elapsed since the state arrived, in the PC's UTC offset. */
@Composable
private fun ClockBlock(clock: ClockState?, battery: BatteryState?, modifier: Modifier, align: Alignment.Horizontal) {
    val received = remember(clock) { SystemClock.elapsedRealtime() }
    var now by remember(clock) { mutableLongStateOf(clock?.epochMs ?: 0L) }
    LaunchedEffect(clock) {
        if (clock != null) {
            while (true) {
                now = clock.epochMs + (SystemClock.elapsedRealtime() - received)
                delay(1000 - Math.floorMod(now, 1000L))
            }
        }
    }
    Column(modifier, horizontalAlignment = align) {
        if (clock != null) {
            val offset = clock.utcOffsetMin
            Row(verticalAlignment = Alignment.Bottom) {
                BasicText(
                    ActionsFormat.hoursMinutes(now, offset),
                    style = TextStyle(color = Color.White, fontSize = 64.sp, fontWeight = FontWeight.Light, fontFeatureSettings = "tnum"),
                )
                Spacer(Modifier.width(6.dp))
                BasicText(
                    ":" + ActionsFormat.seconds(now, offset),
                    style = TextStyle(color = Color.White.copy(alpha = 0.6f), fontSize = 28.sp, fontWeight = FontWeight.Light, fontFeatureSettings = "tnum"),
                    modifier = Modifier.padding(bottom = 10.dp),
                )
            }
            GlassText(ActionsFormat.date(now, offset), size = 20.sp, alpha = 0.9f)
        }
        if (battery != null) {
            Spacer(Modifier.height(6.dp))
            GlassText(ActionsFormat.battery(battery), size = 16.sp, alpha = 0.75f)
        }
    }
}

// --- Cards ---------------------------------------------------------------------------------

@Composable
private fun SoundCard(state: ActionsState, c: Controls) {
    val audio = state.audio
    GlassCard(Modifier.fillMaxWidth()) {
        GlassText("Son", size = 16.sp, weight = FontWeight.SemiBold)
        if (audio != null) {
            Spacer(Modifier.height(8.dp))
            Row(verticalAlignment = Alignment.CenterVertically) {
                GlassSlider(
                    value = audio.volume,
                    onChange = { v ->
                        c.update { copy(audio = AudioState(v, audio.muted)) }
                        c.volumeThrottle.onChange(v)
                    },
                    onFinish = { v ->
                        c.update { copy(audio = AudioState(v, audio.muted)) }
                        c.volumeThrottle.onRelease(v)
                    },
                    modifier = Modifier.weight(1f),
                )
                Spacer(Modifier.width(12.dp))
                Box(Modifier.width(52.dp), contentAlignment = Alignment.CenterEnd) {
                    GlassText(if (audio.muted) "Muet" else "${(audio.volume * 100).roundToInt()} %", size = 16.sp)
                }
            }
            Spacer(Modifier.height(10.dp))
        }
        Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.spacedBy(8.dp), verticalAlignment = Alignment.CenterVertically) {
            if (audio != null) {
                Pill("Muet", selected = audio.muted, onClick = {
                    c.tap()
                    c.update { copy(audio = AudioState(audio.volume, !audio.muted)) }
                    c.send(ActionMessages.volumeMute(!audio.muted))
                })
            }
            if (state.mediaAvailable) {
                Spacer(Modifier.weight(1f))
                RoundKey("⏮") { c.tap(); c.send(ActionMessages.mediaPrevious()) }
                RoundKey("⏯") { c.tap(); c.send(ActionMessages.mediaPlayPause()) }
                RoundKey("⏭") { c.tap(); c.send(ActionMessages.mediaNext()) }
            }
        }
    }
}

@Composable
private fun BrightnessCard(brightness: BrightnessState, c: Controls) {
    GlassCard(Modifier.fillMaxWidth()) {
        GlassText("Luminosité", size = 16.sp, weight = FontWeight.SemiBold)
        Spacer(Modifier.height(8.dp))
        Row(verticalAlignment = Alignment.CenterVertically) {
            GlassSlider(
                value = brightness.value,
                onChange = { v ->
                    c.update { copy(brightness = BrightnessState(v)) }
                    c.brightnessThrottle.onChange(v)
                },
                onFinish = { v ->
                    c.update { copy(brightness = BrightnessState(v)) }
                    c.brightnessThrottle.onRelease(v)
                },
                modifier = Modifier.weight(1f),
            )
            Spacer(Modifier.width(12.dp))
            Box(Modifier.width(52.dp), contentAlignment = Alignment.CenterEnd) {
                GlassText("${(brightness.value * 100).roundToInt()} %", size = 16.sp)
            }
        }
    }
}

@Composable
private fun RadioTiles(state: ActionsState, c: Controls) {
    Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.spacedBy(10.dp)) {
        state.wifi?.let { wifi: WifiState ->
            Tile("Wi-Fi", wifi.ssid ?: onOff(wifi.on), wifi.on, Modifier.weight(1f)) {
                c.tap()
                c.update { copy(wifi = WifiState(!wifi.on, wifi.ssid)) }
                c.send(ActionMessages.wifiSet(!wifi.on))
            }
        }
        state.bluetooth?.let { bt: BluetoothState ->
            Tile("Bluetooth", bt.connected.firstOrNull() ?: onOff(bt.on), bt.on, Modifier.weight(1f)) {
                c.tap()
                c.update { copy(bluetooth = BluetoothState(!bt.on, bt.connected)) }
                c.send(ActionMessages.bluetoothSet(!bt.on))
            }
        }
        state.airplane?.let { plane: AirplaneState ->
            Tile("Avion", onOff(plane.on), plane.on, Modifier.weight(1f)) {
                c.tap()
                c.update { copy(airplane = AirplaneState(!plane.on)) }
                c.send(ActionMessages.airplaneSet(!plane.on))
            }
        }
    }
}

private fun onOff(on: Boolean) = if (on) "Activé" else "Désactivé"

@Composable
private fun UsbCard(drive: UsbDrive, c: Controls) {
    GlassCard(Modifier.fillMaxWidth()) {
        Row(verticalAlignment = Alignment.CenterVertically) {
            Box(Modifier.weight(1f)) {
                BasicText(
                    drive.label.ifBlank { "Clé USB" },
                    style = TextStyle(color = Color.White, fontSize = 16.sp, fontWeight = FontWeight.SemiBold),
                    maxLines = 1,
                    overflow = TextOverflow.Ellipsis,
                )
            }
            Spacer(Modifier.width(8.dp))
            GlassText(drive.drive, size = 16.sp, alpha = 0.8f)
        }
        drive.freeBytes?.let {
            Spacer(Modifier.height(4.dp))
            GlassText(ActionsFormat.freeSpace(it), size = 14.sp, alpha = 0.75f)
        }
        Spacer(Modifier.height(12.dp))
        Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.spacedBy(10.dp)) {
            GlassButton("Ouvrir", selected = false, modifier = Modifier.weight(1f), onClick = {
                c.tap()
                c.send(ActionMessages.usbOpen(drive.drive))
            })
            GlassButton("Éjecter", selected = false, modifier = Modifier.weight(1f), onClick = {
                c.tap()
                c.send(ActionMessages.usbEject(drive.drive))
            })
        }
    }
}

// --- Controls ------------------------------------------------------------------------------

@Composable
private fun Pill(text: String, selected: Boolean, onClick: () -> Unit, modifier: Modifier = Modifier) {
    Box(
        modifier
            .heightIn(min = 44.dp)
            .clip(PillShape)
            .background(Color.White.copy(alpha = if (selected) 0.30f else 0.10f))
            .border(1.dp, Color.White.copy(alpha = if (selected) 0.8f else 0.25f), PillShape)
            .clickable(onClick = onClick)
            .padding(horizontal = 16.dp, vertical = 8.dp),
        contentAlignment = Alignment.Center,
    ) {
        GlassText(text, size = 15.sp, weight = if (selected) FontWeight.SemiBold else FontWeight.Normal)
    }
}

@Composable
private fun RoundKey(glyph: String, onClick: () -> Unit) {
    Box(
        Modifier
            .size(52.dp)
            .clip(CircleShape)
            .background(Color.White.copy(alpha = 0.10f))
            .border(1.dp, Color.White.copy(alpha = 0.25f), CircleShape)
            .clickable(onClick = onClick),
        contentAlignment = Alignment.Center,
    ) {
        GlassText(glyph, size = 22.sp, align = TextAlign.Center)
    }
}

@Composable
private fun Tile(title: String, subtitle: String, on: Boolean, modifier: Modifier, onClick: () -> Unit) {
    Column(
        modifier
            .heightIn(min = 92.dp)
            .clip(TileShape)
            .background(Color.White.copy(alpha = if (on) 0.28f else 0.08f))
            .border(if (on) 2.dp else 1.dp, Color.White.copy(alpha = if (on) 0.85f else 0.25f), TileShape)
            .clickable(onClick = onClick)
            .padding(12.dp),
        horizontalAlignment = Alignment.CenterHorizontally,
        verticalArrangement = Arrangement.Center,
    ) {
        GlassText(title, size = 16.sp, weight = if (on) FontWeight.SemiBold else FontWeight.Normal, alpha = if (on) 1f else 0.8f)
        Spacer(Modifier.height(4.dp))
        BasicText(
            subtitle,
            style = TextStyle(color = Color.White.copy(alpha = 0.7f), fontSize = 12.sp, textAlign = TextAlign.Center),
            maxLines = 1,
            overflow = TextOverflow.Ellipsis,
        )
    }
}

/**
 * Horizontal 0..1 slider. While dragging (and for [SLIDER_HOLD_MS] after release) it shows its own value
 * so the PC's echo of an older value does not make the thumb jump back.
 */
@Composable
private fun GlassSlider(value: Float, onChange: (Float) -> Unit, onFinish: (Float) -> Unit, modifier: Modifier = Modifier) {
    var pending by remember { mutableStateOf<Float?>(null) }
    var holdJob by remember { mutableStateOf<Job?>(null) }
    val scope = rememberCoroutineScope()
    val change by rememberUpdatedState(onChange)
    val finish by rememberUpdatedState(onFinish)
    val shown = (pending ?: value).coerceIn(0f, 1f)

    fun move(v: Float) {
        holdJob?.cancel()
        holdJob = null
        pending = v
        change(v)
    }

    fun release() {
        val v = pending ?: return
        finish(v)
        holdJob?.cancel()
        holdJob = scope.launch {
            delay(SLIDER_HOLD_MS)
            pending = null
        }
    }

    Box(
        modifier
            .height(44.dp)
            .pointerInput(Unit) {
                detectTapGestures(onTap = { offset ->
                    move((offset.x / size.width).coerceIn(0f, 1f))
                    release()
                })
            }
            .pointerInput(Unit) {
                detectHorizontalDragGestures(
                    onDragStart = { offset -> move((offset.x / size.width).coerceIn(0f, 1f)) },
                    onDragEnd = { release() },
                    onDragCancel = { release() },
                    onHorizontalDrag = { pointer, _ -> move((pointer.position.x / size.width).coerceIn(0f, 1f)) },
                )
            },
        contentAlignment = Alignment.CenterStart,
    ) {
        Box(Modifier.fillMaxWidth().height(8.dp).clip(CircleShape).background(Color.White.copy(alpha = 0.2f)))
        Box(Modifier.fillMaxWidth(shown).height(8.dp).clip(CircleShape).background(Color.White.copy(alpha = 0.85f)))
        Row(Modifier.fillMaxWidth(), verticalAlignment = Alignment.CenterVertically) {
            Spacer(Modifier.weight(shown.coerceAtLeast(0.001f)))
            Box(Modifier.size(26.dp).background(Color.White, CircleShape))
            Spacer(Modifier.weight((1f - shown).coerceAtLeast(0.001f)))
        }
    }
}
