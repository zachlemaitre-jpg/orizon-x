package com.orizonx.client.claude

import org.json.JSONObject
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

class ClaudeAppTest {
    private val appJson = """{
      "session_title":"OrizonX App","seen_at":1800000000,
      "context":{"percent":61,"used":"598.5k","window":"1M",
        "items":[{"name":"Messages","tokens":"540.3k","percent":"54,0 %"},{"name":"System tools","tokens":"9.1k","percent":"0,9 %"}],
        "deferred":[{"name":"MCP tools (deferred)","tokens":"12k"}]},
      "connected":1,"results":["a.kt","b/c.kt"],"changes":{"added":2140,"removed":9},
      "usage":{"session":{"percent":42,"reset":"1 h 12 min"},"weekly":{"percent":34,"reset":"sam. 11:00"}}
    }"""

    private fun section(app: String?, sessions: String = "[]") =
        """{"available":true,"sessions":$sessions${if (app != null) ""","app":$app""" else ""}}"""

    private fun parse(json: String) = ClaudeInfo.parse(JSONObject(json))!!

    @Test
    fun theAppPanelIsParsed() {
        val app = parse(section(appJson)).app!!
        assertEquals("OrizonX App", app.sessionTitle)
        assertEquals(1_800_000_000L, app.seenAt)
        val ctx = app.context!!
        assertEquals(61, ctx.percent)
        assertEquals("598.5k", ctx.used)
        assertEquals("1M", ctx.window)
        assertEquals(ClaudeContextItem("Messages", "540.3k", "54,0 %"), ctx.items[0])
        assertEquals(2, ctx.items.size)
        assertEquals(listOf(ClaudeContextItem("MCP tools (deferred)", "12k", "")), ctx.deferred)
        assertEquals(1, app.connected)
        assertEquals(listOf("a.kt", "b/c.kt"), app.results)
        assertEquals(ClaudeChanges(2140, 9), app.changes)
        assertEquals(ClaudeLimit(42, "1 h 12 min"), app.usage!!.session)
        assertEquals(ClaudeLimit(34, "sam. 11:00"), app.usage!!.weekly)
    }

    @Test
    fun noAppSectionMeansNoApp() {
        assertNull(parse(section(null)).app)
        assertNull(parse(section("null")).app)
        assertNull(parse(section("5")).app)
        assertNull(parse(section("[]")).app)
    }

    @Test
    fun weeklyLimitCanBeNull() {
        val app = parse(section("""{"usage":{"session":{"percent":42,"reset":"1 h"},"weekly":null}}""")).app!!
        assertEquals(ClaudeLimit(42, "1 h"), app.usage!!.session)
        assertNull(app.usage!!.weekly)
    }

    @Test
    fun usageWithoutAnyLimitIsNull() {
        assertNull(parse(section("""{"usage":{"session":null,"weekly":null}}""")).app!!.usage)
        assertNull(parse(section("""{"usage":null}""")).app!!.usage)
        assertNull(parse(section("""{"usage":{"session":{"percent":"high"}}}""")).app!!.usage)
        assertNull(parse(section("""{"usage":{"session":{"percent":150}}}""")).app!!.usage)
    }

    @Test
    fun anEmptyAppObjectIsAllNulls() {
        val app = parse(section("{}")).app!!
        assertEquals("", app.sessionTitle)
        assertEquals(0L, app.seenAt)
        assertNull(app.context)
        assertNull(app.connected)
        assertTrue(app.results.isEmpty())
        assertNull(app.changes)
        assertNull(app.usage)
    }

    @Test
    fun oddValuesAreTolerated() {
        val app = parse(
            section(
                """{"session_title":5,"seen_at":"now","context":{"percent":"61","used":598,"window":null,
                     "items":[5,{"tokens":"1"},{"name":"X","tokens":12,"percent":null}],"deferred":"x"},
                    "connected":-1,"results":[1,"ok",""],"changes":{"added":"2","removed":1}}""",
            ),
        ).app!!
        assertEquals("5", app.sessionTitle)
        assertEquals(0L, app.seenAt)
        assertNull(app.context!!.percent)
        assertEquals("598", app.context!!.used)
        assertEquals("", app.context!!.window)
        assertEquals(listOf(ClaudeContextItem("X", "12", "")), app.context!!.items)
        assertTrue(app.context!!.deferred.isEmpty())
        assertNull(app.connected)
        assertEquals(listOf("ok"), app.results)
        assertNull(app.changes)
    }

