package dev.tabx.client.ui

import android.view.Surface
import androidx.compose.animation.AnimatedVisibility
import androidx.compose.animation.core.tween
import androidx.compose.animation.fadeIn
import androidx.compose.animation.fadeOut
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.aspectRatio
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.padding
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
    val state = model.state
    Box(
        Modifier
            .fillMaxSize()
            .background(Color.Black)
            .pointerInput(Unit) { detectThreeFingerTap(model::toggleHud) },
        contentAlignment = Alignment.Center,
    ) {
        val videoModifier = if (state is ConnectionState.Streaming) {
            Modifier.aspectRatio(state.width.toFloat() / state.height)
        } else {
            Modifier.fillMaxSize()
        }
        VideoSurface(videoModifier, onSurfaceCreated, onSurfaceDestroyed)

        AnimatedVisibility(
            visible = state is ConnectionState.Waiting,
            enter = fadeIn(tween(400)),
            exit = fadeOut(tween(400)),
        ) {
            WaitingScreen((state as? ConnectionState.Waiting)?.reason, screen)
        }

        val hud = model.hud
        if (model.hudVisible && hud != null && state is ConnectionState.Streaming) {
            HudOverlay(hud, Modifier.align(Alignment.TopEnd).padding(16.dp))
        }
    }
}
