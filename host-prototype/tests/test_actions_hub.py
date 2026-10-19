import copy
import threading
import time
import unittest

from actions import hub as hub_mod
from actions.hub import ActionsHub, default_providers


class FakeProvider:
    def __init__(self, snap=None, result=None):
        self.snap = snap if snap is not None else {"available": True}
        self.result = result
        self.snapshots = 0
        self.handled = []
        self.handle_threads = []
        self.snapshot_threads = []
        self.raises = None
        self.handle_raises = None

    def snapshot(self):
        self.snapshots += 1
        self.snapshot_threads.append(threading.get_ident())
        if self.raises:
            raise self.raises
        return copy.deepcopy(self.snap)

    def handle(self, action):
        self.handled.append(action)
        self.handle_threads.append(threading.get_ident())
        if self.handle_raises:
            raise self.handle_raises
        return self.result


COVER_A = b"\x89PNG-cover-A"
COVER_B = b"\xff\xd8\xff-cover-B"
ID_A = "a" * 40
ID_B = "b" * 40


class FakeNowPlaying(FakeProvider):
    """now_playing stand-in: `covers` maps an artwork id to its bytes (what artwork_bytes gives)."""

    def __init__(self, snap=None, covers=None):
        super().__init__(snap if snap is not None else {
            "available": True, "app": "Spotify", "title": "UN BESO", "artist": "M4GN", "album": "UN BESO",
            "playing": True, "artwork": ID_A})
        self.covers = dict(covers) if covers is not None else {ID_A: COVER_A}
        self.artwork_requests = []
        self.artwork_threads = []

    def artwork_bytes(self, artwork_id):
        self.artwork_requests.append(artwork_id)
        self.artwork_threads.append(threading.get_ident())
        return self.covers.get(artwork_id)


class FakeClock:
    def __init__(self, t=100.0):
        self.t = t

    def __call__(self):
        return self.t


def make_providers():
    return {
        "clock": FakeProvider({"epoch_ms": 1000, "utc_offset_min": 120}),
        "battery": FakeProvider({"available": True, "percent": 76, "charging": True}),
        "audio": FakeProvider({"available": True, "volume": 0.42, "muted": False}),
        "media": FakeProvider({"available": True}),
        "brightness": FakeProvider({"available": True, "value": 0.7}),
        "radios": FakeProvider({"available": True,
                                "wifi": {"available": True, "on": True},
                                "bluetooth": {"available": True, "on": True},
                                "airplane": {"available": True, "on": False}}),
        "wifi_info": FakeProvider({"available": True, "ssid": "Maison", "signal": 64}),
        "bt_info": FakeProvider({"available": True, "connected": ["Casque"]}),
        "usb": FakeProvider({"available": True, "drives": [
            {"drive": "E:", "label": "KINGSTON", "free_bytes": 1, "total_bytes": 2, "kind": "stick"}]}),
        "now_playing": FakeNowPlaying(),
        "context": FakeProvider({"available": True, "app": "Spotify", "profile": "spotify", "buttons": [
            {"id": "spotify.playpause", "icon": "play_pause", "label": "Lecture/Pause"}]}),
    }


class Harness:
    """A hub driven step by step (no thread) with a fake clock."""

    def __init__(self, providers=None, **kw):
        self.providers = providers if providers is not None else make_providers()
        self.clock = FakeClock()
        self.sent = []
        self.logs = []
        self.artworks = []
        self.events = []  # ("artwork", id) / ("state", now_playing artwork id), in sending order
        kw.setdefault("send_artwork", self._send_artwork)
        self.hub = ActionsHub(self.providers, self._send, clock=self.clock, log=self.logs.append, **kw)

    def _send(self, state):
        self.sent.append(state)
        self.events.append(("state", state.get("now_playing", {}).get("artwork")))

    def _send_artwork(self, artwork_id, image):
        self.artworks.append((artwork_id, image))
        self.events.append(("artwork", artwork_id))

    def tick(self, advance=0.0):
        self.clock.t += advance
        self.hub._tick(self.clock.t)


