package com.orizonx.client.ui

import androidx.compose.animation.core.LinearEasing
import androidx.compose.animation.core.RepeatMode
import androidx.compose.animation.core.animateFloat
import androidx.compose.animation.core.infiniteRepeatable
import androidx.compose.animation.core.rememberInfiniteTransition
import androidx.compose.animation.core.tween
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.horizontalScroll
import androidx.compose.foundation.interaction.MutableInteractionSource
import androidx.compose.foundation.interaction.collectIsPressedAsState
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.BoxWithConstraints
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxHeight
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.BasicText
import androidx.compose.foundation.verticalScroll
import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberUpdatedState
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.alpha
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.text.TextStyle
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.orizonx.client.actions.ActionMessages
import com.orizonx.client.actions.ActionsState
import com.orizonx.client.claude.ClaudeApp
import com.orizonx.client.claude.ClaudeChanges
import com.orizonx.client.claude.ClaudeFormat
import com.orizonx.client.claude.ClaudeGroups
import com.orizonx.client.claude.ClaudeInfo
import com.orizonx.client.claude.ClaudeLimit
import com.orizonx.client.claude.ClaudeSelection
import com.orizonx.client.claude.ClaudeSession
import com.orizonx.client.i18n.LocalLang
import com.orizonx.client.i18n.S
import com.orizonx.client.i18n.tr
import org.json.JSONObject
import kotlin.math.min

private val ClaudeGreen = Color(0xFF34C77B)
private val ClaudeRed = Color(0xFFE5484D)
private val ClaudeGrey = Color(0xFF9AA0A6)
private val PanelShape = RoundedCornerShape(16.dp)
private val ChipShape = RoundedCornerShape(12.dp)
private val RowShape = RoundedCornerShape(12.dp)

/**
 * The PC's Claude Code sessions, read only, in the layout of the user's mock-up (glass style, no other colours than the
 * green and red of the line counts). Left: the clock block, four buttons that press the matching buttons of the Claude app,
 * and the conversations grouped by project. Right: the chosen session, with the data the PC read from the app's right
 * panel when that conversation is the one open in the app. Portrait shows the left column, then the panel after a tap.
 * The app panel is only read while this screen is open (`claude.watch`).
 */
@Composable
fun ClaudeCodeScreen(
    state: ActionsState,
    info: ClaudeInfo,
    nowSeconds: Long,
    onAction: (JSONObject) -> Unit,
    onClose: () -> Unit,
    tap: () -> Unit,
    modifier: Modifier = Modifier,
) {
    val send by rememberUpdatedState(onAction)
    DisposableEffect(Unit) {
        send(ActionMessages.claudeWatch(true))
        onDispose { send(ActionMessages.claudeWatch(false)) }
    }

    var selectedId by remember { mutableStateOf<String?>(null) }
    var detailsOpen by remember { mutableStateOf(false) }
    val currentId = ClaudeSelection.resolve(info.sessions, selectedId)
    val current = info.sessions.firstOrNull { it.id == currentId }
    val groups = remember(info.sessions) { ClaudeGroups.of(info.sessions) }

    BoxWithConstraints(modifier.fillMaxSize()) {
        val width = maxWidth
        val landscape = width >= 700.dp
        val pick: (ClaudeSession) -> Unit = { session ->
            tap()
            selectedId = session.id
            detailsOpen = true
            send(ActionMessages.claudeOpen(session.title))
        }
        val left: @Composable (Modifier, Dp) -> Unit = { m, width ->
            LeftColumn(state, groups, currentId, width, m, tap, send, pick)
        }
        val right: @Composable (Modifier) -> Unit = { m ->
            RightPanel(current, info, state, nowSeconds, m, tap, send, onClose, back = if (landscape) null else ({ tap(); detailsOpen = false }), portrait = !landscape)
        }
        if (landscape) {
            Row(Modifier.fillMaxSize().padding(horizontal = 12.dp, vertical = 12.dp), horizontalArrangement = Arrangement.spacedBy(14.dp)) {
                left(Modifier.weight(0.32f).fillMaxHeight(), width * 0.32f)
                right(Modifier.weight(0.68f).fillMaxHeight())
            }
        } else if (detailsOpen && current != null) {
            right(Modifier.fillMaxSize().padding(horizontal = 12.dp, vertical = 12.dp))
        } else {
            Column(Modifier.fillMaxSize().padding(horizontal = 12.dp, vertical = 12.dp)) {
                Row(Modifier.fillMaxWidth().height(40.dp), horizontalArrangement = Arrangement.End, verticalAlignment = Alignment.CenterVertically) {
                    CloseButton(tap, onClose)
                }
                left(Modifier.fillMaxSize(), width)
            }
        }
    }
}

