import inspect
import threading
import unittest

import display_layout as dl
import engine
import virtual_display as vd
from display_layout import MonitorKey, MonitorPath, Rect

PRIMARY = Rect(0, 0, 2560, 1600)
VDD_KEY = MonitorKey(0x7E6D58, 0, 256)
TABLET = (2880, 1800, 274)
COMMON_MODES = [(2880, 1800), (2560, 1600), (1920, 1200), (1920, 1080), (1280, 800)]


class FakeVdd:
    def __init__(self, installed=True):
        self.installed = installed

    def is_installed(self):
        return self.installed


class FakeLayout:
    """display_layout stand-in: one VDD monitor whose path the code switches on and off.

    The pure helpers are the real ones; every Windows call is recorded in ``calls``.
    """

    Rect = dl.Rect
    DisplayLayoutError = dl.DisplayLayoutError
    pick_mode = staticmethod(dl.pick_mode)
    place = staticmethod(dl.place)
    auto_scale = staticmethod(dl.auto_scale)

    def __init__(self, modes=COMMON_MODES, active_rect=None, present=True):
        self.modes = list(modes)
        self.present = present
        self.rect = active_rect            # None = chemin inactif
        self.calls = []
        self.fail = {}                     # nom de méthode -> exception à lever
        self.reject_one_step = False       # SetDisplayConfig refuse l'activation avec un mode fourni
        self.find_failures = 0             # nombre d'appels find_vdd_monitor qui renvoient None
        self.scale = 100                   # échelle Windows courante (gardée par Windows, allumé ou non)
        self.path_positions = []           # position passée à chaque set_path_active (None = non fournie)

    def _maybe_fail(self, name):
        if name in self.fail:
            raise self.fail[name]

    def find_vdd_monitor(self):
        self.calls.append(("find",))
        self._maybe_fail("find_vdd_monitor")
        if not self.present:
            return None
        if self.find_failures:
            self.find_failures -= 1
            return None
        return MonitorPath(key=VDD_KEY, source_adapter=(VDD_KEY.adapter_low, 0), source_id=0,
                           gdi_name=r"\\.\DISPLAY9", name="VDD by MTT", device_path=r"\\?\DISPLAY#MTT1337#x",
                           active=self.rect is not None, target_available=True, rect=self.rect,
                           is_primary=False)

    def available_modes(self, key):
        self.calls.append(("modes", key))
        self._maybe_fail("available_modes")
        return list(self.modes)

    def set_path_active(self, key, active, mode=None, position=None, api=None):
        self.calls.append(("path", key, active, mode))
        self.path_positions.append(position)
        self._maybe_fail("set_path_active")
        if not active:
            changed = self.rect is not None
            self.rect = None
            return changed
        if self.rect is None:
            if mode is not None and self.reject_one_step:
                raise dl.DisplayLayoutError("SetDisplayConfig failed (Win32 error 87)", 87)
            size = mode or (1920, 1080)    # mode mémorisé par Windows
            self.rect = Rect(*(position or (PRIMARY.width, 0)), *size)
            return True
        if mode is None:
            return False
        left, top = position or (self.rect.left, self.rect.top)
        self.rect = Rect(left, top, *mode)
        return True

    def set_position(self, key, x, y, api=None):
        self.calls.append(("position", key, x, y))
        self._maybe_fail("set_position")
        self.rect = Rect(x, y, self.rect.width, self.rect.height)

    def get_scale(self, key, api=None):
        self.calls.append(("get_scale", key))
        self._maybe_fail("get_scale")
        return self.scale, 200

    def set_scale(self, key, percent, api=None):
        self.calls.append(("scale", key, percent))
        self._maybe_fail("set_scale")
        self.scale = percent
        return percent

    def path_calls(self):
        return [c for c in self.calls if c[0] == "path"]

    def layout_calls(self):
        return [c for c in self.calls if c[0] in ("position", "scale")]


class FakeMonitors:
    """injector.monitors() stand-in: the VDD monitor shows up ``delay_polls`` polls after activation."""

    def __init__(self, layout, delay_polls=0, others=()):
        self.layout = layout
        self.delay_polls = delay_polls
        self.others = list(others)
        self.polls = 0

    def __call__(self):
        self.polls += 1
        found = [(PRIMARY, True, r"\\.\DISPLAY1"), *self.others]
        if self.layout.rect is not None:
            if self.delay_polls > 0:
                self.delay_polls -= 1
            else:
                found.append((self.layout.rect, False, r"\\.\DISPLAY9"))
        return found


