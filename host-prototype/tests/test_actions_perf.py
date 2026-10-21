import sys
import unittest

from actions import perf
from actions.perf import (CPU_FREQUENCY, CPU_PERFORMANCE, CPU_UTILITY, GPU_DEDICATED, GPU_ENGINE, GPU_SHARED, NET_RECEIVED,
                          NET_SENT, PdhError, PerfProvider, PerfSampler, pdh_instance_name)

GPU = "0x00000000_0x00015cba"
NPU = "0x00000000_0x00018269"
OTHER = "0x00000000_0x00015cd0"
GIB = 2 ** 30


def engine(luid, eng, typ, pid=1):
    return f"pid_{pid}_luid_{luid}_phys_0_eng_{eng}_engtype_{typ}"


def memory_name(luid):
    return f"luid_{luid}_phys_0"


class FakeReader:
    """Scripted counters: ``values`` (path -> number or Exception) and ``arrays`` (path -> dict or Exception)."""

    def __init__(self):
        self.values = {CPU_UTILITY: 23.4, CPU_FREQUENCY: 2000.0, CPU_PERFORMANCE: 205.0}
        self.arrays = {
            GPU_ENGINE: {engine(GPU, 0, "3D"): 8.0, engine(GPU, 3, "Copy"): 2.0, engine(OTHER, 0, "3D"): 1.0,
                         engine(NPU, 0, "Compute 0"): 5.4},
            GPU_DEDICATED: {memory_name(GPU): 1.5 * GIB, memory_name(OTHER): 0.0},
            GPU_SHARED: {memory_name(GPU): 1.7 * GIB, memory_name(OTHER): 0.0},
            NET_RECEIVED: {"Intel[R] Wi-Fi 7 BE200": 1_250_000.4, "Realtek PCIe GbE": 5.0},
            NET_SENT: {"Intel[R] Wi-Fi 7 BE200": 82_000.0, "Realtek PCIe GbE": 1.0},
        }
        self.opened = []
        self.collected = 0
        self.closed = []
        self.refuse = set()  # paths that cannot be added

    def open(self, paths):
        self.opened.append(list(paths))
        for path in paths:
            if path in self.refuse:
                raise PdhError(path, 0xC0000BB8)
        return perf.PdhQuery(object(), {path: path for path in paths})

    def collect(self, query):
        self.collected += 1

    def value(self, counter):
        v = self.values[counter]
        if isinstance(v, Exception):
            raise v
        return v

    def array(self, counter):
        v = self.arrays[counter]
        if isinstance(v, Exception):
            raise v
        return dict(v)

    def close(self, query):
        self.closed.append(query)


class FakeAdapters:
    def __init__(self):
        self.calls = 0
        self.adapters = [
            {"luid": GPU, "description": "AMD Radeon(TM) 890M Graphics", "software": False, "dedicated": 512 * 2 ** 20,
             "shared": int(15.5 * GIB)},
            {"luid": OTHER, "description": "Virtual Display Driver", "software": False, "dedicated": 0, "shared": 10 * GIB},
            {"luid": "0x00000000_0x0000dead", "description": "Microsoft Basic Render Driver", "software": True,
             "dedicated": 0, "shared": 20 * GIB}]

    def list(self):
        self.calls += 1
        return [dict(a) for a in self.adapters]


class Clock:
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t


def make(**kw):
    reader = kw.pop("reader", None) or FakeReader()
    adapters = kw.pop("adapters", None) or FakeAdapters()
    memory = kw.pop("memory", lambda: {"load": 41, "total": 32 * GIB, "avail": int(19.7 * GIB)})
    clock = kw.pop("clock", None) or Clock()
    logs = kw.pop("logs", [])
    sampler = PerfSampler(reader, adapters, memory, clock=clock, sleep=lambda s: None,
                          wifi=kw.pop("wifi", lambda: "Intel(R) Wi-Fi 7 BE200"), log=logs.append)
    return sampler, reader, adapters, clock, logs


