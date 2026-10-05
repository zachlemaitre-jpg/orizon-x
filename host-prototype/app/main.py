"""Orizon X PC app: single instance, log file, window and tray around the relay engine."""
from __future__ import annotations

import argparse
import logging
import os
import sys
import threading
from logging.handlers import RotatingFileHandler
from pathlib import Path

from PySide6.QtCore import QObject, Signal
from PySide6.QtGui import QIcon, QPixmap
from PySide6.QtNetwork import QLocalServer, QLocalSocket
from PySide6.QtWidgets import QApplication

import engine
import tools
from app import autostart
from app import settings as settings_store
from app.controller import Controller
from app.glass import apply_glass
from app.tray import Tray
from app.window import MainWindow

ASSETS = Path(__file__).resolve().parent / "assets"
INSTANCE_NAME = f"OrizonX-PC-{os.environ.get('USERNAME', 'user')}"
logger = logging.getLogger("orizonx")


def setup_logging() -> Path:
    directory = Path(os.environ.get("LOCALAPPDATA") or str(Path.home())) / "OrizonX"
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / "relay.log"
    handler = RotatingFileHandler(path, maxBytes=1_000_000, backupCount=3, encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s %(message)s"))
    logger.setLevel(logging.INFO)
    logger.addHandler(handler)
    sys.excepthook = lambda kind, value, tb: logger.error("Exception non gérée", exc_info=(kind, value, tb))
    # pythonw n'a pas de console : sans ce crochet, une exception dans un thread disparaîtrait sans trace.
    threading.excepthook = lambda a: logger.error("Exception non gérée (thread %s)", a.thread.name if a.thread else "?",
                                                  exc_info=(a.exc_type, a.exc_value, a.exc_traceback))
    return path


def notify_running_instance() -> bool:
    """True if another Orizon X is running; it is asked to show its window."""
    socket = QLocalSocket()
    socket.connectToServer(INSTANCE_NAME)
    if not socket.waitForConnected(500):
        return False
    socket.write(b"show")
    socket.flush()
    socket.waitForBytesWritten(500)
    socket.disconnectFromServer()
    return True


def make_engine(config: engine.Config, listener: engine.Listener) -> engine.RelayEngine:
    # Outils cherchés à chaque démarrage : « Réessayer » marche après une installation de ffmpeg/adb.
    return engine.RelayEngine(config, listener, ffmpeg=tools.find_tool("ffmpeg"), adb=tools.find_tool("adb"))


class OutputProber(QObject):
    """Lists the capturable screens in the background (ffmpeg takes ~1 s per screen)."""

    done = Signal(object)

    def probe(self) -> None:
        def work() -> None:
            try:
                outputs = engine.probe_outputs(tools.find_tool("ffmpeg"))
            except Exception:  # noqa: BLE001 — liste vide : seul « Auto » reste proposé
                logger.exception("Liste des écrans impossible")
                outputs = []
            self.done.emit(outputs)

        threading.Thread(target=work, name="probe-outputs", daemon=True).start()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="OrizonX")
    parser.add_argument("--minimized", action="store_true", help="démarre dans la zone de notification")
    args = parser.parse_args(sys.argv[1:] if argv is None else argv)

    app = QApplication(sys.argv[:1])
    app.setApplicationName("Orizon X")
    app.setQuitOnLastWindowClosed(False)  # seul « Quitter » ferme l'appli
    if notify_running_instance():
        return 0
    server = QLocalServer()
    QLocalServer.removeServer(INSTANCE_NAME)  # nettoie un nom resté après un plantage
    server.listen(INSTANCE_NAME)

    log_path = setup_logging()
    logger.info("Orizon X démarre")
    logo = QPixmap(str(ASSETS / "orizonx.png"))
    app.setWindowIcon(QIcon(str(ASSETS / "orizonx.ico")))

    settings_path = settings_store.default_path()
    current = settings_store.load(settings_path)
    controller = Controller(make_engine, engine.Config(output=current.output, encoder=current.encoder))
    window = MainWindow(logo)
    window.set_acrylic(apply_glass(int(window.winId())))
    window.set_encoder(current.encoder)
    window.set_outputs([], current.output)
    tray = Tray(logo, autostart_supported=autostart.supported(),
                autostart_enabled=autostart.supported() and autostart.is_enabled())
    prober = OutputProber()

    def show_window() -> None:
        window.show_and_raise()

    def on_state(state: engine.State, detail: str) -> None:
        logger.info("État : %s — %s", state.value, detail)
        window.set_state(state, detail)
        tray.set_state(state, detail)

    def apply_settings() -> None:
        settings_store.save(current, settings_path)
        controller.restart(engine.Config(output=current.output, encoder=current.encoder))

    def on_output(value: str) -> None:
        current.output = value
        apply_settings()

    def on_encoder(value: str) -> None:
        current.encoder = value
        apply_settings()

    def on_toggle() -> None:
        if controller.state in (engine.State.STOPPED, engine.State.ERROR):
            controller.start()
        else:
            controller.stop()

    def on_closed_to_tray() -> None:
        if not current.first_close_hint_shown:
            tray.show_message("Orizon X tourne toujours",
                              "Le flux continue. Clique sur l'icône Orizon X pour rouvrir la fenêtre.")
            current.first_close_hint_shown = True
            settings_store.save(current, settings_path)

    def on_autostart(enabled: bool) -> None:
        try:
            if enabled:
                autostart.enable(sys.executable)
            else:
                autostart.disable()
        except OSError:
            logger.exception("Lancer avec Windows : échec")
        tray.set_autostart_checked(autostart.is_enabled())

    def on_quit() -> None:
        logger.info("Arrêt demandé")
        controller.stop_blocking()  # lève les contacts et tue ffmpeg avant de partir
        tray.hide()
        app.quit()

    def on_new_connection() -> None:
        connection = server.nextPendingConnection()
        connection.readyRead.connect(show_window)
        connection.disconnected.connect(connection.deleteLater)

    controller.state_changed.connect(on_state)
    controller.log.connect(logger.info)
    controller.stats.connect(window.set_stats)
    window.output_changed.connect(on_output)
    window.encoder_changed.connect(on_encoder)
    window.primary_clicked.connect(on_toggle)
    window.closed_to_tray.connect(on_closed_to_tray)
    window.shown.connect(prober.probe)
    prober.done.connect(lambda outputs: window.set_outputs(outputs, current.output))
    tray.show_requested.connect(show_window)
    tray.toggle_requested.connect(on_toggle)
    tray.open_log_requested.connect(lambda: os.startfile(log_path))
    tray.autostart_toggled.connect(on_autostart)
    tray.quit_requested.connect(on_quit)
    server.newConnection.connect(on_new_connection)

    controller.start()
    if args.minimized:
        prober.probe()
    else:
        show_window()
    return app.exec()
