import hashlib
import importlib.util
import os
import shutil
import sys
import tempfile
import threading
import unittest
import urllib.error

HAVE_QT = importlib.util.find_spec("PySide6") is not None
if HAVE_QT:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtGui import QImage  # noqa: F401 - loaded before anything can import winrt

from actions import app_icons
from actions import context_profiles as cp
from actions.app_icons import AppIconProvider, fetch_https
from actions.foreground import ForegroundApp


def sha1(data):
    return hashlib.sha1(data).hexdigest()


class FakeWin32:
    """Shell calls: `sh` / `ex` map a path to the HICON they give (0 = nothing)."""

    def __init__(self, sh=None, ex=None):
        self.sh = dict(sh or {})
        self.ex = dict(ex or {})
        self.calls = []
        self.destroyed = []

    def sh_def_extract_icon(self, path):
        self.calls.append(("sh", path))
        return self.sh.get(path, 0)

    def extract_icon_ex(self, path):
        self.calls.append(("ex", path))
        return self.ex.get(path, 0)

    def destroy_icon(self, hicon):
        self.destroyed.append(hicon)


class FakeImaging:
    """`icons` maps an HICON to its PNG (absent = the conversion fails); decoding maps the bytes of an image file."""

    def __init__(self, icons=None, decodes=None):
        self.icons = dict(icons or {})
        self.decodes = dict(decodes or {})
        self.error = None

    def hicon_to_png(self, hicon):
        if self.error:
            raise self.error
        return self.icons.get(hicon)

    def decode_to_png(self, data):
        return self.decodes.get(data)


class FakeFetcher:
    def __init__(self, files=None):
        self.files = dict(files or {})
        self.calls = []

    def __call__(self, url):
        self.calls.append(url)
        return self.files.get(url)


class Clock:
    def __init__(self, t=1000.0):
        self.t = t

    def __call__(self):
        return self.t


PATH_AI = r"C:\Program Files\Adobe\Illustrator.exe"
PATH_CHROME = r"C:\Program Files\Google\Chrome\chrome.exe"
PNG_AI = b"\x89PNG-illustrator"
PNG_CHROME = b"\x89PNG-chrome"
PNG_CANVA = b"\x89PNG-canva-favicon"


def app(exe, path, title="Window", hwnd=5):
    return ForegroundApp(exe, "Cls", title, 1, hwnd, path)


def make(win32=None, imaging=None, fetcher=None, **kw):
    win32 = win32 or FakeWin32(sh={PATH_AI: 11, PATH_CHROME: 12})
    imaging = imaging or FakeImaging(icons={11: PNG_AI, 12: PNG_CHROME})
    fetcher = fetcher or FakeFetcher()
    kw.setdefault("cache_dir", None)
    kw.setdefault("threaded", False)
    kw.setdefault("log", lambda _l: None)
    return AppIconProvider(win32=win32, imaging=imaging, fetcher=fetcher, **kw), win32, imaging, fetcher


