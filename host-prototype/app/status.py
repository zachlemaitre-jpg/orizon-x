"""Per-state texts and colours, shared by the window and the tray icon (no Qt here)."""
from __future__ import annotations

from engine import State, StreamStats

TITLES = {
    State.STOPPED: "Arrêté",
    State.WAITING_DEVICE: "En attente de la tablette",
    State.WAITING_APP: "Ouvre Orizon X sur la tablette",
    State.STREAMING: "Connecté",
    State.ERROR: "Erreur",
}

COLORS = {
    State.STOPPED: "#8A8F98",
    State.WAITING_DEVICE: "#F5B544",
    State.WAITING_APP: "#F5B544",
    State.STREAMING: "#4ADE80",
    State.ERROR: "#F87171",
}

_ACTIVE = frozenset({State.WAITING_DEVICE, State.WAITING_APP, State.STREAMING})


def is_active(state: State) -> bool:
    """True while the engine runs (the button stops it)."""
    return state in _ACTIVE


def primary_label(state: State) -> str:
    if is_active(state):
        return "Arrêter"
    return "Réessayer" if state is State.ERROR else "Démarrer"


def detail_for(state: State, detail: str) -> str:
    return "Clique sur Démarrer." if state is State.STOPPED else detail


def stream_detail(stats: StreamStats) -> str:
    return f"{stats.width}×{stats.height} · {stats.fps} fps · {round(stats.latency_avg_ms)} ms"
