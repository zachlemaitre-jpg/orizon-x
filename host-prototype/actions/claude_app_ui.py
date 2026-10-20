"""The right-hand panel of the Claude app, read with UI Automation (spec 2026-10-20 claude-code §7.1-§7.2), and its sidebar.

The Claude app (Electron) exposes its accessibility tree only after a first request; the first query then returns about
24 elements and a second one, a few seconds later, about 650 (about 200 ms). ``ClaudeAppReader.read()`` walks the window
once (``walk``: the elements in document order as ``Node(depth, role, name)``), and:

* fewer than ``WARMUP_MIN_NODES`` (100) elements means the tree is not awake yet: ``None``, to try again next cycle;
* otherwise the panel is isolated by its ``Group`` elements (Context, Connectors, Results, Changes, in French or English),
  and the usage lines are found by their wording. **Only the labels and values of that panel are kept**: the nodes are
  thrown away after the parse, so no conversation text is ever stored or sent. Names that are not part of the panel
  vocabulary and structure are dropped.

The ``app`` object: ``{"session_title", "seen_at", "context": {"percent", "used", "window", "items": [{"name",
"tokens", "percent"}], "deferred": [{"name", "tokens"}]} | None, "connected": int | None, "results": [file names],
"changes": {"added", "removed"} | None, "usage": {"session": {"percent", "reset"} | None, "weekly": {...} | None, "weekly_seen_at": epoch s | None},
"tasks": [{"name", "status": "running" | "completed", "elapsed"}], "tasks_done": int}``; the parts that are not found
are ``None`` (``[]`` for the results). ``tasks`` (the "Background tasks" card, at most 10 rows) and ``tasks_done`` (its
"N completed" summary) are present only when the card is. None when nothing of the panel is found.

``invoke_sidebar`` clicks nothing with the mouse: the UIA layer invokes (``InvokePattern``) the button of the sidebar
whose accessible name is given. The real layer is ``browser_url.UiaLayer`` (``walk_nodes`` / ``invoke_named``, comtypes
imported lazily there, never here). Layers are injectable for the tests.
"""
from __future__ import annotations

import logging
import re
from typing import Any, Callable, NamedTuple, Optional

_log = logging.getLogger("orizonx.actions.claude_app_ui")

WARMUP_MIN_NODES = 100
MAX_ELEMENTS = 20000
MAX_RESULTS = 40
MAX_ITEMS = 24

# FR / EN names of the sidebar buttons (exact accessible names, case-insensitive)
SIDEBAR_BUTTONS = {
    "claude.new": ("Nouveau", "New"),
    "claude.artifacts": ("Artéfacts", "Artefacts", "Artifacts"),
    "claude.customize": ("Personnalisation", "Customize"),
    "claude.more": ("Plus", "More"),
}

# Group names of the panel cards, French then English
CONTEXT_GROUPS = ("contexte", "context")
RESULTS_GROUPS = ("résultats", "results")
CHANGES_GROUPS = ("modifications", "changes")
CONNECTORS_PREFIXES = ("connecteurs", "connectors")
TASKS_GROUPS = ("tâches en arrière-plan", "background tasks")
MAX_TASKS = 10

# Elements opened by the tablet's Context and usage blocks (read-only findings on the real tree, 2026-10-20):
# * usage: the status-bar Button "Utilisation : 76 % de la limite de session et Réinitialisation dans 48 min" supports
#   ExpandCollapsePattern only (no Invoke): expanding it opens the plan usage-limits popover;
# * context: the card header Button "Contexte" supports ExpandCollapsePattern only (no Invoke); the card lives in the
#   right rail, which the toggle button "Panneau des sessions" (TogglePattern) shows or hides.
USAGE_BUTTON = r"^(?:Utilisation|Usage)\s*:"
CONTEXT_HEADER = r"^(?:Contexte|Context)$"
RAIL_TOGGLES = ("Panneau des sessions", "Session panel", "Sessions panel")

