"""USB drives provider for the Actions mode: lists USB drives, opens one in Explorer, ejects one safely.

Snapshot shape: `snapshot()` returns `{"available": True, "drives": [...]}`, one entry per drive sorted by letter:
`{"drive": "E:", "label": "KINGSTON", "free_bytes": 12884901888, "total_bytes": 31914983424, "kind": "stick"}`.
"kind" is "stick" for removable media (GetDriveTypeW = DRIVE_REMOVABLE, or STORAGE_DEVICE_DESCRIPTOR.RemovableMedia
set) and "disk" for a USB fixed disk (external HDD/SSD). The wire state
(spec §2.1) carries the bare list under "usb", so the hub puts `snapshot()["drives"]` there (an empty list when the
provider is unavailable or raised). `snapshot()` raises UsbError (a ProviderError) only when the drive list itself
cannot be read.

- Listing: GetLogicalDrives, then the removable and fixed drives whose disk reports BusTypeUsb through
  IOCTL_STORAGE_QUERY_PROPERTY (USB sticks and USB hard disks; SD slots, SATA/NVMe disks, optical and network
  drives are left out). Label from GetVolumeInformationW, space from GetDiskFreeSpaceExW; a slot without media
  (card reader) is skipped.
- `usb.open`: os.startfile on the drive root, so Explorer opens it.
- `usb.eject`: volume → disk number (IOCTL_STORAGE_GET_DEVICE_NUMBER) → the GUID_DEVINTERFACE_DISK interface with the
  same number (SetupAPI) → its devinst → CM_Get_Parent → CM_Request_Device_EjectW with a veto buffer (which also
  keeps Windows from showing its own dialog). A veto (file open, Explorer window…) gives "usb_busy" after a few
  attempts, any other failure "usb_failed".
- Both actions only accept a drive letter that is a USB drive right now: anything else is "usb_failed", so the device
  can never open an arbitrary path nor eject an internal disk.

Every Win32 call goes through a small API object (Win32UsbApi) that tests replace with a fake.
"""
from __future__ import annotations

import contextlib
import ctypes
import os
import re
import struct
import time
from typing import Any, Callable, Iterator, Protocol

from actions.base import ProviderError

# GetDriveTypeW
DRIVE_UNKNOWN = 0
DRIVE_NO_ROOT_DIR = 1
DRIVE_REMOVABLE = 2
DRIVE_FIXED = 3
DRIVE_REMOTE = 4
DRIVE_CDROM = 5
DRIVE_RAMDISK = 6

# STORAGE_BUS_TYPE
BusTypeUnknown = 0
BusTypeScsi = 1
BusTypeAtapi = 2
BusTypeAta = 3
BusTypeUsb = 7
BusTypeSata = 11
BusTypeSd = 12
BusTypeNvme = 17

# DEVICE_TYPE (STORAGE_DEVICE_NUMBER.DeviceType)
FILE_DEVICE_CD_ROM = 0x02
FILE_DEVICE_DISK = 0x07

IOCTL_STORAGE_QUERY_PROPERTY = 0x2D1400
IOCTL_STORAGE_GET_DEVICE_NUMBER = 0x2D1080

# CONFIGRET
CR_SUCCESS = 0x00
CR_REMOVE_VETOED = 0x17

# PNP_VETO_TYPE
PNP_VetoTypeUnknown = 0
PNP_VetoLegacyDevice = 1
PNP_VetoPendingClose = 2
PNP_VetoWindowsApp = 3
PNP_VetoWindowsService = 4
PNP_VetoOutstandingOpen = 5
PNP_VetoDevice = 6
PNP_VetoDriver = 7
PNP_VetoIllegalDeviceRequest = 8
PNP_VetoInsufficientPower = 9
PNP_VetoNonDisableable = 10
PNP_VetoLegacyDriver = 11
PNP_VetoInsufficientRights = 12
PNP_VetoAlreadyRemoved = 13

_VETO_NAMES = {value: name for name, value in globals().items() if name.startswith("PNP_Veto")}

# Le premier essai est parfois refusé le temps que l'indexeur ou l'antivirus lâche la clé.
EJECT_ATTEMPTS = 3
EJECT_RETRY_S = 0.5

BUSY = "usb_busy"
FAILED = "usb_failed"

_DRIVE = re.compile(r"([A-Za-z])(?::\\?)?")


