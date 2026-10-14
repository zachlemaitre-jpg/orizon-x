package com.orizonx.client.ui

import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.hapticfeedback.HapticFeedbackType
import androidx.compose.ui.platform.LocalHapticFeedback
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.semantics
import com.orizonx.client.i18n.LangPref
import com.orizonx.client.i18n.S
import com.orizonx.client.i18n.tr

/** Shows the language choice (Auto / EN / FR); each tap moves to the next one. */
@Composable
fun LangPill(pref: LangPref, onChange: (LangPref) -> Unit, modifier: Modifier = Modifier) {
    val haptics = LocalHapticFeedback.current
    val label = tr(
        when (pref) {
            LangPref.SYSTEM -> S.LANG_AUTO
            LangPref.EN -> S.LANG_EN
            LangPref.FR -> S.LANG_FR
        },
    )
    val description = tr(S.LANG_PILL_DESC, "value" to label)
    Pill(
        label,
        selected = false,
        onClick = {
            haptics.performHapticFeedback(HapticFeedbackType.ContextClick)
            onChange(pref.next())
        },
        modifier = modifier.semantics { contentDescription = description },
    )
}
