# English Android UI and Setup Guide Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** The Android app speaks English or French, a per-brand setup guide brings a new device to its first connection, and the PC follows the device's language for the context bar.

**Architecture:**
- Android uses a Kotlin string table (`i18n/Strings.kt`) and a `LocalLang` CompositionLocal, so changing the language never recreates the Activity.
- The device reports its language in `DEVICE_INFO.lang`, and `context.lang` reports a change during a session. The PC profiles carry en and fr labels.
- The setup guide is pure data plus a pure state (`setup/`), driven by injectable probes of `Settings.Global` and the USB plug state.

**Tech Stack:** Kotlin + Jetpack Compose (JVM unit tests); Python 3.13 unittest.

**Spec:** `docs/superpowers/specs/2026-10-14-i18n-setup-guide-design.md`. Branch `i18n-guide`.

## Ground rules

- **Running the tests**
  - PC: `cd host-prototype; .\.venv\Scripts\python.exe -m unittest discover -s tests` (1132 OK at start), plus `py -m unittest discover -s tests`.
  - Android: `$env:JAVA_HOME = "C:\Program Files\Android\Android Studio\jbr"; cd android; .\gradlew.bat :app:testDebugUnitTest :app:assembleDebug`.
- **Discipline**
  - TDD; never weaken existing assertions.
  - No app, relay or adb runs, and no device install.
  - Never run commands that read stdin.
  - Never touch `C:\Users\zachl\OrizonX-signing\` and never print its contents.
- **Commits**
  - `git add` only the files you changed, by explicit path. Another task may be running in the same tree, so never use `git add -A` or `git add .`.
  - Commit messages end with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.

Tasks 1 and 2 are independent (PC vs Android) and may run in parallel. Task 3 needs Task 2.

### Task 1 — PC: device language, bilingual profiles, guiding adb messages (model: sonnet)

Spec §3, §5.

**`protocol.py`**
- `DeviceInfo.lang: str = "fr"`.
- `_decode_device_info` reads `lang` tolerantly: only `"en"` or `"fr"`, otherwise `"fr"`.
- Tests in `tests/test_protocol.py`: present en, present fr, absent, `"de"`, non-string.

**`actions/context_profiles.py`**
- `Button.label` becomes `labels: dict[str, str]` with `"en"` and `"fr"` (or two fields `label_en`/`label_fr`; pick one, use it everywhere).
- Every existing French label keeps its exact text. Add the English labels:

| Profile | English labels (same order as the French ones) |
|---|---|
| spotify | Previous, Play/Pause, Next, Like, Shuffle, Repeat |
| powerpoint | Slideshow, From slide, Previous, Next, Black screen, Exit |
| browser | Back, Forward, Reload, New tab, Close tab, Zoom −, Zoom + |
| word | Undo, Redo, Bold, Italic, Underline, Save |
| excel | Undo, Redo, Bold, AutoSum, Filter, Save |
| vscode | Palette, Search, Terminal, Comment, Save, Explorer |
| explorer | Back, Up, New folder, Rename, Refresh |
| generic | Copy, Paste, Undo, Screenshot, Desktop, Switch app |

- Display names get the same treatment.
  - Names that vary: `Browser`/`Navigateur` (the real browser name such as Chrome or Edge stays as today) and `Explorer`/`Explorateur`.
  - `DEFAULT_APP_NAME` becomes per language: `App` in en, `Application` in fr.
  - Spotify, PowerPoint, Word, Excel and VS Code are the same in both languages.
- `display_name(app, lang)`.

**`actions/context.py`**
- `ContextProvider(lang="fr", ...)`.
- `snapshot()` emits `label` in the current language.
- `handle({"id":"context.lang","lang":"en"})` sets the language (ignores unknown values and logs them) and returns so the hub broadcasts at once (follow how `context.press` and the hub broadcast after a handled action).

**Hub and engine**
- `actions/hub.py`: `default_providers(..., lang)` and the hub factory accept `lang` and pass it to `ContextProvider`.
- `engine.py`: `actions_hub_factory(send_actions_state, self._log, send_media_artwork, lang=info.lang)`.
- Keep every existing factory signature working: `lang` is a keyword argument with default `"fr"`, so the fakes in the tests still work. Update them where the tests need to check it.
- Routing: the hub already routes `context.*` to the context provider; check that `context.lang` reaches it.

**`messages.py`**
```
"adb.no_device": en "No device found. 1. Install Orizon X on the device and open it: it shows how to turn on USB debugging. 2. Plug it in with a USB cable that carries data."
                 fr "Aucun appareil trouvé. 1. Installe Orizon X sur l'appareil et ouvre-le : il explique comment activer le débogage USB. 2. Branche-le avec un câble USB qui transmet des données."