_SPACES = re.compile(r"[\s  ]+")
_TOKENS = re.compile(r"^\d[\d.,]*\s?[kKmM]?$")
_PERCENT = re.compile(r"^\d[\d.,]*\s?%$")
_TOTAL = re.compile(r"^(\d[\d.,]*\s?[kKmM]?)\s*/\s*(\d[\d.,]*\s?[kKmM]?)$")
_USED = re.compile(r"^(\d{1,3})\s?%\s*(?:utilisé|used)", re.I)
_DEFERRED = re.compile(r"deferred|diff[ée]r", re.I)
_RESET = re.compile(r"(?:Réinitialisation|Resets?)\s*(?:dans|in|le|on)?\s*(.+)$", re.I)
_PCT = re.compile(r"(\d{1,3})\s?%")
_USAGE_START = re.compile(r"^(?:Utilisation|Usage|Hebdomadaire|Weekly|Limite|Limit)", re.I)
_ADDED = re.compile(r"(\d[\d\s.,]*?)\s*(?:ajout|added|insertion)", re.I)
_REMOVED = re.compile(r"(\d[\d\s.,]*?)\s*(?:supprim|removed|deletion)", re.I)
_PLUS = re.compile(r"^\+\s?(\d[\d\s.,]*)$")
_MINUS = re.compile(r"^[−\-–]\s?(\d[\d\s.,]*)$")
_CONNECTED = re.compile(r"(\d+)\s*(?:connect)", re.I)
_TITLE_BUTTON = re.compile(r"^(.{1,200}?),\s*(?:renommer la session|rename (?:the )?session)$", re.I)
_TASK_ROW = re.compile(r"^(?:Ouvrir|Open)\s+(.+?)\s+(?:dans|in)\s+(?:Tâches en arrière-plan|Background tasks)$", re.I)
_TASK_STOP = re.compile(r"^(?:Arrêter|Stop)\b", re.I)
_TASKS_DONE = re.compile(r"^(\d+)\s*(?:terminé|completed|done|finished)", re.I)
_ELAPSED = re.compile(r"^\d+\s?(?:h|min|s)\b", re.I)


class Node(NamedTuple):
    depth: int
    role: str   # "Group", "Text", "Button", "ListItem", "ToolBar" or "Other"
    name: str


def norm(text: Any) -> str:
    """The name with every kind of space (no-break, narrow no-break) turned into one plain space."""
    return _SPACES.sub(" ", text).strip() if isinstance(text, str) else ""


def _digits(text: str) -> Optional[int]:
    d = re.sub(r"\D", "", text)
    return int(d) if d else None


def _subtree(nodes: "list[Node]", names: "tuple[str, ...]", prefix: bool = False) -> "Optional[list[Node]]":
    """The nodes under the first Group whose name is one of ``names`` (or starts with one of them)."""
    for i, node in enumerate(nodes):
        if node.role != "Group":
            continue
        name = norm(node.name).lower()
        if (name.startswith(names) if prefix else name in names):
            end = i + 1
            while end < len(nodes) and nodes[end].depth > node.depth:
                end += 1
            return nodes[i + 1:end]
    return None


def _group_name(nodes: "list[Node]", names: "tuple[str, ...]") -> Optional[str]:
    for node in nodes:
        if node.role == "Group" and norm(node.name).lower().startswith(names):
            return norm(node.name)
    return None


def _parse_context(sub: "list[Node]") -> dict:
    texts = [norm(n.name) for n in sub if n.role == "Text" and norm(n.name)]
    percent = used = window = None
    items: list = []
    deferred: list = []
    i = 0
    while i < len(texts):
        text = texts[i]
        m = _USED.match(text)
        if m:
            percent = int(m.group(1))
            i += 1
            continue
        m = _TOTAL.match(text)
        if m:
            used, window = m.group(1).replace(" ", ""), m.group(2).replace(" ", "")
            i += 1
            continue
        is_label = not (_TOKENS.match(text) or _PERCENT.match(text)) and len(text) <= 60
        if is_label and i + 1 < len(texts) and _TOKENS.match(texts[i + 1]):
            tokens = texts[i + 1].replace(" ", "")
            share = texts[i + 2] if i + 2 < len(texts) and _PERCENT.match(texts[i + 2]) else None
            if _DEFERRED.search(text):
                deferred.append({"name": text, "tokens": tokens})
            elif share:  # a row without a share is a count (tools, files, agents), not a slice of the window
                items.append({"name": text, "tokens": tokens, "percent": share})
            i += 3 if share else 2
            continue
        i += 1
    if percent is None and used is None and not items:
        return {}
    return {"percent": percent, "used": used, "window": window, "items": items[:MAX_ITEMS],
            "deferred": deferred[:MAX_ITEMS]}