    @Test
    fun changesArePerSessionAndNullable() {
        val info = parse(
            section(
                null,
                """[{"id":"a","changes":{"added":3,"removed":0}},{"id":"b","changes":null},{"id":"c"},
                   {"id":"d","changes":{"added":-1,"removed":2}},{"id":"e","changes":5}]""",
            ),
        )
        val changes = info.sessions.associate { it.id to it.changes }
        assertEquals(ClaudeChanges(3, 0), changes["a"])
        assertNull(changes["b"])
        assertNull(changes["c"])
        assertNull(changes["d"])
        assertNull(changes["e"])
    }

    @Test
    fun listsAreCapped() {
        val results = (1..100).joinToString(",") { "\"f$it\"" }
        val items = (1..50).joinToString(",") { """{"name":"n$it"}""" }
        val app = parse(section("""{"results":[$results],"context":{"items":[$items]}}""")).app!!
        assertEquals(60, app.results.size)
        assertEquals(30, app.context!!.items.size)
    }

    // --- Title matching ---------------------------------------------------------------------------------

    private fun session(title: String) = ClaudeSession(
        "s", title, "p", "", 0, false, "", "", "", null, "", "", emptyList(), "cli",
    )

    @Test
    fun theOpenConversationIsFoundByTitle() {
        val app = parse(section(appJson)).app!!
        assertTrue(app.isOpen(session("OrizonX App")))
        assertTrue(app.isOpen(session("  orizonx app ")))
        assertFalse(app.isOpen(session("Other")))
        assertFalse(app.isOpen(session("")))
    }

    @Test
    fun anEmptyAppTitleMatchesNothing() {
        val app = parse(section("""{"session_title":""}""")).app!!
        assertFalse(app.isOpen(session("")))
        assertFalse(app.isOpen(session("x")))
    }

    // --- Grouping ---------------------------------------------------------------------------------------

    private fun s(id: String, project: String, updated: Long) = ClaudeSession(
        id, id, project, "", updated, false, "", "", "", null, "", "", emptyList(), "cli",
    )

    @Test
    fun groupsAreOrderedByTheirMostRecentSession() {
        val groups = ClaudeGroups.of(
            listOf(s("a1", "alpha", 100), s("b1", "beta", 500), s("a2", "alpha", 900), s("c1", "gamma", 300)),
        )
        assertEquals(listOf("alpha", "beta", "gamma"), groups.map { it.project })
    }

    @Test
    fun sessionsInAGroupAreNewestFirst() {
        val groups = ClaudeGroups.of(listOf(s("a1", "alpha", 100), s("a3", "alpha", 300), s("a2", "alpha", 200)))
        assertEquals(listOf("a3", "a2", "a1"), groups.single().sessions.map { it.id })
    }

    @Test
    fun sessionsWithoutAProjectFormTheirOwnGroup() {
        val groups = ClaudeGroups.of(listOf(s("x", "", 50), s("y", "p", 40)))
        assertEquals(listOf("", "p"), groups.map { it.project })
    }

    @Test
    fun noSessionsNoGroups() {
        assertTrue(ClaudeGroups.of(emptyList()).isEmpty())
    }

    // --- Misc formats -----------------------------------------------------------------------------------

    @Test
    fun seenAtIsTheClockTimeOnThePc() {
        // 2025-10-11 12:32:00 UTC.
        assertEquals("12:32", ClaudeFormat.clockTime(1_760_185_920L, 0))
        assertEquals("14:32", ClaudeFormat.clockTime(1_760_185_920L, 120))
        assertEquals("07:32", ClaudeFormat.clockTime(1_760_185_920L, -300))
        assertEquals("00:05", ClaudeFormat.clockTime(5 * 60L, 0))
        assertEquals("23:55", ClaudeFormat.clockTime(5 * 60L, -10))
    }

    @Test
    fun barFractionIsClamped() {
        assertEquals(0.61f, ClaudeFormat.fraction(61), 0.0001f)
        assertEquals(0f, ClaudeFormat.fraction(null), 0f)
        assertEquals(1f, ClaudeFormat.fraction(140), 0f)
        assertEquals(0f, ClaudeFormat.fraction(-5), 0f)
        assertNotNull(parse(section(appJson)).app)
    }

    // --- Background tasks -----------------------------------------------------------------------------

    @Test
    fun backgroundTasksAreParsed() {
        val app = parse(section("""{"tasks":[{"name":"npm run dev","status":"running"},{"name":"tests","status":"done"}]}""")).app!!
        assertEquals(listOf(ClaudeTask("npm run dev", "running"), ClaudeTask("tests", "done")), app.tasks)
    }

