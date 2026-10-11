"""Audio provider: master volume and mute of the default render endpoint.

Uses pycaw / comtypes (``IAudioEndpointVolume``).

COM threading: this provider assumes COM is already initialised in the
calling thread (the ActionsHub thread does ``CoInitializeEx``), and every
call (``snapshot`` and ``handle``) must come from that same thread because
the cached COM interfaces belong to its apartment.

The default device is re-checked on every snapshot (a cheap
``GetDefaultAudioEndpoint`` + ``GetId``) so the provider follows the user
switching the output device; the endpoint is also dropped and re-acquired
after any COM error.
"""

from __future__ import annotations

import logging
import math
import threading
from typing import Any, Optional, Protocol, Tuple

_log = logging.getLogger("orizonx.actions.audio")

ACTION_FAILED = "action_failed"


class VolumeEndpoint(Protocol):
    """The subset of IAudioEndpointVolume this provider uses."""

    def GetMasterVolumeLevelScalar(self) -> float: ...
    def SetMasterVolumeLevelScalar(self, level: float, ctx: Any) -> Any: ...
    def GetMute(self) -> Any: ...
    def SetMute(self, mute: Any, ctx: Any) -> Any: ...


class AudioBackend(Protocol):
    """Access to the default render endpoint (injectable for tests)."""

    def default_device_id(self) -> Optional[str]:
        """Id of the current default render device, None when there is none."""

    def open_endpoint(self) -> Tuple[Optional[str], VolumeEndpoint]:
        """Open the volume interface of the current default render device."""


class PycawBackend:
    """Real backend on top of pycaw / comtypes (imported lazily)."""

    def __init__(self) -> None:
        self._enumerator = None

    def _get_enumerator(self):
        if self._enumerator is None:
            from pycaw.pycaw import AudioUtilities

            self._enumerator = AudioUtilities.GetDeviceEnumerator()
        return self._enumerator

    def _default_device(self):
        # eRender = 0, eMultimedia = 1.
        try:
            return self._get_enumerator().GetDefaultAudioEndpoint(0, 1)
        except Exception:
            self._enumerator = None  # force a fresh enumerator next time
            raise

    def default_device_id(self) -> Optional[str]:
        return self._default_device().GetId()

    def open_endpoint(self) -> Tuple[Optional[str], VolumeEndpoint]:
        import comtypes
        from pycaw.pycaw import IAudioEndpointVolume

        device = self._default_device()
        device_id = device.GetId()
        iface = device.Activate(IAudioEndpointVolume._iid_, comtypes.CLSCTX_ALL, None)
        return device_id, iface.QueryInterface(IAudioEndpointVolume)


def _clamp01(value: Any) -> Optional[float]:
    """Number -> clamped to 0..1; None when not a finite number."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    if not math.isfinite(value):
        return None
    return max(0.0, min(1.0, float(value)))


class AudioProvider:
    """Provider for ``volume.set`` / ``volume.mute`` and the ``audio`` state."""

    def __init__(self, backend: Optional[AudioBackend] = None) -> None:
        self._backend: AudioBackend = backend if backend is not None else PycawBackend()
        self._lock = threading.Lock()
        self._device_id: Optional[str] = None
        self._endpoint: Optional[VolumeEndpoint] = None

    # -- endpoint management -------------------------------------------------

    def _drop(self) -> None:
        self._endpoint = None
        self._device_id = None

    def _ensure_endpoint(self) -> VolumeEndpoint:
        """Return an endpoint for the *current* default device (may raise)."""
        current = self._backend.default_device_id()
        if self._endpoint is not None and current == self._device_id:
            return self._endpoint
        device_id, endpoint = self._backend.open_endpoint()
        self._device_id = device_id if device_id is not None else current
        self._endpoint = endpoint
        return endpoint

    def _with_endpoint(self, fn):
        """Run fn(endpoint); on any error re-acquire the endpoint and retry once."""
        last: Optional[BaseException] = None
        for _attempt in range(2):
            try:
                return fn(self._ensure_endpoint())
            except Exception as exc:  # COMError, OSError, ... : try a fresh endpoint
                last = exc
                self._drop()
        assert last is not None
        raise last

    # -- Provider protocol -----------------------------------------------------

    def snapshot(self) -> dict:
        with self._lock:
            try:
                volume, muted = self._with_endpoint(
                    lambda ep: (
                        float(ep.GetMasterVolumeLevelScalar()),
                        bool(ep.GetMute()),
                    )
                )
            except Exception as exc:
                _log.debug("audio endpoint unavailable: %r", exc)
                return {"available": False}
        return {
            "available": True,
            "volume": round(max(0.0, min(1.0, volume)), 2),
            "muted": muted,
        }

    def handle(self, action: dict) -> Optional[str]:
        action_id = action.get("id")
        if action_id == "volume.set":
            level = _clamp01(action.get("value"))
            if level is None:
                return ACTION_FAILED
            call = lambda ep: ep.SetMasterVolumeLevelScalar(level, None)  # noqa: E731
        elif action_id == "volume.mute":
            value = action.get("value")
            if not isinstance(value, bool):
                return ACTION_FAILED
            call = lambda ep: ep.SetMute(1 if value else 0, None)  # noqa: E731
        else:
            return ACTION_FAILED
        with self._lock:
            try:
                self._with_endpoint(call)
            except Exception as exc:
                _log.warning("audio action %s failed: %r", action_id, exc)
                return ACTION_FAILED
        return None
