package dev.tabx.client.ui

import android.view.Surface
import android.view.SurfaceHolder
import android.view.SurfaceView
import androidx.compose.foundation.gestures.awaitEachGesture
import androidx.compose.foundation.gestures.awaitFirstDown
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.input.pointer.PointerEventPass
import androidx.compose.ui.input.pointer.PointerInputScope
import androidx.compose.ui.unit.sp
import androidx.compose.ui.viewinterop.AndroidView
import dev.tabx.client.HudData

/** SurfaceView whose Surface feeds MediaCodec. Lifecycle callbacks drive the Receiver. */
@Composable
fun VideoSurface(modifier: Modifier, onCreated: (Surface) -> Unit, onDestroyed: () -> Unit) {
    AndroidView(
        modifier = modifier,
        factory = { context ->
            SurfaceView(context).apply {
                holder.addCallback(object : SurfaceHolder.Callback {
                    override fun surfaceCreated(holder: SurfaceHolder) = onCreated(holder.surface)
                    override fun surfaceChanged(holder: SurfaceHolder, format: Int, width: Int, height: Int) {}
                    override fun surfaceDestroyed(holder: SurfaceHolder) = onDestroyed()
                })
            }
        },
    )
}

@Composable
fun HudOverlay(hud: HudData, modifier: Modifier = Modifier) {
    GlassPanel(modifier) {
        GlassText("${hud.fps} fps", size = 12.sp, mono = true)
        GlassText("envoi→aff. %.1f / max %.1f ms".format(hud.avgMs, hud.maxMs), size = 12.sp, mono = true)
        GlassText("p50 ${hud.p50Ms} / p99 ${hud.p99Ms} ms", size = 12.sp, mono = true)
        GlassText(hud.offsetMs?.let { "offset %+.1f ms".format(it) } ?: "offset : synchro…", size = 12.sp, mono = true)
        GlassText(hud.decoder, size = 11.sp, alpha = 0.7f, mono = true)
    }
}

/** Calls [onTap] once each time three or more fingers are down together. */
suspend fun PointerInputScope.detectThreeFingerTap(onTap: () -> Unit) {
    awaitEachGesture {
        awaitFirstDown(requireUnconsumed = false, pass = PointerEventPass.Initial)
        var fired = false
        do {
            val event = awaitPointerEvent(PointerEventPass.Initial)
            if (!fired && event.changes.count { it.pressed } >= 3) {
                onTap()
                fired = true
            }
        } while (event.changes.any { it.pressed })
    }
}
