import ctypes
import math
import threading
import unittest

from actions import keys, trackpad
from actions.trackpad import TrackpadProvider

MOVE, LDOWN, LUP, RDOWN, RUP, WHEEL, HWHEEL = 0x0001, 0x0002, 0x0004, 0x0008, 0x0010, 0x0800, 0x1000


class FakeSendInput:
    """Records every SendInput call as a list of events: ("mouse", dx, dy, signed mouseData, flags) or
    ("key", vk, flags). `result` overrides the injected count (None: all of them)."""

    def __init__(self):
        self.calls = []
        self.result = None

    def __call__(self, count, events, size):
        assert size == ctypes.sizeof(keys.INPUT)
        call = []
        for e in events:
            if e.type == trackpad.INPUT_MOUSE:
                data = e.u.mi.mouseData
                call.append(("mouse", e.u.mi.dx, e.u.mi.dy, data - (1 << 32) if data >= 1 << 31 else data,
                             e.u.mi.dwFlags))
            else:
                assert e.type == keys.INPUT_KEYBOARD
                call.append(("key", e.u.ki.wVk, e.u.ki.dwFlags))
        self.calls.append(call)
        return count if self.result is None else self.result

    @property
    def events(self):
        return [e for call in self.calls for e in call]

    def clear(self):
        self.calls.clear()


def make(**kw):
    send = FakeSendInput()
    logs = []
    return TrackpadProvider(send_input=send, log=logs.append, **kw), send, logs


def act(_kind, **fields):
    return dict(id="trackpad." + _kind, **fields)


class MoveTest(unittest.TestCase):
    def test_relative_move_without_the_absolute_flag(self):
        p, send, _ = make()
        self.assertIsNone(p.handle(act("move", dx=5, dy=-3)))
        self.assertEqual(send.calls, [[("mouse", 5, -3, 0, MOVE)]])
        self.assertEqual(MOVE & 0x8000, 0)  # MOUSEEVENTF_ABSOLUTE is never set

    def test_decimals_are_carried_and_only_whole_pixels_sent(self):
        p, send, _ = make()
        for _ in range(4):
            p.handle(act("move", dx=0.6, dy=0.0))
        # 0.6, 1.2, 1.8, 2.4 -> 0, 1, 1 (carry .8 -> 1.8: +1), ... the total sent is the integer part of the sum
        sent = sum(e[1] for e in send.events)
        self.assertEqual(sent, 2)
        self.assertEqual(len(send.events), 2)  # the calls that moved nothing are not sent

    def test_nothing_is_sent_for_less_than_a_pixel(self):
        p, send, _ = make()
        p.handle(act("move", dx=0.4, dy=-0.4))
        self.assertEqual(send.calls, [])

    def test_negative_decimals_carry_toward_zero(self):
        p, send, _ = make()
        for _ in range(5):
            p.handle(act("move", dx=-0.5, dy=0.25))
        self.assertEqual(sum(e[1] for e in send.events), -2)   # -2.5 total: -2 sent, -0.5 carried
        self.assertEqual(sum(e[2] for e in send.events), 1)    # 1.25 total: 1 sent

    def test_axes_carry_separately(self):
        p, send, _ = make()
        p.handle(act("move", dx=0.9, dy=2.0))
        p.handle(act("move", dx=0.2, dy=0.0))
        self.assertEqual(send.events, [("mouse", 0, 2, 0, MOVE), ("mouse", 1, 0, 0, MOVE)])

    def test_large_moves_are_clamped(self):
        p, send, _ = make()
        p.handle(act("move", dx=99999, dy=-99999))
        self.assertEqual(send.events, [("mouse", 2000, -2000, 0, MOVE)])
        send.clear()
        p.handle(act("move", dx=2000, dy=-2000))
        self.assertEqual(send.events, [("mouse", 2000, -2000, 0, MOVE)])

    def test_integers_and_floats_are_both_accepted(self):
        p, send, _ = make()
        p.handle(act("move", dx=3, dy=4.0))
        self.assertEqual(send.events, [("mouse", 3, 4, 0, MOVE)])


