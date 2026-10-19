package com.orizonx.client.actions

import org.junit.Assert.assertEquals
import org.junit.Test

class ContextScrollTest {
    @Test
    fun activeTabIsCentredInTheViewport() {
        // 132 px keys, 500 px viewport: key 5 starts at 660 and is centred at 660 + 66 - 250 = 476 scroll offset.
        assertEquals(476, ContextScroll.target(activeIndex = 5, keyPx = 132, viewportPx = 500))
    }

    @Test
    fun firstTabsStayAtTheStart() {
        assertEquals(0, ContextScroll.target(0, 132, 500))
        assertEquals(0, ContextScroll.target(1, 132, 500))
    }

    @Test
    fun noActiveTabOrEmptyViewportScrollsToTheStart() {
        assertEquals(0, ContextScroll.target(-1, 132, 500))
        assertEquals(0, ContextScroll.target(3, 132, 0))
    }
}
