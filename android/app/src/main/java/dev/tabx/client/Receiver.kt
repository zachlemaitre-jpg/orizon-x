package dev.tabx.client

import android.util.Log
import android.view.Surface
import dev.tabx.client.net.Server
import dev.tabx.client.protocol.Protocol
import dev.tabx.client.protocol.ProtocolException
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
    private val worker = thread(name = "net-reader") { loop() }

    private fun loop() {
        var reason: String? = null
        while (running) {
            model.showWaiting(reason)
            try {
                val listening = server ?: Server().also { server = it }
                val connection = listening.accept().also { socket = it }
                Session(connection, surface, screen, model).run()
            } catch (e: BindException) {
                reason = "Port ${Protocol.PORT} déjà utilisé, nouvel essai…"
                model.showWaiting(reason)
                try {
                    Thread.sleep(BIND_RETRY_MS)
                } catch (_: InterruptedException) {
                    return
                }
            } catch (e: SocketTimeoutException) {
                reason = "Le PC ne répond plus"
            } catch (e: ProtocolException) {
                reason = "Protocole invalide : ${e.message}"
            } catch (e: IOException) {
                reason = "PC déconnecté"
            } catch (e: Exception) {
                Log.e(TAG, "session interrompue", e)
                reason = "Erreur : ${e.message}"
            }
        }
    }

    /** Closes sockets and waits briefly so the decoder is released before the Surface goes away. */
    fun stop() {
        running = false
        worker.interrupt()
        runCatching { server?.close() }
        runCatching { socket?.close() }
        worker.join(STOP_TIMEOUT_MS)
    }

    private companion object {
        const val TAG = "Receiver"
        const val BIND_RETRY_MS = 2000L
        const val STOP_TIMEOUT_MS = 1000L
    }
}
