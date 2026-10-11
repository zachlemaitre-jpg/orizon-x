import unittest

from actions.brightness import BrightnessProvider, DdcBackend, WmiBackend


class FakeBackend:
    """Stand-in for a BrightnessBackend."""

    def __init__(self, value=None):
        self.value = value  # None = no display
        self.error = None
        self.reads = 0
        self.writes = []
        self.write_ok = True

    def read(self):
        self.reads += 1
        if self.error is not None:
            raise self.error
        return self.value

    def write(self, value):
        if self.error is not None:
            raise self.error
        self.writes.append(value)
        if self.write_ok:
            self.value = value
        return self.write_ok


class FakeClock:
    def __init__(self):
        self.now = 100.0

    def __call__(self):
        return self.now


class ProviderTest(unittest.TestCase):
    def make(self, wmi=None, ddc=None, retry_s=10.0):
        self.wmi = wmi or FakeBackend()
        self.ddc = ddc or FakeBackend()
        self.clock = FakeClock()
        return BrightnessProvider(self.wmi, self.ddc, clock=self.clock, retry_s=retry_s)

    def test_wmi_is_preferred(self):
        p = self.make(FakeBackend(0.7), FakeBackend(0.2))
        self.assertEqual(p.snapshot(), {"available": True, "value": 0.7})
        self.assertEqual(self.ddc.reads, 0)

    def test_ddc_fallback_when_wmi_has_no_display(self):
        p = self.make(FakeBackend(None), FakeBackend(0.35))
        self.assertEqual(p.snapshot(), {"available": True, "value": 0.35})

    def test_ddc_fallback_when_wmi_raises(self):
        wmi = FakeBackend(0.5)
        wmi.error = OSError("wmi down")
        p = self.make(wmi, FakeBackend(0.35))
        self.assertEqual(p.snapshot()["value"], 0.35)

    def test_unavailable_when_neither_answers(self):
        p = self.make()
        self.assertEqual(p.snapshot(), {"available": False})

    def test_failed_probe_is_not_repeated_before_retry_delay(self):
        p = self.make(retry_s=10.0)
        p.snapshot()
        reads = self.wmi.reads
        self.clock.now += 5
        p.snapshot()
        self.assertEqual(self.wmi.reads, reads)
        self.clock.now += 6
        self.wmi.value = 0.4
        self.assertEqual(p.snapshot(), {"available": True, "value": 0.4})

    def test_active_backend_is_reused(self):
        p = self.make(FakeBackend(0.7), FakeBackend(0.2))
        p.snapshot()
        self.wmi.value = 0.8
        self.assertEqual(p.snapshot()["value"], 0.8)
        self.assertEqual(self.ddc.reads, 0)

    def test_active_backend_lost_then_other_takes_over(self):
        p = self.make(FakeBackend(0.7), FakeBackend(None))
        p.snapshot()
        self.wmi.value = None
        self.ddc.value = 0.1
        self.assertEqual(p.snapshot()["value"], 0.1)

    def test_set_goes_to_active_backend(self):
        p = self.make(FakeBackend(0.7))
        self.assertIsNone(p.handle({"id": "brightness.set", "value": 0.25}))
        self.assertEqual(self.wmi.writes, [0.25])
        self.assertEqual(self.ddc.writes, [])

    def test_set_uses_ddc_when_that_is_active(self):
        p = self.make(FakeBackend(None), FakeBackend(0.5))
        self.assertIsNone(p.handle({"id": "brightness.set", "value": 1}))
        self.assertEqual(self.ddc.writes, [1.0])

    def test_set_clamps(self):
        p = self.make(FakeBackend(0.7))
        p.handle({"id": "brightness.set", "value": 5})
        p.handle({"id": "brightness.set", "value": -1})
        self.assertEqual(self.wmi.writes, [1.0, 0.0])

    def test_set_rejects_bad_values(self):
        p = self.make(FakeBackend(0.7))
        for bad in (None, "0.5", True, float("nan")):
            self.assertEqual(p.handle({"id": "brightness.set", "value": bad}), "action_failed", bad)
        self.assertEqual(p.handle({"id": "brightness.other", "value": 0.5}), "action_failed")
        self.assertEqual(self.wmi.writes, [])

    def test_set_without_any_display_fails(self):
        p = self.make()
        self.assertEqual(p.handle({"id": "brightness.set", "value": 0.5}), "action_failed")

    def test_set_failure_reported(self):
        wmi = FakeBackend(0.7)
        wmi.write_ok = False
        p = self.make(wmi)
        self.assertEqual(p.handle({"id": "brightness.set", "value": 0.5}), "action_failed")


