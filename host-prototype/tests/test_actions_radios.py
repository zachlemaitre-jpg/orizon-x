import importlib.util
import threading
import unittest

from actions import radios, winrt_call
from actions.base import ProviderError
from actions.radios import RadioInfo, RadiosProvider, merge_radio_state

HAS_WINRT = importlib.util.find_spec("winrt") is not None and \
    importlib.util.find_spec("winrt.windows.devices.radios") is not None


class FakeRadiosApi:
    """In-memory radios: set_state really changes the listed state (unless denied)."""

    def __init__(self, radios_list, access=True, allow_set=True):
        self.radios = list(radios_list)
        self.access = access
        self.allow_set = allow_set
        self.access_calls = 0
        self.set_calls = []
        self.fail_list = None
        self.fail_set = None

    def request_access(self):
        self.access_calls += 1
        return self.access

    def list_radios(self):
        if self.fail_list:
            raise self.fail_list
        return list(self.radios)

    def set_state(self, radio, on):
        if self.fail_set:
            raise self.fail_set
        self.set_calls.append((radio.kind, radio.name, on))
        if not self.allow_set:
            return False
        self.radios[radio.index] = RadioInfo(radio.kind, radio.name, "on" if on else "off", radio.index)
        return True

    def state_of(self, kind):
        return [r.state for r in self.radios if r.kind == kind]


def api_with(*specs, **kw):
    return FakeRadiosApi([RadioInfo(kind, name, state, i) for i, (kind, name, state) in enumerate(specs)], **kw)


def both_on(**kw):
    return api_with(("bluetooth", "Bluetooth", "on"), ("wifi", "Wi-Fi", "on"), **kw)


class SnapshotTest(unittest.TestCase):
    def test_both_radios_on(self):
        snap = RadiosProvider(both_on()).snapshot()
        self.assertEqual(snap, {"available": True,
                                "wifi": {"available": True, "on": True},
                                "bluetooth": {"available": True, "on": True},
                                "airplane": {"available": True, "on": False}})

    def test_missing_bluetooth_radio_is_unavailable(self):
        snap = RadiosProvider(api_with(("wifi", "Wi-Fi", "off"))).snapshot()
        self.assertEqual(snap["wifi"], {"available": True, "on": False})
        self.assertEqual(snap["bluetooth"], {"available": False})
        self.assertEqual(snap["airplane"], {"available": True, "on": False})

    def test_no_radio_at_all(self):
        snap = RadiosProvider(api_with()).snapshot()
        self.assertEqual(snap["wifi"], {"available": False})
        self.assertEqual(snap["bluetooth"], {"available": False})
        self.assertEqual(snap["airplane"], {"available": False})

    def test_disabled_radio_counts_as_off(self):
        snap = RadiosProvider(api_with(("wifi", "Wi-Fi", "disabled"))).snapshot()
        self.assertEqual(snap["wifi"], {"available": True, "on": False})

    def test_any_wifi_radio_on_means_on(self):
        snap = RadiosProvider(api_with(("wifi", "A", "off"), ("wifi", "B", "on"))).snapshot()
        self.assertTrue(snap["wifi"]["on"])

    def test_without_winrt_the_provider_is_unavailable(self):
        self.assertEqual(RadiosProvider(api=None).snapshot(), {"available": False})

    def test_listing_failure_is_a_provider_error(self):
        api = both_on()
        api.fail_list = OSError("boom")
        with self.assertRaises(ProviderError):
            RadiosProvider(api).snapshot()

    def test_snapshot_never_requests_access(self):
        api = both_on()
        RadiosProvider(api).snapshot()
        self.assertEqual(api.access_calls, 0)