class ExeIconTest(unittest.TestCase):
    def test_extracted_converted_and_identified_by_sha1(self):
        provider, win32, _, _ = make()
        a = app("Illustrator.exe", PATH_AI)
        icon_id = provider.icon_id(a, cp.match(a), None)
        self.assertEqual(icon_id, sha1(PNG_AI))
        self.assertEqual(provider.artwork_bytes(icon_id), PNG_AI)
        self.assertEqual(win32.calls, [("sh", PATH_AI)])
        self.assertEqual(win32.destroyed, [11])

    def test_falls_back_to_extracticonex(self):
        win32 = FakeWin32(sh={}, ex={PATH_AI: 21})
        provider, win32, _, _ = make(win32=win32, imaging=FakeImaging(icons={21: PNG_AI}))
        a = app("Illustrator.exe", PATH_AI)
        self.assertEqual(provider.icon_id(a, cp.match(a), None), sha1(PNG_AI))
        self.assertEqual(win32.calls, [("sh", PATH_AI), ("ex", PATH_AI)])
        self.assertEqual(win32.destroyed, [21])

    def test_falls_back_when_the_first_icon_cannot_be_converted_and_destroys_both(self):
        win32 = FakeWin32(sh={PATH_AI: 11}, ex={PATH_AI: 21})
        provider, win32, _, _ = make(win32=win32, imaging=FakeImaging(icons={21: PNG_AI}))
        a = app("Illustrator.exe", PATH_AI)
        self.assertEqual(provider.icon_id(a, cp.match(a), None), sha1(PNG_AI))
        self.assertEqual(win32.destroyed, [11, 21])

    def test_no_icon_at_all_is_none(self):
        provider, win32, _, _ = make(win32=FakeWin32(), imaging=FakeImaging())
        a = app("Illustrator.exe", PATH_AI)
        self.assertIsNone(provider.icon_id(a, cp.match(a), None))
        self.assertEqual(win32.destroyed, [])

    def test_destroy_icon_is_called_even_when_the_conversion_raises(self):
        imaging = FakeImaging(icons={11: PNG_AI})
        imaging.error = RuntimeError("Qt exploded")
        logs = []
        provider, win32, _, _ = make(imaging=imaging, log=logs.append)
        a = app("Illustrator.exe", PATH_AI)
        self.assertIsNone(provider.icon_id(a, cp.match(a), None))
        self.assertEqual(win32.destroyed, [11])
        self.assertEqual(len(logs), 1)  # logged once

    def test_no_path_no_icon(self):
        provider, win32, _, _ = make()
        a = app("Illustrator.exe", "")
        self.assertIsNone(provider.icon_id(a, cp.match(a), None))
        self.assertIsNone(provider.icon_id(None, cp.match(None), None))
        self.assertEqual(win32.calls, [])

    def test_artwork_bytes_of_an_unknown_id(self):
        provider, *_ = make()
        self.assertIsNone(provider.artwork_bytes("nope"))
        self.assertIsNone(provider.artwork_bytes(None))

    def test_memory_cache_by_exe_path(self):
        provider, win32, _, _ = make()
        a = app("Illustrator.exe", PATH_AI)
        first = provider.icon_id(a, cp.match(a), None)
        for _ in range(5):
            self.assertEqual(provider.icon_id(a, cp.match(a), None), first)
        self.assertEqual(len(win32.calls), 1)
        upper = app("Illustrator.exe", PATH_AI.upper())  # Windows paths ignore the case
        self.assertEqual(provider.icon_id(upper, cp.match(upper), None), first)
        self.assertEqual(len(win32.calls), 1)

    def test_failure_is_remembered_for_ten_minutes(self):
        clock = Clock()
        provider, win32, _, _ = make(win32=FakeWin32(), imaging=FakeImaging(), clock=clock)
        a = app("Illustrator.exe", PATH_AI)
        for _ in range(4):
            self.assertIsNone(provider.icon_id(a, cp.match(a), None))
        self.assertEqual(len(win32.calls), 2)  # one attempt: SHDefExtractIconW then ExtractIconExW
        clock.t += app_icons.FAILURE_MEMORY_S - 1
        provider.icon_id(a, cp.match(a), None)
        self.assertEqual(len(win32.calls), 2)
        clock.t += 2
        provider.icon_id(a, cp.match(a), None)
        self.assertEqual(len(win32.calls), 4)  # retried

    def test_images_cache_stays_bounded(self):
        win32 = FakeWin32(sh={f"C:\\app{i}.exe": i + 1 for i in range(100)})
        imaging = FakeImaging(icons={i + 1: f"png{i}".encode() for i in range(100)})
        provider, *_ = make(win32=win32, imaging=imaging)
        for i in range(100):
            a = app(f"app{i}.exe", f"C:\\app{i}.exe")
            provider.icon_id(a, cp.match(a), None)
        self.assertLessEqual(len(provider._images), 64)


