import json
import unittest

from actions import browser_tabs
from actions import context_profiles as cp
from actions.browser_tabs import BrowserTabsReader, Tab, short_tab_title
from actions.context import ContextProvider
from actions.foreground import ForegroundApp


class FakeUia:
    """The UI Automation layer: `raw` is the list of (name, selected, handle) the window's TabItems give."""

    def __init__(self, raw=None):
        self.raw = list(raw or [])
        self.listed = []
        self.selected = []
        self.error = None
        self.select_error = None

    def list_tabs(self, hwnd):
        self.listed.append(hwnd)
        if self.error:
            raise self.error
        return list(self.raw)

    def select_tab(self, handle):
        self.selected.append(handle)
        if self.select_error:
            raise self.select_error


class Clock:
    def __init__(self):
        self.t = 100.0

    def __call__(self):
        return self.t


def raw(*names, active=0):
    return [(name, i == active, f"h{i}") for i, name in enumerate(names)]


class ShortTitleTest(unittest.TestCase):
    def test_memory_suffix_is_removed_in_both_languages(self):
        self.assertEqual(short_tab_title("Accueil - Canva - Utilisation de la mémoire - 498 Mo"), "Accueil - Canva")
        self.assertEqual(short_tab_title("Inbox - Memory usage - 1.2 GB"), "Inbox")
        self.assertEqual(short_tab_title("Page - Memory usage - 12 MB"), "Page")

    def test_plain_titles_are_untouched_and_spaces_stripped(self):
        self.assertEqual(short_tab_title("  Google  "), "Google")
        self.assertEqual(short_tab_title("Memory usage report"), "Memory usage report")

    def test_cut_to_forty_characters_with_an_ellipsis(self):
        out = short_tab_title("x" * 100)
        self.assertEqual(len(out), 40)
        self.assertTrue(out.endswith("…"))
        self.assertEqual(short_tab_title("y" * 40), "y" * 40)
        self.assertEqual(len(short_tab_title("z" * 41)), 40)

    def test_not_a_string_is_empty(self):
        self.assertEqual(short_tab_title(None), "")


class ReaderTest(unittest.TestCase):
    def setUp(self):
        self.uia = FakeUia(raw("A", "B - Memory usage - 10 MB", "C", active=1))
        self.clock = Clock()
        self.logs = []
        self.sent = []
        self.reader = BrowserTabsReader(self.uia, self.logs.append, self.clock, self.send)

    def send(self, shortcut):
        self.sent.append(shortcut)
        return True

    def test_order_titles_and_active_tab(self):
        self.assertEqual(self.reader.tabs(7, "w"), [Tab(0, "A", False), Tab(1, "B", True), Tab(2, "C", False)])

    def test_at_most_24_tabs(self):
        self.uia.raw = raw(*[f"t{i}" for i in range(40)])
        tabs = self.reader.tabs(7, "w")
        self.assertEqual(len(tabs), 24)
        self.assertEqual(tabs[-1].index, 23)

    def test_cached_while_window_and_title_are_unchanged(self):
        for _ in range(7):
            self.reader.tabs(7, "w")
            self.clock.t += 0.25
        self.assertEqual(len(self.uia.listed), 1)

    def test_read_again_after_two_seconds(self):
        self.reader.tabs(7, "w")
        self.clock.t += 1.9
        self.reader.tabs(7, "w")
        self.assertEqual(len(self.uia.listed), 1)
        self.clock.t += 0.2
        self.uia.raw = raw("A", "B", "C", "D")
        self.assertEqual(len(self.reader.tabs(7, "w")), 4)
        self.assertEqual(len(self.uia.listed), 2)

    def test_read_again_when_the_title_or_the_window_changes(self):
        self.reader.tabs(7, "w")
        self.reader.tabs(7, "other title")
        self.reader.tabs(8, "w")
        self.assertEqual(self.uia.listed, [7, 7, 8])

    def test_an_error_gives_an_empty_list_logged_once_per_kind(self):
        self.uia.error = OSError("COM")
        for i in range(3):
            self.assertEqual(self.reader.tabs(7, f"t{i}"), [])
        self.assertEqual(len(self.logs), 1)
        self.uia.error = RuntimeError("other")
        self.assertEqual(self.reader.tabs(7, "again"), [])
        self.assertEqual(len(self.logs), 2)

    def test_no_window_is_empty_without_a_call(self):
        self.assertEqual(self.reader.tabs(0, "w"), [])
        self.assertEqual(self.uia.listed, [])

    def test_a_window_without_tabs_is_empty(self):
        self.uia.raw = []
        self.assertEqual(self.reader.tabs(7, "w"), [])

    def test_no_active_tab_is_all_false_and_blank_names_are_numbered(self):
        self.uia.raw = [("", False, "h0"), ("B", False, "h1")]
        self.assertEqual(self.reader.tabs(7, "w"), [Tab(0, "1", False), Tab(1, "B", False)])

    def test_malformed_entries_are_dropped(self):
        self.uia.raw = [("A", True, "h0"), None, ("B",), (5, True, "h2"), ("C", False, "h3")]
        self.assertEqual([t.title for t in self.reader.tabs(7, "w")], ["A", "C"])


