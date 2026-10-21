package com.orizonx.client.actions

import org.json.JSONArray
import org.json.JSONObject

/** One percentage measure: the current [value] (0..100) and its [history] (oldest first, 0..100). */
data class PerfMeter(val value: Int, val history: List<Int>)

/**
 * The `perf` section of the PC's state: CPU, GPU, RAM, network and NPU, each null when the PC cannot measure it.
 * The network rates are in bytes per second.
 */
data class PerfState(
    val cpu: PerfMeter?,
    val cpuGhz: Float?,
    val gpu: PerfMeter?,
    val gpuMemUsed: Float?,
    val gpuMemTotal: Float?,
    val ram: PerfMeter?,
    val ramUsed: Float?,
    val ramTotal: Float?,
    val netDown: Long?,
    val netUp: Long?,
    val netDownHistory: List<Long>,
    val netUpHistory: List<Long>,
    val npu: PerfMeter?,
) {
    companion object {
        /** Null when the section is absent, not an object, or not `available: true`. Never throws. */
        fun parse(json: JSONObject?): PerfState? {
            if (json == null || json.opt("available") != true) return null
            val cpu = json.optJSONObject("cpu")
            val gpu = json.optJSONObject("gpu")
            val ram = json.optJSONObject("ram")
            val net = json.optJSONObject("net")
            val npu = json.optJSONObject("npu")
            val down = number(net, "down")
            return PerfState(
                cpu = meter(cpu),
                cpuGhz = number(cpu, "ghz")?.toFloat(),
                gpu = meter(gpu),
                gpuMemUsed = number(gpu, "mem_used")?.toFloat(),
                gpuMemTotal = number(gpu, "mem_total")?.toFloat(),
                ram = meter(ram),
                ramUsed = number(ram, "used")?.toFloat(),
                ramTotal = number(ram, "total")?.toFloat(),
                netDown = down?.toLong(),
                netUp = number(net, "up")?.toLong(),
                netDownHistory = if (down == null) emptyList() else longs(net?.optJSONArray("down_history")),
                netUpHistory = if (down == null) emptyList() else longs(net?.optJSONArray("up_history")),
                npu = meter(npu),
            )
        }

        private fun number(obj: JSONObject?, key: String): Double? =
            (obj?.opt(key) as? Number)?.toDouble()?.takeIf { it.isFinite() }

        private fun meter(obj: JSONObject?): PerfMeter? {
            val value = number(obj, "value") ?: return null
            val history = obj?.optJSONArray("history")
            val points = buildList {
                if (history != null) {
                    for (i in 0 until history.length()) {
                        val n = (history.opt(i) as? Number)?.toDouble()?.takeIf { it.isFinite() } ?: continue
                        add(percent(n))
                    }
                }
            }
            return PerfMeter(percent(value), points)
        }

        private fun percent(v: Double): Int = Math.round(v).toInt().coerceIn(0, 100)

        private fun longs(array: JSONArray?): List<Long> = buildList {
            if (array != null) {
                for (i in 0 until array.length()) {
                    val n = (array.opt(i) as? Number)?.toDouble()?.takeIf { it.isFinite() } ?: continue
                    add(n.toLong().coerceAtLeast(0L))
                }
            }
        }
    }
}
