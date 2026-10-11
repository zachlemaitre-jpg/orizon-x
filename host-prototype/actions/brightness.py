"""Brightness provider: laptop panel (WMI) with a DDC/CI fallback.

* WMI (``root\\wmi``): ``WmiMonitorBrightness.CurrentBrightness`` (0..100) and
  ``WmiMonitorBrightnessMethods.WmiSetBrightness(timeout, level)``, reached
  through comtypes ``CoGetObject("winmgmts:root\\wmi")``. Works for internal
  panels only.
* DDC/CI (``dxva2``, VCP feature 0x10 "luminance"): for external monitors.

COM threading: the WMI backend uses COM, so this provider assumes COM is
already initialised in the calling thread (the ActionsHub thread does
``CoInitializeEx``) and that ``snapshot`` / ``handle`` are always called from
that thread. The DDC/CI backend is plain ctypes and has no such constraint.

The snapshot is ``{"available": bool, "value": 0..1}``; ``available`` is False
when neither backend answers. After a failed probe the providers are not
re-probed for ``retry_s`` seconds so an unavailable system is not hammered.
"""

from __future__ import annotations

import ctypes
import logging
import math
import threading
import time
from ctypes import wintypes
from typing import Any, Callable, Optional, Protocol

_log = logging.getLogger("orizonx.actions.brightness")

ACTION_FAILED = "action_failed"
VCP_LUMINANCE = 0x10


class BrightnessBackend(Protocol):
    def read(self) -> Optional[float]:
        """Current brightness 0..1, or None when this backend has no display."""

    def write(self, value: float) -> bool:
        """Set brightness (0..1). True when applied."""


# -- WMI -------------------------------------------------------------------------


class WmiBackend:
    """Internal panel through WMI (``root\\wmi``). Needs an initialised COM thread."""

    def __init__(self, connect: Optional[Callable[[], Any]] = None) -> None:
        self._connect = connect or self._default_connect
        self._services: Any = None

    @staticmethod
    def _default_connect() -> Any:
        import comtypes.client

        return comtypes.client.CoGetObject("winmgmts:root\\wmi", dynamic=True)

    def _wmi(self) -> Any:
        if self._services is None:
            self._services = self._connect()
        return self._services

    def _query(self, class_name: str) -> list:
        try:
            return list(self._wmi().ExecQuery(f"SELECT * FROM {class_name}"))
        except Exception:
            self._services = None  # reconnect next time
            raise

    def read(self) -> Optional[float]:
        for inst in self._query("WmiMonitorBrightness"):
            current = inst.Properties_("CurrentBrightness").Value
            if current is None:
                continue
            return max(0.0, min(1.0, float(current) / 100.0))
        return None

    def write(self, value: float) -> bool:
        level = int(round(max(0.0, min(1.0, value)) * 100))
        applied = False
        for inst in self._query("WmiMonitorBrightnessMethods"):
            inst.WmiSetBrightness(1, level)
            applied = True
        return applied


# -- DDC/CI (dxva2) -----------------------------------------------------------------


class _PHYSICAL_MONITOR(ctypes.Structure):
    _pack_ = 1
    _fields_ = [
        ("hPhysicalMonitor", wintypes.HANDLE),
        ("szPhysicalMonitorDescription", wintypes.WCHAR * 128),
    ]


