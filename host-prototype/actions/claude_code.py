"""Claude Code sessions of the PC, read-only (Actions mode, spec 2026-10-20 claude-code §2-§4).

Snapshot (the ``claude`` section of the state): ``{"available": False}`` when ``~/.claude/projects`` does not exist, else
``{"available": True, "sessions": [{"id", "title", "project", "branch", "updated": <epoch s>,
"status": "working" | "idle", "model", "effort", "mode", "tokens": <int> | None, "last_prompt", "last_result",
"files": [...], "entry": "desktop" | "cli"}], "connectors": [{"name", "type", "scope"}]}``; fields that are unknown are
``""`` (``None`` for ``tokens``).

Sessions: the ``SESSION_COUNT`` (12) most recently modified ``~/.claude/projects/<project>/<id>.jsonl``, every project
together; sub-folders (sub-agents, memory) are ignored. A file is read once from its last 2 MiB (the first, partial line
of that window is skipped), then only what was appended since the cached offset; a file that got shorter or was
replaced is read again as the first time. An invalid JSON line is ignored. Fields (the last one met wins): see
``_Fields.apply``. ``status`` is ``working`` when the file was modified less than 15 s ago.

Connectors: ONLY the name, the type (``stdio`` | ``http`` | ``sse``) and the scope (``global``, or the project's folder
name) of the ``mcpServers`` entries of ``~/.claude.json`` (the global ones, and those of the projects of the listed
sessions) and of ``<cwd>/.mcp.json`` of those projects. NOTHING else of ``.claude.json`` is read into a field or sent
(it holds account information), and no server command, URL, header or environment variable ever leaves this module. At
most 30. Those files are parsed again only when their size or modification time changes.

Size: the whole section stays under ``SECTION_MAX_BYTES`` (compact UTF-8 JSON). The ACTIONS_STATE as a whole may not
exceed 64 KiB (protocol.MAX_JSON) and the other sections need room, so the budget is lower than 64 KiB; ``last_result``
is shortened session after session, the oldest first, then ``last_prompt``, then the file lists, until it fits.

App panel (spec §7): while the device has its Claude screen open (``claude.watch {"open": true}``), at most every 3 s
(1 s while the app's accessibility tree is still waking up), the right-hand panel of the Claude app is read with UI
Automation (actions.claude_app_ui) into ``section["app"]``: context, connectors, results, changes, usage limits. Only
panel labels and values are kept, never conversation text. Each session also carries ``changes``
(``{"added", "removed"}`` or None): ``git diff --shortstat`` of its ``cwd`` against the merge-base with ``main`` /
``master`` (tracked files only), computed by ``GitStats`` in a background thread and cached for 30 s.

``claude.new`` / ``claude.artifacts`` / ``claude.customize`` / ``claude.more`` bring the app to the front, then invoke
(``InvokePattern``, never the mouse) the sidebar button of that name; ``claude.open {"title"}`` invokes the sidebar item
with that title. Notice ``claude_ui_not_found`` when the app or the button cannot be found.

``claude.focus``: brings the main window of the Claude app to the front (``Win32Focus``, injectable): the visible,
unowned, titled top-level window of a ``claude.exe`` process; ``SW_RESTORE`` if minimised, ``SetForegroundWindow``, and on
refusal an Alt key press and release (``keybd_event``, the usual workaround) and one more try. Returns the notice code
``claude_not_running`` when there is no such window, ``action_failed`` when Windows refuses twice. Normal hub path.
"""
from __future__ import annotations

import json
import logging
import os
import queue
import re
import subprocess
import threading
import time
from datetime import datetime
from typing import Any, Callable, Optional

from actions.claude_app_ui import SIDEBAR_BUTTONS, ClaudeAppReader, ClaudeAppUi

_log = logging.getLogger("orizonx.actions.claude_code")

SESSION_COUNT = 12
WINDOW_BYTES = 2 * 1024 * 1024
WORKING_S = 15.0
MAX_CONNECTORS = 30
MAX_FILES = 20
PROMPT_MAX = 300
RESULT_MAX = 1500
SECTION_MAX_BYTES = 40 * 1024
CONFIG_MAX_BYTES = 32 * 1024 * 1024
_CACHE_KEEP = 32