class StateTest(unittest.TestCase):
    def test_first_tick_sends_the_full_state(self):
        h = Harness()
        h.tick()
        self.assertEqual(len(h.sent), 1)
        self.assertEqual(h.sent[0], {
            "v": 1,
            "clock": {"epoch_ms": 1000, "utc_offset_min": 120, "available": True},
            "battery": {"available": True, "percent": 76, "charging": True},
            "audio": {"available": True, "volume": 0.42, "muted": False},
            "media": {"available": True},
            "brightness": {"available": True, "value": 0.7},
            "wifi": {"available": True, "on": True, "ssid": "Maison", "signal": 64},
            "bluetooth": {"available": True, "on": True, "connected": ["Casque"]},
            "airplane": {"available": True, "on": False},
            "usb": [{"drive": "E:", "label": "KINGSTON", "free_bytes": 1, "total_bytes": 2, "kind": "stick"}],
            "now_playing": {"available": True, "app": "Spotify", "title": "UN BESO", "artist": "M4GN",
                            "album": "UN BESO", "playing": True, "artwork": ID_A},
            "context": {"available": True, "app": "Spotify", "profile": "spotify", "buttons": [
                {"id": "spotify.playpause", "icon": "play_pause", "label": "Lecture/Pause"}]},
        })
        self.assertNotIn("notice", h.sent[0])

    def test_state_is_json_serialisable(self):
        import json
        h = Harness()
        h.tick()
        json.dumps(h.sent[0])

    def test_radio_merge_hides_ssid_and_devices_when_radio_off(self):
        h = Harness()
        h.providers["radios"].snap["wifi"]["on"] = False
        h.providers["radios"].snap["bluetooth"]["on"] = False
        h.tick()
        self.assertEqual(h.sent[0]["wifi"], {"available": True, "on": False, "ssid": "", "signal": None})
        self.assertEqual(h.sent[0]["bluetooth"], {"available": True, "on": False, "connected": []})

    def test_radio_merge_with_info_providers_missing(self):
        providers = make_providers()
        del providers["wifi_info"], providers["bt_info"]
        h = Harness(providers)
        h.tick()
        self.assertEqual(h.sent[0]["wifi"], {"available": True, "on": True, "ssid": "", "signal": None})
        self.assertEqual(h.sent[0]["bluetooth"], {"available": True, "on": True, "connected": []})

    def test_radios_unavailable_makes_the_three_sections_unavailable(self):
        h = Harness()
        h.providers["radios"].snap = {"available": False}
        h.tick()
        for key in ("wifi", "bluetooth", "airplane"):
            self.assertEqual(h.sent[0][key], {"available": False})

    def test_every_object_section_carries_available(self):
        providers = make_providers()
        providers["radios"].snap = {"available": False}
        providers["battery"].snap = {"available": False}
        del providers["brightness"]
        h = Harness(providers)
        h.tick()
        for key in ("clock", "battery", "audio", "media", "brightness", "wifi", "bluetooth", "airplane",
                    "now_playing", "context"):
            self.assertIn("available", h.sent[0][key], key)
        self.assertEqual(h.sent[0]["brightness"], {"available": False})
        self.assertEqual(h.sent[0]["battery"], {"available": False})
        self.assertTrue(h.sent[0]["clock"]["available"])

    def test_usb_is_a_list_of_drives(self):
        h = Harness()
        h.providers["usb"].snap = {"available": True, "drives": []}
        h.tick()
        self.assertEqual(h.sent[0]["usb"], [])

    def test_usb_unavailable_is_an_empty_list(self):
        h = Harness()
        h.providers["usb"].snap = {"available": False}
        h.tick()
        self.assertEqual(h.sent[0]["usb"], [])

    def test_missing_providers_are_unavailable(self):
        h = Harness({})
        h.tick()
        self.assertEqual(h.sent[0]["audio"], {"available": False})
        self.assertEqual(h.sent[0]["clock"], {"available": False})
        self.assertEqual(h.sent[0]["usb"], [])
        self.assertEqual(h.sent[0]["wifi"], {"available": False})
        self.assertEqual(h.sent[0]["context"], {"available": False})

    def test_context_section_is_the_providers_snapshot(self):
        h = Harness()
        h.providers["context"].snap = {"available": True, "app": "Word", "profile": "word", "buttons": []}
        h.tick()
        self.assertEqual(h.sent[0]["context"], {"available": True, "app": "Word", "profile": "word",
                                                "buttons": []})

    def test_failing_context_provider_is_unavailable_and_the_rest_goes_on(self):
        h = Harness()
        h.providers["context"].raises = RuntimeError("boom")
        h.tick()
        self.assertEqual(h.sent[0]["context"], {"available": False})
        self.assertTrue(h.sent[0]["audio"]["available"])


class PollingTest(unittest.TestCase):
    def test_audio_polled_every_250ms_others_every_second(self):
        h = Harness()
        h.tick()
        h.tick(0.25)
        h.tick(0.25)
        h.tick(0.25)
        self.assertEqual(h.providers["audio"].snapshots, 4)
        self.assertEqual(h.providers["battery"].snapshots, 1)
        h.tick(0.25)  # t = 1.0 after the first tick
        self.assertEqual(h.providers["audio"].snapshots, 5)
        self.assertEqual(h.providers["battery"].snapshots, 2)
        self.assertEqual(h.providers["usb"].snapshots, 2)
        self.assertEqual(h.providers["radios"].snapshots, 2)
        self.assertEqual(h.providers["now_playing"].snapshots, 2)

    def test_context_is_polled_in_the_fast_group(self):
        h = Harness()
        h.tick()
        h.tick(0.25)
        h.tick(0.25)
        h.tick(0.25)
        self.assertEqual(h.providers["context"].snapshots, 4)
        self.assertEqual(h.providers["battery"].snapshots, 1)

    def test_tick_before_deadline_polls_nothing(self):
        h = Harness()
        h.tick()
        h.tick(0.1)
        self.assertEqual(h.providers["audio"].snapshots, 1)
        self.assertEqual(h.providers["battery"].snapshots, 1)

    def test_custom_intervals(self):
        h = Harness(poll_fast_s=0.5, poll_slow_s=2.0)
        h.tick()
        h.tick(0.25)
        self.assertEqual(h.providers["audio"].snapshots, 1)
        h.tick(0.25)
        self.assertEqual(h.providers["audio"].snapshots, 2)
        self.assertEqual(h.providers["battery"].snapshots, 1)
        h.tick(1.5)
        self.assertEqual(h.providers["battery"].snapshots, 2)


