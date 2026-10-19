import sys
import unittest

from actions import browser_url
from actions import context_profiles as cp
from actions.browser_url import BrowserUrlReader, host_matches, host_of
from actions.context import ContextProvider
from actions.foreground import ForegroundApp


class HostOfTest(unittest.TestCase):
    def test_hosts(self):
        cases = {
            "canva.com/design/DAHXJqQrXIo/abc/edit": "canva.com",   # Chrome omits the scheme
            "https://www.canva.com/design/x/edit?utm=1#frag": "canva.com",
            "HTTP://Canva.COM": "canva.com",
            "www.figma.com/file/1": "figma.com",
            "https://design.figma.com:8443/x": "design.figma.com",
            "https://user:pw@canva.com/x": "canva.com",
            "  canva.com  ": "canva.com",
            "example.org/canva.com": "example.org",
            "canva.com?x=1": "canva.com",
            "localhost:3000/x": "localhost",
        }
        for url, host in cases.items():
            with self.subTest(url):
                self.assertEqual(host_of(url), host)

    def test_not_an_address(self):
        for url in (None, "", "   ", "canva design ideas", 5, "/path/only"):
            with self.subTest(url):
                self.assertIsNone(host_of(url))

    def test_host_matches_the_domain_and_its_subdomains_only(self):
        self.assertTrue(host_matches("canva.com", "canva.com"))
        self.assertTrue(host_matches("www2.canva.com", "canva.com"))
        self.assertFalse(host_matches("notcanva.com", "canva.com"))
        self.assertFalse(host_matches("canva.com.evil.org", "canva.com"))
        self.assertFalse(host_matches("canva.fr", "canva.com"))
        self.assertFalse(host_matches(None, "canva.com"))


class FakeUia:
    def __init__(self, value="canva.com/design/x/edit"):
        self.value = value
        self.calls = []

    def address_bar_value(self, hwnd):
        self.calls.append(hwnd)
        if isinstance(self.value, Exception):
            raise self.value
        return self.value


class Clock:
    def __init__(self):
        self.now = 100.0

    def __call__(self):
        return self.now


class ReaderTest(unittest.TestCase):
    def setUp(self):
        self.uia = FakeUia()
        self.clock = Clock()
        self.logs = []
        self.reader = BrowserUrlReader(self.uia, self.logs.append, self.clock)

    def test_returns_the_address_bar_value(self):
        self.assertEqual(self.reader.url(7, "t"), "canva.com/design/x/edit")
        self.assertEqual(self.uia.calls, [7])

    def test_no_uia_call_while_window_and_title_are_unchanged(self):
        for _ in range(20):
            self.assertEqual(self.reader.url(7, "t"), "canva.com/design/x/edit")
            self.clock.now += 0.25
        self.assertEqual(len(self.uia.calls), 1)  # 5 s of polling at 250 ms stays under the recheck delay

    def test_new_call_when_the_title_changes(self):
        self.reader.url(7, "tab one")
        self.uia.value = "figma.com/file/1"
        self.assertEqual(self.reader.url(7, "tab two"), "figma.com/file/1")
        self.assertEqual(len(self.uia.calls), 2)
        self.assertEqual(self.reader.url(7, "tab two"), "figma.com/file/1")
        self.assertEqual(len(self.uia.calls), 2)

    def test_new_call_when_the_window_changes(self):
        self.reader.url(7, "t")
        self.reader.url(8, "t")
        self.assertEqual(self.uia.calls, [7, 8])

    def test_going_back_to_a_window_uses_its_cached_answer(self):
        self.reader.url(7, "a")
        self.reader.url(8, "b")
        self.reader.url(7, "a")
        self.assertEqual(self.uia.calls, [7, 8])

    def test_answer_is_rechecked_after_the_delay_even_with_the_same_title(self):
        self.reader.url(7, "t")
        self.uia.value = "figma.com/x"
        self.clock.now += browser_url.RECHECK_S + 0.1
        self.assertEqual(self.reader.url(7, "t"), "figma.com/x")
        self.assertEqual(len(self.uia.calls), 2)

    def test_errors_give_none_and_never_raise(self):
        for error in (OSError("COM"), RuntimeError("boom"), ImportError("no comtypes"), ValueError("x")):
            with self.subTest(error):
                reader = BrowserUrlReader(FakeUia(error), self.logs.append, self.clock)
                self.assertIsNone(reader.url(7, "t"))

    def test_an_error_is_logged_once_per_kind(self):
        self.uia.value = OSError("COM")
        for i in range(3):
            self.assertIsNone(self.reader.url(7, f"title {i}"))
        self.assertEqual(len(self.logs), 1)
        self.uia.value = RuntimeError("other")
        self.assertIsNone(self.reader.url(7, "another"))
        self.assertEqual(len(self.logs), 2)

    def test_a_failure_is_retried_after_the_delay(self):
        self.uia.value = OSError("COM")
        self.assertIsNone(self.reader.url(7, "t"))
        self.uia.value = "canva.com/x"
        self.assertIsNone(self.reader.url(7, "t"))  # cached
        self.clock.now += browser_url.RECHECK_S + 0.1
        self.assertEqual(self.reader.url(7, "t"), "canva.com/x")

    def test_missing_or_blank_address_bar_is_none(self):
        for value in (None, "", "   ", 3):
            with self.subTest(value):
                reader = BrowserUrlReader(FakeUia(value), self.logs.append, self.clock)
                self.assertIsNone(reader.url(7, "t"))

    def test_no_window_is_none_without_a_call(self):
        self.assertIsNone(self.reader.url(0, "t"))
        self.assertEqual(self.uia.calls, [])

    def test_cache_stays_bounded(self):
        for i in range(100):
            self.reader.url(i + 1, "t")
        self.assertLessEqual(len(self.reader._cache), 16)

    def test_comtypes_is_not_imported_by_these_modules(self):
        self.assertFalse(hasattr(browser_url, "comtypes"))
        BrowserUrlReader(FakeUia())  # constructing it needs no UI Automation


