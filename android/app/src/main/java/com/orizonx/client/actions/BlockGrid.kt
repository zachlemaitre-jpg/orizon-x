package com.orizonx.client.actions

import kotlin.math.floor
import kotlin.math.max
import kotlin.math.min

/** Size of a block in grid cells. */
data class Span(val cols: Int, val rows: Int)

/**
 * The blocks of the Actions main screen. Each has a stable [wire] id (kept in the saved layout) and a size in square
 * grid cells: a default one and a minimum. There is no maximum: a block can be made as wide as the grid and as tall as the
 * user likes (up to a sanity cap of [MAX_CELLS]). The enum order is the default order.
 *
 * What a block shows adapts to its size (see [SoundContent] and [UsbContent]), so the minimum is just what its smallest
 * content needs: the Sound block shows only its volume slider at 2x1, and gains the mute button and the media keys as it
 * grows.
 */
enum class BlockId(val wire: String, private val default: Span, private val min: Span) {
    CLOCK("clock", Span(4, 2), Span(2, 1)),
    NOW_PLAYING("now_playing", Span(3, 2), Span(3, 2)),
    SOUND("sound", Span(3, 1), Span(2, 1)),
    BRIGHTNESS("brightness", Span(3, 1), Span(2, 1)),
    WIFI("wifi", Span(1, 1), Span(1, 1)),
    BLUETOOTH("bluetooth", Span(1, 1), Span(1, 1)),
    AIRPLANE("airplane", Span(1, 1), Span(1, 1)),
    USB("usb", Span(3, 1), Span(2, 1)),
    SETTINGS("settings", Span(1, 1), Span(1, 1)),
    DISCORD("discord", Span(1, 1), Span(1, 1)),
    SPOTIFY("spotify", Span(1, 1), Span(1, 1)),
    DOWNLOADS("downloads", Span(1, 1), Span(1, 1)),
    ;

    /** The Sound block starts taller when it carries the media keys, so they are visible by default. */
    fun defaultSize(soundKeys: Boolean = false): Span = if (this == SOUND && soundKeys) Span(3, 2) else default

    fun minSize(): Span = min

    /** [size] raised to this block's minimum (and held under the sanity cap); the grid's own width is applied by [BlockGrid.place]. */
    fun clamp(size: Span): Span = Span(size.cols.coerceIn(min.cols, MAX_CELLS), size.rows.coerceIn(min.rows, MAX_CELLS))

    /** [start] grown or shrunk by whole cells ([dCols], [dRows]) and kept above the minimum. */
    fun resized(start: Span, dCols: Int, dRows: Int): Span = clamp(Span(start.cols + dCols, start.rows + dRows))

    companion object {
        /** Not a limit anyone should meet: it only keeps a corrupt saved value from making a huge grid. */
        const val MAX_CELLS = 64

        val DEFAULT_ORDER: List<BlockId> = entries.toList()

        fun fromWire(value: String?): BlockId? = entries.firstOrNull { it.wire == value }
    }
}

/** How much of the Sound block is shown. */
enum class SoundMode { SLIDER_ONLY, WITH_MUTE, WITH_KEYS }

/** What the Sound block shows at a given size in cells: more as it grows. */
object SoundContent {
    /**
     * - 2x1 (and any smaller room): the volume slider alone;
     * - from 3 cells wide, or 2 tall: the header with the value, the mute button and the slider;
     * - 3x2 or more, when the media keys belong to this block: the full card, with the keys.
     */
    fun mode(cols: Int, rows: Int, mediaKeys: Boolean): SoundMode = when {
        mediaKeys && cols >= 3 && rows >= 2 -> SoundMode.WITH_KEYS
        cols >= 3 || rows >= 2 -> SoundMode.WITH_MUTE
        else -> SoundMode.SLIDER_ONLY
    }
}

/** How much of the USB block is shown. */
enum class UsbMode { COMPACT, FULL }

