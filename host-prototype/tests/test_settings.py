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

    def test_round_trip(self):
        saved = settings.Settings(output="2", encoder="amf", first_close_hint_shown=True, language="fr")
        settings.save(saved, self.path)
        self.assertEqual(settings.load(self.path), saved)

    def test_corrupt_json_gives_defaults(self):
        self.path.parent.mkdir(parents=True)
        self.path.write_text("{pas du json", encoding="utf-8")
        self.assertEqual(settings.load(self.path), settings.Settings())

    def test_invalid_values_fall_back_one_by_one(self):
        self.path.parent.mkdir(parents=True)
        self.path.write_text(json.dumps({"output": "deux", "encoder": "amf", "first_close_hint_shown": "oui"}),
                             encoding="utf-8")
        self.assertEqual(settings.load(self.path), settings.Settings(encoder="amf"))

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