class SelectTest(unittest.TestCase):
    def setUp(self):
        self.uia = FakeUia(raw("A", "B", "C", "B", active=0))
        self.clock = Clock()
        self.logs = []
        self.sent = []
        self.reader = BrowserTabsReader(self.uia, self.logs.append, self.clock, self.send)

    def send(self, shortcut):
        self.sent.append(shortcut)
        return True

    def test_selects_the_tab_of_that_rank_when_its_title_matches(self):
        self.assertTrue(self.reader.select(7, 3, "B"))
        self.assertEqual(self.uia.selected, ["h3"])  # rank 3, not the first "B"
        self.assertEqual(self.sent, [])

    def test_finds_the_title_at_another_rank(self):
        self.uia.raw = raw("X", "A", "C", "B")  # the tab strip changed since the bar was drawn
        self.assertTrue(self.reader.select(7, 0, "B"))
        self.assertEqual(self.uia.selected, ["h3"])

    def test_first_tab_of_that_title_when_the_rank_no_longer_matches(self):
        self.uia.raw = raw("B", "A", "B", "C")
        self.assertTrue(self.reader.select(7, 3, "B"))
        self.assertEqual(self.uia.selected, ["h0"])

    def test_no_match_does_nothing(self):
        self.assertFalse(self.reader.select(7, 1, "Closed tab"))
        self.assertEqual(self.uia.selected, [])
        self.assertEqual(self.sent, [])

    def test_failed_select_falls_back_to_ctrl_number(self):
        self.uia.select_error = OSError("pattern gone")
        self.assertTrue(self.reader.select(7, 2, "C"))
        self.assertEqual(self.sent, ["Ctrl+3"])
        self.assertEqual(len(self.logs), 1)

    def test_fallback_only_for_the_first_eight_tabs(self):
        self.uia.raw = raw(*[f"t{i}" for i in range(12)])
        self.uia.select_error = OSError("pattern gone")
        self.assertTrue(self.reader.select(7, 7, "t7"))
        self.assertEqual(self.sent, ["Ctrl+8"])
        self.sent.clear()
        self.assertFalse(self.reader.select(7, 8, "t8"))
        self.assertEqual(self.sent, [])

    def test_the_fallback_uses_the_rank_the_title_was_found_at(self):
        self.uia.raw = raw("X", "Y", "B")
        self.uia.select_error = OSError("x")
        self.assertTrue(self.reader.select(7, 0, "B"))
        self.assertEqual(self.sent, ["Ctrl+3"])

    def test_fallback_result_follows_the_shortcut(self):
        self.uia.select_error = OSError("x")
        self.reader = BrowserTabsReader(self.uia, self.logs.append, self.clock, lambda s: False)
        self.assertFalse(self.reader.select(7, 0, "A"))
        self.reader = BrowserTabsReader(self.uia, self.logs.append, self.clock,
                                        lambda s: (_ for _ in ()).throw(ValueError("no key")))
        self.assertFalse(self.reader.select(7, 0, "A"))

    def test_the_cache_is_invalidated_after_a_switch(self):
        self.reader.tabs(7, "w")
        self.reader.select(7, 0, "A")
        self.uia.raw = raw("A", "B", "C", "B", active=2)
        tabs = self.reader.tabs(7, "w")  # same window, same title, within 2 s: read again anyway
        self.assertTrue(tabs[2].active)

    def test_read_error_during_select_is_false(self):
        self.uia.error = OSError("COM")
        self.assertFalse(self.reader.select(7, 0, "A"))
        self.assertEqual(self.uia.selected, [])

    def test_no_window_is_false(self):
        self.assertFalse(self.reader.select(0, 0, "A"))

    def test_module_does_not_import_comtypes(self):
        self.assertFalse(hasattr(browser_tabs, "comtypes"))


