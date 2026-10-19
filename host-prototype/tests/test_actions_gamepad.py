import ctypes
import math
import os
import shutil
import sys
import tempfile
import threading
import unittest

from actions import gamepad
from actions.gamepad import DriverMissingError, GamepadError, GamepadProvider


class Clock:
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t


class FakeLayer:
    """A fake ViGEm layer: records every call; the *_error attributes make the next calls raise."""

    def __init__(self):
        self.calls = []
        self.connect_error = None
        self.add_error = None
        self.update_error = None
        self.remove_error = None
        self.free_error = None
        self.disconnect_error = None

    def _raise(self, error):
        if error is not None:
            raise error

    def connect(self):
        self.calls.append(("connect",))
        self._raise(self.connect_error)

    def add_target(self):
        self.calls.append(("add",))
        self._raise(self.add_error)

    def update(self, buttons, lt, rt, lx, ly, rx, ry):
        self.calls.append(("update", buttons, lt, rt, lx, ly, rx, ry))
        self._raise(self.update_error)

    def remove_target(self):
        self.calls.append(("remove",))
        self._raise(self.remove_error)

    def free_target(self):
        self.calls.append(("free",))
        self._raise(self.free_error)

    def disconnect(self):
        self.calls.append(("disconnect",))
        self._raise(self.disconnect_error)

    def names(self):
        return [c[0] for c in self.calls]


def make():
    layer, clock, logs = FakeLayer(), Clock(), []
    return GamepadProvider(layer=layer, clock=clock, log=logs.append), layer, clock, logs


def state(**kw):
    s = {"id": "gamepad.state", "buttons": 0, "lt": 0, "rt": 0, "lx": 0, "ly": 0, "rx": 0, "ry": 0}
    s.update(kw)
    return s


OPEN = {"id": "gamepad.open"}
CLOSE = {"id": "gamepad.close"}


class ReportStructTest(unittest.TestCase):
    def test_xusb_report_is_12_bytes_with_the_xinput_layout(self):
        self.assertEqual(ctypes.sizeof(gamepad.XUSB_REPORT), 12)
        offsets = {name: getattr(gamepad.XUSB_REPORT, name).offset for name, _ in gamepad.XUSB_REPORT._fields_}
        self.assertEqual(offsets, {"wButtons": 0, "bLeftTrigger": 2, "bRightTrigger": 3, "sThumbLX": 4,
                                   "sThumbLY": 6, "sThumbRX": 8, "sThumbRY": 10})

    def test_button_bits(self):
        expected = {"DPAD_UP": 0x0001, "DPAD_DOWN": 0x0002, "DPAD_LEFT": 0x0004, "DPAD_RIGHT": 0x0008,
                    "START": 0x0010, "BACK": 0x0020, "LEFT_THUMB": 0x0040, "RIGHT_THUMB": 0x0080,
                    "LEFT_SHOULDER": 0x0100, "RIGHT_SHOULDER": 0x0200, "GUIDE": 0x0400, "A": 0x1000, "B": 0x2000,
                    "X": 0x4000, "Y": 0x8000}
        self.assertEqual(gamepad.BUTTON_BITS, expected)
        self.assertEqual(gamepad.BUTTON_MASK, sum(expected.values()))
        self.assertEqual(gamepad.BUTTON_MASK & 0x0800, 0)  # the unused bit

    def test_vigem_error_codes(self):
        gamepad.check_vigem(0x20000000)  # VIGEM_ERROR_NONE
        with self.assertRaises(DriverMissingError):
            gamepad.check_vigem(0xE0000001)  # BUS_NOT_FOUND
        with self.assertRaises(GamepadError) as ctx:
            gamepad.check_vigem(0xE0000002)  # NO_FREE_SLOT
        self.assertNotIsInstance(ctx.exception, DriverMissingError)
        self.assertIn("E0000002", str(ctx.exception).upper())


