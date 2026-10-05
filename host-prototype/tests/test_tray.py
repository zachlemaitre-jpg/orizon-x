import importlib.util
import os
import unittest

HAVE_QT = importlib.util.find_spec("PySide6") is not None
if HAVE_QT:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtGui import QPixmap
    from PySide6.QtWidgets import QApplication

    from app import tray

from engine import State


@unittest.skipUnless(HAVE_QT, "PySide6 absent")
class TrayTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        logo = QPixmap(64, 64)
        logo.fill()
        self.tray = tray.Tray(logo, autostart_supported=False, autostart_enabled=False)

    def tearDown(self):
        self.tray.hide()

    def test_badge_icon_is_not_null(self):
        logo = QPixmap(64, 64)
        logo.fill()
        self.assertFalse(tray.badge_icon(logo, "#4ADE80").isNull())

    def test_state_updates_menu_and_tooltip(self):
        self.tray.set_state(State.STREAMING, "Flux 2880×1800")
        self.assertEqual(self.tray.toggle_text(), "Arrêter")
        self.assertIn("Connecté", self.tray.status_text())
        self.assertIn("Flux 2880×1800", self.tray.tooltip())
        self.tray.set_state(State.ERROR, "boom")
        self.assertEqual(self.tray.toggle_text(), "Réessayer")

    def test_autostart_entry_disabled_from_source(self):
        self.assertFalse(self.tray.autostart_action_enabled())

    def test_menu_actions_emit(self):
        seen = []
        self.tray.quit_requested.connect(lambda: seen.append("quit"))
        self.tray.toggle_requested.connect(lambda: seen.append("toggle"))
        self.tray.trigger("Quitter")
        self.tray.trigger("Démarrer")  # la zone de notification démarre à l'état « Arrêté »
        self.assertEqual(seen, ["quit", "toggle"])


if __name__ == "__main__":
    unittest.main()
