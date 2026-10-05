# Installer + App-Driven Virtual Display Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** One `OrizonX-Setup.exe` (English by default, French selectable) that installs the app plus the VDD virtual display driver; the app creates the virtual screen only while a tablet is connected, places it and scales it, and is fully bilingual with an explicit Quit button.

**Architecture:** New Qt-free modules in `host-prototype/`: `vdd.py` (VDD named-pipe + XML control), `display_layout.py` (position/scale maths + Windows CCD API via ctypes), `virtual_display.py` (screen lifecycle: appear on HELLO, 5 s grace on leave, cleanup on start). The engine gains a display hook and a `PREPARING_DISPLAY` state, answering PINGs while the screen is being prepared. `app/i18n.py` makes every visible string bilingual. Inno Setup 6 builds the installer from `installer/orizonx.iss`.

**Tech Stack:** Python 3.13 stdlib + ctypes (user32 CCD API, named pipes), PySide6 6.11, PyInstaller 6.22, Inno Setup 6, devcon (from the VDD package), unittest.

**Spec:** `docs/superpowers/specs/2026-10-05-installer-virtual-display-design.md` — every task implementer reads the sections named in its task.

**Why this plan specifies interfaces and tests rather than verbatim code:** the VDD pipe protocol is only known after Task 1. Each task gives the exact public interface, behaviour and test cases; implementers write the code test-first.


## REVISION after Task 1 (overrides Tasks 3, 5, 7, 9 where they conflict)

Read `docs/notes/vdd-control.md` and spec §8. Changes:

- **Task 3 `vdd.py`:** `VddController` keeps only `is_installed()` (pipe `PING`, UTF-16LE, overlapped read per the notes), XML helpers (`read_resolutions()`, `add_resolutions(list)` → bool changed; atomic write + one-time backup; `count` forced to 1), `set_gpu_in_xml(name)`, and device helpers (in a separate module `vdd_device.py`, Windows-only, admin): `find_device()` (registry scan for hardware ID `Root\MttVDD` under `HKLM\SYSTEM\CurrentControlSet\Enum\ROOT\DISPLAY`, no admin), `install_driver(inf_path)` (SetupAPI root device + `UpdateDriverForPlugAndPlayDevicesW`), `remove_driver()` (`SetupDiRemoveDevice` + `pnputil /delete-driver`), `restart_device()` (`pnputil /restart-device <instance id>`). No `SETDISPLAYCOUNT`/`RELOAD_DRIVER`/`SETGPU` over the pipe, ever. `COMMON_RESOLUTIONS` list from spec §8 lives here.
- **Task 4 `display_layout.py`:** add `set_path_active(monitor_key, active: bool)` (SetDisplayConfig: enable/disable the VDD target's path; keep `SDC_SAVE_TO_DATABASE` so Windows remembers), `find_vdd_monitor()` (CCD: the path whose target device path / EDID manufacturer identifies VDD — the notes give the identification; key = adapter LUID + target id), `available_modes(monitor_key)`; `pick_mode(available, w, h)` (pure: exact, else same aspect ±1 % largest, else largest that fits).
- **Task 5 `virtual_display.py`:** `prepare()` = find VDD monitor → pick mode → activate path with that mode → wait for the Windows monitor of that size (≤ 10 s) → first-time layout. Returns `(rect, exact: bool)`. `release()` = deactivate path after grace (immediate on Quit). `cleanup_on_start()` = deactivate path. No pipe commands.
- **Task 7 app:** CLI flags become `--cleanup` (deactivate path), `--install-driver <inf>`, `--remove-driver`, `--configure-vdd` (GPU friendly name + `COMMON_RESOLUTIONS` into XML, count 1; no restart), `--add-resolution WxH` (admin: add to XML + `restart_device()`). Window: when `exact` is False, show "Add exact resolution" button → `ShellExecuteW(None, "runas", sys.executable, "--add-resolution WxH", ...)`. Settings/UI/i18n keys accordingly.
- **Task 9 installer:** no devcon. Order in `[Code]`/`[Run]` (elevated, hidden, exit codes checked): `--configure-vdd` → if no existing device: show the SignPath info page, then `--install-driver "{app}dd\MttVDD.inf"` (record `VddInstalledByUs=1`) else `restart_device` via `--add-resolution` path equivalent (`--configure-vdd --restart`) so the new resolutions load → icacls on `C:\VirtualDisplayDriver` → language to HKCU and HKLM. Uninstall: `--cleanup`, then if `VddInstalledByUs=1` ask, then `--remove-driver`. `installer/vdd/` = `MttVDD.inf`, `MttVDD.dll`, `mttvdd.cat`, `LICENSE` (MIT text fetched from the GitHub repo), `SOURCE.txt`.
- **Task 8 (real PC)** also checks: path deactivation hides the screen and reactivation restores position/scale; plugging another monitor while the app is closed does not wrongly re-enable the virtual screen (or, if it does, `cleanup_on_start` fixes it at next launch).

## Ground rules (all tasks)

- Repo `D:\TumorScreen App`, branch `pc-app`. Tests: `cd host-prototype; .\.venv\Scripts\python.exe -m unittest discover -s tests` (all) and `py -m unittest discover -s tests` (Qt tests skip). 183 pass at the start.
- **Display safety:** the user's PC already has VDD installed and may be streaming to the tablet. Unless a task explicitly says the user has approved it, NEVER send `SETDISPLAYCOUNT`, `RELOAD_DRIVER`, `SETGPU` to the real pipe, NEVER call `SetDisplayConfig`/`DisplayConfigSetDeviceInfo` for real, NEVER edit `C:\VirtualDisplayDriver\vdd_settings.xml`, NEVER run devcon/pnputil, NEVER run adb or the relay/app against the tablet. Read-only calls (`QueryDisplayConfig`, `PING`, `GETSETTINGS`, reading the XML) are allowed.
- Never run commands that read stdin. Use timeouts.
- TDD: failing test first, then code. Never weaken assertions to pass.
- Keep the established style: English docstrings, French inline comments are fine, small focused modules.
- Commits end with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.

---

### Task 1: Spike — VDD control protocol and Windows display APIs (research, no code in the app)

**Output:** `docs/notes/vdd-control.md` (commit it). It must answer, with evidence (source links + line excerpts ≤ 15 lines each, or observed outputs):

1. Pipe `\\.\pipe\MTTVirtualDisplayPipe`: message encoding (UTF-16LE? bytes?), framing (one message per connection? terminator?), exact syntax of `PING`, `GETSETTINGS`, `SETDISPLAYCOUNT <n>`, `SETGPU "<name>"`, `RELOAD_DRIVER`, and the responses. Source of truth: the driver source on GitHub `VirtualDrivers/Virtual-Display-Driver` (look for the pipe handler, e.g. `HandleClient` in `Driver.cpp`; use the tag/branch matching driver version 25.7.23 / DriverVer 11.30.4.434 if you can identify it).
2. Does `SETDISPLAYCOUNT` persist `<count>` in the XML and recreate monitors by itself, or must the XML be edited + `RELOAD_DRIVER` sent? Is a resolution added to `<resolutions>` picked up by `RELOAD_DRIVER`? Where does the driver read the XML from (path, registry override)?
3. Allowed real checks on this PC (read-only): connect to the pipe and send `PING` and `GETSETTINGS` only; record exact replies. Read `C:\VirtualDisplayDriver\vdd_settings.xml`.
4. devcon command lines to install (`devcon install MttVDD.inf Root\MttVDD`) and remove (`devcon remove Root\MttVDD`), how to detect an existing `Root\MttVDD` device without devcon (e.g. `pnputil /enum-devices /class Display` output or SetupAPI) — document, do not run install/remove. devcon licence: where it comes from and whether it can be redistributed (the VDD repo ships it; note its licence statement).
5. Windows CCD: confirm with a read-only ctypes probe (`GetDisplayConfigBufferSizes` + `QueryDisplayConfig(QDC_ONLY_ACTIVE_PATHS)`) that you can list active paths with source mode positions and sizes; give the struct layouts you used. Document the DPI scale get/set via `DisplayConfigGetDeviceInfo`/`DisplayConfigSetDeviceInfo` with types -3 (get) / -4 (set), struct layout and the meaning of the relative value (index around the recommended step in the list 100,125,150,175,200,225,250,300,350,400,450,500), with a reference to a known implementation (e.g. the open-source "SetDPI" / "windows-DPI-scaling-sample"). Read-only GET on the current monitors is allowed; do not SET.
6. Inno Setup 6: ISCC path when installed by winget (`JRSoftware.InnoSetup`), how to run a post-install `[Run]` step elevated with a hidden window and check its exit code in `[Code]`, `ShowLanguageDialog`, built-in French messages file name (`compiler:Languages\French.isl`), `CloseApplications`, uninstall `[Code]` hooks for asking a question. Do not install Inno Setup.

Report: the doc path, a 10-line summary, and anything that contradicts the spec.

---

### Task 2: `app/i18n.py` and bilingual engine messages

**Spec:** §5 (Langue).

**Files:** create `host-prototype/app/i18n.py`, `host-prototype/messages.py` (Qt-free, shared by engine/CLI/app), tests `tests/test_i18n.py`; modify `engine.py`, `relay.py`, `app/status.py`, `app/window.py`, `app/tray.py`, `app/main.py`, and their tests.

**Interface:**
- `messages.py`: `TEXTS: dict[str, dict[str, str]]` with `"en"` and `"fr"` for every key; `def tr(key: str, lang: str = "en", **args) -> str` (unknown lang → en; missing key → raises KeyError in tests, returns the key in production? → raise, keep it strict); `class Msg(NamedTuple): key: str; args: dict` with `def text(self, lang) -> str`.
- Engine: `Listener.on_state(state, detail)` keeps its signature but `detail` becomes a `Msg` (not a str). `FatalError` carries a `Msg`. Every French sentence currently built in `engine.py` for the user becomes a key. Log lines (`on_log`) stay plain English strings (they go to the log file, not the UI) — translate the existing French log lines to English.
- `app/i18n.py`: `current_language()` (settings → `HKCU\Software\OrizonX\Language` → `"en"`), `set_language(lang)` emitting a Qt signal `language_changed` on a module-level `QObject`, re-export `tr`.
- `status.py`: titles/labels become keys; functions take `lang`.
- Window/tray: all visible strings via `tr`; `retranslate()` re-applies them on `language_changed`.
- CLI prints English (`Msg.text("en")`).
- Settings: add `language: str | None = None` (None = follow installer/registry).

**Tests:** every key has en+fr; the `{name}` placeholders are identical in both; engine tests assert on `Msg.key` instead of French substrings (update all existing tests accordingly); window test: switching language to fr changes the primary button text to "Arrêter"/"Démarrer"… and back to "Stop"/"Start".

**English wording:** short, plain, sentence case (e.g. "Waiting for the tablet", "Open Orizon X on the tablet.", "Connected", "Error", "Stopped", "Click Start.", "Preparing the screen…", "Virtual display driver not found. Reinstall Orizon X, or switch to Duplicate mode.").

---

### Task 3: `vdd.py` — VddController

**Spec:** §2. **Depends on:** Task 1 findings (`docs/notes/vdd-control.md`) — read it first.

**Interface:**
```python
class VddError(Exception): ...
class VddController:
    def __init__(self, settings_path: Path = Path(r"C:\VirtualDisplayDriver\vdd_settings.xml"),
                 transport: Callable[[str], str] | None = None) -> None
    def is_installed(self) -> bool            # PING answered
    def set_display_count(self, n: int) -> None
    def ensure_resolution(self, width: int, height: int, refresh: int = 60) -> bool  # True if XML changed
    def set_gpu(self, friendly_name: str) -> None
    def reload(self) -> None
```
- `transport(message) -> reply` defaults to a real named-pipe client (ctypes `CreateFileW`/`WriteFile`/`ReadFile` or `open(r"\\.\pipe\...", "r+b")`, per Task 1 framing) with a 2 s timeout; tests inject a fake.
- XML editing with `xml.etree.ElementTree`, preserving all other elements and comments as far as ElementTree allows (document the limitation); atomic write; one-time backup `vdd_settings.xml.bak-orizonx`.
- Use the pipe commands where Task 1 shows they work; edit XML + reload otherwise.

**Tests:** fake transport records messages and replies; XML round trip on a copy of the real XML structure (inline fixture), resolution added once, unknown sections kept, backup created once, atomic write leaves no temp file; `is_installed` false when transport raises.

---

### Task 4: `display_layout.py` — position and scale

**Spec:** §3 (Position, Échelle).

**Interface (pure):**
```python
@dataclass(frozen=True) class Rect: left: int; top: int; width: int; height: int
def place(primary: Rect, size: tuple[int, int], side: str) -> tuple[int, int]   # side: right|left|above|below; centred on that edge
SCALE_STEPS = (100, 125, 150, 175, 200, 225, 250, 300)
def auto_scale(dpi: int) -> int     # round(dpi/96*0.75) to nearest step, clamp 100..300 ; 274 -> 200
def relative_scale_index(target: int, recommended: int) -> int   # per Task 1 semantics
```
**Interface (Windows, ctypes):** `active_monitors() -> list[MonitorPath]` (QueryDisplayConfig: adapter/source ids, position, size, is_primary), `set_position(path, x, y)` (SetDisplayConfig with supplied config, SDC_APPLY|SDC_USE_SUPPLIED_DISPLAY_CONFIG|SDC_SAVE_TO_DATABASE|SDC_ALLOW_CHANGES), `get_scale(path) -> (current, recommended)`, `set_scale(path, percent)`.
**Tests:** `place` for the 4 sides with primary at origin and with a primary that is not at (0,0) and another monitor at negative coords; `auto_scale` table (96→100, 160→125, 274→200, 400→300, 60→100); `relative_scale_index` table; ctypes structs sizes (sizeof checks against Task 1 layouts); `active_monitors()` read-only smoke test on Windows (returns ≥ 1 primary). Never call the setters in tests except through injected fakes.

---

### Task 5: `virtual_display.py` — screen lifecycle

**Spec:** §3 (Cycle de vie).

**Interface:**
```python
class VirtualDisplay:
    def __init__(self, vdd: VddController, layout=display_layout, monitors=injector.monitors,
                 clock=time.monotonic, sleep=time.sleep, grace_s=5.0, appear_timeout_s=10.0) -> None
    def cleanup_on_start(self) -> None                       # count 0, ignore errors when VDD absent
    def prepare(self, width, height, dpi, position, scale, first_time: bool, should_stop) -> None
        # ensure_resolution + count 1, wait for a w×h monitor (≤ appear_timeout_s, polling 200 ms,
        # abort if should_stop()), apply position+scale if first_time (errors logged, not raised);
        # raises FatalError(Msg("display_timeout")) on timeout, FatalError(Msg("vdd_missing")) if not installed
    def release(self, immediate: bool = False) -> None      # schedules count 0 after grace_s; immediate for Quit
    def cancel_release(self) -> None                         # tablet came back within grace
    def apply_layout(self, position, scale) -> None          # live change from the UI while streaming
```
- The grace timer is a `threading.Timer`-like object injectable for tests (or driven by the injected clock in a small background thread). `release` then `prepare` within grace → no count change at all.
- `prepare` returns which monitor matched (Rect) so the engine can map it to a ddagrab index.

**Tests:** fakes for vdd/layout/monitors/clock: appear OK; timeout → FatalError key; should_stop aborts; grace release; cancel within grace; immediate release; cleanup tolerant of missing driver; first_time applies layout once, later no layout calls; layout failure logged and not fatal.

---

### Task 6: Engine integration

**Spec:** §4.

- `Config`: add `mode: str = "extend"`, `position: str = "right"`, `scale: str = "auto"`; `RelayEngine(..., display: VirtualDisplay | None = None, layout_state: Callable[[], bool] / on_layout_applied: Callable[[], None])` — keep it simple: pass `first_time` from a callback the app owns (settings flag `layout_applied`).
- New `State.PREPARING_DISPLAY`.
- Session order when `display` is set and `mode == "extend"`: connect → HELLO → start tablet reader (answers PING) → `PREPARING_DISPLAY` → `display.prepare(...)` → probe outputs and pick the one matching the tablet size → ffmpeg. On session end: `display.release()`; on `stop()` from Quit: `release(immediate=True)` (add `stop(immediate_display_release: bool = False)`).
- `mode == "duplicate"` or `display is None`: current behaviour (output from config, default 0 for duplicate).
- `engine.start()` calls `display.cleanup_on_start()` once per engine instance? No — the app calls `cleanup_on_start()` once at app start (Task 7); the engine never does.
- Tests (fakes): PING answered while prepare blocks (fake prepare waits on an Event; tablet sends PING, expects PONG before releasing); state sequence includes PREPARING_DISPLAY; prepare timeout → ERROR with key; duplicate mode never calls display; release called on tablet leave, immediate on stop(immediate…).

---

### Task 7: App — settings UI, Quit button, VDD diagnostic, CLI flags

**Spec:** §5 (Fenêtre, Diagnostic) and §6 (`--configure-vdd`, `--cleanup`).

- Settings gain `mode`, `position`, `scale`, `layout_applied: bool`, `language`. Remove `output` from the app (keep reading old files gracefully).
- Window: combos Mode / Position / Scale / Encoder / Language, link "Adjust in Windows…" (`os.startfile("ms-settings:display")`), bottom row [primary][Quit]. Position/Scale disabled in Duplicate. "Use Duplicate" button visible only on the VDD-missing error. Height grows as needed (≈ 520 px); verify nothing is clipped with an offscreen grab (`window.grab().save(...)`, view it).
- `main.py`: at startup `VirtualDisplay(VddController()).cleanup_on_start()`; factory builds the engine with the display; Position/Scale change while streaming → `display.apply_layout` (no restart); Mode/Encoder change → restart; Language → retranslate only. Quit (button and tray) → `stop_blocking(immediate_display_release=True)` (extend Controller accordingly).
- New CLI flags of the app exe (parsed in `main.py` before Qt starts): `--cleanup` (count 0, exit 0, no window) and `--configure-vdd` (admin context during install: set GPU friendly name of the adapter driving the primary display — find it via `EnumDisplayDevicesW` primary device `DeviceString` — write minimal XML: count 0, that GPU, 1920×1080@60 plus keep existing resolutions if a file exists; exit code 0/1; no window). Both log to the usual log file.
- Tests: window (combos, disabled states, Quit emits quit_requested, Use Duplicate visibility), main wiring with fakes (position change while streaming calls apply_layout without restart; Quit uses immediate release), `--cleanup` and `--configure-vdd` with injected VddController/fake EnumDisplayDevices (no real calls).

---

### Task 8: Real-PC verification of the virtual display (CONTROLLER ONLY, needs user approval)

Not for a subagent. The controller asks the user, then on the real PC (VDD already installed): app from source in Extend mode → tablet connect → screen appears at tablet resolution, placed right, 200 %; unplug → disappears after ~5 s; replug within 5 s → no flicker; Position left while streaming; Quit → screen gone, tablet "PC disconnected"; `taskkill /f` then relaunch → leftover screen removed. Fix findings via a subagent.

---

### Task 9: Installer (Inno Setup) and build

**Spec:** §6. **Depends on:** Task 1 (Inno details), Task 7 (`--configure-vdd`, `--cleanup`).

- `installer/orizonx.iss`: AppId fixed GUID, AppName "Orizon X", version from a `#define` passed by the build script, `PrivilegesRequired=admin`, `ArchitecturesAllowed=x64compatible`, `ArchitecturesInstallIn64BitMode=x64compatible`, `ShowLanguageDialog=yes`, languages English (default) + French, `CloseApplications=yes`, `SetupIconFile`, `WizardStyle=modern`, LicenseFile = `installer/LICENSES.txt` (create: short MIT notice for VDD + GPL notice for ffmpeg with source link; English), tasks desktopicon (checked) / autostart (unchecked), `[Files]` from `dist\OrizonX-PC\*` and `installer\vdd\*` (to `{app}\vdd`), `[Registry]` HKCU Language (from `ActiveLanguage`), `[Run]` hidden elevated: driver detection/installation via `[Code]` (existing `Root\MttVDD` → skip; else devcon install; record `VddInstalledByUs`), then `OrizonX.exe --configure-vdd`, then `icacls "C:\VirtualDisplayDriver" /grant *S-1-5-32-545:(OI)(CI)M`; postinstall "Launch Orizon X". Messages for driver failure as in the spec. `[UninstallRun]` `--cleanup`; `[Code]` uninstall question for driver removal when `VddInstalledByUs=1`.
- `installer/vdd/`: not committed if large? They are small (≈ 400 KB) — commit `MttVDD.inf`, `MttVDD.dll`, `mttvdd.cat`, `devcon.exe`, `LICENSE` copied from the local winget package (x64 = the folder named `x86` in the package if Task 1 confirms the binaries are x64 — verify with the PE header machine field), plus `installer/vdd/SOURCE.txt` (origin URL, version, date).
- `build-pc.ps1`: after the app build, find `ISCC.exe` (winget path from Task 1, or `${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe`); if found compile to `dist\OrizonX-Setup.exe` with `/DAppVersion=…`; if not found, print how to install it and still succeed for the app folder. Version: `host-prototype/version.py` (`__version__ = "0.5.0"`) used by the app (window tooltip/about line) and the installer.
- Do NOT install Inno Setup yourself: the controller does it after user approval, then you (or a follow-up) compile and fix.

---

### Task 10: Installer test in Windows Sandbox (CONTROLLER, needs user approval)

Controller asks the user to enable Windows Sandbox (optional feature, reboot may be needed) or does it with approval; then runs `OrizonX-Setup.exe` inside the sandbox via a `.wsb` file mapping `dist` read-only and a logon command that runs the setup silently (`/VERYSILENT /SUPPRESSMSGBOXES /LOG=...`) plus a manual interactive pass; checks: language dialog, files, `Root\MttVDD` present, XML count 0 + ACL, app starts (ERROR no tablet), uninstall removes app and (on yes) driver.

---

### Task 11: README and docs

Rewrite the README "Install / Run" for end users first (download two files, install, prepare tablet → link to guide placeholder for sub-project 4), keep a "Developer" section with build/test/CLI. Document SmartScreen ("More info" → "Run anyway"), admin prompt once, Extend/Duplicate, Position/Scale, Quit, language, uninstall. Update the PC app checklist with the new items.
