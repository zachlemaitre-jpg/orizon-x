import unittest

from actions.audio import AudioProvider


class FakeEndpoint:
    def __init__(self, volume=0.5, muted=False):
        self.volume = volume
        self.muted = muted
        self.fail = None  # exception raised by every call when set
        self.sets = []

    def _check(self):
        if self.fail is not None:
            raise self.fail

    def GetMasterVolumeLevelScalar(self):
        self._check()
        return self.volume

    def SetMasterVolumeLevelScalar(self, level, ctx):
        self._check()
        self.sets.append(level)
        self.volume = level

    def GetMute(self):
        self._check()
        return 1 if self.muted else 0

    def SetMute(self, mute, ctx):
        self._check()
        self.muted = bool(mute)


class FakeBackend:
    def __init__(self):
        self.devices = {}  # id -> FakeEndpoint
        self.default = None
        self.opens = 0
        self.id_error = None

    def add(self, device_id, endpoint, default=False):
        self.devices[device_id] = endpoint
        if default:
            self.default = device_id

    def default_device_id(self):
        if self.id_error is not None:
            raise self.id_error
        return self.default

    def open_endpoint(self):
        if self.default is None:
            raise OSError("no device")
        self.opens += 1
        return self.default, self.devices[self.default]


class AudioSnapshotTest(unittest.TestCase):
    def setUp(self):
        self.backend = FakeBackend()
        self.ep = FakeEndpoint(0.42, False)
        self.backend.add("A", self.ep, default=True)
        self.provider = AudioProvider(self.backend)

    def test_snapshot_reports_volume_and_mute(self):
        self.assertEqual(self.provider.snapshot(), {"available": True, "volume": 0.42, "muted": False})
        self.ep.muted = True
        self.assertTrue(self.provider.snapshot()["muted"])

    def test_float32_noise_is_rounded(self):
        self.ep.volume = 0.4199999868869781
        self.assertEqual(self.provider.snapshot()["volume"], 0.42)

    def test_endpoint_is_cached_between_snapshots(self):
        self.provider.snapshot()
        self.provider.snapshot()
        self.assertEqual(self.backend.opens, 1)

    def test_default_device_change_reacquires_endpoint(self):
        self.provider.snapshot()
        other = FakeEndpoint(0.9, True)
        self.backend.add("B", other, default=True)
        self.assertEqual(self.provider.snapshot(), {"available": True, "volume": 0.9, "muted": True})
        self.assertEqual(self.backend.opens, 2)

    def test_com_error_reacquires_and_retries_once(self):
        self.provider.snapshot()
        self.ep.fail = OSError("device invalidated")
        fresh = FakeEndpoint(0.7, False)
        # The stale endpoint raises; a re-open of the same id must return a working one.
        self.backend.devices["A"] = fresh
        self.assertEqual(self.provider.snapshot()["volume"], 0.7)
        self.assertEqual(self.backend.opens, 2)

    def test_unavailable_when_endpoint_keeps_failing(self):
        self.ep.fail = OSError("boom")
        self.assertEqual(self.provider.snapshot(), {"available": False})

    def test_unavailable_without_default_device_then_recovers(self):
        self.backend.id_error = OSError("E_NOTFOUND")
        self.assertEqual(self.provider.snapshot(), {"available": False})
        self.backend.id_error = None
        self.assertTrue(self.provider.snapshot()["available"])


class AudioActionTest(unittest.TestCase):
    def setUp(self):
        self.backend = FakeBackend()
        self.ep = FakeEndpoint(0.2, False)
        self.backend.add("A", self.ep, default=True)
        self.provider = AudioProvider(self.backend)

    def test_volume_set(self):
        self.assertIsNone(self.provider.handle({"id": "volume.set", "value": 0.65}))
        self.assertEqual(self.ep.sets, [0.65])

    def test_volume_set_clamps(self):
        self.provider.handle({"id": "volume.set", "value": 1.7})
        self.provider.handle({"id": "volume.set", "value": -3})
        self.assertEqual(self.ep.sets, [1.0, 0.0])

    def test_volume_set_accepts_integers(self):
        self.provider.handle({"id": "volume.set", "value": 1})
        self.assertEqual(self.ep.sets, [1.0])

    def test_volume_set_rejects_bad_values(self):
        for bad in (None, "0.5", True, float("nan"), float("inf"), [0.5]):
            self.assertEqual(self.provider.handle({"id": "volume.set", "value": bad}), "action_failed", bad)
        self.assertEqual(self.provider.handle({"id": "volume.set"}), "action_failed")
        self.assertEqual(self.ep.sets, [])

    def test_mute_and_unmute(self):
        self.assertIsNone(self.provider.handle({"id": "volume.mute", "value": True}))
        self.assertTrue(self.ep.muted)
        self.assertIsNone(self.provider.handle({"id": "volume.mute", "value": False}))
        self.assertFalse(self.ep.muted)

    def test_mute_requires_a_bool(self):
        for bad in (None, 1, "true"):
            self.assertEqual(self.provider.handle({"id": "volume.mute", "value": bad}), "action_failed", bad)
        self.assertFalse(self.ep.muted)

    def test_unknown_id(self):
        self.assertEqual(self.provider.handle({"id": "volume.bogus", "value": 1}), "action_failed")

    def test_set_follows_default_device_change(self):
        self.provider.snapshot()
        other = FakeEndpoint(0.9)
        self.backend.add("B", other, default=True)
        self.provider.handle({"id": "volume.set", "value": 0.1})
        self.assertEqual(other.sets, [0.1])
        self.assertEqual(self.ep.sets, [])

    def test_set_reports_failure_when_endpoint_is_gone(self):
        self.ep.fail = OSError("gone")
        self.assertEqual(self.provider.handle({"id": "volume.set", "value": 0.5}), "action_failed")

    def test_set_retries_with_a_fresh_endpoint(self):
        self.provider.snapshot()
        self.ep.fail = OSError("stale")
        fresh = FakeEndpoint(0.3)
        self.backend.devices["A"] = fresh
        self.assertIsNone(self.provider.handle({"id": "volume.set", "value": 0.8}))
        self.assertEqual(fresh.sets, [0.8])


if __name__ == "__main__":
    unittest.main()
