package com.orizonx.client.keyboard

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

class KeyLayoutsTest {
    private val azerty = KeyLayouts.of(KeyboardLayoutId.AZERTY)
    private val qwerty = KeyLayouts.of(KeyboardLayoutId.QWERTY)

    private fun ids(layout: KeyboardLayout) = layout.keys.map { it.id }

    @Test
    fun keysAreUniqueInEachLayout() {
        assertEquals(ids(azerty).size, ids(azerty).toSet().size)
        assertEquals(ids(qwerty).size, ids(qwerty).toSet().size)
    }

    @Test
    fun bothLayoutsCoverTheSamePositionsExceptTheIsoKey() {
        val iso = KeySpec(0x56, false, "").id
        assertTrue(iso in ids(azerty))
        assertFalse(iso in ids(qwerty))
        assertEquals(ids(azerty).toSet() - iso, ids(qwerty).toSet())
    }

    @Test
    fun everyRowHasTheSameWidth() {
        for (layout in listOf(azerty, qwerty)) {
            for ((i, row) in layout.rows.withIndex()) {
                assertEquals("${layout.id} row $i", KeyLayouts.ROW_WIDTH, row.sumOf { it.width.toDouble() }.toFloat(), 0.001f)
            }
        }
    }

    @Test
    fun scanCodesStayInTheProtocolRange() {
        for (key in azerty.keys + qwerty.keys) assertTrue("${key.base} ${key.sc}", key.sc in 1..127)
    }

    @Test
    fun extendedKeysAreTheNavigationWinMenuAltGrCtrlAndDel() {
        val extended = azerty.keys.filter { it.ext }.map { it.sc }.toSet()
        assertEquals(setOf(0x53, 0x5B, 0x38, 0x5D, 0x1D, 0x52, 0x47, 0x4F, 0x49, 0x51, 0x48, 0x4B, 0x50, 0x4D), extended)
    }

    @Test
    fun scanCodesOfTheSpecTable() {
        assertEquals("a", azerty.key(0x10, false)!!.base)
        assertEquals("q", qwerty.key(0x10, false)!!.base)
        assertEquals("à", azerty.key(0x0B, false)!!.base)
        assertEquals("@", azerty.key(0x0B, false)!!.altGr)
        assertEquals("0", azerty.key(0x0B, false)!!.shift)
        assertEquals(")", qwerty.key(0x0B, false)!!.shift)
        assertEquals("m", azerty.key(0x27, false)!!.base)
        assertEquals(";", qwerty.key(0x27, false)!!.base)
        assertEquals("<", azerty.key(0x56, false)!!.base)
        assertNull(qwerty.key(0x56, false))
        assertEquals("²", azerty.key(0x29, false)!!.base)
        assertEquals("¤", azerty.key(0x1B, false)!!.altGr)
        assertEquals("AltGr", azerty.key(0x38, true)!!.base)
        assertEquals("Alt", qwerty.key(0x38, true)!!.base)
        assertEquals(6f, azerty.key(0x39, false)!!.width, 0f)
        assertEquals(2f, azerty.key(0x0E, false)!!.width, 0f)
        assertEquals(1.25f, azerty.key(0x2A, false)!!.width, 0f)
        assertEquals(2.25f, qwerty.key(0x2A, false)!!.width, 0f)
        assertEquals(2.25f, qwerty.key(0x1C, false)!!.width, 0f)
    }

    @Test
    fun functionRowAndNavigationExist() {
        for (layout in listOf(azerty, qwerty)) {
            for (sc in (0x3B..0x44) + listOf(0x57, 0x58, 0x01)) assertNotNull(layout.key(sc, false))
            for (sc in listOf(0x53, 0x52, 0x47, 0x4F, 0x49, 0x51, 0x48, 0x4B, 0x50, 0x4D, 0x5B, 0x5D)) assertNotNull(layout.key(sc, true))
        }
    }

    @Test
    fun modifiersAreShiftCtrlAltWinAltGrAndNothingElse() {
        val mods = azerty.keys.filter { it.modifier }.map { it.id }.toSet()
        assertEquals(setOf(0x2A, 0x36, 0x1D, 0x11D, 0x38, 0x138, 0x15B), mods)
        assertFalse(azerty.key(0x3A, false)!!.modifier)
    }

    @Test
    fun layoutIdFromWire() {
        assertEquals(KeyboardLayoutId.AZERTY, KeyboardLayoutId.fromWire("azerty"))
        assertEquals(KeyboardLayoutId.QWERTY, KeyboardLayoutId.fromWire("qwerty"))
        assertEquals(KeyboardLayoutId.QWERTY, KeyboardLayoutId.fromWire("dvorak"))
        assertEquals(KeyboardLayoutId.QWERTY, KeyboardLayoutId.fromWire(null))
    }
}
