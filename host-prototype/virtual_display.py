"""Lifecycle of the virtual screen: on while a tablet is connected, off a few seconds after it leaves.

The VDD monitor always exists at driver level (``count`` stays 1, see spec §8 and
docs/notes/vdd-control.md); this module only switches its Windows display path on and off with
``display_layout.set_path_active``, like Settings > Display > "Disconnect this display". No pipe
command except PING (``VddController.is_installed``).

Threads: ``prepare``/``release`` run on the engine thread, the grace timer on its own thread and
``apply_layout`` on an app worker thread (via ``RelayEngine.relayout``). One re-entrant lock serialises every Windows call and the timer
state; the waits (``sleep``) happen outside it so the other threads are never blocked for long.
A grace timer that fires after being cancelled sees a newer generation and does nothing.
"""
from __future__ import annotations

import threading
import time
from typing import Any, Callable, NamedTuple

import display_layout
import engine   # module, pas « from engine import » : engine importera ce module (cycle)
import injector
from display_layout import MonitorKey, Rect
from messages import msg

POLL_S = 0.2


class PrepareResult(NamedTuple):
    """The tablet's screen, ready: its rect in desktop pixels, and the mode chosen for it."""
    rect: Rect
    exact: bool                # False : mode le plus proche, la tablette aura des bandes noires
    mode: tuple[int, int]


def daemon_timer(interval: float, function: Callable[[], None]) -> threading.Timer:
    """Default grace timer: a threading.Timer that never keeps the process alive."""
    timer = threading.Timer(interval, function)
    timer.daemon = True
    return timer


def _no_log(_line: str) -> None:
    pass


