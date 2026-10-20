"""The address of the tab in front in a browser window (context bar, creative-apps spec 2026-10-19 §2).

Chrome's window title for a Canva design is "hdi - Présentation - Google Chrome": nothing says Canva, so the browser
profiles Canva and Figma are picked by the page's host, read from the browser's address bar with UI Automation
(read-only: it looks at the accessibility tree, sends no key and no click). Chrome and Edge show the URL without its
scheme ("canva.com/design/DAH.../edit"), which ``host_of`` accepts as well as a full URL.

``BrowserUrlReader.url(hwnd, title)`` never raises: any failure (UI Automation missing, a window that closed, a
browser without a findable address bar) is ``None`` and is logged once per kind of failure. It asks UI Automation
(about 40 ms) only when the window or its title is not the one of the last answer (a tab switch or a navigation changes
the title), or when that answer is older than ``RECHECK_S`` (the URL can change while the title does not), so the
context poll (every 250 ms) stays cheap. The UI Automation layer is injectable (``uia.address_bar_value(hwnd)``).

``UiaLayer`` is the real one. comtypes is imported lazily in its first call, never at module level (importing comtypes
or winrt before PySide6 crashes the app, 0xC0000005), and the UIAutomation object is created on the thread that uses
it (the hub thread, which has joined the multithreaded apartment; see actions/hub.py) and again if another thread
comes to use it.
"""
from __future__ import annotations

import logging
import re
import threading
import time
from typing import Any, Callable, Optional

_log = logging.getLogger("orizonx.actions.browser_url")

RECHECK_S = 5.0
_CACHE_MAX = 16
_SCHEME = re.compile(r"^[a-z][a-z0-9+.\-]*://", re.IGNORECASE)


def host_of(url: Optional[str]) -> Optional[str]:
    """The lower-case host of an address as a browser shows it, with or without a scheme, a ``www.`` prefix, a port
    or a path ("Canva.com/design/x" -> "canva.com"); None when it does not look like an address (empty, a search
    typed in the bar)."""
    if not isinstance(url, str):
        return None
    text = _SCHEME.sub("", url.strip())
    host = re.split(r"[/?#]", text, maxsplit=1)[0]
    host = host.rsplit("@", 1)[-1]
    host = host.split(":", 1)[0].strip().lower().rstrip(".")
    if host.startswith("www."):
        host = host[4:]
    if not host or re.search(r"\s", host):
        return None
    return host


def host_matches(host: Optional[str], domain: str) -> bool:
    """True when ``host`` is ``domain`` or one of its subdomains."""
    return bool(host) and (host == domain or host.endswith("." + domain))


