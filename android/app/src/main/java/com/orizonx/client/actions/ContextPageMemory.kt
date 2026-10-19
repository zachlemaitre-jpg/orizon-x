package com.orizonx.client.actions

/**
 * Page chosen by the user for each context profile, kept in memory for the session: coming back to an app
 * (or to a profile whose page list changed) shows the page it was left on, and page 1 when that page is gone.
 */
class ContextPageMemory {
    private val byProfile = HashMap<String, String>()

    fun select(profile: String, pageId: String) {
        byProfile[profile] = pageId
    }

    /** The remembered page of [bar]'s profile when [bar] still has it, else its first page. */
    fun current(bar: ContextBar): ContextPage =
        byProfile[bar.profile]?.let { id -> bar.pages.firstOrNull { it.id == id } } ?: bar.pages.first()

    /** The page [offset] positions after (positive) or before (negative) the current one; null past either end. */
    fun neighbour(bar: ContextBar, offset: Int): ContextPage? {
        val index = bar.pages.indexOf(current(bar)) + offset
        return bar.pages.getOrNull(index)
    }
}
