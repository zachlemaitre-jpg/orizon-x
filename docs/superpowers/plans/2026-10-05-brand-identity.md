# Brand Identity Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Show the Orizon X logo (white vector) and the title "Orizon X" in the MAZAGLA font on the tablet waiting screen and in the PC window.

**Architecture:** Copy the SVG/OTF sources from `extended/` into each app's resources (Android `res/drawable` VectorDrawable + `res/font`; PC `app/assets`). PC gets a small `app/brand.py` (font loading + SVG rendering); `MainWindow` and `WaitingScreen` get a centred hero (logo + title) above the status.

**Tech Stack:** PySide6 6.11 (QtSvg, QFontDatabase), Kotlin/Compose (BOM 2026.06.01, AGP 9.0.1), unittest, Gradle.

**Spec:** `docs/superpowers/specs/2026-10-05-brand-identity-design.md`.

## Ground rules

- Repo `D:\TumorScreen App`, branch `pc-app`. Sources: `extended/SVG/icon_app.svg` (viewBox 0 0 1024 1024, three `<path>` with default black fill), `extended/Maglaza-Regular.otf` (family `MAZAGLA`).
- PC tests: `cd host-prototype; .\.venv\Scripts\python.exe -m unittest discover -s tests` (177 OK before) and `py -m unittest discover -s tests` (Qt skipped).
- Android: `$env:JAVA_HOME = "C:\Program Files\Android\Android Studio\jbr"; cd android; .\gradlew.bat :app:testDebugUnitTest :app:assembleDebug` (41 tests before).
- The user may be streaming to the plugged-in tablet with the relay. Never run adb, the relay, or the app with adb reachable. Never run commands that read stdin.
- Commits end with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.

---

### Task 1: PC — brand module, assets, window hero

**Files:**
- Create: `host-prototype/app/assets/logo.svg`, `host-prototype/app/assets/mazagla.otf`, `host-prototype/app/brand.py`, `host-prototype/tests/test_brand.py`
- Modify: `host-prototype/app/window.py`, `host-prototype/tests/test_window.py`, `host-prototype/app/main.py` (only if needed to load the font before building the window)

