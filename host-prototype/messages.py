"""User-facing texts in English and French, shared by the engine, the CLI and the app (no Qt here).

The engine never builds sentences: it emits a Msg (key + arguments) and whoever shows it picks the language.
"""
from __future__ import annotations

import re
from types import MappingProxyType
from typing import Any, Callable, Mapping, NamedTuple

LANGUAGES = ("en", "fr")
DEFAULT_LANGUAGE = "en"
REGISTRY_KEY = r"Software\OrizonX"
REGISTRY_VALUE = "Language"

TEXTS: dict[str, dict[str, str]] = {
    # --- détails d'état du moteur ---
    "state.preparing_capture": {"en": "Preparing the capture…", "fr": "Préparation de la capture…"},
    "state.waiting_app": {"en": "Tablet plugged in. Open Orizon X on it.",
                          "fr": "Tablette branchée : ouvre Orizon X dessus."},
    "state.preparing_display": {"en": "Preparing the screen…", "fr": "Préparation de l'écran…"},
    "state.starting_stream": {"en": "Starting the stream…", "fr": "Démarrage du flux…"},
    "state.streaming": {"en": "Stream {width}×{height}", "fr": "Flux {width}×{height}"},
    "state.stopped": {"en": "Stopped.", "fr": "Arrêté."},
    # --- adb ---
    "adb.timeout": {"en": "adb is not responding (timed out).", "fr": "adb ne répond pas (délai dépassé)."},
    "adb.failed": {"en": "adb is not responding: {error}", "fr": "adb ne répond pas : {error}"},
    "adb.no_device": {"en": "No tablet found. Plug in the USB cable and turn on USB debugging.",
                      "fr": "Aucune tablette détectée : branche le câble USB et active le débogage USB."},
    "adb.unauthorized": {"en": "Tablet not authorized. Accept the USB debugging prompt on the tablet.",
                         "fr": "Tablette non autorisée : accepte la demande de débogage USB sur l'écran de la tablette."},
    "adb.not_exactly_one": {"en": "Exactly one ready tablet is needed. Current state: {states}",
                            "fr": "Il faut exactement une tablette prête. État actuel : {states}"},
    "adb.forward_failed": {"en": "adb forward failed: {error}", "fr": "adb forward a échoué : {error}"},
    # --- écrans capturables ---
    "outputs.none": {"en": "No capturable screen (ffmpeg/ddagrab unavailable?)",
                     "fr": "Aucun écran capturable (ffmpeg/ddagrab indisponible ?)"},
    "outputs.line": {"en": "--output {index}: {width}x{height}", "fr": "--output {index} : {width}x{height}"},
    "outputs.line_unknown": {"en": "--output {index}: unknown size", "fr": "--output {index} : taille inconnue"},
    "outputs.list": {
        "en": "{lines}\nOnly screens on the default GPU are listed "
              "(on a hybrid laptop, screens plugged into the other GPU do not appear).",
        "fr": "{lines}\nSeuls les écrans du GPU par défaut sont listés "
              "(sur un portable hybride, ceux branchés sur l'autre GPU n'apparaissent pas).",
    },
    # --- erreurs fatales ---
    "error.no_matching_screen": {
        "en": "No screen at {width}x{height} (the tablet's size). Set the virtual display to this resolution, "
              "or pick another screen (Screen setting in the app, --output N on the command line):\n{outputs}",
        "fr": "Aucun écran en {width}x{height} (taille de la tablette). Règle l'écran virtuel à cette résolution, "
              "ou choisis un autre écran (réglage Écran dans l'appli, --output N en ligne de commande) :\n{outputs}",
    },
    "error.no_encoder": {"en": "No H.264 hardware encoder (AMF/NVENC) available.",
                         "fr": "Aucun encodeur matériel H.264 (AMF/NVENC) disponible."},
    "error.ffmpeg_keeps_stopping": {"en": "ffmpeg keeps stopping ({count} times in a row). Last message: {last}",
                                    "fr": "ffmpeg s'arrête sans cesse ({count} fois de suite). Dernier message : {last}"},
    "error.no_message": {"en": "no message", "fr": "aucun message"},
    "error.unexpected_first_message": {"en": "Unexpected first message from the tablet: {message}",
                                       "fr": "Premier message inattendu de la tablette : {message}"},
    "error.protocol_mismatch": {"en": "Incompatible protocol: tablet v{tablet}, PC v{pc}. Update the app or the relay.",
                                "fr": "Protocole incompatible : tablette v{tablet}, PC v{pc}. "
                                      "Mets à jour l'app ou le relais."},
    "error.unexpected": {"en": "Unexpected error: {error}", "fr": "Erreur inattendue : {error}"},
    # --- écran virtuel (VDD) ---
    "display.vdd_missing": {
        "en": "Virtual display driver not found. Reinstall Orizon X, or switch to Duplicate mode.",
        "fr": "Pilote d'écran virtuel introuvable. Réinstalle Orizon X, ou passe en mode Dupliquer.",
    },
    "display.timeout": {
        "en": "The virtual screen did not appear. Try again, or switch to Duplicate mode.",
        "fr": "L'écran virtuel n'est pas apparu. Réessaie, ou passe en mode Dupliquer.",
    },
    "display.no_mode": {
        "en": "The virtual screen has no resolution that fits the tablet ({width}×{height}). Reinstall Orizon X.",
        "fr": "L'écran virtuel n'a aucune résolution adaptée à la tablette ({width}×{height}). Réinstalle Orizon X.",
    },
    "display.not_capturable": {
        "en": "The virtual screen ({width}×{height}) is not among the screens that can be captured. "
              "Switch to Duplicate mode, or reinstall Orizon X:\n{outputs}",
        "fr": "L'écran virtuel ({width}×{height}) ne fait pas partie des écrans capturables. "
              "Passe en mode Dupliquer, ou réinstalle Orizon X :\n{outputs}",
    },
    "display.activate_failed": {
        "en": "Windows could not turn on the virtual screen: {error}",
        "fr": "Windows n'a pas pu allumer l'écran virtuel : {error}",
    },
    # --- outils externes ---
    "tools.ffmpeg_missing": {
        "en": "ffmpeg not found. Rebuild the app (build-pc.ps1) or install ffmpeg (winget install Gyan.FFmpeg).",
        "fr": "ffmpeg introuvable. Recompile l'appli (build-pc.ps1) ou installe ffmpeg (winget install Gyan.FFmpeg).",
    },
    "tools.adb_missing": {
        "en": "adb not found. Rebuild the app (build-pc.ps1) or install Android platform-tools.",
        "fr": "adb introuvable. Recompile l'appli (build-pc.ps1) ou installe Android platform-tools.",
    },
    # --- titres d'état et bouton principal (fenêtre et zone de notification) ---
    "status.stopped": {"en": "Stopped", "fr": "Arrêté"},
    "status.waiting_device": {"en": "Waiting for the tablet", "fr": "En attente de la tablette"},
    "status.waiting_app": {"en": "Open Orizon X on the tablet", "fr": "Ouvre Orizon X sur la tablette"},
    "status.preparing_display": {"en": "Preparing the screen", "fr": "Préparation de l'écran"},
    "status.streaming": {"en": "Connected", "fr": "Connecté"},
    "status.error": {"en": "Error", "fr": "Erreur"},
    "status.click_start": {"en": "Click Start.", "fr": "Clique sur Démarrer."},
    "button.stop": {"en": "Stop", "fr": "Arrêter"},
    "button.start": {"en": "Start", "fr": "Démarrer"},
    "button.retry": {"en": "Retry", "fr": "Réessayer"},
    "button.quit": {"en": "Quit", "fr": "Quitter"},
    "button.use_duplicate": {"en": "Use Duplicate", "fr": "Passer en Dupliquer"},
    "button.add_resolution": {"en": "Add exact resolution", "fr": "Ajouter la résolution exacte"},
    # --- fenêtre ---
    "window.minimize": {"en": "Minimize", "fr": "Réduire"},
    "window.close": {"en": "Close (Orizon X keeps running in the notification area)",
                     "fr": "Fermer (Orizon X continue dans la zone de notification)"},
    "window.mode": {"en": "Mode", "fr": "Mode"},
    "window.mode_extend": {"en": "Extend", "fr": "Étendre"},
    "window.mode_duplicate": {"en": "Duplicate", "fr": "Dupliquer"},
    "window.position": {"en": "Position", "fr": "Position"},
    "window.position_right": {"en": "Right", "fr": "À droite"},
    "window.position_left": {"en": "Left", "fr": "À gauche"},
    "window.position_above": {"en": "Above", "fr": "Au-dessus"},
    "window.position_below": {"en": "Below", "fr": "En dessous"},
    "window.scale": {"en": "Scale", "fr": "Échelle"},
    "window.scale_percent": {"en": "{percent}%", "fr": "{percent} %"},
    "window.auto": {"en": "Auto", "fr": "Auto"},
    "window.encoder": {"en": "Encoder", "fr": "Encodeur"},
    "window.language": {"en": "Language", "fr": "Langue"},
    "window.adjust_in_windows": {"en": "Adjust in Windows…", "fr": "Régler dans Windows…"},
    "window.adjust_in_windows_tip": {"en": "Open Windows display settings",
                                     "fr": "Ouvrir les paramètres d'affichage de Windows"},
    "window.add_resolution_tip": {
        "en": "Adds {width}×{height} to the virtual screen (asks for administrator rights). "
              "The tablet reconnects by itself.",
        "fr": "Ajoute {width}×{height} à l'écran virtuel (demande les droits administrateur). "
              "La tablette se reconnecte toute seule.",
    },
    # --- zone de notification ---
    "tray.open_window": {"en": "Open window", "fr": "Ouvrir la fenêtre"},
    "tray.open_log": {"en": "Open log", "fr": "Ouvrir le journal"},
    "tray.autostart": {"en": "Start with Windows", "fr": "Lancer avec Windows"},
    "tray.autostart_unavailable": {"en": "Available in the built app (OrizonX.exe)",
                                   "fr": "Disponible dans l'appli compilée (OrizonX.exe)"},
    "tray.quit": {"en": "Quit", "fr": "Quitter"},
    "tray.still_running_title": {"en": "Orizon X is still running", "fr": "Orizon X tourne toujours"},
    "tray.resolution_title": {"en": "Exact resolution", "fr": "Résolution exacte"},
    "tray.resolution_refused": {"en": "Administrator rights were refused: the tablet keeps its black bars.",
                                "fr": "Droits administrateur refusés : la tablette garde ses bandes noires."},
    "tray.resolution_failed": {"en": "The resolution could not be added. See the log.",
                               "fr": "La résolution n'a pas pu être ajoutée. Voir le journal."},
    "tray.still_running_text": {"en": "The stream continues. Click the Orizon X icon to open the window again.",
                                "fr": "Le flux continue. Clique sur l'icône Orizon X pour rouvrir la fenêtre."},
}