NOT_RUNNING = "claude_not_running"
UI_NOT_FOUND = "claude_ui_not_found"
ACTION_FAILED = "action_failed"
FOCUS_ID = "claude.focus"
WATCH_ID = "claude.watch"
OPEN_ID = "claude.open"
APP_READ_S = 3.0
APP_WARMUP_RETRY_S = 1.0
GIT_CACHE_S = 30.0
GIT_TIMEOUT_S = 5.0
MAX_TITLE = 200

_SERVER_TYPES = ("stdio", "http", "sse")


# --- file system ---------------------------------------------------------------------------------------------------

class RealFs:
    def isdir(self, path: str) -> bool:
        return os.path.isdir(path)

    def listdir(self, path: str) -> "list[str]":
        return os.listdir(path)

    def stat(self, path: str) -> "Optional[tuple[float, int]]":
        """(modification time, size) of a regular file, or None."""
        try:
            st = os.stat(path)
        except OSError:
            return None
        return (st.st_mtime, st.st_size) if os.path.isfile(path) else None

    def read_range(self, path: str, start: int, end: int) -> bytes:
        with open(path, "rb") as f:
            f.seek(start)
            return f.read(max(0, end - start))


# --- extracted fields ----------------------------------------------------------------------------------------------

def _clip(text: str, limit: int) -> str:
    return text if len(text) <= limit else text[:limit - 1].rstrip() + "…"


def _epoch(value: Any) -> Optional[float]:
    if not isinstance(value, str):
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()
    except ValueError:
        return None


def _text(value: Any) -> str:
    return value if isinstance(value, str) else ""


def _tokens(usage: Any) -> int:
    if not isinstance(usage, dict):
        return 0
    total = 0
    for key in ("input_tokens", "cache_read_input_tokens", "cache_creation_input_tokens"):
        v = usage.get(key)
        if isinstance(v, int) and not isinstance(v, bool):
            total += v
    return total


class _Fields:
    def __init__(self) -> None:
        self.custom_title = ""
        self.slug = ""
        self.cwd = ""
        self.branch = ""
        self.timestamp: Optional[float] = None
        self.model = ""
        self.effort = ""
        self.mode = ""
        self.tokens: Optional[int] = None
        self.last_prompt = ""
        self.last_result = ""
        self.backups: "list[str]" = []
        self.entrypoint = ""

    def apply(self, r: dict) -> None:
        kind = r.get("type")
        if _text(r.get("slug")):
            self.slug = r["slug"]
        ts = _epoch(r.get("timestamp"))
        if ts is not None and (self.timestamp is None or ts > self.timestamp):
            self.timestamp = ts
        if kind == "custom-title":
            if _text(r.get("customTitle")).strip():
                self.custom_title = r["customTitle"].strip()
        elif kind == "last-prompt":
            if _text(r.get("lastPrompt")):
                self.last_prompt = _clip(r["lastPrompt"], PROMPT_MAX)
        elif kind == "file-history-snapshot":
            snapshot = r.get("snapshot")
            backups = snapshot.get("trackedFileBackups") if isinstance(snapshot, dict) else None
            if isinstance(backups, dict):
                self.backups = [k for k in backups if isinstance(k, str)]
        elif kind in ("user", "assistant"):
            if _text(r.get("cwd")):
                self.cwd = r["cwd"]
            if _text(r.get("gitBranch")):
                self.branch = r["gitBranch"]
            if _text(r.get("entrypoint")):
                self.entrypoint = r["entrypoint"]
            message = r.get("message") if isinstance(r.get("message"), dict) else {}
            if kind == "user":
                if _text(r.get("permissionMode")):
                    self.mode = r["permissionMode"]
            else:
                model = _text(r.get("requestedModel")) or _text(message.get("model"))
                if model and not model.startswith("<"):  # "<synthetic>": a local error message, not a model
                    self.model = model
                if _text(r.get("effort")):
                    self.effort = r["effort"]
                tokens = _tokens(message.get("usage"))
                if tokens > 0:
                    self.tokens = tokens
                content = message.get("content")
                if isinstance(content, list):
                    texts = [b["text"] for b in content
                             if isinstance(b, dict) and b.get("type") == "text" and isinstance(b.get("text"), str)]
                    if texts:
                        self.last_result = _clip("".join(texts), RESULT_MAX)

    def files(self) -> "list[str]":
        base = self.cwd.replace("\\", "/").rstrip("/")
        out = []
        for key in self.backups:
            path = key.replace("\\", "/")
            if base and path.lower().startswith(base.lower() + "/"):
                path = path[len(base) + 1:]
            out.append(path)
        return sorted(set(out))[:MAX_FILES]