class DdcBackend:
    """External monitors through DDC/CI (VCP 0x10), using dxva2 via ctypes.

    ``api`` is injectable for tests; it must offer ``physical_monitors()``
    (list of opaque handles), ``get_vcp(handle) -> (current, maximum)``,
    ``set_vcp(handle, value)`` and ``close(handles)``.
    """

    def __init__(self, api: Optional["_Dxva2Api"] = None) -> None:
        self._api = api if api is not None else _Dxva2Api()
        self._handles: list = []

    def _refresh_handles(self) -> list:
        self._release()
        self._handles = list(self._api.physical_monitors())
        return self._handles

    def _release(self) -> None:
        if self._handles:
            try:
                self._api.close(self._handles)
            except Exception:  # pragma: no cover - best effort
                _log.debug("DestroyPhysicalMonitors failed", exc_info=True)
        self._handles = []

    def read(self) -> Optional[float]:
        handles = self._handles or self._refresh_handles()
        for handle in handles:
            try:
                current, maximum = self._api.get_vcp(handle)
            except OSError:
                self._release()  # stale handles: re-enumerate next time
                continue
            if maximum > 0:
                return max(0.0, min(1.0, current / maximum))
        return None

    def write(self, value: float) -> bool:
        handles = self._handles or self._refresh_handles()
        applied = False
        for handle in handles:
            try:
                _current, maximum = self._api.get_vcp(handle)
                if maximum <= 0:
                    continue
                level = int(round(max(0.0, min(1.0, value)) * maximum))
                self._api.set_vcp(handle, level)
                applied = True
            except OSError:
                self._release()
                break
        return applied

    def close(self) -> None:
        self._release()


class _Dxva2Api:
    """Thin ctypes wrapper over user32/dxva2 monitor functions."""

    def __init__(self) -> None:
        self._user32 = ctypes.WinDLL("user32", use_last_error=True)
        self._dxva2 = ctypes.WinDLL("dxva2", use_last_error=True)
        d = self._dxva2
        d.GetNumberOfPhysicalMonitorsFromHMONITOR.argtypes = [
            wintypes.HANDLE,
            ctypes.POINTER(wintypes.DWORD),
        ]
        d.GetNumberOfPhysicalMonitorsFromHMONITOR.restype = wintypes.BOOL
        d.GetPhysicalMonitorsFromHMONITOR.argtypes = [
            wintypes.HANDLE,
            wintypes.DWORD,
            ctypes.POINTER(_PHYSICAL_MONITOR),
        ]
        d.GetPhysicalMonitorsFromHMONITOR.restype = wintypes.BOOL
        d.GetVCPFeatureAndVCPFeatureReply.argtypes = [
            wintypes.HANDLE,
            wintypes.BYTE,
            ctypes.c_void_p,
            ctypes.POINTER(wintypes.DWORD),
            ctypes.POINTER(wintypes.DWORD),
        ]
        d.GetVCPFeatureAndVCPFeatureReply.restype = wintypes.BOOL
        d.SetVCPFeature.argtypes = [wintypes.HANDLE, wintypes.BYTE, wintypes.DWORD]
        d.SetVCPFeature.restype = wintypes.BOOL
        d.DestroyPhysicalMonitors.argtypes = [
            wintypes.DWORD,
            ctypes.POINTER(_PHYSICAL_MONITOR),
        ]
        d.DestroyPhysicalMonitors.restype = wintypes.BOOL
        self._user32.EnumDisplayMonitors.argtypes = [
            wintypes.HDC,
            ctypes.c_void_p,
            ctypes.c_void_p,
            wintypes.LPARAM,
        ]
        self._user32.EnumDisplayMonitors.restype = wintypes.BOOL
        self._owned: dict = {}

    def _hmonitors(self) -> list:
        found: list = []
        proto = ctypes.WINFUNCTYPE(
            wintypes.BOOL,
            wintypes.HANDLE,
            wintypes.HDC,
            ctypes.POINTER(wintypes.RECT),
            wintypes.LPARAM,
        )

        def _cb(hmon, _hdc, _rect, _lparam):
            found.append(hmon)
            return True

        cb = proto(_cb)
        self._user32.EnumDisplayMonitors(None, None, ctypes.cast(cb, ctypes.c_void_p), 0)
        return found

    def physical_monitors(self) -> list:
        """Handles of all DDC-capable physical monitors (int values)."""
        handles: list = []
        for hmon in self._hmonitors():
            count = wintypes.DWORD(0)
            if not self._dxva2.GetNumberOfPhysicalMonitorsFromHMONITOR(
                hmon, ctypes.byref(count)
            ) or count.value == 0:
                continue
            array = (_PHYSICAL_MONITOR * count.value)()
            if not self._dxva2.GetPhysicalMonitorsFromHMONITOR(hmon, count.value, array):
                continue
            for item in array:
                handle = item.hPhysicalMonitor
                handles.append(handle)
                self._owned[handle] = item
        return handles

    def get_vcp(self, handle) -> tuple:
        current = wintypes.DWORD(0)
        maximum = wintypes.DWORD(0)
        ok = self._dxva2.GetVCPFeatureAndVCPFeatureReply(
            handle, VCP_LUMINANCE, None, ctypes.byref(current), ctypes.byref(maximum)
        )
        if not ok:
            raise ctypes.WinError(ctypes.get_last_error())
        return current.value, maximum.value

    def set_vcp(self, handle, value: int) -> None:
        if not self._dxva2.SetVCPFeature(handle, VCP_LUMINANCE, int(value)):
            raise ctypes.WinError(ctypes.get_last_error())

    def close(self, handles) -> None:
        items = [self._owned.pop(h) for h in handles if h in self._owned]
        if items:
            array = (_PHYSICAL_MONITOR * len(items))(*items)
            self._dxva2.DestroyPhysicalMonitors(len(items), array)


