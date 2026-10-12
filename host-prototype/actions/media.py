"""Media provider: play/pause, next and previous as synthetic media key presses (SendInput)."""
from __future__ import annotations

import ctypes
import logging

from actions.keys import (  # noqa: F401 - INPUT_KEYBOARD / KEYBDINPUT stay importable from here
    INPUT, INPUT_KEYBOARD, KEYBDINPUT, KEYEVENTF_KEYUP, SendInputFn, default_send_input, key_events)

log = logging.getLogger(__name__)

VK_MEDIA_NEXT_TRACK = 0xB0
VK_MEDIA_PREV_TRACK = 0xB1
VK_MEDIA_PLAY_PAUSE = 0xB3

_KEYS = {
    "media.play_pause": VK_MEDIA_PLAY_PAUSE,
    "media.next": VK_MEDIA_NEXT_TRACK,
    "media.previous": VK_MEDIA_PREV_TRACK,
}


def _key_press(vk: int) -> "ctypes.Array[INPUT]":
    return key_events([(vk, 0), (vk, KEYEVENTF_KEYUP)])


class MediaProvider:
    def __init__(self, send_input: SendInputFn | None = None):
        self._send_input = send_input

    def snapshot(self) -> dict:
        return {"available": True}

    def handle(self, action: dict) -> str | None:
        vk = _KEYS.get(action.get("id"))
        if vk is None:
            log.warning("media: unknown action %r", action.get("id"))
            return "action_failed"
        send = self._send_input or default_send_input()
        events = _key_press(vk)
        sent = send(len(events), events, ctypes.sizeof(INPUT))
        if sent != len(events):
            log.warning("media: SendInput injected %d of %d events", sent, len(events))
            return "action_failed"
        return None
