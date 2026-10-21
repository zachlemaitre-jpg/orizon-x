package com.orizonx.client.actions

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class NowPlayingLayoutTest {
    private fun plan(w: Float, h: Float) = NowPlayingLayout.plan(w, h)

    @Test
    fun theCoverIsNeverSmallerThanToday() {
        assertEquals(112f, plan(340f, 60f).coverSide, 0f) // a very short block
        assertEquals(112f, plan(200f, 190f).coverSide, 0f) // too narrow to give the text 180 dp beside a bigger cover
        assertEquals(112f, plan(0f, 0f).coverSide, 0f)
        assertFalse(plan(0f, 0f).vertical)
        assertEquals(112f, plan(-5f, -5f).coverSide, 0f)
    }

    @Test
    fun theCoverGrowsWithTheHeightBesideTheText() {
        // 600 wide leaves 404 for the cover after the gap and the 180 dp of text.
        val a = plan(600f, 130f).coverSide
        val b = plan(600f, 200f).coverSide
        val c = plan(600f, 300f).coverSide
        assertEquals(130f, a, 0f)
        assertEquals(200f, b, 0f)
        assertEquals(300f, c, 0f)
        assertTrue(a < b && b < c)
        assertFalse(plan(600f, 300f).vertical)
    }

    @Test
    fun theCoverStopsGrowingWhereTheTextWouldBeSqueezed() {
        // 336 wide: the cover can be at most 336 - 16 - 180 = 140 dp, however tall the block is while it is not taller than wide.
        assertEquals(140f, plan(336f, 204f).coverSide, 0f)
        assertEquals(140f, plan(336f, 300f).coverSide, 0f)
        assertEquals(140f, plan(336f, 336f).coverSide, 0f) // square: not yet vertical
        // The text column keeps its width.
        for (w in listOf(336f, 400f, 500f, 800f)) {
            val p = plan(w, w * 1.0f)
            assertTrue(w - NowPlayingLayout.GAP - p.coverSide >= NowPlayingLayout.TEXT_MIN_WIDTH || p.coverSide == NowPlayingLayout.MIN_COVER)
        }
    }

    @Test
    fun aTallerThanWideBlockPutsTheCoverOnTop() {
        // 3x4 cells of 116 dp, 14 dp padding: about 336 x 460.
        val p = plan(336f, 460f)
        assertTrue(p.vertical)
        assertEquals(276f, p.coverSide, 0.001f) // 60 % of the height, less than the 336 dp width
    }

    @Test
    fun theVerticalCoverIsCappedByTheWidth() {
        val p = plan(300f, 900f)
        assertTrue(p.vertical)
        assertEquals(300f, p.coverSide, 0f) // 60 % of 900 is 540, but the block is only 300 wide
    }

    @Test
    fun theVerticalSwitchIsHeightOverWidthAndNeedsARoomyCover() {
        assertFalse(plan(336f, 336f).vertical) // square: still beside
        assertTrue(plan(336f, 337f).vertical) // one dp taller: on top
        assertEquals(202.2f, plan(336f, 337f).coverSide, 0.001f)
        assertFalse(plan(336f, 300f).vertical) // wider than tall
        // Tall and narrow but the 60 % cover would be under the minimum: stays beside the text.
        assertFalse(plan(120f, 180f).vertical) // 60 % of 180 is 108 < 112
    }

    @Test
    fun theVerticalCoverGrowsWithTheHeight() {
        val small = plan(336f, 460f).coverSide
        val big = plan(336f, 520f).coverSide
        assertTrue(plan(336f, 520f).vertical)
        assertTrue(big > small)
        assertEquals(312f, big, 0.001f)
    }

    @Test
    fun onlySpotifyShowsItsIconWhateverTheCase() {
        assertTrue(NowPlayingLayout.isSpotify("Spotify"))
        assertTrue(NowPlayingLayout.isSpotify("spotify.exe"))
        assertTrue(NowPlayingLayout.isSpotify("SPOTIFY Premium"))
        assertFalse(NowPlayingLayout.isSpotify("Chrome"))
        assertFalse(NowPlayingLayout.isSpotify(""))
    }

    @Test
    fun theVerticalCoverLeavesRoomForTheTextAndKeys() {
        for (h in 337..1200 step 21) {
            val p = plan(336f, h.toFloat())
            assertTrue("$h", p.vertical)
            assertTrue("$h", h - p.coverSide >= h * 0.4f - 0.01f) // 40 % of the height for the text and keys
        }
    }
}