class _Cached:
    def __init__(self) -> None:
        self.offset = 0
        self.mtime = 0.0
        self.size = 0
        self.fields = _Fields()


def _project_of(cwd: str) -> str:
    parts = [p for p in cwd.replace("\\", "/").split("/") if p]
    return parts[-1] if parts else ""


def _norm_path(path: str) -> str:
    return path.replace("\\", "/").rstrip("/").lower()


def _server_entries(servers: Any, scope: str, out: list, seen: set) -> None:
    """Appends (name, type, scope) for each entry of an ``mcpServers`` mapping: nothing but those three."""
    if not isinstance(servers, dict):
        return
    for name, entry in servers.items():
        if not isinstance(name, str) or not name or (name, scope) in seen:
            continue
        kind = entry.get("type") if isinstance(entry, dict) else None
        out.append({"name": name[:80], "type": kind if kind in _SERVER_TYPES else "stdio", "scope": scope[:80]})
        seen.add((name, scope))


class _JsonCache:
    """A JSON file parsed again only when its size or modification time changes."""

    def __init__(self, fs: Any) -> None:
        self._fs = fs
        self._entries: dict = {}

    def get(self, path: str) -> Any:
        info = self._fs.stat(path)
        if info is None or info[1] > CONFIG_MAX_BYTES:
            self._entries.pop(path, None)
            return None
        cached = self._entries.get(path)
        if cached is not None and cached[0] == info:
            return cached[1]
        try:
            data = json.loads(self._fs.read_range(path, 0, info[1]).decode("utf-8-sig", "replace"))
        except (OSError, ValueError):
            data = None
        self._entries[path] = (info, data)
        return data


# --- git statistics ------------------------------------------------------------------------------------------------

def default_git_runner(args: "list[str]", cwd: str, timeout: float) -> "Optional[tuple[int, str]]":
    """(exit code, stdout) of a git command run in ``cwd`` without a console window, never waiting for input; None if git
    cannot run (not installed, timeout)."""
    try:
        done = subprocess.run(args, cwd=cwd, capture_output=True, timeout=timeout, stdin=subprocess.DEVNULL,
                              creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                              env=dict(os.environ, GIT_TERMINAL_PROMPT="0"))
    except (OSError, subprocess.SubprocessError):
        return None
    return done.returncode, done.stdout.decode("utf-8", "replace")


_INSERTIONS = re.compile(r"(\d+) insertion")
_DELETIONS = re.compile(r"(\d+) deletion")