class RadioSetTest(unittest.TestCase):
    def test_wifi_off_touches_only_wifi(self):
        api = both_on()
        provider = RadiosProvider(api)
        self.assertIsNone(provider.handle({"id": "wifi.set", "value": False}))
        self.assertEqual(api.set_calls, [("wifi", "Wi-Fi", False)])
        self.assertEqual(provider.snapshot()["wifi"], {"available": True, "on": False})
        self.assertTrue(provider.snapshot()["bluetooth"]["on"])

    def test_bluetooth_on(self):
        api = api_with(("bluetooth", "Bluetooth", "off"), ("wifi", "Wi-Fi", "on"))
        self.assertIsNone(RadiosProvider(api).handle({"id": "bluetooth.set", "value": True}))
        self.assertEqual(api.set_calls, [("bluetooth", "Bluetooth", True)])

    def test_already_in_the_wanted_state_changes_nothing(self):
        api = both_on()
        self.assertIsNone(RadiosProvider(api).handle({"id": "wifi.set", "value": True}))
        self.assertEqual(api.set_calls, [])

    def test_access_not_allowed_is_radio_denied(self):
        api = both_on(access=False)
        self.assertEqual(RadiosProvider(api).handle({"id": "wifi.set", "value": False}), "radio_denied")
        self.assertEqual(api.set_calls, [])

    def test_set_state_refused_is_radio_denied(self):
        api = both_on(allow_set=False)
        self.assertEqual(RadiosProvider(api).handle({"id": "bluetooth.set", "value": False}), "radio_denied")

    def test_value_must_be_a_bool(self):
        api = both_on()
        provider = RadiosProvider(api)
        for bad in (1, "false", None, 0.0):
            self.assertEqual(provider.handle({"id": "wifi.set", "value": bad}), "action_failed")
        self.assertEqual(provider.handle({"id": "wifi.set"}), "action_failed")
        self.assertEqual(api.set_calls, [])
        self.assertEqual(api.access_calls, 0)

    def test_unknown_id_is_logged_and_ignored(self):
        api = both_on()
        with self.assertLogs("orizonx.actions.radios", level="WARNING") as logs:
            self.assertIsNone(RadiosProvider(api).handle({"id": "wifi.toggle", "value": True}))
        self.assertIn("wifi.toggle", logs.output[0])
        self.assertEqual(api.set_calls, [])
        self.assertEqual(api.access_calls, 0)

    def test_no_radio_of_that_kind_fails(self):
        api = api_with(("wifi", "Wi-Fi", "on"))
        self.assertEqual(RadiosProvider(api).handle({"id": "bluetooth.set", "value": True}), "action_failed")

    def test_disabled_radio_cannot_be_switched(self):
        api = api_with(("wifi", "Wi-Fi", "disabled"))
        self.assertEqual(RadiosProvider(api).handle({"id": "wifi.set", "value": True}), "action_failed")
        self.assertEqual(api.set_calls, [])

    def test_every_radio_of_the_kind_is_switched(self):
        api = api_with(("wifi", "A", "on"), ("wifi", "B", "on"))
        self.assertIsNone(RadiosProvider(api).handle({"id": "wifi.set", "value": False}))
        self.assertEqual(api.state_of("wifi"), ["off", "off"])

    def test_winrt_error_is_action_failed(self):
        api = both_on()
        api.fail_set = OSError("0x80070005")
        self.assertEqual(RadiosProvider(api).handle({"id": "wifi.set", "value": False}), "action_failed")

    def test_timeout_is_action_failed(self):
        api = both_on()
        api.fail_set = winrt_call.WinRTCallError("timed out")
        self.assertEqual(RadiosProvider(api).handle({"id": "wifi.set", "value": False}), "action_failed")

    def test_without_winrt_actions_fail(self):
        self.assertEqual(RadiosProvider(api=None).handle({"id": "wifi.set", "value": False}), "action_failed")


