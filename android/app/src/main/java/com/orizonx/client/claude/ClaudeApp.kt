package com.orizonx.client.claude

import org.json.JSONArray
import org.json.JSONObject

/** Lines added and removed ("+2140 −9"). */
data class ClaudeChanges(val added: Int, val removed: Int) {
    companion object {
        /** Null unless both counts are non-negative numbers. */
        fun parse(obj: JSONObject?): ClaudeChanges? {
            if (obj == null) return null
            val added = (obj.opt("added") as? Number)?.toInt() ?: return null
            val removed = (obj.opt("removed") as? Number)?.toInt() ?: return null
            if (added < 0 || removed < 0) return null
            return ClaudeChanges(added, removed)
        }
    }
}

/** A row of the detailed context: [tokens] and [percent] are the app's own strings ("540.3k", "54,0 %"). */
data class ClaudeContextItem(val name: String, val tokens: String, val percent: String)

/** The "Detailed context" block of the app: [percent] used, "[used] / [window]", then the rows and the deferred ones. */
data class ClaudeContext(
    val percent: Int?,
    val used: String,
    val window: String,
    val items: List<ClaudeContextItem>,
    val deferred: List<ClaudeContextItem>,
)

/** A background task of the open conversation: its [name] and the app's own [status] text ("running", "done"...). */
data class ClaudeTask(val name: String, val status: String)

/** A usage limit: [percent] used and the app's own text for the reset ("1 h 12 min", "sam. 11:00"). */
data class ClaudeLimit(val percent: Int, val reset: String)

/** Usage limits are global; [weekly] is only there when the app's limits panel has been read. */
data class ClaudeUsage(val session: ClaudeLimit?, val weekly: ClaudeLimit?)

/**
 * What the PC read from the Claude app's right panel (spec section 7.2). It belongs to the conversation that is open in
 * the app, named by [sessionTitle]; [seenAt] is when it was read (epoch seconds on the PC's clock).
 */
data class ClaudeApp(
    val sessionTitle: String,
    val seenAt: Long,
    val context: ClaudeContext?,
    val connected: Int?,
    val results: List<String>,
    val changes: ClaudeChanges?,
    val usage: ClaudeUsage?,
    val tasks: List<ClaudeTask> = emptyList(),
) {
    /** True when the app has [session] open: same title, ignoring case and surrounding spaces. */
    fun isOpen(session: ClaudeSession): Boolean =
        sessionTitle.isNotBlank() && sessionTitle.trim().equals(session.title.trim(), ignoreCase = true)

    companion object {
        const val MAX_RESULTS = 60
        const val MAX_ITEMS = 30
        const val MAX_TASKS = 30

        /** Null when absent or not an object; never throws. */
        fun parse(obj: JSONObject?): ClaudeApp? {
            if (obj == null) return null
            return ClaudeApp(
                sessionTitle = text(obj.opt("session_title")),
                seenAt = (obj.opt("seen_at") as? Number)?.toLong()?.coerceAtLeast(0L) ?: 0L,
                context = context(obj.optJSONObject("context")),
                connected = (obj.opt("connected") as? Number)?.toInt()?.takeIf { it >= 0 },
                results = strings(obj.optJSONArray("results")).take(MAX_RESULTS),
                changes = ClaudeChanges.parse(obj.optJSONObject("changes")),
                usage = usage(obj.optJSONObject("usage")),
                tasks = tasks(obj.optJSONArray("tasks")),
            )
        }

        /** A string, or a number written out; "" for anything else (null, objects, arrays). */
        private fun text(value: Any?): String = when (value) {
            is String -> value.trim()
            is Number -> value.toString()
            else -> ""
        }

        private fun strings(array: JSONArray?): List<String> =
            if (array == null) emptyList() else (0 until array.length()).mapNotNull { (array.opt(it) as? String)?.takeIf(String::isNotBlank) }

        private fun items(array: JSONArray?): List<ClaudeContextItem> {
            if (array == null) return emptyList()
            return (0 until array.length()).mapNotNull { i ->
                val item = array.optJSONObject(i) ?: return@mapNotNull null
                val name = text(item.opt("name")).ifEmpty { return@mapNotNull null }
                ClaudeContextItem(name, text(item.opt("tokens")), text(item.opt("percent")))
            }.take(MAX_ITEMS)
        }

        private fun tasks(array: JSONArray?): List<ClaudeTask> {
            if (array == null) return emptyList()
            return (0 until array.length()).mapNotNull { i ->
                val task = array.optJSONObject(i) ?: return@mapNotNull null
                val name = text(task.opt("name")).ifEmpty { return@mapNotNull null }
                ClaudeTask(name, text(task.opt("status")))
            }.take(MAX_TASKS)
        }

        private fun context(obj: JSONObject?): ClaudeContext? {
            if (obj == null) return null
            return ClaudeContext(
                percent = (obj.opt("percent") as? Number)?.toInt()?.takeIf { it in 0..100 },
                used = text(obj.opt("used")),
                window = text(obj.opt("window")),
                items = items(obj.optJSONArray("items")),
                deferred = items(obj.optJSONArray("deferred")),
            )
        }

        private fun limit(obj: JSONObject?): ClaudeLimit? {
            if (obj == null) return null
            val percent = (obj.opt("percent") as? Number)?.toInt()?.takeIf { it in 0..100 } ?: return null
            return ClaudeLimit(percent, text(obj.opt("reset")))
        }

        private fun usage(obj: JSONObject?): ClaudeUsage? {
            if (obj == null) return null
            val usage = ClaudeUsage(limit(obj.optJSONObject("session")), limit(obj.optJSONObject("weekly")))
            return if (usage.session == null && usage.weekly == null) null else usage
        }
    }
}

/** The sessions grouped by project, as the Claude app's sidebar does. */
object ClaudeGroups {
    data class Group(val project: String, val sessions: List<ClaudeSession>)

    /**
     * One group per project (a missing project is its own group, with the name ""). Groups are ordered by their most
     * recent session, newest first, and the sessions inside a group are newest first. Ties keep the incoming order.
     */
    fun of(sessions: List<ClaudeSession>): List<Group> =
        sessions.groupBy { it.project }
            .map { (project, list) -> Group(project, list.sortedByDescending { it.updated }) }
            .sortedByDescending { group -> group.sessions.maxOf { it.updated } }
}
