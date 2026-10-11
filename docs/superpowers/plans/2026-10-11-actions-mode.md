# Actions Mode Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A connected phone/tablet can take the "Actions" role and show native controls (clock, PC battery, volume/media, brightness, Wi-Fi/Bluetooth/airplane, USB drives) that drive the Windows PC, with no video and no virtual screen.

**Architecture:** Three new protocol messages (DEVICE_INFO 0x86, ACTIONS_STATE 0x04, ACTION 0x87, JSON payloads). PC: `host-prototype/actions/` providers + `ActionsHub` polling/broadcasting state; the engine branches on the role after HELLO. Android: role persisted, chosen on the waiting screen, `ActionsScreen` in Compose, orientation switched dynamically.

**Tech Stack:** Python 3.13 + ctypes, pycaw/comtypes, pywinrt (`winrt-*`), PySide6 app; Kotlin/Compose (BOM 2026.06.01), org.json.

**Spec:** `docs/superpowers/specs/2026-10-11-actions-mode-design.md` (every task reads the sections it names).

**Model per task (user preference: smallest model that fits):** marked on each task.

## Ground rules

- Repo `D:\TumorScreen App`, branch `pc-app`. PC tests: `cd host-prototype; .\.venv\Scripts\python.exe -m unittest discover -s tests` (557 OK at start) and `py -m unittest discover -s tests`. Android: `$env:JAVA_HOME = "C:\Program Files\Android\Android Studio\jbr"; cd android; .\gradlew.bat :app:testDebugUnitTest :app:assembleDebug`.
- TDD; never weaken assertions; English docstrings/log lines; user-visible PC text via `messages.py` keys (en+fr); Android texts in French for now (string literals as today).
- **No real system changes in automated tests or manual checks** unless the task says the user approved: never change real volume/brightness/radios, never eject a drive, never send media keys; read-only queries are fine. Never run the app/relay/adb against the tablet; never install on the device. Never run commands that read stdin.
- Commits end with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.

---

### Task 1 — Protocol messages (model: sonnet)

Spec §2. Files: `protocol/PROTOCOL.md`, `protocol/test-vectors.json`, `host-prototype/protocol.py`, `host-prototype/tests/test_protocol.py`, `android/app/src/main/java/com/orizonx/client/protocol/{Messages,FrameReader,FrameWriter}.kt`, Kotlin tests under `android/app/src/test/java/com/orizonx/client/protocol/`.

- Python: `DeviceInfo(role, kind, name, app)` decoded from 0x86; `Action(fields: dict)` from 0x87 (requires string `id`); `encode_actions_state(state: dict) -> bytes` (0x04, compact JSON, UTF-8, ≤ 64 KiB else ValueError). JSON errors / wrong types → ProtocolError. Constants `ACTIONS_STATE`, `DEVICE_INFO`, `ACTION`, `MAX_JSON = 65536`.
- Kotlin: `FrameWriter.deviceInfo(...)`, `FrameWriter.action(JSONObject)`; `FrameReader` decodes 0x04 into `ActionsStateMessage(json: JSONObject)` (parsing into a model is Task 8).
- Vectors: one per new message (hex + fields), checked by both test suites like the existing ones.
- PROTOCOL.md: document the three messages, the HELLO → DEVICE_INFO sequence, the 1 s default-to-screen rule, compatibility note.

### Task 2 — Runtime dependencies and packaging (model: sonnet)

Spec §3 (Dépendances). Create `host-prototype/requirements.txt` pinned (`pycaw`, `comtypes`, `psutil` if pulled, `winrt-runtime`, `winrt-Windows.Devices.Radios`, `winrt-Windows.Devices.Enumeration`, `winrt-Windows.Foundation`, `winrt-Windows.Foundation.Collections`), make `requirements-dev.txt` include it (`-r requirements.txt`), install into `.venv`. Read-only smoke script (scratchpad, not committed): import each lib, list radios (kind/state only), read master volume. Verify PyInstaller picks them up: add needed `--hidden-import`/`--collect-submodules winrt` to `build-pc.ps1`, build the app folder only (skip ISCC if long? no — full build is fine) and run the frozen exe with `--cleanup`? NO (touches display). Instead run a tiny frozen-import check: add a hidden `--selftest-imports` flag? Keep simple: after build, check `dist\OrizonX-PC\_internal` contains `winrt` and `pycaw` packages. Commit requirements + build script changes.

### Task 3 — Simple providers: clock, battery, media (model: sonnet)

Spec §3 table. Create `host-prototype/actions/__init__.py`, `actions/base.py` (`Provider` protocol, `ProviderError`), `actions/clock.py`, `actions/battery.py`, `actions/media.py`; tests with injected Win32 fakes (`GetSystemPowerStatus` struct values incl. no-battery 128, charging flags; SendInput called with the right VK and KEYEVENTF_KEYUP pair). Read-only smoke: real battery snapshot.

### Task 4 — USB drives provider (model: opus)

Spec §3 (`usb`). `actions/usb.py`: enumerate drives with bus type USB (removable and USB fixed disks), label/free/total; `usb.open` (os.startfile, injectable); `usb.eject`: volume → disk number (`IOCTL_STORAGE_GET_DEVICE_NUMBER`) → disk devinst (SetupAPI GUID_DEVINTERFACE_DISK match) → `CM_Get_Parent` → `CM_Request_Device_EjectW` with veto → `usb_busy` on veto, `usb_failed` on other errors. All Win32 through an injectable layer; tests with fakes (veto, success, unknown drive). Read-only smoke: list drives on this PC (may be empty). NEVER eject for real.

