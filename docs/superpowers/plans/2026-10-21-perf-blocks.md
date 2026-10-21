# Performance Blocks Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Five Actions-mode blocks (CPU, GPU, RAM, Wi-Fi, NPU), each showing a value, a 60 s graph and a detail line.

**Architecture:**
- The PC samples Windows PDH counters once a second in its own thread (`actions/perf.py`) and keeps 60-point histories.
- The hub reads the latest snapshot as a `perf` section in the slow group (1 s).
- Android parses the section, adds five grid blocks and draws them with a Compose Canvas graph.

**Tech Stack:**
- PC: Python 3.13, ctypes (pdh.dll, kernel32, DXGI through the existing `dxgi_outputs.py` patterns), unittest.
- Android: Kotlin, Jetpack Compose, JUnit.

Spec: `docs/superpowers/specs/2026-10-21-perf-blocks-design.md`. Branch `perf-blocks`.

**Commands:**
- PC tests: `cd "D:\TumorScreen App\host-prototype"; .\.venv\Scripts\python.exe -m unittest discover -s tests`.
- Android tests: `cd "D:\TumorScreen App\android"; .\gradlew.bat :app:testDebugUnitTest`.
- Android compile check: `.\gradlew.bat :app:assembleDebug`.

**Commit trailer:** `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`

---

## File structure

**PC (`host-prototype/`):**
- `actions/perf_math.py` (create): pure functions.
  - Engine aggregation per LUID.
  - Picking the GPU and NPU LUIDs.
  - The history ring.
  - Building the section.
  - No ctypes in this file.
- `actions/perf.py` (create):
  - `PdhReader`: ctypes; opens queries with `PdhAddEnglishCounterW` and reads wildcard arrays with `PdhGetFormattedCounterArrayW`.
  - `DxgiAdapters`: LUID, description, flags and memory, by `CreateDXGIFactory1` / `EnumAdapters1`.
  - `PerfSampler`: the 1 s thread.
  - `PerfProvider`: the hub provider, with `snapshot()` and `close()`.
- `actions/hub.py` (modify):
  - register `perf` in the factory list and in `_SLOW`;
  - add `state["perf"] = self._section("perf")`;
  - stop the sampler on hub close, the same way the other providers are closed.
- `tests/test_actions_perf_math.py` (create) and `tests/test_actions_perf.py` (create).

**Android (`android/app/src/main/java/com/orizonx/client/`):**
- `actions/PerfState.kt` (create): the data classes and `parse(JSONObject?)`.
- `actions/PerfFormat.kt` (create): pure formatting, the network scale and the compact rule.
- `actions/ActionsState.kt` (modify): `perf = PerfState.parse(json.optJSONObject("perf"))`.
- `actions/BlockGrid.kt` (modify):
  - add the five `BlockId`s with `Span(2,1)` default and `Span(1,1)` minimum;
  - add the `ActionsBlocks.present` rules.
- `ui/PerfBlock.kt` (create): the `PerfCard` composable and the `PerfGraph` Canvas.
- `ui/ActionsScreen.kt` (modify): the `BlockContent` branches and `blockName`.
- `i18n/Strings.kt` (modify): the block names.
- `res/drawable/ox_perf_cpu.xml`, `ox_perf_gpu.xml`, `ox_perf_ram.xml`, `ox_perf_npu.xml` (create): Material paths `memory`, `developer_board`, `storage` and `psychology`, 24 dp, white fill, with an Apache-2.0 comment like the existing `ctx_*` icons. The Wi-Fi block reuses the existing wifi drawable.
- Tests: `test/.../actions/PerfStateTest.kt`, `PerfFormatTest.kt` and `BlockGridTest.kt` (extend).

---

## Task 1 (PC): pure perf math

**Files:** create `host-prototype/actions/perf_math.py` and `host-prototype/tests/test_actions_perf_math.py`.

Interfaces:

```python
ENGINE_RE = re.compile(r"luid_(0x[0-9a-fA-F]+_0x[0-9a-fA-F]+)_phys_(\d+)_eng_(\d+)_engtype_(.*)$")

def engine_busy(samples: dict[str, float], luid: str) -> Optional[int]:
    """Task-manager style % of one adapter: sum the per-process instances of each engine (phys, eng), keep the busiest
    engine, clamp 0..100, round. None when no instance of that luid exists."""

def engine_types(instance_names: Iterable[str]) -> dict[str, set[str]]:
    """luid -> set of engtype strings (lower-cased, e.g. {'3d', 'copy', 'compute 0'})."""

def pick_npu(engines: dict[str, set[str]], dxgi_luids: set[str]) -> Optional[str]:
    """A luid not among the DXGI adapters whose engine types all start with 'compute'."""

def pick_gpu(adapters: list[dict]) -> Optional[str]:
    """adapters: {'luid','description','software':bool,'dedicated':int,'shared':int}. Drop software ones and any whose
    description contains 'Virtual Display' ; keep the largest dedicated+shared. Returns its luid string 'luid_0x..._0x...'
    form without the 'luid_' prefix, i.e. '0x00000000_0x00015cba'."""

class History:
    def __init__(self, size: int = 60): ...
    def push(self, v: int) -> None: ...
    def values(self) -> list[int]:  # oldest first, at most size entries

def build_section(cpu, gpu, ram, net, npu) -> dict:
    """Each arg a dict or None; None ones are left out. Always 'available': True when at least one is present, else
    {'available': False}."""
```

