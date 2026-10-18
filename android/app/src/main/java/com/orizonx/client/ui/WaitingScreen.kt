package com.orizonx.client.ui

import androidx.compose.animation.core.LinearEasing
import androidx.compose.animation.core.RepeatMode
import androidx.compose.animation.core.animateFloat
import androidx.compose.animation.core.infiniteRepeatable
import androidx.compose.animation.core.rememberInfiniteTransition
import androidx.compose.animation.core.tween
import androidx.compose.foundation.Image
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.WindowInsets
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.safeDrawing
import androidx.compose.foundation.layout.windowInsetsPadding
import androidx.compose.foundation.layout.BoxScope
import androidx.compose.foundation.layout.BoxWithConstraints
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.offset
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.layout.widthIn
import androidx.compose.foundation.layout.wrapContentWidth
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.foundation.text.BasicText
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.foundation.layout.Arrangement
import android.os.Build
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.alpha
import androidx.compose.ui.draw.blur
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.res.painterResource
import androidx.compose.ui.text.TextStyle
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.orizonx.client.DeviceRole
import com.orizonx.client.R
import com.orizonx.client.ScreenInfo
import com.orizonx.client.i18n.LangPref
import com.orizonx.client.i18n.Msg
import com.orizonx.client.i18n.S
import com.orizonx.client.i18n.tr
import com.orizonx.client.protocol.Protocol
import com.orizonx.client.setup.guideFor

private val Night = Color(0xFF0B0B1A)
private val Violet = Color(0xFF7F77DD)
private val Teal = Color(0xFF1D9E75)
private val Pink = Color(0xFFD4537E)
private val Amber = Color(0xFFFAC775)

@Composable
fun WaitingScreen(
    reason: Msg?,
    screen: ScreenInfo,
    role: DeviceRole,
    connectedRole: DeviceRole?,
    onRoleChosen: (DeviceRole) -> Unit,
    langPref: LangPref,
    onLangPref: (LangPref) -> Unit,
) {
    BoxWithConstraints(Modifier.fillMaxSize(), contentAlignment = Alignment.Center) {
        BlobBackground()
        val actionsConnected = connectedRole == DeviceRole.ACTIONS
        val connected = connectedRole != null
        val steps = rememberSetupSteps(active = !connected)
        val guide = remember { guideFor(Build.MANUFACTURER ?: "") }
        // null = follow the live state (open while USB debugging is off); the pill overrides it.
        var userChoice by remember { mutableStateOf<Boolean?>(null) }
        val guideShown = !connected && (userChoice ?: steps.autoOpen)
        val landscape = maxWidth > maxHeight
        val fraction = if (maxWidth < 600.dp) 0.92f else 0.55f

        val mainCard: @Composable (Modifier, Boolean) -> Unit = { modifier, innerScroll ->
            GlassCard(modifier) {
                Column(
                    if (innerScroll) Modifier.fillMaxWidth().verticalScroll(rememberScrollState()) else Modifier.fillMaxWidth(),
                    horizontalAlignment = Alignment.CenterHorizontally,
                ) {
                    MainCardContent(
                        reason, screen, role, actionsConnected, onRoleChosen,
                        showGuidePill = !connected,
                        guideShown = guideShown,
                        onGuidePill = { userChoice = !guideShown },
                    )
                }
            }
        }

        if (!guideShown) {
            mainCard(Modifier.fillMaxWidth(fraction).wrapContentWidth().widthIn(max = 620.dp), true)
        } else if (landscape) {
            // Main card and guide side by side; each scrolls on its own when the screen is short.
            Row(
                Modifier
                    .fillMaxSize()
                    .windowInsetsPadding(WindowInsets.safeDrawing)
                    .padding(start = 16.dp, end = 16.dp, top = 64.dp, bottom = 16.dp),
                horizontalArrangement = Arrangement.spacedBy(16.dp),
                verticalAlignment = Alignment.CenterVertically,
            ) {
                mainCard(Modifier.weight(1f), true)
                Column(Modifier.weight(1.2f).verticalScroll(rememberScrollState())) {
                    SetupGuideCard(guide, steps, Modifier.fillMaxWidth())
                }
            }
        } else {
            // Portrait: guide below the main card, the whole column scrolls so it fits a phone.
            Column(
                Modifier
                    .fillMaxSize()
                    .windowInsetsPadding(WindowInsets.safeDrawing)
                    .verticalScroll(rememberScrollState())
                    .padding(top = 64.dp, bottom = 16.dp),
                horizontalAlignment = Alignment.CenterHorizontally,
                verticalArrangement = Arrangement.Center,
            ) {
                mainCard(Modifier.fillMaxWidth(fraction).widthIn(max = 620.dp), false)
                Spacer(Modifier.height(16.dp))
                SetupGuideCard(guide, steps, Modifier.fillMaxWidth(fraction).widthIn(max = 620.dp))
            }
        }
        LangPill(
            langPref,
            onLangPref,
            Modifier.align(Alignment.TopEnd).windowInsetsPadding(WindowInsets.safeDrawing).padding(16.dp),
        )
    }
}