class FakeClock:
    def __init__(self):
        self.now = 100.0
        self.sleeps = []

    def __call__(self):
        return self.now

    def sleep(self, seconds):
        self.sleeps.append(seconds)
        self.now += seconds


class FakeTimer:
    def __init__(self, interval, function):
        self.interval = interval
        self.function = function
        self.started = False
        self.cancelled = False

    def start(self):
        self.started = True

    def cancel(self):
        self.cancelled = True

    def fire(self):
        """What threading.Timer does when the delay ends, cancelled or not (the race the code must handle)."""
        self.function()


class Harness:
    def __init__(self, layout=None, vdd=None, delay_polls=0, others=()):
        self.layout = layout or FakeLayout()
        self.vdd = vdd or FakeVdd()
        self.monitors = FakeMonitors(self.layout, delay_polls, others)
        self.clock = FakeClock()
        self.timers = []
        self.logs = []
        self.display = vd.VirtualDisplay(
            self.vdd, layout=self.layout, monitors=self.monitors, clock=self.clock, sleep=self.clock.sleep,
            timer_factory=self.make_timer, appear_timeout_s=10.0, log=self.logs.append)   # grace_s : le défaut

    def make_timer(self, interval, function):
        timer = FakeTimer(interval, function)
        self.timers.append(timer)
        return timer

    def prepare(self, width=TABLET[0], height=TABLET[1], dpi=TABLET[2], position="right", scale="auto",
                first_time=False, should_stop=lambda: False):
        return self.display.prepare(width, height, dpi, position, scale, first_time, should_stop)