class FakeReader:
    def __init__(self, url=None):
        self.value = url
        self.calls = []

    def url(self, hwnd, title=""):
        self.calls.append((hwnd, title))
        return self.value


def app(exe, title="Window", hwnd=42, window_class="Cls"):
    return ForegroundApp(exe, window_class, title, 1, hwnd)


class MatchWithUrlTest(unittest.TestCase):
    def test_url_picks_canva_and_figma_in_every_browser(self):
        for exe in ("chrome.exe", "MSEDGE.EXE", "firefox.exe", "brave.exe", "opera.exe"):
            with self.subTest(exe):
                self.assertEqual(cp.match(app(exe, "hdi - Présentation - Google Chrome"),
                                          "canva.com/design/DAH/edit").id, "canva")
                self.assertEqual(cp.match(app(exe, "Board"), "https://www.figma.com/design/abc").id, "figma")

    def test_subdomains_count_and_lookalikes_do_not(self):
        a = app("chrome.exe", "Plain - Google Chrome")
        self.assertEqual(cp.match(a, "www.canva.com/x").id, "canva")
        self.assertEqual(cp.match(a, "design.figma.com/x").id, "figma")
        self.assertEqual(cp.match(a, "notcanva.com/x").id, "browser")
        self.assertEqual(cp.match(a, "example.org/figma.com").id, "browser")

    def test_precedence_url_then_title_then_browser(self):
        self.assertEqual(cp.match(app("chrome.exe", "figma stuff - Google Chrome"), "canva.com/x").id, "canva")
        self.assertEqual(cp.match(app("chrome.exe", "Logo - Canva - Google Chrome"), "figma.com/x").id, "figma")
        self.assertEqual(cp.match(app("chrome.exe", "Logo - Canva - Google Chrome"), "example.org").id, "canva")
        self.assertEqual(cp.match(app("chrome.exe", "Logo - Canva - Google Chrome"), None).id, "canva")
        self.assertEqual(cp.match(app("chrome.exe", "Plain - Google Chrome"), "example.org").id, "browser")
        self.assertEqual(cp.match(app("chrome.exe", "Plain - Google Chrome"), None).id, "browser")
        self.assertEqual(cp.match(app("chrome.exe", "Plain - Google Chrome")).id, "browser")

    def test_url_is_ignored_outside_browsers(self):
        self.assertEqual(cp.match(app("notepad.exe"), "canva.com/x").id, "generic")
        self.assertEqual(cp.match(app("Code.exe"), "figma.com/x").id, "vscode")
        self.assertEqual(cp.match(app("Canva.exe"), "figma.com/x").id, "canva")

    def test_is_browser(self):
        self.assertTrue(cp.is_browser(app("Chrome.EXE")))
        self.assertFalse(cp.is_browser(app("notepad.exe")))
        self.assertFalse(cp.is_browser(None))

    def test_display_name_follows_the_url(self):
        a = app("chrome.exe", "hdi - Présentation - Google Chrome")
        self.assertEqual(cp.display_name(a, "fr", "canva.com/design/x"), "Canva")
        self.assertEqual(cp.display_name(a, "fr"), "Chrome")


