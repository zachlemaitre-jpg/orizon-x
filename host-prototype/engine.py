"""Relay engine: waits for the tablet over adb, streams one screen through ffmpeg, injects touch and pen.

The CLI (relay.py) and the PC app (app/) both drive it through a Listener. Threads: one engine thread and, per
session, an ffmpeg stderr pump and a tablet reader.
"""
from __future__ import annotations

import collections
import contextlib
import re
import socket
import subprocess
import threading
import time
import traceback
from dataclasses import dataclass
from enum import Enum
from typing import Any, BinaryIO, Callable, Protocol

import annexb
import injector
import protocol
import tools


class State(Enum):
    STOPPED = "stopped"
    WAITING_DEVICE = "waiting_device"  # adb : pas de tablette, non autorisée, plusieurs…
    WAITING_APP = "waiting_app"  # adb OK, Orizon X pas ouverte sur la tablette
    STREAMING = "streaming"
    ERROR = "error"  # fatal : le moteur s'est arrêté


@dataclass(frozen=True)
class Config:
    output: str = "auto"  # "auto" ou un index ddagrab
    encoder: str = "auto"  # "auto" | "nvenc" | "amf"
    fps: int = 60
    bitrate: str = "30M"


@dataclass(frozen=True)
class StreamStats:
    width: int
    height: int
    fps: int
    latency_avg_ms: float
    latency_max_ms: float
    dropped: int
    rtt_ms: float


class Listener(Protocol):
    """Called from the engine's threads: must not block. `detail` is a French sentence ready to show."""

    def on_state(self, state: State, detail: str) -> None: ...

    def on_log(self, line: str) -> None: ...

    def on_stats(self, stats: StreamStats) -> None: ...


class FatalError(Exception):
    """Stops the engine; the message is shown to the user as is."""


ENCODERS = {
    "nvenc": ["-c:v", "h264_nvenc", "-preset", "p1", "-tune", "ull", "-zerolatency", "1", "-delay", "0"],
    # AMF : -usage ultralowlatency/lowlatency ignorent -g (une seule IDR) ; sans -usage, -latency 1 donne la basse latence en gardant le GOP.
    # -aud 0 : sinon AMF ajoute ses propres AUD, en double avec ceux du bsf h264_metadata.
    "amf": ["-c:v", "h264_amf", "-latency", "1", "-quality", "speed", "-aud", "0"],
}
ENCODER_NAMES = {"nvenc": "NVENC", "amf": "AMF"}
ENCODER_CHOICES = ("auto", "nvenc", "amf")
AUTO_ORDER = ("nvenc", "amf")  # NVENC d'abord (sur secteur), AMF sinon (sur batterie, ou pilote NVIDIA trop ancien)

MAX_FFMPEG_FAILURES = 3
RETRY_DELAY_S = 2.0
STOP_TIMEOUT_S = 3.0
ENCODER_PROBE_TIMEOUT_S = 15

WAITING_APP_DETAIL = "Tablette branchée : ouvre Orizon X dessus."

Run = Callable[..., subprocess.CompletedProcess]
Outputs = list[tuple[int, tuple[int, int] | None]]

_ONLY_DEFAULT_GPU = ("Seuls les écrans du GPU par défaut sont listés "
                     "(sur un portable hybride, ceux branchés sur l'autre GPU n'apparaissent pas).")


def now_us() -> int:
    # perf_counter (QueryPerformanceCounter) : time.monotonic n'a que ~15,6 ms de résolution sous Windows avant 3.13.
    return time.perf_counter_ns() // 1000


class SocketReader:
    """Minimal binary reader over recv(). Unlike makefile(), it lets sock.close() abort a blocked recv on Windows."""

    def __init__(self, sock: socket.socket) -> None:
        self._sock = sock

    def read(self, size: int) -> bytes:
        return self._sock.recv(size)


def probe_outputs(ffmpeg: str, max_outputs: int = 8, run: Run = subprocess.run) -> Outputs:
    """Captures one frame per ddagrab output (default D3D11 adapter) and returns (index, (width, height))."""
    outputs: Outputs = []
    for index in range(max_outputs):
        result = run(
            [ffmpeg, "-nostdin", "-hide_banner", "-f", "lavfi",
             "-i", f"ddagrab=output_idx={index}:framerate=1,hwdownload,format=bgra",
             "-frames:v", "1", "-f", "null", "-"],
            capture_output=True, text=True, errors="replace", creationflags=tools.NO_WINDOW,
        )
        if result.returncode != 0:
            break  # les index sont contigus : le premier échec marque la fin
        size = re.search(r"\b(\d{3,5})x(\d{3,5})\b", result.stderr)
        outputs.append((index, (int(size.group(1)), int(size.group(2))) if size else None))
    return outputs


def describe_outputs(outputs: Outputs) -> str:
    if not outputs:
        return "Aucun écran capturable (ffmpeg/ddagrab indisponible ?)"
    lines = [f"--output {i} : {f'{s[0]}x{s[1]}' if s else 'taille inconnue'}" for i, s in outputs]
    return "\n".join(lines + [_ONLY_DEFAULT_GPU])


def pick_output(choice: str, outputs: Outputs, width: int, height: int) -> int:
    """Explicit index, or ('auto') the first screen whose size matches the tablet's."""
    if choice != "auto":
        return int(choice)
    for index, size in outputs:
        if size == (width, height):
            return index
    raise FatalError(f"Aucun écran en {width}x{height} (taille de la tablette). Règle l'écran virtuel à cette "
                     f"résolution, ou choisis un écran dans les réglages :\n{describe_outputs(outputs)}")