class AvailabilityTest(unittest.TestCase):
    def test_connected_is_available_and_connects_once(self):
        p, layer, _, _ = make()
        self.assertEqual(p.snapshot(), {"available": True})
        self.assertEqual(p.snapshot(), {"available": True})
        self.assertEqual(layer.calls, [("connect",)])

    def test_missing_dll_or_bus_is_driver_missing(self):
        p, layer, _, logs = make()
        layer.connect_error = DriverMissingError("ViGEmClient.dll not found")
        self.assertEqual(p.snapshot(), {"available": False, "reason": "driver_missing"})
        self.assertEqual(len(logs), 1)

    def test_any_other_error_is_error(self):
        for error in (GamepadError("slot"), OSError("dll broken"), RuntimeError("x")):
            with self.subTest(error):
                p, layer, _, _ = make()
                layer.connect_error = error
                self.assertEqual(p.snapshot(), {"available": False, "reason": "error"})

    def test_retried_after_30_seconds_not_before(self):
        p, layer, clock, _ = make()
        layer.connect_error = DriverMissingError("no bus")
        p.snapshot()
        clock.t += 29.9
        p.snapshot()
        self.assertEqual(layer.names().count("connect"), 1)
        clock.t += 0.2
        p.snapshot()
        self.assertEqual(layer.names().count("connect"), 2)
        clock.t += 30.1
        layer.connect_error = None  # the driver was installed meanwhile
        self.assertEqual(p.snapshot(), {"available": True})
        self.assertEqual(layer.names().count("connect"), 3)
        clock.t += 100
        p.snapshot()
        self.assertEqual(layer.names().count("connect"), 3)

    def test_the_same_failure_is_logged_once_per_streak(self):
        p, layer, clock, logs = make()
        layer.connect_error = GamepadError("x")
        for _ in range(4):
            p.snapshot()
            clock.t += 31
        self.assertEqual(len(logs), 1)

    def test_snapshot_never_raises(self):
        p, layer, _, _ = make()
        layer.connect_error = KeyError("x")
        self.assertEqual(p.snapshot()["available"], False)


class OpenTest(unittest.TestCase):
    def test_open_connects_and_adds_the_target_once(self):
        p, layer, _, _ = make()
        self.assertIsNone(p.handle(OPEN))
        self.assertIsNone(p.handle(OPEN))
        self.assertEqual(layer.names(), ["connect", "add"])
        self.assertTrue(p.is_open)

    def test_open_after_a_snapshot_does_not_connect_again(self):
        p, layer, _, _ = make()
        p.snapshot()
        p.handle(OPEN)
        self.assertEqual(layer.names(), ["connect", "add"])

    def test_open_without_a_driver_does_nothing_and_logs(self):
        p, layer, _, logs = make()
        layer.connect_error = DriverMissingError("no bus")
        self.assertIsNone(p.handle(OPEN))
        self.assertFalse(p.is_open)
        self.assertEqual(layer.names(), ["connect"])
        self.assertTrue(logs)
        self.assertEqual(p.snapshot(), {"available": False, "reason": "driver_missing"})

    def test_open_tries_again_at_once_even_within_the_retry_delay(self):
        p, layer, clock, _ = make()
        layer.connect_error = DriverMissingError("no bus")
        p.snapshot()
        layer.connect_error = None  # the user just installed the driver and reopened the screen
        clock.t += 1
        p.handle(OPEN)
        self.assertTrue(p.is_open)

    def test_a_failed_add_is_error_and_not_open(self):
        p, layer, _, logs = make()
        layer.add_error = GamepadError("no free slot")
        p.handle(OPEN)
        self.assertFalse(p.is_open)
        self.assertEqual(p.snapshot(), {"available": False, "reason": "error"})
        self.assertTrue(logs)

    def test_open_after_a_failed_add_adds_again(self):
        p, layer, _, _ = make()
        layer.add_error = GamepadError("x")
        p.handle(OPEN)
        layer.add_error = None
        p.handle(OPEN)
        self.assertTrue(p.is_open)
        self.assertEqual(layer.names().count("add"), 2)