class SourceChoiceTest(unittest.TestCase):
    CANVA_FILES = {"https://canva.com/favicon.ico": b"ICO-canva"}

    def provider(self, **kw):
        fetcher = FakeFetcher(self.CANVA_FILES)
        imaging = FakeImaging(icons={11: PNG_AI, 12: PNG_CHROME}, decodes={b"ICO-canva": PNG_CANVA})
        return make(imaging=imaging, fetcher=fetcher, **kw)

    def test_a_native_app_uses_its_exe_and_never_the_network(self):
        provider, _, _, fetcher = self.provider()
        a = app("Illustrator.exe", PATH_AI)
        self.assertEqual(provider.icon_id(a, cp.match(a), "canva.com/x"), sha1(PNG_AI))
        self.assertEqual(fetcher.calls, [])

    def test_native_canva_uses_its_exe_not_the_favicon(self):
        provider, _, _, fetcher = self.provider()
        a = app("Canva.exe", PATH_CHROME)  # any exe path: the point is that the site is not fetched
        self.assertEqual(cp.match(a).id, "canva")
        provider.icon_id(a, cp.match(a), "canva.com/x")
        self.assertEqual(fetcher.calls, [])

    def test_generic_browser_keeps_the_browser_icon(self):
        provider, _, _, fetcher = self.provider()
        a = app("chrome.exe", PATH_CHROME, "Wikipedia - Google Chrome")
        profile = cp.match(a, "fr.wikipedia.org/wiki/X")
        self.assertEqual(profile.id, "browser")
        self.assertEqual(provider.icon_id(a, profile, "fr.wikipedia.org/wiki/X"), sha1(PNG_CHROME))
        self.assertEqual(fetcher.calls, [])

    def test_a_site_profile_picked_by_url_uses_the_favicon(self):
        provider, _, _, fetcher = self.provider()
        a = app("chrome.exe", PATH_CHROME, "hdi - Présentation - Google Chrome")
        profile = cp.match(a, "canva.com/design/x/edit")
        self.assertEqual(profile.id, "canva")
        icon_id = provider.icon_id(a, profile, "canva.com/design/x/edit")
        self.assertEqual(icon_id, sha1(PNG_CANVA))
        self.assertEqual(provider.artwork_bytes(icon_id), PNG_CANVA)
        self.assertEqual(fetcher.calls, ["https://canva.com/favicon.ico"])

    def test_a_site_profile_picked_by_title_only_uses_the_browser_icon(self):
        provider, _, _, fetcher = self.provider()
        a = app("chrome.exe", PATH_CHROME, "Logo - Canva - Google Chrome")
        profile = cp.match(a, None)
        self.assertEqual(profile.id, "canva")
        self.assertEqual(provider.icon_id(a, profile, None), sha1(PNG_CHROME))
        self.assertEqual(fetcher.calls, [])

    def test_a_subdomain_is_fetched_from_that_host(self):
        fetcher = FakeFetcher({"https://design.figma.com/favicon.ico": b"ICO-f"})
        provider, *_ = make(imaging=FakeImaging(icons={12: PNG_CHROME}, decodes={b"ICO-f": b"PNG-f"}),
                            fetcher=fetcher)
        a = app("msedge.exe", PATH_CHROME)
        profile = cp.match(a, "https://www.design.figma.com/file/1")
        self.assertEqual(profile.id, "figma")
        self.assertEqual(provider.icon_id(a, profile, "https://www.design.figma.com/file/1"), sha1(b"PNG-f"))
        self.assertEqual(fetcher.calls, ["https://design.figma.com/favicon.ico"])

    def test_hosts_that_are_not_public_names_are_never_fetched(self):
        provider, _, _, fetcher = self.provider()
        a = app("chrome.exe", PATH_CHROME)
        figma = cp.profile_by_id("figma")
        for url in ("localhost/x", "192.168.1.5/figma.com", "10.0.0.1:8080", "evil host/x", None):
            provider.icon_id(a, figma, url)
        self.assertEqual(fetcher.calls, [])


