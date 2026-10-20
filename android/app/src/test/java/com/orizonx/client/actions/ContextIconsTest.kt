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
    fun specListHasOneHundredTwentyThreeNames() {
        // 38 from the first bar + 36 creative-tool names + 42 for Premiere Pro, After Effects, InDesign and Lightroom + `tab` for the browser tabs page + 6 for the AI chat profiles.
        assertEquals(123, ContextIcons.NAMES.size)
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

    @Test
    fun tabIconIsMappedAndDistinctFromTabNewAndTabClose() {
        assertTrue("tab" in ContextIcons.NAMES)
        val tab = ContextIcons.drawable("tab")
        assertNotEquals(R.drawable.ctx_unknown, tab)
        assertNotEquals(ContextIcons.drawable("tab_new"), tab)
        assertNotEquals(ContextIcons.drawable("tab_close"), tab)
    }

    @Test
    fun everyAiChatProfileNameIsMapped() {
        val names = listOf("chat_new", "sidebar", "copy_reply", "copy_code", "input_focus", "stop")
        for (name in names) {
            assertTrue("$name missing from NAMES", name in ContextIcons.NAMES)
            assertNotEquals("$name maps to the dot", R.drawable.ctx_unknown, ContextIcons.drawable(name))
        }
        // Their own files, not shared with the older copy or comment icons.
        assertNotEquals(ContextIcons.drawable("copy"), ContextIcons.drawable("copy_reply"))
        assertNotEquals(ContextIcons.drawable("comment"), ContextIcons.drawable("chat_new"))
    }

    @Test
    fun everyVideoPhotoAndLayoutToolNameIsMapped() {
        val names = listOf(
            "track_select", "ripple_edit", "razor", "slip", "add_edit", "ripple_delete", "mark_in", "mark_out", "export",
            "frame_prev", "frame_next", "edit_prev", "edit_next", "timeline_fit",
            "rotate", "anchor", "split_layer", "precompose", "solid", "keyframes", "go_start", "go_end",
            "keyframe_prev", "keyframe_next", "render",
            "rect_frame", "place", "preview", "grid", "loupe", "develop", "compare", "spot", "pick", "reject", "unflag",
            "star", "auto", "copy_settings", "paste_settings", "before_after", "fullscreen",
        )
        assertEquals(42, names.size)
        for (name in names) {
            assertTrue("$name missing from NAMES", name in ContextIcons.NAMES)
            assertNotEquals("$name maps to the dot", R.drawable.ctx_unknown, ContextIcons.drawable(name))
        }
    }
}
