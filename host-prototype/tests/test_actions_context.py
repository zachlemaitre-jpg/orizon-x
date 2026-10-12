import json
import unittest

from actions import context_profiles as cp
from actions import keys
from actions.context import ContextProvider
from actions.foreground import ForegroundApp


def app(exe, window_class="Cls", title="Window", pid=1):
    return ForegroundApp(exe, window_class, title, pid)


class MatchTest(unittest.TestCase):
    def test_known_exes(self):
        cases = {
            "Spotify.exe": "spotify",
            "POWERPNT.EXE": "powerpoint",
            "chrome.exe": "browser", "msedge.exe": "browser", "firefox.exe": "browser",
            "brave.exe": "browser", "opera.exe": "browser",
            "WINWORD.EXE": "word",
            "EXCEL.EXE": "excel",
            "Code.exe": "vscode",
        }
        for exe, profile in cases.items():
            with self.subTest(exe):
                self.assertEqual(cp.match(app(exe)).id, profile)

    def test_match_is_case_insensitive(self):
        self.assertEqual(cp.match(app("spotify.EXE")).id, "spotify")
        self.assertEqual(cp.match(app("powerpnt.exe")).id, "powerpoint")
        self.assertEqual(cp.match(app("CHROME.EXE")).id, "browser")

    def test_explorer_needs_a_folder_window(self):
        self.assertEqual(cp.match(app("explorer.exe", "CabinetWClass")).id, "explorer")
        self.assertEqual(cp.match(app("EXPLORER.EXE", "CabinetWClass")).id, "explorer")
        self.assertEqual(cp.match(app("explorer.exe", "#32770")).id, "generic")
        self.assertEqual(cp.match(app("explorer.exe", "")).id, "generic")

    def test_everything_else_is_generic(self):
        for exe in ("notepad.exe", "", "Slack.exe", "codex.exe"):
            with self.subTest(exe):
                self.assertEqual(cp.match(app(exe)).id, "generic")

    def test_no_app_is_generic(self):
        self.assertEqual(cp.match(None).id, "generic")


class DisplayNameTest(unittest.TestCase):
    def test_fixed_names(self):
        for exe, name in (("Spotify.exe", "Spotify"), ("POWERPNT.EXE", "PowerPoint"), ("WINWORD.EXE", "Word"),
                          ("EXCEL.EXE", "Excel"), ("Code.exe", "VS Code")):
            with self.subTest(exe):
                self.assertEqual(cp.display_name(app(exe)), name)

    def test_explorer(self):
        self.assertEqual(cp.display_name(app("explorer.exe", "CabinetWClass")), "Explorateur")

    def test_browsers_use_their_real_name(self):
        for exe, name in (("chrome.exe", "Chrome"), ("msedge.exe", "Edge"), ("firefox.exe", "Firefox"),
                          ("brave.exe", "Brave"), ("opera.exe", "Opera")):
            with self.subTest(exe):
                self.assertEqual(cp.display_name(app(exe)), name)

    def test_generic_uses_the_short_title(self):
        self.assertEqual(cp.display_name(app("notepad.exe", title="Untitled - Notepad")), "Notepad")

    def test_generic_falls_back_to_the_exe_without_extension(self):
        self.assertEqual(cp.display_name(app("Slack.exe", title="")), "Slack")
        self.assertEqual(cp.display_name(app("slack.EXE", title="  ")), "slack")

    def test_generic_with_nothing_at_all(self):
        self.assertEqual(cp.display_name(app("", title="")), "Application")
        self.assertEqual(cp.display_name(None), "Application")


