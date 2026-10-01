import contextlib
import io
import unittest

import relay

OUTPUTS = [(0, (2560, 1600)), (1, (2880, 1800)), (2, None)]


class PickOutputTest(unittest.TestCase):
    def test_explicit_index_is_used_as_is(self):
        self.assertEqual(relay.pick_output("2", OUTPUTS, 2880, 1800), 2)

    def test_auto_picks_screen_with_tablet_size(self):
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(relay.pick_output("auto", OUTPUTS, 2880, 1800), 1)

    def test_auto_without_match_exits_with_the_list(self):
        with self.assertRaises(SystemExit) as raised:
            relay.pick_output("auto", OUTPUTS, 1920, 1200)
        self.assertIn("--output 1 : 2880x1800", str(raised.exception.code))

    def test_output_choice_rejects_garbage(self):
        with self.assertRaises(Exception):
            relay.output_choice("deux")


if __name__ == "__main__":
    unittest.main()