- [ ] Write the tests first. Required cases:

```python
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
class HistoryTest(unittest.TestCase):
    def test_keeps_last_60_oldest_first(self):
        h = History(60)
        for i in range(70): h.push(i)
        self.assertEqual(h.values(), list(range(10, 70)))
class SectionTest(unittest.TestCase):
    def test_absent_measures_left_out_and_size(self):
        cpu = {"value": 23, "ghz": 4.1, "history": [50] * 60}
        sec = build_section(cpu, None, None, None, None)
        self.assertEqual(sec, {"available": True, "cpu": cpu})
        full = build_section(cpu, dict(cpu), dict(cpu), {"down": 10**7, "up": 10**6, "down_history": [10**7] * 60, "up_history": [10**6] * 60}, dict(cpu))
        self.assertLess(len(json.dumps(full, separators=(",", ":"))), 4096)
    def test_nothing_is_unavailable(self):
        self.assertEqual(build_section(None, None, None, None, None), {"available": False})
```

- [ ] Run the tests and confirm they fail with an ImportError.
- [ ] Implement `perf_math.py` with the interfaces above. Match the docstring style of `actions/launchers.py`.
- [ ] Run the tests and confirm they pass.
- [ ] Commit `feat(pc): perf math (engine %, GPU/NPU pick, history, section)`.

## Task 2 (PC): PDH/DXGI readers, sampler and provider

**Files:** create `host-prototype/actions/perf.py` and `host-prototype/tests/test_actions_perf.py`.

`PdhReader` (ctypes, `pdh.dll`):
- `open(paths: list[str]) -> handle`. It uses `PdhOpenQueryW` and `PdhAddEnglishCounterW` for each path, then a first `PdhCollectQueryData`. Rate counters need two collections.
- `collect(handle)`.
- `value(counter) -> Optional[float]`: `PdhGetFormattedCounterValue` with `PDH_FMT_DOUBLE`.
- `array(counter) -> dict[str, float]`: `PdhGetFormattedCounterArrayW` with `PDH_FMT_DOUBLE | PDH_FMT_NOCAP100`. Size it in two calls (the first returns `PDH_MORE_DATA` = 0x800007D2).
- `close(handle)`: `PdhCloseQuery`.
- Any non-zero status raises `PdhError(status)`.

Counter paths:
- `\Processor Information(_Total)\% Processor Utility`, falling back to `% Processor Time` if adding the first fails.
- `\Processor Information(_Total)\Processor Frequency` and `\Processor Information(_Total)\% Processor Performance`.
- `\GPU Engine(*)\Utilization Percentage`.
- `\GPU Adapter Memory(*)\Dedicated Usage` and `\GPU Adapter Memory(*)\Shared Usage`. Instance names start with `luid_0x..._0x..._phys_0`.
- `\Network Interface(*)\Bytes Received/sec` and `\Network Interface(*)\Bytes Sent/sec`.

RAM:
- `GlobalMemoryStatusEx`, through a `MEMORYSTATUSEX` ctypes struct.
- `value` = `dwMemoryLoad`.
- `used` = `(ullTotalPhys - ullAvailPhys) / 2**30`, rounded to 1 decimal.
- `total` = `ullTotalPhys / 2**30`, rounded to 1 decimal.

Wi-Fi adapter instance:
- Take the PDH instance whose name matches the active wireless adapter's `InterfaceDescription`.
- PDH swaps `(`→`[`, `)`→`]`, `#`→`_` and `/`→`_`. Normalise both sides with those replacements and compare case-insensitively.
- Get the description through `GetAdaptersAddresses` (`IfType == 71`, `IF_TYPE_IEEE80211`, `OperStatus == 1`). If the existing wifi provider already exposes it, reuse that.
- No Wi-Fi instance means `net` is absent.