class PrepareTest(unittest.TestCase):
    def test_activates_the_path_with_the_exact_mode_and_returns_the_monitor(self):
        h = Harness(delay_polls=3)
        result = h.prepare()
        self.assertEqual(h.layout.path_calls(), [("path", VDD_KEY, True, (2880, 1800))])
        self.assertEqual(result, vd.PrepareResult(Rect(2560, -100, 2880, 1800), True, (2880, 1800)))
        self.assertEqual(h.clock.sleeps, [0.2, 0.2, 0.2])   # interrogé toutes les 200 ms

    def test_nearest_mode_of_the_same_shape_is_not_exact(self):
        h = Harness(FakeLayout(modes=[(2560, 1600), (1920, 1200), (1920, 1080)]))
        result = h.prepare()
        self.assertEqual(result.mode, (2560, 1600))
        self.assertFalse(result.exact)
        self.assertEqual(result.rect, Rect(2560, 0, 2560, 1600))
        self.assertEqual(h.layout.path_calls(), [("path", VDD_KEY, True, (2560, 1600))])

    def test_timeout_raises_display_timeout(self):
        h = Harness(delay_polls=1000)
        with self.assertRaises(engine.FatalError) as caught:
            h.prepare()
        self.assertEqual(caught.exception.msg.key, "display.timeout")
        self.assertGreaterEqual(h.clock.now - 100.0, 10.0)
        self.assertLess(h.clock.now - 100.0, 10.5)

    def test_should_stop_aborts_the_wait_and_returns_none(self):
        h = Harness(delay_polls=1000)
        polls = []

        def should_stop():
            polls.append(1)
            return len(polls) > 3

        self.assertIsNone(h.prepare(should_stop=should_stop))
        self.assertLess(h.clock.now - 100.0, 1.0)

    def test_should_stop_before_activation_changes_nothing(self):
        h = Harness()
        self.assertIsNone(h.prepare(should_stop=lambda: True))
        self.assertEqual(h.layout.path_calls(), [])

    def test_missing_driver_raises_vdd_missing(self):
        h = Harness(vdd=FakeVdd(installed=False))
        with self.assertRaises(engine.FatalError) as caught:
            h.prepare()
        self.assertEqual(caught.exception.msg.key, "display.vdd_missing")
        self.assertEqual(h.layout.path_calls(), [])

    def test_monitor_not_listed_yet_is_waited_for(self):
        h = Harness()
        h.layout.find_failures = 2   # p. ex. juste après un redémarrage du périphérique
        result = h.prepare()
        self.assertEqual(result.mode, (2880, 1800))
        self.assertEqual(h.clock.sleeps[:2], [0.2, 0.2])

    def test_monitor_never_listed_times_out(self):
        h = Harness(FakeLayout(present=False))
        with self.assertRaises(engine.FatalError) as caught:
            h.prepare()
        self.assertEqual(caught.exception.msg.key, "display.timeout")

    def test_no_fitting_mode_raises_display_no_mode_with_the_tablet_size(self):
        h = Harness(FakeLayout(modes=[(3840, 2160)]))
        with self.assertRaises(engine.FatalError) as caught:
            h.prepare(width=1280, height=800)
        self.assertEqual(caught.exception.msg.key, "display.no_mode")
        self.assertEqual(dict(caught.exception.msg.args), {"width": 1280, "height": 800})
        self.assertIn("1280", str(caught.exception))
        self.assertEqual(h.layout.path_calls(), [])

    def test_one_step_activation_rejected_falls_back_to_activate_then_set_mode(self):
        layout = FakeLayout()
        layout.reject_one_step = True
        h = Harness(layout)
        result = h.prepare()
        self.assertEqual(layout.path_calls(), [("path", VDD_KEY, True, (2880, 1800)),
                                               ("path", VDD_KEY, True, None),
                                               ("path", VDD_KEY, True, (2880, 1800))])
        self.assertEqual(result.rect, Rect(2560, -100, 2880, 1800))
        self.assertTrue(any("87" in line for line in h.logs))

    def test_activation_failing_twice_is_fatal(self):
        layout = FakeLayout()
        layout.fail["set_path_active"] = dl.DisplayLayoutError("SetDisplayConfig failed (Win32 error 31)", 31)
        h = Harness(layout)
        with self.assertRaises(engine.FatalError) as caught:
            h.prepare()
        self.assertEqual(caught.exception.msg.key, "display.activate_failed")
        self.assertIn("31", str(caught.exception))

    def test_active_path_of_another_size_is_resized_in_place(self):
        h = Harness(FakeLayout(active_rect=Rect(2560, 0, 1920, 1080)))
        result = h.prepare()
        self.assertEqual(h.layout.path_calls(), [("path", VDD_KEY, True, (2880, 1800))])
        self.assertEqual(result.rect, Rect(2560, -100, 2880, 1800))

    def test_active_path_of_the_right_size_is_left_alone(self):
        h = Harness(FakeLayout(active_rect=Rect(-2880, 0, 2880, 1800)))
        result = h.prepare()
        self.assertEqual(h.layout.path_calls(), [])
        self.assertEqual(result.rect, Rect(-2880, 0, 2880, 1800))

    def test_another_monitor_of_the_same_size_is_not_mistaken_for_the_tablet(self):
        twin = (Rect(-2880, 0, 2880, 1800), False, r"\\.\DISPLAY2")
        h = Harness(others=[twin])
        result = h.prepare()
        self.assertEqual(result.rect, Rect(2560, -100, 2880, 1800))

    def test_modes_unreadable_on_an_inactive_path_are_read_after_activating_it(self):
        layout = FakeLayout()
        original = layout.available_modes

        def modes_only_when_active(key):
            if layout.rect is None:
                raise dl.DisplayLayoutError("No GDI device name")
            return original(key)

        layout.available_modes = modes_only_when_active
        h = Harness(layout)
        result = h.prepare()
        self.assertEqual(layout.path_calls(), [("path", VDD_KEY, True, None),
                                               ("path", VDD_KEY, True, (2880, 1800))])
        self.assertTrue(result.exact)