class GitStats:
    """``{"added", "removed"}`` per working folder: ``git diff --shortstat`` against the merge-base with main / master
    (the working tree against ``HEAD`` when there is no such branch); untracked files are not counted. ``get()`` answers
    from the cache at once (None while unknown or when the folder is not a repository) and refreshes a value older than
    ``GIT_CACHE_S`` in a background thread, so the hub is never held by a git process."""

    def __init__(self, runner: Optional[Callable[..., Any]] = None, clock: Callable[[], float] = time.monotonic,
                 isdir: Callable[[str], bool] = os.path.isdir, threaded: bool = True,
                 log: Optional[Callable[[str], None]] = None) -> None:
        self._run = runner or default_git_runner
        self._clock = clock
        self._isdir = isdir
        self._threaded = threaded
        self._log = log or _log.info
        self._cache: "dict[str, tuple[float, Optional[dict]]]" = {}
        self._pending: set = set()
        self._queue: "queue.Queue[str]" = queue.Queue()
        self._lock = threading.Lock()
        self._worker: Optional[threading.Thread] = None
        self._logged = False

    def get(self, cwd: str) -> Optional[dict]:
        if not cwd or "\0" in cwd:
            return None
        key = _norm_path(cwd)
        with self._lock:
            entry = self._cache.get(key)
            stale = entry is None or self._clock() - entry[0] >= GIT_CACHE_S
            schedule = stale and key not in self._pending
            if schedule:
                self._pending.add(key)
        if schedule:
            if self._threaded:
                if self._worker is None or not self._worker.is_alive():
                    self._worker = threading.Thread(target=self._loop, name="orizonx-git-stats", daemon=True)
                    self._worker.start()
                self._queue.put(cwd)
            else:
                self._refresh(cwd)
                entry = self._cache.get(key)
        return entry[1] if entry else None

    def wait_idle(self, timeout: float = 5.0) -> bool:
        """For tests."""
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            with self._lock:
                if not self._pending:
                    return True
            time.sleep(0.002)
        return False

    def _loop(self) -> None:
        while True:
            self._refresh(self._queue.get())

    def _refresh(self, cwd: str) -> None:
        key = _norm_path(cwd)
        try:
            value = self._compute(cwd)
        except Exception as e:  # noqa: BLE001
            value = None
            if not self._logged:
                self._logged = True
                self._log(f"claude: git statistics failed ({type(e).__name__}: {e})")
        with self._lock:
            self._cache[key] = (self._clock(), value)
            self._pending.discard(key)

    def _compute(self, cwd: str) -> Optional[dict]:
        if not self._isdir(cwd):
            return None
        base = None
        for branch in ("main", "master"):
            result = self._run(["git", "merge-base", "HEAD", branch], cwd, GIT_TIMEOUT_S)
            if result is not None and result[0] == 0 and result[1].strip():
                base = result[1].strip().splitlines()[0]
                break
        result = self._run(["git", "-c", "core.fsmonitor=false", "diff", "--no-ext-diff", "--shortstat", base or "HEAD"],
                           cwd, GIT_TIMEOUT_S)
        if result is None or result[0] != 0:
            return None
        added, removed = _INSERTIONS.search(result[1]), _DELETIONS.search(result[1])
        return {"added": int(added.group(1)) if added else 0, "removed": int(removed.group(1)) if removed else 0}


# --- provider ----------------------------------------------------------------------------------------------------

