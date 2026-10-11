import ctypes
import time
import unittest

from actions import base, battery, clock, media


class BaseTest(unittest.TestCase):
    def test_provider_error_is_an_exception(self):
        self.assertTrue(issubclass(base.ProviderError, Exception))

    def test_providers_satisfy_the_protocol_shape(self):
        for provider in (clock.ClockProvider(), battery.BatteryProvider(), media.MediaProvider()):
            self.assertTrue(callable(provider.snapshot))
            self.assertTrue(callable(provider.handle))


class ClockTest(unittest.TestCase):
    def test_snapshot_uses_injected_time_and_offset(self):
        provider = clock.ClockProvider(now=lambda: 1760185920.1239, utc_offset_min=lambda: 120)
        self.assertEqual(provider.snapshot(), {"epoch_ms": 1760185920123, "utc_offset_min": 120})

    def test_snapshot_negative_offset(self):
        provider = clock.ClockProvider(now=lambda: 1.0, utc_offset_min=lambda: -300)
        self.assertEqual(provider.snapshot(), {"epoch_ms": 1000, "utc_offset_min": -300})

    def test_default_offset_is_whole_minutes_within_range(self):
        snap = clock.ClockProvider().snapshot()
        self.assertIsInstance(snap["utc_offset_min"], int)
        self.assertTrue(-14 * 60 <= snap["utc_offset_min"] <= 14 * 60)
        self.assertLess(abs(snap["epoch_ms"] - time.time() * 1000), 5000)

    def test_handle_ignores_actions(self):
        self.assertIsNone(clock.ClockProvider().handle({"id": "clock.x"}))


def status(ac=1, flag=0, percent=50):
    result = battery.SYSTEM_POWER_STATUS()
    result.ACLineStatus = ac
    result.BatteryFlag = flag
    result.BatteryLifePercent = percent
    return result


class BatteryTest(unittest.TestCase):
    def snap(self, **kwargs):
        return battery.BatteryProvider(read=lambda: status(**kwargs)).snapshot()

    def test_struct_size_matches_winbase_h(self):
        self.assertEqual(ctypes.sizeof(battery.SYSTEM_POWER_STATUS), 12)

    def test_discharging(self):
        self.assertEqual(self.snap(ac=0, flag=1, percent=76), {"available": True, "percent": 76, "charging": False})

    def test_charging_flag(self):
        self.assertEqual(self.snap(ac=1, flag=8 | 1, percent=40), {"available": True, "percent": 40, "charging": True})

    def test_on_ac_not_charging_when_full(self):
        self.assertEqual(self.snap(ac=1, flag=1, percent=100), {"available": True, "percent": 100, "charging": False})

    def test_no_battery_flag_means_unavailable(self):
        self.assertEqual(self.snap(ac=1, flag=128, percent=255), {"available": False})

    def test_no_battery_flag_combined_with_other_bits_is_unavailable(self):
        self.assertEqual(self.snap(ac=1, flag=128 | 4, percent=50), {"available": False})

    def test_unknown_percent_is_unavailable(self):
        self.assertEqual(self.snap(ac=0, flag=255, percent=255), {"available": False})
        self.assertEqual(self.snap(ac=0, flag=1, percent=255), {"available": False})

    def test_percent_above_100_other_than_unknown_is_clamped(self):
        self.assertEqual(self.snap(ac=0, flag=1, percent=101)["percent"], 100)

    def test_read_failure_raises_provider_error(self):
        def failing():
            raise base.ProviderError("GetSystemPowerStatus failed")
        with self.assertRaises(base.ProviderError):
            battery.BatteryProvider(read=failing).snapshot()

    def test_default_reader_raises_provider_error_when_api_fails(self):
        class FakeApi:
            def __call__(self, ptr):
                return 0
        with self.assertRaises(base.ProviderError):
            battery.read_power_status(FakeApi())

    def test_default_reader_returns_struct(self):
        def api(ptr):
            ptr._obj.BatteryLifePercent = 33
            return 1
        self.assertEqual(battery.read_power_status(api).BatteryLifePercent, 33)

    def test_handle_ignores_actions(self):
        self.assertIsNone(battery.BatteryProvider(read=lambda: status()).handle({"id": "x"}))

    def test_real_read_only_smoke(self):
        snap = battery.BatteryProvider().snapshot()
        self.assertIn("available", snap)
        if snap["available"]:
            self.assertTrue(0 <= snap["percent"] <= 100)
            self.assertIsInstance(snap["charging"], bool)


class FakeSendInput:
    def __init__(self, result=None):
        self.calls = []
        self.result = result

    def __call__(self, count, array, size):
        events = [(array[i].type, array[i].u.ki.wVk, array[i].u.ki.wScan, array[i].u.ki.dwFlags,
                   array[i].u.ki.time, array[i].u.ki.dwExtraInfo) for i in range(count)]
        self.calls.append((count, size, events))
        return count if self.result is None else self.result


class MediaTest(unittest.TestCase):
    def test_input_struct_sizes_on_x64(self):
        self.assertEqual(ctypes.sizeof(ctypes.c_void_p), 8)
        self.assertEqual(ctypes.sizeof(media.INPUT), 40)
        self.assertEqual(ctypes.sizeof(media.KEYBDINPUT), 24)

    def test_virtual_key_codes(self):
        self.assertEqual(media.VK_MEDIA_PLAY_PAUSE, 0xB3)
        self.assertEqual(media.VK_MEDIA_NEXT_TRACK, 0xB0)
        self.assertEqual(media.VK_MEDIA_PREV_TRACK, 0xB1)
        self.assertEqual(media.KEYEVENTF_KEYUP, 0x0002)
        self.assertEqual(media.INPUT_KEYBOARD, 1)

    def press(self, action_id):
        fake = FakeSendInput()
        result = media.MediaProvider(send_input=fake).handle({"id": action_id})
        return result, fake

    def test_each_action_sends_one_down_up_pair_with_the_right_key(self):
        for action_id, vk in (("media.play_pause", 0xB3), ("media.next", 0xB0), ("media.previous", 0xB1)):
            with self.subTest(action_id):
                result, fake = self.press(action_id)
                self.assertIsNone(result)
                self.assertEqual(len(fake.calls), 1)
                count, size, events = fake.calls[0]
                self.assertEqual(count, 2)
                self.assertEqual(size, 40)
                self.assertEqual(events, [(1, vk, 0, 0, 0, 0), (1, vk, 0, 2, 0, 0)])

    def test_unknown_action_sends_nothing_and_reports_failure(self):
        result, fake = self.press("media.stop")
        self.assertEqual(result, "action_failed")
        self.assertEqual(fake.calls, [])

    def test_action_without_id_sends_nothing(self):
        fake = FakeSendInput()
        self.assertEqual(media.MediaProvider(send_input=fake).handle({}), "action_failed")
        self.assertEqual(fake.calls, [])

    def test_partial_injection_reports_failure(self):
        fake = FakeSendInput(result=0)
        self.assertEqual(media.MediaProvider(send_input=fake).handle({"id": "media.next"}), "action_failed")

    def test_snapshot_is_available(self):
        self.assertEqual(media.MediaProvider(send_input=FakeSendInput()).snapshot(), {"available": True})

    def test_constructing_with_default_sender_does_not_send(self):
        provider = media.MediaProvider()
        self.assertEqual(provider.snapshot(), {"available": True})


if __name__ == "__main__":
    unittest.main()
