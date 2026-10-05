"""Position, scale and on/off of the virtual screen.

Pure maths (``place``, ``auto_scale``, ``relative_scale_index``, ``pick_mode``) plus a thin layer over
the Windows CCD API (QueryDisplayConfig / SetDisplayConfig / DisplayConfig{Get,Set}DeviceInfo) via
ctypes. Every Windows call goes through an ``api`` object (``Win32DisplayApi`` by default) so tests
inject fakes; the setters are never called for real in tests.

Monitors are identified by ``MonitorKey`` = target adapter LUID + target id (target ids alone are not
unique across adapters). LUIDs change across boots and driver restarts: never persist a key.
See docs/notes/vdd-control.md §5 and §C for the layouts and the DPI semantics.
"""
from __future__ import annotations

import ctypes
import sys
from ctypes import wintypes
from dataclasses import dataclass
from typing import Iterable, Protocol

import inputstate

# ---------- pure maths ----------

Rect = inputstate.Rect   # même type que injector.monitors(), pour comparer les rectangles

SIDES = ("right", "left", "above", "below")
SCALE_STEPS = (100, 125, 150, 175, 200, 225, 250, 300)
# Liste complète des paliers Windows : les valeurs DPI relatives sont des indices dans celle-ci
DPI_VALS = (100, 125, 150, 175, 200, 225, 250, 300, 350, 400, 450, 500)
SAME_ASPECT_TOLERANCE = 0.01


def place(primary: Rect, size: tuple[int, int], side: str) -> tuple[int, int]:
    """Top-left corner of a ``size`` screen glued to ``side`` of ``primary``, centred on that edge."""
    width, height = size
    if side == "right":
        return primary.left + primary.width, primary.top + (primary.height - height) // 2
    if side == "left":
        return primary.left - width, primary.top + (primary.height - height) // 2
    if side == "above":
        return primary.left + (primary.width - width) // 2, primary.top - height
    if side == "below":
        return primary.left + (primary.width - width) // 2, primary.top + primary.height
    raise ValueError(f"Unknown side {side!r}, expected one of: {', '.join(SIDES)}")


def auto_scale(dpi: int) -> int:
    """Windows scale for a tablet of ``dpi``: dpi / 96 x 0.75, down to a step of SCALE_STEPS (100..300).

    Rounded down, not to the nearest step: 274 dpi gives 214 %, and the spec wants 200 % there
    (more room on the tablet). The 0.75 factor accounts for a tablet held closer than a monitor.
    """
    chosen = SCALE_STEPS[0]
    for step in SCALE_STEPS:
        if step * 96 <= dpi * 75:   # step <= dpi / 96 x 0.75 x 100, en entiers
            chosen = step
    return chosen


def relative_scale_index(target: int, recommended: int) -> int:
    """Value Windows wants for a scale: steps from the recommended one in DPI_VALS (may be negative)."""
    for value in (target, recommended):
        if value not in DPI_VALS:
            raise ValueError(f"{value} % is not a Windows scale step {DPI_VALS}")
    return DPI_VALS.index(target) - DPI_VALS.index(recommended)


def pick_mode(available: Iterable[tuple[int, ...]], width: int, height: int) -> tuple[int, int] | None:
    """Best display mode for a ``width`` x ``height`` tablet among ``available`` ((w, h) or (w, h, hz)).

    Exact size; else the largest mode with the same aspect ratio (within 1 %) that fits; else the
    largest mode that fits; else None. "Fits" = not wider and not taller than the tablet.
    """
    modes = {(int(m[0]), int(m[1])) for m in available if m[0] > 0 and m[1] > 0}
    if (width, height) in modes:
        return width, height
    fitting = [m for m in modes if m[0] <= width and m[1] <= height]
    if not fitting or height <= 0:
        return None
    ratio = width / height
    same = [m for m in fitting if abs(m[0] / m[1] - ratio) <= ratio * SAME_ASPECT_TOLERANCE]
    return max(same or fitting, key=lambda m: (m[0] * m[1], m[0]))


