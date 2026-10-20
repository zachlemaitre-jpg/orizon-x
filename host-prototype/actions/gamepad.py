"""The device as a virtual Xbox 360 controller (Actions mode, spec 2026-10-19 gamepad §4-§5), through the ViGEmBus
driver and ``ViGEmClient.dll``.

Snapshot (the ``gamepad`` section of the state): ``{"available": True}`` when the bus is reachable, else
``{"available": False, "reason": "driver_missing" | "error"}``. ``driver_missing``: the DLL is not found or
``vigem_connect`` answers VIGEM_ERROR_BUS_NOT_FOUND (the driver is not installed); ``error``: anything else. The
connection to the bus is tried once and, if it failed, again every ``RETRY_S`` (30 s); ``gamepad.open`` tries at once.

Actions (all ``ACTION`` messages; none raises, a refused one is logged):

* ``gamepad.open``: connects to the bus if needed and plugs the virtual pad in (idempotent);
* ``gamepad.state {buttons, lt, rt, lx, ly, rx, ry}``: the full report. ``buttons`` is reduced to the known XUSB bits,
  the triggers are digital (any value above 0 is 255, else 0), the axes are clamped to [-32768, 32767] (Y positive
  upwards, as in XInput). Anything that is not an integer-valued JSON number (bool, text, null, NaN...) refuses the
  whole state. Ignored while no pad is open;
* ``gamepad.close``: a neutral report (everything 0), then remove, then free the target. ``stop()`` does the same, then
  disconnects from the bus. Every step is tried even if the previous one failed; nothing raises.

``ViGEmLayer`` is the thin ctypes layer on the DLL, loaded on the first ``connect()`` (never at import), searched in
the application folder (frozen exe), PyInstaller's ``_internal`` folder, then ``host-prototype/vendor``. The layer is
injectable for the tests. Thread-safe.
"""
from __future__ import annotations

import ctypes
import logging
import math
import os
import sys
import threading
import time
from typing import Any, Callable, Optional

_log = logging.getLogger("orizonx.actions.gamepad")

DLL_NAME = "ViGEmClient.dll"
RETRY_S = 30.0

BUTTON_BITS = {
    "DPAD_UP": 0x0001, "DPAD_DOWN": 0x0002, "DPAD_LEFT": 0x0004, "DPAD_RIGHT": 0x0008,
    "START": 0x0010, "BACK": 0x0020, "LEFT_THUMB": 0x0040, "RIGHT_THUMB": 0x0080,
    "LEFT_SHOULDER": 0x0100, "RIGHT_SHOULDER": 0x0200, "GUIDE": 0x0400,
    "A": 0x1000, "B": 0x2000, "X": 0x4000, "Y": 0x8000,
}
BUTTON_MASK = sum(BUTTON_BITS.values())

VIGEM_ERROR_NONE = 0x20000000
VIGEM_ERROR_BUS_NOT_FOUND = 0xE0000001


class GamepadError(Exception):
    """A ViGEm call failed."""


class DriverMissingError(GamepadError):
    """The ViGEmBus driver (or ViGEmClient.dll) is not there."""


class XUSB_REPORT(ctypes.Structure):
    _fields_ = [
        ("wButtons", ctypes.c_uint16),
        ("bLeftTrigger", ctypes.c_uint8),
        ("bRightTrigger", ctypes.c_uint8),
        ("sThumbLX", ctypes.c_int16),
        ("sThumbLY", ctypes.c_int16),
        ("sThumbRX", ctypes.c_int16),
        ("sThumbRY", ctypes.c_int16),
    ]


def check_vigem(code: int) -> None:
    """Raises for a VIGEM_ERROR other than NONE: DriverMissingError for BUS_NOT_FOUND, GamepadError otherwise."""
    code &= 0xFFFFFFFF
    if code == VIGEM_ERROR_NONE:
        return
    if code == VIGEM_ERROR_BUS_NOT_FOUND:
        raise DriverMissingError("ViGEmBus not found (VIGEM_ERROR_BUS_NOT_FOUND)")
    raise GamepadError(f"ViGEm error 0x{code:08X}")