def ffmpeg_command(ffmpeg: str, encoder: str, output: int, fps: int, bitrate: str) -> list[str]:
    return [
        ffmpeg, "-nostdin", "-hide_banner", "-loglevel", "warning",
        # hwdownload : sur le portable hybride l'écran est sur l'AMD et NVENC sur la NVIDIA (corrigé en phase 2).
        "-f", "lavfi", "-i", f"ddagrab=output_idx={output}:framerate={fps},hwdownload,format=bgra",
        *ENCODERS[encoder],
        "-rc", "cbr", "-b:v", bitrate, "-bf", "0", "-g", str(fps),
        "-bsf:v", "h264_metadata=aud=insert", "-f", "h264", "-",
    ]


def probe_encoder(ffmpeg: str, encoder: str, run: Run = subprocess.run) -> bool:
    """True if this hardware encoder can encode one frame right now (driver present, GPU awake)."""
    try:
        result = run(
            [ffmpeg, "-nostdin", "-hide_banner", "-loglevel", "error",
             "-f", "lavfi", "-i", "color=c=black:s=256x256:r=1", "-frames:v", "1",
             *ENCODERS[encoder], "-f", "null", "-"],
            capture_output=True, creationflags=tools.NO_WINDOW, timeout=ENCODER_PROBE_TIMEOUT_S,
        )
    except subprocess.TimeoutExpired:
        return False
    return result.returncode == 0


def resolve_encoder(ffmpeg: str, choice: str, run: Run = subprocess.run) -> tuple[str, str]:
    """(encoder, log line). 'auto' probes NVENC then AMF; a forced encoder is trusted as is."""
    if choice != "auto":
        return choice, f"Encodeur : {ENCODER_NAMES[choice]} (forcé)"
    unavailable: list[str] = []
    for name in AUTO_ORDER:
        if probe_encoder(ffmpeg, name, run):
            suffix = f" ({', '.join(unavailable)} indisponible)" if unavailable else ""
            return name, f"Encodeur : {ENCODER_NAMES[name]}{suffix}"
        unavailable.append(ENCODER_NAMES[name])
    raise FatalError("Aucun encodeur matériel H.264 (AMF/NVENC) disponible.")


def adb_problem(adb: str, run: Run = subprocess.run) -> str | None:
    """None if exactly one authorized device is ready, else a message saying what to do."""
    result = run([adb, "devices"], capture_output=True, text=True, creationflags=tools.NO_WINDOW)
    if result.returncode != 0:
        return f"adb ne répond pas : {result.stderr.strip()}"
    states = [line.split("\t")[1] for line in result.stdout.splitlines()[1:] if "\t" in line]
    if not states:
        return "Aucune tablette détectée : branche le câble USB et active le débogage USB."
    if "unauthorized" in states:
        return "Tablette non autorisée : accepte la demande de débogage USB sur l'écran de la tablette."
    if states.count("device") != 1:
        return f"Il faut exactement une tablette prête. État actuel : {states}"
    return None


def ensure_forward(adb: str, run: Run = subprocess.run) -> str | None:
    """(Re)creates the adb forward; returns a message if it can't. adb drops forwards when the device reconnects."""
    problem = adb_problem(adb, run)
    if problem is not None:
        return problem
    result = run([adb, "forward", f"tcp:{protocol.PORT}", f"tcp:{protocol.PORT}"],
                 capture_output=True, text=True, creationflags=tools.NO_WINDOW)
    if result.returncode != 0:
        return f"adb forward a échoué : {result.stderr.strip()}"
    return None


def format_stats(stats: StreamStats) -> str:
    return (f"{stats.fps:3d} fps | latence moy {stats.latency_avg_ms:5.1f} ms, "
            f"max {stats.latency_max_ms:5.1f} ms | perdues {stats.dropped} | RTT {stats.rtt_ms:.2f} ms")


def stream(source: BinaryIO, send: Callable[[bytes], None], fps: int, stop: threading.Event,
           on_size: Callable[[int, int], None], log: Callable[[str], None]) -> None:
    """Forwards ffmpeg's Annex-B output as TABX messages until EOF or stop."""
    splitter = annexb.AccessUnitSplitter()
    size: tuple[int, int] | None = None
    last_sps: bytes | None = None
    last_pps: bytes | None = None
    bad_sps: bytes | None = None
    while not stop.is_set():
        chunk = source.read1(65536)
        if not chunk:
            return
        for unit in splitter.feed(chunk):
            info = annexb.describe(unit)
            if size is None and not (info.is_idr and info.sps and info.pps):
                continue  # on attend la première IDR avec ses SPS/PPS
            if info.sps is not None and info.pps is not None and (info.sps != last_sps or info.pps != last_pps):
                try:
                    new_size = annexb.parse_sps_size(info.sps)
                except ValueError as e:
                    if info.sps != bad_sps:
                        log(f"SPS illisible ({e}) : unité ignorée")
                        bad_sps = info.sps
                    continue
                if new_size != size:
                    size = new_size
                    on_size(size[0], size[1])
                    send(protocol.encode_config(size[0], size[1], fps))
                    log(f"Flux : {size[0]}x{size[1]} @ {fps} fps")
                codec_config = annexb.START_CODE + info.sps + annexb.START_CODE + info.pps
                send(protocol.encode_video(now_us(), codec_config, protocol.FLAG_CODEC_CONFIG))
                last_sps = info.sps
                last_pps = info.pps
            if info.is_idr and info.sps is None and last_sps is not None:
                unit = annexb.insert_parameter_sets(unit, last_sps, last_pps)
            send(protocol.encode_video(now_us(), unit, protocol.FLAG_KEY if info.is_idr else 0))
