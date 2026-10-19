"""The PC keyboard of the device (Actions mode, spec 2026-10-19 keyboard §3-§5).

The device shows a full keyboard and sends each key by its physical position, a scan code ("set 1"); Windows applies
its own layout afterwards, so characters, AltGr, shortcuts and games all work.

Snapshot: ``{"available": True, "layout": "azerty" | "qwerty"}``, the layout the device must draw. It is read with
``GetKeyboardLayout`` on the thread of the window in front (the shell's when there is none): primary language 0x0C
(French) except 0x0C0C (French Canadian) is azerty, anything else qwerty.

``handle({"id": "keyboard.key", "sc": 1..127, "ext": bool, "down": bool})`` injects one key with ``SendInput``:
``KEYBDINPUT(wVk=0, wScan=sc, dwFlags=KEYEVENTF_SCANCODE | EXTENDEDKEY if ext | KEYUP if not down)``. The pair
(sc, ext) must be in ``KEY_TABLE`` (the keys of spec §4, nothing else): any other is ignored and logged. The keys that
are down are tracked in press order. ``handle({"id": "keyboard.release"})`` and ``stop()`` lift all of them, in
reverse order, so that no key stays stuck on the PC when the keyboard closes or the session ends; after ``stop()``
no key is injected any more. An injection that fails (a window run as administrator refuses injected keys unless
Orizon X runs as administrator too) is logged once per streak and never an error: key repeat would flood the device
with notices. ``SendInput`` and the layout reader are injectable for the tests. Thread-safe (the hub thread handles
the keys, ``stop()`` may come from another).
"""
from __future__ import annotations

import ctypes
import logging
import threading
from typing import Any, Callable, Optional

from actions import keys

_log = logging.getLogger("orizonx.actions.keyboard")

KEYEVENTF_SCANCODE = 0x0008

KEY_ID = "keyboard.key"
RELEASE_ID = "keyboard.release"

_PLAIN = (
    [0x01, 0x29, 0x0C, 0x0D, 0x0E, 0x0F, 0x1A, 0x1B, 0x1C, 0x3A, 0x27, 0x28, 0x2B, 0x2A, 0x56, 0x33, 0x34, 0x35,
     0x36, 0x1D, 0x38, 0x39, 0x57, 0x58]
    + list(range(0x3B, 0x45))    # F1..F10
    + list(range(0x02, 0x0C))    # 1..0
    + list(range(0x10, 0x1A))    # the second row
    + list(range(0x1E, 0x27))    # the third row
    + list(range(0x2C, 0x33))    # the fourth row
)
_EXTENDED = [0x53, 0x5B, 0x38, 0x5D, 0x1D, 0x52, 0x47, 0x4F, 0x49, 0x51, 0x48, 0x4B, 0x50, 0x4D]
# Del, Win, AltGr / right Alt, Menu, right Ctrl, Ins, Home, End, PgUp, PgDn, Up, Left, Down, Right
KEY_TABLE = frozenset([(sc, False) for sc in _PLAIN] + [(sc, True) for sc in _EXTENDED])


def layout_of_hkl(hkl: int) -> str:
    """"azerty" or "qwerty" for a keyboard layout handle (its low word is the language id)."""
    langid = hkl & 0xFFFF
    if langid == 0x0C0C:
        return "qwerty"  # French Canadian
    return "azerty" if langid & 0x3FF == 0x0C else "qwerty"


def default_layout_reader() -> int:
    """The HKL of the window in front (of the shell's window when there is none)."""
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    user32.GetForegroundWindow.restype = ctypes.c_void_p
    user32.GetShellWindow.restype = ctypes.c_void_p
    user32.GetWindowThreadProcessId.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
    user32.GetWindowThreadProcessId.restype = ctypes.c_uint
    user32.GetKeyboardLayout.argtypes = [ctypes.c_uint]
    user32.GetKeyboardLayout.restype = ctypes.c_void_p
    hwnd = user32.GetForegroundWindow() or user32.GetShellWindow()
    thread = user32.GetWindowThreadProcessId(hwnd, None) if hwnd else 0
    return int(user32.GetKeyboardLayout(thread) or 0)


