package com.orizonx.client.ui

import android.content.Context
import android.os.SystemClock
import androidx.compose.animation.AnimatedVisibility
import androidx.compose.animation.Crossfade
import androidx.compose.animation.core.tween
import androidx.compose.animation.fadeIn
import androidx.compose.animation.fadeOut
import androidx.compose.foundation.Canvas
import androidx.compose.foundation.Image
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.gestures.awaitEachGesture
import androidx.compose.foundation.gestures.awaitFirstDown
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
import androidx.compose.foundation.layout.RowScope
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.WindowInsets
import androidx.compose.foundation.layout.fillMaxHeight
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.safeDrawing
import androidx.compose.foundation.layout.requiredSize
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
import androidx.compose.runtime.mutableFloatStateOf
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.mutableLongStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.rememberUpdatedState
import androidx.compose.runtime.snapshotFlow
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.layout.onSizeChanged
import androidx.compose.ui.geometry.CornerRadius
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.geometry.RoundRect
import androidx.compose.ui.geometry.Size
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.FilterQuality
import androidx.compose.ui.graphics.ColorFilter
import androidx.compose.ui.graphics.ImageBitmap
import androidx.compose.ui.graphics.Path
import androidx.compose.ui.graphics.Shadow
import androidx.compose.ui.graphics.drawscope.clipPath
import androidx.compose.ui.hapticfeedback.HapticFeedbackType
import androidx.compose.ui.input.pointer.PointerEventPass
import androidx.compose.ui.input.pointer.pointerInput
import androidx.compose.ui.platform.LocalContext
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
import androidx.compose.ui.unit.IntOffset
import androidx.compose.ui.unit.IntRect
import androidx.compose.ui.unit.IntSize
import androidx.compose.ui.unit.LayoutDirection
import androidx.compose.ui.window.Popup
import androidx.compose.ui.window.PopupPositionProvider
import com.orizonx.client.actions.ActionMessages
import com.orizonx.client.actions.ActionsLayoutStore
import com.orizonx.client.actions.ActionThrottle
import com.orizonx.client.actions.ActionsFormat
import com.orizonx.client.actions.ActionsIcons
import com.orizonx.client.actions.ActionsState
import com.orizonx.client.actions.AirplaneState
import com.orizonx.client.actions.AudioState
import com.orizonx.client.actions.BatteryLevel
import com.orizonx.client.actions.BatteryState
import com.orizonx.client.actions.BluetoothState
import com.orizonx.client.actions.BrightnessIcon
import com.orizonx.client.actions.BrightnessState
import com.orizonx.client.actions.ClockState
import com.orizonx.client.actions.ContextBar
import com.orizonx.client.actions.ContextButton
import com.orizonx.client.actions.BlockId
import com.orizonx.client.actions.ControlRules
import com.orizonx.client.actions.SoundContent
import com.orizonx.client.actions.SoundMode
import com.orizonx.client.actions.UsbContent
import com.orizonx.client.actions.UsbMode
import com.orizonx.client.actions.KeyboardTopCards
import com.orizonx.client.actions.ContextIcons
import com.orizonx.client.actions.ContextPage
import com.orizonx.client.actions.ContextPageMemory
import com.orizonx.client.actions.ContextScroll
import com.orizonx.client.actions.NowPlaying
import com.orizonx.client.actions.NowPlayingLayout
import com.orizonx.client.actions.UsbDrive
import com.orizonx.client.actions.UsbKind
import com.orizonx.client.actions.VolumeIcon
import com.orizonx.client.actions.WifiIcon
import com.orizonx.client.actions.WifiState
import com.orizonx.client.i18n.LangPref
import com.orizonx.client.keyboard.KeyLayouts
import com.orizonx.client.trackpad.TrackpadStore
import com.orizonx.client.i18n.LocalLang
import com.orizonx.client.i18n.S
import com.orizonx.client.i18n.tr
import kotlinx.coroutines.Job
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.launch
import kotlinx.coroutines.withTimeoutOrNull
import org.json.JSONObject
import kotlin.math.min
import kotlin.math.roundToInt

private val Amber = Color(0xFFFAC775)
private val MuteRed = Color(0xFFFF6B6B)
private val BatteryGreen = Color(0xFF34C77B)
private val BatteryAmber = Color(0xFFF2A93B)
private val BatteryRed = Color(0xFFE5484D)
private val BatteryText = Color(0xFF0B1F14)
private val PillShape = RoundedCornerShape(24.dp)
private val TileShape = RoundedCornerShape(18.dp)
private val CoverShape = RoundedCornerShape(16.dp)
private val ChipShape = RoundedCornerShape(20.dp)

/**
 * The Actions remote: clock, PC battery and the controls reported by the PC's latest ACTIONS_STATE ([rawState]).
 * Actions update the displayed state immediately (optimistic); the next ACTIONS_STATE wins.
 * [images] holds the decoded images by id (cover art and app icons); the cover is looked up by `now_playing.artwork`, the bar icon by `context.icon`.
 */