`DxgiAdapters.list() -> list[dict]`:
- `CreateDXGIFactory1` and `IDXGIFactory1::EnumAdapters1`, then `IDXGIAdapter1::GetDesc1` (vtable index 10 on IDXGIAdapter1; check against `dxgi_outputs.py`, which already does DXGI by ctypes, and reuse its helpers if any).
- LUID formatting: `f"0x{high:08x}_0x{low:08x}"`, where `high` is `HighPart` (signed int32 masked to uint32) and `low` is `LowPart`.
- The PDH instance names may use upper- or lower-case hex. Compare lower-cased.
- Memory totals for the section: `dedicated = DedicatedVideoMemory`, `shared = SharedSystemMemory`, both in bytes.

`PerfSampler(reader, adapters, memory, clock=time.monotonic, sleep=threading.Event().wait)`:
- `start()` spawns a daemon thread named `orizonx-perf`.
- Each tick: `collect`, then compute each measure and push it to its `History`.
- Discovery (GPU/NPU luid, Wi-Fi instance) runs at start, every 60 s, and when the chosen luid vanishes from the engine array.
- A measure that raises becomes None for that tick. It logs at most once per minute per measure.
- `latest() -> dict` returns the section from `build_section` under a lock.
- `stop()` sets the event, joins for 2 s and closes the query.
- `tick()` is public so tests can drive it without the thread.

Values:
- CPU `value` = `round(min(utility, 100))`.
- `ghz` = `round(freq_mhz * perf_pct / 100 / 1000, 1)`.
- GPU `value` = `engine_busy(...)`.
- `mem_used` = `round((dedicated_usage + shared_usage) / 2**30, 1)` and `mem_total` = `round((dedicated + shared) / 2**30, 1)`, where the usages come from the `phys_0` instance of that luid.
- NPU `value` = `engine_busy(..., npu_luid)`.
- Net `down` and `up` are ints, in bytes/s.

`PerfProvider(log=None, sampler_factory=None)`:
- `snapshot()` starts the sampler lazily on first call, then returns `sampler.latest()`.
- `close()` stops it.
- `handle(action)` returns None. No actions exist.

- [ ] Write the tests first, with a `FakeReader` returning scripted arrays and values, `FakeAdapters` and fake memory:
  - one `tick()` fills all five measures with the expected numbers (CPU 23 % at 4.1 GHz with freq 2000 MHz and perf 205 %; GPU from engines; RAM 41 %);
  - a reader error on GPU leaves only `gpu` absent;
  - the GPU luid vanishing triggers rediscovery on the next tick;
  - 61 ticks keep 60 history points;
  - `PerfProvider.snapshot()` starts the sampler once and `close()` stops it (fake sampler);
  - a real-system, read-only smoke test, skipped when not Windows: `PdhReader().open([r"\Processor Information(_Total)\% Processor Time"])`, `collect`, `close`, without asserting values.
- [ ] Run the tests and confirm they fail.
- [ ] Implement `perf.py`.
- [ ] Run the tests and confirm they pass.
- [ ] Commit `feat(pc): perf sampler (PDH, DXGI) and provider`.

## Task 3 (PC): hub wiring

**Files:** modify `host-prototype/actions/hub.py` and the hub tests (find them with `grep -rl "launchers" host-prototype/tests`).

- [ ] Write the test first, in the same style as the existing hub section tests: with a fake `perf` provider, the state contains `"perf"`, and the hub's close calls the provider's `close()`.
- [ ] Add a `perf` factory: `from actions.perf import PerfProvider; return PerfProvider(log=log)`.
- [ ] Add `"perf"` to `_SLOW`, add `state["perf"] = self._section("perf")`, and update the module docstring's section list.
- [ ] If providers are not closed today, close `perf` in the hub's stop path. Check how `gamepad` is released.
- [ ] Run the full PC suite. Everything must pass.
- [ ] Commit `feat(pc): perf section in the actions state`.

## Task 4 (Android): state, format and blocks (pure)

**Files:** create `actions/PerfState.kt` and `actions/PerfFormat.kt`; modify `actions/ActionsState.kt` and `actions/BlockGrid.kt`; add tests.

```kotlin
data class PerfMeter(val value: Int, val history: List<Int>)
data class PerfState(
    val cpu: PerfMeter?, val cpuGhz: Float?,
    val gpu: PerfMeter?, val gpuMemUsed: Float?, val gpuMemTotal: Float?,
    val ram: PerfMeter?, val ramUsed: Float?, val ramTotal: Float?,
    val netDown: Long?, val netUp: Long?, val netDownHistory: List<Long>, val netUpHistory: List<Long>,
    val npu: PerfMeter?,
) { companion object { fun parse(json: JSONObject?): PerfState? /* null when absent or available=false */ } }

object PerfFormat {
    fun percent(v: Int, lang: Lang): String            // "23 %" fr, "23%" en
    fun gb(used: Float, total: Float, lang: Lang): String  // fr "12,3 / 32 Go", en "12.3 / 32 GB"; whole numbers drop ",0"
    fun ghz(v: Float, lang: Lang): String             // "4,1 GHz" / "4.1 GHz"
    fun rate(bytesPerS: Long, lang: Lang): String      // fr o/s, Ko/s, Mo/s ; en B/s, KB/s, MB/s ; 1024 base; 1 decimal ≥ 1 Mo/s, none below
    fun netScale(maxValue: Long): Long                 // next of 1,2,5 × 10^n ≥ max, min 1024
    fun compact(cols: Int, rows: Int): Boolean = cols < 2 && rows < 2
}
```