class BroadcastTest(unittest.TestCase):
    def test_unchanged_state_is_not_resent(self):
        h = Harness()
        h.tick()
        for _ in range(8):
            h.tick(0.25)
        self.assertEqual(len(h.sent), 1)

    def test_clock_ticking_alone_does_not_trigger_a_send(self):
        h = Harness()
        h.tick()
        h.providers["clock"].snap["epoch_ms"] = 2000
        h.tick(1.0)
        self.assertEqual(len(h.sent), 1)

    def test_clock_offset_change_is_sent(self):
        h = Harness()
        h.tick()
        h.providers["clock"].snap["utc_offset_min"] = 60
        h.tick(1.0)
        self.assertEqual(len(h.sent), 2)
        self.assertEqual(h.sent[1]["clock"]["utc_offset_min"], 60)

    def test_audio_change_is_sent_within_one_fast_poll(self):
        h = Harness()
        h.tick()
        h.providers["audio"].snap["volume"] = 0.5
        h.tick(0.25)
        self.assertEqual(len(h.sent), 2)
        self.assertEqual(h.sent[1]["audio"]["volume"], 0.5)
        # the broadcast is the full state, not a diff
        self.assertEqual(h.sent[1]["battery"], h.sent[0]["battery"])

    def test_slow_provider_change_is_sent_at_the_next_slow_poll(self):
        h = Harness()
        h.tick()
        h.providers["battery"].snap["percent"] = 75
        h.tick(0.25)
        h.tick(0.25)
        self.assertEqual(len(h.sent), 1)
        h.tick(0.5)
        self.assertEqual(len(h.sent), 2)
        self.assertEqual(h.sent[1]["battery"]["percent"], 75)

    def test_profile_change_is_broadcast_within_one_fast_poll(self):
        h = Harness()
        h.tick()
        self.assertEqual(len(h.sent), 1)
        h.providers["context"].snap = {"available": True, "app": "Chrome", "profile": "browser", "buttons": [
            {"id": "web.reload", "icon": "refresh", "label": "Actualiser"}]}
        h.tick(0.25)
        self.assertEqual(len(h.sent), 2)
        self.assertEqual(h.sent[1]["context"]["profile"], "browser")
        h.tick(0.25)
        self.assertEqual(len(h.sent), 2)

    def test_usb_change_is_sent(self):
        h = Harness()
        h.tick()
        h.providers["usb"].snap["drives"] = []
        h.tick(1.0)
        self.assertEqual(h.sent[1]["usb"], [])

    def test_refresh_after_30_seconds(self):
        h = Harness()
        h.tick()
        h.tick(29.0)
        self.assertEqual(len(h.sent), 1)
        h.tick(1.0)
        self.assertEqual(len(h.sent), 2)
        self.assertEqual(h.sent[1], h.sent[0])
        h.tick(29.9)
        self.assertEqual(len(h.sent), 2)
        h.tick(0.1)
        self.assertEqual(len(h.sent), 3)

    def test_custom_refresh(self):
        h = Harness(refresh_s=5.0)
        h.tick()
        h.tick(5.0)
        self.assertEqual(len(h.sent), 2)

    def test_sent_state_is_not_aliased_to_later_ones(self):
        h = Harness()
        h.tick()
        first = copy.deepcopy(h.sent[0])
        h.providers["usb"].snap["drives"][0]["label"] = "OTHER"
        h.tick(1.0)
        self.assertEqual(h.sent[0], first)
        self.assertEqual(h.sent[1]["usb"][0]["label"], "OTHER")

    def test_failing_send_is_retried_and_logged_once(self):
        h = Harness()
        calls = []

        def send(state):
            calls.append(state)
            if len(calls) <= 2:
                raise OSError("closed")
        h.hub._send = send
        h.tick()
        h.tick(0.25)
        self.assertEqual(len(calls), 2)  # still "due": retried
        self.assertEqual(sum("send failed" in line for line in h.logs), 1)
        h.tick(0.25)
        self.assertEqual(len(calls), 3)
        h.tick(0.25)
        self.assertEqual(len(calls), 3)


class RoutingTest(unittest.TestCase):
    def route(self, action, key):
        h = Harness()
        h.tick()
        h.hub._actions.put(action)
        h.hub._tick(h.clock.t)
        for name, provider in h.providers.items():
            if name == key:
                self.assertEqual(provider.handled, [action], name)
            else:
                self.assertEqual(provider.handled, [], name)

    def test_routing_by_prefix(self):
        cases = [
            ({"id": "volume.set", "value": 0.3}, "audio"),
            ({"id": "volume.mute", "value": True}, "audio"),
            ({"id": "media.play_pause"}, "media"),
            ({"id": "media.next"}, "media"),
            ({"id": "media.previous"}, "media"),
            ({"id": "brightness.set", "value": 0.5}, "brightness"),
            ({"id": "wifi.set", "value": False}, "radios"),
            ({"id": "bluetooth.set", "value": True}, "radios"),
            ({"id": "airplane.set", "value": True}, "radios"),
            ({"id": "usb.open", "drive": "E:"}, "usb"),
            ({"id": "usb.eject", "drive": "E:"}, "usb"),
            ({"id": "context.press", "button": "spotify.playpause"}, "context"),
        ]
        for action, key in cases:
            with self.subTest(action=action):
                self.route(action, key)

    def test_values_are_passed_through_untouched(self):
        h = Harness()
        h.tick()
        for value in (0, 1, 0.5, True, False):
            h.hub._actions.put({"id": "volume.set", "value": value})
        h.hub._tick(h.clock.t)
        got = [a["value"] for a in h.providers["audio"].handled]
        self.assertEqual(got, [0, 1, 0.5, True, False])
        self.assertEqual([type(v) for v in got], [int, int, float, bool, bool])

    def test_unknown_or_malformed_actions_are_logged_and_ignored(self):
        h = Harness()
        h.tick()
        for action in ({"id": "unknown.thing"}, {"id": 5}, {}, "volume.set", None, {"id": "volumex"}):
            h.hub._actions.put(action)
        h.hub._tick(h.clock.t)
        for provider in h.providers.values():
            self.assertEqual(provider.handled, [])
        self.assertEqual(len(h.logs), 6)
        self.assertEqual(len(h.sent), 1)  # no notice for an unknown action

    def test_action_forces_an_immediate_poll_and_broadcast(self):
        h = Harness()
        h.tick()
        h.providers["audio"].snap["volume"] = 0.9
        h.providers["battery"].snap["percent"] = 10
        h.hub._actions.put({"id": "volume.set", "value": 0.9})
        h.hub._tick(h.clock.t)  # same instant: nothing is due, only the action forces it
        self.assertEqual(len(h.sent), 2)
        self.assertEqual(h.sent[1]["audio"]["volume"], 0.9)
        self.assertEqual(h.sent[1]["battery"]["percent"], 10)

    def test_action_for_a_missing_provider_gives_action_failed_notice(self):
        providers = make_providers()
        del providers["brightness"]
        h = Harness(providers)
        h.tick()
        h.hub._actions.put({"id": "brightness.set", "value": 0.5})
        h.hub._tick(h.clock.t)
        self.assertEqual(h.sent[1]["notice"], {"code": "action_failed"})

    def test_provider_raising_in_handle_gives_action_failed_notice(self):
        h = Harness()
        h.tick()
        h.providers["audio"].handle_raises = RuntimeError("boom")
        h.hub._actions.put({"id": "volume.set", "value": 0.5})
        h.hub._tick(h.clock.t)
        self.assertEqual(h.sent[1]["notice"], {"code": "action_failed"})
        self.assertTrue(any("boom" in line for line in h.logs))