    @Test
    fun missingEmptyOrOddTasksAreAnEmptyList() {
        assertTrue(parse(section("{}")).app!!.tasks.isEmpty())
        assertTrue(parse(section("""{"tasks":[]}""")).app!!.tasks.isEmpty())
        assertTrue(parse(section("""{"tasks":null}""")).app!!.tasks.isEmpty())
        assertTrue(parse(section("""{"tasks":"x"}""")).app!!.tasks.isEmpty())
        assertEquals(
            listOf(ClaudeTask("ok", "")),
            parse(section("""{"tasks":[5,null,{"status":"x"},{"name":""},{"name":"ok","status":null}]}""")).app!!.tasks,
        )
    }

    @Test
    fun tasksAreCapped() {
        val tasks = (1..50).joinToString(",") { """{"name":"t$it"}""" }
        assertEquals(30, parse(section("""{"tasks":[$tasks]}""")).app!!.tasks.size)
    }

    @Test
    fun taskElapsedAndStatusAreParsed() {
        val app = parse(
            section(
                """{"tasks":[{"name":"npm run dev","status":"running","elapsed":"2 min"},{"name":"tests","status":"completed","elapsed":"14 s"},
                    {"name":"bare","status":"Running"},{"name":"odd","status":5,"elapsed":7}],"tasks_done":3}""",
            ),
        ).app!!
        assertEquals(listOf("npm run dev", "tests", "bare", "odd"), app.tasks.map { it.name })
        assertEquals(listOf("2 min", "14 s", "", "7"), app.tasks.map { it.elapsed })
        assertEquals(listOf(true, false, true, false), app.tasks.map { it.running })
        assertEquals(3, app.tasksDone)
    }

    @Test
    fun tasksDoneIsZeroWhenMissingNegativeOrNotANumber() {
        assertEquals(0, parse(section("{}")).app!!.tasksDone)
        assertEquals(0, parse(section("""{"tasks_done":-2}""")).app!!.tasksDone)
        assertEquals(0, parse(section("""{"tasks_done":"3"}""")).app!!.tasksDone)
        assertEquals(0, parse(section("""{"tasks_done":null}""")).app!!.tasksDone)
        assertEquals(12, parse(section("""{"tasks_done":12}""")).app!!.tasksDone)
    }

    @Test
    fun aTaskWithoutAStatusIsNotRunning() {
        assertTrue(!ClaudeTask("x", "").running)
        assertTrue(ClaudeTask("x", "RUNNING").running)
    }

    // --- Each limit keeps its own reading time -----------------------------------------------------------------------

    @Test
    fun eachLimitHasItsOwnSeenAt() {
        val app = parse(
            section(
                """{"seen_at":1000,"usage":{"session":{"percent":42,"reset":"1 h"},"weekly":{"percent":34,"reset":"sam."},
                    "session_seen_at":990,"weekly_seen_at":400}}""",
            ),
        ).app!!
        assertEquals(990L, app.sessionLimitSeenAt())
        assertEquals(400L, app.weeklyLimitSeenAt())
    }

    @Test
    fun withoutItsOwnTimeALimitUsesThePanelsSeenAt() {
        val app = parse(section("""{"seen_at":1000,"usage":{"session":{"percent":42,"reset":"1 h"},"weekly":null}}""")).app!!
        assertEquals(1000L, app.sessionLimitSeenAt())
        assertEquals(1000L, app.weeklyLimitSeenAt())
    }

    @Test
    fun theWeeklyTimeSurvivesWhenOnlyTheSessionIsFresh() {
        // The PC keeps the old weekly value and time while a new reading only brings the session limit.
        val app = parse(
            section(
                """{"seen_at":5000,"usage":{"session":{"percent":10,"reset":"4 h"},"weekly":{"percent":34,"reset":"sam."},
                    "session_seen_at":5000,"weekly_seen_at":1200}}""",
            ),
        ).app!!
        assertEquals(10, app.usage!!.session!!.percent)
        assertEquals(34, app.usage!!.weekly!!.percent)
        assertEquals(5000L, app.sessionLimitSeenAt())
        assertEquals(1200L, app.weeklyLimitSeenAt())
    }

    @Test
    fun badSeenAtValuesAreIgnored() {
        val app = parse(section("""{"seen_at":7,"usage":{"session":{"percent":1,"reset":""},"session_seen_at":"x","weekly_seen_at":-3}}""")).app!!
        assertEquals(7L, app.sessionLimitSeenAt())
        assertEquals(7L, app.weeklyLimitSeenAt())
    }
}
