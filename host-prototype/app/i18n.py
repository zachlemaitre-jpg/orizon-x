"""The app's current language and the signal that makes the window and the tray switch live."""
from __future__ import annotations

from PySide6.QtCore import QObject, Signal

from messages import LANGUAGES, Msg, detect_language, msg, tr

__all__ = ["LANGUAGES", "Msg", "current_language", "detect_language", "language_changed", "msg", "set_language",
           "tr"]


class _Signals(QObject):
    language_changed = Signal(str)


_signals = _Signals()  # au niveau du module : vit aussi longtemps que l'appli
language_changed = _signals.language_changed
_current: str | None = None


def current_language() -> str:
    """The language in use. main() sets it from the settings at start-up; until then, the installer's choice."""
    global _current
    if _current is None:
        _current = detect_language(None)  # pas encore de réglage lu : HKCU, puis HKLM, puis l'anglais
    return _current


def set_language(lang: str) -> None:
    """Switches every text of the app; emits language_changed only when the language really changes."""
    global _current
    if lang not in LANGUAGES:
        raise ValueError(f"unknown language: {lang}")
    if lang == _current:
        return
    _current = lang
    language_changed.emit(lang)