### Task 5 — Audio and brightness providers (model: sonnet)

Spec §3 (`audio`, `brightness`). `actions/audio.py` via pycaw (default render endpoint re-acquired when the default device changes — re-query each snapshot cheaply or on COM error); `volume.set` clamps 0..1; `volume.mute`. `actions/brightness.py`: WMI via comtypes `CoGetObject("winmgmts:root\\wmi")` (WmiMonitorBrightness.CurrentBrightness, WmiMonitorBrightnessMethods.WmiSetBrightness(1, level)); DDC/CI fallback via dxva2 (GetNumberOfPhysicalMonitorsFromHMONITOR, GetPhysicalMonitorsFromHMONITOR, Get/SetVCPFeature 0x10) for external monitors; available False if neither works. COM must be initialised per thread (CoInitializeEx in the hub thread — document; providers assume an initialised apartment). Tests with fakes; read-only smoke (read volume, read brightness).

### Task 6 — Radios, Wi-Fi SSID, Bluetooth devices (model: opus)

Spec §3 (`radios`, `wifi_info`, `bt_info`). `actions/radios.py` with pywinrt: `Radio.get_radios_async()`, kinds WI_FI / BLUETOOTH, `set_state_async`, access via `Radio.request_access_async()` → not ALLOWED → `radio_denied`. Airplane: remember states of all radios, turn all off; on airplane off restore remembered states (persist in memory only). Sync wrappers around WinRT async (`asyncio.run` in the provider thread or `.get()` style available in pywinrt — choose and document). `actions/wifi_info.py`: wlanapi ctypes SSID of the connected interface (none → ""). `actions/bt_info.py`: connected Bluetooth/BLE devices names via `DeviceInformation.find_all_async(aqs, ["System.Devices.Aep.IsConnected"], AssociationEndpoint)` filtered on IsConnected. Tests with fakes; read-only smoke (list radios and states, current SSID, connected BT names). NEVER change radio state for real.

### Task 7 — ActionsHub (model: sonnet)

Spec §3 (hub). `actions/hub.py`: `ActionsHub(providers: dict[str, Provider], send: Callable[[dict], None], clock, poll_fast_s=0.25, poll_slow_s=1.0, refresh_s=30.0, log)`; `start()/stop()`; thread does CoInitializeEx; builds state `{"v":1, <name>: snapshot...}` (usb as a list), sends on change or every refresh_s; `handle(action)` routes by id prefix (`volume.`→audio, `media.`, `brightness.`, `wifi.`/`bluetooth.`/`airplane.`→radios, `usb.`), sets `notice` once in the next state, forces an immediate poll. Provider exception → logged once, provider marked `{"available": False}` until it recovers. `default_providers()` builds the real set, tolerating ImportError (missing libs → unavailable). Tests with fake providers and fake clock.

### Task 8 — Engine integration + PC window (model: opus)

Spec §3 (Moteur), §5. Engine: after HELLO wait ≤ 1 s for DEVICE_INFO (reader thread already running — route DEVICE_INFO to a one-shot event); absent → screen. Role actions → actions session: no display/ffmpeg/injector; start `ActionsHub(send=lambda s: sock_send(encode_actions_state(s)))`; route ACTION messages to `hub.handle`; PING/PONG as today; end → hub.stop(). New `State.ACTIONS` with Msg detail key (en "{name} connected" / fr "{name} connecté"), title "Actions device"/"Appareil Actions", green, active. `Deps.actions_hub_factory` injectable. Tests: role actions never touches display/ffmpeg; ACTION routed; DEVICE_INFO absent → screen path; state sequence; stop → hub stopped. Window/tray: show the new state (status tables).

### Task 9 — Android: role, DEVICE_INFO, orientation, waiting screen (model: sonnet)

Spec §4. `DeviceRole` + persistence (SharedPreferences), default by `smallestScreenWidthDp`; send DEVICE_INFO right after HELLO (Session/Server code — read it); waiting screen: two large glass buttons Screen / Actions (current highlighted); switching role closes the current connection and reconnects; `requestedOrientation` SENSOR_LANDSCAPE vs FULL_SENSOR by role. Unit tests: default role by width, DEVICE_INFO bytes. Build + tests green. Do not install.

### Task 10 — Android: ActionsScreen (model: sonnet)

Spec §4 (ActionsScreen). `actions/ActionsState.kt` (immutable model parsed from JSONObject, tolerant to missing fields), `actions/ActionThrottle.kt` (≤ 20 Hz, final value on release), `ui/ActionsScreen.kt` (portrait column / landscape split, big clock ~64 sp ticking locally from epoch_ms + measured offset in the PC's UTC offset, battery line hidden if unavailable, audio card with slider/mute/media buttons, brightness card, Wi-Fi/Bluetooth/Airplane tiles, USB cards with Open/Eject, optimistic updates, notice snackbar ~3 s with French texts per code, haptic feedback, FLAG_KEEP_SCREEN_ON while in Actions). Unit tests for parsing and throttle. Build + tests green. Copy APK to `dist/OrizonX.apk`. Do not install.

### Task 11 — Build and real test (CONTROLLER, needs user approval)

Rebuild exe/setup, install APK on the tablet (warn: interrupts the stream), user switches the tablet to Actions, test each control live (volume both ways, media, brightness, Wi-Fi/BT toggles, airplane on/off restore, USB open/eject with a test stick), portrait/landscape on a phone if available. Fix findings via subagents.
