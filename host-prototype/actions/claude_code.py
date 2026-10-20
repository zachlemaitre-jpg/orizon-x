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

``claude.focus``: brings the main window of the Claude app to the front (``Win32Focus``, injectable): the visible,
unowned, titled top-level window of a ``claude.exe`` process; ``SW_RESTORE`` if minimised, ``SetForegroundWindow``, and on
refusal an Alt key press and release (``keybd_event``, the usual workaround) and one more try. Returns the notice code
``claude_not_running`` when there is no such window, ``action_failed`` when Windows refuses twice. Normal hub path.
"""
from __future__ import annotations

import json
import logging
import os
import time
from datetime import datetime
from typing import Any, Callable, Optional

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
ACTION_FAILED = "action_failed"
FOCUS_ID = "claude.focus"

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


# --- provider ----------------------------------------------------------------------------------------------------

class ClaudeCodeProvider:
    def __init__(self, root: Optional[str] = None, clock: Callable[[], float] = time.time, fs: Any = None,
                 home: Optional[str] = None, win32: Any = None, log: Optional[Callable[[str], None]] = None) -> None:
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
            section = {"available": True, "sessions": [s[0] for s in sessions], "connectors": connectors}
            return _fit(section)
        except Exception as e:  # noqa: BLE001 - the hub marks a failing provider unavailable; keep the bar alive
            self._note("snapshot", e)
            return {"available": False}

    def handle(self, action: dict) -> Optional[str]:
        if action.get("id") != FOCUS_ID:
            self._log(f"claude: unknown action {action.get('id')!r}")
            return ACTION_FAILED
        return self._focus()

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
        try:
            if self._win32 is None:
                self._win32 = Win32Focus()
            win32 = self._win32
            hwnd = win32.find_window()
            if not hwnd:
                return NOT_RUNNING
            if win32.is_iconic(hwnd):
                win32.restore(hwnd)
            if win32.set_foreground(hwnd):
                return None
            win32.alt_tap()  # Windows refuses focus changes from a background process unless a key was just pressed
            if win32.set_foreground(hwnd):
                return None
            self._log("claude: Windows refused to bring the Claude window to the front")
            return ACTION_FAILED
        except Exception as e:  # noqa: BLE001
            self._note("focus", e)
            return ACTION_FAILED

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

    def alt_tap(self) -> None:
        self._u.keybd_event(self.VK_MENU, 0, 0, 0)
        self._u.keybd_event(self.VK_MENU, 0, self.KEYEVENTF_KEYUP, 0)
