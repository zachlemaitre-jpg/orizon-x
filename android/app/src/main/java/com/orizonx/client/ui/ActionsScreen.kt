package com.orizonx.client.ui

import android.os.SystemClock
import androidx.compose.animation.AnimatedVisibility
import androidx.compose.animation.fadeIn
import androidx.compose.animation.fadeOut
import androidx.compose.foundation.Canvas
import androidx.compose.foundation.Image
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.gestures.detectHorizontalDragGestures
import androidx.compose.foundation.gestures.detectTapGestures
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.BoxScope
import androidx.compose.foundation.layout.BoxWithConstraints
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ColumnScope
import androidx.compose.foundation.layout.IntrinsicSize
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.WindowInsets
import androidx.compose.foundation.layout.fillMaxHeight
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.safeDrawing
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.layout.widthIn
import androidx.compose.foundation.layout.windowInsetsPadding
import androidx.compose.foundation.layout.wrapContentHeight
import androidx.compose.foundation.horizontalScroll
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
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.geometry.CornerRadius
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.geometry.Size
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.ColorFilter
import androidx.compose.ui.graphics.ImageBitmap
import androidx.compose.ui.graphics.Path
import androidx.compose.ui.graphics.Shadow
import androidx.compose.ui.graphics.StrokeCap
import androidx.compose.ui.graphics.drawscope.Stroke
import androidx.compose.ui.hapticfeedback.HapticFeedbackType
import androidx.compose.ui.input.pointer.pointerInput
import androidx.compose.ui.platform.LocalDensity
import androidx.compose.ui.platform.LocalHapticFeedback
import androidx.compose.ui.platform.LocalView
import androidx.compose.ui.res.painterResource
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.text.TextStyle
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.orizonx.client.R
import com.orizonx.client.actions.ActionMessages
import com.orizonx.client.actions.ActionThrottle
import com.orizonx.client.actions.ActionsFormat
import com.orizonx.client.actions.ActionsState
import com.orizonx.client.actions.AirplaneState
import com.orizonx.client.actions.AudioState
import com.orizonx.client.actions.BatteryLevel
import com.orizonx.client.actions.BatteryState
import com.orizonx.client.actions.BluetoothState
import com.orizonx.client.actions.BrightnessState
import com.orizonx.client.actions.ClockState
import com.orizonx.client.actions.NowPlaying
import com.orizonx.client.actions.UsbDrive
import com.orizonx.client.actions.WifiState
import kotlinx.coroutines.Job
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch
import org.json.JSONObject
import kotlin.math.min
import kotlin.math.roundToInt

private val Amber = Color(0xFFFAC775)
private val MuteRed = Color(0xFFFF6B6B)
private val BatteryGreen = Color(0xFF34C77B)
private val BatteryAmber = Color(0xFFF2A93B)
private val BatteryRed = Color(0xFFE5484D)
private val PillShape = RoundedCornerShape(24.dp)
private val TileShape = RoundedCornerShape(18.dp)
private val CoverShape = RoundedCornerShape(16.dp)
private val ChipShape = RoundedCornerShape(20.dp)
private val UsbChipMaxWidth = 280.dp

/**
 * The Actions remote: clock, PC battery and the controls reported by the PC's latest ACTIONS_STATE ([rawState]).
 * Actions update the displayed state immediately (optimistic); the next ACTIONS_STATE wins.
 * [artwork] is the last cover received (id, bitmap); it is shown only while it matches `now_playing.artwork`.
 */
@Composable
fun ActionsScreen(
    rawState: JSONObject?,
    artwork: Pair<String, ImageBitmap>?,
    onAction: (JSONObject) -> Unit,
    onSwitchMode: () -> Unit,
) {
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
        artwork = artwork,
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
                } else {
                    ActionsBody(state, controls, landscape, Modifier.fillMaxWidth().weight(1f))
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
    val artwork: Pair<String, ImageBitmap>?,
)

/**
 * Clock, date and PC battery centred at the top; the controls form a centred block anchored to the bottom.
 * Scrolls only when the content does not fit.
 */