@Composable
fun ActionsScreen(
    rawState: JSONObject?,
    images: Map<String, ImageBitmap>,
    onAction: (JSONObject) -> Unit,
    onSwitchMode: () -> Unit,
    langPref: LangPref,
    onLangPref: (LangPref) -> Unit,
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
    val lang = LocalLang.current
    var noticeCode by remember { mutableStateOf<String?>(null) }
    var noticeSeq by remember { mutableIntStateOf(0) }
    LaunchedEffect(parsed) {
        parsed?.notice?.let {
            noticeCode = it.code
            noticeSeq++
        }
    }
    LaunchedEffect(noticeSeq) {
        if (noticeSeq > 0) {
            delay(NOTICE_MS)
            noticeCode = null
        }
    }

    // The PC learns the new language when it changes during the session (its first value went out in DEVICE_INFO).
    var announcedLang by remember { mutableStateOf(lang) }
    LaunchedEffect(lang) {
        if (lang != announcedLang) {
            announcedLang = lang
            send(ActionMessages.contextLang(lang))
        }
    }

    // Page picked per context profile; lives with the screen so it survives the bar disappearing and coming back.
    val pageMemory = remember { ContextPageMemory() }
    var pageVersion by remember { mutableIntStateOf(0) }
    var keyboardOpen by remember { mutableStateOf(false) }
    var trackpadOpen by remember { mutableStateOf(false) }
    var gamepadOpen by remember { mutableStateOf(false) }
    var claudeOpen by remember { mutableStateOf(false) }
    val appContext = LocalContext.current
    val trackpadStore = remember { TrackpadStore(appContext.getSharedPreferences("orizonx", Context.MODE_PRIVATE)) }
    var trackpadSensitivity by remember { mutableFloatStateOf(trackpadStore.load()) }
    val layoutStore = remember { ActionsLayoutStore(appContext.getSharedPreferences("orizonx", Context.MODE_PRIVATE)) }
    var blocksLayout by remember { mutableStateOf(layoutStore.load()) }
    var editingBlocks by remember { mutableStateOf(false) }
    var addListOpen by remember { mutableStateOf(false) }
    LaunchedEffect(editingBlocks) { if (!editingBlocks) addListOpen = false }

    val volumeThrottle = remember { ActionThrottle(clock = SystemClock::elapsedRealtime) { send(ActionMessages.volumeSet(it)) } }
    val brightnessThrottle = remember { ActionThrottle(clock = SystemClock::elapsedRealtime) { send(ActionMessages.brightnessSet(it)) } }

    val controls = Controls(
        send = { send(it) },
        tap = tap,
        update = update,
        volumeThrottle = volumeThrottle,
        brightnessThrottle = brightnessThrottle,
        images = images,
    )

    BoxWithConstraints(Modifier.fillMaxSize()) {
        DarkBackdrop()
        val landscape = maxWidth > maxHeight
        Box(Modifier.fillMaxSize().windowInsetsPadding(WindowInsets.safeDrawing)) {
            val state = shown
            val contextBar = state?.context
            val keyboardInfo = state?.keyboard
            // The keyboard screen replaces the tiles; it closes by itself when the PC stops offering a keyboard.
            val showKeyboard = keyboardOpen && keyboardInfo != null
            val showTrackpad = trackpadOpen && !showKeyboard && state?.trackpad == true
            val gamepadInfo = state?.gamepad
            val showGamepad = gamepadOpen && !showKeyboard && !showTrackpad && gamepadInfo != null
            val claudeInfo = state?.claude
            // Opening the keyboard, trackpad, gamepad or Claude Code ends the block edit mode.
            val otherScreenOpen = keyboardOpen || trackpadOpen || gamepadOpen || claudeOpen
            LaunchedEffect(otherScreenOpen) { if (otherScreenOpen) editingBlocks = false }
            val showClaude = claudeOpen && !showKeyboard && !showTrackpad && !showGamepad && claudeInfo != null
            val contextStrip: @Composable () -> Unit = {
                if (contextBar != null) {
                    ContextBarStrip(
                        contextBar, controls, landscape, pageMemory, pageVersion,
                        onPage = { profile, id ->
                            pageMemory.select(profile, id)
                            pageVersion++
                        },
                    )
                }
            }
            if (showKeyboard && keyboardInfo != null) {
                Column(Modifier.fillMaxSize()) {
                    // The context bar stays, above the keyboard.
                    Box(Modifier.padding(top = 8.dp)) { contextStrip() }
                    // Clock, battery, sound and brightness stay too; the keyboard gets the height that is left.
                    if (state != null) OverlayTopRow(state, controls)
                    KeyboardScreen(
                        KeyLayouts.of(keyboardInfo.layout),
                        onAction = { send(it) },
                        onClose = { keyboardOpen = false },
                        tap = tap,
                        modifier = Modifier.weight(1f),
                    )
                }
            } else if (showGamepad && gamepadInfo != null) {
                // Full screen, no header and no context bar.
                GamepadScreen(gamepadInfo, onAction = { send(it) }, onClose = { gamepadOpen = false }, tap = tap)
            } else if (showClaude && claudeInfo != null) {
                Column(Modifier.fillMaxSize()) {
                    // The context bar stays on top over the full width; the Claude screen has its own clock block.
                    Box(Modifier.padding(top = 8.dp)) { contextStrip() }
                    if (state != null) {
                        ClaudeCodeScreen(
                            state = state,
                            info = claudeInfo,
                            // The sessions' times are on the PC's clock: compare them with the PC's, not the device's.
                            nowSeconds = state.clock?.epochMs?.div(1000) ?: (System.currentTimeMillis() / 1000),
                            onAction = { send(it) },
                            onClose = { claudeOpen = false },
                            tap = tap,
                            modifier = Modifier.weight(1f),
                        )
                    }
                }
            } else if (showTrackpad) {
                Column(Modifier.fillMaxSize()) {
                    // Same header as the keyboard: context bar, then clock, battery, sound and brightness.
                    Box(Modifier.padding(top = 8.dp)) { contextStrip() }
                    if (state != null) OverlayTopRow(state, controls)
                    TrackpadScreen(
                        sensitivity = trackpadSensitivity,
                        onSensitivity = {
                            trackpadSensitivity = it
                            trackpadStore.save(it)
                        },
                        onAction = { send(it) },
                        onClose = { trackpadOpen = false },
                        tap = tap,
                        modifier = Modifier.weight(1f),
                    )
                }
            } else {
                Column(Modifier.fillMaxSize()) {
                    Column(Modifier.fillMaxWidth().weight(1f).padding(horizontal = 16.dp)) {
                        Row(Modifier.fillMaxWidth().padding(top = 8.dp), horizontalArrangement = Arrangement.End) {
                            if (editingBlocks) {
                                // The edit mode's buttons take the place of the pills, in the same row: nothing below moves.
                                Pill(tr(S.BLOCKS_DONE), selected = true, onClick = { tap(); editingBlocks = false })
                                if (blocksLayout.hidden.isNotEmpty()) {
                                    Spacer(Modifier.width(10.dp))
                                    Box {
                                        Pill(tr(S.BLOCKS_ADD), selected = addListOpen, onClick = { tap(); addListOpen = !addListOpen })
                                        if (addListOpen) {
                                            Popup(popupPositionProvider = BelowAnchor, onDismissRequest = { addListOpen = false }) {
                                                Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
                                                    val hiddenNow = blocksLayout.hiddenInOrder()
                                                    for (id in hiddenNow) {
                                                        Pill(tr(blockName(id)), selected = false, onClick = {
                                                            tap()
                                                            blocksLayout = blocksLayout.restore(id)
                                                            layoutStore.save(blocksLayout)
                                                            if (hiddenNow.size <= 1) addListOpen = false
                                                        })
                                                    }
                                                }
                                            }
                                        }
                                    }
                                }
                                Spacer(Modifier.weight(1f))
                            } else {
                                LangPill(langPref, onLangPref)
                                if (keyboardInfo != null) {
                                    Spacer(Modifier.width(10.dp))
                                    Pill(tr(S.KEYBOARD), selected = false, onClick = { tap(); trackpadOpen = false; gamepadOpen = false; claudeOpen = false; keyboardOpen = true }, icon = R.drawable.ox_keyboard)
                                }
                                if (state?.trackpad == true) {
                                    Spacer(Modifier.width(10.dp))
                                    Pill(tr(S.TRACKPAD), selected = false, onClick = { tap(); keyboardOpen = false; gamepadOpen = false; claudeOpen = false; trackpadOpen = true }, icon = R.drawable.ox_trackpad)
                                }
                                if (gamepadInfo != null) {
                                    Spacer(Modifier.width(10.dp))
                                    Pill(tr(S.GAMEPAD), selected = false, onClick = { tap(); keyboardOpen = false; trackpadOpen = false; claudeOpen = false; gamepadOpen = true }, icon = R.drawable.ox_gamepad)
                                }
                                if (claudeInfo != null) {
                                    Spacer(Modifier.width(10.dp))
                                    Pill(tr(S.CLAUDE_CODE), selected = false, onClick = { tap(); keyboardOpen = false; trackpadOpen = false; gamepadOpen = false; claudeOpen = true }, icon = R.drawable.ox_claude_code)
                                }
                                Spacer(Modifier.width(10.dp))
                                Pill(tr(S.SWITCH_MODE), selected = false, onClick = { tap(); onSwitchMode() })
                            }
                        }
                        if (state == null) {
                            Box(Modifier.fillMaxSize(), contentAlignment = Alignment.Center) {
                                GlassText(tr(S.CONNECTING_TO_PC), size = 16.sp, alpha = 0.8f)
                            }
                        } else {
                            BlocksBody(
                                state, controls, blocksLayout,
                                onLayout = {
                                    blocksLayout = it
                                    layoutStore.save(it)
                                },
                                landscape = landscape,
                                editing = editingBlocks,
                                onEditing = { editingBlocks = it },
                                haptic = { haptics.performHapticFeedback(it) },
                                // A separate child of the column: it starts where the measured header row ends, plus a gap, and ends the same
                                // gap above the context bar. The grid (and its clip) is sized inside this area.
                                modifier = Modifier.fillMaxWidth().weight(1f).padding(top = BlocksAreaGap, bottom = BlocksAreaGap),
                            )
                        }
                    }
                    // The Touch-Bar-like strip sits at the very bottom, in an area reserved at its tallest (tabs stacked over the buttons)
                    // whether a bar is shown or not: the grid above keeps its size and place when the bar comes, goes or changes shape.
                    Box(Modifier.fillMaxWidth().height(ContextStripReservedHeight), contentAlignment = Alignment.BottomCenter) { contextStrip() }
                }
            }
            AnimatedVisibility(
                visible = noticeCode != null,
                modifier = Modifier
                    .align(Alignment.BottomCenter)
                    .padding(
                        bottom = if (!showKeyboard && !showTrackpad && !showGamepad && !showClaude) {
                            // The normal page always reserves the strip's area: the notice clears it.
                            24.dp + ContextStripReservedHeight
                        } else {
                            24.dp
                        },
                        start = 16.dp,
                        end = 16.dp,
                    ),
                enter = fadeIn(),
                exit = fadeOut(),
            ) {
                GlassPanel { GlassText(noticeCode?.let { ActionsFormat.notice(it, lang) } ?: "", size = 15.sp, color = Amber) }
            }
        }
    }
}

