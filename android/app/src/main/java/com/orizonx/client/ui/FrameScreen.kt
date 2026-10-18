package com.orizonx.client.ui

import android.content.Context
import android.graphics.BitmapFactory
import android.graphics.Matrix
import android.graphics.SurfaceTexture
import android.media.MediaPlayer
import android.os.SystemClock
import android.view.Surface
import android.view.TextureView
import androidx.compose.animation.AnimatedVisibility
import androidx.compose.animation.Crossfade
import androidx.compose.animation.core.tween
import androidx.compose.animation.fadeIn
import androidx.compose.animation.fadeOut
import androidx.compose.foundation.Image
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.gestures.detectTapGestures
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.BoxWithConstraints
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.WindowInsets
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.safeDrawing
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.widthIn
import androidx.compose.foundation.layout.windowInsetsPadding
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.SideEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberUpdatedState
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.ColorFilter
import androidx.compose.ui.graphics.ImageBitmap
import androidx.compose.ui.graphics.asImageBitmap
import androidx.compose.ui.hapticfeedback.HapticFeedbackType
import androidx.compose.ui.input.pointer.pointerInput
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.platform.LocalHapticFeedback
import androidx.compose.ui.platform.LocalView
import androidx.compose.ui.res.painterResource
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.compose.ui.viewinterop.AndroidView
import com.orizonx.client.R
import com.orizonx.client.frame.FrameController
import com.orizonx.client.frame.FrameFormat
import com.orizonx.client.frame.FrameGeometry
import com.orizonx.client.frame.FrameItem
import com.orizonx.client.i18n.LocalLang
import com.orizonx.client.i18n.S
import com.orizonx.client.i18n.tr
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.delay
import kotlinx.coroutines.withContext

private const val FADE_MS = 1000
private const val BAR_MS = 5000L
private const val TICK_MS = 200L

/**
 * Frame mode: the images and videos of the PC folder, full screen on black, with a 1 s crossfade between them.
 * A tap shows a control bar for 5 s (pause/play, next, crop/fit, interval); [onSwitchMode] leaves Frame mode.
 */
@Composable
fun FrameScreen(frame: FrameController, onSwitchMode: () -> Unit) {
    val view = frame.view
    val host = LocalView.current
    DisposableEffect(host) {
        host.keepScreenOn = true
        onDispose { host.keepScreenOn = false }
    }
    val haptics = LocalHapticFeedback.current

    var barVisible by remember { mutableStateOf(false) }
    var barTouch by remember { mutableIntStateOf(0) }
    LaunchedEffect(barVisible, barTouch) {
        if (barVisible) {
            delay(BAR_MS)
            barVisible = false
        }
    }
    // A press on the bar restarts the 5 s and gives a haptic tick.
    val press: (() -> Unit) -> Unit = { action ->
        haptics.performHapticFeedback(HapticFeedbackType.ContextClick)
        barTouch++
        action()
    }

    // The timer of an image only runs while one is shown and not paused.
    val timerRuns = view.current?.isImage == true && !view.paused
    LaunchedEffect(timerRuns, view.current?.id) {
        if (timerRuns) {
            var last = SystemClock.elapsedRealtime()
            while (true) {
                delay(TICK_MS)
                val now = SystemClock.elapsedRealtime()
                frame.tick(now - last)
                last = now
            }
        }
    }

    BoxWithConstraints(
        Modifier
            .fillMaxSize()
            .background(Color.Black)
            .pointerInput(Unit) {
                detectTapGestures(onTap = {
                    barVisible = !barVisible
                    barTouch++
                })
            },
    ) {
        // Decode images at most ~2x the screen, whichever way it is turned.
        val decodeLimit = 2 * maxOf(constraints.maxWidth, constraints.maxHeight)
        Crossfade(targetState = view.current, animationSpec = tween(FADE_MS), label = "frame") { item ->
            if (item == null) {
                StatusMessage(view.status)
            } else if (item.isImage) {
                ImageSlide(item, fit = view.fit == "fit", decodeLimit = decodeLimit, onFailed = { frame.playbackFailed(item.id) })
            } else {
                VideoSlide(
                    item,
                    fit = view.fit == "fit",
                    paused = view.paused,
                    onEnded = { frame.videoEnded(item.id) },
                    onFailed = { frame.playbackFailed(item.id) },
                )
            }
        }

        AnimatedVisibility(
            visible = barVisible,
            modifier = Modifier.align(Alignment.TopEnd).windowInsetsPadding(WindowInsets.safeDrawing).padding(16.dp),
            enter = fadeIn(tween(200)),
            exit = fadeOut(tween(300)),
        ) {
            Pill(tr(S.SWITCH_MODE), selected = false, onClick = { press(onSwitchMode) })
        }
        AnimatedVisibility(
            visible = barVisible,
            modifier = Modifier.align(Alignment.BottomCenter).windowInsetsPadding(WindowInsets.safeDrawing).padding(24.dp),
            enter = fadeIn(tween(200)),
            exit = fadeOut(tween(300)),
        ) {
            ControlBar(
                paused = view.paused,
                fit = view.fit,
                intervalS = view.intervalS,
                onPause = { press(frame::togglePause) },
                onNext = { press(frame::next) },
                onFit = { press(frame::toggleFit) },
                onInterval = { delta -> press { frame.stepInterval(delta) } },
            )
        }
    }
}

