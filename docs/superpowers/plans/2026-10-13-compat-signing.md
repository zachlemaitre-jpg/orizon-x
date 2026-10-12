# Release Signing and Broad Compatibility Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A release-signed APK built from the user's own key, and video that adapts to any PC (Intel QuickSync, CPU fallback) and any device decoder (size, fps, bitrate).

**Architecture:** Gradle reads the signing settings from outside the repo, and the version comes from `version.py`. Android reports its best decodable size in `DEVICE_INFO.video`. The PC engine picks the encoder (nvenc → amf → qsv → x264), the capture size and fps from the device's caps and the encoder's limits, and an automatic bitrate.

**Spec:** `docs/superpowers/specs/2026-10-13-compat-signing-design.md`. Branch `compat`.

**Facts:** the keystore already exists at `C:\Users\zachl\OrizonX-signing\orizonx-release.jks`, with `keystore.properties` (storeFile relative to that folder, storePassword, keyAlias=orizonx, keyPassword). Never print or commit the passwords.

## Ground rules

- PC tests: `cd host-prototype; .\.venv\Scripts\python.exe -m unittest discover -s tests` (1084 OK at start) + `py -m unittest discover -s tests`. Android: `$env:JAVA_HOME = "C:\Program Files\Android\Android Studio\jbr"; cd android; .\gradlew.bat :app:testDebugUnitTest :app:assembleDebug`.
- TDD; never weaken assertions. No app/relay/adb runs, no device install. Never run commands that read stdin. Commits end with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.

### Task 1 — Android: signing, version, decoder caps (model: sonnet)

Spec §1 and §3 (Android).
- Release `signingConfigs` read from `ORIZONX_SIGNING_DIR` or `%USERPROFILE%\OrizonX-signing\keystore.properties`. A missing file fails only release tasks, with a clear message.
- `versionName` and `versionCode` come from `../host-prototype/version.py` (regex on `__version__`).
- `build-android.ps1` at the repo root: release build, copy to `dist/OrizonX.apk`, print the certificate SHA-256. Run it once to prove it works (it only reads the keystore).
- `video/DecoderCaps.kt` with injectable capabilities, and `DEVICE_INFO.video` added through `FrameWriter.deviceInfo(...)` and `DeviceRole.deviceInfoFor`, so the JSON writer emits `video` when present. Update `protocol/PROTOCOL.md`.
- Tests: candidate sizes and selection (native, ×0.75, 30 fps only, none), DEVICE_INFO bytes with video, version parsing.

### Task 2 — PC: encoders, adaptive size/fps/bitrate (model: sonnet)

Spec §2, §3 (PC).
- `engine.py`:
  - ENCODERS `qsv` and `x264`, with `AUTO_ORDER` extended;
  - x264 limits (30 fps, ≤ 1920 wide, aspect kept);
  - `protocol.DeviceInfo` gains an optional `video` (parse the JSON field, tolerant);
  - the session uses `video` for the virtual-screen size in Extend and for fps;
  - `Config.bitrate = "auto"` → computed bitrate (§3), a fixed value wins;
  - the auto scale is corrected by the capture/native ratio.
- `messages.py` and the window Encoder combo get the new choices (en/fr). Settings validation accepts `qsv` and `x264`.
- Read-only real checks: probe `qsv` (expected unavailable here) and `x264` (expected available) with the real ffmpeg.
- Tests as in spec §4 (PC).