private const val NOTICE_MS = 3000L

/** Space between the header pills and the block grid, and between the grid and the context bar. */
private val BlocksAreaGap = 12.dp

/** Puts a popup just under the control it belongs to, left edges aligned. */
private object BelowAnchor : PopupPositionProvider {
    override fun calculatePosition(anchorBounds: IntRect, windowSize: IntSize, layoutDirection: LayoutDirection, popupContentSize: IntSize) =
        IntOffset(anchorBounds.left, anchorBounds.bottom + 8)
}
private const val SLIDER_HOLD_MS = 700L

/** Everything a card needs to act: send, haptics, optimistic update and the slider throttles. */
internal class Controls(
    val send: (JSONObject) -> Unit,
    val tap: () -> Unit,
    val update: (ActionsState.() -> ActionsState) -> Unit,
    val volumeThrottle: ActionThrottle,
    val brightnessThrottle: ActionThrottle,
    val images: Map<String, ImageBitmap>,
)

/** The media keys live in the "En cours de lecture" card when it is shown, in the Son card otherwise. */
private fun soundKeys(state: ActionsState) = ControlRules.soundKeys(state)

/**
 * What stays above the open keyboard, compact: the clock with its date and the PC battery, then the Sound and Brightness
 * cards (the very same cards as the tiles, with the same actions). Only what the PC reports ([KeyboardTopCards]).
 * Wide screens put all three on one row; narrow ones put the clock on top of the cards, which then sit side by side
 * when they fit.
 */
@Composable
private fun OverlayTopRow(state: ActionsState, c: Controls) {
    val keep = KeyboardTopCards.of(state)
    if (!keep.any) return
    val brightness = state.brightness
    BoxWithConstraints(Modifier.fillMaxWidth().padding(horizontal = 16.dp).padding(top = 6.dp, bottom = 2.dp)) {
        val width = maxWidth
        val wide = width >= 720.dp
        val cardsAside = width >= 480.dp
        @Composable
        fun RowScope.cards() {
            if (keep.sound) SoundCard(state, c, Modifier.weight(1f).fillMaxHeight())
            if (brightness != null) BrightnessCard(brightness, c, Modifier.weight(1f).fillMaxHeight())
        }
        if (wide) {
            Row(Modifier.fillMaxWidth().height(IntrinsicSize.Min), horizontalArrangement = Arrangement.spacedBy(14.dp), verticalAlignment = Alignment.CenterVertically) {
                if (keep.clock) {
                    // Pas de BoxWithConstraints ici : la rangée mesure ses enfants en taille intrinsèque, ce qu'un
                    // SubcomposeLayout refuse (plantage). La largeur de l'horloge se déduit de celle de la rangée.
                    val weights = 0.8f + (if (keep.sound) 1f else 0f) + (if (brightness != null) 1f else 0f)
                    val clockWidth = width.value * 0.8f / weights
                    Box(Modifier.weight(0.8f), contentAlignment = Alignment.Center) {
                        ClockBlock(state.clock, state.battery, min(KeyboardClockSp, clockWidth / 4.1f), 16f)
                    }
                }
                cards()
            }
        } else {
            Column(Modifier.fillMaxWidth(), horizontalAlignment = Alignment.CenterHorizontally, verticalArrangement = Arrangement.spacedBy(8.dp)) {
                if (keep.clock) ClockBlock(state.clock, state.battery, min(KeyboardClockSp, width.value / 4.1f), 16f)
                if (cardsAside) {
                    Row(Modifier.fillMaxWidth().height(IntrinsicSize.Min), horizontalArrangement = Arrangement.spacedBy(14.dp)) { cards() }
                } else {
                    if (keep.sound) SoundCard(state, c)
                    if (brightness != null) BrightnessCard(brightness, c)
                }
            }
        }
    }
}

private const val KeyboardClockSp = 52f

// --- Contextual bar ------------------------------------------------------------------------

private val ContextBarHeight = 76.dp
private val ContextBarBottomMargin = 8.dp
private val ContextBarShape = RoundedCornerShape(22.dp)
private val ContextKeyShape = RoundedCornerShape(14.dp)
private val ContextKeyMinWidth = 64.dp
private val ContextScrollKeyWidth = 132.dp
private val ContextTabsRowHeight = 34.dp

/**
 * The tallest the strip gets: the stacked layout (tabs row over the buttons area, [ContextBarHeight] less 8 dp) plus its
 * bottom margin. The normal page reserves exactly this under the grid, bar or no bar.
 */
private val ContextStripReservedHeight = ContextTabsRowHeight + (ContextBarHeight - 8.dp) + ContextBarBottomMargin
private val ContextIconSize = 28.dp
private val ContextIconShape = RoundedCornerShape(6.dp)
private val ContextSwipeThreshold = 48.dp
private const val CONTEXT_FADE_MS = 200
private const val CONTEXT_PAGE_FADE_MS = 150

/**
 * Full-width glass strip with the buttons for the PC's foreground app. The content crossfades (~200 ms) when the profile
 * changes; changes inside the same profile (e.g. the window title in the app name) just update it in place.
 * With several pages, tabs pick the page and a horizontal swipe on the buttons moves to the neighbour page;
 * [pageMemory] gives each profile back the page it was left on. */
@Composable
private fun ContextBarStrip(
    bar: ContextBar,
    c: Controls,
    landscape: Boolean,
    pageMemory: ContextPageMemory,
    pageVersion: Int,
    onPage: (profile: String, pageId: String) -> Unit,
) {
    val latest by rememberUpdatedState(bar)
    // The outgoing profile keeps showing its own buttons while it fades out.
    val lastByProfile = remember { mutableMapOf<String, ContextBar>() }
    lastByProfile[bar.profile] = bar
    Box(
        Modifier
            .fillMaxWidth()
            .padding(start = 12.dp, end = 12.dp, bottom = ContextBarBottomMargin)
            .heightIn(min = ContextBarHeight)
            .clip(ContextBarShape)
            .background(Color.White.copy(alpha = 0.10f))
            .border(
                1.dp,
                Brush.verticalGradient(listOf(Color.White.copy(alpha = 0.45f), Color.White.copy(alpha = 0.12f))),
                ContextBarShape,
            ),
    ) {
        Crossfade(targetState = bar.profile, animationSpec = tween(CONTEXT_FADE_MS), label = "contextBar") { profile ->
            val shown = if (profile == latest.profile) latest else lastByProfile[profile] ?: latest
            // pageVersion is read here on purpose: the memory is not snapshot state, a new version re-reads it.
            val page = remember(shown, pageVersion) { pageMemory.current(shown) }
            ContextBarContent(
                shown, page, c, landscape,
                onPage = { target ->
                    if (target.id != page.id) {
                        c.tap()
                        onPage(shown.profile, target.id)
                    }
                },
                neighbour = { offset -> pageMemory.neighbour(shown, offset) },
            )
        }
    }
}

