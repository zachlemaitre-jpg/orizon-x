"""Windows 11 frosted glass (DWM Acrylic backdrop) for a frameless Qt window."""
from __future__ import annotations

import ctypes
import sys
from ctypes import wintypes

DWMWA_USE_IMMERSIVE_DARK_MODE = 20
DWMWA_WINDOW_CORNER_PREFERENCE = 33
DWMWA_SYSTEMBACKDROP_TYPE = 38
DWMSBT_TRANSIENTWINDOW = 3  # Acrylic
DWMWCP_ROUND = 2
MIN_BUILD = 22621  # Windows 11 22H2 : premier build avec DWMWA_SYSTEMBACKDROP_TYPE


class MARGINS(ctypes.Structure):
    _fields_ = [("cxLeftWidth", ctypes.c_int), ("cxRightWidth", ctypes.c_int),
                ("cyTopHeight", ctypes.c_int), ("cyBottomHeight", ctypes.c_int)]


def _set_attribute(dwmapi, hwnd: int, attribute: int, value: int) -> bool:
    data = ctypes.c_int(value)
    return dwmapi.DwmSetWindowAttribute(wintypes.HWND(hwnd), attribute, ctypes.byref(data), ctypes.sizeof(data)) == 0


def apply_glass(hwnd: int) -> bool:
    """True when the Acrylic backdrop is on; False means the window must paint its own glass."""
    if sys.platform != "win32" or sys.getwindowsversion().build < MIN_BUILD:
        return False
    try:
        dwmapi = ctypes.WinDLL("dwmapi")
    except OSError:
        return False
    _set_attribute(dwmapi, hwnd, DWMWA_USE_IMMERSIVE_DARK_MODE, 1)
    _set_attribute(dwmapi, hwnd, DWMWA_WINDOW_CORNER_PREFERENCE, DWMWCP_ROUND)
    margins = MARGINS(-1, -1, -1, -1)
    if dwmapi.DwmExtendFrameIntoClientArea(wintypes.HWND(hwnd), ctypes.byref(margins)) != 0:
        return False
    return _set_attribute(dwmapi, hwnd, DWMWA_SYSTEMBACKDROP_TYPE, DWMSBT_TRANSIENTWINDOW)