# ---------- identities ----------

@dataclass(frozen=True)
class MonitorKey:
    """A monitor of the current boot: target adapter LUID + target id."""
    adapter_low: int
    adapter_high: int
    target_id: int


@dataclass(frozen=True)
class MonitorPath:
    """One CCD path (source -> monitor) as seen by QueryDisplayConfig."""
    key: MonitorKey
    source_adapter: tuple[int, int]   # (LowPart, HighPart)
    source_id: int
    gdi_name: str                     # \\.\DISPLAYn ("" if unknown)
    name: str                         # nom du moniteur (EDID)
    device_path: str
    active: bool
    target_available: bool
    rect: Rect | None                 # None si le chemin est inactif
    is_primary: bool


class DisplayLayoutError(RuntimeError):
    """A display configuration call failed; ``code`` is the Win32 error code when there is one."""

    def __init__(self, message: str, code: int | None = None) -> None:
        super().__init__(message)
        self.code = code


class MonitorNotFoundError(DisplayLayoutError):
    """The monitor is unknown, or not active when the operation needs it active."""


# ---------- ctypes layouts (docs/notes/vdd-control.md §C) ----------

class LUID(ctypes.Structure):
    _fields_ = [("LowPart", wintypes.DWORD), ("HighPart", wintypes.LONG)]


class RATIONAL(ctypes.Structure):
    _fields_ = [("Numerator", ctypes.c_uint32), ("Denominator", ctypes.c_uint32)]


class REGION2D(ctypes.Structure):
    _fields_ = [("cx", ctypes.c_uint32), ("cy", ctypes.c_uint32)]


class PATH_SOURCE_INFO(ctypes.Structure):
    _fields_ = [("adapterId", LUID), ("id", ctypes.c_uint32), ("modeInfoIdx", ctypes.c_uint32),
                ("statusFlags", ctypes.c_uint32)]


class PATH_TARGET_INFO(ctypes.Structure):
    _fields_ = [("adapterId", LUID), ("id", ctypes.c_uint32), ("modeInfoIdx", ctypes.c_uint32),
                ("outputTechnology", ctypes.c_uint32), ("rotation", ctypes.c_uint32),
                ("scaling", ctypes.c_uint32), ("refreshRate", RATIONAL),
                ("scanLineOrdering", ctypes.c_uint32), ("targetAvailable", wintypes.BOOL),
                ("statusFlags", ctypes.c_uint32)]


class PATH_INFO(ctypes.Structure):
    _fields_ = [("sourceInfo", PATH_SOURCE_INFO), ("targetInfo", PATH_TARGET_INFO), ("flags", ctypes.c_uint32)]


class VIDEO_SIGNAL_INFO(ctypes.Structure):
    _fields_ = [("pixelRate", ctypes.c_uint64), ("hSyncFreq", RATIONAL), ("vSyncFreq", RATIONAL),
                ("activeSize", REGION2D), ("totalSize", REGION2D), ("videoStandard", ctypes.c_uint32),
                ("scanLineOrdering", ctypes.c_uint32)]


class SOURCE_MODE(ctypes.Structure):
    _fields_ = [("width", ctypes.c_uint32), ("height", ctypes.c_uint32), ("pixelFormat", ctypes.c_uint32),
                ("position", wintypes.POINTL)]


class DESKTOP_IMAGE_INFO(ctypes.Structure):
    _fields_ = [("PathSourceSize", wintypes.POINTL), ("DesktopImageRegion", wintypes.RECTL),
                ("DesktopImageClip", wintypes.RECTL)]


class MODE_UNION(ctypes.Union):
    _fields_ = [("targetVideoSignalInfo", VIDEO_SIGNAL_INFO), ("sourceMode", SOURCE_MODE),
                ("desktopImageInfo", DESKTOP_IMAGE_INFO)]


