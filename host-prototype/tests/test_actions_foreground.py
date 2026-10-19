import sys
import unittest

from actions import foreground
from actions.foreground import ForegroundApp, ForegroundTracker


class FakeApi:
    """A user32/kernel32 stand-in: windows are hwnd -> (class, title, pid); exes are pid -> full path."""

    def __init__(self):
        self.windows = {}
        self.exes = {}
        self.foreground = 0

    def add(self, hwnd, cls, title, pid, exe):
        self.windows[hwnd] = (cls, title, pid)
        self.exes[pid] = exe

    def foreground_window(self):
        return self.foreground

    def window_class(self, hwnd):
        return self.windows[hwnd][0]

    def window_title(self, hwnd):
        return self.windows[hwnd][1]

    def window_pid(self, hwnd):
        return self.windows[hwnd][2]

    def process_exe(self, pid):
        return self.exes.get(pid)


OWN_PID = 4000
PARENT_PID = 3000


def make(own_exe=r"C:\Program Files\OrizonX\OrizonX.exe"):
    api = FakeApi()
    api.exes[OWN_PID] = own_exe
    tracker = ForegroundTracker(api=api, own_pid=OWN_PID, parent_pid=PARENT_PID)
    return api, tracker


class DetectionTest(unittest.TestCase):
    def test_reports_the_exe_class_title_and_pid(self):
        api, tracker = make()
        api.add(10, "PPTFrameClass", "Deck - PowerPoint", 111, r"C:\Office\POWERPNT.EXE")
        api.foreground = 10
        self.assertEqual(tracker.current(), ForegroundApp("POWERPNT.EXE", "PPTFrameClass", "Deck - PowerPoint", 111))

    def test_reports_the_window_handle(self):
        api, tracker = make()
        api.add(10, "Chrome_WidgetWin_1", "Tab", 111, r"C:\x\chrome.exe")
        api.foreground = 10
        self.assertEqual(tracker.current().hwnd, 10)

    def test_nothing_seen_yet_is_none(self):
        api, tracker = make()
        api.foreground = 0
        self.assertIsNone(tracker.current())

    def test_follows_the_foreground_window(self):
        api, tracker = make()
        api.add(10, "Chrome_WidgetWin_1", "Tab", 111, r"C:\x\chrome.exe")
        api.add(11, "SpotifyMainWindow", "Spotify", 112, r"C:\x\Spotify.exe")
        api.foreground = 10
        self.assertEqual(tracker.current().exe, "chrome.exe")
        api.foreground = 11
        self.assertEqual(tracker.current().exe, "Spotify.exe")

    def test_unreadable_process_gives_an_empty_exe(self):
        api, tracker = make()
        api.windows[10] = ("Cls", "Admin shell", 222)  # no exe: an elevated process
        api.foreground = 10
        app = tracker.current()
        self.assertEqual((app.exe, app.title, app.pid), ("", "Admin shell", 222))


