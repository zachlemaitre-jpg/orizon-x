"""The context bar's profiles (spec 2026-10-13 §4, creative apps 2026-10-19 §2): for each app in front on the PC, the
buttons the device shows and the keyboard shortcut each one sends. ``match(app)`` picks the profile,
``display_name(app, lang)`` the name shown.

A profile has one to four pages (``Page``: id, labels, up to 8 buttons) that the device shows as tabs; the existing
profiles have a single page ``main``, which the device does not label. ``Profile.buttons`` is every button of every
page, in order (``context.press`` checks a button against it). The creative profiles (Illustrator, Photoshop, Canva,
Figma) are picked by exe; Canva and Figma are also picked in a browser whose window title mentions them.

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
    # creative apps (spec 2026-10-19 §4)
    "select", "direct_select", "pen", "text", "rectangle", "ellipse", "line", "brush", "eraser", "eyedropper",
    "crop", "lasso", "marquee", "move", "frame",
    "group", "ungroup", "lock", "unlock", "layer_new", "layer_duplicate", "merge", "deselect", "transform",
    "component", "hide", "paste_front",
    "hand", "zoom_fit", "zoom_100", "zoom_selection", "outline", "rulers", "brush_smaller", "brush_larger", "present",
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
class Page:
    id: str
    labels: dict  # {"en": ..., "fr": ...}
    buttons: tuple

    def label(self, lang: str) -> str:
        return self.labels.get(lang) or self.labels[DEFAULT_LANG]


@dataclass(frozen=True)
class Profile:
    id: str
    exes: tuple  # lower-case exe names; empty for the generic profile
    pages: tuple  # one to MAX_PAGES Page
    window_class: Optional[str] = None  # when set, the window must have this class too

    @property
    def buttons(self) -> tuple:
        """Every button of every page, in order."""
        return tuple(b for page in self.pages for b in page.buttons)


MAX_PAGES = 4
MAX_BUTTONS_PER_PAGE = 8


def _b(id: str, icon: str, en: str, fr: str, shortcut: str) -> Button:
    return Button(id, icon, {"en": en, "fr": fr}, shortcut)


def _page(id: str, en: str, fr: str, *buttons: Button) -> Page:
    return Page(id, {"en": en, "fr": fr}, tuple(buttons))


def _single(id: str, exes: tuple, buttons: tuple, window_class: Optional[str] = None) -> Profile:
    """A profile of one page ``main`` (never labelled on the device, which hides the tabs of a single page)."""
    return Profile(id, exes, (_page("main", "Main", "Principal", *buttons),), window_class)


def _tools(*buttons: Button) -> Page:
    return _page("tools", "Tools", "Outils", *buttons)


def _edit(*buttons: Button) -> Page:
    return _page("edit", "Edit", "Édition", *buttons)


def _view(*buttons: Button) -> Page:
    return _page("view", "View", "Affichage", *buttons)


PROFILES = (
    _single("spotify", ("spotify.exe",), (
        _b("spotify.prev", "skip_previous", "Previous", "Précédent", "Ctrl+Left"),
        _b("spotify.playpause", "play_pause", "Play/Pause", "Lecture/Pause", "Space"),
        _b("spotify.next", "skip_next", "Next", "Suivant", "Ctrl+Right"),
        _b("spotify.like", "heart", "Like", "J'aime", "Alt+Shift+B"),
        _b("spotify.shuffle", "shuffle", "Shuffle", "Aléatoire", "Ctrl+S"),
        _b("spotify.repeat", "repeat", "Repeat", "Répéter", "Ctrl+R"),
    )),
    _single("powerpoint", ("powerpnt.exe",), (
        _b("ppt.slideshow", "slideshow", "Slideshow", "Diaporama", "F5"),
        _b("ppt.from_current", "slideshow_current", "From slide", "Depuis la diapo", "Shift+F5"),
        _b("ppt.prev", "arrow_left", "Previous", "Précédent", "Left"),
        _b("ppt.next", "arrow_right", "Next", "Suivant", "Right"),
        _b("ppt.black", "screen_black", "Black screen", "Écran noir", "B"),
        _b("ppt.exit", "exit", "Exit", "Quitter", "Esc"),
    )),
    _single("browser", ("chrome.exe", "msedge.exe", "firefox.exe", "brave.exe", "opera.exe"), (
        _b("web.back", "arrow_left", "Back", "Retour", "Alt+Left"),
        _b("web.forward", "arrow_right", "Forward", "Avance", "Alt+Right"),
        _b("web.reload", "refresh", "Reload", "Actualiser", "F5"),
        _b("web.new_tab", "tab_new", "New tab", "Nouvel onglet", "Ctrl+T"),
        _b("web.close_tab", "tab_close", "Close tab", "Fermer l'onglet", "Ctrl+W"),
        _b("web.zoom_out", "zoom_out", "Zoom −", "Zoom −", "Ctrl+-"),
        _b("web.zoom_in", "zoom_in", "Zoom +", "Zoom +", "Ctrl+="),
    )),
    _single("word", ("winword.exe",), (
        _b("word.undo", "undo", "Undo", "Annuler", "Ctrl+Z"),
        _b("word.redo", "redo", "Redo", "Rétablir", "Ctrl+Y"),
        _b("word.bold", "bold", "Bold", "Gras", "Ctrl+B"),
        _b("word.italic", "italic", "Italic", "Italique", "Ctrl+I"),
        _b("word.underline", "underline", "Underline", "Souligné", "Ctrl+U"),
        _b("word.save", "save", "Save", "Enregistrer", "Ctrl+S"),
    )),
    _single("excel", ("excel.exe",), (
        _b("xl.undo", "undo", "Undo", "Annuler", "Ctrl+Z"),
        _b("xl.redo", "redo", "Redo", "Rétablir", "Ctrl+Y"),
        _b("xl.bold", "bold", "Bold", "Gras", "Ctrl+B"),
        _b("xl.sum", "sum", "AutoSum", "Somme auto", "Alt+="),
        _b("xl.filter", "filter", "Filter", "Filtre", "Ctrl+Shift+L"),
        _b("xl.save", "save", "Save", "Enregistrer", "Ctrl+S"),
    )),
    _single("vscode", ("code.exe",), (
        _b("code.palette", "command", "Palette", "Palette", "Ctrl+Shift+P"),
        _b("code.search", "search", "Search", "Rechercher", "Ctrl+Shift+F"),
        _b("code.terminal", "terminal", "Terminal", "Terminal", "Ctrl+OEM_3"),
        _b("code.comment", "comment", "Comment", "Commenter", "Ctrl+OEM_2"),
        _b("code.save", "save", "Save", "Enregistrer", "Ctrl+S"),
        _b("code.explorer", "explorer", "Explorer", "Explorateur", "Ctrl+Shift+E"),
    )),
    _single("explorer", ("explorer.exe",), (
        _b("exp.back", "arrow_left", "Back", "Retour", "Alt+Left"),
        _b("exp.up", "arrow_up", "Up", "Dossier parent", "Alt+Up"),
        _b("exp.new_folder", "folder_new", "New folder", "Nouveau dossier", "Ctrl+Shift+N"),
        _b("exp.rename", "rename", "Rename", "Renommer", "F2"),
        _b("exp.reload", "refresh", "Refresh", "Actualiser", "F5"),
    ), window_class="CabinetWClass"),
    Profile("illustrator", ("illustrator.exe",), (
        _tools(
            _b("ai.select", "select", "Selection", "Sélection", "V"),
            _b("ai.direct_select", "direct_select", "Direct selection", "Sélection directe", "A"),
            _b("ai.pen", "pen", "Pen", "Plume", "P"),
            _b("ai.text", "text", "Type", "Texte", "T"),
            _b("ai.rectangle", "rectangle", "Rectangle", "Rectangle", "M"),
            _b("ai.ellipse", "ellipse", "Ellipse", "Ellipse", "L"),
            _b("ai.brush", "brush", "Brush", "Pinceau", "B"),
            _b("ai.eyedropper", "eyedropper", "Eyedropper", "Pipette", "I"),
        ),
        _edit(
            _b("ai.undo", "undo", "Undo", "Annuler", "Ctrl+Z"),
            _b("ai.redo", "redo", "Redo", "Rétablir", "Shift+Ctrl+Z"),
            _b("ai.group", "group", "Group", "Grouper", "Ctrl+G"),
            _b("ai.ungroup", "ungroup", "Ungroup", "Dissocier", "Shift+Ctrl+G"),
            _b("ai.paste_front", "paste_front", "Paste in front", "Coller devant", "Ctrl+F"),
            _b("ai.lock", "lock", "Lock", "Verrouiller", "Ctrl+2"),
            _b("ai.unlock", "unlock", "Unlock all", "Tout déverrouiller", "Ctrl+Alt+2"),
            _b("ai.save", "save", "Save", "Enregistrer", "Ctrl+S"),
        ),
        _view(
            _b("ai.hand", "hand", "Hand", "Main", "H"),
            _b("ai.zoom", "search", "Zoom", "Zoom", "Z"),
            _b("ai.zoom_fit", "zoom_fit", "Fit", "Ajuster", "Ctrl+0"),
            _b("ai.zoom_100", "zoom_100", "100 %", "100 %", "Ctrl+1"),
            _b("ai.zoom_out", "zoom_out", "Zoom −", "Zoom −", "Ctrl+-"),
            _b("ai.zoom_in", "zoom_in", "Zoom +", "Zoom +", "Ctrl+="),
            _b("ai.outline", "outline", "Outline", "Tracés", "Ctrl+Y"),
            _b("ai.rulers", "rulers", "Rulers", "Règles", "Ctrl+R"),
        ),
    )),
    Profile("photoshop", ("photoshop.exe",), (
        _tools(
            _b("ps.move", "move", "Move", "Déplacement", "V"),
            _b("ps.marquee", "marquee", "Marquee", "Rectangle de sélection", "M"),
            _b("ps.lasso", "lasso", "Lasso", "Lasso", "L"),
            _b("ps.brush", "brush", "Brush", "Pinceau", "B"),
            _b("ps.eraser", "eraser", "Eraser", "Gomme", "E"),
            _b("ps.crop", "crop", "Crop", "Recadrage", "C"),
            _b("ps.text", "text", "Type", "Texte", "T"),
            _b("ps.eyedropper", "eyedropper", "Eyedropper", "Pipette", "I"),
        ),
        _edit(
            _b("ps.undo", "undo", "Undo", "Annuler", "Ctrl+Z"),
            _b("ps.redo", "redo", "Redo", "Rétablir", "Shift+Ctrl+Z"),
            _b("ps.deselect", "deselect", "Deselect", "Désélectionner", "Ctrl+D"),
            _b("ps.transform", "transform", "Transform", "Transformer", "Ctrl+T"),
            _b("ps.layer_new", "layer_new", "New layer", "Nouveau calque", "Shift+Ctrl+N"),
            _b("ps.layer_duplicate", "layer_duplicate", "Duplicate layer", "Dupliquer le calque", "Ctrl+J"),
            _b("ps.merge", "merge", "Merge down", "Fusionner", "Ctrl+E"),
            _b("ps.save", "save", "Save", "Enregistrer", "Ctrl+S"),
        ),
        _view(
            _b("ps.hand", "hand", "Hand", "Main", "H"),
            _b("ps.zoom", "search", "Zoom", "Zoom", "Z"),
            _b("ps.zoom_fit", "zoom_fit", "Fit", "Ajuster", "Ctrl+0"),
            _b("ps.zoom_100", "zoom_100", "100 %", "100 %", "Ctrl+1"),
            _b("ps.zoom_out", "zoom_out", "Zoom −", "Zoom −", "Ctrl+-"),
            _b("ps.zoom_in", "zoom_in", "Zoom +", "Zoom +", "Ctrl+="),
            _b("ps.brush_smaller", "brush_smaller", "Brush −", "Pinceau −", "OEM_4"),
            _b("ps.brush_larger", "brush_larger", "Brush +", "Pinceau +", "OEM_6"),
        ),
    )),
    Profile("canva", ("canva.exe",), (
        _tools(
            _b("canva.text", "text", "Text", "Texte", "T"),
            _b("canva.rectangle", "rectangle", "Rectangle", "Rectangle", "R"),
            _b("canva.ellipse", "ellipse", "Circle", "Cercle", "C"),
            _b("canva.line", "line", "Line", "Ligne", "L"),
        ),
        _edit(
            _b("canva.undo", "undo", "Undo", "Annuler", "Ctrl+Z"),
            _b("canva.redo", "redo", "Redo", "Rétablir", "Ctrl+Y"),
            _b("canva.duplicate", "copy", "Duplicate", "Dupliquer", "Ctrl+D"),
            _b("canva.group", "group", "Group", "Grouper", "Ctrl+G"),
            _b("canva.ungroup", "ungroup", "Ungroup", "Dissocier", "Ctrl+Shift+G"),
            _b("canva.lock", "lock", "Lock", "Verrouiller", "Alt+Shift+L"),
        ),
        _view(
            _b("canva.zoom_out", "zoom_out", "Zoom −", "Zoom −", "Ctrl+-"),
            _b("canva.zoom_in", "zoom_in", "Zoom +", "Zoom +", "Ctrl+="),
            _b("canva.zoom_fit", "zoom_fit", "Fit", "Ajuster", "Ctrl+Alt+0"),
            _b("canva.present", "present", "Present", "Présenter", "Ctrl+Alt+P"),
        ),
    )),
    Profile("figma", ("figma.exe",), (
        _tools(
            _b("figma.move", "move", "Move", "Déplacer", "V"),
            _b("figma.frame", "frame", "Frame", "Cadre", "F"),
            _b("figma.rectangle", "rectangle", "Rectangle", "Rectangle", "R"),
            _b("figma.ellipse", "ellipse", "Ellipse", "Ellipse", "O"),
            _b("figma.line", "line", "Line", "Ligne", "L"),
            _b("figma.pen", "pen", "Pen", "Plume", "P"),
            _b("figma.text", "text", "Text", "Texte", "T"),
            _b("figma.comment", "comment", "Comment", "Commentaire", "C"),
        ),
        _edit(
            _b("figma.undo", "undo", "Undo", "Annuler", "Ctrl+Z"),
            _b("figma.redo", "redo", "Redo", "Rétablir", "Ctrl+Shift+Z"),
            _b("figma.duplicate", "copy", "Duplicate", "Dupliquer", "Ctrl+D"),
            _b("figma.group", "group", "Group", "Grouper", "Ctrl+G"),
            _b("figma.ungroup", "ungroup", "Ungroup", "Dissocier", "Ctrl+Shift+G"),
            _b("figma.component", "component", "Component", "Composant", "Ctrl+Alt+K"),
            _b("figma.hide", "hide", "Hide", "Masquer", "Ctrl+Shift+H"),
        ),
        _view(
            _b("figma.zoom_out", "zoom_out", "Zoom −", "Zoom −", "-"),
            _b("figma.zoom_in", "zoom_in", "Zoom +", "Zoom +", "="),
            _b("figma.zoom_fit", "zoom_fit", "Fit", "Ajuster", "Shift+1"),
            _b("figma.zoom_selection", "zoom_selection", "Selection", "Sélection", "Shift+2"),
            _b("figma.zoom_100", "zoom_100", "100 %", "100 %", "Shift+0"),
            _b("figma.rulers", "rulers", "Rulers", "Règles", "Shift+R"),
            _b("figma.outline", "outline", "Outline", "Contours", "Ctrl+Y"),
        ),
    )),
    _single("generic", (), (
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
_WEB_TITLES = ("canva", "figma")  # profile ids that a browser window title can pick (the id is the word looked for)

_FIXED_NAMES = {
    "spotify": "Spotify", "powerpoint": "PowerPoint", "word": "Word", "excel": "Excel", "vscode": "VS Code",
    "illustrator": "Illustrator", "photoshop": "Photoshop", "canva": "Canva", "figma": "Figma",
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
    """The profile of an app (generic for an unknown one or none). In a browser, a window title that mentions Canva
    or Figma (case-insensitive) picks that profile; the title of any other window is never looked at."""
    if app is None:
        return _GENERIC
    exe = app.exe.lower()
    for profile in PROFILES:
        if exe in profile.exes and (profile.window_class is None or app.window_class == profile.window_class):
            if profile.id == "browser":
                title = app.title.lower()
                for web_id in _WEB_TITLES:
                    if web_id in title:
                        return _BY_ID[web_id]
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
