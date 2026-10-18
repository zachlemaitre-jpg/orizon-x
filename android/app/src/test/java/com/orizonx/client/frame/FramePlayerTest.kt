package com.orizonx.client.frame

import com.orizonx.client.frame.FramePlayer.Effect
import com.orizonx.client.protocol.PcMessage
import com.orizonx.client.protocol.Protocol
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test
import java.io.File

class FramePlayerTest {
    private fun image(id: Long) = FrameItem(id, Protocol.FRAME_KIND_IMAGE, File("img$id.jpg"))
    private fun video(id: Long) = FrameItem(id, Protocol.FRAME_KIND_VIDEO, File("vid$id.mp4"))

    private fun state(epoch: Long = 1, status: String = "ok", interval: Int = 10, fit: String = "crop", paused: Boolean = false) =
        PcMessage.FrameState(epoch, status, "Photos", interval, fit, paused)

    private fun player(interval: Int = 10, epoch: Long = 1) = FramePlayer().also { it.onState(state(epoch, interval = interval)) }

    @Test
    fun theFirstItemIsShownAsSoonAsItIsReady() {
        val p = player()
        assertEquals(listOf(Effect.Show(image(1))), p.onItemReady(image(1)))
        assertEquals(image(1), p.current)
        assertTrue(p.queue.isEmpty())
    }

    @Test
    fun theSecondItemWaitsInTheQueue() {
        val p = player()
        p.onItemReady(image(1))
        assertTrue(p.onItemReady(image(2)).isEmpty())
        assertEquals(listOf(image(2)), p.queue)
        assertEquals(image(1), p.current)
    }

    @Test
    fun stateIsTakenFromFrameState() {
        val p = FramePlayer()
        assertEquals(emptyList<Effect>(), p.onState(state(status = "empty", interval = 60, fit = "fit", paused = true)))
        assertEquals("empty", p.status)
        assertEquals(60, p.intervalS)
        assertEquals("fit", p.fit)
        assertTrue(p.paused)
    }

    @Test
    fun anImageIsFinishedWhenTheIntervalIsReached() {
        val p = player(interval = 10)
        p.onItemReady(image(1))
        p.onItemReady(image(2))
        assertTrue(p.onTick(9_800).isEmpty())
        assertEquals(9_800L, p.elapsedMs)
        val effects = p.onTick(200)
        assertEquals(listOf(Effect.Release(1), Effect.SendNext, Effect.Show(image(2))), effects)
        assertEquals(image(2), p.current)
        assertTrue(p.queue.isEmpty())
        assertEquals(0L, p.elapsedMs)
    }

    @Test
    fun pauseStopsTheTimer() {
        val p = player(interval = 10)
        p.onItemReady(image(1))
        p.onItemReady(image(2))
        p.onTick(5_000)
        assertEquals(listOf(Effect.SendPause(true)), p.onPauseTapped())
        assertTrue(p.paused)
        assertTrue(p.onTick(60_000).isEmpty())
        assertEquals(5_000L, p.elapsedMs)
        assertEquals(listOf(Effect.SendPause(false)), p.onPauseTapped())
        assertTrue(p.onTick(4_000).isEmpty())
        assertEquals(3, p.onTick(1_000).size)
    }

    @Test
    fun theTimerDoesNotApplyToVideos() {
        val p = player(interval = 5)
        p.onItemReady(video(1))
        p.onItemReady(image(2))
        assertTrue(p.onTick(60_000).isEmpty())
        assertEquals(video(1), p.current)
    }

    @Test
    fun aVideoEndingAdvances() {
        val p = player()
        p.onItemReady(video(1))
        p.onItemReady(image(2))
        assertEquals(listOf(Effect.Release(1), Effect.SendNext, Effect.Show(image(2))), p.onVideoEnded())
        assertEquals(image(2), p.current)
    }

    @Test
    fun aVideoEndedEventWhileAnImageIsShownIsIgnored() {
        val p = player()
        p.onItemReady(image(1))
        p.onItemReady(image(2))
        assertTrue(p.onVideoEnded().isEmpty())
        assertEquals(image(1), p.current)
    }

    @Test
    fun nextTappedAdvancesEvenWhilePaused() {
        val p = player()
        p.onItemReady(image(1))
        p.onItemReady(image(2))
        p.onPauseTapped()
        assertEquals(listOf(Effect.Release(1), Effect.SendNext, Effect.Show(image(2))), p.onNextTapped())
        assertTrue(p.paused)
    }

    @Test
    fun nextTappedWithNothingShownDoesNothing() {
        assertTrue(player().onNextTapped().isEmpty())
    }