class TickTest(unittest.TestCase):
    def test_one_tick_fills_the_five_measures(self):
        sampler, *_ = make()
        sampler.tick()
        s = sampler.latest()
        self.assertTrue(s["available"])
        self.assertEqual(s["cpu"], {"value": 23, "ghz": 4.1, "history": [23]})
        self.assertEqual(s["gpu"], {"value": 8, "mem_used": 3.2, "mem_total": 16.0, "history": [8]})
        self.assertEqual(s["ram"], {"value": 41, "used": 12.3, "total": 32.0, "history": [41]})
        self.assertEqual(s["net"], {"down": 1_250_000, "up": 82_000, "down_history": [1_250_000], "up_history": [82_000]})
        self.assertEqual(s["npu"], {"value": 5, "history": [5]})

    def test_before_any_tick_nothing_is_available(self):
        sampler, *_ = make()
        self.assertEqual(sampler.latest(), {"available": False})

    def test_cpu_is_capped_at_100(self):
        sampler, reader, *_ = make()
        reader.values[CPU_UTILITY] = 137.0
        sampler.tick()
        self.assertEqual(sampler.latest()["cpu"]["value"], 100)

    def test_cpu_falls_back_to_processor_time(self):
        reader = FakeReader()
        reader.refuse = {CPU_UTILITY}
        reader.values[perf.CPU_TIME] = 12.0
        sampler, *_ = make(reader=reader)
        sampler.tick()
        self.assertEqual(sampler.latest()["cpu"]["value"], 12)
        self.assertEqual(sampler.latest()["cpu"]["ghz"], 4.1)

    def test_a_reader_error_on_the_gpu_leaves_only_the_gpu_absent(self):
        sampler, reader, *_ = make()
        reader.arrays[GPU_ENGINE] = PdhError("engine", 0x800007D5)
        sampler.tick()
        s = sampler.latest()
        self.assertNotIn("gpu", s)
        self.assertNotIn("npu", s)
        for name in ("cpu", "ram", "net"):
            self.assertIn(name, s)

    def test_gpu_memory_failure_keeps_the_load(self):
        sampler, reader, *_ = make()
        reader.arrays[GPU_DEDICATED] = PdhError("memory", 1)
        sampler.tick()
        self.assertEqual(sampler.latest()["gpu"], {"value": 8, "history": [8]})

    def test_no_wifi_means_no_net(self):
        sampler, *_ = make(wifi=lambda: None)
        sampler.tick()
        self.assertNotIn("net", sampler.latest())

    def test_wifi_instance_is_matched_after_pdh_renaming(self):
        self.assertEqual(pdh_instance_name("Intel(R) Wi-Fi #2/6E"), "intel[r] wi-fi _2_6e")
        reader = FakeReader()
        reader.arrays[NET_RECEIVED] = {"Intel[R] Wi-Fi _2_6E": 10.0}
        reader.arrays[NET_SENT] = {"Intel[R] Wi-Fi _2_6E": 4.0}
        sampler, *_ = make(reader=reader, wifi=lambda: "Intel(R) Wi-Fi #2/6E")
        sampler.tick()
        self.assertEqual(sampler.latest()["net"]["down"], 10)

    def test_no_npu_when_every_luid_is_a_dxgi_adapter(self):
        reader = FakeReader()
        del reader.arrays[GPU_ENGINE][engine(NPU, 0, "Compute 0")]
        sampler, *_ = make(reader=reader)
        sampler.tick()
        self.assertNotIn("npu", sampler.latest())

    def test_a_query_that_cannot_be_opened_is_retried_at_the_next_discovery_only(self):
        reader = FakeReader()
        reader.refuse = {NET_RECEIVED}
        sampler, _, _, clock, logs = make(reader=reader)
        sampler.tick()
        self.assertNotIn("net", sampler.latest())
        net_opens = lambda: sum(1 for paths in reader.opened if NET_RECEIVED in paths)
        self.assertEqual(net_opens(), 1)
        sampler.tick()
        self.assertEqual(net_opens(), 1)
        reader.refuse = set()
        clock.t += 61
        sampler.tick()
        self.assertEqual(net_opens(), 2)
        self.assertIn("net", sampler.latest())


