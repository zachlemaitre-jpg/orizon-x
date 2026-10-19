# Creative-App Context Bar Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** The Actions-mode context bar gets tool profiles for Illustrator, Photoshop, Canva and Figma, spread over up to 4 pages that are picked by tabs or a swipe.

**Architecture:**
- PC profiles gain pages. The `context` snapshot sends `pages`, and keeps `buttons` as page 1 for old apps.
- Browser windows whose title contains Canva or Figma pick those profiles.
- Android parses the pages, shows tabs and handles the swipe, remembers the page per profile, and adds Material-based `ctx_*` icons.

**Tech Stack:** Python 3.13 unittest; Kotlin and Jetpack Compose with JVM tests.

**Spec:** `docs/superpowers/specs/2026-10-19-creative-bar-design.md` (§2 holds the exact button tables, to be used verbatim). Branch `creative-bar`.

## Ground rules

- **Tests**
  - PC: `cd host-prototype; .\.venv\Scripts\python.exe -m unittest discover -s tests` and `py -m unittest discover -s tests`. Both must pass.
  - Android (PowerShell): `$env:JAVA_HOME = "C:\Program Files\Android\Android Studio\jbr"; cd android; .\gradlew.bat :app:testDebugUnitTest :app:assembleDebug`.
- **Discipline**
  - TDD.
  - Never weaken existing assertions.
  - Never send real keystrokes: use a fake `SendInput`.
- **Forbidden actions**
  - No app, relay or adb runs, and no installs.
  - Never run commands that read stdin.
  - Never touch `C:\Users\zachl\OrizonX-signing\`.
- **Commits**
  - Tasks 1 and 2 run in parallel in the same tree. Stage files by explicit path only.
  - Commit messages end with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.

### Task 1 — PC: pages, creative profiles, title detection (model: sonnet)

Spec §2 and §3.

**`actions/context_profiles.py`**
- Add `Page(id, labels, buttons)`. `Profile` gains `pages`, and `Profile.buttons` becomes the flattened tuple of every page's buttons.
  - Existing profiles get one page `main` (labels "Main"/"Principal", never shown since the device hides tabs for a single page). Their button order is unchanged.
- Add the four profiles from spec §2 verbatim: labels, shortcuts and icons.
- Add the new icon names from spec §4 to `ICON_NAMES`.
- Shortcuts:
  - `OEM_4` and `OEM_6` follow the VS Code `OEM_3`/`OEM_2` precedent: check how `actions/keys.py` parses them.
  - `Shift+0/1/2` must send the digit-row virtual keys `0x30`–`0x32`.
  - Figma's plain `-` and `=` go through `VkKeyScanW`, as other punctuation does.
  - Check each one with the existing fake-SendInput test helpers.
- `match(app)`:
  - Match on exe first: `illustrator.exe`, `photoshop.exe`, `canva.exe`, `figma.exe`, case-insensitive.
  - If the exe is one of the browser exes, a title containing "canva" picks `canva` and a title containing "figma" picks `figma` (case-insensitive). Otherwise the result is `browser`.
- `display_name`: Illustrator, Photoshop, Canva and Figma are the same in both languages.

**`actions/context.py`**
- `snapshot()` adds `"pages":[{"id","label","buttons":[{"id","icon","label"}]}]` in the current language, and keeps `buttons` equal to page 1.
- `context.press` accepts any button of any page of the active profile.

**Other updates**
- `protocol/PROTOCOL.md`: document `pages`.

**Tests**
- Every profile and page: 1 to 8 buttons, at most 4 pages, button ids unique within each profile, icons in `ICON_NAMES`, labels non-empty in en and fr, and every shortcut parsed by `actions.keys` into a non-empty event list with the fake layer.
- Exe detection for the four new profiles, in mixed case.
- Browser title detection:
  - a Chrome title "Logo – Canva - Google Chrome" gives canva;
  - an Edge title with Figma gives figma;
  - a plain Chrome title gives browser;
  - "Canva" in a non-browser window title does not give canva.
- The snapshot has pages, with `buttons` equal to page 1, in both languages.
- `context.press` accepts a view-page button and rejects a button from another profile.
- The existing profiles' snapshot `buttons` are unchanged.

**Commit:** `feat(pc): creative-app tool profiles with pages, browser title detection`.

### Task 2 — Android: pages, tabs, swipe, page memory, icons (model: sonnet)

Spec §3 and §4.

**`actions/ActionsState.kt`**
- Add `ContextPage(id, label, buttons)` and `ContextBar.pages`.
- Parsing:
  - if `pages` is absent or empty, use a single page built from `buttons`;
  - keep at most 4 pages (`MAX_PAGES = 4`) of 8 buttons;
  - drop empty pages;
  - if every page is empty, the bar is null as today.

**Page memory**
- `actions/ContextPageMemory.kt`, pure: `select(profile, pageId)` and `current(bar): ContextPage`, which returns the remembered page if present, else page 1.
- Keep it in memory for the session, owned by the Actions UI state, so it survives recomposition (a `remember` at the screen level, or the model).

**`ui/ActionsScreen.kt` (`ContextBarStrip`)**
- With more than one page:
  - tabs as compact pills (12 sp) after the app name, the selected one highlighted;
  - the buttons of the current page;
  - a horizontal swipe on the button area (`detectHorizontalDragGestures` with a threshold of about 48 dp, or `HorizontalPager`) moves to the neighbour page;
  - haptics, and a crossfade of about 150 ms.
- In portrait, the tabs go above the buttons when space is short.
- With a single page, the strip renders exactly as today.

**Icons**
- New `res/drawable/ctx_<name>.xml` VectorDrawables for every new name in spec §4, from Material Icons paths (24 dp viewport, white fill, Apache-2.0 comment in each file), in the same format as the existing `ctx_*.xml`.
- Extend `ContextIcons.NAMES` and its mapping.

**Tests**
- Pages parsing:
  - absent;
  - empty;
  - 5 pages truncated to 4;
  - an empty page dropped;
  - 9 buttons truncated to 8;
  - all pages empty gives null.
- Page memory:
  - default page 1;
  - a page remembered across profile switches;
  - an unknown page id falls back to page 1.
- Every new icon name maps to a drawable that is not `ctx_unknown`, and an unknown name maps to `ctx_unknown`.

**Build:** build, then copy the debug APK to `dist/OrizonX-debug.apk`. Do not install.

**Commit:** `feat(android): context bar pages (tabs, swipe, page memory) and creative-tool icons`.

### Task 3 — Real test (controller, with the user)

1. Build the release APK and install it with `-r`.
2. Run the PC app from source.
3. For each app the user has (Illustrator, Photoshop, Canva in the app and in the browser, Figma), try every page and button. Check the AZERTY-sensitive shortcuts.
4. Fix the shortcuts and update the spec.
5. Rebuild the installer, merge, push, then publish a release (version 0.8.0).