@Composable
private fun CloseButton(tap: () -> Unit, onClose: () -> Unit) {
    val description = tr(S.CLAUDE_CLOSE_DESC)
    Box(
        Modifier
            .size(40.dp)
            .clip(RoundedCornerShape(20.dp))
            .clickable { tap(); onClose() }
            .semantics { contentDescription = description },
        contentAlignment = Alignment.Center,
    ) {
        BasicText("✕", style = TextStyle(color = Color.White, fontSize = 20.sp))
    }
}

// --- Left column -------------------------------------------------------------------------------------------

@Composable
private fun LeftColumn(
    state: ActionsState,
    groups: List<ClaudeGroups.Group>,
    selectedId: String?,
    width: Dp,
    modifier: Modifier,
    tap: () -> Unit,
    send: (JSONObject) -> Unit,
    onPick: (ClaudeSession) -> Unit,
) {
    Column(modifier, verticalArrangement = Arrangement.spacedBy(10.dp)) {
        ClockBlock(state.clock, state.battery, min(44f, width.value / 4.1f), 15f)
        Pill(tr(S.CLAUDE_NEW), selected = false, onClick = { tap(); send(ActionMessages.claudeNew()) }, modifier = Modifier.fillMaxWidth())
        Pill(tr(S.CLAUDE_ARTIFACTS), selected = false, onClick = { tap(); send(ActionMessages.claudeArtifacts()) }, modifier = Modifier.fillMaxWidth())
        Pill(tr(S.CLAUDE_CUSTOMIZE), selected = false, onClick = { tap(); send(ActionMessages.claudeCustomize()) }, modifier = Modifier.fillMaxWidth())
        Pill(tr(S.CLAUDE_MORE), selected = false, onClick = { tap(); send(ActionMessages.claudeMore()) }, modifier = Modifier.fillMaxWidth())
        Panel(Modifier.weight(1f).fillMaxWidth(), padding = 10.dp) {
            Label(tr(S.CLAUDE_CONVERSATIONS))
            if (groups.isEmpty()) {
                BasicText(tr(S.CLAUDE_NO_SESSIONS), style = TextStyle(color = Color.White.copy(alpha = 0.6f), fontSize = 14.sp))
            } else {
                Conversations(groups, selectedId, Modifier.weight(1f), onPick)
            }
        }
    }
}

/** The conversations, grouped by project like the app's sidebar; this block scrolls on its own. */
@Composable
private fun Conversations(groups: List<ClaudeGroups.Group>, selectedId: String?, modifier: Modifier, onPick: (ClaudeSession) -> Unit) {
    LazyColumn(modifier.fillMaxWidth(), verticalArrangement = Arrangement.spacedBy(2.dp)) {
        for (group in groups) {
            item(key = "group:${group.project}") {
                BasicText(
                    group.project.ifEmpty { tr(S.CLAUDE_NO_PROJECT) },
                    style = TextStyle(color = Color.White.copy(alpha = 0.55f), fontSize = 12.sp, fontWeight = FontWeight.SemiBold),
                    maxLines = 1,
                    overflow = TextOverflow.Ellipsis,
                    modifier = Modifier.padding(start = 6.dp, top = 8.dp, bottom = 2.dp),
                )
            }
            items(group.sessions, key = { it.id }) { session ->
                val selected = session.id == selectedId
                Row(
                    Modifier
                        .fillMaxWidth()
                        .clip(RowShape)
                        .background(Color.White.copy(alpha = if (selected) 0.20f else 0f))
                        .then(if (selected) Modifier.border(1.dp, Color.White.copy(alpha = 0.55f), RowShape) else Modifier)
                        .clickable { onPick(session) }
                        .padding(horizontal = 8.dp, vertical = 9.dp),
                    verticalAlignment = Alignment.CenterVertically,
                ) {
                    StatusDot(session.working)
                    Spacer(Modifier.width(10.dp))
                    BasicText(
                        session.title,
                        style = TextStyle(color = Color.White, fontSize = 15.sp, fontWeight = if (selected) FontWeight.SemiBold else FontWeight.Normal),
                        maxLines = 1,
                        overflow = TextOverflow.Ellipsis,
                    )
                }
            }
        }
    }
}

