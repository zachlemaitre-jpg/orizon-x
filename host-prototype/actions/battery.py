"""Battery provider: GetSystemPowerStatus (kernel32)."""
from __future__ import annotations

import ctypes
from ctypes import wintypes
from typing import Callable

from actions.base import ProviderError

BATTERY_FLAG_CHARGING = 8
BATTERY_FLAG_NO_BATTERY = 128
PERCENT_UNKNOWN = 255


class SYSTEM_POWER_STATUS(ctypes.Structure):
    _fields_ = [
        ("ACLineStatus", ctypes.c_ubyte),
        ("BatteryFlag", ctypes.c_ubyte),
        ("BatteryLifePercent", ctypes.c_ubyte),
        ("SystemStatusFlag", ctypes.c_ubyte),
        ("BatteryLifeTime", wintypes.DWORD),
        ("BatteryFullLifeTime", wintypes.DWORD),
    ]


def _default_api() -> Callable:
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    api = kernel32.GetSystemPowerStatus
    api.argtypes = [ctypes.POINTER(SYSTEM_POWER_STATUS)]
    api.restype = wintypes.BOOL
    return api


def read_power_status(api: Callable | None = None) -> SYSTEM_POWER_STATUS:
    """Calls GetSystemPowerStatus (or the injected stand-in); ProviderError if it fails."""
    status = SYSTEM_POWER_STATUS()
    if not (api or _default_api())(ctypes.byref(status)):
        raise ProviderError("GetSystemPowerStatus failed")
    return status


class BatteryProvider:
    def __init__(self, read: Callable[[], SYSTEM_POWER_STATUS] = read_power_status):
        self._read = read

    def snapshot(self) -> dict:
        status = self._read()
        if status.BatteryFlag & BATTERY_FLAG_NO_BATTERY or status.BatteryLifePercent == PERCENT_UNKNOWN:
            return {"available": False}
        return {
            "available": True,
            "percent": min(int(status.BatteryLifePercent), 100),
            "charging": bool(status.BatteryFlag & BATTERY_FLAG_CHARGING),
        }

    def handle(self, action: dict) -> str | None:
        return None