/**
 * App name small on the left (with its icon above it once received), then the buttons evenly spread; they scroll horizontally when they would get too narrow.
 * With several pages the tabs follow the name on the same line, or sit above the buttons when the line is too short.
 */
@Composable
private fun ContextBarContent(
    bar: ContextBar,
    page: ContextPage,
    c: Controls,
    landscape: Boolean,
    onPage: (ContextPage) -> Unit,
    neighbour: (Int) -> ContextPage?,
) {
    val nameWidth = if (landscape) 140.dp else 84.dp
    val multi = bar.pages.size > 1
    // The icon shows only once its image has arrived; until then (or without an id) the name stands alone, as before.
    val icon = bar.icon?.let { c.images[it] }
    val hasLabel = bar.app.isNotBlank() || icon != null
    BoxWithConstraints(Modifier.fillMaxWidth()) {
        val stacked = multi && !tabsFitInline(bar, hasLabel, nameWidth, maxWidth)
        @Composable
        fun appLabel() {
            if (hasLabel) ContextAppLabel(bar.app, icon, nameWidth)
        }
        if (stacked && icon != null) {
            // Tabs above the buttons, and the icon over the name in a column of its own on the left, as in the inline layout.
            Row(Modifier.fillMaxWidth().padding(horizontal = 14.dp), verticalAlignment = Alignment.CenterVertically) {
                appLabel()
                Spacer(Modifier.width(12.dp))
                Column(Modifier.weight(1f)) {
                    Row(Modifier.fillMaxWidth().height(ContextTabsRowHeight), verticalAlignment = Alignment.CenterVertically) {
                        ContextTabs(bar.pages, page, onPage)
                    }
                    ContextButtonsArea(page, c, onPage, neighbour, Modifier.fillMaxWidth().height(ContextBarHeight - 8.dp))
                }
            }
        } else if (stacked) {
            Column(Modifier.fillMaxWidth().padding(horizontal = 14.dp)) {
                Row(Modifier.fillMaxWidth().height(ContextTabsRowHeight), verticalAlignment = Alignment.CenterVertically) {
                    appLabel()
                    if (hasLabel) Spacer(Modifier.width(12.dp))
                    ContextTabs(bar.pages, page, onPage)
                }
                ContextButtonsArea(page, c, onPage, neighbour, Modifier.fillMaxWidth().height(ContextBarHeight - 8.dp))
            }
        } else {
            Row(Modifier.fillMaxWidth().height(ContextBarHeight).padding(horizontal = 14.dp), verticalAlignment = Alignment.CenterVertically) {
                appLabel()
                if (hasLabel) Spacer(Modifier.width(12.dp))
                if (multi) {
                    ContextTabs(bar.pages, page, onPage)
                    Spacer(Modifier.width(12.dp))
                }
                ContextButtonsArea(page, c, onPage, neighbour, Modifier.weight(1f).fillMaxHeight())
            }
        }
    }
}

/** The app name, small; with an [icon], a 28 dp full-colour rounded icon centred above it. */
@Composable
private fun ContextAppLabel(app: String, icon: ImageBitmap?, nameWidth: Dp) {
    Column(horizontalAlignment = Alignment.CenterHorizontally, verticalArrangement = Arrangement.Center) {
        if (icon != null) {
            Image(
                icon,
                contentDescription = null,
                modifier = Modifier.size(ContextIconSize).clip(ContextIconShape),
                contentScale = ContentScale.Fit,
            )
            if (app.isNotBlank()) Spacer(Modifier.height(3.dp))
        }
        if (app.isNotBlank()) {
            BasicText(
                app,
                style = TextStyle(color = Color.White.copy(alpha = 0.6f), fontSize = 13.sp, textAlign = TextAlign.Center),
                maxLines = 1,
                overflow = TextOverflow.Ellipsis,
                modifier = Modifier.widthIn(max = nameWidth),
            )
        }
    }
}

/** Rough width of the tab pills, used only to decide between "tabs on the name line" and "tabs above the buttons". */
private fun tabsFitInline(bar: ContextBar, hasName: Boolean, nameWidth: Dp, available: Dp): Boolean {
    val tabs = bar.pages.sumOf { it.label.length * 7 + 26 + TAB_GAP_DP }.dp
    val name = if (hasName) nameWidth + 12.dp else 0.dp
    // A scrolling page (the tabs) never needs its whole width on the line: count a few keys for it.
    val keys = ContextKeyMinWidth * bar.pages.maxOf { if (it.scroll) 4 else it.buttons.size }
    return available - 28.dp - name - tabs - 12.dp >= keys
}

private const val TAB_GAP_DP = 6

/** Compact 12 sp pills, the current page highlighted. */
@Composable
private fun ContextTabs(pages: List<ContextPage>, current: ContextPage, onPage: (ContextPage) -> Unit) {
    Row(horizontalArrangement = Arrangement.spacedBy(TAB_GAP_DP.dp), verticalAlignment = Alignment.CenterVertically) {
        for (p in pages) {
            val selected = p.id == current.id
            Box(
                Modifier
                    .heightIn(min = 28.dp)
                    .clip(PillShape)
                    .background(Color.White.copy(alpha = if (selected) 0.30f else 0.08f))
                    .border(1.dp, Color.White.copy(alpha = if (selected) 0.8f else 0.2f), PillShape)
                    .clickable { onPage(p) }
                    .padding(horizontal = 12.dp, vertical = 4.dp),
                contentAlignment = Alignment.Center,
            ) {
                BasicText(
                    p.label,
                    style = TextStyle(
                        color = Color.White.copy(alpha = if (selected) 1f else 0.7f),
                        fontSize = 12.sp,
                        fontWeight = if (selected) FontWeight.SemiBold else FontWeight.Normal,
                    ),
                    maxLines = 1,
                )
            }
        }
    }
}

/**
 * The buttons of [page], crossfaded (~150 ms) when the page changes, with the swipe that moves to the neighbour page.
 * A [ContextPage.scroll] page (the browser tabs) is a row of wide buttons that scrolls; its active button is brought
 * to the middle when the page appears.
 */