class FaviconTest(unittest.TestCase):
    def setUp(self):
        self.a = app("chrome.exe", PATH_CHROME, "x - Google Chrome")
        self.profile = cp.profile_by_id("canva")

    def ask(self, provider):
        return provider.icon_id(self.a, self.profile, "canva.com/design/x")

    def test_ico_then_png_fallback(self):
        fetcher = FakeFetcher({"https://canva.com/apple-touch-icon.png": b"PNGFILE"})
        provider, *_ = make(imaging=FakeImaging(icons={12: PNG_CHROME}, decodes={b"PNGFILE": PNG_CANVA}),
                            fetcher=fetcher)
        self.assertEqual(self.ask(provider), sha1(PNG_CANVA))
        self.assertEqual(fetcher.calls, ["https://canva.com/favicon.ico", "https://canva.com/apple-touch-icon.png"])

    def test_an_ico_that_does_not_decode_falls_back_to_the_png(self):
        fetcher = FakeFetcher({"https://canva.com/favicon.ico": b"garbage",
                               "https://canva.com/apple-touch-icon.png": b"PNGFILE"})
        provider, *_ = make(imaging=FakeImaging(icons={12: PNG_CHROME}, decodes={b"PNGFILE": PNG_CANVA}),
                            fetcher=fetcher)
        self.assertEqual(self.ask(provider), sha1(PNG_CANVA))

    def test_too_big_a_download_is_skipped(self):
        big = b"x" * (app_icons.FETCH_MAX_BYTES + 1)
        fetcher = FakeFetcher({"https://canva.com/favicon.ico": big})
        provider, *_ = make(imaging=FakeImaging(icons={12: PNG_CHROME}, decodes={big: b"never"}), fetcher=fetcher)
        self.assertEqual(self.ask(provider), sha1(PNG_CHROME))  # the browser's icon stands in

    def test_failure_gives_the_browser_icon_and_is_not_retried_for_ten_minutes(self):
        clock = Clock()
        fetcher = FakeFetcher()
        provider, *_ = make(imaging=FakeImaging(icons={12: PNG_CHROME}), fetcher=fetcher, clock=clock)
        self.assertEqual(self.ask(provider), sha1(PNG_CHROME))
        self.assertEqual(len(fetcher.calls), 2)
        for _ in range(3):
            self.assertEqual(self.ask(provider), sha1(PNG_CHROME))
        self.assertEqual(len(fetcher.calls), 2)
        clock.t += app_icons.FAILURE_MEMORY_S + 1
        fetcher.files["https://canva.com/favicon.ico"] = b"ICO"
        provider._imaging.decodes[b"ICO"] = PNG_CANVA
        self.ask(provider)  # the retry
        self.assertEqual(len(fetcher.calls), 3)
        self.assertEqual(self.ask(provider), sha1(PNG_CANVA))

    def test_memory_cache_by_host(self):
        fetcher = FakeFetcher({"https://canva.com/favicon.ico": b"ICO"})
        provider, *_ = make(imaging=FakeImaging(icons={12: PNG_CHROME}, decodes={b"ICO": PNG_CANVA}), fetcher=fetcher)
        for _ in range(4):
            self.assertEqual(self.ask(provider), sha1(PNG_CANVA))
        self.assertEqual(len(fetcher.calls), 1)


