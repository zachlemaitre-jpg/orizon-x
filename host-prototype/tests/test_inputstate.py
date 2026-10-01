import unittest

import inputstate as s
import protocol

RECT = s.Rect(2560, -207, 2880, 1800)
DOWN = protocol.CONTACT_CONTACT | protocol.CONTACT_IN_RANGE
HOVER = protocol.CONTACT_IN_RANGE
F_DOWN = s.POINTER_FLAG_DOWN | s.POINTER_FLAG_INRANGE | s.POINTER_FLAG_INCONTACT
F_MOVE = s.POINTER_FLAG_UPDATE | s.POINTER_FLAG_INRANGE | s.POINTER_FLAG_INCONTACT
PRIMARY = s.POINTER_FLAG_PRIMARY


def c(id_, flags=DOWN, x=0, y=0, pressure=0, tilt_x=0, tilt_y=0):
    return protocol.Contact(id_, flags, x, y, pressure, tilt_x, tilt_y)


def flags_by_id(frame):
    return {a.pointer_id: a.flags for a in frame}


class TouchTest(unittest.TestCase):
    def setUp(self):
        self.touch = s.DeviceState(protocol.DEVICE_TOUCH)

    def test_new_contact_goes_down_as_primary(self):
        (a,) = self.touch.update([c(0)], RECT)
        self.assertEqual(a.flags, F_DOWN | PRIMARY)
        self.assertEqual((a.x, a.y), (2560, -207))

    def test_far_corner_maps_to_last_pixel(self):
        (a,) = self.touch.update([c(0, x=65535, y=65535)], RECT)
        self.assertEqual((a.x, a.y), (2560 + 2879, -207 + 1799))

    def test_held_contact_updates(self):
        self.touch.update([c(0)], RECT)
        (a,) = self.touch.update([c(0, x=100)], RECT)
        self.assertEqual(a.flags, F_MOVE | PRIMARY)

    def test_missing_contact_goes_up(self):
        self.touch.update([c(0)], RECT)
        (a,) = self.touch.update([], RECT)
        self.assertEqual(a.flags, s.POINTER_FLAG_UP | PRIMARY)
        self.assertEqual(self.touch.update([], RECT), [])

    def test_primary_is_the_oldest_contact(self):
        self.touch.update([c(0)], RECT)
        both = flags_by_id(self.touch.update([c(0), c(1)], RECT))
        self.assertTrue(both[0] & PRIMARY)
        self.assertFalse(both[1] & PRIMARY)
        lifted = flags_by_id(self.touch.update([c(1)], RECT))
        self.assertEqual(lifted[0], s.POINTER_FLAG_UP | PRIMARY)
        self.assertTrue(flags_by_id(self.touch.update([c(1)], RECT))[1] & PRIMARY)

    def test_canceled_contact(self):
        self.touch.update([c(0)], RECT)
        (a,) = self.touch.update([c(0, DOWN | protocol.CONTACT_CANCELED)], RECT)
        self.assertEqual(a.flags, s.POINTER_FLAG_UP | s.POINTER_FLAG_CANCELED | PRIMARY)
        self.assertEqual(self.touch.update([], RECT), [])

    def test_canceled_unknown_contact_is_ignored(self):
        self.assertEqual(self.touch.update([c(3, DOWN | protocol.CONTACT_CANCELED)], RECT), [])

    def test_refresh_resends_held_contacts(self):
        self.assertEqual(self.touch.refresh(), [])
        self.touch.update([c(0, x=10)], RECT)
        (a,) = self.touch.refresh()
        self.assertEqual(a.flags, F_MOVE | PRIMARY)

    def test_cancel_all(self):
        self.touch.update([c(0), c(1)], RECT)
        frame = flags_by_id(self.touch.cancel_all())
        self.assertEqual(frame[0], s.POINTER_FLAG_UP | s.POINTER_FLAG_CANCELED | PRIMARY)
        self.assertEqual(frame[1], s.POINTER_FLAG_UP | s.POINTER_FLAG_CANCELED)
        self.assertEqual(self.touch.update([], RECT), [])

    def test_finger_has_no_pen_data(self):
        (a,) = self.touch.update([c(0, pressure=500, tilt_x=10)], RECT)
        self.assertEqual((a.pressure, a.tilt_x, a.pen_mask), (0, 0, 0))


class PenTest(unittest.TestCase):
    def setUp(self):
        self.pen = s.DeviceState(protocol.DEVICE_PEN)

    def test_hover(self):
        (a,) = self.pen.update([c(0, HOVER)], RECT)
        self.assertEqual(a.flags, s.POINTER_FLAG_UPDATE | s.POINTER_FLAG_INRANGE | PRIMARY)
        self.assertEqual(a.pen_mask, s.PEN_MASK_PRESSURE | s.PEN_MASK_TILT_X | s.PEN_MASK_TILT_Y)

    def test_down_with_pressure_tilt_and_barrel(self):
        self.pen.update([c(0, HOVER)], RECT)
        (a,) = self.pen.update([c(0, DOWN | protocol.CONTACT_BARREL, pressure=512, tilt_x=-30, tilt_y=45)], RECT)
        self.assertEqual(a.flags, F_DOWN | PRIMARY)
        self.assertEqual((a.pressure, a.tilt_x, a.tilt_y, a.pen_flags), (512, -30, 45, s.PEN_FLAG_BARREL))

    def test_pressure_is_clamped_to_1024(self):
        (a,) = self.pen.update([c(0, DOWN, pressure=65535)], RECT)
        self.assertEqual(a.pressure, 1024)

    def test_lift_while_still_in_range(self):
        self.pen.update([c(0)], RECT)
        (a,) = self.pen.update([c(0, HOVER)], RECT)
        self.assertEqual(a.flags, s.POINTER_FLAG_UP | s.POINTER_FLAG_INRANGE | PRIMARY)

    def test_leaving_range(self):
        self.pen.update([c(0, HOVER)], RECT)
        (a,) = self.pen.update([], RECT)
        self.assertEqual(a.flags, s.POINTER_FLAG_UPDATE | PRIMARY)

    def test_cancel_all_while_hovering_just_leaves(self):
        self.pen.update([c(0, HOVER)], RECT)
        (a,) = self.pen.cancel_all()
        self.assertEqual(a.flags, s.POINTER_FLAG_UPDATE | PRIMARY)


if __name__ == "__main__":
    unittest.main()