class FirstTimeLayoutTest(unittest.TestCase):
    def test_first_time_places_and_scales(self):
        h = Harness()
        result = h.prepare(position="left", scale="auto", first_time=True)
        # La position est donnée à l'allumage même : plus d'appel set_position séparé.
        self.assertEqual(h.layout.path_positions, [(-2880, -100)])
        self.assertEqual(h.layout.layout_calls(), [("scale", VDD_KEY, 200)])
        self.assertEqual(result.rect, Rect(-2880, -100, 2880, 1800))

    def test_fixed_scale_is_used_as_is(self):
        h = Harness()
        h.prepare(scale="150", first_time=True)
        self.assertIn(("scale", VDD_KEY, 150), h.layout.calls)

    def test_later_prepares_do_not_touch_position_or_scale(self):
        h = Harness()
        h.prepare(first_time=True)
        h.display.release(immediate=True)
        h.layout.calls.clear()
        h.prepare(first_time=False)
        self.assertEqual(h.layout.layout_calls(), [])
        self.assertEqual(h.layout.path_calls(), [("path", VDD_KEY, True, (2880, 1800))])

    def test_layout_failures_are_logged_not_fatal(self):
        # Écran resté allumé (grâce) ailleurs qu'à la position réglée : seul cas où set_position sert encore.
        layout = FakeLayout(active_rect=Rect(-2880, 0, 2880, 1800))
        layout.fail["set_position"] = dl.DisplayLayoutError("SetDisplayConfig failed (Win32 error 5)", 5)
        layout.fail["set_scale"] = dl.DisplayLayoutError("DPI scale failed (Win32 error 1)", 1)
        h = Harness(layout)
        result = h.prepare(first_time=True)
        self.assertEqual(result.rect, Rect(-2880, 0, 2880, 1800))
        self.assertTrue(any("error 5" in line for line in h.logs))
        self.assertTrue(any("error 1" in line for line in h.logs))

    def test_bad_scale_setting_is_logged_and_position_still_applied(self):
        h = Harness()
        h.prepare(scale="huge", first_time=True)
        self.assertEqual(h.layout.path_positions, [(2560, -100)])
        self.assertEqual(h.layout.layout_calls(), [])
        self.assertTrue(any("huge" in line for line in h.logs))


