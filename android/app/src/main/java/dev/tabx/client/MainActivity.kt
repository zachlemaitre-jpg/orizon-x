package dev.tabx.client

import android.os.Bundle
import android.view.Surface
import android.view.WindowInsets
import android.view.WindowInsetsController
import android.view.WindowManager
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import dev.tabx.client.ui.TabXApp

class MainActivity : ComponentActivity() {
    private val model = UiModel()
    private var receiver: Receiver? = null

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        window.addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON)
        window.setDecorFitsSystemWindows(false)
        val screen = screenInfo()
        setContent { TabXApp(model, screen, ::onSurfaceCreated, ::onSurfaceDestroyed) }
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
