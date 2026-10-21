"""The launcher tiles of the Actions mode (spec 2026-10-20 launchers-compact §1): Settings, Discord, Spotify, Downloads.

Snapshot (the ``launchers`` section): ``{"settings": True, "discord": bool, "spotify": bool, "downloads": True,
"icons": {"discord": <sha1> | None, "spotify": <sha1> | None}}``. Discord and Spotify are present only when installed (the
detection is cached 60 s). Their icons are the real icons of their exe, extracted by ``AppIconProvider`` (actions.app_icons)
and sent by the hub as MEDIA_ARTWORK, like the context bar's icon (``artwork_bytes(id)``); None while not ready, or when
the app has no exe to take it from (a protocol only).

``{"id": "launch.open", "target": ...}``: a CLOSED list maps each target to its command, no other target is accepted (an
unknown or malformed one is ignored and logged, nothing is run):

* ``settings``: ``ms-settings:`` ;
* ``discord``: ``%LOCALAPPDATA%\\Discord\\Update.exe --processStart Discord.exe``, else the ``discord://`` protocol when it
  is registered;
* ``spotify``: ``%APPDATA%\\Spotify\\Spotify.exe``, else the ``spotify:`` protocol (Microsoft Store version). The Store
  package keeps a readable ``Spotify.exe``: its folder is read (read-only) from the registry value ``PackageRootFolder`` of
  ``HKCU\\...\\AppModel\\Repository\\Packages\\SpotifyAB.SpotifyMusic_*`` and gives the icon; the launch stays ``spotify:``;
* ``downloads``: the Downloads known folder (``FOLDERID_Downloads``) opened with ``explorer.exe``.

Nothing is run through a shell and no console window appears (``CREATE_NO_WINDOW``). A missing app or a launch that fails
is the notice ``app_not_found``. Normal hub path.

Open, then minimize (spec §4.4): when the target's window is already the PC foreground window, the tap minimizes it
(``ShowWindow(SW_MINIMIZE)``) instead of launching. The foreground window is recognised by its process: ``Discord.exe``,
``Spotify.exe``; Settings is ``SystemSettings.exe``, or an ``ApplicationFrameWindow`` that has a child window owned by
``SystemSettings.exe``; Downloads is an Explorer window (``CabinetWClass``) whose current folder is the Downloads folder
(compared case-insensitively, normalised). Any failure of that detection means "not in front": the app is launched.

The file system, registry, Store package lookup, launcher, window functions (``windows``: foreground_window,
window_class, window_pid, process_exe, child_exes, explorer_folder, minimize), clock and icon provider are injectable
for the tests, which never touch a real window.
"""
from __future__ import annotations

import ctypes
import logging
import os
import re
import subprocess
import time
from ctypes import wintypes
from typing import Any, Callable, Optional
from urllib.parse import unquote, urlparse

_log = logging.getLogger("orizonx.actions.launchers")

LAUNCH_ID = "launch.open"
APP_NOT_FOUND = "app_not_found"
TARGETS = ("settings", "discord", "spotify", "downloads")
CACHE_S = 60.0
PROCESS_OF = {"discord": "discord.exe", "spotify": "spotify.exe"}  # exe of the window in front, lower case
SETTINGS_EXE = "systemsettings.exe"
CREATE_NO_WINDOW = 0x08000000
SW_MINIMIZE = 6
SPOTIFY_PACKAGE = "SpotifyAB.SpotifyMusic_"
_PACKAGES_KEY = (r"Software\Classes\Local Settings\Software\Microsoft\Windows\CurrentVersion\AppModel"
                 r"\Repository\Packages")


class RealFs:
    def isfile(self, path: str) -> bool:
        return os.path.isfile(path)

    def isdir(self, path: str) -> bool:
        return os.path.isdir(path)

    def listdir(self, path: str) -> "list[str]":
        return os.listdir(path)


def protocol_registered(name: str) -> bool:
    """True when a URL protocol (``discord``, ``spotify``) is registered for the user or the machine (read-only)."""
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CLASSES_ROOT, name) as key:
            winreg.QueryValueEx(key, "URL Protocol")
        return True
    except (ImportError, OSError):
        return False


