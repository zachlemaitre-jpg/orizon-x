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

    private val layout = ActionsLayout.DEFAULT

    private fun placeDefault(columns: Int, keys: Boolean = false) =
        BlockGrid.place(BlockId.DEFAULT_ORDER, columns) { layout.sizeOf(it, columns, keys) }

    @Test
    fun defaultMinAndMaxSizes() {
        val table = listOf(
            Triple(CLOCK, Span(4, 2), Span(2, 1)),
            Triple(NOW_PLAYING, Span(3, 2), Span(3, 2)),
            Triple(SOUND, Span(3, 1), Span(2, 1)),
            Triple(BRIGHTNESS, Span(3, 1), Span(2, 1)),
            Triple(WIFI, Span(1, 1), Span(1, 1)),
            Triple(BLUETOOTH, Span(1, 1), Span(1, 1)),
            Triple(AIRPLANE, Span(1, 1), Span(1, 1)),
            Triple(USB, Span(3, 1), Span(3, 1)),
        )
        for ((id, default, min) in table) {
            assertEquals(id.name, default, id.defaultSize())
            assertEquals(id.name, min, id.minSize())
            val max = id.maxSize()
            assertTrue(id.name, max.cols >= default.cols && max.rows >= default.rows)
            assertTrue(id.name, default.cols >= min.cols && default.rows >= min.rows)
        }
    }

    @Test
    fun soundNeedsMoreRoomWithTheMediaKeys() {
        assertEquals(Span(3, 1), SOUND.defaultSize(soundKeys = false))
        assertEquals(Span(2, 1), SOUND.minSize(soundKeys = false))
        assertEquals(Span(3, 2), SOUND.defaultSize(soundKeys = true))
        assertEquals(Span(3, 2), SOUND.minSize(soundKeys = true))
        // The other blocks do not care.
        assertEquals(CLOCK.defaultSize(), CLOCK.defaultSize(soundKeys = true))
    }

    @Test
    fun defaultOrder() {
        assertEquals(listOf(CLOCK, NOW_PLAYING, SOUND, BRIGHTNESS, WIFI, BLUETOOTH, AIRPLANE, USB), BlockId.DEFAULT_ORDER)
        assertEquals(listOf("clock", "now_playing", "sound", "brightness", "wifi", "bluetooth", "airplane", "usb"), BlockId.DEFAULT_ORDER.map { it.wire })
    }

    @Test
    fun columnsFollowTheWidthInAbout120DpCells() {
        assertEquals(11, BlockGrid.columnsFor(1408f)) // 1440 dp landscape tablet minus its margins
        assertEquals(7, BlockGrid.columnsFor(868f)) // 900 dp portrait
        assertEquals(2, BlockGrid.columnsFor(328f)) // phone portrait
        assertEquals(3, BlockGrid.columnsFor(379f))
        assertEquals(2, BlockGrid.columnsFor(100f)) // never fewer than 2
        assertEquals(2, BlockGrid.columnsFor(0f))
    }

    @Test
    fun defaultOrderOnElevenColumns() {
        val p = placeDefault(11)
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
            p,
        )
        assertEquals(3, BlockGrid.rowCount(p))
    }

    @Test
    fun defaultOrderOnElevenColumnsWithTheMediaKeys() {
        val p = placeDefault(11, keys = true)
        assertEquals(at(SOUND, 7, 0, 3, 2), p[2])
        assertEquals(at(BRIGHTNESS, 0, 2, 3, 1), p[3])
        assertEquals(at(WIFI, 10, 0, 1, 1), p[4])
        assertEquals(at(BLUETOOTH, 10, 1, 1, 1), p[5])
        assertEquals(at(AIRPLANE, 3, 2, 1, 1), p[6])
        assertEquals(at(USB, 4, 2, 3, 1), p[7])
    }

    @Test
    fun defaultOrderOnSevenColumns() {
        val p = placeDefault(7)
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
            p,
        )
        assertEquals(4, BlockGrid.rowCount(p))
    }

    @Test
    fun blocksWiderThanTheGridAreNarrowedToIt() {
        val p = placeDefault(2)
        assertEquals(
            listOf(
                at(CLOCK, 0, 0, 2, 2),
                at(NOW_PLAYING, 0, 2, 2, 2),
                at(SOUND, 0, 4, 2, 1),
                at(BRIGHTNESS, 0, 5, 2, 1),
                at(WIFI, 0, 6, 1, 1),
                at(BLUETOOTH, 1, 6, 1, 1),
                at(AIRPLANE, 0, 7, 1, 1),
                at(USB, 0, 8, 2, 1),
            ),
            p,
        )
    }

    @Test
    fun smallBlocksFillHolesLeftHigherUp() {
        // The 3x2 block cannot sit beside the three tiles on a 5-wide row 0, so the later 2x1 goes back up into the hole.
        val sizes = mapOf(NOW_PLAYING to Span(3, 2), BRIGHTNESS to Span(2, 1))
        val p = BlockGrid.place(listOf(WIFI, BLUETOOTH, AIRPLANE, NOW_PLAYING, BRIGHTNESS), 5) { sizes[it] ?: it.defaultSize() }
        assertEquals(at(AIRPLANE, 2, 0, 1, 1), p[2])
        assertEquals(at(NOW_PLAYING, 0, 1, 3, 2), p[3])
        assertEquals(at(BRIGHTNESS, 3, 0, 2, 1), p[4])
    }

    @Test
    fun aTileTakesTheHoleAnEarlierBlockLeft() {
        val p = BlockGrid.place(listOf(WIFI, SOUND, USB, BLUETOOTH), 5)
        assertEquals(at(WIFI, 0, 0, 1, 1), p[0])
        assertEquals(at(SOUND, 1, 0, 3, 1), p[1])
        assertEquals(at(USB, 0, 1, 3, 1), p[2])
        assertEquals(at(BLUETOOTH, 4, 0, 1, 1), p[3])
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
        for (columns in 1..12) {
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
