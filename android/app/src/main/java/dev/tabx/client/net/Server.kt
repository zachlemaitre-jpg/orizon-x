package dev.tabx.client.net

import dev.tabx.client.protocol.Protocol
import java.io.Closeable
import java.net.InetAddress
import java.net.InetSocketAddress
import java.net.ServerSocket
import java.net.Socket

/**
 * Loopback-only listening socket: reachable through `adb forward`, never from the Wi-Fi.
 * IPv4 explicite : getLoopbackAddress() renvoie ::1 sur Android, alors que adb forward vise 127.0.0.1.
 */
class Server(port: Int = Protocol.PORT) : Closeable {
    private val serverSocket = ServerSocket().apply {
        reuseAddress = true
        bind(InetSocketAddress(InetAddress.getByName("127.0.0.1"), port), 1) // BindException si le port est pris
    }

    fun accept(): Socket = serverSocket.accept()

    override fun close() = serverSocket.close()
}