@Composable
private fun ActionsBody(state: ActionsState, c: Controls, landscape: Boolean, modifier: Modifier) {
    BoxWithConstraints(modifier) {
        val viewport = maxHeight
        // MAZAGLA is wide: "HH:MM" (fixed digit cells) plus the small seconds is ~3.75 em: scale the font so it never clips.
        val clockSp = min(if (landscape) 112f else 80f, maxWidth.value / 4.1f)
        Column(Modifier.fillMaxSize().verticalScroll(rememberScrollState())) {
            Column(Modifier.fillMaxWidth().heightIn(min = viewport), horizontalAlignment = Alignment.CenterHorizontally) {
                ClockBlock(state.clock, state.battery, clockSp, if (landscape) 26f else 22f)
                Spacer(Modifier.height(16.dp))
                if (landscape) {
                    // The free space between the clock and the bottom block holds the USB side rail, on the right edge.
                    Box(Modifier.weight(1f).fillMaxWidth()) { UsbRail(state.usb, c) }
                    LandscapeControls(state, c)
                } else {
                    Spacer(Modifier.weight(1f))
                    PortraitControls(state.usb, c, cards(state, c))
                }
                Spacer(Modifier.height(16.dp))
            }
        }
    }
}

/** USB chips in a scrollable row just above the bottom column (nothing without a drive). */
@Composable
private fun PortraitControls(usb: List<UsbDrive>, c: Controls, all: List<@Composable () -> Unit>) {
    Column(Modifier.widthIn(max = 560.dp).fillMaxWidth(), verticalArrangement = Arrangement.spacedBy(14.dp)) {
        if (usb.isNotEmpty()) {
            Row(
                Modifier.fillMaxWidth().horizontalScroll(rememberScrollState()),
                horizontalArrangement = Arrangement.spacedBy(10.dp),
            ) {
                for (drive in usb) UsbChip(drive, c, Modifier.width(UsbChipMaxWidth))
            }
        }
        for (card in all) card()
    }
}

/** Side rail on the right edge: one chip per drive, stacked; nothing without a drive. */
@Composable
private fun BoxScope.UsbRail(usb: List<UsbDrive>, c: Controls) {
    if (usb.isEmpty()) return
    Column(
        Modifier.align(Alignment.CenterEnd).wrapContentHeight(unbounded = true).width(UsbChipMaxWidth),
        verticalArrangement = Arrangement.spacedBy(10.dp),
    ) {
        for (drive in usb) UsbChip(drive, c, Modifier.fillMaxWidth())
    }
}

/**
 * Two columns with the same top and bottom: Son on the left; Luminosité with the Wi-Fi/Bluetooth/Avion tiles under it
 * on the right. A lone column is centred. USB drives are not here: they live in the side rail ([UsbRail]).
 */
@Composable
private fun LandscapeControls(state: ActionsState, c: Controls) {
    val sound = hasSound(state)
    val brightness = state.brightness
    val radios = hasRadios(state)
    val right = brightness != null || radios
    val nowPlaying = state.nowPlaying
    if (!sound && !right && nowPlaying == null) return
    Column(Modifier.widthIn(max = 920.dp).fillMaxWidth(), verticalArrangement = Arrangement.spacedBy(14.dp)) {
        if (nowPlaying != null) NowPlayingCard(nowPlaying, c)
        if (sound && right) {
            Row(Modifier.fillMaxWidth().height(IntrinsicSize.Min), horizontalArrangement = Arrangement.spacedBy(14.dp)) {
                SoundCard(state, c, Modifier.weight(1f).fillMaxHeight(), stretch = true)
                Column(Modifier.weight(1f).fillMaxHeight(), verticalArrangement = Arrangement.spacedBy(14.dp)) {
                    RightColumn(state, c, brightness, radios)
                }
            }
        } else if (sound) {
            Box(Modifier.fillMaxWidth(), contentAlignment = Alignment.TopCenter) {
                SoundCard(state, c, Modifier.widthIn(max = 460.dp).fillMaxWidth())
            }
        } else if (right) {
            Box(Modifier.fillMaxWidth(), contentAlignment = Alignment.TopCenter) {
                Column(Modifier.widthIn(max = 460.dp).fillMaxWidth(), verticalArrangement = Arrangement.spacedBy(14.dp)) {
                    RightColumn(state, c, brightness, radios)
                }
            }
        }
    }
}