// --- Right panel -------------------------------------------------------------------------------------------

@Composable
private fun RightPanel(
    session: ClaudeSession?,
    info: ClaudeInfo,
    state: ActionsState,
    nowSeconds: Long,
    modifier: Modifier,
    tap: () -> Unit,
    send: (JSONObject) -> Unit,
    onClose: () -> Unit,
    back: (() -> Unit)?,
    portrait: Boolean,
) {
    val app = info.app
    // The app's panel belongs to the conversation open in the app; limits are global.
    val appForSession = if (session != null && app != null && app.isOpen(session)) app else null
    val open: (JSONObject) -> () -> Unit = { action -> { tap(); send(action) } }
    val showContext = open(ActionMessages.claudeShowContext())
    val showUsage = open(ActionMessages.claudeShowUsage())
    BoxWithConstraints(modifier) {
        val wide = !portrait
        // Roughly square, half the panel, but short enough that the changes and the results stay above the fold.
        val topHeight = (maxWidth / 2).coerceAtMost(340.dp)
        Column(Modifier.fillMaxSize().verticalScroll(rememberScrollState()), verticalArrangement = Arrangement.spacedBy(10.dp)) {
            if (session != null) {
                Header(session, tap, send, onClose, back)
                if (wide) {
                    Row(Modifier.fillMaxWidth().height(topHeight), horizontalArrangement = Arrangement.spacedBy(10.dp)) {
                        ContextBlock(session, appForSession, Modifier.weight(1f).fillMaxHeight(), true, showContext)
                        Column(Modifier.weight(1f).fillMaxHeight(), verticalArrangement = Arrangement.spacedBy(10.dp)) {
                            LimitBlock(S.CLAUDE_SESSION_LIMIT, app?.usage?.session, app, state, Modifier.weight(1f).fillMaxWidth(), showUsage)
                            LimitBlock(S.CLAUDE_WEEKLY_LIMIT, app?.usage?.weekly, app, state, Modifier.weight(1f).fillMaxWidth(), showUsage)
                        }
                    }
                } else {
                    ContextBlock(session, appForSession, Modifier.fillMaxWidth(), false, showContext)
                    Row(Modifier.fillMaxWidth().height(LimitBlockHeight), horizontalArrangement = Arrangement.spacedBy(10.dp)) {
                        LimitBlock(S.CLAUDE_SESSION_LIMIT, app?.usage?.session, app, state, Modifier.weight(1f).fillMaxHeight(), showUsage)
                        LimitBlock(S.CLAUDE_WEEKLY_LIMIT, app?.usage?.weekly, app, state, Modifier.weight(1f).fillMaxHeight(), showUsage)
                    }
                }
                ChangesLine(appForSession?.changes ?: session.changes)
                val files = appForSession?.results?.takeIf { it.isNotEmpty() } ?: session.files
                if (wide) {
                    // Results on the left, background tasks on the right, same height: no scrolling on a tablet.
                    Row(Modifier.fillMaxWidth().height(LowerBlocksHeight), horizontalArrangement = Arrangement.spacedBy(10.dp)) {
                        ResultsBlock(files, Modifier.weight(1f).fillMaxHeight())
                        TasksBlock(appForSession, Modifier.weight(1f).fillMaxHeight(), showContext)
                    }
                } else {
                    ResultsBlock(files, Modifier.fillMaxWidth().height(LowerBlocksHeight))
                    TasksBlock(appForSession, Modifier.fillMaxWidth().height(LowerBlocksHeight), showContext)
                }
            } else {
                Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.End) { CloseButton(tap, onClose) }
                LimitBlock(S.CLAUDE_SESSION_LIMIT, app?.usage?.session, app, state, Modifier.fillMaxWidth(), showUsage)
                LimitBlock(S.CLAUDE_WEEKLY_LIMIT, app?.usage?.weekly, app, state, Modifier.fillMaxWidth(), showUsage)
            }
            Spacer(Modifier.height(4.dp))
        }
    }
}

private val LimitBlockHeight = 140.dp
private val LowerBlocksHeight = 170.dp

