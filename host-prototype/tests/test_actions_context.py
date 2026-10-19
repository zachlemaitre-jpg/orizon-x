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
            "Illustrator.exe": "illustrator", "Photoshop.exe": "photoshop",
            "Canva.exe": "canva", "Figma.exe": "figma",
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
        self.assertEqual(cp.display_name(app("explorer.exe", "CabinetWClass"), "fr"), "Explorateur")
        self.assertEqual(cp.display_name(app("explorer.exe", "CabinetWClass"), "en"), "Explorer")

    def test_names_that_do_not_vary_are_the_same_in_english(self):
        for exe, name in (("Spotify.exe", "Spotify"), ("POWERPNT.EXE", "PowerPoint"), ("WINWORD.EXE", "Word"),
                          ("EXCEL.EXE", "Excel"), ("Code.exe", "VS Code"), ("chrome.exe", "Chrome")):
            with self.subTest(exe):
                self.assertEqual(cp.display_name(app(exe), "en"), name)

    def test_unknown_language_is_french(self):
        self.assertEqual(cp.display_name(app("explorer.exe", "CabinetWClass"), "de"), "Explorateur")
        self.assertEqual(cp.display_name(None, "de"), "Application")

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
        self.assertEqual(cp.display_name(app("", title=""), "en"), "App")
        self.assertEqual(cp.display_name(None, "en"), "App")
        self.assertEqual(cp.DEFAULT_APP_NAME, {"en": "App", "fr": "Application"})


class TableTest(unittest.TestCase):
    def test_profile_ids(self):
        self.assertEqual([p.id for p in cp.PROFILES],
                         ["spotify", "powerpoint", "browser", "word", "excel", "vscode", "explorer",
                          "illustrator", "photoshop", "canva", "figma", "generic"])

    def test_each_page_has_one_to_eight_buttons_with_unique_ids(self):
        seen = set()
        for profile in cp.PROFILES:
            with self.subTest(profile.id):
                self.assertTrue(1 <= len(profile.pages) <= 4)
                self.assertEqual(len({p.id for p in profile.pages}), len(profile.pages))
                self.assertEqual(profile.buttons, tuple(b for p in profile.pages for b in p.buttons))
                self.assertEqual(len({b.id for b in profile.buttons}), len(profile.buttons))
                for page in profile.pages:
                    self.assertTrue(1 <= len(page.buttons) <= 8, page.id)
                for b in profile.buttons:
                    self.assertTrue(b.id and b.icon and b.labels["fr"] and b.shortcut)
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
            return [(b.icon, b.labels["fr"], b.shortcut) for b in cp.profile_by_id(pid).buttons]
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
        labels = {p.id: [b.labels["fr"] for b in p.buttons] for p in cp.PROFILES}
        self.assertEqual(labels["spotify"][:3], ["Précédent", "Lecture/Pause", "Suivant"])
        self.assertIn("Écran noir", labels["powerpoint"])
        self.assertIn("Nouvel onglet", labels["browser"])
        self.assertIn("Dossier parent", labels["explorer"])

    def test_every_button_has_english_and_french_labels(self):
        for profile in cp.PROFILES:
            for b in profile.buttons:
                with self.subTest(b.id):
                    self.assertEqual(set(b.labels), {"en", "fr"})
                    self.assertTrue(b.labels["en"].strip() and b.labels["fr"].strip())

    def test_labels_are_english(self):
        expected = {
            "spotify": ["Previous", "Play/Pause", "Next", "Like", "Shuffle", "Repeat"],
            "powerpoint": ["Slideshow", "From slide", "Previous", "Next", "Black screen", "Exit"],
            "browser": ["Back", "Forward", "Reload", "New tab", "Close tab", "Zoom −", "Zoom +"],
            "word": ["Undo", "Redo", "Bold", "Italic", "Underline", "Save"],
            "excel": ["Undo", "Redo", "Bold", "AutoSum", "Filter", "Save"],
            "vscode": ["Palette", "Search", "Terminal", "Comment", "Save", "Explorer"],
            "explorer": ["Back", "Up", "New folder", "Rename", "Refresh"],
            "generic": ["Copy", "Paste", "Undo", "Screenshot", "Desktop", "Switch app"],
        }
        for pid, labels in expected.items():
            with self.subTest(pid):
                self.assertEqual([b.labels["en"] for b in cp.profile_by_id(pid).buttons], labels)

    def test_french_labels_are_the_complete_original_table(self):
        expected = {
            "spotify": ["Précédent", "Lecture/Pause", "Suivant", "J'aime", "Aléatoire", "Répéter"],
            "powerpoint": ["Diaporama", "Depuis la diapo", "Précédent", "Suivant", "Écran noir", "Quitter"],
            "browser": ["Retour", "Avance", "Actualiser", "Nouvel onglet", "Fermer l'onglet", "Zoom −", "Zoom +"],
            "word": ["Annuler", "Rétablir", "Gras", "Italique", "Souligné", "Enregistrer"],
            "excel": ["Annuler", "Rétablir", "Gras", "Somme auto", "Filtre", "Enregistrer"],
            "vscode": ["Palette", "Rechercher", "Terminal", "Commenter", "Enregistrer", "Explorateur"],
            "explorer": ["Retour", "Dossier parent", "Nouveau dossier", "Renommer", "Actualiser"],
            "generic": ["Copier", "Coller", "Annuler", "Capture", "Bureau", "Changer d'app"],
        }
        for pid, labels in expected.items():
            with self.subTest(pid):
                self.assertEqual([b.labels["fr"] for b in cp.profile_by_id(pid).buttons], labels)

    def test_profile_by_id(self):
        self.assertEqual(cp.profile_by_id("word").id, "word")
        self.assertIsNone(cp.profile_by_id("nope"))