/** Luminosité then the radio tiles; the last element takes the remaining height of the column. */
@Composable
private fun ColumnScope.RightColumn(state: ActionsState, c: Controls, brightness: BrightnessState?, radios: Boolean) {
    if (brightness != null) {
        BrightnessCard(brightness, c, if (radios) Modifier.fillMaxWidth() else Modifier.fillMaxWidth().weight(1f))
    }
    if (radios) RadioTiles(state, c, Modifier.fillMaxWidth().weight(1f))
}

/** The media keys live in the "En cours de lecture" card when it is shown, in the Son card otherwise. */
private fun soundKeys(state: ActionsState) = state.mediaAvailable && state.nowPlaying == null

private fun hasSound(state: ActionsState) = state.audio != null || soundKeys(state)
private fun hasRadios(state: ActionsState) = state.wifi != null || state.bluetooth != null || state.airplane != null

/** The controls the PC reports as available, in display order. */
private fun cards(state: ActionsState, c: Controls): List<@Composable () -> Unit> {
    val list = mutableListOf<@Composable () -> Unit>()
    state.nowPlaying?.let { n -> list += { NowPlayingCard(n, c) } }
    if (hasSound(state)) list += { SoundCard(state, c) }
    state.brightness?.let { b -> list += { BrightnessCard(b, c) } }
    if (hasRadios(state)) list += { RadioTiles(state, c) }
    return list
}

// --- Clock ---------------------------------------------------------------------------------

/** Ticks locally from the PC's epoch_ms plus the time elapsed since the state arrived, in the PC's UTC offset. */
@Composable
private fun ClockBlock(clock: ClockState?, battery: BatteryState?, clockSp: Float, dateSp: Float) {
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
    Column(Modifier.fillMaxWidth(), horizontalAlignment = Alignment.CenterHorizontally) {
        if (clock != null) {
            val offset = clock.utcOffsetMin
            Row(verticalAlignment = Alignment.Bottom) {
                ClockDigits(ActionsFormat.hoursMinutes(now, offset), clockSp, Color.White)
                Spacer(Modifier.width((clockSp / 14f).dp))
                ClockDigits(
                    ":" + ActionsFormat.seconds(now, offset),
                    clockSp * 0.36f,
                    Color.White.copy(alpha = 0.6f),
                    Modifier.padding(bottom = (clockSp * 0.16f).dp),
                )
            }
            GlassText(ActionsFormat.date(now, offset), size = dateSp.sp, alpha = 0.9f)
        }
        if (battery != null) {
            Spacer(Modifier.height(10.dp))
            BatteryPicto(battery)
        }
    }
}

/**
 * Clock text in MAZAGLA. Its digits are proportional (the "1" is narrower), so every character gets a fixed cell:
 * the clock keeps a constant width instead of shifting every second.
 */
@Composable
private fun ClockDigits(text: String, sizeSp: Float, color: Color, modifier: Modifier = Modifier) {
    val density = LocalDensity.current
    val style = TextStyle(color = color, fontSize = sizeSp.sp, fontFamily = BrandFont, fontWeight = FontWeight.Normal)
    Row(modifier) {
        for (ch in text) {
            val cell: Dp = with(density) { (sizeSp * (if (ch == ':') 0.30f else 0.69f)).sp.toDp() }
            Box(Modifier.width(cell), contentAlignment = Alignment.Center) {
                BasicText(ch.toString(), style = style, maxLines = 1, softWrap = false)
            }
        }
    }
}

/** White Material icon from [res], tinted; [alpha] dims it. */
@Composable
private fun Picto(res: Int, size: Dp, alpha: Float = 1f, modifier: Modifier = Modifier) {
    Image(
        painterResource(res),
        contentDescription = null,
        modifier = modifier.size(size),
        colorFilter = ColorFilter.tint(Color.White.copy(alpha = alpha)),
    )
}