def dll_candidates(frozen: bool, executable: str, meipass: Optional[str], module_dir: str) -> "list[str]":
    """Where to look for ViGEmClient.dll, in order: next to the frozen exe, in PyInstaller's data folder
    (``_internal``), then ``host-prototype/vendor`` (running from the sources)."""
    paths = []
    if frozen:
        paths.append(os.path.join(os.path.dirname(executable), DLL_NAME))
        if meipass:
            paths.append(os.path.join(meipass, DLL_NAME))
    paths.append(os.path.join(os.path.dirname(module_dir), "vendor", DLL_NAME))
    seen: "list[str]" = []
    for p in paths:
        if p not in seen:
            seen.append(p)
    return seen


def default_dll_candidates() -> "list[str]":
    return dll_candidates(bool(getattr(sys, "frozen", False)), sys.executable, getattr(sys, "_MEIPASS", None),
                          os.path.dirname(os.path.abspath(__file__)))


def find_dll(candidates: "list[str]") -> Optional[str]:
    return next((p for p in candidates if os.path.isfile(p)), None)


class ViGEmLayer:
    """The calls of ViGEmClient.dll that the provider needs, with one client and one X360 target."""

    def __init__(self, dll_paths: Optional["list[str]"] = None) -> None:
        self._paths = dll_paths if dll_paths is not None else default_dll_candidates()
        self._dll: Any = None
        self._client: Any = None
        self._target: Any = None

    def _load(self) -> Any:
        if self._dll is None:
            path = find_dll(self._paths)
            if path is None:
                raise DriverMissingError(f"{DLL_NAME} not found (looked in: {'; '.join(self._paths)})")
            dll = ctypes.CDLL(path)
            vp, u32 = ctypes.c_void_p, ctypes.c_uint32
            for name, argtypes, restype in (
                    ("vigem_alloc", [], vp), ("vigem_free", [vp], None),
                    ("vigem_connect", [vp], u32), ("vigem_disconnect", [vp], None),
                    ("vigem_target_x360_alloc", [], vp), ("vigem_target_free", [vp], None),
                    ("vigem_target_add", [vp, vp], u32), ("vigem_target_remove", [vp, vp], u32),
                    ("vigem_target_x360_update", [vp, vp, XUSB_REPORT], u32)):
                function = getattr(dll, name)
                function.argtypes, function.restype = argtypes, restype
            self._dll = dll
        return self._dll

    def connect(self) -> None:
        if self._client is not None:
            return
        dll = self._load()
        client = dll.vigem_alloc()
        if not client:
            raise GamepadError("vigem_alloc failed")
        try:
            check_vigem(dll.vigem_connect(client))
        except BaseException:
            dll.vigem_free(client)
            raise
        self._client = client

    def add_target(self) -> None:
        if self._client is None:
            raise GamepadError("not connected to the bus")
        dll = self._dll
        target = dll.vigem_target_x360_alloc()
        if not target:
            raise GamepadError("vigem_target_x360_alloc failed")
        try:
            check_vigem(dll.vigem_target_add(self._client, target))
        except BaseException:
            dll.vigem_target_free(target)
            raise
        self._target = target

    def update(self, buttons: int, lt: int, rt: int, lx: int, ly: int, rx: int, ry: int) -> None:
        if self._client is None or self._target is None:
            raise GamepadError("no pad plugged in")
        report = XUSB_REPORT(buttons, lt, rt, lx, ly, rx, ry)
        check_vigem(self._dll.vigem_target_x360_update(self._client, self._target, report))

    def remove_target(self) -> None:
        if self._client is not None and self._target is not None:
            check_vigem(self._dll.vigem_target_remove(self._client, self._target))

    def free_target(self) -> None:
        target, self._target = self._target, None
        if target is not None:
            self._dll.vigem_target_free(target)

    def disconnect(self) -> None:
        client, self._client = self._client, None
        if client is not None:
            try:
                self._dll.vigem_disconnect(client)
            finally:
                self._dll.vigem_free(client)


