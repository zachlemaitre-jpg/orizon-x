import ctypes
import threading
import unittest

from actions import keyboard, keys
from actions.keyboard import KeyboardProvider, layout_of_hkl


class FakeSendInput:
    """Records every SendInput call as a list of (wVk, wScan, dwFlags); `result` overrides the injected count."""

    def __init__(self):
        self.calls = []
        self.result = None  # None: all injected

    def __call__(self, count, events, size):
        assert size == ctypes.sizeof(keys.INPUT)
        self.calls.append([(e.u.ki.wVk, e.u.ki.wScan, e.u.ki.dwFlags) for e in events])
        assert all(e.type == keys.INPUT_KEYBOARD for e in events)
        return count if self.result is None else self.result

    @property
    def events(self):
        return [e for call in self.calls for e in call]


SC = keyboard.KEYEVENTF_SCANCODE
EXT = keys.KEYEVENTF_EXTENDEDKEY
UP = keys.KEYEVENTF_KEYUP


def make(**kw):
    send = FakeSendInput()
    logs = []
    kw.setdefault("layout_reader", lambda: 0x040C040C)
    provider = KeyboardProvider(send_input=send, log=logs.append, **kw)
    return provider, send, logs


def key(sc, ext=False, down=True):
    return {"id": "keyboard.key", "sc": sc, "ext": ext, "down": down}


class TableTest(unittest.TestCase):
    def test_pairs_are_unique_and_in_range(self):
        pairs = list(keyboard.KEY_TABLE)
        self.assertEqual(len(pairs), len(set(pairs)))
        for sc, ext in pairs:
            self.assertTrue(1 <= sc <= 127, sc)
            self.assertIsInstance(ext, bool)

    def test_the_table_follows_the_spec(self):
        t = keyboard.KEY_TABLE
        plain = (list(range(0x3B, 0x45)) + [0x57, 0x58, 0x01, 0x29, 0x0C, 0x0D, 0x0E, 0x0F, 0x1A, 0x1B, 0x1C, 0x3A,
                                           0x27, 0x28, 0x2B, 0x2A, 0x56, 0x33, 0x34, 0x35, 0x36, 0x1D, 0x38, 0x39]
                 + list(range(0x02, 0x0C)) + list(range(0x10, 0x1A)) + list(range(0x1E, 0x27)) + list(range(0x2C, 0x33)))
        for sc in plain:
            self.assertIn((sc, False), t, hex(sc))
        for sc in (0x53, 0x5B, 0x38, 0x5D, 0x1D, 0x52, 0x47, 0x4F, 0x49, 0x51, 0x48, 0x4B, 0x50, 0x4D):
            self.assertIn((sc, True), t, hex(sc))
        self.assertEqual(len(t), len(set(plain)) + 14)

    def test_pairs_the_spec_does_not_list_are_not_in_it(self):
        for pair in ((0x5B, False), (0x53, False), (0x48, False), (0x56, True), (0x7F, False), (0x3B, True)):
            self.assertNotIn(pair, keyboard.KEY_TABLE)


