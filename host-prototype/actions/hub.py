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
"usb": [...], "now_playing", "context", "keyboard", "trackpad", "gamepad", "claude", "launchers", optional "notice"}``. Every object section carries ``"available"``; ``wifi`` / ``bluetooth`` /
``airplane`` come from ``merge_radio_state(radios, wifi_info, bt_info)`` (see actions.radios); ``usb`` is the list
of drives. A section whose provider is missing or raising is ``{"available": False}`` (``[]`` for usb) until the
provider answers again; the failure is logged once per streak.

A state is sent when it differs from the last one sent, or ``refresh_s`` after the last send. The clock's
``epoch_ms`` is left out of that comparison (it changes at every poll; the device ticks it locally and the periodic
refresh resynchronises it); a change of UTC offset still counts. ``notice`` (``{"code": ..., "drive": ...}``) is put
in the next state only, and that state is sent even if nothing else changed.

Cover art (spec §7): ``now_playing.artwork`` is the sha1 of the current cover (actions.now_playing). When a state
to send references a cover the device does not hold (the device keeps only the last one received), the hub first
calls ``send_artwork(id, image)`` with the provider's ``artwork_bytes(id)``, then ``send(state)``. A cover that cannot
be sent (no ``send_artwork`` callback, no bytes, or ``send_artwork`` raised ValueError: not encodable) is replaced
by ``None`` in the state; another error of ``send_artwork`` (the socket closed) holds the state back as well, and
both are tried again at the next poll.

Icons (spec app-icon §3): ``context.icon`` is the sha1 of the icon of the app (or site) in front, produced by the
``context`` provider, whose ``artwork_bytes(id)`` gives the PNG. The device keeps only a small image cache shared with
the covers, so the image is sent (MEDIA_ARTWORK, before the state) every time ``context.icon`` changes to an id other
than the one of the last state broadcast, not once per session; an icon that cannot be sent is replaced by ``None``
in the state, like a cover.

The ``context`` section (actions.context, the context bar) is polled with the fast group (250 ms), like audio: the
bar must follow the foreground app. Its actions are ``context.*``.

