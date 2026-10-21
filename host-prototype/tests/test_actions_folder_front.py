import unittest

from actions import folder_front
from actions.folder_front import bring_folder_to_front, open_folder_to_front, same_path


class FakeFront:
    """Fake window layer: nothing real is ever pressed, opened or raised."""

    def __init__(self, appears_after=0, hwnd=42, foreground=0, raise_ok=True, calls=None):
        self.appears_after = appears_after  # find() answers 0 this many times, then hwnd
        self.hwnd = hwnd
        self.fg = foreground
        self.raise_ok = raise_ok
        self.finds = []
        self.raised = []
        self.calls = calls if calls is not None else []

    def prepare(self):
        self.calls.append("prepare")

    def find(self, path):
        self.finds.append(path)
        return self.hwnd if len(self.finds) > self.appears_after else 0

    def foreground(self):
        return self.fg

    def raise_(self, hwnd):
        self.raised.append(hwnd)
        return self.raise_ok


class BringTests(unittest.TestCase):
    def run_bring(self, front, **kwargs):
        sleeps, logs = [], []
        result = bring_folder_to_front("E:\\", front, sleeps.append, log=logs.append, **kwargs)
        return result, sleeps, logs

    def test_found_at_once_is_raised_without_waiting(self):
        front = FakeFront()
        result, sleeps, logs = self.run_bring(front)
        self.assertTrue(result)
        self.assertEqual(front.raised, [42])
        self.assertEqual(sleeps, [])
        self.assertEqual(logs, [])

    def test_found_after_n_polls_then_raised_and_polling_stops(self):
        front = FakeFront(appears_after=3)
        result, sleeps, _ = self.run_bring(front)
        self.assertTrue(result)
        self.assertEqual(len(front.finds), 4)
        self.assertEqual(sleeps, [0.1, 0.1, 0.1])
        self.assertEqual(front.raised, [42])

    def test_not_found_times_out_without_raising(self):
        front = FakeFront(appears_after=10 ** 6)
        result, sleeps, logs = self.run_bring(front, timeout_s=3.0, step_s=0.1)
        self.assertFalse(result)
        self.assertEqual(front.raised, [])
        self.assertAlmostEqual(sum(sleeps), 3.0)
        self.assertEqual(len(logs), 1)

    def test_already_in_front_is_left_alone(self):
        front = FakeFront(foreground=42)
        result, _, _ = self.run_bring(front)
        self.assertTrue(result)
        self.assertEqual(front.raised, [])

    def test_a_refused_raise_is_logged_once_and_not_an_error(self):
        front = FakeFront(raise_ok=False)
        result, _, logs = self.run_bring(front)
        self.assertFalse(result)
        self.assertEqual(len(logs), 1)

    def test_never_raises(self):
        class Boom(FakeFront):
            def find(self, path):
                raise OSError("COM")

        result, _, logs = self.run_bring(Boom())
        self.assertFalse(result)
        self.assertEqual(len(logs), 1)
        self.assertIn("OSError", logs[0])


class OpenTests(unittest.TestCase):
    def test_prepare_comes_before_the_open_and_the_raise_after(self):
        calls = []
        front = FakeFront(calls=calls)
        open_folder_to_front("E:\\", lambda: calls.append("open"), front, lambda _s: None)
        self.assertEqual(calls, ["prepare", "open"])
        self.assertEqual(front.raised, [42])

    def test_the_opener_error_propagates_and_nothing_is_raised(self):
        front = FakeFront()

        def opener():
            raise OSError(2, "gone")

        with self.assertRaises(OSError):
            open_folder_to_front("E:\\", opener, front, lambda _s: None)
        self.assertEqual(front.raised, [])

    def test_a_failing_prepare_does_not_stop_the_open(self):
        class BadPrepare(FakeFront):
            def prepare(self):
                raise RuntimeError("user32")

        opened, logs = [], []
        front = BadPrepare()
        open_folder_to_front("E:\\", lambda: opened.append(1), front, lambda _s: None, logs.append)
        self.assertEqual(opened, [1])
        self.assertEqual(front.raised, [42])
        self.assertEqual(len(logs), 1)

    def test_no_front_only_opens(self):
        opened = []
        open_folder_to_front("E:\\", lambda: opened.append(1), None, lambda _s: None)
        self.assertEqual(opened, [1])

    def test_ensure_front_keeps_a_given_one_and_survives_a_failing_build(self):
        front = FakeFront()
        self.assertIs(folder_front.ensure_front(front, lambda _l: None), front)
        real = folder_front.FolderFront

        def broken():
            raise OSError("not windows")

        logs = []
        folder_front.FolderFront = broken
        try:
            self.assertIsNone(folder_front.ensure_front(None, logs.append))
        finally:
            folder_front.FolderFront = real
        self.assertEqual(len(logs), 1)


