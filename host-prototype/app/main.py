"""Orizon X PC app: single instance, log file, window and tray around the relay engine.

Also the admin command line (--cleanup, --configure-vdd, --install-driver, --remove-driver, --add-resolution, see
app/admin.py), handled before Qt starts: no window, exit code only.
"""
from __future__ import annotations

import argparse
import ctypes
import functools
import logging
import os
import subprocess
import sys
import threading
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Any, Callable, NoReturn

from PySide6.QtCore import QObject, Signal
from PySide6.QtGui import QIcon, QPixmap
from PySide6.QtNetwork import QLocalServer, QLocalSocket
from PySide6.QtWidgets import QApplication

import engine
import tools
from app import admin, autostart, elevate, i18n
from app import settings as settings_store
from app.controller import Controller
from app.glass import apply_glass
from app.tray import Tray
from app.window import MainWindow
from vdd import VddController
from virtual_display import VirtualDisplay

ASSETS = Path(__file__).resolve().parent / "assets"
INSTANCE_NAME = f"OrizonX-PC-{os.environ.get('USERNAME', 'user')}"
SHOW_MESSAGE = b"show"
ASFW_ANY = -1  # AllowSetForegroundWindow : n'importe quel processus
DISPLAY_SETTINGS_URI = "ms-settings:display"
LOG_NAME = "relay.log"
# Commandes admin (installateur, invite UAC) : leur propre fichier. Écrire relay.log depuis un second processus
# ferait tourner (renommer) le fichier que l'appli a ouvert.
ADMIN_LOG_NAME = "relay-admin.log"
logger = logging.getLogger("orizonx")


