# Browser Tabs in the Context Bar Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a "Tabs" page to the browser context bar. It lists the open tabs of the foreground browser window, highlights the active one, and switches tab on tap.

**Architecture:**
- The PC reads the tab items through UI Automation and switches tabs with `SelectionItemPattern.Select()`, falling back to `Ctrl+N`.
- The `tabs` page is dynamic: up to 24 buttons, marked `scroll`, each with an `active` flag.
- Android draws a scroll page as a horizontally scrolling row of wider tab buttons.

**Tech Stack:** Python, comtypes UIA (imported lazily); Kotlin and Compose.

**Spec:** `docs/superpowers/specs/2026-10-19-browser-tabs-design.md`. Branch `browser-tabs`.

## Ground rules

- **Tests**
  - PC: `cd host-prototype; .\.venv\Scripts\python.exe -m unittest discover -s tests` and `py -m unittest discover -s tests`. Both must pass.
  - Android: `$env:JAVA_HOME = "C:\Program Files\Android\Android Studio\jbr"; cd android; .\gradlew.bat :app:testDebugUnitTest :app:assembleDebug`.
- **TDD, with fakes only**
  - Never weaken existing assertions.
  - Use a fake UIA and a fake SendInput only: no real tab switching and no keystrokes, in tests or in checks.
- **Never**
  - run the app, the relay or adb, or install anything;
  - run commands that read stdin;
  - touch `C:\Users\zachl\OrizonX-signing\`;
  - import comtypes, winrt or Qt at module import time in `actions/`.
- **Commits**
  - Tasks 1 and 2 run in parallel in the same tree: stage files by explicit path only.
  - Commit messages end with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.
- **Running app:** a dev copy of the PC app runs from this tree (pythonw). Don't kill it.

### Task 1 — PC (model: sonnet)

Spec §2 and §3.

- `actions/browser_tabs.py`: the reader and `select`. Inject it into `ContextProvider` (default: the real reader).
- The snapshot gets a dynamic `tabs` page:
  - first page for the browser profile;
  - last page for canva/figma when the exe is a browser;
  - no page when no tabs are read.
- The `tabs` page carries `"scroll":true`; its buttons carry `"active"`.
- `context.press` handles `tab.N` against the last tab list sent, then broadcasts at once.
- Add `tab` to `ICON_NAMES`.
- Update `PROTOCOL.md`.
- Tests: as listed in spec §5 (PC).
- Optional read-only check: list the user's Chrome tabs with the real reader. Never call `select` for real.

**Commit:** `feat(pc): browser tabs page in the context bar (UI Automation)`.

### Task 2 — Android (model: sonnet)

Spec §4.

- `ContextPage.scroll` and `ContextButton.active`, parsed tolerantly.
- Button limit: 24 on a scroll page, 8 on any other page.
- Scroll page layout:
  - a horizontally scrolling row of buttons about 132 dp wide, icon above a one-line title with ellipsis;
  - the active tab scrolled into view when the page appears;
  - the active button styled like the selected page tab.
- `ctx_tab` icon (Material "tab"), its mapping and the icon count test.
- Tests: parsing, both limits, the icon mapping.
- Build, then copy the debug APK to `dist/OrizonX-debug.apk`. Do not install.

**Commit:** `feat(android): scrolling tabs page with the active tab highlighted`.

### Task 3 — Real test (controller, with the user)

1. Test in Chrome with several tabs, switching from the bar (with the user's go-ahead).
2. Test with Canva open in Chrome.
3. Merge `app-icon` and `browser-tabs`, push, and publish 0.8.1.