- `Lang` is whatever `i18n/Strings.kt` uses. Check the existing `ActionsFormat` for the language type and the number formatting helpers, and reuse them.
- `BlockId`: `PERF_CPU("perf_cpu")`, `PERF_GPU("perf_gpu")`, `PERF_RAM("perf_ram")`, `PERF_NET("perf_net")`, `PERF_NPU("perf_npu")`. Each gets `Span(2,1)` as default and `Span(1,1)` as minimum, appended after `DOWNLOADS`.
- `ActionsBlocks.present`: each block is present when its meter is non-null. For `PERF_NET`, when `netDown != null`.

- [ ] Write the tests first:
  - parsing a full JSON and a partial one;
  - `available:false` gives null;
  - every format in fr and en (`rate(1_250_000)` gives "1,2 Mo/s"; `rate(82_000)` gives "80 Ko/s"; `rate(500)` gives "500 o/s");
  - `netScale(3_000_000)` gives 5_000_000 and `netScale(0)` gives 1024;
  - `compact`;
  - `present` with and without NPU;
  - new blocks land at the first free place in an existing saved layout. Copy the pattern of the launcher test in `BlockGridTest`.
- [ ] Run them and confirm they fail.
- [ ] Implement.
- [ ] Run them and confirm they pass.
- [ ] Commit `feat(android): perf state, formats and blocks`.

## Task 5 (Android): drawing the blocks

**Files:** create `ui/PerfBlock.kt` and the four drawables; modify `ui/ActionsScreen.kt` and `i18n/Strings.kt`.

- `PerfCard(icon: Int, name: String, value: String, detail: String?, series: List<List<Float>>, dashed: Set<Int>, compact: Boolean, modifier)`:
  - It uses the same glass card as the other blocks (`GlassCard`, or the tile background used by `LauncherTile`; match the Sound card look).
  - The top row holds the 22 dp icon, the name (16 sp SemiBold) and the value aligned right (16 sp).
  - Below that, `PerfGraph(series, dashed, Modifier.weight(1f).fillMaxWidth())`.
  - Then the detail line (12 sp, 0.7 alpha).
  - In compact mode: the icon, the name and the value only, centred.
- `PerfGraph`: a Compose `Canvas`.
  - Values are already normalised 0..1, oldest first, spread over the width.
  - Draw a smooth path (quadratic midpoints), white 2 dp. Series 0 gets a vertical gradient fill (white 0.25 down to 0 alpha). Dashed series use `PathEffect.dashPathEffect(floatArrayOf(8f, 6f))`.
  - Draw a faint baseline.
  - No BoxWithConstraints inside intrinsic rows. This crashed the app before.
- Normalisation, in the `BlockContent` branch:
  - percentages: `/100f`;
  - net: both histories divided by `PerfFormat.netScale(max of both)`.
- Labels:
  - `S.BLOCK_PERF_CPU` = "Processeur" / "CPU";
  - `S.BLOCK_PERF_GPU` = "GPU";
  - `S.BLOCK_PERF_RAM` = "RAM";
  - `S.BLOCK_PERF_NET` = "Wi-Fi";
  - `S.BLOCK_PERF_NPU` = "NPU".
  - Add them to `blockName(id)` too, for the "+ Ajouter" list.
- Net block content:
  - the value is "↓ " + rate(down);
  - the detail is "↑ " + rate(up);
  - the series are down (solid) and up (dashed).

- [ ] Implement it.
- [ ] Run `:app:testDebugUnitTest` and `:app:assembleDebug`. Both must pass.
- [ ] Commit `feat(android): performance blocks with live graphs`.

## Task 6: README and real test

- [ ] README, in the Actions mode section, add after the Lanceurs bullet: "- **Performances** : un bloc par mesure (Processeur, GPU, RAM, Wi-Fi, NPU) avec la valeur, une courbe des 60 dernières secondes et un détail (fréquence, mémoire, débit montant). Les blocs absents du PC (pas de NPU…) n'apparaissent pas."
- [ ] Commit `docs: README performance blocks`.
- [ ] Real test, done by the user: compare each block with the Task Manager under load.
