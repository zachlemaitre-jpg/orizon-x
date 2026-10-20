package com.orizonx.client.actions

import android.content.SharedPreferences
import org.json.JSONArray
import org.json.JSONObject

/**
 * The user's arrangement of the Actions blocks: the [order] of every block (present or not, hidden or not) and which
 * ones are [hidden]. A block that is absent keeps its place in the order, and a restored one comes back to its place.
 */
data class ActionsLayout(
    val order: List<BlockId> = BlockId.DEFAULT_ORDER,
    val hidden: Set<BlockId> = emptySet(),
    /** Sizes the user chose, in cells; a block without an entry has its default size. */
    val sizes: Map<BlockId, Span> = emptyMap(),
) {
    /**
     * The size to draw [id] at on a grid [columns] wide: the chosen (or default) size, kept within the block's minimum
     * and maximum, then narrowed to the grid's width. [soundKeys] is true while the Sound block carries the media keys.
     */
    fun sizeOf(id: BlockId, columns: Int, soundKeys: Boolean = false): Span {
        val size = id.clamp(sizes[id] ?: id.defaultSize(soundKeys), soundKeys)
        return Span(size.cols.coerceAtMost(columns.coerceAtLeast(1)), size.rows)
    }

    /** Gives [id] the size [size] (kept within its limits), for every grid width. */
    fun resize(id: BlockId, size: Span, soundKeys: Boolean = false): ActionsLayout =
        copy(sizes = sizes + (id to id.clamp(size, soundKeys)))

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

    /** [id] goes to the end of the order (dropped below the last row). */
    fun moveToEnd(id: BlockId): ActionsLayout =
        if (id !in order || order.last() == id) this else copy(order = (order - id) + id)

    fun hide(id: BlockId): ActionsLayout = copy(hidden = hidden + id)

    /** The block is drawn again where it was in the order. */
    fun restore(id: BlockId): ActionsLayout = copy(hidden = hidden - id)

    /** The hidden blocks in order, for the "+ Add" list. */
    fun hiddenInOrder(): List<BlockId> = order.filter { it in hidden }

    fun toJson(): String = JSONObject()
        .put("order", JSONArray(order.map { it.wire }))
        .put("hidden", JSONArray(hiddenInOrder().map { it.wire }))
        .put("sizes", sizesJson())
        .toString()

    private fun sizesJson(): JSONObject {
        val out = JSONObject()
        for (id in BlockId.entries) sizes[id]?.let { out.put(id.wire, JSONArray(listOf(it.cols, it.rows))) }
        return out
    }

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
            return ActionsLayout(order, ids(json.optJSONArray("hidden")).toSet(), sizes(json.optJSONObject("sizes")))
        }

        /** `{"id":[w,h]}`: unknown ids and anything but two positive whole numbers are dropped; the rest is kept within the limits. */
        private fun sizes(json: JSONObject?): Map<BlockId, Span> {
            if (json == null) return emptyMap()
            val out = LinkedHashMap<BlockId, Span>()
            for (key in json.keys()) {
                val id = BlockId.fromWire(key) ?: continue
                val pair = json.optJSONArray(key) ?: continue
                if (pair.length() != 2) continue
                val w = (pair.opt(0) as? Number)?.toInt() ?: continue
                val h = (pair.opt(1) as? Number)?.toInt() ?: continue
                if (w < 1 || h < 1) continue
                out[id] = id.clamp(Span(w, h))
            }
            return out
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
