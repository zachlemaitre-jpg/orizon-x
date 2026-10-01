import ctypes
import time
import unittest
from unittest import mock

import injector
import inputstate
import protocol
from inputstate import Rect


class LayoutTest(unittest.TestCase):
    def test_struct_sizes_match_winuser_h_on_x64(self):
        self.assertEqual(ctypes.sizeof(ctypes.c_void_p), 8, "Python 64 bits requis")
        self.assertEqual(ctypes.sizeof(injector.POINTER_INFO), 96)
        self.assertEqual(ctypes.sizeof(injector.POINTER_TOUCH_INFO), 144)
        self.assertEqual(ctypes.sizeof(injector.POINTER_PEN_INFO), 120)
        self.assertEqual(ctypes.sizeof(injector.POINTER_TYPE_INFO), 152)


    def test_to_native_converts_desktop_to_virtual_screen_coordinates(self):
        info = injector._to_native(protocol.DEVICE_TOUCH, inputstate.PointerAction(0, 0, 1200, 800), (-1920, -207))
        point = info.touchInfo.pointerInfo.ptPixelLocation
        self.assertEqual((point.x, point.y), (3120, 1007))
        self.assertEqual(info.type, injector.PT_TOUCH)

    def test_to_native_pen_fills_pen_info(self):
        action = inputstate.PointerAction(
            0, inputstate.POINTER_FLAG_UPDATE, 100, 50, pressure=512, tilt_x=-30, tilt_y=45,
            pen_flags=inputstate.PEN_FLAG_BARREL, pen_mask=inputstate.PEN_MASK_PRESSURE)
        info = injector._to_native(protocol.DEVICE_PEN, action, (-10, -20))
        pen = info.penInfo
        self.assertEqual(info.type, injector.PT_PEN)
        self.assertEqual(pen.pointerInfo.pointerType, injector.PT_PEN)
        self.assertEqual((pen.pointerInfo.ptPixelLocation.x, pen.pointerInfo.ptPixelLocation.y), (110, 70))
        self.assertEqual(pen.pointerInfo.pointerFlags, inputstate.POINTER_FLAG_UPDATE)
        self.assertEqual((pen.pressure, pen.tiltX, pen.tiltY), (512, -30, 45))
        self.assertEqual((pen.penFlags, pen.penMask), (inputstate.PEN_FLAG_BARREL, inputstate.PEN_MASK_PRESSURE))


class FindTargetTest(unittest.TestCase):
    MONITORS = [
        (Rect(0, 0, 2560, 1600), True, r"\\.\DISPLAY1"),
        (Rect(2560, -207, 2880, 1800), False, r"\\.\DISPLAY13"),
    ]

    def test_unique_match(self):
        self.assertEqual(injector.find_target(2880, 1800, self.MONITORS), (Rect(2560, -207, 2880, 1800), ""))

    def test_no_match(self):
        rect, problem = injector.find_target(1920, 1080, self.MONITORS)
        self.assertIsNone(rect)
        self.assertIn("1920x1080", problem)

    def test_ambiguous_match(self):
        rect, problem = injector.find_target(2880, 1800, self.MONITORS + [(Rect(-2880, 0, 2880, 1800), False, "X")])
        self.assertIsNone(rect)
        self.assertIn("2 écrans", problem)


class FakeWin32:
    """Replaces the Win32 entry points so that unit tests never inject real input."""

    def __init__(self) -> None:
        self.calls: list[tuple] = []
        self.next_handle = 100
        self.inject_result = True
        self.inject_error = 0

    def create_device(self, pointer_type, max_count, mode):
        self.calls.append(("create", pointer_type))
        self.next_handle += 1
        return self.next_handle

    def inject(self, handle, infos, count):
        frame = [(infos[i].type, infos[i].touchInfo.pointerInfo.pointerId,
                  infos[i].touchInfo.pointerInfo.pointerFlags) for i in range(count)]
        self.calls.append(("inject", handle, frame))
        if not self.inject_result:
            ctypes.set_last_error(self.inject_error)
        return self.inject_result

    def destroy_device(self, handle):
        self.calls.append(("destroy", handle))

    def kinds(self, kind):
        return [c for c in self.calls if c[0] == kind]


