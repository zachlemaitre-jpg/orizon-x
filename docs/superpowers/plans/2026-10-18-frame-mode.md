# Frame Mode Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A third device role, Frame, that shows the images and videos of a PC folder as a slideshow, with settings in the PC window and quick controls on the device.

**Architecture:**
- The PC owns the playlist and sends prepared files (JPEG images, videos as-is) in 1 MiB `FRAME_FILE` chunks, always one file ahead. `FRAME_STATE` carries the settings and the status.
- The device reassembles the files into its cache and displays them natively: images in Compose, videos with `MediaPlayer` in a `TextureView`.
- When an item ends, or on a tap of Next, the device sends `frame.next`.

**Tech Stack:** Python 3.13, PySide6 (QImageReader, QFileDialog), ffmpeg (codec probe); Kotlin, Jetpack Compose, MediaPlayer.

**Spec:** `docs/superpowers/specs/2026-10-18-frame-mode-design.md`. Branch `frame-mode`, created from `i18n-guide`, which is not merged yet.

## Ground rules

- **Running the tests**
  - PC: `cd host-prototype; .\.venv\Scripts\python.exe -m unittest discover -s tests` and `py -m unittest discover -s tests`. Both must pass. Tests that need Qt are skipped under `py`; follow the existing pattern.
  - Android (PowerShell): `$env:JAVA_HOME = "C:\Program Files\Android\Android Studio\jbr"; cd android; .\gradlew.bat :app:testDebugUnitTest :app:assembleDebug`.