@Composable
private fun Header(session: ClaudeSession, tap: () -> Unit, send: (JSONObject) -> Unit, onClose: () -> Unit, back: (() -> Unit)?) {
    Panel(Modifier.fillMaxWidth()) {
        Row(verticalAlignment = Alignment.CenterVertically) {
            if (back != null) {
                Box(Modifier.clip(ChipShape).clickable(onClick = back).padding(end = 12.dp, top = 4.dp, bottom = 4.dp)) {
                    BasicText(tr(S.CLAUDE_BACK), style = TextStyle(color = Color.White, fontSize = 15.sp, fontWeight = FontWeight.SemiBold))
                }
            }
            BasicText(
                session.title,
                style = TextStyle(color = Color.White, fontSize = 20.sp, fontWeight = FontWeight.Bold),
                maxLines = 1,
                overflow = TextOverflow.Ellipsis,
                modifier = Modifier.weight(1f),
            )
            CloseButton(tap, onClose)
        }
        Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            StatusDot(session.working)
            val where = listOf(session.project, session.branch).filter { it.isNotEmpty() }.joinToString(" · ")
            BasicText(
                where,
                style = TextStyle(color = Color.White.copy(alpha = 0.65f), fontSize = 14.sp),
                maxLines = 1,
                overflow = TextOverflow.Ellipsis,
                modifier = Modifier.weight(1f),
            )
            Pill(tr(S.CLAUDE_FRONT), selected = false, onClick = { tap(); send(ActionMessages.claudeFocus()) })
        }
        val chips = listOf(session.model, session.mode).filter { it.isNotEmpty() }
        if (chips.isNotEmpty()) {
            Row(Modifier.horizontalScroll(rememberScrollState()), horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                for (chip in chips) Chip(chip)
            }
        }
    }
}

/** The big block: the app's breakdown when it is this conversation, else the local token count and a note. */
@Composable
private fun ContextBlock(session: ClaudeSession, app: ClaudeApp?, modifier: Modifier, fillHeight: Boolean, onClick: () -> Unit) {
    val lang = LocalLang.current
    val context = app?.context
    Panel(modifier, onClick = onClick) {
        Label(tr(S.CLAUDE_CONTEXT))
        // The content scrolls inside the block when it is taller than the block.
        val inner = if (fillHeight) Modifier.weight(1f) else Modifier.heightIn(max = 360.dp)
        Column(inner.fillMaxWidth().verticalScroll(rememberScrollState()), verticalArrangement = Arrangement.spacedBy(8.dp)) {
        if (context != null) {
            val headline = when {
                context.percent != null && context.used.isNotEmpty() && context.window.isNotEmpty() ->
                    tr(S.CLAUDE_CONTEXT_USED, "percent" to context.percent, "used" to context.used, "window" to context.window)
                context.percent != null -> tr(S.CLAUDE_CONTEXT_PERCENT, "percent" to context.percent)
                else -> ""
            }
            if (headline.isNotEmpty()) {
                BasicText(headline, style = TextStyle(color = Color.White, fontSize = 18.sp, fontWeight = FontWeight.SemiBold))
            }
            if (context.percent != null) ProgressBar(ClaudeFormat.fraction(context.percent))
            for (item in context.items) ContextRow(item.name, item.tokens, item.percent, 0.9f)
            for (item in context.deferred) ContextRow(item.name, item.tokens, item.percent, 0.45f)
        } else {
            val tokens = session.tokens
            BasicText(
                if (tokens != null) tr(S.CLAUDE_TOKENS, "count" to ClaudeFormat.tokens(tokens, lang)) else tr(S.CLAUDE_NONE),
                style = TextStyle(color = Color.White, fontSize = 18.sp, fontWeight = FontWeight.SemiBold),
            )
            BasicText(tr(S.CLAUDE_CONTEXT_NOTE), style = TextStyle(color = Color.White.copy(alpha = 0.55f), fontSize = 13.sp))
        }
        }
    }
}

@Composable
private fun ContextRow(name: String, tokens: String, percent: String, alpha: Float) {
    Row(Modifier.fillMaxWidth(), verticalAlignment = Alignment.CenterVertically) {
        BasicText(
            name,
            style = TextStyle(color = Color.White.copy(alpha = alpha), fontSize = 14.sp),
            maxLines = 1,
            overflow = TextOverflow.Ellipsis,
            modifier = Modifier.weight(1f),
        )
        BasicText(tokens, style = TextStyle(color = Color.White.copy(alpha = alpha), fontSize = 14.sp))
        Box(Modifier.width(70.dp), contentAlignment = Alignment.CenterEnd) {
            BasicText(percent, style = TextStyle(color = Color.White.copy(alpha = alpha * 0.8f), fontSize = 13.sp))
        }
    }
}

