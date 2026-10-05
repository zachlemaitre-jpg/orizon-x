"""Finds the external tools (ffmpeg, adb) and runs them without a console window.

In the packaged app they sit in tools/ next to OrizonX.exe; in development they come from the PATH or the
Android SDK.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Callable

# Sans ce drapeau, chaque appel à adb ou ffmpeg depuis l'exe graphique ouvre une console qui clignote.
NO_WINDOW = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0

_EXE = ".exe" if os.name == "nt" else ""

_MISSING = {
    "ffmpeg": "ffmpeg introuvable. Recompile l'appli (build-pc.ps1) ou installe ffmpeg (winget install Gyan.FFmpeg).",
    "adb": "adb introuvable. Recompile l'appli (build-pc.ps1) ou installe Android platform-tools.",
}


class ToolMissing(Exception):
    """A required tool is nowhere to be found; the message tells the user what to do."""


def app_dir() -> Path:
    """Folder of OrizonX.exe when packaged, of this file in development."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


def sdk_platform_tools() -> Path:
    local = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
    return Path(local) / "Android" / "Sdk" / "platform-tools"


def find_tool(name: str, *, bundled_dir: Path | None = None, sdk_dir: Path | None = None,
              which: Callable[[str], str | None] = shutil.which) -> str:
    """Path of ffmpeg or adb, or ToolMissing.

    ffmpeg: the bundled copy first (the version we tested). adb: the installed one first, because two adb versions
    on one PC keep killing each other's server; the bundled copy is the last resort.
    """
    if name not in _MISSING:
        raise ValueError(f"outil inconnu : {name}")
    bundled = (bundled_dir if bundled_dir is not None else app_dir() / "tools") / f"{name}{_EXE}"
    if name == "ffmpeg":
        candidates = [bundled, which(name)]
    else:
        sdk = (sdk_dir if sdk_dir is not None else sdk_platform_tools()) / f"{name}{_EXE}"
        candidates = [which(name), sdk, bundled]
    for candidate in candidates:
        if candidate and Path(candidate).is_file():
            return str(candidate)
    raise ToolMissing(_MISSING[name])
