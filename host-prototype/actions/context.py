"""The context bar's provider (spec 2026-10-13 §3): the profile of the app in front on the PC, and its buttons.

Snapshot: ``{"available": True, "app": <name>, "profile": <profile id>, "buttons": [{"id", "icon", "label"}],
"pages": [{"id", "label", "buttons": [{"id", "icon", "label"}]}]}`` (the shortcuts stay on the PC; ``buttons`` is the
first page, for the apps that do not know ``pages``), or ``{"available": False}`` while no app has been in front yet. Labels and the app
name are in the device's language (``lang``, "en" or "fr"; French when unknown).

``handle({"id": "context.lang", "lang": "en"})`` switches that language (an unknown value is ignored and logged); the
hub re-polls after any handled action, so the translated bar is broadcast at once.

``handle({"id": "context.press", "button": <id>})`` looks at the app in front NOW, and presses the shortcut of the
button only if that button belongs to a page of its profile: when the foreground changed since the device drew its bar, the
action is ignored (and logged), never sent to the wrong app. A shortcut that cannot be injected (blocked by UIPI in
front of an elevated app, a key the layout lacks) is ``action_failed``. Hub thread only.
"""
from __future__ import annotations

import logging
from typing import Any, Callable, Optional

from actions import context_profiles, keys
from actions.browser_url import BrowserUrlReader
from actions.foreground import ForegroundTracker

_log = logging.getLogger("orizonx.actions.context")

PRESS_ID = "context.press"
LANG_ID = "context.lang"
ACTION_FAILED = "action_failed"


class ContextProvider:
    def __init__(self, tracker: Any = None, send_shortcut: Optional[Callable[[str], bool]] = None,
                 log: Optional[Callable[[str], None]] = None, lang: str = context_profiles.DEFAULT_LANG,
                 url_reader: Any = None) -> None:
        self.lang = context_profiles.normalize_lang(lang)
        self._tracker = tracker if tracker is not None else ForegroundTracker()
        self._send_shortcut = send_shortcut or keys.send_shortcut
        self._log = log or _log.info
        self._url_reader = url_reader if url_reader is not None else BrowserUrlReader(log=self._log)

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
        return {
            "available": True,
            "app": context_profiles.display_name(app, self.lang, url),
            "profile": profile.id,
            "buttons": self._buttons(profile.pages[0]),
            "pages": [{"id": page.id, "label": page.label(self.lang), "buttons": self._buttons(page)}
                      for page in profile.pages],
        }

    def _buttons(self, page: context_profiles.Page) -> list:
        return [{"id": b.id, "icon": b.icon, "label": b.label(self.lang)} for b in page.buttons]

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
        profile, _ = self._profile(app)
        button = next((b for b in profile.buttons if b.id == button_id), None) if app is not None else None
        if button is None:
            self._log(f"context: button {button_id!r} ignored, it is not in the profile of the app in front "
                      f"({profile.id if app is not None else 'none'})")
            return None
        try:
            sent = self._send_shortcut(button.shortcut)
        except ValueError as e:
            self._log(f"context: shortcut {button.shortcut!r} of {button.id!r} cannot be sent: {e}")
            return ACTION_FAILED
        if not sent:
            self._log(f"context: {button.shortcut!r} was not injected (an elevated app in front?)")
            return ACTION_FAILED
        return None