# --- context bar -----------------------------------------------------------------------------------------------

class FakeTabsReader:
    def __init__(self, tabs=None):
        self.value = list(tabs or [])
        self.calls = []
        self.selects = []
        self.select_result = True

    def tabs(self, hwnd, title=""):
        self.calls.append((hwnd, title))
        return list(self.value)

    def select(self, hwnd, index, title):
        self.selects.append((hwnd, index, title))
        return self.select_result


class FakeUrlReader:
    def __init__(self, url=None):
        self.value = url

    def url(self, hwnd, title=""):
        return self.value


class NoIcons:
    def icon_id(self, app, profile, url):
        return None

    def artwork_bytes(self, icon_id):
        return None


def app(exe, title="Window", hwnd=42, window_class="Cls"):
    return ForegroundApp(exe, window_class, title, 1, hwnd)


TABS = [Tab(0, "Accueil - Canva", True), Tab(1, "Wikipedia", False), Tab(2, "Mail", False)]


class Tracker:
    def __init__(self, current=None):
        self.app = current

    def current(self):
        return self.app


class TabsPageTest(unittest.TestCase):
    def setUp(self):
        self.tracker = Tracker()
        self.reader = FakeTabsReader(TABS)
        self.urls = FakeUrlReader()
        self.sent = []
        self.logs = []
        self.provider = self.make("fr")

    def make(self, lang):
        return ContextProvider(tracker=self.tracker, send_shortcut=lambda s: self.sent.append(s) or True,
                               log=self.logs.append, lang=lang, url_reader=self.urls, icons=NoIcons(),
                               tabs_reader=self.reader)

    def test_browser_gets_the_tabs_page_first_then_main(self):
        self.tracker.app = app("chrome.exe", "Wikipedia - Google Chrome", hwnd=9)
        snap = self.provider.snapshot()
        self.assertEqual(snap["profile"], "browser")
        self.assertEqual([p["id"] for p in snap["pages"]], ["tabs", "main"])
        tabs = snap["pages"][0]
        self.assertEqual(tabs["label"], "Onglets")
        self.assertIs(tabs["scroll"], True)
        self.assertEqual(tabs["buttons"], [
            {"id": "tab.0", "icon": "tab", "label": "Accueil - Canva", "active": True},
            {"id": "tab.1", "icon": "tab", "label": "Wikipedia", "active": False},
            {"id": "tab.2", "icon": "tab", "label": "Mail", "active": False}])
        self.assertNotIn("scroll", snap["pages"][1])
        self.assertEqual(self.reader.calls, [(9, "Wikipedia - Google Chrome")])
        json.dumps(snap)

    def test_english_label(self):
        self.tracker.app = app("chrome.exe")
        snap = self.make("en").snapshot()
        self.assertEqual(snap["pages"][0]["label"], "Tabs")

    def test_buttons_stays_the_first_static_page_for_old_devices(self):
        self.tracker.app = app("chrome.exe")
        snap = self.provider.snapshot()
        self.assertEqual(snap["buttons"], snap["pages"][1]["buttons"])
        self.assertEqual(snap["buttons"][0]["id"], "web.back")
        self.assertTrue(len(snap["buttons"]) <= 8)

    def test_a_site_profile_in_a_browser_gets_the_tabs_page_last(self):
        self.tracker.app = app("chrome.exe", "hdi - Présentation - Google Chrome")
        self.urls.value = "canva.com/design/x/edit"
        snap = self.provider.snapshot()
        self.assertEqual(snap["profile"], "canva")
        self.assertEqual([p["id"] for p in snap["pages"]], ["tools", "edit", "view", "tabs"])
        self.assertEqual(snap["buttons"], snap["pages"][0]["buttons"])
        self.assertEqual(len(snap["pages"][3]["buttons"]), 3)

    def test_figma_in_a_browser_too(self):
        self.tracker.app = app("msedge.exe", "Board")
        self.urls.value = "www.figma.com/design/abc"
        snap = self.provider.snapshot()
        self.assertEqual((snap["profile"], snap["pages"][-1]["id"]), ("figma", "tabs"))

    def test_no_tabs_read_no_page(self):
        self.reader.value = []
        for exe, url in (("chrome.exe", None), ("chrome.exe", "canva.com/x")):
            self.tracker.app = app(exe)
            self.urls.value = url
            snap = self.provider.snapshot()
            self.assertNotIn("tabs", [p["id"] for p in snap["pages"]])
        self.tracker.app = app("chrome.exe")
        self.urls.value = None
        self.assertEqual([p["id"] for p in self.provider.snapshot()["pages"]], ["main"])

    def test_a_native_app_never_gets_the_tabs_page_or_a_read(self):
        for exe in ("Canva.exe", "Figma.exe", "Illustrator.exe", "notepad.exe", "Spotify.exe", "Code.exe"):
            self.tracker.app = app(exe)
            snap = self.provider.snapshot()
            self.assertNotIn("tabs", [p["id"] for p in snap["pages"]], exe)
        self.assertEqual(self.reader.calls, [])

    def test_no_window_handle_means_no_read(self):
        self.tracker.app = app("chrome.exe", hwnd=0)
        self.assertEqual([p["id"] for p in self.provider.snapshot()["pages"]], ["main"])
        self.assertEqual(self.reader.calls, [])

    def test_static_pages_carry_no_scroll_or_active(self):
        self.tracker.app = app("Illustrator.exe")
        snap = self.provider.snapshot()
        for page in snap["pages"]:
            self.assertNotIn("scroll", page)
            for b in page["buttons"]:
                self.assertEqual(set(b), {"id", "icon", "label"})

    def test_tab_icon_is_known(self):
        self.assertIn("tab", cp.ICON_NAMES)