class StateTest(unittest.TestCase):
    def setUp(self):
        self.p, self.layer, self.clock, self.logs = make()
        self.p.handle(OPEN)
        self.layer.calls.clear()

    def updates(self):
        return [c[1:] for c in self.layer.calls if c[0] == "update"]

    def test_full_report_is_sent(self):
        self.p.handle(state(buttons=0x1000 | 0x0001, lt=255, rt=0, lx=1000, ly=-2000, rx=-3, ry=32767))
        self.assertEqual(self.updates(), [(0x1001, 255, 0, 1000, -2000, -3, 32767)])

    def test_buttons_are_reduced_to_the_known_bits(self):
        self.p.handle(state(buttons=0xFFFF))
        self.assertEqual(self.updates(), [(gamepad.BUTTON_MASK, 0, 0, 0, 0, 0, 0)])
        self.layer.calls.clear()
        self.p.handle(state(buttons=0x0800 | 0x0100))
        self.assertEqual(self.updates()[0][0], 0x0100)

    def test_triggers_are_all_or_nothing(self):
        for value, expected in ((0, 0), (255, 255), (1, 255), (128, 255), (127, 255), (-5, 0), (1000, 255)):
            with self.subTest(value):
                self.layer.calls.clear()
                self.p.handle(state(lt=value, rt=value))
                self.assertEqual(self.updates(), [(0, expected, expected, 0, 0, 0, 0)])

    def test_axes_are_clamped_to_16_bits(self):
        self.p.handle(state(lx=99999, ly=-99999, rx=32768, ry=-32769))
        self.assertEqual(self.updates(), [(0, 0, 0, 32767, -32768, 32767, -32768)])
        self.layer.calls.clear()
        self.p.handle(state(lx=-32768, ly=32767))
        self.assertEqual(self.updates(), [(0, 0, 0, -32768, 32767, 0, 0)])

    def test_invalid_fields_refuse_the_whole_state_and_log(self):
        bad_values = [None, "5", True, 1.5, math.nan, math.inf, [1], {"a": 1}]
        for field in ("buttons", "lt", "rt", "lx", "ly", "rx", "ry"):
            for value in bad_values:
                with self.subTest(field=field, value=value):
                    self.layer.calls.clear()
                    self.logs.clear()
                    self.assertIsNone(self.p.handle(state(**{field: value})))
                    self.assertEqual(self.updates(), [])
                    self.assertEqual(len(self.logs), 1)

    def test_missing_fields_are_refused(self):
        for field in ("buttons", "lt", "rt", "lx", "ly", "rx", "ry"):
            with self.subTest(field):
                action = state()
                del action[field]
                self.layer.calls.clear()
                self.p.handle(action)
                self.assertEqual(self.updates(), [])

    def test_whole_valued_floats_are_accepted_as_numbers(self):
        self.p.handle(state(lx=100.0))
        self.assertEqual(self.updates(), [(0, 0, 0, 100, 0, 0, 0)])

    def test_state_without_an_open_pad_is_ignored(self):
        p, layer, _, _ = make()
        p.handle(state(buttons=1))
        self.assertEqual(layer.calls, [])

    def test_update_errors_are_logged_once_and_never_raise(self):
        self.layer.update_error = GamepadError("gone")
        for _ in range(3):
            self.assertIsNone(self.p.handle(state(buttons=1)))
        self.assertEqual(len(self.logs), 1)
        self.layer.update_error = None
        self.p.handle(state(buttons=1))
        self.layer.update_error = GamepadError("gone again")
        self.p.handle(state(buttons=1))
        self.assertEqual(len(self.logs), 2)

    def test_unknown_action_id(self):
        self.assertIsNone(self.p.handle({"id": "gamepad.rumble"}))
        self.assertEqual(len(self.logs), 1)


