"""The tabs of the browser window in front (context bar, spec 2026-10-19 browser-tabs §2).

``BrowserTabsReader.tabs(hwnd, title)`` lists the ``TabItem`` elements of the window with UI Automation (read-only),
in the order of the tab strip, at most 24: ``[Tab(index, title, active)]``. ``active`` is the item's
``SelectionItemPattern.CurrentIsSelected``. It never raises: an error is ``[]``, logged once per kind of error. The
list is cached per (window, window title) and read again after ``RECHECK_S`` even when the title did not change, and
at once after a switch.

``select(hwnd, index, title)`` switches to a tab: it reads the tabs again, takes the one of rank ``index`` if its
short title is ``title`` (the title the device was given), else the first tab with that title, else does nothing
(False). It calls ``SelectionItemPattern.Select()``; if that fails and the rank is under 8 it presses ``Ctrl+<rank+1>``
through actions.keys. Returns True when one of the two went through.

The real UI Automation layer is ``browser_url.UiaLayer`` (``list_tabs`` / ``select_tab``), shared with the address bar
reader; comtypes is imported lazily there, never here, and the UIAutomation object belongs to the thread that uses it.
"""
from __future__ import annotations

import logging
import re
import time
from dataclasses import dataclass
from typing import Any, Callable, Optional

_log = logging.getLogger("orizonx.actions.browser_tabs")

MAX_TABS = 24
MAX_TITLE = 40
RECHECK_S = 2.0
MAX_CTRL_DIGIT_RANK = 8  # Ctrl+1..Ctrl+8 reach the first eight tabs
_CACHE_MAX = 16
_MEMORY_SUFFIX = re.compile(r" - (?:Utilisation de la mémoire|Memory usage) - .*$")


@dataclass(frozen=True)
class Tab:
    index: int
    title: str
    active: bool


def short_tab_title(name: object) -> str:
    """A tab's accessible name as a short title: Chrome's memory tooltip suffix is removed ("Accueil - Canva -
    Utilisation de la mémoire - 498 Mo" -> "Accueil - Canva"), spaces are stripped, and the title is cut to
    MAX_TITLE characters, the last one being an ellipsis."""
    if not isinstance(name, str):
        return ""
    text = _MEMORY_SUFFIX.sub("", name).strip()
    if len(text) > MAX_TITLE:
        text = text[:MAX_TITLE - 1].rstrip() + "…"
    return text


class BrowserTabsReader:
    def __init__(self, uia: Any = None, log: Optional[Callable[[str], None]] = None,
                 clock: Callable[[], float] = time.monotonic,
                 send_shortcut: Optional[Callable[[str], bool]] = None) -> None:
        self._uia = uia  # browser_url.UiaLayer on first use when None
        self._log = log or _log.warning
        self._clock = clock
        self._send_shortcut = send_shortcut
        self._cache: dict = {}  # (hwnd, window title) -> (read time, [Tab])
        self._logged: set = set()

    # --- reading ---

    def tabs(self, hwnd: int, title: str = "") -> "list[Tab]":
        if not hwnd:
            return []
        key = (hwnd, title)
        now = self._clock()
        cached = self._cache.get(key)
        if cached is not None and now - cached[0] < RECHECK_S:
            return list(cached[1])
        tabs = [Tab(t[0], t[1], t[2]) for t in self._read(hwnd)]
        if len(self._cache) >= _CACHE_MAX:
            self._cache.clear()
        self._cache[key] = (now, tabs)
        return list(tabs)

    def _read(self, hwnd: int) -> "list[tuple]":
        """(index, short title, active, handle) of the tabs of the window; [] on any error."""
        raw = self._read_raw(hwnd)
        out = []
        for entry in raw:
            if not isinstance(entry, tuple) or len(entry) != 3 or not isinstance(entry[0], str):
                continue
            name, selected, handle = entry
            if len(out) >= MAX_TABS:
                break
            index = len(out)
            out.append((index, short_tab_title(name) or str(index + 1), bool(selected), handle))
        return out

    def _read_raw(self, hwnd: int) -> list:
        try:
            if self._uia is None:
                from actions.browser_url import UiaLayer
                self._uia = UiaLayer()
            return [tuple(e) if isinstance(e, (tuple, list)) else e for e in self._uia.list_tabs(hwnd)]
        except Exception as e:  # noqa: BLE001 - COMError, ImportError, a closed window...: no tabs page
            self._note("cannot read the tabs", e)
            return []

    # --- switching ---

    def select(self, hwnd: int, index: int, title: str) -> bool:
        if not hwnd:
            return False
        entries = self._read(hwnd)
        self._cache.clear()  # the strip changes now, whatever happens next
        match = next((e for e in entries if e[0] == index and e[1] == title), None)
        if match is None:
            match = next((e for e in entries if e[1] == title), None)
        if match is None:
            return False
        rank, _, _, handle = match
        try:
            self._uia.select_tab(handle)
            return True
        except Exception as e:  # noqa: BLE001
            self._note("Select() failed", e)
        if rank >= MAX_CTRL_DIGIT_RANK:
            return False
        try:
            send = self._send_shortcut
            if send is None:
                from actions import keys
                send = keys.send_shortcut
            return bool(send(f"Ctrl+{rank + 1}"))
        except Exception as e:  # noqa: BLE001 - ValueError: a key the layout lacks
            self._note("Ctrl+number failed", e)
            return False

    def _note(self, what: str, error: Exception) -> None:
        kind = (what, type(error).__name__)
        if kind not in self._logged:
            self._logged.add(kind)
            self._log(f"browser tabs: {what} ({type(error).__name__}: {error})")