class ClaudeCodeProvider:
    def __init__(self, root: Optional[str] = None, clock: Callable[[], float] = time.time, fs: Any = None,
                 home: Optional[str] = None, win32: Any = None, log: Optional[Callable[[str], None]] = None,
                 ui: Any = None, git_runner: Optional[Callable[..., Any]] = None, git_threaded: bool = True) -> None:
        self._home = home or os.path.expanduser("~")
        self._root = root or os.path.join(self._home, ".claude", "projects")
        self._config = os.path.join(self._home, ".claude.json")
        self._clock = clock
        self._fs = fs if fs is not None else RealFs()
        self._win32 = win32
        self._log = log or _log.info
        self._cache: "dict[str, _Cached]" = {}
        self._json = _JsonCache(self._fs)
        self._logged: set = set()
        self._ui = ui if ui is not None else ClaudeAppUi()
        self._app_reader = ClaudeAppReader(self._ui, self._log)
        self._git = GitStats(git_runner, isdir=self._fs.isdir, threaded=git_threaded, log=self._log)
        self._watch = False
        self._app: Optional[dict] = None
        self._app_next = 0.0

    # --- provider API ---

    def snapshot(self) -> dict:
        try:
            if not self._fs.isdir(self._root):
                return {"available": False}
            sessions = []
            for path, mtime in self._recent_files():
                session = self._session(path, mtime)
                if session is not None:
                    sessions.append(session)
            connectors = self._connectors(sessions)
            for session, cwd in sessions:
                session["changes"] = self._git.get(cwd)
            section = {"available": True, "sessions": [s[0] for s in sessions], "connectors": connectors}
            app = self._read_app()
            if app is not None:
                section["app"] = app
            return _fit(section)
        except Exception as e:  # noqa: BLE001 - the hub marks a failing provider unavailable; keep the bar alive
            self._note("snapshot", e)
            return {"available": False}

    def handle(self, action: dict) -> Optional[str]:
        action_id = action.get("id")
        if action_id == FOCUS_ID:
            return self._focus()
        if action_id == WATCH_ID:
            opened = action.get("open")
            if type(opened) is not bool:
                self._log(f"claude: watch ignored, not a boolean: {opened!r}")
                return None
            self._watch = opened
            self._app, self._app_next = None, 0.0  # a fresh read at the next poll; nothing kept while closed
            return None
        if action_id in SIDEBAR_BUTTONS:
            return self._invoke(SIDEBAR_BUTTONS[action_id])
        if action_id == OPEN_ID:
            title = action.get("title")
            if not isinstance(title, str) or not title.strip() or len(title) > MAX_TITLE:
                self._log(f"claude: open ignored, bad title: {title!r}")
                return UI_NOT_FOUND
            return self._invoke((title.strip(),))
        self._log(f"claude: unknown action {action_id!r}")
        return ACTION_FAILED

    # --- sessions ---

    def _recent_files(self) -> "list[tuple[str, float]]":
        found = []
        for project in self._fs.listdir(self._root):
            folder = os.path.join(self._root, project)
            if not self._fs.isdir(folder):
                continue
            try:
                names = self._fs.listdir(folder)
            except OSError:
                continue
            for name in names:
                if not name.endswith(".jsonl"):
                    continue
                path = os.path.join(folder, name)
                info = self._fs.stat(path)  # None for a sub-folder named x.jsonl
                if info is not None:
                    found.append((path, info[0]))
        found.sort(key=lambda item: item[1], reverse=True)
        chosen = found[:SESSION_COUNT]
        keep = {p for p, _ in chosen}
        if len(self._cache) > _CACHE_KEEP:
            for path in [p for p in self._cache if p not in keep]:
                del self._cache[path]
        return chosen

    def _session(self, path: str, mtime: float) -> "Optional[tuple[dict, str]]":
        try:
            fields = self._read(path)
        except OSError as e:
            self._note("read", e)
            return None
        session_id = os.path.splitext(os.path.basename(path))[0]
        updated = fields.timestamp if fields.timestamp is not None else mtime
        project = _project_of(fields.cwd)
        session = {
            "id": session_id,
            "title": fields.custom_title or fields.slug or session_id[:8],
            "project": project,
            "branch": fields.branch,
            "updated": int(updated),
            "status": "working" if self._clock() - mtime < WORKING_S else "idle",
            "model": fields.model,
            "effort": fields.effort,
            "mode": fields.mode,
            "tokens": fields.tokens,
            "last_prompt": fields.last_prompt,
            "last_result": fields.last_result,
            "files": fields.files(),
            "entry": "desktop" if fields.entrypoint == "claude-desktop" else "cli",
        }
        return session, fields.cwd

    def _read(self, path: str) -> _Fields:
        info = self._fs.stat(path)
        if info is None:
            raise OSError(f"{path} vanished")
        mtime, size = info
        cached = self._cache.get(path)
        if cached is not None and (size < cached.offset or size < cached.size or (size == cached.size and mtime != cached.mtime)):
            cached = None  # shorter or replaced: read it again as the first time
        if cached is None:
            cached = _Cached()
            self._cache[path] = cached
        if size > cached.offset:
            start = max(cached.offset, size - WINDOW_BYTES)
            data = self._fs.read_range(path, start, size)
            skip = 0
            if start > 0 and start != cached.offset:  # not on a line boundary we know
                cut = data.find(b"\n")  # the first line of the window is probably partial
                skip = len(data) if cut < 0 else cut + 1
            cached.offset = self._consume(cached.fields, data, skip, start)
        cached.mtime, cached.size = mtime, size
        return cached.fields

    @staticmethod
    def _consume(fields: _Fields, data: bytes, pos: int, base: int) -> int:
        """Applies the complete records of ``data`` from ``pos``; returns the file offset of the first byte not
        consumed (a last line without its newline that is not yet valid JSON waits for the next pass)."""
        end = len(data)
        while pos < end:
            nl = data.find(b"\n", pos)
            line = data[pos:end if nl < 0 else nl]
            complete = nl >= 0
            if line.strip():
                if line.startswith(b'{"type":"api-request'):  # big request records, nothing we need
                    record = None
                else:
                    try:
                        record = json.loads(line)
                        complete = True  # a valid JSON object is complete even without its newline
                    except ValueError:
                        record = None
                if record is not None and isinstance(record, dict):
                    fields.apply(record)
            if not complete:
                return base + pos
            pos = end if nl < 0 else nl + 1
        return base + end

    # --- connectors ---

    def _connectors(self, sessions: "list[tuple[dict, str]]") -> "list[dict]":
        out: list = []
        seen: set = set()
        config = self._json.get(self._config)
        if isinstance(config, dict):
            _server_entries(config.get("mcpServers"), "global", out, seen)
        projects = config.get("projects") if isinstance(config, dict) else None
        by_path = {}
        if isinstance(projects, dict):
            by_path = {_norm_path(k): v for k, v in projects.items() if isinstance(k, str)}
        done: set = set()
        for _session, cwd in sessions:
            if not cwd or _norm_path(cwd) in done:
                continue
            done.add(_norm_path(cwd))
            scope = _project_of(cwd)
            entry = by_path.get(_norm_path(cwd))
            if isinstance(entry, dict):
                _server_entries(entry.get("mcpServers"), scope, out, seen)
            mcp = self._json.get(os.path.join(cwd, ".mcp.json"))
            if isinstance(mcp, dict):
                _server_entries(mcp.get("mcpServers"), scope, out, seen)
        return out[:MAX_CONNECTORS]

    # --- focus ---

    def _focus(self) -> Optional[str]:
        return self._focus_window()[1]

    def _focus_window(self) -> "tuple[int, Optional[str]]":
        """(window, None) once the Claude window is in front; (0, notice code) otherwise."""
        try:
            if self._win32 is None:
                self._win32 = Win32Focus()
            win32 = self._win32
            hwnd = win32.find_window()
            if not hwnd:
                return 0, NOT_RUNNING
            if win32.is_iconic(hwnd):
                win32.restore(hwnd)
            if win32.set_foreground(hwnd):
                return hwnd, None
            win32.alt_tap()  # Windows refuses focus changes from a background process unless a key was just pressed
            if win32.set_foreground(hwnd):
                return hwnd, None
            self._log("claude: Windows refused to bring the Claude window to the front")
            return 0, ACTION_FAILED
        except Exception as e:  # noqa: BLE001
            self._note("focus", e)
            return 0, ACTION_FAILED

    def _invoke(self, names: "tuple[str, ...]") -> Optional[str]:
        """Bring the app to the front, then invoke its sidebar button named ``names`` (never a mouse click)."""
        hwnd, code = self._focus_window()
        if code is not None:
            return code
        try:
            if self._ui.invoke(hwnd, names):
                return None
        except Exception as e:  # noqa: BLE001
            self._note("sidebar", e)
        self._log(f"claude: no sidebar button {names[0]!r} found in the Claude app")
        return UI_NOT_FOUND

    # --- app panel ---

    def _read_app(self) -> Optional[dict]:
        """The panel of the Claude app while the device watches (at most every 3 s); the last read otherwise."""
        if not self._watch:
            return None
        now = self._clock()
        if now < self._app_next:
            return self._app
        self._app_next = now + APP_READ_S
        try:
            if self._win32 is None:
                self._win32 = Win32Focus()
            hwnd = self._win32.find_window()
            if not hwnd:
                self._app = None
                return None
            self._app = self._app_reader.read(hwnd, self._win32.window_title(hwnd), now)
            if self._app is None and self._app_reader.warming_up:
                self._app_next = now + APP_WARMUP_RETRY_S
        except Exception as e:  # noqa: BLE001
            self._note("app panel", e)
            self._app = None
        return self._app

    def _note(self, what: str, error: Exception) -> None:
        kind = (what, type(error).__name__)
        if kind not in self._logged:
            self._logged.add(kind)
            self._log(f"claude: {what}: {type(error).__name__}: {error}")