class UsbError(ProviderError):
    """A Win32 call failed (a ProviderError, so the hub marks the provider unavailable).

    `code` = Windows error / CONFIGRET, None if not applicable.
    """

    def __init__(self, operation: str, code: int | None = None, detail: str = "") -> None:
        self.operation = operation
        self.code = code
        self.detail = detail
        super().__init__(operation, code, detail)

    def __str__(self) -> str:
        text = f"{self.operation} failed"
        if self.detail:
            text += f": {self.detail}"
        if self.code is not None:
            text += f" (code {self.code})"
        return text


# --- logique pure ---

def normalize_drive(value: Any) -> str | None:
    """'E:', 'e:', 'E:\\' or 'e' → 'E'; anything else (paths, digits, non-strings) → None."""
    if not isinstance(value, str):
        return None
    match = _DRIVE.fullmatch(value)
    return match.group(1).upper() if match else None


def letters(mask: int) -> list[str]:
    """Drive letters set in a GetLogicalDrives bit mask (bit 0 = A)."""
    return [chr(ord("A") + bit) for bit in range(26) if mask & (1 << bit)]


def veto_name(veto: int) -> str:
    return _VETO_NAMES.get(veto, f"veto {veto}")


def volume_path(letter: str) -> str:
    return f"\\\\.\\{letter}:"


def root_path(letter: str) -> str:
    return f"{letter}:\\"


# --- couche Win32 (interface) ---

class UsbApi(Protocol):
    def logical_drives(self) -> int: ...
    def drive_type(self, root: str) -> int: ...
    def bus_type(self, device_path: str) -> int: ...
    def removable_media(self, device_path: str) -> bool: ...                # STORAGE_DEVICE_DESCRIPTOR.RemovableMedia
    def volume_label(self, root: str) -> str: ...
    def disk_space(self, root: str) -> tuple[int, int]: ...                 # (free for the caller, total)
    def device_number(self, path: str) -> tuple[int, int, int]: ...         # (device type, number, partition)
    def disk_interfaces(self) -> list[tuple[int, str]]: ...                 # [(devinst, interface path)]
    def get_parent(self, devinst: int) -> int: ...
    def request_eject(self, devinst: int) -> tuple[int, int, str]: ...      # (CONFIGRET, veto type, veto name)
    def startfile(self, path: str) -> None: ...


# --- fournisseur ---

