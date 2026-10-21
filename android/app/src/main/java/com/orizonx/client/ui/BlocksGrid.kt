package com.orizonx.client.ui

import androidx.compose.animation.core.Animatable
import androidx.compose.animation.core.VectorConverter
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
import androidx.compose.foundation.layout.fillMaxHeight
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.offset
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.BasicText
import androidx.compose.foundation.verticalScroll
import androidx.compose.runtime.Composable
import androidx.compose.runtime.CompositionLocalProvider
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberUpdatedState
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.draw.clipToBounds
import androidx.compose.ui.draw.drawBehind
import androidx.compose.ui.geometry.CornerRadius
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.geometry.Size
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.drawscope.Stroke
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
import androidx.compose.ui.unit.IntOffset
import androidx.compose.ui.unit.IntSize
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.compose.ui.zIndex
import com.orizonx.client.actions.ActionsBlocks
import com.orizonx.client.actions.ActionsLayout
import com.orizonx.client.actions.ActionsState
import com.orizonx.client.actions.BlockGrid
import com.orizonx.client.actions.CellPos
import com.orizonx.client.actions.GridOrientation
import com.orizonx.client.actions.GridPlanner
import com.orizonx.client.actions.BlockId
import com.orizonx.client.actions.ControlRules
import com.orizonx.client.actions.Span
import com.orizonx.client.i18n.S
import com.orizonx.client.i18n.tr
import kotlin.math.min
import kotlin.math.roundToInt

private val GridGap = 8.dp
private val BlockShape = RoundedCornerShape(20.dp)
private val CellShape = RoundedCornerShape(14.dp)
private const val LONG_PRESS_MS = 500L
private const val MOVE_ANIMATION_MS = 200

/** Name of a block, for the "+ Add" list and the hide badge. */
internal fun blockName(id: BlockId): S = when (id) {
    BlockId.CLOCK -> S.BLOCK_CLOCK
    BlockId.SOUND -> S.BLOCK_SOUND
    BlockId.NOW_PLAYING -> S.BLOCK_NOW_PLAYING
    BlockId.BRIGHTNESS -> S.BLOCK_BRIGHTNESS
    BlockId.WIFI -> S.BLOCK_WIFI
    BlockId.BLUETOOTH -> S.BLOCK_BLUETOOTH
    BlockId.AIRPLANE -> S.BLOCK_AIRPLANE
    BlockId.USB -> S.BLOCK_USB
    BlockId.USB_2 -> S.BLOCK_USB_2
    BlockId.USB_3 -> S.BLOCK_USB_3
    BlockId.USB_4 -> S.BLOCK_USB_4
    BlockId.SETTINGS -> S.BLOCK_SETTINGS
    BlockId.DISCORD -> S.BLOCK_DISCORD
    BlockId.SPOTIFY -> S.BLOCK_SPOTIFY
    BlockId.DOWNLOADS -> S.BLOCK_DOWNLOADS
    BlockId.PERF_CPU -> S.BLOCK_PERF_CPU
    BlockId.PERF_GPU -> S.BLOCK_PERF_GPU
    BlockId.PERF_RAM -> S.BLOCK_PERF_RAM
    BlockId.PERF_NET -> S.BLOCK_PERF_NET
    BlockId.PERF_NPU -> S.BLOCK_PERF_NPU
}

