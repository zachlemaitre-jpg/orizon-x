package com.orizonx.client

import android.os.Bundle
import android.view.Surface
import android.view.View
import android.view.WindowInsets
import android.view.WindowInsetsController
import android.view.WindowManager
import androidx.activity.ComponentActivity
import androidx.activity.SystemBarStyle
import androidx.activity.compose.setContent
import androidx.activity.enableEdgeToEdge
import com.orizonx.client.input.TouchForwarder
import com.orizonx.client.ui.OrizonXApp

class MainActivity : ComponentActivity() {
    private val model = UiModel()
    private var receiver: Receiver? = null

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        enableEdgeToEdge(
            statusBarStyle = SystemBarStyle.dark(android.graphics.Color.TRANSPARENT),
            navigationBarStyle = SystemBarStyle.dark(android.graphics.Color.TRANSPARENT),
        )
        window.addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON)
        val screen = screenInfo()
        setContent { OrizonXApp(model, screen, ::onVideoView, ::onSurfaceCreated, ::onSurfaceDestroyed) }
    }

    override fun onResume() {
        super.onResume()
        hideSystemBars() // certains OEM réaffichent les barres après un passage en arrière-plan
    }

    private fun hideSystemBars() {
        window.insetsController?.let {
            it.hide(WindowInsets.Type.systemBars())
            it.systemBarsBehavior = WindowInsetsController.BEHAVIOR_SHOW_TRANSIENT_BARS_BY_SWIPE
        }
    }

    /** Physical screen size in landscape orientation. */
    private fun screenInfo(): ScreenInfo {
        val bounds = windowManager.maximumWindowMetrics.bounds
        return ScreenInfo(
            width = maxOf(bounds.width(), bounds.height()),
            height = minOf(bounds.width(), bounds.height()),
            dpi = resources.displayMetrics.densityDpi,
        )
    }

    private fun onVideoView(view: View) {
        TouchForwarder(
            view = view,
            currentSession = { if (model.state is ConnectionState.Streaming) model.streamGeneration else null },
            send = { receiver?.sendInput(it) },
            onToggleHud = model::toggleHud,
        ).attach()
    }

    private fun onSurfaceCreated(surface: Surface) {
        receiver?.stop()
        receiver = Receiver(surface, screenInfo(), model)
    }

    private fun onSurfaceDestroyed() {
        receiver?.stop()
        receiver = null
        model.showWaiting(null) // au retour, l'écran d'attente plutôt qu'un écran noir en état « Streaming »
    }
}
