import unittest

from app import status
from engine import State, StreamStats
from messages import msg


class StatusTest(unittest.TestCase):
    def test_every_state_has_title_and_colour(self):
        for state in State:
            for lang in ("en", "fr"):
                self.assertTrue(status.title(state, lang))
            self.assertRegex(status.COLORS[state], r"^#[0-9A-F]{6}$")

    def test_titles(self):
        self.assertEqual(status.title(State.WAITING_DEVICE, "en"), "Waiting for the tablet")
        self.assertEqual(status.title(State.WAITING_DEVICE, "fr"), "En attente de la tablette")
        self.assertEqual(status.title(State.STREAMING, "en"), "Connected")
        self.assertEqual(status.title(State.STREAMING, "fr"), "Connecté")

    def test_primary_label(self):
        self.assertEqual(status.primary_label(State.STREAMING, "fr"), "Arrêter")
        self.assertEqual(status.primary_label(State.WAITING_DEVICE, "fr"), "Arrêter")
        self.assertEqual(status.primary_label(State.WAITING_APP, "fr"), "Arrêter")
        self.assertEqual(status.primary_label(State.STOPPED, "fr"), "Démarrer")
        self.assertEqual(status.primary_label(State.ERROR, "fr"), "Réessayer")
        self.assertEqual(status.primary_label(State.STREAMING, "en"), "Stop")
        self.assertEqual(status.primary_label(State.STOPPED, "en"), "Start")
        self.assertEqual(status.primary_label(State.ERROR, "en"), "Retry")

    def test_is_active(self):
        self.assertTrue(status.is_active(State.STREAMING))
        self.assertFalse(status.is_active(State.ERROR))
        self.assertFalse(status.is_active(State.STOPPED))

    def test_stream_detail(self):
        stats = StreamStats(2880, 1800, 60, 18.4, 40.0, 0, 0.5)
        self.assertEqual(status.stream_detail(stats), "2880×1800 · 60 fps · 18 ms")

    def test_stopped_detail_tells_what_to_do(self):
        self.assertEqual(status.detail_for(State.STOPPED, msg("state.stopped"), "fr"), "Clique sur Démarrer.")
        self.assertEqual(status.detail_for(State.STOPPED, msg("state.stopped"), "en"), "Click Start.")

    def test_other_details_are_the_engine_message_translated(self):
        boom = msg("error.unexpected", error="boom")
        self.assertEqual(status.detail_for(State.ERROR, boom, "fr"), "Erreur inattendue : boom")
        self.assertEqual(status.detail_for(State.ERROR, boom, "en"), "Unexpected error: boom")

    def test_no_detail_yet_is_empty(self):
        self.assertEqual(status.detail_for(State.WAITING_DEVICE, None, "en"), "")


if __name__ == "__main__":
    unittest.main()