- [ ] **Step 1: Assets.** Copy `extended/Maglaza-Regular.otf` to `host-prototype/app/assets/mazagla.otf`. Create `host-prototype/app/assets/logo.svg` = the source SVG with `fill="#FFFFFF"` added to each of the three `<path>` elements (drop the XML prolog's `id`/`data-name` attributes if you like; keep viewBox).

- [ ] **Step 2: Failing tests** — `host-prototype/tests/test_brand.py`:

```python
import importlib.util
import os
import unittest

HAVE_QT = importlib.util.find_spec("PySide6") is not None
if HAVE_QT:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication

    from app import brand


@unittest.skipUnless(HAVE_QT, "PySide6 absent")
class BrandTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_font_family_is_mazagla(self):
        self.assertEqual(brand.load_brand_font(), "MAZAGLA")
        self.assertEqual(brand.load_brand_font(), "MAZAGLA")  # deuxième appel : pas de double chargement

    def test_logo_is_sharp_on_hidpi(self):
        pixmap = brand.logo_pixmap(44, 2.0)
        self.assertFalse(pixmap.isNull())
        self.assertEqual((pixmap.width(), pixmap.height()), (88, 88))
        self.assertEqual(pixmap.devicePixelRatio(), 2.0)

    def test_logo_is_white_with_transparent_corners(self):
        image = brand.logo_pixmap(64, 1.0).toImage()
        centre = image.pixelColor(32, 40)  # dans le X
        self.assertEqual((centre.red(), centre.green(), centre.blue(), centre.alpha()), (255, 255, 255, 255))
        self.assertEqual(image.pixelColor(0, 0).alpha(), 0)

    def test_missing_font_falls_back_without_crashing(self):
        family = brand.load_brand_font(path=brand.ASSETS / "absent.otf", cache=False)
        self.assertTrue(family)
        self.assertNotEqual(family, "MAZAGLA")
```

Add to `tests/test_window.py` (inside `WindowTest`):

```python
    def test_brand_title_uses_mazagla_and_title_bar_has_no_name(self):
        self.assertEqual(self.window.brand_title_family(), "MAZAGLA")
        self.assertEqual(self.window.brand_title_text(), "Orizon X")
        self.assertNotIn("Orizon X", self.window.title_bar_texts())
```

Run: `.\.venv\Scripts\python.exe -m unittest tests.test_brand tests.test_window -v` → fails (`cannot import name 'brand'`, missing methods). Check that pixel (32, 40) of a 64-px render is inside the X: the X's central body spans x≈447-577 / y≈239-785 in the 1024 viewBox; (32,40)→(512,640) in viewBox coordinates is inside the lower part of the X. If not, pick a point that is, and say so.

- [ ] **Step 3: Implement `host-prototype/app/brand.py`:**

```python
"""Orizon X identity: the MAZAGLA title font and the white vector logo."""
from __future__ import annotations

import logging
from pathlib import Path

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QFont, QFontDatabase, QPainter, QPixmap
from PySide6.QtSvg import QSvgRenderer

ASSETS = Path(__file__).resolve().parent / "assets"
FONT_PATH = ASSETS / "mazagla.otf"
LOGO_PATH = ASSETS / "logo.svg"

logger = logging.getLogger("orizonx")
_family: str | None = None


def load_brand_font(path: Path = FONT_PATH, cache: bool = True) -> str:
    """Family name of the title font (loaded once); the default UI family if the file can't be loaded."""
    global _family
    if cache and _family is not None:
        return _family
    font_id = QFontDatabase.addApplicationFont(str(path))
    families = QFontDatabase.applicationFontFamilies(font_id) if font_id >= 0 else []
    if families:
        family = families[0]
    else:
        logger.warning("Police du titre introuvable (%s) : police système utilisée", path)
        family = QFont().defaultFamily()
    if cache:
        _family = family
    return family


def logo_pixmap(size_px: int, device_pixel_ratio: float) -> QPixmap:
    """The white logo, size_px logical pixels wide, rendered at the screen's real resolution."""
    physical = round(size_px * device_pixel_ratio)
    pixmap = QPixmap(physical, physical)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    QSvgRenderer(str(LOGO_PATH)).render(painter, QRectF(0, 0, physical, physical))
    painter.end()
    pixmap.setDevicePixelRatio(device_pixel_ratio)
    return pixmap
```

- [ ] **Step 4: Window hero** in `host-prototype/app/window.py`:
  - Title bar: remove the 18-px icon `QLabel` and the `brand` `QLabel`; keep `addStretch(1)`, minimize and close buttons (the bar stays draggable).
  - `StatusDot`: fixed size 10×10, plain filled circle, no halo.
  - New hero at the top of `body` (centred): `self._logo = QLabel()` with `brand.logo_pixmap(44, self.devicePixelRatioF())` (refresh it in `showEvent` in case the window opened on a screen with another scale), then `self._brand_title = QLabel("Orizon X")` with `QFont(brand.load_brand_font(), 26)` set via `setFont` (not the stylesheet, which sets the family for every QWidget; give the label objectName `brandTitle` and in STYLE add `QLabel#brandTitle { font-family: "<family>"; font-size: 26px; }` built from the loaded family — whichever approach actually wins over the global `QWidget { font-family: ... }` rule; the test checks `QFontInfo(label.font()).family()`).
  - Status line: `QHBoxLayout` centred with `self._dot` (10 px) + 8 px spacing + `self._title` (16 px, weight 600 — update `QLabel#title` in STYLE).
  - Remove the old big-dot row. `setFixedSize(360, 380)`.
  - Test accessors: `brand_title_family()` → `QFontInfo(self._brand_title.font()).family()`; `brand_title_text()`; `title_bar_texts()` → texts of all `QLabel`s that are children of the title bar.
  - Remove the now-unused `brand` objectName style rule; drop the `logo` use in the title bar but keep the constructor signature `MainWindow(logo: QPixmap)` (`setWindowIcon(QIcon(logo))`).

- [ ] **Step 5: Run tests** (venv and `py`, 3× venv): all pass.

- [ ] **Step 6: Visual check (safe, no adb).** Same procedure as the PC app plan Task 10 Step 5: override `LOCALAPPDATA` and `APPDATA` to temp folders, verify `Get-Command adb` returns nothing, start `.venv\Scripts\pythonw.exe orizonx_pc.py` with Start-Process, wait 4 s, make the window topmost if needed (the app has the title "Orizon X"), capture the screen DPI-aware, crop around the window, Stop-Process in a `finally` (and check no leftover pythonw child). View the crop with the Read tool: logo crisp and white, "Orizon X" in the MAZAGLA font, status line readable, nothing clipped at 380 px height. Adjust sizes/spacing if something is clipped or cramped and re-check. Keep the final crop in the scratchpad `C:\Users\zachl\AppData\Local\Temp\claude\D--TumorScreen-App\c1c69d40-6f64-499c-bfd0-916de6e62694\scratchpad\brand-pc.png`.

- [ ] **Step 7: Commit** (`feat(pc): logo and MAZAGLA title in the window`).

---

### Task 2: Android — vector logo, font, waiting screen hero

**Files:**
- Create: `android/app/src/main/res/drawable/ic_orizonx_logo.xml`, `android/app/src/main/res/font/mazagla.otf`
- Modify: `android/app/src/main/java/com/orizonx/client/ui/Glass.kt`, `android/app/src/main/java/com/orizonx/client/ui/WaitingScreen.kt`

- [ ] **Step 1: VectorDrawable** `res/drawable/ic_orizonx_logo.xml`:

```xml
<?xml version="1.0" encoding="utf-8"?>
<!-- Logo Orizon X (extended/SVG/icon_app.svg), en blanc pour le verre sombre. -->
<vector xmlns:android="http://schemas.android.com/apk/res/android"
    android:width="96dp"
    android:height="96dp"
    android:viewportWidth="1024"
    android:viewportHeight="1024">
    <path android:fillColor="#FFFFFFFF" android:pathData="<d of path 1, copied exactly from the SVG>" />
    <path android:fillColor="#FFFFFFFF" android:pathData="<d of path 2>" />
    <path android:fillColor="#FFFFFFFF" android:pathData="<d of path 3>" />
</vector>
```
Copy the three `d` attributes verbatim from `extended/SVG/icon_app.svg` (no angle-bracket placeholders may remain).

- [ ] **Step 2: Font.** Copy `extended/Maglaza-Regular.otf` to `android/app/src/main/res/font/mazagla.otf`. In `ui/Glass.kt` add:

```kotlin
/** Police du titre « Orizon X » (MAZAGLA), réservée à la marque. */
val BrandFont = FontFamily(Font(R.font.mazagla))
```
(imports `androidx.compose.ui.text.font.Font`, `com.orizonx.client.R`).

- [ ] **Step 3: WaitingScreen** — replace the card content with a centred column (`Column(horizontalAlignment = Alignment.CenterHorizontally)` inside the existing `GlassCard`, keeping the card's width modifiers):
  1. `Image(painterResource(R.drawable.ic_orizonx_logo), contentDescription = "Logo Orizon X", Modifier.size(96.dp))`
  2. 8 dp, then title `BasicText("Orizon X", style = TextStyle(color = Color.White, fontSize = 44.sp, fontFamily = BrandFont))`
  3. 20 dp, status `Row(verticalAlignment = CenterVertically)`: `PulsingDot()`, 10 dp, `GlassText("En attente du PC…", size = 16.sp)`
  4. if `reason != null`: 8 dp, `GlassText(reason, size = 13.sp, color = Amber)` (centred text: use `TextAlign.Center` — add an optional `align: TextAlign? = null` parameter to `GlassText` if needed)
  5. 14 dp, `GlassText("Lance Orizon X sur le PC.", size = 13.sp, alpha = 0.85f)` — the old "Sur le PC :" label and the `py relay.py --encoder amf` command box are removed.
  6. 10 dp, `GlassText("Appui long à 4 doigts : infos de connexion", size = 12.sp, alpha = 0.75f)`
  7. 18 dp, footer `Row`: `"${screen.width}×${screen.height}"` · `"127.0.0.1:${Protocol.PORT}"` · `"protocole v${Protocol.VERSION}"` (12 sp, alpha 0.7, 20 dp gaps). The old header row with the 26-sp "Orizon X" and the protocol version is removed.
  Remove imports that become unused.

- [ ] **Step 4: Build and unit tests.** `:app:testDebugUnitTest :app:assembleDebug` → BUILD SUCCESSFUL, 41 tests. Do NOT install on the tablet (the controller does it after warning the user). Copy the APK to `dist/OrizonX.apk` (overwrite).

- [ ] **Step 5: Visual check without the device.** Render a Compose preview image is not available headless; instead verify the VectorDrawable compiles and, as a proxy, render `extended/SVG/icon_app.svg` paths are identical: compare the three `pathData` strings with the SVG `d` strings by script (must be byte-identical).

- [ ] **Step 6: Commit** (`feat(android): logo and MAZAGLA title on the waiting screen`).