class KeyInjectionTest(unittest.TestCase):
    def test_down_is_a_scan_code_event_without_a_virtual_key(self):
        provider, send, _ = make()
        self.assertIsNone(provider.handle(key(0x10)))  # 'a' on AZERTY, 'q' on QWERTY: the position
        self.assertEqual(send.calls, [[(0, 0x10, SC)]])

    def test_up_adds_the_keyup_flag(self):
        provider, send, _ = make()
        provider.handle(key(0x10))
        provider.handle(key(0x10, down=False))
        self.assertEqual(send.calls, [[(0, 0x10, SC)], [(0, 0x10, SC | UP)]])

    def test_extended_keys_carry_the_e0_flag(self):
        provider, send, _ = make()
        for sc in (0x4B, 0x4D, 0x48, 0x50, 0x38, 0x5B, 0x53, 0x1D):  # arrows, AltGr, Win, Suppr, right Ctrl
            send.calls.clear()
            provider.handle(key(sc, True))
            provider.handle(key(sc, True, down=False))
            self.assertEqual(send.calls, [[(0, sc, SC | EXT)], [(0, sc, SC | EXT | UP)]], hex(sc))

    def test_left_and_right_variants_are_different_keys(self):
        provider, send, _ = make()
        provider.handle(key(0x38, False))
        provider.handle(key(0x38, True))
        self.assertEqual(send.events, [(0, 0x38, SC), (0, 0x38, SC | EXT)])
        self.assertEqual(provider.held, [(0x38, False), (0x38, True)])

    def test_a_key_outside_the_table_is_refused_and_logged(self):
        provider, send, logs = make()
        for action in (key(0x5B, False), key(0x7F), key(0x48, False), key(0x56, True), key(0), key(200),
                       key(-1), key(1005)):
            with self.subTest(action):
                logs.clear()
                self.assertIsNone(provider.handle(action))
                self.assertEqual(len(logs), 1)
        self.assertEqual(send.calls, [])
        self.assertEqual(provider.held, [])

    def test_malformed_actions_are_refused(self):
        provider, send, logs = make()
        bad = [
            {"id": "keyboard.key"},
            {"id": "keyboard.key", "sc": 0x10, "ext": False},
            {"id": "keyboard.key", "sc": 0x10, "down": True},
            {"id": "keyboard.key", "ext": False, "down": True},
            {"id": "keyboard.key", "sc": "16", "ext": False, "down": True},
            {"id": "keyboard.key", "sc": 16.0, "ext": False, "down": True},
            {"id": "keyboard.key", "sc": True, "ext": False, "down": True},
            {"id": "keyboard.key", "sc": 0x10, "ext": 0, "down": True},
            {"id": "keyboard.key", "sc": 0x10, "ext": False, "down": 1},
            {"id": "keyboard.key", "sc": None, "ext": None, "down": None},
        ]
        for action in bad:
            with self.subTest(action):
                self.assertIsNone(provider.handle(action))
        self.assertEqual(send.calls, [])

    def test_unknown_action_id_is_ignored_and_logged(self):
        provider, send, logs = make()
        self.assertIsNone(provider.handle({"id": "keyboard.other"}))
        self.assertEqual(len(logs), 1)
        self.assertEqual(send.calls, [])

    def test_repeated_downs_are_all_sent_but_the_key_is_held_once(self):
        provider, send, _ = make()
        for _ in range(4):
            provider.handle(key(0x0E))  # Backspace auto-repeat
        self.assertEqual(len(send.calls), 4)
        self.assertEqual(provider.held, [(0x0E, False)])

    def test_up_of_a_key_that_is_not_held_sends_nothing(self):
        provider, send, _ = make()
        provider.handle(key(0x10, down=False))
        self.assertEqual(send.calls, [])

    def test_blocked_injection_is_logged_once_per_streak_and_the_key_is_not_held(self):
        provider, send, logs = make()
        send.result = 0  # UIPI: an elevated window in front
        for _ in range(3):
            self.assertIsNone(provider.handle(key(0x10)))
        self.assertEqual(len(logs), 1)
        self.assertEqual(provider.held, [])
        send.result = None
        provider.handle(key(0x10))
        self.assertEqual(provider.held, [(0x10, False)])
        send.result = 0
        provider.handle(key(0x11))
        self.assertEqual(len(logs), 2)  # a new streak is logged again

    def test_a_failed_up_still_forgets_the_key(self):
        provider, send, _ = make()
        provider.handle(key(0x10))
        send.result = 0
        provider.handle(key(0x10, down=False))
        self.assertEqual(provider.held, [])

    def test_send_input_that_raises_does_not_propagate(self):
        def boom(count, events, size):
            raise OSError("no user32")
        provider = KeyboardProvider(send_input=boom, log=lambda _l: None, layout_reader=lambda: 0)
        self.assertIsNone(provider.handle(key(0x10)))
        self.assertEqual(provider.held, [])


