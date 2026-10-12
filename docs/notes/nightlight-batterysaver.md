# Night light and Energy saver toggles: research spike

Date: 2026-10-12. Target PC: Windows 11 Pro 25H2, build 26200.9168, hybrid laptop (AMD 890M + RTX 5070).
Scope: Orizon X Actions-mode tiles "Éclairage nocturne" and "Économiseur d'énergie".
Constraint: the host runs as a normal user. Here that means a medium-integrity token: the user is in
Administrators, but UAC filters the group to deny-only (`whoami /groups`).
Method: only **read** operations were run on this PC. Nothing was written to the registry or to power settings.
Every claim below about **setting** a value comes from documentation or community reports. None of it was tested here.

---

## 1. Night light (Éclairage nocturne)

### 1.1 No public API
Windows has no documented Win32 or WinRT API that turns Night light on or off.
Every tool that does it rewrites an undocumented binary value in the per-user CloudStore:

```
HKCU\Software\Microsoft\Windows\CurrentVersion\CloudStore\Store\DefaultAccount\Current\
  default$windows.data.bluelightreduction.bluelightreductionstate\
    windows.data.bluelightreduction.bluelightreductionstate   (value "Data", REG_BINARY)
  default$windows.data.bluelightreduction.settings\...settings (schedule, colour temperature)
```

Sources:
- nightlight-cli: https://github.com/nathanbabcock/nightlight-cli. Its README warns that recent Windows updates have broken it.
- tiny-screen `NightLight.cs`, the reverse-engineering origin: https://github.com/Maclay74/tiny-screen/blob/master/TinyScreen/Src/Services/NightLight.cs
- sem-reg-rs, a Rust crate and CLI that also documents the format: https://github.com/enyium/sem-reg-rs (`src/cloud_store/night_light/docs.md`)

### 1.2 Byte layout (from sem-reg docs.md and tiny-screen; consistent with what this PC holds)

```
43 42 01 00 0a 02 01 00 2a 06 <VLQ unix-seconds, 5 B>   outer prologue + change timestamp
2a 2b 0e <len>                                         len = byte count of the inner record
43 42 01 00                                            inner record signature
[10 00]                                                present  <=> Night light ACTIVE
[d0 0a 02]                                             present  <=> last change was manual (absent = schedule)
c6 14 <VLQ FILETIME, 9 B>                              precise time of last transition
00 00 00 00                                            trailer
```

- tiny-screen reads the state from **byte 18**, the inner length: `0x15` means on and `0x13` means off.
  To toggle, it inserts or removes `10 00` right after the inner signature, rewrites byte 18,
  and increments the prologue timestamp.
- sem-reg says Windows applies a written value **immediately**, with no logoff needed.
  It also gives two cautions:
  - If the prologue timestamp is **lower** than the one already stored, Windows undoes the write at once.
    Each write therefore has to bump that timestamp.
  - Some malformed writes leave the Night light engine broken until logoff. In bad cases the value
    has to be deleted to recover.
- Settings blob tags (sem-reg):
  - `02 01`: schedule enabled.
  - `c2 0a 00`: fixed hours instead of sunset-to-sunrise.
  - `ca 14 0e HH 2e MM`: start time.
  - `ca 1e ...`: end time.
  - `cf 28 <zigzag VLQ>`: colour temperature in Kelvin.
  - `ca 32` / `ca 3c`: sunset and sunrise.

### 1.3 What this PC holds (read-only dump, `winreg`)

```
default$...bluelightreductionstate   Data (41 B):
43 42 01 00 0a 02 01 00 2a 06 99 92 d0 d2 06 2a 2b 0e 13 43 42 01 00 d0 0a 02 c6 14
fd c9 c7 9d ea c8 c4 ee 01 00 00 00 00
{1af7386a-ad4b-4e12-96f2-d0f4552f2812}$...bluelightreductionstateperdevice   Data (42 B):
43 42 01 00 0a 02 01 00 2a 06 d5 dd f6 d2 06 2a 2b 0e 14 43 42 01 00 d0 0a 02 c6 14
fd c9 c7 9d ea c8 c4 ee 01 01 00 00 00 00
default$...settings   Data: ... 43 42 01 00 c2 0a 00 ca 14 0e 15 2e 0f 00 ca 1e 0e 07 00
                               ca 32 0e 12 2e 2d 00 ca 3c 0e 05 2e 11 00 00 00 00 00
```

Decoded:
- **Night light is OFF.** There is no `10 00`, and the inner length is `0x13`.
- The last change was manual (`d0 0a 02`). Its FILETIME is 2026-07-12 21:37:29 UTC.
- The schedule is off (no `02 01`). It is set to fixed hours, 21:15 to 07:00, with the default colour temperature.

