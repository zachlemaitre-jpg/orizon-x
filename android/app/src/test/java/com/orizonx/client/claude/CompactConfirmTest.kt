package com.orizonx.client.claude

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class CompactConfirmTest {
    private var now = 10_000L
    private val confirm = CompactConfirm(clock = { now })

    @Test
    fun theFirstTapOnlyArms() {
        assertFalse(confirm.isArmed())
        assertFalse(confirm.tap())
        assertTrue(confirm.isArmed())
    }

    @Test
    fun aSecondTapWithinThreeSecondsSends() {
        confirm.tap()
        now += 2_999
        assertTrue(confirm.isArmed())
        assertTrue(confirm.tap())
        assertFalse(confirm.isArmed()) // used up
    }

    @Test
    fun aSecondTapAfterThreeSecondsOnlyArmsAgain() {
        confirm.tap()
        now += 3_000
        assertFalse(confirm.isArmed())
        assertFalse(confirm.tap())
        assertTrue(confirm.isArmed())
        now += 100
        assertTrue(confirm.tap())
    }

    @Test
    fun afterSendingTheNextTapArmsAgain() {
        confirm.tap()
        assertTrue(confirm.tap())
        assertFalse(confirm.tap())
        assertTrue(confirm.isArmed())
    }

    @Test
    fun cancelDisarms() {
        confirm.tap()
        confirm.cancel()
        assertFalse(confirm.isArmed())
        assertFalse(confirm.tap())
    }

    @Test
    fun theWindowIsThreeSeconds() {
        assertEquals(3_000L, CompactConfirm.WINDOW_MS)
    }
}