class MODE_INFO(ctypes.Structure):
    _anonymous_ = ("u",)
    _fields_ = [("infoType", ctypes.c_uint32), ("id", ctypes.c_uint32), ("adapterId", LUID), ("u", MODE_UNION)]


class DEVICE_INFO_HEADER(ctypes.Structure):
    _fields_ = [("type", ctypes.c_int32), ("size", ctypes.c_uint32), ("adapterId", LUID), ("id", ctypes.c_uint32)]


class SOURCE_DEVICE_NAME(ctypes.Structure):
    _fields_ = [("header", DEVICE_INFO_HEADER), ("viewGdiDeviceName", ctypes.c_wchar * 32)]


class TARGET_DEVICE_NAME(ctypes.Structure):
    _fields_ = [("header", DEVICE_INFO_HEADER), ("flags", ctypes.c_uint32), ("outputTechnology", ctypes.c_uint32),
                ("edidManufactureId", ctypes.c_uint16), ("edidProductCodeId", ctypes.c_uint16),
                ("connectorInstance", ctypes.c_uint32), ("monitorFriendlyDeviceName", ctypes.c_wchar * 64),
                ("monitorDevicePath", ctypes.c_wchar * 128)]


class SOURCE_DPI_SCALE_GET(ctypes.Structure):
    _fields_ = [("header", DEVICE_INFO_HEADER), ("minScaleRel", ctypes.c_int32), ("curScaleRel", ctypes.c_int32),
                ("maxScaleRel", ctypes.c_int32)]


class SOURCE_DPI_SCALE_SET(ctypes.Structure):
    _fields_ = [("header", DEVICE_INFO_HEADER), ("scaleRel", ctypes.c_int32)]


class DEVMODEW(ctypes.Structure):
    """Display variant of DEVMODEW (220 bytes)."""
    _fields_ = [("dmDeviceName", ctypes.c_wchar * 32), ("dmSpecVersion", wintypes.WORD),
                ("dmDriverVersion", wintypes.WORD), ("dmSize", wintypes.WORD), ("dmDriverExtra", wintypes.WORD),
                ("dmFields", wintypes.DWORD), ("dmPosition", wintypes.POINTL),
                ("dmDisplayOrientation", wintypes.DWORD), ("dmDisplayFixedOutput", wintypes.DWORD),
                ("dmColor", ctypes.c_short), ("dmDuplex", ctypes.c_short), ("dmYResolution", ctypes.c_short),
                ("dmTTOption", ctypes.c_short), ("dmCollate", ctypes.c_short), ("dmFormName", ctypes.c_wchar * 32),
                ("dmLogPixels", wintypes.WORD), ("dmBitsPerPel", wintypes.DWORD), ("dmPelsWidth", wintypes.DWORD),
                ("dmPelsHeight", wintypes.DWORD), ("dmDisplayFlags", wintypes.DWORD),
                ("dmDisplayFrequency", wintypes.DWORD), ("dmICMMethod", wintypes.DWORD),
                ("dmICMIntent", wintypes.DWORD), ("dmMediaType", wintypes.DWORD), ("dmDitherType", wintypes.DWORD),
                ("dmReserved1", wintypes.DWORD), ("dmReserved2", wintypes.DWORD),
                ("dmPanningWidth", wintypes.DWORD), ("dmPanningHeight", wintypes.DWORD)]


