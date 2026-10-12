"""Runs this app again as administrator (one UAC prompt) and waits for it: "Add exact resolution" (no Qt here).

The elevated process is `OrizonX.exe --add-resolution WxH` (app/admin.py): it edits the VDD XML and restarts the
device. ShellExecuteExW with the "runas" verb shows the UAC prompt; SEE_MASK_NOCLOSEPROCESS gives the process handle
to wait for its exit code. Refusing the prompt fails with ERROR_CANCELLED.
"""
from __future__ import annotations

import ctypes
import os
import subprocess
import sys
import time
from ctypes import wintypes
from pathlib import Path
from typing import Any, Callable

SW_HIDE = 0
SEE_MASK_NOCLOSEPROCESS = 0x00000040
SEE_MASK_NOASYNC = 0x00000100
ERROR_SUCCESS_REBOOT_REQUIRED = 3010  # --add-resolution worked, Windows only wants a restart to finish: a success
ERROR_CANCELLED = 1223  # l'utilisateur a refusé l'invite UAC
WAIT_OBJECT_0 = 0
WAIT_FAILED = 0xFFFFFFFF
ADMIN_TIMEOUT_S = 180.0  # pnputil /restart-device prend quelques secondes ; au-delà, quelque chose est bloqué
READY_TIMEOUT_S = 20.0  # le pilote redémarré répond de nouveau au PING
READY_POLL_S = 0.5
SCRIPT = Path(__file__).resolve().parents[1] / "orizonx_pc.py"


class SHELLEXECUTEINFOW(ctypes.Structure):
    _fields_ = [("cbSize", wintypes.DWORD), ("fMask", wintypes.ULONG), ("hwnd", wintypes.HWND),
                ("lpVerb", wintypes.LPCWSTR), ("lpFile", wintypes.LPCWSTR), ("lpParameters", wintypes.LPCWSTR),
                ("lpDirectory", wintypes.LPCWSTR), ("nShow", ctypes.c_int), ("hInstApp", wintypes.HINSTANCE),
                ("lpIDList", ctypes.c_void_p), ("lpClass", wintypes.LPCWSTR), ("hkeyClass", wintypes.HKEY),
                ("dwHotKey", wintypes.DWORD), ("hIconOrMonitor", wintypes.HANDLE), ("hProcess", wintypes.HANDLE)]


class Win32Shell:
    """The four Win32 calls run_as_admin needs (tests replace this object)."""

    def __init__(self) -> None:
        shell32 = ctypes.WinDLL("shell32", use_last_error=True)
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        self._execute = shell32.ShellExecuteExW
        self._execute.argtypes = [ctypes.POINTER(SHELLEXECUTEINFOW)]
        self._execute.restype = wintypes.BOOL
        self._wait = kernel32.WaitForSingleObject
        self._wait.argtypes = [wintypes.HANDLE, wintypes.DWORD]
        self._wait.restype = wintypes.DWORD
        self._exit_code = kernel32.GetExitCodeProcess
        self._exit_code.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
        self._exit_code.restype = wintypes.BOOL
        self._close = kernel32.CloseHandle
        self._close.argtypes = [wintypes.HANDLE]
        self._close.restype = wintypes.BOOL

    def shell_execute(self, verb: str, file: str, parameters: str, show: int,
                      hwnd: int | None = None) -> tuple[Any, int]:
        """(process handle or None, Windows error code). hwnd: owner window, so the UAC prompt comes to the front."""
        info = SHELLEXECUTEINFOW()
        info.cbSize = ctypes.sizeof(info)
        info.fMask = SEE_MASK_NOCLOSEPROCESS | SEE_MASK_NOASYNC
        info.hwnd = hwnd
        info.lpVerb = verb
        info.lpFile = file
        info.lpParameters = parameters
        info.nShow = show
        if not self._execute(ctypes.byref(info)):
            return None, ctypes.get_last_error()
        return info.hProcess, 0

    def wait(self, process: Any, timeout_ms: int) -> bool:
        """True once the process has ended, False on timeout; OSError if the wait itself failed."""
        result = self._wait(process, timeout_ms)
        if result == WAIT_FAILED:
            raise ctypes.WinError(ctypes.get_last_error())
        return result == WAIT_OBJECT_0

    def exit_code(self, process: Any) -> int:
        code = wintypes.DWORD()
        if not self._exit_code(process, ctypes.byref(code)):
            raise ctypes.WinError(ctypes.get_last_error())
        return code.value

    def close(self, process: Any) -> None:
        self._close(process)


