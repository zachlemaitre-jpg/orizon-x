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
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
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
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.orizonx.client.actions.ActionMessages
import com.orizonx.client.claude.ClaudeFormat
import com.orizonx.client.claude.ClaudeInfo
import com.orizonx.client.claude.ClaudeSelection
import com.orizonx.client.claude.ClaudeSession
import com.orizonx.client.i18n.LocalLang
import com.orizonx.client.i18n.S
import com.orizonx.client.i18n.tr
import org.json.JSONObject

private val ClaudeGreen = Color(0xFF34C77B)
private val ClaudeGrey = Color(0xFF9AA0A6)
private val RowShape = RoundedCornerShape(16.dp)
private val ChipShape = RoundedCornerShape(12.dp)

/**
 * The PC's Claude Code sessions, read only. Landscape: the list on the left (about 38 %) and the details of the chosen
 * session on the right. Portrait: the list, and a tap opens the details with a "← Sessions" button. The choice is kept
 * by session id while new states arrive; by default it is the most recent session.
 */
@Composable
fun ClaudeCodeScreen(
    info: ClaudeInfo,
    nowSeconds: Long,
    onAction: (JSONObject) -> Unit,
    onClose: () -> Unit,
    tap: () -> Unit,
    modifier: Modifier = Modifier,
) {
    var selectedId by remember { mutableStateOf<String?>(null) }
    var detailsOpen by remember { mutableStateOf(false) }
    val sessions = remember(info.sessions) { info.sessions.sortedByDescending { it.updated } }
    val currentId = ClaudeSelection.resolve(sessions, selectedId)
    val current = sessions.firstOrNull { it.id == currentId }

    BoxWithConstraints(modifier.fillMaxSize()) {
        val landscape = maxWidth >= 700.dp
        Column(Modifier.fillMaxSize().padding(horizontal = 12.dp)) {
            Row(Modifier.fillMaxWidth().height(40.dp), verticalAlignment = Alignment.CenterVertically) {
                if (!landscape && detailsOpen && current != null) {
                    Box(
                        Modifier.clip(ChipShape).clickable { tap(); detailsOpen = false }.padding(horizontal = 12.dp, vertical = 8.dp),
                    ) {
                        BasicText(tr(S.CLAUDE_BACK), style = TextStyle(color = Color.White, fontSize = 15.sp, fontWeight = FontWeight.SemiBold))
                    }
                }
                Spacer(Modifier.weight(1f))
                val closeDescription = tr(S.CLAUDE_CLOSE_DESC)
                Box(
                    Modifier
                        .size(40.dp)
                        .clip(RoundedCornerShape(20.dp))
                        .clickable { tap(); onClose() }
                        .semantics { contentDescription = closeDescription },
                    contentAlignment = Alignment.Center,
                ) {
                    BasicText("✕", style = TextStyle(color = Color.White, fontSize = 20.sp))
                }
            }
            when {
                sessions.isEmpty() -> Box(Modifier.fillMaxSize(), contentAlignment = Alignment.Center) {
                    BasicText(tr(S.CLAUDE_NO_SESSIONS), style = TextStyle(color = Color.White.copy(alpha = 0.8f), fontSize = 17.sp))
                }
                landscape -> Row(Modifier.fillMaxSize().padding(bottom = 12.dp), horizontalArrangement = Arrangement.spacedBy(14.dp)) {
                    SessionList(sessions, currentId, nowSeconds, Modifier.weight(0.38f).fillMaxHeight()) {
                        tap()
                        selectedId = it
                    }
                    if (current != null) {
                        SessionDetails(current, info, nowSeconds, Modifier.weight(0.62f).fillMaxHeight()) {
                            tap()
                            onAction(ActionMessages.claudeFocus())
                        }
                    }
                }
                detailsOpen && current != null -> SessionDetails(current, info, nowSeconds, Modifier.fillMaxSize().padding(bottom = 12.dp)) {
                    tap()
                    onAction(ActionMessages.claudeFocus())
                }
                else -> SessionList(sessions, currentId, nowSeconds, Modifier.fillMaxSize().padding(bottom = 12.dp)) {
                    tap()
                    selectedId = it
                    detailsOpen = true
                }
            }
        }
    }
}