QDC_ALL_PATHS = 0x1
QDC_ONLY_ACTIVE_PATHS = 0x2
SDC_USE_SUPPLIED_DISPLAY_CONFIG = 0x20
SDC_APPLY = 0x80
SDC_SAVE_TO_DATABASE = 0x200
SDC_ALLOW_CHANGES = 0x400
SDC_FLAGS = SDC_APPLY | SDC_USE_SUPPLIED_DISPLAY_CONFIG | SDC_SAVE_TO_DATABASE | SDC_ALLOW_CHANGES
DISPLAYCONFIG_PATH_ACTIVE = 0x1
DISPLAYCONFIG_PATH_MODE_IDX_INVALID = 0xFFFFFFFF
DISPLAYCONFIG_MODE_INFO_TYPE_SOURCE = 1
DISPLAYCONFIG_MODE_INFO_TYPE_TARGET = 2
DISPLAYCONFIG_PIXELFORMAT_32BPP = 4
DISPLAYCONFIG_DEVICE_INFO_GET_SOURCE_NAME = 1
DISPLAYCONFIG_DEVICE_INFO_GET_TARGET_NAME = 2
DISPLAYCONFIG_DEVICE_INFO_GET_DPI_SCALE = -3   # non documenté
DISPLAYCONFIG_DEVICE_INFO_SET_DPI_SCALE = -4   # non documenté
ERROR_INSUFFICIENT_BUFFER = 122
VDD_DEVICE_TAG = "#MTT1337#"   # dans monitorDevicePath du moniteur VDD


# ---------- the Windows api object ----------

class DisplayApi(Protocol):
    """What the layer needs from Windows; methods return Win32 codes, the layer raises."""

    def query(self, flags: int) -> tuple[int, list[PATH_INFO], list[MODE_INFO]]: ...
    def set_config(self, paths: list[PATH_INFO], modes: list[MODE_INFO], flags: int) -> int: ...
    def get_device_info(self, packet: ctypes.Structure) -> int: ...
    def set_device_info(self, packet: ctypes.Structure) -> int: ...
    def enum_modes(self, gdi_name: str) -> list[tuple[int, int, int]]: ...


class Win32DisplayApi:
    """Real user32 calls. Build it on Windows only."""

    def __init__(self) -> None:
        u = ctypes.WinDLL("user32", use_last_error=True)
        u.GetDisplayConfigBufferSizes.argtypes = [ctypes.c_uint32, ctypes.POINTER(ctypes.c_uint32),
                                                  ctypes.POINTER(ctypes.c_uint32)]
        u.GetDisplayConfigBufferSizes.restype = wintypes.LONG
        u.QueryDisplayConfig.argtypes = [ctypes.c_uint32, ctypes.POINTER(ctypes.c_uint32), ctypes.POINTER(PATH_INFO),
                                         ctypes.POINTER(ctypes.c_uint32), ctypes.POINTER(MODE_INFO), ctypes.c_void_p]
        u.QueryDisplayConfig.restype = wintypes.LONG
        u.SetDisplayConfig.argtypes = [ctypes.c_uint32, ctypes.POINTER(PATH_INFO), ctypes.c_uint32,
                                       ctypes.POINTER(MODE_INFO), ctypes.c_uint32]
        u.SetDisplayConfig.restype = wintypes.LONG
        u.DisplayConfigGetDeviceInfo.argtypes = [ctypes.POINTER(DEVICE_INFO_HEADER)]
        u.DisplayConfigGetDeviceInfo.restype = wintypes.LONG
        u.DisplayConfigSetDeviceInfo.argtypes = [ctypes.POINTER(DEVICE_INFO_HEADER)]
        u.DisplayConfigSetDeviceInfo.restype = wintypes.LONG
        u.EnumDisplaySettingsW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, ctypes.POINTER(DEVMODEW)]
        u.EnumDisplaySettingsW.restype = wintypes.BOOL
        self._u = u

    def query(self, flags: int) -> tuple[int, list[PATH_INFO], list[MODE_INFO]]:
        rc = 0
        for _attempt in range(5):   # 122 = la topologie a changé entre les deux appels
            n_paths, n_modes = ctypes.c_uint32(), ctypes.c_uint32()
            rc = self._u.GetDisplayConfigBufferSizes(flags, ctypes.byref(n_paths), ctypes.byref(n_modes))
            if rc:
                return rc, [], []
            paths = (PATH_INFO * max(n_paths.value, 1))()
            modes = (MODE_INFO * max(n_modes.value, 1))()
            rc = self._u.QueryDisplayConfig(flags, ctypes.byref(n_paths), paths, ctypes.byref(n_modes), modes, None)
            if rc == ERROR_INSUFFICIENT_BUFFER:
                continue
            if rc:
                return rc, [], []
            return (0, [PATH_INFO.from_buffer_copy(paths[i]) for i in range(n_paths.value)],
                    [MODE_INFO.from_buffer_copy(modes[i]) for i in range(n_modes.value)])
        return rc, [], []

    def set_config(self, paths: list[PATH_INFO], modes: list[MODE_INFO], flags: int) -> int:
        path_array = (PATH_INFO * len(paths))(*paths)
        mode_array = (MODE_INFO * len(modes))(*modes)
        return self._u.SetDisplayConfig(len(paths), path_array, len(modes), mode_array, flags)

    def get_device_info(self, packet: ctypes.Structure) -> int:
        return self._u.DisplayConfigGetDeviceInfo(ctypes.byref(packet.header))

    def set_device_info(self, packet: ctypes.Structure) -> int:
        return self._u.DisplayConfigSetDeviceInfo(ctypes.byref(packet.header))

    def enum_modes(self, gdi_name: str) -> list[tuple[int, int, int]]:
        found = []
        mode = DEVMODEW()
        mode.dmSize = ctypes.sizeof(DEVMODEW)
        index = 0
        while index < 10000 and self._u.EnumDisplaySettingsW(gdi_name, index, ctypes.byref(mode)):
            found.append((mode.dmPelsWidth, mode.dmPelsHeight, mode.dmDisplayFrequency))
            index += 1
        return found