class TableTest(unittest.TestCase):
    def test_profile_ids(self):
        self.assertEqual([p.id for p in cp.PROFILES],
                         ["spotify", "powerpoint", "browser", "word", "excel", "vscode", "explorer", "generic"])

    def test_each_profile_has_one_to_eight_buttons_with_unique_ids(self):
        seen = set()
        for profile in cp.PROFILES:
            with self.subTest(profile.id):
                self.assertTrue(1 <= len(profile.buttons) <= 8)
                for b in profile.buttons:
                    self.assertTrue(b.id and b.icon and b.label and b.shortcut)
                    self.assertNotIn(b.id, seen)
                    seen.add(b.id)

    def test_icons_come_from_the_known_list(self):
        for profile in cp.PROFILES:
            for b in profile.buttons:
                self.assertIn(b.icon, cp.ICON_NAMES, f"{profile.id}/{b.id}")

    def test_every_shortcut_parses(self):
        scan = lambda ch: {"-": 0xBD, "=": 0xBB, "/": 0xBF, "`": 0xC0}.get(ch, -1)  # noqa: E731
        for profile in cp.PROFILES:
            for b in profile.buttons:
                with self.subTest(profile.id + "/" + b.id):
                    self.assertTrue(keys.parse_shortcut(b.shortcut, scan))

    def test_shortcuts_follow_the_spec(self):
        def table(pid):
            return [(b.icon, b.label, b.shortcut) for b in cp.profile_by_id(pid).buttons]
        self.assertEqual([s for _, _, s in table("spotify")],
                         ["Ctrl+Left", "Space", "Ctrl+Right", "Alt+Shift+B", "Ctrl+S", "Ctrl+R"])
        self.assertEqual([s for _, _, s in table("powerpoint")], ["F5", "Shift+F5", "Left", "Right", "B", "Esc"])
        self.assertEqual([s for _, _, s in table("browser")],
                         ["Alt+Left", "Alt+Right", "F5", "Ctrl+T", "Ctrl+W", "Ctrl+-", "Ctrl+="])
        self.assertEqual([s for _, _, s in table("word")],
                         ["Ctrl+Z", "Ctrl+Y", "Ctrl+B", "Ctrl+I", "Ctrl+U", "Ctrl+S"])
        self.assertEqual([s for _, _, s in table("excel")],
                         ["Ctrl+Z", "Ctrl+Y", "Ctrl+B", "Alt+=", "Ctrl+Shift+L", "Ctrl+S"])
        self.assertEqual([s for _, _, s in table("vscode")],
                         ["Ctrl+Shift+P", "Ctrl+Shift+F", "Ctrl+OEM_3", "Ctrl+OEM_2", "Ctrl+S", "Ctrl+Shift+E"])
        self.assertEqual([s for _, _, s in table("explorer")],
                         ["Alt+Left", "Alt+Up", "Ctrl+Shift+N", "F2", "F5"])
        self.assertEqual([s for _, _, s in table("generic")],
                         ["Ctrl+C", "Ctrl+V", "Ctrl+Z", "Win+Shift+S", "Win+D", "Alt+Tab"])

    def test_labels_are_french(self):
        labels = {p.id: [b.label for b in p.buttons] for p in cp.PROFILES}
        self.assertEqual(labels["spotify"][:3], ["Précédent", "Lecture/Pause", "Suivant"])
        self.assertIn("Écran noir", labels["powerpoint"])
        self.assertIn("Nouvel onglet", labels["browser"])
        self.assertIn("Dossier parent", labels["explorer"])

    def test_profile_by_id(self):
        self.assertEqual(cp.profile_by_id("word").id, "word")
        self.assertIsNone(cp.profile_by_id("nope"))


class FakeTracker:
    def __init__(self, current=None):
        self.app = current

    def current(self):
        return self.app


