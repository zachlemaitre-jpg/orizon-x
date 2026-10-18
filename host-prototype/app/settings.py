"""User settings of the PC app, stored as JSON in %APPDATA%\\OrizonX\\settings.json."""
from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass
from pathlib import Path

from frame.session import INTERVALS
from messages import LANGUAGES

ENCODERS = ("auto", "nvenc", "amf", "qsv", "x264")
MODES = ("extend", "duplicate")  # Extend : écran virtuel ; Duplicate : écran principal
POSITIONS = ("right", "left", "above", "below")  # côté de l'écran principal où se place l'écran virtuel
SCALES = ("auto", "100", "125", "150", "175", "200", "225", "250")  # "auto" : selon la densité de la tablette
FRAME_INTERVALS = INTERVALS  # secondes par image du Tableau : 5 s .. 1 h
FRAME_FITS = ("crop", "fit")  # Crop remplit l'écran, Fit montre l'image entière


@dataclass
class Settings:
    encoder: str = "auto"
    mode: str = "extend"
    position: str = "right"
    scale: str = "auto"
    # Position et échelle que Windows a reçues pour l'écran virtuel (il s'en souvient ensuite) ; None : jamais.
    # Différentes de position/scale : changées hors flux, appliquées à la prochaine apparition de l'écran.
    applied_position: str | None = None
    applied_scale: str | None = None
    first_close_hint_shown: bool = False  # bulle « Orizon X tourne toujours » déjà montrée
    language: str | None = None  # None : la langue choisie à l'installation (registre), sinon l'anglais
    frame_folder: str | None = None  # dossier montré par un appareil en rôle Tableau ; None : aucun
    frame_interval_s: int = 30
    frame_fit: str = "crop"


def default_path() -> Path:
    roaming = os.environ.get("APPDATA") or str(Path.home() / "AppData" / "Roaming")
    return Path(roaming) / "OrizonX" / "settings.json"


def load(path: Path) -> Settings:
    """Never fails: a missing or broken file gives the defaults, a bad field only resets that field.

    Unknown fields are ignored, e.g. "output" (screen choice) from versions before the virtual display. The older
    boolean "layout_applied" (true: the saved position and scale were applied) is read when there is no valid
    applied_position/applied_scale pair.
    """
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return Settings()
    result = Settings()
    if not isinstance(raw, dict):
        return result
    for name, allowed in (("encoder", ENCODERS), ("mode", MODES), ("position", POSITIONS), ("scale", SCALES)):
        value = raw.get(name)
        if isinstance(value, str) and value in allowed:
            setattr(result, name, value)
    applied = (raw.get("applied_position"), raw.get("applied_scale"))
    if applied[0] in POSITIONS and applied[1] in SCALES:
        result.applied_position, result.applied_scale = applied
    elif raw.get("layout_applied") is True:
        result.applied_position, result.applied_scale = result.position, result.scale
    value = raw.get("first_close_hint_shown")
    if isinstance(value, bool):
        result.first_close_hint_shown = value
    language = raw.get("language")
    if language in LANGUAGES:
        result.language = language
    folder = raw.get("frame_folder")
    if isinstance(folder, str) and folder:
        result.frame_folder = folder
    interval = raw.get("frame_interval_s")
    if isinstance(interval, int) and not isinstance(interval, bool) and interval in FRAME_INTERVALS:
        result.frame_interval_s = interval
    fit = raw.get("frame_fit")
    if isinstance(fit, str) and fit in FRAME_FITS:
        result.frame_fit = fit
    return result


def save(settings: Settings, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + ".tmp")
    temp.write_text(json.dumps(asdict(settings), indent=2), encoding="utf-8")
    os.replace(temp, path)  # atomique : jamais de fichier à moitié écrit
