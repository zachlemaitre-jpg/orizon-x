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
            pressure=min(max(contact.pressure, 0), 1024), tilt_x=contact.tilt_x, tilt_y=contact.tilt_y,
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