@Composable
private fun ContextButtonsArea(
    page: ContextPage,
    c: Controls,
    onPage: (ContextPage) -> Unit,
    neighbour: (Int) -> ContextPage?,
    modifier: Modifier,
) {
    val scroll = rememberScrollState()
    val density = LocalDensity.current
    val threshold = with(density) { ContextSwipeThreshold.toPx() }
    val keyPx = with(density) { ContextScrollKeyWidth.roundToPx() }
    val latestNeighbour by rememberUpdatedState(neighbour)
    val latestOnPage by rememberUpdatedState(onPage)
    val latestPage by rememberUpdatedState(page)
    var viewportPx by remember { mutableIntStateOf(0) }
    // A page keeps showing its own buttons while it fades out, and a content update (a new active tab) does not re-fade.
    val pagesById = remember { mutableMapOf<String, ContextPage>() }
    pagesById[page.id] = page
    LaunchedEffect(page.id, viewportPx > 0) {
        val p = latestPage
        if (!p.scroll) {
            scroll.scrollTo(0)
        } else if (viewportPx > 0) {
            val target = ContextScroll.target(p.buttons.indexOfFirst { it.active }, keyPx, viewportPx)
            // Wait for the row to be measured (its range is 0 before), but not for ever when it is shorter than the view.
            if (target > 0) withTimeoutOrNull(500) { snapshotFlow { scroll.maxValue }.first { it > 0 } }
            scroll.scrollTo(target)
        }
    }
    Box(
        modifier
            .onSizeChanged { viewportPx = it.width }
            .pointerInput(threshold) {
                // Watches the gesture before the buttons see it and consumes nothing: taps and the row's own scrolling keep working.
                // It changes page only for a mostly horizontal swipe during which the row did not move (nothing to scroll, or at its end).
                awaitEachGesture {
                    val down = awaitFirstDown(requireUnconsumed = false, pass = PointerEventPass.Initial)
                    val startScroll = scroll.value
                    var last = down.position
                    while (true) {
                        val event = awaitPointerEvent(PointerEventPass.Initial)
                        val change = event.changes.firstOrNull { it.id == down.id } ?: break
                        last = change.position
                        if (!change.pressed) break
                    }
                    val dx = last.x - down.position.x
                    val dy = last.y - down.position.y
                    if (kotlin.math.abs(dx) >= threshold && kotlin.math.abs(dx) > 2 * kotlin.math.abs(dy) && scroll.value == startScroll) {
                        latestNeighbour(if (dx < 0) 1 else -1)?.let { latestOnPage(it) }
                    }
                }
            },
    ) {
        Crossfade(targetState = page.id, animationSpec = tween(CONTEXT_PAGE_FADE_MS), label = "contextPage") { id ->
            val p = if (id == latestPage.id) latestPage else pagesById[id] ?: latestPage
            BoxWithConstraints(Modifier.fillMaxSize()) {
                if (p.scroll) {
                    Row(Modifier.fillMaxSize().horizontalScroll(scroll)) { ContextKeys(p.buttons, c, ContextScrollKeyWidth) }
                } else if (maxWidth / p.buttons.size >= ContextKeyMinWidth) {
                    Row(Modifier.fillMaxSize()) { ContextKeys(p.buttons, c, keyWidth = null) }
                } else {
                    Row(Modifier.fillMaxSize().horizontalScroll(scroll)) { ContextKeys(p.buttons, c, ContextKeyMinWidth) }
                }
            }
        }
    }
}

/** The keys of a row: all [keyWidth] wide, or evenly spread over the row when it is null. */
@Composable
private fun RowScope.ContextKeys(buttons: List<ContextButton>, c: Controls, keyWidth: Dp?) {
    for (button in buttons) {
        ContextKey(
            button, c,
            if (keyWidth == null) Modifier.weight(1f).fillMaxHeight() else Modifier.width(keyWidth).fillMaxHeight(),
        )
    }
}

/**
 * 24 dp pictogram over a one-line 11 sp label; a tap sends `context.press` for this button.
 * The [ContextButton.active] one is styled like the selected page tab: lighter fill and a border.
 */
@Composable
private fun ContextKey(button: ContextButton, c: Controls, modifier: Modifier) {
    val active = button.active
    Column(
        modifier
            .padding(vertical = 6.dp, horizontal = 2.dp)
            .clip(ContextKeyShape)
            .then(
                if (active) {
                    Modifier
                        .background(Color.White.copy(alpha = 0.30f))
                        .border(1.dp, Color.White.copy(alpha = 0.8f), ContextKeyShape)
                } else {
                    Modifier
                },
            )
            .clickable {
                c.tap()
                c.send(ActionMessages.contextPress(button.id))
            }
            .padding(horizontal = 4.dp),
        horizontalAlignment = Alignment.CenterHorizontally,
        verticalArrangement = Arrangement.Center,
    ) {
        Picto(ContextIcons.drawable(button.icon), 24.dp)
        Spacer(Modifier.height(4.dp))
        BasicText(
            button.label,
            style = TextStyle(
                color = Color.White.copy(alpha = if (active) 1f else 0.85f),
                fontSize = 11.sp,
                fontWeight = if (active) FontWeight.SemiBold else FontWeight.Normal,
                textAlign = TextAlign.Center,
            ),
            maxLines = 1,
            overflow = TextOverflow.Ellipsis,
        )
    }
}

// --- Clock ---------------------------------------------------------------------------------