def store_package_roots(prefix: str) -> "list[str]":
    """The ``PackageRootFolder`` of every installed Microsoft Store package whose full name starts with ``prefix``, newest
    version first (read-only registry lookup; the exe inside is readable even though the folder is not listable)."""
    try:
        import winreg
        found = []
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, _PACKAGES_KEY) as packages:
            index = 0
            while True:
                try:
                    name = winreg.EnumKey(packages, index)
                except OSError:
                    break
                index += 1
                if not name.startswith(prefix):
                    continue
                try:
                    with winreg.OpenKey(packages, name) as package:
                        root = winreg.QueryValueEx(package, "PackageRootFolder")[0]
                except OSError:
                    continue
                if isinstance(root, str) and root:
                    found.append((name, root))
        found.sort(key=lambda item: _version_key(item[0]), reverse=True)
        return [root for _, root in found]
    except (ImportError, OSError):
        return []


class _GUID(ctypes.Structure):
    _fields_ = [("Data1", ctypes.c_uint32), ("Data2", ctypes.c_uint16), ("Data3", ctypes.c_uint16),
                ("Data4", ctypes.c_uint8 * 8)]


def downloads_folder() -> Optional[str]:
    """The user's Downloads folder (``SHGetKnownFolderPath(FOLDERID_Downloads)``), or None."""
    try:
        guid = _GUID(0x374DE290, 0x123F, 0x4565, (ctypes.c_uint8 * 8)(0x91, 0x64, 0x39, 0xC4, 0x92, 0x5E, 0x46, 0x7B))
        shell32 = ctypes.WinDLL("shell32")
        ole32 = ctypes.WinDLL("ole32")
        shell32.SHGetKnownFolderPath.argtypes = [ctypes.POINTER(_GUID), ctypes.c_uint32, ctypes.c_void_p,
                                                 ctypes.POINTER(ctypes.c_void_p)]
        shell32.SHGetKnownFolderPath.restype = ctypes.c_long
        ole32.CoTaskMemFree.argtypes = [ctypes.c_void_p]
        pointer = ctypes.c_void_p()
        if shell32.SHGetKnownFolderPath(ctypes.byref(guid), 0, None, ctypes.byref(pointer)) != 0:
            return None
        try:
            return ctypes.wstring_at(pointer.value)
        finally:
            ole32.CoTaskMemFree(pointer)
    except (OSError, AttributeError, ValueError):
        return None


class RealLauncher:
    """Starts programs and URIs without a shell and without a console window."""

    def startfile(self, target: str) -> None:
        os.startfile(target)  # noqa: S606 - only the fixed URIs of the closed list reach it

    def popen(self, args: "list[str]") -> None:
        subprocess.Popen(args, creationflags=CREATE_NO_WINDOW, close_fds=True, stdin=subprocess.DEVNULL,
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, shell=False)


def _same_path(a: Optional[str], b: Optional[str]) -> bool:
    return bool(a and b) and os.path.normcase(os.path.normpath(a)) == os.path.normcase(os.path.normpath(b))


class RealWindows:
    """The real user32 / kernel32 / Explorer calls behind the minimize toggle. ``foreground.Win32Api`` answers the window
    class, process id and exe (an empty answer on failure, never an exception); the rest is added here."""

    def __init__(self) -> None:
        from actions.foreground import Win32Api
        self._api = Win32Api()
        user32 = ctypes.WinDLL("user32", use_last_error=True)
        self._enum_children = user32.EnumChildWindows
        self._enum_children.argtypes = [wintypes.HWND, ctypes.c_void_p, wintypes.LPARAM]
        self._enum_children.restype = wintypes.BOOL
        self._show = user32.ShowWindow
        self._show.argtypes = [wintypes.HWND, ctypes.c_int]
        self._show.restype = wintypes.BOOL

    def foreground_window(self) -> int:
        return self._api.foreground_window()

    def window_class(self, hwnd: int) -> str:
        return self._api.window_class(hwnd)

    def window_pid(self, hwnd: int) -> int:
        return self._api.window_pid(hwnd)

    def process_exe(self, pid: int) -> Optional[str]:
        return self._api.process_exe(pid)

    def child_exes(self, hwnd: int) -> "list[str]":
        """The exe base names (lower case) of the processes that own the child windows of ``hwnd``."""
        pids: "set[int]" = set()

        @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
        def collect(child, _lparam):  # Win32 callback
            pids.add(self._api.window_pid(int(child or 0)))
            return True

        self._enum_children(hwnd, collect, 0)
        exes = (self._api.process_exe(pid) for pid in pids)
        return [os.path.basename(exe).lower() for exe in exes if exe]

    def explorer_folder(self, hwnd: int) -> Optional[str]:
        """The folder shown by the Explorer window ``hwnd`` (``Shell.Application().Windows()``, matched by HWND), or None.
        comtypes is imported here, in the hub thread (which has COM initialised), never at module level."""
        import comtypes.client
        shell = comtypes.client.CreateObject("Shell.Application", dynamic=True)
        windows = shell.Windows()
        for i in range(int(windows.Count)):
            try:
                window = windows.Item(i)
                if int(window.HWND) != hwnd:
                    continue
                try:
                    return str(window.Document.Folder.Self.Path)
                except Exception:  # noqa: BLE001 - fall back on the URL of the window
                    url = urlparse(str(window.LocationURL))
                    return unquote(url.path).lstrip("/").replace("/", "\\") if url.scheme == "file" else None
            except Exception:  # noqa: BLE001 - a window that went away while it was read
                continue
        return None

    def minimize(self, hwnd: int) -> None:
        self._show(hwnd, SW_MINIMIZE)


