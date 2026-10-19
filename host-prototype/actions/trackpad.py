"""The device's trackpad as the PC mouse (Actions mode, spec 2026-10-19 trackpad §3-§4).

Section of the state: ``"trackpad": {"available": True}``. Actions (all ``ACTION`` messages), validated first: numbers
must be finite JSON numbers (not bool, not text), ``dx``/``dy`` are clamped to +-2000, ``steps`` is an int clamped to
+-10, unknown button or gesture names and malformed actions are ignored and logged; nothing raises.

* ``trackpad.move {dx, dy}``: a relative ``MOUSEEVENTF_MOVE`` (never ABSOLUTE: Windows applies its pointer speed and
  acceleration as for a real mouse). The decimals are carried over, only whole pixels are sent;
* ``trackpad.button {button: "left"|"right", down}``: LEFTDOWN/LEFTUP or RIGHTDOWN/RIGHTUP. The buttons that are down are
  tracked; an ``up`` of a button that is not down is ignored;
* ``trackpad.scroll {dx, dy}``: the fingers' movement in dp (x to the right, y downwards, as for ``move``), sent as
  ``MOUSEEVENTF_WHEEL`` / ``MOUSEEVENTF_HWHEEL`` (1 dp = UNITS_PER_DP = 4 wheel units, 120 = one notch), remainders
  carried, nothing sent for 0.

  Windows conventions: a POSITIVE ``WHEEL`` is a wheel turned forward, away from the user = scroll UP (the content
  slides down); a POSITIVE ``HWHEEL`` is a tilt to the right = scroll RIGHT (the content slides left). Natural
  scrolling (the content follows the fingers) is therefore: fingers down (dy > 0) -> content down -> WHEEL > 0, i.e.
  ``WHEEL = +dy * 4``; fingers to the right (dx > 0) -> content right -> scroll left -> ``HWHEEL = -dx * 4``. The two
  signs are ``WHEEL_SIGN`` and ``HWHEEL_SIGN`` (flip one to get the traditional direction on that axis);
* ``trackpad.zoom {steps}``: Ctrl down, one ``WHEEL`` of +-120 per step (positive = zoom in), Ctrl up, in one
  SendInput call (Ctrl is lifted by a second call if the first is only partly injected);
* ``trackpad.gesture {name}``: ``task_view`` -> Win+Tab, ``desktop`` -> Win+D, ``app_prev`` -> Alt+Shift+Tab,
  ``app_next`` -> Alt+Tab, through actions.keys;
* ``trackpad.release`` and ``stop()`` lift the buttons that are down (the last pressed first); after ``stop()`` nothing
  is injected any more.

An injection that fails (a window run as administrator refuses injected input unless Orizon X runs as administrator
too) is logged once per streak and is never an error. ``SendInput`` is injectable. Thread-safe.
"""
from __future__ import annotations

import ctypes
import logging
import math
import threading
from typing import Any, Callable, Optional

from actions import keys

_log = logging.getLogger("orizonx.actions.trackpad")

INPUT_MOUSE = 0
MOUSEEVENTF_MOVE = 0x0001
MOUSEEVENTF_LEFTDOWN = 0x0002
MOUSEEVENTF_LEFTUP = 0x0004
MOUSEEVENTF_RIGHTDOWN = 0x0008
MOUSEEVENTF_RIGHTUP = 0x0010
MOUSEEVENTF_WHEEL = 0x0800
MOUSEEVENTF_HWHEEL = 0x1000

WHEEL_DELTA = 120
UNITS_PER_DP = 4
MAX_DELTA = 2000.0
MAX_STEPS = 10
WHEEL_SIGN = 1     # natural scrolling: fingers down (dy > 0) scroll up (WHEEL > 0)
HWHEEL_SIGN = -1   # natural scrolling: fingers right (dx > 0) scroll left (HWHEEL < 0)

_BUTTONS = {"left": (MOUSEEVENTF_LEFTDOWN, MOUSEEVENTF_LEFTUP), "right": (MOUSEEVENTF_RIGHTDOWN, MOUSEEVENTF_RIGHTUP)}
_GESTURES = {"task_view": "Win+Tab", "desktop": "Win+D", "app_prev": "Alt+Shift+Tab", "app_next": "Alt+Tab"}

_Event = "tuple[int, int, int, int]"  # (dx, dy, mouseData, flags)


def _mouse_events(events: "list[tuple[int, int, int, int]]") -> "ctypes.Array[keys.INPUT]":
    array = (keys.INPUT * len(events))()
    for event, (dx, dy, data, flags) in zip(array, events):
        event.type = INPUT_MOUSE
        event.u.mi = keys.MOUSEINPUT(dx=dx, dy=dy, mouseData=data & 0xFFFFFFFF, dwFlags=flags, time=0, dwExtraInfo=0)
    return array


def _number(value: Any) -> Optional[float]:
    """A finite JSON number clamped to +-MAX_DELTA, or None."""
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        return None
    return max(-MAX_DELTA, min(MAX_DELTA, float(value)))


def _whole(value: float) -> int:
    """Nearest integer, halves away from zero (the remainder is carried by the caller)."""
    return int(math.floor(value + 0.5)) if value >= 0 else -int(math.floor(-value + 0.5))


