package com.orizonx.client.actions

import org.json.JSONObject
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertNull
import org.junit.Test

class PerfStateTest {
    private fun parse(json: String) = ActionsState.parse(JSONObject(json)).perf

    @Test
    fun aFullSectionIsParsed() {
        val p = parse(
            """{"perf":{"available":true,
              "cpu":{"value":23,"ghz":4.1,"history":[1,2,3]},
              "gpu":{"value":8,"mem_used":3.2,"mem_total":16.0,"history":[4,5]},
              "ram":{"value":41,"used":12.3,"total":32.0,"history":[6]},
              "net":{"down":1250000,"up":82000,"down_history":[10,20],"up_history":[30,40]},
              "npu":{"value":0,"history":[0,0]}}}""",
        )!!
        assertEquals(PerfMeter(23, listOf(1, 2, 3)), p.cpu)
        assertEquals(4.1f, p.cpuGhz!!, 0.001f)
        assertEquals(PerfMeter(8, listOf(4, 5)), p.gpu)
        assertEquals(3.2f, p.gpuMemUsed!!, 0.001f)
        assertEquals(16.0f, p.gpuMemTotal!!, 0.001f)
        assertEquals(PerfMeter(41, listOf(6)), p.ram)
        assertEquals(12.3f, p.ramUsed!!, 0.001f)
        assertEquals(32.0f, p.ramTotal!!, 0.001f)
        assertEquals(1_250_000L, p.netDown)
        assertEquals(82_000L, p.netUp)
        assertEquals(listOf(10L, 20L), p.netDownHistory)
        assertEquals(listOf(30L, 40L), p.netUpHistory)
        assertEquals(PerfMeter(0, listOf(0, 0)), p.npu)
    }

    @Test
    fun aPartialSectionKeepsOnlyTheMeasuresThatAreThere() {
        val p = parse("""{"perf":{"available":true,"cpu":{"value":50,"history":[50]},"ram":{"value":40}}}""")!!
        assertEquals(PerfMeter(50, listOf(50)), p.cpu)
        assertNull(p.cpuGhz)
        assertEquals(PerfMeter(40, emptyList()), p.ram)
        assertNull(p.ramUsed)
        assertNull(p.gpu)
        assertNull(p.netDown)
        assertEquals(emptyList<Long>(), p.netDownHistory)
        assertNull(p.npu)
    }

    @Test
    fun anObjectWithoutValueIsNoMeasure() {
        val p = parse("""{"perf":{"available":true,"cpu":{"history":[1,2]},"gpu":{"value":"x"},"npu":null}}""")!!
        assertNull(p.cpu)
        assertNull(p.gpu)
        assertNull(p.npu)
    }

    @Test
    fun unavailableOrAbsentGivesNull() {
        assertNull(parse("{}"))
        assertNull(parse("""{"perf":null}"""))
        assertNull(parse("""{"perf":"yes"}"""))
        assertNull(parse("""{"perf":{"available":false,"cpu":{"value":5}}}"""))
        assertNull(parse("""{"perf":{"cpu":{"value":5}}}"""))
        assertNotNull(parse("""{"perf":{"available":true}}"""))
    }

    @Test
    fun percentagesAreClampedAndJunkInAHistoryIsSkipped() {
        val p = parse("""{"perf":{"available":true,"cpu":{"value":140,"history":[-5,50,"x",null,120]}}}""")!!
        assertEquals(PerfMeter(100, listOf(0, 50, 100)), p.cpu)
    }

    @Test
    fun netNeedsTheReceivedRate() {
        val p = parse("""{"perf":{"available":true,"net":{"up":5,"up_history":[1]}}}""")!!
        assertNull(p.netDown)
    }
}