CREATIVE = {
    "illustrator": {
        "tools": [
            "Selection|Sélection|V|select", "Direct selection|Sélection directe|A|direct_select",
            "Pen|Plume|P|pen", "Type|Texte|T|text", "Rectangle|Rectangle|M|rectangle",
            "Ellipse|Ellipse|L|ellipse", "Brush|Pinceau|B|brush", "Eyedropper|Pipette|I|eyedropper"],
        "edit": [
            "Undo|Annuler|Ctrl+Z|undo", "Redo|Rétablir|Shift+Ctrl+Z|redo", "Group|Grouper|Ctrl+G|group",
            "Ungroup|Dissocier|Shift+Ctrl+G|ungroup", "Paste in front|Coller devant|Ctrl+F|paste_front",
            "Lock|Verrouiller|Ctrl+2|lock", "Unlock all|Tout déverrouiller|Ctrl+Alt+2|unlock",
            "Save|Enregistrer|Ctrl+S|save"],
        "view": [
            "Hand|Main|H|hand", "Zoom|Zoom|Z|search", "Fit|Ajuster|Ctrl+0|zoom_fit", "100 %|100 %|Ctrl+1|zoom_100",
            "Zoom −|Zoom −|Ctrl+-|zoom_out", "Zoom +|Zoom +|Ctrl+=|zoom_in", "Outline|Tracés|Ctrl+Y|outline",
            "Rulers|Règles|Ctrl+R|rulers"],
    },
    "photoshop": {
        "tools": [
            "Move|Déplacement|V|move", "Marquee|Rectangle de sélection|M|marquee", "Lasso|Lasso|L|lasso",
            "Brush|Pinceau|B|brush", "Eraser|Gomme|E|eraser", "Crop|Recadrage|C|crop", "Type|Texte|T|text",
            "Eyedropper|Pipette|I|eyedropper"],
        "edit": [
            "Undo|Annuler|Ctrl+Z|undo", "Redo|Rétablir|Shift+Ctrl+Z|redo", "Deselect|Désélectionner|Ctrl+D|deselect",
            "Transform|Transformer|Ctrl+T|transform", "New layer|Nouveau calque|Shift+Ctrl+N|layer_new",
            "Duplicate layer|Dupliquer le calque|Ctrl+J|layer_duplicate", "Merge down|Fusionner|Ctrl+E|merge",
            "Save|Enregistrer|Ctrl+S|save"],
        "view": [
            "Hand|Main|H|hand", "Zoom|Zoom|Z|search", "Fit|Ajuster|Ctrl+0|zoom_fit", "100 %|100 %|Ctrl+1|zoom_100",
            "Zoom −|Zoom −|Ctrl+-|zoom_out", "Zoom +|Zoom +|Ctrl+=|zoom_in",
            "Brush −|Pinceau −|OEM_4|brush_smaller", "Brush +|Pinceau +|OEM_6|brush_larger"],
    },
    "canva": {
        "tools": [
            "Text|Texte|T|text", "Rectangle|Rectangle|R|rectangle", "Circle|Cercle|C|ellipse", "Line|Ligne|L|line"],
        "edit": [
            "Undo|Annuler|Ctrl+Z|undo", "Redo|Rétablir|Ctrl+Y|redo", "Duplicate|Dupliquer|Ctrl+D|copy",
            "Group|Grouper|Ctrl+G|group", "Ungroup|Dissocier|Ctrl+Shift+G|ungroup",
            "Lock|Verrouiller|Alt+Shift+L|lock"],
        "view": [
            "Zoom −|Zoom −|Ctrl+-|zoom_out", "Zoom +|Zoom +|Ctrl+=|zoom_in", "Fit|Ajuster|Ctrl+Alt+0|zoom_fit",
            "Present|Présenter|Ctrl+Alt+P|present"],
    },
    "figma": {
        "tools": [
            "Move|Déplacer|V|move", "Frame|Cadre|F|frame", "Rectangle|Rectangle|R|rectangle",
            "Ellipse|Ellipse|O|ellipse", "Line|Ligne|L|line", "Pen|Plume|P|pen", "Text|Texte|T|text",
            "Comment|Commentaire|C|comment"],
        "edit": [
            "Undo|Annuler|Ctrl+Z|undo", "Redo|Rétablir|Ctrl+Shift+Z|redo", "Duplicate|Dupliquer|Ctrl+D|copy",
            "Group|Grouper|Ctrl+G|group", "Ungroup|Dissocier|Ctrl+Shift+G|ungroup",
            "Component|Composant|Ctrl+Alt+K|component", "Hide|Masquer|Ctrl+Shift+H|hide"],
        "view": [
            "Zoom −|Zoom −|-|zoom_out", "Zoom +|Zoom +|=|zoom_in", "Fit|Ajuster|Shift+1|zoom_fit",
            "Selection|Sélection|Shift+2|zoom_selection", "100 %|100 %|Shift+0|zoom_100",
            "Rulers|Règles|Shift+R|rulers", "Outline|Contours|Ctrl+Y|outline"],
    },
}
PAGE_LABELS = {"tools": ("Tools", "Outils"), "edit": ("Edit", "Édition"), "view": ("View", "Affichage")}
US_SCAN = lambda ch: {"-": 0xBD, "=": 0xBB, "/": 0xBF, "`": 0xC0}.get(ch, -1)  # noqa: E731


