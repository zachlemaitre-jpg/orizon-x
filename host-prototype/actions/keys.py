"""Keyboard shortcuts as synthetic input (SendInput), shared by the media keys and the context bar.

``send_shortcut("Ctrl+Shift+P")`` presses the modifiers in order, then the key, then releases in reverse order, all
in ONE ``SendInput`` call so that nothing the user types can interleave. Everything is in virtual-key codes.

Shortcut syntax: names joined by ``+``, case-insensitive, spaces around names tolerated. Modifiers: Ctrl (Control),
Alt, Shift, Win. The last name is the key: a letter, a digit, F1..F24, a named key (Space, Esc, Enter, Tab,
Backspace, Delete, Insert, Home, End, PageUp, PageDown, Left, Right, Up, Down) or ONE punctuation character
(``+ - = / ` , . ;`` ...). ``+`` itself is written ``Ctrl++`` or ``+``. ``OEM_1``..``OEM_8``, ``OEM_102``,
``OEM_PLUS``/``MINUS``/``COMMA``/``PERIOD`` name a key by its position (US virtual key), whatever the layout.

Punctuation depends on the keyboard layout, so it goes through ``VkKeyScanW`` (the active layout, AZERTY included):
it gives the virtual key and the modifiers the layout needs to type that character; those that the shortcut does
not already hold are pressed too (an AltGr character thus becomes Ctrl+Alt+key). A character the layout lacks is a
``ValueError``, and nothing is sent. Arrows, Insert/Delete/Home/End/Page keys and Win carry KEYEVENTF_EXTENDEDKEY.
"""
from __future__ import annotations

import ctypes
from ctypes import wintypes
from typing import Callable, Optional

INPUT_KEYBOARD = 1
KEYEVENTF_EXTENDEDKEY = 0x0001
KEYEVENTF_KEYUP = 0x0002

VK_SHIFT = 0x10
VK_CONTROL = 0x11
VK_MENU = 0x12  # Alt
VK_LWIN = 0x5B

_SHIFT_BIT, _CTRL_BIT, _ALT_BIT = 1, 2, 4  # high byte of VkKeyScanW