/**
 * The main Actions screen: the blocks the PC offers, on a grid of square cells that is always [BlockGrid.ROWS] rows tall:
 * the cells are sized to fill the height between the header and the context bar, and as many columns as fit in the width
 * are used (the grid is centred). Blocks that do not fit in 6 rows make it scroll.
 *
 * Blocks stay on the exact cells the user put them on (no gravity, gaps are fine; see [GridPlanner]). A long press outside
 * a block's controls starts the edit mode ([editing]). There the cells are drawn behind the blocks; a block can be dragged
 * (the cells under its top-left corner light up, red when the spot is not free) and dropped on a free spot, or it springs
 * back; resized from its bottom-right corner (it only grows into free cells, down to its minimum); and hidden with its badge.
 * The buttons of the edit mode live in the screen's header, so nothing here moves when it starts or ends. The layout is
 * changed only through [onLayout]; [haptic] gives the feedback.
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
    BoxWithConstraints(modifier.clipToBounds()) {
        val density = LocalDensity.current
        val metrics = BlockGrid.metrics(
            width = with(density) { maxWidth.toPx() },
            height = with(density) { maxHeight.toPx() },
            gap = with(density) { GridGap.toPx() },
        )
        Column(Modifier.fillMaxSize().verticalScroll(rememberScrollState(), enabled = dragging == null)) {
            if (visible.isEmpty() && !editing) {
                // Everything is hidden or missing: keep a way back into the edit mode.
                if (layout.hidden.isNotEmpty()) {
                    Pill(tr(S.BLOCKS_ADD), selected = false, onClick = { c.tap(); onEditing(true) })
                }
            } else {
                CompositionLocalProvider(LocalGlassPadding provides 14.dp) {
                    Grid(state, c, layout, onLayout, visible, metrics, GridOrientation.of(landscape), editing, onEditing, haptic, dragging) { dragging = it }
                }
            }
        }
    }
}

@Composable
private fun Grid(
    state: ActionsState,
    c: Controls,
    layout: ActionsLayout,
    onLayout: (ActionsLayout) -> Unit,
    visible: List<BlockId>,
    metrics: BlockGrid.Metrics,
    orientation: GridOrientation,
    editing: Boolean,
    onEditing: (Boolean) -> Unit,
    haptic: (HapticFeedbackType) -> Unit,
    dragging: BlockId?,
    setDragging: (BlockId?) -> Unit,
) {
    val density = LocalDensity.current
    val columns = metrics.columns
    val keys = ControlRules.soundKeys(state)
    val cell = metrics.side
    val gap = with(density) { GridGap.toPx() }
    val pitch = cell + gap
    val placements = GridPlanner.place(visible, columns, BlockGrid.ROWS, { layout.sizeOf(it, columns, keys) }, layout.positionsFor(orientation))
    // Always at least the 6 rows; more only when some block had to go below them.
    val rows = maxOf(BlockGrid.ROWS, BlockGrid.rowCount(placements))
    val gridWidth = with(density) { (cell * columns + gap * (columns - 1)).toDp() }
    val gridHeight = with(density) { (cell * rows + gap * (rows - 1)).toDp() }
    fun position(p: BlockGrid.Placement) = IntOffset((pitch * p.col).roundToInt(), (pitch * p.row).roundToInt())
    fun size(p: BlockGrid.Placement) = IntSize((cell * p.cols + gap * (p.cols - 1)).roundToInt(), (cell * p.rows + gap * (p.rows - 1)).roundToInt())

    val latestPlacements by rememberUpdatedState(placements)
    val latestLayout by rememberUpdatedState(layout)
    var dragPos by remember { mutableStateOf(IntOffset.Zero) }
    var resizeStart by remember { mutableStateOf(Span(1, 1)) }
    var resizeAcc by remember { mutableStateOf(Offset.Zero) }

    // Where the held block would land: the cell nearest to its top-left corner.
    fun targetCell(): CellPos = CellPos((dragPos.x / pitch).roundToInt(), (dragPos.y / pitch).roundToInt())

    // The cells under the held block, and whether it may be dropped there.
    val held = placements.firstOrNull { it.id == dragging }
    val heldCell = if (held != null) targetCell() else null
    val heldFree = held != null && heldCell != null &&
        GridPlanner.isFree(placements, held.id, heldCell.x, heldCell.y, held.cols, held.rows, columns, BlockGrid.ROWS)
    val highlighted: Set<Pair<Int, Int>> = if (held != null && heldCell != null) {
        buildSet {
            for (r in heldCell.y until heldCell.y + held.rows) for (cc in heldCell.x until heldCell.x + held.cols) {
                if (cc in 0 until columns && r in 0 until rows) add(cc to r)
            }
        }
    } else {
        emptySet()
    }

    Box(Modifier.fillMaxWidth().height(gridHeight), contentAlignment = Alignment.TopCenter) {
        Box(
            Modifier
                .width(gridWidth)
                .fillMaxHeight()
                .then(
                    if (editing) {
                        Modifier.drawBehind {
                            val radius = CornerRadius(14.dp.toPx())
                            val stroke = Stroke(1.dp.toPx())
                            val bad = Color(0xFFE5484D)
                            for (r in 0 until rows) {
                                for (col in 0 until columns) {
                                    val topLeft = Offset(pitch * col, pitch * r)
                                    val on = (col to r) in highlighted
                                    val fill = if (!on) Color.White.copy(alpha = 0.07f) else if (heldFree) Color.White.copy(alpha = 0.16f) else bad.copy(alpha = 0.28f)
                                    val line = if (!on) Color.White.copy(alpha = 0.2f) else if (heldFree) Color.White.copy(alpha = 0.65f) else bad.copy(alpha = 0.85f)
                                    drawRoundRect(fill, topLeft, Size(cell, cell), radius)
                                    drawRoundRect(line, topLeft, Size(cell, cell), radius, style = stroke)
                                }
                            }
                        }
                    } else {
                        Modifier
                    },
                ),
        ) {
            for (placement in placements) {
                val id = placement.id
                androidx.compose.runtime.key(id) {
                    val isDragging = dragging == id
                    val widthDp = with(density) { size(placement).width.toDp().value }
                    val heightDp = with(density) { size(placement).height.toDp().value }
                    GridBlock(
                        target = position(placement),
                        size = size(placement),
                        editing = editing,
                        isDragging = isDragging,
                        dragPos = dragPos,
                        hideDescription = tr(S.BLOCKS_HIDE_DESC, "name" to tr(blockName(id))),
                        onLongPress = {
                            haptic(HapticFeedbackType.LongPress)
                            onEditing(true)
                        },
                        onDragStart = {
                            setDragging(id)
                            dragPos = position(latestPlacements.first { it.id == id })
                        },
                        onDrag = { delta -> dragPos += delta },
                        onDragEnd = {
                            val cellPos = targetCell()
                            val spot = GridPlanner.drop(latestPlacements, id, cellPos.x, cellPos.y, columns, BlockGrid.ROWS)
                            setDragging(null)
                            if (spot != null) {
                                // Free: it stays exactly there (and so does everything else). Otherwise it springs back.
                                haptic(HapticFeedbackType.ContextClick)
                                val moved = latestPlacements.map { if (it.id == id) it.copy(col = spot.x, row = spot.y) else it }
                                onLayout(latestLayout.withPlacements(orientation, moved))
                            }
                        },
                        onHide = {
                            haptic(HapticFeedbackType.ContextClick)
                            onLayout(latestLayout.withPlacements(orientation, latestPlacements).hide(id))
                        },
                        onResizeStart = {
                            val p = latestPlacements.first { it.id == id }
                            resizeStart = Span(p.cols, p.rows)
                            resizeAcc = Offset.Zero
                        },
                        onResize = { amount ->
                            resizeAcc += amount
                            val wanted = id.resized(resizeStart, (resizeAcc.x / pitch).roundToInt(), (resizeAcc.y / pitch).roundToInt())
                            // Grows only into free cells (it stops at other blocks and at the grid's edges), shrinks to its minimum.
                            val next = GridPlanner.resize(latestPlacements, id, wanted, columns, BlockGrid.ROWS)
                            val now = latestPlacements.first { it.id == id }
                            if (next != Span(now.cols, now.rows)) {
                                haptic(HapticFeedbackType.ContextClick)
                                onLayout(latestLayout.resize(id, next).withPlacements(orientation, latestPlacements))
                            }
                        },
                    ) { m ->
                        // The clock scales with its cell: big digits in a tall block, smaller in a one-row block.
                        val clockSp = min(((heightDp - 64f) / 1.2f).coerceIn(20f, 112f), widthDp / 4.1f)
                        BlockContent(id, state, c, clockSp, placement.cols, placement.rows, m)
                    }
                }
            }
        }
    }
}

/**
 * One block at [target] (animated over ~200 ms when it changes). Outside the edit mode a long press that no control of the
 * block took starts it; inside, a transparent layer takes every touch (so the controls are off), drags move the block, the
 * badge hides it and the corner handle resizes it.
 */
