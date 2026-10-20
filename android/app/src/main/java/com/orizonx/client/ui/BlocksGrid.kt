package com.orizonx.client.ui

import androidx.compose.animation.core.Animatable
import androidx.compose.animation.core.LinearEasing
import androidx.compose.animation.core.RepeatMode
import androidx.compose.animation.core.StartOffset
import androidx.compose.animation.core.VectorConverter
import androidx.compose.animation.core.animateFloat
import androidx.compose.animation.core.infiniteRepeatable
import androidx.compose.animation.core.rememberInfiniteTransition
import androidx.compose.animation.core.tween
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.gestures.awaitEachGesture
import androidx.compose.foundation.gestures.awaitFirstDown
import androidx.compose.foundation.gestures.detectDragGestures
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.BoxWithConstraints
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.offset
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.BasicText
import androidx.compose.foundation.verticalScroll
import androidx.compose.runtime.Composable
import androidx.compose.runtime.CompositionLocalProvider
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.State
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberUpdatedState
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.graphicsLayer
import androidx.compose.ui.hapticfeedback.HapticFeedbackType
import androidx.compose.ui.input.pointer.PointerEventPass
import androidx.compose.ui.input.pointer.pointerInput
import androidx.compose.ui.platform.LocalDensity
import androidx.compose.ui.platform.LocalViewConfiguration
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.text.TextStyle
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.IntOffset
import androidx.compose.ui.unit.IntSize
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.compose.ui.zIndex
import com.orizonx.client.actions.ActionsBlocks
import com.orizonx.client.actions.ActionsLayout
import com.orizonx.client.actions.ActionsState
import com.orizonx.client.actions.BlockGrid
import com.orizonx.client.actions.BlockId
import com.orizonx.client.i18n.S
import com.orizonx.client.i18n.tr
import kotlin.math.min
import kotlin.math.roundToInt

private val GridGap = 14.dp
private val BlockShape = RoundedCornerShape(20.dp)
private const val LONG_PRESS_MS = 500L
private const val MOVE_ANIMATION_MS = 200
private const val MOVE_COOLDOWN_MS = 250L

/** Name of a block, for the "+ Add" list and the hide badge. */
private fun blockName(id: BlockId): S = when (id) {
    BlockId.CLOCK -> S.BLOCK_CLOCK
    BlockId.SOUND -> S.BLOCK_SOUND
    BlockId.NOW_PLAYING -> S.BLOCK_NOW_PLAYING
    BlockId.BRIGHTNESS -> S.BLOCK_BRIGHTNESS
    BlockId.WIFI -> S.BLOCK_WIFI
    BlockId.BLUETOOTH -> S.BLOCK_BLUETOOTH
    BlockId.AIRPLANE -> S.BLOCK_AIRPLANE
    BlockId.USB -> S.BLOCK_USB
}

/**
 * The main Actions screen: the blocks the PC offers, in the user's [layout], on a grid that scrolls vertically.
 * A long press outside a block's controls starts the edit mode ([editing]); there blocks wiggle, can be dragged onto
 * one another to swap places, hidden with their badge, and brought back from the "+ Add" list. The layout is changed
 * only through [onLayout]; [haptic] gives the feedback of entering, moving and hiding.
 */
@Composable
internal fun BlocksBody(
    state: ActionsState,
    c: Controls,
    layout: ActionsLayout,
    onLayout: (ActionsLayout) -> Unit,
    landscape: Boolean,
    editing: Boolean,
    onEditing: (Boolean) -> Unit,
    haptic: (HapticFeedbackType) -> Unit,
    modifier: Modifier = Modifier,
) {
    val present = ActionsBlocks.present(state)
    val visible = layout.visible(present)
    var dragging by remember { mutableStateOf<BlockId?>(null) }
    Column(
        modifier.verticalScroll(rememberScrollState(), enabled = dragging == null),
        verticalArrangement = Arrangement.spacedBy(10.dp),
    ) {
        if (editing) {
            EditBar(layout.hiddenInOrder(), onRestore = { onLayout(layout.restore(it)) }, onDone = { onEditing(false) })
        }
        if (visible.isEmpty() && !editing) {
            // Everything is hidden or missing: keep a way back into the edit mode.
            if (layout.hidden.isNotEmpty()) {
                Pill(tr(S.BLOCKS_ADD), selected = false, onClick = { c.tap(); onEditing(true) })
            }
        } else {
            CompositionLocalProvider(LocalGlassPadding provides 14.dp) {
                Grid(state, c, layout, onLayout, visible, landscape, editing, onEditing, haptic, dragging) { dragging = it }
            }
        }
        Spacer(Modifier.height(16.dp))
    }
}