class UiaLayer:
    """The real UI Automation calls: the value of the first Edit control of a window (a browser's address bar), and the
    tab items of a browser window (actions.browser_tabs)."""

    def __init__(self) -> None:
        self._uia: Any = None
        self._client: Any = None
        self._thread: Optional[int] = None

    def _ensure(self) -> None:
        if self._uia is not None and self._thread == threading.get_ident():
            return
        import comtypes.client
        comtypes.client.GetModule("UIAutomationCore.dll")
        from comtypes.gen import UIAutomationClient as client
        self._client = client
        self._uia = comtypes.client.CreateObject(client.CUIAutomation, interface=client.IUIAutomation)
        self._thread = threading.get_ident()

    def list_tabs(self, hwnd: int) -> list:
        """The TabItem elements of the window, in tab-strip order: [(accessible name, selected, element)]. Read-only."""
        self._ensure()
        client = self._client
        element = self._uia.ElementFromHandle(hwnd)
        condition = self._uia.CreatePropertyCondition(client.UIA_ControlTypePropertyId, client.UIA_TabItemControlTypeId)
        found = element.FindAll(client.TreeScope_Descendants, condition)
        tabs = []
        for i in range(found.Length):
            item = found.GetElement(i)
            try:
                selected = bool(item.GetCurrentPattern(client.UIA_SelectionItemPatternId).QueryInterface(
                    client.IUIAutomationSelectionItemPattern).CurrentIsSelected)
            except Exception:  # noqa: BLE001 - an item without the pattern is just not the selected one
                selected = False
            tabs.append((item.CurrentName, selected, item))
        return tabs

    def _role(self, element: Any) -> str:
        client = self._client
        try:
            kind = element.CurrentControlType
        except Exception:  # noqa: BLE001
            return "Other"
        return {client.UIA_GroupControlTypeId: "Group", client.UIA_TextControlTypeId: "Text",
                client.UIA_ButtonControlTypeId: "Button", client.UIA_ListItemControlTypeId: "ListItem",
                client.UIA_ToolBarControlTypeId: "ToolBar", client.UIA_TreeItemControlTypeId: "TreeItem",
                client.UIA_HyperlinkControlTypeId: "Hyperlink"}.get(kind, "Other")

    def walk_nodes(self, hwnd: int, cap: int = 20000, budget_s: float = 2.5) -> list:
        """The elements of the window in document order (RawView walker, depth first, at most ``cap`` and ``budget_s``
        seconds): [(depth, role, accessible name)]. Read-only."""
        import time
        self._ensure()
        walker = self._uia.RawViewWalker
        deadline = time.monotonic() + budget_s
        stack = [(self._uia.ElementFromHandle(hwnd), 0)]
        out: list = []
        while stack and len(out) < cap and time.monotonic() < deadline:
            element, depth = stack.pop()
            try:
                name = element.CurrentName or ""
            except Exception:  # noqa: BLE001
                name = ""
            out.append((depth, self._role(element), name))
            try:
                child, kids = walker.GetFirstChildElement(element), []
                while child:
                    kids.append(child)
                    child = walker.GetNextSiblingElement(child)
                stack.extend((k, depth + 1) for k in reversed(kids))
            except Exception:  # noqa: BLE001 - a node that vanished: skip its subtree
                pass
        return out

    def invoke_named(self, hwnd: int, names: tuple, cap: int = 20000, budget_s: float = 2.5) -> bool:
        """InvokePattern.Invoke() on the first button-like element of the window whose accessible name is one of
        ``names`` (case-insensitive) and that supports Invoke. False when there is none."""
        import time
        self._ensure()
        client = self._client
        wanted = {n.strip().lower() for n in names}
        walker = self._uia.RawViewWalker
        deadline = time.monotonic() + budget_s
        stack = [self._uia.ElementFromHandle(hwnd)]
        seen = 0
        while stack and seen < cap and time.monotonic() < deadline:
            element = stack.pop()
            seen += 1
            try:
                name = (element.CurrentName or "").strip().lower()
            except Exception:  # noqa: BLE001
                name = ""
            if name in wanted and self._role(element) in ("Button", "ListItem", "TreeItem", "Hyperlink"):
                try:
                    if element.GetCurrentPropertyValue(client.UIA_IsInvokePatternAvailablePropertyId):
                        element.GetCurrentPattern(client.UIA_InvokePatternId).QueryInterface(
                            client.IUIAutomationInvokePattern).Invoke()
                        return True
                    # Sans Invoke, un bouton qui déplie (« Afficher la barre latérale » de l'app Claude n'a que
                    # ExpandCollapse) : on bascule son état, comme un clic.
                    if element.GetCurrentPropertyValue(client.UIA_IsExpandCollapsePatternAvailablePropertyId):
                        pattern = element.GetCurrentPattern(client.UIA_ExpandCollapsePatternId).QueryInterface(
                            client.IUIAutomationExpandCollapsePattern)
                        if pattern.CurrentExpandCollapseState == client.ExpandCollapseState_Collapsed:
                            pattern.Expand()
                        else:
                            pattern.Collapse()
                        return True
                except Exception:  # noqa: BLE001 - not invokable after all: keep looking
                    pass
            try:
                child, kids = walker.GetFirstChildElement(element), []
                while child:
                    kids.append(child)
                    child = walker.GetNextSiblingElement(child)
                stack.extend(reversed(kids))
            except Exception:  # noqa: BLE001
                pass
        return False

    def _find(self, hwnd: int, accept: Any, cap: int = 20000, budget_s: float = 2.5) -> Any:
        """The first element (document order) for which ``accept(element, role, name)`` is true, or None."""
        import time
        walker = self._uia.RawViewWalker
        deadline = time.monotonic() + budget_s
        stack = [self._uia.ElementFromHandle(hwnd)]
        seen = 0
        while stack and seen < cap and time.monotonic() < deadline:
            element = stack.pop()
            seen += 1
            try:
                name = " ".join((element.CurrentName or "").split())
            except Exception:  # noqa: BLE001
                name = ""
            if name and accept(element, self._role(element), name):
                return element
            try:
                child, kids = walker.GetFirstChildElement(element), []
                while child:
                    kids.append(child)
                    child = walker.GetNextSiblingElement(child)
                stack.extend(reversed(kids))
            except Exception:  # noqa: BLE001
                pass
        return None

    def _has(self, element: Any, prop: int) -> bool:
        try:
            return bool(element.GetCurrentPropertyValue(prop))
        except Exception:  # noqa: BLE001
            return False

    def expand_matching(self, hwnd: int, pattern: str, wait_s: float = 0.0) -> bool:
        """ExpandCollapsePattern.Expand() on the first Button whose name matches ``pattern`` (Invoke if it has no
        ExpandCollapse), unless it is already expanded. True when such a button exists, waiting up to ``wait_s``."""
        import re
        import time
        self._ensure()
        client = self._client
        rx = re.compile(pattern, re.IGNORECASE)

        def accept(element, role, name):
            return (role == "Button" and rx.search(name) is not None
                    and (self._has(element, client.UIA_IsExpandCollapsePatternAvailablePropertyId)
                         or self._has(element, client.UIA_IsInvokePatternAvailablePropertyId)))

        deadline = time.monotonic() + wait_s
        while True:
            element = self._find(hwnd, accept)
            if element is not None:
                break
            if time.monotonic() >= deadline:
                return False
            time.sleep(0.15)
        if self._has(element, client.UIA_IsExpandCollapsePatternAvailablePropertyId):
            pat = element.GetCurrentPattern(client.UIA_ExpandCollapsePatternId).QueryInterface(
                client.IUIAutomationExpandCollapsePattern)
            if pat.CurrentExpandCollapseState == 0:  # ExpandCollapseState_Collapsed
                pat.Expand()
        else:
            element.GetCurrentPattern(client.UIA_InvokePatternId).QueryInterface(client.IUIAutomationInvokePattern).Invoke()
        return True

    def toggle_on_named(self, hwnd: int, names: tuple) -> bool:
        """TogglePattern.Toggle() on the toggle button of one of these names when it is off (state 0). True if found."""
        self._ensure()
        client = self._client
        wanted = {n.strip().lower() for n in names}

        def accept(element, role, name):
            return (role == "Button" and name.lower() in wanted
                    and self._has(element, client.UIA_IsTogglePatternAvailablePropertyId))

        element = self._find(hwnd, accept)
        if element is None:
            return False
        pat = element.GetCurrentPattern(client.UIA_TogglePatternId).QueryInterface(client.IUIAutomationTogglePattern)
        if pat.CurrentToggleState == 0:  # ToggleState_Off
            pat.Toggle()
        return True

    def select_tab(self, item: Any) -> None:
        """SelectionItemPattern.Select() on a TabItem element given by list_tabs: switches to that tab."""
        self._ensure()
        client = self._client
        item.GetCurrentPattern(client.UIA_SelectionItemPatternId).QueryInterface(
            client.IUIAutomationSelectionItemPattern).Select()

    def address_bar_value(self, hwnd: int) -> Optional[str]:
        self._ensure()
        client = self._client
        element = self._uia.ElementFromHandle(hwnd)
        condition = self._uia.CreatePropertyCondition(client.UIA_ControlTypePropertyId, client.UIA_EditControlTypeId)
        edit = element.FindFirst(client.TreeScope_Descendants, condition)
        if not edit:
            return None
        pattern = edit.GetCurrentPattern(client.UIA_ValuePatternId).QueryInterface(client.IUIAutomationValuePattern)
        value = pattern.CurrentValue
        return value if isinstance(value, str) else None


