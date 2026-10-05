"""Installs, removes, restarts and finds the VDD device node (Windows only; no Qt here).

- find_device(): registry scan of HKLM\\SYSTEM\\CurrentControlSet\\Enum\\ROOT\\DISPLAY for the hardware ID
  Root\\MttVDD. No admin needed. The instance ID is ROOT\\DISPLAY\\NNNN, not ROOT\\MTTVDD\\…: the node is created
  under the class enumerator.
- install_driver / remove_driver / restart_device: need admin (the installer, or `--add-resolution` after UAC).
  Install = what `devcon install` does (SetupDiCreateDeviceInfoW + SPDRP_HARDWAREID + DIF_REGISTERDEVICE, then
  UpdateDriverForPlugAndPlayDevicesW), without shipping Microsoft's devcon.exe. Remove = DIF_REMOVE through
  SetupDiCallClassInstaller (SP_REMOVEDEVICE_PARAMS, global scope, as `devcon remove`), then
  `pnputil /delete-driver oemNN.inf /uninstall`. Restart = `pnputil /restart-device <instance id>` (Windows 10 2004+),
  the only way to make the driver read its XML again (docs/notes/vdd-control.md §2).

Every Win32 call goes through a small API object (Win32DeviceApi) that tests replace with a fake.
Errors raise VddDeviceError carrying the Windows error code (or pnputil's exit code). Texts are plain English: they
end up in the log and in the CLI exit status read by the installer.
"""
from __future__ import annotations

import ctypes
import os
import re
import struct
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

import tools

HARDWARE_ID = "Root\\MttVDD"
ENUM_KEY = r"SYSTEM\CurrentControlSet\Enum\ROOT\DISPLAY"
ENUM_PREFIX = r"ROOT\DISPLAY"
CLASS_KEY = r"SYSTEM\CurrentControlSet\Control\Class"

ERROR_FILE_NOT_FOUND = 2
ERROR_ACCESS_DENIED = 5
ERROR_ALREADY_EXISTS = 183
ERROR_NOT_FOUND = 1168
ERROR_TIMEOUT = 1460
ERROR_SUCCESS_REBOOT_REQUIRED = 3010
PNPUTIL_TIMEOUT_S = 120

_OEM_INF = re.compile(r"^oem\d+\.inf$", re.IGNORECASE)


class VddDeviceError(Exception):
    """A device operation failed. `winerror` = Windows error code (or pnputil exit code), None if not applicable."""

    def __init__(self, operation: str, winerror: int | None = None, detail: str = "") -> None:
        self.operation = operation
        self.winerror = winerror
        self.detail = detail
        super().__init__(operation, winerror, detail)

    def __str__(self) -> str:
        text = f"{self.operation} failed"
        if self.detail:
            text += f": {self.detail}"
        if self.winerror is not None:
            text += f" ({format_winerror(self.winerror)})"
        return text


def format_winerror(code: int) -> str:
    # Les codes SetupAPI (0xE000xxxx) se lisent en hexadécimal.
    shown = f"0x{code:08X}" if code > 0xFFFF else str(code)
    description = ""
    if os.name == "nt":
        try:
            description = ctypes.FormatError(code).strip()
        except (OSError, ValueError, OverflowError):
            description = ""
    known = bool(description) and not description.startswith("<")
    return f"Windows error {shown}: {description}" if known else f"Windows error {shown}"


@dataclass(frozen=True)
class DeviceInfo:
    instance_id: str                  # ROOT\DISPLAY\0000
    hardware_ids: tuple[str, ...]     # ("Root\MttVDD",)
    driver_key: str | None            # {4d36e968-…}\0004, sous …\Control\Class
    inf_name: str | None              # oem114.inf (nom dans le magasin de pilotes), validé
    driver_version: str | None        # 11.30.4.434


# --- logique pure ---

def parse_hardware_ids(value: Any) -> tuple[str, ...]:
    """HardwareID as read from the registry (REG_MULTI_SZ list, or a NUL-separated / plain string)."""
    if isinstance(value, str):
        value = value.split("\0")
    if not isinstance(value, (list, tuple)):
        return ()
    return tuple(item for item in value if isinstance(item, str) and item)


def is_vdd(hardware_ids: tuple[str, ...]) -> bool:
    return any(item.lower() == HARDWARE_ID.lower() for item in hardware_ids)