# -- Provider ------------------------------------------------------------------------


class BrightnessProvider:
    """Provider for ``brightness.set`` and the ``brightness`` state."""

    def __init__(
        self,
        wmi: Optional[BrightnessBackend] = None,
        ddc: Optional[BrightnessBackend] = None,
        clock: Callable[[], float] = time.monotonic,
        retry_s: float = 10.0,
    ) -> None:
        self._wmi: BrightnessBackend = wmi if wmi is not None else WmiBackend()
        self._ddc: BrightnessBackend = ddc if ddc is not None else DdcBackend()
        self._clock = clock
        self._retry_s = retry_s
        self._lock = threading.Lock()
        self._active: Optional[BrightnessBackend] = None
        self._last_probe_failed_at: Optional[float] = None

    def _read_backend(self, backend: BrightnessBackend) -> Optional[float]:
        try:
            return backend.read()
        except Exception as exc:
            _log.debug("brightness backend %s failed: %r", type(backend).__name__, exc)
            return None

    def _read(self) -> Optional[float]:
        """Read through the active backend, probing WMI then DDC/CI if needed."""
        if self._active is not None:
            value = self._read_backend(self._active)
            if value is not None:
                return value
            self._active = None  # lost: probe again below
        now = self._clock()
        if (
            self._last_probe_failed_at is not None
            and now - self._last_probe_failed_at < self._retry_s
        ):
            return None
        for backend in (self._wmi, self._ddc):
            value = self._read_backend(backend)
            if value is not None:
                self._active = backend
                self._last_probe_failed_at = None
                return value
        self._last_probe_failed_at = now
        return None

    def snapshot(self) -> dict:
        with self._lock:
            value = self._read()
        if value is None:
            return {"available": False}
        return {"available": True, "value": round(value, 2)}

    def handle(self, action: dict) -> Optional[str]:
        if action.get("id") != "brightness.set":
            return ACTION_FAILED
        raw = action.get("value")
        if isinstance(raw, bool) or not isinstance(raw, (int, float)) or not math.isfinite(raw):
            return ACTION_FAILED
        value = max(0.0, min(1.0, float(raw)))
        with self._lock:
            if self._active is None and self._read() is None:
                return ACTION_FAILED
            backend = self._active
            try:
                if backend is not None and backend.write(value):
                    return None
            except Exception as exc:
                _log.warning("brightness.set failed: %r", exc)
                self._active = None
        return ACTION_FAILED
