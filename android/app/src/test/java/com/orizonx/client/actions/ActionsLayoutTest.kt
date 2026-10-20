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

    // --- Reordering ---------------------------------------------------------------------------------------------------

    private val abcd = layout(CLOCK, SOUND, WIFI, USB)

    @Test
    fun movingForwardPutsTheBlockWhereTheTargetWas() {
        assertEquals(listOf(SOUND, WIFI, CLOCK, USB), abcd.move(CLOCK, WIFI).order)
        assertEquals(listOf(SOUND, WIFI, USB, CLOCK), abcd.move(CLOCK, USB).order)
        assertEquals(listOf(CLOCK, WIFI, SOUND, USB), abcd.move(SOUND, WIFI).order)
    }

    @Test
    fun movingBackwardPutsTheBlockBeforeTheTarget() {
        assertEquals(listOf(CLOCK, USB, SOUND, WIFI), abcd.move(USB, SOUND).order)
        assertEquals(listOf(USB, CLOCK, SOUND, WIFI), abcd.move(USB, CLOCK).order)
        assertEquals(listOf(SOUND, CLOCK, WIFI, USB), abcd.move(SOUND, CLOCK).order)
    }

    @Test
    fun droppingOnItselfChangesNothing() {
        assertEquals(abcd, abcd.move(WIFI, WIFI))
    }

    @Test
    fun unknownTargetsChangeNothing() {
        assertEquals(abcd, abcd.move(CLOCK, BRIGHTNESS))
        assertEquals(abcd, abcd.move(BRIGHTNESS, CLOCK))
    }

    @Test
    fun movingKeepsEveryBlockExactlyOnce() {
        var l = ActionsLayout.DEFAULT
        l = l.move(USB, CLOCK).move(CLOCK, AIRPLANE).move(WIFI, NOW_PLAYING).move(BRIGHTNESS, USB)
        assertEquals(BlockId.entries.toSet(), l.order.toSet())
        assertEquals(BlockId.entries.size, l.order.size)
    }

    @Test
    fun droppingBelowTheLastRowMovesToTheEnd() {
        assertEquals(listOf(SOUND, WIFI, USB, CLOCK), abcd.moveToEnd(CLOCK).order)
        assertEquals(abcd, abcd.moveToEnd(USB))
        assertEquals(abcd, abcd.moveToEnd(BRIGHTNESS))
    }

    @Test
    fun hiddenOrAbsentBlocksBetweenAreStepped() {
        // WIFI is hidden and SOUND is absent: they still count in the order, so the drop lands where the target sits.
        val l = layout(CLOCK, WIFI, SOUND, BRIGHTNESS, USB, hidden = setOf(WIFI))
        val present = setOf(CLOCK, WIFI, BRIGHTNESS, USB) // no SOUND
        assertEquals(listOf(CLOCK, BRIGHTNESS, USB), l.visible(present))
        val moved = l.move(CLOCK, BRIGHTNESS)
        assertEquals(listOf(WIFI, SOUND, BRIGHTNESS, CLOCK, USB), moved.order)
        assertEquals(listOf(BRIGHTNESS, CLOCK, USB), moved.visible(present))
        assertEquals(setOf(WIFI), moved.hidden)
        // And backward over the same two.
        val back = moved.move(USB, WIFI)
        assertEquals(listOf(USB, WIFI, SOUND, BRIGHTNESS, CLOCK), back.order)
    }

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
    fun otherBlocksCanBeMovedWhileOneIsHidden() {
        val l = abcd.hide(USB).move(CLOCK, SOUND).restore(USB)
        assertEquals(listOf(SOUND, CLOCK, WIFI, USB), l.order)
        assertTrue(USB !in l.hidden)
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
        val l = ActionsLayout.DEFAULT.move(USB, CLOCK).hide(WIFI)
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
    fun aChosenSizeIsUsedWithinTheLimits() {
        val l = ActionsLayout.DEFAULT.resize(BRIGHTNESS, Span(5, 2))
        assertEquals(Span(5, 2), l.sizeOf(BRIGHTNESS, 11))
        assertEquals(Span(6, 2), ActionsLayout.DEFAULT.resize(BRIGHTNESS, Span(40, 9)).sizeOf(BRIGHTNESS, 11)) // max
        assertEquals(Span(2, 1), ActionsLayout.DEFAULT.resize(BRIGHTNESS, Span(0, -3)).sizeOf(BRIGHTNESS, 11)) // min
    }

    @Test
    fun theSizeIsNarrowedToTheColumnCountAtLayoutTimeButKept() {
        val l = ActionsLayout.DEFAULT.resize(CLOCK, Span(8, 3))
        assertEquals(Span(8, 3), l.sizeOf(CLOCK, 11))
        assertEquals(Span(2, 3), l.sizeOf(CLOCK, 2))
        assertEquals(Span(7, 3), l.sizeOf(CLOCK, 7))
        // The stored size is untouched by the narrower grid.
        assertEquals(Span(8, 3), l.sizes[CLOCK])
    }

    @Test
    fun theMediaKeysRaiseTheSoundMinimum() {
        val small = ActionsLayout.DEFAULT.resize(SOUND, Span(2, 1))
        assertEquals(Span(2, 1), small.sizeOf(SOUND, 11))
        assertEquals(Span(3, 2), small.sizeOf(SOUND, 11, soundKeys = true))
        assertEquals(Span(3, 2), ActionsLayout.DEFAULT.resize(SOUND, Span(1, 1), soundKeys = true).sizes[SOUND])
    }

    @Test
    fun resizingStepsCellByCellWithinMinAndMax() {
        val start = Span(3, 1)
        assertEquals(Span(4, 2), BRIGHTNESS.resized(start, +1, +1))
        assertEquals(Span(2, 1), BRIGHTNESS.resized(start, -1, 0))
        assertEquals(Span(2, 1), BRIGHTNESS.resized(start, -5, -5)) // minimum
        assertEquals(Span(6, 2), BRIGHTNESS.resized(start, +9, +9)) // maximum
        assertEquals(start, BRIGHTNESS.resized(start, 0, 0))
        assertEquals(Span(1, 1), WIFI.resized(Span(1, 1), -1, -1))
        assertEquals(Span(2, 2), WIFI.resized(Span(1, 1), +1, +1))
        assertEquals(Span(2, 2), WIFI.resized(Span(2, 2), +1, +1))
        assertEquals(Span(3, 2), SOUND.resized(Span(3, 2), -1, -1, soundKeys = true))
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
    fun badSizesAreDroppedAndOutOfRangeOnesClamped() {
        val l = ActionsLayout.fromJson(
            """{"sizes":{"clock":[99,99],"wifi":[0,1],"sound":[3],"usb":[3,2,1],"brightness":["a",1],"nope":[1,1],
                "bluetooth":[1.0,1],"airplane":[-4,2],"now_playing":[1,1]}}""",
        )
        assertEquals(Span(8, 3), l.sizes[CLOCK]) // clamped to the maximum
        assertNull(l.sizes[WIFI]) // zero
        assertNull(l.sizes[SOUND]) // one number
        assertNull(l.sizes[USB]) // three numbers
        assertNull(l.sizes[BRIGHTNESS]) // not numbers
        assertEquals(Span(1, 1), l.sizes[BLUETOOTH])
        assertNull(l.sizes[AIRPLANE]) // negative
        assertEquals(Span(3, 2), l.sizes[NOW_PLAYING]) // raised to the minimum
    }
}