class ActivationLayoutTest(unittest.TestCase):
    """Every activation puts the screen at the configured position and scale, not where Windows remembers."""

    LEFT = (-2880, -100)

    def test_activation_after_a_left_setting_lands_on_the_left_even_without_first_time(self):
        # Constat réel : Position=Gauche appliquée, écran éteint par la grâce, rallumé -> il revenait à droite.
        h = Harness()
        h.prepare(position="left", first_time=True)
        h.display.release(immediate=True)
        h.layout.calls.clear()
        h.layout.path_positions.clear()
        result = h.prepare(position="left", first_time=False)
        self.assertEqual(h.layout.path_calls(), [("path", VDD_KEY, True, (2880, 1800))])
        self.assertEqual(h.layout.path_positions, [self.LEFT])
        self.assertEqual(result.rect, Rect(*self.LEFT, 2880, 1800))
        self.assertEqual([c for c in h.layout.calls if c[0] == "position"], [])   # déjà placé à l'allumage

    def test_each_side_is_computed_with_place_against_the_primary(self):
        for side, expected in (("right", (2560, -100)), ("left", (-2880, -100)),
                               ("above", (-160, -1800)), ("below", (-160, 1600))):
            with self.subTest(side=side):
                h = Harness()
                result = h.prepare(position=side)
                self.assertEqual(h.layout.path_positions, [expected])
                self.assertEqual(result.rect, Rect(*expected, 2880, 1800))

    def test_activation_goes_past_a_second_monitor_on_that_side(self):
        side = (Rect(2560, -200, 1920, 1080), False, r"\.\DISPLAY2")
        h = Harness(others=[side])
        h.prepare(position="right")
        self.assertEqual(h.layout.path_positions, [(4480, -100)])

    def test_two_step_fallback_places_the_screen_with_the_mode_step(self):
        layout = FakeLayout()
        layout.reject_one_step = True
        h = Harness(layout)
        result = h.prepare(position="left")
        self.assertEqual(layout.path_calls(), [("path", VDD_KEY, True, (2880, 1800)),
                                               ("path", VDD_KEY, True, None),
                                               ("path", VDD_KEY, True, (2880, 1800))])
        self.assertEqual(layout.path_positions, [self.LEFT, None, self.LEFT])
        self.assertEqual(result.rect, Rect(*self.LEFT, 2880, 1800))

    def test_resizing_an_active_path_also_places_it(self):
        h = Harness(FakeLayout(active_rect=Rect(2560, 0, 1920, 1080)))
        result = h.prepare(position="left")
        self.assertEqual(h.layout.path_positions, [self.LEFT])
        self.assertEqual(result.rect, Rect(*self.LEFT, 2880, 1800))

    def test_path_turned_on_to_read_its_modes_is_placed_even_when_its_mode_already_fits(self):
        layout = FakeLayout(modes=[(1920, 1080)])   # Windows rallume au mode mémorisé : 1920x1080
        original = layout.available_modes

        def modes_only_when_active(key):
            if layout.rect is None:
                raise dl.DisplayLayoutError("No GDI device name")
            return original(key)

        layout.available_modes = modes_only_when_active
        h = Harness(layout)
        result = h.prepare(width=1920, height=1080, position="left")
        self.assertEqual(result.rect, Rect(-1920, 260, 1920, 1080))
        self.assertEqual(layout.path_positions[-1], (-1920, 260))

    def test_a_screen_kept_on_within_the_grace_delay_is_left_where_it_is(self):
        h = Harness(FakeLayout(active_rect=Rect(-2880, 0, 2880, 1800)))
        h.layout.scale = 200
        h.prepare(position="right")
        self.assertEqual(h.layout.path_calls(), [])

    def test_unknown_position_still_activates_and_is_logged(self):
        h = Harness()
        result = h.prepare(position="diagonal")
        self.assertEqual(h.layout.path_positions, [None])
        self.assertEqual(result.rect, Rect(2560, 0, 2880, 1800))
        self.assertTrue(any("diagonal" in line for line in h.logs))

    def test_scale_is_corrected_on_activation(self):
        h = Harness()
        h.layout.scale = 100   # Windows a rallumé l'écran à 100 %
        h.prepare(scale="auto")
        self.assertIn(("scale", VDD_KEY, 200), h.layout.calls)
        self.assertEqual(h.layout.scale, 200)

    def test_fixed_scale_is_corrected_on_activation(self):
        h = Harness()
        h.layout.scale = 200
        h.prepare(scale="150")
        self.assertIn(("scale", VDD_KEY, 150), h.layout.calls)

    def test_scale_already_correct_makes_no_extra_call(self):
        h = Harness()
        h.layout.scale = 200
        h.prepare(scale="auto")
        self.assertEqual(h.layout.layout_calls(), [])
        self.assertEqual(h.layout.path_calls(), [("path", VDD_KEY, True, (2880, 1800))])

    def test_scale_is_read_after_the_screen_is_on(self):
        h = Harness()
        h.prepare()
        self.assertGreater(h.layout.calls.index(("get_scale", VDD_KEY)), h.layout.calls.index(
            ("path", VDD_KEY, True, (2880, 1800))))

    def test_scale_failures_on_activation_are_logged_not_fatal(self):
        for name in ("get_scale", "set_scale"):
            with self.subTest(name=name):
                layout = FakeLayout()
                layout.fail[name] = dl.DisplayLayoutError("DPI scale failed (Win32 error 1)", 1)
                h = Harness(layout)
                result = h.prepare()
                self.assertEqual(result.rect, Rect(2560, -100, 2880, 1800))
                self.assertTrue(any("error 1" in line for line in h.logs))

    def test_bad_scale_setting_on_activation_is_logged_not_fatal(self):
        h = Harness()
        result = h.prepare(scale="huge")
        self.assertEqual(result.mode, (2880, 1800))
        self.assertTrue(any("huge" in line for line in h.logs))
        self.assertNotIn("scale", [c[0] for c in h.layout.calls])


