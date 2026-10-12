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
import com.orizonx.client.protocol.Protocol

private val Night = Color(0xFF0B0B1A)
private val Violet = Color(0xFF7F77DD)
private val Teal = Color(0xFF1D9E75)
private val Pink = Color(0xFFD4537E)
private val Amber = Color(0xFFFAC775)

@Composable
fun WaitingScreen(
    reason: String?,
    screen: ScreenInfo,
    role: DeviceRole,
    connectedRole: DeviceRole?,
    onRoleChosen: (DeviceRole) -> Unit,
) {
    BoxWithConstraints(Modifier.fillMaxSize(), contentAlignment = Alignment.Center) {
        BlobBackground()
        val actionsConnected = connectedRole == DeviceRole.ACTIONS
        val fraction = if (maxWidth < 600.dp) 0.92f else 0.55f
        GlassCard(Modifier.fillMaxWidth(fraction).wrapContentWidth().widthIn(max = 620.dp)) {
            Column(
                Modifier.fillMaxWidth().verticalScroll(rememberScrollState()),
                horizontalAlignment = Alignment.CenterHorizontally,
            ) {
                Image(
                    painterResource(R.drawable.ic_orizonx_logo),
                    contentDescription = "Logo Orizon X",
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
                    GlassText(if (actionsConnected) "PC connecté — mode Actions" else "En attente du PC…", size = 16.sp)
                }
                Spacer(Modifier.height(16.dp))
                Row(Modifier.fillMaxWidth()) {
                    GlassButton("Écran", selected = role == DeviceRole.SCREEN, onClick = { onRoleChosen(DeviceRole.SCREEN) }, modifier = Modifier.weight(1f), icon = R.drawable.ox_mode_screen)
                    Spacer(Modifier.width(12.dp))
                    GlassButton("Actions", selected = role == DeviceRole.ACTIONS, onClick = { onRoleChosen(DeviceRole.ACTIONS) }, modifier = Modifier.weight(1f), icon = R.drawable.ox_mode_actions)
                }
                if (reason != null) {
                    Spacer(Modifier.height(8.dp))
                    GlassText(reason, size = 13.sp, color = Amber, align = TextAlign.Center)
                }
                Spacer(Modifier.height(14.dp))
                if (!actionsConnected) GlassText("Lance Orizon X sur le PC.", size = 13.sp, alpha = 0.85f)
                if (role == DeviceRole.SCREEN) {
                    Spacer(Modifier.height(10.dp))
                    GlassText("Appui long à 4 doigts : infos de connexion", size = 12.sp, alpha = 0.75f)
                }
                Spacer(Modifier.height(18.dp))
                Row {
                    GlassText("${screen.width}×${screen.height}", size = 12.sp, alpha = 0.7f)
                    Spacer(Modifier.width(20.dp))
                    GlassText("127.0.0.1:${Protocol.PORT}", size = 12.sp, alpha = 0.7f)
                    Spacer(Modifier.width(20.dp))
                    GlassText("protocole v${Protocol.VERSION}", size = 12.sp, alpha = 0.7f)
                }
            }
        }
    }
}

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
