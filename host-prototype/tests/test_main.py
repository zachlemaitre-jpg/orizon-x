import importlib.util
import os
import json
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock

HAVE_QT = importlib.util.find_spec("PySide6") is not None
if HAVE_QT:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtCore import QCoreApplication
    from PySide6.QtGui import QPixmap
    from PySide6.QtNetwork import QLocalServer, QLocalSocket
    from PySide6.QtWidgets import QApplication

    from app import i18n, main
    from app.controller import Controller
    from app.settings import Settings
    from app.tray import Tray
    from app.window import MainWindow
    from tests.test_controller import FakeEngine, pump_until

import time

import engine
from engine import DisplayInfo, State
from inputstate import Rect
from messages import msg


class FakeDisplay:
    def __init__(self):
        self.calls = []

    def release(self, immediate=False):
        self.calls.append(("release", immediate))


def settle(seconds=0.05):
    """Lets queued signals and short worker threads finish."""
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        QCoreApplication.processEvents()
        time.sleep(0.005)


@unittest.skipUnless(HAVE_QT, "PySide6 absent")
class WireTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        i18n.set_language("fr")
        self.addCleanup(i18n.set_language, "en")
        FakeEngine.instances.clear()
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.settings_path = Path(temp.name) / "settings.json"
        self.current = Settings()
        self.keeper = main.SettingsKeeper(self.current, self.settings_path)
        self.controller = Controller(FakeEngine, self.keeper.config())
        logo = QPixmap(64, 64)
        logo.fill()
        self.window = MainWindow(logo)
        self.tray = Tray(logo, autostart_supported=False, autostart_enabled=False)
        self.addCleanup(self.tray.hide)
        self.quits = []
        self.display = FakeDisplay()
        self.resolution_results = []  # résultats successifs du faux add_resolution
        self.resolution_calls = []
        self.opened = []
        main.wire(controller=self.controller, window=self.window, tray=self.tray, keeper=self.keeper,
                  log_path=self.settings_path, quit_app=lambda: self.quits.append(True), display=self.display,
                  add_resolution=self.fake_add_resolution, open_settings=lambda: self.opened.append(True))

    def fake_add_resolution(self, width, height):
        self.resolution_calls.append((width, height, threading.current_thread() is threading.main_thread()))
        # Moteurs déjà arrêtés quand l'invite UAC s'ouvre (le redémarrage du périphérique coupe l'écran virtuel).
        self.stopped_at_elevation = [e.stopped.is_set() for e in FakeEngine.instances]
        result = self.resolution_results.pop(0)
        if isinstance(result, Exception):
            raise result
        return result

    def saved(self):
        return main.settings_store.load(self.settings_path)

    def start_engine(self):
        self.controller.start()
        pump_until(lambda: self.controller.state is State.WAITING_DEVICE)
        # The window learns the state through a queued Qt signal: under load it can lag behind the controller.
        pump_until(lambda: self.window.primary_text() in ("Arrêter", "Stop"))
        return FakeEngine.instances[-1]

    def test_primary_button_starts_then_stops(self):
        self.window._primary.click()
        pump_until(lambda: self.controller.state is State.WAITING_DEVICE)
        self.window._primary.click()
        pump_until(lambda: self.controller.state is State.STOPPED)
        self.assertEqual(len(FakeEngine.instances), 1)

    def test_same_value_does_not_restart_and_save_errors_do_not_block(self):
        with mock.patch.object(self.controller, "restart") as restart:
            self.window.choose_encoder("auto")  # déjà la valeur courante
            restart.assert_not_called()
            with mock.patch.object(main.settings_store, "save", side_effect=OSError("disque plein")), \
                    self.assertLogs("orizonx", "ERROR"):
                self.window.choose_encoder("amf")
            restart.assert_called_once_with(engine.Config(encoder="amf"))
        self.assertEqual(self.current.encoder, "amf")

    def test_mode_change_restarts_and_duplicate_turns_the_virtual_screen_off_now(self):
        with mock.patch.object(self.controller, "restart") as restart:
            self.window.choose("mode", "duplicate")
            restart.assert_called_once_with(engine.Config(mode="duplicate"), immediate_display_release=True)
            self.window.choose("mode", "extend")
            restart.assert_called_with(engine.Config(mode="extend"), immediate_display_release=False)
        self.assertEqual(self.saved().mode, "extend")

    def test_position_change_while_streaming_moves_the_screen_without_restart(self):
        first = self.start_engine()
        self.keeper.mark_layout_applied("right", "auto")
        self.assertFalse(self.keeper.first_time())
        with mock.patch.object(self.controller, "restart") as restart:
            self.window.choose("position", "left")
            pump_until(lambda: len(first.relayouts) == 1)
            self.window.choose("scale", "175")
            pump_until(lambda: len(first.relayouts) == 2)
            restart.assert_not_called()
        self.assertEqual(first.relayouts, [("left", "auto"), ("left", "175")])
        self.assertEqual(first.stop_calls, [])  # le flux continue
        self.assertEqual(len(FakeEngine.instances), 1)
        self.assertEqual((self.saved().position, self.saved().scale), ("left", "175"))
        # Pas encore appliquées tant que le moteur ne dit pas les avoir appliquées (on_layout_applied).
        self.assertEqual((self.saved().applied_position, self.saved().applied_scale), ("right", "auto"))
        self.assertTrue(self.keeper.first_time())
        self.assertEqual((self.controller.config.position, self.controller.config.scale), ("left", "175"))

    def test_same_position_again_does_nothing(self):
        first = self.start_engine()
        self.window.choose("position", "right")
        settle()
        self.assertEqual(first.relayouts, [])

    def test_engine_marks_the_layout_applied_from_its_thread(self):
        self.keeper.update(position="above")
        self.assertTrue(self.keeper.first_time())
        worker = threading.Thread(target=self.keeper.mark_layout_applied, args=("above", "auto"))
        worker.start()
        worker.join(2)
        self.assertFalse(self.keeper.first_time())
        self.assertEqual((self.saved().applied_position, self.saved().applied_scale), ("above", "auto"))
        self.assertEqual(self.saved().position, "above")

    def test_older_layout_applied_while_the_user_changed_it_again_stays_pending(self):
        # Le moteur finit d'appliquer l'ancienne valeur après que l'utilisateur en a choisi une autre.
        self.keeper.update(position="below")
        self.keeper.mark_layout_applied("left", "auto")
        self.assertTrue(self.keeper.first_time())
        self.keeper.mark_layout_applied("below", "auto")
        self.assertFalse(self.keeper.first_time())
        self.keeper.update(scale="150")
        self.assertTrue(self.keeper.first_time())

    def test_display_info_shows_add_exact_resolution(self):
        self.window.show()
        self.controller.state_changed.emit(State.PREPARING_DISPLAY, msg("state.preparing_display"))
        self.controller.display_changed.emit(DisplayInfo((2800, 1752), (2560, 1600), False, Rect(0, 0, 2560, 1600)))
        self.controller.state_changed.emit(State.STREAMING, msg("state.starting_stream"))
        self.assertTrue(self.window.add_resolution_visible())

    def test_add_exact_resolution_stops_the_stream_runs_elevated_in_a_worker_then_restarts(self):
        first = self.start_engine()
        self.resolution_results = [0]
        with mock.patch.object(self.controller, "restart") as restart, \
                mock.patch.object(self.tray, "show_message") as show:
            self.window.add_resolution_clicked.emit(2800, 1752)
            pump_until(lambda: restart.called)
        self.assertEqual(self.resolution_calls, [(2800, 1752, False)])  # jamais sur le thread Qt (UAC bloquant)
        self.assertEqual(first.stop_calls, [False])
        self.assertEqual(self.stopped_at_elevation, [True])  # arrêté avant l'invite UAC
        restart.assert_called_once_with(self.keeper.config())
        show.assert_not_called()

    def test_add_exact_resolution_without_a_running_engine_still_restarts(self):
        self.resolution_results = [0]
        with mock.patch.object(self.controller, "restart") as restart:
            self.window.add_resolution_clicked.emit(2800, 1752)
            pump_until(lambda: restart.called)
        restart.assert_called_once_with(self.keeper.config())

    def test_add_exact_resolution_refused_or_failed_shows_a_tray_message_and_restarts(self):
        cases = ((None, "Droits administrateur refusés : la tablette garde ses bandes noires."),
                 (1, "La résolution n'a pas pu être ajoutée. Voir le journal."),
                 (OSError(2, "introuvable"), "La résolution n'a pas pu être ajoutée. Voir le journal."))
        for result, text in cases:
            first = self.start_engine()
            with self.subTest(result=result), mock.patch.object(self.controller, "restart") as restart, \
                    mock.patch.object(self.tray, "show_message") as show, self.assertLogs("orizonx", "INFO") as logs:
                self.resolution_results = [result]
                self.window.add_resolution_clicked.emit(2800, 1752)
                pump_until(lambda: show.called and restart.called)
                show.assert_called_once_with("Résolution exacte", text)
                restart.assert_called_once_with(self.keeper.config())  # le flux reprend, bandes noires comprises
                self.assertEqual(self.stopped_at_elevation[-1], True)
                self.assertEqual(first.stop_calls, [False])
            self.assertTrue(any("2800x1752" in line for line in logs.output))

    def test_use_duplicate_switches_mode_and_restarts(self):
        self.controller.state_changed.emit(State.ERROR, msg("display.vdd_missing"))
        with mock.patch.object(self.controller, "restart") as restart:
            self.window._use_duplicate.click()
            restart.assert_called_once_with(engine.Config(mode="duplicate"), immediate_display_release=True)
        self.assertEqual(self.window.selected("mode"), "duplicate")
        self.assertFalse(self.window.is_enabled("position"))
        self.assertEqual(self.saved().mode, "duplicate")

    def test_use_duplicate_restarts_a_stopped_engine_in_duplicate(self):
        self.start_engine()
        FakeEngine.instances[0].running = False  # le moteur s'est arrêté en ERROR
        self.controller.state_changed.emit(State.ERROR, msg("display.vdd_missing"))
        self.window._use_duplicate.click()
        pump_until(lambda: len(FakeEngine.instances) == 2)
        self.assertEqual(FakeEngine.instances[1].config.mode, "duplicate")

    def test_adjust_in_windows_opens_the_display_settings(self):
        self.window._adjust.click()
        self.assertEqual(self.opened, [True])
        self.assertEqual(main.DISPLAY_SETTINGS_URI, "ms-settings:display")

    def test_adjust_failure_is_logged(self):
        def failing():
            raise OSError("no handler")

        window = MainWindow(QPixmap(8, 8))
        tray = Tray(QPixmap(8, 8), autostart_supported=False, autostart_enabled=False)
        self.addCleanup(tray.hide)
        main.wire(controller=Controller(FakeEngine, engine.Config()), window=window, tray=tray, keeper=self.keeper,
                  log_path=self.settings_path, quit_app=lambda: None, open_settings=failing)
        with self.assertLogs("orizonx", "ERROR"):
            window._adjust.click()

    def test_state_is_logged_in_english(self):
        with self.assertLogs("orizonx", "INFO") as logs:
            self.controller.state_changed.emit(State.WAITING_DEVICE, msg("adb.no_device"))
        self.assertEqual(logs.records[-1].getMessage(),
                         "State: waiting_device — No device found. 1. Install Orizon X on the device and open it: it "
                         "shows how to turn on USB debugging. 2. Plug it in with a USB cable that carries data.")
        self.assertEqual(self.window.detail_text(),
                         "Aucun appareil trouvé. 1. Installe Orizon X sur l'appareil et ouvre-le : il explique "
                         "comment activer le débogage USB. 2. Branche-le avec un câble USB qui transmet des données.")

    def test_close_hint_is_in_the_current_language_and_shown_once(self):
        i18n.set_language("en")
        with mock.patch.object(self.tray, "show_message") as show:
            self.window.show()
            self.window.close()
            self.window.show()
            self.window.close()
        show.assert_called_once_with("Orizon X is still running",
                                     "The stream continues. Click the Orizon X icon to open the window again.")
        self.assertTrue(self.current.first_close_hint_shown)

    def test_language_choice_switches_live_saves_and_keeps_the_stream(self):
        self.assertEqual(self.window.primary_text(), "Démarrer")
        first = self.start_engine()
        with mock.patch.object(self.controller, "restart") as restart:
            self.window.choose_language("en")
            self.assertEqual((self.window.primary_text(), self.tray.toggle_text()), ("Stop", "Stop"))
            self.assertEqual(i18n.current_language(), "en")
            self.assertEqual(self.current.language, "en")
            self.assertEqual(main.settings_store.load(self.settings_path).language, "en")
            self.window.choose_language("fr")
            self.assertEqual((self.window.primary_text(), self.tray.toggle_text()), ("Arrêter", "Arrêter"))
            self.assertEqual(main.settings_store.load(self.settings_path).language, "fr")
            restart.assert_not_called()
        settle()
        self.assertEqual((first.stop_calls, first.relayouts, len(FakeEngine.instances)), ([], [], 1))

    def test_wire_hands_the_saved_frame_settings_to_the_next_engine(self):
        self.assertEqual(self.controller._frame_config, (None, 30, "crop"))
        self.current.frame_folder, self.current.frame_interval_s, self.current.frame_fit = "D:\\Photos", 900, "fit"
        controller = Controller(FakeEngine, self.keeper.config())
        logo = QPixmap(64, 64)
        logo.fill()
        main.wire(controller=controller, window=MainWindow(logo), tray=self.tray, keeper=self.keeper,
                  log_path=self.settings_path, quit_app=lambda: None)
        controller.start()
        pump_until(lambda: FakeEngine.instances)
        self.assertEqual(FakeEngine.instances[-1].frame_configs, [("D:\\Photos", 900, "fit")])
        controller.stop_blocking()

    def test_choosing_a_frame_folder_saves_shows_and_tells_the_engine(self):
        engine_ = self.start_engine()
        self.window.frame_folder_chosen.emit("D:\\Photos")
        self.assertEqual(self.window.frame_folder_text(), "D:\\Photos")
        self.assertEqual(self.saved().frame_folder, "D:\\Photos")
        self.assertEqual(engine_.frame_configs[-1], ("D:\\Photos", 30, "crop"))
        self.assertEqual((len(FakeEngine.instances), engine_.stop_calls), (1, []))  # no restart

    def test_frame_interval_and_fit_choices_are_saved_and_sent(self):
        engine_ = self.start_engine()
        self.window.choose("frame_interval", 300)
        self.assertEqual((self.saved().frame_interval_s, engine_.frame_configs[-1]), (300, (None, 300, "crop")))
        self.window.choose("frame_fit", "fit")
        self.assertEqual((self.saved().frame_fit, engine_.frame_configs[-1]), ("fit", (None, 300, "fit")))
        self.assertEqual(engine_.stop_calls, [])

    def test_frame_settings_changed_on_the_device_are_saved_and_shown(self):
        engine_ = self.start_engine()
        threading.Thread(target=engine_.listener.on_frame_settings, args=(3600, "fit", True)).start()
        pump_until(lambda: self.saved().frame_interval_s == 3600)
        self.assertEqual(self.saved().frame_fit, "fit")
        self.assertEqual((self.window.selected("frame_interval"), self.window.selected("frame_fit")), (3600, "fit"))
        self.assertEqual(engine_.frame_configs[-1], (None, 3600, "fit"))
        self.assertNotIn("paused", json.loads(self.settings_path.read_text(encoding="utf-8")))  # the pause is not saved

    def test_quit_hides_first_then_stops_without_the_close_hint(self):
        for quit_from in ("tray", "window"):
            with self.subTest(quit_from=quit_from):
                self.quits.clear()
                self.display.calls.clear()
                self.window.show()
                self.tray._icon.show()
                self.assertTrue(self.window.isVisible() and self.tray.is_visible())
                seen = []

                def stop_blocking(**kwargs):
                    seen.append((self.window.isVisible(), self.tray.is_visible(), kwargs, list(self.display.calls)))

                with mock.patch.object(self.controller, "stop_blocking", side_effect=stop_blocking):
                    if quit_from == "tray":
                        self.tray.trigger("Quitter")
                    else:
                        self.window._quit.click()
                # Écran virtuel éteint sans grâce : par le moteur (immediate), puis le filet de l'appli.
                self.assertEqual(seen, [(False, False, {"immediate_display_release": True}, [])])
                self.assertEqual(self.display.calls, [("release", True)])
                self.assertEqual(self.quits, [True])
                self.assertFalse(self.current.first_close_hint_shown)
                self.window._quitting = False  # fenêtre réutilisée par le sous-test suivant

    def test_quit_really_stops_the_engine_with_immediate_release(self):
        first = self.start_engine()
        self.window._quit.click()
        self.assertEqual(first.stop_calls, [True])
        self.assertEqual(self.quits, [True])