def _parse_results(sub: "list[Node]", labels: "tuple[str, ...]") -> "list[str]":
    out: list = []
    for n in sub:
        name = norm(n.name)
        if (n.role not in ("Text", "ListItem") or not name or name.lower() in labels
                or name.lower().startswith(("réorganiser", "reorder")) or len(name) > 120 or name in out):
            continue
        out.append(name)
    return out[:MAX_RESULTS]


def _parse_changes(sub: "list[Node]") -> "Optional[dict]":
    added = removed = None
    for n in sub:
        name = norm(n.name)
        if n.role in ("Button", "Text", "Group", "ListItem"):
            m = _ADDED.search(name)
            if m and added is None:
                added = _digits(m.group(1))
            m = _REMOVED.search(name)
            if m and removed is None:
                removed = _digits(m.group(1))
            m = _PLUS.match(name)
            if m and added is None:
                added = _digits(m.group(1))
            m = _MINUS.match(name)
            if m and removed is None:
                removed = _digits(m.group(1))
    if added is None and removed is None:
        return None
    return {"added": added or 0, "removed": removed or 0}


def _parse_usage(nodes: "list[Node]", seen_at: int = 0) -> dict:
    """The session and weekly limits. Either one line carries it all ("Utilisation : 44 % de la limite de session et
    Réinitialisation dans 1 h 10 min", the status-bar button) or, in the usage popover, a label ("Hebdomadaire · tous les
    modèles") is followed by its own texts ("34 % utilisé", "Réinitialisation sam. 11:00")."""
    session = weekly = None
    for i, n in enumerate(nodes):
        if n.role not in ("Button", "Text", "Group", "Other") or len(n.name) > 200:
            continue
        name = norm(n.name)
        if not _USAGE_START.match(name):
            continue
        parts = [name]
        if not (_PCT.search(name) and _RESET.search(name)):
            for m in nodes[i + 1:i + 7]:
                text = norm(m.name)
                if m.role not in ("Text", "Button", "Group", "Other") or not text or len(text) > 200:
                    continue
                if _USAGE_START.match(text):
                    break  # the next label
                parts.append(text)
        joined = " ".join(parts)
        pct = _PCT.search(joined)
        reset = next((r for r in (_RESET.search(p) for p in parts) if r), None)
        if not (pct and reset):
            continue
        entry = {"percent": int(pct.group(1)), "reset": reset.group(1).strip()[:40]}
        low = name.lower()
        if "hebdomadaire" in low or "weekly" in low:
            weekly = weekly or entry
        elif "session" in low:
            session = session or entry
    return {"session": session, "weekly": weekly, "weekly_seen_at": int(seen_at) if weekly else None}


def _parse_tasks(sub: "list[Node]") -> dict:
    """The rows of the background-tasks card: a row is the button "Open <name> in Background tasks" with its texts (the
    task's name, then its elapsed time); a "Stop this task" button after it means it is running."""
    tasks: list = []
    done = None
    row: Optional[dict] = None
    row_depth = 0
    for n in sub:
        name = norm(n.name)
        if n.role == "Button":
            m = _TASK_ROW.match(name)
            if m:
                row = {"name": m.group(1)[:120], "status": "completed", "elapsed": "", "_named": False}
                row_depth = n.depth
                if len(tasks) < MAX_TASKS:
                    tasks.append(row)
                continue
            if _TASK_STOP.match(name):
                if row is not None:
                    row["status"] = "running"
                continue
            m = _TASKS_DONE.match(name)
            if m:
                done = int(m.group(1))
            row = None if not name.lower().startswith(("réorganiser", "reorder")) else row
            continue
        if n.role == "Text" and row is not None and n.depth > row_depth and name:
            if not row["_named"]:
                row["name"], row["_named"] = name[:120], True
            elif _ELAPSED.match(name) and not row["elapsed"]:
                row["elapsed"] = name[:20]
    for task in tasks:
        task.pop("_named", None)
    out: dict = {"tasks": tasks}
    if done is not None:
        out["tasks_done"] = done
    return out