class IgnoredTest(unittest.TestCase):
    def setUp(self):
        self.api, self.tracker = make()
        self.api.add(10, "Chrome_WidgetWin_1", "Tab", 111, r"C:\x\chrome.exe")
        self.api.foreground = 10
        self.assertEqual(self.tracker.current().exe, "chrome.exe")

    def assert_keeps_chrome(self):
        self.assertEqual(self.tracker.current().exe, "chrome.exe")

    def test_own_exe_name_is_ignored(self):
        self.api.add(20, "SomeWnd", "Orizon X", 999, r"C:\Apps\OrizonX.exe")
        self.api.foreground = 20
        self.assert_keeps_chrome()

    def test_own_exe_name_is_case_insensitive(self):
        self.api.add(20, "SomeWnd", "Orizon X", 999, r"C:\Apps\ORIZONX.EXE")
        self.api.foreground = 20
        self.assert_keeps_chrome()

    def test_own_pid_is_ignored_when_running_from_source(self):
        # python.exe is not ignored by name, only by pid
        self.api.exes[OWN_PID] = r"C:\Python\pythonw.exe"
        self.api.add(20, "TkTopLevel", "Orizon X settings", OWN_PID, r"C:\Python\pythonw.exe")
        self.api.foreground = 20
        self.assert_keeps_chrome()

    def test_another_python_process_is_a_real_app(self):
        self.api.exes[OWN_PID] = r"C:\Python\pythonw.exe"
        self.api.add(20, "TkTopLevel", "Other tool", 777, r"C:\Python\pythonw.exe")
        self.api.foreground = 20
        self.assertEqual(self.tracker.current().exe, "pythonw.exe")

    def test_desktop_and_taskbar_classes_are_ignored(self):
        for cls in ("Progman", "WorkerW", "Shell_TrayWnd", "Shell_SecondaryTrayWnd"):
            with self.subTest(cls):
                self.api.add(30, cls, "", 555, r"C:\Windows\explorer.exe")
                self.api.foreground = 30
                self.assert_keeps_chrome()

    def test_explorer_folder_window_is_a_real_app(self):
        self.api.add(30, "CabinetWClass", "Documents", 555, r"C:\Windows\explorer.exe")
        self.api.foreground = 30
        app = self.tracker.current()
        self.assertEqual((app.exe, app.window_class), ("explorer.exe", "CabinetWClass"))

    def test_no_foreground_window_keeps_the_last_app(self):
        self.api.foreground = 0
        self.assert_keeps_chrome()

    def test_ignored_window_before_any_app_gives_none(self):
        api, tracker = make()
        api.add(30, "Shell_TrayWnd", "", 555, r"C:\Windows\explorer.exe")
        api.foreground = 30
        self.assertIsNone(tracker.current())


class ParentLauncherTest(unittest.TestCase):
    def test_parent_with_the_same_exe_name_is_one_of_ours(self):
        # venv launcher / PyInstaller onefile bootloader: the parent is the same exe
        api = FakeApi()
        api.exes[OWN_PID] = r"C:\venv\Scripts\python.exe"
        api.exes[PARENT_PID] = r"C:\venv\Scripts\python.exe"
        tracker = ForegroundTracker(api=api, own_pid=OWN_PID, parent_pid=PARENT_PID)
        api.add(10, "Chrome_WidgetWin_1", "Tab", 111, r"C:\x\chrome.exe")
        api.foreground = 10
        tracker.current()
        api.add(20, "Cls", "launcher window", PARENT_PID, r"C:\venv\Scripts\python.exe")
        api.foreground = 20
        self.assertEqual(tracker.current().exe, "chrome.exe")

    def test_parent_with_another_exe_is_a_real_app(self):
        # started from Explorer or a terminal: the parent must not be ignored
        api = FakeApi()
        api.exes[OWN_PID] = r"C:\venv\Scripts\python.exe"
        api.exes[PARENT_PID] = r"C:\Windows\explorer.exe"
        tracker = ForegroundTracker(api=api, own_pid=OWN_PID, parent_pid=PARENT_PID)
        api.add(20, "CabinetWClass", "Documents", PARENT_PID, r"C:\Windows\explorer.exe")
        api.foreground = 20
        self.assertEqual(tracker.current().exe, "explorer.exe")


class ShortTitleTest(unittest.TestCase):
    def test_last_segment_of_the_title(self):
        for title, expected in (
                ("Untitled - Notepad", "Notepad"),
                ("Calculator", "Calculator"),
                ("Doc \u2013 Something \u2014 App", "App"),
                ("  Spaced  ", "Spaced"),
                ("", ""),
                ("Trailing - ", "Trailing")):
            with self.subTest(title):
                self.assertEqual(foreground.short_title(title), expected)

    def test_long_titles_are_truncated(self):
        out = foreground.short_title("x" * 80)
        self.assertEqual(len(out), foreground.SHORT_TITLE_MAX)
        self.assertTrue(out.endswith("\u2026"))


@unittest.skipUnless(sys.platform == "win32", "Win32 only")
class Win32ApiTest(unittest.TestCase):
    def test_real_layer_reads_without_raising(self):
        # read-only: asks Windows which window is in front; nothing is sent anywhere
        tracker = ForegroundTracker()
        app = tracker.current()
        self.assertTrue(app is None or isinstance(app, ForegroundApp))


if __name__ == "__main__":
    unittest.main()