- **Discipline**
  - TDD; never weaken existing assertions.
  - No app, relay or adb runs, and no device install.
  - Never run commands that read stdin.
  - Never touch `C:\Users\zachl\OrizonX-signing\`.
- **Commits**
  - Stage only your files, by explicit path. Tasks 2 and 3 run in parallel in the same tree.
  - Commit messages end with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.

Order: Task 1, then Tasks 2 and 3 in parallel, then Task 4.

### Task 1 — Protocol: FRAME_STATE, FRAME_FILE, DEVICE_INFO role (model: sonnet)

Spec §3.

**`protocol/PROTOCOL.md`**
- Rows for `0x06 FRAME_STATE` and `0x07 FRAME_FILE` in the PC → device table.
- `"frame"` in the `DEVICE_INFO.role` values.
- A "Frame mode" section with the JSON fields, the chunk rules, the `frame.*` actions and the one-ahead flow.

**`protocol/test-vectors.json`**
- Add the vectors in the same format as the existing ones:
  - `frame_state_ok`: epoch 3, status ok, folder "Photos", interval_s 30, fit crop, paused false;
  - `frame_state_no_folder`: folder null;
  - `frame_file_first_chunk`: epoch 3, id 7, kind 1, total 10, offset 0, data `0102030405`;
  - `frame_file_last_chunk`: offset 5, data `060708090a`.
- JSON key order for `FRAME_STATE`: `epoch, status, folder, interval_s, fit, paused`, compact.

**Python (`host-prototype/protocol.py`)**
- Types `FRAME_STATE = 0x06` and `FRAME_FILE = 0x07`.
- `encode_frame_state(...)` and `encode_frame_file(epoch, id, kind, total, offset, data)`, with header fields big-endian like the rest of the protocol. Check how CONFIG and VIDEO are packed.
- Validation: data of 1..1_048_576 bytes, `offset + len <= total`, kind 1 or 2.
- Decoders for the tests, if the existing vector test harness decodes PC → device messages. Follow it.
- `DeviceInfo` accepts role `"frame"`; check how unknown roles are handled today and keep that for others.

**Kotlin (`android/.../protocol/`)**
- `PcMessage.FrameState(epoch, status, folder, intervalS, fit, paused)`, tolerant: unknown fields ignored, an unknown status maps to `"unreadable"`.
- `PcMessage.FrameFile(epoch, id, kind, total, offset, data)`, with the same validation (violation = protocol error).
- Decoded in the existing frame reader.
- `DeviceRole.FRAME("frame")`: add the enum value only. No UI in this task, but make sure the existing `when` expressions still compile; map FRAME to the waiting screen like SCREEN for now if needed.

**Tests:** both vector suites (Python and Kotlin) cover the 4 new vectors, plus the validation errors.

**Commit:** `feat(protocol): FRAME_STATE and FRAME_FILE messages, frame role`.

### Task 2 — PC: playlist, preparation, session, engine, window (model: sonnet)

Spec §2, §4, §6. Needs Task 1.

**`host-prototype/frame/__init__.py`, `frame/playlist.py`**
- `IMAGE_EXTS = {".jpg",".jpeg",".png",".webp",".bmp",".gif"}`, `VIDEO_EXTS = {".mp4",".m4v",".mov",".webm",".mkv"}`.
- `scan_folder(folder) -> list[Path]`: recursive, case-insensitive extensions, skips hidden and system files (`FILE_ATTRIBUTE_HIDDEN | FILE_ATTRIBUTE_SYSTEM` via `os.stat(...).st_file_attributes`, plus names starting with `.`), sorted for determinism. `OSError` on the root → raise `FolderUnreadable`.
- `Playlist(folder, scan=scan_folder, rng=random.Random())`:
  - `next() -> Path | None` and `remove(path)`;
  - `status`: `"ok"`, `"empty"` or `"unreadable"`;
  - a new round re-scans and shuffles; if the round's first file equals the last one played and there are at least 2 files, swap it with the second;
  - files removed by `remove()` stay excluded for the playlist's life.

**`frame/prepare.py`**
- `cover_size((w,h), (sw,sh)) -> (w,h)`. Let `limit = max(sw, sh)`. If `min(w,h) <= limit`, return `(w,h)`; otherwise scale by `limit / min(w,h)`, rounding both sides.
- `prepare_image(path, screen) -> bytes`:
  - `QImageReader(str(path))` with `setAutoTransform(True)`;
  - read the size (after the EXIF transform: the `transformation()` swaps w/h for 90°/270°), then `setScaledSize(cover)`;
  - `read()`, then save as JPEG quality 90 into a `QBuffer`;
  - any failure raises `PrepareError`.
  - Import Qt lazily inside the function, so a `py` run without PySide6 still imports the module.
- `video_codec(ffmpeg, path, run=subprocess.run) -> str | None`:
  - run `[ffmpeg, "-hide_banner", "-nostdin", "-i", str(path)]` (exit code 1 is normal: no output);
  - parse stderr for the first `Stream #...: Video: (\w+)`;
  - use `creationflags=tools.NO_WINDOW`, `cwd=tools.tool_cwd(ffmpeg)` and a 10 s timeout;
  - an error or timeout gives `None`.
- `VIDEO_CODECS = {"h264","hevc","vp8","vp9"}`, `MAX_VIDEO_BYTES = 2 * 1024**3`.

**`frame/session.py`**
- `FrameConfig(folder: str | None, interval_s: int, fit: str)` and `INTERVALS = (5, 10, 30, 60, 300, 900, 3600)`.
- `FrameSession(send_state, send_file_chunk, log, config, screen, ffmpeg, listener=None, deps…)`:
  - Its own worker thread with a queue of commands: start, next, failed, set_config, stop.
  - On start, send `FRAME_STATE`, then prepare and send 2 files. Each `frame.next` or `frame.failed` sends one more.
  - A file's bytes:
    - image: `prepare_image`;
    - video: the codec must be in `VIDEO_CODECS` and the size at most `MAX_VIDEO_BYTES`; otherwise skip, log, and take the next.
  - Videos are streamed from disk in 1 MiB reads, never held whole in memory. Images are bytes, chunked the same way.
  - Ids increase from 1.
- `epoch`: starts at 1 and increments on a folder change. A folder change resets the playlist, sends `FRAME_STATE` and sends 2 files of the new epoch.
- Actions:
  - `frame.pause` / `frame.fit` / `frame.interval`: update, send `FRAME_STATE`, call `listener.on_frame_settings(interval_s, fit, paused)`;
  - `frame.interval` values not in `INTERVALS` are ignored and logged;
  - `frame.failed` (`file` id): remove that path from the playlist, then send the next file.
