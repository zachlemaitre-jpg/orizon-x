"""Bridges the relay engine (its own threads) to Qt (GUI thread) and owns start, stop and restart."""
from __future__ import annotations

import dataclasses
import threading
import time
from typing import Callable, Protocol

from PySide6.QtCore import QObject, Signal

from engine import STOP_TIMEOUT_S, STOPPED_DETAIL, Config, DisplayInfo, Listener, State, StreamStats
from messages import MessageError, Msg, msg


class Engine(Protocol):
    def start(self) -> None: ...

    def stop(self, immediate_display_release: bool = False) -> None: ...

    def is_running(self) -> bool: ...

    def relayout(self, position: str, scale: str) -> bool: ...


EngineFactory = Callable[[Config, Listener], Engine]


class _EngineListener:
    """One per engine: forwards its callbacks only while it is the controller's latest engine.

    A replaced engine can still call back while it stops (STOPPED, last log lines): showing them would
    say « Arrêté » over a stream that the new engine is running.
    """

    def __init__(self, controller: Controller, generation: int) -> None:
        self._controller = controller
        self._generation = generation

    def on_state(self, state: State, detail: Msg) -> None:
        self._controller._forward(self._generation, self._controller.on_state, state, detail)

    def on_log(self, line: str) -> None:
        self._controller._forward(self._generation, self._controller.on_log, line)

    def on_stats(self, stats: StreamStats) -> None:
        self._controller._forward(self._generation, self._controller.on_stats, stats)

    def on_display(self, info: DisplayInfo) -> None:
        self._controller._forward(self._generation, self._controller.on_display, info)


class Controller(QObject):
    """Re-emits the current engine's Listener callbacks (received through _EngineListener) as Qt signals.

    Signals emitted from engine threads are queued to the GUI thread, so slots never touch widgets off-thread.
    """

    state_changed = Signal(object, object)  # (State, Msg)
    log = Signal(str)
    stats = Signal(object)
    display_changed = Signal(object)  # DisplayInfo : écran virtuel de la session, une fois allumé

    def __init__(self, factory: EngineFactory, config: Config, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._factory = factory
        self._config = config
        self._engine: Engine | None = None
        self._generation = 0  # numéro du dernier moteur créé ; un arrêt ne le change pas (son STOPPED compte)
        # Intention de l'utilisateur : un redémarrage en cours ne relance le moteur que si personne ne l'a arrêté entre-temps.
        self._want_running = False
        self._restarts: list[threading.Thread] = []  # redémarrages en cours, attendus par stop_blocking
        # RLock : un signal émis depuis le thread Qt appelle ses slots tout de suite, et ils peuvent relancer une commande.
        self._lock = threading.RLock()
        self.state = State.STOPPED
        self.detail: Msg = STOPPED_DETAIL
        self.state_changed.connect(self._remember)

    @property
    def config(self) -> Config:
        return self._config

    def _remember(self, state: State, detail: Msg) -> None:
        self.state = state
        self.detail = detail

    # --- Listener (appelé depuis les threads du moteur) ---

    def on_state(self, state: State, detail: Msg) -> None:
        self.state_changed.emit(state, detail)

    def on_log(self, line: str) -> None:
        self.log.emit(line)

    def on_stats(self, stats: StreamStats) -> None:
        self.stats.emit(stats)

    def on_display(self, info: DisplayInfo) -> None:
        self.display_changed.emit(info)

    def _forward(self, generation: int, emit: Callable[..., None], *args: object) -> None:
        # Vérification et émission sous le verrou : aucun nouveau moteur ne peut naître entre les deux.
        # Depuis un thread du moteur, emit() ne fait que mettre le signal en file : le verrou n'est tenu qu'un instant.
        with self._lock:
            if generation == self._generation:
                emit(*args)

    # --- commandes (thread Qt) ---

    def start(self) -> None:
        with self._lock:
            self._want_running = True
            self._start_locked()

    def stop(self, immediate_display_release: bool = False) -> threading.Thread | None:
        """Non-blocking: the engine's stop (up to 3 s) runs in a worker thread, returned for tests."""
        with self._lock:
            self._want_running = False
            engine, self._engine = self._engine, None
        if engine is None:
            return None
        worker = threading.Thread(target=engine.stop, name="engine-stop", daemon=True,
                                  kwargs={"immediate_display_release": immediate_display_release})
        worker.start()
        return worker

    def stop_blocking(self, immediate_display_release: bool = False) -> None:
        """For Quit: returns once every touch contact is lifted and ffmpeg is gone, pending restarts included.

        immediate_display_release (Quit): the virtual screen goes off now instead of after the grace delay. An old
        engine still stopping in a pending restart keeps its grace: the app turns the screen off itself after this.
        """
        with self._lock:
            self._want_running = False
            engine, self._engine = self._engine, None
            restarts, self._restarts = self._restarts, []
        if engine is not None:
            engine.stop(immediate_display_release=immediate_display_release)
        deadline = time.monotonic() + STOP_TIMEOUT_S + 0.5
        for worker in restarts:  # l'ancien moteur d'un redémarrage s'arrête dans ce thread-là
            worker.join(max(0.0, deadline - time.monotonic()))

    def restart(self, config: Config, immediate_display_release: bool = False) -> threading.Thread:
        """Stops then starts with the new config, unless stop() or stop_blocking() is called in between.

        immediate_display_release: the old engine turns the virtual screen off at once (switch to Duplicate).
        """
        def work() -> None:
            with self._lock:
                old, self._engine = self._engine, None
                self._config = config
            # Hors du verrou : l'arrêt prend jusqu'à 3 s, un clic pendant ce temps ne doit pas figer le thread Qt.
            if old is not None:
                old.stop(immediate_display_release=immediate_display_release)
            with self._lock:
                if self._want_running:
                    self._start_locked()  # sans effet si un start() a déjà relancé un moteur entre-temps

        worker = threading.Thread(target=work, name="engine-restart", daemon=True)
        with self._lock:
            self._want_running = True
            self._restarts = [t for t in self._restarts if t.is_alive()] + [worker]
        worker.start()
        return worker

    def relayout(self, position: str, scale: str) -> threading.Thread | None:
        """Position/Scale changed: kept for the next engines, and applied by the running one in a worker thread
        (Windows takes about a second to move a screen). Returns that thread (for tests), or None without engine."""
        with self._lock:
            self._config = dataclasses.replace(self._config, position=position, scale=scale)
            engine = self._engine
        if engine is None:
            return None
        worker = threading.Thread(target=engine.relayout, args=(position, scale), name="engine-relayout",
                                  daemon=True)
        worker.start()
        return worker

    def _start_locked(self) -> None:
        if self._engine is not None and self._engine.is_running():
            return
        self._generation += 1  # les rappels des moteurs précédents sont désormais ignorés
        try:
            self._engine = self._factory(self._config, _EngineListener(self, self._generation))
        except Exception as e:  # noqa: BLE001 — ex. ToolMissing : on l'affiche au lieu de planter
            self._engine = None
            self.on_state(State.ERROR, e.msg if isinstance(e, MessageError) else msg("error.unexpected", error=str(e)))
            return
        self._engine.start()