class PressTabTest(unittest.TestCase):
    def setUp(self):
        self.tracker = Tracker(app("chrome.exe", "Wikipedia - Google Chrome", hwnd=9))
        self.reader = FakeTabsReader(TABS)
        self.sent = []
        self.logs = []
        self.provider = ContextProvider(tracker=self.tracker, send_shortcut=lambda s: self.sent.append(s) or True,
                                        log=self.logs.append, url_reader=FakeUrlReader(), icons=NoIcons(),
                                        tabs_reader=self.reader)

    def press(self, button):
        return self.provider.handle({"id": "context.press", "button": button})

    def test_a_tab_of_the_last_list_sent_is_selected_with_the_title_sent(self):
        self.provider.snapshot()
        self.assertIsNone(self.press("tab.1"))
        self.assertEqual(self.reader.selects, [(9, 1, "Wikipedia")])
        self.assertEqual(self.sent, [])  # no key sent by the provider itself

    def test_works_on_a_site_profile_in_a_browser(self):
        self.provider._url_reader.value = "canva.com/design/x"
        self.provider.snapshot()
        self.assertIsNone(self.press("tab.2"))
        self.assertEqual(self.reader.selects, [(9, 2, "Mail")])

    def test_an_unknown_rank_is_refused_and_logged(self):
        self.provider.snapshot()
        for button in ("tab.3", "tab.99", "tab.-1", "tab.x", "tab.", "tab"):
            with self.subTest(button):
                self.logs.clear()
                self.assertIsNone(self.press(button))
                self.assertEqual(len(self.logs), 1)
        self.assertEqual(self.reader.selects, [])

    def test_nothing_was_sent_yet_refuses(self):
        self.assertIsNone(self.press("tab.0"))
        self.assertEqual(self.reader.selects, [])

    def test_rank_is_checked_against_the_list_sent_not_the_current_one(self):
        self.provider.snapshot()
        self.reader.value = TABS[:1]  # a tab closed since: the device still shows three
        self.assertIsNone(self.press("tab.2"))
        self.assertEqual(self.reader.selects, [(9, 2, "Mail")])  # the reader decides (title not found there)

    def test_not_in_front_of_a_browser_refuses(self):
        self.provider.snapshot()
        self.tracker.app = app("notepad.exe")
        self.assertIsNone(self.press("tab.0"))
        self.tracker.app = app("Canva.exe")
        self.assertIsNone(self.press("tab.0"))
        self.assertEqual(self.reader.selects, [])

    def test_another_browser_window_refuses(self):
        self.provider.snapshot()
        self.tracker.app = app("chrome.exe", "Other - Google Chrome", hwnd=10)
        self.assertIsNone(self.press("tab.0"))
        self.assertEqual(self.reader.selects, [])

    def test_a_failed_switch_is_logged_and_gives_no_notice(self):
        self.provider.snapshot()
        self.reader.select_result = False
        self.logs.clear()
        self.assertIsNone(self.press("tab.1"))
        self.assertEqual(len(self.logs), 1)

    def test_static_buttons_still_work_next_to_the_tabs_page(self):
        self.provider.snapshot()
        self.assertIsNone(self.press("web.reload"))
        self.assertEqual(self.sent, ["F5"])


if __name__ == "__main__":
    unittest.main()