def self_command(arguments: list[str], *, frozen: bool | None = None, executable: str | None = None,
                 script: str | os.PathLike | None = None,
                 exists: Callable[[str], bool] = os.path.exists) -> tuple[str, str]:
    """(file, parameters) that run this app with `arguments`: the exe when packaged, else Python + orizonx_pc.py."""
    frozen = bool(getattr(sys, "frozen", False)) if frozen is None else frozen
    executable = executable or sys.executable
    if frozen:
        return executable, subprocess.list2cmdline(arguments)
    # pythonw quand il existe : pas de console qui clignote derrière l'invite UAC.
    windowless = str(Path(executable).with_name("pythonw.exe"))
    file = windowless if Path(executable).name.lower() == "python.exe" and exists(windowless) else executable
    return file, subprocess.list2cmdline([str(script or SCRIPT), *arguments])


def run_as_admin(file: str, parameters: str, *, hwnd: int | None = None, api: Any = None,
                 timeout_s: float = ADMIN_TIMEOUT_S) -> int | None:
    """Runs `file parameters` elevated and hidden, waits for it, returns its exit code; None if UAC was refused.

    hwnd: the app's main window, owner of the UAC prompt (brought to the front instead of blinking in the taskbar).
    Raises OSError if it could not be launched or gave no process handle to wait for, TimeoutError if it is still
    running after timeout_s.
    """
    api = api or Win32Shell()
    process, error = api.shell_execute("runas", file, parameters, SW_HIDE, hwnd)
    if not process:
        if error == ERROR_CANCELLED:
            return None
        if error == 0:
            raise OSError("ShellExecuteExW succeeded but gave no process handle: the administrator process "
                          "cannot be waited for")
        raise OSError(error, f"ShellExecuteExW failed (Windows error {error})")
    try:
        if not api.wait(process, int(timeout_s * 1000)):
            raise TimeoutError(f"the administrator process is still running after {timeout_s:.0f} s")
        return api.exit_code(process)
    finally:
        api.close(process)


def _driver_ready() -> bool:
    import vdd
    return vdd.VddController().is_installed()


def add_resolution(width: int, height: int, *, hwnd: int | None = None,
                   run: Callable[..., int | None] = run_as_admin,
                   driver_ready: Callable[[], bool] = _driver_ready, sleep: Callable[[float], None] = time.sleep,
                   clock: Callable[[], float] = time.monotonic,
                   command: Callable[[list[str]], tuple[str, str]] = self_command) -> int | None:
    """One UAC prompt (owned by the window `hwnd`): `--add-resolution WxH` as admin. Blocking (worker thread).

    Returns the admin process's exit code (0 = added and device restarted), or None if UAC was refused. After a
    success, waits (up to READY_TIMEOUT_S) for the restarted driver to answer PING again, so that the engine
    restarted next does not report "driver not found" while it is still coming back.
    """
    file, parameters = command(["--add-resolution", f"{width}x{height}"])
    code = run(file, parameters, hwnd=hwnd)
    if code == ERROR_SUCCESS_REBOOT_REQUIRED:
        code = 0
    if code == 0:
        deadline = clock() + READY_TIMEOUT_S
        while not driver_ready() and clock() < deadline:
            sleep(READY_POLL_S)
    return code