class PathTests(unittest.TestCase):
    def test_drive_root_matches_whatever_the_spelling(self):
        for other in ("E:\\", "e:\\", "e:/", "E:\\."):
            self.assertTrue(same_path(other, "E:\\"), other)

    def test_folders_compare_normalised_and_case_insensitive(self):
        self.assertTrue(same_path("c:/users/ME/downloads\\", r"C:\Users\me\Downloads"))
        self.assertFalse(same_path(r"C:\Users\me\Documents", r"C:\Users\me\Downloads"))
        self.assertFalse(same_path(None, r"C:\x"))
        self.assertFalse(same_path("E:\\", "F:\\"))


class FolderFrontFindTests(unittest.TestCase):
    """The real class with its Explorer listing and user32 pieces faked: no window is touched."""

    def make(self, folders, visible, classes):
        front = folder_front.FolderFront.__new__(folder_front.FolderFront)
        front._visible = lambda hwnd: hwnd in visible

        class Api:
            def window_class(self, hwnd):
                return classes.get(hwnd, "")

        front._api = Api()
        real = folder_front.explorer_folders
        folder_front.explorer_folders = lambda: folders
        self.addCleanup(setattr, folder_front, "explorer_folders", real)
        return front

    def test_a_visible_cabinet_window_on_the_drive_root_is_found(self):
        front = self.make({7: "E:\\", 8: "C:\\x"}, {7, 8}, {7: "CabinetWClass", 8: "CabinetWClass"})
        self.assertEqual(front.find("e:\\"), 7)

    def test_hidden_or_non_explorer_windows_and_other_folders_are_not(self):
        front = self.make({7: "E:\\", 8: "E:\\", 9: "F:\\"}, {8, 9}, {7: "CabinetWClass", 8: "IEFrame", 9: "CabinetWClass"})
        self.assertEqual(front.find("E:\\"), 0)


class RaiseTests(unittest.TestCase):
    def make(self, iconic=False, results=(True,)):
        front = folder_front.FolderFront.__new__(folder_front.FolderFront)
        log = []
        outcomes = list(results)

        class Raiser:
            def is_iconic(self, hwnd):
                return iconic

            def restore(self, hwnd):
                log.append("restore")

            def set_foreground(self, hwnd):
                log.append("set")
                return outcomes.pop(0)

            def alt_tap(self):
                log.append("alt")

        front._raiser = Raiser()
        return front, log

    def test_plain_raise(self):
        front, log = self.make()
        self.assertTrue(front.raise_(1))
        self.assertEqual(log, ["set"])

    def test_minimized_window_is_restored_first(self):
        front, log = self.make(iconic=True)
        self.assertTrue(front.raise_(1))
        self.assertEqual(log, ["restore", "set"])

    def test_refusal_taps_alt_and_retries_once(self):
        front, log = self.make(results=(False, True))
        self.assertTrue(front.raise_(1))
        self.assertEqual(log, ["set", "alt", "set"])
        front, log = self.make(results=(False, False))
        self.assertFalse(front.raise_(1))
        self.assertEqual(log, ["set", "alt", "set"])


if __name__ == "__main__":
    unittest.main()