- Status:
  - no folder → `no_folder`, and nothing is sent;
  - empty → `empty`;
  - unreadable → `unreadable`, re-scan every 10 s while unreadable or empty;
  - when all files of a round fail → `empty`.
- `stop()` ends the thread; an `OSError` from send ends the session quietly.

**`engine.py`**
- `ROLE_FRAME = "frame"`, `Deps.frame_session_factory` (default builds `FrameSession`).
- In the session flow next to the Actions branch:
  - role frame → create the session with the HELLO screen size, the current frame config and the ffmpeg path;
  - route `ACTION` ids starting with `frame.` to it;
  - no virtual display, no ffmpeg capture;
  - stop it at session end.
- `RelayEngine.set_frame_config(folder, interval_s, fit)` stores the config, thread-safe, and forwards it to the live session.
- The listener's `on_frame_settings` is forwarded through the engine listener (`getattr(self._listener, "on_frame_settings", None)`, like `on_display`).
- Log line `Device role: frame (...)`, which the existing role log already gives once frame is a known role.

**`protocol.py`:** nothing beyond Task 1.

**App**
- `app/settings.py`:
  - `frame_folder: str | None = None`, `frame_interval_s: int = 30`, `frame_fit: str = "crop"`;
  - validated at load (interval in `INTERVALS`, fit in `("crop","fit")`, folder a str or None);
  - tests in `tests/test_settings.py`.
- `app/window.py`, a "Frame" / "Tableau" group under the existing fields, using the same look:
  - a label showing the folder, elided in the middle, "No folder" / "Aucun dossier" when unset;
  - a "Choose…" / "Choisir…" button that opens `QFileDialog.getExistingDirectory` and emits `frame_folder_chosen(str)`;
  - an Interval `ChoiceCombo` with labels like "5 s", "1 min", "1 h";
  - a Display `ChoiceCombo` "Crop"/"Fit" ("Rogner"/"Ajuster");
  - signals `frame_interval_changed(int)` and `frame_fit_changed(str)`, and setters for the controller;
  - make the dialog injectable for tests;
  - strings in `messages.py` (en/fr).
- `app/controller.py`:
  - at start, apply the saved frame settings to the engine and the window;
  - window signals → save the settings plus `engine.set_frame_config`;
  - engine `on_frame_settings` → save, then update the window on the Qt thread, as other engine callbacks do.

**Tests**
- playlist (shuffle without repeat, no duplicate at the junction, subfolders, filters, hidden files, re-scan, remove, states);
- `cover_size`;
- `video_codec` with fake stderr for h264, hevc, vp9, av1 and an error;
- the session with fake sends and a fake prepare:
  - 2 files ahead;
  - chunking, a 2.5 MiB file giving 3 chunks with correct offsets;
  - `frame.next`;
  - epoch on a folder change;
  - pause, fit and interval with the listener;
  - an invalid interval;
  - failed;
  - empty, unreadable and no_folder;
- engine: role frame → factory called, no display prepare, `frame.*` routed;
- settings, window and controller.

**Commit:** `feat(pc): frame mode (playlist, image preparation, session, window group)`.

### Task 3 — Android: frame role, store, player, screen (model: sonnet)

Spec §2, §5. Needs Task 1.

**Role**
- On the waiting screen, a "Frame" / "Tableau" button (strings in `Strings`, en/fr) next to Screen and Actions.
- Icon `res/drawable/ox_mode_frame.xml` from the Material Icons "image" path (24 dp, Apache-2.0 comment), in the same style as the `ox_mode_*` drawables.
- Role persisted like the others.
- Keep the screen on in the frame role (as Actions does).

**`frame/FrameStore.kt`**
- `FrameStore(dir: File)`:
  - `begin(epoch)` sets the current epoch and deletes files of other epochs;
  - `onChunk(FrameFile): Result`, where `Result` is `Partial`, `Complete(FrameItem(id, kind, file))`, `Rejected(id)` (out of order, or an offset that does not match the bytes received so far) or `Stale`;
  - write with an append stream per file;
  - `release(id)` deletes a played file;
  - at most 3 completed files kept, the oldest deleted;
  - `clear()` at session start and end.