class DiskCacheTest(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="orizonx-icons-test-")
        self.addCleanup(shutil.rmtree, self.dir, ignore_errors=True)
        self.a = app("chrome.exe", PATH_CHROME)
        self.profile = cp.profile_by_id("canva")
        self.wall = Clock(2_000_000.0)

    def provider(self, files):
        fetcher = FakeFetcher(files)
        imaging = FakeImaging(icons={12: PNG_CHROME}, decodes={b"ICO": PNG_CANVA, b"ICO2": b"PNG2"})
        provider, *_ = make(imaging=imaging, fetcher=fetcher, cache_dir=self.dir, wall_clock=self.wall)
        return provider, fetcher

    def ask(self, provider):
        return provider.icon_id(self.a, self.profile, "canva.com/x")

    def test_a_downloaded_favicon_is_written_to_disk(self):
        provider, _ = self.provider({"https://canva.com/favicon.ico": b"ICO"})
        self.ask(provider)
        path = os.path.join(self.dir, "canva.com.png")
        with open(path, "rb") as f:
            self.assertEqual(f.read(), PNG_CANVA)

    def test_a_fresh_disk_file_avoids_the_network(self):
        provider, _ = self.provider({"https://canva.com/favicon.ico": b"ICO"})
        self.ask(provider)
        path = os.path.join(self.dir, "canva.com.png")
        os.utime(path, (self.wall.t - 3600, self.wall.t - 3600))
        second, fetcher = self.provider({})
        self.assertEqual(self.ask(second), sha1(PNG_CANVA))
        self.assertEqual(fetcher.calls, [])

    def test_an_expired_disk_file_is_downloaded_again(self):
        provider, _ = self.provider({"https://canva.com/favicon.ico": b"ICO"})
        self.ask(provider)
        path = os.path.join(self.dir, "canva.com.png")
        old = self.wall.t - app_icons.DISK_VALID_S - 10
        os.utime(path, (old, old))
        second, fetcher = self.provider({"https://canva.com/favicon.ico": b"ICO2"})
        self.assertEqual(self.ask(second), sha1(b"PNG2"))
        self.assertEqual(len(fetcher.calls), 1)
        with open(path, "rb") as f:
            self.assertEqual(f.read(), b"PNG2")

    def test_an_expired_file_is_used_when_the_download_fails(self):
        provider, _ = self.provider({"https://canva.com/favicon.ico": b"ICO"})
        self.ask(provider)
        path = os.path.join(self.dir, "canva.com.png")
        old = self.wall.t - app_icons.DISK_VALID_S - 10
        os.utime(path, (old, old))
        second, fetcher = self.provider({})
        self.assertEqual(self.ask(second), sha1(PNG_CANVA))
        self.assertEqual(len(fetcher.calls), 2)

    def test_exe_icons_are_not_written_to_disk(self):
        provider, *_ = make(cache_dir=self.dir)
        a = app("Illustrator.exe", PATH_AI)
        provider.icon_id(a, cp.match(a), None)
        self.assertEqual(os.listdir(self.dir), [])

    def test_an_unwritable_cache_dir_is_not_an_error(self):
        blocker = os.path.join(self.dir, "file")
        with open(blocker, "wb") as f:
            f.write(b"x")
        fetcher = FakeFetcher({"https://canva.com/favicon.ico": b"ICO"})
        provider, *_ = make(imaging=FakeImaging(icons={12: PNG_CHROME}, decodes={b"ICO": PNG_CANVA}),
                            fetcher=fetcher, cache_dir=os.path.join(blocker, "icons"))
        self.assertEqual(self.ask(provider), sha1(PNG_CANVA))


