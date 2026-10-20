"""The context bar's provider (spec 2026-10-13 §3): the profile of the app in front on the PC, and its buttons.

Snapshot: ``{"available": True, "app": <name>, "profile": <profile id>, "buttons": [{"id", "icon", "label"}],
"pages": [{"id", "label", "buttons": [{"id", "icon", "label"}]}], "icon": <sha1 of the app's or site's icon PNG> | None}``
(the shortcuts stay on the PC; ``buttons`` is the first page that does not scroll, for the apps that do not know
``pages``; ``icon`` comes from actions.app_icons, None while it is not ready, and the hub sends the image whenever it
changes), or ``{"available": False}`` while no app has been in front yet. Labels and the app name are in the device's
language (``lang``, "en" or "fr"; French when unknown).

Browser tabs (actions.browser_tabs): for a browser window, when its tabs can be read, a dynamic page ``tabs``
(``"scroll": True``, up to 24 buttons ``{"id": "tab.<rank>", "icon": "tab", "label": <short title>, "active": bool}``)
is the first page of the browser profile and the last page of the site profiles (canva, figma). The list sent last is
remembered: ``context.press`` on ``tab.<rank>`` is accepted only for a rank of that list, in front of that browser
window, and asks the reader to ``select`` the tab (with the title that was sent); a failure is logged.

``handle({"id": "context.lang", "lang": "en"})`` switches that language (an unknown value is ignored and logged); the
hub re-polls after any handled action, so the translated bar is broadcast at once.

``handle({"id": "context.press", "button": <id>})`` looks at the app in front NOW, and presses the shortcut of the
button only if that button belongs to a page of its profile: when the foreground changed since the device drew its bar, the
action is ignored (and logged), never sent to the wrong app. A shortcut that cannot be injected (blocked by UIPI in
front of an elevated app, a key the layout lacks) is ``action_failed``. Hub thread only.
"""
from __future__ import annotations

import logging
import re
from typing import Any, Callable, Optional

from actions import context_profiles, keys
from actions.app_icons import AppIconProvider
from actions.browser_tabs import BrowserTabsReader
from actions.browser_url import BrowserUrlReader, UiaLayer
from actions.foreground import ForegroundTracker

_log = logging.getLogger("orizonx.actions.context")

PRESS_ID = "context.press"
LANG_ID = "context.lang"
ACTION_FAILED = "action_failed"
UI_NOT_FOUND = "claude_ui_not_found"
TABS_PAGE_LABELS = {"en": "Tabs", "fr": "Onglets"}
_TAB_BUTTON = re.compile(r"^tab\.(\d+)$")