_NO_ARGS: Mapping[str, Any] = MappingProxyType({})


def tr(key: str, lang: str = DEFAULT_LANGUAGE, **args: Any) -> str:
    """The text of `key` in `lang` (English if `lang` is unknown). Strict: an unknown key or argument raises KeyError.

    A Msg argument is translated in the same language; a list or tuple argument gives one line per item.
    """
    texts = TEXTS[key]
    template = texts.get(lang, texts[DEFAULT_LANGUAGE])
    return template.format(**{name: _render(value, lang) for name, value in args.items()})


def _render(value: Any, lang: str) -> Any:
    if isinstance(value, Msg):
        return value.text(lang)
    if isinstance(value, (list, tuple)):
        return "\n".join(str(_render(item, lang)) for item in value)
    return value


class Msg(NamedTuple):
    """A user-facing message, translated only when shown."""

    key: str
    args: Mapping[str, Any] = _NO_ARGS

    def text(self, lang: str = DEFAULT_LANGUAGE) -> str:
        return tr(self.key, lang, **self.args)


def msg(key: str, **args: Any) -> Msg:
    return Msg(key, args)


class MessageError(Exception):
    """An error whose text is a Msg; str() gives the English text (logs, CLI)."""

    def __init__(self, message: Msg) -> None:
        super().__init__(message)
        self.msg = message

    def __str__(self) -> str:
        return self.msg.text(DEFAULT_LANGUAGE)


