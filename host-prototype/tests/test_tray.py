import importlib.util
import os
import unittest

HAVE_QT = importlib.util.find_spec("PySide6") is not None
if HAVE_QT:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtGui import QPixmap
    from PySide6.QtWidgets import QApplication

    from app import i18n, tray

from engine import State
from messages import msg


@unittest.skipUnless(HAVE_QT, "PySide6 absent")
class TrayTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        i18n.set_language("fr")
        self.addCleanup(i18n.set_language, "en")
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
        self.tray.set_state(State.STREAMING, msg("state.streaming", width=2880, height=1800))
        self.assertEqual(self.tray.toggle_text(), "Arrêter")
        self.assertIn("Connecté", self.tray.status_text())
        self.assertIn("Flux 2880×1800", self.tray.tooltip())
        self.tray.set_state(State.ERROR, msg("error.unexpected", error="boom"))
        self.assertEqual(self.tray.toggle_text(), "Réessayer")
        self.assertEqual(self.tray.status_text(), "Erreur — Erreur inattendue : boom")

    def test_language_switch_retranslates_live(self):
        self.tray.set_state(State.STREAMING, msg("state.streaming", width=2880, height=1800))
        self.assertEqual(self.tray.menu_texts(), ["Connecté — Flux 2880×1800", "Arrêter", "Ouvrir la fenêtre",
                                                  "Ouvrir le journal", "Lancer avec Windows", "Quitter"])
        self.assertEqual(self.tray.autostart_tooltip(), "Disponible dans l'appli compilée (OrizonX.exe)")
        i18n.set_language("en")
        self.assertEqual(self.tray.menu_texts(), ["Connected — Stream 2880×1800", "Stop", "Open window", "Open log",
                                                  "Start with Windows", "Quit"])
        self.assertEqual(self.tray.tooltip(), "Orizon X — Connected\nStream 2880×1800")
        self.assertEqual(self.tray.autostart_tooltip(), "Available in the built app (OrizonX.exe)")
        seen = []
        self.tray.quit_requested.connect(lambda: seen.append("quit"))
        self.tray.trigger("Quit")
        self.assertEqual(seen, ["quit"])

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