class UsbProvider:
    """Provider for the "usb" part of the state and the usb.open / usb.eject actions."""

    def __init__(self, api: UsbApi | None = None, *, log: Callable[[str], None] | None = None,
                 sleep: Callable[[float], None] = time.sleep) -> None:
        self._api = api if api is not None else Win32UsbApi()
        self._log = log or (lambda _line: None)
        self._sleep = sleep

    def snapshot(self) -> dict:
        drives = []
        for letter in letters(self._api.logical_drives()):
            if not self._is_usb(letter):
                continue
            root = root_path(letter)
            try:
                free, total = self._api.disk_space(root)
            except (UsbError, OSError):
                continue  # pas de support (lecteur de cartes vide) ou volume illisible
            try:
                label = self._api.volume_label(root)
            except (UsbError, OSError):
                label = ""
            drives.append({"drive": f"{letter}:", "label": label, "free_bytes": int(free), "total_bytes": int(total),
                           "kind": self._kind(letter, root)})
        return {"available": True, "drives": drives}

    def handle(self, action: dict) -> str | None:
        kind = action.get("id")
        if kind not in ("usb.open", "usb.eject"):
            self._log(f"USB: unknown action {kind!r} ignored")
            return None
        letter = normalize_drive(action.get("drive"))
        if letter is None or not self._is_usb(letter, check_present=True):
            self._log(f"USB: {kind} refused, {action.get('drive')!r} is not a USB drive")
            return FAILED
        return self._open(letter) if kind == "usb.open" else self._eject(letter)

    # --- interne ---

    def _is_usb(self, letter: str, *, check_present: bool = False) -> bool:
        try:
            if check_present and letter not in letters(self._api.logical_drives()):
                return False
            if self._api.drive_type(root_path(letter)) not in (DRIVE_REMOVABLE, DRIVE_FIXED):
                return False
            return self._api.bus_type(volume_path(letter)) == BusTypeUsb
        except (UsbError, OSError):
            return False

    def _kind(self, letter: str, root: str) -> str:
        """"stick" when the drive is removable media, "disk" for a USB fixed disk."""
        try:
            if self._api.drive_type(root) == DRIVE_REMOVABLE:
                return "stick"
            return "stick" if self._api.removable_media(volume_path(letter)) else "disk"
        except (UsbError, OSError):
            return "disk"  # unreadable descriptor on a fixed drive: the safer reading

    def _open(self, letter: str) -> str | None:
        try:
            self._api.startfile(root_path(letter))
        except (UsbError, OSError) as error:
            self._log(f"USB: cannot open {letter}: ({error})")
            return FAILED
        return None

    def _eject(self, letter: str) -> str | None:
        try:
            parent = self._parent_of(letter)
        except (UsbError, OSError) as error:
            self._log(f"USB: cannot eject {letter}: ({error})")
            return FAILED
        for attempt in range(1, EJECT_ATTEMPTS + 1):
            try:
                result, veto, name = self._api.request_eject(parent)
            except (UsbError, OSError) as error:
                self._log(f"USB: cannot eject {letter}: ({error})")
                return FAILED
            if veto == PNP_VetoAlreadyRemoved or (result == CR_SUCCESS and veto == PNP_VetoTypeUnknown):
                self._log(f"USB: {letter}: ejected")
                return None
            if result != CR_REMOVE_VETOED and veto == PNP_VetoTypeUnknown:
                self._log(f"USB: cannot eject {letter}: CM_Request_Device_EjectW returned 0x{result:X}")
                return FAILED
            self._log(f"USB: eject of {letter}: refused (attempt {attempt}/{EJECT_ATTEMPTS}), "
                      f"{veto_name(veto)} {name}".rstrip())
            if attempt < EJECT_ATTEMPTS:
                self._sleep(EJECT_RETRY_S)
        return BUSY

    def _parent_of(self, letter: str) -> int:
        """devinst to eject for a drive letter: the parent (USB mass storage device) of its disk."""
        device_type, number, _partition = self._api.device_number(volume_path(letter))
        if device_type != FILE_DEVICE_DISK:
            raise UsbError("IOCTL_STORAGE_GET_DEVICE_NUMBER", None, f"not a disk (device type {device_type})")
        for devinst, path in self._api.disk_interfaces():
            try:
                other_type, other_number, _ = self._api.device_number(path)
            except (UsbError, OSError):
                continue  # disque inaccessible (lecteur de cartes vide…) : ce n'est pas le nôtre
            if (other_type, other_number) == (device_type, number):
                return self._api.get_parent(devinst)
        raise UsbError("SetupDiEnumDeviceInterfaces", None, f"no disk interface for disk {number}")


# --- couche Win32 (ctypes) ---

class GUID(ctypes.Structure):
    _fields_ = [("Data1", ctypes.c_uint32), ("Data2", ctypes.c_uint16), ("Data3", ctypes.c_uint16),
                ("Data4", ctypes.c_ubyte * 8)]


GUID_DEVINTERFACE_DISK = GUID(0x53F56307, 0xB6BF, 0x11D0, (ctypes.c_ubyte * 8)(*bytes.fromhex("94f200a0c91efb8b")))


class STORAGE_DEVICE_NUMBER(ctypes.Structure):
    _fields_ = [("DeviceType", ctypes.c_uint32), ("DeviceNumber", ctypes.c_uint32),
                ("PartitionNumber", ctypes.c_uint32)]


class STORAGE_PROPERTY_QUERY(ctypes.Structure):
    _fields_ = [("PropertyId", ctypes.c_uint32), ("QueryType", ctypes.c_uint32),
                ("AdditionalParameters", ctypes.c_ubyte * 1)]


class STORAGE_DEVICE_DESCRIPTOR(ctypes.Structure):
    _fields_ = [("Version", ctypes.c_uint32), ("Size", ctypes.c_uint32), ("DeviceType", ctypes.c_ubyte),
                ("DeviceTypeModifier", ctypes.c_ubyte), ("RemovableMedia", ctypes.c_ubyte),
                ("CommandQueueing", ctypes.c_ubyte), ("VendorIdOffset", ctypes.c_uint32),
                ("ProductIdOffset", ctypes.c_uint32), ("ProductRevisionOffset", ctypes.c_uint32),
                ("SerialNumberOffset", ctypes.c_uint32), ("BusType", ctypes.c_uint32),
                ("RawPropertiesLength", ctypes.c_uint32), ("RawDeviceProperties", ctypes.c_ubyte * 1)]


