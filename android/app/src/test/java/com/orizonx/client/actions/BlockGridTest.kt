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
import org.junit.Assert.assertTrue
import org.junit.Test

class BlockGridTest {
    private fun at(id: BlockId, col: Int, row: Int, cols: Int, rows: Int) = Placement(id, col, row, cols, rows)

    @Test
    fun spansFollowTheTable() {
        assertEquals(Span(4, 1), CLOCK.span(4))
        assertEquals(Span(2, 1), CLOCK.span(2))
        assertEquals(Span(2, 2), NOW_PLAYING.span(4))
        assertEquals(Span(2, 2), NOW_PLAYING.span(2))
        assertEquals(Span(2, 1), SOUND.span(4))
        assertEquals(Span(2, 1), BRIGHTNESS.span(2))
        for (tile in listOf(WIFI, BLUETOOTH, AIRPLANE)) assertEquals(Span(1, 1), tile.span(4))
        assertEquals(Span(2, 1), USB.span(4))
        assertEquals(Span(2, 1), USB.span(2))
    }

    @Test
    fun defaultOrder() {
        assertEquals(listOf(CLOCK, NOW_PLAYING, SOUND, BRIGHTNESS, WIFI, BLUETOOTH, AIRPLANE, USB), BlockId.DEFAULT_ORDER)
        assertEquals(listOf("clock", "now_playing", "sound", "brightness", "wifi", "bluetooth", "airplane", "usb"), BlockId.DEFAULT_ORDER.map { it.wire })
    }

    @Test
    fun defaultOrderOnFourColumns() {
        val p = BlockGrid.place(BlockId.DEFAULT_ORDER, 4)
        assertEquals(
            listOf(
                at(CLOCK, 0, 0, 4, 1),
                at(NOW_PLAYING, 0, 1, 2, 2),
                at(SOUND, 2, 1, 2, 1),
                at(BRIGHTNESS, 2, 2, 2, 1),
                at(WIFI, 0, 3, 1, 1),
                at(BLUETOOTH, 1, 3, 1, 1),
                at(AIRPLANE, 2, 3, 1, 1),
                at(USB, 0, 4, 2, 1),
            ),
            p,
        )
        assertEquals(5, BlockGrid.rowCount(p))
    }

    @Test
    fun defaultOrderOnTwoColumns() {
        val p = BlockGrid.place(BlockId.DEFAULT_ORDER, 2)
        assertEquals(
            listOf(
                at(CLOCK, 0, 0, 2, 1),
                at(NOW_PLAYING, 0, 1, 2, 2),
                at(SOUND, 0, 3, 2, 1),
                at(BRIGHTNESS, 0, 4, 2, 1),
                at(WIFI, 0, 5, 1, 1),
                at(BLUETOOTH, 1, 5, 1, 1),
                at(AIRPLANE, 0, 6, 1, 1),
                at(USB, 0, 7, 2, 1),
            ),
            p,
        )
        assertEquals(8, BlockGrid.rowCount(p))
    }

    @Test
    fun smallBlocksFillHolesLeftHigherUp() {
        // The 2x2 block cannot sit beside the 3 tiles of row 0, so the later 1x1 goes back up into the hole.
        val p = BlockGrid.place(listOf(WIFI, BLUETOOTH, AIRPLANE, NOW_PLAYING, USB, SOUND), 4)
        assertEquals(at(WIFI, 0, 0, 1, 1), p[0])
        assertEquals(at(AIRPLANE, 2, 0, 1, 1), p[2])
        assertEquals(at(NOW_PLAYING, 0, 1, 2, 2), p[3])
        // Row 0 has a free cell at column 3: only a 1x1 could use it, a 2x1 goes next to the now playing block.
        assertEquals(at(USB, 2, 1, 2, 1), p[4])
        assertEquals(at(SOUND, 2, 2, 2, 1), p[5])
    }

    @Test
    fun aTileTakesTheHoleAnEarlierBlockLeft() {
        // A wide block pushed to row 1 leaves one cell free at the end of row 0; the next tile fills it.
        val p = BlockGrid.place(listOf(WIFI, SOUND, USB, BLUETOOTH), 4)
        assertEquals(at(WIFI, 0, 0, 1, 1), p[0])
        assertEquals(at(SOUND, 1, 0, 2, 1), p[1])
        assertEquals(at(USB, 0, 1, 2, 1), p[2])
        assertEquals(at(BLUETOOTH, 3, 0, 1, 1), p[3])
    }

    @Test
    fun aBlockWiderThanTheGridIsNarrowedToIt() {
        val p = BlockGrid.place(listOf(SOUND, CLOCK), 1)
        assertEquals(at(SOUND, 0, 0, 1, 1), p[0])
        assertEquals(at(CLOCK, 0, 1, 1, 1), p[1])
        assertEquals(at(NOW_PLAYING, 0, 0, 1, 2), BlockGrid.place(listOf(NOW_PLAYING), 1).single())
    }

    @Test
    fun anEmptyGridHasNoRows() {
        assertTrue(BlockGrid.place(emptyList(), 4).isEmpty())
        assertEquals(0, BlockGrid.rowCount(emptyList()))
    }

    @Test
    fun aGridWithoutColumnsIsTreatedAsOneColumn() {
        assertEquals(at(WIFI, 0, 0, 1, 1), BlockGrid.place(listOf(WIFI), 0).single())
    }

    @Test
    fun placementsNeverOverlapAndStayInsideTheGrid() {
        for (columns in 1..6) {
            val p = BlockGrid.place(BlockId.DEFAULT_ORDER + BlockId.DEFAULT_ORDER.reversed(), columns)
            val cells = HashSet<Pair<Int, Int>>()
            for (b in p) {
                assertTrue(b.col >= 0 && b.col + b.cols <= columns)
                for (y in b.row until b.row + b.rows) for (x in b.col until b.col + b.cols) assertTrue("overlap", cells.add(x to y))
            }
        }
    }

    // --- Which blocks are there -----------------------------------------------------------------------------------

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
        assertEquals(emptySet<BlockId>(), ActionsBlocks.present(state("""{"media":{"available":true},"now_playing":null}""")) - SOUND)
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