class ReleaseTest(unittest.TestCase):
    def test_release_deactivates_after_the_grace_delay(self):
        h = Harness()
        h.prepare()
        h.display.release()
        self.assertEqual(len(h.timers), 1)
        self.assertEqual(h.timers[0].interval, 15.0)   # l'arrachage + rebranchement du câble dure ~5,5 s
        self.assertTrue(h.timers[0].started)
        self.assertEqual(h.layout.path_calls()[1:], [])   # rien avant la fin de la grâce
        h.timers[0].fire()
        self.assertEqual(h.layout.path_calls()[1:], [("path", VDD_KEY, False, None)])

    def test_prepare_within_grace_keeps_the_screen(self):
        h = Harness()
        h.prepare()
        h.display.release()
        result = h.prepare()
        self.assertTrue(h.timers[0].cancelled)
        h.timers[0].fire()   # le Timer partait déjà : il ne doit rien faire
        self.assertEqual(h.layout.path_calls(), [("path", VDD_KEY, True, (2880, 1800))])
        self.assertTrue(result.exact)

    def test_cancel_release_within_grace(self):
        h = Harness()
        h.prepare()
        h.display.release()
        h.display.cancel_release()
        h.timers[0].fire()
        self.assertTrue(h.timers[0].cancelled)
        self.assertEqual(h.layout.path_calls(), [("path", VDD_KEY, True, (2880, 1800))])

    def test_immediate_release(self):
        h = Harness()
        h.prepare()
        h.display.release(immediate=True)
        self.assertEqual(h.timers, [])
        self.assertEqual(h.layout.path_calls()[1:], [("path", VDD_KEY, False, None)])

    def test_immediate_release_replaces_a_pending_one(self):
        h = Harness()
        h.prepare()
        h.display.release()
        h.display.release(immediate=True)
        h.timers[0].fire()
        self.assertTrue(h.timers[0].cancelled)
        self.assertEqual(h.layout.path_calls()[1:], [("path", VDD_KEY, False, None)])

    def test_second_release_restarts_the_grace(self):
        h = Harness()
        h.prepare()
        h.display.release()
        h.display.release()
        self.assertTrue(h.timers[0].cancelled)
        h.timers[0].fire()
        h.timers[1].fire()
        self.assertEqual(h.layout.path_calls()[1:], [("path", VDD_KEY, False, None)])

    def test_release_errors_are_logged(self):
        h = Harness()
        h.prepare()
        h.layout.fail["set_path_active"] = dl.DisplayLayoutError("only active display")
        h.display.release(immediate=True)
        self.assertTrue(any("only active display" in line for line in h.logs))

    def test_grace_delay_defaults_to_15_seconds(self):
        self.assertEqual(vd.GRACE_S, 15.0)
        self.assertEqual(inspect.signature(vd.VirtualDisplay).parameters["grace_s"].default, vd.GRACE_S)

    def test_default_timer_is_a_daemon_thread_timer(self):
        timer = vd.daemon_timer(5.0, lambda: None)
        self.assertIsInstance(timer, threading.Timer)
        self.assertTrue(timer.daemon)


class CleanupTest(unittest.TestCase):
    def test_cleanup_deactivates_an_active_path(self):
        h = Harness(FakeLayout(active_rect=Rect(2560, 0, 2880, 1800)))
        h.display.cleanup_on_start()
        self.assertEqual(h.layout.path_calls(), [("path", VDD_KEY, False, None)])

    def test_cleanup_leaves_an_inactive_path_alone(self):
        h = Harness()
        h.display.cleanup_on_start()
        self.assertEqual(h.layout.path_calls(), [])

    def test_cleanup_tolerates_a_missing_driver(self):
        h = Harness(FakeLayout(present=False), vdd=FakeVdd(installed=False))
        h.display.cleanup_on_start()
        self.assertEqual(h.layout.path_calls(), [])

    def test_cleanup_tolerates_errors(self):
        layout = FakeLayout()
        layout.fail["find_vdd_monitor"] = dl.DisplayLayoutError("QueryDisplayConfig failed (Win32 error 5)", 5)
        h = Harness(layout)
        h.display.cleanup_on_start()
        self.assertTrue(any("error 5" in line for line in h.logs))