/** Ticks locally from the PC's epoch_ms plus the time elapsed since the state arrived, in the PC's UTC offset. */
@Composable
internal fun ClockBlock(clock: ClockState?, battery: BatteryState?, clockSp: Float, dateSp: Float) {
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
            GlassText(ActionsFormat.date(now, offset, LocalLang.current), size = dateSp.sp, alpha = 0.9f)
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

/** Orizon X pictogram from [res] (white vector), tinted with [tint]; [alpha] dims it. */
@Composable
private fun Picto(res: Int, size: Dp, alpha: Float = 1f, modifier: Modifier = Modifier, tint: Color = Color.White) {
    Image(
        painterResource(res),
        contentDescription = null,
        modifier = modifier.size(size),
        colorFilter = ColorFilter.tint(tint.copy(alpha = tint.alpha * alpha)),
    )
}

private fun volumeRes(audio: AudioState): Int = when (ActionsIcons.volume(audio.volume, audio.muted)) {
    VolumeIcon.MUTE -> R.drawable.ox_mute
    VolumeIcon.LOW -> R.drawable.ox_son_1
    VolumeIcon.MEDIUM -> R.drawable.ox_son_2
    VolumeIcon.HIGH -> R.drawable.ox_son_3
}

private fun brightnessRes(brightness: BrightnessState): Int = when (ActionsIcons.brightness(brightness.value)) {
    BrightnessIcon.NONE -> R.drawable.ox_no_lum
    BrightnessIcon.LOW -> R.drawable.ox_lum_1
    BrightnessIcon.MEDIUM -> R.drawable.ox_lum_2
    BrightnessIcon.HIGH -> R.drawable.ox_lum_3
}

private fun wifiRes(wifi: WifiState): Int = when (ActionsIcons.wifi(wifi.on, wifi.signal)) {
    WifiIcon.WEAK -> R.drawable.ox_wifi_1
    WifiIcon.MEDIUM -> R.drawable.ox_wifi_2
    WifiIcon.STRONG -> R.drawable.ox_wifi_3
}

private fun usbRes(kind: UsbKind): Int = when (kind) {
    UsbKind.STICK -> R.drawable.ox_cle_usb
    UsbKind.DISK -> R.drawable.ox_externe
}

/**
 * Battery: the ox_batterie shape is the body; its left part is filled in green / amber / red in proportion to the charge
 * (clipped to the shape), the rest stays dim. The percentage sits inside; ox_charge is the bolt when charging.
 */
@Composable
private fun BatteryPicto(battery: BatteryState) {
    val fillColor = when (ActionsFormat.batteryLevel(battery.percent)) {
        BatteryLevel.NORMAL -> BatteryGreen
        BatteryLevel.LOW -> BatteryAmber
        BatteryLevel.CRITICAL -> BatteryRed
    }
    val fraction = ActionsFormat.batteryFill(battery.percent)
    val shape = painterResource(R.drawable.ox_batterie)
    Row(verticalAlignment = Alignment.CenterVertically) {
        // The vector is a 48x48 square whose body spans x 2.46..45.55 and y 12.46..35.54: draw it larger than its box.
        val bodyW = 68.dp
        val bodyH = bodyW * (BATTERY_BODY_H / BATTERY_BODY_W)
        Box(Modifier.size(width = bodyW, height = bodyH), contentAlignment = Alignment.Center) {
            Canvas(Modifier.requiredSize(bodyW * (BATTERY_VIEWPORT / BATTERY_BODY_W))) {
                val k = size.width / BATTERY_VIEWPORT
                val left = BATTERY_BODY_X * k
                val top = BATTERY_BODY_Y * k
                val width = BATTERY_BODY_W * k
                val height = BATTERY_BODY_H * k
                val body = Path().apply {
                    addRoundRect(RoundRect(left, top, left + width, top + height, CornerRadius(BATTERY_BODY_R * k)))
                }
                // 1. The whole body, dimmed (the vector is white: drawn at 28 % alpha).
                with(shape) { draw(size, alpha = 0.28f) }
                // 2. The charge at full opacity on top, clipped to the rounded body.
                if (fraction > 0f) {
                    clipPath(body) {
                        drawRect(fillColor, Offset(left, top), Size(width * fraction.coerceAtLeast(0.14f), height))
                    }
                }
            }
            // Dark text when the charge covers the middle of the body (bright fill behind it), white otherwise.
            val onFill = fraction >= 0.5f
            BasicText(
                "${battery.percent}%",
                style = TextStyle(
                    color = if (onFill) BatteryText else Color.White,
                    fontSize = 15.sp,
                    fontWeight = FontWeight.Bold,
                    fontFeatureSettings = "tnum",
                    shadow = if (onFill) null else Shadow(Color.Black.copy(alpha = 0.55f), Offset(0f, 1f), 3f),
                ),
                maxLines = 1,
                softWrap = false,
            )
        }
        if (battery.charging) {
            Spacer(Modifier.width(6.dp))
            Picto(R.drawable.ox_charge, 28.dp, tint = Amber)
        }
    }
}

// Geometry of ox_batterie.xml (viewport units).
private const val BATTERY_VIEWPORT = 48f
private const val BATTERY_BODY_X = 2.46f
private const val BATTERY_BODY_Y = 12.46f
private const val BATTERY_BODY_W = 43.09f
private const val BATTERY_BODY_H = 23.08f
private const val BATTERY_BODY_R = 9.22f

// --- Cards ---------------------------------------------------------------------------------

/**
 * Son card. With the media keys in it (no now-playing card): header, slider with its value, then mute + keys.
 * Without them (the now-playing card has the keys): compact, header with the value and one row mute button + slider.
 * With [stretch] the card may be taller than its content: the keys / the slider row take the free space.
 */
@Composable
private fun SoundCard(
    state: ActionsState,
    c: Controls,
    modifier: Modifier = Modifier.fillMaxWidth(),
    stretch: Boolean = false,
    mode: SoundMode = SoundMode.WITH_KEYS,
) {
    val audio = state.audio
    // The media keys only show when the block is big enough for them (and when they belong to this block at all).
    val keys = soundKeys(state) && (mode == SoundMode.WITH_KEYS || audio == null)
    val muted = audio?.muted == true
    if (mode == SoundMode.SLIDER_ONLY && audio != null) {
        // The smallest form: the volume slider alone (the speaker is only a picture, the mute button comes with more room).
        GlassCard(modifier) {
            Row(Modifier.fillMaxSize(), verticalAlignment = Alignment.CenterVertically) {
                Picto(volumeRes(audio), 28.dp, tint = if (muted) MuteRed else Color.White)
                Spacer(Modifier.width(10.dp))
                VolumeSlider(audio, c, Modifier.weight(1f))
            }
        }
        return
    }
    GlassCard(modifier) {
        Row(Modifier.fillMaxWidth(), verticalAlignment = Alignment.CenterVertically) {
            Picto(
                if (audio != null) volumeRes(audio) else R.drawable.ox_son_3,
                28.dp,
                tint = if (muted) MuteRed else Color.White,
            )
            Spacer(Modifier.width(8.dp))
            GlassText(tr(S.SOUND), size = 16.sp, weight = FontWeight.SemiBold)
            if (audio != null && !keys) {
                Spacer(Modifier.weight(1f))
                GlassText(if (audio.muted) tr(S.MUTED) else tr(S.PERCENT, "value" to (audio.volume * 100).roundToInt()), size = 16.sp)
            }
        }
        if (audio != null && !keys) {
            if (stretch) Spacer(Modifier.weight(1f)) else Spacer(Modifier.height(10.dp))
            Row(Modifier.fillMaxWidth(), verticalAlignment = Alignment.CenterVertically) {
                MuteButton(audio, compact = true, onClick = {
                    c.tap()
                    c.update { copy(audio = AudioState(audio.volume, !audio.muted)) }
                    c.send(ActionMessages.volumeMute(!audio.muted))
                })
                Spacer(Modifier.width(14.dp))
                VolumeSlider(audio, c, Modifier.weight(1f))
            }
            if (stretch) Spacer(Modifier.weight(1f))
        } else {
            if (audio != null) {
                Spacer(Modifier.height(8.dp))
                // Taller than its content: the slider sits in the middle of the free space, the keys at the bottom.
                if (stretch) Spacer(Modifier.weight(1f))
                Row(verticalAlignment = Alignment.CenterVertically) {
                    VolumeSlider(audio, c, Modifier.weight(1f))
                    Spacer(Modifier.width(12.dp))
                    Box(Modifier.width(52.dp), contentAlignment = Alignment.CenterEnd) {
                        GlassText(if (audio.muted) tr(S.MUTED) else tr(S.PERCENT, "value" to (audio.volume * 100).roundToInt()), size = 16.sp)
                    }
                }
                Spacer(Modifier.height(10.dp))
            }
            // The card may be taller than its content (a grid block, the equal-height landscape row): push the keys to the bottom.
            if (stretch) Spacer(Modifier.weight(1f))
            Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.spacedBy(8.dp), verticalAlignment = Alignment.CenterVertically) {
                if (audio != null) {
                    MuteButton(audio, onClick = {
                        c.tap()
                        c.update { copy(audio = AudioState(audio.volume, !audio.muted)) }
                        c.send(ActionMessages.volumeMute(!audio.muted))
                    })
                }
                if (keys) {
                    Spacer(Modifier.weight(1f))
                    RoundIconKey(R.drawable.ox_next_left) { c.tap(); c.send(ActionMessages.mediaPrevious()) }
                    RoundIconKey(R.drawable.ox_play) { c.tap(); c.send(ActionMessages.mediaPlayPause()) }
                    RoundIconKey(R.drawable.ox_next_right) { c.tap(); c.send(ActionMessages.mediaNext()) }
                }
            }
        }
    }
}

@Composable
private fun VolumeSlider(audio: AudioState, c: Controls, modifier: Modifier) {
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
        modifier = modifier,
    )
}

/**
 * The now-playing block. The cover grows with the block ([NowPlayingLayout]): beside the text it is as tall as the block,
 * but the text column keeps at least ~180 dp; in a block much taller than wide it sits above the text, as wide as the block.
 * The bitmap is only scaled (high quality) to the drawn size; the title, artist, app and the three keys follow.
 * With [stretch] the content follows the block's height: beside the cover the text column fills the room (title, artist and
 * app on top, the three keys spread along the bottom); above the text (taller than wide) the cover is on top and the text
 * and keys fill the rest. [appIcon] is Spotify's icon (when the media comes from Spotify), small in the block's top-right corner.
 */