class CloseTest(unittest.TestCase):
    def opened(self):
        p, layer, clock, logs = make()
        p.handle(OPEN)
        layer.calls.clear()
        return p, layer, logs

    def test_close_is_neutral_report_then_remove_then_free(self):
        p, layer, _ = self.opened()
        self.assertIsNone(p.handle(CLOSE))
        self.assertEqual(layer.calls, [("update", 0, 0, 0, 0, 0, 0, 0), ("remove",), ("free",)])
        self.assertFalse(p.is_open)

    def test_close_when_not_open_does_nothing(self):
        p, layer, clock, _ = make()
        p.handle(CLOSE)
        self.assertEqual(layer.calls, [])

    def test_close_twice(self):
        p, layer, _ = self.opened()
        p.handle(CLOSE)
        layer.calls.clear()
        p.handle(CLOSE)
        self.assertEqual(layer.calls, [])

    def test_reopen_after_close(self):
        p, layer, _ = self.opened()
        p.handle(CLOSE)
        layer.calls.clear()
        p.handle(OPEN)
        self.assertEqual(layer.names(), ["add"])  # still connected to the bus
        self.assertTrue(p.is_open)

    def test_stop_is_neutral_remove_free_then_disconnect(self):
        p, layer, _ = self.opened()
        p.stop()
        self.assertEqual(layer.calls, [("update", 0, 0, 0, 0, 0, 0, 0), ("remove",), ("free",), ("disconnect",)])

    def test_stop_without_open_only_disconnects_if_connected(self):
        p, layer, clock, _ = make()
        p.stop()
        self.assertEqual(layer.calls, [])
        p, layer, clock, _ = make()
        p.snapshot()
        layer.calls.clear()
        p.stop()
        self.assertEqual(layer.calls, [("disconnect",)])

    def test_stop_twice_and_actions_after_stop(self):
        p, layer, _ = self.opened()
        p.stop()
        layer.calls.clear()
        p.stop()
        p.handle(OPEN)
        p.handle(state(buttons=1))
        self.assertEqual(layer.calls, [])
        self.assertEqual(p.snapshot()["available"], False)
        self.assertEqual(layer.calls, [])

    def test_nothing_ever_raises(self):
        for failing in ("update_error", "remove_error", "free_error", "disconnect_error"):
            with self.subTest(failing):
                p, layer, _ = self.opened()
                setattr(layer, failing, RuntimeError("boom"))
                p.handle(CLOSE)
                p.stop()
        p, layer, _ = self.opened()
        layer.update_error = layer.remove_error = layer.free_error = layer.disconnect_error = OSError("x")
        p.stop()
        names = layer.names()
        self.assertEqual(names, ["update", "remove", "free", "disconnect"])  # every step is tried

    def test_failed_close_still_leaves_the_pad_closed(self):
        p, layer, _ = self.opened()
        layer.remove_error = GamepadError("x")
        p.handle(CLOSE)
        self.assertFalse(p.is_open)


class ConcurrencyTest(unittest.TestCase):
    """open / state / close run on the hub's input thread, snapshot (bus connect and retry) on the hub thread."""

    def test_no_two_layer_calls_overlap(self):
        guard = threading.Lock()
        inside, overlaps = [0], [0]

        class SlowLayer(FakeLayer):
            def _enter(self):
                with guard:
                    inside[0] += 1
                    if inside[0] > 1:
                        overlaps[0] += 1
                threading.Event().wait(0.0003)
                with guard:
                    inside[0] -= 1

            def connect(self):
                self._enter()
                super().connect()

            def add_target(self):
                self._enter()
                super().add_target()

            def update(self, *a):
                self._enter()
                super().update(*a)

        layer, clock = SlowLayer(), Clock()
        p = GamepadProvider(layer=layer, clock=clock, log=lambda _l: None)
        layer.connect_error = DriverMissingError("no bus")  # the hub thread keeps retrying the connection
        stop = threading.Event()

        def hub_thread():
            while not stop.is_set():
                clock.t += 31
                p.snapshot()

        def input_thread():
            for i in range(24):
                p.handle(OPEN)
                p.handle(state(buttons=i & 0xF))
                if i == 12:
                    layer.connect_error = None

        poller = threading.Thread(target=hub_thread)
        poller.start()
        worker = threading.Thread(target=input_thread)
        worker.start()
        worker.join(20)
        stop.set()
        poller.join(5)
        self.assertEqual(overlaps[0], 0)
        self.assertTrue(p.is_open)
        self.assertEqual(layer.names().count("add"), 1)  # opened once, however the threads interleaved

    def test_stop_during_a_connect_attempt_leaves_nothing_open(self):
        started, release = threading.Event(), threading.Event()

        class BlockingLayer(FakeLayer):
            def connect(self):
                super().connect()
                started.set()
                release.wait(5)

        layer = BlockingLayer()
        p = GamepadProvider(layer=layer, clock=Clock(), log=lambda _l: None)
        poller = threading.Thread(target=p.snapshot)
        poller.start()
        self.assertTrue(started.wait(5))
        stopper = threading.Thread(target=p.stop)
        stopper.start()
        stopper.join(0.1)
        self.assertTrue(stopper.is_alive())  # waits for the connect in progress
        release.set()
        poller.join(5)
        stopper.join(5)
        self.assertEqual(layer.names()[-1], "disconnect")
        self.assertFalse(p.is_open)


