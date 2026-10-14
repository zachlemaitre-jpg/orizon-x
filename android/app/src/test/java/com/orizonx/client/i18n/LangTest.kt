package com.orizonx.client.i18n

import org.junit.Assert.assertEquals
import org.junit.Test

class LangTest {
    @Test
    fun prefCyclesSystemEnFrSystem() {
        assertEquals(LangPref.EN, LangPref.SYSTEM.next())
        assertEquals(LangPref.FR, LangPref.EN.next())
        assertEquals(LangPref.SYSTEM, LangPref.FR.next())
    }

    @Test
    fun effectiveLanguageForEveryPrefAndSystemLanguage() {
        for (system in listOf("fr", "en", "de")) {
            assertEquals(Lang.EN, LangPref.effective(LangPref.EN, system))
            assertEquals(Lang.FR, LangPref.effective(LangPref.FR, system))
        }
        assertEquals(Lang.FR, LangPref.effective(LangPref.SYSTEM, "fr"))
        assertEquals(Lang.EN, LangPref.effective(LangPref.SYSTEM, "en"))
        assertEquals(Lang.EN, LangPref.effective(LangPref.SYSTEM, "de"))
        assertEquals(Lang.EN, LangPref.effective(LangPref.SYSTEM, ""))
    }

    @Test
    fun wireNamesRoundTripAndUnknownMeansSystem() {
        for (pref in LangPref.entries) assertEquals(pref, LangPref.fromWire(pref.wire))
        assertEquals(LangPref.SYSTEM, LangPref.fromWire(null))
        assertEquals(LangPref.SYSTEM, LangPref.fromWire("de"))
        assertEquals("en", Lang.EN.wire)
        assertEquals("fr", Lang.FR.wire)
    }
}