/** "Modifications  +2140 −9": the only coloured line of the screen. */
@Composable
private fun ChangesLine(changes: ClaudeChanges?) {
    Panel(Modifier.fillMaxWidth()) {
        Row(verticalAlignment = Alignment.CenterVertically) {
            Label(tr(S.CLAUDE_CHANGES), Modifier.weight(1f))
            if (changes == null) {
                BasicText("—", style = TextStyle(color = Color.White.copy(alpha = 0.5f), fontSize = 16.sp))
            } else {
                BasicText("+${changes.added}", style = TextStyle(color = ClaudeGreen, fontSize = 17.sp, fontWeight = FontWeight.SemiBold))
                Spacer(Modifier.width(12.dp))
                BasicText("−${changes.removed}", style = TextStyle(color = ClaudeRed, fontSize = 17.sp, fontWeight = FontWeight.SemiBold))
            }
        }
    }
}

@Composable
private fun ResultsBlock(files: List<String>, modifier: Modifier) {
    Panel(modifier) {
        Label(tr(S.CLAUDE_RESULTS))
        if (files.isEmpty()) {
            BasicText(tr(S.CLAUDE_NONE), style = TextStyle(color = Color.White.copy(alpha = 0.55f), fontSize = 14.sp))
        } else {
            Column(Modifier.fillMaxWidth().weight(1f).verticalScroll(rememberScrollState())) {
                for (file in files) {
                    BasicText(
                        file,
                        style = TextStyle(color = Color.White.copy(alpha = 0.88f), fontSize = 14.sp),
                        maxLines = 1,
                        overflow = TextOverflow.Ellipsis,
                        modifier = Modifier.padding(vertical = 2.dp),
                    )
                }
            }
        }
    }
}

/**
 * The background tasks of the conversation open in the app: a dot (green and pulsing while running, grey once completed),
 * the name and the elapsed time, then how many are completed. [app] is null when the chosen session is not the open one.
 * Tapping it brings the app forward with its right rail.
 */
@Composable
private fun TasksBlock(app: ClaudeApp?, modifier: Modifier, onClick: () -> Unit) {
    Panel(modifier, onClick = onClick) {
        Label(tr(S.CLAUDE_TASKS))
        when {
            app == null -> BasicText(tr(S.CLAUDE_TASKS_UNAVAILABLE), style = TextStyle(color = Color.White.copy(alpha = 0.55f), fontSize = 13.sp))
            app.tasks.isEmpty() && app.tasksDone == 0 ->
                BasicText(tr(S.CLAUDE_NO_TASKS), style = TextStyle(color = Color.White.copy(alpha = 0.55f), fontSize = 13.sp))
            else -> {
                Column(Modifier.fillMaxWidth().weight(1f).verticalScroll(rememberScrollState()), verticalArrangement = Arrangement.spacedBy(6.dp)) {
                    for (task in app.tasks) {
                        Row(Modifier.fillMaxWidth(), verticalAlignment = Alignment.CenterVertically) {
                            StatusDot(task.running)
                            Spacer(Modifier.width(10.dp))
                            BasicText(
                                task.name,
                                style = TextStyle(color = Color.White.copy(alpha = if (task.running) 0.95f else 0.7f), fontSize = 14.sp),
                                maxLines = 1,
                                overflow = TextOverflow.Ellipsis,
                                modifier = Modifier.weight(1f),
                            )
                            if (task.elapsed.isNotEmpty()) {
                                Spacer(Modifier.width(10.dp))
                                BasicText(task.elapsed, style = TextStyle(color = Color.White.copy(alpha = 0.55f), fontSize = 13.sp), maxLines = 1)
                            }
                        }
                    }
                }
                if (app.tasksDone > 0) {
                    BasicText(
                        tr(S.CLAUDE_TASKS_DONE, "n" to app.tasksDone),
                        style = TextStyle(color = Color.White.copy(alpha = 0.55f), fontSize = 13.sp),
                    )
                }
            }
        }
    }
}