@Composable
private fun SessionList(
    sessions: List<ClaudeSession>,
    selectedId: String?,
    nowSeconds: Long,
    modifier: Modifier,
    onPick: (String) -> Unit,
) {
    val lang = LocalLang.current
    LazyColumn(modifier, verticalArrangement = Arrangement.spacedBy(8.dp)) {
        items(sessions, key = { it.id }) { session ->
            val selected = session.id == selectedId
            Row(
                Modifier
                    .fillMaxWidth()
                    .clip(RowShape)
                    .background(Color.White.copy(alpha = if (selected) 0.20f else 0.08f))
                    .border(1.dp, Color.White.copy(alpha = if (selected) 0.7f else 0.18f), RowShape)
                    .clickable { onPick(session.id) }
                    .padding(horizontal = 14.dp, vertical = 12.dp),
                verticalAlignment = Alignment.CenterVertically,
            ) {
                StatusDot(session.working)
                Spacer(Modifier.width(12.dp))
                Column(Modifier.weight(1f)) {
                    BasicText(
                        session.title,
                        style = TextStyle(color = Color.White, fontSize = 16.sp, fontWeight = FontWeight.Bold),
                        maxLines = 1,
                        overflow = TextOverflow.Ellipsis,
                    )
                    val where = listOf(session.project, session.branch).filter { it.isNotEmpty() }.joinToString(" · ")
                    if (where.isNotEmpty()) {
                        BasicText(
                            where,
                            style = TextStyle(color = Color.White.copy(alpha = 0.6f), fontSize = 13.sp),
                            maxLines = 1,
                            overflow = TextOverflow.Ellipsis,
                        )
                    }
                    if (session.updated > 0) {
                        BasicText(
                            ClaudeFormat.age(session.updated, nowSeconds, lang),
                            style = TextStyle(color = Color.White.copy(alpha = 0.6f), fontSize = 12.sp),
                            maxLines = 1,
                        )
                    }
                }
            }
        }
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
private fun SessionDetails(session: ClaudeSession, info: ClaudeInfo, nowSeconds: Long, modifier: Modifier, onFocus: () -> Unit) {
    val lang = LocalLang.current
    Column(modifier.verticalScroll(rememberScrollState()), verticalArrangement = Arrangement.spacedBy(10.dp)) {
        Row(verticalAlignment = Alignment.CenterVertically) {
            BasicText(
                session.title,
                style = TextStyle(color = Color.White, fontSize = 20.sp, fontWeight = FontWeight.Bold),
                maxLines = 2,
                overflow = TextOverflow.Ellipsis,
                modifier = Modifier.weight(1f),
            )
            Spacer(Modifier.width(12.dp))
            StatusDot(session.working)
            Spacer(Modifier.width(6.dp))
            BasicText(
                tr(if (session.working) S.CLAUDE_WORKING else S.CLAUDE_IDLE),
                style = TextStyle(color = Color.White.copy(alpha = 0.85f), fontSize = 14.sp),
            )
        }
        val chips = listOf(session.model, session.effort, session.mode).filter { it.isNotEmpty() }
        if (chips.isNotEmpty()) {
            Row(Modifier.horizontalScroll(rememberScrollState()), horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                for (chip in chips) Chip(chip)
            }
        }
        val meta = buildList {
            session.tokens?.let { add(tr(S.CLAUDE_TOKENS, "count" to ClaudeFormat.tokens(it, lang))) }
            if (session.updated > 0) add(ClaudeFormat.age(session.updated, nowSeconds, lang))
        }
        if (meta.isNotEmpty()) {
            BasicText(meta.joinToString(" · "), style = TextStyle(color = Color.White.copy(alpha = 0.7f), fontSize = 14.sp))
        }

        Section(tr(S.CLAUDE_LAST_REQUEST)) {
            BasicText(
                session.lastPrompt.ifEmpty { tr(S.CLAUDE_NONE) },
                style = TextStyle(color = Color.White.copy(alpha = 0.9f), fontSize = 15.sp),
                maxLines = 4,
                overflow = TextOverflow.Ellipsis,
            )
        }
        Section(tr(S.CLAUDE_LAST_REPLY)) {
            // Its own scroll, inside the page's: the reply can be long.
            Box(Modifier.fillMaxWidth().heightIn(max = 190.dp).verticalScroll(rememberScrollState())) {
                BasicText(
                    session.lastResult.ifEmpty { tr(S.CLAUDE_NONE) },
                    style = TextStyle(color = Color.White.copy(alpha = 0.9f), fontSize = 15.sp),
                )
            }
        }
        Section(tr(S.CLAUDE_FILES)) {
            if (session.files.isEmpty()) {
                BasicText(tr(S.CLAUDE_NONE), style = TextStyle(color = Color.White.copy(alpha = 0.6f), fontSize = 14.sp))
            } else {
                Column(Modifier.fillMaxWidth().heightIn(max = 130.dp).verticalScroll(rememberScrollState())) {
                    for (file in session.files) {
                        BasicText(
                            file,
                            style = TextStyle(color = Color.White.copy(alpha = 0.85f), fontSize = 13.sp),
                            maxLines = 1,
                            overflow = TextOverflow.Ellipsis,
                        )
                    }
                }
            }
        }
        Section(tr(S.CLAUDE_CONNECTORS)) {
            val connectors = info.connectorsFor(session)
            if (connectors.isEmpty()) {
                BasicText(tr(S.CLAUDE_NONE), style = TextStyle(color = Color.White.copy(alpha = 0.6f), fontSize = 14.sp))
            } else {
                Row(Modifier.horizontalScroll(rememberScrollState()), horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                    for (connector in connectors) {
                        Chip(listOf(connector.name, connector.type).filter { it.isNotEmpty() }.joinToString(" · "))
                    }
                }
            }
        }
        Pill(tr(S.CLAUDE_FOCUS), selected = false, onClick = onFocus, modifier = Modifier.fillMaxWidth())
        Spacer(Modifier.height(4.dp))
    }
}

@Composable
private fun Section(title: String, content: @Composable () -> Unit) {
    Column(verticalArrangement = Arrangement.spacedBy(4.dp)) {
        BasicText(title, style = TextStyle(color = Color.White.copy(alpha = 0.55f), fontSize = 12.sp, fontWeight = FontWeight.SemiBold))
        content()
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
