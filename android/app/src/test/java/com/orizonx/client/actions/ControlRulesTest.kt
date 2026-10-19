package com.orizonx.client.actions

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class ControlRulesTest {
    private fun parse(json: String) = ActionsState.parse(org.json.JSONObject(json))

    private val clock = """"clock":{"epoch_ms":1,"utc_offset_min":0}"""
    private val audio = """"audio":{"available":true,"volume":0.5,"muted":false}"""
    private val media = """"media":{"available":true}"""
    private val playing = """"now_playing":{"available":true,"app":"Spotify","title":"T","playing":true}"""
    private val brightness = """"brightness":{"available":true,"value":0.4}"""
    private val battery = """"battery":{"available":true,"percent":80,"charging":false}"""

    @Test
    fun everythingAvailable() {
        val s = parse("{$clock,$audio,$brightness,$battery}")
        assertEquals(KeyboardTopCards(clock = true, sound = true, brightness = true), KeyboardTopCards.of(s))
    }

    @Test
    fun noBrightnessOnADesktopMonitor() {
        val s = parse("{$clock,$audio}")
        assertEquals(KeyboardTopCards(clock = true, sound = true, brightness = false), KeyboardTopCards.of(s))
    }

    @Test
    fun clockCardIsKeptForTheBatteryAlone() {
        assertTrue(KeyboardTopCards.of(parse("{$battery}")).clock)
        assertFalse(KeyboardTopCards.of(parse("{$audio}")).clock)
    }

    @Test
    fun mediaKeysBelongToTheSoundCardOnlyWithoutNowPlaying() {
        val withoutPlaying = parse("{$media}")
        assertTrue(ControlRules.soundKeys(withoutPlaying))
        assertTrue(KeyboardTopCards.of(withoutPlaying).sound) // keys alone are enough for the card
        val withPlaying = parse("{$media,$playing}")
        assertFalse(ControlRules.soundKeys(withPlaying))
        assertFalse(KeyboardTopCards.of(withPlaying).sound)
        assertTrue(KeyboardTopCards.of(parse("{$media,$playing,$audio}")).sound)
    }

    @Test
    fun nothingAvailableMeansNoHeader() {
        val none = KeyboardTopCards.of(parse("{}"))
        assertFalse(none.any)
        assertFalse(KeyboardTopCards.of(parse("{$playing}")).any) // now playing is not kept above the keyboard
    }
}
