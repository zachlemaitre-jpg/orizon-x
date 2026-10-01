"""Windows pointer injection for TABX INPUT frames (spec phase 4 §5.3): synthetic touch and pen devices.

`py injector.py --selftest` checks the Win32 layer without a tablet: the pen hovers in a circle (never clicks).
"""
from __future__ import annotations

import ctypes
import math
import sys
import threading
import time
from ctypes import wintypes
from typing import Callable

import inputstate
import protocol

PT_TOUCH = 2
PT_PEN = 3
POINTER_FEEDBACK_DEFAULT = 1
DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2 = -4
MONITORINFOF_PRIMARY = 1
ERROR_ACCESS_DENIED = 5
KEEPALIVE_S = 0.1

Log = Callable[[str], None]
Monitor = tuple[inputstate.Rect, bool, str]


class POINTER_INFO(ctypes.Structure):
    _fields_ = [
        ("pointerType", wintypes.DWORD),
        ("pointerId", ctypes.c_uint32),
        ("frameId", ctypes.c_uint32),
        ("pointerFlags", ctypes.c_uint32),
        ("sourceDevice", wintypes.HANDLE),
        ("hwndTarget", wintypes.HWND),
        ("ptPixelLocation", wintypes.POINT),
        ("ptHimetricLocation", wintypes.POINT),
        ("ptPixelLocationRaw", wintypes.POINT),
        ("ptHimetricLocationRaw", wintypes.POINT),
        ("dwTime", wintypes.DWORD),
        ("historyCount", ctypes.c_uint32),
        ("InputData", ctypes.c_int32),
        ("dwKeyStates", wintypes.DWORD),
        ("PerformanceCount", ctypes.c_uint64),
        ("ButtonChangeType", ctypes.c_int),
    ]


class POINTER_TOUCH_INFO(ctypes.Structure):
    _fields_ = [
        ("pointerInfo", POINTER_INFO),
        ("touchFlags", ctypes.c_uint32),
        ("touchMask", ctypes.c_uint32),
        ("rcContact", wintypes.RECT),
        ("rcContactRaw", wintypes.RECT),
        ("orientation", ctypes.c_uint32),
        ("pressure", ctypes.c_uint32),
    ]


class POINTER_PEN_INFO(ctypes.Structure):
    _fields_ = [
        ("pointerInfo", POINTER_INFO),
        ("penFlags", ctypes.c_uint32),
        ("penMask", ctypes.c_uint32),
        ("pressure", ctypes.c_uint32),
        ("rotation", ctypes.c_uint32),
        ("tiltX", ctypes.c_int32),
        ("tiltY", ctypes.c_int32),
    ]


class _POINTER_INFO_UNION(ctypes.Union):
    _fields_ = [("touchInfo", POINTER_TOUCH_INFO), ("penInfo", POINTER_PEN_INFO)]


class POINTER_TYPE_INFO(ctypes.Structure):
    _anonymous_ = ("u",)
    _fields_ = [("type", wintypes.DWORD), ("u", _POINTER_INFO_UNION)]


class MONITORINFOEXW(ctypes.Structure):
    _fields_ = [
        ("cbSize", wintypes.DWORD),
        ("rcMonitor", wintypes.RECT),
        ("rcWork", wintypes.RECT),
        ("dwFlags", wintypes.DWORD),
        ("szDevice", wintypes.WCHAR * 32),
    ]


_MONITORENUMPROC = ctypes.WINFUNCTYPE(
    wintypes.BOOL, wintypes.HMONITOR, wintypes.HDC, ctypes.POINTER(wintypes.RECT), wintypes.LPARAM
)

_user32 = ctypes.WinDLL("user32", use_last_error=True)
_user32.EnumDisplayMonitors.argtypes = [wintypes.HDC, ctypes.c_void_p, _MONITORENUMPROC, wintypes.LPARAM]
_user32.EnumDisplayMonitors.restype = wintypes.BOOL
_user32.GetMonitorInfoW.argtypes = [wintypes.HMONITOR, ctypes.POINTER(MONITORINFOEXW)]
_user32.GetMonitorInfoW.restype = wintypes.BOOL