class WorkerTest(unittest.TestCase):
    def test_icon_id_never_blocks_and_the_icon_comes_later(self):
        gate = threading.Event()
        calls = []

        def slow_fetcher(url):
            calls.append(url)
            gate.wait(5)
            return b"ICO" if url.endswith("favicon.ico") else None

        provider = AppIconProvider(win32=FakeWin32(sh={PATH_CHROME: 12}),
                                   imaging=FakeImaging(icons={12: PNG_CHROME}, decodes={b"ICO": PNG_CANVA}),
                                   fetcher=slow_fetcher, cache_dir=None, log=lambda _l: None)
        a = app("chrome.exe", PATH_CHROME)
        canva = cp.profile_by_id("canva")
        self.assertIsNone(provider.icon_id(a, canva, "canva.com/x"))  # returns at once, nothing ready
        self.assertIsNone(provider.icon_id(a, canva, "canva.com/x"))  # still downloading: no second request
        gate.set()
        self.assertTrue(provider.wait_idle(5))
        self.assertEqual(provider.icon_id(a, canva, "canva.com/x"), sha1(PNG_CANVA))
        self.assertEqual(calls, ["https://canva.com/favicon.ico"])

    def test_the_extraction_runs_in_another_thread(self):
        seen = []

        class Win32(FakeWin32):
            def sh_def_extract_icon(self, path):
                seen.append(threading.get_ident())
                return 11

        provider = AppIconProvider(win32=Win32(), imaging=FakeImaging(icons={11: PNG_AI}), cache_dir=None,
                                   log=lambda _l: None)
        a = app("Illustrator.exe", PATH_AI)
        self.assertIsNone(provider.icon_id(a, cp.match(a), None))
        self.assertTrue(provider.wait_idle(5))
        self.assertEqual(provider.icon_id(a, cp.match(a), None), sha1(PNG_AI))
        self.assertNotIn(threading.get_ident(), seen)
        self.assertEqual(len(seen), 1)


class FakeResponse:
    def __init__(self, data, chunk=None):
        self.data = data
        self.pos = 0

    def read(self, n=-1):
        chunk = self.data[self.pos:self.pos + n]
        self.pos += len(chunk)
        return chunk

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class FakeOpener:
    def __init__(self, response=None, error=None):
        self.response = response
        self.error = error
        self.requests = []
        self.timeouts = []

    def open(self, request, timeout=None):
        self.requests.append(request)
        self.timeouts.append(timeout)
        if self.error:
            raise self.error
        return self.response


class FetchHttpsTest(unittest.TestCase):
    def test_downloads_with_a_neutral_user_agent_and_the_timeout(self):
        opener = FakeOpener(FakeResponse(b"icon-bytes"))
        self.assertEqual(fetch_https("https://canva.com/favicon.ico", opener=opener), b"icon-bytes")
        request = opener.requests[0]
        self.assertEqual(request.get_header("User-agent"), "Mozilla/5.0")
        self.assertIsNone(request.get_header("Cookie"))
        self.assertEqual(opener.timeouts, [3.0])

    def test_http_is_refused_without_any_request(self):
        opener = FakeOpener(FakeResponse(b"x"))
        for url in ("http://canva.com/favicon.ico", "ftp://x/y", "//canva.com/x", "canva.com/x", "", None):
            self.assertIsNone(fetch_https(url, opener=opener))
        self.assertEqual(opener.requests, [])

    def test_exactly_the_limit_is_accepted_one_more_byte_is_not(self):
        limit = app_icons.FETCH_MAX_BYTES
        self.assertEqual(len(fetch_https("https://a.com/i", opener=FakeOpener(FakeResponse(b"x" * limit)))), limit)
        self.assertIsNone(fetch_https("https://a.com/i", opener=FakeOpener(FakeResponse(b"x" * (limit + 1)))))

    def test_errors_and_timeouts_give_none(self):
        for error in (urllib.error.URLError("x"), TimeoutError("slow"), OSError("reset"), ValueError("bad")):
            with self.subTest(error):
                self.assertIsNone(fetch_https("https://a.com/i", opener=FakeOpener(error=error)))

    def test_total_time_is_bounded(self):
        t = [0.0]

        class Slow(FakeResponse):
            def read(self, n=-1):
                t[0] += 2.0  # each chunk takes 2 s
                return b"x" * 10

        self.assertIsNone(fetch_https("https://a.com/i", opener=FakeOpener(Slow(b"")), clock=lambda: t[0]))

    def test_empty_body_is_none(self):
        self.assertIsNone(fetch_https("https://a.com/i", opener=FakeOpener(FakeResponse(b""))))

    def test_a_redirect_to_http_is_refused(self):
        handler = app_icons._HttpsOnlyRedirects()
        with self.assertRaises(urllib.error.URLError):
            handler.redirect_request(None, None, 302, "Found", {}, "http://evil.example/x")


