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
    fun specListHasSeventyFourNames() {
        // 38 from the first bar + 36 creative-tool names (the creative `comment` already existed).
        assertEquals(74, ContextIcons.NAMES.size)
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

    @Test
    fun everyCreativeToolNameIsMapped() {
        val creative = listOf(
            "select", "direct_select", "pen", "text", "rectangle", "ellipse", "line", "brush", "eraser", "eyedropper",
            "crop", "lasso", "marquee", "move", "frame", "comment",
            "group", "ungroup", "lock", "unlock", "layer_new", "layer_duplicate", "merge", "deselect", "transform",
            "component", "hide", "paste_front",
            "hand", "zoom_fit", "zoom_100", "zoom_selection", "outline", "rulers", "brush_smaller", "brush_larger", "present",
        )
        assertEquals(37, creative.size)
        for (name in creative) {
            assertTrue("$name missing from NAMES", name in ContextIcons.NAMES)
            assertNotEquals("$name maps to the dot", R.drawable.ctx_unknown, ContextIcons.drawable(name))
        }
    }
}