class ButtonTest(unittest.TestCase):
    def test_left_and_right_down_up(self):
        p, send, _ = make()
        p.handle(act("button", button="left", down=True))
        p.handle(act("button", button="left", down=False))
        p.handle(act("button", button="right", down=True))
        p.handle(act("button", button="right", down=False))
        self.assertEqual(send.events, [("mouse", 0, 0, 0, LDOWN), ("mouse", 0, 0, 0, LUP),
                                       ("mouse", 0, 0, 0, RDOWN), ("mouse", 0, 0, 0, RUP)])

    def test_held_buttons_are_tracked(self):
        p, _, _ = make()
        p.handle(act("button", button="left", down=True))
        p.handle(act("button", button="right", down=True))
        self.assertEqual(p.held, ["left", "right"])
        p.handle(act("button", button="left", down=False))
        self.assertEqual(p.held, ["right"])

    def test_up_of_a_button_that_is_not_held_is_ignored(self):
        p, send, _ = make()
        p.handle(act("button", button="left", down=False))
        self.assertEqual(send.calls, [])

    def test_a_second_down_of_a_held_button_is_not_sent_again(self):
        p, send, _ = make()
        p.handle(act("button", button="left", down=True))
        p.handle(act("button", button="left", down=True))
        self.assertEqual(len(send.events), 1)

    def test_blocked_injection_does_not_hold_the_button(self):
        p, send, logs = make()
        send.result = 0
        p.handle(act("button", button="left", down=True))
        self.assertEqual(p.held, [])
        self.assertEqual(len(logs), 1)

    def test_release_and_stop_lift_the_held_buttons_last_pressed_first(self):
        p, send, _ = make()
        p.handle(act("button", button="left", down=True))
        p.handle(act("button", button="right", down=True))
        send.clear()
        self.assertIsNone(p.handle(act("release")))
        self.assertEqual(send.events, [("mouse", 0, 0, 0, RUP), ("mouse", 0, 0, 0, LUP)])
        self.assertEqual(p.held, [])
        p.handle(act("button", button="left", down=True))
        send.clear()
        p.stop()
        p.stop()
        self.assertEqual(send.events, [("mouse", 0, 0, 0, LUP)])

    def test_release_with_nothing_held_sends_nothing(self):
        p, send, _ = make()
        p.handle(act("release"))
        p.stop()
        self.assertEqual(send.calls, [])

    def test_nothing_is_injected_after_stop(self):
        p, send, _ = make()
        p.stop()
        for a in (act("move", dx=5, dy=5), act("button", button="left", down=True), act("scroll", dx=0, dy=40),
                  act("zoom", steps=1), act("gesture", name="desktop")):
            p.handle(a)
        self.assertEqual(send.calls, [])