class BrowserUrlReader:
    def __init__(self, uia: Any = None, log: Optional[Callable[[str], None]] = None,
                 clock: Callable[[], float] = time.monotonic) -> None:
        self._uia = uia  # created on first use when None (the import of comtypes waits for it)
        self._log = log or _log.warning
        self._clock = clock
        self._cache: dict = {}  # (hwnd, title) -> (answer time, url)
        self._logged: set = set()

    def url(self, hwnd: int, title: str = "") -> Optional[str]:
        """The address in the bar of the browser window ``hwnd`` (whose title is ``title``), or None."""
        if not hwnd:
            return None
        key = (hwnd, title)
        now = self._clock()
        cached = self._cache.get(key)
        if cached is not None and now - cached[0] < RECHECK_S:
            return cached[1]
        try:
            if self._uia is None:
                self._uia = UiaLayer()
            value = self._uia.address_bar_value(hwnd)
            url = value.strip() if isinstance(value, str) and value.strip() else None
        except Exception as e:  # noqa: BLE001 - COMError, ImportError, a closed window...: never a reason to break the bar
            kind = type(e).__name__
            if kind not in self._logged:
                self._logged.add(kind)
                self._log(f"browser url: cannot read the address bar ({kind}: {e}); using the window title only")
            url = None
        if len(self._cache) >= _CACHE_MAX:
            self._cache.clear()
        self._cache[key] = (now, url)
        return url
