package com.orizonx.client.i18n

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNotNull
import org.junit.Test

class StringsTest {
    private val placeholder = Regex("""\{([a-z_]+)}""")

    private fun placeholders(text: String) = placeholder.findAll(text).map { it.groupValues[1] }.toSet()

    @Test
    fun everyKeyHasNonEmptyEnglishAndFrench() {
        for (key in S.entries) {
            val entry = Strings.entry(key)
            assertNotNull("missing entry for $key", entry)
            assertFalse("empty en for $key", entry!!.first.isBlank())
            assertFalse("empty fr for $key", entry.second.isBlank())
        }
    }

    @Test
    fun bothLanguagesUseTheSamePlaceholders() {
        for (key in S.entries) {
            val (en, fr) = Strings.entry(key)!!
            assertEquals("placeholders of $key", placeholders(en), placeholders(fr))
        }
    }

    @Test
    fun getPicksTheLanguage() {
        assertEquals("Waiting for the PC…", Strings.get(S.WAITING_FOR_PC, Lang.EN))
        assertEquals("En attente du PC…", Strings.get(S.WAITING_FOR_PC, Lang.FR))
    }

    @Test
    fun getReplacesPlaceholders() {
        assertEquals("Port 27183 already in use, retrying…", Strings.get(S.REASON_PORT_BUSY, Lang.EN, "port" to 27183))
        assertEquals("Port 27183 déjà utilisé, nouvel essai…", Strings.get(S.REASON_PORT_BUSY, Lang.FR, "port" to 27183))
        assertEquals("Eject E:", Strings.get(S.USB_EJECT_DESC, Lang.EN, "drive" to "E:"))
        assertEquals("Éjecter E:", Strings.get(S.USB_EJECT_DESC, Lang.FR, "drive" to "E:"))
    }

    @Test
    fun percentFollowsTheLanguageTypography() {
        assertEquals("42%", Strings.get(S.PERCENT, Lang.EN, "value" to 42))
        assertEquals("42 %", Strings.get(S.PERCENT, Lang.FR, "value" to 42))
    }

    @Test
    fun aMsgArgumentIsTranslatedInTheTargetLanguage() {
        val reason = Msg(S.REASON_PROTOCOL, "detail" to Msg(S.DETAIL_CODEC_UNSUPPORTED, "codec" to 7))
        assertEquals("Invalid protocol: unsupported codec: 7", Strings.get(reason, Lang.EN))
        assertEquals("Protocole invalide : codec non supporté : 7", Strings.get(reason, Lang.FR))
    }

    @Test
    fun aMsgWithoutArgs() {
        assertEquals("PC disconnected", Strings.get(Msg(S.REASON_PC_DISCONNECTED), Lang.EN))
        assertEquals("PC déconnecté", Strings.get(Msg(S.REASON_PC_DISCONNECTED), Lang.FR))
    }
}