class TrackpadProvider:
    def __init__(self, send_input: Optional[keys.SendInputFn] = None, log: Optional[Callable[[str], None]] = None) -> None:
        self._send_input = send_input
        self._log = log or _log.info
        self._lock = threading.RLock()
        self._held: "list[str]" = []
        self._stopped = False
        self._blocked = False
        self._move_carry = [0.0, 0.0]
        self._scroll_carry = [0.0, 0.0]  # wheel units, vertical then horizontal

    @property
    def held(self) -> "list[str]":
        with self._lock:
            return list(self._held)

    # --- provider API ---

    def snapshot(self) -> dict:
        return {"available": True}

    def handle(self, action: dict) -> Optional[str]:
        name = str(action.get("id", ""))[len("trackpad."):] if str(action.get("id", "")).startswith("trackpad.") else None
        handler = {"move": self._move, "button": self._button, "scroll": self._scroll, "zoom": self._zoom,
                   "gesture": self._gesture, "release": lambda _a: self.release_all()}.get(name)
        if handler is None:
            self._log(f"trackpad: unknown action {action.get('id')!r}")
            return None
        with self._lock:
            if not self._stopped:
                handler(action)
        return None

    def stop(self) -> None:
        """Lift the buttons that are down and refuse everything after. Safe to call twice."""
        with self._lock:
            self._stopped = True
            self.release_all()

    def release_all(self) -> None:
        with self._lock:
            held, self._held = self._held, []
            if held:
                self._inject([(0, 0, 0, _BUTTONS[b][1]) for b in reversed(held)])

    # --- actions ---

    def _refuse(self, what: str, action: dict) -> None:
        self._log(f"trackpad: {what} ignored: {action!r}")

    def _move(self, action: dict) -> None:
        dx, dy = _number(action.get("dx")), _number(action.get("dy"))
        if dx is None or dy is None:
            return self._refuse("move", action)
        out = []
        for i, value in enumerate((dx, dy)):
            total = self._move_carry[i] + value
            whole = int(total)  # toward zero
            self._move_carry[i] = total - whole
            out.append(whole)
        if out[0] or out[1]:
            self._inject([(out[0], out[1], 0, MOUSEEVENTF_MOVE)])

    def _button(self, action: dict) -> None:
        button, down = action.get("button"), action.get("down")
        if not isinstance(button, str) or button not in _BUTTONS or type(down) is not bool:
            return self._refuse("button", action)
        down_flag, up_flag = _BUTTONS[button]
        if down:
            if button not in self._held and self._inject([(0, 0, 0, down_flag)]):
                self._held.append(button)
        elif button in self._held:
            self._held.remove(button)
            self._inject([(0, 0, 0, up_flag)])

    def _scroll(self, action: dict) -> None:
        dx, dy = _number(action.get("dx")), _number(action.get("dy"))
        if dx is None or dy is None:
            return self._refuse("scroll", action)
        events = []
        for i, (value, sign, flag) in enumerate(((dy, WHEEL_SIGN, MOUSEEVENTF_WHEEL),
                                                 (dx, HWHEEL_SIGN, MOUSEEVENTF_HWHEEL))):
            total = self._scroll_carry[i] + sign * value * UNITS_PER_DP
            whole = _whole(total)
            self._scroll_carry[i] = total - whole
            if whole:
                events.append((0, 0, whole, flag))
        if events:
            self._inject(events)

    def _zoom(self, action: dict) -> None:
        steps = action.get("steps")
        if type(steps) is not int:
            return self._refuse("zoom", action)
        steps = max(-MAX_STEPS, min(MAX_STEPS, steps))
        if steps == 0:
            return
        wheel = [(0, 0, WHEEL_DELTA if steps > 0 else -WHEEL_DELTA, MOUSEEVENTF_WHEEL)] * abs(steps)
        ctrl_down = keys.key_events([(keys.VK_CONTROL, 0)])[0]
        ctrl_up = keys.key_events([(keys.VK_CONTROL, keys.KEYEVENTF_KEYUP)])[0]
        mouse = _mouse_events(wheel)
        events = (keys.INPUT * (len(wheel) + 2))()
        events[0], events[-1] = ctrl_down, ctrl_up
        for i, event in enumerate(mouse):
            events[i + 1] = event
        if not self._send(events):
            # Ctrl may be down without its release: lift it on its own
            self._send(keys.key_events([(keys.VK_CONTROL, keys.KEYEVENTF_KEYUP)]))

    def _gesture(self, action: dict) -> None:
        name = action.get("name")
        shortcut = _GESTURES.get(name) if isinstance(name, str) else None
        if shortcut is None:
            return self._refuse("gesture", action)
        try:
            ok = keys.send_shortcut(shortcut, self._send_input)
        except Exception as e:  # noqa: BLE001 - never an error for the hub
            return self._failed(f"{shortcut} failed ({e!r})")
        self._streak(ok)

    # --- injection ---

    def _inject(self, events: "list[tuple[int, int, int, int]]") -> bool:
        return self._send(_mouse_events(events))

    def _send(self, array: "ctypes.Array[keys.INPUT]") -> bool:
        try:
            send = self._send_input or keys.default_send_input()
            self._send_input = send
            ok = send(len(array), array, ctypes.sizeof(keys.INPUT)) == len(array)
        except Exception as e:  # noqa: BLE001
            self._failed(f"SendInput failed ({e!r})")
            return False
        self._streak(ok)
        return ok

    def _failed(self, why: str) -> None:
        if not self._blocked:
            self._log(f"trackpad: {why}")
        self._blocked = True

    def _streak(self, ok: bool) -> None:
        if not ok:
            self._failed("input was not injected (a window run as administrator in front?)")
        else:
            self._blocked = False
