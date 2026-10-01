import ctypes
import unittest

import injector
from inputstate import Rect


class LayoutTest(unittest.TestCase):
    def test_struct_sizes_match_winuser_h_on_x64(self):
        self.assertEqual(ctypes.sizeof(ctypes.c_void_p), 8, "Python 64 bits requis")
        self.assertEqual(ctypes.sizeof(injector.POINTER_INFO), 96)
        self.assertEqual(ctypes.sizeof(injector.POINTER_TOUCH_INFO), 144)
        self.assertEqual(ctypes.sizeof(injector.POINTER_PEN_INFO), 120)
        self.assertEqual(ctypes.sizeof(injector.POINTER_TYPE_INFO), 152)


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


if __name__ == "__main__":
    unittest.main()
