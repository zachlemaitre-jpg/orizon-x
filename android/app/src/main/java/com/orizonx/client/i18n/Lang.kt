package com.orizonx.client.i18n

import android.content.SharedPreferences
import androidx.compose.runtime.staticCompositionLocalOf

/** Interface language actually shown (and announced to the PC in DEVICE_INFO.lang). */
enum class Lang(val wire: String) {
    EN("en"),
    FR("fr"),
}

/** What the user chose with the language pill: follow the system, or force one language. */
enum class LangPref(val wire: String) {
    SYSTEM("system"),
    EN("en"),
    FR("fr"),
    ;

    /** The pill cycles SYSTEM -> EN -> FR -> SYSTEM. */
    fun next(): LangPref = entries[(ordinal + 1) % entries.size]

    companion object {
        fun fromWire(value: String?): LangPref = entries.firstOrNull { it.wire == value } ?: SYSTEM

        /** French when forced, or when following a French system; English otherwise (any other system language too). */
        fun effective(pref: LangPref, systemLanguage: String): Lang = when (pref) {
            FR -> Lang.FR
            EN -> Lang.EN
            SYSTEM -> if (systemLanguage.lowercase() == "fr") Lang.FR else Lang.EN
        }
    }
}

/** Persists the [LangPref] next to the role, in the same SharedPreferences. */
class LangStore(private val prefs: SharedPreferences) {
    fun load(): LangPref = LangPref.fromWire(prefs.getString(KEY, null))

    fun save(pref: LangPref) {
        prefs.edit().putString(KEY, pref.wire).apply()
    }

    private companion object {
        const val KEY = "language"
    }
}

/** Current language for the whole composition; changing it redraws every text without recreating the Activity. */
val LocalLang = staticCompositionLocalOf { Lang.EN }