**Important finding for 24H2 and 25H2:** this build also keeps **per-device** copies.
They use a `{1af7386a-...}$` prefix, the same device GUID as 27 other CloudStore keys on this PC.
The matching schemas, `Windows.Data.BlueLightReduction.BlueLightReductionStatePerDevice` and
`SettingsPerDevice`, exist under `HKLM\SOFTWARE\Microsoft\Windows\CurrentVersion\CloudStore\Schema`.
Mirrors of both families also sit under `DefaultAccount\Cloud`.

Timestamps:
- The per-device blob's prologue is newer: 2026-07-20 07:15. The `default$` blob's is 2026-07-12 23:37.
- Both carry the **same** transition FILETIME.

This looks like a migration that made the per-device record authoritative. The per-device inner record
has one extra byte (`01`) whose meaning is unknown. None of the public tools mention the per-device
values: nightlight-cli, tiny-screen and sem-reg all write only `default$`.
**On 26200 it is therefore unverified which copy the Night light engine actually reads.**
Writing only `default$` may do nothing, or Windows may overwrite it.

### 1.4 Alternatives considered
- `ms-settings:nightlight` is documented in the Microsoft "Launch Windows Settings" URI table:
  https://learn.microsoft.com/en-us/windows/apps/develop/launch/launch-settings-app
- UI Automation of Quick Settings is fragile and would steal focus on the PC. Rejected.
- An app-owned gamma ramp (`SetDeviceGammaRamp`) would imitate the effect, but it is not the Windows
  feature. It conflicts with Night light and HDR. Rejected.

### 1.5 Recommendation: Night light
1. **Read the state** by polling the registry value every 2–3 s, or using `RegNotifyChangeKeyValue` on both
   keys. Prefer the `{GUID}$...perdevice` key when it exists and fall back to `default$`.
   Night light is on when the inner record (after `2a 2b 0e <len> 43 42 01 00`) begins with `10 00`.
   Parse the record. Do not rely on a fixed offset, because the per-device record is one byte longer.
2. **Set the state** only behind an experimental flag, after a one-time manual test on this PC.
   The test should toggle both copies with a bumped prologue timestamp, then check the screen,
   then check that Settings agrees. Back up both blobs before any write and restore them on failure.
   Until that test passes, the tile should **open `ms-settings:nightlight`** and show the read state.
3. Risks:
   - The format is undocumented and changed in 24H2 with the per-device keys.
   - A bad write can break Night light until logoff.
   - Feature updates can silently change the format.

---

## 2. Battery saver / Energy saver (Économiseur d'énergie)

On 24H2 and later, Energy saver replaces Battery saver. It can be turned on from Quick Settings at any time,
set to start automatically at a battery threshold, or set to stay on while plugged in.
Source: https://learn.microsoft.com/en-us/windows-hardware/design/component-guidelines/energy-saver

### 2.1 Read APIs, tested on this PC (on AC, battery 100 %, Energy saver off)

