package com.orizonx.client.keyboard

import kotlin.math.max
import kotlin.math.min

/**
 * Sizes of the on-screen keyboard. The grid is [COLUMNS] units wide and one unit per row; a key of width `w` covers `w`
 * units of pitch and is drawn inset by half the gap on each side, so a 1-unit key is exactly square and wider keys keep
 * their relative width at the same height. Units are whatever the caller measures in (dp or px).
 */
object KeyboardGeometry {
    const val COLUMNS = KeyLayouts.ROW_WIDTH

    /**
     * Side of one grid unit that makes [columns] x [rows] units fit in [width] x [height] after taking [margin] off every
     * edge: the smaller of the two fits, 0 when nothing fits.
     */
    fun unit(width: Float, height: Float, columns: Float = COLUMNS, rows: Int, margin: Float = 0f): Float {
        if (columns <= 0f || rows <= 0) return 0f
        val byWidth = (width - 2f * margin) / columns
        val byHeight = (height - 2f * margin) / rows
        return max(0f, min(byWidth, byHeight))
    }

    /** Drawn width of a key [widthUnits] wide on a grid of [unit], leaving [gap] between neighbours. */
    fun keyWidth(widthUnits: Float, unit: Float, gap: Float): Float = max(0f, widthUnits * unit - gap)

    /** Drawn height of a key: one unit less the gap, so a 1-unit key is square. */
    fun keyHeight(unit: Float, gap: Float): Float = max(0f, unit - gap)

    fun blockWidth(unit: Float, columns: Float = COLUMNS): Float = unit * columns

    fun blockHeight(unit: Float, rows: Int): Float = unit * rows
}