class ContextProviderTest(unittest.TestCase):
    def setUp(self):
        self.tracker = FakeTracker()
        self.sent = []
        self.result = True
        self.logs = []
        self.provider = ContextProvider(tracker=self.tracker, send_shortcut=self._send, log=self.logs.append)

    def _send(self, shortcut):
        self.sent.append(shortcut)
        if isinstance(self.result, Exception):
            raise self.result
        return self.result

    def test_no_app_yet_is_unavailable(self):
        self.assertEqual(self.provider.snapshot(), {"available": False})

    def test_snapshot_shape(self):
        self.tracker.app = app("POWERPNT.EXE")
        snap = self.provider.snapshot()
        self.assertEqual(set(snap), {"available", "app", "profile", "buttons"})
        self.assertIs(snap["available"], True)
        self.assertEqual(snap["app"], "PowerPoint")
        self.assertEqual(snap["profile"], "powerpoint")
        self.assertEqual(snap["buttons"][0], {"id": "ppt.slideshow", "icon": "slideshow", "label": "Diaporama"})
        self.assertEqual(len(snap["buttons"]), 6)
        for b in snap["buttons"]:
            self.assertEqual(set(b), {"id", "icon", "label"})  # no shortcut leaks to the device
        json.dumps(snap)

    def test_generic_snapshot_names_the_window(self):
        self.tracker.app = app("notepad.exe", title="Untitled - Notepad")
        snap = self.provider.snapshot()
        self.assertEqual((snap["app"], snap["profile"]), ("Notepad", "generic"))

    def test_snapshot_follows_the_foreground(self):
        self.tracker.app = app("Spotify.exe")
        self.assertEqual(self.provider.snapshot()["profile"], "spotify")
        self.tracker.app = app("chrome.exe")
        snap = self.provider.snapshot()
        self.assertEqual((snap["app"], snap["profile"]), ("Chrome", "browser"))

    def test_press_sends_the_shortcut_of_the_button(self):
        self.tracker.app = app("Spotify.exe")
        code = self.provider.handle({"id": "context.press", "button": "spotify.playpause"})
        self.assertIsNone(code)
        self.assertEqual(self.sent, ["Space"])

    def test_press_every_button_of_every_profile(self):
        exes = {"spotify": ("Spotify.exe", "Cls"), "powerpoint": ("POWERPNT.EXE", "Cls"),
                "browser": ("chrome.exe", "Cls"), "word": ("WINWORD.EXE", "Cls"), "excel": ("EXCEL.EXE", "Cls"),
                "vscode": ("Code.exe", "Cls"), "explorer": ("explorer.exe", "CabinetWClass"),
                "generic": ("notepad.exe", "Cls")}
        for profile in cp.PROFILES:
            self.tracker.app = app(*exes[profile.id])
            for b in profile.buttons:
                with self.subTest(b.id):
                    self.sent.clear()
                    self.assertIsNone(self.provider.handle({"id": "context.press", "button": b.id}))
                    self.assertEqual(self.sent, [b.shortcut])

    def test_button_of_another_profile_is_ignored_and_logged(self):
        self.tracker.app = app("chrome.exe")  # the device still shows PowerPoint's bar
        code = self.provider.handle({"id": "context.press", "button": "ppt.next"})
        self.assertIsNone(code)
        self.assertEqual(self.sent, [])
        self.assertEqual(len(self.logs), 1)
        self.assertIn("ppt.next", self.logs[0])

    def test_unknown_or_malformed_button_sends_nothing(self):
        self.tracker.app = app("chrome.exe")
        for action in ({"id": "context.press"}, {"id": "context.press", "button": 5},
                       {"id": "context.press", "button": ""}, {"id": "context.press", "button": "nope"}):
            with self.subTest(action=action):
                self.assertIsNone(self.provider.handle(action))
        self.assertEqual(self.sent, [])

    def test_press_without_a_known_app_sends_nothing(self):
        self.assertIsNone(self.provider.handle({"id": "context.press", "button": "gen.copy"}))
        self.assertEqual(self.sent, [])

    def test_unknown_action_id_fails(self):
        self.tracker.app = app("chrome.exe")
        self.assertEqual(self.provider.handle({"id": "context.other"}), "action_failed")
        self.assertEqual(self.provider.handle({}), "action_failed")
        self.assertEqual(self.sent, [])

    def test_blocked_injection_reports_failure(self):
        self.tracker.app = app("chrome.exe")
        self.result = False
        self.assertEqual(self.provider.handle({"id": "context.press", "button": "web.reload"}), "action_failed")

    def test_unmappable_shortcut_reports_failure(self):
        self.tracker.app = app("chrome.exe")
        self.result = ValueError("no such key")
        self.assertEqual(self.provider.handle({"id": "context.press", "button": "web.reload"}), "action_failed")
        self.assertTrue(self.logs)

    def test_default_construction_sends_nothing(self):
        provider = ContextProvider()  # real tracker, real sender: only the read-only parts are used
        snap = provider.snapshot()
        self.assertIn("available", snap)


if __name__ == "__main__":
    unittest.main()