class _InjectorCase(unittest.TestCase):
    KEEPALIVE_S = 3600  # le keep-alive ne se déclenche pas pendant un test, sauf pour KeepAliveTest
    RECT = Rect(2560, -207, 2880, 1800)
    TOUCH = lambda self, *contacts: protocol.Input(protocol.DEVICE_TOUCH, tuple(contacts))
    PEN = lambda self, *contacts: protocol.Input(protocol.DEVICE_PEN, tuple(contacts))
    DOWN = protocol.CONTACT_CONTACT | protocol.CONTACT_IN_RANGE

    def setUp(self):
        self.win32 = FakeWin32()
        self.log: list[str] = []
        patches = mock.patch.multiple(
            injector, create=True, AVAILABLE=True,
            _create_device=self.win32.create_device, _inject=self.win32.inject,
            _destroy_device=self.win32.destroy_device, virtual_screen_origin=lambda: (-1920, -207),
            KEEPALIVE_S=self.KEEPALIVE_S)
        patches.start()
        self.addCleanup(patches.stop)
        self.injector = injector.Injector(self.RECT, log=self.log.append)
        self.addCleanup(self.injector.close)

    def contact(self, id_, flags):
        return protocol.Contact(id_, flags, 0, 0, 0, 0, 0)



class InjectorTest(_InjectorCase):
    def test_devices_are_created_lazily_once_per_type(self):
        self.assertEqual(self.win32.calls, [])
        self.injector.handle(self.TOUCH(self.contact(0, self.DOWN)))
        self.injector.handle(self.TOUCH(self.contact(0, self.DOWN)))
        self.assertEqual(self.win32.kinds("create"), [("create", injector.PT_TOUCH)])
        self.injector.handle(self.PEN(self.contact(0, protocol.CONTACT_IN_RANGE)))
        self.assertEqual(self.win32.kinds("create"), [("create", injector.PT_TOUCH), ("create", injector.PT_PEN)])

    def test_access_denied_logs_once_and_keeps_going(self):
        self.win32.inject_result = False
        self.win32.inject_error = injector.ERROR_ACCESS_DENIED
        self.injector.handle(self.TOUCH(self.contact(0, self.DOWN)))
        self.injector.handle(self.TOUCH(self.contact(0, self.DOWN)))
        self.assertEqual(len(self.log), 1)
        self.assertIn("administrateur", self.log[0])
        self.assertTrue(self.injector.enabled)
        self.assertEqual(len(self.win32.kinds("inject")), 2)

    def test_other_error_disables_with_one_message(self):
        self.win32.inject_result = False
        self.win32.inject_error = 87
        self.injector.handle(self.TOUCH(self.contact(0, self.DOWN)))
        self.injector.handle(self.TOUCH(self.contact(0, self.DOWN)))
        self.assertEqual(len(self.log), 1)
        self.assertIn("87", self.log[0])
        self.assertFalse(self.injector.enabled)
        self.assertEqual(len(self.win32.kinds("inject")), 1)

    def test_close_cancels_pointers_before_destroying_devices(self):
        self.injector.handle(self.TOUCH(self.contact(0, self.DOWN)))
        self.win32.calls.clear()
        self.injector.close()
        names = [c[0] for c in self.win32.calls]
        self.assertIn("destroy", names)
        self.assertLess(max(i for i, n in enumerate(names) if n == "inject"), names.index("destroy"))
        cancel = self.win32.kinds("inject")[0]
        self.assertEqual(cancel[2][0][2] & (inputstate.POINTER_FLAG_UP | inputstate.POINTER_FLAG_CANCELED),
                         inputstate.POINTER_FLAG_UP | inputstate.POINTER_FLAG_CANCELED)

    def test_nothing_is_injected_after_close(self):
        self.injector.close()
        self.win32.calls.clear()
        self.injector.handle(self.TOUCH(self.contact(0, self.DOWN)))
        self.assertEqual(self.win32.calls, [])


class KeepAliveTest(_InjectorCase):
    KEEPALIVE_S = 0.02

    def test_held_contact_is_reinjected(self):
        self.injector.handle(self.TOUCH(self.contact(0, self.DOWN)))
        self.assertEqual(len(self.win32.kinds("inject")), 1)
        time.sleep(0.1)
        extra = self.win32.kinds("inject")[1:]
        self.assertGreaterEqual(len(extra), 1)
        held = inputstate.POINTER_FLAG_UPDATE | inputstate.POINTER_FLAG_INRANGE | inputstate.POINTER_FLAG_INCONTACT
        self.assertTrue(all(frame[0][2] & ~inputstate.POINTER_FLAG_PRIMARY == held for _, _, frame in extra))
        self.injector.close()

    def test_nothing_is_reinjected_without_a_held_contact(self):
        self.injector.handle(self.PEN(self.contact(0, protocol.CONTACT_IN_RANGE)))
        count = len(self.win32.kinds("inject"))
        self.assertEqual(count, 1)
        time.sleep(0.1)
        self.assertEqual(len(self.win32.kinds("inject")), count)
        self.injector.close()


if __name__ == "__main__":
    unittest.main()