/** Battery drawn with a Canvas: outline, terminal nub, proportional fill and the percentage inside; a bolt when charging. */
@Composable
private fun BatteryPicto(battery: BatteryState) {
    val fillColor = when (ActionsFormat.batteryLevel(battery.percent)) {
        BatteryLevel.NORMAL -> BatteryGreen
        BatteryLevel.LOW -> BatteryAmber
        BatteryLevel.CRITICAL -> BatteryRed
    }
    val fraction = ActionsFormat.batteryFill(battery.percent)
    Row(verticalAlignment = Alignment.CenterVertically) {
        Box(Modifier.size(width = 76.dp, height = 32.dp), contentAlignment = Alignment.Center) {
            Canvas(Modifier.fillMaxSize()) {
                val nubW = 4.dp.toPx()
                val stroke = 2.dp.toPx()
                val bodyW = size.width - nubW
                val outline = Color.White.copy(alpha = 0.85f)
                drawRoundRect(
                    outline,
                    topLeft = Offset(stroke / 2, stroke / 2),
                    size = Size(bodyW - stroke, size.height - stroke),
                    cornerRadius = CornerRadius(8.dp.toPx()),
                    style = Stroke(stroke),
                )
                drawRoundRect(
                    outline,
                    topLeft = Offset(bodyW, size.height * 0.32f),
                    size = Size(nubW, size.height * 0.36f),
                    cornerRadius = CornerRadius(1.5.dp.toPx()),
                )
                val pad = stroke + 1.5.dp.toPx()
                val innerW = bodyW - 2 * pad
                val fillW = if (fraction > 0f) (innerW * fraction).coerceAtLeast(6.dp.toPx()) else 0f
                if (fillW > 0f) {
                    drawRoundRect(
                        fillColor.copy(alpha = 0.9f),
                        topLeft = Offset(pad, pad),
                        size = Size(fillW, size.height - 2 * pad),
                        cornerRadius = CornerRadius(5.dp.toPx()),
                    )
                }
            }
            BasicText(
                "${battery.percent}%",
                style = TextStyle(
                    color = Color.White,
                    fontSize = 15.sp,
                    fontWeight = FontWeight.Bold,
                    fontFeatureSettings = "tnum",
                    shadow = Shadow(Color.Black.copy(alpha = 0.55f), Offset(0f, 1f), 3f),
                ),
                modifier = Modifier.padding(end = 4.dp),
                maxLines = 1,
                softWrap = false,
            )
        }
        if (battery.charging) {
            Spacer(Modifier.width(6.dp))
            BoltIcon(Modifier.size(width = 14.dp, height = 24.dp))
        }
    }
}

@Composable
private fun BoltIcon(modifier: Modifier) {
    Canvas(modifier) {
        val w = size.width
        val h = size.height
        val bolt = Path().apply {
            moveTo(0.62f * w, 0f)
            lineTo(0.05f * w, 0.56f * h)
            lineTo(0.45f * w, 0.56f * h)
            lineTo(0.30f * w, h)
            lineTo(0.95f * w, 0.40f * h)
            lineTo(0.55f * w, 0.40f * h)
            close()
        }
        drawPath(bolt, Amber)
    }
}

