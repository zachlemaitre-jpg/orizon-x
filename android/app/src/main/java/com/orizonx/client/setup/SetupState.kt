package com.orizonx.client.setup

import android.content.Context
import android.content.Intent
import android.content.IntentFilter
import android.os.BatteryManager
import android.provider.Settings

/** Live facts about the device; null means the read failed (unknown). */
interface SetupProbe {
    fun devOptions(): Boolean?
    fun usbDebugging(): Boolean?
    fun usbPlugged(): Boolean?
}

/** State of the three checkable steps (developer options, USB debugging, USB cable). */
data class SetupSteps(val devOptions: Boolean?, val usbDebugging: Boolean?, val usbPlugged: Boolean?) {
    /** Step to highlight, 1..3, or 4 (the tip) once the three are done. Unknown counts as not done. */
    val current: Int
        get() = when {
            devOptions != true -> 1
            usbDebugging != true -> 2
            usbPlugged != true -> 3
            else -> 4
        }

    /** The guide opens by itself while USB debugging is not confirmed on. */
    val autoOpen: Boolean get() = usbDebugging != true

    companion object {
        fun read(probe: SetupProbe) = SetupSteps(probe.devOptions(), probe.usbDebugging(), probe.usbPlugged())
    }
}

class AndroidSetupProbe(private val context: Context) : SetupProbe {
    private fun globalFlag(name: String): Boolean? = try {
        Settings.Global.getInt(context.contentResolver, name, 0) == 1
    } catch (_: Exception) {
        null
    }

    override fun devOptions() = globalFlag(Settings.Global.DEVELOPMENT_SETTINGS_ENABLED)

    override fun usbDebugging() = globalFlag(Settings.Global.ADB_ENABLED)

    override fun usbPlugged(): Boolean? = try {
        val battery = context.registerReceiver(null, IntentFilter(Intent.ACTION_BATTERY_CHANGED))
        battery?.let { it.getIntExtra(BatteryManager.EXTRA_PLUGGED, 0) == BatteryManager.BATTERY_PLUGGED_USB }
    } catch (_: Exception) {
        null
    }
}