@Composable
private fun StatusMessage(status: String) {
    val text = when (status) {
        "no_folder" -> S.FRAME_NO_FOLDER
        "empty" -> S.FRAME_EMPTY
        "unreadable" -> S.FRAME_UNREADABLE
        else -> S.FRAME_LOADING
    }
    Box(Modifier.fillMaxSize().padding(32.dp), contentAlignment = Alignment.Center) {
        GlassText(tr(text), size = 20.sp, alpha = 0.85f, align = TextAlign.Center)
    }
}

// --- Images ---------------------------------------------------------------------------------

@Composable
private fun ImageSlide(item: FrameItem, fit: Boolean, decodeLimit: Int, onFailed: () -> Unit) {
    val failed by rememberUpdatedState(onFailed)
    var bitmap by remember(item.id) { mutableStateOf<ImageBitmap?>(null) }
    LaunchedEffect(item.id) {
        val decoded = withContext(Dispatchers.IO) { decodeImage(item.file.path, decodeLimit) }
        if (decoded == null) failed() else bitmap = decoded
    }
    bitmap?.let {
        Image(
            bitmap = it,
            contentDescription = null,
            modifier = Modifier.fillMaxSize(),
            contentScale = if (fit) ContentScale.Fit else ContentScale.Crop,
        )
    }
}

/** Decodes [path] with an `inSampleSize` that keeps each side within [limit]; null when it cannot be decoded. */
private fun decodeImage(path: String, limit: Int): ImageBitmap? = try {
    val bounds = BitmapFactory.Options().apply { inJustDecodeBounds = true }
    BitmapFactory.decodeFile(path, bounds)
    if (bounds.outWidth <= 0 || bounds.outHeight <= 0) {
        null
    } else {
        val options = BitmapFactory.Options().apply {
            inSampleSize = FrameGeometry.sampleSize(bounds.outWidth, bounds.outHeight, limit, limit)
        }
        BitmapFactory.decodeFile(path, options)?.asImageBitmap()
    }
} catch (_: Exception) {
    null
} catch (_: OutOfMemoryError) {
    null
}

// --- Videos ---------------------------------------------------------------------------------

@Composable
private fun VideoSlide(item: FrameItem, fit: Boolean, paused: Boolean, onEnded: () -> Unit, onFailed: () -> Unit) {
    val ended by rememberUpdatedState(onEnded)
    val failed by rememberUpdatedState(onFailed)
    val holder = remember(item.id) { VideoHolder(item.file.path, { ended() }, { failed() }) }
    SideEffect { holder.update(fit, paused) }
    DisposableEffect(holder) { onDispose { holder.release() } }
    AndroidView(factory = { holder.createView(it) }, modifier = Modifier.fillMaxSize())
}

