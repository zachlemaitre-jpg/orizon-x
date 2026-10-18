package com.orizonx.client.frame

import com.orizonx.client.protocol.PcMessage
import com.orizonx.client.protocol.Protocol
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Before
import org.junit.Rule
import org.junit.Test
import org.junit.rules.TemporaryFolder
import java.io.File

class FrameControllerTest {
    @get:Rule val tmp = TemporaryFolder()
    private lateinit var dir: File
    private val sent = mutableListOf<String>()
    private lateinit var controller: FrameController

    @Before fun setUp() {
        dir = File(tmp.root, "frame")
        controller = FrameController(FrameStore(dir)) { sent += it.toString() }
    }

    private fun state(epoch: Long = 1, status: String = "ok") = PcMessage.FrameState(epoch, status, "Photos", 5, "crop", false)

    private fun file(id: Long, epoch: Long = 1, offset: Long = 0, total: Long = 2) =
        PcMessage.FrameFile(epoch, id, Protocol.FRAME_KIND_IMAGE, total, offset, byteArrayOf(1, 2))

    private fun files() = dir.listFiles().orEmpty().filter { it.isFile }

    @Test
    fun aReceivedFileIsShownAndTheViewFollowsTheState() {
        controller.onState(state())
        assertEquals("Photos", controller.view.folder)
        assertEquals(5, controller.view.intervalS)
        controller.onFile(file(1))
        assertEquals(1L, controller.view.current?.id)
    }

    @Test
    fun theTimerAsksForTheNextFileAndDeletesThePlayedOne() {
        controller.onState(state())
        controller.onFile(file(1))
        controller.onFile(file(2))
        val first = controller.view.current!!.file
        controller.tick(5_000)
        assertEquals(2L, controller.view.current?.id)
        assertEquals(listOf("""{"id":"frame.next"}"""), sent)
        assertFalse(first.exists())
    }

    @Test
    fun buttonsSendTheirActions() {
        controller.onState(state())
        controller.togglePause()
        controller.toggleFit()
        controller.stepInterval(+1)
        assertEquals(3, sent.size)
        assertTrue(controller.view.paused)
        assertEquals("fit", controller.view.fit)
        assertEquals(10, controller.view.intervalS)
    }

    @Test
    fun aBrokenFileIsReportedFailed() {
        controller.onState(state())
        controller.onFile(file(7, offset = 2, total = 4)) // no chunk at offset 0
        assertEquals(1, sent.size)
        assertTrue(sent[0].contains("frame.failed"))
        assertNull(controller.view.current)
    }

    @Test
    fun aNewEpochDropsTheOldFilesAndTheViewItem() {
        controller.onState(state(epoch = 1))
        controller.onFile(file(1))
        controller.onState(state(epoch = 2))
        assertNull(controller.view.current)
        assertTrue(files().isEmpty())
        controller.onFile(file(2, epoch = 1)) // late chunk of the old epoch
        assertNull(controller.view.current)
    }

    @Test
    fun anEndEventOfAnItemNoLongerShownIsIgnored() {
        controller.onState(state())
        controller.onFile(file(1))
        controller.onFile(file(2))
        controller.tick(5_000)
        controller.playbackFailed(1) // the faded-out first item
        controller.videoEnded(1)
        assertEquals(2L, controller.view.current?.id)
        assertEquals(1, sent.size) // only the frame.next
    }

    @Test
    fun resetEmptiesTheCacheAndTheView() {
        controller.onState(state())
        controller.onFile(file(1))
        controller.reset()
        assertNull(controller.view.current)
        assertTrue(files().isEmpty())
    }
}