**`frame/FramePlayer.kt`, pure logic (no Android types)**
- State:
  - `current: FrameItem?`, `queue: List<FrameItem>`;
  - `status`, `intervalS`, `fit`, `paused`;
  - `elapsedMs` for images.
- Events:
  - `onState(FrameState)`: an epoch change clears `current` and `queue`;
  - `onItemReady(item)`: if nothing is shown, show it;
  - `onTick(dtMs)`: images only, not paused; when `elapsedMs >= intervalS*1000`, finish;
  - `onVideoEnded()`, `onNextTapped()`, `onPlaybackFailed()`, `onPauseTapped()`, `onFitTapped()`, `onIntervalStep(+1/-1)` (moves in `INTERVALS = 5,10,30,60,300,900,3600`, clamped).
- Outputs:
  - `List<Effect>`, where `Effect` is `SendNext`, `SendFailed(id)`, `SendPause(b)`, `SendFit(f)`, `SendInterval(s)`, `Release(id)` or `Show(item)`.
  - Finishing an item emits `Release(old)` and `SendNext`, then shows `queue.first()` if there is one. Otherwise it keeps the old item on screen until the next is ready, and does not release it until replaced.
  - A failure emits `SendFailed`, then advances in the same way.
- `frame/FrameActions.kt`: JSON for the 5 actions, `id` first then the other keys alphabetically, as in the protocol.

**`ui/FrameScreen.kt`**
- Full-screen black.
- Images: decode with `BitmapFactory` using `inSampleSize` so the bitmap is at most about 2× the screen, then `Image` with `ContentScale.Crop` or `Fit`.
- Videos: `MediaPlayer` + `TextureView` (`AndroidView`), `setVolume(0f, 0f)`.
  - Apply a `Matrix` so the video fills the view (crop) or fits inside it (fit), centred.
  - `setOnCompletionListener` → `onVideoEnded`, `setOnErrorListener` → `onPlaybackFailed`.
  - Release the player when the item changes or on dispose.
- 1 s crossfade (`Crossfade` or alpha animation) between items.
- A tap shows the control bar (glass style) for 5 s:
  - Pause/Play, Next, Crop/Fit, and interval − / value / +;
  - the existing `ox_*` or Material icons, with haptics.
- Status messages from `Strings` (§2 table: Choose a folder…, No images…, Cannot read…, Loading…).
- A ticker drives `onTick` every 200 ms while an image is shown.

**Wiring**
- Route `FRAME_STATE` and `FRAME_FILE` from the session or receiver to the store and the player, in the frame role, following how Actions receives `ACTIONS_STATE`.
- Send the actions with the existing `FrameWriter.action`.
- Disconnection → `store.clear()`, then back to the waiting screen.

**Tests (JVM)**
- `FrameStore` with a temp dir: reassembly, out-of-order → Rejected, stale epoch, max 3 files, release.
- `FramePlayer`:
  - image timer;
  - pause stops the timer;
  - video end;
  - next tapped;
  - next not ready yet (the old item is kept, then shown when the next arrives);
  - failed;
  - epoch change;
  - interval stepping and clamping;
  - fit toggle.
- Action JSON.
- The new strings are covered by the existing completeness test.

**Build:** copy the debug APK to `dist/OrizonX-debug.apk`. Do not install.

**Commit:** `feat(android): frame mode (store, player, screen, role)`.

### Task 4 — Real test (controller, with the user)

1. Build the release APK with `.\build-android.ps1`, install it with `adb install -r`, and run the PC app from source.
2. Make a test folder with the user's own photos (one portrait phone photo) and an MP4 video.
3. Check:
   - crop and fit;
   - the interval;
   - pause;
   - next;
   - the bar;
   - a folder change during a session;
   - an unsupported video skipped;
   - the empty and no-folder messages.
4. Fix the findings.
5. Rebuild the installer.
6. Merge `i18n-guide` then `frame-mode` into master (fast-forward), push, bump `version.py` to 0.7.0 and publish a Release.