class CreativeProfilesTest(unittest.TestCase):
    def test_tables_follow_the_spec_verbatim(self):
        for pid, pages in CREATIVE.items():
            profile = cp.profile_by_id(pid)
            self.assertIsNotNone(profile, pid)
            self.assertEqual([p.id for p in profile.pages], list(pages), pid)
            for page in profile.pages:
                with self.subTest(pid + "/" + page.id):
                    self.assertEqual(page.labels, dict(zip(("en", "fr"), PAGE_LABELS[page.id])))
                    self.assertEqual(["|".join((b.labels["en"], b.labels["fr"], b.shortcut, b.icon))
                                      for b in page.buttons], pages[page.id])

    def test_every_creative_shortcut_parses_to_events(self):
        for pid in CREATIVE:
            for b in cp.profile_by_id(pid).buttons:
                with self.subTest(pid + "/" + b.id):
                    self.assertTrue(keys.parse_shortcut(b.shortcut, US_SCAN))

    def test_creative_button_ids_are_unique_in_the_profile_and_across_profiles(self):
        ids = [b.id for p in cp.PROFILES for b in p.buttons]
        self.assertEqual(len(ids), len(set(ids)))

    def test_new_icons_are_known(self):
        for name in ("select", "direct_select", "pen", "text", "rectangle", "ellipse", "line", "brush", "eraser",
                     "eyedropper", "crop", "lasso", "marquee", "move", "frame", "comment",
                     "group", "ungroup", "lock", "unlock", "layer_new", "layer_duplicate", "merge", "deselect",
                     "transform", "component", "hide", "paste_front",
                     "hand", "zoom_fit", "zoom_100", "zoom_selection", "outline", "rulers", "brush_smaller",
                     "brush_larger", "present"):
            self.assertIn(name, cp.ICON_NAMES)

    def test_layout_sensitive_shortcuts_become_the_right_keys(self):
        def vks(shortcut, scan=US_SCAN):
            return [vk for vk, flags in keys.parse_shortcut(shortcut, scan) if not flags & keys.KEYEVENTF_KEYUP]
        # [ and ] by position, as VS Code's OEM_3 / OEM_2
        self.assertEqual(vks("OEM_4"), [0xDB])
        self.assertEqual(vks("OEM_6"), [0xDD])
        # Shift+digit: the digit-row virtual keys, never the layout (a scan that fails proves it is not asked)
        never = lambda ch: self.fail("the layout must not be consulted")  # noqa: E731
        self.assertEqual(vks("Shift+0", never), [keys.VK_SHIFT, 0x30])
        self.assertEqual(vks("Shift+1", never), [keys.VK_SHIFT, 0x31])
        self.assertEqual(vks("Shift+2", never), [keys.VK_SHIFT, 0x32])
        # Figma's plain - and = go through VkKeyScanW
        self.assertEqual(vks("-"), [0xBD])
        self.assertEqual(vks("="), [0xBB])
        self.assertEqual(vks("-", lambda ch: 0x36), [0x36])  # an AZERTY-like layout answer is honoured

    def test_creative_shortcuts_with_a_fake_send_input(self):
        sent = []

        def fake_send(count, events, size):
            sent.append([(e.u.ki.wVk, e.u.ki.dwFlags) for e in events])
            return count
        for pid in CREATIVE:
            for b in cp.profile_by_id(pid).buttons:
                with self.subTest(pid + "/" + b.id):
                    sent.clear()
                    self.assertTrue(keys.send_shortcut(b.shortcut, fake_send, US_SCAN))
                    self.assertEqual(len(sent), 1)  # one SendInput call
                    self.assertTrue(sent[0])