class VirtualDisplay:
    """Turns the VDD monitor on for a tablet (``prepare``) and off after it leaves (``release``)."""

    def __init__(self, vdd: Any, layout: Any = display_layout, monitors: Callable[[], list] = injector.monitors,
                 clock: Callable[[], float] = time.monotonic, sleep: Callable[[float], None] = time.sleep,
                 timer_factory: Callable[[float, Callable[[], None]], Any] = daemon_timer,
                 grace_s: float = 5.0, appear_timeout_s: float = 10.0,
                 log: Callable[[str], None] = _no_log) -> None:
        self._vdd = vdd
        self._layout = layout
        self._monitors = monitors
        self._clock = clock
        self._sleep = sleep
        self._timer_factory = timer_factory
        self._grace_s = grace_s
        self._appear_timeout_s = appear_timeout_s
        self._log = log
        self._lock = threading.RLock()
        self._timer: Any = None
        self._generation = 0   # incrémenté à chaque release/cancel : un Timer périmé ne fait rien

    # ---------- public ----------

    def cleanup_on_start(self) -> None:
        """Turn the virtual screen off if a crash or Windows left it on. Never raises."""
        self.cancel_release()
        self._deactivate("cleanup")

    def prepare(self, width: int, height: int, dpi: int, position: str, scale: str | int, first_time: bool,
                should_stop: Callable[[], bool]) -> PrepareResult | None:
        """Turn the virtual screen on at the tablet's size and wait for Windows to show it.

        Returns None when ``should_stop()`` becomes true (the screen may be left on: the caller
        releases it as after any session). Raises engine.FatalError with display.vdd_missing,
        display.no_mode, display.activate_failed or display.timeout. On ``first_time`` the position
        and the scale are applied; their failures are only logged.
        """
        self.cancel_release()
        if not self._vdd.is_installed():
            raise engine.FatalError(msg("display.vdd_missing"))
        deadline = self._clock() + self._appear_timeout_s

        monitor = self._wait_for(self._find_monitor, deadline, should_stop)
        if monitor is None:
            return None
        mode = self._pick_mode(monitor, width, height)
        if should_stop():
            return None
        self._activate(mode)

        rect = self._wait_for(lambda: self._locate(mode), deadline, should_stop)
        if rect is None:
            return None
        self._log(f"Virtual screen on: {mode[0]}x{mode[1]} at ({rect.left},{rect.top})"
                  + ("" if mode == (width, height) else f" (nearest mode for a {width}x{height} tablet)"))
        if first_time:
            with self._lock:
                self._apply_layout(position, scale, dpi)
            rect = self._locate(mode) or rect
        return PrepareResult(rect, mode == (width, height), mode)

    def release(self, immediate: bool = False) -> None:
        """Turn the virtual screen off after the grace delay, or now when ``immediate`` (Quit)."""
        with self._lock:
            self._cancel_timer()
            if immediate:
                self._deactivate("release")
                return
            generation = self._generation
            self._timer = self._timer_factory(self._grace_s, lambda: self._grace_over(generation))
            self._timer.start()

    def cancel_release(self) -> None:
        """Keep the virtual screen: the tablet came back within the grace delay."""
        with self._lock:
            self._cancel_timer()

    def apply_layout(self, position: str, scale: str | int, dpi: int) -> Rect | None:
        """Move and scale the virtual screen now (settings changed while streaming). Never raises.

        Returns where the screen now is (the touch target), or None if it is off or cannot be located.
        """
        with self._lock:
            size = self._apply_layout(position, scale, dpi)
            return self._locate(size) if size is not None else None

    # ---------- steps ----------

    def _wait_for(self, probe: Callable[[], Any], deadline: float, should_stop: Callable[[], bool]) -> Any:
        """``probe()`` every POLL_S until it gives something; None if stopped; display.timeout at ``deadline``."""
        while True:
            if should_stop():
                self._log("Virtual screen: preparation stopped")
                return None
            found = probe()
            if found is not None:
                return found
            if self._clock() >= deadline:
                raise engine.FatalError(msg("display.timeout"))
            self._sleep(POLL_S)

    def _find_monitor(self) -> Any:
        try:
            with self._lock:
                return self._layout.find_vdd_monitor()
        except Exception as e:  # noqa: BLE001 - réessayé jusqu'au délai maximal
            self._log(f"Virtual screen: cannot list the displays: {e}")
            return None

    def _modes(self, key: MonitorKey) -> list[tuple[int, int]]:
        try:
            with self._lock:
                return list(self._layout.available_modes(key))
        except Exception as e:  # noqa: BLE001
            self._log(f"Virtual screen: cannot read its modes: {e}")
            return []

    def _pick_mode(self, monitor: Any, width: int, height: int) -> tuple[int, int]:
        modes = self._modes(monitor.key)
        if not modes and not monitor.active:
            # Une source sans écran allumé peut ne lister aucun mode : on allume, puis on relit.
            self._log("Virtual screen: no modes while off, turning it on to read them")
            self._set_path(monitor.key, None)
            monitor = self._find_monitor() or monitor
            modes = self._modes(monitor.key)
        mode = self._layout.pick_mode(modes, width, height)
        if mode is None:
            self._log(f"Virtual screen: no mode fits {width}x{height} among {modes}")
            raise engine.FatalError(msg("display.no_mode", width=width, height=height))
        return mode

    def _activate(self, mode: tuple[int, int]) -> None:
        """Turn the path on at ``mode``, or resize it in place; nothing if it already is at ``mode``."""
        with self._lock:
            monitor = self._find_monitor()
            if monitor is None:
                raise engine.FatalError(msg("display.timeout"))
            if monitor.active and monitor.rect is not None and (monitor.rect.width, monitor.rect.height) == mode:
                return
            if monitor.active:
                self._set_path(monitor.key, mode)
                return
            try:
                self._layout.set_path_active(monitor.key, True, mode=mode)
                return
            except Exception as e:  # noqa: BLE001
                # Windows peut refuser d'allumer et de changer de mode d'un coup : en deux temps.
                self._log(f"Virtual screen: activation with mode {mode[0]}x{mode[1]} refused ({e}), "
                          "trying in two steps")
            self._set_path(monitor.key, None)
            self._set_path(monitor.key, mode)

    def _set_path(self, key: MonitorKey, mode: tuple[int, int] | None) -> None:
        with self._lock:
            try:
                self._layout.set_path_active(key, True, mode=mode)
            except Exception as e:  # noqa: BLE001
                self._log(f"Virtual screen: cannot turn it on: {e}")
                raise engine.FatalError(msg("display.activate_failed", error=str(e))) from e

    def _locate(self, mode: tuple[int, int]) -> Rect | None:
        """The Windows monitor of the virtual screen, once it has the ``mode`` size; else None."""
        try:
            listed = self._monitors()
        except Exception as e:  # noqa: BLE001
            self._log(f"Virtual screen: cannot list the monitors: {e}")
            return None
        matches = [rect for rect, _primary, _name in listed if (rect.width, rect.height) == mode]
        if len(matches) <= 1:
            return matches[0] if matches else None
        # Plusieurs écrans de cette taille : celui dont le rectangle est celui du moniteur VDD.
        monitor = self._find_monitor()
        if monitor is not None and monitor.rect in matches:
            return monitor.rect
        return None

    def _apply_layout(self, position: str, scale: str | int, dpi: int) -> tuple[int, int] | None:
        """Position then scale of the active virtual screen; every failure is logged. Lock held.

        Returns the screen's size, or None if it is off."""
        monitor = self._find_monitor()
        if monitor is None or not monitor.active or monitor.rect is None:
            self._log("Virtual screen: off, layout not applied")
            return None
        size = (monitor.rect.width, monitor.rect.height)
        try:
            primary = next(rect for rect, is_primary, _name in self._monitors() if is_primary)
            x, y = self._layout.place(primary, size, position)
            self._layout.set_position(monitor.key, x, y)
            self._log(f"Virtual screen placed {position} of the main screen, at ({x},{y})")
        except Exception as e:  # noqa: BLE001 - la disposition n'est jamais fatale
            self._log(f"Virtual screen: cannot place it {position}: {e!r}")
        try:
            percent = self._layout.auto_scale(dpi) if scale == "auto" else int(scale)
            applied = self._layout.set_scale(monitor.key, percent)
            self._log(f"Virtual screen scale: {applied} %")
        except Exception as e:  # noqa: BLE001
            self._log(f"Virtual screen: cannot set the scale {scale!r}: {e!r}")
        return size

    # ---------- release ----------

    def _cancel_timer(self) -> None:
        """Lock held. Cancels the pending release; a timer already firing becomes stale."""
        self._generation += 1
        if self._timer is not None:
            self._timer.cancel()
            self._timer = None

    def _grace_over(self, generation: int) -> None:
        with self._lock:
            if generation != self._generation:
                return
            self._timer = None
            self._deactivate("grace over")

    def _deactivate(self, reason: str) -> None:
        """Turn the path off if it is on. Never raises."""
        with self._lock:
            try:
                monitor = self._layout.find_vdd_monitor()
                if monitor is None:
                    self._log(f"Virtual screen ({reason}): no VDD monitor, nothing to turn off")
                    return
                if not monitor.active:
                    return
                self._layout.set_path_active(monitor.key, False)
                self._log(f"Virtual screen off ({reason})")
            except Exception as e:  # noqa: BLE001
                self._log(f"Virtual screen ({reason}): cannot turn it off: {e!r}")