def _axis(value: Any) -> Optional[int]:
    """An integer-valued JSON number as an int (clamped to 16 bits), or None."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    if isinstance(value, float) and (not math.isfinite(value) or value != int(value)):
        return None
    return max(-32768, min(32767, int(value)))


def _plain_int(value: Any) -> Optional[int]:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    if isinstance(value, float) and (not math.isfinite(value) or value != int(value)):
        return None
    return int(value)


class GamepadProvider:
    def __init__(self, layer: Any = None, clock: Callable[[], float] = time.monotonic,
                 log: Optional[Callable[[str], None]] = None) -> None:
        self._layer = layer if layer is not None else ViGEmLayer()
        self._clock = clock
        self._log = log or _log.info
        self._lock = threading.RLock()
        self._connected = False
        self._reason: Optional[str] = None  # why the bus is not available
        self._last_try: Optional[float] = None
        self._open = False
        self._stopped = False
        self._failure_logged = False
        self._update_failing = False

    @property
    def is_open(self) -> bool:
        with self._lock:
            return self._open

    # --- provider API ---

    def snapshot(self) -> dict:
        with self._lock:
            if self._stopped:
                return {"available": False, "reason": "error"}
            if not self._connected and (self._last_try is None or self._clock() - self._last_try >= RETRY_S):
                self._connect()
            if self._connected:
                return {"available": True}
            return {"available": False, "reason": self._reason or "error"}

    def handle(self, action: dict) -> Optional[str]:
        action_id = action.get("id")
        with self._lock:
            if self._stopped:
                return None
            if action_id == "gamepad.open":
                self._do_open()
            elif action_id == "gamepad.state":
                self._do_state(action)
            elif action_id == "gamepad.close":
                self._do_close()
            else:
                self._log(f"gamepad: unknown action {action_id!r}")
        return None

    def stop(self) -> None:
        """Neutral report, remove, free the target, disconnect from the bus. Never raises; safe to call twice."""
        with self._lock:
            if self._stopped:
                return
            self._stopped = True
            self._do_close()
            if self._last_try is not None:  # a connection was tried: the layer drops whatever it holds
                self._connected = False
                self._step("disconnect", self._layer.disconnect)

    # --- internals ---

    def _connect(self) -> bool:
        self._last_try = self._clock()
        try:
            self._layer.connect()
        except DriverMissingError as e:
            self._fail("driver_missing", e)
            return False
        except Exception as e:  # noqa: BLE001 - any other failure is "error", never an exception for the hub
            self._fail("error", e)
            return False
        self._connected = True
        self._reason = None
        self._failure_logged = False
        return True

    def _fail(self, reason: str, error: BaseException) -> None:
        self._connected = False
        if reason != self._reason or not self._failure_logged:
            self._log(f"gamepad: unavailable ({reason}): {error!r}")
            self._failure_logged = True
        self._reason = reason

    def _do_open(self) -> None:
        if self._open:
            return
        if not self._connected and not self._connect():
            return
        try:
            self._layer.add_target()
        except DriverMissingError as e:
            self._fail("driver_missing", e)
            return
        except Exception as e:  # noqa: BLE001
            # Vu sur le PC de l'utilisateur : un ajout refusé une fois (0xE0000007, cible non branchée). On repart
            # d'une connexion neuve au bus et on réessaie une fois avant de déclarer la manette indisponible.
            self._log(f"gamepad: add failed, reconnecting and retrying once: {e!r}")
            self._connected = False
            self._step("disconnect", self._layer.disconnect)
            if not self._connect():
                return
            try:
                self._layer.add_target()
            except Exception as e2:  # noqa: BLE001
                self._fail("driver_missing" if isinstance(e2, DriverMissingError) else "error", e2)
                return
        self._open = True
        self._update_failing = False

    def _do_state(self, action: dict) -> None:
        buttons, lt, rt = _plain_int(action.get("buttons")), _plain_int(action.get("lt")), _plain_int(action.get("rt"))
        axes = [_axis(action.get(k)) for k in ("lx", "ly", "rx", "ry")]
        if buttons is None or lt is None or rt is None or any(a is None for a in axes):
            self._log(f"gamepad: state ignored, invalid field: {action!r}")
            return
        if not self._open:
            return
        try:
            self._layer.update(buttons & BUTTON_MASK, 255 if lt > 0 else 0, 255 if rt > 0 else 0, *axes)
        except Exception as e:  # noqa: BLE001
            if not self._update_failing:
                self._log(f"gamepad: update failed: {e!r}")
            self._update_failing = True
            return
        self._update_failing = False

    def _do_close(self) -> None:
        if not self._open:
            return
        self._open = False
        self._step("neutral report", lambda: self._layer.update(0, 0, 0, 0, 0, 0, 0))
        self._step("remove", self._layer.remove_target)
        self._step("free", self._layer.free_target)

    def _step(self, what: str, call: Callable[[], Any]) -> None:
        try:
            call()
        except Exception as e:  # noqa: BLE001 - every step is tried, nothing propagates
            self._log(f"gamepad: {what} failed: {e!r}")
