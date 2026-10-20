package com.orizonx.client.claude

import org.json.JSONObject
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

class ClaudeInfoTest {
    private fun parse(json: String) = ClaudeInfo.parse(JSONObject(json))

    private val full = """{
      "available": true,
      "sessions": [
        {"id":"s1","title":"Fix the login","project":"orizon-x","branch":"main","updated":1800000000,"status":"working",
         "model":"claude-opus-4","effort":"high","mode":"acceptEdits","tokens":561234,
         "last_prompt":"fix it","last_result":"Done.\nTests pass.","files":["a.kt","dir/b.kt"],"entry":"desktop"},
        {"id":"s2","title":"Docs","project":"site","branch":"","updated":1799990000,"status":"idle","tokens":null,"entry":"cli"}
      ],
      "connectors": [
        {"name":"github","type":"http","scope":"global"},
        {"name":"db","type":"stdio","scope":"orizon-x"}
      ]
    }"""

    @Test
    fun fullSectionIsParsed() {
        val info = parse(full)!!
        assertEquals(2, info.sessions.size)
        val s = info.sessions[0]
        assertEquals("s1", s.id)
        assertEquals("Fix the login", s.title)
        assertEquals("orizon-x", s.project)
        assertEquals("main", s.branch)
        assertEquals(1_800_000_000L, s.updated)
        assertTrue(s.working)
        assertEquals("claude-opus-4", s.model)
        assertEquals("high", s.effort)
        assertEquals("acceptEdits", s.mode)
        assertEquals(561_234L, s.tokens)
        assertEquals("fix it", s.lastPrompt)
        assertEquals("Done.\nTests pass.", s.lastResult)
        assertEquals(listOf("a.kt", "dir/b.kt"), s.files)
        assertEquals("desktop", s.entry)
        assertEquals(listOf(ClaudeConnector("github", "http", "global"), ClaudeConnector("db", "stdio", "orizon-x")), info.connectors)
    }

    @Test
    fun missingFieldsAreEmptyOrNull() {
        val s = parse(full)!!.sessions[1]
        assertFalse(s.working)
        assertNull(s.tokens)
        assertEquals("", s.model)
        assertEquals("", s.lastResult)
        assertEquals(emptyList<String>(), s.files)
        assertEquals("cli", s.entry)
    }

    @Test
    fun absentOrUnavailableSectionIsNull() {
        assertNull(ClaudeInfo.parse(null))
        assertNull(parse("""{"available":false}"""))
        assertNull(parse("""{"sessions":[]}"""))
        assertNull(parse("""{"available":"true"}"""))
    }

    @Test
    fun availableWithoutSessionsIsAnEmptyList() {
        val info = parse("""{"available":true}""")!!
        assertTrue(info.sessions.isEmpty())
        assertTrue(info.connectors.isEmpty())
    }

    @Test
    fun badEntriesAreSkippedAndBadTypesTolerated() {
        val info = parse(
            """{"available":true,"sessions":[
                5, null, {"title":"no id"}, {"id":""}, {"id":7},
                {"id":"ok","title":null,"updated":"yesterday","tokens":"many","files":"x","status":5,"entry":3}],
               "connectors":[{"name":""},{"type":"http"},"x",{"name":"fs"}]}""",
        )!!
        assertEquals(listOf("ok"), info.sessions.map { it.id })
        val s = info.sessions[0]
        assertEquals("ok", s.title) // falls back to the id
        assertEquals(0L, s.updated)
        assertNull(s.tokens)
        assertEquals(emptyList<String>(), s.files)
        assertFalse(s.working)
        assertEquals("cli", s.entry)
        assertEquals(listOf(ClaudeConnector("fs", "", "global")), info.connectors)
    }

    @Test
    fun negativeNumbersAreIgnored() {
        val s = parse("""{"available":true,"sessions":[{"id":"a","updated":-5,"tokens":-1}]}""")!!.sessions[0]
        assertEquals(0L, s.updated)
        assertNull(s.tokens)
    }

    @Test
    fun listsAreCapped() {
        val sessions = (1..40).joinToString(",") { """{"id":"s$it"}""" }
        val connectors = (1..40).joinToString(",") { """{"name":"c$it"}""" }
        val files = (1..60).joinToString(",") { "\"f$it\"" }
        val info = parse("""{"available":true,"sessions":[$sessions,{"id":"x","files":[$files]}],"connectors":[$connectors]}""")!!
        assertEquals(30, info.sessions.size)
        assertEquals(30, info.connectors.size)
        val withFiles = parse("""{"available":true,"sessions":[{"id":"x","files":[$files]}]}""")!!.sessions[0]
        assertEquals(40, withFiles.files.size)
    }

    @Test
    fun connectorsOfASessionAreTheGlobalOnesAndItsProjects() {
        val info = parse(full)!!
        assertEquals(listOf("github", "db"), info.connectorsFor(info.sessions[0]).map { it.name })
        assertEquals(listOf("github"), info.connectorsFor(info.sessions[1]).map { it.name })
    }

    @Test
    fun projectScopeMatchesIgnoringCase() {
        val info = ClaudeInfo(
            emptyList(),
            listOf(ClaudeConnector("a", "stdio", "Orizon-X"), ClaudeConnector("b", "stdio", "other"), ClaudeConnector("g", "http", "global")),
        )
        val s = parse(full)!!.sessions[0]
        assertEquals(listOf("g", "a"), info.connectorsFor(s).map { it.name })
    }

    // --- Selection -----------------------------------------------------------------------------------

    private fun sessions(vararg idAndUpdated: Pair<String, Long>) =
        parse(
            """{"available":true,"sessions":[${idAndUpdated.joinToString(",") { """{"id":"${it.first}","updated":${it.second}}""" }}]}""",
        )!!.sessions

    @Test
    fun defaultSelectionIsTheMostRecent() {
        val list = sessions("a" to 100, "b" to 300, "c" to 200)
        assertEquals("b", ClaudeSelection.resolve(list, null))
        assertEquals("b", ClaudeSelection.mostRecent(list)!!.id)
    }

    @Test
    fun aTieGoesToTheFirstOfThem() {
        assertEquals("a", ClaudeSelection.resolve(sessions("a" to 100, "b" to 100), null))
    }

    @Test
    fun theSelectionIsKeptByIdWhenTheListUpdates() {
        val before = sessions("a" to 100, "b" to 300)
        assertEquals("a", ClaudeSelection.resolve(before, "a"))
        // A newer session appears and the order changes: the pick stays.
        val after = sessions("c" to 500, "b" to 300, "a" to 100)
        assertEquals("a", ClaudeSelection.resolve(after, "a"))
    }

    @Test
    fun aSelectionThatDisappearedFallsBackToTheMostRecent() {
        val list = sessions("c" to 500, "b" to 300)
        assertEquals("c", ClaudeSelection.resolve(list, "a"))
    }

    @Test
    fun noSessionsMeansNoSelection() {
        assertNull(ClaudeSelection.resolve(emptyList(), "a"))
        assertNull(ClaudeSelection.mostRecent(emptyList()))
        assertNotNull(ClaudeSelection.resolve(sessions("a" to 1), null))
    }
}
