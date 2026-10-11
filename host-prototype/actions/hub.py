"""ActionsHub: polls the Actions providers and broadcasts the full state (spec Actions mode §2.1, §3 hub).

One thread owns everything:

* it does ``CoInitializeEx`` (MTA) at start and ``CoUninitialize`` at stop, because the audio provider (pycaw) and
  the brightness provider (WMI) need an initialised apartment and keep COM interfaces that belong to the thread
  that created them. Their ``snapshot()`` AND ``handle()`` therefore run on this thread only;
* ``handle(action)`` may be called from any thread (the session's reader): it only enqueues the action and wakes the
  hub thread, which routes it by id prefix, executes it, then polls every provider at once;
* the radios provider (and wifi_info / bt_info) have their own WinRT worker (actions.winrt_call): safe from here.
  Actions all run on the hub thread, so a slow one (a Wi-Fi switch, a USB eject) delays the next poll for as long
  as it lasts.

State shape: ``{"v": 1, "clock", "battery", "audio", "media", "brightness", "wifi", "bluetooth", "airplane",
"usb": [...], optional "notice"}``. Every object section carries ``"available"``; ``wifi`` / ``bluetooth`` /
``airplane`` come from ``merge_radio_state(radios, wifi_info, bt_info)`` (see actions.radios); ``usb`` is the list
of drives. A section whose provider is missing or raising is ``{"available": False}`` (``[]`` for usb) until the
provider answers again; the failure is logged once per streak.

A state is sent when it differs from the last one sent, or ``refresh_s`` after the last send. The clock's
``epoch_ms`` is left out of that comparison (it changes at every poll; the device ticks it locally and the periodic
refresh resynchronises it); a change of UTC offset still counts. ``notice`` (``{"code": ..., "drive": ...}``) is put
in the next state only, and that state is sent even if nothing else changed.

Provider keys in the ``providers`` dict: clock, battery, audio, media, brightness, radios, wifi_info, bt_info, usb.
"""
from __future__ import annotations

import copy
import logging
import queue
import threading
import time
from typing import Any, Callable, Optional

from actions.radios import merge_radio_state

_logger = logging.getLogger("orizonx.actions.hub")

STATE_VERSION = 1
STOP_JOIN_S = 2.0
ACTION_FAILED = "action_failed"

# action id prefix -> provider key
_ROUTES = (
    ("volume.", "audio"),
    ("media.", "media"),
    ("brightness.", "brightness"),
    ("wifi.", "radios"),
    ("bluetooth.", "radios"),
    ("airplane.", "radios"),
    ("usb.", "usb"),
)

_FAST = ("audio",)
_SLOW = ("clock", "battery", "media", "brightness", "radios", "wifi_info", "bt_info", "usb")
_UNAVAILABLE = {"available": False}

_COINIT_MULTITHREADED = 0
_S_OK, _S_FALSE = 0, 1


def _com_init() -> Optional[Callable[[], None]]:
    """Initialise COM (MTA) in the calling thread; returns the matching uninitialise function, or None if COM
    was not initialised here (already initialised with another model, or not Windows)."""
    try:
        import ctypes
        ole32 = ctypes.OleDLL("ole32")
    except (ImportError, OSError, AttributeError):
        return None
    hr = ole32.CoInitializeEx(None, _COINIT_MULTITHREADED) & 0xFFFFFFFF
    if hr in (_S_OK, _S_FALSE):
        return ole32.CoUninitialize
    _logger.warning("CoInitializeEx failed: 0x%08X", hr)
    return None


def _route(action_id: Any) -> Optional[str]:
    if isinstance(action_id, str):
        for prefix, key in _ROUTES:
            if action_id.startswith(prefix):
                return key
    return None


def _comparable(state: dict) -> dict:
    """The state without the ticking part of the clock."""
    cmp = dict(state)
    cmp.pop("notice", None)
    clock = cmp.get("clock")
    if isinstance(clock, dict):
        cmp["clock"] = {k: v for k, v in clock.items() if k != "epoch_ms"}
    return cmp


