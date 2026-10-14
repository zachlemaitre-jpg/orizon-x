package com.orizonx.client.setup

import com.orizonx.client.i18n.Lang
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

class SetupGuidesTest {
    @Test
    fun everyManufacturerAndAliasMapsToItsGuide() {
        val expected = mapOf(
            "samsung" to "samsung",
            "xiaomi" to "xiaomi", "redmi" to "xiaomi", "poco" to "xiaomi",
            "google" to "pixel",
            "oneplus" to "oneplus", "oppo" to "oneplus", "realme" to "oneplus",
            "huawei" to "huawei",
            "honor" to "honor",
            "motorola" to "motorola",
            "lenovo" to "lenovo",
            "sony" to "sony",
            "nothing" to "nothing",
        )
        for ((manufacturer, id) in expected) {
            assertEquals("guide of $manufacturer", id, guideFor(manufacturer).id)
        }
    }

    @Test
    fun lookupIgnoresCaseAndSurroundingSpaces() {
        assertEquals("samsung", guideFor("SAMSUNG").id)
        assertEquals("samsung", guideFor("Samsung").id)
        assertEquals("xiaomi", guideFor("  Xiaomi ").id)
        assertEquals("oneplus", guideFor("OnePlus").id)
        assertEquals("pixel", guideFor(" GOOGLE\t").id)
    }

    @Test
    fun unknownOrEmptyManufacturerGivesTheGenericGuide() {
        assertEquals("generic", guideFor("Fairphone").id)
        assertEquals("generic", guideFor("").id)
        assertEquals("generic", guideFor("   ").id)
    }

    @Test
    fun everyGuideHasNonEmptyPathsInBothLanguages() {
        val manufacturers = listOf(
            "samsung", "xiaomi", "redmi", "poco", "google", "oneplus", "oppo", "realme", "huawei", "honor",
            "motorola", "lenovo", "sony", "nothing", "fairphone",
        )
        for (manufacturer in manufacturers) {
            val guide = guideFor(manufacturer)
            for (lang in Lang.entries) {
                assertFalse("$manufacturer build path $lang", guide.buildPath.forLang(lang).isBlank())
                assertFalse("$manufacturer dev path $lang", guide.devPath.forLang(lang).isBlank())
            }
        }
    }

    @Test
    fun samsungPathsMatchThePlan() {
        val guide = guideFor("samsung")
        assertEquals(
            "Settings › About tablet (or phone) › Software information › Build number",
            guide.buildPath.forLang(Lang.EN),
        )
        assertEquals(
            "Paramètres › À propos de la tablette (ou du téléphone) › Informations sur le logiciel › Numéro de version",
            guide.buildPath.forLang(Lang.FR),
        )
        assertEquals("Settings › Developer options (at the bottom)", guide.devPath.forLang(Lang.EN))
        assertEquals("Paramètres › Options de développement (tout en bas)", guide.devPath.forLang(Lang.FR))
    }

    @Test
    fun onlyXiaomiAndHuaweiCarryANote() {
        val withNote = listOf("samsung", "xiaomi", "google", "oneplus", "huawei", "honor", "motorola", "lenovo", "sony", "nothing", "x")
            .filter { guideFor(it).note != null }
        assertEquals(listOf("xiaomi", "huawei"), withNote)
        assertEquals("On HyperOS or MIUI, tap 7 times on the OS version.", guideFor("poco").note!!.forLang(Lang.EN))
        assertEquals("Sur HyperOS ou MIUI, tape 7 fois sur la version de l'OS.", guideFor("poco").note!!.forLang(Lang.FR))
        assertEquals("In the USB notification, choose File transfer.", guideFor("huawei").note!!.forLang(Lang.EN))
        assertEquals("Dans la notification USB, choisis Transfert de fichiers.", guideFor("huawei").note!!.forLang(Lang.FR))
        assertNull(guideFor("samsung").note)
        assertNotNull(guideFor("xiaomi").note)
        assertTrue(guideFor("").note == null)
    }
}