class NoticeTest(unittest.TestCase):
    def test_notice_is_sent_once_in_the_next_state_only(self):
        h = Harness()
        h.tick()
        h.providers["usb"].result = "usb_busy"
        h.hub._actions.put({"id": "usb.eject", "drive": "E:"})
        h.hub._tick(h.clock.t)
        self.assertEqual(len(h.sent), 2)
        self.assertEqual(h.sent[1]["notice"], {"code": "usb_busy", "drive": "E:"})
        # nothing changed: the notice alone forced that send, and is gone now
        h.providers["audio"].snap["volume"] = 0.1
        h.tick(0.25)
        self.assertEqual(len(h.sent), 3)
        self.assertNotIn("notice", h.sent[2])
        h.tick(30.0)
        self.assertNotIn("notice", h.sent[3])

    def test_notice_without_drive(self):
        h = Harness()
        h.tick()
        h.providers["radios"].result = "radio_denied"
        h.hub._actions.put({"id": "wifi.set", "value": True})
        h.hub._tick(h.clock.t)
        self.assertEqual(h.sent[1]["notice"], {"code": "radio_denied"})

    def test_no_notice_when_the_action_succeeds(self):
        h = Harness()
        h.tick()
        h.hub._actions.put({"id": "volume.set", "value": 0.1})
        h.hub._tick(h.clock.t)
        for state in h.sent:
            self.assertNotIn("notice", state)

    def test_notice_survives_a_failed_send(self):
        h = Harness()
        h.tick()
        h.providers["usb"].result = "usb_failed"
        h.hub._actions.put({"id": "usb.eject", "drive": "F:"})
        real_send = h.hub._send
        h.hub._send = lambda s: (_ for _ in ()).throw(OSError("closed"))
        h.hub._tick(h.clock.t)
        h.hub._send = real_send
        h.tick(0.25)
        self.assertEqual(h.sent[-1]["notice"], {"code": "usb_failed", "drive": "F:"})


class FailureTest(unittest.TestCase):
    def test_failing_provider_is_logged_once_and_marked_unavailable(self):
        h = Harness()
        h.tick()
        h.providers["audio"].raises = RuntimeError("com gone")
        for _ in range(5):
            h.tick(0.25)
        self.assertEqual(h.sent[1]["audio"], {"available": False})
        self.assertEqual(len(h.sent), 2)
        self.assertEqual(sum("audio" in line and "failed" in line for line in h.logs), 1)

    def test_recovery(self):
        h = Harness()
        h.tick()
        h.providers["audio"].raises = RuntimeError("com gone")
        h.tick(0.25)
        h.providers["audio"].raises = None
        h.tick(0.25)
        self.assertEqual(h.sent[-1]["audio"], {"available": True, "volume": 0.42, "muted": False})
        self.assertTrue(any("recovered" in line for line in h.logs))
        # a second outage is logged again
        h.providers["audio"].raises = RuntimeError("again")
        h.tick(0.25)
        self.assertEqual(sum("failed" in line for line in h.logs), 2)

    def test_failing_usb_gives_empty_list(self):
        h = Harness()
        h.tick()
        h.providers["usb"].raises = OSError("x")
        h.tick(1.0)
        self.assertEqual(h.sent[1]["usb"], [])

    def test_failing_radios_makes_radio_sections_unavailable(self):
        h = Harness()
        h.providers["radios"].raises = RuntimeError("winrt timeout")
        h.tick()
        for key in ("wifi", "bluetooth", "airplane"):
            self.assertEqual(h.sent[0][key], {"available": False})

    def test_failing_wifi_info_only_blanks_the_ssid(self):
        h = Harness()
        h.providers["wifi_info"].raises = OSError("wlan")
        h.tick()
        self.assertEqual(h.sent[0]["wifi"], {"available": True, "on": True, "ssid": "", "signal": None})

    def test_failing_clock_does_not_stop_the_others(self):
        h = Harness()
        h.providers["clock"].raises = RuntimeError("x")
        h.tick()
        self.assertEqual(h.sent[0]["clock"], {"available": False})
        self.assertEqual(h.sent[0]["audio"]["volume"], 0.42)

    def test_non_dict_snapshot_counts_as_failure(self):
        h = Harness()
        h.providers["battery"].snap = [1, 2]
        h.tick()
        self.assertEqual(h.sent[0]["battery"], {"available": False})