def oem_inf_name(value: Any) -> str | None:
    """The driver store name (oemNN.inf) or None: anything else is never handed to pnputil /delete-driver."""
    if isinstance(value, str) and _OEM_INF.match(value):
        return value
    return None


def multi_sz(text: str) -> bytes:
    """A one-entry REG_MULTI_SZ in UTF-16LE, as SetupDiSetDeviceRegistryPropertyW expects for SPDRP_HARDWAREID."""
    return (text + "\0\0").encode("utf-16le")


def pnputil_path(system_root: str, wow64: bool) -> str:
    # Un processus 32 bits sur Windows 64 bits doit passer par Sysnative pour atteindre le vrai pnputil.
    return os.path.join(system_root, "Sysnative" if wow64 else "System32", "pnputil.exe")


# --- registre ---

class Registry(Protocol):
    def subkeys(self, path: str) -> list[str]: ...
    def value(self, path: str, name: str) -> Any: ...


class WinRegistry:
    """Read-only HKLM access, 64-bit view."""

    def subkeys(self, path: str) -> list[str]:
        import winreg

        names = []
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, path, 0, winreg.KEY_READ | winreg.KEY_WOW64_64KEY) as key:
            index = 0
            while True:
                try:
                    names.append(winreg.EnumKey(key, index))
                except OSError:
                    return names
                index += 1

    def value(self, path: str, name: str) -> Any:
        import winreg

        try:
            with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, path, 0,
                                winreg.KEY_READ | winreg.KEY_WOW64_64KEY) as key:
                return winreg.QueryValueEx(key, name)[0]
        except OSError:
            return None


def find_devices(registry: Registry | None = None) -> list[DeviceInfo]:
    """Every Root\\MttVDD node (several if devcon install was run twice). Read-only, no admin."""
    registry = registry or WinRegistry()
    try:
        names = registry.subkeys(ENUM_KEY)
    except OSError:
        return []
    devices = []
    for name in names:
        key = ENUM_KEY + "\\" + name
        hardware_ids = parse_hardware_ids(registry.value(key, "HardwareID"))
        if not is_vdd(hardware_ids):
            continue
        driver = registry.value(key, "Driver")
        driver_key = driver if isinstance(driver, str) and driver else None
        inf_name = version = None
        if driver_key:
            class_key = CLASS_KEY + "\\" + driver_key
            inf_name = oem_inf_name(registry.value(class_key, "InfPath"))
            raw_version = registry.value(class_key, "DriverVersion")
            version = raw_version if isinstance(raw_version, str) else None
        devices.append(DeviceInfo(instance_id=ENUM_PREFIX + "\\" + name, hardware_ids=hardware_ids,
                                  driver_key=driver_key, inf_name=inf_name, driver_version=version))
    return devices


def find_device(registry: Registry | None = None) -> DeviceInfo | None:
    devices = find_devices(registry)
    return devices[0] if devices else None


# --- opérations (admin) ---

def is_admin(api: "DeviceApi | None" = None) -> bool:
    """True when this process runs elevated (the device operations below need it)."""
    return (api or Win32DeviceApi()).is_admin()


def install_driver(inf_path: str | os.PathLike, *, api: "DeviceApi | None" = None,
                   registry: Registry | None = None) -> bool:
    """Creates the Root\\MttVDD root device and installs the driver from `inf_path` (admin).

    Returns True when Windows says a reboot is needed to finish (UpdateDriverForPlugAndPlayDevicesW).

    Windows shows its "install this device software? (SignPath Foundation)" prompt on PCs that do not trust the
    signer yet; refusing it fails UpdateDriverForPlugAndPlayDevicesW, and the half-created node is removed again so
    a later detection does not mistake it for an installed driver. Refuses to create a second node.
    """
    operation = "install_driver"
    api = api or Win32DeviceApi()
    _require_admin(api, operation)
    inf = Path(inf_path).resolve()
    if not inf.is_file():
        raise VddDeviceError(operation, ERROR_FILE_NOT_FOUND, f"INF not found: {inf}")
    existing = find_devices(registry)
    if existing:
        raise VddDeviceError(operation, ERROR_ALREADY_EXISTS,
                             f"a {HARDWARE_ID} device already exists ({existing[0].instance_id})")
    try:
        class_guid, class_name = api.inf_class(str(inf))
        hset = api.create_info_list(class_guid)
        try:
            dev = api.create_device_info(hset, class_name, class_guid)
            api.set_hardware_id(hset, dev, HARDWARE_ID)
            api.register_device(hset, dev)
            try:
                reboot = bool(api.update_driver(HARDWARE_ID, str(inf)))
            except VddDeviceError:
                try:
                    api.remove_device(hset, dev)
                except VddDeviceError:
                    pass  # l'erreur utile est celle du pilote
                raise
        finally:
            api.destroy_info_list(hset)
    except VddDeviceError as error:
        raise _as(operation, error) from error
    return reboot