class ReleaseTest(unittest.TestCase):
    def hold(self, provider, *pairs):
        for sc, ext in pairs:
            provider.handle(key(sc, ext))

    def test_release_lifts_every_held_key_in_reverse_order(self):
        provider, send, _ = make()
        self.hold(provider, (0x1D, False), (0x38, False), (0x53, True))  # Ctrl, Alt, Suppr
        send.calls.clear()
        self.assertIsNone(provider.handle({"id": "keyboard.release"}))
        self.assertEqual(send.events, [(0, 0x53, SC | EXT | UP), (0, 0x38, SC | UP), (0, 0x1D, SC | UP)])
        self.assertEqual(provider.held, [])

    def test_release_with_nothing_held_sends_nothing(self):
        provider, send, _ = make()
        provider.handle({"id": "keyboard.release"})
        self.assertEqual(send.calls, [])

    def test_stop_releases_everything_in_reverse_order(self):
        provider, send, _ = make()
        self.hold(provider, (0x2A, False), (0x10, False))
        send.calls.clear()
        provider.stop()
        self.assertEqual(send.events, [(0, 0x10, SC | UP), (0, 0x2A, SC | UP)])
        self.assertEqual(provider.held, [])

    def test_stop_twice_and_stop_with_nothing_held(self):
        provider, send, _ = make()
        provider.stop()
        provider.stop()
        self.assertEqual(send.calls, [])
        provider, send, _ = make()
        self.hold(provider, (0x10, False))
        provider.stop()
        provider.stop()
        self.assertEqual(len(send.events), 1 + 1)  # the key down, then one release

    def test_keys_after_stop_are_ignored(self):
        provider, send, _ = make()
        provider.stop()
        provider.handle(key(0x10))
        self.assertEqual(send.calls, [])
        self.assertEqual(provider.held, [])

    def test_a_key_released_then_pressed_again_is_last_in_order(self):
        provider, send, _ = make()
        self.hold(provider, (0x1D, False), (0x38, False))
        provider.handle(key(0x1D, False, down=False))
        provider.handle(key(0x1D, False))
        send.calls.clear()
        provider.stop()
        self.assertEqual([e[1] for e in send.events], [0x1D, 0x38])

    def test_release_clears_the_held_keys_even_if_the_injection_fails(self):
        provider, send, _ = make()
        self.hold(provider, (0x10, False))
        send.result = 0
        provider.stop()
        self.assertEqual(provider.held, [])

    def test_stop_never_raises(self):
        def boom(count, events, size):
            raise OSError("gone")
        provider, send, _ = make()
        self.hold(provider, (0x10, False))
        provider._send_input = boom
        provider.stop()
        self.assertEqual(provider.held, [])


class LayoutTest(unittest.TestCase):
    def test_french_layouts_are_azerty_except_canadian(self):
        cases = {0x040C: "azerty", 0x080C: "azerty", 0x0C0C: "qwerty", 0x0409: "qwerty", 0x0809: "qwerty",
                 0x0407: "qwerty", 0x100C: "azerty", 0x0000: "qwerty"}
        for langid, layout in cases.items():
            with self.subTest(hex(langid)):
                self.assertEqual(layout_of_hkl(langid), layout)
                self.assertEqual(layout_of_hkl(0x04120000 | langid), layout)  # the HKL carries the device in its high word
                self.assertEqual(layout_of_hkl((0xF0010000 | langid) - (1 << 32)), layout)  # signed

    def test_snapshot_reads_the_layout_of_the_foreground_window(self):
        values = [0x040C040C, 0x04090409]
        provider, _, _ = make(layout_reader=lambda: values[0])
        self.assertEqual(provider.snapshot(), {"available": True, "layout": "azerty"})
        provider._layout_reader = lambda: values[1]
        self.assertEqual(provider.snapshot(), {"available": True, "layout": "qwerty"})

    def test_a_layout_that_cannot_be_read_is_qwerty_and_logged_once(self):
        def boom():
            raise OSError("no window")
        provider, _, logs = make(layout_reader=boom)
        for _ in range(3):
            self.assertEqual(provider.snapshot(), {"available": True, "layout": "qwerty"})
        self.assertEqual(len(logs), 1)

    def test_default_layout_reader_is_read_only(self):
        provider = KeyboardProvider(send_input=FakeSendInput(), log=lambda _l: None)  # the real GetKeyboardLayout
        snap = provider.snapshot()
        self.assertTrue(snap["available"])
        self.assertIn(snap["layout"], ("azerty", "qwerty"))


class ThreadSafetyTest(unittest.TestCase):
    def test_concurrent_keys_and_stop_leave_nothing_held(self):
        provider, send, _ = make()

        def press(sc):
            for _ in range(50):
                provider.handle(key(sc))

        threads = [threading.Thread(target=press, args=(sc,)) for sc in (0x10, 0x11, 0x12)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        provider.stop()
        self.assertEqual(provider.held, [])
        downs = [e for e in send.events if not e[2] & UP]
        ups = [e for e in send.events if e[2] & UP]
        self.assertEqual(len(downs), 150)
        self.assertEqual(sorted(e[1] for e in ups), [0x10, 0x11, 0x12])


if __name__ == "__main__":
    unittest.main()
