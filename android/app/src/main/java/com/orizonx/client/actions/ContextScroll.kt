package com.orizonx.client.actions

/** Scroll positions for the scrolling (browser tabs) page of the context bar. */
object ContextScroll {
    /**
     * Scroll offset in pixels that brings the key at [activeIndex] to the middle of a viewport [viewportPx] wide,
     * when every key is [keyPx] wide. Never negative; 0 when there is no active key or no viewport yet.
     * The scroll state clamps the end of the range itself.
     */
    fun target(activeIndex: Int, keyPx: Int, viewportPx: Int): Int {
        if (activeIndex < 0 || viewportPx <= 0) return 0
        return (activeIndex * keyPx + keyPx / 2 - viewportPx / 2).coerceAtLeast(0)
    }
}