    @Test
    fun whenTheNextItemIsNotReadyTheOldOneStaysThenIsReplaced() {
        val p = player(interval = 5)
        p.onItemReady(image(1))
        assertEquals(listOf(Effect.SendNext), p.onTick(5_000))
        assertEquals(image(1), p.current) // still on screen, not released
        assertTrue(p.onTick(60_000).isEmpty()) // no second SendNext
        assertTrue(p.onNextTapped().isEmpty())
        assertEquals(listOf(Effect.Release(1), Effect.Show(image(2))), p.onItemReady(image(2)))
        assertEquals(image(2), p.current)
        assertEquals(0L, p.elapsedMs)
        assertTrue(p.onTick(1_000).isEmpty())
    }

    @Test
    fun aPlaybackFailureReportsTheFileAndAdvances() {
        val p = player()
        p.onItemReady(video(1))
        p.onItemReady(image(2))
        // the PC sends the next file after frame.failed, so no SendNext here
        assertEquals(listOf(Effect.SendFailed(1), Effect.Release(1), Effect.Show(image(2))), p.onPlaybackFailed())
        assertEquals(image(2), p.current)
    }

    @Test
    fun aPlaybackFailureWithNothingNextEmptiesTheScreenUntilTheNextArrives() {
        val p = player()
        p.onItemReady(image(1))
        assertEquals(listOf(Effect.SendFailed(1), Effect.Release(1)), p.onPlaybackFailed())
        assertNull(p.current)
        assertEquals(listOf(Effect.Show(image(2))), p.onItemReady(image(2)))
    }

    @Test
    fun aPlaybackFailureWithNothingShownDoesNothing() {
        assertTrue(player().onPlaybackFailed().isEmpty())
    }

    @Test
    fun aRejectedFileIsReportedFailed() {
        val p = player()
        assertEquals(listOf(Effect.SendFailed(9)), p.onFileRejected(9))
    }

    @Test
    fun anEpochChangeClearsEverything() {
        val p = player(epoch = 1)
        p.onItemReady(image(1))
        p.onItemReady(image(2))
        p.onTick(3_000)
        assertTrue(p.onState(state(epoch = 2)).isEmpty())
        assertNull(p.current)
        assertTrue(p.queue.isEmpty())
        assertEquals(0L, p.elapsedMs)
        assertEquals(listOf(Effect.Show(image(3))), p.onItemReady(image(3)))
    }

    @Test
    fun theSameEpochKeepsWhatIsShown() {
        val p = player(epoch = 1)
        p.onItemReady(image(1))
        p.onState(state(epoch = 1, interval = 60, fit = "fit"))
        assertEquals(image(1), p.current)
        assertEquals(60, p.intervalS)
    }

    @Test
    fun anEpochChangeWhileWaitingForTheNextItemForgetsTheWait() {
        val p = player(interval = 5, epoch = 1)
        p.onItemReady(image(1))
        p.onTick(5_000)
        p.onState(state(epoch = 2))
        assertEquals(listOf(Effect.Show(image(4))), p.onItemReady(image(4)))
    }

    @Test
    fun intervalSteppingMovesAlongTheListAndClamps() {
        val p = player(interval = 30)
        assertEquals(listOf(Effect.SendInterval(60)), p.onIntervalStep(+1))
        assertEquals(60, p.intervalS)
        assertEquals(listOf(Effect.SendInterval(300)), p.onIntervalStep(+1))
        assertEquals(listOf(Effect.SendInterval(900)), p.onIntervalStep(+1))
        assertEquals(listOf(Effect.SendInterval(3600)), p.onIntervalStep(+1))
        assertTrue(p.onIntervalStep(+1).isEmpty())
        assertEquals(3600, p.intervalS)
        repeat(6) { p.onIntervalStep(-1) }
        assertEquals(5, p.intervalS)
        assertTrue(p.onIntervalStep(-1).isEmpty())
        assertEquals(5, p.intervalS)
    }

    @Test
    fun anIntervalOutsideTheListSnapsToTheNearestValueWhenStepping() {
        val p = player(interval = 12)
        assertEquals(listOf(Effect.SendInterval(30)), p.onIntervalStep(+1))
        val q = player(interval = 12)
        assertEquals(listOf(Effect.SendInterval(5)), q.onIntervalStep(-1))
    }

    @Test
    fun theIntervalListMatchesTheProtocol() {
        assertEquals(listOf(5, 10, 30, 60, 300, 900, 3600), FramePlayer.INTERVALS)
    }

    @Test
    fun fitToggles() {
        val p = player()
        assertEquals(listOf(Effect.SendFit("fit")), p.onFitTapped())
        assertEquals("fit", p.fit)
        assertEquals(listOf(Effect.SendFit("crop")), p.onFitTapped())
        assertEquals("crop", p.fit)
    }
}
