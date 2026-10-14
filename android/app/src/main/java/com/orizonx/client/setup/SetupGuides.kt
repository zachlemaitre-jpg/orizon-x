package com.orizonx.client.setup

import com.orizonx.client.i18n.Lang
import java.util.Locale

/** A pair of (English, French) texts. */
fun Pair<String, String>.forLang(lang: Lang): String = if (lang == Lang.FR) second else first

/** Menu paths for one brand, as (English, French) pairs; [note] only where the brand really differs. */
data class SetupGuide(
    val id: String,
    val buildPath: Pair<String, String>,
    val devPath: Pair<String, String>,
    val note: Pair<String, String>? = null,
)

private val DEV_SYSTEM = "Settings › System › Developer options" to "Paramètres › Système › Options pour les développeurs"
private val DEV_SYSTEM_UPDATES =
    "Settings › System & updates › Developer options" to "Paramètres › Système et mises à jour › Options pour les développeurs"
private val BUILD_PHONE = "Settings › About phone › Build number" to "Paramètres › À propos du téléphone › Numéro de build"

private val GUIDES: Map<String, SetupGuide> = listOf(
    SetupGuide(
        "samsung",
        "Settings › About tablet (or phone) › Software information › Build number" to
            "Paramètres › À propos de la tablette (ou du téléphone) › Informations sur le logiciel › Numéro de version",
        "Settings › Developer options (at the bottom)" to "Paramètres › Options de développement (tout en bas)",
    ),
    SetupGuide(
        "xiaomi",
        "Settings › About phone › OS version (or MIUI version)" to
            "Paramètres › À propos du téléphone › Version de l'OS (ou Version MIUI)",
        "Settings › Additional settings › Developer options" to
            "Paramètres › Paramètres supplémentaires › Options pour les développeurs",
        "On HyperOS or MIUI, tap 7 times on the OS version." to "Sur HyperOS ou MIUI, tape 7 fois sur la version de l'OS.",
    ),
    SetupGuide(
        "pixel",
        BUILD_PHONE,
        DEV_SYSTEM,
    ),
    SetupGuide(
        "oneplus",
        "Settings › About device › Version › Build number" to
            "Paramètres › À propos de l'appareil › Version › Numéro de version",
        "Settings › Additional settings (or System settings) › Developer options" to
            "Paramètres › Paramètres supplémentaires (ou Paramètres système) › Options pour les développeurs",
    ),
    SetupGuide(
        "huawei",
        BUILD_PHONE,
        DEV_SYSTEM_UPDATES,
        "In the USB notification, choose File transfer." to "Dans la notification USB, choisis Transfert de fichiers.",
    ),
    SetupGuide("honor", BUILD_PHONE, DEV_SYSTEM_UPDATES),
    SetupGuide("motorola", BUILD_PHONE, DEV_SYSTEM),
    SetupGuide(
        "lenovo",
        "Settings › About tablet › Build number" to "Paramètres › À propos de la tablette › Numéro de build",
        DEV_SYSTEM,
    ),
    SetupGuide("sony", BUILD_PHONE, DEV_SYSTEM),
    SetupGuide(
        "nothing",
        "Settings › About phone › Software info › Build number" to
            "Paramètres › À propos du téléphone › Infos logiciel › Numéro de build",
        DEV_SYSTEM,
    ),
    SetupGuide(
        "generic",
        "Settings › About (phone or tablet) › Build number" to
            "Paramètres › À propos (du téléphone ou de la tablette) › Numéro de build (ou de version)",
        DEV_SYSTEM,
    ),
).associateBy { it.id }

private val ALIASES: Map<String, String> = mapOf(
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

/** The guide for a `Build.MANUFACTURER` value: case-insensitive, trimmed; unknown brands get the generic one. */
fun guideFor(manufacturer: String): SetupGuide {
    val id = ALIASES[manufacturer.trim().lowercase(Locale.ROOT)] ?: "generic"
    return GUIDES.getValue(id)
}