class FakeWmiInstance:
    def __init__(self, props=None):
        self._props = props or {}
        self.set_calls = []

    class _Prop:
        def __init__(self, value):
            self.Value = value

    def Properties_(self, name):
        return self._Prop(self._props[name])

    def WmiSetBrightness(self, timeout, level):
        self.set_calls.append((timeout, level))


class FakeWmiServices:
    def __init__(self, tables):
        self.tables = tables
        self.queries = []

    def ExecQuery(self, text):
        self.queries.append(text)
        return self.tables.get(text.rsplit(" ", 1)[1], [])


class WmiBackendTest(unittest.TestCase):
    def test_read_scales_percent_to_unit(self):
        services = FakeWmiServices({"WmiMonitorBrightness": [FakeWmiInstance({"CurrentBrightness": 99})]})
        backend = WmiBackend(connect=lambda: services)
        self.assertAlmostEqual(backend.read(), 0.99)
        self.assertIn("SELECT * FROM WmiMonitorBrightness", services.queries)

    def test_read_without_instances_is_none(self):
        backend = WmiBackend(connect=lambda: FakeWmiServices({}))
        self.assertIsNone(backend.read())

    def test_write_calls_wmi_set_brightness_with_timeout_1(self):
        inst = FakeWmiInstance()
        backend = WmiBackend(connect=lambda: FakeWmiServices({"WmiMonitorBrightnessMethods": [inst]}))
        self.assertTrue(backend.write(0.376))
        self.assertEqual(inst.set_calls, [(1, 38)])

    def test_write_without_instances_is_false(self):
        backend = WmiBackend(connect=lambda: FakeWmiServices({}))
        self.assertFalse(backend.write(0.5))

    def test_connection_is_cached_and_dropped_on_error(self):
        connects = []

        class Boom:
            def ExecQuery(self, text):
                raise OSError("rpc")

        def connect():
            connects.append(1)
            return Boom() if len(connects) == 1 else FakeWmiServices({})

        backend = WmiBackend(connect=connect)
        with self.assertRaises(OSError):
            backend.read()
        backend.read()
        backend.read()
        self.assertEqual(len(connects), 2)


class FakeDdcApi:
    def __init__(self, monitors):
        self.monitors = monitors  # handle -> [current, maximum]
        self.enumerations = 0
        self.closed = []
        self.sets = []
        self.broken = set()

    def physical_monitors(self):
        self.enumerations += 1
        return list(self.monitors)

    def get_vcp(self, handle):
        if handle in self.broken:
            raise OSError("no DDC")
        return tuple(self.monitors[handle])

    def set_vcp(self, handle, value):
        if handle in self.broken:
            raise OSError("no DDC")
        self.sets.append((handle, value))
        self.monitors[handle][0] = value

    def close(self, handles):
        self.closed.append(list(handles))


class DdcBackendTest(unittest.TestCase):
    def test_read_normalises_by_maximum(self):
        backend = DdcBackend(api=FakeDdcApi({1: [30, 60]}))
        self.assertEqual(backend.read(), 0.5)

    def test_no_monitor_is_none(self):
        self.assertIsNone(DdcBackend(api=FakeDdcApi({})).read())

    def test_handles_are_cached(self):
        api = FakeDdcApi({1: [30, 60]})
        backend = DdcBackend(api=api)
        backend.read()
        backend.read()
        self.assertEqual(api.enumerations, 1)

    def test_broken_monitor_is_skipped_and_handles_released(self):
        api = FakeDdcApi({1: [0, 0], 2: [20, 100]})
        api.broken.add(1)
        backend = DdcBackend(api=api)
        self.assertEqual(backend.read(), 0.2)
        self.assertEqual(api.closed, [[1, 2]])

    def test_write_scales_to_maximum(self):
        api = FakeDdcApi({1: [10, 60]})
        backend = DdcBackend(api=api)
        self.assertTrue(backend.write(0.5))
        self.assertEqual(api.sets, [(1, 30)])

    def test_write_failure_is_false(self):
        api = FakeDdcApi({1: [10, 60]})
        api.broken.add(1)
        self.assertFalse(DdcBackend(api=api).write(0.5))

    def test_close_releases_handles(self):
        api = FakeDdcApi({1: [10, 60]})
        backend = DdcBackend(api=api)
        backend.read()
        backend.close()
        self.assertEqual(api.closed, [[1]])


if __name__ == "__main__":
    unittest.main()