class ArtworkTest(unittest.TestCase):
    def test_artwork_sent_before_the_first_state_that_references_it(self):
        h = Harness()
        h.tick()
        self.assertEqual(h.events, [("artwork", ID_A), ("state", ID_A)])
        self.assertEqual(h.artworks, [(ID_A, COVER_A)])

    def test_artwork_sent_once_per_cover(self):
        h = Harness()
        h.tick()
        for _ in range(10):
            h.tick(1.0)
        h.tick(30.0)  # periodic refresh: the state again, not the cover
        self.assertEqual(h.artworks, [(ID_A, COVER_A)])
        self.assertEqual(h.events[-1], ("state", ID_A))
        self.assertEqual(len(h.sent), 2)

    def test_new_cover_sent_before_the_state_that_switches_to_it(self):
        h = Harness()
        h.tick()
        h.providers["now_playing"].snap["artwork"] = ID_B
        h.providers["now_playing"].covers[ID_B] = COVER_B
        h.tick(1.0)
        self.assertEqual(h.events, [("artwork", ID_A), ("state", ID_A), ("artwork", ID_B), ("state", ID_B)])
        self.assertEqual(h.artworks[-1], (ID_B, COVER_B))

    def test_back_to_a_previous_cover_sends_it_again(self):
        # the device keeps only the last cover received
        h = Harness()
        h.providers["now_playing"].covers[ID_B] = COVER_B
        h.tick()
        h.providers["now_playing"].snap["artwork"] = ID_B
        h.tick(1.0)
        h.providers["now_playing"].snap["artwork"] = ID_A
        h.tick(1.0)
        self.assertEqual([a for a, _ in h.artworks], [ID_A, ID_B, ID_A])
        self.assertEqual(h.events[-2:], [("artwork", ID_A), ("state", ID_A)])

    def test_no_cover_sends_no_artwork(self):
        h = Harness()
        h.providers["now_playing"].snap["artwork"] = None
        h.tick()
        self.assertEqual(h.artworks, [])
        self.assertIsNone(h.sent[0]["now_playing"]["artwork"])

    def test_cover_then_none_then_same_cover_resends_only_the_state(self):
        h = Harness()
        h.tick()
        h.providers["now_playing"].snap["artwork"] = None
        h.tick(1.0)
        self.assertEqual(h.events[-1], ("state", None))
        h.providers["now_playing"].snap["artwork"] = ID_A
        h.tick(1.0)
        # the device still caches ID_A (nothing replaced it): no need to send it again
        self.assertEqual(h.artworks, [(ID_A, COVER_A)])
        self.assertEqual(h.events[-1], ("state", ID_A))

    def test_now_playing_unavailable(self):
        h = Harness()
        h.providers["now_playing"].snap = {"available": False}
        h.tick()
        self.assertEqual(h.sent[0]["now_playing"], {"available": False})
        self.assertEqual(h.artworks, [])

    def test_now_playing_missing_or_failing_is_unavailable(self):
        providers = make_providers()
        del providers["now_playing"]
        h = Harness(providers)
        h.tick()
        self.assertEqual(h.sent[0]["now_playing"], {"available": False})
        h2 = Harness()
        h2.providers["now_playing"].raises = RuntimeError("winrt")
        h2.tick()
        self.assertEqual(h2.sent[0]["now_playing"], {"available": False})
        self.assertEqual(h2.artworks, [])

    def test_without_send_artwork_the_state_never_references_a_cover(self):
        h = Harness(send_artwork=None)
        h.tick()
        self.assertIsNone(h.sent[0]["now_playing"]["artwork"])
        self.assertEqual(h.sent[0]["now_playing"]["title"], "UN BESO")
        self.assertEqual(h.providers["now_playing"].artwork_requests, [])

    def test_constructor_send_artwork_is_optional(self):
        sent = []
        hub = ActionsHub(make_providers(), sent.append, clock=FakeClock(), log=lambda _l: None)
        hub._tick(100.0)
        self.assertIsNone(sent[0]["now_playing"]["artwork"])

    def test_missing_bytes_nulls_the_artwork_without_resending_every_tick(self):
        h = Harness()
        h.providers["now_playing"].covers = {}
        h.tick()
        self.assertEqual(h.artworks, [])
        self.assertIsNone(h.sent[0]["now_playing"]["artwork"])
        h.tick(0.25)
        h.tick(0.25)
        h.tick(0.5)
        self.assertEqual(len(h.sent), 1)

    def test_bytes_appearing_later_for_a_new_cover_are_sent(self):
        h = Harness()
        h.providers["now_playing"].covers = {}
        h.tick()
        h.providers["now_playing"].snap["artwork"] = ID_B
        h.providers["now_playing"].covers = {ID_B: COVER_B}
        h.tick(1.0)
        self.assertEqual(h.events[-2:], [("artwork", ID_B), ("state", ID_B)])

    def test_provider_without_artwork_bytes_nulls_the_artwork(self):
        providers = make_providers()
        providers["now_playing"] = FakeProvider(dict(FakeNowPlaying().snap))
        h = Harness(providers)
        h.tick()
        self.assertIsNone(h.sent[0]["now_playing"]["artwork"])
        self.assertEqual(h.artworks, [])

    def test_artwork_bytes_raising_nulls_the_artwork(self):
        h = Harness()

        def boom(_id):
            raise RuntimeError("gone")
        h.providers["now_playing"].artwork_bytes = boom
        h.tick()
        self.assertIsNone(h.sent[0]["now_playing"]["artwork"])
        self.assertEqual(len(h.sent), 1)
        self.assertEqual(h.artworks, [])

    def test_unencodable_cover_is_dropped_and_logged_once(self):
        calls = []

        def send_artwork(artwork_id, image):
            calls.append(artwork_id)
            raise ValueError("MEDIA_ARTWORK too large")
        h = Harness(send_artwork=send_artwork)
        h.tick()
        self.assertIsNone(h.sent[0]["now_playing"]["artwork"])
        self.assertEqual(h.sent[0]["now_playing"]["title"], "UN BESO")
        for _ in range(5):
            h.tick(1.0)
        self.assertEqual(calls, [ID_A])
        self.assertEqual(len(h.sent), 1)
        self.assertEqual(len([line for line in h.logs if "artwork" in line]), 1)

    def test_socket_error_on_artwork_holds_the_state_and_retries(self):
        fail = [True]
        h = Harness()
        real = h._send_artwork

        def send_artwork(artwork_id, image):
            if fail[0]:
                raise OSError("connection reset")
            real(artwork_id, image)
        h.hub._send_artwork = send_artwork
        h.tick()
        self.assertEqual(h.sent, [])  # never a state that references a cover the device did not get
        h.tick(0.25)
        self.assertEqual(h.sent, [])
        self.assertEqual(len([line for line in h.logs if "send failed" in line]), 1)
        fail[0] = False
        h.tick(0.25)
        self.assertEqual(h.events, [("artwork", ID_A), ("state", ID_A)])

    def test_state_send_failure_after_the_artwork_does_not_resend_the_cover(self):
        h = Harness()
        fail = [True]
        real = h.hub._send

        def send(state):
            if fail[0]:
                raise OSError("connection reset")
            real(state)
        h.hub._send = send
        h.tick()
        self.assertEqual(h.artworks, [(ID_A, COVER_A)])
        fail[0] = False
        h.tick(0.25)
        self.assertEqual(h.artworks, [(ID_A, COVER_A)])
        self.assertEqual(h.events, [("artwork", ID_A), ("state", ID_A)])

    def test_artwork_with_a_notice(self):
        h = Harness()
        h.tick()
        h.providers["usb"].result = "usb_busy"
        h.providers["now_playing"].snap["artwork"] = ID_B
        h.providers["now_playing"].covers[ID_B] = COVER_B
        h.hub.handle({"id": "usb.eject", "drive": "E:"})
        h.tick()
        self.assertEqual(h.events[-2:], [("artwork", ID_B), ("state", ID_B)])
        self.assertEqual(h.sent[-1]["notice"], {"code": "usb_busy", "drive": "E:"})

    def test_artwork_change_alone_triggers_a_broadcast(self):
        h = Harness()
        h.tick()
        h.providers["now_playing"].snap["artwork"] = ID_B
        h.providers["now_playing"].covers[ID_B] = COVER_B
        h.tick(1.0)
        self.assertEqual(len(h.sent), 2)

    def test_the_state_passed_to_send_is_not_the_hubs_own(self):
        h = Harness()
        h.tick()
        h.sent[0]["now_playing"]["artwork"] = "mutated"
        h.tick(1.0)
        self.assertEqual(len(h.sent), 1)