class SP_DEVINFO_DATA(ctypes.Structure):
    _fields_ = [("cbSize", ctypes.c_uint32), ("ClassGuid", GUID), ("DevInst", ctypes.c_uint32),
                ("Reserved", ctypes.c_size_t)]


class SP_DEVICE_INTERFACE_DATA(ctypes.Structure):
    _fields_ = [("cbSize", ctypes.c_uint32), ("InterfaceClassGuid", GUID), ("Flags", ctypes.c_uint32),
                ("Reserved", ctypes.c_size_t)]


def interface_detail_cbsize() -> int:
    """cbSize of SP_DEVICE_INTERFACE_DETAIL_DATA_W: DWORD + one WCHAR, packed to 1 on x86, aligned to 4 on x64."""
    return 8 if ctypes.sizeof(ctypes.c_void_p) == 8 else 6


def parse_bus_type(data: bytes, length: int) -> int:
    """BusType out of the STORAGE_DEVICE_DESCRIPTOR returned by IOCTL_STORAGE_QUERY_PROPERTY."""
    offset = STORAGE_DEVICE_DESCRIPTOR.BusType.offset
    if length < offset + 4 or len(data) < offset + 4:
        raise UsbError("IOCTL_STORAGE_QUERY_PROPERTY", None, f"descriptor too short ({length} bytes)")
    return struct.unpack_from("<I", data, offset)[0]


def parse_removable_media(data: bytes, length: int) -> bool:
    """RemovableMedia out of the STORAGE_DEVICE_DESCRIPTOR returned by IOCTL_STORAGE_QUERY_PROPERTY."""
    offset = STORAGE_DEVICE_DESCRIPTOR.RemovableMedia.offset
    if length < offset + 1 or len(data) < offset + 1:
        raise UsbError("IOCTL_STORAGE_QUERY_PROPERTY", None, f"descriptor too short ({length} bytes)")
    return data[offset] != 0


StorageDeviceProperty = 0
PropertyStandardQuery = 0
FILE_SHARE_READ = 0x1
FILE_SHARE_WRITE = 0x2
OPEN_EXISTING = 3
DIGCF_PRESENT = 0x2
DIGCF_DEVICEINTERFACE = 0x10
ERROR_INSUFFICIENT_BUFFER = 122
ERROR_NO_MORE_ITEMS = 259
SEM_FAILCRITICALERRORS = 0x1
SEM_NOOPENFILEERRORBOX = 0x8000
MAX_PATH = 260
DESCRIPTOR_BUFFER = 1024


