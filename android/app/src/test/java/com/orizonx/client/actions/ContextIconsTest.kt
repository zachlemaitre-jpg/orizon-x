package com.orizonx.client.actions

import com.orizonx.client.R
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNotEquals
import org.junit.Assert.assertTrue
import org.junit.Test

class ContextIconsTest {
    @Test
    fun everyKnownNameHasItsOwnDrawable() {
        val ids = ContextIcons.NAMES.map { ContextIcons.drawable(it) }
        assertTrue(ids.none { it == R.drawable.ctx_unknown })
        assertEquals("two names share a drawable", ids.size, ids.toSet().size)
    }

    @Test
    fun specListHasThirtyEightNames() {
        assertEquals(38, ContextIcons.NAMES.size)
        assertEquals(ContextIcons.NAMES.size, ContextIcons.NAMES.toSet().size)
    }

    @Test
    fun unknownBlankOrMissingNameGivesTheDot() {
        assertEquals(R.drawable.ctx_unknown, ContextIcons.drawable("does_not_exist"))
        assertEquals(R.drawable.ctx_unknown, ContextIcons.drawable(""))
        assertEquals(R.drawable.ctx_unknown, ContextIcons.drawable(null))
    }

    @Test
    fun lookupIsCaseAndWhitespaceTolerant() {
        assertEquals(R.drawable.ctx_play_pause, ContextIcons.drawable("play_pause"))
        assertEquals(R.drawable.ctx_play_pause, ContextIcons.drawable(" Play_Pause "))
        assertNotEquals(R.drawable.ctx_unknown, ContextIcons.drawable("ARROW_LEFT"))
    }
}
