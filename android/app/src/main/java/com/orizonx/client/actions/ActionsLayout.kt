package com.orizonx.client.actions

import android.content.SharedPreferences
import org.json.JSONArray
import org.json.JSONObject

/**
 * The user's arrangement of the Actions blocks: the [order] of every block (present or not, hidden or not) and which
 * ones are [hidden]. A block that is absent keeps its place in the order, and a restored one comes back to its place.
 */
data class ActionsLayout(val order: List<BlockId> = BlockId.DEFAULT_ORDER, val hidden: Set<BlockId> = emptySet()) {
    /** The blocks to draw, in order: not hidden and in [present]. */
    fun visible(present: Set<BlockId>): List<BlockId> = order.filter { it in present && it !in hidden }

    /**
     * [dragged] takes the place of [target]: it leaves the order and is inserted at the position [target] had, so the
     * blocks in between shift by one. Dropping a block on itself, or on an unknown one, changes nothing.
     */
    fun move(dragged: BlockId, target: BlockId): ActionsLayout {
        if (dragged == target) return this
        val to = order.indexOf(target)
        if (to < 0 || dragged !in order) return this
        val without = order - dragged
        return copy(order = without.take(to) + dragged + without.drop(to))
    }

    fun hide(id: BlockId): ActionsLayout = copy(hidden = hidden + id)

    /** The block is drawn again where it was in the order. */
    fun restore(id: BlockId): ActionsLayout = copy(hidden = hidden - id)

    /** The hidden blocks in order, for the "+ Add" list. */
    fun hiddenInOrder(): List<BlockId> = order.filter { it in hidden }

    fun toJson(): String = JSONObject()
        .put("order", JSONArray(order.map { it.wire }))
        .put("hidden", JSONArray(hiddenInOrder().map { it.wire }))
        .toString()

    companion object {
        val DEFAULT = ActionsLayout()

        /**
         * Tolerant reading: unknown ids are dropped, repeated ones counted once, a known block missing from the saved
         * order (added by a later version) goes at the end, and anything unreadable gives [DEFAULT].
         */
        fun fromJson(text: String?): ActionsLayout {
            if (text.isNullOrBlank()) return DEFAULT
            val json = try {
                JSONObject(text)
            } catch (_: Exception) {
                return DEFAULT
            }
            val saved = ids(json.optJSONArray("order")).distinct()
            val order = saved + BlockId.DEFAULT_ORDER.filter { it !in saved }
            return ActionsLayout(order, ids(json.optJSONArray("hidden")).toSet())
        }

        private fun ids(array: JSONArray?): List<BlockId> =
            if (array == null) emptyList() else (0 until array.length()).mapNotNull { BlockId.fromWire(array.opt(it) as? String) }
    }
}

/** Keeps the [ActionsLayout] in the app's SharedPreferences, saved at every change. */
class ActionsLayoutStore(private val prefs: SharedPreferences) {
    fun load(): ActionsLayout = ActionsLayout.fromJson(prefs.getString(KEY, null))

    fun save(layout: ActionsLayout) {
        prefs.edit().putString(KEY, layout.toJson()).apply()
    }

    private companion object {
        const val KEY = "actions_layout"
    }
}