class Win32UsbApi:
    """Thin ctypes wrappers; each raises UsbError(<Win32 function>, GetLastError() or CONFIGRET) on failure."""

    def __init__(self) -> None:
        if os.name != "nt":
            raise UsbError("usb", None, "Windows only")
        from ctypes import wintypes

        self._invalid = ctypes.c_void_p(-1).value
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        setupapi = ctypes.WinDLL("setupapi", use_last_error=True)
        cfgmgr32 = ctypes.WinDLL("cfgmgr32", use_last_error=True)
        lp_guid = ctypes.POINTER(GUID)
        lp_dev = ctypes.POINTER(SP_DEVINFO_DATA)
        lp_iface = ctypes.POINTER(SP_DEVICE_INTERFACE_DATA)
        lp_dword = ctypes.POINTER(wintypes.DWORD)
        lp_u64 = ctypes.POINTER(ctypes.c_ulonglong)
        handle = ctypes.c_void_p
        signatures = {
            (kernel32, "GetLogicalDrives"): ([], wintypes.DWORD),
            (kernel32, "GetDriveTypeW"): ([wintypes.LPCWSTR], wintypes.UINT),
            (kernel32, "GetVolumeInformationW"): ([wintypes.LPCWSTR, wintypes.LPWSTR, wintypes.DWORD, lp_dword,
                                                   lp_dword, lp_dword, wintypes.LPWSTR, wintypes.DWORD],
                                                  wintypes.BOOL),
            (kernel32, "GetDiskFreeSpaceExW"): ([wintypes.LPCWSTR, lp_u64, lp_u64, lp_u64], wintypes.BOOL),
            (kernel32, "CreateFileW"): ([wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, ctypes.c_void_p,
                                         wintypes.DWORD, wintypes.DWORD, handle], handle),
            (kernel32, "DeviceIoControl"): ([handle, wintypes.DWORD, ctypes.c_void_p, wintypes.DWORD,
                                             ctypes.c_void_p, wintypes.DWORD, lp_dword, ctypes.c_void_p],
                                            wintypes.BOOL),
            (kernel32, "CloseHandle"): ([handle], wintypes.BOOL),
            (kernel32, "SetThreadErrorMode"): ([wintypes.DWORD, lp_dword], wintypes.BOOL),
            (setupapi, "SetupDiGetClassDevsW"): ([lp_guid, wintypes.LPCWSTR, wintypes.HWND, wintypes.DWORD], handle),
            (setupapi, "SetupDiEnumDeviceInterfaces"): ([handle, lp_dev, lp_guid, wintypes.DWORD, lp_iface],
                                                        wintypes.BOOL),
            (setupapi, "SetupDiGetDeviceInterfaceDetailW"): ([handle, lp_iface, ctypes.c_void_p, wintypes.DWORD,
                                                              lp_dword, lp_dev], wintypes.BOOL),
            (setupapi, "SetupDiDestroyDeviceInfoList"): ([handle], wintypes.BOOL),
            (cfgmgr32, "CM_Get_Parent"): ([lp_dword, wintypes.DWORD, wintypes.ULONG], wintypes.DWORD),
            (cfgmgr32, "CM_Request_Device_EjectW"): ([wintypes.DWORD, ctypes.POINTER(ctypes.c_int), wintypes.LPWSTR,
                                                      wintypes.ULONG, wintypes.ULONG], wintypes.DWORD),
        }
        self._f = {}
        for (dll, name), (argtypes, restype) in signatures.items():
            function = getattr(dll, name)
            function.argtypes = argtypes
            function.restype = restype
            self._f[name] = function

    @contextlib.contextmanager
    def _no_error_box(self) -> Iterator[None]:
        """No "There is no disk in the drive" dialog while touching removable media."""
        from ctypes import wintypes

        old = wintypes.DWORD()
        changed = self._f["SetThreadErrorMode"](SEM_FAILCRITICALERRORS | SEM_NOOPENFILEERRORBOX, ctypes.byref(old))
        try:
            yield
        finally:
            if changed:
                self._f["SetThreadErrorMode"](old.value, None)

    def logical_drives(self) -> int:
        mask = self._f["GetLogicalDrives"]()
        if not mask:
            error = ctypes.get_last_error()
            if error:
                raise UsbError("GetLogicalDrives", error)
        return mask

    def drive_type(self, root: str) -> int:
        return self._f["GetDriveTypeW"](root)

    def volume_label(self, root: str) -> str:
        name = ctypes.create_unicode_buffer(MAX_PATH + 1)
        with self._no_error_box():
            ok = self._f["GetVolumeInformationW"](root, name, MAX_PATH + 1, None, None, None, None, 0)
        if not ok:
            raise UsbError("GetVolumeInformationW", ctypes.get_last_error())
        return name.value

    def disk_space(self, root: str) -> tuple[int, int]:
        free, total, total_free = ctypes.c_ulonglong(), ctypes.c_ulonglong(), ctypes.c_ulonglong()
        with self._no_error_box():
            ok = self._f["GetDiskFreeSpaceExW"](root, ctypes.byref(free), ctypes.byref(total),
                                                ctypes.byref(total_free))
        if not ok:
            raise UsbError("GetDiskFreeSpaceExW", ctypes.get_last_error())
        return free.value, total.value

    def bus_type(self, device_path: str) -> int:
        data, length = self._device_descriptor(device_path)
        return parse_bus_type(data, length)

    def removable_media(self, device_path: str) -> bool:
        data, length = self._device_descriptor(device_path)
        return parse_removable_media(data, length)

    def _device_descriptor(self, device_path: str) -> tuple[bytes, int]:
        from ctypes import wintypes

        query = STORAGE_PROPERTY_QUERY(StorageDeviceProperty, PropertyStandardQuery)
        buffer = ctypes.create_string_buffer(DESCRIPTOR_BUFFER)
        returned = wintypes.DWORD()
        with self._open(device_path) as h:
            self._ioctl(h, "IOCTL_STORAGE_QUERY_PROPERTY", IOCTL_STORAGE_QUERY_PROPERTY, ctypes.byref(query),
                        ctypes.sizeof(query), buffer, DESCRIPTOR_BUFFER, returned)
        return buffer.raw, returned.value

    def device_number(self, path: str) -> tuple[int, int, int]:
        from ctypes import wintypes

        number = STORAGE_DEVICE_NUMBER()
        returned = wintypes.DWORD()
        with self._open(path) as h:
            self._ioctl(h, "IOCTL_STORAGE_GET_DEVICE_NUMBER", IOCTL_STORAGE_GET_DEVICE_NUMBER, None, 0,
                        ctypes.byref(number), ctypes.sizeof(number), returned)
        return number.DeviceType, number.DeviceNumber, number.PartitionNumber

    def disk_interfaces(self) -> list[tuple[int, str]]:
        from ctypes import wintypes

        guid = GUID_DEVINTERFACE_DISK
        hset = self._f["SetupDiGetClassDevsW"](ctypes.byref(guid), None, None,
                                               DIGCF_PRESENT | DIGCF_DEVICEINTERFACE)
        if not hset or hset == self._invalid:
            raise UsbError("SetupDiGetClassDevsW", ctypes.get_last_error())
        found = []
        try:
            index = 0
            while True:
                iface = SP_DEVICE_INTERFACE_DATA()
                iface.cbSize = ctypes.sizeof(SP_DEVICE_INTERFACE_DATA)
                if not self._f["SetupDiEnumDeviceInterfaces"](hset, None, ctypes.byref(guid), index,
                                                              ctypes.byref(iface)):
                    error = ctypes.get_last_error()
                    if error == ERROR_NO_MORE_ITEMS:
                        return found
                    raise UsbError("SetupDiEnumDeviceInterfaces", error)
                index += 1
                required = wintypes.DWORD()
                self._f["SetupDiGetDeviceInterfaceDetailW"](hset, ctypes.byref(iface), None, 0,
                                                            ctypes.byref(required), None)
                error = ctypes.get_last_error()
                if error != ERROR_INSUFFICIENT_BUFFER or required.value < interface_detail_cbsize():
                    raise UsbError("SetupDiGetDeviceInterfaceDetailW", error)
                detail = ctypes.create_string_buffer(required.value + 2)
                ctypes.c_uint32.from_buffer(detail).value = interface_detail_cbsize()
                dev = SP_DEVINFO_DATA()
                dev.cbSize = ctypes.sizeof(SP_DEVINFO_DATA)
                if not self._f["SetupDiGetDeviceInterfaceDetailW"](hset, ctypes.byref(iface), detail,
                                                                   required.value, None, ctypes.byref(dev)):
                    raise UsbError("SetupDiGetDeviceInterfaceDetailW", ctypes.get_last_error())
                found.append((dev.DevInst, ctypes.wstring_at(ctypes.addressof(detail) + 4)))
        finally:
            self._f["SetupDiDestroyDeviceInfoList"](hset)

    def get_parent(self, devinst: int) -> int:
        from ctypes import wintypes

        parent = wintypes.DWORD()
        result = self._f["CM_Get_Parent"](ctypes.byref(parent), devinst, 0)
        if result != CR_SUCCESS:
            raise UsbError("CM_Get_Parent", result)
        return parent.value

    def request_eject(self, devinst: int) -> tuple[int, int, str]:
        # Passer un tampon de veto empêche Windows d'afficher lui-même « Impossible d'éjecter ».
        veto = ctypes.c_int(PNP_VetoTypeUnknown)
        name = ctypes.create_unicode_buffer(MAX_PATH)
        result = self._f["CM_Request_Device_EjectW"](devinst, ctypes.byref(veto), name, MAX_PATH, 0)
        return result, veto.value, name.value

    def startfile(self, path: str) -> None:
        os.startfile(path)

    # --- interne ---

    @contextlib.contextmanager
    def _open(self, path: str) -> Iterator[int]:
        # Accès 0 : suffit pour ces IOCTL, sans droits administrateur ni verrou sur le volume.
        with self._no_error_box():
            h = self._f["CreateFileW"](path, 0, FILE_SHARE_READ | FILE_SHARE_WRITE, None, OPEN_EXISTING, 0, None)
        if not h or h == self._invalid:
            raise UsbError("CreateFileW", ctypes.get_last_error(), path)
        try:
            yield h
        finally:
            self._f["CloseHandle"](h)

    def _ioctl(self, h: int, name: str, code: int, in_buffer: Any, in_size: int, out_buffer: Any, out_size: int,
               returned: Any) -> None:
        if not self._f["DeviceIoControl"](h, code, in_buffer, in_size, out_buffer, out_size, ctypes.byref(returned),
                                          None):
            raise UsbError(f"DeviceIoControl({name})", ctypes.get_last_error())
