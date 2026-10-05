# VDD control, Windows display APIs and Inno Setup — research notes (Task 1)

Date: 2026-10-05. Branch `pc-app`. Scope: Task 1 of
`docs/superpowers/plans/2026-10-05-installer-virtual-display.md` (spec §2, §3, §6).

Everything below is either a source excerpt (with a permalink) or an output observed on the
user's PC. All probes ran **non-elevated** (medium integrity, `IsInRole(Administrator) = False`) and
were read-only: pipe `PING` / `GETSETTINGS` only, `GetDisplayConfigBufferSizes`,
`QueryDisplayConfig`, `DisplayConfigGetDeviceInfo` (types 1, 2, -3), `EnumDisplayDevicesW`,
`pnputil /enum-devices`, `reg query`, `icacls` (display only), event-log reads.

## TL;DR (read this first)

1. Pipe protocol: one command per connection, **UTF-16LE, no terminator, ≤ 127 chars**; the
   server reads once, answers (or not), then `DisconnectNamedPipe`. `PING` → 4 ASCII bytes
   `PONG`. `GETSETTINGS` → UTF-16LE `SETTINGS DEBUG=false LOG=false` + U+0000.
2. **`<count>0</count>` does not remove the screen**: the driver forces 0 → 1 monitor.
3. **There is no working "reload"**: `RELOAD_DRIVER`, `SETDISPLAYCOUNT`, `SETGPU`, `HDRPLUS`…
   all call `ReloadDriver(hPipe)`, which passes the *pipe handle* to a WDF accessor and crashes the
   UMDF host (upstream issue #351). The new XML is only read again because the crashed device is
   restarted. Matching crashes (`c0000005` in `WUDFx02000.dll`, module `mttvdd.dll`) are in this
   PC's event log on 2026-10-01.
4. The XML (count, GPU, resolutions) is read **only when the device starts** (`DeviceAdd`). A
   resolution added to `<resolutions>` is visible only after a device restart.
5. Consequence: the spec's "count 1 on HELLO / count 0 on leave" cannot work as written.
   Recommendation: keep the VDD at **count 1 permanently** and make the screen appear/disappear
   by **activating/deactivating its display path with `SetDisplayConfig`** (no admin, no driver
   restart). Restart the device only when a new resolution must be added.
6. The CCD read probe works from Python ctypes (struct sizes 72/64/20/84/420/32/24). The DPI
   relative value is confirmed on this PC: `DpiVals[|minScaleRel| + curScaleRel]` = current %.

---

## 1. Pipe `\\.\pipe\MTTVirtualDisplayPipe`

### Which source matches the installed binary

- Installed INF (winget package, `SignedDrivers\x86\VDD\MttVDD.inf`): `DriverVer = 12/24/2024,11.30.4.434`.
- The GitHub tag `25.7.23` (commit `d437ebc9b4`) contains source **newer** than the binary: strings
  `ColourFormat` and `SendLogsThroughPipe` exist in the 25.7.23 source but **not** in the installed
  `MttVDD.dll`. The binary matches tag **`24.12.24`** (commit `b07c8cc80c`), i.e. the 25.7.23
  release re-ships the 24.12.24 driver.
- `HandleClient` is byte-for-byte identical in 24.12.24 and 25.7.23 (`diff` of the function: no
  difference), and it is still the same on `master` (2026-04) — `ReloadDriver(hPipe)` unchanged.
- Strings checked in the installed DLL: `Loading singular monitor`, `Adapter reinitialized`,
  `PONG` (ASCII); `SETTINGS `, `SDR10`, `CUSTOMEDID`, `GETALLGPUS`, `D3DDEVICEGPU` (UTF-16LE).

Permalink base used below (24.12.24):
`https://github.com/VirtualDrivers/Virtual-Display-Driver/blob/b07c8cc80c95042a8b5a1a97e67c8e4a51ab8c10/Virtual%20Display%20Driver%20(HDR)/MttVDD/Driver.cpp`

### Server: message pipe, one instance at a time, DACL Everyone

[Driver.cpp#L1096-L1103](https://github.com/VirtualDrivers/Virtual-Display-Driver/blob/b07c8cc80c95042a8b5a1a97e67c8e4a51ab8c10/Virtual%20Display%20Driver%20(HDR)/MttVDD/Driver.cpp#L1096-L1103)
(the SDDL `D:(A;;GA;;;WD)` is on L1085):

```cpp
		hPipe = CreateNamedPipeW(
			PIPE_NAME,
			PIPE_ACCESS_DUPLEX,
			PIPE_TYPE_MESSAGE | PIPE_READMODE_MESSAGE | PIPE_WAIT,
			PIPE_UNLIMITED_INSTANCES,
			512, 512,
			0,
			&sa);
```

The loop creates one instance, `ConnectNamedPipe`, `HandleClient`, then loops: clients are served
**sequentially**. Between two clients there is a short window with no instance: my first probe
got `ERROR_FILE_NOT_FOUND` (2) when reconnecting immediately; the next runs connected at the first
attempt. → Retry on error 2 and `ERROR_PIPE_BUSY` (231) for a few hundred ms.

### Request: a single `ReadFile` of at most 254 bytes, UTF-16LE

[Driver.cpp#L868-L882](https://github.com/VirtualDrivers/Virtual-Display-Driver/blob/b07c8cc80c95042a8b5a1a97e67c8e4a51ab8c10/Virtual%20Display%20Driver%20(HDR)/MttVDD/Driver.cpp#L868-L882):

```cpp
void HandleClient(HANDLE hPipe) {
	g_pipeHandle = hPipe;
	vddlog("p", "Client Handling Enabled");
	wchar_t buffer[128];
	DWORD bytesRead;
	BOOL result = ReadFile(hPipe, buffer, sizeof(buffer) - sizeof(wchar_t), &bytesRead, NULL);
	if (result && bytesRead != 0) {
		buffer[bytesRead / sizeof(wchar_t)] = L'\0';
		...
		if (wcsncmp(buffer, L"RELOAD_DRIVER", 13) == 0) {
```

- Encoding: UTF-16LE (`wchar_t`), no terminator needed (the server adds `L'\0'`).
- Framing: exactly **one message per connection**; after the `if/else` chain the server calls
  `DisconnectNamedPipe` + `CloseHandle`. A message > 254 bytes makes `ReadFile` fail with
  `ERROR_MORE_DATA` → `result` is FALSE → the command is silently ignored. Max 127 UTF-16 chars.
- Matching is by **prefix** (`wcsncmp`), so `PINGxyz` is a PING.

### Commands and replies

[Driver.cpp#L1028-L1062](https://github.com/VirtualDrivers/Virtual-Display-Driver/blob/b07c8cc80c95042a8b5a1a97e67c8e4a51ab8c10/Virtual%20Display%20Driver%20(HDR)/MttVDD/Driver.cpp#L1028-L1062) (abridged, ≤ 15 lines):

```cpp
		else if (wcsncmp(buffer, L"SETDISPLAYCOUNT", 15) == 0) {
			int newDisplayCount = 1;
			swscanf_s(buffer + 15, L"%d", &newDisplayCount);
			if (UpdateXmlDisplayCountSetting(newDisplayCount)){ ... }
			ReloadDriver(hPipe);
		}
		else if (wcsncmp(buffer, L"GETSETTINGS", 11) == 0) {
			wstring settingsResponse = L"SETTINGS ";
			settingsResponse += debugEnabled ? L"DEBUG=true " : L"DEBUG=false ";
			settingsResponse += loggingEnabled ? L"LOG=true" : L"LOG=false";
			DWORD bytesToWrite = static_cast<DWORD>((settingsResponse.length() + 1) * sizeof(wchar_t));
			WriteFile(hPipe, settingsResponse.c_str(), bytesToWrite, &bytesWritten, NULL);
		}
		else if (wcsncmp(buffer, L"PING", 4) == 0) {
			SendToPipe("PONG");          // std::string → narrow bytes
```

| Command (UTF-16LE) | Exact syntax | Reply | Side effect |
|---|---|---|---|
| `PING` | `PING` | `b"PONG"` (4 bytes, ASCII, no NUL) | none |
| `GETSETTINGS` | `GETSETTINGS` | UTF-16LE `SETTINGS DEBUG=<b> LOG=<b>` + `\0\0` | none (reads registry/XML) |
| `SETDISPLAYCOUNT` | `SETDISPLAYCOUNT 2` (`%d` after char 15; missing/invalid → 1) | none | rewrites `<count>`, then `ReloadDriver` (crash, see §2) |
| `SETGPU` | `SETGPU "AMD Radeon(TM) 890M Graphics"` — one space, then the name **with quotes** (`substr(1, size-2)` strips first and last char) | none | rewrites `<friendlyname>`, then `ReloadDriver` (crash) |
| `RELOAD_DRIVER` | `RELOAD_DRIVER` | none | `ReloadDriver` (crash, issue #351) |
| `LOGGING` / `LOG_DEBUG` | `LOGGING true` / `LOG_DEBUG false` | none | XML toggle, no reload |
| `HDRPLUS`, `SDR10`, `CUSTOMEDID`, `PREVENTSPOOF`, `CEAOVERRIDE`, `HARDWARECURSOR` | `<NAME> true|false` | none | XML toggle + `ReloadDriver` (crash) |
| `D3DDEVICEGPU`, `IDDCXVERSION`, `GETASSIGNEDGPU`, `GETALLGPUS` | name only | log lines only (see below) | none |

Log lines: when `<logging>` is true, every `vddlog(...)` during the connection is also written to
the pipe as narrow text (`"<date> [TYPE] message\n"`, see
[Driver.cpp#L354-L359](https://github.com/VirtualDrivers/Virtual-Display-Driver/blob/b07c8cc80c95042a8b5a1a97e67c8e4a51ab8c10/Virtual%20Display%20Driver%20(HDR)/MttVDD/Driver.cpp#L354-L359)).
With logging off (this PC) `vddlog` returns early, so `PING` yields exactly `PONG`. Parse
defensively: "reply contains `PONG`".

Reply race: the server does `WriteFile` then immediately `DisconnectNamedPipe`, which discards
unread data. The official Electron client documents this and arms an overlapped read *before*
writing — [pipe-client.ts#L14-L21](https://github.com/VirtualDrivers/Virtual-Driver-Control/blob/a1ae80aa1407402468dfb9893530f933cb6da1cf/VirtualDriverControl/src/main/services/pipe-client.ts#L14-L21):

```ts
/**
 * Commands the driver answers with data. These need the PowerShell round trip:
 * the driver responds with WriteFile immediately followed by
 * DisconnectNamedPipe, which discards anything the client has not read yet.
 * Only a client with an overlapped read already pending in the kernel receives
 * the data - Node's net stack reads too late by design, .NET ReadAsync works.
 */
```

The same file ([L80-L94](https://github.com/VirtualDrivers/Virtual-Driver-Control/blob/a1ae80aa1407402468dfb9893530f933cb6da1cf/VirtualDriverControl/src/main/services/pipe-client.ts#L80-L94))
states "one-shot connection per command", "commands written as UTF-16LE", "responses decoded as
UTF-8 except GETSETTINGS (UTF-16LE)" and "RELOAD_DRIVER is never sent (upstream undefined
behavior, issue #351)". The older Python reference client
([MTTVirtualDisplayPipe.py#L70](https://github.com/VirtualDrivers/Python-VDD-Pipe-Control/blob/d59455fddd20af736e6f6d4eda24addbbdf4b90c/MTTVirtualDisplayPipe.py#L70))
also writes `command.encode('utf-16le')`.

### Observed on this PC (allowed commands only)

Probe: ctypes, `CreateFileW(..., FILE_FLAG_OVERLAPPED)`, overlapped `ReadFile` armed first, then
`WriteFile`, then collect messages until the server disconnects (2 s timeouts). Two rounds:

```
> PING
  wrote 8 bytes: b'P\x00I\x00N\x00G\x00'
  read ended, error 233
  elapsed 2 ms
  message 4 bytes: b'PONG'
> GETSETTINGS
  wrote 22 bytes: b'G\x00E\x00T\x00S\x00E\x00T\x00T\x00I\x00N\x00G\x00S\x00'
  elapsed 1 ms
  message 62 bytes: b'S\x00E\x00T\x00T\x00I\x00N\x00G\x00S\x00 \x00D\x00E\x00B\x00U\x00G\x00=\x00f\x00a\x00l\x00s\x00e\x00 \x00L\x00O\x00G\x00=\x00f\x00a\x00l\x00s\x00e\x00\x00\x00'
```

Decoded: `PONG`; `SETTINGS DEBUG=false LOG=false`. Round trip ≤ 2 ms. After the reply, the next
read fails with 233 (`ERROR_PIPE_NOT_CONNECTED`) = end of conversation.

A naive synchronous client (`open(r"\\.\pipe\MTTVirtualDisplayPipe", "r+b", buffering=0)`,
`write`, `read(512)`) also received `b'PONG'` 3/3 times here, but it is racy by design (see above);
use the armed overlapped read.

---

## 2. SETDISPLAYCOUNT, XML and "reload"

### `count = 0` is coerced to 1

[Driver.cpp#L1316-L1322](https://github.com/VirtualDrivers/Virtual-Display-Driver/blob/b07c8cc80c95042a8b5a1a97e67c8e4a51ab8c10/Virtual%20Display%20Driver%20(HDR)/MttVDD/Driver.cpp#L1316-L1322)
(same in 25.7.23 L1541-L1547 and in master):

```cpp
				if (currentElement == L"count") {
					monitorcount = stoi(wstring(pwszValue, cwchValue));
					if (monitorcount == 0) {
						monitorcount = 1;
						vddlog("i", "Loading singular monitor (Monitor Count is not valid)");
					}
				}
```

The string `Loading singular monitor` is present in the installed DLL. **There is no XML/pipe value
that yields zero VDD monitors**; zero monitors = device disabled or removed (admin).

### `ReloadDriver` crashes; the XML is not re-read anyway

[Driver.cpp#L859-L865](https://github.com/VirtualDrivers/Virtual-Display-Driver/blob/b07c8cc80c95042a8b5a1a97e67c8e4a51ab8c10/Virtual%20Display%20Driver%20(HDR)/MttVDD/Driver.cpp#L859-L865):

```cpp
void ReloadDriver(HANDLE hPipe) {
	auto* pContext = WdfObjectGet_IndirectDeviceContextWrapper(hPipe);
	if (pContext && pContext->pContext) {
		pContext->pContext->InitAdapter();
		vddlog("i", "Adapter reinitialized");
	}
}
```

- `hPipe` is a Win32 pipe handle, not a WDF object. Upstream issue
  [#351 "RELOAD_DRIVER causes segfault"](https://github.com/VirtualDrivers/Virtual-Display-Driver/issues/351)
  (open, driver 24.12.24) shows `read access violation` in `FxObject::_GetObjectFromHandle` /
  `WUDFx02000.dll!imp_WdfObjectGetTypedContextWorker` called from `ReloadDriver`; a 2026-04
  comment points at the same line. `SETDISPLAYCOUNT`, `SETGPU` and the toggles call the same
  function (24.12.24: 15 call sites, L883–L1043).
- Even if it did not crash, `InitAdapter` uses the global `numVirtualDisplays`, which is set
  only by `loadSettings()`; `loadSettings()` has a **single call site**, in `DeviceAdd`
  ([Driver.cpp#L1539](https://github.com/VirtualDrivers/Virtual-Display-Driver/blob/b07c8cc80c95042a8b5a1a97e67c8e4a51ab8c10/Virtual%20Display%20Driver%20(HDR)/MttVDD/Driver.cpp#L1539)).
  Monitors are created in `FinishInit` from that global
  ([L2340-L2346](https://github.com/VirtualDrivers/Virtual-Display-Driver/blob/b07c8cc80c95042a8b5a1a97e67c8e4a51ab8c10/Virtual%20Display%20Driver%20(HDR)/MttVDD/Driver.cpp#L2340-L2346)).
- So `SETDISPLAYCOUNT n` "works" only because the host process dies and UMDF restarts the device,
  which runs `DeviceAdd` → `loadSettings` again. The Electron client treats these as "heavyweight,
  2-8s" reloads with a 45 s timeout and a 3 s cooldown
  ([pipe-client.ts#L56-L72](https://github.com/VirtualDrivers/Virtual-Driver-Control/blob/a1ae80aa1407402468dfb9893530f933cb6da1cf/VirtualDriverControl/src/main/services/pipe-client.ts#L56-L72)).
  During the restart the pipe does not exist (`is_installed()` would be False).
- Risks: undefined behaviour, a WER report per command, and UMDF may stop restarting a host that
  keeps crashing (device left in error) — not verified here, deliberately.

Evidence on this PC (Application log, read-only): a burst of about 40 `Windows Error Reporting`
1001 events on 2026-10-01 between 22:07:04 and 22:08:00 (plus 1000/1001 at 22:13:41-47); the three
that mention MttVDD (22:07:55, 22:07:55, 22:08:00) read:

```
Nom d'événement : WUDFUnhandledException
P1 : UnhandledException
P2 : Host
P3 : c0000005
P5 : WUDFx02000.dll
P7 : mttvdd.dll
P9 : 2.35.0
```

That is the issue #351 signature. What triggered it that evening is not recorded (the XML was last
written at 21:50 the same day); the device is back to normal now (`Status OK`, `CM_PROB_NONE`).

### XML location and overrides

- Default folder `C:\VirtualDisplayDriver` (`confpath`, [L94](https://github.com/VirtualDrivers/Virtual-Display-Driver/blob/b07c8cc80c95042a8b5a1a97e67c8e4a51ab8c10/Virtual%20Display%20Driver%20(HDR)/MttVDD/Driver.cpp#L94)), file `vdd_settings.xml`.
- Override: `HKLM\SOFTWARE\MikeTheTech\VirtualDisplayDriver`, value `VDDPATH` (REG_SZ), read once in
  `DriverEntry` → `initpath()` ([L1173-L1181](https://github.com/VirtualDrivers/Virtual-Display-Driver/blob/b07c8cc80c95042a8b5a1a97e67c8e4a51ab8c10/Virtual%20Display%20Driver%20(HDR)/MttVDD/Driver.cpp#L1173-L1181)).
  The same key can hold DWORD/string overrides for the toggles (`LOGS`, `DEBUGLOGS`, `HDRPLUS`…).
  On this PC: `reg query` → key not found (defaults apply).
- If the XML is missing: `option.txt` (first line = count, then `w,h,hz`), else a built-in list
  (800×600 … 3840×2160 at 30–165 Hz) with count 1.
- GPU: `<gpu><friendlyname>`; empty or `default` → `adapter.txt`, else the driver picks.
- Modes: each `<resolution>` gives `w×h@refresh_rate`, and **every** `<g_refresh_rate>` is
  multiplied with every distinct `w×h` (see `loadSettings`, 25.7.23 L1601-L1610). Upstream issue
  #254 reports init failures with many custom resolutions — keep the list short.
- The driver's own XML rewriter (`UpdateXmlDisplayCountSetting`, L680+) copies elements, text,
  whitespace and comments, but **drops attributes, the original XML declaration and does not
  handle self-closing elements** (`<x/>` has no EndElement for `IXmlReader`, so nesting breaks).
  It writes `vdd_settings.xml.temp` then `MoveFileExW(REPLACE_EXISTING)`.

### Resolution added to `<resolutions>`

Picked up **only at the next device start** (`DeviceAdd`): reboot, `pnputil /restart-device`
(admin), disable/enable (admin), or the crash-restart side effect of a `ReloadDriver` command.

---

## 3. This PC: XML, device, ACL

`C:\VirtualDisplayDriver\vdd_settings.xml` (3178 bytes, 2026-10-01 21:50; abridged):

```xml
<?xml version='1.0' encoding='utf-8'?>
<vdd_settings>
    <monitors><count>1</count></monitors>
    <gpu><friendlyname>AMD Radeon(TM) 890M Graphics</friendlyname></gpu>
	<global> <!-- comment --> <g_refresh_rate>60</g_refresh_rate> … 90 120 144 165 244 </global>
    <resolutions>
        <!-- TabX : Galaxy Tab S10 FE+ (natif) et alternative 16:10 -->
        <resolution><width>2880</width><height>1800</height><refresh_rate>60</refresh_rate></resolution>
        … 2560×1600@60, 800×600@30, 1366×768@30, 1920×1080@30, 2560×1440@30, 3840×2160@30
    </resolutions>
    <options> CustomEdid false, PreventSpoof false, EdidCeaOverride false, HardwareCursor true,
              SDR10bit false, HDRPlus false, logging false, debuglogging false (+ comments) </options>
</vdd_settings>
```

Diff with `vdd_settings.xml.bak-tabx` (2024-12-24): only `friendlyname` (`default` → AMD) and the
two TabX resolutions + comment. The file uses single-quoted declaration (written by Python
ElementTree earlier) — the driver's `IXmlReader` accepts it.

Device (`pnputil /enum-devices /class Display /ids /drivers`, abridged; output is localised):

```
ID d'instance :          ROOT\DISPLAY\0000
Description de l'appareil : Virtual Display Driver
ID matériels :           Root\MttVDD
    Nom du pilote:       oem114.inf   Nom original: mttvdd.inf
    Version du pilote:   12/24/2024 11.30.4.434   Nom du signataire: SignPath Foundation
```

- **The instance ID is `ROOT\DISPLAY\0000`, not `ROOT\MTTVDD\…`**: devcon creates the node under
  the class enumerator. Detect by **hardware ID** `Root\MttVDD`.
- Registry (readable without admin): `HKLM\SYSTEM\CurrentControlSet\Enum\ROOT\DISPLAY\0000`
  `HardwareID = Root\MttVDD` (REG_MULTI_SZ), `Driver = {4d36e968-…}\0004` →
  `HKLM\SYSTEM\CurrentControlSet\Control\Class\{4d36e968-e325-11ce-bfc1-08002be10318}\0004`
  `InfPath = oem114.inf`, `DriverVersion = 11.30.4.434`.
- Monitor: `DISPLAY\MTT1337\1&28A6823A&0&UID256`, "Generic Monitor (VDD by MTT)".
- `icacls C:\VirtualDisplayDriver`: `Utilisateurs authentifiés:(I)(M)` and `(OI)(CI)(IO)(M)`
  inherited from `C:\` → a standard user can already modify the folder and the XML here. The
  installer's `icacls … /grant *S-1-5-32-545:(OI)(CI)M` stays useful when the folder pre-exists
  with other ACLs.
- `HKLM\…\TrustedPublisher` already contains `CN=SignPath Foundation`
  (thumbprint `3CF8CF26D8BA266C3A483AB7D26D4A818E317D76`, the `mttvdd.cat` signer, expires
  2027-09-07). On a fresh PC it will not be there → see §6/Task 9.

Package files (`%LOCALAPPDATA%\Microsoft\WinGet\Packages\VirtualDrivers.Virtual-Display-Driver_…`):
`Dependencies\devcon.exe`, `Dependencies\vdd_settings.xml`, `SignedDrivers\{x86,ARM64}\VDD\{MttVDD.inf,MttVDD.dll,mttvdd.cat,vdd_settings.xml}`,
`SignedDrivers\x86\VAD\…` (audio), `VDD Control.exe` (171 MB). **No LICENSE file** in the package.
PE machine fields: `x86\VDD\MttVDD.dll` = `0x8664` (AMD64), `ARM64\VDD\MttVDD.dll` = `0xAA64`,
`devcon.exe` = `0x8664`. → the folder named `x86` holds the x64 driver (confirms the plan).

---

## 4. devcon, detection, licence

Command lines (documented, **not run**):

```
devcon.exe install "<dir>\MttVDD.inf" Root\MttVDD      # creates a NEW root device node every time
devcon.exe remove Root\MttVDD                         # removes every node with that hardware ID
pnputil /delete-driver oem114.inf /uninstall          # then drop the package (name from InfPath)
pnputil /restart-device "ROOT\DISPLAY\0000"           # Win10 2004+; /deviceid "Root\MttVDD" on Win11 21H2+
```

- `devcon install` = `SetupDiCreateDeviceInfo` + `DIF_REGISTERDEVICE` + `UpdateDriverForPlugAndPlayDevices`
  ([cmds.cpp `cmdInstall`](https://github.com/microsoft/Windows-driver-samples/blob/main/setup/devcon/cmds.cpp)),
  so running it twice makes two VDD adapters (this happened on this PC before). Always detect first.
- devcon exit codes ([devcon.h#L131-L134](https://github.com/microsoft/Windows-driver-samples/blob/main/setup/devcon/devcon.h#L131-L134)):
  `0` OK, `1` OK but reboot needed, `2` failure, `3` usage error.
- Detection without devcon, locale-independent, no admin needed: enumerate subkeys of
  `HKLM\SYSTEM\CurrentControlSet\Enum\ROOT\DISPLAY` and look for `HardwareID` containing
  `Root\MttVDD` (verified above). `pnputil /enum-devices /deviceid "Root\MttVDD"` (Win11 22H2+)
  also works but exits **0 whether found or not** and its text is localised ("Aucun appareil n'a
  été trouvé…"); if used, test for the substring `ROOT\` in stdout.
- PowerShell alternative: `Get-PnpDevice | ? { $_.HardwareID -contains 'Root\MttVDD' }`.

Licence:
- VDD repo: MIT ("Copyright (c) 2024 Virtual Display",
  [LICENSE](https://github.com/VirtualDrivers/Virtual-Display-Driver/blob/d437ebc9b44a14ce6e5cc9c8b7f6beb08d6faf77/LICENSE)).
  Take the LICENSE from GitHub (the winget package has none).
- `devcon.exe` in the package is **Microsoft's** WDK binary: Authenticode `CN=Microsoft
  Corporation` (valid), `FileVersion 10.0.26100.2454`, `OriginalFilename DevCon.exe`,
  `© Microsoft Corporation. All rights reserved.` It is **not** covered by VDD's MIT licence. The VDD
  project redistributes it (and its `silent-install.ps1` instead downloads it with the third-party
  "DevCon-Installer"). Microsoft's docs only say devcon "is included when you install the WDK" and
  "Microsoft recommends using PnPUtil instead of DevCon"
  ([devcon.md](https://github.com/MicrosoftDocs/windows-driver-docs/blob/staging/windows-driver-docs-pr/devtest/devcon.md));
  I found no explicit redistribution grant. The devcon **source** is in
  `microsoft/Windows-driver-samples` under **MS-PL** (redistributable; an unsigned self-built exe is
  fine — only the driver needs a signature). Microsoft's replacement for `devcon install` is
  `devgen /add /bus ROOT` + `pnputil /add-driver <inf> /install`
  ([devcon-migration.md](https://github.com/MicrosoftDocs/windows-driver-docs/blob/staging/windows-driver-docs-pr/devtest/devcon-migration.md)),
  but devgen is also a WDK tool.

---

## 5. Windows CCD and DPI (read-only probe)

`GetDisplayConfigBufferSizes(QDC_ONLY_ACTIVE_PATHS)` + `QueryDisplayConfig` returned rc 0,
3 paths, 6 modes; `DisplayConfigGetDeviceInfo` types 1, 2 and -3 all rc 0:

```
sizeof PATH_INFO 72 MODE_INFO 64 HEADER 20 SOURCE_NAME 84 TARGET_NAME 420 DPI_GET 32 DPI_SET 24
path 0: adapter=0x0:0x15d7e source.id=0 target.id=256 flags=0x1 outTech=0x80000000 refresh=60/1
   gdi='\\.\DISPLAY1' monitor='NE160QDM-NYJ'
   sourceMode 2560x1600 at (0,0) primary=True
   DPI get rc=0 min=-2 cur=0 max=4 -> recommended=150% current=150% max=250%
path 1: adapter=0x0:0x43f5d2 source.id=0 target.id=409857 outTech=0x5
   gdi='\\.\DISPLAY6' monitor='24E6C'      sourceMode 1920x1080 at (-1920,0)
   DPI get rc=0 min=0 cur=0 max=3 -> recommended=100% current=100% max=175%
path 2: adapter=0x0:0x7e6d58 source.id=0 target.id=256 outTech=0x5
   gdi='\\.\DISPLAY10' monitor='VDD by MTT'
   devicePath='\\?\DISPLAY#MTT1337#1&28a6823a&0&UID256#{e6f07b5f-ee97-4a90-b076-33f57bf4eaa7}'
   sourceMode 2880x1800 at (2560,-207) primary=False
   DPI get rc=0 min=-2 cur=2 max=5 -> recommended=150% current=200% max=300%
EnumDisplayDevicesW: \\.\DISPLAY1 | AMD Radeon(TM) 890M Graphics | flags=0x5 primary=True
                     \\.\DISPLAY6 | NVIDIA GeForce RTX 5070 Laptop GPU | flags=0x1
                     \\.\DISPLAY10 | Virtual Display Driver | flags=0x1 | Root\MttVDD
```

Notes:
- Target IDs are **not unique** across adapters (256 on the internal panel and on the VDD): key
  paths by `(adapterId LUID, id)`. LUIDs change across boots/driver restarts: never persist them.
- Primary = source mode at `(0,0)`; positions can be negative (24" at x = -1920) and the VDD is
  currently at y = -207 (user's manual placement).
- Identify the VDD path by its source GDI name ↔ `EnumDisplayDevicesW` entry whose `DeviceID` is
  `Root\MttVDD` (adapter-level), or by `monitorDevicePath` containing `#MTT1337#`.
- `QDC_ALL_PATHS`: 159 paths; the VDD adapter has exactly one path (one monitor, one source).
- `EnumDisplayDevicesW` gives the primary adapter's `DeviceString` = `AMD Radeon(TM) 890M Graphics`,
  which is exactly the VDD `<friendlyname>` that works on this PC (for `--configure-vdd`).

DPI (undocumented types −3/−4), reference implementation
[lihas/windows-DPI-scaling-sample DpiHelper.h#L6-L13](https://github.com/lihas/windows-DPI-scaling-sample/blob/738ac18b7a7ce2d8fdc157eb825de9cb5eee0448/DPIHelper/DpiHelper.h#L6-L13) (Unlicense):

```cpp
/*
* OS reports DPI scaling values in relative terms, and not absolute terms.
* eg. if current DPI value is 250%, and recommended value is 200%, then
* OS will give us integer 2 for DPI scaling value (starting from recommended
* DPI scaling move 2 steps to the right in this list).
* values observed (and extrapolated) from system settings app (immersive control panel).
*/
static const UINT32 DpiVals[] = { 100,125,150,175,200,225,250,300,350, 400, 450, 500 };
```

[DpiHelper.cpp#L71-L76](https://github.com/lihas/windows-DPI-scaling-sample/blob/738ac18b7a7ce2d8fdc157eb825de9cb5eee0448/DPIHelper/DpiHelper.cpp#L71-L76) and
[#L136-L144](https://github.com/lihas/windows-DPI-scaling-sample/blob/738ac18b7a7ce2d8fdc157eb825de9cb5eee0448/DPIHelper/DpiHelper.cpp#L136-L144):

```cpp
        std::int32_t minAbs = abs((int)requestPacket.minScaleRel);
        ...
            dpiInfo.current = DpiVals[minAbs + requestPacket.curScaleRel];
            dpiInfo.recommended = DpiVals[minAbs];
            dpiInfo.maximum = DpiVals[minAbs + requestPacket.maxScaleRel];
    ...
    int dpiRelativeVal = idx1 - idx2;          // idx(target) - idx(recommended) in DpiVals
    setPacket.header.size = sizeof(setPacket);
    assert(0x18 == sizeof(setPacket));
    setPacket.header.type = (DISPLAYCONFIG_DEVICE_INFO_TYPE)...SET_DPI_SCALE;   // -4
    setPacket.scaleRel = (UINT32)dpiRelativeVal;
```

Confirmed on this PC: VDD `min=-2` → recommended = `DpiVals[2]` = 150 %, `cur=2` →
`DpiVals[4]` = 200 % (what the user set). The DPI header uses the **source** id and adapter.

---

## 6. Inno Setup 6

- winget: `JRSoftware.InnoSetup` = Inno Setup **6** (latest manifest 6.7.3, x86 installer, scopes
  machine `/ALLUSERS` and user `/CURRENTUSER`). **Inno Setup 7 is a separate id**
  `JRSoftware.InnoSetup.7` (7.1.0, x64/x86) — don't confuse them.
  Install with `winget install --id JRSoftware.InnoSetup -e --scope machine`.
- ISCC path: Inno's own `DefaultDirName={code:GetDefaultDirName|Inno Setup 6}` = `{autopf}\Inno Setup 6`
  ([isportable.iss](https://github.com/jrsoftware/issrc/blob/is-6_7_3/isportable.iss)):
  machine → `C:\Program Files (x86)\Inno Setup 6\ISCC.exe`; user →
  `%LOCALAPPDATA%\Programs\Inno Setup 6\ISCC.exe`. Robust lookup: `InstallLocation` of uninstall
  key `Inno Setup 6_is1` under `HKLM\SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall`
  or `HKCU\Software\Microsoft\Windows\CurrentVersion\Uninstall`.
- Elevated hidden step with exit code: `[Run]` cannot return exit codes to the script; use
  `Exec` in `[Code]` (e.g. `CurStepChanged(ssPostInstall)`). Inno 6.7.3 help (issrc `ISHelp/isxfunc.xml`):
  "Executes the specified executable or batch file, using the same credentials as Setup/Uninstall"
  (so elevated with `PrivilegesRequired=admin`); `ResultCode` = exit code with
  `ewWaitUntilTerminated`; "when Setup/Uninstall is running in 64-bit install mode, this function
  disables WOW64 file system redirection" (so `{sys}\pnputil.exe` is the 64-bit one).
  `ExecAndCaptureOutput` (same args + `var Output: TExecOutput`) captures stdout/stderr.
- `[Run]` flags: `runhidden`; non-`postinstall` entries run with Setup's (admin) credentials by
  default (`runascurrentuser`); `postinstall` entries run as the original user by default
  (`runasoriginaluser`, no effect if Setup itself was started elevated).
- `ShowLanguageDialog=yes|no|auto` (default yes); `[Languages]` `MessagesFile:
  "compiler:Default.isl"` and `"compiler:Languages\French.isl"` (present in 6.7.3, header "Inno
  Setup version 6.5.0+ French messages"). The chosen language is the constant `{language}`
  (the `Name:` of the `[Languages]` entry), also `ActiveLanguage` in `[Code]`.
- `CloseApplications=yes` (default `yes`): Restart Manager on files being replaced by `[Files]`,
  filter `CloseApplicationsFilter` default `*.exe,*.dll,*.chm`; `force` also exists.
- `ArchitecturesAllowed=x64compatible` / `ArchitecturesInstallIn64BitMode=x64compatible` are valid
  in 6.7.3 (`x64compatible` also allows Arm64 Windows 11 — irrelevant, we ship x64 only).
- Uninstall hooks: `procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep)` with
  `usAppMutexCheck, usUninstall, usPostUninstall, usDone`; `UninstallSilent()`; `MsgBox(...,
  mbConfirmation, MB_YESNO)` / `SuppressibleMsgBox`. `[UninstallRun]` entries need `RunOnceId`
  (compiler warning otherwise).
- `HKCU` from an admin-mode install: if the user elevates with a *different* admin account,
  `HKCU` is that account's hive. Inno warns about it (`UsedUserAreasWarning`).

---

## Implications for Tasks 3-5 and 9

### A. Spec changes I recommend (needs the controller's decision)

1. **Appear/disappear by display path, not by count.** Keep `<count>1</count>` forever. "Screen
   appears" = activate the VDD path with the tablet mode at the chosen position (`SetDisplayConfig`,
   user rights). "Screen disappears" = deactivate the path (same as Settings ▸ Display ▸
   "Disconnect this display"). No driver restart, no crash, no admin, nothing to "clean" in the XML.
   `cleanup_on_start()` / `--cleanup` = deactivate the VDD path if active.
   Caveat to verify in Task 8: when the monitor set changes (user plugs a monitor) while the app is
   not running, Windows may re-extend to the VDD ("ghost" screen); the app should re-deactivate on
   `WM_DISPLAYCHANGE` when no tablet is connected.
2. **Device restart only to add a resolution.** `ensure_resolution` edits the XML; if it changed,
   the device must restart before the mode exists. Options, best first:
   (a) in the installer (already elevated): `pnputil /restart-device <instance id>`;
   (b) in the app: one UAC prompt, `ShellExecuteW(None, "runas", "pnputil.exe",
   '/restart-device "ROOT\DISPLAY\0000"', None, SW_HIDE)` (instance ID from the registry scan),
   only the first time a new tablet resolution is seen;
   (c) fallback without admin: pipe `SETDISPLAYCOUNT 1` — relies on the crash-restart (§2), then
   wait for the pipe to come back (PING) and for the mode (≤ 45 s like the official client).
   Pre-seed the installer XML with the common tablet resolutions to make (b)/(c) rare.
3. **Never send `RELOAD_DRIVER`**, and avoid `SETGPU`/`SETDISPLAYCOUNT` in normal operation.
4. Installer XML: `count` **1** (0 is coerced to 1 anyway), GPU, a short resolution list, and a
   short `<global>` (just `60`) to limit the mode product (issue #254).

### B. Task 3 — `vdd.py`

- Pipe transport (exact bytes): request `command.encode("utf-16le")`, no NUL, `len(command) ≤ 127`.
  `PING` = `b'P\x00I\x00N\x00G\x00'` → success if `b"PONG"` in reply. `GETSETTINGS` →
  `reply.decode("utf-16le").rstrip("\x00")` starts with `SETTINGS `. Other commands have no reply;
  treat "server disconnected after our write" (109/233) as delivered.
- Client recipe that worked: `CreateFileW(name, GENERIC_READ|GENERIC_WRITE, 0, None,
  OPEN_EXISTING, FILE_FLAG_OVERLAPPED, None)`; retry on 2/231 up to the 2 s budget (sleep 20 ms /
  `WaitNamedPipeW(name, 200)`); arm overlapped `ReadFile(4096)`; overlapped `WriteFile`; loop
  `WaitForSingleObject(ev, 2000)` + `GetOverlappedResult`, re-arm until error 109/233; on timeout
  `CancelIoEx`. `OVERLAPPED` = `(c_size_t Internal, c_size_t InternalHigh, DWORD Offset, DWORD
  OffsetHigh, HANDLE hEvent)`; set `use_last_error=True` and full `argtypes`/`restype` (64-bit handles).
- `is_installed()`: PING answered. Add `device_present()` (registry scan for `Root\MttVDD`) so
  the app can tell "driver missing" from "driver restarting".
- XML editing: `ET.parse(path, parser=ET.XMLParser(target=ET.TreeBuilder(insert_comments=True)))`
  to keep comments; write with `short_empty_elements=False` (the driver's rewriter breaks on
  `<x/>`); UTF-8 with declaration; temp file in the same folder + `os.replace`; one-time backup.
  ElementTree loses the original quoting/indentation of the declaration and attribute order —
  harmless for the driver. Keep the element names exactly: `monitors/count`,
  `gpu/friendlyname`, `global/g_refresh_rate`, `resolutions/resolution/{width,height,refresh_rate}`.
- `set_gpu(name)`: edit `<friendlyname>` in the XML (effective at next device start); do not use
  the `SETGPU` pipe command.

### C. Task 4 — `display_layout.py`: ctypes structs that worked

```python
class LUID(Structure): _fields_ = [("LowPart", DWORD), ("HighPart", LONG)]
class RATIONAL(Structure): _fields_ = [("Numerator", c_uint32), ("Denominator", c_uint32)]
class REGION2D(Structure): _fields_ = [("cx", c_uint32), ("cy", c_uint32)]
class PATH_SOURCE_INFO(Structure): _fields_ = [("adapterId", LUID), ("id", c_uint32), ("modeInfoIdx", c_uint32), ("statusFlags", c_uint32)]
class PATH_TARGET_INFO(Structure): _fields_ = [("adapterId", LUID), ("id", c_uint32), ("modeInfoIdx", c_uint32), ("outputTechnology", c_uint32), ("rotation", c_uint32), ("scaling", c_uint32), ("refreshRate", RATIONAL), ("scanLineOrdering", c_uint32), ("targetAvailable", BOOL), ("statusFlags", c_uint32)]
class PATH_INFO(Structure): _fields_ = [("sourceInfo", PATH_SOURCE_INFO), ("targetInfo", PATH_TARGET_INFO), ("flags", c_uint32)]   # 72
class VIDEO_SIGNAL_INFO(Structure): _fields_ = [("pixelRate", c_uint64), ("hSyncFreq", RATIONAL), ("vSyncFreq", RATIONAL), ("activeSize", REGION2D), ("totalSize", REGION2D), ("videoStandard", c_uint32), ("scanLineOrdering", c_uint32)]   # 48
class SOURCE_MODE(Structure): _fields_ = [("width", c_uint32), ("height", c_uint32), ("pixelFormat", c_uint32), ("position", POINTL)]
class DESKTOP_IMAGE_INFO(Structure): _fields_ = [("PathSourceSize", POINTL), ("DesktopImageRegion", RECTL), ("DesktopImageClip", RECTL)]
class MODE_UNION(Union): _fields_ = [("targetVideoSignalInfo", VIDEO_SIGNAL_INFO), ("sourceMode", SOURCE_MODE), ("desktopImageInfo", DESKTOP_IMAGE_INFO)]
class MODE_INFO(Structure): _anonymous_ = ("u",); _fields_ = [("infoType", c_uint32), ("id", c_uint32), ("adapterId", LUID), ("u", MODE_UNION)]   # 64
class DEVICE_INFO_HEADER(Structure): _fields_ = [("type", c_int32), ("size", c_uint32), ("adapterId", LUID), ("id", c_uint32)]   # 20
class SOURCE_DEVICE_NAME(Structure): _fields_ = [("header", DEVICE_INFO_HEADER), ("viewGdiDeviceName", c_wchar * 32)]   # 84, type 1
class TARGET_DEVICE_NAME(Structure): _fields_ = [("header", DEVICE_INFO_HEADER), ("flags", c_uint32), ("outputTechnology", c_uint32), ("edidManufactureId", c_uint16), ("edidProductCodeId", c_uint16), ("connectorInstance", c_uint32), ("monitorFriendlyDeviceName", c_wchar * 64), ("monitorDevicePath", c_wchar * 128)]   # 420, type 2
class SOURCE_DPI_SCALE_GET(Structure): _fields_ = [("header", DEVICE_INFO_HEADER), ("minScaleRel", c_int32), ("curScaleRel", c_int32), ("maxScaleRel", c_int32)]   # 32, type -3
class SOURCE_DPI_SCALE_SET(Structure): _fields_ = [("header", DEVICE_INFO_HEADER), ("scaleRel", c_int32)]   # 24, type -4
```

(In the probe `MODE_UNION.targetMode` wrapped `VIDEO_SIGNAL_INFO` in a one-field struct; same
layout.) Constants: `QDC_ALL_PATHS=0x1`, `QDC_ONLY_ACTIVE_PATHS=0x2`,
`DISPLAYCONFIG_PATH_ACTIVE=0x1`, `DISPLAYCONFIG_PATH_MODE_IDX_INVALID=0xFFFFFFFF`, mode
`infoType` 1 = source, 2 = target, 3 = desktop image. `SDC_APPLY=0x80`,
`SDC_USE_SUPPLIED_DISPLAY_CONFIG=0x20`, `SDC_SAVE_TO_DATABASE=0x200`, `SDC_ALLOW_CHANGES=0x400`.
Retry `QueryDisplayConfig` when it returns 122 (`ERROR_INSUFFICIENT_BUFFER`, topology changed
between the two calls). `sizeof` tests: 72, 64, 20, 84, 420, 32, 24.

- `relative_scale_index(target, recommended) = DPI_VALS.index(target) - DPI_VALS.index(recommended)`
  with `DPI_VALS = (100,125,150,175,200,225,250,300,350,400,450,500)` (the full 12-step list,
  not `SCALE_STEPS`). Clamp the target to `[100, DPI_VALS[abs(min)+max]]` first. Table for tests:
  `(200,150)→2`, `(150,150)→0`, `(100,150)→-2`, `(300,150)→5`, `(125,100)→1`, `(100,100)→0`,
  `(250,200)→2`, `(175,250)→-3`. `get_scale` = `(DPI_VALS[abs(min)+cur], DPI_VALS[abs(min)])`.
- Position: `SetDisplayConfig(n_paths, paths, n_modes, modes, SDC_APPLY |
  SDC_USE_SUPPLIED_DISPLAY_CONFIG | SDC_SAVE_TO_DATABASE | SDC_ALLOW_CHANGES)` with the arrays from
  `QDC_ONLY_ACTIVE_PATHS`, only the VDD source mode's `position` changed (as in the spec). Not
  executed here (forbidden).
- New (for A.1), to validate in Task 8: `set_active(vdd, True, w, h, x, y)` = `QDC_ALL_PATHS`,
  take the VDD path, set `flags |= PATH_ACTIVE`, keep the other active paths, then
  `SetDisplayConfig(... SDC_APPLY | SDC_USE_SUPPLIED_DISPLAY_CONFIG | SDC_ALLOW_CHANGES |
  SDC_SAVE_TO_DATABASE)` with source/target mode indices set to `PATH_MODE_IDX_INVALID` (Windows
  picks a mode), then a second call to set the w×h source mode and position;
  `set_active(vdd, False)` = submit the active paths without the VDD one.

### D. Task 5 — lifecycle

- `prepare`: `vdd.is_installed()` (else `vdd_missing`) → `ensure_resolution(w,h,60)` (restart per
  A.2 only if changed) → activate the VDD path at w×h and position → poll monitors every 200 ms
  (10 s; 45 s right after a device restart) → scale on first time.
- `release(grace)` / `cancel_release` / `immediate`: deactivate the path instead of count 0.
- Expected delays (not measured — forbidden here): path activation ~1–2 s (mode set); device
  restart 2–8 s per the official client. Measure both in Task 8.

### E. Task 9 — installer

- Files: copy `MttVDD.inf`, `MttVDD.dll`, `mttvdd.cat` from the package's `SignedDrivers\x86\VDD`
  (AMD64 PE confirmed); `LICENSE` from the GitHub repo (MIT; not in the package); devcon: see
  §4 licence note — prefer building devcon from the MS-PL sample or let the app create the root
  device itself (`OrizonX.exe --install-vdd`: `SetupDiCreateDeviceInfoW` + `DIF_REGISTERDEVICE` +
  `UpdateDriverForPlugAndPlayDevicesW`, ~60 lines of ctypes) if redistributing Microsoft's binary is
  not acceptable. Decision for the controller/user.
- Order: (1) `OrizonX.exe --configure-vdd` (writes the XML **before** the device starts, so no
  restart is needed on a fresh install); (2) detect `Root\MttVDD`; if absent `devcon install`
  (exit 0/1 = OK), else `pnputil /restart-device <instance>` so the new XML is read; (3) icacls;
  (4) `OrizonX.exe --cleanup` after the monitor appears (deactivate the VDD path) — or leave it to
  the app's start-up cleanup.
- Trust prompt: on a PC without `SignPath Foundation` in `LocalMachine\TrustedPublisher`, the
  driver install shows "Would you like to install this device software?". Either let it show
  (don't rely on `SW_HIDE`), or import the signer certificate first
  (`certutil -addstore TrustedPublisher signpath.cer`, cert exported from `mttvdd.cat`). Check in
  the Sandbox test (Task 10).
- HKCU Language/autostart: also write `HKLM\Software\OrizonX\Language` and let the app fall back to
  it, or have the app write its HKCU values on first run (`postinstall` runs as the original user).

Snippets (Inno Setup 6.7.3 syntax; to adapt):

```iss
[Setup]
PrivilegesRequired=admin
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
ShowLanguageDialog=yes
CloseApplications=yes
UsedUserAreasWarning=no

[Languages]
Name: "en"; MessagesFile: "compiler:Default.isl"
Name: "fr"; MessagesFile: "compiler:Languages\French.isl"

[Registry]
Root: HKCU; Subkey: "Software\OrizonX"; ValueType: string; ValueName: "Language"; ValueData: "{language}"
Root: HKLM; Subkey: "Software\OrizonX"; ValueType: string; ValueName: "Language"; ValueData: "{language}"; Flags: uninsdeletekey

[Run]
Filename: "{app}\OrizonX.exe"; Description: "{cm:LaunchApp}"; Flags: postinstall nowait skipifsilent
```

```pascal
[Code]
function FindVddInstance(var InstanceId: String): Boolean;
var Keys: TArrayOfString; I: Integer; Ids: String;
begin
  Result := False;
  if RegGetSubkeyNames(HKLM, 'SYSTEM\CurrentControlSet\Enum\ROOT\DISPLAY', Keys) then
    for I := 0 to GetArrayLength(Keys) - 1 do
      if RegQueryMultiStringValue(HKLM, 'SYSTEM\CurrentControlSet\Enum\ROOT\DISPLAY\' + Keys[I], 'HardwareID', Ids)
         and (Pos('root\mttvdd', Lowercase(Ids)) > 0) then
      begin
        InstanceId := 'ROOT\DISPLAY\' + Keys[I]; Result := True; Exit;
      end;
end;

function RunHidden(const Exe, Params: String): Integer;
begin
  if not Exec(Exe, Params, '', SW_HIDE, ewWaitUntilTerminated, Result) then
    Result := -1;   { Exec failed to start the process }
  Log(Format('%s %s -> %d', [Exe, Params, Result]));
end;

procedure CurStepChanged(CurStep: TSetupStep);
var Inst: String; RC: Integer; ByUs: Cardinal;
begin
  if CurStep <> ssPostInstall then Exit;
  RunHidden(ExpandConstant('{app}\OrizonX.exe'), '--configure-vdd');
  ByUs := 0;
  if FindVddInstance(Inst) then
    RunHidden(ExpandConstant('{sys}\pnputil.exe'), '/restart-device "' + Inst + '"')
  else begin
    RC := RunHidden(ExpandConstant('{app}\vdd\devcon.exe'),
      'install "' + ExpandConstant('{app}\vdd\MttVDD.inf') + '" Root\MttVDD');
    if (RC = 0) or (RC = 1) then ByUs := 1
    else SuppressibleMsgBox(CustomMessage('VddInstallFailed'), mbError, MB_OK, IDOK);
  end;
  RegWriteDWordValue(HKLM, 'Software\OrizonX', 'VddInstalledByUs', ByUs);
  RunHidden(ExpandConstant('{sys}\icacls.exe'), '"C:\VirtualDisplayDriver" /grant *S-1-5-32-545:(OI)(CI)M');
end;

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
var ByUs: Cardinal; Inst, Drv, Inf: String;
begin
  if CurUninstallStep <> usUninstall then Exit;   { before files (devcon.exe) are deleted }
  RunHidden(ExpandConstant('{app}\OrizonX.exe'), '--cleanup');
  if RegQueryDWordValue(HKLM, 'Software\OrizonX', 'VddInstalledByUs', ByUs) and (ByUs = 1)
     and not UninstallSilent
     and (MsgBox(CustomMessage('RemoveVddQuestion'), mbConfirmation, MB_YESNO) = IDYES)
     and FindVddInstance(Inst) then
  begin
    Inf := '';
    if RegQueryStringValue(HKLM, 'SYSTEM\CurrentControlSet\Enum\' + Inst, 'Driver', Drv) then
      RegQueryStringValue(HKLM, 'SYSTEM\CurrentControlSet\Control\Class\' + Drv, 'InfPath', Inf);
    RunHidden(ExpandConstant('{app}\vdd\devcon.exe'), 'remove Root\MttVDD');
    if Inf <> '' then
      RunHidden(ExpandConstant('{sys}\pnputil.exe'), '/delete-driver ' + Inf + ' /uninstall');
  end;
end;
```

(`--cleanup` is called from `[Code]` instead of `[UninstallRun]` so that the order "cleanup →
question → removal" is explicit and runs before `{app}` is deleted. If `[UninstallRun]` is kept,
give it `RunOnceId: "OrizonXCleanup"`.)

- `build-pc.ps1` ISCC lookup order: `${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe`,
  `$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe`, then `InstallLocation` of `Inno Setup 6_is1`.
  Do not pick up Inno Setup 7 (`…\Inno Setup 7\`) silently: the script syntax is mostly compatible
  but 7 builds 64-bit installers and is a different product line.