_api: DisplayApi | None = None


def _default_api() -> DisplayApi:
    global _api
    if _api is None:
        if sys.platform != "win32":
            raise DisplayLayoutError("Display configuration is only available on Windows")
        _api = Win32DisplayApi()
    return _api


# ---------- helpers ----------

def _copy(item):
    return type(item).from_buffer_copy(item)


def _query(api: DisplayApi, flags: int) -> tuple[list[PATH_INFO], list[MODE_INFO]]:
    rc, paths, modes = api.query(flags)
    if rc:
        raise DisplayLayoutError(f"QueryDisplayConfig failed (Win32 error {rc})", rc)
    return [_copy(p) for p in paths], [_copy(m) for m in modes]


def _apply(api: DisplayApi, paths: list[PATH_INFO], modes: list[MODE_INFO]) -> None:
    rc = api.set_config(paths, modes, SDC_FLAGS)
    if rc:
        raise DisplayLayoutError(f"SetDisplayConfig failed (Win32 error {rc})", rc)


def _key_of(path: PATH_INFO) -> MonitorKey:
    t = path.targetInfo
    return MonitorKey(t.adapterId.LowPart, t.adapterId.HighPart, t.id)


def _packet(cls, kind: int, adapter: LUID, ident: int):
    packet = cls()
    packet.header.type = kind
    packet.header.size = ctypes.sizeof(cls)
    packet.header.adapterId.LowPart = adapter.LowPart
    packet.header.adapterId.HighPart = adapter.HighPart
    packet.header.id = ident
    return packet


def _source_name(api: DisplayApi, path: PATH_INFO) -> str:
    packet = _packet(SOURCE_DEVICE_NAME, DISPLAYCONFIG_DEVICE_INFO_GET_SOURCE_NAME,
                     path.sourceInfo.adapterId, path.sourceInfo.id)
    return packet.viewGdiDeviceName if api.get_device_info(packet) == 0 else ""


def _target_name(api: DisplayApi, path: PATH_INFO) -> tuple[str, str]:
    packet = _packet(TARGET_DEVICE_NAME, DISPLAYCONFIG_DEVICE_INFO_GET_TARGET_NAME,
                     path.targetInfo.adapterId, path.targetInfo.id)
    if api.get_device_info(packet) != 0:
        return "", ""
    return packet.monitorFriendlyDeviceName, packet.monitorDevicePath


