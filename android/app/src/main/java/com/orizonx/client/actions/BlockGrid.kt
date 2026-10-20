package com.orizonx.client.actions

import kotlin.math.min

/** Size of a block in grid cells. */
data class Span(val cols: Int, val rows: Int)

/**
 * The blocks of the Actions main screen. Each has a stable [wire] id (kept in the saved layout) and a size in square
 * grid cells: a default one, and a minimum and maximum the user can resize between (the cells are about 120 dp, and the
 * minimum is what the block's content needs without clipping). The enum order is the default order.
 *
 * The Sound block needs more room when it carries the media keys (no "now playing" block), hence the `soundKeys` flag.
 */
enum class BlockId(val wire: String, private val default: Span, private val min: Span, private val max: Span) {
    CLOCK("clock", Span(4, 2), Span(2, 1), Span(8, 3)),
    NOW_PLAYING("now_playing", Span(3, 2), Span(3, 2), Span(6, 4)),
    SOUND("sound", Span(3, 1), Span(2, 1), Span(6, 2)),
    BRIGHTNESS("brightness", Span(3, 1), Span(2, 1), Span(6, 2)),
    WIFI("wifi", Span(1, 1), Span(1, 1), Span(2, 2)),
    BLUETOOTH("bluetooth", Span(1, 1), Span(1, 1), Span(2, 2)),
    AIRPLANE("airplane", Span(1, 1), Span(1, 1), Span(2, 2)),
    USB("usb", Span(3, 1), Span(3, 1), Span(6, 3)),
    ;

    fun defaultSize(soundKeys: Boolean = false): Span = if (this == SOUND && soundKeys) SOUND_WITH_KEYS else default

    fun minSize(soundKeys: Boolean = false): Span = if (this == SOUND && soundKeys) SOUND_WITH_KEYS else min

    fun maxSize(soundKeys: Boolean = false): Span = if (this == SOUND && soundKeys) Span(6, 3) else max

    /** [size] kept between this block's minimum and maximum (the grid's own width is applied by [BlockGrid.place]). */
    fun clamp(size: Span, soundKeys: Boolean = false): Span {
        val lo = minSize(soundKeys)
        val hi = maxSize(soundKeys)
        return Span(size.cols.coerceIn(lo.cols, hi.cols), size.rows.coerceIn(lo.rows, hi.rows))
    }

    /** [start] grown or shrunk by whole cells ([dCols], [dRows]) and kept within the limits. */
    fun resized(start: Span, dCols: Int, dRows: Int, soundKeys: Boolean = false): Span =
        clamp(Span(start.cols + dCols, start.rows + dRows), soundKeys)

    companion object {
        private val SOUND_WITH_KEYS = Span(3, 2)

        val DEFAULT_ORDER: List<BlockId> = entries.toList()

        fun fromWire(value: String?): BlockId? = entries.firstOrNull { it.wire == value }
    }
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
    }
}

/** Where blocks sit on the grid (pure placement, no pixels). */
object BlockGrid {
    /** Side of a grid cell the screen aims for, in dp: about the size of the old Wi-Fi tile. */
    const val TARGET_CELL_DP = 120f

    data class Placement(val id: BlockId, val col: Int, val row: Int, val cols: Int, val rows: Int)

    /**
     * Places [blocks], in the given order, on a grid [columns] wide: each takes the first free spot scanning the rows from
     * the top and the columns from the left, so a small block can fill a hole left higher up. [sizeOf] gives each block's
     * size in cells; a block wider than the grid is narrowed to it.
     */
    fun place(blocks: List<BlockId>, columns: Int, sizeOf: (BlockId) -> Span = { it.defaultSize() }): List<Placement> {
        val width = columns.coerceAtLeast(1)
        val used = ArrayList<BooleanArray>()
        fun row(r: Int): BooleanArray {
            while (used.size <= r) used += BooleanArray(width)
            return used[r]
        }
        fun fits(col: Int, r: Int, w: Int, h: Int): Boolean {
            for (y in r until r + h) for (x in col until col + w) if (row(y)[x]) return false
            return true
        }
        val out = ArrayList<Placement>(blocks.size)
        for (block in blocks) {
            val span = sizeOf(block)
            val w = min(span.cols.coerceAtLeast(1), width)
            val h = span.rows.coerceAtLeast(1)
            var r = 0
            search@ while (true) {
                for (c in 0..width - w) {
                    if (fits(c, r, w, h)) {
                        for (y in r until r + h) for (x in c until c + w) row(y)[x] = true
                        out += Placement(block, c, r, w, h)
                        break@search
                    }
                }
                r++
            }
        }
        return out
    }

    /** Columns of the grid for [widthDp]: cells of about [TARGET_CELL_DP], at least 2 columns. */
    fun columnsFor(widthDp: Float): Int = maxOf(2, (widthDp / TARGET_CELL_DP).toInt())

    /** Number of rows the placements cover. */
    fun rowCount(placements: List<Placement>): Int = placements.maxOfOrNull { it.row + it.rows } ?: 0
}
