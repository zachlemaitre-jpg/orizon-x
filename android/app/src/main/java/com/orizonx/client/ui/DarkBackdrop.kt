package com.orizonx.client.ui

import android.content.Context
import android.content.ContextWrapper
import androidx.activity.ComponentActivity
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableFloatStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.runtime.withFrameNanos
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.drawBehind
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalContext
import androidx.lifecycle.Lifecycle
import androidx.lifecycle.LifecycleEventObserver
import com.orizonx.client.backdrop.BackdropMotion
import kotlin.math.max

private val BackdropBase = Color(0xFF0A0A0B)

/** Frame interval of the drift: it is slow, so about 30 images a second is plenty and spares the battery. */
private const val FRAME_STEP_NS = 32_000_000L

/**
 * The backdrop of the app: a near-black base, a faint diagonal gradient, and a few large, very soft patches of dark grey
 * that drift slowly ([BackdropMotion]). No hue, no hard edge, no blur layer: a single `drawBehind`, so the glass panels on
 * top stay readable and nothing offscreen is created.
 *
 * The time is only read while drawing, so the content above never recomposes because of it. The drift stops when the app
 * is not resumed, and it does not exist while the video stream is shown (this is not composed then).
 */
@Composable
fun DarkBackdrop(modifier: Modifier = Modifier) {
    val resumed = rememberResumed()
    val time = remember { mutableFloatStateOf(0f) }
    LaunchedEffect(resumed) {
        if (!resumed) return@LaunchedEffect
        var last = -1L
        while (true) {
            withFrameNanos { now ->
                if (last < 0) {
                    last = now
                } else if (now - last >= FRAME_STEP_NS) {
                    // Keep the time continuous after a pause: never advance more than a tenth of a second at once.
                    val seconds = (now - last).coerceAtMost(100_000_000L) / 1e9f
                    time.floatValue += seconds
                    last = now
                }
            }
        }
    }
    Box(
        modifier
            .fillMaxSize()
            .drawBehind {
                val w = size.width
                val h = size.height
                val longSide = max(w, h)
                drawRect(BackdropBase)
                drawRect(
                    Brush.linearGradient(
                        listOf(Color(0xFF121214), Color(0xFF0A0A0B), Color(0xFF0E0E10)),
                        start = Offset.Zero,
                        end = Offset(w, h),
                    ),
                )
                val t = time.floatValue
                for (patch in BackdropMotion.PATCHES) {
                    val center = Offset(BackdropMotion.x(patch, t) * w, BackdropMotion.y(patch, t) * h)
                    val radius = BackdropMotion.radius(patch, t) * longSide
                    val grey = Color(patch.argb)
                    drawCircle(
                        Brush.radialGradient(
                            0f to grey.copy(alpha = 0.95f),
                            0.55f to grey.copy(alpha = 0.45f),
                            1f to grey.copy(alpha = 0f),
                            center = center,
                            radius = radius,
                        ),
                        radius = radius,
                        center = center,
                    )
                }
            },
    )
}


/** True while the activity is RESUMED; false when it is paused or stopped (screen off, other app on top). */
@Composable
private fun rememberResumed(): Boolean {
    val activity = findActivity(LocalContext.current)
    var resumed by remember { mutableStateOf(activity?.lifecycle?.currentState?.isAtLeast(Lifecycle.State.RESUMED) ?: true) }
    DisposableEffect(activity) {
        val lifecycle = activity?.lifecycle
        val observer = LifecycleEventObserver { _, _ ->
            resumed = lifecycle?.currentState?.isAtLeast(Lifecycle.State.RESUMED) ?: true
        }
        lifecycle?.addObserver(observer)
        onDispose { lifecycle?.removeObserver(observer) }
    }
    return resumed
}

private fun findActivity(context: Context): ComponentActivity? {
    var c = context
    while (c is ContextWrapper) {
        if (c is ComponentActivity) return c
        c = c.baseContext
    }
    return null
}
