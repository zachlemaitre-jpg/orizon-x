package com.orizonx.client.actions

import android.content.SharedPreferences
import com.orizonx.client.actions.BlockId.AIRPLANE
import com.orizonx.client.actions.BlockId.BLUETOOTH
import com.orizonx.client.actions.BlockId.BRIGHTNESS
import com.orizonx.client.actions.BlockId.CLOCK
import com.orizonx.client.actions.BlockId.NOW_PLAYING
import com.orizonx.client.actions.BlockId.SOUND
import com.orizonx.client.actions.BlockId.USB
import com.orizonx.client.actions.BlockId.WIFI
import org.json.JSONObject
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

class ActionsLayoutTest {
    private fun layout(vararg order: BlockId, hidden: Set<BlockId> = emptySet()) = ActionsLayout(order.toList(), hidden)

    private val abcd = layout(CLOCK, SOUND, WIFI, USB)

    // --- Hiding and restoring ------------------------------------------------------------------------------------------

    @Test
    fun hidingRemovesFromViewButKeepsThePlace() {
        val hidden = abcd.hide(SOUND)
        assertEquals(abcd.order, hidden.order)
        assertEquals(listOf(CLOCK, WIFI, USB), hidden.visible(abcd.order.toSet()))
        assertEquals(listOf(SOUND), hidden.hiddenInOrder())
    }

    @Test
    fun aRestoredBlockComesBackToItsPlace() {
        val back = abcd.hide(SOUND).hide(WIFI).restore(SOUND)
        assertEquals(listOf(CLOCK, SOUND, USB), back.visible(abcd.order.toSet()))
        assertEquals(listOf(WIFI), back.hiddenInOrder())
        assertEquals(abcd, abcd.hide(SOUND).restore(SOUND))
    }

    @Test
    fun hiddenInOrderFollowsTheOrderNotTheHidingOrder() {
        val l = abcd.hide(USB).hide(CLOCK)
        assertEquals(listOf(CLOCK, USB), l.hiddenInOrder())
    }

    // --- Saving ---------------------------------------------------------------------------------------------------------------

    @Test
    fun roundTrip() {
        val l = ActionsLayout(listOf(USB, WIFI, CLOCK, SOUND, NOW_PLAYING, BRIGHTNESS, BLUETOOTH, AIRPLANE), setOf(WIFI, USB))
        assertEquals(l, ActionsLayout.fromJson(l.toJson()))
    }

    @Test
    fun theJsonHasTheDocumentedShape() {
        val json = JSONObject(ActionsLayout.DEFAULT.hide(USB).toJson())
        assertEquals("clock", json.getJSONArray("order").getString(0))
        assertEquals(8, json.getJSONArray("order").length())
        assertEquals("usb", json.getJSONArray("hidden").getString(0))
    }

    @Test
    fun unknownIdsAreDropped() {
        val l = ActionsLayout.fromJson("""{"order":["wifi","hologram",5,null,"clock"],"hidden":["usb","nope"]}""")
        assertEquals(listOf(WIFI, CLOCK), l.order.take(2))
        assertEquals(BlockId.entries.toSet(), l.order.toSet())
        assertEquals(setOf(USB), l.hidden)
    }

    @Test
    fun aNewBlockIsAddedAtTheEnd() {
        val l = ActionsLayout.fromJson("""{"order":["usb","clock","sound"],"hidden":[]}""")
        assertEquals(listOf(USB, CLOCK, SOUND), l.order.take(3))
        assertEquals(listOf(NOW_PLAYING, BRIGHTNESS, WIFI, BLUETOOTH, AIRPLANE), l.order.drop(3))
    }

    @Test
    fun repeatedIdsCountOnce() {
        val l = ActionsLayout.fromJson("""{"order":["wifi","wifi","clock","wifi"],"hidden":["usb","usb"]}""")
        assertEquals(1, l.order.count { it == WIFI })
        assertEquals(BlockId.entries.size, l.order.size)
    }

    @Test
    fun invalidOrMissingJsonGivesTheDefault() {
        assertEquals(ActionsLayout.DEFAULT, ActionsLayout.fromJson(null))
        assertEquals(ActionsLayout.DEFAULT, ActionsLayout.fromJson(""))
        assertEquals(ActionsLayout.DEFAULT, ActionsLayout.fromJson("   "))
        assertEquals(ActionsLayout.DEFAULT, ActionsLayout.fromJson("not json"))
        assertEquals(ActionsLayout.DEFAULT, ActionsLayout.fromJson("[1,2]"))
        assertEquals(ActionsLayout.DEFAULT, ActionsLayout.fromJson("""{"order":"clock"}"""))
        assertEquals(ActionsLayout.DEFAULT, ActionsLayout.fromJson("{}"))
    }