@Composable
private fun NowPlayingCard(
    now: NowPlaying,
    c: Controls,
    modifier: Modifier = Modifier.fillMaxWidth(),
    stretch: Boolean = false,
    appIcon: ImageBitmap? = null,
) {
    val cover = now.artworkId?.let { c.images[it] }
    GlassCard(modifier) {
        BoxWithConstraints(Modifier.fillMaxWidth().weight(1f, fill = stretch)) {
            val plan = NowPlayingLayout.plan(maxWidth.value, if (maxHeight.value.isFinite()) maxHeight.value else NowPlayingLayout.MIN_COVER)
            val side = plan.coverSide.dp
            val art: @Composable () -> Unit = {
                Box(
                    Modifier.size(side).clip(CoverShape).background(Color.White.copy(alpha = 0.10f)),
                    contentAlignment = Alignment.Center,
                ) {
                    if (cover != null) {
                        Image(
                            cover,
                            contentDescription = null,
                            modifier = Modifier.fillMaxSize(),
                            contentScale = ContentScale.Crop,
                            filterQuality = FilterQuality.High,
                        )
                    } else {
                        Picto(R.drawable.ic_action_music_note, (plan.coverSide * 0.46f).dp, alpha = 0.6f)
                    }
                }
            }
            // The icon sits in the top-right corner: beside the cover the title stops short of it, above the text it overlays the cover.
            val showIcon = appIcon != null && NowPlayingLayout.isSpotify(now.app)
            val titleEnd = if (showIcon && !plan.vertical) NowPlayingLayout.APP_ICON_DP.dp + 8.dp else 0.dp
            val texts: @Composable () -> Unit = {
                Box(Modifier.padding(end = titleEnd)) { OneLine(now.title.ifBlank { tr(S.NOW_PLAYING) }, 18.sp, FontWeight.Bold, 1f) }
                val details = listOf(now.artist, now.album).filter { it.isNotBlank() }.joinToString(" · ")
                if (details.isNotEmpty()) OneLine(details, 14.sp, FontWeight.Normal, 0.8f)
                if (now.app.isNotBlank()) OneLine(now.app, 12.sp, FontWeight.Normal, 0.55f)
            }
            val keys: @Composable (Arrangement.Horizontal, Modifier) -> Unit = { arrangement, keysModifier ->
                Row(keysModifier, horizontalArrangement = arrangement, verticalAlignment = Alignment.CenterVertically) {
                    RoundIconKey(R.drawable.ox_next_left) { c.tap(); c.send(ActionMessages.mediaPrevious()) }
                    RoundIconKey(if (now.playing) R.drawable.ox_pause else R.drawable.ox_play) {
                        c.tap()
                        c.update { copy(nowPlaying = nowPlaying?.copy(playing = !now.playing)) }
                        c.send(ActionMessages.mediaPlayPause())
                    }
                    RoundIconKey(R.drawable.ox_next_right) { c.tap(); c.send(ActionMessages.mediaNext()) }
                }
            }
            if (plan.vertical) {
                Column(Modifier.fillMaxSize(), horizontalAlignment = Alignment.CenterHorizontally) {
                    art()
                    Spacer(Modifier.height(10.dp))
                    // Text on top of what is left, the keys at its bottom.
                    Column(Modifier.fillMaxWidth().weight(1f), horizontalAlignment = Alignment.CenterHorizontally, verticalArrangement = Arrangement.SpaceBetween) {
                        Column(Modifier.padding(bottom = 10.dp), horizontalAlignment = Alignment.CenterHorizontally) { texts() }
                        keys(Arrangement.spacedBy(10.dp, Alignment.CenterHorizontally), Modifier)
                    }
                }
            } else {
                Row(
                    Modifier.fillMaxSize(),
                    horizontalArrangement = Arrangement.spacedBy(NowPlayingLayout.GAP.dp),
                    verticalAlignment = Alignment.CenterVertically,
                ) {
                    art()
                    // The column takes the width right of the cover and the block's height: text on top, the keys spread along the bottom.
                    Column(Modifier.weight(1f).fillMaxHeight(), verticalArrangement = Arrangement.SpaceBetween) {
                        Column(Modifier.padding(bottom = 10.dp)) { texts() }
                        keys(Arrangement.SpaceEvenly, Modifier.fillMaxWidth())
                    }
                }
            }
            if (showIcon && appIcon != null) {
                Image(
                    appIcon,
                    contentDescription = null,
                    modifier = Modifier.align(Alignment.TopEnd).size(NowPlayingLayout.APP_ICON_DP.dp).clip(RoundedCornerShape(5.dp)),
                    contentScale = ContentScale.Fit,
                    filterQuality = FilterQuality.High,
                )
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
private fun BrightnessCard(brightness: BrightnessState, c: Controls, modifier: Modifier = Modifier.fillMaxWidth(), stretch: Boolean = false) {
    GlassCard(modifier) {
        Row(verticalAlignment = Alignment.CenterVertically) {
            Picto(brightnessRes(brightness), 28.dp)
            Spacer(Modifier.width(8.dp))
            GlassText(tr(S.BRIGHTNESS), size = 16.sp, weight = FontWeight.SemiBold)
        }
        Spacer(Modifier.height(8.dp))
        // With [stretch] (a grid block) the slider sits in the middle of the room under the header; nothing grows.
        if (stretch) Spacer(Modifier.weight(1f))
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
                GlassText(tr(S.PERCENT, "value" to (brightness.value * 100).roundToInt()), size = 16.sp)
            }
        }
        if (stretch) Spacer(Modifier.weight(1f))
    }
}

@Composable
private fun WifiTile(wifi: WifiState, c: Controls, modifier: Modifier) {
    Tile(wifiRes(wifi), tr(S.WIFI), wifi.ssid ?: onOff(wifi.on), wifi.on, modifier) {
        c.tap()
        c.update { copy(wifi = wifi.copy(on = !wifi.on)) }
        c.send(ActionMessages.wifiSet(!wifi.on))
    }
}

@Composable
private fun BluetoothTile(bt: BluetoothState, c: Controls, modifier: Modifier) {
    Tile(R.drawable.ox_bluetooth, tr(S.BLUETOOTH), bt.connected.firstOrNull() ?: onOff(bt.on), bt.on, modifier) {
        c.tap()
        c.update { copy(bluetooth = BluetoothState(!bt.on, bt.connected)) }
        c.send(ActionMessages.bluetoothSet(!bt.on))
    }
}

@Composable
private fun AirplaneTile(plane: AirplaneState, c: Controls, modifier: Modifier) {
    Tile(R.drawable.ic_action_airplane, tr(S.AIRPLANE), onOff(plane.on), plane.on, modifier) {
        c.tap()
        c.update { copy(airplane = AirplaneState(!plane.on)) }
        c.send(ActionMessages.airplaneSet(!plane.on))
    }
}

/**
 * A launcher block: the icon and the name of what it opens on the PC. [image] is the PC's own icon of the application
 * (full colour, from the image cache), or null while it has not arrived: then the neutral [fallback] drawable is shown.
 * A tap opens [target] on the PC. The icon grows with the block.
 */
@Composable
private fun LauncherTile(target: String, label: String, fallback: Int, image: ImageBitmap?, c: Controls, modifier: Modifier) {
    BoxWithConstraints(
        modifier
            .clip(TileShape)
            .background(Color.White.copy(alpha = 0.12f))
            .border(1.dp, Color.White.copy(alpha = 0.28f), TileShape)
            .clickable {
                c.tap()
                c.send(ActionMessages.launchOpen(target))
            }
            .padding(10.dp),
        contentAlignment = Alignment.Center,
    ) {
        val icon = (min(maxWidth.value, maxHeight.value) * 0.42f).coerceIn(28f, 96f).dp
        Column(horizontalAlignment = Alignment.CenterHorizontally, verticalArrangement = Arrangement.Center) {
            if (image != null) {
                Image(image, contentDescription = null, modifier = Modifier.size(icon).clip(RoundedCornerShape(8.dp)), contentScale = ContentScale.Fit, filterQuality = FilterQuality.High)
            } else {
                Picto(fallback, icon)
            }
            Spacer(Modifier.height(6.dp))
            BasicText(
                label,
                style = TextStyle(color = Color.White, fontSize = 13.sp, fontWeight = FontWeight.SemiBold, textAlign = TextAlign.Center),
                maxLines = 1,
                overflow = TextOverflow.Ellipsis,
            )
        }
    }
}

/** The drives of the USB block, one chip each; it scrolls on its own when there are more than fit. */
@Composable
private fun UsbBlock(usb: List<UsbDrive>, c: Controls, modifier: Modifier, mode: UsbMode) {
    val compact = mode == UsbMode.COMPACT
    // Not inside an intrinsic-size row (a BoxWithConstraints there crashes): the grid gives the block a fixed cell.
    BoxWithConstraints(modifier) {
        if (UsbContent.fits(usb.size, maxHeight.value)) {
            // Enough room: the chips share the block's height (each at least 68 dp).
            Column(Modifier.fillMaxSize(), verticalArrangement = Arrangement.spacedBy(UsbContent.CHIP_GAP.dp)) {
                for (drive in usb) UsbChip(drive, c, Modifier.fillMaxWidth().weight(1f), compact = compact, fixedHeight = false)
            }
        } else {
            Column(
                Modifier.fillMaxSize().verticalScroll(rememberScrollState()),
                verticalArrangement = Arrangement.spacedBy(UsbContent.CHIP_GAP.dp, Alignment.CenterVertically),
            ) {
                for (drive in usb) UsbChip(drive, c, Modifier.fillMaxWidth(), compact = compact)
            }
        }
    }
}

/** The content of one grid block, filling the cell it is given; [clockSp] sizes the clock for its cell. */
@Composable
internal fun BlockContent(id: BlockId, state: ActionsState, c: Controls, clockSp: Float, cols: Int, rows: Int, modifier: Modifier) {
    when (id) {
        BlockId.CLOCK -> Box(modifier, contentAlignment = Alignment.Center) {
            // The clock takes its natural height inside its cell.
            Box(Modifier.wrapContentHeight(unbounded = true)) { ClockBlock(state.clock, state.battery, clockSp, (clockSp * 0.42f).coerceIn(12f, 22f)) }
        }
        BlockId.SOUND -> SoundCard(state, c, modifier, stretch = true, mode = SoundContent.mode(cols, rows, soundKeys(state)))
        BlockId.NOW_PLAYING -> state.nowPlaying?.let {
            NowPlayingCard(it, c, modifier, stretch = true, appIcon = state.launchers?.spotifyIcon?.let { id -> c.images[id] })
        }
        BlockId.BRIGHTNESS -> state.brightness?.let { BrightnessCard(it, c, modifier, stretch = true) }
        BlockId.WIFI -> state.wifi?.let { WifiTile(it, c, modifier) }
        BlockId.BLUETOOTH -> state.bluetooth?.let { BluetoothTile(it, c, modifier) }
        BlockId.AIRPLANE -> state.airplane?.let { AirplaneTile(it, c, modifier) }
        BlockId.USB -> UsbBlock(state.usb, c, modifier, UsbContent.mode(cols))
        BlockId.SETTINGS -> LauncherTile("settings", tr(S.BLOCK_SETTINGS), R.drawable.ox_settings, null, c, modifier)
        BlockId.DISCORD -> LauncherTile("discord", tr(S.BLOCK_DISCORD), R.drawable.ox_apps, state.launchers?.discordIcon?.let { c.images[it] }, c, modifier)
        BlockId.SPOTIFY -> LauncherTile("spotify", tr(S.BLOCK_SPOTIFY), R.drawable.ox_apps, state.launchers?.spotifyIcon?.let { c.images[it] }, c, modifier)
        BlockId.DOWNLOADS -> LauncherTile("downloads", tr(S.BLOCK_DOWNLOADS), R.drawable.ox_download, null, c, modifier)
        BlockId.PERF_CPU, BlockId.PERF_GPU, BlockId.PERF_RAM, BlockId.PERF_NET, BlockId.PERF_NPU -> Unit // drawn in the next commit
    }
}

@Composable
private fun onOff(on: Boolean) = tr(if (on) S.STATE_ON else S.STATE_OFF)

/**
 * Compact USB chip: pictogram, "label  E:" with "12 Go libres" under it, then the open-folder and eject buttons.
 * The chips are stacked inside the USB block of the grid.
 */
@Composable
private fun UsbChip(drive: UsbDrive, c: Controls, modifier: Modifier = Modifier, compact: Boolean = false, fixedHeight: Boolean = true) {
    Row(
        modifier
            .then(if (fixedHeight) Modifier.height(UsbContent.CHIP_HEIGHT.dp) else Modifier)
            .clip(ChipShape)
            .background(Color.White.copy(alpha = 0.10f))
            .border(1.dp, Color.White.copy(alpha = 0.25f), ChipShape)
            .padding(start = 14.dp, end = 10.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Picto(usbRes(drive.kind), 28.dp, alpha = 0.9f)
        Spacer(Modifier.width(10.dp))
        Column(Modifier.weight(1f), verticalArrangement = Arrangement.Center) {
            BasicText(
                drive.label.ifBlank { tr(S.USB_DRIVE) } + "  " + drive.drive,
                style = TextStyle(color = Color.White, fontSize = 15.sp, fontWeight = FontWeight.SemiBold),
                maxLines = 1,
                overflow = TextOverflow.Ellipsis,
            )
            drive.freeBytes?.takeIf { !compact }?.let {
                BasicText(
                    ActionsFormat.freeSpace(it, LocalLang.current),
                    style = TextStyle(color = Color.White.copy(alpha = 0.7f), fontSize = 12.sp),
                    maxLines = 1,
                    overflow = TextOverflow.Ellipsis,
                )
            }
        }
        Spacer(Modifier.width(6.dp))
        if (!compact) {
            ChipIconButton(R.drawable.ox_dossier, tr(S.USB_OPEN_DESC, "drive" to drive.drive)) {
                c.tap()
                c.send(ActionMessages.usbOpen(drive.drive))
            }
            Spacer(Modifier.width(6.dp))
        }
        ChipIconButton(R.drawable.ox_eject, tr(S.USB_EJECT_DESC, "drive" to drive.drive)) {
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
internal fun Pill(text: String, selected: Boolean, onClick: () -> Unit, modifier: Modifier = Modifier, icon: Int? = null) {
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
        if (icon == null) {
            GlassText(text, size = 15.sp, weight = if (selected) FontWeight.SemiBold else FontWeight.Normal)
        } else {
            Row(verticalAlignment = Alignment.CenterVertically) {
                Picto(icon, 20.dp)
                Spacer(Modifier.width(8.dp))
                GlassText(text, size = 15.sp, weight = if (selected) FontWeight.SemiBold else FontWeight.Normal)
            }
        }
    }
}

/**
 * Speaker toggle: red tint, crossed-out speaker and the label "Muet" when muted; the speaker for the level otherwise.
 * [compact] is a 56 dp square with the icon alone (the card header already says "Son").
 */
@Composable
private fun MuteButton(audio: AudioState, onClick: () -> Unit, compact: Boolean = false) {
    val muted = audio.muted
    val tint = if (muted) MuteRed else Color.White
    val shape = if (compact) RoundedCornerShape(16.dp) else TileShape
    val description = tr(if (muted) S.UNMUTE_DESC else S.MUTE_DESC)
    val base = Modifier
        .clip(shape)
        .background(if (muted) MuteRed.copy(alpha = 0.28f) else Color.White.copy(alpha = 0.10f))
        .border(if (muted) 2.dp else 1.dp, if (muted) MuteRed.copy(alpha = 0.9f) else Color.White.copy(alpha = 0.25f), shape)
        .semantics { contentDescription = description }
        .clickable(onClick = onClick)
    if (compact) {
        Box(base.size(56.dp), contentAlignment = Alignment.Center) {
            Picto(volumeRes(audio), 32.dp, tint = tint)
        }
    } else {
        Column(base.padding(horizontal = 16.dp, vertical = 8.dp), horizontalAlignment = Alignment.CenterHorizontally) {
            Picto(volumeRes(audio), 32.dp, tint = tint)
            GlassText(tr(if (muted) S.MUTED else S.SOUND), size = 12.sp, color = tint, weight = if (muted) FontWeight.SemiBold else FontWeight.Normal)
        }
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