class ThreadTest(unittest.TestCase):
    def make(self, **kw):
        providers = make_providers()
        sent = []
        events = []
        lock = threading.Lock()

        def send(state):
            with lock:
                sent.append(state)

        def com_init():
            events.append(("init", threading.get_ident()))
            return lambda: events.append(("uninit", threading.get_ident()))

        hub = ActionsHub(providers, send, poll_fast_s=0.01, poll_slow_s=0.02, refresh_s=30.0,
                         com_init=com_init, log=lambda _l: None, **kw)
        return hub, providers, sent, events

    def wait_for(self, predicate, timeout=3.0):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if predicate():
                return True
            time.sleep(0.005)
        return False

    def test_start_sends_first_state_and_stop_joins(self):
        hub, providers, sent, events = self.make()
        hub.start()
        try:
            self.assertTrue(self.wait_for(lambda: len(sent) >= 1))
        finally:
            started = time.monotonic()
            hub.stop()
        self.assertLess(time.monotonic() - started, 2.0)
        self.assertFalse(hub._thread.is_alive())
        self.assertEqual(sent[0]["v"], 1)

    def test_com_initialised_on_hub_thread_and_released_at_stop(self):
        hub, providers, sent, events = self.make(send_artwork=lambda _id, _data: None)
        hub.start()
        self.assertTrue(self.wait_for(lambda: len(sent) >= 1))
        hub.stop()
        self.assertEqual([e[0] for e in events], ["init", "uninit"])
        hub_thread = events[0][1]
        self.assertEqual(events[1][1], hub_thread)
        self.assertNotEqual(hub_thread, threading.get_ident())
        self.assertEqual(set(providers["audio"].snapshot_threads), {hub_thread})
        self.assertEqual(set(providers["brightness"].snapshot_threads), {hub_thread})
        self.assertEqual(set(providers["now_playing"].artwork_threads), {hub_thread})

    def test_handle_from_another_thread_runs_on_the_hub_thread(self):
        hub, providers, sent, events = self.make()
        hub.start()
        try:
            self.assertTrue(self.wait_for(lambda: len(sent) >= 1))
            caller = []
            t = threading.Thread(target=lambda: (caller.append(threading.get_ident()),
                                                 hub.handle({"id": "volume.set", "value": 0.3}),
                                                 hub.handle({"id": "brightness.set", "value": 0.2})))
            t.start()
            t.join()
            self.assertTrue(self.wait_for(lambda: providers["audio"].handled and providers["brightness"].handled))
        finally:
            hub.stop()
        hub_thread = events[0][1]
        self.assertEqual(providers["audio"].handle_threads, [hub_thread])
        self.assertEqual(providers["brightness"].handle_threads, [hub_thread])
        self.assertNotEqual(hub_thread, caller[0])

    def test_handle_returns_without_executing_inline(self):
        hub, providers, sent, events = self.make()
        hub.handle({"id": "volume.set", "value": 0.3})  # not started: queued only
        self.assertEqual(providers["audio"].handled, [])

    def test_handle_wakes_the_hub_and_triggers_a_broadcast(self):
        providers = make_providers()
        sent = []
        hub = ActionsHub(providers, sent.append, poll_fast_s=60.0, poll_slow_s=60.0, refresh_s=600.0,
                         com_init=lambda: None, log=lambda _l: None)
        hub.start()
        try:
            self.assertTrue(self.wait_for(lambda: len(sent) == 1))
            providers["audio"].snap["volume"] = 0.8
            hub.handle({"id": "volume.set", "value": 0.8})
            self.assertTrue(self.wait_for(lambda: len(sent) == 2))
            self.assertEqual(sent[1]["audio"]["volume"], 0.8)
        finally:
            hub.stop()

    def test_handle_after_stop_is_dropped(self):
        hub, providers, sent, events = self.make()
        hub.start()
        hub.stop()
        hub.handle({"id": "volume.set", "value": 0.3})
        time.sleep(0.05)
        self.assertEqual(providers["audio"].handled, [])

    def test_no_state_sent_after_stop(self):
        hub, providers, sent, events = self.make()
        hub.start()
        self.assertTrue(self.wait_for(lambda: len(sent) >= 1))
        hub.stop()
        count = len(sent)
        providers["audio"].snap["volume"] = 0.1
        time.sleep(0.1)
        self.assertEqual(len(sent), count)

    def test_stop_without_start_and_double_stop(self):
        hub, *_ = self.make()
        hub.stop()
        hub.stop()

    def test_com_init_returning_none_is_fine(self):
        providers = make_providers()
        sent = []
        hub = ActionsHub(providers, sent.append, poll_fast_s=0.01, poll_slow_s=0.02,
                         com_init=lambda: None, log=lambda _l: None)
        hub.start()
        self.assertTrue(self.wait_for(lambda: len(sent) >= 1))
        hub.stop()


ICON_1 = "1" * 40
ICON_2 = "2" * 40
PNG_1 = b"\x89PNG-icon-1"
PNG_2 = b"\x89PNG-icon-2"


class FakeContext(FakeProvider):
    """context stand-in with an icon: `images` maps an icon id to its PNG (what artwork_bytes gives)."""

    def __init__(self, icon=ICON_1, images=None):
        super().__init__({"available": True, "app": "Illustrator", "profile": "illustrator", "buttons": [],
                          "icon": icon})
        self.images = dict(images) if images is not None else {ICON_1: PNG_1, ICON_2: PNG_2}
        self.artwork_requests = []

    def artwork_bytes(self, icon_id):
        self.artwork_requests.append(icon_id)
        return self.images.get(icon_id)


