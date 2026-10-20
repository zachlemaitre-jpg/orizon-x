package com.orizonx.client.actions

import android.content.SharedPreferences
import org.json.JSONArray
import org.json.JSONObject

/** The screen's orientation: the grid has a different number of columns, so each keeps its own block positions. */
enum class GridOrientation(val wire: String) {
    LANDSCAPE("landscape"),
    PORTRAIT("portrait"),
    ;

    companion object {
        fun of(landscape: Boolean) = if (landscape) LANDSCAPE else PORTRAIT
    }
}

/**
 * The user's arrangement of the Actions blocks: which ones are [hidden], their [sizes], and the cell each was put on
 * ([positions], per orientation). The [order] lists every block (present or not, hidden or not) and is the priority when
 * positions have to be (re)found: a block without a usable saved cell takes the first free spot, in that order.
 */
data class ActionsLayout(
    val order: List<BlockId> = BlockId.DEFAULT_ORDER,
    val hidden: Set<BlockId> = emptySet(),
    /** Sizes the user chose, in cells; a block without an entry has its default size. */
    val sizes: Map<BlockId, Span> = emptyMap(),
    /** The cell (top-left corner) of each block the user placed, per orientation; a block without one is placed automatically. */
    val positions: Map<GridOrientation, Map<BlockId, CellPos>> = emptyMap(),
) {
    /**
     * The size to draw [id] at on a grid [columns] wide: the chosen (or default) size, raised to the block's minimum, then
     * narrowed to the grid's width (there is no other maximum). [soundKeys] is true while the Sound block carries the media keys.
     */
    fun sizeOf(id: BlockId, columns: Int, soundKeys: Boolean = false): Span {
        val size = id.clamp(sizes[id] ?: id.defaultSize(soundKeys))
        return Span(size.cols.coerceAtMost(columns.coerceAtLeast(1)), size.rows)
    }

    /** Gives [id] the size [size] (raised to its minimum), for every grid width. */
    fun resize(id: BlockId, size: Span): ActionsLayout = copy(sizes = sizes + (id to id.clamp(size)))

    /** The blocks to draw, in order: not hidden and in [present]. */
    fun visible(present: Set<BlockId>): List<BlockId> = order.filter { it in present && it !in hidden }

    fun hide(id: BlockId): ActionsLayout = copy(hidden = hidden + id)

    /** The block is drawn again, on its saved cell if that is still free, else on the first free spot. */
    fun restore(id: BlockId): ActionsLayout = copy(hidden = hidden - id)

    /** The saved cells for [orientation]. */
    fun positionsFor(orientation: GridOrientation): Map<BlockId, CellPos> = positions[orientation] ?: emptyMap()

    /**
     * Remembers where [placements] are for [orientation] (blocks hidden or absent at the moment keep the cell they had), so
     * that nothing moves by itself afterwards.
     */
    fun withPlacements(orientation: GridOrientation, placements: List<BlockGrid.Placement>): ActionsLayout =
        copy(positions = positions + (orientation to (positionsFor(orientation) + placements.associate { it.id to it.pos })))

    /** The hidden blocks in order, for the "+ Add" list. */
    fun hiddenInOrder(): List<BlockId> = order.filter { it in hidden }

    fun toJson(): String = JSONObject()
        .put("order", JSONArray(order.map { it.wire }))
        .put("hidden", JSONArray(hiddenInOrder().map { it.wire }))
        .put("sizes", sizesJson())
        .put("pos", positionsJson())
        .toString()

    private fun positionsJson(): JSONObject {
        val out = JSONObject()
        for (orientation in GridOrientation.entries) {
            val map = positions[orientation] ?: continue
            val json = JSONObject()
            for (id in BlockId.entries) map[id]?.let { json.put(id.wire, JSONArray(listOf(it.x, it.y))) }
            out.put(orientation.wire, json)
        }
        return out
    }

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
            return ActionsLayout(order, ids(json.optJSONArray("hidden")).toSet(), sizes(json.optJSONObject("sizes")), positions(json.optJSONObject("pos")))
        }

        /** `{"landscape":{"id":[x,y]},"portrait":{…}}`: unknown ids, other orientations and anything but two whole numbers >= 0 are dropped. */
        private fun positions(json: JSONObject?): Map<GridOrientation, Map<BlockId, CellPos>> {
            if (json == null) return emptyMap()
            val out = LinkedHashMap<GridOrientation, Map<BlockId, CellPos>>()
            for (orientation in GridOrientation.entries) {
                val map = json.optJSONObject(orientation.wire) ?: continue
                val cells = LinkedHashMap<BlockId, CellPos>()
                for (key in map.keys()) {
                    val id = BlockId.fromWire(key) ?: continue
                    val pair = map.optJSONArray(key) ?: continue
                    if (pair.length() != 2) continue
                    val x = (pair.opt(0) as? Number)?.toInt() ?: continue
                    val y = (pair.opt(1) as? Number)?.toInt() ?: continue
                    if (x < 0 || y < 0) continue
                    cells[id] = CellPos(x, y)
                }
                out[orientation] = cells
            }
            return out
        }

        /** `{"id":[w,h]}`: unknown ids and anything but two positive whole numbers are dropped; the rest is raised to the block's minimum. */
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
