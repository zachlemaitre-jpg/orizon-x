package com.orizonx.client.actions

import com.orizonx.client.actions.BlockGrid.Placement
import com.orizonx.client.actions.BlockId.AIRPLANE
import com.orizonx.client.actions.BlockId.BLUETOOTH
import com.orizonx.client.actions.BlockId.BRIGHTNESS
import com.orizonx.client.actions.BlockId.CLOCK
import com.orizonx.client.actions.BlockId.NOW_PLAYING
import com.orizonx.client.actions.BlockId.SOUND
import com.orizonx.client.actions.BlockId.USB
import com.orizonx.client.actions.BlockId.WIFI
import org.json.JSONObject
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

class BlockGridTest {
    private fun at(id: BlockId, col: Int, row: Int, cols: Int, rows: Int) = Placement(id, col, row, cols, rows)

    private val layout = ActionsLayout.DEFAULT

    private fun place(
        blocks: List<BlockId> = BlockId.DEFAULT_ORDER,
        columns: Int,
        rows: Int = BlockGrid.ROWS,
        keys: Boolean = false,
        saved: Map<BlockId, CellPos> = emptyMap(),
        sizes: Map<BlockId, Span> = emptyMap(),
    ) = GridPlanner.place(blocks, columns, rows, { sizes[it] ?: layout.sizeOf(it, columns, keys) }, saved)

    // --- Sizes ----------------------------------------------------------------------------------------------------------------------

    @Test
    fun defaultAndMinimumSizes() {
        val table = listOf(
            Triple(CLOCK, Span(4, 2), Span(2, 1)),
            Triple(NOW_PLAYING, Span(3, 2), Span(3, 2)),
            Triple(SOUND, Span(3, 1), Span(2, 1)),
            Triple(BRIGHTNESS, Span(3, 1), Span(2, 1)),
            Triple(WIFI, Span(1, 1), Span(1, 1)),
            Triple(BLUETOOTH, Span(1, 1), Span(1, 1)),
            Triple(AIRPLANE, Span(1, 1), Span(1, 1)),
            Triple(USB, Span(3, 1), Span(2, 1)),
        )
        for ((id, default, min) in table) {
            assertEquals(id.name, default, id.defaultSize())
            assertEquals(id.name, min, id.minSize())
            assertTrue(id.name, default.cols >= min.cols && default.rows >= min.rows)
        }
    }

    @Test
    fun soundStartsTallerWithTheMediaKeysButItsMinimumDoesNotJump() {
        assertEquals(Span(3, 1), SOUND.defaultSize(soundKeys = false))
        assertEquals(Span(3, 2), SOUND.defaultSize(soundKeys = true))
        assertEquals(Span(2, 1), SOUND.minSize())
        assertEquals(CLOCK.defaultSize(), CLOCK.defaultSize(soundKeys = true))
    }

    @Test
    fun thereIsNoMaximumBeyondTheSanityCap() {
        assertEquals(Span(30, 40), BRIGHTNESS.clamp(Span(30, 40)))
        assertEquals(Span(BlockId.MAX_CELLS, BlockId.MAX_CELLS), BRIGHTNESS.clamp(Span(9999, 9999)))
        assertEquals(Span(2, 1), BRIGHTNESS.clamp(Span(0, -4)))
        assertEquals(Span(12, 9), WIFI.resized(Span(1, 1), 11, 8))
    }

    @Test
    fun defaultOrder() {
        assertEquals(listOf(CLOCK, NOW_PLAYING, SOUND, BRIGHTNESS, WIFI, BLUETOOTH, AIRPLANE, USB), BlockId.DEFAULT_ORDER)
        assertEquals(listOf("clock", "now_playing", "sound", "brightness", "wifi", "bluetooth", "airplane", "usb"), BlockId.DEFAULT_ORDER.map { it.wire })
    }

    // --- What the Sound and USB blocks show ----------------------------------------------------------------------------------

    @Test
    fun soundShowsOnlyTheSliderAtTwoByOne() {
        assertEquals(SoundMode.SLIDER_ONLY, SoundContent.mode(2, 1, mediaKeys = false))
        assertEquals(SoundMode.SLIDER_ONLY, SoundContent.mode(2, 1, mediaKeys = true))
        assertEquals(SoundMode.SLIDER_ONLY, SoundContent.mode(1, 1, mediaKeys = true))
    }