    // --- The store ---------------------------------------------------------------------------------------------------------------

    private class FakePrefs : SharedPreferences {
        val values = HashMap<String, String?>()

        override fun getString(key: String, defValue: String?): String? = values[key] ?: defValue

        override fun edit(): SharedPreferences.Editor = object : SharedPreferences.Editor {
            override fun putString(key: String, value: String?) = also { values[key] = value }
            override fun apply() = Unit
            override fun commit() = true
            override fun putStringSet(key: String, value: MutableSet<String>?) = this
            override fun putInt(key: String, value: Int) = this
            override fun putLong(key: String, value: Long) = this
            override fun putFloat(key: String, value: Float) = this
            override fun putBoolean(key: String, value: Boolean) = this
            override fun remove(key: String) = this
            override fun clear() = this
        }

        override fun getAll(): MutableMap<String, *> = HashMap<String, Any?>()
        override fun getStringSet(key: String, defValues: MutableSet<String>?): MutableSet<String>? = defValues
        override fun getInt(key: String, defValue: Int) = defValue
        override fun getLong(key: String, defValue: Long) = defValue
        override fun getFloat(key: String, defValue: Float) = defValue
        override fun getBoolean(key: String, defValue: Boolean) = defValue
        override fun contains(key: String) = values.containsKey(key)
        override fun registerOnSharedPreferenceChangeListener(listener: SharedPreferences.OnSharedPreferenceChangeListener) = Unit
        override fun unregisterOnSharedPreferenceChangeListener(listener: SharedPreferences.OnSharedPreferenceChangeListener) = Unit
    }

    @Test
    fun theStoreSavesUnderActionsLayout() {
        val prefs = FakePrefs()
        val store = ActionsLayoutStore(prefs)
        assertEquals(ActionsLayout.DEFAULT, store.load())
        val l = ActionsLayout.DEFAULT.resize(CLOCK, Span(6, 2)).withPlacements(GridOrientation.PORTRAIT, listOf(BlockGrid.Placement(USB, 0, 1, 3, 1))).hide(WIFI)
        store.save(l)
        assertEquals(l.toJson(), prefs.values["actions_layout"])
        assertEquals(l, ActionsLayoutStore(prefs).load())
    }

    @Test
    fun aCorruptStoredValueGivesTheDefault() {
        val prefs = FakePrefs()
        prefs.values["actions_layout"] = "{oops"
        assertEquals(ActionsLayout.DEFAULT, ActionsLayoutStore(prefs).load())
        assertNull(prefs.values["other"])
    }

    // --- Sizes ------------------------------------------------------------------------------------------------------------------

    @Test
    fun withoutAChoiceABlockHasItsDefaultSize() {
        assertEquals(Span(4, 2), ActionsLayout.DEFAULT.sizeOf(CLOCK, 11))
        assertEquals(Span(3, 1), ActionsLayout.DEFAULT.sizeOf(SOUND, 11))
        assertEquals(Span(3, 2), ActionsLayout.DEFAULT.sizeOf(SOUND, 11, soundKeys = true))
    }

    @Test
    fun aChosenSizeHasNoMaximumButTheMinimumAndTheColumns() {
        val l = ActionsLayout.DEFAULT.resize(BRIGHTNESS, Span(9, 5))
        assertEquals(Span(9, 5), l.sizeOf(BRIGHTNESS, 11))
        assertEquals(Span(2, 1), ActionsLayout.DEFAULT.resize(BRIGHTNESS, Span(0, -3)).sizeOf(BRIGHTNESS, 11)) // minimum
        assertEquals(Span(11, 30), ActionsLayout.DEFAULT.resize(BRIGHTNESS, Span(40, 30)).sizeOf(BRIGHTNESS, 11)) // columns only
    }

    @Test
    fun theSizeIsNarrowedToTheColumnCountAtLayoutTimeButKept() {
        val l = ActionsLayout.DEFAULT.resize(CLOCK, Span(8, 3))
        assertEquals(Span(8, 3), l.sizeOf(CLOCK, 11))
        assertEquals(Span(2, 3), l.sizeOf(CLOCK, 2))
        assertEquals(Span(7, 3), l.sizeOf(CLOCK, 7))
        assertEquals(Span(8, 3), l.sizes[CLOCK]) // the stored size is untouched by a narrower grid
    }

