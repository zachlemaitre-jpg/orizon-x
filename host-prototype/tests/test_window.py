import importlib.util
import os
import unittest

HAVE_QT = importlib.util.find_spec("PySide6") is not None
if HAVE_QT:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtCore import QCoreApplication, Qt
    from PySide6.QtGui import QPixmap
    from PySide6.QtWidgets import QApplication

    from app import i18n
    from app.window import MainWindow

from engine import DisplayInfo, State, StreamStats
from inputstate import Rect
from messages import msg

INEXACT = DisplayInfo((2800, 1752), (2560, 1600), False, Rect(2560, 0, 2560, 1600))
EXACT = DisplayInfo((2880, 1800), (2880, 1800), True, Rect(2560, 0, 2880, 1800))


@unittest.skipUnless(HAVE_QT, "PySide6 absent")
class WindowTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        i18n.set_language("fr")  # les textes historiques ; l'anglais est vérifié par les tests de bascule
        self.addCleanup(i18n.set_language, "en")
        pixmap = QPixmap(32, 32)
        pixmap.fill()
        self.window = MainWindow(pixmap)
        self.events = []
        self.window.mode_changed.connect(lambda v: self.events.append(("mode", v)))
        self.window.position_changed.connect(lambda v: self.events.append(("position", v)))
        self.window.scale_changed.connect(lambda v: self.events.append(("scale", v)))
        self.window.encoder_changed.connect(lambda v: self.events.append(("encoder", v)))
        self.window.language_chosen.connect(lambda v: self.events.append(("language", v)))
        self.window.closed_to_tray.connect(lambda: self.events.append(("closed",)))
        self.window.quit_clicked.connect(lambda: self.events.append(("quit",)))
        self.window.use_duplicate_clicked.connect(lambda: self.events.append(("use_duplicate",)))
        self.window.add_resolution_clicked.connect(lambda w, h: self.events.append(("add_resolution", w, h)))
        self.window.adjust_requested.connect(lambda: self.events.append(("adjust",)))

    def tearDown(self):
        self.window.deleteLater()

    def test_state_drives_texts(self):
        self.window.set_state(State.WAITING_APP, msg("state.waiting_app"))
        self.assertEqual(self.window.title_text(), "Ouvre Orizon X sur la tablette")
        self.assertEqual(self.window.detail_text(), "Tablette branchée : ouvre Orizon X dessus.")
        self.assertEqual(self.window.primary_text(), "Arrêter")
        self.window.set_state(State.ERROR, msg("error.unexpected", error="boom"))
        self.assertEqual(self.window.detail_text(), "Erreur inattendue : boom")
        self.assertEqual(self.window.primary_text(), "Réessayer")

    def test_actions_state_shows_the_device(self):
        self.window.set_state(State.ACTIONS, msg("state.actions", name="Pixel 8"))
        self.assertEqual(self.window.title_text(), "Appareil Actions")
        self.assertEqual(self.window.detail_text(), "Pixel 8 connecté")
        self.assertEqual(self.window.primary_text(), "Arrêter")
        i18n.set_language("en")
        self.assertEqual((self.window.title_text(), self.window.detail_text(), self.window.primary_text()),
                         ("Actions device", "Pixel 8 connected", "Stop"))

    def test_stats_only_shown_while_streaming(self):
        stats = StreamStats(2880, 1800, 60, 18.0, 30.0, 0, 0.4)
        self.window.set_state(State.WAITING_APP, msg("state.waiting_app"))
        self.window.set_stats(stats)
        self.assertEqual(self.window.detail_text(), "Tablette branchée : ouvre Orizon X dessus.")
        self.window.set_state(State.STREAMING, msg("state.streaming", width=2880, height=1800))
        self.window.set_stats(stats)
        self.assertEqual(self.window.detail_text(), "2880×1800 · 60 fps · 18 ms")

    def test_combos_list_their_choices_in_french(self):
        self.assertEqual(self.window.combo_items("mode"), [("Étendre", "extend"), ("Dupliquer", "duplicate")])
        self.assertEqual(self.window.combo_items("position"),
                         [("À droite", "right"), ("À gauche", "left"), ("Au-dessus", "above"), ("En dessous", "below")])
        self.assertEqual(self.window.combo_items("scale"),
                         [("Auto", "auto"), ("100 %", "100"), ("125 %", "125"), ("150 %", "150"), ("175 %", "175"),
                          ("200 %", "200"), ("225 %", "225"), ("250 %", "250")])
        self.assertEqual(self.window.combo_items("encoder"),
                         [("Auto", "auto"), ("AMF (AMD)", "amf"), ("NVENC (NVIDIA)", "nvenc")])
        self.assertEqual(self.window.field_labels(), ["Mode", "Position", "Échelle", "Encodeur", "Langue"])
        self.assertEqual((self.window.adjust_text(), self.window.quit_text()), ("Régler dans Windows…", "Quitter"))

    def test_combos_and_labels_in_english(self):
        i18n.set_language("en")
        self.assertEqual(self.window.combo_items("mode"), [("Extend", "extend"), ("Duplicate", "duplicate")])
        self.assertEqual([label for label, _v in self.window.combo_items("position")],
                         ["Right", "Left", "Above", "Below"])
        self.assertEqual([label for label, _v in self.window.combo_items("scale")],
                         ["Auto", "100%", "125%", "150%", "175%", "200%", "225%", "250%"])
        self.assertEqual(self.window.field_labels(), ["Mode", "Position", "Scale", "Encoder", "Language"])
        self.assertEqual((self.window.adjust_text(), self.window.quit_text()), ("Adjust in Windows…", "Quit"))

    def test_settings_are_shown_without_signals(self):
        self.window.set_mode("duplicate")
        self.window.set_position("below")
        self.window.set_scale("175")
        self.window.set_encoder("nvenc")
        self.assertEqual([self.window.selected(name) for name in ("mode", "position", "scale", "encoder")],
                         ["duplicate", "below", "175", "nvenc"])
        self.assertEqual(self.events, [])

    def test_user_choice_emits(self):
        self.window.choose("mode", "duplicate")
        self.window.choose("mode", "extend")
        self.window.choose("position", "left")
        self.window.choose("scale", "150")
        self.window.choose_encoder("amf")
        self.assertEqual(self.events, [("mode", "duplicate"), ("mode", "extend"), ("position", "left"),
                                       ("scale", "150"), ("encoder", "amf")])

    def test_position_and_scale_are_disabled_in_duplicate(self):
        self.assertTrue(self.window.is_enabled("position") and self.window.is_enabled("scale"))
        self.window.set_mode("duplicate")
        self.assertEqual([self.window.is_enabled(n) for n in ("mode", "position", "scale", "encoder", "language")],
                         [True, False, False, True, True])
        self.window.choose("mode", "extend")  # choix de l'utilisateur : réactivés tout de suite
        self.assertTrue(self.window.is_enabled("position") and self.window.is_enabled("scale"))
        self.window.choose("mode", "duplicate")
        self.assertFalse(self.window.is_enabled("position") or self.window.is_enabled("scale"))

    def test_quit_button_emits(self):
        self.window._quit.click()
        self.assertEqual(self.events, [("quit",)])

    def test_adjust_link_emits(self):
        self.window._adjust.click()
        self.assertEqual(self.events, [("adjust",)])

    def test_use_duplicate_only_on_the_missing_driver_error(self):
        self.window.show()
        self.assertFalse(self.window.use_duplicate_visible())
        for state, detail in ((State.ERROR, msg("display.timeout")), (State.ERROR, msg("error.no_encoder")),
                              (State.WAITING_DEVICE, msg("adb.no_device"))):
            self.window.set_state(state, detail)
            self.assertFalse(self.window.use_duplicate_visible(), detail)
        self.window.set_state(State.ERROR, msg("display.vdd_missing"))
        self.assertTrue(self.window.use_duplicate_visible())
        self.assertEqual(self.window.use_duplicate_text(), "Passer en Dupliquer")
        self.window._use_duplicate.click()
        self.assertEqual(self.events, [("use_duplicate",)])
        i18n.set_language("en")
        self.assertEqual(self.window.use_duplicate_text(), "Use Duplicate")
        self.window.set_state(State.WAITING_DEVICE, msg("adb.no_device"))  # l'erreur est passée
        self.assertFalse(self.window.use_duplicate_visible())

    def test_add_exact_resolution_only_after_an_inexact_display(self):
        self.window.show()
        self.window.set_state(State.PREPARING_DISPLAY, msg("state.preparing_display"))
        self.window.set_display_info(EXACT)
        self.window.set_state(State.STREAMING, msg("state.starting_stream"))
        self.assertFalse(self.window.add_resolution_visible())
        self.window.set_state(State.PREPARING_DISPLAY, msg("state.preparing_display"))  # nouvelle session
        self.window.set_display_info(INEXACT)
        self.window.set_state(State.STREAMING, msg("state.starting_stream"))
        self.window.set_state(State.STREAMING, msg("state.streaming", width=2560, height=1600))
        self.assertTrue(self.window.add_resolution_visible())
        self.assertEqual(self.window.add_resolution_text(), "Ajouter la résolution exacte")
        self.assertIn("2800×1752", self.window.add_resolution_tooltip())
        i18n.set_language("en")
        self.assertEqual(self.window.add_resolution_text(), "Add exact resolution")
        self.assertIn("2800×1752", self.window.add_resolution_tooltip())
        self.window._add_resolution.click()
        self.assertEqual(self.events, [("add_resolution", 2800, 1752)])
        self.assertFalse(self.window.add_resolution_visible())  # une seule invite UAC par clic

    def test_add_exact_resolution_hides_when_the_session_ends(self):
        self.window.show()
        for state, detail in ((State.WAITING_APP, msg("state.waiting_app")), (State.STOPPED, msg("state.stopped")),
                              (State.PREPARING_DISPLAY, msg("state.preparing_display")),
                              (State.ERROR, msg("display.timeout"))):
            with self.subTest(state=state):
                self.window.set_state(State.PREPARING_DISPLAY, msg("state.preparing_display"))
                self.window.set_display_info(INEXACT)
                self.window.set_state(State.STREAMING, msg("state.starting_stream"))
                self.assertTrue(self.window.add_resolution_visible())
                self.window.set_state(state, detail)
                self.assertFalse(self.window.add_resolution_visible())

    def test_exact_display_after_an_inexact_one_hides_the_button(self):
        self.window.show()
        self.window.set_display_info(INEXACT)
        self.window.set_display_info(EXACT)
        self.assertFalse(self.window.add_resolution_visible())

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

    def test_language_switch_retranslates_live(self):
        self.window.set_position("left")
        self.window.set_state(State.STOPPED, msg("state.stopped"))
        self.assertEqual((self.window.title_text(), self.window.detail_text(), self.window.primary_text()),
                         ("Arrêté", "Clique sur Démarrer.", "Démarrer"))
        self.assertEqual(self.window.field_labels(), ["Mode", "Position", "Échelle", "Encodeur", "Langue"])
        self.assertEqual(self.window.tooltips(), ["Réduire", "Fermer (Orizon X continue dans la zone de notification)"])
        i18n.set_language("en")
        self.assertEqual((self.window.title_text(), self.window.detail_text(), self.window.primary_text()),
                         ("Stopped", "Click Start.", "Start"))
        self.assertEqual(self.window.field_labels(), ["Mode", "Position", "Scale", "Encoder", "Language"])
        self.assertEqual(self.window.selected_language(), "en")  # la liste suit une bascule faite ailleurs
        self.assertEqual(self.window.tooltips(), ["Minimize", "Close (Orizon X keeps running in the notification area)"])
        self.assertEqual(self.window.combo_items("position")[1], ("Left", "left"))
        self.assertEqual(self.window.selected("position"), "left")  # la sélection ne bouge pas
        self.window.set_state(State.WAITING_APP, msg("state.waiting_app"))
        self.assertEqual(self.window.primary_text(), "Stop")
        self.assertEqual(self.window.detail_text(), "Tablet plugged in. Open Orizon X on it.")
        i18n.set_language("fr")
        self.assertEqual(self.window.primary_text(), "Arrêter")
        self.assertEqual(self.window.title_text(), "Ouvre Orizon X sur la tablette")
        self.assertEqual(self.window.detail_text(), "Tablette branchée : ouvre Orizon X dessus.")
        self.assertEqual(self.window.combo_items("position")[1], ("À gauche", "left"))
        self.assertEqual(self.window.combo_items("mode"), [("Étendre", "extend"), ("Dupliquer", "duplicate")])
        self.assertEqual(self.events, [])  # changer de langue ne touche pas aux réglages

    def test_language_list_shows_each_language_in_its_own_name(self):
        self.assertEqual(self.window.language_items(), [("English", "en"), ("Français", "fr")])
        self.assertEqual(self.window.selected_language(), "fr")

    def test_choosing_a_language_only_emits(self):
        self.window.choose_language("en")
        self.assertEqual(self.events, [("language", "en")])
        self.assertEqual(self.window.primary_text(), "Démarrer")  # la bascule passe par i18n.set_language (main.wire)

    def test_everything_fits_in_the_window(self):
        self.assertEqual(self.window.width(), 360)
        self.window.show()
        for lang in ("fr", "en"):
            i18n.set_language(lang)
            for show_action in (False, True):  # un bouton d'action (Passer en Dupliquer…) sous l'état, ou aucun
                with self.subTest(lang=lang, action=show_action):
                    if show_action:
                        self.window.set_state(State.ERROR, msg("display.vdd_missing"))
                    else:
                        self.window.set_state(State.STOPPED, msg("state.stopped"))
                    QCoreApplication.processEvents()
                    self.assertLessEqual(self.window.layout().minimumSize().height(), self.window.height())
                    self.assertLessEqual(self.window.layout().totalSizeHint().height(), self.window.height())
                    for widget in self.window.visible_controls():
                        self.assertGreaterEqual(widget.width(), widget.minimumSizeHint().width(), widget)
                        self.assertGreaterEqual(widget.height(), widget.minimumSizeHint().height(), widget)
                        bottom = widget.mapTo(self.window, widget.rect().bottomRight()).y()
                        self.assertLess(bottom, self.window.height(), widget)

    def test_language_switch_keeps_the_stream_stats(self):
        self.window.set_state(State.STREAMING, msg("state.streaming", width=2880, height=1800))
        self.window.set_stats(StreamStats(2880, 1800, 60, 18.0, 30.0, 0, 0.4))
        i18n.set_language("en")
        self.assertEqual((self.window.title_text(), self.window.detail_text()), ("Connected", "2880×1800 · 60 fps · 18 ms"))

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
