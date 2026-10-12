"""Radios provider: Wi-Fi / Bluetooth on-off and the airplane mode (spec Actions mode §2.1, §2.2, §3 `radios`).

WinRT ``Windows.Devices.Radios``: ``Radio.get_radios_async()`` lists the radios, ``Radio.set_state_async()`` switches
one, ``Radio.request_access_async()`` must answer ALLOWED before any change (else the notice ``radio_denied``).
All WinRT calls go through actions.winrt_call (one MTA worker thread, bounded waits: see that module).

Airplane mode is ours, kept in memory only: ``airplane.set true`` remembers which radios (every kind, mobile
broadband included) were on and turns them all off; ``airplane.set false`` turns the remembered ones back on. A
radio that was off stays as it is now, so one switched on during airplane mode (``bluetooth.set true``) stays on.
Windows' own airplane switch is not read: the tile shows our mode, False after a restart of the app.

``handle()`` returns None on success (and for an unknown id, which is logged and ignored), ``radio_denied``
when RequestAccessAsync or SetStateAsync does not answer ALLOWED, ``action_failed`` for a bad value, no radio of
that kind (or only disabled ones), a WinRT error or a timeout.

Merge contract for the ActionsHub
---------------------------------
Three providers feed the "wifi", "bluetooth" and "airplane" objects of ACTIONS_STATE (spec §2.1); none of them maps
to a top-level key by itself, so the hub must NOT put their snapshots under "radios" / "wifi_info" / "bt_info".

1. On each 1 s poll the hub takes the three snapshots separately, each guarded like any provider: a snapshot that
   raises (ProviderError, WinRTCallError on timeout, ...) is logged once and replaced by ``{"available": False}``.

   * ``RadiosProvider().snapshot()``::

         {"available": True,
          "wifi": {"available": bool, "on": bool},        # {"available": False} when there is no Wi-Fi radio
          "bluetooth": {"available": bool, "on": bool},   # {"available": False} when there is no Bluetooth radio
          "airplane": {"available": bool, "on": bool}}    # {"available": False} when there is no radio at all

     or ``{"available": False}`` without WinRT.
   * ``WifiInfoProvider().snapshot()`` (actions.wifi_info): ``{"available": True, "ssid": str, "signal": int | None}`` or
     ``{"available": False}``.
   * ``BluetoothInfoProvider().snapshot()`` (actions.bt_info): ``{"available": True, "connected": [str]}`` or
     ``{"available": False}``.

2. The hub calls ``merge_radio_state(radios_snapshot, wifi_info_snapshot, bt_info_snapshot)`` (None is accepted for
   a provider it does not have) and copies the three keys of the result into the state::

       state.update(merge_radio_state(radios_snap, wifi_snap, bt_snap))
       # -> state["wifi"]      = {"available": True, "on": bool, "ssid": str, "signal": int | None}
       #                         or {"available": False}
       #    state["bluetooth"] = {"available": True, "on": bool, "connected": [str]} or {"available": False}
       #    state["airplane"]  = {"available": True, "on": bool}                    or {"available": False}

   Every object always carries "available". Radios unavailable -> the three objects are ``{"available": False}``
   whatever the two others say. wifi_info / bt_info unavailable or missing -> ``ssid`` "" / ``signal`` None /
   ``connected`` []. ``ssid``, ``signal`` and ``connected`` are also "" / None / [] while their radio is off (stale
   values are not shown). ``signal`` is the Wi-Fi signal quality 0..100, None when not connected.

3. Actions ``wifi.set``, ``bluetooth.set`` and ``airplane.set`` all go to this provider; wifi_info and bt_info have
   no action (they log and ignore any id). After any of them the hub re-polls the three snapshots.

Threading: the WinRT calls run on the actions.winrt_call worker, so this provider can be called from any thread;
an internal lock serialises snapshot() and handle() (the airplane memory).
"""
from __future__ import annotations

import logging
import threading
from dataclasses import dataclass
from typing import Any, Optional, Protocol

from actions import winrt_call
from actions.base import ProviderError

_log = logging.getLogger("orizonx.actions.radios")

ACTION_FAILED = "action_failed"
RADIO_DENIED = "radio_denied"

LIST_TIMEOUT_S = 2.0
SET_TIMEOUT_S = 5.0   # switching Wi-Fi on can take a few seconds

# Windows.Devices.Radios.RadioKind / RadioState / RadioAccessStatus
_KINDS = {0: "other", 1: "wifi", 2: "mobile", 3: "bluetooth", 4: "fm"}
_STATES = {0: "unknown", 1: "on", 2: "off", 3: "disabled"}
_STATE_ON, _STATE_OFF = 1, 2
_ACCESS_ALLOWED = 1