try:  # API Synthetic Pointer : Windows 10 1809+
    _create_device = _user32.CreateSyntheticPointerDevice
    _create_device.argtypes = [wintypes.DWORD, wintypes.ULONG, wintypes.DWORD]
    _create_device.restype = wintypes.HANDLE
    _inject = _user32.InjectSyntheticPointerInput
    _inject.argtypes = [wintypes.HANDLE, ctypes.POINTER(POINTER_TYPE_INFO), ctypes.c_uint32]
    _inject.restype = wintypes.BOOL
    _destroy_device = _user32.DestroySyntheticPointerDevice
    _destroy_device.argtypes = [wintypes.HANDLE]
    _destroy_device.restype = None
    AVAILABLE = True
except AttributeError:
    AVAILABLE = False


def enable_dpi_awareness() -> None:
    """Physical pixels everywhere (the virtual screen is scaled 200 %). Call before any monitor query."""
    try:
        set_context = _user32.SetProcessDpiAwarenessContext
    except AttributeError:
        return
    set_context.argtypes = [ctypes.c_void_p]
    set_context.restype = wintypes.BOOL
    set_context(ctypes.c_void_p(DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2))


def monitors() -> list[Monitor]:
    """(rect in physical pixels, is_primary, device name) for every active monitor."""
    found: list[Monitor] = []

    def callback(hmonitor, _hdc, _rect, _data):
        info = MONITORINFOEXW()
        info.cbSize = ctypes.sizeof(MONITORINFOEXW)
        if _user32.GetMonitorInfoW(hmonitor, ctypes.byref(info)):
            r = info.rcMonitor
            rect = inputstate.Rect(r.left, r.top, r.right - r.left, r.bottom - r.top)
            found.append((rect, bool(info.dwFlags & MONITORINFOF_PRIMARY), info.szDevice))
        return True

    _user32.EnumDisplayMonitors(None, None, _MONITORENUMPROC(callback), 0)
    return found


def find_target(width: int, height: int, available: list[Monitor] | None = None) -> tuple[inputstate.Rect | None, str]:
    """The only monitor whose size equals the stream's, or (None, reason)."""
    candidates = monitors() if available is None else available
    matches = [rect for rect, _primary, _name in candidates if (rect.width, rect.height) == (width, height)]
    if len(matches) == 1:
        return matches[0], ""
    if not matches:
        return None, f"aucun écran Windows en {width}x{height}"
    return None, f"{len(matches)} écrans en {width}x{height} : impossible de savoir lequel est la tablette"


def _to_native(device: int, action: inputstate.PointerAction) -> POINTER_TYPE_INFO:
    info = POINTER_TYPE_INFO()
    if device == protocol.DEVICE_TOUCH:
        info.type = PT_TOUCH
        pointer = info.touchInfo.pointerInfo
        pointer.pointerType = PT_TOUCH
    else:
        info.type = PT_PEN
        pen = info.penInfo
        pen.penFlags = action.pen_flags
        pen.penMask = action.pen_mask
        pen.pressure = action.pressure
        pen.tiltX = action.tilt_x
        pen.tiltY = action.tilt_y
        pointer = pen.pointerInfo
        pointer.pointerType = PT_PEN
    pointer.pointerId = action.pointer_id
    pointer.pointerFlags = action.flags
    pointer.ptPixelLocation.x = action.x
    pointer.ptPixelLocation.y = action.y
    return info