| API | Result here | Notes |
|---|---|---|
| WinRT `PowerManager.EnergySaverStatus` (pywinrt 3.2.1) | `DISABLED` | The doc defines Disabled as off permanently **or plugged in**. Old 3-state model. |
| WinRT `PowerManager.IsEnergySaverStatus2Supported` / `EnergySaverStatus2` (through PowerShell's WinRT projection, since pywinrt 3.2.1 lacks it) | `False` / `Unknown` | Values: Unknown/Off/Standard/HighSavings. Present in the OS metadata (`IPowerManagerStatics2` {67a446c3-4f2e-5d56-b2e8-7707c264745b}) but reports **unsupported** on 26200.9168. |
| `GetSystemPowerStatus().SystemStatusFlag` | `0` | 1 means saver on. |
| `PowerRegisterForEffectivePowerModeNotifications(V2)` | `2 = Balanced` | Callback fires once on registration. `0 = EffectivePowerModeBatterySaver`. |
| `HKLM\SYSTEM\CurrentControlSet\Control\Power` `EnergySaverState` | `2` | Community reports 1 = on and 2 = off. Users have ReadKey only. A Microsoft Q&A answer says it may not update in real time. |
| `powercfg /qh SCHEME_CURRENT SUB_ENERGYSAVER` | ESBATTTHRESHOLD AC 0 / DC 0x1e (30 %); ESPOLICY AC 0 / DC 1; ESBRIGHTNESS 70 % | Read-only query. |

Known bug: on 24H2 and 25H2 (26100.6725 and 26200.7840), `EnergySaverStatus` and `SystemStatusFlag`
reported Off while Energy saver was visibly on above roughly 20 % battery.
A Microsoft employee pointed to `EnergySaverStatus2` as the fix:
https://learn.microsoft.com/en-us/answers/questions/5579583/powermanager-energysaverstatus-not-working-properl
The Windows App SDK feature request gives the same explanation: the legacy API reports Off in "Standard" mode.
https://github.com/microsoft/WindowsAppSDK/issues/6483
EnergySaverStatus2 enum: https://learn.microsoft.com/en-us/uwp/api/windows.system.power.energysaverstatus2

### 2.2 Set paths (none tested; based on evidence only)

| Path | Admin? | Works as "toggle now"? |
|---|---|---|
| Public on/off API | No such API. `PowerSetEnergySaverStatus` is **not exported** by powrprof.dll on this PC (checked with ctypes `hasattr`). The G-Helper maintainer says no documented way exists (https://github.com/seerge/g-helper/issues/3888). | n/a |
| `PowerWriteDCValueIndex` / `powercfg /setdcvalueindex SCHEME_CURRENT SUB_ENERGYSAVER ESBATTTHRESHOLD 100`, then `PowerSetActiveScheme` / `powercfg /setactive SCHEME_CURRENT` | Probably **no**. The read-only `powercfg /getsecuritydescriptor` shows `(A;CI;KRKW;;;BU)`, which gives Builtin Users read and write, on both `SCHEME_BALANCED` and `ActionSetActive`. | Community guides say 100 means "always on" **on battery** and 0 means never. Restoring the previous value (30) turns it off. It has **no effect on AC**. Whether AC index 100 maps to "always on when plugged in" is undocumented. ESBATTTHRESHOLD doc: https://learn.microsoft.com/en-us/windows-hardware/customize/power-settings/battery-threshold |
| `PowerSetActiveOverlayScheme` (exported) | Unknown | It changes the **power mode** overlay (Best efficiency / Balanced / Best performance), not Energy saver. Do not confuse the two. On this PC the DC overlay is `961cc777-...` (best efficiency) and the AC overlay is all zeros. |
| `HKLM\...\Power\EnergySaverState` write | **Yes** (Users have ReadKey only) | Community reports it needs a reboot. Rejected. |
| Group Policy / Intune "Energy saver always on" | Admin | Rejected. |

### 2.3 Recommendation: Energy saver
1. **Read the state** with the effective power mode callback. Register once at host start;
   `mode == 0` means saver on. That is event-driven and needs no polling.
   As secondary signals, use `EnergySaverStatus2` when `IsEnergySaverStatus2Supported` returns true
   (this needs a raw ABI call through `IPowerManagerStatics2` or a newer pywinrt), and `SystemStatusFlag`.
   Also send `ACLineStatus`, so the tile can show "on AC" and be disabled.
   Before trusting the callback, check it once manually: turn Energy saver on from Quick Settings
   while unplugged, above 20 %, and confirm `mode == 0`. That is the case where the legacy APIs fail.
2. **Set the state:** on 26200 there is no reliable on/off toggle without admin. Default tile action:
   **open `ms-settings:batterysaver`**. That page is available on devices with a battery.
   An optional experimental "force on battery" mode can be added later: write DC ESBATTTHRESHOLD to 100
   and re-apply the active scheme, then restore the saved value to turn it off. That changes a persistent
   user setting, the saved threshold has to be stored by the host, and it does nothing while plugged in.
   Before shipping it, test it once by hand on this laptop on battery.
3. Risks:
   - The status APIs are inconsistent on 24H2 and 25H2, as described above.
   - The threshold hack leaves the setting at 100 if the host crashes before restoring it.
   - The behaviour of the 25H2 "adaptive energy saver" is undocumented.

---

## 3. Commands used (all read-only)
- Python `winreg.QueryValueEx` and `EnumKey` on the CloudStore keys listed above.
- `powercfg /getactivescheme`, `/qh SCHEME_CURRENT SUB_ENERGYSAVER`, and `/getsecuritydescriptor SCHEME_BALANCED|ActionSetActive|ActionCreate`.
- Python `winrt.windows.system.power.PowerManager` (winrt-Windows.System.Power 3.2.1, installed only into the scratch dir) and `GetSystemPowerStatus`.
- `PowerGetEffectiveOverlayScheme` and `PowerRegisterForEffectivePowerModeNotifications` / `Unregister`.
- PowerShell `[Windows.System.Power.PowerManager]::IsEnergySaverStatus2Supported` / `EnergySaverStatus2`.
- `Get-ItemProperty HKLM:\SYSTEM\CurrentControlSet\Control\Power` and `Get-Acl` on the same key.