_KIND_OF_ACTION = {"wifi.set": "wifi", "bluetooth.set": "bluetooth"}


def kind_name(kind: int) -> str:
    """RadioKind value -> "wifi" | "bluetooth" | "mobile" | "fm" | "other"."""
    return _KINDS.get(int(kind), "other")


def state_name(state: int) -> str:
    """RadioState value -> "on" | "off" | "disabled" | "unknown"."""
    return _STATES.get(int(state), "unknown")


@dataclass(frozen=True)
class RadioInfo:
    kind: str    # kind_name()
    name: str    # Radio.Name ("Wi-Fi", "Bluetooth"...)
    state: str   # state_name()
    index: int   # position in Radio.get_radios_async() when it was read


class RadiosApi(Protocol):
    def request_access(self) -> bool:
        """True when Radio.request_access_async() answers ALLOWED."""

    def list_radios(self) -> list[RadioInfo]:
        """The radios, in WinRT order (index = position)."""

    def set_state(self, radio: RadioInfo, on: bool) -> bool:
        """Switch that radio; True when SetStateAsync answers ALLOWED."""


class WinRTRadiosApi:
    """The real radios, through pywinrt on the WinRT worker thread."""

    def __init__(self, worker: Optional[winrt_call.WinRTWorker] = None) -> None:
        from winrt.windows.devices.radios import Radio  # ImportError -> provider unavailable

        self._radio = Radio
        self._worker = worker or winrt_call.WORKER

    def request_access(self) -> bool:
        op = lambda: int(winrt_call.wait_op(self._radio.request_access_async(), LIST_TIMEOUT_S))  # noqa: E731
        return self._worker.run(op, LIST_TIMEOUT_S) == _ACCESS_ALLOWED

    def _radios(self) -> list[Any]:
        return list(winrt_call.wait_op(self._radio.get_radios_async(), LIST_TIMEOUT_S))

    def list_radios(self) -> list[RadioInfo]:
        def read() -> list[RadioInfo]:
            return [RadioInfo(kind_name(r.kind), r.name, state_name(r.state), i)
                    for i, r in enumerate(self._radios())]
        return self._worker.run(read, LIST_TIMEOUT_S)

    def set_state(self, radio: RadioInfo, on: bool) -> bool:
        def switch() -> bool:
            radios = self._radios()
            if radio.index >= len(radios):
                raise LookupError(f"radio {radio.name!r} is gone")
            target = radios[radio.index]
            if kind_name(target.kind) != radio.kind or target.name != radio.name:
                raise LookupError(f"radio {radio.name!r} moved")
            status = winrt_call.wait_op(target.set_state_async(_STATE_ON if on else _STATE_OFF), SET_TIMEOUT_S)
            return int(status) == _ACCESS_ALLOWED
        return self._worker.run(switch, LIST_TIMEOUT_S + SET_TIMEOUT_S)


def _default_api() -> Optional[RadiosApi]:
    try:
        return WinRTRadiosApi()
    except ImportError as e:
        _log.info("radios unavailable: %s", e)
        return None


def _keys(radios: list[RadioInfo]) -> list[tuple[str, str, int]]:
    """(kind, name, rank among the radios of the same kind and name): stable even if Windows reorders them."""
    seen: dict[tuple[str, str], int] = {}
    keys = []
    for r in radios:
        rank = seen.get((r.kind, r.name), 0)
        seen[(r.kind, r.name)] = rank + 1
        keys.append((r.kind, r.name, rank))
    return keys


_DEFAULT = object()