@Composable
private fun Grid(
    state: ActionsState,
    c: Controls,
    layout: ActionsLayout,
    onLayout: (ActionsLayout) -> Unit,
    visible: List<BlockId>,
    landscape: Boolean,
    editing: Boolean,
    onEditing: (Boolean) -> Unit,
    haptic: (HapticFeedbackType) -> Unit,
    dragging: BlockId?,
    setDragging: (BlockId?) -> Unit,
) {
    BoxWithConstraints(Modifier.fillMaxWidth()) {
        val density = LocalDensity.current
        val columns = if (landscape && maxWidth >= 600.dp) 4 else 2
        val rowHeight: Dp = if (columns >= 4) 170.dp else 150.dp
        val cellWidth = (maxWidth - GridGap * (columns - 1)) / columns
        val placements = BlockGrid.place(visible, columns)
        val rows = BlockGrid.rowCount(placements)
        val gridHeight = if (rows == 0) 0.dp else rowHeight * rows + GridGap * (rows - 1)

        val cellW = with(density) { cellWidth.toPx() }
        val rowH = with(density) { rowHeight.toPx() }
        val gap = with(density) { GridGap.toPx() }
        fun position(p: BlockGrid.Placement) = IntOffset(((cellW + gap) * p.col).roundToInt(), ((rowH + gap) * p.row).roundToInt())
        fun size(p: BlockGrid.Placement) = IntSize((cellW * p.cols + gap * (p.cols - 1)).roundToInt(), (rowH * p.rows + gap * (p.rows - 1)).roundToInt())

        val latestPlacements by rememberUpdatedState(placements)
        val latestLayout by rememberUpdatedState(layout)
        val latestEditing by rememberUpdatedState(editing)
        var dragPos by remember { mutableStateOf(IntOffset.Zero) }
        var lastMove by remember { mutableStateOf(0L) }

        Box(Modifier.fillMaxWidth().height(gridHeight)) {
            for ((index, placement) in placements.withIndex()) {
                val id = placement.id
                androidx.compose.runtime.key(id) {
                    val isDragging = dragging == id
                    GridBlock(
                        target = position(placement),
                        size = size(placement),
                        editing = editing,
                        isDragging = isDragging,
                        dragPos = dragPos,
                        wiggleIndex = index,
                        hideDescription = tr(S.BLOCKS_HIDE_DESC, "name" to tr(blockName(id))),
                        onLongPress = {
                            haptic(HapticFeedbackType.LongPress)
                            onEditing(true)
                        },
                        onDragStart = {
                            setDragging(id)
                            dragPos = position(latestPlacements.first { it.id == id })
                        },
                        onDrag = { delta ->
                            dragPos += delta
                            val me = latestPlacements.firstOrNull { it.id == id } ?: return@GridBlock
                            val mySize = size(me)
                            val centerX = dragPos.x + mySize.width / 2
                            val centerY = dragPos.y + mySize.height / 2
                            val now = System.currentTimeMillis()
                            val over = latestPlacements.firstOrNull { other ->
                                if (other.id == id) return@firstOrNull false
                                val pos = position(other)
                                val sz = size(other)
                                centerX >= pos.x && centerX < pos.x + sz.width && centerY >= pos.y && centerY < pos.y + sz.height
                            }
                            if (over != null && now - lastMove >= MOVE_COOLDOWN_MS) {
                                lastMove = now
                                haptic(HapticFeedbackType.ContextClick)
                                onLayout(latestLayout.move(id, over.id))
                            }
                        },
                        onDragEnd = { setDragging(null) },
                        onHide = {
                            haptic(HapticFeedbackType.ContextClick)
                            onLayout(latestLayout.hide(id))
                        },
                    ) { m ->
                        BlockContent(id, state, c, min(if (columns >= 4) 76f else 60f, cellWidth.value * placement.cols / 4.1f), m)
                    }
                }
            }
        }
    }
}

/**
 * One block at [target] (animated over ~200 ms when it changes). Outside the edit mode a long press that no control of the
 * block took starts it; inside, a transparent layer takes every touch (so the controls are off), drags move the block, and
 * the badge hides it.
 */
