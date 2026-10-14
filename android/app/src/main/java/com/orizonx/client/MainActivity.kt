package com.orizonx.client

import android.content.pm.ActivityInfo
import android.content.res.Configuration
import android.os.LocaleList
import android.os.Bundle
import android.os.Build
import android.view.Surface
import android.view.View
import android.view.WindowInsets
import android.view.WindowInsetsController
import android.view.WindowManager
import androidx.activity.ComponentActivity
import androidx.activity.SystemBarStyle
import androidx.activity.compose.setContent
import androidx.activity.enableEdgeToEdge
import com.orizonx.client.i18n.LangPref
import com.orizonx.client.i18n.LangStore
import com.orizonx.client.input.TouchForwarder
import com.orizonx.client.video.DecoderCaps
import com.orizonx.client.ui.OrizonXApp

class MainActivity : ComponentActivity() {
    private val model = UiModel()
    private var receiver: Receiver? = null
    private lateinit var roleStore: RoleStore
    private lateinit var langStore: LangStore

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        val prefs = getSharedPreferences("orizonx", MODE_PRIVATE)
        roleStore = RoleStore(prefs, smallestWidthDp())
        langStore = LangStore(prefs)
        model.chooseLangPref(langStore.load())
        model.updateSystemLanguage(LocaleList.getDefault()[0].language)
        model.chooseRole(roleStore.load())
        applyOrientation(model.role)
        enableEdgeToEdge(
            statusBarStyle = SystemBarStyle.dark(android.graphics.Color.TRANSPARENT),
            navigationBarStyle = SystemBarStyle.dark(android.graphics.Color.TRANSPARENT),
        )
        window.addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON)
        val screen = screenInfo()
        setContent {
            OrizonXApp(model, screen, ::onVideoView, ::onSurfaceCreated, ::onSurfaceDestroyed, ::onRoleChosen, ::onLangPrefChosen, ::onAction)
        }
    }

    /** The activity handles `locale` itself (see the manifest): follow the system language without being recreated. */
    override fun onConfigurationChanged(newConfig: Configuration) {
        super.onConfigurationChanged(newConfig)
        val locales = newConfig.locales
        model.updateSystemLanguage(if (locales.isEmpty) LocaleList.getDefault()[0].language else locales[0].language)
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

    private fun smallestWidthDp() = resources.configuration.smallestScreenWidthDp

    /** Landscape-only to stream (as before); free rotation for the Actions remote. */
    private fun applyOrientation(role: DeviceRole) {
        requestedOrientation = when (role) {
            DeviceRole.SCREEN -> ActivityInfo.SCREEN_ORIENTATION_SENSOR_LANDSCAPE
            DeviceRole.ACTIONS -> ActivityInfo.SCREEN_ORIENTATION_FULL_SENSOR
        }
    }

    /** Hardware decoder limits for the native screen size; computed once (MediaCodecList queries are not free). */
    private val videoCaps by lazy {
        val screen = screenInfo()
        DecoderCaps.best(screen.width, screen.height, DecoderCaps.system())
    }

    private fun currentDeviceInfo() = deviceInfoFor(model.role, smallestWidthDp(), Build.MODEL, appVersion(), videoCaps, model.lang)

    private fun appVersion(): String = try {
        packageManager.getPackageInfo(packageName, 0).versionName ?: "?"
    } catch (_: Exception) {
        "?"
    }

    /** Waiting-screen button: persist, rotate, and drop the PC connection so the PC reconnects with the new role. */
    private fun onRoleChosen(role: DeviceRole) {
        if (role == model.role) return
        roleStore.save(role)
        model.chooseRole(role)
        applyOrientation(role)
        receiver?.closeConnection()
    }

    /** Language pill: persist the choice; the UI follows at once and Actions sessions tell the PC (see ActionsScreen). */
    private fun onLangPrefChosen(pref: LangPref) {
        langStore.save(pref)
        model.chooseLangPref(pref)
    }

    private fun onAction(json: org.json.JSONObject) {
        receiver?.sendAction(json)
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
        receiver = Receiver(surface, screenInfo(), model, ::currentDeviceInfo)
    }

    private fun onSurfaceDestroyed() {
        receiver?.stop()
        receiver = null
        model.showWaiting(null) // au retour, l'écran d'attente plutôt qu'un écran noir en état « Streaming »
    }
}
