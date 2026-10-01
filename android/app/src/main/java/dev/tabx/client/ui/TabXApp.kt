package dev.tabx.client.ui

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
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.input.pointer.pointerInput
import androidx.compose.ui.unit.dp
import dev.tabx.client.ConnectionState
import dev.tabx.client.ScreenInfo
import dev.tabx.client.UiModel

/** Root: letterboxed video, waiting screen on top while disconnected, optional HUD while streaming. */
@Composable
fun TabXApp(
    model: UiModel,
    screen: ScreenInfo,
    onSurfaceCreated: (Surface) -> Unit,
    onSurfaceDestroyed: () -> Unit,
) {
    val streaming = model.state is ConnectionState.Streaming
    Box(
        Modifier
            .fillMaxSize()
            .background(Color.Black)
            .pointerInput(model) {
                detectThreeFingerTap { if (model.state is ConnectionState.Streaming) model.toggleHud() }
            },
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
        VideoSurface(videoModifier, onSurfaceCreated, onSurfaceDestroyed)

        AnimatedVisibility(visible = !streaming, enter = fadeIn(tween(400)), exit = fadeOut(tween(400))) {
            WaitingScreen(model.waitingReason, screen)
        }

        if (streaming) HudLayer(model, Modifier.align(Alignment.TopEnd).padding(16.dp))
    }
}

/** Own restart scope: the per-second HUD updates don't recompose the root. */
@Composable
private fun HudLayer(model: UiModel, modifier: Modifier) {
    val hud = model.hud
    if (model.hudVisible && hud != null) {
        HudOverlay(hud, modifier.windowInsetsPadding(WindowInsets.displayCutout))
    }
}
