"""Orizon X PC app: single instance, log file, window and tray around the relay engine."""
from __future__ import annotations

import argparse
import ctypes
import logging
import os
import sys
import threading
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Callable

from PySide6.QtCore import QObject, Signal
from PySide6.QtGui import QIcon, QPixmap
from PySide6.QtNetwork import QLocalServer, QLocalSocket
from PySide6.QtWidgets import QApplication

import engine
import tools
from app import autostart, i18n
from app import settings as settings_store
from app.controller import Controller
from app.glass import apply_glass
from app.tray import Tray
from app.window import MainWindow

ASSETS = Path(__file__).resolve().parent / "assets"
INSTANCE_NAME = f"OrizonX-PC-{os.environ.get('USERNAME', 'user')}"
SHOW_MESSAGE = b"show"
ASFW_ANY = -1  # AllowSetForegroundWindow : n'importe quel processus
logger = logging.getLogger("orizonx")


def setup_logging() -> Path:
    directory = Path(os.environ.get("LOCALAPPDATA") or str(Path.home())) / "OrizonX"
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / "relay.log"
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


def make_engine(config: engine.Config, listener: engine.Listener) -> engine.RelayEngine:
    # Outils cherchés à chaque démarrage : « Réessayer » marche après une installation de ffmpeg/adb.
    return engine.RelayEngine(config, listener, ffmpeg=tools.find_tool("ffmpeg"), adb=tools.find_tool("adb"))


class OutputProber(QObject):
    """Lists the capturable screens in the background (ffmpeg takes ~1 s per screen), one probe at a time."""

    done = Signal(object)

    def __init__(self) -> None:
        super().__init__()
        self._busy = threading.Lock()

    def probe(self) -> None:
        if not self._busy.acquire(blocking=False):
            return  # une liste est déjà en cours : son résultat suffira

        def work() -> None:
            try:
                outputs = engine.probe_outputs(tools.find_tool("ffmpeg"))
            except tools.ToolMissing as e:  # déjà affiché par l'état ERROR du moteur : une ligne suffit
                logger.info("Cannot list the screens: %s", e)
                outputs = []
            except Exception:  # noqa: BLE001 — liste vide : seul « Auto » reste proposé
                logger.exception("Cannot list the screens")
                outputs = []
            finally:
                self._busy.release()
            self.done.emit(outputs)

        threading.Thread(target=work, name="probe-outputs", daemon=True).start()


def wire(*, controller: Controller, window: MainWindow, tray: Tray, prober: OutputProber,
         current: settings_store.Settings, settings_path: Path, log_path: Path,
         quit_app: Callable[[], None]) -> None:
    """Connects the controller, the window, the tray and the settings (testable with a fake engine)."""

    def save_settings() -> None:
        try:
            settings_store.save(current, settings_path)
        except OSError:
            logger.exception("Settings not saved")

    def on_state(state: engine.State, detail: i18n.Msg) -> None:
        logger.info("State: %s — %s", state.value, detail.text("en"))
        window.set_state(state, detail)
        tray.set_state(state, detail)

    def on_setting(name: str, value: str) -> None:
        if getattr(current, name) == value:
            return  # même valeur choisie à nouveau : pas de coupure du flux
        setattr(current, name, value)
        save_settings()
        controller.restart(engine.Config(output=current.output, encoder=current.encoder))

    def on_language(lang: str) -> None:
        if current.language != lang:
            current.language = lang  # choix explicite : il prime désormais sur celui de l'installateur
            save_settings()
        i18n.set_language(lang)  # textes réappliqués tout de suite ; le flux continue

    def on_toggle() -> None:
        if controller.state in (engine.State.STOPPED, engine.State.ERROR):
            controller.start()
        else:
            controller.stop()

    def on_closed_to_tray() -> None:
        if not current.first_close_hint_shown:
            lang = i18n.current_language()
            tray.show_message(i18n.tr("tray.still_running_title", lang), i18n.tr("tray.still_running_text", lang))
            current.first_close_hint_shown = True
            save_settings()

    def on_autostart(enabled: bool) -> None:
        try:
            if enabled:
                autostart.enable(sys.executable)
            else:
                autostart.disable()
        except OSError:
            logger.exception("Start with Windows: failed")
        tray.set_autostart_checked(autostart.is_enabled())

    def on_quit() -> None:
        logger.info("Quit requested")
        tray.hide()  # disparaissent tout de suite : l'arrêt du moteur peut prendre jusqu'à 3 s
        window.prepare_quit()
        window.hide()
        controller.stop_blocking()  # lève les contacts et tue ffmpeg avant de partir
        quit_app()

    controller.state_changed.connect(on_state)
    controller.log.connect(logger.info)
    controller.stats.connect(window.set_stats)
    window.output_changed.connect(lambda value: on_setting("output", value))
    window.encoder_changed.connect(lambda value: on_setting("encoder", value))
    window.language_chosen.connect(on_language)
    window.primary_clicked.connect(on_toggle)
    window.closed_to_tray.connect(on_closed_to_tray)
    window.shown.connect(prober.probe)
    prober.done.connect(lambda outputs: window.set_outputs(outputs, current.output))
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


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="OrizonX")
    parser.add_argument("--minimized", action="store_true", help="start in the notification area")
    args = parser.parse_args(sys.argv[1:] if argv is None else argv)

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

    settings_path = settings_store.default_path()
    current = settings_store.load(settings_path)
    i18n.set_language(i18n.detect_language(current.language))  # avant de créer la fenêtre et l'icône
    controller = Controller(make_engine, engine.Config(output=current.output, encoder=current.encoder))
    window = MainWindow(logo)
    window.set_acrylic(apply_glass(int(window.winId())))
    window.set_encoder(current.encoder)
    window.set_outputs([], current.output)
    tray = Tray(logo, autostart_supported=autostart.supported(),
                autostart_enabled=autostart.supported() and autostart.is_enabled())
    prober = OutputProber()
    wire(controller=controller, window=window, tray=tray, prober=prober, current=current,
         settings_path=settings_path, log_path=log_path, quit_app=app.quit)
    serve_instance(server, window.show_and_raise)

    controller.start()
    if args.minimized:
        prober.probe()
    else:
        window.show_and_raise()
    return app.exec()