def setup_logging(name: str = LOG_NAME) -> Path:
    directory = Path(os.environ.get("LOCALAPPDATA") or str(Path.home())) / "OrizonX"
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / name
    handler = RotatingFileHandler(path, maxBytes=1_000_000, backupCount=3, encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s %(message)s"))
    logger.setLevel(logging.INFO)
    logger.addHandler(handler)
    sys.excepthook = lambda kind, value, tb: logger.error("Unhandled exception", exc_info=(kind, value, tb))
    # pythonw n'a pas de console : sans ce crochet, une exception dans un thread disparaîtrait sans trace.
    threading.excepthook = lambda a: logger.error("Unhandled exception (thread %s)", a.thread.name if a.thread else "?",
                                                  exc_info=(a.exc_type, a.exc_value, a.exc_traceback))
    return path


def notify_running_instance(show: bool) -> bool:
    """True if another Orizon X is running; if show, it is asked to show its window."""
    socket = QLocalSocket()
    socket.connectToServer(INSTANCE_NAME)
    if not socket.waitForConnected(500):
        return False
    if show:
        if sys.platform == "win32":
            # Sans ce droit, Windows refuse le premier plan à l'autre instance : sa fenêtre clignoterait dans la barre.
            ctypes.windll.user32.AllowSetForegroundWindow(ASFW_ANY)
        socket.write(SHOW_MESSAGE)
        socket.flush()
        socket.waitForBytesWritten(500)
    socket.disconnectFromServer()
    return True


def serve_instance(server: QLocalServer, show_window: Callable[[], None]) -> None:
    """Shows the window when a second launch asks for it."""
    def on_new_connection() -> None:
        connection = server.nextPendingConnection()
        if connection is None:
            return
        received = bytearray()

        def check() -> None:
            # Le message est souvent déjà là (le client écrit puis se déconnecte aussitôt) : readyRead ne viendrait plus.
            received.extend(connection.readAll().data())
            if SHOW_MESSAGE in received:
                received.clear()
                show_window()

        connection.readyRead.connect(check)
        connection.disconnected.connect(connection.deleteLater)
        check()

    server.newConnection.connect(on_new_connection)


class SettingsKeeper:
    """The user's settings and their file, shared by the Qt thread and the engine thread.

    The engine asks first_time() and calls mark_layout_applied() from its own thread: one lock around every read,
    change and save (two saves at once would race on the temporary file).
    """

    def __init__(self, current: settings_store.Settings, path: Path) -> None:
        self.current = current
        self.path = path
        self._lock = threading.RLock()

    def get(self, name: str) -> Any:
        with self._lock:
            return getattr(self.current, name)

    def update(self, **fields: Any) -> bool:
        """Sets the fields and saves if any changed; True if something changed."""
        with self._lock:
            changed = {name: value for name, value in fields.items() if getattr(self.current, name) != value}
            for name, value in changed.items():
                setattr(self.current, name, value)
            if changed:
                self._save_locked()
            return bool(changed)

    def config(self) -> engine.Config:
        with self._lock:
            c = self.current
            return engine.Config(encoder=c.encoder, mode=c.mode, position=c.position, scale=c.scale)

    def first_time(self) -> bool:
        """Engine thread: the chosen position and scale are not the ones last applied to the virtual screen."""
        with self._lock:
            c = self.current
            return (c.applied_position, c.applied_scale) != (c.position, c.scale)

    def mark_layout_applied(self, position: str, scale: str) -> None:
        """Engine thread (or relayout worker): Windows now has (and remembers) this position and scale.

        The pair is kept rather than a flag: if the user picked something else meanwhile, first_time() stays True.
        """
        self.update(applied_position=position, applied_scale=scale)

    def _save_locked(self) -> None:
        try:
            settings_store.save(self.current, self.path)
        except OSError:
            logger.exception("Settings not saved")


def make_engine_factory(display: Any, keeper: SettingsKeeper,
                        find_tool: Callable[[str], str] = tools.find_tool) -> Callable[..., engine.RelayEngine]:
    """Engines with the virtual display in Extend mode, without it in Duplicate mode."""
    def factory(config: engine.Config, listener: engine.Listener) -> engine.RelayEngine:
        # Outils cherchés à chaque démarrage : « Réessayer » marche après une installation de ffmpeg/adb.
        return engine.RelayEngine(config, listener, ffmpeg=find_tool("ffmpeg"), adb=find_tool("adb"),
                                  display=display if config.mode == "extend" else None,
                                  first_time=keeper.first_time, on_layout_applied=keeper.mark_layout_applied)
    return factory


def open_display_settings() -> None:
    os.startfile(DISPLAY_SETTINGS_URI)


class _ResolutionResult(QObject):
    """Brings the end of an "Add exact resolution" (worker thread) back to the Qt thread."""

    done = Signal(int, int, object)  # largeur, hauteur, code de sortie | None (UAC refusé) | exception


def wire(*, controller: Controller, window: MainWindow, tray: Tray, keeper: SettingsKeeper, log_path: Path,
         quit_app: Callable[[], None], display: Any = None,
         add_resolution: Callable[[int, int], int | None] = elevate.add_resolution,
         open_settings: Callable[[], None] = open_display_settings) -> None:
    """Connects the controller, the window, the tray and the settings (testable with fakes).

    display: the app's VirtualDisplay, turned off at once on Quit (an old engine may still hold a grace delay).
    add_resolution(width, height): blocking UAC + admin process (elevate.add_resolution), run in a worker thread.
    """
    def on_state(state: engine.State, detail: i18n.Msg) -> None:
        logger.info("State: %s — %s", state.value, detail.text("en"))
        window.set_state(state, detail)
        tray.set_state(state, detail)

    def on_mode(value: str) -> None:
        if keeper.update(mode=value):
            # Vers Duplicate, l'écran virtuel n'a plus d'usage : éteint sans attendre la grâce.
            controller.restart(keeper.config(), immediate_display_release=value == "duplicate")

    def on_encoder(value: str) -> None:
        if keeper.update(encoder=value):
            controller.restart(keeper.config())

    def on_layout(name: str, value: str) -> None:
        if keeper.get(name) == value:
            return  # même valeur choisie à nouveau : rien à déplacer
        # Différente de la paire appliquée : le moteur la note appliquée s'il déplace l'écran tout de suite (flux en
        # cours), sinon la prochaine apparition de l'écran l'applique. Pas de redémarrage : le flux continue.
        keeper.update(**{name: value})
        controller.relayout(keeper.get("position"), keeper.get("scale"))

    def on_language(lang: str) -> None:
        keeper.update(language=lang)  # choix explicite : il prime désormais sur celui de l'installateur
        i18n.set_language(lang)  # textes réappliqués tout de suite ; le flux continue

    def on_toggle() -> None:
        if controller.state in (engine.State.STOPPED, engine.State.ERROR):
            controller.start()
        else:
            controller.stop()

    def on_closed_to_tray() -> None:
        if not keeper.get("first_close_hint_shown"):
            lang = i18n.current_language()
            tray.show_message(i18n.tr("tray.still_running_title", lang), i18n.tr("tray.still_running_text", lang))
            keeper.update(first_close_hint_shown=True)

    def on_autostart(enabled: bool) -> None:
        try:
            if enabled:
                autostart.enable(sys.executable)
            else:
                autostart.disable()
        except OSError:
            logger.exception("Start with Windows: failed")
        tray.set_autostart_checked(autostart.is_enabled())

    def on_use_duplicate() -> None:
        logger.info("Switching to Duplicate mode (virtual display driver not found)")
        window.set_mode("duplicate")
        on_mode("duplicate")

    def on_adjust() -> None:
        try:
            open_settings()
        except OSError:
            logger.exception("Cannot open the Windows display settings")

    resolution_result = _ResolutionResult(controller)  # enfant du contrôleur : vit aussi longtemps que lui

    def on_add_resolution(width: int, height: int) -> None:
        logger.info("Add exact resolution %dx%d: stopping the stream, asking for administrator rights",
                    width, height)
        # Le périphérique va redémarrer : plus de capture ni de tactile sur un écran qui disparaît.
        stopping = controller.stop()

        def work() -> None:
            if stopping is not None:
                stopping.join(engine.STOP_TIMEOUT_S + 0.5)  # avant l'invite UAC
            try:
                result: object = add_resolution(width, height)
            except Exception as e:  # noqa: BLE001 — rapporté au thread Qt, jamais perdu
                result = e
            resolution_result.done.emit(width, height, result)

        threading.Thread(target=work, name="add-resolution", daemon=True).start()

    def on_resolution_done(width: int, height: int, result: object) -> None:
        lang = i18n.current_language()
        title = i18n.tr("tray.resolution_title", lang)
        if result == 0:
            logger.info("Resolution %dx%d added: restarting the engine so the tablet reconnects", width, height)
        elif result is None:
            logger.info("Add exact resolution %dx%d: administrator rights refused, restarting the engine",
                        width, height)
            tray.show_message(title, i18n.tr("tray.resolution_refused", lang))
        else:
            logger.error("Add exact resolution %dx%d failed (%s): restarting the engine", width, height,
                         f"exit code {result}" if isinstance(result, int) else repr(result))
            tray.show_message(title, i18n.tr("tray.resolution_failed", lang))
        controller.restart(keeper.config())  # dans tous les cas : le flux reprend (bandes noires sinon)

    def on_quit() -> None:
        logger.info("Quit requested")
        tray.hide()  # disparaissent tout de suite : l'arrêt du moteur peut prendre jusqu'à 3 s
        window.prepare_quit()
        window.hide()
        # Lève les contacts, tue ffmpeg et éteint l'écran virtuel sans grâce avant de partir.
        controller.stop_blocking(immediate_display_release=True)
        if display is not None:
            display.release(immediate=True)  # filet : grâce d'un ancien moteur (redémarrage en cours), sans effet sinon
        quit_app()

    controller.state_changed.connect(on_state)
    controller.log.connect(logger.info)
    controller.stats.connect(window.set_stats)
    controller.display_changed.connect(window.set_display_info)
    window.mode_changed.connect(on_mode)
    window.position_changed.connect(lambda value: on_layout("position", value))
    window.scale_changed.connect(lambda value: on_layout("scale", value))
    window.encoder_changed.connect(on_encoder)
    window.language_chosen.connect(on_language)
    window.primary_clicked.connect(on_toggle)
    window.quit_clicked.connect(on_quit)
    window.use_duplicate_clicked.connect(on_use_duplicate)
    window.add_resolution_clicked.connect(on_add_resolution)
    window.adjust_requested.connect(on_adjust)
    window.closed_to_tray.connect(on_closed_to_tray)
    resolution_result.done.connect(on_resolution_done)
    tray.show_requested.connect(window.show_and_raise)
    tray.toggle_requested.connect(on_toggle)
    tray.open_log_requested.connect(lambda: os.startfile(log_path))
    tray.autostart_toggled.connect(on_autostart)
    tray.quit_requested.connect(on_quit)


def refresh_autostart() -> None:
    """The app folder was moved: points 'Start with Windows' at this exe again (packaged app only)."""
    if autostart.supported() and autostart.is_stale():
        try:
            autostart.enable(sys.executable)
            logger.info("Start with Windows: path updated (%s)", sys.executable)
        except OSError:
            logger.exception("Start with Windows: cannot update the path")


class UsageError(Exception):
    """The command line is wrong (argparse's message)."""


class _Parser(argparse.ArgumentParser):
    def error(self, message: str) -> NoReturn:
        # L'exe est fenêtré : argparse écrirait sur une console absente puis sortirait sans trace.
        raise UsageError(message)


def parse_args(argv: list[str]) -> argparse.Namespace:
    """Raises UsageError on a wrong command line."""
    parser = _Parser(prog="OrizonX")
    parser.add_argument("--minimized", action="store_true", help="start in the notification area")
    admin.add_arguments(parser)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    try:
        args = parse_args(argv)
    except UsageError as e:
        # Le plus souvent l'installateur : journal des commandes admin, code 2 comme argparse.
        setup_logging(ADMIN_LOG_NAME)
        logger.error("Command line error: %s (arguments: %s)", e, subprocess.list2cmdline(argv))
        return 2
    except SystemExit as e:  # --help
        return e.code if isinstance(e.code, int) else 0
    if admin.requested(args):
        # Installateur ou invite UAC : ni fenêtre, ni instance unique, ni Qt ; code de sortie 0/1, détails au journal.
        setup_logging(ADMIN_LOG_NAME)
        return admin.run(args, log=logger)

    app = QApplication(sys.argv[:1])
    app.setApplicationName("Orizon X")
    app.setQuitOnLastWindowClosed(False)  # seul « Quitter » ferme l'appli
    if notify_running_instance(show=not args.minimized):
        return 0
    log_path = setup_logging()
    server = QLocalServer()
    # Même utilisateur, élevé ou non : sinon une instance administrateur serait injoignable par un lancement normal.
    server.setSocketOptions(QLocalServer.SocketOption.UserAccessOption)
    QLocalServer.removeServer(INSTANCE_NAME)  # nettoie un nom resté après un plantage
    if not server.listen(INSTANCE_NAME):
        logger.error("Cannot ensure a single instance (%s): another Orizon X may be running as administrator.",
                     server.errorString())
        return 1

    logger.info("Orizon X starting")
    refresh_autostart()
    logo = QPixmap(str(ASSETS / "orizonx.png"))
    app.setWindowIcon(QIcon(str(ASSETS / "orizonx.ico")))

    keeper = SettingsKeeper(settings_store.load(settings_store.default_path()), settings_store.default_path())
    current = keeper.current
    i18n.set_language(i18n.detect_language(current.language))  # avant de créer la fenêtre et l'icône
    display = VirtualDisplay(VddController(), log=logger.info)
    display.cleanup_on_start()  # une fois : un plantage ou Windows a pu laisser l'écran virtuel allumé
    controller = Controller(make_engine_factory(display, keeper), keeper.config())
    window = MainWindow(logo)
    window.set_acrylic(apply_glass(int(window.winId())))
    window.set_mode(current.mode)
    window.set_position(current.position)
    window.set_scale(current.scale)
    window.set_encoder(current.encoder)
    tray = Tray(logo, autostart_supported=autostart.supported(),
                autostart_enabled=autostart.supported() and autostart.is_enabled())
    # Invite UAC de « Résolution exacte » rattachée à la fenêtre : au premier plan, pas un bouton qui clignote.
    wire(controller=controller, window=window, tray=tray, keeper=keeper, log_path=log_path, quit_app=app.quit,
         display=display, add_resolution=functools.partial(elevate.add_resolution, hwnd=int(window.winId())))
    serve_instance(server, window.show_and_raise)

    controller.start()
    if not args.minimized:
        window.show_and_raise()
    return app.exec()
