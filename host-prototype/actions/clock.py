"""Clock provider: the PC's wall time, so the device shows the PC's time even when its own is off."""
from __future__ import annotations

import time
from typing import Callable


def _local_utc_offset_min() -> int:
    local = time.localtime()
    return int((local.tm_gmtoff or 0) // 60)


class ClockProvider:
    def __init__(self, now: Callable[[], float] = time.time,
                 utc_offset_min: Callable[[], int] = _local_utc_offset_min):
        self._now = now
        self._utc_offset_min = utc_offset_min

    def snapshot(self) -> dict:
        return {"epoch_ms": int(self._now() * 1000), "utc_offset_min": int(self._utc_offset_min())}

    def handle(self, action: dict) -> str | None:
        return None