class AirplaneTest(unittest.TestCase):
    def three(self, bt="off", wifi="on", mobile="on"):
        return api_with(("bluetooth", "Bluetooth", bt), ("wifi", "Wi-Fi", wifi), ("other", "Mobile", mobile))

    def test_airplane_on_turns_every_radio_off(self):
        api = self.three()
        provider = RadiosProvider(api)
        self.assertIsNone(provider.handle({"id": "airplane.set", "value": True}))
        self.assertEqual([r.state for r in api.radios], ["off", "off", "off"])
        self.assertEqual(sorted(api.set_calls), [("other", "Mobile", False), ("wifi", "Wi-Fi", False)])
        snap = provider.snapshot()
        self.assertEqual(snap["airplane"], {"available": True, "on": True})
        self.assertFalse(snap["wifi"]["on"])

    def test_airplane_off_restores_the_radios_that_were_on(self):
        api = self.three()
        provider = RadiosProvider(api)
        provider.handle({"id": "airplane.set", "value": True})
        api.set_calls.clear()
        self.assertIsNone(provider.handle({"id": "airplane.set", "value": False}))
        self.assertEqual([r.state for r in api.radios], ["off", "on", "on"])  # Bluetooth était éteint
        self.assertEqual(sorted(api.set_calls), [("other", "Mobile", True), ("wifi", "Wi-Fi", True)])
        self.assertEqual(provider.snapshot()["airplane"], {"available": True, "on": False})

    def test_airplane_on_twice_keeps_the_first_memory(self):
        api = self.three()
        provider = RadiosProvider(api)
        provider.handle({"id": "airplane.set", "value": True})
        self.assertIsNone(provider.handle({"id": "airplane.set", "value": True}))
        provider.handle({"id": "airplane.set", "value": False})
        self.assertEqual([r.state for r in api.radios], ["off", "on", "on"])

    def test_airplane_off_when_not_in_airplane_does_nothing(self):
        api = self.three()
        self.assertIsNone(RadiosProvider(api).handle({"id": "airplane.set", "value": False}))
        self.assertEqual(api.set_calls, [])
        self.assertEqual(api.access_calls, 0)

    def test_radio_switched_on_during_airplane_stays_on(self):
        api = self.three()
        provider = RadiosProvider(api)
        provider.handle({"id": "airplane.set", "value": True})
        self.assertIsNone(provider.handle({"id": "bluetooth.set", "value": True}))
        self.assertTrue(provider.snapshot()["airplane"]["on"])  # le mode avion reste actif
        provider.handle({"id": "airplane.set", "value": False})
        self.assertEqual([r.state for r in api.radios], ["on", "on", "on"])

    def test_airplane_access_denied(self):
        api = self.three()
        api.access = False
        provider = RadiosProvider(api)
        self.assertEqual(provider.handle({"id": "airplane.set", "value": True}), "radio_denied")
        self.assertEqual(api.set_calls, [])
        self.assertFalse(provider.snapshot()["airplane"]["on"])

    def test_restore_refused_keeps_airplane_for_a_retry(self):
        api = self.three()
        provider = RadiosProvider(api)
        provider.handle({"id": "airplane.set", "value": True})
        api.allow_set = False
        self.assertEqual(provider.handle({"id": "airplane.set", "value": False}), "radio_denied")
        self.assertTrue(provider.snapshot()["airplane"]["on"])
        api.allow_set = True
        self.assertIsNone(provider.handle({"id": "airplane.set", "value": False}))
        self.assertEqual([r.state for r in api.radios], ["off", "on", "on"])
        self.assertFalse(provider.snapshot()["airplane"]["on"])

    def test_restore_matches_radios_by_kind_and_name(self):
        api = api_with(("wifi", "A", "on"), ("wifi", "B", "off"))
        provider = RadiosProvider(api)
        provider.handle({"id": "airplane.set", "value": True})
        api.radios.reverse()  # l'ordre de Windows a changé
        api.radios = [RadioInfo(r.kind, r.name, r.state, i) for i, r in enumerate(api.radios)]
        provider.handle({"id": "airplane.set", "value": False})
        self.assertEqual({r.name: r.state for r in api.radios}, {"A": "on", "B": "off"})

    def test_airplane_value_must_be_a_bool(self):
        self.assertEqual(RadiosProvider(self.three()).handle({"id": "airplane.set", "value": "on"}),
                         "action_failed")

    def test_airplane_on_with_no_radio_fails(self):
        self.assertEqual(RadiosProvider(api_with()).handle({"id": "airplane.set", "value": True}),
                         "action_failed")