class ScrollTest(unittest.TestCase):
    """Windows: a positive WHEEL is a wheel turned forward, away from the user = scroll UP (the content slides
    down); a positive HWHEEL is a tilt to the right = scroll RIGHT (the content slides left). `trackpad.scroll`
    carries the fingers' movement in dp (x to the right, y downwards, like `move`). Natural scrolling = the content
    follows the fingers: fingers down -> content down -> scroll up -> WHEEL > 0; fingers to the right -> content to the
    right -> scroll left -> HWHEEL < 0. 1 dp = 4 wheel units (120 = one notch)."""

    def test_fingers_down_scroll_up_content_follows_the_fingers(self):
        p, send, _ = make()
        p.handle(act("scroll", dx=0, dy=30))
        self.assertEqual(send.events, [("mouse", 0, 0, 120, WHEEL)])

    def test_fingers_up_scroll_down(self):
        p, send, _ = make()
        p.handle(act("scroll", dx=0, dy=-30))
        self.assertEqual(send.events, [("mouse", 0, 0, -120, WHEEL)])

    def test_fingers_right_scroll_left_fingers_left_scroll_right(self):
        p, send, _ = make()
        p.handle(act("scroll", dx=10, dy=0))
        p.handle(act("scroll", dx=-10, dy=0))
        self.assertEqual(send.events, [("mouse", 0, 0, -40, HWHEEL), ("mouse", 0, 0, 40, HWHEEL)])

    def test_the_wheel_constants_are_windows_values(self):
        self.assertEqual((trackpad.MOUSEEVENTF_WHEEL, trackpad.MOUSEEVENTF_HWHEEL), (WHEEL, HWHEEL))
        self.assertEqual(trackpad.UNITS_PER_DP, 4)

    def test_both_axes_in_one_call(self):
        p, send, _ = make()
        p.handle(act("scroll", dx=5, dy=10))
        self.assertEqual(send.calls, [[("mouse", 0, 0, 40, WHEEL), ("mouse", 0, 0, -20, HWHEEL)]])

    def test_zero_sends_nothing(self):
        p, send, _ = make()
        p.handle(act("scroll", dx=0, dy=0))
        p.handle(act("scroll", dx=0.1, dy=-0.1))  # 0.4 units: below one
        self.assertEqual(send.calls, [])

    def test_remainders_are_carried(self):
        p, send, _ = make()
        for _ in range(10):
            p.handle(act("scroll", dx=0, dy=0.3))  # 1.2 units each
        total = sum(e[3] for e in send.events if e[4] == WHEEL)
        self.assertEqual(total, 12)  # 10 x 1.2, nothing lost
        send.clear()
        for _ in range(10):
            p.handle(act("scroll", dx=0.3, dy=0))
        self.assertEqual(sum(e[3] for e in send.events if e[4] == HWHEEL), -12)

    def test_negative_remainders_too(self):
        p, send, _ = make()
        for _ in range(10):
            p.handle(act("scroll", dx=0, dy=-0.3))
        self.assertEqual(sum(e[3] for e in send.events), -12)

    def test_large_scrolls_are_clamped(self):
        p, send, _ = make()
        p.handle(act("scroll", dx=0, dy=1e9))
        self.assertEqual(send.events, [("mouse", 0, 0, 8000, WHEEL)])


class ZoomTest(unittest.TestCase):
    def test_ctrl_down_wheel_ctrl_up_in_one_call(self):
        p, send, _ = make()
        p.handle(act("zoom", steps=2))
        self.assertEqual(send.calls, [[("key", keys.VK_CONTROL, 0), ("mouse", 0, 0, 120, WHEEL),
                                       ("mouse", 0, 0, 120, WHEEL), ("key", keys.VK_CONTROL, keys.KEYEVENTF_KEYUP)]])

    def test_negative_steps_zoom_out(self):
        p, send, _ = make()
        p.handle(act("zoom", steps=-3))
        wheels = [e[3] for e in send.events if e[0] == "mouse"]
        self.assertEqual(wheels, [-120, -120, -120])
        self.assertEqual(send.events[0][:2], ("key", keys.VK_CONTROL))
        self.assertEqual(send.events[-1], ("key", keys.VK_CONTROL, keys.KEYEVENTF_KEYUP))

    def test_steps_are_clamped_to_ten(self):
        p, send, _ = make()
        p.handle(act("zoom", steps=99))
        self.assertEqual(len([e for e in send.events if e[0] == "mouse"]), 10)
        send.clear()
        p.handle(act("zoom", steps=-99))
        self.assertEqual(len([e for e in send.events if e[0] == "mouse"]), 10)

    def test_zero_steps_send_nothing(self):
        p, send, _ = make()
        p.handle(act("zoom", steps=0))
        self.assertEqual(send.calls, [])

    def test_ctrl_is_released_even_if_the_injection_is_partial(self):
        p, send, logs = make()
        send.result = 1
        p.handle(act("zoom", steps=1))
        self.assertEqual(len(send.calls), 2)  # a second call lifts Ctrl
        self.assertEqual(send.calls[1], [("key", keys.VK_CONTROL, keys.KEYEVENTF_KEYUP)])


