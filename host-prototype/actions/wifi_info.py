"""Wi-Fi SSID provider (spec Actions mode §3 `wifi_info`): the SSID of the connected wireless interface.

wlanapi.dll through ctypes: WlanOpenHandle, WlanEnumInterfaces, then WlanQueryInterface
(wlan_intf_opcode_current_connection) on each interface whose state is connected; the first SSID wins, "" when
none is connected. Read-only; the handle is closed and every WLAN buffer freed on each snapshot.

Snapshot: ``{"available": True, "ssid": str}``; ``{"available": False}`` without wlanapi.dll or when the WLAN
AutoConfig service is not running (no Wi-Fi). Windows 11 24H2+ refuses the SSID (ERROR_ACCESS_DENIED) to apps that
lack location permission: the SSID is then "". This provider has no action; the hub merges it with the radios
provider (see actions.radios.merge_radio_state).
"""
from __future__ import annotations

import ctypes
import logging
import sys
from ctypes import wintypes
from typing import Any, Optional, Protocol

from actions.base import ProviderError

_log = logging.getLogger("orizonx.actions.wifi_info")

ERROR_SUCCESS = 0
ERROR_ACCESS_DENIED = 5
ERROR_SERVICE_NOT_ACTIVE = 1062
WLAN_CLIENT_VERSION_2 = 2                  # Vista and later
WLAN_INTERFACE_STATE_CONNECTED = 1         # wlan_interface_state_connected
WLAN_INTF_OPCODE_CURRENT_CONNECTION = 7    # wlan_intf_opcode_current_connection
DOT11_SSID_MAX_LENGTH = 32


class WlanError(ProviderError):
    """A wlanapi call returned an error (Win32 code in `code`)."""

    def __init__(self, call: str, code: int) -> None:
        super().__init__(f"{call} failed (error {code})")
        self.code = code


# --- structures (wlanapi.h, windot11.h) ---

class GUID(ctypes.Structure):
    _fields_ = [("Data1", wintypes.DWORD), ("Data2", wintypes.WORD), ("Data3", wintypes.WORD),
                ("Data4", ctypes.c_ubyte * 8)]

    def __str__(self) -> str:
        d4 = bytes(self.Data4)
        return (f"{{{self.Data1:08x}-{self.Data2:04x}-{self.Data3:04x}-{d4[:2].hex()}-{d4[2:].hex()}}}")


class WLAN_INTERFACE_INFO(ctypes.Structure):
    _fields_ = [("InterfaceGuid", GUID), ("strInterfaceDescription", wintypes.WCHAR * 256),
                ("isState", wintypes.DWORD)]


class WLAN_INTERFACE_INFO_LIST(ctypes.Structure):
    _fields_ = [("dwNumberOfItems", wintypes.DWORD), ("dwIndex", wintypes.DWORD),
                ("InterfaceInfo", WLAN_INTERFACE_INFO * 1)]


class DOT11_SSID(ctypes.Structure):
    _fields_ = [("uSSIDLength", wintypes.ULONG), ("ucSSID", ctypes.c_ubyte * DOT11_SSID_MAX_LENGTH)]


class WLAN_ASSOCIATION_ATTRIBUTES(ctypes.Structure):
    _fields_ = [("dot11Ssid", DOT11_SSID), ("dot11BssType", wintypes.DWORD),
                ("dot11Bssid", ctypes.c_ubyte * 6), ("dot11PhyType", wintypes.DWORD),
                ("uDot11PhyIndex", wintypes.ULONG), ("wlanSignalQuality", wintypes.ULONG),
                ("ulRxRate", wintypes.ULONG), ("ulTxRate", wintypes.ULONG)]


class WLAN_SECURITY_ATTRIBUTES(ctypes.Structure):
    _fields_ = [("bSecurityEnabled", wintypes.BOOL), ("bOneXEnabled", wintypes.BOOL),
                ("dot11AuthAlgorithm", wintypes.DWORD), ("dot11CipherAlgorithm", wintypes.DWORD)]


class WLAN_CONNECTION_ATTRIBUTES(ctypes.Structure):
    _fields_ = [("isState", wintypes.DWORD), ("wlanConnectionMode", wintypes.DWORD),
                ("strProfileName", wintypes.WCHAR * 256),
                ("wlanAssociationAttributes", WLAN_ASSOCIATION_ATTRIBUTES),
                ("wlanSecurityAttributes", WLAN_SECURITY_ATTRIBUTES)]


def ssid_bytes(attrs: WLAN_CONNECTION_ATTRIBUTES) -> bytes:
    """The raw SSID of a WLAN_CONNECTION_ATTRIBUTES (its length clamped to 32)."""
    ssid = attrs.wlanAssociationAttributes.dot11Ssid
    return bytes(ssid.ucSSID[:min(int(ssid.uSSIDLength), DOT11_SSID_MAX_LENGTH)])


# --- couche wlanapi (injectable) ---

class WlanLayer(Protocol):
    def open(self) -> Any:
        """A WLAN client handle; WlanError on failure."""

    def enum_interfaces(self, handle: Any) -> list[tuple[Any, int]]:
        """[(interface GUID, WLAN_INTERFACE_STATE)]."""

    def current_ssid(self, handle: Any, guid: Any) -> bytes:
        """Raw SSID of the interface's current connection; WlanError on failure."""

    def close(self, handle: Any) -> None: ...