def _scan_events(pairs: "list[tuple[int, bool, bool]]") -> "ctypes.Array[keys.INPUT]":
    """A SendInput array for (scan code, extended, down) triples: wVk = 0, wScan = the scan code."""
    events = (keys.INPUT * len(pairs))()
    for event, (sc, ext, down) in zip(events, pairs):
        flags = KEYEVENTF_SCANCODE | (keys.KEYEVENTF_EXTENDEDKEY if ext else 0) | (0 if down else keys.KEYEVENTF_KEYUP)
        event.type = keys.INPUT_KEYBOARD
        event.u.ki = keys.KEYBDINPUT(wVk=0, wScan=sc, dwFlags=flags, time=0, dwExtraInfo=0)
    return events


class KeyboardProvider:
    def __init__(self, send_input: Optional[keys.SendInputFn] = None, layout_reader: Optional[Callable[[], int]] = None,
                 log: Optional[Callable[[str], None]] = None) -> None:
        self._send_input = send_input
        self._layout_reader = layout_reader or default_layout_reader
        self._log = log or _log.info
        self._lock = threading.RLock()
        self._held: "list[tuple[int, bool]]" = []  # (sc, ext) in press order
        self._stopped = False
        self._blocked = False  # the last injection failed (logged once per streak)
        self._layout_logged = False

    @property
    def held(self) -> "list[tuple[int, bool]]":
        with self._lock:
            return list(self._held)

    # --- provider API ---

    def snapshot(self) -> dict:
        try:
            layout = layout_of_hkl(self._layout_reader())
        except Exception as e:  # noqa: BLE001 - the keyboard works without knowing the layout
            if not self._layout_logged:
                self._layout_logged = True
                self._log(f"keyboard: layout unreadable ({e!r}), qwerty assumed")
            layout = "qwerty"
        return {"available": True, "layout": layout}

    def handle(self, action: dict) -> Optional[str]:
        action_id = action.get("id")
        if action_id == KEY_ID:
            self._key(action)
        elif action_id == RELEASE_ID:
            self.release_all()
        else:
            self._log(f"keyboard: unknown action {action_id!r}")
        return None

    def stop(self) -> None:
        """Lift every key that is down and refuse the next ones. Safe to call twice."""
        with self._lock:
            self._stopped = True
            self.release_all()

    # --- keys ---

    def _key(self, action: dict) -> None:
        sc, ext, down = action.get("sc"), action.get("ext"), action.get("down")
        if (type(sc) is not int or type(ext) is not bool or type(down) is not bool
                or (sc, ext) not in KEY_TABLE):
            self._log(f"keyboard: key ignored, not a key of the table: sc={sc!r} ext={ext!r} down={down!r}")
            return
        with self._lock:
            if self._stopped:
                return
            pair = (sc, ext)
            if down:
                if self._inject([(sc, ext, True)]) and pair not in self._held:
                    self._held.append(pair)
            elif pair in self._held:
                self._held.remove(pair)
                self._inject([(sc, ext, False)])

    def release_all(self) -> None:
        """Lift all the keys that are down, the last pressed first (one SendInput call)."""
        with self._lock:
            held, self._held = self._held, []
            if held:
                self._inject([(sc, ext, False) for sc, ext in reversed(held)])

    def _inject(self, triples: "list[tuple[int, bool, bool]]") -> bool:
        try:
            events = _scan_events(triples)
            send = self._send_input or keys.default_send_input()
            self._send_input = send
            ok = send(len(events), events, ctypes.sizeof(keys.INPUT)) == len(events)
        except Exception as e:  # noqa: BLE001 - never an error for the hub
            ok = False
            if not self._blocked:
                self._log(f"keyboard: SendInput failed ({e!r})")
                self._blocked = True
            return False
        if not ok and not self._blocked:
            self._log("keyboard: keys were not injected (a window run as administrator in front?)")
        self._blocked = not ok
        return ok
