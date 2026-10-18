package com.orizonx.client.frame

import com.orizonx.client.protocol.PcMessage
import com.orizonx.client.protocol.Protocol
import java.io.File
import java.io.FileOutputStream
import java.io.IOException

/** A completely received Frame mode file, ready to show. [kind] is [Protocol.FRAME_KIND_IMAGE] or [Protocol.FRAME_KIND_VIDEO]. */
data class FrameItem(val id: Long, val kind: Int, val file: File) {
    val isImage: Boolean get() = kind == Protocol.FRAME_KIND_IMAGE
    val isVideo: Boolean get() = kind == Protocol.FRAME_KIND_VIDEO
}

/**
 * Rebuilds the files of FRAME_FILE chunks inside [dir] (the app cache). Thread-safe.
 *
 * Chunks of a file must arrive in order with no gap; a chunk that breaks that drops the file ([Result.Rejected], reported
 * once: the rest of that file is then ignored). At most [MAX_KEPT] completed files stay on disk.
 */
class FrameStore(private val dir: File) {
    sealed interface Result {
        /** The chunk was stored, the file is not complete yet. */
        data object Partial : Result

        /** The last chunk arrived: [item] is ready. */
        data class Complete(val item: FrameItem) : Result

        /** Out of order, or an offset/total that does not match what was received: the file [id] is dropped. */
        data class Rejected(val id: Long) : Result

        /** Ignored: another epoch, no epoch started, or the remainder of a file already rejected. */
        data object Stale : Result
    }

    private class Open(val id: Long, val kind: Int, val total: Long, val file: File, val out: FileOutputStream) {
        var received = 0L
    }

    private var epoch: Long? = null
    private var open: Open? = null
    private val completed = ArrayDeque<FrameItem>()
    private val rejected = HashSet<Long>()

    /** Makes [epoch] the current one: files of any other epoch (complete or partial) are deleted. The same epoch again changes nothing. */
    @Synchronized
    fun begin(epoch: Long) {
        if (this.epoch == epoch) return
        this.epoch = epoch
        abortOpen()
        completed.clear()
        rejected.clear()
        deleteFiles { !it.name.startsWith("$epoch-") }
    }

    @Synchronized
    fun onChunk(chunk: PcMessage.FrameFile): Result {
        val current = epoch
        if (current == null || chunk.epoch != current) return Result.Stale
        if (chunk.id in rejected) return Result.Stale
        var target = open
        if (chunk.offset == 0L) {
            abortOpen() // a restarted file replaces the partial one
            dir.mkdirs()
            val file = File(dir, "$current-${chunk.id}.${if (chunk.kind == Protocol.FRAME_KIND_VIDEO) "vid" else "jpg"}")
            target = try {
                Open(chunk.id, chunk.kind, chunk.total, file, FileOutputStream(file))
            } catch (e: IOException) {
                return reject(chunk.id, null)
            }
            open = target
        } else if (target == null || target.id != chunk.id || chunk.offset != target.received || chunk.total != target.total) {
            return reject(chunk.id, target?.takeIf { it.id == chunk.id })
        }
        val file = target!!
        try {
            file.out.write(chunk.data)
        } catch (e: IOException) {
            return reject(chunk.id, file)
        }
        file.received += chunk.data.size
        if (file.received < file.total) return Result.Partial
        runCatching { file.out.close() }
        open = null
        val item = FrameItem(file.id, file.kind, file.file)
        completed.addLast(item)
        while (completed.size > MAX_KEPT) completed.removeFirst().file.delete()
        return Result.Complete(item)
    }

    /** Deletes a file that was shown. */
    @Synchronized
    fun release(id: Long) {
        val item = completed.firstOrNull { it.id == id } ?: return
        completed.remove(item)
        item.file.delete()
    }

    /** Session start and end: forgets the epoch and deletes everything, leftovers of a previous run included. */
    @Synchronized
    fun clear() {
        epoch = null
        abortOpen()
        completed.clear()
        rejected.clear()
        deleteFiles { true }
    }

    private fun reject(id: Long, partial: Open?): Result {
        if (partial != null) {
            if (open === partial) open = null
            runCatching { partial.out.close() }
            partial.file.delete()
        }
        rejected.add(id)
        return Result.Rejected(id)
    }

    private fun abortOpen() {
        val partial = open ?: return
        open = null
        runCatching { partial.out.close() }
        partial.file.delete()
    }

    private fun deleteFiles(filter: (File) -> Boolean) {
        dir.listFiles()?.filter { it.isFile && filter(it) }?.forEach { it.delete() }
    }

    companion object {
        const val MAX_KEPT = 3
    }
}
