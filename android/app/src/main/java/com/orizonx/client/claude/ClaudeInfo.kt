package com.orizonx.client.claude

import org.json.JSONArray
import org.json.JSONObject

/** One Claude Code session of the PC, as reported in the `claude` section (spec section 3). Unknown fields are "" or null. */
data class ClaudeSession(
    val id: String,
    val title: String,
    val project: String,
    val branch: String,
    /** Last activity, epoch seconds on the PC's clock; 0 when unknown. */
    val updated: Long,
    val working: Boolean,
    val model: String,
    val effort: String,
    val mode: String,
    val tokens: Long?,
    val lastPrompt: String,
    val lastResult: String,
    val files: List<String>,
    /** "desktop" or "cli". */
    val entry: String,
)

/** An MCP connector: [scope] is "global" or the name of a project. */
data class ClaudeConnector(val name: String, val type: String, val scope: String)

/** The `claude` section when the PC has Claude Code data ([available] true). */
data class ClaudeInfo(val sessions: List<ClaudeSession>, val connectors: List<ClaudeConnector>) {
    /** The connectors that apply to [session]: the global ones, then those of its project. */
    fun connectorsFor(session: ClaudeSession): List<ClaudeConnector> =
        connectors.filter { it.scope == GLOBAL } + connectors.filter { it.scope != GLOBAL && it.scope.equals(session.project, ignoreCase = true) }

    companion object {
        const val GLOBAL = "global"
        const val MAX_SESSIONS = 30
        const val MAX_CONNECTORS = 30
        const val MAX_FILES = 40

        /** Null (no Claude button) when the section is absent or not available. Never throws: bad entries are skipped. */
        fun parse(section: JSONObject?): ClaudeInfo? {
            if (section == null || section.opt("available") != true) return null
            val sessions = objects(section.optJSONArray("sessions")).mapNotNull(::session).take(MAX_SESSIONS)
            val connectors = objects(section.optJSONArray("connectors")).mapNotNull(::connector).take(MAX_CONNECTORS)
            return ClaudeInfo(sessions, connectors)
        }

        private fun objects(array: JSONArray?): List<JSONObject> =
            if (array == null) emptyList() else (0 until array.length()).mapNotNull { array.optJSONObject(it) }

        private fun text(obj: JSONObject, key: String): String = (obj.opt(key) as? String)?.trim() ?: ""

        private fun session(obj: JSONObject): ClaudeSession? {
            val id = text(obj, "id").ifEmpty { return null }
            val files = obj.optJSONArray("files")
            return ClaudeSession(
                id = id,
                title = text(obj, "title").ifEmpty { id.take(8) },
                project = text(obj, "project"),
                branch = text(obj, "branch"),
                updated = (obj.opt("updated") as? Number)?.toLong()?.coerceAtLeast(0L) ?: 0L,
                working = obj.opt("status") == "working",
                model = text(obj, "model"),
                effort = text(obj, "effort"),
                mode = text(obj, "mode"),
                tokens = (obj.opt("tokens") as? Number)?.toLong()?.takeIf { it >= 0 },
                // Keep the text as the PC sent it (line breaks included), only dropping blank edges.
                lastPrompt = text(obj, "last_prompt"),
                lastResult = text(obj, "last_result"),
                files = if (files == null) emptyList() else (0 until files.length()).mapNotNull { (files.opt(it) as? String)?.takeIf(String::isNotBlank) }.take(MAX_FILES),
                entry = if (text(obj, "entry") == "desktop") "desktop" else "cli",
            )
        }

        private fun connector(obj: JSONObject): ClaudeConnector? {
            val name = text(obj, "name").ifEmpty { return null }
            return ClaudeConnector(name, text(obj, "type"), text(obj, "scope").ifEmpty { GLOBAL })
        }
    }
}

/** Which session the screen shows: the one the user picked while it still exists, else the most recent. */
object ClaudeSelection {
    fun resolve(sessions: List<ClaudeSession>, selectedId: String?): String? {
        if (sessions.isEmpty()) return null
        if (selectedId != null && sessions.any { it.id == selectedId }) return selectedId
        return mostRecent(sessions)?.id
    }

    /** The session with the latest activity; the first of them in list order on a tie. */
    fun mostRecent(sessions: List<ClaudeSession>): ClaudeSession? = sessions.maxByOrNull { it.updated }
}