class DllLookupTest(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="orizonx-vigem-test-")
        self.addCleanup(shutil.rmtree, self.dir, ignore_errors=True)

    def test_frozen_app_looks_in_its_folder_first_then_internal_then_vendor(self):
        c = gamepad.dll_candidates(frozen=True, executable=r"C:\Program Files\Orizon X\OrizonX.exe",
                                   meipass=r"C:\Program Files\Orizon X\_internal", module_dir=r"C:\src\actions")
        self.assertEqual(c[0], os.path.join(r"C:\Program Files\Orizon X", "ViGEmClient.dll"))
        self.assertEqual(c[1], os.path.join(r"C:\Program Files\Orizon X\_internal", "ViGEmClient.dll"))
        self.assertEqual(c[-1], os.path.join(os.path.dirname(r"C:\src\actions"), "vendor", "ViGEmClient.dll"))
        self.assertEqual(len(c), len(set(c)))

    def test_from_sources_it_is_host_prototype_vendor(self):
        c = gamepad.dll_candidates(frozen=False, executable="python.exe", meipass=None, module_dir=r"C:\src\actions")
        self.assertEqual(c, [os.path.join(r"C:\src", "vendor", "ViGEmClient.dll")])

    def test_find_dll_takes_the_first_that_exists(self):
        first = os.path.join(self.dir, "a", "ViGEmClient.dll")
        second = os.path.join(self.dir, "b", "ViGEmClient.dll")
        os.makedirs(os.path.dirname(second))
        with open(second, "wb") as f:
            f.write(b"x")
        self.assertEqual(gamepad.find_dll([first, second]), second)
        self.assertIsNone(gamepad.find_dll([first]))

    def test_a_missing_dll_is_driver_missing(self):
        layer = gamepad.ViGEmLayer(dll_paths=[os.path.join(self.dir, "nope", "ViGEmClient.dll")])
        with self.assertRaises(DriverMissingError):
            layer.connect()

    def test_importing_and_constructing_the_layer_loads_nothing(self):
        layer = gamepad.ViGEmLayer(dll_paths=[])
        self.assertIsNone(layer._dll)

    def test_the_real_provider_without_a_dll_reports_driver_missing(self):
        p = GamepadProvider(layer=gamepad.ViGEmLayer(dll_paths=[os.path.join(self.dir, "x.dll")]),
                            log=lambda _l: None)
        self.assertEqual(p.snapshot(), {"available": False, "reason": "driver_missing"})


@unittest.skipUnless(sys.platform == "win32" and os.path.isfile(gamepad.default_dll_candidates()[-1]),
                     "ViGEmClient.dll not vendored")
class RealDllSmokeTest(unittest.TestCase):
    """Read-only: the vendored DLL loads and exports what the layer needs; a client is allocated and freed. Never
    connects to the bus, never plugs a pad."""

    def test_exports_and_alloc_free(self):
        path = gamepad.default_dll_candidates()[-1]
        dll = ctypes.WinDLL(path)
        for name in ("vigem_alloc", "vigem_free", "vigem_connect", "vigem_disconnect", "vigem_target_x360_alloc",
                     "vigem_target_add", "vigem_target_remove", "vigem_target_free", "vigem_target_x360_update"):
            self.assertTrue(hasattr(dll, name), name)
        dll.vigem_alloc.restype = ctypes.c_void_p
        dll.vigem_free.argtypes = [ctypes.c_void_p]
        client = dll.vigem_alloc()
        self.assertTrue(client)
        dll.vigem_free(client)


if __name__ == "__main__":
    unittest.main()
