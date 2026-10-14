package com.orizonx.client.ui

import android.content.ActivityNotFoundException
import android.content.Context
import android.content.Intent
import android.provider.Settings
import androidx.compose.foundation.Canvas
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.alpha
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.StrokeCap
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.platform.LocalContext
import androidx.lifecycle.compose.LocalLifecycleOwner
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.lifecycle.Lifecycle
import androidx.lifecycle.LifecycleEventObserver
import com.orizonx.client.i18n.LocalLang
import com.orizonx.client.i18n.S
import com.orizonx.client.i18n.tr
import com.orizonx.client.setup.AndroidSetupProbe
import com.orizonx.client.setup.SetupGuide
import com.orizonx.client.setup.SetupSteps
import com.orizonx.client.setup.forLang
import kotlinx.coroutines.delay

private val Teal = Color(0xFF5DCAA5)
private val StepShape = RoundedCornerShape(14.dp)
private const val REFRESH_MS = 2000L

/** Live setup state: read again when the app comes back to the foreground, and every 2 s while [active]. */
@Composable
fun rememberSetupSteps(active: Boolean): SetupSteps {
    val context = LocalContext.current
    val probe = remember(context) { AndroidSetupProbe(context.applicationContext) }
    var steps by remember(probe) { mutableStateOf(SetupSteps.read(probe)) }
    val owner = LocalLifecycleOwner.current
    DisposableEffect(owner, probe) {
        val observer = LifecycleEventObserver { _, event ->
            if (event == Lifecycle.Event.ON_RESUME) steps = SetupSteps.read(probe)
        }
        owner.lifecycle.addObserver(observer)
        onDispose { owner.lifecycle.removeObserver(observer) }
    }
    LaunchedEffect(active, probe) {
        if (active) {
            steps = SetupSteps.read(probe)
            while (true) {
                delay(REFRESH_MS)
                steps = SetupSteps.read(probe)
            }
        }
    }
    return steps
}

/** Glass card with the five steps to bring a new device to its first connection, brand paths included. */
@Composable
fun SetupGuideCard(guide: SetupGuide, steps: SetupSteps, modifier: Modifier = Modifier) {
    val lang = LocalLang.current
    val context = LocalContext.current
    val current = steps.current
    GlassCard(modifier) {
        GlassText(tr(S.SETUP_GUIDE), size = 20.sp, weight = FontWeight.SemiBold)
        Spacer(Modifier.height(12.dp))
        Step(1, steps.devOptions == true, current == 1) {
            GlassText(tr(S.SETUP_STEP_1), size = 15.sp)
            PathText(guide.buildPath.forLang(lang))
            guide.note?.let { GlassText(it.forLang(lang), size = 13.sp, color = Color(0xFFFAC775)) }
            GlassText(tr(S.SETUP_TIP_SEARCH), size = 12.sp, alpha = 0.7f)
            Spacer(Modifier.height(6.dp))
            Pill(tr(S.SETUP_OPEN_ABOUT), selected = false, onClick = { openSettings(context, Settings.ACTION_DEVICE_INFO_SETTINGS) })
        }
        Step(2, steps.usbDebugging == true, current == 2) {
            GlassText(tr(S.SETUP_STEP_2), size = 15.sp)
            PathText(guide.devPath.forLang(lang))
            Spacer(Modifier.height(6.dp))
            Pill(tr(S.SETUP_OPEN_DEV), selected = false, onClick = { openSettings(context, Settings.ACTION_APPLICATION_DEVELOPMENT_SETTINGS) })
        }
        Step(3, steps.usbPlugged == true, current == 3) {
            GlassText(tr(S.SETUP_STEP_3), size = 15.sp)
        }
        Step(4, false, current == 4) {
            GlassText(tr(S.SETUP_STEP_4), size = 14.sp, alpha = 0.85f)
        }
        Step(5, false, false) {
            GlassText(tr(S.SETUP_STEP_5), size = 15.sp)
        }
    }
}

@Composable
private fun PathText(path: String) {
    Spacer(Modifier.height(2.dp))
    GlassText(path, size = 13.sp, alpha = 0.8f, weight = FontWeight.Medium)
}

/** One numbered step: a done step is ticked and dimmed, the current one is highlighted. */
@Composable
private fun Step(number: Int, done: Boolean, highlighted: Boolean, content: @Composable () -> Unit) {
    Row(
        Modifier
            .fillMaxWidth()
            .padding(vertical = 3.dp)
            .background(Color.White.copy(alpha = if (highlighted) 0.14f else 0f), StepShape)
            .border(1.dp, Color.White.copy(alpha = if (highlighted) 0.5f else 0f), StepShape)
            .padding(horizontal = 10.dp, vertical = 8.dp)
            .alpha(if (done) 0.5f else 1f),
        horizontalArrangement = Arrangement.Start,
    ) {
        StepBadge(number, done)
        Spacer(Modifier.width(12.dp))
        Column(Modifier.weight(1f)) { content() }
    }
}

@Composable
private fun StepBadge(number: Int, done: Boolean) {
    val description = if (done) tr(S.SETUP_DONE_DESC) else number.toString()
    Box(
        Modifier
            .size(28.dp)
            .background(if (done) Teal else Color.White.copy(alpha = 0.18f), CircleShape)
            .semantics { contentDescription = description },
        contentAlignment = Alignment.Center,
    ) {
        if (done) {
            Canvas(Modifier.size(28.dp)) {
                val w = size.width
                val stroke = w * 0.09f
                val dark = Color(0xFF0B0B1A)
                drawLine(dark, Offset(w * 0.27f, w * 0.52f), Offset(w * 0.43f, w * 0.68f), stroke, StrokeCap.Round)
                drawLine(dark, Offset(w * 0.43f, w * 0.68f), Offset(w * 0.74f, w * 0.34f), stroke, StrokeCap.Round)
            }
        } else {
            GlassText(number.toString(), size = 14.sp, weight = FontWeight.SemiBold)
        }
    }
}

/** Opens a system settings screen; some makers drop an intent, so fall back to the main Settings. */
private fun openSettings(context: Context, action: String) {
    fun start(act: String) = context.startActivity(Intent(act).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK))
    try {
        start(action)
    } catch (_: ActivityNotFoundException) {
        try {
            start(Settings.ACTION_SETTINGS)
        } catch (_: Exception) {
            // nothing more we can do
        }
    } catch (_: SecurityException) {
        // some builds refuse the intent; the path in the card still tells the user where to go
    }
}