def _fit(section: dict) -> dict:
    """The section within SECTION_MAX_BYTES: last_result shortened oldest session first, then last_prompt, then files."""
    sessions = section["sessions"]

    def size() -> int:
        return len(json.dumps(section, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))

    app = section.get("app")
    if app is not None:  # the tail of the app's results goes first
        section["app"] = app = dict(app, results=list(app.get("results") or []))
        while size() > SECTION_MAX_BYTES and app["results"]:
            app["results"].pop()

    for field in ("last_result", "last_prompt", "files"):
        for session in reversed(sessions):  # the list is newest first: the oldest is shortened first
            excess = size() - SECTION_MAX_BYTES
            if excess <= 0:
                return section
            value = session[field]
            if not value:
                continue
            if field == "files":
                session[field] = []
                continue
            raw = value.encode("utf-8")
            keep = max(0, len(raw) - excess - 3)
            session[field] = raw[:keep].decode("utf-8", "ignore").rstrip() + ("…" if keep > 0 else "")
    while size() > SECTION_MAX_BYTES and section["connectors"]:
        section["connectors"].pop()
    return section


# --- real window layer ---------------------------------------------------------------------------------------------

class Win32Focus:
    """The window of the Claude app: found, restored, brought to the front. Created on first use."""

    SW_RESTORE = 9
    GW_OWNER = 4
    VK_MENU = 0x12
    KEYEVENTF_KEYUP = 0x0002

    def __init__(self) -> None:
        import ctypes
        from ctypes import wintypes
        from actions.foreground import Win32Api
        self._ctypes, self._wintypes = ctypes, wintypes
        self._api = Win32Api()
        u = ctypes.WinDLL("user32", use_last_error=True)
        self._u = u
        self._enum_proto = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
        u.EnumWindows.argtypes = [self._enum_proto, wintypes.LPARAM]
        u.IsWindowVisible.argtypes = [wintypes.HWND]
        u.GetWindow.argtypes = [wintypes.HWND, wintypes.UINT]
        u.GetWindow.restype = wintypes.HWND
        u.IsIconic.argtypes = [wintypes.HWND]
        u.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
        u.SetForegroundWindow.argtypes = [wintypes.HWND]
        u.keybd_event.argtypes = [wintypes.BYTE, wintypes.BYTE, wintypes.DWORD, ctypes.c_size_t]

    def find_window(self) -> int:
        found: "list[tuple[int, int]]" = []

        def visit(hwnd, _lparam):
            try:
                if (self._u.IsWindowVisible(hwnd) and not self._u.GetWindow(hwnd, self.GW_OWNER)
                        and self._api.window_title(int(hwnd))):
                    path = self._api.process_exe(self._api.window_pid(int(hwnd))) or ""
                    if os.path.basename(path).lower() == "claude.exe":
                        found.append((0 if "anthropic" in path.lower() else 1, int(hwnd)))
            except Exception:  # noqa: BLE001 - one odd window must not stop the search
                pass
            return True

        callback = self._enum_proto(visit)
        self._u.EnumWindows(callback, 0)
        found.sort(key=lambda item: item[0])
        return found[0][1] if found else 0

    def is_iconic(self, hwnd: int) -> bool:
        return bool(self._u.IsIconic(hwnd))

    def restore(self, hwnd: int) -> None:
        self._u.ShowWindow(hwnd, self.SW_RESTORE)

    def set_foreground(self, hwnd: int) -> bool:
        return bool(self._u.SetForegroundWindow(hwnd))

    def window_title(self, hwnd: int) -> str:
        return self._api.window_title(hwnd)

    def alt_tap(self) -> None:
        self._u.keybd_event(self.VK_MENU, 0, 0, 0)
        self._u.keybd_event(self.VK_MENU, 0, self.KEYEVENTF_KEYUP, 0)
