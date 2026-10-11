"""Common contract of the Actions providers (spec Actions mode §3)."""
from __future__ import annotations

from typing import Protocol


class ProviderError(Exception):
    """A provider could not read or change its part of the system; the hub marks it unavailable."""


class Provider(Protocol):
    def snapshot(self) -> dict:
        """This provider's part of the state; {"available": False} when the feature is absent."""
        ...

    def handle(self, action: dict) -> str | None:
        """Apply an ACTION. None when OK, else a notice code (usb_busy, usb_failed, radio_denied, action_failed)."""
        ...
