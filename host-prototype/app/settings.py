"""User settings of the PC app, stored as JSON in %APPDATA%\\OrizonX\\settings.json."""
from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass
from pathlib import Path

ENCODERS = ("auto", "nvenc", "amf")


@dataclass
class Settings:
    output: str = "auto"  # "auto" ou un index ddagrab
    encoder: str = "auto"
    first_close_hint_shown: bool = False  # bulle « Orizon X tourne toujours » déjà montrée


def default_path() -> Path:
    roaming = os.environ.get("APPDATA") or str(Path.home() / "AppData" / "Roaming")
    return Path(roaming) / "OrizonX" / "settings.json"


def load(path: Path) -> Settings:
    """Never fails: a missing or broken file gives the defaults, a bad field only resets that field."""
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return Settings()
    result = Settings()
    if not isinstance(raw, dict):
        return result
    output = raw.get("output")
    if isinstance(output, str) and (output == "auto" or output.isdigit()):
        result.output = output
    encoder = raw.get("encoder")
    if encoder in ENCODERS:
        result.encoder = encoder
    hint = raw.get("first_close_hint_shown")
    if isinstance(hint, bool):
        result.first_close_hint_shown = hint
    return result


def save(settings: Settings, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + ".tmp")
    temp.write_text(json.dumps(asdict(settings), indent=2), encoding="utf-8")
    os.replace(temp, path)  # atomique : jamais de fichier à moitié écrit
