package dev.tabx.client

import android.os.Process
import android.util.Log
import android.view.Surface
import dev.tabx.client.net.Server
import dev.tabx.client.protocol.Protocol
import dev.tabx.client.protocol.ProtocolException
import dev.tabx.client.protocol.TabletMessage
import dev.tabx.client.video.DecoderUnavailable
import java.io.IOException
import java.net.BindException
import java.net.Socket
import java.net.SocketTimeoutException
import kotlin.concurrent.thread

/** Accept loop on the "net-reader" thread: one [Session] at a time until [stop]. */
class Receiver(
    private val surface: Surface,
    private val screen: ScreenInfo,
    private val model: UiModel,
) {
    @Volatile private var running = true
    @Volatile private var server: Server? = null
    @Volatile private var socket: Socket? = null
    @Volatile private var session: Session? = null
    private val worker = thread(name = "net-reader") { loop() }

    /** Forwards an INPUT frame to the running session, if any. */
    fun sendInput(message: TabletMessage.Input) {
        session?.sendInput(message)
    }

    private fun loop() {
        Process.setThreadPriority(Process.THREAD_PRIORITY_DISPLAY)
        var reason: String? = null
        try {
            while (running) {
                model.showWaiting(reason)
                try {
                    val listening = server ?: Server().also { server = it }
                    // stop() écrit `running` puis lit `server` ; ici on écrit `server` puis on relit `running` :
                    // les deux champs étant volatiles, au moins un des deux côtés voit l'autre.
                    if (!running) break
                    val connection = listening.accept().also { socket = it }
                    if (!running) {
                        connection.close()
                        break
                    }
                    val current = Session(connection, surface, screen, model)
                    session = current
                    try {
                        current.run()
                    } finally {
                        session = null
                    }
                } catch (e: BindException) {
                    reason = "Port ${Protocol.PORT} déjà utilisé, nouvel essai…"
                    model.showWaiting(reason)
                    if (!pause()) break
                } catch (e: SocketTimeoutException) {
                    reason = "Le PC ne répond plus"
                } catch (e: ProtocolException) {
                    reason = "Protocole invalide : ${e.message}"
                } catch (e: DecoderUnavailable) {
                    Log.e(TAG, "décodeur indisponible", e)
                    reason = "Décodeur indisponible : ${e.message}"
                } catch (e: InterruptedException) {
                    break
                } catch (e: IOException) {
                    if (!running) break
                    if (server == null) {
                        reason = "Écoute impossible : ${e.message ?: e.javaClass.simpleName}"
                        if (!pause()) break
                    } else {
                        reason = "PC déconnecté"
                    }
                } catch (e: Exception) {
                    if (!running) break
                    Log.e(TAG, "session interrompue", e)
                    reason = "Erreur : ${e.message ?: e.javaClass.simpleName}"
                }
            }
        } finally {
            runCatching { server?.close() }
        }
    }

    /** Sleeps before retrying; returns false if [stop] interrupted the wait. */
    private fun pause(): Boolean = try {
        Thread.sleep(RETRY_MS)
        true
    } catch (_: InterruptedException) {
        false
    }

    /** Closes sockets and waits briefly so the decoder is released before the Surface goes away. */
    fun stop() {
        running = false
        worker.interrupt()
        runCatching { server?.close() }
        runCatching { socket?.close() }
        worker.join(STOP_TIMEOUT_MS)
        if (worker.isAlive) Log.w(TAG, "net-reader encore actif après $STOP_TIMEOUT_MS ms")
    }

    private companion object {
        const val TAG = "Receiver"
        const val RETRY_MS = 2000L
        const val STOP_TIMEOUT_MS = 1000L
    }
}