    @Test
    fun soundGainsTheMuteButtonThenTheKeys() {
        assertEquals(SoundMode.WITH_MUTE, SoundContent.mode(3, 1, mediaKeys = true))
        assertEquals(SoundMode.WITH_MUTE, SoundContent.mode(6, 1, mediaKeys = true))
        assertEquals(SoundMode.WITH_MUTE, SoundContent.mode(2, 2, mediaKeys = true))
        assertEquals(SoundMode.WITH_KEYS, SoundContent.mode(3, 2, mediaKeys = true))
        assertEquals(SoundMode.WITH_KEYS, SoundContent.mode(5, 4, mediaKeys = true))
    }

    @Test
    fun soundWithoutMediaKeysNeverShowsThem() {
        assertEquals(SoundMode.WITH_MUTE, SoundContent.mode(3, 2, mediaKeys = false))
        assertEquals(SoundMode.WITH_MUTE, SoundContent.mode(8, 5, mediaKeys = false))
    }

    @Test
    fun usbIsCompactAtTwoCellsAndFullFromThree() {
        assertEquals(UsbMode.COMPACT, UsbContent.mode(2))
        assertEquals(UsbMode.COMPACT, UsbContent.mode(1))
        assertEquals(UsbMode.FULL, UsbContent.mode(3))
        assertEquals(UsbMode.FULL, UsbContent.mode(7))
    }

    // --- The fixed 6-row grid -----------------------------------------------------------------------------------------------------

    @Test
    fun theGridIsSixRowsAndTheSideComesFromTheHeight() {
        // 1440 x 900 dp landscape: the area between the header and the context bar is about 1408 x 740.
        val m = BlockGrid.metrics(1408f, 740f, 8f)
        assertEquals(116f, m.side, 0f) // (740 - 5 * 8) / 6 = 116.67, rounded down
        assertEquals(11, m.columns) // floor((1408 + 8) / (116 + 8))
        assertTrue(6 * m.side + 5 * 8f <= 740f)
    }

    @Test
    fun columnsFollowTheWidthForTheSameSide() {
        assertEquals(4, BlockGrid.metrics(868f, 1100f, 8f).columns) // portrait tablet: side 176
        assertEquals(3, BlockGrid.metrics(328f, 560f, 8f).columns) // phone: side 86
        assertEquals(2, BlockGrid.metrics(100f, 740f, 8f).columns) // never fewer than 2
        assertEquals(2, BlockGrid.metrics(0f, 740f, 8f).columns)
    }

    @Test
    fun theSideNeverMakesTheRowsOverflowTheHeight() {
        for (h in 200..1200 step 7) {
            val m = BlockGrid.metrics(1000f, h.toFloat(), 8f)
            assertTrue("$h", 6 * m.side + 5 * 8f <= h)
            assertTrue(m.side >= 1f)
        }
    }

    // --- Planner: no saved cells = the dense default ------------------------------------------------------------------------------

    @Test
    fun defaultOrderOnElevenColumns() {
        assertEquals(
            listOf(
                at(CLOCK, 0, 0, 4, 2),
                at(NOW_PLAYING, 4, 0, 3, 2),
                at(SOUND, 7, 0, 3, 1),
                at(BRIGHTNESS, 7, 1, 3, 1),
                at(WIFI, 10, 0, 1, 1),
                at(BLUETOOTH, 10, 1, 1, 1),
                at(AIRPLANE, 0, 2, 1, 1),
                at(USB, 1, 2, 3, 1),
            ),
            place(columns = 11),
        )
    }

    @Test
    fun defaultOrderOnElevenColumnsWithTheMediaKeys() {
        val p = place(columns = 11, keys = true)
        assertEquals(at(SOUND, 7, 0, 3, 2), p[2])
        assertEquals(at(BRIGHTNESS, 0, 2, 3, 1), p[3])
        assertEquals(at(AIRPLANE, 3, 2, 1, 1), p[6])
        assertEquals(at(USB, 4, 2, 3, 1), p[7])
    }

