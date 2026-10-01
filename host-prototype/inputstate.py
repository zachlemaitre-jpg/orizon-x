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
    """Follows one synthetic device (touch or pen) across INPUT frames and yields complete injection frames.

    PRIMARY (Windows rule: once a primary exists, every contact must lift before another can become primary):
    the pen is always primary; a finger that goes down becomes primary only if there is no primary and no other
    finger in contact, keeps the flag (including on its UP) and is never replaced; once it lifts, no finger is
    primary until all of them have lifted.
    """

    def __init__(self, device: int) -> None:
        self._pen = device == protocol.DEVICE_PEN
        self._active: dict[int, PointerAction] = {}  # contacts posés, ou stylet en portée (sans PRIMARY)
        self._touching: set[int] = set()  # contacts actuellement posés
        self._primary: int | None = None  # doigt principal (tactile uniquement)

    def update(self, contacts: Iterable[protocol.Contact], rect: Rect) -> list[PointerAction]:
        blocking = set(self._touching)  # doigts posés au début de la trame : empêchent un nouveau principal
        frame: list[PointerAction] = []
        seen: set[int] = set()
        for contact in contacts:
            previous = self._active.get(contact.id)
            action = self._action(contact, rect)
            if contact.flags & protocol.CONTACT_CANCELED:
                seen.add(contact.id)
                if previous is not None:
                    in_contact = bool(previous.flags & POINTER_FLAG_INCONTACT)
                    flags = POINTER_FLAG_UP | POINTER_FLAG_CANCELED if in_contact else POINTER_FLAG_UPDATE
                    frame.append(self._mark(replace(action, flags=flags)))
                self._forget(contact.id)
                continue
            down = bool(contact.flags & protocol.CONTACT_CONTACT)
            if not down and not self._pen:
                continue  # le tactile n'a pas de survol : un contact non posé est un doigt levé
            seen.add(contact.id)
            was_down = previous is not None and bool(previous.flags & POINTER_FLAG_INCONTACT)
            in_range = down or bool(contact.flags & protocol.CONTACT_IN_RANGE)
            if down and not was_down:
                flags = POINTER_FLAG_DOWN | POINTER_FLAG_INRANGE | POINTER_FLAG_INCONTACT
                if not self._pen and self._primary is None and not blocking:
                    self._primary = contact.id
                blocking.add(contact.id)
                self._touching.add(contact.id)
            elif down:
                flags = POINTER_FLAG_UPDATE | POINTER_FLAG_INRANGE | POINTER_FLAG_INCONTACT
            elif was_down:
                flags = POINTER_FLAG_UP | (POINTER_FLAG_INRANGE if in_range else 0)
            elif previous is None and not in_range:
                continue  # ni posé ni en portée, et inconnu : rien à injecter
            else:
                flags = POINTER_FLAG_UPDATE | (POINTER_FLAG_INRANGE if in_range else 0)
            action = replace(action, flags=flags)
            frame.append(self._mark(action))
            if in_range:
                self._active[contact.id] = action
                if not down:
                    self._touching.discard(contact.id)
            else:
                self._forget(contact.id)
        for pointer_id in [p for p in self._active if p not in seen]:
            previous = self._active[pointer_id]
            flags = POINTER_FLAG_UP if previous.flags & POINTER_FLAG_INCONTACT else POINTER_FLAG_UPDATE
            frame.append(self._mark(replace(previous, flags=flags, pressure=0)))
            self._forget(pointer_id)
        return frame

    def refresh(self) -> list[PointerAction]:
        """Re-sends held contacts unchanged (keep-alive while nothing moves). Empty if nothing is in contact."""
        if not any(a.flags & POINTER_FLAG_INCONTACT for a in self._active.values()):
            return []
        return [
            self._mark(replace(a, flags=POINTER_FLAG_UPDATE | POINTER_FLAG_INRANGE | (a.flags & POINTER_FLAG_INCONTACT)))
            for a in self._active.values()
        ]

    def cancel_all(self) -> list[PointerAction]:
        """Ends every active pointer without a click (session end)."""
        frame = [
            self._mark(replace(a, pressure=0, flags=(POINTER_FLAG_UP | POINTER_FLAG_CANCELED)
                               if a.flags & POINTER_FLAG_INCONTACT else POINTER_FLAG_UPDATE))
            for a in self._active.values()
        ]
        self._active.clear()
        self._touching.clear()
        self._primary = None
        return frame

    def _action(self, contact: protocol.Contact, rect: Rect) -> PointerAction:
        x = to_pixels(contact.x, rect.left, rect.width)
        y = to_pixels(contact.y, rect.top, rect.height)
        if not self._pen:
            return PointerAction(contact.id, 0, x, y)
        return PointerAction(
            contact.id, 0, x, y,
            pressure=min(max(contact.pressure, 0), 1024), tilt_x=contact.tilt_x, tilt_y=contact.tilt_y,
            pen_flags=PEN_FLAG_BARREL if contact.flags & protocol.CONTACT_BARREL else 0,
            pen_mask=PEN_MASK_PRESSURE | PEN_MASK_TILT_X | PEN_MASK_TILT_Y,
        )

    def _mark(self, action: PointerAction) -> PointerAction:
        if self._pen or action.pointer_id == self._primary:
            return replace(action, flags=action.flags | POINTER_FLAG_PRIMARY)
        return action

    def _forget(self, pointer_id: int) -> None:
        self._active.pop(pointer_id, None)
        self._touching.discard(pointer_id)
        if pointer_id == self._primary:
            self._primary = None
