# Contextual Bar Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** In Actions mode, a Touch-Bar-like strip at the bottom of the device shows buttons for the PC's foreground app; tapping one sends that app's keyboard shortcut.

**Architecture:** The PC owns the profiles. `actions/foreground.py` detects the foreground exe, `actions/context_profiles.py` holds the profile table, `actions/keys.py` sends shortcuts with SendInput, and `actions/context.py` is the provider (snapshot → `context` section, handle → `context.press`). The hub merges it. Android renders `context` generically from icon names.

**Spec:** `docs/superpowers/specs/2026-10-13-context-bar-design.md`. Branch `context-bar`.

## Ground rules

- Tests: PC `cd host-prototype; .\.venv\Scripts\python.exe -m unittest discover -s tests` (1004 OK at start) + `py -m unittest discover -s tests`; Android `$env:JAVA_HOME = "C:\Program Files\Android\Android Studio\jbr"; cd android; .\gradlew.bat :app:testDebugUnitTest :app:assembleDebug`.
- TDD; never weaken assertions. Never send real keystrokes in tests or smoke checks (read-only foreground detection is fine). No app/relay/adb runs. Never run commands that read stdin.
- Commits end with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.

### Task 1 — PC side (model: sonnet)

Spec §2–§4, §6 (PC).
- `actions/foreground.py` : `ForegroundTracker` (injectable user32/kernel32 layer). `current() -> ForegroundApp(exe, window_class, title, pid)`. Ignores own PID and the desktop/taskbar classes, keeping the last real app.
- `actions/keys.py` : `send_shortcut("Ctrl+Shift+P")` with a parser, VK mapping, `VkKeyScanW` for punctuation, `KEYEVENTF_EXTENDEDKEY` for extended keys, and an injectable `SendInput`.
- `actions/context_profiles.py` : the profile table from spec §4 (ids, icons, French labels, shortcuts), plus `match(app) -> Profile`.
- `actions/context.py` : `ContextProvider`. Its `snapshot()` gives `{"available", "app", "profile", "buttons":[{"id","icon","label"}]}`, and `handle({"id":"context.press","button":...})` checks the button belongs to the active profile, then sends the shortcut.
- Hub: add the provider to `default_providers` and the fast poll group (250 ms). Route `context.*`. The state gains a `context` section.
- Spec §3 and protocol doc: document `context` and `context.press` in `protocol/PROTOCOL.md` (no vector change).

### Task 2 — Android side (model: sonnet)

Spec §3, §5, §6 (Android).
- `actions/ActionsState.kt` : parse `context` into `ContextBar(app, profile, buttons: List<ContextButton(id, icon, label)>)`, at most 8 buttons, tolerant.
- `actions/ActionMessages.kt` : `contextPress(buttonId)`.
- Drawables `ctx_<name>.xml` for every icon name in spec §5, using Material Icons paths (Apache-2.0 comment in each), plus `ctx_unknown`. Pure mapping function name → drawable id, with tests.
- `ui/ActionsScreen.kt` : the bottom bar as specified (landscape and portrait). The existing bottom block moves up. Crossfade on profile change. Haptics.
- Build, then copy the APK to `dist/OrizonX.apk`. Do not install.

### Task 3 — Real test (controller, with the user)

Run the PC app from source (venv) with the APK installed, then open each app (Spotify, PowerPoint if installed, Chrome/Edge, Word/Excel if installed, VS Code, Explorer, another app → generic) and press each button. Fix findings, rebuild the installer, merge.
