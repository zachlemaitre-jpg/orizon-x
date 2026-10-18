package com.orizonx.client.protocol

import java.io.BufferedInputStream
import java.io.DataInputStream
import org.json.JSONException
import org.json.JSONObject
import java.io.InputStream
import java.nio.ByteBuffer
import java.nio.charset.CharacterCodingException
import java.nio.charset.CodingErrorAction

/** Reads PC -> tablet messages. Not thread-safe: use from a single reader thread. */
class FrameReader(input: InputStream) {
    private val stream = DataInputStream(BufferedInputStream(input, 64 * 1024))
    private val scratch = ByteArray(8 * 1024)

    /** Blocks until the next known message; unknown types are skipped. Throws EOFException at end of stream. */
    fun read(): PcMessage {
        while (true) {
            val type = stream.readUnsignedByte()
            val flags = stream.readUnsignedByte()
            stream.readUnsignedShort() // reserved
            val length = stream.readInt().toLong() and 0xFFFF_FFFFL
            if (length > Protocol.MAX_PAYLOAD) throw ProtocolException("payload trop gros : $length octets")
            val size = length.toInt()
            when (type) {
                Protocol.TYPE_CONFIG -> {
                    expectSize("CONFIG", size, 7)
                    return PcMessage.Config(
                        codec = stream.readUnsignedByte(),
                        width = stream.readUnsignedShort(),
                        height = stream.readUnsignedShort(),
                        fps = stream.readUnsignedShort(),
                    )
                }
                Protocol.TYPE_VIDEO -> {
                    if (size < 8) throw ProtocolException("VIDEO trop court : $size octets")
                    val ptsUs = stream.readLong()
                    val data = ByteArray(size - 8)
                    stream.readFully(data)
                    return PcMessage.Video(ptsUs, flags, data)
                }
                Protocol.TYPE_PONG -> {
                    expectSize("PONG", size, 16)
                    return PcMessage.Pong(stream.readLong(), stream.readLong())
                }
                Protocol.TYPE_ACTIONS_STATE -> {
                    if (size > Protocol.MAX_JSON) throw ProtocolException("ACTIONS_STATE trop gros : $size octets")
                    val bytes = ByteArray(size)
                    stream.readFully(bytes)
                    return ActionsStateMessage(parseJsonObject("ACTIONS_STATE", bytes))
                }
                Protocol.TYPE_MEDIA_ARTWORK -> {
                    if (size > Protocol.MAX_ARTWORK) throw ProtocolException("MEDIA_ARTWORK trop gros : $size octets")
                    if (size < 1) throw ProtocolException("MEDIA_ARTWORK vide")
                    val idLength = stream.readUnsignedByte()
                    if (idLength == 0) throw ProtocolException("MEDIA_ARTWORK : identifiant vide")
                    if (1 + idLength >= size) throw ProtocolException("MEDIA_ARTWORK : $size octets pour un identifiant de $idLength")
                    val idBytes = ByteArray(idLength)
                    stream.readFully(idBytes)
                    if (idBytes.any { it < 0 }) throw ProtocolException("MEDIA_ARTWORK : identifiant non ASCII")
                    val image = ByteArray(size - 1 - idLength)
                    stream.readFully(image)
                    return MediaArtworkMessage(String(idBytes, Charsets.US_ASCII), image)
                }
                Protocol.TYPE_FRAME_STATE -> {
                    if (size > Protocol.MAX_JSON) throw ProtocolException("FRAME_STATE trop gros : $size octets")
                    val bytes = ByteArray(size)
                    stream.readFully(bytes)
                    return frameState(parseJsonObject("FRAME_STATE", bytes))
                }
                Protocol.TYPE_FRAME_FILE -> {
                    val headerSize = Protocol.FRAME_FILE_HEADER_SIZE
                    if (size <= headerSize) throw ProtocolException("FRAME_FILE : $size octets, aucune donnée")
                    val dataSize = size - headerSize
                    if (dataSize > Protocol.MAX_FRAME_CHUNK) throw ProtocolException("FRAME_FILE : $dataSize octets de données")
                    val epoch = stream.readInt().toLong() and 0xFFFF_FFFFL
                    val id = stream.readInt().toLong() and 0xFFFF_FFFFL
                    val kind = stream.readUnsignedByte()
                    val total = stream.readLong()
                    val offset = stream.readLong()
                    if (kind != Protocol.FRAME_KIND_IMAGE && kind != Protocol.FRAME_KIND_VIDEO) {
                        throw ProtocolException("FRAME_FILE : type de fichier $kind inconnu")
                    }
                    // u64 values with the high bit set read as negative: far beyond any real file, so invalid.
                    if (total < 0 || offset < 0 || offset > total - dataSize) {
                        throw ProtocolException("FRAME_FILE : morceau $offset+$dataSize hors du total $total")
                    }
                    val data = ByteArray(dataSize)
                    stream.readFully(data)
                    return PcMessage.FrameFile(epoch, id, kind, total, offset, data)
                }
                else -> skip(size)
            }
        }
    }

    /** FRAME_STATE is read tolerantly (unknown fields ignored); only an unusable epoch or interval is an error. */
    private fun frameState(json: JSONObject): PcMessage.FrameState {
        val epoch = (json.opt("epoch") as? Number)?.takeIf { it is Int || it is Long }?.toLong()
        if (epoch == null || epoch !in 0..0xFFFF_FFFFL) throw ProtocolException("FRAME_STATE : epoch manquant ou invalide")
        val interval = (json.opt("interval_s") as? Number)?.takeIf { it is Int || it is Long }?.toLong()
        if (interval == null || interval !in 1..Int.MAX_VALUE.toLong()) {
            throw ProtocolException("FRAME_STATE : interval_s manquant ou invalide")
        }
        val status = (json.opt("status") as? String)?.takeIf { it in FRAME_STATUSES } ?: "unreadable"
        return PcMessage.FrameState(
            epoch = epoch,
            status = status,
            folder = json.opt("folder") as? String,
            intervalS = interval.toInt(),
            fit = if (json.opt("fit") == "fit") "fit" else "crop",
            paused = json.opt("paused") == true,
        )
    }

    private companion object {
        val FRAME_STATUSES = setOf("ok", "no_folder", "empty", "unreadable")
    }

    private fun parseJsonObject(name: String, bytes: ByteArray): JSONObject {
        val text = try {
            Charsets.UTF_8.newDecoder()
                .onMalformedInput(CodingErrorAction.REPORT)
                .onUnmappableCharacter(CodingErrorAction.REPORT)
                .decode(ByteBuffer.wrap(bytes))
                .toString()
        } catch (e: CharacterCodingException) {
            throw ProtocolException("$name : UTF-8 invalide")
        }
        try {
            return JSONObject(text)
        } catch (e: JSONException) {
            throw ProtocolException("$name : JSON invalide (${e.message})")
        }
    }

    private fun skip(size: Int) {
        var remaining = size
        while (remaining > 0) {
            val n = minOf(remaining, scratch.size)
            stream.readFully(scratch, 0, n)
            remaining -= n
        }
    }

    private fun expectSize(name: String, actual: Int, expected: Int) {
        if (actual != expected) throw ProtocolException("$name : $actual octets au lieu de $expected")
    }
}
