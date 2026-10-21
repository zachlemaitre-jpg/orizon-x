"""Bring an Explorer folder window to the front after the hub opened it (USB drive blocks, Downloads tile).

The hub runs in a background process, so Windows' foreground lock keeps the Explorer window it just started from
activating: the folder opens BEHIND the other windows. The fix has three parts, all best effort:

1. ``FolderFront.prepare()`` right BEFORE opening: an Alt tap (Windows then treats us as the user's input process) and
   ``AllowSetForegroundWindow(ASFW_ANY)``, so Explorer may take the foreground itself;
2. open the folder (``os.startfile`` / ``explorer.exe``);
3. ``bring_folder_to_front``: poll ``FolderFront.find(path)`` (a visible ``CabinetWClass`` window whose folder is
   ``path``, compared normalised and case-insensitively; a drive root ``E:\\`` matches) for up to ``timeout_s``, stop at
   the first hit, and raise it (``FolderFront.raise_``: restore if minimized, ``SetForegroundWindow``, on refusal an Alt
   tap and one retry) unless it is already the foreground window.

``open_folder_to_front`` chains the three. Nothing here raises: a failure is logged once and the open itself still
counts as a success. The Win32 layer (``front``: prepare, find, foreground, raise_) and ``sleep`` are injectable, so the
tests never press a key, open a folder or move a real window. comtypes is imported lazily, in the hub thread (which has
COM initialised).

``WindowRaiser`` holds the restore / foreground / Alt-tap primitives, shared with the Claude app's ``Win32Focus``.
"""
from __future__ import annotations

import ctypes
import os
from ctypes import wintypes
from typing import Any, Callable, Optional
from urllib.parse import unquote, urlparse

ASFW_ANY = -1
EXPLORER_CLASS = "CabinetWClass"
WAIT_S = 3.0
STEP_S = 0.1


class WindowRaiser:
    """restore / SetForegroundWindow / Alt tap on user32."""

    SW_RESTORE = 9
    VK_MENU = 0x12
    KEYEVENTF_KEYUP = 0x0002

    def __init__(self) -> None:
        self._u = u = ctypes.WinDLL("user32", use_last_error=True)
        u.IsIconic.argtypes = [wintypes.HWND]
        u.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
        u.SetForegroundWindow.argtypes = [wintypes.HWND]
        u.keybd_event.argtypes = [wintypes.BYTE, wintypes.BYTE, wintypes.DWORD, ctypes.c_size_t]

    def is_iconic(self, hwnd: int) -> bool:
        return bool(self._u.IsIconic(hwnd))

    def restore(self, hwnd: int) -> None:
        self._u.ShowWindow(hwnd, self.SW_RESTORE)

    def set_foreground(self, hwnd: int) -> bool:
        return bool(self._u.SetForegroundWindow(hwnd))

    def alt_tap(self) -> None:
        self._u.keybd_event(self.VK_MENU, 0, 0, 0)
        self._u.keybd_event(self.VK_MENU, 0, self.KEYEVENTF_KEYUP, 0)


def explorer_folders() -> "dict[int, str]":
    """HWND -> folder path of every Explorer window (``Shell.Application().Windows()``). A window that went away or whose
    folder cannot be read is left out. comtypes is imported here, never at module level."""
    import comtypes.client
    shell = comtypes.client.CreateObject("Shell.Application", dynamic=True)
    windows = shell.Windows()
    found: "dict[int, str]" = {}
    for i in range(int(windows.Count)):
        try:
            window = windows.Item(i)
            hwnd = int(window.HWND)
            try:
                found[hwnd] = str(window.Document.Folder.Self.Path)
            except Exception:  # noqa: BLE001 - fall back on the URL of the window
                url = urlparse(str(window.LocationURL))
                if url.scheme == "file":
                    found[hwnd] = unquote(url.path).lstrip("/").replace("/", "\\")
        except Exception:  # noqa: BLE001 - a window that went away while it was read
            continue
    return found