def remove_driver(*, api: "DeviceApi | None" = None, registry: Registry | None = None) -> None:
    """Removes every Root\\MttVDD node, then its driver package from the driver store (admin). No-op if absent."""
    operation = "remove_driver"
    api = api or Win32DeviceApi()
    _require_admin(api, operation)
    devices = find_devices(registry)
    if not devices:
        return
    # Noms oemNN.inf relevés avant le retrait : après, la clé de classe a disparu.
    packages = list(dict.fromkeys(d.inf_name for d in devices if d.inf_name))
    try:
        hset = api.create_info_list(None)
        try:
            for device in devices:
                api.remove_device(hset, api.open_device(hset, device.instance_id))
        finally:
            api.destroy_info_list(hset)
    except VddDeviceError as error:
        raise _as(operation, error) from error
    for package in packages:
        _pnputil(api, operation, ["/delete-driver", package, "/uninstall"])


def restart_device(*, api: "DeviceApi | None" = None, registry: Registry | None = None) -> None:
    """Restarts the VDD device so the driver reads vdd_settings.xml again (admin). The screen blinks."""
    operation = "restart_device"
    api = api or Win32DeviceApi()
    _require_admin(api, operation)
    devices = find_devices(registry)
    if not devices:
        raise VddDeviceError(operation, ERROR_NOT_FOUND, f"no {HARDWARE_ID} device")
    for device in devices:
        _pnputil(api, operation, ["/restart-device", device.instance_id])


def _require_admin(api: "DeviceApi", operation: str) -> None:
    if not api.is_admin():
        raise VddDeviceError(operation, ERROR_ACCESS_DENIED, "administrator rights required")


def _pnputil(api: "DeviceApi", operation: str, args: list[str]) -> None:
    code, output = api.pnputil(args)
    if code not in (0, ERROR_SUCCESS_REBOOT_REQUIRED):
        tail = " ".join(output.split())[-300:]
        raise VddDeviceError(operation, code, f"pnputil {' '.join(args)}: {tail}" if tail else f"pnputil {args[0]}")


def _as(operation: str, error: VddDeviceError) -> VddDeviceError:
    """Re-labels a low-level error (named after the Win32 function) with the public operation."""
    return VddDeviceError(operation, error.winerror, error.operation + (f": {error.detail}" if error.detail else ""))


# --- couche Win32 (ctypes) ---

class GUID(ctypes.Structure):
    _fields_ = [("Data1", ctypes.c_uint32), ("Data2", ctypes.c_uint16), ("Data3", ctypes.c_uint16),
                ("Data4", ctypes.c_ubyte * 8)]


class SP_DEVINFO_DATA(ctypes.Structure):
    _fields_ = [("cbSize", ctypes.c_uint32), ("ClassGuid", GUID), ("DevInst", ctypes.c_uint32),
                ("Reserved", ctypes.c_size_t)]


class SP_CLASSINSTALL_HEADER(ctypes.Structure):
    _fields_ = [("cbSize", ctypes.c_uint32), ("InstallFunction", ctypes.c_uint32)]


class SP_REMOVEDEVICE_PARAMS(ctypes.Structure):
    _fields_ = [("ClassInstallHeader", SP_CLASSINSTALL_HEADER), ("Scope", ctypes.c_uint32),
                ("HwProfile", ctypes.c_uint32)]


DIF_REMOVE = 0x05
DI_REMOVEDEVICE_GLOBAL = 0x1


class DeviceApi(Protocol):
    def is_admin(self) -> bool: ...
    def inf_class(self, inf_path: str) -> tuple[Any, str]: ...
    def create_info_list(self, class_guid: Any) -> Any: ...
    def create_device_info(self, hset: Any, class_name: str, class_guid: Any) -> Any: ...
    def set_hardware_id(self, hset: Any, dev: Any, hardware_id: str) -> None: ...
    def register_device(self, hset: Any, dev: Any) -> None: ...
    def update_driver(self, hardware_id: str, inf_path: str) -> bool: ...
    def open_device(self, hset: Any, instance_id: str) -> Any: ...
    def remove_device(self, hset: Any, dev: Any) -> None: ...
    def destroy_info_list(self, hset: Any) -> None: ...
    def pnputil(self, args: list[str]) -> tuple[int, str]: ...