def _version_key(folder: str) -> "tuple[int, ...]":
    return tuple(int(x) for x in re.findall(r"\d+", folder))


class LaunchersProvider:
    def __init__(self, env: Optional[dict] = None, fs: Any = None, registry: Optional[Callable[[str], bool]] = None,
                 launcher: Any = None, icons: Any = None, downloads: Optional[Callable[[], Optional[str]]] = None,
                 clock: Callable[[], float] = time.monotonic, log: Optional[Callable[[str], None]] = None,
                 packages: Optional[Callable[[str], "list[str]"]] = None, windows: Any = None) -> None:
        self._env = env if env is not None else os.environ
        self._fs = fs if fs is not None else RealFs()
        self._registry = registry or protocol_registered
        self._launcher = launcher if launcher is not None else RealLauncher()
        self._icons = icons
        self._downloads = downloads or downloads_folder
        self._packages = packages or store_package_roots  # Store package name prefix -> its root folders
        self._windows = windows  # created on first use when None (the real one needs no window until a tap)
        self._clock = clock
        self._log = log or _log.info
        self._found: Optional[dict] = None
        self._found_at = 0.0

    # --- detection (cached 60 s) ---

    def _detect(self) -> dict:
        now = self._clock()
        if self._found is None or now - self._found_at >= CACHE_S:
            self._found = {"discord": self._find_discord(), "spotify": self._find_spotify()}
            self._found_at = now
        return self._found

    def _join(self, var: str, *parts: str) -> Optional[str]:
        base = self._env.get(var)
        return os.path.join(base, *parts) if base else None

    def _find_discord(self) -> Optional[dict]:
        updater = self._join("LOCALAPPDATA", "Discord", "Update.exe")
        if updater and self._fs.isfile(updater):
            folder = os.path.dirname(updater)
            exe = updater  # the icon: the newest app-<version>\\Discord.exe, else the updater itself
            try:
                versions = sorted((d for d in self._fs.listdir(folder) if d.lower().startswith("app-")),
                                  key=_version_key, reverse=True)
            except OSError:
                versions = []
            for version in versions:
                candidate = os.path.join(folder, version, "Discord.exe")
                if self._fs.isfile(candidate):
                    exe = candidate
                    break
            return {"command": [updater, "--processStart", "Discord.exe"], "icon": exe}
        if self._registry("discord"):
            return {"uri": "discord://", "icon": None}
        return None

    def _find_spotify(self) -> Optional[dict]:
        exe = self._join("APPDATA", "Spotify", "Spotify.exe")
        if exe and self._fs.isfile(exe):
            return {"command": [exe], "icon": exe}
        store_exe = self._store_spotify_exe()  # the Store version: launched by protocol, its exe only gives the icon
        if store_exe or self._registry("spotify"):
            return {"uri": "spotify:", "icon": store_exe}
        return None

    def _store_spotify_exe(self) -> Optional[str]:
        try:
            for root in self._packages(SPOTIFY_PACKAGE):
                exe = os.path.join(root, "Spotify.exe")
                if self._fs.isfile(exe):
                    return exe
        except Exception as e:  # noqa: BLE001 - no registry answer means no icon, not a failed snapshot
            self._log(f"launchers: Store package lookup failed ({type(e).__name__}: {e})")
        return None

    # --- provider API ---

    def snapshot(self) -> dict:
        found = self._detect()
        icons = {}
        for name in ("discord", "spotify"):
            entry = found[name]
            icons[name] = self._icon_id(entry["icon"]) if entry and entry["icon"] else None
        return {"settings": True, "discord": found["discord"] is not None, "spotify": found["spotify"] is not None,
                "downloads": True, "icons": icons}

    def artwork_bytes(self, icon_id: Optional[str]) -> Optional[bytes]:
        return self._icon_provider().artwork_bytes(icon_id) if icon_id else None

    def handle(self, action: dict) -> Optional[str]:
        if action.get("id") != LAUNCH_ID:
            self._log(f"launchers: unknown action {action.get('id')!r}")
            return None
        target = action.get("target")
        if not isinstance(target, str) or target not in TARGETS:
            self._log(f"launchers: target {target!r} ignored, only {', '.join(TARGETS)} are allowed")
            return None
        try:
            if self._open(target):
                return None
        except Exception as e:  # noqa: BLE001 - OSError from the launch, anything unexpected
            self._log(f"launchers: {target} failed to start ({type(e).__name__}: {e})")
            return APP_NOT_FOUND
        self._log(f"launchers: {target} is not installed")
        return APP_NOT_FOUND

    # --- the closed list of commands ---

    def _open(self, target: str) -> bool:
        if self._minimize_if_in_front(target):
            return True
        if target == "settings":
            self._launcher.startfile("ms-settings:")
            return True
        if target == "downloads":
            folder = self._downloads()
            if not folder or not self._fs.isdir(folder):
                return False
            self._launcher.popen(["explorer.exe", folder])
            return True
        self._found = None  # an explicit tap looks again: the app may have been installed since
        entry = self._detect()[target]
        if entry is None:
            return False
        if "command" in entry:
            self._launcher.popen(list(entry["command"]))
        else:
            self._launcher.startfile(entry["uri"])
        return True

    # --- open, then minimize ---

    def _minimize_if_in_front(self, target: str) -> bool:
        """Minimize the target's window when it is the PC foreground window; True when that was done. Every failure of the
        detection answers False: the caller launches the app as it always did."""
        try:
            if self._windows is None:
                self._windows = RealWindows()
            hwnd = self._windows.foreground_window()
            if not hwnd or not self._is_target_window(target, hwnd):
                return False
            self._windows.minimize(hwnd)
            return True
        except Exception as e:  # noqa: BLE001 - COM, ctypes, anything: launching is the safe answer
            self._log(f"launchers: foreground check of {target} failed ({type(e).__name__}: {e})")
            return False

    def _is_target_window(self, target: str, hwnd: int) -> bool:
        windows = self._windows
        window_class = windows.window_class(hwnd)
        exe = os.path.basename(windows.process_exe(windows.window_pid(hwnd)) or "").lower()
        if target in PROCESS_OF:
            return exe == PROCESS_OF[target]
        if target == "settings":
            if exe == SETTINGS_EXE:
                return True
            return window_class == "ApplicationFrameWindow" and SETTINGS_EXE in windows.child_exes(hwnd)
        if target == "downloads":
            folder = self._downloads()
            return window_class == "CabinetWClass" and _same_path(windows.explorer_folder(hwnd), folder)
        return False

    # --- icons ---

    def _icon_provider(self) -> Any:
        if self._icons is None:
            from actions.app_icons import AppIconProvider
            self._icons = AppIconProvider(log=self._log)
        return self._icons

    def _icon_id(self, path: str) -> Optional[str]:
        from actions import context_profiles
        from actions.foreground import ForegroundApp
        app = ForegroundApp(os.path.basename(path), "", "", 0, 0, path)
        try:
            return self._icon_provider().icon_id(app, context_profiles.profile_by_id("generic"), None)
        except Exception as e:  # noqa: BLE001 - a tile without its icon is still a tile
            self._log(f"launchers: icon of {path} unavailable ({type(e).__name__}: {e})")
            return None
