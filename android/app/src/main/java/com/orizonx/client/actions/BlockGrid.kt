package com.orizonx.client.actions

import kotlin.math.min

/** Size of a block in grid cells. */
data class Span(val cols: Int, val rows: Int)

/**
 * The blocks of the Actions main screen. Each has a stable [wire] id (kept in the saved layout) and a fixed size, wide
 * on a 4-column grid (landscape tablet) and narrow on a 2-column one (portrait or phone). The enum order is the
 * default order.
 */
enum class BlockId(val wire: String, private val wide: Span, private val narrow: Span) {
    CLOCK("clock", Span(4, 1), Span(2, 1)),
    NOW_PLAYING("now_playing", Span(2, 2), Span(2, 2)),
    SOUND("sound", Span(2, 1), Span(2, 1)),
    BRIGHTNESS("brightness", Span(2, 1), Span(2, 1)),
    WIFI("wifi", Span(1, 1), Span(1, 1)),
    BLUETOOTH("bluetooth", Span(1, 1), Span(1, 1)),
    AIRPLANE("airplane", Span(1, 1), Span(1, 1)),
    USB("usb", Span(2, 1), Span(2, 1)),
    ;

    /** The size on a grid of [columns] columns. */
    fun span(columns: Int): Span = if (columns >= WIDE_GRID_COLUMNS) wide else narrow

    companion object {
        const val WIDE_GRID_COLUMNS = 4

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
    data class Placement(val id: BlockId, val col: Int, val row: Int, val cols: Int, val rows: Int)

    /**
     * Places [blocks], in the given order, on a grid [columns] wide: each takes the first free spot scanning the rows from
     * the top and the columns from the left, so a small block can fill a hole left higher up. A block wider than the grid
     * is narrowed to it.
     */
    fun place(blocks: List<BlockId>, columns: Int): List<Placement> {
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
            val span = block.span(width)
            val w = min(span.cols, width)
            val h = span.rows
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

    /** Number of rows the placements cover. */
    fun rowCount(placements: List<Placement>): Int = placements.maxOfOrNull { it.row + it.rows } ?: 0
}