class DiscoveryTest(unittest.TestCase):
    def test_discovery_runs_at_start_then_every_60_seconds(self):
        sampler, _, adapters, clock, _ = make()
        sampler.tick()
        sampler.tick()
        self.assertEqual(adapters.calls, 1)
        clock.t += 59
        sampler.tick()
        self.assertEqual(adapters.calls, 1)
        clock.t += 2
        sampler.tick()
        self.assertEqual(adapters.calls, 2)

    def test_the_gpu_luid_vanishing_triggers_a_rediscovery_on_the_next_tick(self):
        sampler, reader, adapters, *_ = make()
        sampler.tick()
        self.assertEqual(adapters.calls, 1)
        new_luid = "0x00000000_0x00099999"  # the driver was reloaded: the adapter has a new LUID
        reader.arrays[GPU_ENGINE] = {engine(new_luid, 0, "3D"): 40.0}
        reader.arrays[GPU_DEDICATED] = {memory_name(new_luid): 1 * GIB}
        reader.arrays[GPU_SHARED] = {memory_name(new_luid): 0.0}
        adapters.adapters[0] = dict(adapters.adapters[0], luid=new_luid)
        sampler.tick()  # the old luid is gone: no gpu this tick
        self.assertNotIn("gpu", sampler.latest())
        self.assertEqual(adapters.calls, 1)
        sampler.tick()  # looked for again
        self.assertEqual(adapters.calls, 2)
        self.assertEqual(sampler.latest()["gpu"]["value"], 40)


class HistoryTest(unittest.TestCase):
    def test_61_ticks_keep_60_points(self):
        sampler, reader, *_ = make()
        for i in range(61):
            reader.values[CPU_UTILITY] = float(i)
            sampler.tick()
        s = sampler.latest()
        self.assertEqual(s["cpu"]["history"], list(range(1, 61)))
        self.assertEqual(len(s["gpu"]["history"]), 60)
        self.assertEqual(len(s["net"]["down_history"]), 60)

    def test_latest_is_a_copy(self):
        sampler, *_ = make()
        sampler.tick()
        sampler.latest()["cpu"]["history"].append(99)
        self.assertEqual(sampler.latest()["cpu"]["history"], [23])


class FakeSampler:
    def __init__(self):
        self.started = 0
        self.stopped = 0

    def start(self):
        self.started += 1

    def stop(self):
        self.stopped += 1

    def latest(self):
        return {"available": True, "ram": {"value": 1, "history": [1]}}


class ProviderTest(unittest.TestCase):
    def test_snapshot_starts_the_sampler_once_and_close_stops_it(self):
        fake = FakeSampler()
        made = []
        provider = PerfProvider(sampler_factory=lambda: made.append(1) or fake)
        self.assertEqual(made, [])  # nothing starts before the first request
        self.assertEqual(provider.snapshot()["ram"]["value"], 1)
        provider.snapshot()
        self.assertEqual((len(made), fake.started, fake.stopped), (1, 1, 0))
        provider.close()
        self.assertEqual(fake.stopped, 1)
        provider.stop()
        self.assertEqual(fake.stopped, 1)

    def test_stop_without_any_snapshot_is_harmless_and_handle_ignores_actions(self):
        provider = PerfProvider(sampler_factory=FakeSampler, log=lambda line: None)
        provider.stop()
        self.assertIsNone(provider.handle({"id": "perf.nothing"}))


class ThreadTest(unittest.TestCase):
    def test_the_thread_samples_and_stop_closes_the_queries(self):
        reader = FakeReader()
        sampler = PerfSampler(reader, FakeAdapters(), lambda: {"load": 5, "total": GIB, "avail": GIB // 2},
                              wifi=lambda: None, log=lambda line: None)
        sampler._sleep = lambda s: sampler._stop.wait(0.01)
        sampler.start()
        for _ in range(200):
            if sampler.latest()["available"]:
                break
            sampler._stop.wait(0.01)
        sampler.stop()
        self.assertTrue(sampler.latest()["available"])
        self.assertEqual(len(reader.closed), 3)
        self.assertFalse(sampler._thread.is_alive())
        self.assertEqual(sampler._thread.name, "orizonx-perf")


@unittest.skipUnless(sys.platform == "win32", "Windows performance counters")
class RealSystemTest(unittest.TestCase):
    def test_open_collect_close_a_real_query_read_only(self):
        reader = perf.PdhReader()
        query = reader.open([r"\Processor Information(_Total)\% Processor Time"])
        try:
            reader.collect(query)
        finally:
            reader.close(query)

    def test_ram_and_dxgi_answer(self):
        status = perf.system_memory()
        self.assertGreater(status["total"], 0)
        self.assertTrue(0 <= status["load"] <= 100)
        self.assertIsInstance(perf.DxgiAdapters().list(), list)


if __name__ == "__main__":
    unittest.main()