object UsbContent {
    /** Two cells wide: a compact chip (icon, name, eject). From three: the full chip (free space, open and eject). */
    fun mode(cols: Int): UsbMode = if (cols >= 3) UsbMode.FULL else UsbMode.COMPACT
}

/** Which blocks the PC currently gives something to show for (a hidden or absent block is simply not drawn). */
object ActionsBlocks {
    fun present(state: ActionsState): Set<BlockId> = buildSet {
        if (state.clock != null || state.battery != null) add(BlockId.CLOCK)
        if (ControlRules.hasSound(state)) add(BlockId.SOUND)
        if (state.nowPlaying != null) add(BlockId.NOW_PLAYING)
        if (state.brightness != null) add(BlockId.BRIGHTNESS)
        if (state.wifi != null) add(BlockId.WIFI)
        if (state.bluetooth != null) add(BlockId.BLUETOOTH)
        if (state.airplane != null) add(BlockId.AIRPLANE)
        if (state.usb.isNotEmpty()) add(BlockId.USB)
        state.launchers?.let { l ->
            if (l.settings) add(BlockId.SETTINGS)
            if (l.discord) add(BlockId.DISCORD)
            if (l.spotify) add(BlockId.SPOTIFY)
            if (l.downloads) add(BlockId.DOWNLOADS)
        }
    }
}

/** Where blocks sit on the grid (pure placement, no pixels). */
object BlockGrid {
    /** The grid is always this many rows tall (its cells are sized to fill the height). */
    const val ROWS = 6

    /** The square side of a cell and the number of columns that fit. */
    data class Metrics(val side: Float, val columns: Int)

    /**
     * Sizes the grid for an area [width] x [height] with [gap] between cells: [ROWS] rows fill the height exactly (the side
     * is rounded down to a whole unit so they never overflow), then as many columns as fit in the width, at least 2.
     */
    fun metrics(width: Float, height: Float, gap: Float): Metrics {
        val side = floor((height - gap * (ROWS - 1)) / ROWS).coerceAtLeast(1f)
        val columns = max(2, floor((width + gap) / (side + gap)).toInt())
        return Metrics(side, columns)
    }

    data class Placement(val id: BlockId, val col: Int, val row: Int, val cols: Int, val rows: Int) {
        val pos: CellPos get() = CellPos(col, row)
    }

    /** Number of rows the placements cover. */
    fun rowCount(placements: List<Placement>): Int = placements.maxOfOrNull { it.row + it.rows } ?: 0
}

/** A cell of the grid: column [x], row [y], counted from the top left. */
data class CellPos(val x: Int, val y: Int)

/**
 * Free placement on the grid: no gravity, a block stays on the exact cells it was put on, and gaps are fine.
 * Pure, in cells. A "free" rectangle is inside the [columns] x [rows] grid and overlaps no other block.
 */
object GridPlanner {
    private fun overlaps(a: BlockGrid.Placement, x: Int, y: Int, w: Int, h: Int) =
        x < a.col + a.cols && a.col < x + w && y < a.row + a.rows && a.row < y + h

    /** True when the rectangle is inside the grid and clear of every placement except [ignore]. */
    fun isFree(placements: List<BlockGrid.Placement>, ignore: BlockId?, x: Int, y: Int, w: Int, h: Int, columns: Int, rows: Int): Boolean {
        if (x < 0 || y < 0 || w < 1 || h < 1 || x + w > columns || y + h > rows) return false
        return placements.none { it.id != ignore && overlaps(it, x, y, w, h) }
    }

    /**
     * Where [id] lands when its top-left corner is dropped on cell ([x], [y]): that cell when its whole rectangle is free
     * (so it may overlap its own old place), otherwise null and the block springs back.
     */
    fun drop(placements: List<BlockGrid.Placement>, id: BlockId, x: Int, y: Int, columns: Int, rows: Int): CellPos? {
        val me = placements.firstOrNull { it.id == id } ?: return null
        return if (isFree(placements, id, x, y, me.cols, me.rows, columns, rows)) CellPos(x, y) else null
    }