@Composable
private fun GridBlock(
    target: IntOffset,
    size: IntSize,
    editing: Boolean,
    isDragging: Boolean,
    dragPos: IntOffset,
    wiggleIndex: Int,
    hideDescription: String,
    onLongPress: () -> Unit,
    onDragStart: () -> Unit,
    onDrag: (IntOffset) -> Unit,
    onDragEnd: () -> Unit,
    onHide: () -> Unit,
    content: @Composable (Modifier) -> Unit,
) {
    val density = LocalDensity.current
    val anim = remember { Animatable(target, IntOffset.VectorConverter) }
    // Settles into its cell when it is not held; while held it follows the finger.
    LaunchedEffect(target, isDragging) {
        if (!isDragging) anim.animateTo(target, tween(MOVE_ANIMATION_MS))
    }
    LaunchedEffect(isDragging, dragPos) {
        if (isDragging) anim.snapTo(dragPos)
    }
    val wiggle: State<Float>? = if (editing && !isDragging) rememberWiggle(wiggleIndex) else null
    val latestLongPress by rememberUpdatedState(onLongPress)
    val latestDragStart by rememberUpdatedState(onDragStart)
    val latestDrag by rememberUpdatedState(onDrag)
    val latestDragEnd by rememberUpdatedState(onDragEnd)
    val slop = LocalViewConfiguration.current.touchSlop
    val widthDp = with(density) { size.width.toDp() }
    val heightDp = with(density) { size.height.toDp() }

    Box(
        Modifier
            .offset { anim.value }
            .size(widthDp, heightDp)
            .zIndex(if (isDragging) 1f else 0f)
            .graphicsLayer {
                val scale = if (isDragging) 1.05f else 1f
                scaleX = scale
                scaleY = scale
                rotationZ = wiggle?.value ?: 0f
                shadowElevation = if (isDragging) 24.dp.toPx() else 0f
                shape = BlockShape
                clip = false
            }
            .then(
                if (editing) {
                    Modifier
                } else {
                    // Observes the gesture after the controls had their say: a touch one of them took never starts the edit mode.
                    Modifier.pointerInput(Unit) {
                        awaitEachGesture {
                            val down = awaitFirstDown(requireUnconsumed = true, pass = PointerEventPass.Final)
                            var held = true
                            val outcome = withTimeoutOrNull(LONG_PRESS_MS) {
                                while (held) {
                                    val event = awaitPointerEvent(PointerEventPass.Final)
                                    val change = event.changes.firstOrNull { it.id == down.id }
                                    if (change == null || !change.pressed || change.isConsumed ||
                                        (change.position - down.position).getDistance() > slop
                                    ) {
                                        held = false
                                    }
                                }
                            }
                            // Still held, still still: the timeout ended the wait.
                            if (outcome == null && held) latestLongPress()
                        }
                    }
                },
            ),
    ) {
        content(Modifier.fillMaxSize())
        if (editing) {
            Box(
                Modifier
                    .fillMaxSize()
                    .pointerInput(Unit) {
                        detectDragGestures(
                            onDragStart = { latestDragStart() },
                            onDrag = { change, amount ->
                                change.consume()
                                latestDrag(IntOffset(amount.x.roundToInt(), amount.y.roundToInt()))
                            },
                            onDragEnd = { latestDragEnd() },
                            onDragCancel = { latestDragEnd() },
                        )
                    },
            )
            Box(
                Modifier
                    .align(Alignment.TopStart)
                    .padding(6.dp)
                    .size(30.dp)
                    .clip(CircleShape)
                    .background(Color(0xFF3A3A3F))
                    .border(1.dp, Color.White.copy(alpha = 0.6f), CircleShape)
                    .semantics { contentDescription = hideDescription }
                    .clickable(onClick = onHide),
                contentAlignment = Alignment.Center,
            ) {
                BasicText("✕", style = TextStyle(color = Color.White, fontSize = 14.sp, fontWeight = FontWeight.Bold))
            }
        }
    }
}

/** A tiny rotation back and forth (about one degree), each block starting a little after the previous one. */
@Composable
private fun rememberWiggle(index: Int): State<Float> {
    val transition = rememberInfiniteTransition(label = "wiggle")
    return transition.animateFloat(
        initialValue = -1f,
        targetValue = 1f,
        animationSpec = infiniteRepeatable(tween(130, easing = LinearEasing), RepeatMode.Reverse, initialStartOffset = StartOffset((index % 6) * 43)),
        label = "wiggleAngle",
    )
}

/** "+ Add" (only when something is hidden), opening the list of hidden blocks, and "Done". */
@Composable
private fun EditBar(hidden: List<BlockId>, onRestore: (BlockId) -> Unit, onDone: () -> Unit) {
    var listOpen by remember { mutableStateOf(false) }
    Column(Modifier.fillMaxWidth(), verticalArrangement = Arrangement.spacedBy(8.dp)) {
        Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.End, verticalAlignment = Alignment.CenterVertically) {
            if (hidden.isNotEmpty()) {
                Pill(tr(S.BLOCKS_ADD), selected = listOpen, onClick = { listOpen = !listOpen })
                Spacer(Modifier.size(10.dp))
            }
            Pill(tr(S.BLOCKS_DONE), selected = true, onClick = onDone)
        }
        if (listOpen && hidden.isNotEmpty()) {
            Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.End) {
                Column(verticalArrangement = Arrangement.spacedBy(8.dp), horizontalAlignment = Alignment.End) {
                    for (id in hidden) {
                        Pill(tr(blockName(id)), selected = false, onClick = {
                            onRestore(id)
                            if (hidden.size <= 1) listOpen = false
                        })
                    }
                }
            }
        }
    }
}