def _source_mode_of(path: PATH_INFO, modes: list[MODE_INFO]) -> MODE_INFO | None:
    index = path.sourceInfo.modeInfoIdx
    if index < len(modes) and modes[index].infoType == DISPLAYCONFIG_MODE_INFO_TYPE_SOURCE:
        return modes[index]
    return None


def _describe(api: DisplayApi, path: PATH_INFO, modes: list[MODE_INFO], names: tuple[str, str]) -> MonitorPath:
    active = bool(path.flags & DISPLAYCONFIG_PATH_ACTIVE)
    rect = None
    mode = _source_mode_of(path, modes) if active else None
    if mode is not None:
        sm = mode.sourceMode
        rect = Rect(sm.position.x, sm.position.y, sm.width, sm.height)
    source = path.sourceInfo
    return MonitorPath(
        key=_key_of(path), source_adapter=(source.adapterId.LowPart, source.adapterId.HighPart),
        source_id=source.id, gdi_name=_source_name(api, path), name=names[0], device_path=names[1],
        active=active, target_available=bool(path.targetInfo.targetAvailable), rect=rect,
        is_primary=rect is not None and (rect.left, rect.top) == (0, 0))


def _find(paths: list[PATH_INFO], key: MonitorKey) -> int | None:
    """Index of the path of ``key``, preferring an active one, then an available target."""
    matches = [i for i, p in enumerate(paths) if _key_of(p) == key]
    if not matches:
        return None
    return min(matches, key=lambda i: (not paths[i].flags & DISPLAYCONFIG_PATH_ACTIVE,
                                       not paths[i].targetInfo.targetAvailable))


def _active_path(api: DisplayApi, key: MonitorKey) -> tuple[list[PATH_INFO], list[MODE_INFO], int]:
    paths, modes = _query(api, QDC_ONLY_ACTIVE_PATHS)
    index = _find(paths, key)
    if index is None:
        raise MonitorNotFoundError(f"Monitor {key} is not active")
    return paths, modes, index


def _compact(paths: list[PATH_INFO], modes: list[MODE_INFO]) -> tuple[list[PATH_INFO], list[MODE_INFO]]:
    """Keep only the modes the paths use, renumbering the indices."""
    kept: list[MODE_INFO] = []
    renumber: dict[int, int] = {}
    for path in paths:
        for info in (path.sourceInfo, path.targetInfo):
            old = info.modeInfoIdx
            if old == DISPLAYCONFIG_PATH_MODE_IDX_INVALID or old >= len(modes):
                continue
            if old not in renumber:
                renumber[old] = len(kept)
                kept.append(modes[old])
            info.modeInfoIdx = renumber[old]
    return paths, kept


def _desktop_right_edge(paths: list[PATH_INFO], modes: list[MODE_INFO]) -> int:
    edges = [m.sourceMode.position.x + m.sourceMode.width
             for m in (_source_mode_of(p, modes) for p in paths) if m is not None]
    return max(edges, default=0)


# ---------- read-only ----------

def active_monitors(api: DisplayApi | None = None) -> list[MonitorPath]:
    """Every active path: key, GDI name, rect in physical desktop pixels, primary flag."""
    api = api or _default_api()
    paths, modes = _query(api, QDC_ONLY_ACTIVE_PATHS)
    return [_describe(api, p, modes, _target_name(api, p)) for p in paths]


def is_vdd_device_path(device_path: str) -> bool:
    return VDD_DEVICE_TAG in device_path.upper()