    @Test
    fun defaultOrderOnSevenColumns() {
        assertEquals(
            listOf(
                at(CLOCK, 0, 0, 4, 2),
                at(NOW_PLAYING, 4, 0, 3, 2),
                at(SOUND, 0, 2, 3, 1),
                at(BRIGHTNESS, 3, 2, 3, 1),
                at(WIFI, 6, 2, 1, 1),
                at(BLUETOOTH, 0, 3, 1, 1),
                at(AIRPLANE, 1, 3, 1, 1),
                at(USB, 2, 3, 3, 1),
            ),
            place(columns = 7),
        )
    }

    @Test
    fun blocksWiderThanTheGridAreNarrowedAndOverflowGoesBelowTheSixRows() {
        val p = place(columns = 2)
        assertEquals(at(CLOCK, 0, 0, 2, 2), p[0])
        assertEquals(at(NOW_PLAYING, 0, 2, 2, 2), p[1])
        assertEquals(at(SOUND, 0, 4, 2, 1), p[2])
        assertEquals(at(BRIGHTNESS, 0, 5, 2, 1), p[3])
        // The six rows are full: the rest scrolls, below them.
        assertEquals(at(WIFI, 0, 6, 1, 1), p[4])
        assertEquals(at(BLUETOOTH, 1, 6, 1, 1), p[5])
        assertEquals(at(AIRPLANE, 0, 7, 1, 1), p[6])
        assertEquals(at(USB, 0, 8, 2, 1), p[7])
    }

    @Test
    fun anEmptyGridHasNoRows() {
        assertTrue(place(blocks = emptyList(), columns = 4).isEmpty())
        assertEquals(0, BlockGrid.rowCount(emptyList()))
    }

    @Test
    fun placementsNeverOverlapAndStayInsideTheColumns() {
        for (columns in 1..12) {
            val p = place(BlockId.DEFAULT_ORDER, columns)
            val cells = HashSet<Pair<Int, Int>>()
            for (b in p) {
                assertTrue(b.col >= 0 && b.col + b.cols <= columns)
                for (y in b.row until b.row + b.rows) for (x in b.col until b.col + b.cols) assertTrue("overlap", cells.add(x to y))
            }
        }
    }

    // --- Planner: saved cells, no gravity ------------------------------------------------------------------------------------------

    @Test
    fun aSavedCellIsKeptEvenWithGapsAround() {
        val saved = mapOf(WIFI to CellPos(5, 4), BLUETOOTH to CellPos(0, 5))
        val p = place(listOf(WIFI, BLUETOOTH), columns = 11, saved = saved)
        assertEquals(at(WIFI, 5, 4, 1, 1), p[0])
        assertEquals(at(BLUETOOTH, 0, 5, 1, 1), p[1])
    }

    @Test
    fun savedBlocksAreSettledBeforeNewOnesSoNobodyTakesTheirCell() {
        // BRIGHTNESS comes first in the order but has no saved cell; WIFI's saved cell is where it would have gone.
        val p = place(listOf(BRIGHTNESS, WIFI), columns = 6, saved = mapOf(WIFI to CellPos(0, 0)))
        assertEquals(at(WIFI, 0, 0, 1, 1), p[1])
        assertEquals(at(BRIGHTNESS, 1, 0, 3, 1), p[0])
    }

    @Test
    fun anOutOfBoundsSavedCellIsRelocatedToTheFirstFreeSpot() {
        val p = place(listOf(CLOCK, WIFI), columns = 6, saved = mapOf(WIFI to CellPos(9, 0)))
        assertEquals(at(WIFI, 4, 0, 1, 1), p[1])
        assertEquals(at(CLOCK, 0, 0, 4, 2), p[0])
    }

    @Test
    fun ofTwoOverlappingSavedCellsTheFirstInOrderKeepsIt() {
        val saved = mapOf(CLOCK to CellPos(0, 0), WIFI to CellPos(1, 1))
        val p = place(listOf(CLOCK, WIFI), columns = 6, saved = saved)
        assertEquals(at(CLOCK, 0, 0, 4, 2), p[0])
        assertEquals(at(WIFI, 4, 0, 1, 1), p[1])
    }

    @Test
    fun aReturningBlockUsesItsSavedCellIfFreeElseTheFirstFreeSpot() {
        val others = mapOf(CLOCK to CellPos(0, 0))
        val free = place(listOf(CLOCK, USB), columns = 6, saved = others + (USB to CellPos(2, 4)))
        assertEquals(at(USB, 2, 4, 3, 1), free[1])
        val taken = place(listOf(CLOCK, USB), columns = 6, saved = others + (USB to CellPos(1, 1)))
        assertEquals(at(USB, 0, 2, 3, 1), taken[1])
    }