class IconArtworkTest(unittest.TestCase):
    def harness(self, **kw):
        providers = make_providers()
        providers["context"] = FakeContext()
        providers["now_playing"].snap["artwork"] = None
        return Harness(providers, **kw)

    def icon_events(self, h):
        return [e for e in h.events if e[0] == "artwork"]

    def test_icon_is_sent_before_the_first_state_that_references_it(self):
        h = self.harness()
        h.tick()
        self.assertEqual(h.events, [("artwork", ICON_1), ("state", None)])
        self.assertEqual(h.artworks, [(ICON_1, PNG_1)])
        self.assertEqual(h.sent[0]["context"]["icon"], ICON_1)

    def test_the_image_is_asked_to_the_context_provider_not_to_now_playing(self):
        h = self.harness()
        h.tick()
        self.assertEqual(h.providers["context"].artwork_requests, [ICON_1])
        self.assertEqual(h.providers["now_playing"].artwork_requests, [])

    def test_an_unchanged_icon_is_not_sent_again(self):
        h = self.harness()
        h.tick()
        for _ in range(10):
            h.tick(1.0)
        h.tick(30.0)  # periodic refresh: the state again, not the icon
        self.assertEqual(h.artworks, [(ICON_1, PNG_1)])
        self.assertEqual(len(h.sent), 2)

    def test_a_new_icon_is_sent_when_context_icon_changes(self):
        h = self.harness()
        h.tick()
        h.providers["context"].snap["icon"] = ICON_2
        h.tick(1.0)
        self.assertEqual(h.events, [("artwork", ICON_1), ("state", None), ("artwork", ICON_2), ("state", None)])
        self.assertEqual(h.sent[-1]["context"]["icon"], ICON_2)

    def test_going_back_to_a_previous_app_sends_its_icon_again(self):
        # the device's image cache is small and shared with the covers: an icon is not assumed to be still there
        h = self.harness()
        h.tick()
        h.providers["context"].snap["icon"] = ICON_2
        h.tick(1.0)
        h.providers["context"].snap["icon"] = ICON_1
        h.tick(1.0)
        self.assertEqual([a for a, _ in h.artworks], [ICON_1, ICON_2, ICON_1])

    def test_icon_then_none_then_the_same_icon_sends_it_again(self):
        h = self.harness()
        h.tick()
        h.providers["context"].snap["icon"] = None
        h.tick(1.0)
        self.assertIsNone(h.sent[-1]["context"]["icon"])
        h.providers["context"].snap["icon"] = ICON_1
        h.tick(1.0)
        self.assertEqual([a for a, _ in h.artworks], [ICON_1, ICON_1])

    def test_no_icon_sends_nothing(self):
        h = self.harness()
        h.providers["context"].snap["icon"] = None
        h.tick()
        self.assertEqual(h.artworks, [])
        self.assertIsNone(h.sent[0]["context"]["icon"])

    def test_a_context_without_an_icon_field_or_unavailable_is_untouched(self):
        h = Harness()  # the default fake context has no "icon"
        h.tick()
        self.assertNotIn("icon", h.sent[0]["context"])
        h2 = self.harness()
        h2.providers["context"].snap = {"available": False}
        h2.tick()
        self.assertEqual(h2.sent[0]["context"], {"available": False})
        self.assertEqual(h2.artworks, [])

    def test_cover_and_icon_are_both_sent_cover_first(self):
        providers = make_providers()
        providers["context"] = FakeContext()
        h = Harness(providers)  # now_playing has the cover ID_A
        h.tick()
        self.assertEqual(h.events, [("artwork", ID_A), ("artwork", ICON_1), ("state", ID_A)])

    def test_a_change_of_icon_alone_triggers_a_broadcast(self):
        h = self.harness()
        h.tick()
        count = len(h.sent)
        h.providers["context"].snap["icon"] = ICON_2
        h.tick(0.25)
        self.assertEqual(len(h.sent), count + 1)

    def test_missing_bytes_null_the_icon_without_resending_every_tick(self):
        h = self.harness()
        h.providers["context"].images = {}
        h.tick()
        self.assertEqual(h.artworks, [])
        self.assertIsNone(h.sent[0]["context"]["icon"])
        h.tick(1.0)
        self.assertEqual(len(h.sent), 1)

    def test_without_send_artwork_the_state_never_references_an_icon(self):
        h = self.harness(send_artwork=None)
        h.tick()
        self.assertIsNone(h.sent[0]["context"]["icon"])
        self.assertEqual(h.providers["context"].artwork_requests, [])

    def test_artwork_bytes_raising_nulls_the_icon(self):
        h = self.harness()

        def boom(_id):
            raise RuntimeError("x")
        h.providers["context"].artwork_bytes = boom
        h.tick()
        self.assertIsNone(h.sent[0]["context"]["icon"])
        self.assertEqual(h.artworks, [])

    def test_unencodable_icon_is_dropped_and_not_retried(self):
        calls = []

        def send_artwork(artwork_id, image):
            calls.append(artwork_id)
            raise ValueError("too big")
        h = self.harness(send_artwork=send_artwork)
        h.tick()
        self.assertIsNone(h.sent[0]["context"]["icon"])
        h.tick(1.0)
        h.tick(1.0)
        self.assertEqual(calls, [ICON_1])

    def test_socket_error_on_the_icon_holds_the_state_and_retries(self):
        h = self.harness()
        real = h._send_artwork
        fail = [True]

        def send_artwork(artwork_id, image):
            if fail[0]:
                raise OSError("closed")
            real(artwork_id, image)
        h.hub._send_artwork = send_artwork
        h.tick()
        self.assertEqual(h.sent, [])
        fail[0] = False
        h.tick(1.0)
        self.assertEqual(h.events, [("artwork", ICON_1), ("state", None)])

    def test_cover_behaviour_is_unchanged_next_to_an_icon(self):
        providers = make_providers()
        providers["context"] = FakeContext()
        providers["now_playing"].covers[ID_B] = COVER_B
        h = Harness(providers)
        h.tick()
        providers["now_playing"].snap["artwork"] = ID_B
        h.tick(1.0)
        providers["now_playing"].snap["artwork"] = ID_A
        h.tick(1.0)
        covers = [a for a, _ in h.artworks if a in (ID_A, ID_B)]
        self.assertEqual(covers, [ID_A, ID_B, ID_A])
        self.assertEqual([a for a, _ in h.artworks if a == ICON_1], [ICON_1])