class CreativeDetectionTest(unittest.TestCase):
    def test_exe_in_mixed_case(self):
        for exe, pid in (("ILLUSTRATOR.EXE", "illustrator"), ("Illustrator.exe", "illustrator"),
                         ("photoshop.exe", "photoshop"), ("PhotoShop.Exe", "photoshop"),
                         ("canva.EXE", "canva"), ("CANVA.exe", "canva"), ("Figma.exe", "figma"),
                         ("FIGMA.EXE", "figma")):
            with self.subTest(exe):
                self.assertEqual(cp.match(app(exe)).id, pid)

    def test_canva_in_a_chrome_title(self):
        a = app("chrome.exe", "Chrome_WidgetWin_1", "Logo – Canva - Google Chrome")
        self.assertEqual(cp.match(a).id, "canva")

    def test_figma_in_an_edge_title(self):
        a = app("msedge.exe", "Chrome_WidgetWin_1", "Design system – Figma - Microsoft Edge")
        self.assertEqual(cp.match(a).id, "figma")

    def test_title_match_ignores_case_and_covers_every_browser(self):
        for exe in ("chrome.exe", "MSEDGE.EXE", "firefox.exe", "brave.exe", "opera.exe"):
            with self.subTest(exe):
                self.assertEqual(cp.match(app(exe, title="my CANVA design")).id, "canva")
                self.assertEqual(cp.match(app(exe, title="board - fIgMa")).id, "figma")

    def test_plain_browser_title_is_the_browser(self):
        for title in ("Google - Google Chrome", "", "Wikipedia - Microsoft Edge"):
            with self.subTest(title):
                self.assertEqual(cp.match(app("chrome.exe", title=title)).id, "browser")

    def test_canva_in_a_non_browser_title_is_ignored(self):
        self.assertEqual(cp.match(app("notepad.exe", title="Canva notes - Notepad")).id, "generic")
        self.assertEqual(cp.match(app("Code.exe", title="figma.ts - Code")).id, "vscode")
        self.assertEqual(cp.match(app("Slack.exe", title="Figma")).id, "generic")

    def test_display_names_are_the_same_in_both_languages(self):
        cases = (("Illustrator.exe", "Illustrator"), ("Photoshop.exe", "Photoshop"), ("Canva.exe", "Canva"),
                 ("Figma.exe", "Figma"))
        for exe, name in cases:
            for lang in ("en", "fr"):
                with self.subTest(exe, lang=lang):
                    self.assertEqual(cp.display_name(app(exe), lang), name)
        self.assertEqual(cp.display_name(app("chrome.exe", title="Logo – Canva - Google Chrome"), "en"), "Canva")
        self.assertEqual(cp.display_name(app("msedge.exe", title="x – Figma - Microsoft Edge"), "fr"), "Figma")
        self.assertEqual(cp.display_name(app("chrome.exe", title="Google - Google Chrome"), "en"), "Chrome")


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
        self.assertEqual(set(snap), {"available", "app", "profile", "buttons", "pages"})
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
                "illustrator": ("Illustrator.exe", "Cls"), "photoshop": ("Photoshop.exe", "Cls"),
                "canva": ("Canva.exe", "Cls"), "figma": ("Figma.exe", "Cls"),
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

    def test_default_language_is_french(self):
        self.assertEqual(self.provider.lang, "fr")

    def test_english_snapshot(self):
        provider = ContextProvider(lang="en", tracker=self.tracker, send_shortcut=self._send, log=self.logs.append)
        self.tracker.app = app("POWERPNT.EXE")
        snap = provider.snapshot()
        self.assertEqual(snap["buttons"][0], {"id": "ppt.slideshow", "icon": "slideshow", "label": "Slideshow"})
        self.tracker.app = app("explorer.exe", "CabinetWClass")
        self.assertEqual(provider.snapshot()["app"], "Explorer")
        self.tracker.app = app("", title="")
        self.assertEqual(provider.snapshot()["app"], "App")

    def test_unknown_constructor_language_is_french(self):
        self.assertEqual(ContextProvider(lang="de", tracker=self.tracker).lang, "fr")

    def test_context_lang_switches_the_snapshot_language(self):
        self.tracker.app = app("POWERPNT.EXE")
        self.assertEqual(self.provider.snapshot()["buttons"][0]["label"], "Diaporama")
        self.assertIsNone(self.provider.handle({"id": "context.lang", "lang": "en"}))
        self.assertEqual(self.provider.snapshot()["buttons"][0]["label"], "Slideshow")
        self.assertIsNone(self.provider.handle({"id": "context.lang", "lang": "fr"}))
        self.assertEqual(self.provider.snapshot()["buttons"][0]["label"], "Diaporama")
        self.assertEqual(self.sent, [])  # nothing is typed

    def test_context_lang_ignores_unknown_values_and_logs_them(self):
        self.tracker.app = app("POWERPNT.EXE")
        self.provider.handle({"id": "context.lang", "lang": "en"})
        for action in ({"id": "context.lang", "lang": "de"}, {"id": "context.lang"},
                       {"id": "context.lang", "lang": 3}, {"id": "context.lang", "lang": None}):
            with self.subTest(action=action):
                self.logs.clear()
                self.assertIsNone(self.provider.handle(action))
                self.assertEqual(self.provider.lang, "en")
                self.assertEqual(len(self.logs), 1)
        self.assertEqual(self.provider.snapshot()["buttons"][0]["label"], "Slideshow")

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

    def test_snapshot_pages_and_buttons_equal_page_one(self):
        for lang in ("fr", "en"):
            provider = ContextProvider(lang=lang, tracker=self.tracker, send_shortcut=self._send, log=self.logs.append)
            for exe in ("Illustrator.exe", "Photoshop.exe", "Canva.exe", "Figma.exe", "POWERPNT.EXE", "notepad.exe"):
                with self.subTest(lang=lang, exe=exe):
                    self.tracker.app = app(exe)
                    snap = provider.snapshot()
                    profile = cp.match(self.tracker.app)
                    self.assertEqual([p["id"] for p in snap["pages"]], [p.id for p in profile.pages])
                    self.assertEqual(snap["buttons"], snap["pages"][0]["buttons"])
                    for page, spec in zip(snap["pages"], profile.pages):
                        self.assertEqual(set(page), {"id", "label", "buttons"})
                        self.assertEqual(page["label"], spec.label(lang))
                        self.assertEqual(page["buttons"], [{"id": b.id, "icon": b.icon, "label": b.label(lang)}
                                                           for b in spec.buttons])
                    json.dumps(snap)

    def test_snapshot_page_labels_follow_the_language(self):
        self.tracker.app = app("Illustrator.exe")
        fr = self.provider.snapshot()
        self.assertEqual([p["label"] for p in fr["pages"]], ["Outils", "Édition", "Affichage"])
        self.provider.handle({"id": "context.lang", "lang": "en"})
        en = self.provider.snapshot()
        self.assertEqual([p["label"] for p in en["pages"]], ["Tools", "Edit", "View"])
        self.assertEqual(en["buttons"][0]["label"], "Selection")
        self.assertEqual(fr["buttons"][0]["label"], "Sélection")

    def test_existing_profiles_have_one_main_page_equal_to_their_buttons(self):
        for pid in ("spotify", "powerpoint", "browser", "word", "excel", "vscode", "explorer", "generic"):
            with self.subTest(pid):
                profile = cp.profile_by_id(pid)
                self.assertEqual([p.id for p in profile.pages], ["main"])
                self.assertEqual(profile.pages[0].buttons, profile.buttons)
                self.assertEqual(profile.pages[0].labels, {"en": "Main", "fr": "Principal"})
        self.tracker.app = app("POWERPNT.EXE")
        snap = self.provider.snapshot()
        self.assertEqual(len(snap["pages"]), 1)
        self.assertEqual(snap["pages"][0]["buttons"], snap["buttons"])

    def test_press_accepts_a_button_of_a_later_page(self):
        self.tracker.app = app("Illustrator.exe")
        self.assertIsNone(self.provider.handle({"id": "context.press", "button": "ai.rulers"}))
        self.assertEqual(self.sent, ["Ctrl+R"])
        self.sent.clear()
        self.tracker.app = app("Figma.exe")
        self.assertIsNone(self.provider.handle({"id": "context.press", "button": "figma.zoom_100"}))
        self.assertEqual(self.sent, ["Shift+0"])

    def test_press_rejects_a_button_of_another_profile(self):
        self.tracker.app = app("Photoshop.exe")
        self.assertIsNone(self.provider.handle({"id": "context.press", "button": "ai.rulers"}))
        self.assertEqual(self.sent, [])
        self.assertEqual(len(self.logs), 1)
        self.tracker.app = app("Illustrator.exe")
        self.assertIsNone(self.provider.handle({"id": "context.press", "button": "ppt.next"}))
        self.assertEqual(self.sent, [])

    def test_default_construction_sends_nothing(self):
        provider = ContextProvider()  # real tracker, real sender: only the read-only parts are used
        snap = provider.snapshot()
        self.assertIn("available", snap)


if __name__ == "__main__":
    unittest.main()