class ContextProvider:
    def __init__(self, tracker: Any = None, send_shortcut: Optional[Callable[[str], bool]] = None,
                 log: Optional[Callable[[str], None]] = None, lang: str = context_profiles.DEFAULT_LANG,
                 url_reader: Any = None, icons: Any = None, tabs_reader: Any = None,
                 uia_invoker: Optional[Callable[[int, tuple], bool]] = None) -> None:
        self.lang = context_profiles.normalize_lang(lang)
        self._tracker = tracker if tracker is not None else ForegroundTracker()
        self._send_shortcut = send_shortcut or keys.send_shortcut
        self._log = log or _log.info
        uia = UiaLayer()  # one UI Automation layer (and one COM object) for the address bar and the tabs
        self._url_reader = url_reader if url_reader is not None else BrowserUrlReader(uia, self._log)
        self._tabs_reader = tabs_reader if tabs_reader is not None else BrowserTabsReader(
            uia, self._log, send_shortcut=self._send_shortcut)
        # buttons that invoke a UI Automation element of the window in front (the Claude app's sidebar); the shared layer
        self._uia_invoker = uia_invoker if uia_invoker is not None else (lambda hwnd, names: uia.invoke_named(hwnd, names))
        self._sent_tabs: Optional[tuple] = None  # (window, [(rank, title)]) of the last snapshot with a tabs page
        self._icons = icons if icons is not None else AppIconProvider(log=self._log)

    def _profile(self, app: Any) -> "tuple[context_profiles.Profile, Optional[str]]":
        """The profile of ``app`` and the tab's URL it was picked with (read only for a browser window)."""
        url = None
        if context_profiles.is_browser(app) and getattr(app, "hwnd", 0):
            url = self._url_reader.url(app.hwnd, app.title)
        return context_profiles.match(app, url), url

    def snapshot(self) -> dict:
        app = self._tracker.current()
        if app is None:
            return {"available": False}
        profile, url = self._profile(app)
        pages = [{"id": page.id, "label": page.label(self.lang), "buttons": self._buttons(page)}
                 for page in profile.pages if page.shown]
        tabs_page = self._tabs_page(app, profile)
        if tabs_page is not None:
            pages = [tabs_page] + pages if profile.id == "browser" else pages + [tabs_page]
        return {
            "available": True,
            "app": context_profiles.display_name(app, self.lang, url),
            "profile": profile.id,
            "buttons": next(p["buttons"] for p in pages if not p.get("scroll")),
            "pages": pages,
            "icon": self._icons.icon_id(app, profile, url),
        }

    def _tabs_page(self, app: Any, profile: context_profiles.Profile) -> Optional[dict]:
        """The dynamic page of the open tabs of a browser window (None: not a browser, or no tab could be read)."""
        self._sent_tabs = None
        hwnd = getattr(app, "hwnd", 0)
        if not (context_profiles.is_browser(app) and hwnd):
            return None
        tabs = self._tabs_reader.tabs(hwnd, app.title)
        if not tabs:
            return None
        self._sent_tabs = (hwnd, [(t.index, t.title) for t in tabs])
        return {"id": "tabs", "label": TABS_PAGE_LABELS[self.lang], "scroll": True,
                "buttons": [{"id": f"tab.{t.index}", "icon": "tab", "label": t.title, "active": t.active}
                            for t in tabs]}

    def _press_uia(self, app: Any, button: "context_profiles.Button") -> Optional[str]:
        """A button that invokes an element of the window in front by name (the app is already in front: it is the one
        whose profile matched). ``claude_ui_not_found`` when the element is not there."""
        try:
            if getattr(app, "hwnd", 0) and self._uia_invoker(app.hwnd, button.uia):
                return None
        except Exception as e:  # noqa: BLE001 - COM errors, a closing window...
            self._log(f"context: {button.id!r} could not invoke {button.uia[0]!r}: {type(e).__name__}: {e}")
            return UI_NOT_FOUND
        self._log(f"context: {button.id!r}: no element named {button.uia[0]!r} in the window in front")
        return UI_NOT_FOUND

    def _press_tab(self, app: Any, rank: int) -> None:
        sent = self._sent_tabs
        title = next((t for r, t in sent[1] if r == rank), None) if sent is not None else None
        if title is None or not context_profiles.is_browser(app) or getattr(app, "hwnd", 0) != sent[0]:
            self._log(f"context: tab {rank} ignored, it is not in the last tab list sent for the window in front")
            return
        if not self._tabs_reader.select(sent[0], rank, title):
            self._log(f"context: tab {rank} ({title!r}) could not be selected")

    def artwork_bytes(self, icon_id: Optional[str]) -> Optional[bytes]:
        """The PNG of an icon id of the snapshot, for the hub (sent as a MEDIA_ARTWORK)."""
        return self._icons.artwork_bytes(icon_id)

    def _buttons(self, page: context_profiles.Page) -> list:
        return [{"id": b.id, "icon": b.icon, "label": b.label(self.lang)} for b in page.shown]

    def handle(self, action: dict) -> Optional[str]:
        if action.get("id") == LANG_ID:
            lang = action.get("lang")
            if lang in context_profiles.LANGS:
                self.lang = lang
            else:
                self._log(f"context: language {lang!r} ignored, only {', '.join(context_profiles.LANGS)} are known")
            return None
        if action.get("id") != PRESS_ID:
            self._log(f"context: unknown action {action.get('id')!r}")
            return ACTION_FAILED
        button_id = action.get("button")
        app = self._tracker.current()
        tab = _TAB_BUTTON.match(button_id) if isinstance(button_id, str) else None
        if tab is not None:
            self._press_tab(app, int(tab.group(1)))
            return None
        profile, _ = self._profile(app)
        button = next((b for b in profile.buttons if b.id == button_id), None) if app is not None else None
        if button is None:
            self._log(f"context: button {button_id!r} ignored, it is not in the profile of the app in front "
                      f"({profile.id if app is not None else 'none'})")
            return None
        if button.uia:
            return self._press_uia(app, button)
        try:
            sent = self._send_shortcut(button.shortcut)
        except ValueError as e:
            self._log(f"context: shortcut {button.shortcut!r} of {button.id!r} cannot be sent: {e}")
            return ACTION_FAILED
        if not sent:
            self._log(f"context: {button.shortcut!r} was not injected (an elevated app in front?)")
            return ACTION_FAILED
        return None