@Composable
private fun GridBlock(
    target: IntOffset,
    size: IntSize,
    editing: Boolean,
    isDragging: Boolean,
    dragPos: IntOffset,
    hideDescription: String,
    onLongPress: () -> Unit,
    onDragStart: () -> Unit,
    onDrag: (IntOffset) -> Unit,
    onDragEnd: () -> Unit,
    onHide: () -> Unit,
    onResizeStart: () -> Unit,
    onResize: (Offset) -> Unit,
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
    val latestLongPress by rememberUpdatedState(onLongPress)
    val latestDragStart by rememberUpdatedState(onDragStart)
    val latestDrag by rememberUpdatedState(onDrag)
    val latestDragEnd by rememberUpdatedState(onDragEnd)
    val latestResizeStart by rememberUpdatedState(onResizeStart)
    val latestResize by rememberUpdatedState(onResize)
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
            // Resize handle: drag it to grow or shrink the block cell by cell.
            Box(
                Modifier
                    .align(Alignment.BottomEnd)
                    .padding(6.dp)
                    .size(34.dp)
                    .clip(CircleShape)
                    .background(Color(0xFF3A3A3F))
                    .border(1.dp, Color.White.copy(alpha = 0.6f), CircleShape)
                    .pointerInput(Unit) {
                        detectDragGestures(
                            onDragStart = { latestResizeStart() },
                            onDrag = { change, amount ->
                                change.consume()
                                latestResize(amount)
                            },
                        )
                    },
                contentAlignment = Alignment.Center,
            ) {
                BasicText("↘", style = TextStyle(color = Color.White, fontSize = 16.sp, fontWeight = FontWeight.Bold))
            }
        }
    }
}
