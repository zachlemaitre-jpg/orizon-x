import unittest

from app import status
from engine import State, StreamStats


class StatusTest(unittest.TestCase):
    def test_every_state_has_title_and_colour(self):
        for state in State:
            self.assertTrue(status.TITLES[state])
            self.assertRegex(status.COLORS[state], r"^#[0-9A-F]{6}$")

    def test_primary_label(self):
        self.assertEqual(status.primary_label(State.STREAMING), "Arrêter")
        self.assertEqual(status.primary_label(State.WAITING_DEVICE), "Arrêter")
        self.assertEqual(status.primary_label(State.WAITING_APP), "Arrêter")
        self.assertEqual(status.primary_label(State.STOPPED), "Démarrer")
        self.assertEqual(status.primary_label(State.ERROR), "Réessayer")

    def test_is_active(self):
        self.assertTrue(status.is_active(State.STREAMING))
        self.assertFalse(status.is_active(State.ERROR))
        self.assertFalse(status.is_active(State.STOPPED))

    def test_stream_detail(self):
        stats = StreamStats(2880, 1800, 60, 18.4, 40.0, 0, 0.5)
        self.assertEqual(status.stream_detail(stats), "2880×1800 · 60 fps · 18 ms")

    def test_stopped_detail_tells_what_to_do(self):
        self.assertEqual(status.detail_for(State.STOPPED, "Arrêté."), "Clique sur Démarrer.")
        self.assertEqual(status.detail_for(State.ERROR, "boom"), "boom")


if __name__ == "__main__":
    unittest.main()