class Injector:
    """Injects TABX INPUT frames into one screen. Thread-safe; turns itself off (one message) on fatal errors."""

    def __init__(self, rect: inputstate.Rect, log: Log = print) -> None:
        self._rect = rect
        self._log = log
        self._lock = threading.Lock()
        self._states = {
            protocol.DEVICE_TOUCH: inputstate.DeviceState(protocol.DEVICE_TOUCH),
            protocol.DEVICE_PEN: inputstate.DeviceState(protocol.DEVICE_PEN),
        }
        self._handles: dict[int, int] = {}
        self._disabled = False
        self._denied_reported = False
        self._last_inject = time.monotonic()
        self._stop = threading.Event()
        if not AVAILABLE:
            self._disable("Windows 10 1809 ou plus récent requis (API Synthetic Pointer absente)")
        threading.Thread(target=self._keepalive, name="input-keepalive", daemon=True).start()

    @property
    def enabled(self) -> bool:
        return not self._disabled

    def handle(self, message: protocol.Input) -> None:
        with self._lock:
            if self._disabled:
                return
            self._inject_frame(message.device, self._states[message.device].update(message.contacts, self._rect))

    def close(self) -> None:
        """Cancels every active pointer (no stuck touch) and destroys the synthetic devices."""
        self._stop.set()
        with self._lock:
            if not self._disabled:
                for device, state in self._states.items():
                    self._inject_frame(device, state.cancel_all())
            for handle in self._handles.values():
                _destroy_device(handle)
            self._handles.clear()
            self._disabled = True

    def _keepalive(self) -> None:
        # Un contact immobile n'envoie plus de trame : on réinjecte l'état pour que Windows ne l'abandonne pas.
        while not self._stop.wait(KEEPALIVE_S):
            with self._lock:
                if self._disabled or time.monotonic() - self._last_inject < KEEPALIVE_S:
                    continue
                for device, state in self._states.items():
                    self._inject_frame(device, state.refresh())

    def _inject_frame(self, device: int, frame: list[inputstate.PointerAction]) -> None:
        if not frame or self._disabled:
            return
        handle = self._device_handle(device)
        if handle is None:
            return
        infos = (POINTER_TYPE_INFO * len(frame))(*(_to_native(device, action) for action in frame))
        self._last_inject = time.monotonic()
        if _inject(handle, infos, len(frame)):
            return
        error = ctypes.get_last_error()
        if error == ERROR_ACCESS_DENIED:
            if not self._denied_reported:
                self._log("Tactile refusé par Windows sur cette fenêtre (programme administrateur ?) : "
                          "lance le relais en administrateur pour la piloter.")
                self._denied_reported = True
        else:
            self._disable(f"InjectSyntheticPointerInput a échoué (erreur Windows {error})")

    def _device_handle(self, device: int) -> int | None:
        handle = self._handles.get(device)
        if handle:
            return handle
        if device == protocol.DEVICE_TOUCH:
            handle = _create_device(PT_TOUCH, protocol.MAX_TOUCH_CONTACTS, POINTER_FEEDBACK_DEFAULT)
        else:
            handle = _create_device(PT_PEN, 1, POINTER_FEEDBACK_DEFAULT)
        if not handle:
            self._disable(f"CreateSyntheticPointerDevice a échoué (erreur Windows {ctypes.get_last_error()})")
            return None
        self._handles[device] = handle
        return handle

    def _disable(self, reason: str) -> None:
        self._disabled = True
        self._log(f"Tactile désactivé : {reason}. La vidéo continue.")


def create_for_stream(width: int, height: int, log: Log = print) -> Injector | None:
    """Injector targeting the screen that has the stream's size, or None (with a message) if there isn't exactly one."""
    rect, problem = find_target(width, height)
    if rect is None:
        log(f"Tactile désactivé : {problem}. La vidéo continue.")
        return None
    log(f"Tactile actif sur l'écran Windows {rect.width}x{rect.height} en ({rect.left}, {rect.top})")
    return Injector(rect, log)


def selftest() -> None:
    """Hovers the pen in a circle at the centre of the primary screen for 2 s. Never touches, so never clicks."""
    enable_dpi_awareness()
    primary = next((rect for rect, is_primary, _name in monitors() if is_primary), None)
    if primary is None:
        sys.exit("Autotest : aucun écran principal trouvé")
    pen = Injector(primary)
    for step in range(61):
        angle = 2 * math.pi * step / 60
        x = round(32768 + 8000 * math.cos(angle))
        y = round(32768 + 8000 * math.sin(angle))
        pen.handle(protocol.Input(protocol.DEVICE_PEN, (protocol.Contact(0, protocol.CONTACT_IN_RANGE, x, y, 0, 0, 0),)))
        time.sleep(2 / 60)
    pen.handle(protocol.Input(protocol.DEVICE_PEN, ()))
    ok = pen.enabled
    pen.close()
    if not ok:
        sys.exit("Autotest en échec : voir le message ci-dessus.")
    print("Autotest terminé : le curseur du stylet a dû décrire un cercle au centre de l'écran principal, sans cliquer.")


if __name__ == "__main__":
    if sys.argv[1:] == ["--selftest"]:
        selftest()
    else:
        sys.exit("Usage : py injector.py --selftest")