class RadiosProvider:
    """Wi-Fi / Bluetooth / airplane; see the module docstring for the snapshot and the merge contract."""

    def __init__(self, api: Any = _DEFAULT) -> None:
        self._api: Optional[RadiosApi] = _default_api() if api is _DEFAULT else api
        self._airplane = False
        self._remembered_on: set[tuple[str, str, int]] = set()
        # snapshot() (hub thread) and handle() (possibly the session's reader thread) share the airplane memory.
        self._lock = threading.Lock()

    def snapshot(self) -> dict:
        if self._api is None:
            return {"available": False}
        with self._lock:
            return self._snapshot()

    def _snapshot(self) -> dict:
        try:
            radios = self._api.list_radios()
        except ProviderError:
            raise
        except Exception as e:  # noqa: BLE001 - WinRT error (OSError) or other
            raise ProviderError(f"radios: cannot list the radios: {e!r}") from e
        return {"available": True,
                "wifi": self._kind_part(radios, "wifi"),
                "bluetooth": self._kind_part(radios, "bluetooth"),
                "airplane": {"available": True, "on": self._airplane} if radios else {"available": False}}

    @staticmethod
    def _kind_part(radios: list[RadioInfo], kind: str) -> dict:
        of_kind = [r for r in radios if r.kind == kind]
        if not of_kind:
            return {"available": False}
        return {"available": True, "on": any(r.state == "on" for r in of_kind)}

    def handle(self, action: dict) -> Optional[str]:
        action_id = action.get("id")
        value = action.get("value")
        if action_id not in ("wifi.set", "bluetooth.set", "airplane.set"):
            _log.warning("radios: unknown action %r ignored", action_id)
            return None
        if not isinstance(value, bool) or self._api is None:
            return ACTION_FAILED
        with self._lock:
            return self._handle(action_id, value)

    def _handle(self, action_id: str, value: bool) -> Optional[str]:
        if action_id == "airplane.set" and value == self._airplane:
            return None  # already in that mode: nothing to remember or restore
        try:
            if not self._api.request_access():
                return RADIO_DENIED
            if action_id == "airplane.set":
                return self._airplane_on() if value else self._airplane_off()
            return self._set_kind(_KIND_OF_ACTION[action_id], value)
        except Exception as e:  # noqa: BLE001 - WinRT error, timeout, radio gone
            _log.warning("radios: %s=%s failed: %r", action_id, value, e)
            return ACTION_FAILED

    def _set_kind(self, kind: str, on: bool) -> Optional[str]:
        targets = [r for r in self._api.list_radios() if r.kind == kind and r.state in ("on", "off")]
        if not targets:
            return ACTION_FAILED  # no radio of that kind, or disabled (hardware switch, driver)
        denied = False
        for r in targets:
            if (r.state == "on") != on and not self._api.set_state(r, on):
                denied = True
        return RADIO_DENIED if denied else None

    def _airplane_on(self) -> Optional[str]:
        radios = self._api.list_radios()
        if not radios:
            return ACTION_FAILED
        self._remembered_on = {k for k, r in zip(_keys(radios), radios) if r.state == "on"}
        self._airplane = True  # even if partly refused: leaving airplane mode restores what was turned off
        denied = False
        for r in radios:
            if r.state == "on" and not self._api.set_state(r, False):
                denied = True
        return RADIO_DENIED if denied else None

    def _airplane_off(self) -> Optional[str]:
        radios = self._api.list_radios()
        denied = False
        for k, r in zip(_keys(radios), radios):
            if k in self._remembered_on and r.state == "off" and not self._api.set_state(r, True):
                denied = True
        if denied:
            return RADIO_DENIED  # stay in airplane mode so that leaving it can be retried
        self._airplane = False
        self._remembered_on = set()
        return None


def _signal(value: Any) -> Optional[int]:
    """A Wi-Fi signal quality as an int 0..100, None for anything that is not a number."""
    if isinstance(value, bool) or not isinstance(value, (int, float)) or value != value:
        return None
    return max(0, min(100, int(value)))


def merge_radio_state(radios: Optional[dict], wifi_info: Optional[dict], bt_info: Optional[dict]) -> dict:
    """The "wifi", "bluetooth" and "airplane" parts of ACTIONS_STATE from the three providers' snapshots.

    ssid / signal / connected are filled only while the radio is on (else "" / None / []); unavailable inputs are
    tolerated. signal is wifi_info's 0..100 signal quality, None when not connected."""
    if not radios or not radios.get("available"):
        return {"wifi": {"available": False}, "bluetooth": {"available": False}, "airplane": {"available": False}}
    wifi = dict(radios.get("wifi") or {"available": False})
    if wifi.get("available"):
        ok = bool(wifi_info and wifi_info.get("available") and wifi.get("on"))
        wifi["ssid"] = str(wifi_info.get("ssid", "")) if ok else ""
        wifi["signal"] = _signal(wifi_info.get("signal")) if ok else None
    bluetooth = dict(radios.get("bluetooth") or {"available": False})
    if bluetooth.get("available"):
        ok = bool(bt_info and bt_info.get("available") and bluetooth.get("on"))
        bluetooth["connected"] = list(bt_info.get("connected", [])) if ok else []
    return {"wifi": wifi, "bluetooth": bluetooth, "airplane": dict(radios.get("airplane") or {"available": False})}