The ``keyboard`` section (actions.keyboard, the device's PC keyboard) carries the layout to draw; its layout is read
in the slow group. The ``trackpad`` section (actions.trackpad, the device's trackpad) is just ``{"available": True}``;
the ``gamepad`` section (actions.gamepad, the virtual Xbox controller) is ``{"available": True}`` or
``{"available": False, "reason": ...}``, read in the slow group.

The ``claude`` section (actions.claude_code, the Claude Code sessions of the PC, read-only) is read in the slow group: it is
``{"available": False}`` or the sessions and connectors. ``claude.focus`` is a normal action (hub thread, a poll
afterwards, a ``claude_not_running`` notice when the Claude app is not running).

The ``launchers`` section (actions.launchers: Settings, Discord, Spotify, Downloads tiles) is read in the slow group; its
``icons`` (sha1 of the real icon of Discord's and Spotify's exe) are sent as MEDIA_ARTWORK before the state that
references them, whenever one changes to an id other than the last broadcast one, like the context bar's icon.
``launch.open`` is a normal action (hub thread, a poll afterwards, the notice ``app_not_found`` on failure).

Input actions (``keyboard.*``: about 30 a second while a key repeats, ``trackpad.*``: up to 60 moves a second,
``gamepad.*``: up to 125 reports a second) run on their OWN thread (``actions-input``), started and stopped with the hub:
the poll of the slow group can block the hub thread for a second or more (brightness, Bluetooth, Wi-Fi, media), and the
input must not wait behind it. ``handle()`` puts them in a separate queue; the input thread runs them at once, in order
of arrival, after merging consecutive ``trackpad.move`` (sum of dx and dy) and consecutive ``trackpad.scroll`` (sum)
that are queued together: any other action between two moves is a barrier. They never make the hub poll every provider
again, never produce a notice, and a provider that raises is logged. So the providers' ``handle()`` runs on the input
thread while their ``snapshot()`` runs on the hub thread: those providers are thread-safe. When the input thread is
not running (a hub driven by ``_tick`` in the tests), the hub thread runs the queued input itself, the same way.

``stop()`` joins the input thread and the hub thread, then calls ``stop()`` of every provider that has one (the keyboard
releases the keys that are down, the trackpad its buttons, the gamepad its pad), whether or not the hub was started and
whatever happened to its threads; one that fails is logged and does not prevent the others. Input still queued at that
point is dropped (the providers' ``stop()`` releases everything that is held). The engine calls ``hub.stop()`` in a ``finally`` at the end of every Actions session (the
device leaves, the connection drops, the role changes, the engine stops).

Provider keys in the ``providers`` dict: clock, battery, audio, media, brightness, radios, wifi_info, bt_info, usb,
now_playing, context, keyboard, trackpad, gamepad, claude, launchers.
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
    ("context.", "context"),
    ("keyboard.", "keyboard"),
    ("trackpad.", "trackpad"),
    ("gamepad.", "gamepad"),
    ("claude.", "claude"),
    ("launch.", "launchers"),
)
_QUIET = ("keyboard.", "trackpad.", "gamepad.")  # input actions: own thread, no re-poll (see the module docstring)
_MERGE_LIMIT = 2000.0  # the provider clamp of a move / scroll: a merged delta never goes beyond it

_FAST = ("audio", "context")
_SLOW = ("clock", "battery", "media", "brightness", "radios", "wifi_info", "bt_info", "usb", "now_playing", "keyboard", "trackpad", "gamepad", "claude", "launchers")
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


def _container(state: dict, path: str) -> Any:
    """``state["a"]["b"]`` for the dotted path ``"a.b"`` (None if a step is missing)."""
    node: Any = state
    for step in path.split("."):
        node = node.get(step) if isinstance(node, dict) else None
    return node


def _number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and value == value and abs(value) != float("inf")


def _merge_input(actions: list) -> list:
    """The input actions with consecutive ``trackpad.move`` (and consecutive ``trackpad.scroll``) summed. Only
    adjacent actions of the same id merge (anything else in between is a barrier), only when all four deltas are
    plain numbers and the sums stay within the provider's clamp; the actions given are never modified."""
    out: list = []
    for action in actions:
        previous = out[-1] if out else None
        if (isinstance(action, dict) and isinstance(previous, dict) and action.get("id") == previous.get("id")
                and action.get("id") in ("trackpad.move", "trackpad.scroll")
                and all(_number(x) for x in (action.get("dx"), action.get("dy"), previous.get("dx"), previous.get("dy")))
                and abs(action["dx"] + previous["dx"]) <= _MERGE_LIMIT
                and abs(action["dy"] + previous["dy"]) <= _MERGE_LIMIT):
            out[-1] = dict(previous, dx=previous["dx"] + action["dx"], dy=previous["dy"] + action["dy"])
        else:
            out.append(action)
    return out


class ActionsHub:
    def __init__(self, providers: dict, send: Callable[[dict], None], *,
                 send_artwork: Optional[Callable[[str, bytes], None]] = None,
                 clock: Callable[[], float] = time.monotonic,
                 poll_fast_s: float = 0.25, poll_slow_s: float = 1.0, refresh_s: float = 30.0,
                 log: Optional[Callable[[str], None]] = None,
                 com_init: Callable[[], Optional[Callable[[], None]]] = _com_init) -> None:
        self._providers = providers
        self._send = send
        self._send_artwork = send_artwork
        self._clock = clock
        self._poll_fast_s = poll_fast_s
        self._poll_slow_s = poll_slow_s
        self._refresh_s = refresh_s
        self._log = log or _logger.info
        self._com_init = com_init

        self._actions: "queue.Queue[dict]" = queue.Queue()
        self._input: "queue.Queue[Any]" = queue.Queue()  # input actions (and the stop sentinel None)
        self._wake = threading.Event()
        self._stopping = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._input_thread: Optional[threading.Thread] = None
        self._input_lock = threading.Lock()  # one runner of the input queue at a time
        self._input_logged: set[str] = set()

        # Only touched by the hub thread (or by tests driving _tick directly).
        self._snap: dict[str, Optional[dict]] = {}
        self._failed: set[str] = set()
        self._notice: Optional[dict] = None
        self._next_fast = 0.0
        self._next_slow = 0.0
        self._last_sent: Optional[dict] = None
        self._last_sent_at = 0.0
        self._send_failed = False
        self._artwork_sent: Optional[str] = None  # the cover the device holds (it keeps only the last one)
        self._artwork_refused: Optional[str] = None  # a cover send_artwork could not encode: never retried
        self._artwork_logged: Optional[str] = None
        self._icon_broadcast: Optional[str] = None  # context.icon of the last state sent
        self._icons_refused: set[str] = set()  # icons send_artwork could not encode: never retried
        self._launcher_broadcast: dict = {}  # launchers.icons of the last state sent: name -> id

    # --- public API ---

    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        self._stopping.clear()
        self._thread = threading.Thread(target=self._run, name="actions-hub", daemon=True)
        self._thread.start()
        if self._input_thread is None or not self._input_thread.is_alive():
            self._drop_input()
            self._input_thread = threading.Thread(target=self._run_input, name="actions-input", daemon=True)
            self._input_thread.start()

    def stop(self) -> None:
        self._stopping.set()
        self._wake.set()
        self._input.put(None)  # wakes the input thread, which stops
        for thread, what in ((self._input_thread, "input thread"), (self._thread, "thread")):
            if thread is not None and thread is not threading.current_thread():
                thread.join(STOP_JOIN_S)
                if thread.is_alive():
                    self._log("hub: %s did not stop within %.0f s" % (what, STOP_JOIN_S))
        self._stop_providers()

    def _stop_providers(self) -> None:
        for name, provider in list(self._providers.items()):
            stopper = getattr(provider, "stop", None)
            if not callable(stopper):
                continue
            try:
                stopper()
            except Exception as e:  # noqa: BLE001 - the other providers must be stopped too
                self._log(f"hub: provider {name!r} did not stop cleanly: {e!r}")

    def handle(self, action: dict) -> None:
        """Queue an ACTION (callable from any thread): input actions for the input thread, the others for the hub
        thread."""
        if self._stopping.is_set():
            return
        action_id = action.get("id") if isinstance(action, dict) else None
        if isinstance(action_id, str) and action_id.startswith(_QUIET):
            self._input.put(action)
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

    # --- input thread ---

    def _drop_input(self) -> None:
        while True:
            try:
                self._input.get_nowait()
            except queue.Empty:
                return

    def _run_input(self) -> None:
        try:
            while not self._stopping.is_set():
                item = self._input.get()
                if item is None or self._stopping.is_set():
                    continue
                self._run_input_batch([item])
        except Exception as e:  # noqa: BLE001 - never die silently
            self._log(f"hub: input thread crashed: {e!r}")

    def _run_input_batch(self, batch: list) -> None:
        """Runs ``batch`` and everything else already queued, merged: the input actions, in order of arrival."""
        while True:
            try:
                item = self._input.get_nowait()
            except queue.Empty:
                break
            if item is not None:
                batch.append(item)
        with self._input_lock:
            for action in _merge_input(batch):
                if self._stopping.is_set():
                    return
                self._execute_input(action)

    def _drain_input(self) -> None:
        """The hub thread runs the queued input itself when the input thread is not running (tests that drive
        ``_tick``)."""
        thread = self._input_thread
        if thread is not None and thread.is_alive():
            return
        batch: list = []
        self._run_input_batch(batch)

    def _execute_input(self, action: Any) -> None:
        action_id = action.get("id") if isinstance(action, dict) else None
        provider = self._providers.get(_route(action_id) or "")
        if provider is None:
            if action_id not in self._input_logged:
                self._input_logged.add(action_id)
                self._log(f"hub: input action {action_id!r} refused, its provider is unavailable")
            return
        try:
            provider.handle(action)  # no notice for input: the return value is not used
        except Exception as e:  # noqa: BLE001
            self._log(f"hub: action {action_id!r} raised {e!r}")

    def _wait_s(self) -> float:
        due = min(self._next_fast, self._next_slow, self._last_sent_at + self._refresh_s)
        return max(0.0, min(due - self._clock(), self._poll_slow_s))

    # --- one iteration (hub thread) ---

    def _tick(self, now: float) -> None:
        self._drain_input()
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
        state["now_playing"] = self._section("now_playing")
        state["context"] = self._section("context")
        state["keyboard"] = self._section("keyboard")
        state["trackpad"] = self._section("trackpad")
        state["gamepad"] = self._section("gamepad")
        state["claude"] = self._section("claude")
        state["launchers"] = self._section("launchers")
        return state

    def _log_artwork_once(self, artwork_id: str, line: str) -> None:
        if self._artwork_logged != artwork_id:
            self._artwork_logged = artwork_id
            self._log(line)

    def _pending_one(self, state: dict, section_name: str, field: str, provider_key: str,
                     held: Callable[[str], bool], refused: Callable[[str], bool]) -> Optional[tuple]:
        """The image ``state[section_name][field]`` (``section_name`` may be a dotted path) references, if it has to be sent before this state:
        (section, field, id, bytes). One that cannot be sent (no send_artwork, no bytes, refused before) is replaced
        by None in the state, so that no state references an image the device lacks. ``held``: the device has it."""
        section = _container(state, section_name)
        if not isinstance(section, dict) or field not in section:
            return None
        artwork_id = section[field]
        if not isinstance(artwork_id, str) or not artwork_id:
            section[field] = None
            return None
        if held(artwork_id):
            return None
        if self._send_artwork is None or refused(artwork_id):
            section[field] = None
            return None
        getter = getattr(self._providers.get(provider_key), "artwork_bytes", None)
        data: Any = None
        if callable(getter):
            try:
                data = getter(artwork_id)
            except Exception as e:  # noqa: BLE001
                self._log_artwork_once(artwork_id, f"hub: artwork {artwork_id} unreadable: {e!r}")
                data = None
        if not isinstance(data, (bytes, bytearray)) or not data:
            section[field] = None
            return None
        return section_name, field, artwork_id, bytes(data)

    def _pending_artworks(self, state: dict) -> list:
        """The images to send before this state: the cover, then the icon."""
        pending = [
            self._pending_one(state, "now_playing", "artwork", "now_playing",
                              lambda i: i == self._artwork_sent, lambda i: i == self._artwork_refused),
            self._pending_one(state, "context", "icon", "context",
                              lambda i: i == self._icon_broadcast, lambda i: i in self._icons_refused),
        ]
        for name in ("discord", "spotify"):  # the real icons of the launcher tiles
            pending.append(self._pending_one(
                state, "launchers.icons", name, "launchers",
                lambda i, name=name: i == self._launcher_broadcast.get(name), lambda i: i in self._icons_refused))
        return [p for p in pending if p is not None]

    def _note_send_failure(self, e: Exception) -> None:
        if not self._send_failed:
            self._send_failed = True
            self._log(f"hub: send failed: {e!r}")

    def _maybe_send(self, now: float) -> None:
        state = self._build_state()
        artworks = self._pending_artworks(state)
        cmp = _comparable(state)
        due = (self._last_sent is None or cmp != self._last_sent or self._notice is not None
               or now - self._last_sent_at >= self._refresh_s or bool(artworks))
        if not due:
            return
        out = copy.deepcopy(state)
        if self._notice is not None:
            out["notice"] = dict(self._notice)
        for section_name, field, artwork_id, data in artworks:  # the images first (cover, icon), then the state
            if self._send_artwork is None:
                break
            try:
                self._send_artwork(artwork_id, data)
            except ValueError as e:  # not encodable (too big...): the state goes without it
                if section_name == "now_playing":
                    self._artwork_refused = artwork_id
                else:
                    self._icons_refused.add(artwork_id)
                self._log_artwork_once(artwork_id, f"hub: artwork {artwork_id} not sent: {e}")
                _container(out, section_name)[field] = None
                _container(state, section_name)[field] = None
                cmp = _comparable(state)
            except Exception as e:  # noqa: BLE001 - the socket closed: no state either (it would reference it)
                self._note_send_failure(e)
                return
            else:
                if section_name == "now_playing":
                    self._artwork_sent = artwork_id
        try:
            self._send(out)
        except Exception as e:  # noqa: BLE001 - e.g. the socket closed; the session will stop us
            self._note_send_failure(e)
            return
        self._send_failed = False
        self._notice = None
        self._last_sent = cmp
        self._last_sent_at = now
        context = state.get("context")
        self._icon_broadcast = context.get("icon") if isinstance(context, dict) else None
        icons = _container(state, "launchers.icons")
        self._launcher_broadcast = dict(icons) if isinstance(icons, dict) else {}


def default_providers(log: Optional[Callable[[str], None]] = None, lang: str = "fr") -> dict:
    """The real providers; one that cannot be built (missing library, not Windows) is left out and the hub
    reports its section as unavailable. ``lang`` is the device's language ("en" or "fr"), for the context bar."""
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

    def now_playing() -> Any:
        from actions.now_playing import NowPlayingProvider
        return NowPlayingProvider()

    def keyboard() -> Any:
        from actions.keyboard import KeyboardProvider
        return KeyboardProvider(log=log)

    def trackpad() -> Any:
        from actions.trackpad import TrackpadProvider
        return TrackpadProvider(log=log)

    def launchers() -> Any:
        from actions.launchers import LaunchersProvider  # detection and icons are read at the first snapshot
        return LaunchersProvider(log=log)

    def claude() -> Any:
        from actions.claude_code import ClaudeCodeProvider  # reads nothing until the first snapshot
        return ClaudeCodeProvider(log=log)

    def gamepad() -> Any:
        from actions.gamepad import GamepadProvider  # the DLL is loaded on the first snapshot, not here
        return GamepadProvider(log=log)

    def context() -> Any:
        try:  # the browser tab's URL is read with UI Automation (comtypes): imported here, in the building thread
            import comtypes.client  # noqa: F401
        except ImportError as e:
            log(f"hub: context: UI Automation unavailable ({e!r}), browser tabs are told by their title only")
        from actions.context import ContextProvider
        return ContextProvider(log=log, lang=lang)

    for name, factory in (("clock", clock), ("battery", battery), ("media", media), ("audio", audio),
                          ("brightness", brightness), ("radios", radios), ("wifi_info", wifi_info),
                          ("bt_info", bt_info), ("usb", usb), ("now_playing", now_playing),
                          ("context", context), ("keyboard", keyboard), ("trackpad", trackpad), ("gamepad", gamepad), ("claude", claude), ("launchers", launchers)):
        add(name, factory)
    return providers
