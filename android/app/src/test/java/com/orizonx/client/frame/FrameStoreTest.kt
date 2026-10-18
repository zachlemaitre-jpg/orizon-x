package com.orizonx.client.frame

import com.orizonx.client.protocol.PcMessage
import com.orizonx.client.protocol.Protocol
import org.junit.Assert.assertArrayEquals
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Before
import org.junit.Rule
import org.junit.Test
import org.junit.rules.TemporaryFolder
import java.io.File

class FrameStoreTest {
    @get:Rule val tmp = TemporaryFolder()
    private lateinit var dir: File
    private lateinit var store: FrameStore

    @Before fun setUp() {
        dir = File(tmp.root, "frame")
        store = FrameStore(dir)
    }

    private fun chunk(epoch: Long, id: Long, total: Long, offset: Long, data: ByteArray, kind: Int = Protocol.FRAME_KIND_IMAGE) =
        PcMessage.FrameFile(epoch, id, kind, total, offset, data)

    private fun bytes(range: IntRange) = range.map { it.toByte() }.toByteArray()

    private fun files() = dir.listFiles().orEmpty().filter { it.isFile }

    @Test
    fun aFileSplitInChunksIsReassembled() {
        store.begin(3)
        assertEquals(FrameStore.Result.Partial, store.onChunk(chunk(3, 7, 10, 0, bytes(1..5))))
        val done = store.onChunk(chunk(3, 7, 10, 5, bytes(6..10)))
        done as FrameStore.Result.Complete
        assertEquals(7L, done.item.id)
        assertEquals(Protocol.FRAME_KIND_IMAGE, done.item.kind)
        assertArrayEquals(bytes(1..10), done.item.file.readBytes())
    }

    @Test
    fun aSingleChunkFileIsCompleteAtOnce() {
        store.begin(1)
        val done = store.onChunk(chunk(1, 1, 3, 0, bytes(1..3), Protocol.FRAME_KIND_VIDEO))
        done as FrameStore.Result.Complete
        assertEquals(Protocol.FRAME_KIND_VIDEO, done.item.kind)
        assertTrue(done.item.isVideo)
    }

    @Test
    fun aChunkThatDoesNotStartAtZeroIsRejectedOnceThenIgnored() {
        store.begin(3)
        assertEquals(FrameStore.Result.Rejected(7), store.onChunk(chunk(3, 7, 10, 5, bytes(6..10))))
        assertEquals(FrameStore.Result.Stale, store.onChunk(chunk(3, 7, 10, 5, bytes(6..10))))
        assertTrue(files().isEmpty())
    }

    @Test
    fun aGapRejectsTheFileAndDropsItsPartialData() {
        store.begin(3)
        store.onChunk(chunk(3, 7, 12, 0, bytes(1..4)))
        assertEquals(FrameStore.Result.Rejected(7), store.onChunk(chunk(3, 7, 12, 8, bytes(9..12))))
        assertTrue(files().isEmpty())
        // the rest of the rejected file is ignored, the next file works
        assertEquals(FrameStore.Result.Stale, store.onChunk(chunk(3, 7, 12, 4, bytes(5..8))))
        assertTrue(store.onChunk(chunk(3, 8, 2, 0, bytes(1..2))) is FrameStore.Result.Complete)
    }

    @Test
    fun anOverlappingChunkIsRejected() {
        store.begin(3)
        store.onChunk(chunk(3, 7, 10, 0, bytes(1..5)))
        assertEquals(FrameStore.Result.Rejected(7), store.onChunk(chunk(3, 7, 10, 3, bytes(4..8))))
    }

    @Test
    fun aChangedTotalIsRejected() {
        store.begin(3)
        store.onChunk(chunk(3, 7, 10, 0, bytes(1..5)))
        assertEquals(FrameStore.Result.Rejected(7), store.onChunk(chunk(3, 7, 11, 5, bytes(6..10))))
    }

    @Test
    fun chunksOfAnotherEpochAreStale() {
        store.begin(3)
        assertEquals(FrameStore.Result.Stale, store.onChunk(chunk(2, 1, 3, 0, bytes(1..3))))
        assertEquals(FrameStore.Result.Stale, store.onChunk(chunk(4, 1, 3, 0, bytes(1..3))))
        assertTrue(files().isEmpty())
    }

    @Test
    fun chunksBeforeAnyBeginAreStale() {
        assertEquals(FrameStore.Result.Stale, store.onChunk(chunk(0, 1, 3, 0, bytes(1..3))))
    }

    @Test
    fun aNewEpochDeletesTheFilesOfTheOldOne() {
        store.begin(3)
        store.onChunk(chunk(3, 1, 3, 0, bytes(1..3)))
        store.onChunk(chunk(3, 2, 6, 0, bytes(1..3))) // partial
        assertEquals(2, files().size)
        store.begin(4)
        assertTrue(files().isEmpty())
        // the partial file of epoch 3 cannot be completed any more
        assertEquals(FrameStore.Result.Stale, store.onChunk(chunk(3, 2, 6, 3, bytes(4..6))))
    }

    @Test
    fun beginningTheSameEpochAgainKeepsTheFiles() {
        store.begin(3)
        store.onChunk(chunk(3, 1, 3, 0, bytes(1..3)))
        store.begin(3)
        assertEquals(1, files().size)
    }

    @Test
    fun atMostThreeCompletedFilesAreKeptTheOldestIsDeleted() {
        store.begin(1)
        val items = (1L..4L).map { id ->
            (store.onChunk(chunk(1, id, 2, 0, bytes(1..2))) as FrameStore.Result.Complete).item
        }
        assertFalse(items[0].file.exists())
        assertTrue(items[1].file.exists() && items[2].file.exists() && items[3].file.exists())
        assertEquals(3, files().size)
    }

    @Test
    fun releaseDeletesAPlayedFile() {
        store.begin(1)
        val item = (store.onChunk(chunk(1, 1, 2, 0, bytes(1..2))) as FrameStore.Result.Complete).item
        store.release(1)
        assertFalse(item.file.exists())
        store.release(99) // unknown id: no effect
    }

    @Test
    fun clearEmptiesTheDirectoryAndForgetsTheEpoch() {
        store.begin(1)
        store.onChunk(chunk(1, 1, 2, 0, bytes(1..2)))
        store.onChunk(chunk(1, 2, 4, 0, bytes(1..2)))
        store.clear()
        assertTrue(files().isEmpty())
        assertEquals(FrameStore.Result.Stale, store.onChunk(chunk(1, 3, 2, 0, bytes(1..2))))
    }

    @Test
    fun clearRemovesLeftoversOfAPreviousRun() {
        dir.mkdirs()
        File(dir, "old.jpg").writeBytes(byteArrayOf(1))
        store.clear()
        assertTrue(files().isEmpty())
    }

    @Test
    fun aFileRestartedAtOffsetZeroReplacesThePartialOne() {
        store.begin(1)
        store.onChunk(chunk(1, 5, 6, 0, bytes(1..3)))
        val done = store.onChunk(chunk(1, 5, 4, 0, bytes(7..10)))
        done as FrameStore.Result.Complete
        assertArrayEquals(bytes(7..10), done.item.file.readBytes())
    }
}
