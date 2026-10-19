package com.orizonx.client.keyboard

import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

class KeyboardGeometryTest {
    @Test
    fun wideScreenIsLimitedByHeight() {
        // 1000 / 18.25 = 54.8 would fit the width, but 300 / 6 = 50 is all the height allows.
        assertEquals(50f, KeyboardGeometry.unit(1000f, 300f, columns = 18.25f, rows = 6), 0.001f)
    }

    @Test
    fun tallScreenIsLimitedByWidth() {
        assertEquals(1000f / 18.25f, KeyboardGeometry.unit(1000f, 900f, columns = 18.25f, rows = 6), 0.001f)
    }

    @Test
    fun landscapeTabletIsWidthLimited() {
        // 1440 x 900 dp, 76 dp context bar and 40 dp close row above, 6 dp of margin on each side.
        val unit = KeyboardGeometry.unit(1440f, 900f - 76f - 8f - 40f, columns = 18.25f, rows = 6, margin = 6f)
        assertEquals((1440f - 12f) / 18.25f, unit, 0.001f)
        assertTrue(unit in 78f..79f)
    }

    @Test
    fun marginsAreTakenOffBothAxes() {
        assertEquals((200f - 20f) / 10f, KeyboardGeometry.unit(200f, 10_000f, columns = 10f, rows = 5, margin = 10f), 0.001f)
        assertEquals((400f - 20f) / 5f, KeyboardGeometry.unit(10_000f, 400f, columns = 10f, rows = 5, margin = 10f), 0.001f)
    }

    @Test
    fun nothingFitsGivesZero() {
        assertEquals(0f, KeyboardGeometry.unit(10f, 500f, columns = 18.25f, rows = 6, margin = 6f), 0f)
        assertEquals(0f, KeyboardGeometry.unit(-5f, -5f, columns = 18.25f, rows = 6), 0f)
        assertEquals(0f, KeyboardGeometry.unit(100f, 100f, columns = 0f, rows = 6), 0f)
        assertEquals(0f, KeyboardGeometry.unit(100f, 100f, columns = 10f, rows = 0), 0f)
    }

    @Test
    fun oneUnitKeyIsSquareAndWideKeysKeepTheirRelativeWidth() {
        val unit = 70f
        val gap = 4f
        val one = KeyboardGeometry.keyWidth(1f, unit, gap)
        assertEquals(unit - gap, one, 0f)
        assertEquals(KeyboardGeometry.keyHeight(unit, gap), one, 0f) // square
        // A key of width w covers w units of pitch, so the neighbours stay aligned with the grid.
        assertEquals(2f * unit - gap, KeyboardGeometry.keyWidth(2f, unit, gap), 0f)
        assertEquals(6f * unit - gap, KeyboardGeometry.keyWidth(6f, unit, gap), 0f)
        assertEquals(1.5f * unit - gap, KeyboardGeometry.keyWidth(1.5f, unit, gap), 0f)
    }

    @Test
    fun blockSizeKeepsTheLayoutProportions() {
        assertEquals(18.25f * 70f, KeyboardGeometry.blockWidth(70f, 18.25f), 0.001f)
        assertEquals(6f * 70f, KeyboardGeometry.blockHeight(70f, 6), 0.001f)
    }

    @Test
    fun everyLayoutRowCountFitsTheGeometryDefaults() {
        for (id in KeyboardLayoutId.entries) {
            val layout = KeyLayouts.of(id)
            assertEquals(KeyLayouts.ROW_WIDTH, KeyboardGeometry.COLUMNS, 0f)
            assertEquals(6, layout.rows.size)
        }
    }
}
