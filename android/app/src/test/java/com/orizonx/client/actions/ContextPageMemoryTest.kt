package com.orizonx.client.actions

import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Test

class ContextPageMemoryTest {
    private fun page(id: String) = ContextPage(id, id.uppercase(), listOf(ContextButton("$id.1", "copy", id)))

    private fun bar(profile: String, vararg pageIds: String) =
        ContextBar("App", profile, emptyList(), pageIds.map { page(it) })

    @Test
    fun defaultsToPageOne() {
        val memory = ContextPageMemory()
        assertEquals("tools", memory.current(bar("illustrator", "tools", "edit", "view")).id)
    }

    @Test
    fun pageIsRememberedAcrossProfileSwitches() {
        val memory = ContextPageMemory()
        val illustrator = bar("illustrator", "tools", "edit", "view")
        val photoshop = bar("photoshop", "tools", "edit", "view")
        memory.select("illustrator", "view")
        memory.select("photoshop", "edit")
        assertEquals("view", memory.current(illustrator).id)
        assertEquals("edit", memory.current(photoshop).id)
        // Back to an app without a remembered page: page 1.
        assertEquals("main", memory.current(bar("browser", "main")).id)
        // Still there after the detour.
        assertEquals("view", memory.current(illustrator).id)
    }

    @Test
    fun unknownPageIdFallsBackToPageOne() {
        val memory = ContextPageMemory()
        memory.select("illustrator", "gone")
        assertEquals("tools", memory.current(bar("illustrator", "tools", "edit")).id)
    }

    @Test
    fun neighbourMovesWithoutWrapping() {
        val memory = ContextPageMemory()
        val b = bar("illustrator", "tools", "edit", "view")
        assertNull(memory.neighbour(b, -1))
        assertEquals("edit", memory.neighbour(b, +1)!!.id)
        memory.select("illustrator", "view")
        assertNull(memory.neighbour(b, +1))
        assertEquals("edit", memory.neighbour(b, -1)!!.id)
    }
}
