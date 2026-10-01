# TabX Phase 4 — Tactile et stylet : plan d'implémentation

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal :** le doigt et le S Pen sur la tablette pilotent Windows à l'endroit touché de l'écran étendu (tap, gestes natifs, encre avec pression et inclinaison, bouton = clic droit). Le geste du HUD devient un appui long à 4 doigts.

**Architecture :**
- La tablette convertit ses `MotionEvent` en trames `INPUT` (état complet d'un périphérique) grâce à un `InputMapper` en Kotlin pur. Une liaison Android les lit sur le `SurfaceView` vidéo.
- Le relais Python compare chaque trame à l'état précédent (`inputstate.py`, logique pure).
- Il l'injecte avec l'API Windows Synthetic Pointer via `ctypes` (`injector.py`).

**Tech Stack :** Python 3.13 (`ctypes`, stdlib), Win32 `CreateSyntheticPointerDevice` / `InjectSyntheticPointerInput`, Kotlin + Compose (projet existant), JUnit 4 + org.json, unittest.

**Spec :** `docs/superpowers/specs/2026-10-01-phase4-touch-pen-input-design.md`

---

## Environnement (identique à la phase 1)

- Commandes PowerShell, depuis la racine `D:\TumorScreen App`, sauf indication contraire. Python : `py`.
- Gradle : `$env:JAVA_HOME = "C:\Program Files\Android\Android Studio\jbr"; cd android; .\gradlew.bat <tâches> --console=plain; cd ..`
- ffmpeg est dans le PATH utilisateur (`%LOCALAPPDATA%\Programs\ffmpeg\bin`).
- Avant la tâche 1 : `git checkout -b phase4-touch-pen`.
- Chaque message de commit se termine par une ligne vide puis `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.
- Ne jamais lancer de commande shell qui lit l'entrée standard sans entrée (`cat` seul…).

## Structure des fichiers

```
protocol/
├── PROTOCOL.md                     (modifié) section INPUT
└── test-vectors.json               (modifié) 3 vecteurs INPUT
host-prototype/
├── protocol.py                     (modifié) Contact, Input, constantes, décodage
├── inputstate.py                   (nouveau) trames INPUT → actions de pointeur Windows (pur)
├── injector.py                     (nouveau) Win32/ctypes : DPI, moniteur cible, injection, --selftest
├── relay.py                        (modifié) DPI au démarrage, injecteur par session, routage INPUT
└── tests/
    ├── test_protocol.py            (modifié) vecteurs INPUT + rejets
    ├── test_inputstate.py          (nouveau)
    └── test_injector.py            (nouveau) tailles des structures Win32, choix du moniteur
android/app/src/main/java/dev/tabx/client/
├── protocol/Messages.kt            (modifié) constantes, InputContact, TabletMessage.Input
├── protocol/FrameWriter.kt         (modifié) encodage INPUT
├── input/InputMapper.kt            (nouveau) logique pure
├── input/TouchForwarder.kt         (nouveau) liaison Android
├── Session.kt                      (modifié) sendInput
├── Receiver.kt                     (modifié) session courante + sendInput
├── MainActivity.kt                 (modifié) création du TouchForwarder
└── ui/TabXApp.kt, ui/StreamScreen.kt, ui/WaitingScreen.kt (modifiés)
android/app/src/test/java/dev/tabx/client/
├── protocol/ProtocolVectorsTest.kt (modifié) branche INPUT
└── input/InputMapperTest.kt        (nouveau)
README.md                           (modifié) section tactile + checklist
```

---

### Task 1 : Protocole INPUT — référence, vecteurs, décodage Python

**Files:**
- Modify: `protocol/PROTOCOL.md`
- Modify: `protocol/test-vectors.json`
- Modify: `host-prototype/protocol.py`
- Modify: `host-prototype/tests/test_protocol.py`

- [ ] **Step 1 : Ajouter les 3 vecteurs** à la fin du tableau `"tablet_to_pc"` de `protocol/test-vectors.json` (après l'objet `"stats"`, avec une virgule après lui) :

```json
    {
      "name": "input_touch_two_fingers",
      "type": "INPUT",
      "fields": {"device": 1, "contacts": [
        {"id": 0, "flags": 3, "x": 32768, "y": 16384, "pressure": 0, "tilt_x": 0, "tilt_y": 0},
        {"id": 1, "flags": 3, "x": 65535, "y": 0, "pressure": 0, "tilt_x": 0, "tilt_y": 0}
      ]},
      "hex": "85000000000000160102000380004000000000000103ffff000000000000"
    },
    {
      "name": "input_pen_contact",
      "type": "INPUT",
      "fields": {"device": 2, "contacts": [
        {"id": 0, "flags": 7, "x": 1000, "y": 2000, "pressure": 512, "tilt_x": -30, "tilt_y": 45}
      ]},
      "hex": "850000000000000c0201000703e807d00200e22d"
    },
    {
      "name": "input_touch_none",
      "type": "INPUT",
      "fields": {"device": 1, "contacts": []},
      "hex": "85000000000000020100"
    }
```

Vérifier : `py -c "import json; d = json.load(open('protocol/test-vectors.json')); print(len(d['tablet_to_pc']))"` → `7`.

- [ ] **Step 2 : Écrire les tests qui échouent** dans `host-prototype/tests/test_protocol.py` :
  - ajouter cette entrée au dictionnaire `EXPECTED_TABLET_MESSAGES` :
    ```python
        "INPUT": lambda f: protocol.Input(f["device"], tuple(protocol.Contact(**c) for c in f["contacts"])),
    ```
  - ajouter ces méthodes à la classe `ReadMessageTest` :
    ```python
        def test_rejects_input_with_wrong_size(self):
            with self.assertRaises(protocol.ProtocolError):
                protocol.read_message(io.BytesIO(bytes.fromhex("8500000000000003" "010100")))

        def test_rejects_input_from_unknown_device(self):
            with self.assertRaises(protocol.ProtocolError):
                protocol.read_message(io.BytesIO(bytes.fromhex("8500000000000002" "0300")))

        def test_rejects_more_than_one_pen_contact(self):
            with self.assertRaises(protocol.ProtocolError):
                protocol.read_message(io.BytesIO(bytes.fromhex("8500000000000016" "0202" + "00" * 20)))
    ```

- [ ] **Step 3 : Lancer, vérifier l'échec**

`cd host-prototype; py -m unittest tests.test_protocol -v; cd ..` → erreurs `AttributeError: module 'protocol' has no attribute 'Input'` (dans le sous-test des vecteurs) et échecs des 3 nouveaux tests (un `INPUT` inconnu est aujourd'hui ignoré, donc `EOFError` au lieu de `ProtocolError`).

- [ ] **Step 4 : Implémenter dans `host-prototype/protocol.py`**
  - ajouter sous `STATS = 0x84` :
    ```python
    INPUT = 0x85

    DEVICE_TOUCH = 1
    DEVICE_PEN = 2
    MAX_TOUCH_CONTACTS = 10
    # bits de Contact.flags
    CONTACT_CONTACT = 0x01
    CONTACT_IN_RANGE = 0x02
    CONTACT_BARREL = 0x04
    CONTACT_CANCELED = 0x08
    ```
  - ajouter sous `_STATS = struct.Struct(">HIIII")` :
    ```python
    _INPUT_HEAD = struct.Struct(">BB")
    _CONTACT = struct.Struct(">BBHHHbb")
    ```
  - ajouter après la dataclass `Stats` :
    ```python
    @dataclass(frozen=True)
    class Contact:
        id: int
        flags: int
        x: int
        y: int
        pressure: int
        tilt_x: int
        tilt_y: int


    @dataclass(frozen=True)
    class Input:
        device: int
        contacts: tuple[Contact, ...]
    ```
  - remplacer `TabletMessage = Hello | Ping | KeyframeRequest | Stats` par `TabletMessage = Hello | Ping | KeyframeRequest | Stats | Input` ;
  - dans `decode_payload`, juste avant la ligne `except struct.error as e:`, ajouter :
    ```python
            if msg_type == INPUT:
                return _decode_input(payload)
    ```
  - ajouter après `decode_payload` :
    ```python
    def _decode_input(payload: bytes) -> Input:
        if len(payload) < _INPUT_HEAD.size:
            raise ProtocolError(f"INPUT trop court : {len(payload)} octets")
        device, count = _INPUT_HEAD.unpack_from(payload)
        max_count = {DEVICE_TOUCH: MAX_TOUCH_CONTACTS, DEVICE_PEN: 1}.get(device)
        if max_count is None:
            raise ProtocolError(f"INPUT : périphérique inconnu {device}")
        if count > max_count:
            raise ProtocolError(f"INPUT : {count} contacts pour le périphérique {device} (max {max_count})")
        if len(payload) != _INPUT_HEAD.size + _CONTACT.size * count:
            raise ProtocolError(f"INPUT : {len(payload)} octets pour {count} contact(s)")
        contacts = tuple(
            Contact(*_CONTACT.unpack_from(payload, _INPUT_HEAD.size + i * _CONTACT.size)) for i in range(count)
        )
        return Input(device, contacts)
    ```

- [ ] **Step 5 : Mettre à jour `protocol/PROTOCOL.md`**
  - remplacer la ligne du tableau « Tablette → PC » `| 0x85 | INPUT | réservé (phase 4) |` par :
    `| 0x85 | INPUT | device u8 (1 tactile, 2 stylet), count u8 (≤ 10 tactile, ≤ 1 stylet), puis count × contact de 10 octets (voir ci-dessous) |`
  - ajouter avant `## Horloges` :

    ````markdown
    ## INPUT (phase 4)

    Contact (10 octets) : `id u8, flags u8, x u16, y u16, pressure u16, tilt_x i8, tilt_y i8`.

    - `id` : emplacement stable 0..9 (tactile) ; 0 (stylet).
    - `flags` : bit0 CONTACT (posé), bit1 IN_RANGE (détecté, y compris en survol), bit2 BARREL (bouton du stylet), bit3 CANCELED (geste annulé, aucun clic). Les autres bits valent 0 et sont ignorés.
    - `x`, `y` : 0..65535 sur l'image vidéo. `pressure` : 0..1024 (stylet). `tilt_x`, `tilt_y` : degrés −90..90 (stylet).

    Chaque message est l'**état complet** d'un périphérique. Un contact absent de la trame suivante est levé, et `count = 0` signifie que tout est levé ou hors de portée. Un contact CANCELED n'apparaît que dans une trame.
    ````

- [ ] **Step 6 : Lancer toute la suite Python**

`cd host-prototype; py -m unittest discover -v; cd ..` → `Ran 34 tests` … `OK`.

- [ ] **Step 7 : Commit**

```powershell
git add protocol host-prototype/protocol.py host-prototype/tests/test_protocol.py
git commit -m "feat(protocol): define INPUT message with shared vectors and Python decoder"
```

---

### Task 2 : Encodage INPUT côté Kotlin

**Files:**
- Modify: `android/app/src/main/java/dev/tabx/client/protocol/Messages.kt`
- Modify: `android/app/src/main/java/dev/tabx/client/protocol/FrameWriter.kt`
- Modify: `android/app/src/test/java/dev/tabx/client/protocol/ProtocolVectorsTest.kt`

- [ ] **Step 1 : Test qui échoue.** Dans `ProtocolVectorsTest.encodesTabletToPcVectors`, ajouter une branche au `when` juste avant `else -> error(...)` :

```kotlin
                "INPUT" -> {
                    val contacts = f.getJSONArray("contacts")
                    TabletMessage.Input(
                        f.getInt("device"),
                        (0 until contacts.length()).map { j ->
                            val c = contacts.getJSONObject(j)
                            InputContact(
                                c.getInt("id"), c.getInt("flags"), c.getInt("x"), c.getInt("y"),
                                c.getInt("pressure"), c.getInt("tilt_x"), c.getInt("tilt_y"),
                            )
                        },
                    )
                }
```

- [ ] **Step 2 : Lancer, vérifier l'échec** : `:app:testDebugUnitTest` → `Unresolved reference 'InputContact'` / `'Input'`.

- [ ] **Step 3 : `Messages.kt`**
  - dans `object Protocol`, ajouter après `const val TYPE_STATS = 0x84` :
    ```kotlin
        const val TYPE_INPUT = 0x85

        const val DEVICE_TOUCH = 1
        const val DEVICE_PEN = 2
        const val MAX_TOUCH_CONTACTS = 10

        // bits de InputContact.flags
        const val CONTACT_CONTACT = 0x01
        const val CONTACT_IN_RANGE = 0x02
        const val CONTACT_BARREL = 0x04
        const val CONTACT_CANCELED = 0x08
    ```
  - ajouter après la classe `ProtocolException` :
    ```kotlin
    /** One finger or the pen in an INPUT frame. Coordinates 0..65535 over the video image (spec phase 4 §3). */
    data class InputContact(
        val id: Int,
        val flags: Int,
        val x: Int,
        val y: Int,
        val pressure: Int = 0,
        val tiltX: Int = 0,
        val tiltY: Int = 0,
    )
    ```
  - dans `sealed interface TabletMessage`, ajouter après `Stats` :
    ```kotlin
        /** Complete state of one device (touch or pen) right after an event. */
        data class Input(val device: Int, val contacts: List<InputContact>) : TabletMessage
    ```

- [ ] **Step 4 : `FrameWriter.kt`** : dans le `when (message)` de `encode`, ajouter après la branche `is TabletMessage.Stats -> { ... }` :

```kotlin
                is TabletMessage.Input -> {
                    out.writeByte(message.device)
                    out.writeByte(message.contacts.size)
                    for (contact in message.contacts) {
                        out.writeByte(contact.id)
                        out.writeByte(contact.flags)
                        out.writeShort(contact.x)
                        out.writeShort(contact.y)
                        out.writeShort(contact.pressure)
                        out.writeByte(contact.tiltX)
                        out.writeByte(contact.tiltY)
                    }
                    Protocol.TYPE_INPUT
                }
```

- [ ] **Step 5 : Lancer** `:app:testDebugUnitTest` → BUILD SUCCESSFUL, 22 tests. Les 3 nouveaux vecteurs passent dans `encodesTabletToPcVectors`.

- [ ] **Step 6 : Commit** : `git add android/app/src` puis `git commit -m "feat(android): encode INPUT messages"`.

---

### Task 3 : `inputstate.py` (logique pure, TDD)

**Files:**
- Create: `host-prototype/tests/test_inputstate.py`
- Create: `host-prototype/inputstate.py`

- [ ] **Step 1 : Test qui échoue** (`host-prototype/tests/test_inputstate.py`)

```python
import unittest

import inputstate as s
import protocol

RECT = s.Rect(2560, -207, 2880, 1800)
DOWN = protocol.CONTACT_CONTACT | protocol.CONTACT_IN_RANGE
HOVER = protocol.CONTACT_IN_RANGE
F_DOWN = s.POINTER_FLAG_DOWN | s.POINTER_FLAG_INRANGE | s.POINTER_FLAG_INCONTACT
F_MOVE = s.POINTER_FLAG_UPDATE | s.POINTER_FLAG_INRANGE | s.POINTER_FLAG_INCONTACT
PRIMARY = s.POINTER_FLAG_PRIMARY


def c(id_, flags=DOWN, x=0, y=0, pressure=0, tilt_x=0, tilt_y=0):
    return protocol.Contact(id_, flags, x, y, pressure, tilt_x, tilt_y)


def flags_by_id(frame):
    return {a.pointer_id: a.flags for a in frame}


class TouchTest(unittest.TestCase):
    def setUp(self):
        self.touch = s.DeviceState(protocol.DEVICE_TOUCH)

    def test_new_contact_goes_down_as_primary(self):
        (a,) = self.touch.update([c(0)], RECT)
        self.assertEqual(a.flags, F_DOWN | PRIMARY)
        self.assertEqual((a.x, a.y), (2560, -207))

    def test_far_corner_maps_to_last_pixel(self):
        (a,) = self.touch.update([c(0, x=65535, y=65535)], RECT)
        self.assertEqual((a.x, a.y), (2560 + 2879, -207 + 1799))

    def test_held_contact_updates(self):
        self.touch.update([c(0)], RECT)
        (a,) = self.touch.update([c(0, x=100)], RECT)
        self.assertEqual(a.flags, F_MOVE | PRIMARY)

    def test_missing_contact_goes_up(self):
        self.touch.update([c(0)], RECT)
        (a,) = self.touch.update([], RECT)
        self.assertEqual(a.flags, s.POINTER_FLAG_UP | PRIMARY)
        self.assertEqual(self.touch.update([], RECT), [])

    def test_primary_is_the_oldest_contact(self):
        self.touch.update([c(0)], RECT)
        both = flags_by_id(self.touch.update([c(0), c(1)], RECT))
        self.assertTrue(both[0] & PRIMARY)
        self.assertFalse(both[1] & PRIMARY)
        lifted = flags_by_id(self.touch.update([c(1)], RECT))
        self.assertEqual(lifted[0], s.POINTER_FLAG_UP | PRIMARY)
        self.assertTrue(flags_by_id(self.touch.update([c(1)], RECT))[1] & PRIMARY)

    def test_canceled_contact(self):
        self.touch.update([c(0)], RECT)
        (a,) = self.touch.update([c(0, DOWN | protocol.CONTACT_CANCELED)], RECT)
        self.assertEqual(a.flags, s.POINTER_FLAG_UP | s.POINTER_FLAG_CANCELED | PRIMARY)
        self.assertEqual(self.touch.update([], RECT), [])

    def test_canceled_unknown_contact_is_ignored(self):
        self.assertEqual(self.touch.update([c(3, DOWN | protocol.CONTACT_CANCELED)], RECT), [])

    def test_refresh_resends_held_contacts(self):
        self.assertEqual(self.touch.refresh(), [])
        self.touch.update([c(0, x=10)], RECT)
        (a,) = self.touch.refresh()
        self.assertEqual(a.flags, F_MOVE | PRIMARY)

    def test_cancel_all(self):
        self.touch.update([c(0), c(1)], RECT)
        frame = flags_by_id(self.touch.cancel_all())
        self.assertEqual(frame[0], s.POINTER_FLAG_UP | s.POINTER_FLAG_CANCELED | PRIMARY)
        self.assertEqual(frame[1], s.POINTER_FLAG_UP | s.POINTER_FLAG_CANCELED)
        self.assertEqual(self.touch.update([], RECT), [])

    def test_finger_has_no_pen_data(self):
        (a,) = self.touch.update([c(0, pressure=500, tilt_x=10)], RECT)
        self.assertEqual((a.pressure, a.tilt_x, a.pen_mask), (0, 0, 0))


class PenTest(unittest.TestCase):
    def setUp(self):
        self.pen = s.DeviceState(protocol.DEVICE_PEN)

    def test_hover(self):
        (a,) = self.pen.update([c(0, HOVER)], RECT)
        self.assertEqual(a.flags, s.POINTER_FLAG_UPDATE | s.POINTER_FLAG_INRANGE | PRIMARY)
        self.assertEqual(a.pen_mask, s.PEN_MASK_PRESSURE | s.PEN_MASK_TILT_X | s.PEN_MASK_TILT_Y)

    def test_down_with_pressure_tilt_and_barrel(self):
        self.pen.update([c(0, HOVER)], RECT)
        (a,) = self.pen.update([c(0, DOWN | protocol.CONTACT_BARREL, pressure=512, tilt_x=-30, tilt_y=45)], RECT)
        self.assertEqual(a.flags, F_DOWN | PRIMARY)
        self.assertEqual((a.pressure, a.tilt_x, a.tilt_y, a.pen_flags), (512, -30, 45, s.PEN_FLAG_BARREL))

    def test_lift_while_still_in_range(self):
        self.pen.update([c(0)], RECT)
        (a,) = self.pen.update([c(0, HOVER)], RECT)
        self.assertEqual(a.flags, s.POINTER_FLAG_UP | s.POINTER_FLAG_INRANGE | PRIMARY)

    def test_leaving_range(self):
        self.pen.update([c(0, HOVER)], RECT)
        (a,) = self.pen.update([], RECT)
        self.assertEqual(a.flags, s.POINTER_FLAG_UPDATE | PRIMARY)

    def test_cancel_all_while_hovering_just_leaves(self):
        self.pen.update([c(0, HOVER)], RECT)
        (a,) = self.pen.cancel_all()
        self.assertEqual(a.flags, s.POINTER_FLAG_UPDATE | PRIMARY)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2 : Lancer, vérifier l'échec** : `cd host-prototype; py -m unittest tests.test_inputstate -v; cd ..` → `ModuleNotFoundError: No module named 'inputstate'`.

- [ ] **Step 3 : Implémenter `host-prototype/inputstate.py`**

```python
"""TABX INPUT frames -> Windows synthetic pointer actions (spec phase 4 §5.2). Pure logic, no Win32."""
from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Iterable

import protocol

# POINTER_FLAG_* (winuser.h)
POINTER_FLAG_INRANGE = 0x00000002
POINTER_FLAG_INCONTACT = 0x00000004
POINTER_FLAG_PRIMARY = 0x00002000
POINTER_FLAG_CANCELED = 0x00008000
POINTER_FLAG_DOWN = 0x00010000
POINTER_FLAG_UPDATE = 0x00020000
POINTER_FLAG_UP = 0x00040000
# PEN_FLAG_* / PEN_MASK_* (winuser.h)
PEN_FLAG_BARREL = 0x00000001
PEN_MASK_PRESSURE = 0x00000001
PEN_MASK_TILT_X = 0x00000004
PEN_MASK_TILT_Y = 0x00000008


@dataclass(frozen=True)
class Rect:
    """Target screen in physical desktop pixels."""
    left: int
    top: int
    width: int
    height: int


@dataclass(frozen=True)
class PointerAction:
    """One pointer of one injection frame."""
    pointer_id: int
    flags: int
    x: int
    y: int
    pressure: int = 0
    tilt_x: int = 0
    tilt_y: int = 0
    pen_flags: int = 0
    pen_mask: int = 0


def to_pixels(value: int, origin: int, size: int) -> int:
    return origin + round(value * (size - 1) / 65535)


class DeviceState:
    """Follows one synthetic device (touch or pen) across INPUT frames and yields complete injection frames."""

    def __init__(self, device: int) -> None:
        self._pen = device == protocol.DEVICE_PEN
        self._active: dict[int, PointerAction] = {}  # contacts posés, ou stylet en portée
        self._down_order: list[int] = []  # doigts posés, du plus ancien au plus récent

    def update(self, contacts: Iterable[protocol.Contact], rect: Rect) -> list[PointerAction]:
        primary_candidates = list(self._down_order)
        frame: list[PointerAction] = []
        seen: set[int] = set()
        for contact in contacts:
            seen.add(contact.id)
            previous = self._active.get(contact.id)
            was_down = previous is not None and bool(previous.flags & POINTER_FLAG_INCONTACT)
            action = self._action(contact, rect)
            if contact.flags & protocol.CONTACT_CANCELED:
                if previous is not None:
                    frame.append(replace(action, flags=POINTER_FLAG_UP | POINTER_FLAG_CANCELED))
                self._forget(contact.id)
                continue
            down = bool(contact.flags & protocol.CONTACT_CONTACT)
            in_range = down or bool(contact.flags & protocol.CONTACT_IN_RANGE)
            if down and not was_down:
                flags = POINTER_FLAG_DOWN | POINTER_FLAG_INRANGE | POINTER_FLAG_INCONTACT
                self._down_order.append(contact.id)
                primary_candidates.append(contact.id)
            elif down:
                flags = POINTER_FLAG_UPDATE | POINTER_FLAG_INRANGE | POINTER_FLAG_INCONTACT
            elif was_down:
                flags = POINTER_FLAG_UP | (POINTER_FLAG_INRANGE if in_range else 0)
                self._remove_from_order(contact.id)
            elif previous is None and not in_range:
                continue  # ni posé ni en portée, et inconnu : rien à injecter
            else:
                flags = POINTER_FLAG_UPDATE | (POINTER_FLAG_INRANGE if in_range else 0)
            action = replace(action, flags=flags)
            frame.append(action)
            if in_range:
                self._active[contact.id] = action
            else:
                self._forget(contact.id)
        for pointer_id in [p for p in self._active if p not in seen]:
            previous = self._active[pointer_id]
            flags = POINTER_FLAG_UP if previous.flags & POINTER_FLAG_INCONTACT else POINTER_FLAG_UPDATE
            frame.append(replace(previous, flags=flags, pressure=0))
            self._forget(pointer_id)
        return self._with_primary(frame, primary_candidates)

    def refresh(self) -> list[PointerAction]:
        """Re-sends held contacts unchanged (keep-alive while nothing moves). Empty if nothing is in contact."""
        if not any(a.flags & POINTER_FLAG_INCONTACT for a in self._active.values()):
            return []
        frame = [
            replace(a, flags=POINTER_FLAG_UPDATE | POINTER_FLAG_INRANGE | (a.flags & POINTER_FLAG_INCONTACT))
            for a in self._active.values()
        ]
        return self._with_primary(frame, list(self._down_order))

    def cancel_all(self) -> list[PointerAction]:
        """Ends every active pointer without a click (session end)."""
        frame = [
            replace(a, pressure=0, flags=(POINTER_FLAG_UP | POINTER_FLAG_CANCELED)
                    if a.flags & POINTER_FLAG_INCONTACT else POINTER_FLAG_UPDATE)
            for a in self._active.values()
        ]
        frame = self._with_primary(frame, list(self._down_order))
        self._active.clear()
        self._down_order.clear()
        return frame

    def _action(self, contact: protocol.Contact, rect: Rect) -> PointerAction:
        x = to_pixels(contact.x, rect.left, rect.width)
        y = to_pixels(contact.y, rect.top, rect.height)
        if not self._pen:
            return PointerAction(contact.id, 0, x, y)
        return PointerAction(
            contact.id, 0, x, y,
            pressure=contact.pressure, tilt_x=contact.tilt_x, tilt_y=contact.tilt_y,
            pen_flags=PEN_FLAG_BARREL if contact.flags & protocol.CONTACT_BARREL else 0,
            pen_mask=PEN_MASK_PRESSURE | PEN_MASK_TILT_X | PEN_MASK_TILT_Y,
        )

    def _with_primary(self, frame: list[PointerAction], candidates: list[int]) -> list[PointerAction]:
        if self._pen:
            return [replace(a, flags=a.flags | POINTER_FLAG_PRIMARY) for a in frame]
        primary = candidates[0] if candidates else None
        return [replace(a, flags=a.flags | POINTER_FLAG_PRIMARY) if a.pointer_id == primary else a for a in frame]

    def _forget(self, pointer_id: int) -> None:
        self._active.pop(pointer_id, None)
        self._remove_from_order(pointer_id)

    def _remove_from_order(self, pointer_id: int) -> None:
        if pointer_id in self._down_order:
            self._down_order.remove(pointer_id)
```

- [ ] **Step 4 : Lancer** : `cd host-prototype; py -m unittest discover -v; cd ..` → `Ran 49 tests` … `OK`.

- [ ] **Step 5 : Commit** : `git add host-prototype/inputstate.py host-prototype/tests/test_inputstate.py` puis `git commit -m "feat(relay): map INPUT frames to Windows pointer actions"`.

---

### Task 4 : `injector.py` (Win32 via ctypes)

**Files:**
- Create: `host-prototype/tests/test_injector.py`
- Create: `host-prototype/injector.py`

- [ ] **Step 1 : Test qui échoue** (`host-prototype/tests/test_injector.py`). Il vérifie la disposition mémoire des structures Win32 en Python 64 bits (valeurs de `winuser.h`) et le choix du moniteur :

```python
import ctypes
import unittest

import injector
from inputstate import Rect


class LayoutTest(unittest.TestCase):
    def test_struct_sizes_match_winuser_h_on_x64(self):
        self.assertEqual(ctypes.sizeof(ctypes.c_void_p), 8, "Python 64 bits requis")
        self.assertEqual(ctypes.sizeof(injector.POINTER_INFO), 96)
        self.assertEqual(ctypes.sizeof(injector.POINTER_TOUCH_INFO), 144)
        self.assertEqual(ctypes.sizeof(injector.POINTER_PEN_INFO), 120)
        self.assertEqual(ctypes.sizeof(injector.POINTER_TYPE_INFO), 152)


class FindTargetTest(unittest.TestCase):
    MONITORS = [
        (Rect(0, 0, 2560, 1600), True, r"\\.\DISPLAY1"),
        (Rect(2560, -207, 2880, 1800), False, r"\\.\DISPLAY13"),
    ]

    def test_unique_match(self):
        self.assertEqual(injector.find_target(2880, 1800, self.MONITORS), (Rect(2560, -207, 2880, 1800), ""))

    def test_no_match(self):
        rect, problem = injector.find_target(1920, 1080, self.MONITORS)
        self.assertIsNone(rect)
        self.assertIn("1920x1080", problem)

    def test_ambiguous_match(self):
        rect, problem = injector.find_target(2880, 1800, self.MONITORS + [(Rect(-2880, 0, 2880, 1800), False, "X")])
        self.assertIsNone(rect)
        self.assertIn("2 écrans", problem)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2 : Lancer, vérifier l'échec** : `cd host-prototype; py -m unittest tests.test_injector -v; cd ..` → `ModuleNotFoundError: No module named 'injector'`.

- [ ] **Step 3 : Implémenter `host-prototype/injector.py`**

```python
"""Windows pointer injection for TABX INPUT frames (spec phase 4 §5.3): synthetic touch and pen devices.

`py injector.py --selftest` checks the Win32 layer without a tablet: the pen hovers in a circle (never clicks).
"""
from __future__ import annotations

import ctypes
import math
import sys
import threading
import time
from ctypes import wintypes
from typing import Callable

import inputstate
import protocol

PT_TOUCH = 2
PT_PEN = 3
POINTER_FEEDBACK_DEFAULT = 1
DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2 = -4
MONITORINFOF_PRIMARY = 1
ERROR_ACCESS_DENIED = 5
KEEPALIVE_S = 0.1

Log = Callable[[str], None]
Monitor = tuple[inputstate.Rect, bool, str]


class POINTER_INFO(ctypes.Structure):
    _fields_ = [
        ("pointerType", wintypes.DWORD),
        ("pointerId", ctypes.c_uint32),
        ("frameId", ctypes.c_uint32),
        ("pointerFlags", ctypes.c_uint32),
        ("sourceDevice", wintypes.HANDLE),
        ("hwndTarget", wintypes.HWND),
        ("ptPixelLocation", wintypes.POINT),
        ("ptHimetricLocation", wintypes.POINT),
        ("ptPixelLocationRaw", wintypes.POINT),
        ("ptHimetricLocationRaw", wintypes.POINT),
        ("dwTime", wintypes.DWORD),
        ("historyCount", ctypes.c_uint32),
        ("InputData", ctypes.c_int32),
        ("dwKeyStates", wintypes.DWORD),
        ("PerformanceCount", ctypes.c_uint64),
        ("ButtonChangeType", ctypes.c_int),
    ]


class POINTER_TOUCH_INFO(ctypes.Structure):
    _fields_ = [
        ("pointerInfo", POINTER_INFO),
        ("touchFlags", ctypes.c_uint32),
        ("touchMask", ctypes.c_uint32),
        ("rcContact", wintypes.RECT),
        ("rcContactRaw", wintypes.RECT),
        ("orientation", ctypes.c_uint32),
        ("pressure", ctypes.c_uint32),
    ]


class POINTER_PEN_INFO(ctypes.Structure):
    _fields_ = [
        ("pointerInfo", POINTER_INFO),
        ("penFlags", ctypes.c_uint32),
        ("penMask", ctypes.c_uint32),
        ("pressure", ctypes.c_uint32),
        ("rotation", ctypes.c_uint32),
        ("tiltX", ctypes.c_int32),
        ("tiltY", ctypes.c_int32),
    ]


class _POINTER_INFO_UNION(ctypes.Union):
    _fields_ = [("touchInfo", POINTER_TOUCH_INFO), ("penInfo", POINTER_PEN_INFO)]


class POINTER_TYPE_INFO(ctypes.Structure):
    _anonymous_ = ("u",)
    _fields_ = [("type", wintypes.DWORD), ("u", _POINTER_INFO_UNION)]


class MONITORINFOEXW(ctypes.Structure):
    _fields_ = [
        ("cbSize", wintypes.DWORD),
        ("rcMonitor", wintypes.RECT),
        ("rcWork", wintypes.RECT),
        ("dwFlags", wintypes.DWORD),
        ("szDevice", wintypes.WCHAR * 32),
    ]


_MONITORENUMPROC = ctypes.WINFUNCTYPE(
    wintypes.BOOL, wintypes.HMONITOR, wintypes.HDC, ctypes.POINTER(wintypes.RECT), wintypes.LPARAM
)

_user32 = ctypes.WinDLL("user32", use_last_error=True)
_user32.EnumDisplayMonitors.argtypes = [wintypes.HDC, ctypes.c_void_p, _MONITORENUMPROC, wintypes.LPARAM]
_user32.EnumDisplayMonitors.restype = wintypes.BOOL
_user32.GetMonitorInfoW.argtypes = [wintypes.HMONITOR, ctypes.POINTER(MONITORINFOEXW)]
_user32.GetMonitorInfoW.restype = wintypes.BOOL

try:  # API Synthetic Pointer : Windows 10 1809+
    _create_device = _user32.CreateSyntheticPointerDevice
    _create_device.argtypes = [wintypes.DWORD, wintypes.ULONG, wintypes.DWORD]
    _create_device.restype = wintypes.HANDLE
    _inject = _user32.InjectSyntheticPointerInput
    _inject.argtypes = [wintypes.HANDLE, ctypes.POINTER(POINTER_TYPE_INFO), ctypes.c_uint32]
    _inject.restype = wintypes.BOOL
    _destroy_device = _user32.DestroySyntheticPointerDevice
    _destroy_device.argtypes = [wintypes.HANDLE]
    _destroy_device.restype = None
    AVAILABLE = True
except AttributeError:
    AVAILABLE = False


def enable_dpi_awareness() -> None:
    """Physical pixels everywhere (the virtual screen is scaled 200 %). Call before any monitor query."""
    try:
        set_context = _user32.SetProcessDpiAwarenessContext
    except AttributeError:
        return
    set_context.argtypes = [ctypes.c_void_p]
    set_context.restype = wintypes.BOOL
    set_context(ctypes.c_void_p(DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2))


def monitors() -> list[Monitor]:
    """(rect in physical pixels, is_primary, device name) for every active monitor."""
    found: list[Monitor] = []

    def callback(hmonitor, _hdc, _rect, _data):
        info = MONITORINFOEXW()
        info.cbSize = ctypes.sizeof(MONITORINFOEXW)
        if _user32.GetMonitorInfoW(hmonitor, ctypes.byref(info)):
            r = info.rcMonitor
            rect = inputstate.Rect(r.left, r.top, r.right - r.left, r.bottom - r.top)
            found.append((rect, bool(info.dwFlags & MONITORINFOF_PRIMARY), info.szDevice))
        return True

    _user32.EnumDisplayMonitors(None, None, _MONITORENUMPROC(callback), 0)
    return found


def find_target(width: int, height: int, available: list[Monitor] | None = None) -> tuple[inputstate.Rect | None, str]:
    """The only monitor whose size equals the stream's, or (None, reason)."""
    candidates = monitors() if available is None else available
    matches = [rect for rect, _primary, _name in candidates if (rect.width, rect.height) == (width, height)]
    if len(matches) == 1:
        return matches[0], ""
    if not matches:
        return None, f"aucun écran Windows en {width}x{height}"
    return None, f"{len(matches)} écrans en {width}x{height} : impossible de savoir lequel est la tablette"


def _to_native(device: int, action: inputstate.PointerAction) -> POINTER_TYPE_INFO:
    info = POINTER_TYPE_INFO()
    if device == protocol.DEVICE_TOUCH:
        info.type = PT_TOUCH
        pointer = info.touchInfo.pointerInfo
        pointer.pointerType = PT_TOUCH
    else:
        info.type = PT_PEN
        pen = info.penInfo
        pen.penFlags = action.pen_flags
        pen.penMask = action.pen_mask
        pen.pressure = action.pressure
        pen.tiltX = action.tilt_x
        pen.tiltY = action.tilt_y
        pointer = pen.pointerInfo
        pointer.pointerType = PT_PEN
    pointer.pointerId = action.pointer_id
    pointer.pointerFlags = action.flags
    pointer.ptPixelLocation.x = action.x
    pointer.ptPixelLocation.y = action.y
    return info


class Injector:
    """Injects TABX INPUT frames into one screen. Thread-safe; turns itself off (one message) on fatal errors."""

    def __init__(self, rect: inputstate.Rect, log: Log = print) -> None:
        self._rect = rect
        self._log = log
        self._lock = threading.Lock()
        self._states = {
            protocol.DEVICE_TOUCH: inputstate.DeviceState(protocol.DEVICE_TOUCH),
            protocol.DEVICE_PEN: inputstate.DeviceState(protocol.DEVICE_PEN),
        }
        self._handles: dict[int, int] = {}
        self._disabled = False
        self._denied_reported = False
        self._last_inject = time.monotonic()
        self._stop = threading.Event()
        if not AVAILABLE:
            self._disable("Windows 10 1809 ou plus récent requis (API Synthetic Pointer absente)")
        threading.Thread(target=self._keepalive, name="input-keepalive", daemon=True).start()

    @property
    def enabled(self) -> bool:
        return not self._disabled

    def handle(self, message: protocol.Input) -> None:
        with self._lock:
            if self._disabled:
                return
            self._inject_frame(message.device, self._states[message.device].update(message.contacts, self._rect))

    def close(self) -> None:
        """Cancels every active pointer (no stuck touch) and destroys the synthetic devices."""
        self._stop.set()
        with self._lock:
            if not self._disabled:
                for device, state in self._states.items():
                    self._inject_frame(device, state.cancel_all())
            for handle in self._handles.values():
                _destroy_device(handle)
            self._handles.clear()
            self._disabled = True

    def _keepalive(self) -> None:
        # Un contact immobile n'envoie plus de trame : on réinjecte l'état pour que Windows ne l'abandonne pas.
        while not self._stop.wait(KEEPALIVE_S):
            with self._lock:
                if self._disabled or time.monotonic() - self._last_inject < KEEPALIVE_S:
                    continue
                for device, state in self._states.items():
                    self._inject_frame(device, state.refresh())

    def _inject_frame(self, device: int, frame: list[inputstate.PointerAction]) -> None:
        if not frame or self._disabled:
            return
        handle = self._device_handle(device)
        if handle is None:
            return
        infos = (POINTER_TYPE_INFO * len(frame))(*(_to_native(device, action) for action in frame))
        self._last_inject = time.monotonic()
        if _inject(handle, infos, len(frame)):
            return
        error = ctypes.get_last_error()
        if error == ERROR_ACCESS_DENIED:
            if not self._denied_reported:
                self._log("Tactile refusé par Windows sur cette fenêtre (programme administrateur ?) : "
                          "lance le relais en administrateur pour la piloter.")
                self._denied_reported = True
        else:
            self._disable(f"InjectSyntheticPointerInput a échoué (erreur Windows {error})")

    def _device_handle(self, device: int) -> int | None:
        handle = self._handles.get(device)
        if handle:
            return handle
        if device == protocol.DEVICE_TOUCH:
            handle = _create_device(PT_TOUCH, protocol.MAX_TOUCH_CONTACTS, POINTER_FEEDBACK_DEFAULT)
        else:
            handle = _create_device(PT_PEN, 1, POINTER_FEEDBACK_DEFAULT)
        if not handle:
            self._disable(f"CreateSyntheticPointerDevice a échoué (erreur Windows {ctypes.get_last_error()})")
            return None
        self._handles[device] = handle
        return handle

    def _disable(self, reason: str) -> None:
        self._disabled = True
        self._log(f"Tactile désactivé : {reason}. La vidéo continue.")


def create_for_stream(width: int, height: int, log: Log = print) -> Injector | None:
    """Injector targeting the screen that has the stream's size, or None (with a message) if there isn't exactly one."""
    rect, problem = find_target(width, height)
    if rect is None:
        log(f"Tactile désactivé : {problem}. La vidéo continue.")
        return None
    log(f"Tactile actif sur l'écran Windows {rect.width}x{rect.height} en ({rect.left}, {rect.top})")
    return Injector(rect, log)


def selftest() -> None:
    """Hovers the pen in a circle at the centre of the primary screen for 2 s. Never touches, so never clicks."""
    enable_dpi_awareness()
    primary = next((rect for rect, is_primary, _name in monitors() if is_primary), None)
    if primary is None:
        sys.exit("Autotest : aucun écran principal trouvé")
    pen = Injector(primary)
    for step in range(61):
        angle = 2 * math.pi * step / 60
        x = round(32768 + 8000 * math.cos(angle))
        y = round(32768 + 8000 * math.sin(angle))
        pen.handle(protocol.Input(protocol.DEVICE_PEN, (protocol.Contact(0, protocol.CONTACT_IN_RANGE, x, y, 0, 0, 0),)))
        time.sleep(2 / 60)
    pen.handle(protocol.Input(protocol.DEVICE_PEN, ()))
    ok = pen.enabled
    pen.close()
    if not ok:
        sys.exit("Autotest en échec : voir le message ci-dessus.")
    print("Autotest terminé : le curseur du stylet a dû décrire un cercle au centre de l'écran principal, sans cliquer.")


if __name__ == "__main__":
    if sys.argv[1:] == ["--selftest"]:
        selftest()
    else:
        sys.exit("Usage : py injector.py --selftest")
```

- [ ] **Step 4 : Lancer les tests** : `cd host-prototype; py -m unittest discover -v; cd ..` → `Ran 53 tests` … `OK`.

- [ ] **Step 5 : Autotest réel sur le PC** (survol uniquement, aucun clic possible) :

```powershell
cd host-prototype; py injector.py --selftest; cd ..
```

Attendu : le message « Autotest terminé… », code de sortie 0. Le curseur du stylet décrit un cercle au centre de l'écran principal. En cas d'échec, noter le message exact (numéro d'erreur Windows) et le rapporter, sans modifier les structures à l'aveugle.

- [ ] **Step 6 : Commit** : `git add host-prototype/injector.py host-prototype/tests/test_injector.py` puis `git commit -m "feat(relay): inject touch and pen through Windows synthetic pointers"`.

---

### Task 5 : Brancher l'injecteur dans le relais

**Files:**
- Modify: `host-prototype/relay.py`

- [ ] **Step 1 : Import** : ajouter `import injector` à côté de `import annexb` et `import protocol`.

- [ ] **Step 2 : `stream()` signale la taille du flux.** Changer la signature :

```python
def stream(source: BinaryIO, send: Callable[[bytes], None], fps: int, stop: threading.Event,
           on_size: Callable[[int, int], None]) -> None:
```

Dans le bloc `if new_size != size:`, appeler `on_size(size[0], size[1])` juste après `size = new_size` (avant l'envoi du CONFIG).

- [ ] **Step 3 : `run_session` crée un injecteur par taille de flux et route les `INPUT`.**
  - Juste après la ligne `closing = threading.Event()  # …` :

    ```python
        pointer_injector: injector.Injector | None = None
        injector_lock = threading.Lock()

        def on_stream_size(width: int, height: int) -> None:
            nonlocal pointer_injector
            with injector_lock:
                if pointer_injector is not None:
                    pointer_injector.close()
                pointer_injector = injector.create_for_stream(width, height)
    ```
  - Dans `read_tablet`, ajouter une branche après celle de `protocol.KeyframeRequest` :

    ```python
                    elif isinstance(message, protocol.Input):
                        with injector_lock:
                            target = pointer_injector
                        if target is not None:
                            target.handle(message)
    ```
  - Remplacer l'appel `stream(ffmpeg.stdout, send, args.fps, disconnected)` par `stream(ffmpeg.stdout, send, args.fps, disconnected, on_stream_size)`.
  - Dans le bloc `finally:` de `run_session`, ajouter en première ligne :

    ```python
            with injector_lock:
                if pointer_injector is not None:
                    pointer_injector.close()  # lève tous les contacts : rien ne reste « posé » dans Windows
                    pointer_injector = None
    ```

- [ ] **Step 4 : DPI au démarrage.** Dans `main()`, juste après `sys.stdout.reconfigure(...)`, ajouter `injector.enable_dpi_awareness()  # coordonnées en pixels physiques (écran virtuel à 200 %)`.

- [ ] **Step 5 : Vérifier**
  - `py -m py_compile host-prototype/relay.py`
  - `cd host-prototype; py -m unittest discover; cd ..` → 53 OK
  - `cd host-prototype; py relay.py --list-outputs; cd ..` → la liste habituelle, inchangée. L'ajustement DPI ne change pas les tailles de capture.

- [ ] **Step 6 : Commit** : `git add host-prototype/relay.py` puis `git commit -m "feat(relay): route INPUT messages to the pointer injector"`.

---

### Task 6 : `InputMapper` (logique pure, TDD)

**Files:**
- Create: `android/app/src/test/java/dev/tabx/client/input/InputMapperTest.kt`
- Create: `android/app/src/main/java/dev/tabx/client/input/InputMapper.kt`

- [ ] **Step 1 : Test qui échoue**

```kotlin
package dev.tabx.client.input

import dev.tabx.client.protocol.InputContact
import dev.tabx.client.protocol.Protocol
import dev.tabx.client.protocol.TabletMessage
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

class InputMapperTest {
    private val w = 1000f
    private val h = 500f
    private val down = Protocol.CONTACT_CONTACT or Protocol.CONTACT_IN_RANGE
    private val canceled = down or Protocol.CONTACT_CANCELED

    private fun mapper() = InputMapper(hudSlopPx = 50f)
    private fun finger(id: Int, x: Float = 100f, y: Float = 100f) = PointerSample(id, Tool.FINGER, x, y)
    private fun touch(vararg contacts: InputContact) = TabletMessage.Input(Protocol.DEVICE_TOUCH, contacts.toList())
    private fun four() = listOf(finger(0), finger(1), finger(2), finger(3))

    @Test
    fun normalizesAndClamps() {
        val out = mapper().process(listOf(finger(0, 500f, 250f), finger(1, -10f, 900f)), w, h, 0)
        assertEquals(listOf(touch(InputContact(0, down, 32768, 32768), InputContact(1, down, 0, 65535))), out.messages)
    }

    @Test
    fun fingerSlotsAreStableAndReused() {
        val m = mapper()
        m.process(listOf(finger(5), finger(7)), w, h, 0)
        assertEquals(listOf(1), m.process(listOf(finger(7)), w, h, 10).messages.single().contacts.map { it.id })
        assertEquals(listOf(0, 1), m.process(listOf(finger(7), finger(9)), w, h, 20).messages.single().contacts.map { it.id })
    }

    @Test
    fun liftingAllFingersSendsEmptyFrame() {
        val m = mapper()
        m.process(listOf(finger(0)), w, h, 0)
        assertEquals(listOf(touch()), m.process(emptyList(), w, h, 10).messages)
    }

    @Test
    fun identicalSnapshotIsNotResent() {
        val m = mapper()
        m.process(listOf(finger(0)), w, h, 0)
        assertTrue(m.process(listOf(finger(0)), w, h, 10).messages.isEmpty())
    }

    @Test
    fun fourthFingerCancelsAndSuppressesUntilAllUp() {
        val m = mapper()
        m.process(listOf(finger(0), finger(1), finger(2)), w, h, 0)
        val cancel = m.process(four(), w, h, 10).messages.single()
        assertEquals(3, cancel.contacts.size)
        assertTrue(cancel.contacts.all { it.flags == canceled })
        assertTrue(m.process(listOf(finger(0, 300f), finger(1)), w, h, 20).messages.isEmpty())
        assertTrue(m.process(emptyList(), w, h, 30).messages.isEmpty())
        assertEquals(1, m.process(listOf(finger(4)), w, h, 40).messages.single().contacts.size)
    }

    @Test
    fun fourFingerHoldTogglesHudOnce() {
        val m = mapper()
        assertFalse(m.process(four(), w, h, 1_000).toggleHud)
        assertEquals(3_000L, m.hudDeadlineMs)
        assertFalse(m.tick(2_999))
        assertTrue(m.tick(3_000))
        assertFalse(m.tick(4_000))
        assertNull(m.hudDeadlineMs)
    }

    @Test
    fun movingAFingerCancelsTheHudGesture() {
        val m = mapper()
        m.process(four(), w, h, 0)
        m.process(listOf(finger(0, 200f), finger(1), finger(2), finger(3)), w, h, 500)
        assertFalse(m.tick(2_000))
    }

    @Test
    fun liftingAFingerCancelsTheHudGesture() {
        val m = mapper()
        m.process(four(), w, h, 0)
        m.process(listOf(finger(0), finger(1), finger(2)), w, h, 500)
        assertFalse(m.tick(2_000))
    }

    @Test
    fun penInRangeCancelsAndIgnoresFingers() {
        val m = mapper()
        m.process(listOf(finger(0)), w, h, 0)
        val pen = PointerSample(0, Tool.PEN, 500f, 250f, inContact = false)
        val out = m.process(listOf(finger(0), pen), w, h, 10).messages
        assertEquals(Protocol.DEVICE_PEN, out[0].device)
        assertEquals(touch(InputContact(0, canceled, 6554, 13107)), out[1])
        assertTrue(m.process(listOf(finger(0, 400f), pen), w, h, 20).messages.isEmpty())
        // le stylet s'éloigne mais la paume reste posée : toujours ignorée
        assertEquals(
            listOf(TabletMessage.Input(Protocol.DEVICE_PEN, emptyList())),
            m.process(listOf(finger(0, 400f)), w, h, 30).messages,
        )
    }

    @Test
    fun penContactConversion() {
        val pen = PointerSample(
            pointerId = 3, tool = Tool.PEN, x = 0f, y = 500f, pressure = 0.5f,
            tiltRad = (Math.PI / 4).toFloat(), orientationRad = (Math.PI / 2).toFloat(), barrel = true,
        )
        val contact = mapper().process(listOf(pen), w, h, 0).messages.single().contacts.single()
        assertEquals(InputContact(0, down or Protocol.CONTACT_BARREL, 0, 65535, 512, 45, 0), contact)
    }

    @Test
    fun hoveringPenHasNoPressure() {
        val pen = PointerSample(0, Tool.PEN, 0f, 0f, pressure = 0.3f, inContact = false)
        val contact = mapper().process(listOf(pen), w, h, 0).messages.single().contacts.single()
        assertEquals(Protocol.CONTACT_IN_RANGE, contact.flags)
        assertEquals(0, contact.pressure)
    }

    @Test
    fun cancelAllCancelsActiveContactsOnce() {
        val m = mapper()
        m.process(listOf(finger(0)), w, h, 0)
        assertEquals(listOf(touch(InputContact(0, canceled, 6554, 13107))), m.cancelAll())
        assertTrue(m.cancelAll().isEmpty())
    }
}
```

- [ ] **Step 2 : Lancer, vérifier l'échec** : `:app:testDebugUnitTest` → `Unresolved reference 'InputMapper'` (et `PointerSample`, `Tool`).

- [ ] **Step 3 : Implémenter `InputMapper.kt`**

```kotlin
package dev.tabx.client.input

import dev.tabx.client.protocol.InputContact
import dev.tabx.client.protocol.Protocol
import dev.tabx.client.protocol.TabletMessage
import kotlin.math.atan
import kotlin.math.cos
import kotlin.math.hypot
import kotlin.math.roundToInt
import kotlin.math.sin
import kotlin.math.tan

enum class Tool { FINGER, PEN }

/** One Android pointer, in video-view pixels. Angles in radians (MotionEvent AXIS_TILT / AXIS_ORIENTATION). */
data class PointerSample(
    val pointerId: Int,
    val tool: Tool,
    val x: Float,
    val y: Float,
    val pressure: Float = 0f,
    val tiltRad: Float = 0f,
    val orientationRad: Float = 0f,
    val barrel: Boolean = false,
    val inContact: Boolean = true,
)

data class MapperOutput(val messages: List<TabletMessage.Input>, val toggleHud: Boolean = false)

/**
 * Android pointer snapshots → TABX INPUT frames (spec phase 4 §4.2): normalisation, stable finger slots,
 * palm rejection while the pen is in range, and the 4-finger long-press that toggles the HUD
 * instead of reaching the PC. Not thread-safe: call from the UI thread.
 */
class InputMapper(private val hudSlopPx: Float, private val hudHoldMs: Long = HUD_HOLD_MS) {
    private val slots = mutableMapOf<Int, Int>()
    private var lastTouch = EMPTY_TOUCH
    private var lastPen = EMPTY_PEN
    private var touchSuppressed = false
    private var hudStartMs: Long? = null
    private var hudOrigins: Map<Int, Pair<Float, Float>> = emptyMap()
    private var hudDisqualified = false
    private var hudFired = false

    /** When the pending 4-finger hold completes; the caller must call [tick] then. */
    val hudDeadlineMs: Long?
        get() = hudStartMs?.takeIf { !hudDisqualified && !hudFired }?.plus(hudHoldMs)

    fun process(samples: List<PointerSample>, width: Float, height: Float, nowMs: Long): MapperOutput {
        val out = mutableListOf<TabletMessage.Input>()
        val pens = samples.filter { it.tool == Tool.PEN }
        val fingers = samples.filter { it.tool == Tool.FINGER }

        emit(TabletMessage.Input(Protocol.DEVICE_PEN, pens.take(1).map { penContact(it, width, height) }), out)

        when {
            fingers.isEmpty() -> {
                emit(EMPTY_TOUCH, out)
                resetGesture()
            }
            pens.isNotEmpty() -> { // paume : le stylet est en portée
                cancelTouches(out)
                touchSuppressed = true
            }
            touchSuppressed || fingers.size >= HUD_FINGERS -> {
                if (!touchSuppressed) {
                    cancelTouches(out)
                    touchSuppressed = true
                }
                trackHud(fingers, nowMs)
            }
            else -> emit(TabletMessage.Input(Protocol.DEVICE_TOUCH, fingerContacts(fingers, width, height)), out)
        }
        return MapperOutput(out, toggleHud = checkHud(nowMs))
    }

    /** Called at [hudDeadlineMs]: true once when the 4-finger hold completes. */
    fun tick(nowMs: Long): Boolean = checkHud(nowMs)

    /** Cancels every transmitted contact (Android ACTION_CANCEL). */
    fun cancelAll(): List<TabletMessage.Input> {
        val out = mutableListOf<TabletMessage.Input>()
        cancelTouches(out)
        if (lastPen.contacts.isNotEmpty()) {
            out += TabletMessage.Input(Protocol.DEVICE_PEN, lastPen.contacts.map { it.copy(flags = it.flags or Protocol.CONTACT_CANCELED) })
        }
        lastPen = EMPTY_PEN
        resetGesture()
        return out
    }

    /** Forgets everything (new session: the PC starts from scratch). */
    fun reset() {
        lastTouch = EMPTY_TOUCH
        lastPen = EMPTY_PEN
        resetGesture()
    }

    private fun emit(frame: TabletMessage.Input, out: MutableList<TabletMessage.Input>) {
        val last = if (frame.device == Protocol.DEVICE_PEN) lastPen else lastTouch
        if (frame == last) return
        out += frame
        if (frame.device == Protocol.DEVICE_PEN) lastPen = frame else lastTouch = frame
    }

    private fun cancelTouches(out: MutableList<TabletMessage.Input>) {
        if (lastTouch.contacts.isNotEmpty()) {
            out += TabletMessage.Input(
                Protocol.DEVICE_TOUCH,
                lastTouch.contacts.map { it.copy(flags = it.flags or Protocol.CONTACT_CANCELED) },
            )
        }
        lastTouch = EMPTY_TOUCH
    }

    private fun fingerContacts(fingers: List<PointerSample>, width: Float, height: Float): List<InputContact> {
        slots.keys.retainAll(fingers.map { it.pointerId }.toSet())
        val contacts = mutableListOf<InputContact>()
        for (finger in fingers) {
            val slot = slots[finger.pointerId] ?: freeSlot()?.also { slots[finger.pointerId] = it } ?: continue
            contacts += InputContact(slot, Protocol.CONTACT_CONTACT or Protocol.CONTACT_IN_RANGE, norm(finger.x, width), norm(finger.y, height))
        }
        return contacts.sortedBy { it.id }
    }

    private fun freeSlot(): Int? = (0 until Protocol.MAX_TOUCH_CONTACTS).firstOrNull { it !in slots.values }

    private fun penContact(pen: PointerSample, width: Float, height: Float): InputContact {
        var flags = Protocol.CONTACT_IN_RANGE
        if (pen.inContact) flags = flags or Protocol.CONTACT_CONTACT
        if (pen.barrel) flags = flags or Protocol.CONTACT_BARREL
        val tilt = tan(pen.tiltRad.toDouble().coerceIn(0.0, MAX_TILT_RAD))
        val orientation = pen.orientationRad.toDouble()
        return InputContact(
            id = 0,
            flags = flags,
            x = norm(pen.x, width),
            y = norm(pen.y, height),
            pressure = if (pen.inContact) (pen.pressure.coerceIn(0f, 1f) * 1024f).roundToInt() else 0,
            tiltX = degrees(atan(sin(orientation) * tilt)),
            tiltY = degrees(atan(-cos(orientation) * tilt)),
        )
    }

    private fun trackHud(fingers: List<PointerSample>, nowMs: Long) {
        if (hudDisqualified || hudFired) return
        val start = hudStartMs
        if (fingers.size < HUD_FINGERS) {
            if (start != null) hudDisqualified = true
            return
        }
        if (start == null) {
            hudStartMs = nowMs
            hudOrigins = fingers.associate { it.pointerId to (it.x to it.y) }
            return
        }
        val moved = fingers.any { finger ->
            val origin = hudOrigins[finger.pointerId] ?: return@any true
            hypot(finger.x - origin.first, finger.y - origin.second) > hudSlopPx
        }
        if (moved) hudDisqualified = true
    }

    private fun checkHud(nowMs: Long): Boolean {
        val start = hudStartMs ?: return false
        if (hudDisqualified || hudFired || nowMs - start < hudHoldMs) return false
        hudFired = true
        return true
    }

    private fun resetGesture() {
        slots.clear()
        touchSuppressed = false
        hudStartMs = null
        hudOrigins = emptyMap()
        hudDisqualified = false
        hudFired = false
    }

    companion object {
        const val HUD_FINGERS = 4
        const val HUD_HOLD_MS = 2000L
        const val HUD_SLOP_DP = 48f
        private const val MAX_TILT_RAD = 1.5533430342749532 // 89° : évite tan(90°)
        private val EMPTY_TOUCH = TabletMessage.Input(Protocol.DEVICE_TOUCH, emptyList())
        private val EMPTY_PEN = TabletMessage.Input(Protocol.DEVICE_PEN, emptyList())

        fun norm(value: Float, size: Float): Int =
            if (size <= 0f) 0 else ((value / size).coerceIn(0f, 1f) * 65535f).roundToInt()

        private fun degrees(rad: Double): Int = Math.toDegrees(rad).roundToInt().coerceIn(-90, 90)
    }
}
```

- [ ] **Step 4 : Lancer** `:app:testDebugUnitTest` → BUILD SUCCESSFUL, 34 tests, 0 échec (compter dans le XML).

- [ ] **Step 5 : Commit** : `git add android/app/src` puis `git commit -m "feat(android): map pointer snapshots to INPUT frames"`.

---

### Task 7 : Liaison Android — capture, envoi, interface

**Files:**
- Create: `android/app/src/main/java/dev/tabx/client/input/TouchForwarder.kt`
- Modify: `Session.kt`, `Receiver.kt`, `MainActivity.kt`, `ui/TabXApp.kt`, `ui/StreamScreen.kt`, `ui/WaitingScreen.kt` (tous sous `android/app/src/main/java/dev/tabx/client/`)

- [ ] **Step 1 : `input/TouchForwarder.kt`**

```kotlin
package dev.tabx.client.input

import android.annotation.SuppressLint
import android.os.SystemClock
import android.view.MotionEvent
import android.view.View
import dev.tabx.client.protocol.TabletMessage

/**
 * Android glue (spec phase 4 §4.3): reads touch and stylus-hover events on the video view,
 * feeds [InputMapper] and sends its INPUT frames, only while [isStreaming].
 */
class TouchForwarder(
    private val view: View,
    private val isStreaming: () -> Boolean,
    private val send: (TabletMessage.Input) -> Unit,
    private val onToggleHud: () -> Unit,
) {
    private val mapper = InputMapper(hudSlopPx = InputMapper.HUD_SLOP_DP * view.resources.displayMetrics.density)
    private var touchSamples: List<PointerSample> = emptyList()
    private var hoverPen: PointerSample? = null
    private var wasStreaming = false
    private val hudCheck = Runnable { if (mapper.tick(SystemClock.uptimeMillis())) onToggleHud() }

    @SuppressLint("ClickableViewAccessibility") // la vue vidéo n'a pas d'action de clic propre
    fun attach() {
        view.setOnTouchListener { v, event ->
            if (event.actionMasked == MotionEvent.ACTION_DOWN) v.requestUnbufferedDispatch(event)
            if (event.actionMasked == MotionEvent.ACTION_CANCEL) {
                touchSamples = emptyList()
                if (streamingNow()) mapper.cancelAll().forEach(send)
            } else {
                touchSamples = touchSamplesOf(event)
                dispatch(event.eventTime)
            }
            true
        }
        view.setOnGenericMotionListener { v, event ->
            when (event.actionMasked) {
                MotionEvent.ACTION_HOVER_ENTER, MotionEvent.ACTION_HOVER_MOVE -> {
                    if (event.actionMasked == MotionEvent.ACTION_HOVER_ENTER) v.requestUnbufferedDispatch(event)
                    hoverPen = hoverSampleOf(event)
                }
                MotionEvent.ACTION_HOVER_EXIT -> hoverPen = null
                else -> return@setOnGenericMotionListener false
            }
            dispatch(event.eventTime)
            true
        }
    }

    private fun dispatch(eventTimeMs: Long) {
        if (!streamingNow()) return
        val pen = hoverPen?.takeIf { touchSamples.none { it.tool == Tool.PEN } }
        val out = mapper.process(touchSamples + listOfNotNull(pen), view.width.toFloat(), view.height.toFloat(), eventTimeMs)
        out.messages.forEach(send)
        if (out.toggleHud) onToggleHud()
        view.removeCallbacks(hudCheck)
        mapper.hudDeadlineMs?.let { view.postDelayed(hudCheck, (it - SystemClock.uptimeMillis()).coerceAtLeast(0)) }
    }

    /** False outside a streaming session; resets the mapper when a new session starts. */
    private fun streamingNow(): Boolean {
        if (!isStreaming()) {
            wasStreaming = false
            view.removeCallbacks(hudCheck)
            return false
        }
        if (!wasStreaming) {
            mapper.reset()
            wasStreaming = true
        }
        return true
    }

    private fun touchSamplesOf(event: MotionEvent): List<PointerSample> {
        val lifted = when (event.actionMasked) {
            MotionEvent.ACTION_UP, MotionEvent.ACTION_POINTER_UP -> event.actionIndex
            else -> -1
        }
        return (0 until event.pointerCount).filter { it != lifted }.map { i ->
            val pen = isPen(event.getToolType(i))
            PointerSample(
                pointerId = event.getPointerId(i),
                tool = if (pen) Tool.PEN else Tool.FINGER,
                x = event.getX(i),
                y = event.getY(i),
                pressure = event.getPressure(i),
                tiltRad = event.getAxisValue(MotionEvent.AXIS_TILT, i),
                orientationRad = event.getAxisValue(MotionEvent.AXIS_ORIENTATION, i),
                barrel = pen && (event.buttonState and MotionEvent.BUTTON_STYLUS_PRIMARY) != 0,
                inContact = true,
            )
        }
    }

    private fun hoverSampleOf(event: MotionEvent): PointerSample? {
        if (!isPen(event.getToolType(0))) return null
        return PointerSample(
            pointerId = event.getPointerId(0),
            tool = Tool.PEN,
            x = event.x,
            y = event.y,
            tiltRad = event.getAxisValue(MotionEvent.AXIS_TILT),
            orientationRad = event.getAxisValue(MotionEvent.AXIS_ORIENTATION),
            barrel = (event.buttonState and MotionEvent.BUTTON_STYLUS_PRIMARY) != 0,
            inContact = false,
        )
    }

    private fun isPen(toolType: Int) =
        toolType == MotionEvent.TOOL_TYPE_STYLUS || toolType == MotionEvent.TOOL_TYPE_ERASER
}
```

- [ ] **Step 2 : `Session.kt`**
  - ajouter sous `private val timerFailure = AtomicReference<Exception?>(null)` :

    ```kotlin
        @Volatile private var inputSink: ((TabletMessage.Input) -> Unit)? = null

        /** Queues an INPUT frame on the net-writer thread (never blocks the caller); no-op outside [run]. */
        fun sendInput(message: TabletMessage.Input) {
            inputSink?.invoke(message)
        }
    ```
  - dans `run()`, juste après `val timers = Executors.newSingleThreadScheduledExecutor { Thread(it, "net-writer") }` :

    ```kotlin
            inputSink = { message -> runCatching { timers.execute { runCatching { writer.write(message) } } } }
    ```
  - en première ligne du bloc `finally {` le plus externe de `run()` (avant `timers.shutdownNow()`) : `inputSink = null`.

- [ ] **Step 3 : `Receiver.kt`**
  - ajouter l'import `dev.tabx.client.protocol.TabletMessage` ;
  - ajouter sous `@Volatile private var socket: Socket? = null` :

    ```kotlin
        @Volatile private var session: Session? = null

        /** Forwards an INPUT frame to the running session, if any. */
        fun sendInput(message: TabletMessage.Input) {
            session?.sendInput(message)
        }
    ```
  - remplacer la ligne `Session(connection, surface, screen, model).run()` par :

    ```kotlin
                        val current = Session(connection, surface, screen, model)
                        session = current
                        try {
                            current.run()
                        } finally {
                            session = null
                        }
    ```

- [ ] **Step 4 : `ui/StreamScreen.kt`**
  - **supprimer** la fonction `detectThreeFingerTap` entière, ainsi que les imports devenus inutiles : `awaitEachGesture`, `awaitFirstDown`, `PointerEventPass`, `PointerInputScope` ;
  - changer `VideoSurface` pour exposer la vue :

    ```kotlin
    /** SurfaceView whose Surface feeds MediaCodec; [onView] receives it once (touch forwarding). */
    @Composable
    fun VideoSurface(
        modifier: Modifier,
        onView: (android.view.View) -> Unit,
        onCreated: (Surface) -> Unit,
        onDestroyed: () -> Unit,
    ) {
        val created by rememberUpdatedState(onCreated)
        val destroyed by rememberUpdatedState(onDestroyed)
        AndroidView(
            modifier = modifier,
            factory = { context ->
                SurfaceView(context).apply {
                    holder.addCallback(object : SurfaceHolder.Callback {
                        override fun surfaceCreated(holder: SurfaceHolder) = created(holder.surface)
                        override fun surfaceChanged(holder: SurfaceHolder, format: Int, width: Int, height: Int) {}
                        override fun surfaceDestroyed(holder: SurfaceHolder) = destroyed()
                    })
                    onView(this)
                }
            },
        )
    }
    ```

- [ ] **Step 5 : `ui/TabXApp.kt`**
  - ajouter le paramètre `onVideoView: (android.view.View) -> Unit,` à `TabXApp`, juste après `screen: ScreenInfo,` ;
  - supprimer le modificateur `.pointerInput(model) { detectThreeFingerTap { … } }` du `Box` racine, et l'import `androidx.compose.ui.input.pointer.pointerInput` ;
  - remplacer `VideoSurface(videoModifier, onSurfaceCreated, onSurfaceDestroyed)` par `VideoSurface(videoModifier, onVideoView, onSurfaceCreated, onSurfaceDestroyed)` ;
  - juste après `if (streaming) HudLayer(…)`, ajouter `GestureHint(streaming, Modifier.align(Alignment.BottomCenter).padding(bottom = 32.dp))` ;
  - ajouter en fin de fichier :

    ```kotlin
    /** Brief reminder of the HUD gesture at the start of each connection (spec phase 4 §4.5). */
    @Composable
    private fun GestureHint(streaming: Boolean, modifier: Modifier) {
        var visible by remember { mutableStateOf(false) }
        LaunchedEffect(streaming) {
            visible = streaming
            if (streaming) {
                delay(HINT_DURATION_MS)
                visible = false
            }
        }
        AnimatedVisibility(visible = visible, modifier = modifier, enter = fadeIn(tween(300)), exit = fadeOut(tween(600))) {
            GlassPanel { GlassText("Appui long à 4 doigts : infos", size = 13.sp) }
        }
    }

    private const val HINT_DURATION_MS = 4000L
    ```
  - imports à ajouter : `androidx.compose.runtime.LaunchedEffect`, `androidx.compose.runtime.getValue`, `androidx.compose.runtime.mutableStateOf`, `androidx.compose.runtime.remember`, `androidx.compose.runtime.setValue`, `androidx.compose.ui.unit.sp`, `kotlinx.coroutines.delay`.

- [ ] **Step 6 : `ui/WaitingScreen.kt`** : dans `WaitingScreen`, trouver la `Box` qui affiche la commande du relais (`GlassText("py relay.py --encoder amf", …)`). Remplacer le `Spacer(Modifier.height(16.dp))` qui la suit par :

```kotlin
            Spacer(Modifier.height(12.dp))
            GlassText("Appui long à 4 doigts : infos de connexion", size = 12.sp, alpha = 0.75f)
            Spacer(Modifier.height(16.dp))
```

- [ ] **Step 7 : `MainActivity.kt`**
  - remplacer `setContent { TabXApp(model, screen, ::onSurfaceCreated, ::onSurfaceDestroyed) }` par `setContent { TabXApp(model, screen, ::onVideoView, ::onSurfaceCreated, ::onSurfaceDestroyed) }` ;
  - ajouter la méthode :

    ```kotlin
        private fun onVideoView(view: View) {
            TouchForwarder(
                view = view,
                isStreaming = { model.state is ConnectionState.Streaming },
                send = { receiver?.sendInput(it) },
                onToggleHud = model::toggleHud,
            ).attach()
        }
    ```
  - imports : `android.view.View`, `dev.tabx.client.input.TouchForwarder`.

- [ ] **Step 8 : Compiler et tester** : `:app:assembleDebug :app:testDebugUnitTest` → BUILD SUCCESSFUL, 34 tests. Rapporter tout avertissement du compilateur mot pour mot.

- [ ] **Step 9 : Commit** : `git add android/app/src` puis `git commit -m "feat(android): forward touch and pen to the PC, 4-finger HUD gesture"`.

---

### Task 8 : README et essai sur la tablette

**Files:**
- Modify: `README.md`

- [ ] **Step 1 : Ajouter au README**, avant `## Tests` :

````markdown
## Tactile et stylet (phase 4)

Pendant le flux, le doigt et le S Pen pilotent Windows à l'endroit touché de l'écran étendu :

- **Doigt** : tap = clic ; appui long = clic droit ; défilement et zoom à deux doigts (gestes natifs de Windows). Au plus 3 doigts sont transmis, le 4e étant réservé au HUD.
- **S Pen** : survol = curseur ; encre avec pression et inclinaison ; bouton latéral = clic droit. Tant que le stylet est détecté, les doigts (la paume) sont ignorés.
- **HUD** : appui long à 4 doigts (2 s, sans bouger).
- Le relais cible l'écran Windows qui a la taille du flux. Sans écran unique de cette taille, le tactile se désactive mais la vidéo continue.
- Les fenêtres administrateur (Gestionnaire des tâches, installeurs) ne répondent qu'à un relais **lancé en administrateur**.
- Autotest de l'injection, sans tablette et sans clic : `cd host-prototype; py injector.py --selftest`.
````

  Et ajouter à la fin de « Vérifications techniques sur la tablette » :

```markdown
- [ ] **Tactile** : tap précis (croix d'une fenêtre), défilement à 2 doigts dans un navigateur, pincement dans Photos, appui long = menu contextuel.
- [ ] **S Pen** : survol sans clic ; trait plus épais quand on appuie (Paint, Whiteboard) ; inclinaison dans le bon sens ; bouton = clic droit. Si le bouton ouvre le menu Air Command de Samsung en survol, le noter.
- [ ] **Paume** : poser la main en dessinant ne clique nulle part.
- [ ] **HUD** : l'appui long à 4 doigts bascule le HUD sans clic ni geste Windows ; rappel visible sur l'écran d'attente et en début de connexion.
- [ ] **Contacts coincés** : Ctrl+C sur le relais pendant un toucher : aucun contact ne reste « posé ».
- [ ] **Garde-fou 100 ms** (`KEEPALIVE_S` dans `injector.py`) : garder un doigt immobile 5 s sur une fenêtre. Mettre ensuite la constante à `3600` et refaire l'essai. Si le contact tient aussi sans garde-fou, le garde-fou est inutile.
```

- [ ] **Step 2 : Commit** : `git add README.md` puis `git commit -m "docs: document touch and pen input"`.

- [ ] **Step 3 : Essai sur la tablette, avec l'utilisateur.**
  - Il installe l'app (Android Studio ▶ Run) et lance `py relay.py --encoder amf`.
  - On déroule les critères de la spec §8 avec la checklist ci-dessus.
  - Si le sens de l'inclinaison est inversé : inverser le signe de `tiltY` ou de `tiltX` dans `InputMapper.penContact`, et ajuster `penContactConversion`.
  - Noter les résultats dans le README (« Mesures »).