/** Speaker with sound waves; with a diagonal slash when [muted]. */
@Composable
private fun SpeakerIcon(muted: Boolean, tint: Color, modifier: Modifier = Modifier) {
    Canvas(modifier) {
        val u = size.minDimension / 24f
        val body = Path().apply {
            moveTo(3f * u, 9f * u)
            lineTo(7f * u, 9f * u)
            lineTo(12.5f * u, 4.5f * u)
            lineTo(12.5f * u, 19.5f * u)
            lineTo(7f * u, 15f * u)
            lineTo(3f * u, 15f * u)
            close()
        }
        drawPath(body, tint)
        if (muted) {
            val from = Offset(3.5f * u, 3.5f * u)
            val to = Offset(20.5f * u, 20.5f * u)
            drawLine(Color.Black.copy(alpha = 0.35f), from, to, strokeWidth = 4.6f * u, cap = StrokeCap.Round)
            drawLine(tint, from, to, strokeWidth = 2.4f * u, cap = StrokeCap.Round)
        } else {
            for (r in listOf(4.5f, 8.5f)) {
                drawArc(
                    tint,
                    startAngle = -50f,
                    sweepAngle = 100f,
                    useCenter = false,
                    topLeft = Offset((11f - r) * u, (12f - r) * u),
                    size = Size(2 * r * u, 2 * r * u),
                    style = Stroke(1.9f * u, cap = StrokeCap.Round),
                )
            }
        }
    }
}

// --- Cards ---------------------------------------------------------------------------------

@Composable
private fun SoundCard(state: ActionsState, c: Controls, modifier: Modifier = Modifier.fillMaxWidth(), stretch: Boolean = false) {
    val audio = state.audio
    GlassCard(modifier) {
        Row(verticalAlignment = Alignment.CenterVertically) {
            val muted = audio?.muted == true
            SpeakerIcon(muted, if (muted) MuteRed else Color.White, Modifier.size(24.dp))
            Spacer(Modifier.width(8.dp))
            GlassText("Son", size = 16.sp, weight = FontWeight.SemiBold)
        }
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
        // In the equal-height landscape row the card may be taller than its content: push the keys to the bottom.
        if (stretch) Spacer(Modifier.weight(1f))
        Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.spacedBy(8.dp), verticalAlignment = Alignment.CenterVertically) {
            if (audio != null) {
                MuteButton(audio.muted, onClick = {
                    c.tap()
                    c.update { copy(audio = AudioState(audio.volume, !audio.muted)) }
                    c.send(ActionMessages.volumeMute(!audio.muted))
                })
            }
            if (soundKeys(state)) {
                Spacer(Modifier.weight(1f))
                RoundKey("⏮") { c.tap(); c.send(ActionMessages.mediaPrevious()) }
                RoundKey("⏯") { c.tap(); c.send(ActionMessages.mediaPlayPause()) }
                RoundKey("⏭") { c.tap(); c.send(ActionMessages.mediaNext()) }
            }
        }
    }
}

/** Cover (placeholder note when missing or not the announced one), track texts and the media keys. */
@Composable
private fun NowPlayingCard(now: NowPlaying, c: Controls, modifier: Modifier = Modifier.fillMaxWidth()) {
    val cover = c.artwork?.takeIf { now.artworkId != null && it.first == now.artworkId }?.second
    GlassCard(modifier) {
        Row(Modifier.fillMaxWidth().height(IntrinsicSize.Min), horizontalArrangement = Arrangement.spacedBy(16.dp)) {
            Box(
                Modifier.size(120.dp).clip(CoverShape).background(Color.White.copy(alpha = 0.10f)),
                contentAlignment = Alignment.Center,
            ) {
                if (cover != null) {
                    Image(cover, contentDescription = null, modifier = Modifier.fillMaxSize(), contentScale = ContentScale.Crop)
                } else {
                    Picto(R.drawable.ic_action_music_note, 56.dp, alpha = 0.6f)
                }
            }
            Column(Modifier.weight(1f).fillMaxHeight(), verticalArrangement = Arrangement.SpaceBetween) {
                Column {
                    OneLine(now.title.ifBlank { "Lecture en cours" }, 18.sp, FontWeight.Bold, 1f)
                    val details = listOf(now.artist, now.album).filter { it.isNotBlank() }.joinToString(" · ")
                    if (details.isNotEmpty()) OneLine(details, 14.sp, FontWeight.Normal, 0.8f)
                    if (now.app.isNotBlank()) OneLine(now.app, 12.sp, FontWeight.Normal, 0.55f)
                }
                Spacer(Modifier.height(8.dp))
                Row(horizontalArrangement = Arrangement.spacedBy(10.dp), verticalAlignment = Alignment.CenterVertically) {
                    RoundIconKey(R.drawable.ic_action_skip_previous) { c.tap(); c.send(ActionMessages.mediaPrevious()) }
                    RoundIconKey(if (now.playing) R.drawable.ic_action_pause else R.drawable.ic_action_play) {
                        c.tap()
                        c.update { copy(nowPlaying = nowPlaying?.copy(playing = !now.playing)) }
                        c.send(ActionMessages.mediaPlayPause())
                    }
                    RoundIconKey(R.drawable.ic_action_skip_next) { c.tap(); c.send(ActionMessages.mediaNext()) }
                }
            }
        }
    }
}

