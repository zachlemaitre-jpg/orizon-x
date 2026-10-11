"""The DXGI outputs as ffmpeg's ddagrab numbers them: read instantly, without running ffmpeg once per output.

What ddagrab does with output_idx (FFmpeg libavfilter/vsrc_ddagrab.c, init_dxgi_dda): it takes the D3D11 device of
its D3D11VA hardware context, which it creates with no device string when none is given
(av_hwdevice_ctx_create(..., AV_HWDEVICE_TYPE_D3D11VA, NULL, ...)); libavutil/hwcontext_d3d11va.c then calls
D3D11CreateDevice with a NULL adapter and D3D_DRIVER_TYPE_HARDWARE, i.e. DXGI's default adapter, the first one
IDXGIFactory1::EnumAdapters lists. ddagrab gets that device's adapter (IDXGIDevice::GetParent) and calls
IDXGIAdapter::EnumOutputs(adapter, output_idx) with output_idx as is: the raw index among that adapter's outputs,
with no filtering on AttachedToDesktop.

So the ddagrab index of a Windows screen is its EnumOutputs index on adapter #0 here, found by its GDI name
(\\\\.\\DISPLAYn, the DeviceName of DXGI_OUTPUT_DESC and the szDevice of GetMonitorInfo). Caveat: Windows' per-app
graphics preference can make the default adapter differ between this process and ffmpeg.exe; without one (the
default) both see the same order.

Read-only: CreateDXGIFactory1, EnumAdapters1, GetDesc1, EnumOutputs, GetDesc; every COM pointer is released.
"""
from __future__ import annotations

import ctypes
from ctypes import wintypes
from dataclasses import dataclass

from inputstate import Rect

DXGI_ERROR_NOT_FOUND = 0x887A0002
MAX_ADAPTERS = 16
MAX_OUTPUTS = 16

# Rangs dans les vtables (IUnknown 0-2, IDXGIObject 3-6, puis l'interface elle-même)
_RELEASE = 2
_FACTORY1_ENUM_ADAPTERS1 = 12
_ADAPTER_ENUM_OUTPUTS = 7
_ADAPTER1_GET_DESC1 = 10
_OUTPUT_GET_DESC = 7


class DxgiError(OSError):
    """A DXGI call failed (its HRESULT is in `hresult`)."""

    def __init__(self, call: str, hresult: int) -> None:
        super().__init__(f"{call} failed (HRESULT 0x{hresult & 0xFFFFFFFF:08X})")
        self.hresult = hresult & 0xFFFFFFFF


@dataclass(frozen=True)
class Output:
    adapter: int        # rang de la carte dans EnumAdapters1 (0 : celle de ddagrab)
    adapter_name: str
    index: int          # rang de la sortie dans EnumOutputs de sa carte (output_idx de ddagrab sur la carte 0)
    device_name: str    # \\.\DISPLAYn
    rect: Rect          # DesktopCoordinates
    attached: bool      # AttachedToDesktop


def ddagrab_output(gdi_name: str, outputs: list[Output]) -> tuple[int | None, str]:
    """(ddagrab output_idx of the screen named gdi_name, "") or (None, English reason) if ddagrab cannot see it."""
    if not gdi_name:
        return None, "no Windows screen name"
    found = [o for o in outputs if o.device_name.lower() == gdi_name.lower()]
    if not found:
        return None, f"{gdi_name} is not listed by DXGI"
    output = found[0]
    if output.adapter != 0:
        default = next((o.adapter_name for o in outputs if o.adapter == 0), "none")
        return None, (f"{gdi_name} is on adapter #{output.adapter} ({output.adapter_name}), "
                      f"not ddagrab's default adapter ({default})")
    if not output.attached:
        return None, f"{gdi_name} is not attached to the desktop"
    return output.index, ""


# --- appels COM (ctypes) ---

class _GUID(ctypes.Structure):
    _fields_ = [("Data1", wintypes.DWORD), ("Data2", wintypes.WORD), ("Data3", wintypes.WORD),
                ("Data4", wintypes.BYTE * 8)]


def _guid(data1: int, data2: int, data3: int, data4: bytes) -> _GUID:
    return _GUID(data1, data2, data3, (wintypes.BYTE * 8)(*data4))


IID_IDXGIFactory1 = _guid(0x770AAE78, 0xF26F, 0x4DBA, b"\xa8\x29\x25\x3c\x83\xd1\xb3\x87")


class _LUID(ctypes.Structure):
    _fields_ = [("LowPart", wintypes.DWORD), ("HighPart", wintypes.LONG)]