class MergeTest(unittest.TestCase):
    RADIOS = {"available": True, "wifi": {"available": True, "on": True},
              "bluetooth": {"available": True, "on": True}, "airplane": {"available": True, "on": False}}

    def test_full_merge_matches_the_spec_shape(self):
        merged = merge_radio_state(self.RADIOS, {"available": True, "ssid": "Maison", "signal": 72},
                                   {"available": True, "connected": ["Casque"]})
        self.assertEqual(merged, {"wifi": {"available": True, "on": True, "ssid": "Maison", "signal": 72},
                                  "bluetooth": {"available": True, "on": True, "connected": ["Casque"]},
                                  "airplane": {"available": True, "on": False}})

    def test_radio_off_hides_ssid_and_devices(self):
        radios = {"available": True, "wifi": {"available": True, "on": False},
                  "bluetooth": {"available": True, "on": False}, "airplane": {"available": True, "on": True}}
        merged = merge_radio_state(radios, {"available": True, "ssid": "Maison"},
                                   {"available": True, "connected": ["Casque"]})
        self.assertEqual(merged["wifi"]["ssid"], "")
        self.assertIsNone(merged["wifi"]["signal"])
        self.assertEqual(merged["bluetooth"]["connected"], [])

    def test_unavailable_radios_make_the_three_tiles_unavailable(self):
        merged = merge_radio_state({"available": False}, {"available": True, "ssid": "Maison"},
                                   {"available": True, "connected": ["Casque"]})
        self.assertEqual(merged, {"wifi": {"available": False}, "bluetooth": {"available": False},
                                  "airplane": {"available": False}})

    def test_unavailable_or_missing_info_gives_empty_values(self):
        for wifi_info, bt_info in (({"available": False}, {"available": False}), (None, None)):
            merged = merge_radio_state(self.RADIOS, wifi_info, bt_info)
            self.assertEqual(merged["wifi"], {"available": True, "on": True, "ssid": "", "signal": None})
            self.assertEqual(merged["bluetooth"], {"available": True, "on": True, "connected": []})

    def test_signal_none_when_not_connected_or_missing(self):
        for info in ({"available": True, "ssid": "", "signal": None}, {"available": True, "ssid": ""}):
            self.assertIsNone(merge_radio_state(self.RADIOS, info, None)["wifi"]["signal"])

    def test_signal_is_an_int_in_range(self):
        for raw, expected in ((0, 0), (100, 100), (140, 100), (-3, 0), (55.9, 55), ("80", None), (True, None),
                              (float("nan"), None)):
            merged = merge_radio_state(self.RADIOS, {"available": True, "ssid": "x", "signal": raw}, None)
            self.assertEqual(merged["wifi"]["signal"], expected, raw)
            self.assertIsInstance(merged["wifi"]["signal"], (int, type(None)))

    def test_wifi_without_radio_has_no_signal(self):
        radios = dict(self.RADIOS, wifi={"available": False})
        self.assertEqual(merge_radio_state(radios, {"available": True, "ssid": "x", "signal": 9}, None)["wifi"],
                         {"available": False})

    def test_missing_radio_kind_stays_unavailable(self):
        radios = dict(self.RADIOS, bluetooth={"available": False})
        merged = merge_radio_state(radios, None, {"available": True, "connected": ["Casque"]})
        self.assertEqual(merged["bluetooth"], {"available": False})

    def test_merge_does_not_alias_the_inputs(self):
        bt_info = {"available": True, "connected": ["Casque"]}
        merged = merge_radio_state(self.RADIOS, None, bt_info)
        merged["bluetooth"]["connected"].append("x")
        merged["wifi"]["on"] = False
        self.assertEqual(bt_info["connected"], ["Casque"])
        self.assertTrue(self.RADIOS["wifi"]["on"])


class KindNameTest(unittest.TestCase):
    def test_winrt_kinds(self):
        # RadioKind : OTHER 0, WI_FI 1, MOBILE_BROADBAND 2, BLUETOOTH 3, FM 4
        self.assertEqual([radios.kind_name(k) for k in range(5)], ["other", "wifi", "mobile", "bluetooth", "fm"])
        self.assertEqual(radios.kind_name(42), "other")

    def test_winrt_states(self):
        # RadioState : UNKNOWN 0, ON 1, OFF 2, DISABLED 3
        self.assertEqual([radios.state_name(s) for s in range(4)], ["unknown", "on", "off", "disabled"])
        self.assertEqual(radios.state_name(9), "unknown")