def find_vdd_monitor(api: DisplayApi | None = None) -> MonitorPath | None:
    """The VDD monitor's path (active or not, via QDC_ALL_PATHS), or None if Windows has none."""
    api = api or _default_api()
    paths, modes = _query(api, QDC_ALL_PATHS)
    names: dict[MonitorKey, tuple[str, str]] = {}
    for path in paths:
        key = _key_of(path)
        if key not in names:
            names[key] = _target_name(api, path)
    vdd_keys = [key for key, (_name, device_path) in names.items() if is_vdd_device_path(device_path)]
    if not vdd_keys:
        return None
    best = min((_find(paths, key) for key in vdd_keys),
               key=lambda i: (not paths[i].flags & DISPLAYCONFIG_PATH_ACTIVE, not paths[i].targetInfo.targetAvailable))
    return _describe(api, paths[best], modes, names[_key_of(paths[best])])


def available_modes(key: MonitorKey, api: DisplayApi | None = None) -> list[tuple[int, int]]:
    """Distinct (w, h) the monitor's source offers (EnumDisplaySettingsW), largest first."""
    api = api or _default_api()
    paths, _modes = _query(api, QDC_ALL_PATHS)
    index = _find(paths, key)
    if index is None:
        raise MonitorNotFoundError(f"Monitor {key} not found")
    gdi_name = _source_name(api, paths[index])
    if not gdi_name:
        raise DisplayLayoutError(f"No GDI device name for monitor {key}")
    sizes = {(w, h) for w, h, *_rest in api.enum_modes(gdi_name) if w and h}
    return sorted(sizes, key=lambda s: (s[0] * s[1], s[0]), reverse=True)


def _dpi_packet(api: DisplayApi, path: PATH_INFO) -> SOURCE_DPI_SCALE_GET:
    packet = _packet(SOURCE_DPI_SCALE_GET, DISPLAYCONFIG_DEVICE_INFO_GET_DPI_SCALE,
                     path.sourceInfo.adapterId, path.sourceInfo.id)
    rc = api.get_device_info(packet)
    if rc:
        raise DisplayLayoutError(f"DisplayConfigGetDeviceInfo (DPI scale) failed (Win32 error {rc})", rc)
    return packet


def _dpi_at(index: int) -> int:
    return DPI_VALS[max(0, min(index, len(DPI_VALS) - 1))]


def get_scale(key: MonitorKey, api: DisplayApi | None = None) -> tuple[int, int]:
    """(current %, recommended %) of an active monitor."""
    api = api or _default_api()
    paths, _modes, index = _active_path(api, key)
    packet = _dpi_packet(api, paths[index])
    base = abs(packet.minScaleRel)
    return _dpi_at(base + packet.curScaleRel), _dpi_at(base)


# ---------- mutators (never called for real in tests) ----------

def set_scale(key: MonitorKey, percent: int, api: DisplayApi | None = None) -> int:
    """Set the Windows scale of an active monitor; returns the % applied (clamped to 100..max)."""
    api = api or _default_api()
    paths, _modes, index = _active_path(api, key)
    path = paths[index]
    current = _dpi_packet(api, path)
    base = abs(current.minScaleRel)
    maximum = _dpi_at(base + current.maxScaleRel)
    target = min(DPI_VALS, key=lambda v: (abs(v - percent), v))   # palier le plus proche
    target = max(DPI_VALS[0], min(target, maximum))
    packet = _packet(SOURCE_DPI_SCALE_SET, DISPLAYCONFIG_DEVICE_INFO_SET_DPI_SCALE,
                     path.sourceInfo.adapterId, path.sourceInfo.id)
    packet.scaleRel = relative_scale_index(target, _dpi_at(base))
    rc = api.set_device_info(packet)
    if rc:
        raise DisplayLayoutError(f"DisplayConfigSetDeviceInfo (DPI scale) failed (Win32 error {rc})", rc)
    return target


