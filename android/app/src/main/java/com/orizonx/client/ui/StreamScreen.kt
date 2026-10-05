package com.orizonx.client.ui

import android.view.Surface
import android.view.SurfaceHolder
import android.view.SurfaceView
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.rememberUpdatedState
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.sp
import androidx.compose.ui.viewinterop.AndroidView
import com.orizonx.client.HudData

/** SurfaceView whose Surface feeds MediaCodec; [onView] receives it once (touch forwarding). */
@Composable
fun VideoSurface(
    modifier: Modifier,
    onView: (android.view.View) -> Unit,
    onCreated: (Surface) -> Unit,
    onDestroyed: () -> Unit,
) {
    val created by rememberUpdatedState(onCreated)
    val destroyed by rememberUpdatedState(onDestroyed)
    AndroidView(
        modifier = modifier,
        factory = { context ->
            SurfaceView(context).apply {
                holder.addCallback(object : SurfaceHolder.Callback {
                    override fun surfaceCreated(holder: SurfaceHolder) = created(holder.surface)
                    override fun surfaceChanged(holder: SurfaceHolder, format: Int, width: Int, height: Int) {}
                    override fun surfaceDestroyed(holder: SurfaceHolder) = destroyed()
                })
                onView(this)
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