class Win32DeviceApi:
    """Thin ctypes wrappers; each raises VddDeviceError(<Win32 function>, GetLastError()) on failure."""

    MAX_CLASS_NAME_LEN = 32
    DICD_GENERATE_ID = 0x1
    SPDRP_HARDWAREID = 0x1
    DIF_REGISTERDEVICE = 0x19
    INSTALLFLAG_FORCE = 0x1

    def __init__(self) -> None:
        if os.name != "nt":
            raise VddDeviceError("vdd_device", None, "Windows only")
        from ctypes import wintypes

        self._invalid = ctypes.c_void_p(-1).value
        setupapi = ctypes.WinDLL("setupapi", use_last_error=True)
        newdev = ctypes.WinDLL("newdev", use_last_error=True)
        lp_guid = ctypes.POINTER(GUID)
        lp_dev = ctypes.POINTER(SP_DEVINFO_DATA)
        hdevinfo = ctypes.c_void_p
        signatures = {
            (setupapi, "SetupDiGetINFClassW"): ([wintypes.LPCWSTR, lp_guid, wintypes.LPWSTR, wintypes.DWORD,
                                                 ctypes.POINTER(wintypes.DWORD)], wintypes.BOOL),
            (setupapi, "SetupDiCreateDeviceInfoList"): ([lp_guid, wintypes.HWND], hdevinfo),
            (setupapi, "SetupDiCreateDeviceInfoW"): ([hdevinfo, wintypes.LPCWSTR, lp_guid, wintypes.LPCWSTR,
                                                      wintypes.HWND, wintypes.DWORD, lp_dev], wintypes.BOOL),
            (setupapi, "SetupDiSetDeviceRegistryPropertyW"): ([hdevinfo, lp_dev, wintypes.DWORD, ctypes.c_char_p,
                                                               wintypes.DWORD], wintypes.BOOL),
            (setupapi, "SetupDiCallClassInstaller"): ([wintypes.UINT, hdevinfo, lp_dev], wintypes.BOOL),
            (setupapi, "SetupDiOpenDeviceInfoW"): ([hdevinfo, wintypes.LPCWSTR, wintypes.HWND, wintypes.DWORD,
                                                    lp_dev], wintypes.BOOL),
            (setupapi, "SetupDiSetClassInstallParamsW"): ([hdevinfo, lp_dev, ctypes.POINTER(SP_CLASSINSTALL_HEADER),
                                                           wintypes.DWORD], wintypes.BOOL),
            (setupapi, "SetupDiDestroyDeviceInfoList"): ([hdevinfo], wintypes.BOOL),
            (newdev, "UpdateDriverForPlugAndPlayDevicesW"): ([wintypes.HWND, wintypes.LPCWSTR, wintypes.LPCWSTR,
                                                              wintypes.DWORD, ctypes.POINTER(wintypes.BOOL)],
                                                             wintypes.BOOL),
        }
        self._f = {}
        for (dll, name), (argtypes, restype) in signatures.items():
            function = getattr(dll, name)
            function.argtypes = argtypes
            function.restype = restype
            self._f[name] = function

    def _check(self, name: str, ok: Any) -> None:
        if not ok:
            raise VddDeviceError(name, ctypes.get_last_error())

    def is_admin(self) -> bool:
        try:
            return bool(ctypes.windll.shell32.IsUserAnAdmin())
        except (AttributeError, OSError):
            return False

    def inf_class(self, inf_path: str) -> tuple[GUID, str]:
        from ctypes import wintypes

        guid = GUID()
        name = ctypes.create_unicode_buffer(self.MAX_CLASS_NAME_LEN)
        self._check("SetupDiGetINFClassW", self._f["SetupDiGetINFClassW"](
            inf_path, ctypes.byref(guid), name, self.MAX_CLASS_NAME_LEN, ctypes.byref(wintypes.DWORD())))
        return guid, name.value

    def create_info_list(self, class_guid: GUID | None) -> int:
        hset = self._f["SetupDiCreateDeviceInfoList"](
            ctypes.byref(class_guid) if class_guid is not None else None, None)
        if not hset or hset == self._invalid:
            raise VddDeviceError("SetupDiCreateDeviceInfoList", ctypes.get_last_error())
        return hset

    def create_device_info(self, hset: int, class_name: str, class_guid: GUID) -> SP_DEVINFO_DATA:
        dev = self._new_devinfo()
        self._check("SetupDiCreateDeviceInfoW", self._f["SetupDiCreateDeviceInfoW"](
            hset, class_name, ctypes.byref(class_guid), None, None, self.DICD_GENERATE_ID, ctypes.byref(dev)))
        return dev

    def set_hardware_id(self, hset: int, dev: SP_DEVINFO_DATA, hardware_id: str) -> None:
        data = multi_sz(hardware_id)
        self._check("SetupDiSetDeviceRegistryPropertyW", self._f["SetupDiSetDeviceRegistryPropertyW"](
            hset, ctypes.byref(dev), self.SPDRP_HARDWAREID, data, len(data)))

    def register_device(self, hset: int, dev: SP_DEVINFO_DATA) -> None:
        self._check("SetupDiCallClassInstaller(DIF_REGISTERDEVICE)", self._f["SetupDiCallClassInstaller"](
            self.DIF_REGISTERDEVICE, hset, ctypes.byref(dev)))

    def update_driver(self, hardware_id: str, inf_path: str) -> bool:
        from ctypes import wintypes

        reboot = wintypes.BOOL(False)
        self._check("UpdateDriverForPlugAndPlayDevicesW", self._f["UpdateDriverForPlugAndPlayDevicesW"](
            None, hardware_id, inf_path, self.INSTALLFLAG_FORCE, ctypes.byref(reboot)))
        return bool(reboot.value)

    def open_device(self, hset: int, instance_id: str) -> SP_DEVINFO_DATA:
        dev = self._new_devinfo()
        self._check("SetupDiOpenDeviceInfoW", self._f["SetupDiOpenDeviceInfoW"](
            hset, instance_id, None, 0, ctypes.byref(dev)))
        return dev

    def remove_device(self, hset: int, dev: SP_DEVINFO_DATA) -> None:
        """Like `devcon remove`: DIF_REMOVE (global scope) through the class installer, so the class and co-installers
        run their removal steps (SetupDiRemoveDevice alone skips them)."""
        params = SP_REMOVEDEVICE_PARAMS()
        params.ClassInstallHeader.cbSize = ctypes.sizeof(SP_CLASSINSTALL_HEADER)
        params.ClassInstallHeader.InstallFunction = DIF_REMOVE
        params.Scope = DI_REMOVEDEVICE_GLOBAL
        params.HwProfile = 0
        header = ctypes.cast(ctypes.pointer(params), ctypes.POINTER(SP_CLASSINSTALL_HEADER))
        self._check("SetupDiSetClassInstallParamsW", self._f["SetupDiSetClassInstallParamsW"](
            hset, ctypes.byref(dev), header, ctypes.sizeof(params)))
        self._check("SetupDiCallClassInstaller(DIF_REMOVE)", self._f["SetupDiCallClassInstaller"](
            DIF_REMOVE, hset, ctypes.byref(dev)))

    def destroy_info_list(self, hset: int) -> None:
        self._f["SetupDiDestroyDeviceInfoList"](hset)

    def pnputil(self, args: list[str]) -> tuple[int, str]:
        wow64 = struct.calcsize("P") == 4 and bool(os.environ.get("PROCESSOR_ARCHITEW6432"))
        exe = pnputil_path(os.environ.get("SystemRoot", r"C:\Windows"), wow64)
        try:
            result = subprocess.run([exe, *args], capture_output=True, creationflags=tools.NO_WINDOW,
                                    timeout=PNPUTIL_TIMEOUT_S, stdin=subprocess.DEVNULL)
        except subprocess.TimeoutExpired:
            return ERROR_TIMEOUT, f"pnputil did not finish within {PNPUTIL_TIMEOUT_S} s"
        except OSError as error:
            return error.winerror or ERROR_FILE_NOT_FOUND, str(error)
        # pnputil écrit dans la page de code OEM de la console, localisée (« Accès refusé »…).
        output = (result.stdout + result.stderr).decode("oem", errors="replace")
        return result.returncode, output

    @staticmethod
    def _new_devinfo() -> SP_DEVINFO_DATA:
        dev = SP_DEVINFO_DATA()
        dev.cbSize = ctypes.sizeof(SP_DEVINFO_DATA)
        return dev
