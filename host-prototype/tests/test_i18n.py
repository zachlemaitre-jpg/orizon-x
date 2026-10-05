import importlib.util
import os
import re
import string
import unittest
from pathlib import Path

import messages
from messages import Msg, msg, tr

HAVE_QT = importlib.util.find_spec("PySide6") is not None
if HAVE_QT:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from app import i18n

ROOT = Path(messages.__file__).resolve().parent


def placeholders(text):
    return {name for _literal, name, _spec, _conv in string.Formatter().parse(text) if name is not None}


def source_files():
    return [p for p in [*ROOT.glob("*.py"), *(ROOT / "app").glob("*.py")] if p.name != "messages.py"]


class TextsTest(unittest.TestCase):
    def test_every_key_has_english_and_french(self):
        for key, texts in messages.TEXTS.items():
            self.assertEqual(set(texts), {"en", "fr"}, key)
            self.assertTrue(texts["en"].strip() and texts["fr"].strip(), key)

    def test_placeholders_are_the_same_in_both_languages(self):
        for key, texts in messages.TEXTS.items():
            self.assertEqual(placeholders(texts["en"]), placeholders(texts["fr"]), key)

    def test_keys_used_in_the_code_exist_and_every_key_is_used(self):
        namespaces = {key.split(".")[0] for key in messages.TEXTS}
        pattern = re.compile(r'"((?:%s)\.[a-z0-9_.]+)"' % "|".join(sorted(namespaces)))
        used = set()
        for path in source_files():
            used.update(pattern.findall(path.read_text(encoding="utf-8")))
        self.assertGreater(len(used), 20)  # le motif trouve bien les clés
        self.assertEqual(sorted(used - set(messages.TEXTS)), [])  # une faute de frappe planterait l'appli (tr strict)
        self.assertEqual(sorted(set(messages.TEXTS) - used), [])


class TrTest(unittest.TestCase):
    def test_translates_with_arguments(self):
        self.assertEqual(tr("state.streaming", "en", width=2880, height=1800), "Stream 2880×1800")
        self.assertEqual(tr("state.streaming", "fr", width=2880, height=1800), "Flux 2880×1800")

    def test_english_is_the_default_and_the_fallback(self):
        self.assertEqual(tr("status.stopped"), "Stopped")
        self.assertEqual(tr("status.stopped", "de"), "Stopped")

    def test_unknown_key_is_an_error(self):
        with self.assertRaises(KeyError):
            tr("status.nope", "en")

    def test_missing_argument_is_an_error(self):
        with self.assertRaises(KeyError):
            tr("state.streaming", "en", width=1)

    def test_message_arguments_are_translated_in_the_same_language(self):
        message = msg("error.ffmpeg_keeps_stopping", count=3, last=msg("error.no_message"))
        self.assertEqual(message.text("fr"), "ffmpeg s'arrête sans cesse (3 fois de suite). Dernier message : aucun message")
        self.assertEqual(message.text("en"), "ffmpeg keeps stopping (3 times in a row). Last message: no message")

    def test_list_arguments_become_one_line_each(self):
        lines = msg("outputs.list", lines=[msg("outputs.line", index=0, width=1920, height=1080),
                                          msg("outputs.line_unknown", index=1)])
        self.assertTrue(lines.text("fr").startswith("--output 0 : 1920x1080\n--output 1 : taille inconnue\n"))
        self.assertTrue(lines.text("en").startswith("--output 0: 1920x1080\n--output 1: unknown size\n"))


class MsgTest(unittest.TestCase):
    def test_msg_helper_builds_a_comparable_message(self):
        self.assertEqual(msg("state.streaming", width=1, height=2), Msg("state.streaming", {"width": 1, "height": 2}))
        self.assertEqual(msg("state.stopped"), Msg("state.stopped", {}))
        self.assertEqual(Msg("state.stopped").args, {})

    def test_text_defaults_to_english(self):
        self.assertEqual(msg("state.stopped").text(), "Stopped.")
        self.assertEqual(msg("state.stopped").text("fr"), "Arrêté.")

    def test_message_error_carries_the_message_and_reads_in_english(self):
        error = messages.MessageError(msg("error.unexpected", error="boom"))
        self.assertEqual(error.msg, msg("error.unexpected", error="boom"))
        self.assertEqual(str(error), "Unexpected error: boom")


class DetectLanguageTest(unittest.TestCase):
    def detect(self, setting, hkcu=None, hklm=None):
        values = {"HKCU": hkcu, "HKLM": hklm}
        return messages.detect_language(setting, read_registry=lambda hive: values[hive])

    def test_order_is_settings_then_hkcu_then_hklm_then_english(self):
        self.assertEqual(self.detect("fr", hkcu="en", hklm="en"), "fr")
        self.assertEqual(self.detect(None, hkcu="fr", hklm="en"), "fr")
        self.assertEqual(self.detect(None, hkcu=None, hklm="fr"), "fr")
        self.assertEqual(self.detect(None), "en")

    def test_unknown_values_are_skipped(self):
        self.assertEqual(self.detect("de", hkcu="klingon", hklm="fr"), "fr")
        self.assertEqual(self.detect(None, hkcu="", hklm="??"), "en")

    def test_registry_values_are_normalised(self):
        self.assertEqual(self.detect(None, hkcu=" FR "), "fr")
        self.assertEqual(self.detect(None, hkcu="fr-FR"), "fr")

    def test_registry_reader_never_fails(self):
        for hive in ("HKCU", "HKLM"):  # lecture seule ; la clé est absente tant que l'installateur n'est pas passé
            self.assertIsInstance(messages.read_registry_language(hive), (str, type(None)))


@unittest.skipUnless(HAVE_QT, "PySide6 absent")
class I18nTest(unittest.TestCase):
    def setUp(self):
        i18n.set_language("en")
        self.addCleanup(i18n.set_language, "en")
        self.seen = []
        i18n.language_changed.connect(self.seen.append)
        self.addCleanup(i18n.language_changed.disconnect, self.seen.append)

    def test_set_language_switches_and_signals_once(self):
        i18n.set_language("fr")
        i18n.set_language("fr")
        self.assertEqual(i18n.current_language(), "fr")
        self.assertEqual(self.seen, ["fr"])
        self.assertEqual(i18n.tr("status.stopped", i18n.current_language()), "Arrêté")

    def test_unknown_language_is_refused(self):
        with self.assertRaises(ValueError):
            i18n.set_language("de")
        self.assertEqual((i18n.current_language(), self.seen), ("en", []))

    def test_reexports(self):
        self.assertIs(i18n.tr, tr)
        self.assertIs(i18n.detect_language, messages.detect_language)


if __name__ == "__main__":
    unittest.main()
