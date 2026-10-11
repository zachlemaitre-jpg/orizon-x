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
        "wifi_info": FakeProvider({"available": True, "ssid": "Maison"}),
        "bt_info": FakeProvider({"available": True, "connected": ["Casque"]}),
        "usb": FakeProvider({"available": True, "drives": [
            {"drive": "E:", "label": "KINGSTON", "free_bytes": 1, "total_bytes": 2}]}),
    }


class Harness:
    """A hub driven step by step (no thread) with a fake clock."""

    def __init__(self, providers=None, **kw):
        self.providers = providers if providers is not None else make_providers()
        self.clock = FakeClock()
        self.sent = []
        self.logs = []
        self.hub = ActionsHub(self.providers, self.sent.append, clock=self.clock, log=self.logs.append, **kw)

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
            "wifi": {"available": True, "on": True, "ssid": "Maison"},
            "bluetooth": {"available": True, "on": True, "connected": ["Casque"]},
            "airplane": {"available": True, "on": False},
            "usb": [{"drive": "E:", "label": "KINGSTON", "free_bytes": 1, "total_bytes": 2}],
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
        self.assertEqual(h.sent[0]["wifi"], {"available": True, "on": False, "ssid": ""})
        self.assertEqual(h.sent[0]["bluetooth"], {"available": True, "on": False, "connected": []})

    def test_radio_merge_with_info_providers_missing(self):
        providers = make_providers()
        del providers["wifi_info"], providers["bt_info"]
        h = Harness(providers)
        h.tick()
        self.assertEqual(h.sent[0]["wifi"], {"available": True, "on": True, "ssid": ""})
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
        for key in ("clock", "battery", "audio", "media", "brightness", "wifi", "bluetooth", "airplane"):
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
        self.assertEqual(h.sent[0]["wifi"], {"available": True, "on": True, "ssid": ""})

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
        hub, providers, sent, events = self.make()
        hub.start()
        self.assertTrue(self.wait_for(lambda: len(sent) >= 1))
        hub.stop()
        self.assertEqual([e[0] for e in events], ["init", "uninit"])
        hub_thread = events[0][1]
        self.assertEqual(events[1][1], hub_thread)
        self.assertNotEqual(hub_thread, threading.get_ident())
        self.assertEqual(set(providers["audio"].snapshot_threads), {hub_thread})
        self.assertEqual(set(providers["brightness"].snapshot_threads), {hub_thread})

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


class DefaultProvidersTest(unittest.TestCase):
    def test_builds_the_known_provider_names_without_calling_any_action(self):
        logs = []
        providers = default_providers(logs.append)
        self.assertTrue(set(providers) <= {"clock", "battery", "audio", "media", "brightness", "radios",
                                           "wifi_info", "bt_info", "usb"})
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