class ContextBarThroughTheHubTest(unittest.TestCase):
    """The real ContextProvider behind the hub, with a fake foreground and a fake key sender (nothing is typed)."""

    class Tracker:
        def __init__(self):
            self.app = None

        def current(self):
            return self.app

    def setUp(self):
        from actions.context import ContextProvider
        from actions.foreground import ForegroundApp
        self.ForegroundApp = ForegroundApp
        self.tracker = self.Tracker()
        self.pressed = []
        providers = make_providers()
        providers["context"] = ContextProvider(tracker=self.tracker, send_shortcut=self._press, log=lambda _l: None)
        self.h = Harness(providers)

    def _press(self, shortcut):
        self.pressed.append(shortcut)
        return True

    def front(self, exe, window_class="Cls", title="Window"):
        self.tracker.app = self.ForegroundApp(exe, window_class, title, 1)

    def test_context_section_follows_the_foreground_app(self):
        self.h.tick()
        self.assertEqual(self.h.sent[0]["context"], {"available": False})
        self.front("POWERPNT.EXE")
        self.h.tick(0.25)
        ctx = self.h.sent[-1]["context"]
        self.assertEqual((ctx["available"], ctx["app"], ctx["profile"]), (True, "PowerPoint", "powerpoint"))
        self.assertEqual(ctx["buttons"][0], {"id": "ppt.slideshow", "icon": "slideshow", "label": "Diaporama"})
        self.front("chrome.exe")
        self.h.tick(0.25)
        self.assertEqual(self.h.sent[-1]["context"]["profile"], "browser")

    def test_press_of_a_button_of_the_active_profile_sends_its_shortcut(self):
        self.front("POWERPNT.EXE")
        self.h.tick()
        self.h.hub.handle({"id": "context.press", "button": "ppt.next"})
        self.h.hub._tick(self.h.clock.t)
        self.assertEqual(self.pressed, ["Right"])
        self.assertTrue(all("notice" not in s for s in self.h.sent))

    def test_press_after_the_foreground_changed_is_ignored(self):
        self.front("POWERPNT.EXE")
        self.h.tick()
        self.front("chrome.exe")  # the device has not redrawn yet
        self.h.hub.handle({"id": "context.press", "button": "ppt.next"})
        self.h.hub._tick(self.h.clock.t)
        self.assertEqual(self.pressed, [])

    def test_blocked_press_gives_an_action_failed_notice(self):
        self.front("chrome.exe")
        self.h.tick()
        self.h.providers["context"]._send_shortcut = lambda _s: False
        self.h.hub.handle({"id": "context.press", "button": "web.reload"})
        self.h.hub._tick(self.h.clock.t)
        self.assertEqual(self.h.sent[-1]["notice"], {"code": "action_failed"})


class ContextLangThroughTheHubTest(unittest.TestCase):
    def setUp(self):
        from actions.context import ContextProvider
        from actions.foreground import ForegroundApp

        class Tracker:
            def current(self):
                return ForegroundApp("POWERPNT.EXE", "Cls", "Window", 1)

        providers = make_providers()
        providers["context"] = ContextProvider(lang="en", tracker=Tracker(), send_shortcut=lambda _s: True,
                                               log=lambda _l: None)
        self.h = Harness(providers)

    def test_the_bar_is_built_in_the_language_given_to_the_provider(self):
        self.h.tick()
        self.assertEqual(self.h.sent[0]["context"]["buttons"][0]["label"], "Slideshow")

    def test_context_lang_is_routed_to_the_provider_and_broadcast_at_once(self):
        self.h.tick()
        count = len(self.h.sent)
        self.h.hub.handle({"id": "context.lang", "lang": "fr"})
        self.h.hub._tick(self.h.clock.t)  # same instant: only the action forces the poll
        self.assertEqual(len(self.h.sent), count + 1)
        self.assertEqual(self.h.sent[-1]["context"]["buttons"][0]["label"], "Diaporama")
        self.assertNotIn("notice", self.h.sent[-1])


class DefaultProvidersTest(unittest.TestCase):
    def test_the_context_provider_gets_the_language(self):
        for lang in ("en", "fr"):
            with self.subTest(lang):
                providers = default_providers(lambda _l: None, lang=lang)
                self.assertEqual(providers["context"].lang, lang)

    def test_the_language_defaults_to_french(self):
        self.assertEqual(default_providers(lambda _l: None)["context"].lang, "fr")

    def test_builds_the_known_provider_names_without_calling_any_action(self):
        logs = []
        providers = default_providers(logs.append)
        self.assertTrue(set(providers) <= {"clock", "battery", "audio", "media", "brightness", "radios",
                                           "wifi_info", "bt_info", "usb", "now_playing", "context"})
        for provider in providers.values():
            self.assertTrue(callable(provider.snapshot) and callable(provider.handle))

    def test_import_error_leaves_the_provider_out(self):
        import builtins
        real_import = builtins.__import__

        def fake_import(name, *args, **kwargs):
            if name.startswith("pycaw"):
                raise ImportError("no pycaw")
            return real_import(name, *args, **kwargs)

        logs = []
        builtins.__import__ = fake_import
        try:
            providers = default_providers(logs.append)
        finally:
            builtins.__import__ = real_import
        self.assertNotIn("audio", providers)
        self.assertIn("clock", providers)
        self.assertTrue(any("audio" in line for line in logs))
        h = Harness(providers)
        h.tick()
        self.assertEqual(h.sent[0]["audio"], {"available": False})

    def test_os_error_leaves_the_provider_out(self):
        import actions.usb as usb_mod
        real = usb_mod.UsbProvider

        def boom(*a, **k):
            raise OSError("no setupapi")
        usb_mod.UsbProvider = boom
        try:
            providers = default_providers(lambda _l: None)
        finally:
            usb_mod.UsbProvider = real
        self.assertNotIn("usb", providers)


class ComInitTest(unittest.TestCase):
    def test_default_com_init_is_balanced_on_a_scratch_thread(self):
        results = []

        def work():
            uninit = hub_mod._com_init()
            results.append(uninit)
            if uninit is not None:
                uninit()
        t = threading.Thread(target=work)
        t.start()
        t.join()
        self.assertEqual(len(results), 1)


if __name__ == "__main__":
    unittest.main()