class CtypesWlan:
    """wlanapi.dll through ctypes."""

    def __init__(self) -> None:
        dll = ctypes.WinDLL("wlanapi.dll")  # OSError -> provider unavailable
        self._open = dll.WlanOpenHandle
        self._open.argtypes = [wintypes.DWORD, ctypes.c_void_p, ctypes.POINTER(wintypes.DWORD),
                               ctypes.POINTER(wintypes.HANDLE)]
        self._open.restype = wintypes.DWORD
        self._close = dll.WlanCloseHandle
        self._close.argtypes = [wintypes.HANDLE, ctypes.c_void_p]
        self._close.restype = wintypes.DWORD
        self._enum = dll.WlanEnumInterfaces
        self._enum.argtypes = [wintypes.HANDLE, ctypes.c_void_p,
                               ctypes.POINTER(ctypes.POINTER(WLAN_INTERFACE_INFO_LIST))]
        self._enum.restype = wintypes.DWORD
        self._query = dll.WlanQueryInterface
        self._query.argtypes = [wintypes.HANDLE, ctypes.POINTER(GUID), ctypes.c_int, ctypes.c_void_p,
                                ctypes.POINTER(wintypes.DWORD), ctypes.POINTER(ctypes.c_void_p),
                                ctypes.POINTER(ctypes.c_int)]
        self._query.restype = wintypes.DWORD
        self._free = dll.WlanFreeMemory
        self._free.argtypes = [ctypes.c_void_p]
        self._free.restype = None

    def open(self) -> wintypes.HANDLE:
        negotiated = wintypes.DWORD()
        handle = wintypes.HANDLE()
        rc = self._open(WLAN_CLIENT_VERSION_2, None, ctypes.byref(negotiated), ctypes.byref(handle))
        if rc != ERROR_SUCCESS:
            raise WlanError("WlanOpenHandle", rc)
        return handle

    def enum_interfaces(self, handle: wintypes.HANDLE) -> list[tuple[GUID, int]]:
        listing = ctypes.POINTER(WLAN_INTERFACE_INFO_LIST)()
        rc = self._enum(handle, None, ctypes.byref(listing))
        if rc != ERROR_SUCCESS:
            raise WlanError("WlanEnumInterfaces", rc)
        try:
            count = listing.contents.dwNumberOfItems
            infos = (WLAN_INTERFACE_INFO * count).from_address(
                ctypes.addressof(listing.contents.InterfaceInfo)) if count else []
            return [(GUID.from_buffer_copy(info.InterfaceGuid), int(info.isState)) for info in infos]
        finally:
            self._free(listing)

    def current_ssid(self, handle: wintypes.HANDLE, guid: GUID) -> bytes:
        size = wintypes.DWORD()
        data = ctypes.c_void_p()
        value_type = ctypes.c_int()
        rc = self._query(handle, ctypes.byref(guid), WLAN_INTF_OPCODE_CURRENT_CONNECTION, None,
                         ctypes.byref(size), ctypes.byref(data), ctypes.byref(value_type))
        if rc != ERROR_SUCCESS:
            raise WlanError("WlanQueryInterface", rc)
        try:
            if size.value < ctypes.sizeof(WLAN_CONNECTION_ATTRIBUTES):
                raise WlanError("WlanQueryInterface (short buffer)", 0)
            return ssid_bytes(WLAN_CONNECTION_ATTRIBUTES.from_address(data.value))
        finally:
            self._free(data)

    def close(self, handle: wintypes.HANDLE) -> None:
        self._close(handle, None)


def _default_wlan() -> Optional[WlanLayer]:
    if sys.platform != "win32":
        return None
    try:
        return CtypesWlan()
    except (OSError, AttributeError) as e:
        _log.info("wifi_info unavailable: %s", e)
        return None


_DEFAULT = object()


class WifiInfoProvider:
    """SSID of the connected Wi-Fi interface (see the module docstring)."""

    def __init__(self, wlan: Any = _DEFAULT) -> None:
        self._wlan: Optional[WlanLayer] = _default_wlan() if wlan is _DEFAULT else wlan

    def snapshot(self) -> dict:
        if self._wlan is None:
            return {"available": False}
        try:
            handle = self._wlan.open()
        except WlanError as e:
            if e.code == ERROR_SERVICE_NOT_ACTIVE:
                return {"available": False}  # WLAN AutoConfig service stopped: no Wi-Fi
            raise
        try:
            for guid, state in self._wlan.enum_interfaces(handle):
                if state != WLAN_INTERFACE_STATE_CONNECTED:
                    continue
                try:
                    raw = self._wlan.current_ssid(handle, guid)
                except WlanError:
                    continue  # ERROR_ACCESS_DENIED without location permission, or just disconnected
                if raw:
                    return {"available": True, "ssid": raw.decode("utf-8", errors="replace")}
            return {"available": True, "ssid": ""}
        finally:
            self._wlan.close(handle)

    def handle(self, action: dict) -> Optional[str]:
        """No action here (wifi.set goes to the radios provider): any id is logged and ignored."""
        _log.warning("wifi_info: unknown action %r ignored", action.get("id"))
        return None