class ApplyLayoutTest(unittest.TestCase):
    def test_moves_and_scales_the_active_screen(self):
        h = Harness()
        h.prepare()
        h.layout.calls.clear()
        h.display.apply_layout("below", "125", 274)
        self.assertEqual(h.layout.layout_calls(), [("position", VDD_KEY, -160, 1600), ("scale", VDD_KEY, 125)])

    def test_auto_scale_uses_the_dpi(self):
        h = Harness()
        h.prepare()
        h.display.apply_layout("right", "auto", 160)
        self.assertIn(("scale", VDD_KEY, 125), h.layout.calls)

    def test_returns_where_the_screen_now_is(self):
        h = Harness()
        h.prepare()
        self.assertEqual(h.display.apply_layout("below", "125", 274), Rect(-160, 1600, 2880, 1800))

    def test_does_nothing_when_the_screen_is_off(self):
        h = Harness()
        self.assertIsNone(h.display.apply_layout("left", "auto", 274))
        self.assertEqual(h.layout.layout_calls(), [])

    def test_errors_are_logged(self):
        h = Harness()
        h.prepare()
        h.layout.fail["set_position"] = dl.DisplayLayoutError("SetDisplayConfig failed (Win32 error 5)", 5)
        h.display.apply_layout("left", "150", 274)
        self.assertIn(("scale", VDD_KEY, 150), h.layout.calls)
        self.assertTrue(any("error 5" in line for line in h.logs))

    def test_scale_only_change_never_moves_the_screen(self):
        h = Harness()
        h.prepare()
        h.layout.calls.clear()
        self.assertEqual(h.display.apply_layout("left", "150", 274, move=False), Rect(2560, -100, 2880, 1800))
        self.assertEqual(h.layout.layout_calls(), [("scale", VDD_KEY, 150)])

    def test_position_only_change_keeps_the_scale(self):
        h = Harness()
        h.prepare()
        h.layout.calls.clear()
        h.display.apply_layout("below", "150", 274, rescale=False)
        self.assertEqual(h.layout.layout_calls(), [("position", VDD_KEY, -160, 1600)])

    def test_screen_already_at_the_target_is_not_moved_again(self):
        h = Harness()
        h.prepare()
        h.display.apply_layout("right", "auto", 274)
        h.layout.calls.clear()
        self.assertEqual(h.display.apply_layout("right", "125", 274), Rect(2560, -100, 2880, 1800))
        self.assertEqual(h.layout.layout_calls(), [("scale", VDD_KEY, 125)])

    def test_placement_goes_past_a_second_monitor_on_that_side(self):
        side = (Rect(2560, -200, 1920, 1080), False, r"\\.\DISPLAY2")
        h = Harness(others=[side])
        h.prepare(position="left")
        h.layout.calls.clear()
        h.display.apply_layout("right", "auto", 274)
        self.assertEqual(h.layout.layout_calls()[0], ("position", VDD_KEY, 4480, -100))
        h.display.apply_layout("above", "auto", 274)
        self.assertEqual(h.layout.layout_calls()[2], ("position", VDD_KEY, -160, -2000))


class ContendedRLock:
    """threading.RLock that sets ``contended`` when a thread has to wait for it: tests know a thread is blocked."""

    def __init__(self):
        self._lock = threading.RLock()
        self.contended = threading.Event()

    def acquire(self, blocking=True, timeout=-1):
        if self._lock.acquire(blocking=False):
            return True
        self.contended.set()
        return self._lock.acquire(blocking, timeout)

    def release(self):
        self._lock.release()

    __enter__ = acquire

    def __exit__(self, *exc):
        self.release()
        return False


class QuitRaceTest(unittest.TestCase):
    def test_stop_arriving_while_activation_waits_for_the_lock_activates_nothing(self):
        # Quit : stop(immediate) lève le drapeau puis éteint l'écran sous le verrou, pendant que prepare,
        # déjà passé par ses vérifications, attend ce verrou pour allumer : il ne doit plus rien allumer.
        h = Harness()
        lock = ContendedRLock()
        h.display._lock = lock
        stop, picked, held = threading.Event(), threading.Event(), threading.Event()
        real_pick = h.layout.pick_mode

        def pick_mode(modes, width, height):
            picked.set()
            self.assertTrue(held.wait(5))
            return real_pick(modes, width, height)

        h.layout.pick_mode = pick_mode
        result = []
        thread = threading.Thread(target=lambda: result.append(h.prepare(should_stop=stop.is_set)))
        thread.start()
        self.assertTrue(picked.wait(5))
        with lock:   # l'extinction immédiate tient le verrou
            held.set()
            self.assertTrue(lock.contended.wait(5))   # prepare attend le verrou pour allumer
            stop.set()
        thread.join(5)
        self.assertEqual(result, [None])
        self.assertEqual(h.layout.path_calls(), [])
        self.assertTrue(any("stopped" in line for line in h.logs))


class ThreadSafetyTest(unittest.TestCase):
    def test_timer_firing_while_prepare_holds_the_lock_waits_and_then_does_nothing(self):
        h = Harness()
        h.prepare()
        h.display.release()
        timer = h.timers[0]
        fired = threading.Event()
        lock = ContendedRLock()
        h.display._lock = lock

        def fire():
            timer.fire()
            fired.set()

        with lock:
            thread = threading.Thread(target=fire)
            thread.start()
            self.assertTrue(lock.contended.wait(5))   # le Timer attend le verrou
            self.assertFalse(fired.is_set())
            h.display.cancel_release()          # même thread : verrou réentrant
        thread.join(2)
        self.assertTrue(fired.is_set())
        self.assertEqual(h.layout.path_calls(), [("path", VDD_KEY, True, (2880, 1800))])


if __name__ == "__main__":
    unittest.main()