class MOUSEINPUT(ctypes.Structure):
    _fields_ = [
        ("dx", wintypes.LONG),
        ("dy", wintypes.LONG),
        ("mouseData", wintypes.DWORD),
        ("dwFlags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ctypes.c_size_t),
    ]


class KEYBDINPUT(ctypes.Structure):
    _fields_ = [
        ("wVk", wintypes.WORD),
        ("wScan", wintypes.WORD),
        ("dwFlags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ctypes.c_size_t),
    ]


class HARDWAREINPUT(ctypes.Structure):
    _fields_ = [("uMsg", wintypes.DWORD), ("wParamL", wintypes.WORD), ("wParamH", wintypes.WORD)]


class _INPUT_UNION(ctypes.Union):
    _fields_ = [("mi", MOUSEINPUT), ("ki", KEYBDINPUT), ("hi", HARDWAREINPUT)]


class INPUT(ctypes.Structure):
    _fields_ = [("type", wintypes.DWORD), ("u", _INPUT_UNION)]


SendInputFn = Callable[[int, "ctypes.Array[INPUT]", int], int]
VkScanFn = Callable[[str], int]


def default_send_input() -> SendInputFn:
    api = ctypes.WinDLL("user32", use_last_error=True).SendInput
    api.argtypes = [wintypes.UINT, ctypes.POINTER(INPUT), ctypes.c_int]
    api.restype = wintypes.UINT
    return api


def default_vk_scan() -> VkScanFn:
    api = ctypes.WinDLL("user32", use_last_error=True).VkKeyScanW
    api.argtypes = [wintypes.WCHAR]
    api.restype = ctypes.c_short

    def scan(ch: str) -> int:
        return int(api(ch))
    return scan


def key_events(vk_flags: "list[tuple[int, int]]") -> "ctypes.Array[INPUT]":
    """A SendInput array for (virtual key, dwFlags) pairs."""
    events = (INPUT * len(vk_flags))()
    for event, (vk, flags) in zip(events, vk_flags):
        event.type = INPUT_KEYBOARD
        event.u.ki = KEYBDINPUT(wVk=vk, wScan=0, dwFlags=flags, time=0, dwExtraInfo=0)
    return events


_MODIFIERS = {
    "ctrl": VK_CONTROL, "control": VK_CONTROL,
    "alt": VK_MENU,
    "shift": VK_SHIFT,
    "win": VK_LWIN,
}
_EXTENDED = {0x21, 0x22, 0x23, 0x24, 0x25, 0x26, 0x27, 0x28, 0x2D, 0x2E, VK_LWIN}
_NAMED = {
    "space": 0x20, "esc": 0x1B, "escape": 0x1B, "enter": 0x0D, "return": 0x0D, "tab": 0x09,
    "backspace": 0x08, "delete": 0x2E, "del": 0x2E, "insert": 0x2D,
    "home": 0x24, "end": 0x23, "pageup": 0x21, "pagedown": 0x22,
    "left": 0x25, "up": 0x26, "right": 0x27, "down": 0x28,
    # keys by POSITION (US virtual-key names), independent of the layout: for the apps that bind a shortcut to the
    # key rather than to the character (VS Code: Ctrl+OEM_3 is Ctrl+` on a US keyboard, Ctrl+ù on AZERTY)
    "oem_1": 0xBA, "oem_plus": 0xBB, "oem_comma": 0xBC, "oem_minus": 0xBD, "oem_period": 0xBE, "oem_2": 0xBF,
    "oem_3": 0xC0, "oem_4": 0xDB, "oem_5": 0xDC, "oem_6": 0xDD, "oem_7": 0xDE, "oem_8": 0xDF, "oem_102": 0xE2,
}


def _flags_for(vk: int) -> int:
    return KEYEVENTF_EXTENDEDKEY if vk in _EXTENDED else 0


def _split(shortcut: str) -> "tuple[list[str], str]":
    if not isinstance(shortcut, str) or not shortcut.strip():
        raise ValueError(f"empty shortcut: {shortcut!r}")
    text = shortcut.strip()
    if text == "+" or text.endswith("++"):
        key, rest = "+", text[:-1].rstrip()
        mods = rest[:-1] if rest.endswith("+") else rest  # "Ctrl+" -> "Ctrl"
        return ([m.strip() for m in mods.split("+")] if mods else []), key
    parts = [p.strip() for p in text.split("+")]
    if any(not p for p in parts):
        raise ValueError(f"malformed shortcut: {shortcut!r}")
    return parts[:-1], parts[-1]


def parse_shortcut(shortcut: str, vk_scan: Optional[VkScanFn] = None) -> "list[tuple[int, int]]":
    """The (virtual key, dwFlags) sequence of a shortcut: modifiers down, key down, key up, modifiers up (reversed).
    Raises ValueError for anything it cannot map."""
    mod_names, key_name = _split(shortcut)
    mods: list[int] = []
    for name in mod_names:
        vk = _MODIFIERS.get(name.lower())
        if vk is None:
            raise ValueError(f"unknown modifier {name!r} in {shortcut!r}")
        if vk in mods:
            raise ValueError(f"modifier {name!r} repeated in {shortcut!r}")
        mods.append(vk)

    lower = key_name.lower()
    if lower in _MODIFIERS:
        raise ValueError(f"{shortcut!r} has no key, only modifiers")
    if lower in _NAMED:
        key = _NAMED[lower]
    elif len(key_name) == 1 and key_name.isascii() and key_name.isalnum():
        key = ord(key_name.upper())  # VK_A..VK_Z / VK_0..VK_9 equal the ASCII codes
    elif lower.startswith("f") and lower[1:].isdigit() and 1 <= int(lower[1:]) <= 24:
        key = 0x70 + int(lower[1:]) - 1
    elif len(key_name) == 1 and not key_name.isspace():
        scanned = (vk_scan or default_vk_scan())(key_name)
        if scanned == -1 or scanned & 0xFF == 0xFF:
            raise ValueError(f"the keyboard layout has no key for {key_name!r} ({shortcut!r})")
        key = scanned & 0xFF
        state = (scanned >> 8) & 0xFF
        for bit, vk in ((_SHIFT_BIT, VK_SHIFT), (_CTRL_BIT, VK_CONTROL), (_ALT_BIT, VK_MENU)):
            if state & bit and vk not in mods:
                mods.append(vk)
    else:
        raise ValueError(f"unknown key {key_name!r} in {shortcut!r}")

    down = [(vk, _flags_for(vk)) for vk in mods] + [(key, _flags_for(key))]
    up = [(vk, flags | KEYEVENTF_KEYUP) for vk, flags in reversed(down)]
    return down + up


def send_shortcut(shortcut: str, send_input: Optional[SendInputFn] = None,
                  vk_scan: Optional[VkScanFn] = None) -> bool:
    """Press a shortcut. True when every event was injected, False otherwise (e.g. blocked by UIPI);
    ValueError, with nothing sent, for a shortcut that cannot be parsed."""
    sequence = parse_shortcut(shortcut, vk_scan)
    events = key_events(sequence)
    send = send_input or default_send_input()
    return send(len(events), events, ctypes.sizeof(INPUT)) == len(events)
