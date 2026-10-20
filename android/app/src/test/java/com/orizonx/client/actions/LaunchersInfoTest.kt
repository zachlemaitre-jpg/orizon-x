package com.orizonx.client.actions

import org.json.JSONObject
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Test

class LaunchersInfoTest {
    private fun parse(json: String) = ActionsState.parse(JSONObject(json)).launchers

    @Test
    fun theSectionIsParsed() {
        assertEquals(
            LaunchersInfo(settings = true, discord = true, spotify = false, downloads = true, discordIcon = "abc", spotifyIcon = null),
            parse("""{"launchers":{"settings":true,"discord":true,"spotify":false,"downloads":true,"icons":{"discord":"abc","spotify":null}}}"""),
        )
    }

    @Test
    fun absentOrNotAnObjectMeansAnOlderPc() {
        assertNull(parse("{}"))
        assertNull(parse("""{"launchers":null}"""))
        assertNull(parse("""{"launchers":"yes"}"""))
        assertNull(parse("""{"launchers":[true]}"""))
    }

    @Test
    fun onlyTheBooleanTrueCounts() {
        val l = parse("""{"launchers":{"settings":"true","discord":1,"spotify":null,"downloads":true}}""")!!
        assertEquals(listOf(false, false, false, true), listOf(l.settings, l.discord, l.spotify, l.downloads))
    }

    @Test
    fun iconIdsMustBeNonBlankStrings() {
        val l = parse("""{"launchers":{"discord":true,"spotify":true,"icons":{"discord":5,"spotify":"  "}}}""")!!
        assertNull(l.discordIcon)
        assertNull(l.spotifyIcon)
        assertNull(parse("""{"launchers":{"icons":[1]}}""")!!.discordIcon)
        assertNull(parse("""{"launchers":{}}""")!!.spotifyIcon)
    }
}