class ActionsHub:
    def __init__(self, providers: dict, send: Callable[[dict], None], *,
                 clock: Callable[[], float] = time.monotonic,
                 poll_fast_s: float = 0.25, poll_slow_s: float = 1.0, refresh_s: float = 30.0,
                 log: Optional[Callable[[str], None]] = None,
                 com_init: Callable[[], Optional[Callable[[], None]]] = _com_init) -> None:
        self._providers = providers
        self._send = send
        self._clock = clock
        self._poll_fast_s = poll_fast_s
        self._poll_slow_s = poll_slow_s
        self._refresh_s = refresh_s
        self._log = log or _logger.info
        self._com_init = com_init

        self._actions: "queue.Queue[dict]" = queue.Queue()
        self._wake = threading.Event()
        self._stopping = threading.Event()
        self._thread: Optional[threading.Thread] = None

        # Only touched by the hub thread (or by tests driving _tick directly).
        self._snap: dict[str, Optional[dict]] = {}
        self._failed: set[str] = set()
        self._notice: Optional[dict] = None
        self._next_fast = 0.0
        self._next_slow = 0.0
        self._last_sent: Optional[dict] = None
        self._last_sent_at = 0.0
        self._send_failed = False

    # --- public API ---

    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        self._stopping.clear()
        self._thread = threading.Thread(target=self._run, name="actions-hub", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stopping.set()
        self._wake.set()
        thread = self._thread
        if thread is not None and thread is not threading.current_thread():
            thread.join(STOP_JOIN_S)
            if thread.is_alive():
                self._log("hub: thread did not stop within %.0f s" % STOP_JOIN_S)

    def handle(self, action: dict) -> None:
        """Queue an ACTION for the hub thread (callable from any thread)."""
        if self._stopping.is_set():
            return
        self._actions.put(action)
        self._wake.set()

    # --- thread ---

    def _run(self) -> None:
        uninit = None
        try:
            uninit = self._com_init()
            while not self._stopping.is_set():
                self._tick(self._clock())
                self._wake.wait(self._wait_s())
                self._wake.clear()
        except Exception as e:  # noqa: BLE001 - never die silently
            self._log(f"hub: thread crashed: {e!r}")
        finally:
            if uninit is not None:
                try:
                    uninit()
                except Exception as e:  # noqa: BLE001
                    self._log(f"hub: CoUninitialize failed: {e!r}")

    def _wait_s(self) -> float:
        due = min(self._next_fast, self._next_slow, self._last_sent_at + self._refresh_s)
        return max(0.0, min(due - self._clock(), self._poll_slow_s))

    # --- one iteration (hub thread) ---

    def _tick(self, now: float) -> None:
        force = self._drain_actions()
        if force:
            now = self._clock()
        if force or now >= self._next_slow:
            for name in _SLOW:
                self._poll(name)
            self._next_slow = now + self._poll_slow_s
            self._next_fast = now + self._poll_fast_s
            self._poll_fast_names()
        elif now >= self._next_fast:
            self._poll_fast_names()
            self._next_fast = now + self._poll_fast_s
        self._maybe_send(now)

    def _poll_fast_names(self) -> None:
        for name in _FAST:
            self._poll(name)

    def _drain_actions(self) -> bool:
        any_action = False
        while True:
            try:
                action = self._actions.get_nowait()
            except queue.Empty:
                return any_action
            any_action = True
            self._execute(action)

    def _execute(self, action: Any) -> None:
        action_id = action.get("id") if isinstance(action, dict) else None
        key = _route(action_id)
        if key is None:
            self._log(f"hub: unknown action {action_id!r} ignored")
            return
        provider = self._providers.get(key)
        if provider is None:
            self._log(f"hub: action {action_id!r} refused, provider {key!r} is unavailable")
            code: Optional[str] = ACTION_FAILED
        else:
            try:
                code = provider.handle(action)
            except Exception as e:  # noqa: BLE001
                self._log(f"hub: action {action_id!r} raised {e!r}")
                code = ACTION_FAILED
        if code:
            notice: dict = {"code": code}
            drive = action.get("drive")
            if isinstance(drive, str):
                notice["drive"] = drive
            self._notice = notice

    def _poll(self, name: str) -> None:
        provider = self._providers.get(name)
        if provider is None:
            self._snap[name] = None
            return
        try:
            snap = provider.snapshot()
            if not isinstance(snap, dict):
                raise TypeError(f"snapshot is {type(snap).__name__}, not a dict")
        except Exception as e:  # noqa: BLE001
            if name not in self._failed:
                self._failed.add(name)
                self._log(f"hub: provider {name!r} failed: {e!r}")
            self._snap[name] = None
            return
        if name in self._failed:
            self._failed.discard(name)
            self._log(f"hub: provider {name!r} recovered")
        self._snap[name] = snap

    def _section(self, name: str) -> dict:
        snap = self._snap.get(name)
        if snap is None:
            return dict(_UNAVAILABLE)
        section = dict(snap)
        section.setdefault("available", True)  # the clock has no "available" of its own
        return section

    def _build_state(self) -> dict:
        state: dict = {"v": STATE_VERSION}
        for name in ("clock", "battery", "audio", "media", "brightness"):
            state[name] = self._section(name)
        state.update(merge_radio_state(self._snap.get("radios"), self._snap.get("wifi_info"),
                                       self._snap.get("bt_info")))
        usb = self._snap.get("usb")
        drives = usb.get("drives", []) if usb and usb.get("available", True) else []
        state["usb"] = [dict(d) for d in drives]
        return state

    def _maybe_send(self, now: float) -> None:
        state = self._build_state()
        cmp = _comparable(state)
        due = (self._last_sent is None or cmp != self._last_sent or self._notice is not None
               or now - self._last_sent_at >= self._refresh_s)
        if not due:
            return
        out = copy.deepcopy(state)
        if self._notice is not None:
            out["notice"] = dict(self._notice)
        try:
            self._send(out)
        except Exception as e:  # noqa: BLE001 - e.g. the socket closed; the session will stop us
            if not self._send_failed:
                self._send_failed = True
                self._log(f"hub: send failed: {e!r}")
            return
        self._send_failed = False
        self._notice = None
        self._last_sent = cmp
        self._last_sent_at = now


def default_providers(log: Optional[Callable[[str], None]] = None) -> dict:
    """The real providers; one that cannot be built (missing library, not Windows) is left out and the hub
    reports its section as unavailable."""
    log = log or _logger.info
    providers: dict = {}

    def add(name: str, factory: Callable[[], Any]) -> None:
        try:
            providers[name] = factory()
        except (ImportError, OSError, AttributeError) as e:
            log(f"hub: provider {name!r} unavailable: {e!r}")

    def clock() -> Any:
        from actions.clock import ClockProvider
        return ClockProvider()

    def battery() -> Any:
        from actions.battery import BatteryProvider
        return BatteryProvider()

    def media() -> Any:
        from actions.media import MediaProvider
        return MediaProvider()

    def audio() -> Any:
        # Import comtypes / pycaw here, in the building thread, so that no import (which initialises COM
        # for its thread) happens later in the hub thread.
        import pycaw.pycaw  # noqa: F401
        from actions.audio import AudioProvider
        return AudioProvider()

    def brightness() -> Any:
        try:
            import comtypes.client  # noqa: F401
        except ImportError as e:
            log(f"hub: brightness: WMI backend unavailable ({e!r}), DDC/CI only")
        from actions.brightness import BrightnessProvider
        return BrightnessProvider()

    def radios() -> Any:
        from actions.radios import RadiosProvider
        return RadiosProvider()

    def wifi_info() -> Any:
        from actions.wifi_info import WifiInfoProvider
        return WifiInfoProvider()

    def bt_info() -> Any:
        from actions.bt_info import BluetoothInfoProvider
        return BluetoothInfoProvider()

    def usb() -> Any:
        from actions.usb import UsbProvider
        return UsbProvider(log=log)

    for name, factory in (("clock", clock), ("battery", battery), ("media", media), ("audio", audio),
                          ("brightness", brightness), ("radios", radios), ("wifi_info", wifi_info),
                          ("bt_info", bt_info), ("usb", usb)):
        add(name, factory)
    return providers
