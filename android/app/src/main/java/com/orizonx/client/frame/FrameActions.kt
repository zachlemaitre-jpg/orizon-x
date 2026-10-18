package com.orizonx.client.frame

import com.orizonx.client.frame.FramePlayer.Effect
import com.orizonx.client.i18n.Lang
import com.orizonx.client.i18n.S
import com.orizonx.client.i18n.Strings
import org.json.JSONObject

/**
 * The `frame.*` ACTION payloads (protocol/PROTOCOL.md, "Actions frame.*"). The writer puts `id` first and the other keys
 * in alphabetical order.
 */
object FrameActions {
    private fun id(name: String) = JSONObject().put("id", name)

    fun next(): JSONObject = id("frame.next")
    fun pause(paused: Boolean): JSONObject = id("frame.pause").put("paused", paused)
    fun fit(fit: String): JSONObject = id("frame.fit").put("fit", fit)
    fun interval(seconds: Int): JSONObject = id("frame.interval").put("interval_s", seconds)
    fun failed(file: Long): JSONObject = id("frame.failed").put("file", file)
}

/** The action to send for this effect, or null when it is local (delete a file, show an item). */
fun Effect.toAction(): JSONObject? = when (this) {
    Effect.SendNext -> FrameActions.next()
    is Effect.SendFailed -> FrameActions.failed(file)
    is Effect.SendPause -> FrameActions.pause(paused)
    is Effect.SendFit -> FrameActions.fit(fit)
    is Effect.SendInterval -> FrameActions.interval(seconds)
    is Effect.Release, is Effect.Show -> null
}

object FrameFormat {
    /** "5 s", "1 min", "1 h": the largest whole unit. */
    fun interval(seconds: Int, lang: Lang): String = when {
        seconds >= 3600 && seconds % 3600 == 0 -> Strings.get(S.FRAME_HOURS, lang, "n" to seconds / 3600)
        seconds >= 60 && seconds % 60 == 0 -> Strings.get(S.FRAME_MINUTES, lang, "n" to seconds / 60)
        else -> Strings.get(S.FRAME_SECONDS, lang, "n" to seconds)
    }
}
