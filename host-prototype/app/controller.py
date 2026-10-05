"""Bridges the relay engine (its own threads) to Qt (GUI thread) and owns start, stop and restart."""
from __future__ import annotations

import threading
from typing import Callable, Protocol

from PySide6.QtCore import QObject, Signal

from engine import Config, Listener, State, StreamStats


class Engine(Protocol):
    def start(self) -> None: ...

    def stop(self) -> None: ...

    def is_running(self) -> bool: ...


EngineFactory = Callable[[Config, Listener], Engine]


class Controller(QObject):
    """Engine Listener whose callbacks are re-emitted as Qt signals.

    Signals emitted from engine threads are queued to the GUI thread, so slots never touch widgets off-thread.
    """

    state_changed = Signal(object, str)
    log = Signal(str)
    stats = Signal(object)

    def __init__(self, factory: EngineFactory, config: Config, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._factory = factory
        self._config = config
        self._engine: Engine | None = None
        self._lock = threading.Lock()
        self.state = State.STOPPED
        self.detail = "Arrêté."
        self.state_changed.connect(self._remember)

    @property
    def config(self) -> Config:
        return self._config

    def _remember(self, state: State, detail: str) -> None:
        self.state = state
        self.detail = detail

    # --- Listener (appelé depuis les threads du moteur) ---

    def on_state(self, state: State, detail: str) -> None:
        self.state_changed.emit(state, detail)

    def on_log(self, line: str) -> None:
        self.log.emit(line)

    def on_stats(self, stats: StreamStats) -> None:
        self.stats.emit(stats)

    # --- commandes (thread Qt) ---

    def start(self) -> None:
        with self._lock:
            self._start_locked()

    def stop(self) -> threading.Thread | None:
        """Non-blocking: the engine's stop (up to 3 s) runs in a worker thread, returned for tests."""
        with self._lock:
            engine, self._engine = self._engine, None
        if engine is None:
            return None
        worker = threading.Thread(target=engine.stop, name="engine-stop", daemon=True)
        worker.start()
        return worker

    def stop_blocking(self) -> None:
        """For Quit: returns once every touch contact is lifted and ffmpeg is gone."""
        with self._lock:
            engine, self._engine = self._engine, None
        if engine is not None:
            engine.stop()

    def restart(self, config: Config) -> threading.Thread:
        def work() -> None:
            with self._lock:
                old, self._engine = self._engine, None
                self._config = config
                if old is not None:
                    old.stop()
                self._start_locked()

        worker = threading.Thread(target=work, name="engine-restart", daemon=True)
        worker.start()
        return worker

    def _start_locked(self) -> None:
        if self._engine is not None and self._engine.is_running():
            return
        try:
            self._engine = self._factory(self._config, self)
        except Exception as e:  # noqa: BLE001 — ex. ToolMissing : on l'affiche au lieu de planter
            self._engine = None
            self.on_state(State.ERROR, str(e))
            return
        self._engine.start()