class GestureTest(unittest.TestCase):
    def test_the_four_gestures_and_their_shortcuts(self):
        cases = {"task_view": "Win+Tab", "desktop": "Win+D", "app_prev": "Alt+Shift+Tab", "app_next": "Alt+Tab"}
        for name, shortcut in cases.items():
            with self.subTest(name):
                p, send, _ = make()
                self.assertIsNone(p.handle(act("gesture", name=name)))
                expected = [(vk, f) for vk, f in keys.parse_shortcut(shortcut)]
                self.assertEqual(send.calls, [[("key", vk, f) for vk, f in expected]])

    def test_modifier_order_of_the_shortcuts(self):
        p, send, _ = make()
        p.handle(act("gesture", name="app_prev"))
        down = [e[1] for e in send.events if not e[2] & keys.KEYEVENTF_KEYUP]
        self.assertEqual(down, [keys.VK_MENU, keys.VK_SHIFT, 0x09])  # Alt, Shift, Tab

    def test_a_blocked_gesture_is_logged(self):
        p, send, logs = make()
        send.result = 0
        p.handle(act("gesture", name="desktop"))
        self.assertEqual(len(logs), 1)


class ValidationTest(unittest.TestCase):
    def test_bad_numbers_are_refused_and_logged(self):
        bad = [math.nan, math.inf, -math.inf, "5", None, True, False, [1], {"a": 1}]
        for value in bad:
            for name in ("move", "scroll"):
                with self.subTest(name=name, value=value):
                    p, send, logs = make()
                    self.assertIsNone(p.handle(act(name, dx=value, dy=1)))
                    self.assertIsNone(p.handle(act(name, dx=1, dy=value)))
                    self.assertEqual(send.calls, [])
                    self.assertEqual(len(logs), 2)

    def test_missing_fields_are_refused(self):
        for a in (act("move"), act("move", dx=1), act("scroll", dy=1), act("zoom"), act("button"),
                  act("button", button="left"), act("button", down=True), act("gesture")):
            with self.subTest(a):
                p, send, logs = make()
                self.assertIsNone(p.handle(a))
                self.assertEqual(send.calls, [])
                self.assertEqual(len(logs), 1)

    def test_bad_steps(self):
        for steps in (1.5, "2", None, True, math.nan, [1]):
            with self.subTest(steps):
                p, send, logs = make()
                p.handle(act("zoom", steps=steps))
                self.assertEqual(send.calls, [])
                self.assertEqual(len(logs), 1)

    def test_unknown_button_and_gesture_names(self):
        p, send, logs = make()
        for a in (act("button", button="middle", down=True), act("button", button=1, down=True),
                  act("button", button="left", down=1), act("gesture", name="four_fingers"),
                  act("gesture", name=None), act("gesture", name=["desktop"])):
            p.handle(a)
        self.assertEqual(send.calls, [])
        self.assertEqual(len(logs), 6)

    def test_unknown_action_id(self):
        p, send, logs = make()
        self.assertIsNone(p.handle({"id": "trackpad.nope"}))
        self.assertEqual(len(logs), 1)
        self.assertEqual(send.calls, [])

    def test_send_input_that_raises_does_not_propagate(self):
        def boom(count, events, size):
            raise OSError("no user32")
        p = TrackpadProvider(send_input=boom, log=lambda _l: None)
        for a in (act("move", dx=5, dy=5), act("button", button="left", down=True), act("scroll", dx=0, dy=40),
                  act("zoom", steps=1), act("release")):
            self.assertIsNone(p.handle(a))
        self.assertEqual(p.held, [])


class SnapshotTest(unittest.TestCase):
    def test_snapshot_is_available(self):
        p, _, _ = make()
        self.assertEqual(p.snapshot(), {"available": True})

    def test_thread_safety(self):
        p, send, _ = make()

        def press():
            for _ in range(50):
                p.handle(act("button", button="left", down=True))
                p.handle(act("button", button="left", down=False))

        threads = [threading.Thread(target=press) for _ in range(3)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        p.stop()
        self.assertEqual(p.held, [])
        downs = [e for e in send.events if e[4] == LDOWN]
        ups = [e for e in send.events if e[4] == LUP]
        self.assertEqual(len(downs), len(ups))


if __name__ == "__main__":
    unittest.main()