/** One video: a silent [MediaPlayer] drawing into a [TextureView] whose matrix gives Crop or Fit. Main thread only. */
private class VideoHolder(
    private val path: String,
    private val onEnded: () -> Unit,
    private val onFailed: () -> Unit,
) {
    private var textureView: TextureView? = null
    private var player: MediaPlayer? = null
    private var surface: Surface? = null
    private var prepared = false
    private var completed = false
    private var released = false
    private var videoWidth = 0
    private var videoHeight = 0
    private var fit = false
    private var paused = false

    fun createView(context: Context): TextureView = TextureView(context).also { view ->
        textureView = view
        view.surfaceTextureListener = object : TextureView.SurfaceTextureListener {
            override fun onSurfaceTextureAvailable(texture: SurfaceTexture, width: Int, height: Int) {
                startPlayer(texture)
                applyTransform()
            }

            override fun onSurfaceTextureSizeChanged(texture: SurfaceTexture, width: Int, height: Int) = applyTransform()

            override fun onSurfaceTextureDestroyed(texture: SurfaceTexture): Boolean {
                stopPlayer()
                return true
            }

            override fun onSurfaceTextureUpdated(texture: SurfaceTexture) = Unit
        }
    }

    fun update(fit: Boolean, paused: Boolean) {
        this.fit = fit
        this.paused = paused
        applyTransform()
        applyPlayState()
    }

    fun release() {
        released = true
        textureView?.surfaceTextureListener = null
        stopPlayer()
    }

    private fun startPlayer(texture: SurfaceTexture) {
        if (released) return
        stopPlayer()
        val target = Surface(texture)
        surface = target
        try {
            val mp = MediaPlayer()
            player = mp
            mp.setSurface(target)
            mp.setVolume(0f, 0f)
            mp.setDataSource(path)
            mp.setOnVideoSizeChangedListener { _, width, height ->
                videoWidth = width
                videoHeight = height
                applyTransform()
            }
            mp.setOnPreparedListener {
                prepared = true
                applyPlayState()
            }
            mp.setOnCompletionListener {
                completed = true
                if (!released) onEnded()
            }
            mp.setOnErrorListener { _, _, _ ->
                if (!released) onFailed()
                true
            }
            mp.prepareAsync()
        } catch (_: Exception) {
            if (!released) onFailed()
        }
    }

    private fun stopPlayer() {
        player?.let { runCatching { it.release() } }
        player = null
        surface?.let { runCatching { it.release() } }
        surface = null
        prepared = false
    }

    private fun applyTransform() {
        val view = textureView ?: return
        val (scaleX, scaleY) = FrameGeometry.videoScale(view.width, view.height, videoWidth, videoHeight, fit)
        view.setTransform(Matrix().apply { setScale(scaleX, scaleY, view.width / 2f, view.height / 2f) })
    }

    private fun applyPlayState() {
        val mp = player ?: return
        if (!prepared || completed) return
        try {
            if (paused) {
                if (mp.isPlaying) mp.pause()
            } else if (!mp.isPlaying) {
                mp.start()
            }
        } catch (_: IllegalStateException) {
            // The player was released between the check and the call: nothing to do.
        }
    }
}

// --- Control bar ----------------------------------------------------------------------------

/** Glass bar: pause/play, next and crop/fit on one line, the interval stepper below. */
@Composable
private fun ControlBar(
    paused: Boolean,
    fit: String,
    intervalS: Int,
    onPause: () -> Unit,
    onNext: () -> Unit,
    onFit: () -> Unit,
    onInterval: (Int) -> Unit,
) {
    val displayLabel = tr(if (fit == "fit") S.FRAME_FIT else S.FRAME_CROP)
    val displayDescription = tr(S.FRAME_DISPLAY_DESC, "value" to displayLabel)
    GlassPanel {
        Row(
            Modifier.align(Alignment.CenterHorizontally),
            verticalAlignment = Alignment.CenterVertically,
            horizontalArrangement = Arrangement.spacedBy(14.dp),
        ) {
            BarButton(tr(if (paused) S.FRAME_PLAY_DESC else S.FRAME_PAUSE_DESC), onPause) {
                BarIcon(if (paused) R.drawable.ox_play else R.drawable.ox_pause)
            }
            BarButton(tr(S.FRAME_NEXT_DESC), onNext) { BarIcon(R.drawable.ox_next_right) }
            Pill(displayLabel, selected = false, onClick = onFit, modifier = Modifier.semantics { contentDescription = displayDescription })
        }
        Spacer(Modifier.height(10.dp))
        Row(
            Modifier.align(Alignment.CenterHorizontally),
            verticalAlignment = Alignment.CenterVertically,
            horizontalArrangement = Arrangement.spacedBy(14.dp),
        ) {
            BarButton(tr(S.FRAME_INTERVAL_LESS_DESC), { onInterval(-1) }) { GlassText("−", size = 26.sp) }
            Box(Modifier.widthIn(min = 76.dp), contentAlignment = Alignment.Center) {
                GlassText(FrameFormat.interval(intervalS, LocalLang.current), size = 17.sp, weight = FontWeight.SemiBold)
            }
            BarButton(tr(S.FRAME_INTERVAL_MORE_DESC), { onInterval(+1) }) { GlassText("+", size = 26.sp) }
        }
    }
}

@Composable
private fun BarButton(description: String, onClick: () -> Unit, content: @Composable () -> Unit) {
    Box(
        Modifier
            .size(56.dp)
            .clip(CircleShape)
            .background(Color.White.copy(alpha = 0.10f))
            .border(1.dp, Color.White.copy(alpha = 0.25f), CircleShape)
            .semantics { contentDescription = description }
            .clickable(onClick = onClick),
        contentAlignment = Alignment.Center,
    ) {
        content()
    }
}

@Composable
private fun BarIcon(drawable: Int) {
    Image(painterResource(drawable), contentDescription = null, modifier = Modifier.size(28.dp), colorFilter = ColorFilter.tint(Color.White))
}