def set_position(key: MonitorKey, x: int, y: int, api: DisplayApi | None = None) -> None:
    """Move an active monitor's top-left corner to (x, y) in desktop pixels (saved by Windows)."""
    api = api or _default_api()
    paths, modes, index = _active_path(api, key)
    mode = _source_mode_of(paths[index], modes)
    if mode is None:
        raise DisplayLayoutError(f"Monitor {key} has no source mode")
    mode.sourceMode.position.x = x
    mode.sourceMode.position.y = y
    _apply(api, paths, modes)


def set_path_active(key: MonitorKey, active: bool, mode: tuple[int, int] | None = None,
                    position: tuple[int, int] | None = None, api: DisplayApi | None = None) -> bool:
    """Connect or disconnect a monitor's display path, like Settings > Display > "Disconnect this display".

    Activating keeps every other active path. With ``mode`` (w, h) the source gets that size, at
    ``position`` (default: right of the desktop, top 0); without it Windows picks the mode and the
    position it remembers. On an already active path, ``mode``/``position`` change it in place.
    Returns False when there was nothing to do. Windows saves the result (SDC_SAVE_TO_DATABASE).
    """
    if position is not None and mode is None:
        raise ValueError("position needs a mode")
    api = api or _default_api()
    paths, modes = _query(api, QDC_ONLY_ACTIVE_PATHS)
    index = _find(paths, key)

    if not active:
        if index is None:
            return False
        remaining = [p for p in paths if _key_of(p) != key]
        if not remaining:
            raise DisplayLayoutError(f"Refusing to disconnect monitor {key}: it is the only active display")
        _apply(api, *_compact(remaining, modes))
        return True

    if index is not None:
        if mode is None:
            return False
        source = _source_mode_of(paths[index], modes)
        if source is None:
            raise DisplayLayoutError(f"Monitor {key} has no source mode")
        source.sourceMode.width, source.sourceMode.height = mode
        if position is not None:
            source.sourceMode.position.x, source.sourceMode.position.y = position
        paths[index].targetInfo.modeInfoIdx = DISPLAYCONFIG_PATH_MODE_IDX_INVALID   # Windows recalcule
        _apply(api, *_compact(paths, modes))
        return True

    all_paths, _all_modes = _query(api, QDC_ALL_PATHS)
    candidate = _find(all_paths, key)
    if candidate is None:
        raise MonitorNotFoundError(f"Monitor {key} not found")
    path = all_paths[candidate]
    if not path.targetInfo.targetAvailable:
        raise DisplayLayoutError(f"Monitor {key} is not available")
    source_ref = (path.sourceInfo.adapterId.LowPart, path.sourceInfo.adapterId.HighPart, path.sourceInfo.id)
    if any((p.sourceInfo.adapterId.LowPart, p.sourceInfo.adapterId.HighPart, p.sourceInfo.id) == source_ref
           for p in paths):
        raise DisplayLayoutError(f"The source of monitor {key} is already used by another display")
    path.flags |= DISPLAYCONFIG_PATH_ACTIVE
    path.sourceInfo.modeInfoIdx = DISPLAYCONFIG_PATH_MODE_IDX_INVALID
    path.targetInfo.modeInfoIdx = DISPLAYCONFIG_PATH_MODE_IDX_INVALID
    if mode is not None:
        x, y = position if position is not None else (_desktop_right_edge(paths, modes), 0)
        new = MODE_INFO()
        new.infoType = DISPLAYCONFIG_MODE_INFO_TYPE_SOURCE
        new.id = path.sourceInfo.id
        new.adapterId.LowPart = path.sourceInfo.adapterId.LowPart
        new.adapterId.HighPart = path.sourceInfo.adapterId.HighPart
        new.sourceMode.width, new.sourceMode.height = mode
        new.sourceMode.pixelFormat = DISPLAYCONFIG_PIXELFORMAT_32BPP
        new.sourceMode.position.x, new.sourceMode.position.y = x, y
        modes.append(new)
        path.sourceInfo.modeInfoIdx = len(modes) - 1
    _apply(api, paths + [path], modes)
    return True