    @Test
    fun theSoundMinimumDoesNotChangeWithTheMediaKeys() {
        val small = ActionsLayout.DEFAULT.resize(SOUND, Span(2, 1))
        assertEquals(Span(2, 1), small.sizeOf(SOUND, 11))
        assertEquals(Span(2, 1), small.sizeOf(SOUND, 11, soundKeys = true))
        assertEquals(Span(2, 1), ActionsLayout.DEFAULT.resize(SOUND, Span(1, 1)).sizes[SOUND])
    }

    @Test
    fun resizingStepsCellByCellFromTheMinimumUp() {
        val start = Span(3, 1)
        assertEquals(Span(4, 2), BRIGHTNESS.resized(start, +1, +1))
        assertEquals(Span(2, 1), BRIGHTNESS.resized(start, -1, 0))
        assertEquals(Span(2, 1), BRIGHTNESS.resized(start, -5, -5)) // minimum
        assertEquals(Span(12, 10), BRIGHTNESS.resized(start, +9, +9)) // no maximum
        assertEquals(start, BRIGHTNESS.resized(start, 0, 0))
        assertEquals(Span(1, 1), WIFI.resized(Span(1, 1), -1, -1))
        assertEquals(Span(2, 2), WIFI.resized(Span(1, 1), +1, +1))
    }

    @Test
    fun sizesRoundTripThroughTheJson() {
        val l = ActionsLayout.DEFAULT.resize(CLOCK, Span(6, 2)).resize(WIFI, Span(2, 2)).hide(USB)
        val back = ActionsLayout.fromJson(l.toJson())
        assertEquals(l, back)
        val json = JSONObject(l.toJson()).getJSONObject("sizes")
        assertEquals(6, json.getJSONArray("clock").getInt(0))
        assertEquals(2, json.getJSONArray("wifi").getInt(1))
        assertEquals(2, json.length())
    }

    @Test
    fun oldJsonWithoutSizesGivesDefaults() {
        val l = ActionsLayout.fromJson("""{"order":["usb","clock"],"hidden":["wifi"]}""")
        assertTrue(l.sizes.isEmpty())
        assertEquals(CLOCK.defaultSize(), l.sizeOf(CLOCK, 11))
        assertTrue(ActionsLayout.fromJson("""{"order":[],"hidden":[],"sizes":null}""").sizes.isEmpty())
        assertTrue(ActionsLayout.fromJson("""{"sizes":[1,2]}""").sizes.isEmpty())
    }

    @Test
    fun badSizesAreDroppedAndSmallOnesRaisedToTheMinimum() {
        val l = ActionsLayout.fromJson(
            """{"sizes":{"clock":[20,30],"wifi":[0,1],"sound":[3],"usb":[3,2,1],"brightness":["a",1],"nope":[1,1],
                "bluetooth":[1.0,1],"airplane":[-4,2],"now_playing":[1,1]}}""",
        )
        assertEquals(Span(20, 30), l.sizes[CLOCK]) // no maximum
        assertNull(l.sizes[WIFI]) // zero
        assertNull(l.sizes[SOUND]) // one number
        assertNull(l.sizes[USB]) // three numbers
        assertNull(l.sizes[BRIGHTNESS]) // not numbers
        assertEquals(Span(1, 1), l.sizes[BLUETOOTH])
        assertNull(l.sizes[AIRPLANE]) // negative
        assertEquals(Span(3, 2), l.sizes[NOW_PLAYING]) // raised to the minimum
    }

    // --- Positions (free placement, one set per orientation) -----------------------------------------------------------------------

    private val tile = BlockGrid.Placement(WIFI, 5, 3, 1, 1)
    private val wide = BlockGrid.Placement(USB, 0, 5, 3, 1)

    @Test
    fun placementsAreRememberedPerOrientation() {
        val l = ActionsLayout.DEFAULT.withPlacements(GridOrientation.LANDSCAPE, listOf(tile, wide))
        assertEquals(mapOf(WIFI to CellPos(5, 3), USB to CellPos(0, 5)), l.positionsFor(GridOrientation.LANDSCAPE))
        assertTrue(l.positionsFor(GridOrientation.PORTRAIT).isEmpty())
    }