    @Test
    fun withNoRoomForTheWantedSizeTheMinimumSizeIsTried() {
        // Row 1 keeps 3 free cells (a tile sits at its end): brightness (wanted 4 wide) fits at its minimum 2.
        val saved = mapOf(CLOCK to CellPos(0, 0), WIFI to CellPos(3, 1))
        val sizes = mapOf(CLOCK to Span(4, 1), BRIGHTNESS to Span(4, 1))
        val p = place(listOf(CLOCK, WIFI, BRIGHTNESS), columns = 4, rows = 2, saved = saved, sizes = sizes)
        assertEquals(at(BRIGHTNESS, 0, 1, 2, 1), p[2])
    }

    @Test
    fun withNoRoomAtAllTheBlockGoesBelowTheRows() {
        val p = place(listOf(CLOCK, BRIGHTNESS), columns = 2, rows = 1, saved = mapOf(CLOCK to CellPos(0, 0)), sizes = mapOf(CLOCK to Span(2, 1)))
        assertEquals(at(BRIGHTNESS, 0, 1, 2, 1), p[1])
    }

    @Test
    fun aSavedCellInTheOverflowIsKept() {
        val p = place(listOf(WIFI), columns = 3, saved = mapOf(WIFI to CellPos(1, 8)))
        assertEquals(at(WIFI, 1, 8, 1, 1), p.single())
    }

    // --- Free spots, drops and resizing -------------------------------------------------------------------------------------------

    private val two = listOf(at(CLOCK, 0, 0, 4, 2), at(WIFI, 5, 1, 1, 1))

    @Test
    fun aRectangleIsFreeInsideTheGridAndClearOfOthers() {
        assertTrue(GridPlanner.isFree(two, null, 4, 0, 1, 1, 11, 6))
        assertTrue(GridPlanner.isFree(two, null, 6, 5, 5, 1, 11, 6))
        assertTrue(!GridPlanner.isFree(two, null, 3, 1, 2, 1, 11, 6)) // overlaps the clock
        assertTrue(!GridPlanner.isFree(two, null, 5, 1, 1, 1, 11, 6)) // on the tile
        assertTrue(!GridPlanner.isFree(two, null, -1, 0, 1, 1, 11, 6))
        assertTrue(!GridPlanner.isFree(two, null, 10, 0, 2, 1, 11, 6)) // past the right edge
        assertTrue(!GridPlanner.isFree(two, null, 0, 5, 1, 2, 11, 6)) // past the 6th row
    }

    @Test
    fun aBlockDoesNotCollideWithItself() {
        assertTrue(GridPlanner.isFree(two, CLOCK, 1, 0, 4, 2, 11, 6)) // slides one cell, over its own old place
        assertTrue(!GridPlanner.isFree(two, CLOCK, 2, 0, 4, 2, 11, 6)) // would hit the tile
    }

    @Test
    fun aDropOnAFreeSpotIsAcceptedOtherwiseRejected() {
        assertEquals(CellPos(6, 3), GridPlanner.drop(two, WIFI, 6, 3, 11, 6))
        assertEquals(CellPos(1, 0), GridPlanner.drop(two, CLOCK, 1, 0, 11, 6))
        assertNull(GridPlanner.drop(two, WIFI, 1, 1, 11, 6)) // on the clock
        assertNull(GridPlanner.drop(two, CLOCK, 8, 0, 11, 6)) // clock is 4 wide: 8..11 is past the edge
        assertNull(GridPlanner.drop(two, CLOCK, 0, 5, 11, 6)) // 2 tall: past the 6th row
        assertNull(GridPlanner.drop(two, SOUND, 0, 0, 11, 6)) // not on the grid
    }

    @Test
    fun growingStopsAtTheNeighbour() {
        val p = listOf(at(BRIGHTNESS, 0, 0, 2, 1), at(WIFI, 4, 0, 1, 1))
        assertEquals(Span(4, 1), GridPlanner.resize(p, BRIGHTNESS, Span(8, 1), 11, 6)) // cells 2 and 3 only
        assertEquals(Span(3, 1), GridPlanner.resize(p, BRIGHTNESS, Span(3, 1), 11, 6))
    }