def same_path(a: Optional[str], b: Optional[str]) -> bool:
    return bool(a and b) and os.path.normcase(os.path.normpath(a)) == os.path.normcase(os.path.normpath(b))


class FolderFront:
    """The real layer: user32 through ``WindowRaiser`` and ``foreground.Win32Api``, Explorer through COM."""

    def __init__(self) -> None:
        from actions.foreground import Win32Api
        self._api = Win32Api()
        self._raiser = WindowRaiser()
        self._allow = self._raiser._u.AllowSetForegroundWindow
        self._allow.argtypes = [wintypes.DWORD]
        self._allow.restype = wintypes.BOOL
        self._visible = self._raiser._u.IsWindowVisible
        self._visible.argtypes = [wintypes.HWND]
        self._visible.restype = wintypes.BOOL

    def prepare(self) -> None:
        """Right before opening the folder: Explorer may take the foreground itself."""
        self._raiser.alt_tap()
        self._allow(ASFW_ANY)

    def find(self, path: str) -> int:
        """The visible Explorer window showing ``path``, 0 when there is none."""
        for hwnd, folder in explorer_folders().items():
            if same_path(folder, path) and self._visible(hwnd) and self._api.window_class(hwnd) == EXPLORER_CLASS:
                return hwnd
        return 0

    def foreground(self) -> int:
        return self._api.foreground_window()

    def raise_(self, hwnd: int) -> bool:
        """Restore if minimized, bring to the front; on refusal an Alt tap and one retry. True when it took."""
        if self._raiser.is_iconic(hwnd):
            self._raiser.restore(hwnd)
        if self._raiser.set_foreground(hwnd):
            return True
        self._raiser.alt_tap()  # Windows refuses focus changes from a background process unless a key was just pressed
        return self._raiser.set_foreground(hwnd)


def ensure_front(front: Any, log: Callable[[str], None]) -> Any:
    """``front``, or the real one when None; None (nothing raised) when it cannot be built."""
    if front is not None:
        return front
    try:
        return FolderFront()
    except Exception as e:  # noqa: BLE001 - not Windows, user32 unavailable: the folder still opens
        log(f"folder front: unavailable ({type(e).__name__}: {e})")
        return None


def bring_folder_to_front(path: str, front: Any, sleep: Callable[[float], None], timeout_s: float = WAIT_S,
                          step_s: float = STEP_S, log: Optional[Callable[[str], None]] = None) -> bool:
    """After ``path`` was opened: wait (polling, at most ``timeout_s``) for its Explorer window, then raise it. True when
    the window is in front at the end. Never raises; a failure is logged once."""
    log = log or (lambda _line: None)
    try:
        hwnd = front.find(path)
        for _ in range(max(0, int(timeout_s / step_s))):
            if hwnd:
                break
            sleep(step_s)
            hwnd = front.find(path)
        if not hwnd:
            log(f"folder front: no Explorer window for {path} after {timeout_s:g} s")
            return False
        if front.foreground() == hwnd:
            return True
        if front.raise_(hwnd):
            return True
        log(f"folder front: Windows refused to bring {path} to the front")
        return False
    except Exception as e:  # noqa: BLE001 - COM, ctypes, anything: the folder is open, that is what counts
        log(f"folder front: {path}: {type(e).__name__}: {e}")
        return False


def open_folder_to_front(path: str, opener: Callable[[], None], front: Any, sleep: Callable[[float], None],
                         log: Optional[Callable[[str], None]] = None) -> None:
    """``front.prepare()``, ``opener()``, then ``bring_folder_to_front``. Whatever ``opener`` raises propagates (the open
    failed); the front steps never do. ``front`` None means only ``opener()``."""
    log = log or (lambda _line: None)
    if front is not None:
        try:
            front.prepare()
        except Exception as e:  # noqa: BLE001
            log(f"folder front: prepare failed ({type(e).__name__}: {e})")
    opener()
    if front is not None:
        bring_folder_to_front(path, front, sleep, log=log)