/** A usage limit (global, whatever the chosen session): percentage, bar, reset, and when the app was last read. */
@Composable
private fun LimitBlock(title: S, limit: ClaudeLimit?, app: ClaudeApp?, state: ActionsState, modifier: Modifier, onClick: () -> Unit) {
    Panel(modifier, onClick = onClick) {
        Row(verticalAlignment = Alignment.CenterVertically) {
            Label(tr(title), Modifier.weight(1f))
            if (limit != null) {
                BasicText("${limit.percent} %", style = TextStyle(color = Color.White, fontSize = 16.sp, fontWeight = FontWeight.SemiBold))
            }
        }
        if (limit == null) {
            BasicText(tr(S.CLAUDE_LIMITS_HINT), style = TextStyle(color = Color.White.copy(alpha = 0.55f), fontSize = 13.sp))
        } else {
            ProgressBar(ClaudeFormat.fraction(limit.percent))
            val seen = if (app != null && app.seenAt > 0) {
                tr(S.CLAUDE_SEEN_AT, "time" to ClaudeFormat.clockTime(app.seenAt, state.clock?.utcOffsetMin ?: 0))
            } else {
                ""
            }
            val line = listOf(
                if (limit.reset.isNotEmpty()) tr(S.CLAUDE_RESET_IN, "time" to limit.reset) else "",
                seen,
            ).filter { it.isNotEmpty() }.joinToString(" · ")
            if (line.isNotEmpty()) {
                BasicText(line, style = TextStyle(color = Color.White.copy(alpha = 0.6f), fontSize = 13.sp))
            }
        }
    }
}

// --- Pieces ------------------------------------------------------------------------------------------------

@Composable
private fun Panel(
    modifier: Modifier = Modifier,
    padding: Dp = 14.dp,
    onClick: (() -> Unit)? = null,
    content: @Composable androidx.compose.foundation.layout.ColumnScope.() -> Unit,
) {
    val source = remember { MutableInteractionSource() }
    val pressed by source.collectIsPressedAsState()
    Column(
        modifier
            .clip(PanelShape)
            .background(Color.White.copy(alpha = if (pressed) 0.17f else 0.08f))
            .border(1.dp, Color.White.copy(alpha = if (pressed) 0.45f else 0.22f), PanelShape)
            .then(if (onClick != null) Modifier.clickable(interactionSource = source, indication = null, onClick = onClick) else Modifier)
            .padding(padding),
        verticalArrangement = Arrangement.spacedBy(8.dp),
        content = content,
    )
}

@Composable
private fun Label(text: String, modifier: Modifier = Modifier) {
    BasicText(text, style = TextStyle(color = Color.White.copy(alpha = 0.6f), fontSize = 13.sp, fontWeight = FontWeight.SemiBold), modifier = modifier)
}

@Composable
private fun ProgressBar(fraction: Float) {
    Box(Modifier.fillMaxWidth().height(8.dp).clip(CircleShape).background(Color.White.copy(alpha = 0.15f))) {
        Box(Modifier.fillMaxWidth(fraction.coerceIn(0f, 1f)).fillMaxHeight().background(Color.White.copy(alpha = 0.8f)))
    }
}

/** Green and gently pulsing while the session works, plain grey otherwise. */
@Composable
private fun StatusDot(working: Boolean) {
    if (working) {
        val pulse by rememberInfiniteTransition(label = "claudeWorking").animateFloat(
            initialValue = 0.35f,
            targetValue = 1f,
            animationSpec = infiniteRepeatable(tween(800, easing = LinearEasing), RepeatMode.Reverse),
            label = "claudeWorkingAlpha",
        )
        Box(Modifier.size(12.dp).alpha(pulse).background(ClaudeGreen, CircleShape))
    } else {
        Box(Modifier.size(12.dp).background(ClaudeGrey, CircleShape))
    }
}

@Composable
private fun Chip(text: String) {
    Box(
        Modifier
            .clip(ChipShape)
            .background(Color.White.copy(alpha = 0.12f))
            .border(1.dp, Color.White.copy(alpha = 0.25f), ChipShape)
            .padding(horizontal = 10.dp, vertical = 4.dp),
    ) {
        BasicText(text, style = TextStyle(color = Color.White.copy(alpha = 0.9f), fontSize = 13.sp), maxLines = 1)
    }
}