class DXGI_ADAPTER_DESC1(ctypes.Structure):
    _fields_ = [
        ("Description", wintypes.WCHAR * 128),
        ("VendorId", wintypes.UINT),
        ("DeviceId", wintypes.UINT),
        ("SubSysId", wintypes.UINT),
        ("Revision", wintypes.UINT),
        ("DedicatedVideoMemory", ctypes.c_size_t),
        ("DedicatedSystemMemory", ctypes.c_size_t),
        ("SharedSystemMemory", ctypes.c_size_t),
        ("AdapterLuid", _LUID),
        ("Flags", wintypes.UINT),
    ]


class DXGI_OUTPUT_DESC(ctypes.Structure):
    _fields_ = [
        ("DeviceName", wintypes.WCHAR * 32),
        ("DesktopCoordinates", wintypes.RECT),
        ("AttachedToDesktop", wintypes.BOOL),
        ("Rotation", wintypes.UINT),
        ("Monitor", wintypes.HMONITOR),
    ]


def _call(obj: ctypes.c_void_p, slot: int, argtypes: tuple, *args) -> int:
    """Calls vtable method `slot` of COM object `obj`; returns the HRESULT as an unsigned 32-bit value."""
    vtable = ctypes.cast(obj, ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p))).contents
    method = ctypes.WINFUNCTYPE(ctypes.c_long, ctypes.c_void_p, *argtypes)(vtable[slot])
    return method(obj, *args) & 0xFFFFFFFF


def _release(obj: ctypes.c_void_p) -> None:
    if obj:
        vtable = ctypes.cast(obj, ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p))).contents
        ctypes.WINFUNCTYPE(wintypes.ULONG, ctypes.c_void_p)(vtable[_RELEASE])(obj)


def _check(hresult: int, call: str) -> None:
    if hresult & 0x80000000:
        raise DxgiError(call, hresult)


def enumerate_outputs() -> list[Output]:
    """Every output of every DXGI adapter, in enumeration order. Raises DxgiError (an OSError) on failure.

    A new factory each call: a DXGI factory keeps the adapters and outputs it saw when it was created.
    """
    dxgi = ctypes.WinDLL("dxgi")
    create = dxgi.CreateDXGIFactory1
    create.restype = ctypes.c_long
    create.argtypes = [ctypes.POINTER(_GUID), ctypes.POINTER(ctypes.c_void_p)]
    factory = ctypes.c_void_p()
    _check(create(ctypes.byref(IID_IDXGIFactory1), ctypes.byref(factory)) & 0xFFFFFFFF, "CreateDXGIFactory1")
    found: list[Output] = []
    try:
        for a in range(MAX_ADAPTERS):
            adapter = ctypes.c_void_p()
            hresult = _call(factory, _FACTORY1_ENUM_ADAPTERS1, (wintypes.UINT, ctypes.POINTER(ctypes.c_void_p)),
                            a, ctypes.byref(adapter))
            if hresult == DXGI_ERROR_NOT_FOUND:
                break
            _check(hresult, f"EnumAdapters1({a})")
            try:
                found.extend(_adapter_outputs(adapter, a))
            finally:
                _release(adapter)
    finally:
        _release(factory)
    return found


def _adapter_outputs(adapter: ctypes.c_void_p, a: int) -> list[Output]:
    desc = DXGI_ADAPTER_DESC1()
    _check(_call(adapter, _ADAPTER1_GET_DESC1, (ctypes.POINTER(DXGI_ADAPTER_DESC1),), ctypes.byref(desc)),
           f"IDXGIAdapter1::GetDesc1({a})")
    outputs: list[Output] = []
    for o in range(MAX_OUTPUTS):
        output = ctypes.c_void_p()
        hresult = _call(adapter, _ADAPTER_ENUM_OUTPUTS, (wintypes.UINT, ctypes.POINTER(ctypes.c_void_p)),
                        o, ctypes.byref(output))
        if hresult == DXGI_ERROR_NOT_FOUND:
            break
        _check(hresult, f"EnumOutputs({a}, {o})")
        try:
            out = DXGI_OUTPUT_DESC()
            _check(_call(output, _OUTPUT_GET_DESC, (ctypes.POINTER(DXGI_OUTPUT_DESC),), ctypes.byref(out)),
                   f"IDXGIOutput::GetDesc({a}, {o})")
        finally:
            _release(output)
        r = out.DesktopCoordinates
        outputs.append(Output(a, desc.Description, o, out.DeviceName,
                              Rect(r.left, r.top, r.right - r.left, r.bottom - r.top), bool(out.AttachedToDesktop)))
    return outputs
