"""'Lancer avec Windows': the HKCU Run value is the single source of truth."""
from __future__ import annotations

import sys

RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
VALUE_NAME = "OrizonX"


def supported() -> bool:
    """Only the packaged exe can be registered (a source checkout has no stable executable)."""
    return bool(getattr(sys, "frozen", False))


def command_for(exe: str) -> str:
    return f'"{exe}" --minimized'


def registered_command(key_path: str = RUN_KEY) -> str | None:
    import winreg
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_path) as key:
            value, _kind = winreg.QueryValueEx(key, VALUE_NAME)
            return value
    except FileNotFoundError:
        return None


def is_enabled(key_path: str = RUN_KEY) -> bool:
    return registered_command(key_path) is not None


def enable(exe: str, key_path: str = RUN_KEY) -> None:
    import winreg
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, key_path) as key:
        winreg.SetValueEx(key, VALUE_NAME, 0, winreg.REG_SZ, command_for(exe))


def disable(key_path: str = RUN_KEY) -> None:
    import winreg
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_path, 0, winreg.KEY_SET_VALUE) as key:
            winreg.DeleteValue(key, VALUE_NAME)
    except FileNotFoundError:
        pass