    @Test
    fun growingStopsAtTheEdgesOfTheGrid() {
        val p = listOf(at(WIFI, 9, 4, 1, 1))
        assertEquals(Span(2, 2), GridPlanner.resize(p, WIFI, Span(5, 5), 11, 6)) // 2 columns left, 2 rows left
        assertEquals(Span(2, 2), GridPlanner.resize(listOf(at(BRIGHTNESS, 9, 4, 2, 2)), BRIGHTNESS, Span(6, 9), 11, 6))
    }

    @Test
    fun anyHeightIsAllowedWhileTheCellsAreFree() {
        val p = listOf(at(BRIGHTNESS, 0, 0, 3, 1))
        assertEquals(Span(3, 6), GridPlanner.resize(p, BRIGHTNESS, Span(3, 20), 11, 6))
        assertEquals(Span(11, 1), GridPlanner.resize(p, BRIGHTNESS, Span(30, 1), 11, 6))
    }

    @Test
    fun shrinkingStopsAtTheMinimum() {
        val p = listOf(at(CLOCK, 0, 0, 4, 2))
        assertEquals(Span(2, 1), GridPlanner.resize(p, CLOCK, Span(0, 0), 11, 6))
        assertEquals(Span(3, 1), GridPlanner.resize(p, CLOCK, Span(3, 1), 11, 6))
        assertEquals(Span(1, 1), GridPlanner.resize(listOf(at(WIFI, 0, 0, 2, 2)), WIFI, Span(-3, -3), 11, 6))
    }

    @Test
    fun growingWiderCanBeBlockedWhileTallerStillWorks() {
        val p = listOf(at(BRIGHTNESS, 0, 0, 2, 1), at(WIFI, 2, 0, 1, 1))
        assertEquals(Span(2, 3), GridPlanner.resize(p, BRIGHTNESS, Span(5, 3), 11, 6))
    }

    @Test
    fun shrinkingOneWayAndGrowingTheOther() {
        val p = listOf(at(BRIGHTNESS, 0, 0, 4, 1))
        assertEquals(Span(2, 3), GridPlanner.resize(p, BRIGHTNESS, Span(2, 3), 11, 6))
    }

    @Test
    fun aBlockBelowTheSixRowsDoesNotGrowDownwards() {
        val p = listOf(at(WIFI, 0, 6, 1, 1))
        assertEquals(Span(3, 1), GridPlanner.resize(p, WIFI, Span(3, 4), 11, 6))
    }

    // --- Which blocks are there -----------------------------------------------------------------------------------------------------

    private fun state(json: String) = ActionsState.parse(JSONObject(json))

    @Test
    fun presentBlocksFollowTheState() {
        assertEquals(emptySet<BlockId>(), ActionsBlocks.present(state("{}")))
        val all = state(
            """{"clock":{"epoch_ms":1,"utc_offset_min":0},"audio":{"available":true,"volume":0.5,"muted":false},
                "now_playing":{"available":true,"app":"S","title":"T","playing":true},
                "brightness":{"available":true,"value":0.5},"wifi":{"available":true,"on":true},
                "bluetooth":{"available":true,"on":false},"airplane":{"available":true,"on":false},
                "usb":[{"drive":"E:","label":"K","kind":"stick"}]}""",
        )
        assertEquals(BlockId.entries.toSet(), ActionsBlocks.present(all))
    }

    @Test
    fun theRadiosAreThreeIndependentBlocks() {
        assertEquals(setOf(WIFI), ActionsBlocks.present(state("""{"wifi":{"available":true,"on":true}}""")))
        assertEquals(setOf(BLUETOOTH, AIRPLANE), ActionsBlocks.present(state("""{"bluetooth":{"available":true,"on":true},"airplane":{"available":true,"on":true}}""")))
    }

    @Test
    fun soundFollowsTheMediaKeyRule() {
        assertEquals(setOf(SOUND), ActionsBlocks.present(state("""{"media":{"available":true}}""")))
        assertEquals(
            setOf(NOW_PLAYING),
            ActionsBlocks.present(state("""{"media":{"available":true},"now_playing":{"available":true,"title":"T"}}""")),
        )
    }

    @Test
    fun clockBlockIsKeptForTheBatteryAlone() {
        assertEquals(setOf(CLOCK), ActionsBlocks.present(state("""{"battery":{"available":true,"percent":50,"charging":false}}""")))
    }
}
