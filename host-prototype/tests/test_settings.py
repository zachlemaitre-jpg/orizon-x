import json
import tempfile
import unittest
from pathlib import Path

from app import settings


class SettingsTest(unittest.TestCase):
    def setUp(self):
        self.path = Path(tempfile.mkdtemp()) / "OrizonX" / "settings.json"

    def test_missing_file_gives_defaults(self):
        self.assertEqual(settings.load(self.path), settings.Settings())

    def test_defaults(self):
        self.assertEqual(settings.Settings(), settings.Settings(encoder="auto", mode="extend", position="right",
                                                                scale="auto", applied_position=None,
                                                                applied_scale=None, first_close_hint_shown=False,
                                                                language=None))
        self.assertFalse(hasattr(settings.Settings(), "output"))
        self.assertFalse(hasattr(settings.Settings(), "layout_applied"))

    def test_choices(self):
        import display_layout
        self.assertEqual(settings.MODES, ("extend", "duplicate"))
        self.assertEqual(settings.POSITIONS, display_layout.SIDES)
        self.assertEqual(settings.SCALES, ("auto", "100", "125", "150", "175", "200", "225", "250"))
        self.assertTrue(set(settings.SCALES[1:]) <= {str(step) for step in display_layout.SCALE_STEPS})

    def test_round_trip(self):
        saved = settings.Settings(encoder="amf", mode="duplicate", position="above", scale="175",
                                  applied_position="left", applied_scale="auto", first_close_hint_shown=True,
                                  language="fr")
        settings.save(saved, self.path)
        self.assertEqual(settings.load(self.path), saved)

    def test_old_layout_applied_flag_means_the_saved_position_and_scale_were_applied(self):
        self.path.parent.mkdir(parents=True)
        for applied, expected in ((True, ("below", "150")), (False, (None, None))):
            with self.subTest(layout_applied=applied):
                self.path.write_text(json.dumps({"position": "below", "scale": "150", "layout_applied": applied}),
                                     encoding="utf-8")
                loaded = settings.load(self.path)
                self.assertEqual((loaded.applied_position, loaded.applied_scale), expected)
                settings.save(loaded, self.path)
                self.assertNotIn("layout_applied", json.loads(self.path.read_text(encoding="utf-8")))
                self.assertEqual(settings.load(self.path), loaded)

    def test_applied_pair_wins_over_the_old_flag_and_needs_both_values(self):
        self.path.parent.mkdir(parents=True)
        self.path.write_text(json.dumps({"position": "below", "layout_applied": True, "applied_position": "left",
                                         "applied_scale": "200"}), encoding="utf-8")
        loaded = settings.load(self.path)
        self.assertEqual((loaded.applied_position, loaded.applied_scale), ("left", "200"))
        for raw in ({"applied_position": "left"}, {"applied_position": "middle", "applied_scale": "200"},
                    {"applied_position": "left", "applied_scale": 200}):
            with self.subTest(raw=raw):
                self.path.write_text(json.dumps(raw), encoding="utf-8")
                loaded = settings.load(self.path)
                self.assertEqual((loaded.applied_position, loaded.applied_scale), (None, None))

    def test_corrupt_json_gives_defaults(self):
        self.path.parent.mkdir(parents=True)
        self.path.write_text("{pas du json", encoding="utf-8")
        self.assertEqual(settings.load(self.path), settings.Settings())

    def test_invalid_values_fall_back_one_by_one(self):
        self.path.parent.mkdir(parents=True)
        self.path.write_text(json.dumps({"encoder": "amf", "first_close_hint_shown": "oui", "mode": "mirror",
                                         "position": "left", "scale": "300", "layout_applied": "yes",
                                         "applied_position": 3, "applied_scale": "300"}),
                             encoding="utf-8")
        self.assertEqual(settings.load(self.path), settings.Settings(encoder="amf", position="left"))
        for bad_scale in (150, "90", "auto ", None):
            self.path.write_text(json.dumps({"scale": bad_scale}), encoding="utf-8")
            self.assertEqual(settings.load(self.path).scale, "auto", bad_scale)

    def test_old_file_with_a_screen_choice_still_loads(self):
        self.path.parent.mkdir(parents=True)
        self.path.write_text(json.dumps({"output": "1", "encoder": "nvenc", "first_close_hint_shown": True,
                                         "language": "fr"}), encoding="utf-8")
        loaded = settings.load(self.path)
        self.assertEqual(loaded, settings.Settings(encoder="nvenc", first_close_hint_shown=True, language="fr"))
        settings.save(loaded, self.path)
        self.assertNotIn("output", json.loads(self.path.read_text(encoding="utf-8")))

    def test_language_follows_the_installer_until_chosen(self):
        self.assertIsNone(settings.Settings().language)
        for raw, expected in (("en", "en"), ("fr", "fr"), ("de", None), (None, None), (1, None)):
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_text(json.dumps({"language": raw}), encoding="utf-8")
            self.assertEqual(settings.load(self.path).language, expected, raw)

    def test_non_object_json_gives_defaults(self):
        self.path.parent.mkdir(parents=True)
        self.path.write_text("[1, 2]", encoding="utf-8")
        self.assertEqual(settings.load(self.path), settings.Settings())

    def test_save_is_atomic_and_leaves_no_temp_file(self):
        settings.save(settings.Settings(), self.path)
        self.assertEqual([p.name for p in self.path.parent.iterdir()], ["settings.json"])

    def test_default_path_is_under_appdata(self):
        self.assertEqual(settings.default_path().parts[-2:], ("OrizonX", "settings.json"))


if __name__ == "__main__":
    unittest.main()
