"""The context bar's provider (spec 2026-10-13 §3): the profile of the app in front on the PC, and its buttons.

Snapshot: ``{"available": True, "app": <name>, "profile": <profile id>, "buttons": [{"id", "icon", "label"}]}``
(the shortcuts stay on the PC), or ``{"available": False}`` while no app has been in front yet.

``handle({"id": "context.press", "button": <id>})`` looks at the app in front NOW, and presses the shortcut of the
button only if that button belongs to its profile: when the foreground changed since the device drew its bar, the
action is ignored (and logged), never sent to the wrong app. A shortcut that cannot be injected (blocked by UIPI in
front of an elevated app, a key the layout lacks) is ``action_failed``. Hub thread only.
"""
from __future__ import annotations

import logging
from typing import Any, Callable, Optional

from actions import context_profiles, keys
from actions.foreground import ForegroundTracker

_log = logging.getLogger("orizonx.actions.context")

PRESS_ID = "context.press"
ACTION_FAILED = "action_failed"


class ContextProvider:
    def __init__(self, tracker: Any = None, send_shortcut: Optional[Callable[[str], bool]] = None,
                 log: Optional[Callable[[str], None]] = None) -> None:
        self._tracker = tracker if tracker is not None else ForegroundTracker()
        self._send_shortcut = send_shortcut or keys.send_shortcut
        self._log = log or _log.info

    def snapshot(self) -> dict:
        app = self._tracker.current()
        if app is None:
            return {"available": False}
        profile = context_profiles.match(app)
        return {
            "available": True,
            "app": context_profiles.display_name(app),
            "profile": profile.id,
            "buttons": [{"id": b.id, "icon": b.icon, "label": b.label} for b in profile.buttons],
        }

    def handle(self, action: dict) -> Optional[str]:
        if action.get("id") != PRESS_ID:
            self._log(f"context: unknown action {action.get('id')!r}")
            return ACTION_FAILED
        button_id = action.get("button")
        app = self._tracker.current()
        profile = context_profiles.match(app)
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
