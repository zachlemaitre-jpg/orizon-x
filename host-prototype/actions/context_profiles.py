"""The context bar's profiles (spec 2026-10-13 §4): for each app in front on the PC, the buttons the device shows and
the keyboard shortcut each one sends. ``match(app)`` picks the profile, ``display_name(app, lang)`` the name shown.

Button ids are unique across profiles (``ppt.next``...), so a ``context.press`` can be checked against the active
profile. ``icon`` is one of ICON_NAMES (the Android side has a drawable per name and a neutral dot for the rest);
each button has an English and a French label (``label(lang)``), the language being the device's. Shortcuts use the syntax of actions.keys. VS Code's terminal
(Ctrl+`) and comment (Ctrl+/) shortcuts are written by key position (OEM_3, OEM_2): VS Code binds them to the key,
so resolving the character through the layout would send Ctrl+Alt+7 / Ctrl+Shift+: on an AZERTY keyboard.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from actions.foreground import ForegroundApp, short_title

ICON_NAMES = frozenset({
    "arrow_left", "arrow_right", "arrow_up", "refresh",
    "play_pause", "skip_previous", "skip_next", "heart", "shuffle", "repeat", "slideshow", "slideshow_current",
    "screen_black", "exit",
    "tab_new", "tab_close", "zoom_out", "zoom_in",
    "undo", "redo", "bold", "italic", "underline", "save", "sum", "filter", "copy", "paste",
    "command", "search", "terminal", "comment", "folder_new", "rename", "explorer",
    "screenshot", "desktop", "switch_app",
})

LANGS = ("en", "fr")
DEFAULT_LANG = "fr"  # a missing or unknown language gives French, the historical behaviour
DEFAULT_APP_NAME = {"en": "App", "fr": "Application"}


@dataclass(frozen=True)
class Button:
    id: str
    icon: str
    labels: dict  # {"en": ..., "fr": ...}
    shortcut: str

    def label(self, lang: str) -> str:
        return self.labels.get(lang) or self.labels[DEFAULT_LANG]


@dataclass(frozen=True)
class Profile:
    id: str
    exes: tuple  # lower-case exe names; empty for the generic profile
    buttons: tuple
    window_class: Optional[str] = None  # when set, the window must have this class too


def _b(id: str, icon: str, en: str, fr: str, shortcut: str) -> Button:
    return Button(id, icon, {"en": en, "fr": fr}, shortcut)


PROFILES = (
    Profile("spotify", ("spotify.exe",), (
        _b("spotify.prev", "skip_previous", "Previous", "Précédent", "Ctrl+Left"),
        _b("spotify.playpause", "play_pause", "Play/Pause", "Lecture/Pause", "Space"),
        _b("spotify.next", "skip_next", "Next", "Suivant", "Ctrl+Right"),
        _b("spotify.like", "heart", "Like", "J'aime", "Alt+Shift+B"),
        _b("spotify.shuffle", "shuffle", "Shuffle", "Aléatoire", "Ctrl+S"),
        _b("spotify.repeat", "repeat", "Repeat", "Répéter", "Ctrl+R"),
    )),
    Profile("powerpoint", ("powerpnt.exe",), (
        _b("ppt.slideshow", "slideshow", "Slideshow", "Diaporama", "F5"),
        _b("ppt.from_current", "slideshow_current", "From slide", "Depuis la diapo", "Shift+F5"),
        _b("ppt.prev", "arrow_left", "Previous", "Précédent", "Left"),
        _b("ppt.next", "arrow_right", "Next", "Suivant", "Right"),
        _b("ppt.black", "screen_black", "Black screen", "Écran noir", "B"),
        _b("ppt.exit", "exit", "Exit", "Quitter", "Esc"),
    )),
    Profile("browser", ("chrome.exe", "msedge.exe", "firefox.exe", "brave.exe", "opera.exe"), (
        _b("web.back", "arrow_left", "Back", "Retour", "Alt+Left"),
        _b("web.forward", "arrow_right", "Forward", "Avance", "Alt+Right"),
        _b("web.reload", "refresh", "Reload", "Actualiser", "F5"),
        _b("web.new_tab", "tab_new", "New tab", "Nouvel onglet", "Ctrl+T"),
        _b("web.close_tab", "tab_close", "Close tab", "Fermer l'onglet", "Ctrl+W"),
        _b("web.zoom_out", "zoom_out", "Zoom −", "Zoom −", "Ctrl+-"),
        _b("web.zoom_in", "zoom_in", "Zoom +", "Zoom +", "Ctrl+="),
    )),
    Profile("word", ("winword.exe",), (
        _b("word.undo", "undo", "Undo", "Annuler", "Ctrl+Z"),
        _b("word.redo", "redo", "Redo", "Rétablir", "Ctrl+Y"),
        _b("word.bold", "bold", "Bold", "Gras", "Ctrl+B"),
        _b("word.italic", "italic", "Italic", "Italique", "Ctrl+I"),
        _b("word.underline", "underline", "Underline", "Souligné", "Ctrl+U"),
        _b("word.save", "save", "Save", "Enregistrer", "Ctrl+S"),
    )),
    Profile("excel", ("excel.exe",), (
        _b("xl.undo", "undo", "Undo", "Annuler", "Ctrl+Z"),
        _b("xl.redo", "redo", "Redo", "Rétablir", "Ctrl+Y"),
        _b("xl.bold", "bold", "Bold", "Gras", "Ctrl+B"),
        _b("xl.sum", "sum", "AutoSum", "Somme auto", "Alt+="),
        _b("xl.filter", "filter", "Filter", "Filtre", "Ctrl+Shift+L"),
        _b("xl.save", "save", "Save", "Enregistrer", "Ctrl+S"),
    )),
    Profile("vscode", ("code.exe",), (
        _b("code.palette", "command", "Palette", "Palette", "Ctrl+Shift+P"),
        _b("code.search", "search", "Search", "Rechercher", "Ctrl+Shift+F"),
        _b("code.terminal", "terminal", "Terminal", "Terminal", "Ctrl+OEM_3"),
        _b("code.comment", "comment", "Comment", "Commenter", "Ctrl+OEM_2"),
        _b("code.save", "save", "Save", "Enregistrer", "Ctrl+S"),
        _b("code.explorer", "explorer", "Explorer", "Explorateur", "Ctrl+Shift+E"),
    )),
    Profile("explorer", ("explorer.exe",), (
        _b("exp.back", "arrow_left", "Back", "Retour", "Alt+Left"),
        _b("exp.up", "arrow_up", "Up", "Dossier parent", "Alt+Up"),
        _b("exp.new_folder", "folder_new", "New folder", "Nouveau dossier", "Ctrl+Shift+N"),
        _b("exp.rename", "rename", "Rename", "Renommer", "F2"),
        _b("exp.reload", "refresh", "Refresh", "Actualiser", "F5"),
    ), window_class="CabinetWClass"),
    Profile("generic", (), (
        _b("gen.copy", "copy", "Copy", "Copier", "Ctrl+C"),
        _b("gen.paste", "paste", "Paste", "Coller", "Ctrl+V"),
        _b("gen.undo", "undo", "Undo", "Annuler", "Ctrl+Z"),
        _b("gen.screenshot", "screenshot", "Screenshot", "Capture", "Win+Shift+S"),
        _b("gen.desktop", "desktop", "Desktop", "Bureau", "Win+D"),
        _b("gen.switch", "switch_app", "Switch app", "Changer d'app", "Alt+Tab"),
    )),
)

_GENERIC = PROFILES[-1]
_BY_ID = {p.id: p for p in PROFILES}

_FIXED_NAMES = {
    "spotify": "Spotify", "powerpoint": "PowerPoint", "word": "Word", "excel": "Excel", "vscode": "VS Code",
}
_NAMES_BY_LANG = {  # the names that vary with the language
    "explorer": {"en": "Explorer", "fr": "Explorateur"},
    "browser": {"en": "Browser", "fr": "Navigateur"},  # a browser we do not know by name
}
_BROWSER_NAMES = {
    "chrome.exe": "Chrome", "msedge.exe": "Edge", "firefox.exe": "Firefox", "brave.exe": "Brave",
    "opera.exe": "Opera",
}


def profile_by_id(profile_id: str) -> Optional[Profile]:
    return _BY_ID.get(profile_id)


def match(app: Optional[ForegroundApp]) -> Profile:
    """The profile of an app (generic for an unknown one or none)."""
    if app is None:
        return _GENERIC
    exe = app.exe.lower()
    for profile in PROFILES:
        if exe in profile.exes and (profile.window_class is None or app.window_class == profile.window_class):
            return profile
    return _GENERIC


def normalize_lang(lang: object) -> str:
    return lang if lang in LANGS else DEFAULT_LANG


def display_name(app: Optional[ForegroundApp], lang: str = DEFAULT_LANG) -> str:
    """The name shown on the bar: fixed for the known apps, the browser's own name, else the window's short title,
    else the exe without ".exe". ``lang`` ("en" or "fr") picks the names that vary and the default name."""
    lang = normalize_lang(lang)
    profile = match(app)
    if app is not None:
        if profile.id == "browser":
            return _BROWSER_NAMES.get(app.exe.lower()) or _NAMES_BY_LANG["browser"][lang]
        if profile.id in _FIXED_NAMES:
            return _FIXED_NAMES[profile.id]
        if profile.id in _NAMES_BY_LANG:
            return _NAMES_BY_LANG[profile.id][lang]
        title = short_title(app.title)
        if title:
            return title
        exe = app.exe[:-4] if app.exe.lower().endswith(".exe") else app.exe
        if exe.strip():
            return exe.strip()
    return DEFAULT_APP_NAME[lang]
