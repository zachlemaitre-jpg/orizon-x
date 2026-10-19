package com.orizonx.client.actions

import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

class ImageLruTest {
    @Test
    fun defaultCapacityIsSixteen() {
        assertEquals(16, ImageLru<String>().capacity)
    }

    @Test
    fun insertAndGet() {
        val lru = ImageLru<String>(3)
        lru.put("a", "A")
        lru.put("b", "B")
        assertEquals("A", lru["a"])
        assertEquals("B", lru["b"])
        assertNull(lru["missing"])
        assertEquals(2, lru.size)
    }

    @Test
    fun evictsTheOldestInsertionFirst() {
        val lru = ImageLru<String>(3)
        for (id in listOf("a", "b", "c", "d")) lru.put(id, id.uppercase())
        assertNull(lru["a"])
        assertEquals(listOf("b", "c", "d"), lru.keys())
        lru.put("e", "E")
        assertEquals(listOf("c", "d", "e"), lru.keys())
        assertEquals(3, lru.size)
    }

    @Test
    fun getRefreshesRecency() {
        val lru = ImageLru<String>(3)
        lru.put("a", "A")
        lru.put("b", "B")
        lru.put("c", "C")
        assertEquals("A", lru["a"]) // a is now the most recent, b the oldest
        lru.put("d", "D")
        assertNull(lru["b"])
        assertEquals(listOf("c", "a", "d"), lru.keys())
    }

    @Test
    fun putOfAnExistingIdReplacesAndRefreshes() {
        val lru = ImageLru<String>(2)
        lru.put("a", "A1")
        lru.put("b", "B")
        lru.put("a", "A2")
        lru.put("c", "C")
        assertNull(lru["b"])
        assertEquals("A2", lru["a"])
    }

    @Test
    fun keysAndSnapshotDoNotChangeTheOrder() {
        val lru = ImageLru<String>(3)
        lru.put("a", "A")
        lru.put("b", "B")
        lru.keys()
        val snap = lru.snapshot()
        assertEquals(mapOf("a" to "A", "b" to "B"), snap)
        assertEquals(listOf("a", "b"), lru.keys())
        lru.put("c", "C")
        assertEquals("snapshot is a copy", 2, snap.size)
    }

    @Test
    fun coverAndIconShareTheSameCache() {
        val lru = ImageLru<String>()
        lru.put("cover-sha", "cover")
        lru.put("icon-sha", "icon")
        assertEquals("cover", lru["cover-sha"])
        assertEquals("icon", lru["icon-sha"])
    }

    @Test
    fun pinnedIdsAreNeverEvicted() {
        // The icon of the app in front stays while many covers arrive (Spotify in front for 16+ songs).
        val lru = ImageLru<String>(3)
        lru.put("icon", "I")
        for (id in listOf("c1", "c2", "c3", "c4")) lru.put(id, id, pinned = setOf("icon", id))
        assertEquals(listOf("icon", "c3", "c4"), lru.keys())
        assertEquals("I", lru["icon"])
    }

    @Test
    fun goesOverCapacityOnlyWhenEverythingIsPinned() {
        val lru = ImageLru<String>(2)
        lru.put("a", "A")
        lru.put("b", "B")
        lru.put("c", "C", pinned = setOf("a", "b", "c"))
        assertEquals(3, lru.size)
        lru.put("d", "D")
        assertEquals(listOf("c", "d"), lru.keys())
    }

    @Test
    fun clearEmptiesIt() {
        val lru = ImageLru<String>(2)
        lru.put("a", "A")
        lru.clear()
        assertEquals(0, lru.size)
        assertTrue(lru.keys().isEmpty())
    }
}