@unittest.skipUnless(HAVE_QT, "PySide6 absent")
class FactoryTest(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.keeper = main.SettingsKeeper(Settings(), Path(temp.name) / "settings.json")
        self.display = FakeDisplay()
        self.factory = main.make_engine_factory(self.display, self.keeper, find_tool=lambda name: name + ".exe")

    def test_extend_engines_drive_the_virtual_display(self):
        relay = self.factory(engine.Config(mode="extend"), mock.Mock())
        self.assertIsInstance(relay, engine.RelayEngine)
        self.assertIs(relay._display, self.display)
        self.assertEqual((relay._ffmpeg, relay._adb), ("ffmpeg.exe", "adb.exe"))
        self.assertTrue(relay._first_time())
        relay._on_layout_applied("right", "auto")
        self.assertFalse(relay._first_time())
        saved = main.settings_store.load(self.keeper.path)
        self.assertEqual((saved.applied_position, saved.applied_scale), ("right", "auto"))

    def test_duplicate_engines_have_no_virtual_display(self):
        relay = self.factory(engine.Config(mode="duplicate"), mock.Mock())
        self.assertIsNone(relay._display)
        self.assertEqual(self.display.calls, [])

    def test_config_comes_from_the_settings(self):
        self.keeper.update(encoder="amf", mode="duplicate", position="below", scale="200")
        self.assertEqual(self.keeper.config(),
                         engine.Config(encoder="amf", mode="duplicate", position="below", scale="200"))


@unittest.skipUnless(HAVE_QT, "PySide6 absent")
class AdminCommandLineTest(unittest.TestCase):
    def test_admin_flags_run_before_qt_and_return_the_exit_code(self):
        for argv, expected in ((["--cleanup"], "cleanup"), (["--configure-vdd", "--restart"], "configure_vdd"),
                               (["--install-driver", r"C:\a b\MttVDD.inf"], "install_driver"),
                               (["--remove-driver"], "remove_driver"), (["--add-resolution", "2800x1752"], "add_resolution")):
            with self.subTest(argv=argv), \
                    mock.patch.object(main, "QApplication", side_effect=AssertionError("Qt started")), \
                    mock.patch.object(main, "setup_logging") as setup_logging, \
                    mock.patch.object(main.admin, "run", return_value=7) as run:
                self.assertEqual(main.main(argv), 7)
                setup_logging.assert_called_once_with(main.ADMIN_LOG_NAME)  # pas relay.log : pas de conflit
                args = run.call_args.args[0]
                self.assertTrue(getattr(args, expected))
                self.assertIs(run.call_args.kwargs["log"], main.logger)
        self.assertEqual(args.add_resolution, (2800, 1752))
        self.assertEqual(main.ADMIN_LOG_NAME, "relay-admin.log")

    def test_usage_errors_are_logged_and_exit_2(self):
        for argv in (["--add-resolution", "huge"], ["--cleanup", "--remove-driver"], ["--bogus"]):
            with self.subTest(argv=argv), \
                    mock.patch.object(main, "QApplication", side_effect=AssertionError("Qt started")), \
                    mock.patch.object(main, "setup_logging") as setup_logging, \
                    mock.patch.object(main.admin, "run", side_effect=AssertionError("ran")), \
                    mock.patch("sys.stderr") as stderr, self.assertLogs("orizonx", "ERROR") as logs:
                self.assertEqual(main.main(argv), 2)
                setup_logging.assert_called_once_with(main.ADMIN_LOG_NAME)
                self.assertIn("Command line error", logs.output[-1])
                self.assertIn(argv[-1], logs.output[-1])
                stderr.write.assert_not_called()  # pas de console (exe fenêtré) : tout va au journal

    def test_setup_logging_writes_the_given_file_in_localappdata(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        hooks = (sys.excepthook, threading.excepthook)
        self.addCleanup(lambda: (setattr(sys, "excepthook", hooks[0]), setattr(threading, "excepthook", hooks[1])))
        before = list(main.logger.handlers)
        with mock.patch.dict(os.environ, {"LOCALAPPDATA": temp.name}):
            path = main.setup_logging(main.ADMIN_LOG_NAME)
        added = [h for h in main.logger.handlers if h not in before]
        for handler in added:
            self.addCleanup(handler.close)
            self.addCleanup(main.logger.removeHandler, handler)
        self.assertEqual(path, Path(temp.name) / "OrizonX" / "relay-admin.log")
        self.assertEqual([Path(h.baseFilename) for h in added], [path])


@unittest.skipUnless(HAVE_QT, "PySide6 absent")
class InstanceTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_show_message_already_received_shows_the_window(self):
        name = f"OrizonX-test-{os.getpid()}"
        server = QLocalServer()
        self.assertTrue(server.listen(name))
        self.addCleanup(server.close)
        shown = []
        main.serve_instance(server, lambda: shown.append(True))
        for message in (b"", main.SHOW_MESSAGE):  # lancement --minimized, puis lancement normal
            client = QLocalSocket()
            client.connectToServer(name)
            self.assertTrue(client.waitForConnected(1000))
            client.write(message)
            client.flush()
            client.waitForBytesWritten(1000)
            client.disconnectFromServer()
        pump_until(lambda: shown)
        self.assertEqual(shown, [True])


if __name__ == "__main__":
    unittest.main()