    @Test
    fun savingAgainKeepsTheCellsOfBlocksNotCurrentlyShown() {
        val first = ActionsLayout.DEFAULT.withPlacements(GridOrientation.LANDSCAPE, listOf(tile, wide))
        val second = first.withPlacements(GridOrientation.LANDSCAPE, listOf(BlockGrid.Placement(WIFI, 7, 0, 1, 1)))
        assertEquals(CellPos(7, 0), second.positionsFor(GridOrientation.LANDSCAPE)[WIFI])
        assertEquals(CellPos(0, 5), second.positionsFor(GridOrientation.LANDSCAPE)[USB]) // hidden or absent now: kept
    }

    @Test
    fun hidingKeepsTheSavedCellForWhenItComesBack() {
        val l = ActionsLayout.DEFAULT.withPlacements(GridOrientation.LANDSCAPE, listOf(tile)).hide(WIFI).restore(WIFI)
        assertEquals(CellPos(5, 3), l.positionsFor(GridOrientation.LANDSCAPE)[WIFI])
        assertTrue(WIFI !in l.hidden)
    }

    @Test
    fun positionsRoundTripThroughTheJson() {
        val l = ActionsLayout.DEFAULT
            .withPlacements(GridOrientation.LANDSCAPE, listOf(tile, wide))
            .withPlacements(GridOrientation.PORTRAIT, listOf(BlockGrid.Placement(CLOCK, 0, 4, 2, 2)))
            .resize(CLOCK, Span(2, 2))
        assertEquals(l, ActionsLayout.fromJson(l.toJson()))
        val pos = JSONObject(l.toJson()).getJSONObject("pos")
        assertEquals(5, pos.getJSONObject("landscape").getJSONArray("wifi").getInt(0))
        assertEquals(4, pos.getJSONObject("portrait").getJSONArray("clock").getInt(1))
    }

    @Test
    fun oldJsonWithoutPositionsIsSeededFromTheOrder() {
        val l = ActionsLayout.fromJson("""{"order":["usb","wifi","clock"],"hidden":[]}""")
        assertTrue(l.positions.isEmpty())
        // No saved cell: the planner packs the blocks in the saved order, as before.
        val placed = GridPlanner.place(listOf(USB, WIFI, CLOCK), 11, BlockGrid.ROWS, { l.sizeOf(it, 11) }, l.positionsFor(GridOrientation.LANDSCAPE))
        assertEquals(BlockGrid.Placement(USB, 0, 0, 3, 1), placed[0])
        assertEquals(BlockGrid.Placement(WIFI, 3, 0, 1, 1), placed[1])
        assertEquals(BlockGrid.Placement(CLOCK, 4, 0, 4, 2), placed[2])
    }

    @Test
    fun badPositionsAreDroppedAndTheRestKept() {
        val l = ActionsLayout.fromJson(
            """{"pos":{"landscape":{"wifi":[3,2],"clock":[-1,0],"usb":[1],"sound":["a",1],"nope":[0,0],"bluetooth":[1.0,4],"airplane":[1,2,3]},
                "tablet":{"wifi":[0,0]},"portrait":5}}""",
        )
        assertEquals(mapOf(WIFI to CellPos(3, 2), BLUETOOTH to CellPos(1, 4)), l.positionsFor(GridOrientation.LANDSCAPE))
        assertTrue(l.positionsFor(GridOrientation.PORTRAIT).isEmpty())
        assertTrue(ActionsLayout.fromJson("""{"pos":null}""").positions.isEmpty())
        assertTrue(ActionsLayout.fromJson("""{"pos":[1]}""").positions.isEmpty())
    }

    @Test
    fun aRelocatedPositionDoesNotLoseTheOthers() {
        // The saved cell of the tile is now on the clock; the sound block's cell still holds.
        val l = ActionsLayout.DEFAULT
            .withPlacements(GridOrientation.LANDSCAPE, listOf(BlockGrid.Placement(CLOCK, 0, 0, 4, 2), BlockGrid.Placement(WIFI, 1, 1, 1, 1), BlockGrid.Placement(SOUND, 6, 4, 3, 1)))
            .resize(CLOCK, Span(4, 2))
        val placed = GridPlanner.place(listOf(CLOCK, WIFI, SOUND), 11, BlockGrid.ROWS, { l.sizeOf(it, 11) }, l.positionsFor(GridOrientation.LANDSCAPE))
        assertEquals(BlockGrid.Placement(SOUND, 6, 4, 3, 1), placed[2])
        assertEquals(BlockGrid.Placement(WIFI, 4, 0, 1, 1), placed[1])
    }
}