@Composable
private fun MainCardContent(
    reason: Msg?,
    screen: ScreenInfo,
    role: DeviceRole,
    actionsConnected: Boolean,
    onRoleChosen: (DeviceRole) -> Unit,
    showGuidePill: Boolean,
    guideShown: Boolean,
    onGuidePill: () -> Unit,
) {
    Image(
        painterResource(R.drawable.ic_orizonx_logo),
        contentDescription = tr(S.LOGO_DESC),
        modifier = Modifier.size(120.dp),
    )
    Spacer(Modifier.height(8.dp))
    BasicText(
        "Orizon X",
        style = TextStyle(color = Color.White, fontSize = 44.sp, fontFamily = BrandFont),
    )
    Spacer(Modifier.height(20.dp))
    Row(verticalAlignment = Alignment.CenterVertically) {
        PulsingDot()
        Spacer(Modifier.width(10.dp))
        GlassText(tr(if (actionsConnected) S.PC_CONNECTED_ACTIONS else S.WAITING_FOR_PC), size = 16.sp)
    }
    Spacer(Modifier.height(16.dp))
    RoleButtons(role, onRoleChosen)
    if (reason != null) {
        Spacer(Modifier.height(8.dp))
        GlassText(tr(reason), size = 13.sp, color = Amber, align = TextAlign.Center)
    }
    Spacer(Modifier.height(14.dp))
    if (!actionsConnected) GlassText(tr(S.HINT_LAUNCH_PC), size = 13.sp, alpha = 0.85f)
    if (role == DeviceRole.SCREEN) {
        Spacer(Modifier.height(10.dp))
        GlassText(tr(S.HINT_HUD_LONG), size = 12.sp, alpha = 0.75f)
    }
    if (showGuidePill) {
        Spacer(Modifier.height(14.dp))
        Pill(tr(S.SETUP_GUIDE), selected = guideShown, onClick = onGuidePill)
    }
    Spacer(Modifier.height(18.dp))
    Row {
        GlassText("${screen.width}×${screen.height}", size = 12.sp, alpha = 0.7f)
        Spacer(Modifier.width(20.dp))
        GlassText("127.0.0.1:${Protocol.PORT}", size = 12.sp, alpha = 0.7f)
        Spacer(Modifier.width(20.dp))
        GlassText(tr(S.PROTOCOL_VERSION, "version" to Protocol.VERSION), size = 12.sp, alpha = 0.7f)
    }
}

/** Screen, Actions and Frame side by side when the card is wide enough; otherwise Frame goes on a second line. */
@Composable
private fun RoleButtons(role: DeviceRole, onRoleChosen: (DeviceRole) -> Unit) {
    BoxWithConstraints(Modifier.fillMaxWidth()) {
        val screenButton: @Composable (Modifier) -> Unit = {
            GlassButton(tr(S.ROLE_SCREEN), selected = role == DeviceRole.SCREEN, onClick = { onRoleChosen(DeviceRole.SCREEN) }, modifier = it, icon = R.drawable.ox_mode_screen)
        }
        val actionsButton: @Composable (Modifier) -> Unit = {
            GlassButton(tr(S.ROLE_ACTIONS), selected = role == DeviceRole.ACTIONS, onClick = { onRoleChosen(DeviceRole.ACTIONS) }, modifier = it, icon = R.drawable.ox_mode_actions)
        }
        val frameButton: @Composable (Modifier) -> Unit = {
            GlassButton(tr(S.ROLE_FRAME), selected = role == DeviceRole.FRAME, onClick = { onRoleChosen(DeviceRole.FRAME) }, modifier = it, icon = R.drawable.ox_mode_frame)
        }
        if (maxWidth >= THREE_ROLES_MIN_WIDTH) {
            Row(Modifier.fillMaxWidth()) {
                screenButton(Modifier.weight(1f))
                Spacer(Modifier.width(12.dp))
                actionsButton(Modifier.weight(1f))
                Spacer(Modifier.width(12.dp))
                frameButton(Modifier.weight(1f))
            }
        } else {
            Column(Modifier.fillMaxWidth()) {
                Row(Modifier.fillMaxWidth()) {
                    screenButton(Modifier.weight(1f))
                    Spacer(Modifier.width(12.dp))
                    actionsButton(Modifier.weight(1f))
                }
                Spacer(Modifier.height(12.dp))
                frameButton(Modifier.fillMaxWidth())
            }
        }
    }
}

private val THREE_ROLES_MIN_WIDTH = 560.dp

/** Dark background with three slowly drifting colour blobs, blurred (real blur, API 31+). */
@Composable
fun BlobBackground() {
    val transition = rememberInfiniteTransition(label = "blobs")
    val drift by transition.animateFloat(
        initialValue = 0f,
        targetValue = 1f,
        animationSpec = infiniteRepeatable(tween(12_000, easing = LinearEasing), RepeatMode.Reverse),
        label = "drift",
    )
    Box(Modifier.fillMaxSize().background(Night)) {
        Box(Modifier.fillMaxSize().blur(80.dp)) {
            Blob(Violet, 520.dp, Alignment.TopStart, x = (-80 + 140 * drift).dp, y = (-60).dp)
            Blob(Teal, 460.dp, Alignment.BottomEnd, x = (60 - 120 * drift).dp, y = 80.dp)
            Blob(Pink, 320.dp, Alignment.Center, x = (120 - 200 * drift).dp, y = (-80 + 60 * drift).dp)
        }
    }
}

@Composable
private fun BoxScope.Blob(color: Color, size: Dp, alignment: Alignment, x: Dp, y: Dp) {
    Box(
        Modifier
            .align(alignment)
            .offset(x, y)
            .size(size)
            .background(color.copy(alpha = 0.85f), CircleShape),
    )
}

@Composable
private fun PulsingDot() {
    val transition = rememberInfiniteTransition(label = "pulse")
    val alpha by transition.animateFloat(
        initialValue = 1f,
        targetValue = 0.25f,
        animationSpec = infiniteRepeatable(tween(800), RepeatMode.Reverse),
        label = "alpha",
    )
    Box(Modifier.size(8.dp).alpha(alpha).background(Color(0xFF5DCAA5), CircleShape))
}
