package com.orizonx.client.ui

import android.view.Surface
import androidx.compose.animation.AnimatedVisibility
import androidx.compose.animation.core.tween
import androidx.compose.animation.fadeIn
import androidx.compose.animation.fadeOut
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.WindowInsets
import androidx.compose.foundation.layout.aspectRatio
import androidx.compose.foundation.layout.displayCutout
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.windowInsetsPadding
import androidx.compose.runtime.Composable
import androidx.compose.runtime.CompositionLocalProvider
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.orizonx.client.ConnectionState
import com.orizonx.client.DeviceRole
import com.orizonx.client.ScreenInfo
import com.orizonx.client.UiModel
import com.orizonx.client.i18n.LangPref
import com.orizonx.client.i18n.LocalLang
import com.orizonx.client.i18n.S
import com.orizonx.client.i18n.tr
import kotlinx.coroutines.delay

/** Root: letterboxed video, waiting screen on top while disconnected, optional HUD while streaming. */
@Composable
fun OrizonXApp(
    model: UiModel,
    screen: ScreenInfo,
    onVideoView: (android.view.View) -> Unit,
    onSurfaceCreated: (Surface) -> Unit,
    onSurfaceDestroyed: () -> Unit,
    onRoleChosen: (DeviceRole) -> Unit,
    onLangPrefChosen: (LangPref) -> Unit,
    onAction: (org.json.JSONObject) -> Unit,
) {
    val streaming = model.state is ConnectionState.Streaming
    val actionsActive = model.role == DeviceRole.ACTIONS && model.connectedRole == DeviceRole.ACTIONS
    val frameActive = model.role == DeviceRole.FRAME && model.connectedRole == DeviceRole.FRAME
    CompositionLocalProvider(LocalLang provides model.lang) {
        Box(
            Modifier
                .fillMaxSize()
                .background(Color.Black),
            contentAlignment = Alignment.Center,
        ) {
            // Ne jamais envelopper VideoSurface dans un graphicsLayer, un alpha ou un AnimatedVisibility :
            // un calque hors écran casse le « trou » du SurfaceView et la vidéo devient noire.
            val size = model.lastStream
            val videoModifier = if (size != null) {
                Modifier.aspectRatio(size.width.toFloat() / size.height)
            } else {
                Modifier.fillMaxSize()
            }
            VideoSurface(videoModifier, onVideoView, onSurfaceCreated, onSurfaceDestroyed)

            AnimatedVisibility(visible = !streaming && !actionsActive && !frameActive, enter = fadeIn(tween(400)), exit = fadeOut(tween(400))) {
                WaitingScreen(model.waitingReason, screen, model.role, model.connectedRole, onRoleChosen, model.langPref, onLangPrefChosen)
            }

            // VideoSurface stays composed underneath: it owns the Receiver's lifecycle (Surface created/destroyed).
            AnimatedVisibility(visible = actionsActive, enter = fadeIn(tween(300)), exit = fadeOut(tween(300))) {
                ActionsScreen(
                    model.actionsState, model.images, onAction,
                    onSwitchMode = { onRoleChosen(DeviceRole.SCREEN) },
                    langPref = model.langPref, onLangPref = onLangPrefChosen,
                )
            }

            AnimatedVisibility(visible = frameActive, enter = fadeIn(tween(300)), exit = fadeOut(tween(300))) {
                FrameScreen(model.frame, onSwitchMode = { onRoleChosen(DeviceRole.SCREEN) })
            }

            if (streaming) HudLayer(model, Modifier.align(Alignment.TopEnd).padding(16.dp), onRoleChosen)
            GestureHint(streaming, model.streamGeneration, Modifier.align(Alignment.BottomCenter).padding(bottom = 32.dp))
        }
    }
}

/** Own restart scope: the per-second HUD updates don't recompose the root. */
@Composable
private fun HudLayer(model: UiModel, modifier: Modifier, onRoleChosen: (DeviceRole) -> Unit) {
    val hud = model.hud
    if (model.hudVisible && hud != null) {
        HudOverlay(hud, modifier.windowInsetsPadding(WindowInsets.displayCutout), onRoleChosen)
    }
}

/** Brief reminder of the HUD gesture at the start of each connection (spec phase 4 §4.5). */
@Composable
private fun GestureHint(streaming: Boolean, generation: Int, modifier: Modifier) {
    var visible by remember { mutableStateOf(false) }
    LaunchedEffect(streaming, generation) {
        visible = streaming
        if (streaming) {
            delay(HINT_DURATION_MS)
            visible = false
        }
    }
    AnimatedVisibility(visible = visible, modifier = modifier, enter = fadeIn(tween(300)), exit = fadeOut(tween(600))) {
        GlassPanel { GlassText(tr(S.HINT_HUD_SHORT), size = 13.sp) }
    }
}

private const val HINT_DURATION_MS = 4000L