class FakeOp:
    """IAsyncOperation stand-in: wait() returns `status`, get_results() returns `result` or raises."""

    def __init__(self, status, result=None, error=None):
        self.status, self.result, self.error = status, result, error
        self.waited = None
        self.canceled = False

    def wait(self, timeout):
        self.waited = timeout
        return self.status

    def cancel(self):
        self.canceled = True

    def get_results(self):
        if self.error:
            raise self.error
        return self.result


class WaitOpTest(unittest.TestCase):
    def test_completed_returns_the_results(self):
        op = FakeOp(winrt_call.COMPLETED, result=[1, 2])
        self.assertEqual(winrt_call.wait_op(op, 1.5), [1, 2])
        self.assertEqual(op.waited, 1.5)
        self.assertFalse(op.canceled)

    def test_still_running_after_the_timeout_is_canceled(self):
        op = FakeOp(winrt_call.STARTED)
        with self.assertRaises(winrt_call.WinRTCallError):
            winrt_call.wait_op(op, 0.5)
        self.assertTrue(op.canceled)

    def test_canceled_is_an_error(self):
        with self.assertRaises(winrt_call.WinRTCallError):
            winrt_call.wait_op(FakeOp(winrt_call.CANCELED), 0.5)

    def test_error_status_raises_the_winrt_error(self):
        with self.assertRaises(OSError):
            winrt_call.wait_op(FakeOp(winrt_call.ERROR, error=OSError("0x8007001F")), 0.5)

    def test_call_error_is_a_provider_error(self):
        self.assertTrue(issubclass(winrt_call.WinRTCallError, ProviderError))


class WorkerTest(unittest.TestCase):
    def test_calls_run_on_one_long_lived_thread_initialised_once(self):
        inits = []
        worker = winrt_call.WinRTWorker(coinit=lambda: inits.append(threading.get_ident()))
        try:
            idents = {worker.run(threading.get_ident, 1.0) for _ in range(3)}
            # depuis un autre thread qui se termine : même thread de travail
            box = []
            t = threading.Thread(target=lambda: box.append(worker.run(threading.get_ident, 1.0)))
            t.start()
            t.join()
            idents.add(box[0])
        finally:
            worker.shutdown()
        self.assertEqual(len(idents), 1)
        self.assertNotIn(threading.get_ident(), idents)
        self.assertEqual(inits, list(idents))

    def test_exceptions_reach_the_caller(self):
        worker = winrt_call.WinRTWorker(coinit=lambda: None)
        try:
            with self.assertRaises(ValueError):
                worker.run(lambda: (_ for _ in ()).throw(ValueError("x")), 1.0)
        finally:
            worker.shutdown()

    def test_a_stuck_call_is_bounded(self):
        release = threading.Event()
        worker = winrt_call.WinRTWorker(coinit=lambda: None, grace_s=0.05)
        try:
            with self.assertRaises(winrt_call.WinRTCallError):
                worker.run(lambda: release.wait(5), 0.05)
        finally:
            release.set()
            worker.shutdown()


@unittest.skipUnless(HAS_WINRT, "winrt Windows.Devices.Radios not installed")
class RealRadiosReadOnlyTest(unittest.TestCase):
    """Read-only: lists the radios, never changes them."""

    def test_list_radios(self):
        listed = radios.WinRTRadiosApi().list_radios()
        for r in listed:
            self.assertIn(r.kind, ("wifi", "bluetooth", "mobile", "fm", "other"))
            self.assertIn(r.state, ("on", "off", "disabled", "unknown"))
            self.assertIsInstance(r.name, str)
        self.assertEqual([r.index for r in listed], list(range(len(listed))))

    def test_snapshot_shape(self):
        snap = RadiosProvider().snapshot()
        self.assertTrue(snap["available"])
        for key in ("wifi", "bluetooth", "airplane"):
            self.assertIn("available", snap[key])


if __name__ == "__main__":
    unittest.main()
