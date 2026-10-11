"""Media provider: play/pause, next and previous as synthetic media key presses (SendInput)."""
from __future__ import annotations

import ctypes
import logging
from ctypes import wintypes
from typing import Callable

log = logging.getLogger(__name__)

INPUT_KEYBOARD = 1
KEYEVENTF_KEYUP = 0x0002
VK_MEDIA_NEXT_TRACK = 0xB0
VK_MEDIA_PREV_TRACK = 0xB1
VK_MEDIA_PLAY_PAUSE = 0xB3

_KEYS = {
    "media.play_pause": VK_MEDIA_PLAY_PAUSE,
    "media.next": VK_MEDIA_NEXT_TRACK,
    "media.previous": VK_MEDIA_PREV_TRACK,
}


class MOUSEINPUT(ctypes.Structure):
    _fields_ = [
        ("dx", wintypes.LONG),
        ("dy", wintypes.LONG),
        ("mouseData", wintypes.DWORD),
        ("dwFlags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ctypes.c_size_t),
    ]


class KEYBDINPUT(ctypes.Structure):
    _fields_ = [
        ("wVk", wintypes.WORD),
        ("wScan", wintypes.WORD),
        ("dwFlags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ctypes.c_size_t),
    ]


class HARDWAREINPUT(ctypes.Structure):
    _fields_ = [("uMsg", wintypes.DWORD), ("wParamL", wintypes.WORD), ("wParamH", wintypes.WORD)]


class _INPUT_UNION(ctypes.Union):
    _fields_ = [("mi", MOUSEINPUT), ("ki", KEYBDINPUT), ("hi", HARDWAREINPUT)]


class INPUT(ctypes.Structure):
    _fields_ = [("type", wintypes.DWORD), ("u", _INPUT_UNION)]


SendInputFn = Callable[[int, "ctypes.Array[INPUT]", int], int]


def _default_send_input() -> SendInputFn:
    api = ctypes.WinDLL("user32", use_last_error=True).SendInput
    api.argtypes = [wintypes.UINT, ctypes.POINTER(INPUT), ctypes.c_int]
    api.restype = wintypes.UINT
    return api


def _key_press(vk: int) -> "ctypes.Array[INPUT]":
    events = (INPUT * 2)()
    for event, flags in zip(events, (0, KEYEVENTF_KEYUP)):
        event.type = INPUT_KEYBOARD
        event.u.ki = KEYBDINPUT(wVk=vk, wScan=0, dwFlags=flags, time=0, dwExtraInfo=0)
    return events


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
        send = self._send_input or _default_send_input()
        events = _key_press(vk)
        sent = send(len(events), events, ctypes.sizeof(INPUT))
        if sent != len(events):
            log.warning("media: SendInput injected %d of %d events", sent, len(events))
            return "action_failed"
        return None
