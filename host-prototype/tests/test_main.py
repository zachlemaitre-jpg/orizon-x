import importlib.util
import os
import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock

HAVE_QT = importlib.util.find_spec("PySide6") is not None
if HAVE_QT:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtCore import QObject, Signal
    from PySide6.QtGui import QPixmap
    from PySide6.QtNetwork import QLocalServer, QLocalSocket
    from PySide6.QtWidgets import QApplication

    from app import i18n, main
    from app.controller import Controller
    from app.settings import Settings
    from app.tray import Tray
    from app.window import MainWindow
    from tests.test_controller import FakeEngine, pump_until

    class FakeProber(QObject):
        done = Signal(object)

        def probe(self):
            pass

import tools
from engine import State
from messages import msg


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
        self.controller = Controller(FakeEngine, main.engine.Config())
        logo = QPixmap(64, 64)
        logo.fill()
        self.window = MainWindow(logo)
        self.tray = Tray(logo, autostart_supported=False, autostart_enabled=False)
        self.addCleanup(self.tray.hide)
        self.quits = []
        main.wire(controller=self.controller, window=self.window, tray=self.tray, prober=FakeProber(),
                  current=self.current, settings_path=self.settings_path, log_path=self.settings_path,
                  quit_app=lambda: self.quits.append(True))

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
            restart.assert_called_once_with(main.engine.Config(output="auto", encoder="amf"))
        self.assertEqual(self.current.encoder, "amf")

    def test_state_is_logged_in_english(self):
        with self.assertLogs("orizonx", "INFO") as logs:
            self.controller.state_changed.emit(State.WAITING_DEVICE, msg("adb.no_device"))
        self.assertEqual(logs.records[-1].getMessage(),
                         "State: waiting_device — No tablet found. Plug in the USB cable and turn on USB debugging.")
        self.assertEqual(self.window.detail_text(),
                         "Aucune tablette détectée : branche le câble USB et active le débogage USB.")

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

    def test_quit_hides_first_then_stops_without_the_close_hint(self):
        self.window.show()
        self.assertTrue(self.window.isVisible() and self.tray.is_visible())
        seen = []
        with mock.patch.object(self.controller, "stop_blocking",
                               side_effect=lambda: seen.append((self.window.isVisible(), self.tray.is_visible()))):
            self.tray.trigger("Quitter")
        self.assertEqual(seen, [(False, False)])
        self.assertEqual(self.quits, [True])
        self.assertFalse(self.current.first_close_hint_shown)


@unittest.skipUnless(HAVE_QT, "PySide6 absent")
class InstanceAndProberTest(unittest.TestCase):
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

    def test_one_probe_at_a_time_and_missing_ffmpeg_is_one_line(self):
        release = threading.Event()
        calls = []

        def find_tool(name):
            calls.append(name)
            release.wait(2)
            raise tools.ToolMissing(msg("tools.ffmpeg_missing"))

        prober = main.OutputProber()
        results = []
        prober.done.connect(results.append)
        with mock.patch.object(main.tools, "find_tool", find_tool), self.assertLogs("orizonx", "INFO") as logs:
            prober.probe()
            prober.probe()  # ignorée : une liste est déjà en cours
            release.set()
            pump_until(lambda: results)
        self.assertEqual((calls, results), (["ffmpeg"], [[]]))
        self.assertEqual([record.exc_info for record in logs.records], [None])


if __name__ == "__main__":
    unittest.main()
