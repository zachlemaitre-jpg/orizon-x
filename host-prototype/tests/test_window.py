import importlib.util
import os
import unittest

HAVE_QT = importlib.util.find_spec("PySide6") is not None
if HAVE_QT:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtCore import QCoreApplication, Qt
    from PySide6.QtGui import QPixmap
    from PySide6.QtWidgets import QApplication

    from app.window import MainWindow

from engine import State, StreamStats


@unittest.skipUnless(HAVE_QT, "PySide6 absent")
class WindowTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        pixmap = QPixmap(32, 32)
        pixmap.fill()
        self.window = MainWindow(pixmap)
        self.events = []
        self.window.output_changed.connect(lambda v: self.events.append(("output", v)))
        self.window.encoder_changed.connect(lambda v: self.events.append(("encoder", v)))
        self.window.closed_to_tray.connect(lambda: self.events.append(("closed",)))

    def tearDown(self):
        self.window.deleteLater()

    def test_state_drives_texts(self):
        self.window.set_state(State.WAITING_APP, "Tablette branchée : ouvre Orizon X dessus.")
        self.assertEqual(self.window.title_text(), "Ouvre Orizon X sur la tablette")
        self.assertEqual(self.window.detail_text(), "Tablette branchée : ouvre Orizon X dessus.")
        self.assertEqual(self.window.primary_text(), "Arrêter")
        self.window.set_state(State.ERROR, "boom")
        self.assertEqual(self.window.primary_text(), "Réessayer")

    def test_stats_only_shown_while_streaming(self):
        stats = StreamStats(2880, 1800, 60, 18.0, 30.0, 0, 0.4)
        self.window.set_state(State.WAITING_APP, "x")
        self.window.set_stats(stats)
        self.assertEqual(self.window.detail_text(), "x")
        self.window.set_state(State.STREAMING, "Flux 2880×1800")
        self.window.set_stats(stats)
        self.assertEqual(self.window.detail_text(), "2880×1800 · 60 fps · 18 ms")

    def test_outputs_list_and_selection_without_signal(self):
        self.window.set_outputs([(0, (2560, 1600)), (1, (2880, 1800))], "1")
        self.assertEqual(self.window.output_items(),
                         [("Auto (taille de la tablette)", "auto"), ("Écran 0 — 2560×1600", "0"),
                          ("Écran 1 — 2880×1800", "1")])
        self.assertEqual(self.window.selected_output(), "1")
        self.assertEqual(self.events, [])

    def test_unknown_saved_output_is_kept(self):
        self.window.set_outputs([], "3")
        self.assertEqual(self.window.selected_output(), "3")

    def test_user_choice_emits(self):
        self.window.set_outputs([(0, (2560, 1600))], "auto")
        self.window.choose_output("0")
        self.window.set_encoder("auto")
        self.window.choose_encoder("amf")
        self.assertEqual(self.events, [("output", "0"), ("encoder", "amf")])

    def test_close_hides_and_tells(self):
        self.window.show()
        self.window.close()
        self.assertFalse(self.window.isVisible())
        self.assertEqual(self.events, [("closed",)])

    def test_close_while_quitting_is_accepted_silently(self):
        self.window.show()
        self.window.prepare_quit()
        self.assertTrue(self.window.close())
        self.assertEqual(self.events, [])

    def test_frameless_but_minimizable_from_the_taskbar(self):
        flags = self.window.windowFlags()
        for flag in (Qt.WindowType.FramelessWindowHint, Qt.WindowType.WindowMinimizeButtonHint,
                     Qt.WindowType.WindowSystemMenuHint):
            self.assertTrue(flags & flag, flag)

    def test_outputs_wait_for_the_open_list_to_close(self):
        self.window.show()
        self.window.set_outputs([(0, (2560, 1600))], "auto")
        self.window._outputs.showPopup()
        self.window.set_outputs([(0, (2560, 1600)), (1, (2880, 1800))], "auto")
        self.assertEqual(len(self.window.output_items()), 2)  # liste ouverte : pas de saut sous le curseur
        # Clic sur un élément : Qt ferme la liste puis émet activated avec l'index de l'ancienne liste.
        self.window._outputs.hidePopup()
        self.window.choose_output("0")
        QCoreApplication.processEvents()
        self.assertEqual([value for _label, value in self.window.output_items()], ["auto", "0", "1"])
        self.assertEqual(self.window.selected_output(), "0")  # le choix de l'utilisateur est gardé
        self.assertEqual(self.events, [("output", "0")])

    def test_brand_title_uses_mazagla_and_title_bar_has_no_name(self):
        self.assertEqual(self.window.brand_title_family(), "MAZAGLA")
        self.assertEqual(self.window.brand_title_text(), "Orizon X")
        self.assertNotIn("Orizon X", self.window.title_bar_texts())

    def test_stylesheet_gives_the_brand_title_its_own_font_rule(self):
        # Hors écran il n'y a pas de police système qui lui fasse concurrence : on vérifie donc la règle elle-même.
        from app.window import build_style
        self.assertIn('QLabel#brandTitle { font-family: "MAZAGLA";', build_style("MAZAGLA"))


if __name__ == "__main__":
    unittest.main()