class ForegroundPathTest(unittest.TestCase):
    def test_path_does_not_take_part_in_equality(self):
        self.assertEqual(ForegroundApp("a.exe", "C", "t", 1, 2, r"C:\x\a.exe"), ForegroundApp("a.exe", "C", "t", 1))

    def test_the_tracker_fills_the_full_path(self):
        from tests.test_actions_foreground import make
        api, tracker = make()
        api.add(10, "Chrome_WidgetWin_1", "Tab", 111, r"C:\x\chrome.exe")
        api.foreground = 10
        self.assertEqual(tracker.current().path, r"C:\x\chrome.exe")
        api.windows[11] = ("Cls", "Admin shell", 222)  # unreadable process
        api.foreground = 11
        self.assertEqual(tracker.current().path, "")


@unittest.skipUnless(HAVE_QT and sys.platform == "win32", "PySide6 absent or not Windows")
class RealConversionTest(unittest.TestCase):
    """Read-only: notepad.exe's icon through the real shell calls and Qt (no window, no file written)."""

    NOTEPAD = r"C:\Windows\System32\notepad.exe"

    def png_size(self, png):
        image = QImage()
        self.assertTrue(image.loadFromData(png))
        return image.width(), image.height(), image

    def test_notepad_icon_becomes_a_96_px_png(self):
        provider = AppIconProvider(cache_dir=None, threaded=False, log=print)  # real Win32 + Qt layers
        a = app("notepad.exe", self.NOTEPAD)
        icon_id = provider.icon_id(a, cp.match(a), None)
        self.assertIsNotNone(icon_id)
        png = provider.artwork_bytes(icon_id)
        self.assertEqual(png[:8], b"\x89PNG\r\n\x1a\n")
        self.assertEqual(icon_id, sha1(png))
        w, h, image = self.png_size(png)
        self.assertEqual((w, h), (96, 96))
        self.assertTrue(image.hasAlphaChannel())
        self.assertTrue(any(image.pixelColor(x, y).alpha() > 0 for x in range(0, 96, 8) for y in range(0, 96, 8)))

    def test_decodes_an_ico_container_and_a_non_square_image(self):
        import struct
        from PySide6.QtCore import QBuffer, QByteArray, QIODevice
        from PySide6.QtGui import QColor
        src = QImage(32, 32, QImage.Format.Format_ARGB32)
        src.fill(QColor(200, 30, 30, 255))
        data = QByteArray()
        buf = QBuffer(data)
        buf.open(QIODevice.OpenModeFlag.WriteOnly)
        src.save(buf, "PNG")
        png = bytes(data.data())
        ico = struct.pack("<HHH", 0, 1, 1) + struct.pack("<BBBBHHII", 32, 32, 0, 0, 1, 32, len(png), 22) + png
        imaging = app_icons.QtImaging()
        out = imaging.decode_to_png(ico)
        self.assertIsNotNone(out)
        self.assertEqual(self.png_size(out)[:2], (96, 96))
        wide = QImage(64, 16, QImage.Format.Format_ARGB32)
        wide.fill(QColor(0, 0, 255, 255))
        data2 = QByteArray()
        buf2 = QBuffer(data2)
        buf2.open(QIODevice.OpenModeFlag.WriteOnly)
        wide.save(buf2, "PNG")
        out2 = imaging.decode_to_png(bytes(data2.data()))
        w, h, image = self.png_size(out2)
        self.assertEqual((w, h), (96, 96))
        self.assertEqual(image.pixelColor(48, 48).blue(), 255)   # the picture, centred
        self.assertEqual(image.pixelColor(48, 2).alpha(), 0)     # transparent bands above and below
        self.assertIsNone(imaging.decode_to_png(b"not an image"))


if __name__ == "__main__":
    unittest.main()
