"""Which app is in front on the PC (context bar, spec 2026-10-13 §2).

``ForegroundTracker.current()`` asks Windows for the foreground window (``GetForegroundWindow``), its class, title
and process (``GetWindowThreadProcessId`` then ``QueryFullProcessImageNameW`` for the exe) and answers a
``ForegroundApp``. Windows that are not "an app" are skipped and the last real app is kept instead:

* Orizon X itself: by exe name (``OrizonX.exe``) and by process id. Run from the sources the app is
  ``python.exe`` / ``pythonw.exe``, which must stay a real app for other scripts, so only OUR pid counts. The
  parent process counts too when it runs the same exe (the venv launcher, the PyInstaller bootloader), but not a
  parent that is Explorer or a terminal;
* the desktop and the taskbars (``Progman``, ``WorkerW``, ``Shell_TrayWnd``, ``Shell_SecondaryTrayWnd``);
* no foreground window at all (a transition, the lock screen).

A process whose exe cannot be read (an elevated one) gives ``exe == ""``: the generic profile applies. The Win32
layer is injectable (``api``: foreground_window, window_class, window_title, window_pid, process_exe) so that the
tests need no real window. Called from the hub thread only.
"""
from __future__ import annotations

import ctypes
import logging
import os
import re
from ctypes import wintypes
from dataclasses import dataclass
from typing import Any, Optional

_log = logging.getLogger("orizonx.actions.foreground")

OWN_EXE = "orizonx.exe"
IGNORED_CLASSES = frozenset({"Progman", "WorkerW", "Shell_TrayWnd", "Shell_SecondaryTrayWnd"})
SHORT_TITLE_MAX = 24

_PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
_MAX_PATH_CHARS = 32768
_TITLE_CHARS = 512
_TITLE_SEPARATOR = re.compile(r"\s+[-–—](?:\s+|$)")


@dataclass(frozen=True)
class ForegroundApp:
    exe: str  # base name as Windows spells it ("POWERPNT.EXE"), "" when unreadable
    window_class: str
    title: str
    pid: int


def short_title(title: str) -> str:
    """The short name of a window title: its last " - " segment ("Untitled - Notepad" -> "Notepad"),
    cut to SHORT_TITLE_MAX characters."""
    segments = [s.strip() for s in _TITLE_SEPARATOR.split(title.strip())]
    text = next((s for s in reversed(segments) if s), "")
    if len(text) > SHORT_TITLE_MAX:
        text = text[:SHORT_TITLE_MAX - 1].rstrip() + "…"
    return text


def _base_name(path: Optional[str]) -> str:
    return path.replace("/", "\\").rsplit("\\", 1)[-1] if path else ""


class Win32Api:
    """The real user32 / kernel32 calls. Every failure is an empty answer (0, "", None), never an exception."""

    def __init__(self) -> None:
        user32 = ctypes.WinDLL("user32", use_last_error=True)
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        self._get_foreground = user32.GetForegroundWindow
        self._get_foreground.argtypes = []
        self._get_foreground.restype = wintypes.HWND
        self._get_class = user32.GetClassNameW
        self._get_class.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
        self._get_class.restype = ctypes.c_int
        self._get_text = user32.GetWindowTextW
        self._get_text.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
        self._get_text.restype = ctypes.c_int
        self._get_pid = user32.GetWindowThreadProcessId
        self._get_pid.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
        self._get_pid.restype = wintypes.DWORD
        self._open_process = kernel32.OpenProcess
        self._open_process.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        self._open_process.restype = wintypes.HANDLE
        self._query_name = kernel32.QueryFullProcessImageNameW
        self._query_name.argtypes = [wintypes.HANDLE, wintypes.DWORD, wintypes.LPWSTR, ctypes.POINTER(wintypes.DWORD)]
        self._query_name.restype = wintypes.BOOL
        self._close = kernel32.CloseHandle
        self._close.argtypes = [wintypes.HANDLE]
        self._close.restype = wintypes.BOOL

    def foreground_window(self) -> int:
        return int(self._get_foreground() or 0)

    def window_class(self, hwnd: int) -> str:
        buf = ctypes.create_unicode_buffer(256)
        return buf.value if self._get_class(hwnd, buf, len(buf)) > 0 else ""

    def window_title(self, hwnd: int) -> str:
        buf = ctypes.create_unicode_buffer(_TITLE_CHARS)
        return buf.value if self._get_text(hwnd, buf, len(buf)) > 0 else ""

    def window_pid(self, hwnd: int) -> int:
        pid = wintypes.DWORD(0)
        self._get_pid(hwnd, ctypes.byref(pid))
        return int(pid.value)

    def process_exe(self, pid: int) -> Optional[str]:
        if pid <= 0:
            return None
        handle = self._open_process(_PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
        if not handle:
            return None
        try:
            buf = ctypes.create_unicode_buffer(_MAX_PATH_CHARS)
            size = wintypes.DWORD(len(buf))
            if self._query_name(handle, 0, buf, ctypes.byref(size)):
                return buf.value
            return None
        finally:
            self._close(handle)


class ForegroundTracker:
    def __init__(self, api: Any = None, own_pid: Optional[int] = None, parent_pid: Optional[int] = None) -> None:
        self._api = api if api is not None else Win32Api()
        own = os.getpid() if own_pid is None else own_pid
        parent = os.getppid() if parent_pid is None else parent_pid
        self._own_pids = {own}
        own_exe = _base_name(self._api.process_exe(own)).lower()
        if parent and own_exe and _base_name(self._api.process_exe(parent)).lower() == own_exe:
            self._own_pids.add(parent)
        self._last: Optional[ForegroundApp] = None

    def current(self) -> Optional[ForegroundApp]:
        """The app in front, or the last real one while Orizon X / the desktop / nothing is; None before any."""
        api = self._api
        hwnd = api.foreground_window()
        if not hwnd:
            return self._last
        window_class = api.window_class(hwnd)
        if window_class in IGNORED_CLASSES:
            return self._last
        pid = api.window_pid(hwnd)
        if pid in self._own_pids:
            return self._last
        exe = _base_name(api.process_exe(pid))
        if exe.lower() == OWN_EXE:
            return self._last
        self._last = ForegroundApp(exe, window_class, api.window_title(hwnd), pid)
        return self._last