def read_registry_language(hive: str) -> str | None:
    """Raw Language value written by the installer under HKCU or HKLM \\Software\\OrizonX, or None. Never fails."""
    try:
        import winreg
    except ImportError:
        return None
    root = winreg.HKEY_CURRENT_USER if hive == "HKCU" else winreg.HKEY_LOCAL_MACHINE
    try:
        # Vue 64 bits : l'installateur (x64) écrit dans HKLM\Software, pas dans WOW6432Node.
        with winreg.OpenKey(root, REGISTRY_KEY, 0, winreg.KEY_READ | winreg.KEY_WOW64_64KEY) as key:
            value, _kind = winreg.QueryValueEx(key, REGISTRY_VALUE)
    except OSError:
        return None
    return value if isinstance(value, str) else None


def normalize_language(value: object) -> str | None:
    """'fr', ' FR ', 'fr-FR' -> 'fr'; anything else unknown -> None."""
    if not isinstance(value, str):
        return None
    code = re.split(r"[-_]", value.strip().lower(), maxsplit=1)[0]
    return code if code in LANGUAGES else None


def detect_language(setting: str | None,
                    read_registry: Callable[[str], str | None] = read_registry_language) -> str:
    """The app's language: its own setting, else HKCU, else HKLM (both written by the installer), else English."""
    for candidate in (lambda: setting, lambda: read_registry("HKCU"), lambda: read_registry("HKLM")):
        language = normalize_language(candidate())
        if language is not None:
            return language
    return DEFAULT_LANGUAGE
