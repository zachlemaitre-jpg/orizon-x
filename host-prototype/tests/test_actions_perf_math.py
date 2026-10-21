import json
import unittest

from actions.perf_math import History, build_section, engine_busy, engine_types, pick_gpu, pick_npu


class EngineBusyTest(unittest.TestCase):
    L = "0x00000000_0x00015cba"

    def name(self, pid, eng, typ, luid=L):
        return f"pid_{pid}_luid_{luid}_phys_0_eng_{eng}_engtype_{typ}"

    def test_sums_processes_per_engine_and_keeps_busiest(self):
        s = {self.name(1, 0, "3D"): 20.0, self.name(2, 0, "3D"): 15.5, self.name(1, 3, "Copy"): 30.0}
        self.assertEqual(engine_busy(s, self.L), 36)

    def test_clamps_to_100(self):
        s = {self.name(1, 0, "3D"): 80.0, self.name(2, 0, "3D"): 70.0}
        self.assertEqual(engine_busy(s, self.L), 100)

    def test_other_luid_ignored_and_absent_is_none(self):
        s = {self.name(1, 0, "3D", luid="0x00000000_0x00018269"): 50.0}
        self.assertIsNone(engine_busy(s, self.L))

    def test_hex_case_does_not_matter(self):
        s = {self.name(1, 0, "3D", luid="0x00000000_0x00015CBA"): 12.0}
        self.assertEqual(engine_busy(s, self.L), 12)

    def test_idle_adapter_is_zero_not_none(self):
        self.assertEqual(engine_busy({self.name(1, 0, "3D"): 0.0}, self.L), 0)

    def test_engine_types_are_grouped_per_luid_in_lower_case(self):
        names = [self.name(1, 0, "3D"), self.name(2, 1, "Compute 0"), self.name(1, 0, "Copy", luid="0x0_0x2")]
        self.assertEqual(engine_types(names), {self.L: {"3d", "compute 0"}, "0x0_0x2": {"copy"}})


class PickTest(unittest.TestCase):
    def test_npu_is_compute_only_non_dxgi(self):
        eng = {"a": {"3d", "copy", "compute 0"}, "b": {"compute 0"}, "c": {"3d"}}
        self.assertEqual(pick_npu(eng, {"a", "c"}), "b")
        self.assertIsNone(pick_npu(eng, {"a", "b", "c"}))

    def test_gpu_skips_software_and_virtual_display(self):
        ads = [{"luid": "v", "description": "Virtual Display Driver", "software": False, "dedicated": 0, "shared": 99},
               {"luid": "s", "description": "Microsoft Basic Render Driver", "software": True, "dedicated": 0, "shared": 99},
               {"luid": "g", "description": "AMD Radeon(TM) 890M Graphics", "software": False, "dedicated": 512, "shared": 16}]
        self.assertEqual(pick_gpu(ads), "g")

    def test_gpu_keeps_the_largest_and_none_when_nothing_fits(self):
        ads = [{"luid": "a", "description": "A", "software": False, "dedicated": 1, "shared": 1},
               {"luid": "b", "description": "B", "software": False, "dedicated": 4, "shared": 1}]
        self.assertEqual(pick_gpu(ads), "b")
        self.assertIsNone(pick_gpu([]))


class HistoryTest(unittest.TestCase):
    def test_keeps_last_60_oldest_first(self):
        h = History(60)
        for i in range(70):
            h.push(i)
        self.assertEqual(h.values(), list(range(10, 70)))


class SectionTest(unittest.TestCase):
    def test_absent_measures_left_out_and_size(self):
        cpu = {"value": 23, "ghz": 4.1, "history": [50] * 60}
        sec = build_section(cpu, None, None, None, None)
        self.assertEqual(sec, {"available": True, "cpu": cpu})
        full = build_section(cpu, dict(cpu), dict(cpu), {"down": 10**7, "up": 10**6, "down_history": [10**7] * 60,
                                                         "up_history": [10**6] * 60}, dict(cpu))
        self.assertLess(len(json.dumps(full, separators=(",", ":"))), 4096)

    def test_nothing_is_unavailable(self):
        self.assertEqual(build_section(None, None, None, None, None), {"available": False})


if __name__ == "__main__":
    unittest.main()
