"""Per-state texts and colours, shared by the window and the tray icon (no Qt here)."""
from __future__ import annotations

from engine import State, StreamStats
from messages import Msg, tr

TITLE_KEYS = {
    State.STOPPED: "status.stopped",
    State.WAITING_DEVICE: "status.waiting_device",
    State.WAITING_APP: "status.waiting_app",
    State.PREPARING_DISPLAY: "status.preparing_display",
    State.STREAMING: "status.streaming",
    State.ERROR: "status.error",
}

COLORS = {
    State.STOPPED: "#8A8F98",
    State.WAITING_DEVICE: "#F5B544",
    State.WAITING_APP: "#F5B544",
    State.PREPARING_DISPLAY: "#F5B544",
    State.STREAMING: "#4ADE80",
    State.ERROR: "#F87171",
}

_ACTIVE = frozenset({State.WAITING_DEVICE, State.WAITING_APP, State.PREPARING_DISPLAY, State.STREAMING})


def is_active(state: State) -> bool:
    """True while the engine runs (the button stops it)."""
    return state in _ACTIVE


def title(state: State, lang: str) -> str:
    return tr(TITLE_KEYS[state], lang)


def primary_label(state: State, lang: str) -> str:
    if is_active(state):
        return tr("button.stop", lang)
    return tr("button.retry" if state is State.ERROR else "button.start", lang)


def detail_for(state: State, detail: Msg | None, lang: str) -> str:
    if state is State.STOPPED:
        return tr("status.click_start", lang)
    return detail.text(lang) if detail is not None else ""


def stream_detail(stats: StreamStats) -> str:
    return f"{stats.width}×{stats.height} · {stats.fps} fps · {round(stats.latency_avg_ms)} ms"