"adb.unauthorized": keep the current sentence and append, en: " Tick “Always allow” to skip this next time."  fr: " Coche « Toujours autoriser » pour ne plus avoir à le faire."
```
Check that the window shows long details wrapped. Look for a test of the detail label; if it is single-line, set `setWordWrap(True)`.

**`protocol/PROTOCOL.md`**
- Document `DEVICE_INFO.lang`.
- Document the `context.lang` action in the Actions section.

**Tests**
- Every button of every profile has non-empty `en` and `fr` labels.
- The French labels are unchanged (the existing tests keep passing).
- `snapshot()` is in English when built with `lang="en"`.
- `context.lang` switches the snapshot language, and the hub broadcasts the new state.
- An engine Actions session passes `DEVICE_INFO.lang` to the factory: a fake factory records its kwargs.
- `adb.*` messages exist in en and fr.

**Commit:** `feat(pc): device language for the context bar, guiding adb messages`.

### Task 2 — Android: English/French interface (model: sonnet)

Spec §2, §3 (device side).

**`i18n/Lang.kt`**
- `enum class Lang(val wire: String) { EN("en"), FR("fr") }`.
- `enum class LangPref { SYSTEM, EN, FR }`, with:
  - `next()`: SYSTEM → EN → FR → SYSTEM;
  - `fun effective(pref: LangPref, systemLanguage: String): Lang`, which gives FR when pref is FR, or when pref is SYSTEM and `systemLanguage == "fr"`, and EN otherwise.
- `val LocalLang = staticCompositionLocalOf { Lang.EN }`.

**`i18n/Strings.kt`**
- `object Strings { fun get(key: S, lang: Lang, vararg args: Pair<String, Any>): String }`, with `S` an enum of keys and a table `Map<S, Pair<String, String>>` (en, fr). `{name}` placeholders are replaced from `args`.
- A Compose helper `@Composable fun tr(key: S, vararg args: Pair<String, Any>) = Strings.get(key, LocalLang.current, *args)`.
- Move every user-visible string here, including:
  - `WaitingScreen.kt` and `ActionsScreen.kt`, including accessibility `contentDescription`s;
  - `OrizonXApp.kt` (the HUD hint);
  - `Receiver.kt` reasons, `TouchForwarder.kt`, `Session.kt`;
  - `ActionsFormat.kt`, including the action error codes.
- Find them with `grep` for literals with letters inside `Text(`, `GlassText(`, `Pill(`, `GlassButton(`, `contentDescription`, `reason =`.
- Code that is not composable gets a `lang` parameter, or returns a key plus its arguments that the UI translates. Prefer returning keys from `Receiver`, so reasons are translated at display time and a language switch re-translates a reason already on screen.
- French texts keep their exact current wording. English translations should be short and natural (e.g. "Waiting for the PC…", "Open Orizon X on the PC.", "Change mode", "Connecting to the PC…", "Long-press with 4 fingers: connection info").
- Sizes: `"$body libres"` → en `"{size} free"` with unit `GB`/`MB` and decimal `.`; fr keeps `Go`/`Mo` with `,`. Test both.
- Role buttons: "Écran" becomes en "Screen" / fr "Écran"; "Actions" is the same in both.

**Preference and wiring**
- Store `language` = `system|en|fr` in the existing SharedPreferences used for the role (find it in `MainActivity`/`DeviceRole`).
- `OrizonXApp` reads the system language with `LocaleList.getDefault()[0].language`. Re-read it on configuration change: the activity handles `locale` itself (see the manifest), so `onConfigurationChanged` must refresh it.
- `OrizonXApp` provides `LocalLang`.

**Language pill**
- `LangPill` shows `Auto`/`EN`/`FR` and cycles on tap with haptics.
- Place it top-right of `WaitingScreen`, and in `ActionsScreen` next to the "Changer de mode" pill.

**Protocol**
- `TabletMessage.DeviceInfo` gains `lang: String`.
- `FrameWriter.deviceInfo(..., lang)` and `deviceInfoFor(..., lang)`: the JSON writer emits `"lang"`.
- Update the shared test vector, if `DEVICE_INFO` has one in `protocol/`, without breaking the Python side: Python must still decode it. Run both test suites.
- `actions/ActionMessages.kt`: `contextLang(lang: Lang)` gives `{"id":"context.lang","lang":"en"}`. Send it when the effective language changes during an Actions session (where `contextPress` is sent).

**Tests (JVM)**
- Every `S` key has non-empty en and fr, with the same set of `{…}` placeholders.
- `effective()` for every pref × system language (fr, en, de).
- `next()` cycle.
- `Strings.get` replaces placeholders.
- Size formatting in both languages.
- `DEVICE_INFO` JSON with `lang`.
- `contextLang` JSON.
- Existing tests that assert French strings pass `Lang.FR`.

**Build:** build, then copy `android/app/build/outputs/apk/debug/app-debug.apk` → `dist/OrizonX-debug.apk`. Do not install.

**Commit:** `feat(android): English/French interface with a language pill, DEVICE_INFO.lang`.

### Task 3 — Android: per-brand setup guide (model: sonnet)

Spec §4. Needs Task 2 (`Strings`, `LocalLang`).

**`setup/SetupGuides.kt`**
- Pure data: `data class SetupGuide(val id: String, val buildPath: Pair<String,String>, val devPath: Pair<String,String>, val note: Pair<String,String>?)`, where each pair is (en, fr).
- `fun guideFor(manufacturer: String): SetupGuide` is case-insensitive and trims.
- Aliases:

| id | manufacturers |
|---|---|
| samsung | samsung |
| xiaomi | xiaomi, redmi, poco |
| pixel | google |
| oneplus | oneplus, oppo, realme |
| huawei | huawei |
| honor | honor |
| motorola | motorola |
| lenovo | lenovo |
| sony | sony |
| nothing | nothing |
| generic | everything else |

- Paths, exactly (en / fr):

| id | buildPath | devPath |
|---|---|---|
| samsung | Settings › About tablet (or phone) › Software information › Build number / Paramètres › À propos de la tablette (ou du téléphone) › Informations sur le logiciel › Numéro de version | Settings › Developer options (at the bottom) / Paramètres › Options de développement (tout en bas) |
| xiaomi | Settings › About phone › OS version (or MIUI version) / Paramètres › À propos du téléphone › Version de l'OS (ou Version MIUI) | Settings › Additional settings › Developer options / Paramètres › Paramètres supplémentaires › Options pour les développeurs |
| pixel | Settings › About phone › Build number / Paramètres › À propos du téléphone › Numéro de build | Settings › System › Developer options / Paramètres › Système › Options pour les développeurs |
| oneplus | Settings › About device › Version › Build number / Paramètres › À propos de l'appareil › Version › Numéro de version | Settings › Additional settings (or System settings) › Developer options / Paramètres › Paramètres supplémentaires (ou Paramètres système) › Options pour les développeurs |
| huawei | Settings › About phone › Build number / Paramètres › À propos du téléphone › Numéro de build | Settings › System & updates › Developer options / Paramètres › Système et mises à jour › Options pour les développeurs |
| honor | Settings › About phone › Build number / Paramètres › À propos du téléphone › Numéro de build | Settings › System & updates › Developer options / Paramètres › Système et mises à jour › Options pour les développeurs |
| motorola | Settings › About phone › Build number / Paramètres › À propos du téléphone › Numéro de build | Settings › System › Developer options / Paramètres › Système › Options pour les développeurs |
| lenovo | Settings › About tablet › Build number / Paramètres › À propos de la tablette › Numéro de build | Settings › System › Developer options / Paramètres › Système › Options pour les développeurs |
| sony | Settings › About phone › Build number / Paramètres › À propos du téléphone › Numéro de build | Settings › System › Developer options / Paramètres › Système › Options pour les développeurs |
| nothing | Settings › About phone › Software info › Build number / Paramètres › À propos du téléphone › Infos logiciel › Numéro de build | Settings › System › Developer options / Paramètres › Système › Options pour les développeurs |
| generic | Settings › About (phone or tablet) › Build number / Paramètres › À propos (du téléphone ou de la tablette) › Numéro de build (ou de version) | Settings › System › Developer options / Paramètres › Système › Options pour les développeurs |

- Notes:
  - xiaomi: en "On HyperOS or MIUI, tap 7 times on the OS version." / fr "Sur HyperOS ou MIUI, tape 7 fois sur la version de l'OS."
  - huawei: en "In the USB notification, choose File transfer." / fr "Dans la notification USB, choisis Transfert de fichiers."
  - All the others have none.
- Every step 1 also shows the tip (a `Strings` key): en "Tip: search “build” in Settings." / fr "Astuce : cherche « numéro » dans la barre de recherche des Paramètres."

**`setup/SetupState.kt`**
- `interface SetupProbe { fun devOptions(): Boolean?; fun usbDebugging(): Boolean?; fun usbPlugged(): Boolean? }`. `null` means unknown: the read failed.
- `data class SetupSteps(val devOptions: Boolean?, val usbDebugging: Boolean?, val usbPlugged: Boolean?)`.
- `val current: Int`: index of the first step not done, among 1..3. A null step counts as not done for the highlight but is shown without a check mark.
- `fun read(probe): SetupSteps`, and `val autoOpen = usbDebugging != true`.
- `AndroidSetupProbe(context)`:
  - `Settings.Global.getInt(cr, Settings.Global.DEVELOPMENT_SETTINGS_ENABLED, 0) == 1`;
  - `Settings.Global.getInt(cr, Settings.Global.ADB_ENABLED, 0) == 1`;
  - the sticky `registerReceiver(null, IntentFilter(Intent.ACTION_BATTERY_CHANGED))` with `EXTRA_PLUGGED == BatteryManager.BATTERY_PLUGGED_USB`;
  - each read is wrapped, so an exception gives null.

**`ui/SetupGuideCard.kt`**
- A glass card titled "Setup guide" / "Guide de connexion", showing:
  - the five steps of spec §4 with their check state (done = check + 50 % alpha; current = highlighted);
  - `buildPath`/`devPath` and the note in the current language;
  - buttons "Open About" / "Ouvrir À propos" (`Settings.ACTION_DEVICE_INFO_SETTINGS`) on step 1 and "Open developer options" / "Ouvrir les options développeur" (`Settings.ACTION_APPLICATION_DEVELOPMENT_SETTINGS`) on step 2, each falling back to `Settings.ACTION_SETTINGS` on `ActivityNotFoundException`;
  - step 4 as a tip;
  - step 5 "Open Orizon X on the PC" / "Ouvre Orizon X sur le PC".
- Refresh the state on `Lifecycle.Event.ON_RESUME` (`LocalLifecycleOwner` + `DisposableEffect`), and every 2 s while shown (`LaunchedEffect` loop).

**`WaitingScreen.kt`**
- While not connected, the card shows automatically if `autoOpen`.
- Otherwise a `Pill("Setup guide")` toggles it.
- When connected (Actions connected, or video starting) the card is not shown.
- In landscape, the card goes beside the logo and role buttons; in portrait, below them. Keep the existing layout readable on a phone (scroll if needed).

**Tests (JVM)**
- `guideFor` for each manufacturer and alias, in mixed case and with spaces, and `generic` for `"Fairphone"` and `""`.
- Every guide has non-empty en and fr paths.
- `SetupSteps.current` and `autoOpen` for: nothing done; dev only; dev + adb; all; null probes.
- The new `Strings` keys in en and fr: the existing completeness test covers them.

**Build:** build, then copy the debug APK to `dist/OrizonX-debug.apk`. Do not install.

**Commit:** `feat(android): per-brand setup guide with live checks`.

### Task 4 — Real test and wrap-up (controller, with the user)

1. Build the release APK with `.\build-android.ps1` and install it over the existing one with `adb install -r` (same key).
2. Run the PC app from source.
3. Check:
   - the language pill cycles (Auto/EN/FR) and the texts change at once;
   - in Actions mode, the context bar follows the language;
   - the guide shows the Samsung paths.
4. With the user's approval only, turn USB debugging off, so the guide opens and step 2 is unchecked, then back on. Turning it off cuts the PC connection.
5. Fix the findings.
6. Rebuild the installer, merge to master, push, and publish a v0.7.0 Release after bumping `version.py`.