class ProviderUrlTest(unittest.TestCase):
    class Tracker:
        def __init__(self, current=None):
            self.app = current

        def current(self):
            return self.app

    def setUp(self):
        self.tracker = self.Tracker()
        self.reader = FakeReader()
        self.sent = []
        self.logs = []
        self.provider = ContextProvider(tracker=self.tracker, send_shortcut=lambda s: self.sent.append(s) or True,
                                        log=self.logs.append, url_reader=self.reader)

    def test_a_canva_tab_with_an_unhelpful_title_gets_the_canva_bar(self):
        self.tracker.app = app("chrome.exe", "hdi - Présentation - Google Chrome", hwnd=77)
        self.reader.value = "canva.com/design/DAHXJqQrXIo/abc/edit"
        snap = self.provider.snapshot()
        self.assertEqual((snap["app"], snap["profile"]), ("Canva", "canva"))
        self.assertEqual([p["id"] for p in snap["pages"]], ["tools", "edit", "view"])
        self.assertEqual(self.reader.calls, [(77, "hdi - Présentation - Google Chrome")])

    def test_a_plain_tab_stays_the_browser(self):
        self.tracker.app = app("chrome.exe", "Wikipedia - Google Chrome")
        self.reader.value = "fr.wikipedia.org/wiki/X"
        snap = self.provider.snapshot()
        self.assertEqual((snap["app"], snap["profile"]), ("Chrome", "browser"))

    def test_unreadable_url_falls_back_to_the_title(self):
        self.tracker.app = app("chrome.exe", "Logo - Canva - Google Chrome")
        self.reader.value = None
        self.assertEqual(self.provider.snapshot()["profile"], "canva")

    def test_non_browser_apps_never_query_uia(self):
        for exe in ("Illustrator.exe", "notepad.exe", "Code.exe", "Spotify.exe", "explorer.exe"):
            self.tracker.app = app(exe)
            self.provider.snapshot()
            self.provider.handle({"id": "context.press", "button": "nope"})
        self.assertEqual(self.reader.calls, [])

    def test_no_window_handle_never_queries_uia(self):
        self.tracker.app = app("chrome.exe", "Plain - Google Chrome", hwnd=0)
        self.assertEqual(self.provider.snapshot()["profile"], "browser")
        self.assertEqual(self.reader.calls, [])

    def test_press_uses_the_url_profile(self):
        self.tracker.app = app("chrome.exe", "hdi - Présentation - Google Chrome")
        self.reader.value = "canva.com/design/x"
        self.assertIsNone(self.provider.handle({"id": "context.press", "button": "canva.zoom_fit"}))
        self.assertEqual(self.sent, ["Ctrl+Alt+0"])
        self.sent.clear()
        self.assertIsNone(self.provider.handle({"id": "context.press", "button": "web.reload"}))
        self.assertEqual(self.sent, [])  # the browser bar is not the one in front any more
        self.reader.value = "example.org"
        self.tracker.app = app("chrome.exe", "Other - Google Chrome")
        self.assertIsNone(self.provider.handle({"id": "context.press", "button": "web.reload"}))
        self.assertEqual(self.sent, ["F5"])


@unittest.skipUnless(sys.platform == "win32", "Win32 only")
class ForegroundHwndTest(unittest.TestCase):
    def test_hwnd_is_kept_but_does_not_take_part_in_equality(self):
        self.assertEqual(ForegroundApp("a.exe", "C", "t", 1, 99), ForegroundApp("a.exe", "C", "t", 1))
        self.assertEqual(ForegroundApp("a.exe", "C", "t", 1).hwnd, 0)


if __name__ == "__main__":
    unittest.main()