@Composable
private fun OneLine(text: String, size: androidx.compose.ui.unit.TextUnit, weight: FontWeight, alpha: Float) {
    BasicText(
        text,
        style = TextStyle(color = Color.White.copy(alpha = alpha), fontSize = size, fontWeight = weight),
        maxLines = 1,
        overflow = TextOverflow.Ellipsis,
    )
}

@Composable
private fun BrightnessCard(brightness: BrightnessState, c: Controls, modifier: Modifier = Modifier.fillMaxWidth()) {
    GlassCard(modifier) {
        Row(verticalAlignment = Alignment.CenterVertically) {
            Picto(R.drawable.ic_action_brightness, 24.dp)
            Spacer(Modifier.width(8.dp))
            GlassText("Luminosité", size = 16.sp, weight = FontWeight.SemiBold)
        }
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
private fun RadioTiles(state: ActionsState, c: Controls, modifier: Modifier = Modifier.fillMaxWidth()) {
    Row(modifier, horizontalArrangement = Arrangement.spacedBy(10.dp)) {
        state.wifi?.let { wifi: WifiState ->
            Tile(R.drawable.ic_action_wifi, "Wi-Fi", wifi.ssid ?: onOff(wifi.on), wifi.on, Modifier.weight(1f).fillMaxHeight()) {
                c.tap()
                c.update { copy(wifi = WifiState(!wifi.on, wifi.ssid)) }
                c.send(ActionMessages.wifiSet(!wifi.on))
            }
        }
        state.bluetooth?.let { bt: BluetoothState ->
            Tile(R.drawable.ic_action_bluetooth, "Bluetooth", bt.connected.firstOrNull() ?: onOff(bt.on), bt.on, Modifier.weight(1f).fillMaxHeight()) {
                c.tap()
                c.update { copy(bluetooth = BluetoothState(!bt.on, bt.connected)) }
                c.send(ActionMessages.bluetoothSet(!bt.on))
            }
        }
        state.airplane?.let { plane: AirplaneState ->
            Tile(R.drawable.ic_action_airplane, "Avion", onOff(plane.on), plane.on, Modifier.weight(1f).fillMaxHeight()) {
                c.tap()
                c.update { copy(airplane = AirplaneState(!plane.on)) }
                c.send(ActionMessages.airplaneSet(!plane.on))
            }
        }
    }
}

private fun onOff(on: Boolean) = if (on) "Activé" else "Désactivé"

/**
 * Compact USB chip: pictogram, "label  E:" with "12 Go libres" under it, then the open-folder and eject buttons.
 * Landscape stacks the chips in a side rail on the right; portrait scrolls them in a row above the controls.
 */
@Composable
private fun UsbChip(drive: UsbDrive, c: Controls, modifier: Modifier = Modifier) {
    Row(
        modifier
            .height(68.dp)
            .clip(ChipShape)
            .background(Color.White.copy(alpha = 0.10f))
            .border(1.dp, Color.White.copy(alpha = 0.25f), ChipShape)
            .padding(start = 14.dp, end = 10.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Picto(R.drawable.ic_action_usb, 28.dp, alpha = 0.9f)
        Spacer(Modifier.width(10.dp))
        Column(Modifier.weight(1f), verticalArrangement = Arrangement.Center) {
            BasicText(
                drive.label.ifBlank { "Clé USB" } + "  " + drive.drive,
                style = TextStyle(color = Color.White, fontSize = 15.sp, fontWeight = FontWeight.SemiBold),
                maxLines = 1,
                overflow = TextOverflow.Ellipsis,
            )
            drive.freeBytes?.let {
                BasicText(
                    ActionsFormat.freeSpace(it),
                    style = TextStyle(color = Color.White.copy(alpha = 0.7f), fontSize = 12.sp),
                    maxLines = 1,
                    overflow = TextOverflow.Ellipsis,
                )
            }
        }
        Spacer(Modifier.width(6.dp))
        ChipIconButton(R.drawable.ic_action_folder_open, "Ouvrir ${drive.drive}") {
            c.tap()
            c.send(ActionMessages.usbOpen(drive.drive))
        }
        Spacer(Modifier.width(6.dp))
        ChipIconButton(R.drawable.ic_action_eject, "Éjecter ${drive.drive}") {
            c.tap()
            c.send(ActionMessages.usbEject(drive.drive))
        }
    }
}

@Composable
private fun ChipIconButton(icon: Int, description: String, onClick: () -> Unit) {
    Box(
        Modifier
            .size(44.dp)
            .clip(CircleShape)
            .background(Color.White.copy(alpha = 0.10f))
            .border(1.dp, Color.White.copy(alpha = 0.25f), CircleShape)
            .semantics { contentDescription = description }
            .clickable(onClick = onClick),
        contentAlignment = Alignment.Center,
    ) {
        Picto(icon, 22.dp)
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

/** Speaker toggle: red tint, slashed speaker and the label "Muet" when muted; plain "Son" otherwise. */
@Composable
private fun MuteButton(muted: Boolean, onClick: () -> Unit) {
    val tint = if (muted) MuteRed else Color.White
    Column(
        Modifier
            .clip(TileShape)
            .background(if (muted) MuteRed.copy(alpha = 0.28f) else Color.White.copy(alpha = 0.10f))
            .border(if (muted) 2.dp else 1.dp, if (muted) MuteRed.copy(alpha = 0.9f) else Color.White.copy(alpha = 0.25f), TileShape)
            .clickable(onClick = onClick)
            .padding(horizontal = 16.dp, vertical = 8.dp),
        horizontalAlignment = Alignment.CenterHorizontally,
    ) {
        SpeakerIcon(muted, tint, Modifier.size(30.dp))
        GlassText(if (muted) "Muet" else "Son", size = 12.sp, color = tint, weight = if (muted) FontWeight.SemiBold else FontWeight.Normal)
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
private fun RoundIconKey(icon: Int, onClick: () -> Unit) {
    Box(
        Modifier
            .size(52.dp)
            .clip(CircleShape)
            .background(Color.White.copy(alpha = 0.10f))
            .border(1.dp, Color.White.copy(alpha = 0.25f), CircleShape)
            .clickable(onClick = onClick),
        contentAlignment = Alignment.Center,
    ) {
        Picto(icon, 28.dp)
    }
}

@Composable
private fun Tile(icon: Int, title: String, subtitle: String, on: Boolean, modifier: Modifier, onClick: () -> Unit) {
    val fg = if (on) 1f else 0.5f
    Column(
        modifier
            .heightIn(min = 104.dp)
            .clip(TileShape)
            .background(Color.White.copy(alpha = if (on) 0.28f else 0.08f))
            .border(if (on) 2.dp else 1.dp, Color.White.copy(alpha = if (on) 0.85f else 0.25f), TileShape)
            .clickable(onClick = onClick)
            .padding(12.dp),
        horizontalAlignment = Alignment.CenterHorizontally,
        verticalArrangement = Arrangement.Center,
    ) {
        Picto(icon, 28.dp, fg)
        Spacer(Modifier.height(4.dp))
        GlassText(title, size = 16.sp, weight = if (on) FontWeight.SemiBold else FontWeight.Normal, alpha = fg)
        Spacer(Modifier.height(2.dp))
        BasicText(
            subtitle,
            style = TextStyle(color = Color.White.copy(alpha = if (on) 0.75f else 0.4f), fontSize = 12.sp, textAlign = TextAlign.Center),
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