    /**
     * The size [id] takes when the user asks for [wanted]: shrinking goes down to the block's minimum, growing only
     * takes free cells one by one (it stops at other blocks and at the edges of the grid), width first then height.
     */
    fun resize(placements: List<BlockGrid.Placement>, id: BlockId, wanted: Span, columns: Int, rows: Int): Span {
        val me = placements.firstOrNull { it.id == id } ?: return wanted
        val min = id.minSize()
        val targetW = wanted.cols.coerceAtLeast(min.cols)
        val targetH = wanted.rows.coerceAtLeast(min.rows)
        var w = me.cols
        var h = me.rows
        if (targetW < w) w = targetW.coerceAtLeast(minOf(min.cols, me.cols))
        if (targetH < h) h = targetH.coerceAtLeast(minOf(min.rows, me.rows))
        // A block pushed below the 6 rows may not grow further down.
        val bottom = maxOf(rows, me.row + me.rows)
        while (w < targetW && isFree(placements, id, me.col, me.row, w + 1, h, columns, bottom)) w++
        while (h < targetH && isFree(placements, id, me.col, me.row, w, h + 1, columns, bottom)) h++
        return Span(w, h)
    }

    /**
     * Resolves where each of [blocks] is drawn. [blocks] is in priority order (the saved order), [saved] holds the cells the
     * user put blocks on, [sizeOf] the size wanted for each.
     *
     * 1. A block whose saved cell is still in bounds and free is put there (in priority order, so of two that now collide
     *    the first keeps its place).
     * 2. Every other block (new, returning, repaired) takes the first free spot scanning the rows from the top and the columns
     *    from the left; failing that, the first free spot for its minimum size; failing that, the first spot below the
     *    [rows] rows, where the screen scrolls.
     *
     * Without any saved cell this is the plain dense packing of the order. A block wider than the grid is narrowed to it.
     */
    fun place(
        blocks: List<BlockId>,
        columns: Int,
        rows: Int,
        sizeOf: (BlockId) -> Span,
        saved: Map<BlockId, CellPos>,
    ): List<BlockGrid.Placement> {
        val width = columns.coerceAtLeast(1)
        val placed = ArrayList<BlockGrid.Placement>(blocks.size)
        fun narrow(size: Span) = Span(size.cols.coerceIn(1, width), size.rows.coerceAtLeast(1))
        fun firstFree(size: Span, id: BlockId, fromRow: Int, toRow: Int): BlockGrid.Placement? {
            for (y in fromRow..toRow - size.rows) {
                for (x in 0..width - size.cols) {
                    if (isFree(placed, null, x, y, size.cols, size.rows, width, toRow)) return BlockGrid.Placement(id, x, y, size.cols, size.rows)
                }
            }
            return null
        }
        val done = HashSet<BlockId>()
        for (id in blocks) {
            val pos = saved[id] ?: continue
            val size = narrow(sizeOf(id))
            // Saved places may sit below the 6 rows (the overflow), so the bottom is open here.
            if (pos.x >= 0 && pos.y >= 0 && pos.x + size.cols <= width &&
                placed.none { overlaps(it, pos.x, pos.y, size.cols, size.rows) }
            ) {
                placed += BlockGrid.Placement(id, pos.x, pos.y, size.cols, size.rows)
                done += id
            }
        }
        for (id in blocks) {
            if (id in done) continue
            val size = narrow(sizeOf(id))
            val min = narrow(id.minSize())
            val found = firstFree(size, id, 0, rows)
                ?: firstFree(Span(minOf(size.cols, min.cols), minOf(size.rows, min.rows)), id, 0, rows)
                ?: firstFree(size, id, rows, Int.MAX_VALUE / 4)
                ?: BlockGrid.Placement(id, 0, rows, size.cols, size.rows)
            placed += found
        }
        // In the order they were asked for.
        val byId = placed.associateBy { it.id }
        return blocks.mapNotNull { byId[it] }
    }
}