def _session_title(nodes: "list[Node]", fallback: str) -> str:
    """The open conversation's title: the session toolbar's button "<title>, rename the session"; the window title
    when there is none."""
    for n in nodes:
        if n.role == "Button":
            m = _TITLE_BUTTON.match(norm(n.name))
            if m:
                return m.group(1)
    return norm(fallback)


def parse_panel(title: str, nodes: "list[Node]", seen_at: int) -> "Optional[dict]":
    """The ``app`` object from the nodes of the window (None if no part of the panel is there). ``title`` is the window
    title, used when the conversation's title cannot be read from the session toolbar."""
    context = _subtree(nodes, CONTEXT_GROUPS)
    connectors = _group_name(nodes, CONNECTORS_PREFIXES)
    results = _subtree(nodes, RESULTS_GROUPS)
    changes = _subtree(nodes, CHANGES_GROUPS)
    tasks = _subtree(nodes, TASKS_GROUPS)
    usage = _parse_usage(nodes, seen_at)
    parsed_context = _parse_context(context) if context is not None else {}
    connected = None
    if connectors:
        m = _CONNECTED.search(connectors)
        connected = int(m.group(1)) if m else None
    app = {
        "session_title": _session_title(nodes, title)[:120],
        "seen_at": int(seen_at),
        "context": parsed_context or None,
        "connected": connected,
        "results": _parse_results(results, RESULTS_GROUPS) if results is not None else [],
        "changes": _parse_changes(changes) if changes is not None else None,
        "usage": usage,
    }
    if tasks is not None:
        app.update(_parse_tasks(tasks))
    if (app["context"] is None and app["connected"] is None and not app["results"] and app["changes"] is None
            and usage["session"] is None and usage["weekly"] is None and tasks is None):
        return None
    return app


class ClaudeAppUi:
    """The UI Automation layer of the Claude window (``browser_url.UiaLayer`` created on first use, comtypes lazy)."""

    def __init__(self, layer: Any = None) -> None:
        self._layer = layer

    def _get(self) -> Any:
        if self._layer is None:
            from actions.browser_url import UiaLayer
            self._layer = UiaLayer()
        return self._layer

    def walk(self, hwnd: int) -> "list[Node]":
        return [Node(d, r, n) for d, r, n in self._get().walk_nodes(hwnd, MAX_ELEMENTS)]

    def invoke(self, hwnd: int, names: "tuple[str, ...]") -> bool:
        return bool(self._get().invoke_named(hwnd, names))

    def expand(self, hwnd: int, pattern: str, wait_s: float = 0.0) -> bool:
        """Expand (or invoke) the first Button whose name matches ``pattern``, waiting up to ``wait_s`` for it to exist."""
        return bool(self._get().expand_matching(hwnd, pattern, wait_s))

    def ensure_on(self, hwnd: int, names: "tuple[str, ...]") -> bool:
        """Turn on the toggle button of that name if it is off; True if the button exists."""
        return bool(self._get().toggle_on_named(hwnd, names))


class ClaudeAppReader:
    def __init__(self, ui: Any = None, log: Optional[Callable[[str], None]] = None) -> None:
        self._ui = ui if ui is not None else ClaudeAppUi()
        self._log = log or _log.info
        self._logged: set = set()
        self.warming_up = False  # the last read found a tree that is not awake yet

    def read(self, hwnd: int, title: str, now: float) -> "Optional[dict]":
        """The ``app`` object of the Claude window ``hwnd`` (whose title is ``title``), or None."""
        self.warming_up = False
        try:
            nodes = self._ui.walk(hwnd)
            if len(nodes) < WARMUP_MIN_NODES:
                self.warming_up = True
                return None
            return parse_panel(title, nodes, int(now))
        except Exception as e:  # noqa: BLE001 - COM errors, a closing window...: the section is just absent
            kind = type(e).__name__
            if kind not in self._logged:
                self._logged.add(kind)
                self._log(f"claude app: cannot read the panel ({kind}: {e})")
            return None
