"""Relay engine: waits for the tablet over adb, streams one screen through ffmpeg, injects touch and pen.

The CLI (relay.py) and the PC app (app/) both drive it through a Listener. Threads: one engine thread and, per
session, a tablet reader and an ffmpeg stderr pump.

Session order: HELLO → tablet reader (answers PING from then on) → screen choice → ffmpeg. In Extend mode with a
virtual display (the app), the screen choice is PREPARING_DISPLAY: display.prepare() turns the virtual screen on
at the tablet's size, then ddagrab is probed to find it. Duplicate mode captures the main screen. Without a
display (CLI, tests), Config.output picks the screen as before.
"""
from __future__ import annotations

import collections
import contextlib
import dataclasses
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
from inputstate import Rect
from messages import MessageError, Msg, msg


class State(Enum):
    STOPPED = "stopped"
    WAITING_DEVICE = "waiting_device"  # adb : pas de tablette, non autorisée, plusieurs…
    WAITING_APP = "waiting_app"  # adb OK, Orizon X pas ouverte sur la tablette
    PREPARING_DISPLAY = "preparing_display"  # tablette connectée, écran virtuel en cours d'allumage
    STREAMING = "streaming"
    ERROR = "error"  # fatal : le moteur s'est arrêté


MODES = ("extend", "duplicate")  # valeurs de Config.mode ; toute autre valeur se comporte comme sans écran virtuel


@dataclass(frozen=True)
class Config:
    output: str = "auto"  # "auto" ou un index ddagrab (sans écran virtuel : CLI, Duplicate)
    encoder: str = "auto"  # "auto" | "nvenc" | "amf"
    fps: int = 60
    bitrate: str = "30M"
    mode: str = "extend"  # "extend" : écran virtuel (si l'engine en a un) | "duplicate" : écran principal
    position: str = "right"  # right | left | above | below : place de l'écran virtuel (1re apparition)
    scale: str = "auto"  # "auto" ou un pourcentage ("150") : échelle de l'écran virtuel (1re apparition)


@dataclass(frozen=True)
class DisplayInfo:
    """The virtual screen of the current session, given to Listener.on_display once it is on.

    exact is False when the virtual display has no mode at the tablet's size: `mode` is the nearest one and the
    tablet shows black bars (the app then offers "Add exact resolution" for tablet_size).
    """
    tablet_size: tuple[int, int]
    mode: tuple[int, int]
    exact: bool
    rect: Rect


class Display(Protocol):
    """What the engine needs from virtual_display.VirtualDisplay (not imported here: it imports this module)."""

    def prepare(self, width: int, height: int, dpi: int, position: str, scale: str, first_time: bool,
                should_stop: Callable[[], bool]) -> Any: ...  # PrepareResult(rect, exact, mode) | None

    def release(self, immediate: bool = False) -> None: ...

    # move=False : seule l'échelle change (jamais déplacé) ; rescale=False : seule la position. Renvoie où est l'écran.
    def apply_layout(self, position: str, scale: str, dpi: int, *, move: bool = True,
                     rescale: bool = True) -> Rect | None: ...


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
    """Called from the engine's threads: must not block.

    `detail` is a Msg the listener translates (the CLI in English, the app in its language); log lines are English.

    Optional: `on_display(info: DisplayInfo)`, called once per session when the virtual screen is on (Extend mode
    with a display). A listener without it is fine.
    """

    def on_state(self, state: State, detail: Msg) -> None: ...

    def on_log(self, line: str) -> None: ...

    def on_stats(self, stats: StreamStats) -> None: ...


class FatalError(MessageError):
    """Stops the engine; its Msg is shown to the user."""


class _Stopped(Exception):
    """stop() was called while resolve_encoder was probing."""


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
ENCODER_PROBE_TIMEOUT_S = 10
ADB_TIMEOUT_S = 10
FFMPEG_WAIT_S = 2  # après kill()

PREPARING_DETAIL = msg("state.preparing_capture")
PREPARING_DISPLAY_DETAIL = msg("state.preparing_display")
WAITING_APP_DETAIL = msg("state.waiting_app")
STOPPED_DETAIL = msg("state.stopped")
_ADB_TIMEOUT_PROBLEM = msg("adb.timeout")

Run = Callable[..., subprocess.CompletedProcess]
Outputs = list[tuple[int, tuple[int, int] | None]]


def now_us() -> int:
    # perf_counter (QueryPerformanceCounter) : time.monotonic n'a que ~15,6 ms de résolution sous Windows avant 3.13.
    return time.perf_counter_ns() // 1000


class SocketReader:
    """Minimal binary reader over recv(). Unlike makefile(), it lets sock.close() abort a blocked recv on Windows."""

    def __init__(self, sock: socket.socket) -> None:
        self._sock = sock

    def read(self, size: int) -> bytes:
        return self._sock.recv(size)


def probe_outputs(ffmpeg: str, max_outputs: int = 8, run: Run = subprocess.run,
                  should_stop: Callable[[], bool] = lambda: False) -> Outputs:
    """Captures one frame per ddagrab output (default D3D11 adapter) and returns (index, (width, height)).

    If should_stop() turns true, or a probe times out, returns the outputs found so far.
    """
    outputs: Outputs = []
    for index in range(max_outputs):
        if should_stop():
            break
        try:
            result = run(
                [ffmpeg, "-nostdin", "-hide_banner", "-f", "lavfi",
                 "-i", f"ddagrab=output_idx={index}:framerate=1,hwdownload,format=bgra",
                 "-frames:v", "1", "-f", "null", "-"],
                capture_output=True, text=True, errors="replace", creationflags=tools.NO_WINDOW,
                timeout=ENCODER_PROBE_TIMEOUT_S,
            )
        except subprocess.TimeoutExpired:
            break  # ffmpeg bloqué (GPU endormi…) : on garde les écrans déjà trouvés
        if result.returncode != 0:
            break  # les index sont contigus : le premier échec marque la fin
        size = re.search(r"\b(\d{3,5})x(\d{3,5})\b", result.stderr)
        outputs.append((index, (int(size.group(1)), int(size.group(2))) if size else None))
    return outputs


def describe_outputs(outputs: Outputs) -> Msg:
    if not outputs:
        return msg("outputs.none")
    lines = [msg("outputs.line", index=i, width=s[0], height=s[1]) if s else msg("outputs.line_unknown", index=i)
             for i, s in outputs]
    return msg("outputs.list", lines=lines)


def pick_output(choice: str, outputs: Outputs, width: int, height: int) -> int:
    """Explicit index, or ('auto') the first screen whose size matches the tablet's."""
    if choice != "auto":
        return int(choice)
    for index, size in outputs:
        if size == (width, height):
            return index
    raise FatalError(msg("error.no_matching_screen", width=width, height=height, outputs=describe_outputs(outputs)))


def output_for_rect(outputs: Outputs, rect: Rect, monitors: list[injector.Monitor]) -> int | None:
    """ddagrab index of the Windows screen `rect`, or None if no output has its size.

    Several outputs of that size (e.g. a main screen as big as the tablet): the one with the same rank among them
    as `rect` among the Windows monitors of that size. This assumes DXGI lists outputs in the EnumDisplayMonitors
    order, which holds in practice; it only matters when two screens share a size.
    """
    size = (rect.width, rect.height)
    candidates = [index for index, found in outputs if found == size]
    if not candidates:
        return None
    same_size = [r for r, _primary, _name in monitors if (r.width, r.height) == size]
    rank = same_size.index(rect) if rect in same_size else 0
    return candidates[min(rank, len(candidates) - 1)]


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


def resolve_encoder(ffmpeg: str, choice: str, run: Run = subprocess.run,
                    should_stop: Callable[[], bool] = lambda: False) -> tuple[str, str]:
    """(encoder, English log line). 'auto' probes NVENC then AMF; a forced encoder is trusted as is.

    Raises _Stopped instead of running the next probe once should_stop() turns true.
    """
    if choice != "auto":
        return choice, f"Encoder: {ENCODER_NAMES[choice]} (forced)"
    unavailable: list[str] = []
    for name in AUTO_ORDER:
        if should_stop():
            raise _Stopped
        if probe_encoder(ffmpeg, name, run):
            suffix = f" ({', '.join(unavailable)} unavailable)" if unavailable else ""
            return name, f"Encoder: {ENCODER_NAMES[name]}{suffix}"
        unavailable.append(ENCODER_NAMES[name])
    raise FatalError(msg("error.no_encoder"))


def adb_problem(adb: str, run: Run = subprocess.run) -> Msg | None:
    """None if exactly one authorized device is ready, else a message saying what to do."""
    try:
        result = run([adb, "devices"], capture_output=True, text=True, creationflags=tools.NO_WINDOW,
                     timeout=ADB_TIMEOUT_S)
    except subprocess.TimeoutExpired:
        return _ADB_TIMEOUT_PROBLEM
    if result.returncode != 0:
        return msg("adb.failed", error=result.stderr.strip())
    states = [line.split("\t")[1] for line in result.stdout.splitlines()[1:] if "\t" in line]
    if not states:
        return msg("adb.no_device")
    if "unauthorized" in states:
        return msg("adb.unauthorized")
    if states.count("device") != 1:
        return msg("adb.not_exactly_one", states=", ".join(states))
    return None


def ensure_forward(adb: str, run: Run = subprocess.run) -> Msg | None:
    """(Re)creates the adb forward; returns a message if it can't. adb drops forwards when the device reconnects."""
    problem = adb_problem(adb, run)
    if problem is not None:
        return problem
    try:
        result = run([adb, "forward", f"tcp:{protocol.PORT}", f"tcp:{protocol.PORT}"],
                     capture_output=True, text=True, creationflags=tools.NO_WINDOW, timeout=ADB_TIMEOUT_S)
    except subprocess.TimeoutExpired:
        return _ADB_TIMEOUT_PROBLEM
    if result.returncode != 0:
        return msg("adb.forward_failed", error=result.stderr.strip())
    return None


def format_stats(stats: StreamStats) -> str:
    return (f"{stats.fps:3d} fps | latency avg {stats.latency_avg_ms:5.1f} ms, "
            f"max {stats.latency_max_ms:5.1f} ms | dropped {stats.dropped} | RTT {stats.rtt_ms:.2f} ms")


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
                        log(f"Unreadable SPS ({e}): unit skipped")
                        bad_sps = info.sps
                    continue
                if new_size != size:
                    size = new_size
                    on_size(size[0], size[1])
                    send(protocol.encode_config(size[0], size[1], fps))
                    log(f"Stream: {size[0]}x{size[1]} @ {fps} fps")
                codec_config = annexb.START_CODE + info.sps + annexb.START_CODE + info.pps
                send(protocol.encode_video(now_us(), codec_config, protocol.FLAG_CODEC_CONFIG))
                last_sps = info.sps
                last_pps = info.pps
            if info.is_idr and info.sps is None and last_sps is not None:
                unit = annexb.insert_parameter_sets(unit, last_sps, last_pps)
            send(protocol.encode_video(now_us(), unit, protocol.FLAG_KEY if info.is_idr else 0))


@dataclass
class Deps:
    """Everything the engine touches outside Python; tests swap in fakes."""
    run: Run = subprocess.run
    popen: Callable[..., Any] = subprocess.Popen
    create_connection: Callable[..., socket.socket] = socket.create_connection
    # (width, height, log, rect=<captured screen or None>) ; rect None : l'écran est cherché par la taille du flux
    create_injector: Callable[..., Any] = injector.create_for_stream
    monitors: Callable[[], list[injector.Monitor]] = injector.monitors
    poll_s: float = 1.0
    retry_delay_s: float = RETRY_DELAY_S


@dataclass
class _DisplaySession:
    """The session whose virtual screen is on and captured (changed under RelayEngine._relayout_lock)."""
    dpi: int
    retarget: Callable[[Rect], None]  # le tactile suit l'écran à son nouvel emplacement
    layout: tuple[str, str]  # (position, échelle) que l'écran a maintenant


@dataclass(frozen=True)
class SessionResult:
    ffmpeg_died: bool  # ffmpeg s'est arrêté seul (ni la tablette ni stop())
    sent_video: bool
    stderr_tail: list[str]


class RelayEngine:
    """Runs the relay loop in its own thread until stop() or a fatal error (state ERROR).

    display: the virtual screen manager (virtual_display.VirtualDisplay), used only when config.mode is "extend";
        None (CLI, tests) keeps the config.output choice. The engine never calls its cleanup_on_start (the app does).
    first_time: asked before each prepare; True makes prepare apply config.position and config.scale (the app
        returns "the current position/scale were never applied" from its settings).
    on_layout_applied(position, scale): called once Windows has that layout: after a prepare asked to apply it,
        or after a relayout that moved/scaled the screen (the app saves the pair).
    Both callbacks run on the engine thread (on_layout_applied also on the thread calling relayout).
    """

    def __init__(self, config: Config, listener: Listener, *, ffmpeg: str, adb: str,
                 deps: Deps | None = None, display: Display | None = None,
                 first_time: Callable[[], bool] = lambda: False,
                 on_layout_applied: Callable[[str, str], None] = lambda position, scale: None) -> None:
        self._config = config
        self._listener = listener
        self._ffmpeg = ffmpeg
        self._adb = adb
        self._deps = deps or Deps()
        self._display = display
        self._first_time = first_time
        self._on_layout_applied = on_layout_applied
        self._display_used = False  # prepare() a été appelé au moins une fois : il y a peut-être un écran à éteindre
        self._immediate_release = False  # posé par stop(immediate_display_release=True) : pas de grâce
        self._immediate_release_done = False  # la session l'a déjà éteint sans grâce : stop() n'a plus à le faire
        self._display_session: _DisplaySession | None = None
        self._prepared_layout: tuple[str, str] | None = None  # (position, échelle) passées au dernier prepare
        self._layout_lock = threading.Lock()  # position/échelle de self._config : lues et changées dessous
        # Un seul relayout à la fois ; chacun applique les valeurs les plus récentes, pas celles de son appel.
        self._relayout_lock = threading.Lock()
        self._lock = threading.Lock()
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._active_sock: socket.socket | None = None
        self._active_ffmpeg: Any = None
        self._state = State.STOPPED
        self._detail: Msg | None = None
        self._last_encoder_line: str | None = None

    @property
    def state(self) -> State:
        return self._state

    def is_running(self) -> bool:
        thread = self._thread
        return thread is not None and thread.is_alive()

    def start(self) -> None:
        """Starts the loop; does nothing if it is already running."""
        with self._lock:
            if self.is_running():
                return
            self._stop_event = threading.Event()
            self._immediate_release = False
            self._immediate_release_done = False
            # Une instance relancée réannonce ses états et son encodeur, même identiques à ceux d'avant.
            self._state = State.STOPPED
            self._detail = None
            self._last_encoder_line = None
            self._thread = threading.Thread(target=self._run, name="relay-engine", daemon=True)
            self._thread.start()

    def stop(self, immediate_display_release: bool = False) -> None:
        """Blocks up to STOP_TIMEOUT_S: kills ffmpeg, closes the socket, lifts every touch contact.

        The virtual screen goes off after the display's grace delay; with immediate_display_release (Quit) it goes
        off now, including when an earlier session's grace delay is still running.
        """
        with self._lock:
            if immediate_display_release:
                self._immediate_release = True  # avant le drapeau d'arrêt : la session le lit en se terminant
            self._stop_event.set()
            thread = self._thread
            # Fermer le socket et tuer ffmpeg débloque tous les threads de la session.
            if self._active_sock is not None:
                with contextlib.suppress(OSError):
                    self._active_sock.close()
            if self._active_ffmpeg is not None:
                with contextlib.suppress(OSError):
                    self._active_ffmpeg.kill()
        if thread is not None and thread is not threading.current_thread():
            thread.join(STOP_TIMEOUT_S)
        # La session l'a déjà éteint en se terminant ; sinon (grâce d'une session finie, ou session encore bloquée
        # dans un appel Windows : elle l'éteindra de nouveau en se terminant), on l'éteint ici.
        if (immediate_display_release and self._display is not None and self._display_used
                and not self._immediate_release_done):
            self._release_display(immediate=True)

    def relayout(self, position: str, scale: str) -> bool:
        """The user changed Position or Scale. Thread-safe; blocks while Windows applies it (about a second).

        While a session shows the virtual screen, it is moved and/or scaled now and touch follows it to its new
        place (ffmpeg keeps capturing the same output: no restart). Calls are coalesced: one applies at a time,
        with the latest values (a call that finds the screen already there does nothing), so quick changes never
        end on an older one. Returns False when there is no such session or the layout could not be applied:
        the values are then kept for the next prepare (applied if first_time, or right after it otherwise).
        """
        with self._layout_lock:
            self._config = dataclasses.replace(self._config, position=position, scale=scale)
        return self._apply_latest_layout()

    def _apply_latest_layout(self) -> bool:
        """Brings the session's screen to the latest position/scale; True if it is there now."""
        with self._relayout_lock:
            with self._layout_lock:
                position, scale = self._config.position, self._config.scale
            with self._lock:
                session = self._display_session
            if session is None or self._display is None:
                return False
            if session.layout == (position, scale):
                return True
            old_position, old_scale = session.layout
            try:
                rect = self._display.apply_layout(position, scale, session.dpi, move=position != old_position,
                                                  rescale=scale != old_scale)
            except Exception as e:  # noqa: BLE001 — la disposition n'est jamais fatale
                self._log(f"Virtual screen: layout failed: {e}")
                return False
            if rect is None:
                self._log("Virtual screen: layout not applied (screen off or not found)")
                return False
            session.layout = (position, scale)
            self._layout_applied(position, scale)
            session.retarget(rect)
            return True

    def _layout_applied(self, position: str, scale: str) -> None:
        try:
            self._on_layout_applied(position, scale)
        except Exception as e:  # noqa: BLE001 — ne pas pouvoir le noter n'arrête ni le flux ni le moteur
            self._log(f"Virtual screen: cannot record the applied layout: {e}")

    def wait(self, timeout: float | None = None) -> bool:
        """True once the engine thread has ended."""
        thread = self._thread
        if thread is None:
            return True
        thread.join(timeout)
        return not thread.is_alive()

    # --- thread du moteur ---

    def _run(self) -> None:
        error: Msg | None = None
        try:
            self._loop()
        except FatalError as e:
            error = e.msg
        except Exception as e:  # noqa: BLE001 — l'appli ne doit jamais planter : on montre l'erreur
            self._log(traceback.format_exc().rstrip())
            error = msg("error.unexpected", error=str(e))
        finally:
            # Avant d'annoncer la fin : un listener qui relance sur ERROR ne doit jamais faire tourner deux ffmpeg.
            self._release_active()
        if error is not None:
            self._set_state(State.ERROR, error)
        else:
            self._set_state(State.STOPPED, STOPPED_DETAIL)

    def _release_active(self) -> None:
        """Safety net: an unexpected exception between ffmpeg's launch and the session's finally leaves nothing open."""
        with self._lock:
            sock, self._active_sock = self._active_sock, None
            ffmpeg, self._active_ffmpeg = self._active_ffmpeg, None
        if sock is not None:
            with contextlib.suppress(OSError):
                sock.close()
        if ffmpeg is not None:
            with contextlib.suppress(OSError):
                ffmpeg.kill()
            with contextlib.suppress(subprocess.TimeoutExpired, OSError):
                ffmpeg.wait(timeout=1)

    def _loop(self) -> None:
        self._set_state(State.WAITING_DEVICE, PREPARING_DETAIL)  # les sondages prennent jusqu'à plusieurs secondes
        failures = 0
        while not self._stop_event.is_set():
            should_stop = self._stop_event.is_set
            try:
                encoder = self._pick_encoder(should_stop)
            except _Stopped:
                return
            # Sondage avant la connexion quand c'est possible (moins d'attente pour la tablette). L'écran virtuel, lui,
            # n'existe qu'après sa préparation : il est sondé pendant la session, le lecteur répondant déjà aux PING.
            outputs = (probe_outputs(self._ffmpeg, run=self._deps.run, should_stop=should_stop)
                       if self._config.output == "auto" and not self._uses_display() else [])
            if self._stop_event.is_set():
                return
            connection = self._connect()
            if connection is None:
                return
            sock, rfile, hello = connection
            self._log(f"Tablet connected: screen {hello.width}x{hello.height}, {hello.dpi} dpi")
            result = self._session(sock, rfile, hello, encoder, outputs)
            if self._stop_event.is_set():
                return
            if result.ffmpeg_died:
                self._log("ffmpeg stopped on its own. Last lines:\n  " + "\n  ".join(result.stderr_tail))
                failures = 0 if result.sent_video else failures + 1
                if failures >= MAX_FFMPEG_FAILURES:
                    last = result.stderr_tail[-1] if result.stderr_tail else msg("error.no_message")
                    raise FatalError(msg("error.ffmpeg_keeps_stopping", count=failures, last=last))
                self._stop_event.wait(self._deps.retry_delay_s)
            else:
                failures = 0
            self._log("Trying to connect again…")

    def _pick_encoder(self, should_stop: Callable[[], bool]) -> str:
        encoder, line = resolve_encoder(self._ffmpeg, self._config.encoder, self._deps.run, should_stop)
        if line != self._last_encoder_line:
            self._log(line)
            self._last_encoder_line = line
        return encoder

    def _connect(self) -> tuple[socket.socket, SocketReader, protocol.Hello] | None:
        """Waits for a tablet, redoing the adb forward on each try, then connects and waits for HELLO."""
        while not self._stop_event.is_set():
            problem = ensure_forward(self._adb, self._deps.run)
            if problem is not None:
                self._set_state(State.WAITING_DEVICE, problem)
                self._stop_event.wait(self._deps.poll_s)
                continue
            try:
                sock = self._deps.create_connection(("127.0.0.1", protocol.PORT), timeout=2)
            except OSError:
                self._wait_for_app()
                continue
            with self._lock:
                if self._stop_event.is_set():
                    sock.close()
                    return None
                self._active_sock = sock
            try:
                with contextlib.suppress(OSError):
                    sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
                # adb accepte la connexion locale même si rien n'écoute sur la tablette : seul le HELLO prouve que l'app est là.
                rfile = SocketReader(sock)
                hello = protocol.read_message(rfile)
                sock.settimeout(None)
            except (OSError, EOFError, protocol.ProtocolError):
                self._close_socket(sock)
                if self._stop_event.is_set():
                    return None
                self._wait_for_app()
                continue
            if not isinstance(hello, protocol.Hello):
                self._close_socket(sock)
                raise FatalError(msg("error.unexpected_first_message", message=str(hello)))
            if hello.version != protocol.VERSION:
                self._close_socket(sock)
                raise FatalError(msg("error.protocol_mismatch", tablet=hello.version, pc=protocol.VERSION))
            return sock, rfile, hello
        return None

    def _wait_for_app(self) -> None:
        self._set_state(State.WAITING_APP, WAITING_APP_DETAIL)
        self._stop_event.wait(self._deps.poll_s)

    # --- choix de l'écran capturé (thread du moteur, lecteur de la tablette déjà lancé) ---

    def _uses_display(self) -> bool:
        return self._display is not None and self._config.mode == "extend"

    def _choose_capture(self, hello: protocol.Hello, outputs: Outputs,
                        should_stop: Callable[[], bool]) -> tuple[int, Rect | None] | None:
        """(ddagrab index, Windows rect of that screen if known), or None if stopped or the tablet left."""
        if self._uses_display():
            return self._prepare_display(hello, should_stop)
        if self._config.mode == "duplicate" and self._config.output == "auto":
            return self._main_screen_output(outputs)
        output = pick_output(self._config.output, outputs, hello.width, hello.height)
        if self._config.output == "auto":
            self._log(f"Captured screen: #{output} ({hello.width}x{hello.height}, picked automatically)")
        return output, None

    def _prepare_display(self, hello: protocol.Hello,
                         should_stop: Callable[[], bool]) -> tuple[int, Rect] | None:
        assert self._display is not None
        self._set_state(State.PREPARING_DISPLAY, PREPARING_DISPLAY_DETAIL)
        self._prepared_layout = None
        with self._layout_lock:
            position, scale = self._config.position, self._config.scale
        first_time = self._first_time()
        self._display_used = True
        prepared = self._display.prepare(hello.width, hello.height, hello.dpi, position, scale, first_time,
                                         should_stop)
        if prepared is None:
            return None
        # Un changement fait pendant la préparation est appliqué dès que la session est en place (_session).
        self._prepared_layout = (position, scale)
        if first_time:
            self._layout_applied(position, scale)
        mode = prepared.mode
        if not prepared.exact:
            self._log(f"Virtual screen: no {hello.width}x{hello.height} mode, nearest is {mode[0]}x{mode[1]} "
                      "(black bars on the tablet)")
        on_display = getattr(self._listener, "on_display", None)
        if on_display is not None:
            self._notify(on_display, DisplayInfo((hello.width, hello.height), mode, prepared.exact, prepared.rect))
        outputs = probe_outputs(self._ffmpeg, run=self._deps.run, should_stop=should_stop)
        if should_stop():
            return None
        output = output_for_rect(outputs, prepared.rect, self._list_monitors())
        if output is None:
            raise FatalError(msg("display.not_capturable", width=prepared.rect.width, height=prepared.rect.height,
                                 outputs=describe_outputs(outputs)))
        self._log(f"Captured screen: #{output} (virtual screen {prepared.rect.width}x{prepared.rect.height})")
        return output, prepared.rect

    def _main_screen_output(self, outputs: Outputs) -> tuple[int, Rect | None]:
        """Duplicate mode: the ddagrab output of the main Windows screen, else #0."""
        listed = self._list_monitors()
        primary = next((rect for rect, is_primary, _name in listed if is_primary), None)
        output = output_for_rect(outputs, primary, listed) if primary is not None else None
        if primary is None or output is None:
            self._log("Main screen not found among the capturable screens: capturing screen #0")
            return 0, None
        self._log(f"Captured screen: #{output} (main screen {primary.width}x{primary.height})")
        return output, primary

    def _list_monitors(self) -> list[injector.Monitor]:
        try:
            return list(self._deps.monitors())
        except Exception as e:  # noqa: BLE001 — sans la liste, on retombe sur le premier écran de la bonne taille
            self._log(f"Cannot list the Windows screens: {e}")
            return []

    def _release_display(self, immediate: bool) -> None:
        assert self._display is not None
        try:
            self._display.release(immediate=immediate)
        except Exception as e:  # noqa: BLE001 — ne doit jamais empêcher la fin de la session
            self._log(f"Virtual screen: release failed: {e}")

    # --- session ---

    def _session(self, sock: socket.socket, rfile: SocketReader, hello: protocol.Hello, encoder: str,
                 outputs: Outputs) -> SessionResult:
        """Starts the tablet reader (PING, stats, input), chooses the screen to capture (preparing the virtual
        screen if any), then streams until the tablet leaves, stop() is called, or ffmpeg exits on its own."""
        send_lock = threading.Lock()
        sent_video = threading.Event()

        def send(data: bytes) -> None:
            with send_lock:
                sock.sendall(data)
            sent_video.set()  # stream() n'envoie rien avant la première IDR : tout envoi est de la vidéo

        def send_pong(t_tab_us: int) -> None:
            with send_lock:  # l'horodatage est pris sous le verrou : pas d'attente entre la mesure et l'envoi
                sock.sendall(protocol.encode_pong(t_tab_us, now_us()))

        if self._stop_event.is_set():  # stop() pendant la connexion : ne pas lancer ffmpeg pour rien
            self._close_socket(sock)
            return SessionResult(ffmpeg_died=False, sent_video=False, stderr_tail=[])
        stderr_tail: collections.deque[str] = collections.deque(maxlen=20)
        disconnected = threading.Event()
        closing = threading.Event()  # posé quand le relais ferme lui-même le socket : pas de message d'erreur parasite
        keyframe_requests = 0  # la tablette en envoie une juste après chaque CONFIG (normal) : on ne journalise que les suivantes
        input_failed = False  # un échec d'injection n'est journalisé qu'une fois par session
        stream_size: tuple[int, int] | None = None
        pointer_injector: Any = None
        injector_lock = threading.Lock()
        ffmpeg: Any = None  # lancé après le choix de l'écran ; le lecteur le tue s'il existe quand la tablette part
        target_rect: Rect | None = None  # écran Windows capturé, s'il est connu : le tactile le vise directement
        session_over = False  # posé sous injector_lock à la fin : un retarget tardif ne crée plus d'injecteur

        def retarget(rect: Rect) -> None:
            """The virtual screen moved (relayout): touch follows it; the video is untouched."""
            nonlocal pointer_injector, target_rect
            with injector_lock:
                if session_over or rect == target_rect:
                    return  # même emplacement (échelle seule, ou déjà là) : les contacts posés restent
                target_rect = rect
                if pointer_injector is None or stream_size is None:
                    return  # on_stream_size visera directement le nouvel emplacement
                self._close_injector(pointer_injector)  # lève les contacts posés à l'ancien emplacement
                pointer_injector = None
                try:
                    pointer_injector = self._deps.create_injector(stream_size[0], stream_size[1], self._log,
                                                                  rect=rect)
                except Exception as e:  # noqa: BLE001 — le tactile ne doit jamais interrompre la vidéo
                    self._log(f"Touch disabled: {e}. Video continues.")

        def on_stream_size(width: int, height: int) -> None:
            nonlocal pointer_injector, stream_size
            stream_size = (width, height)
            self._set_state(State.STREAMING, msg("state.streaming", width=width, height=height))
            with injector_lock:
                if pointer_injector is not None:
                    self._close_injector(pointer_injector)
                    pointer_injector = None
                try:
                    pointer_injector = self._deps.create_injector(width, height, self._log, rect=target_rect)
                except Exception as e:  # noqa: BLE001 — le tactile ne doit jamais interrompre la vidéo
                    self._log(f"Touch disabled: {e}. Video continues.")
                    pointer_injector = None

        def pump_stderr() -> None:
            try:
                for line in ffmpeg.stderr:
                    text = line.decode(errors="replace").rstrip()
                    stderr_tail.append(text)
                    self._log(f"[ffmpeg] {text}")
            except (OSError, ValueError):
                pass  # le thread ne doit jamais mourir tant que ffmpeg écrit

        def read_tablet() -> None:
            nonlocal keyframe_requests, input_failed
            try:
                while True:
                    message = protocol.read_message(rfile)
                    if isinstance(message, protocol.Ping):
                        send_pong(message.t_tab_us)
                    elif isinstance(message, protocol.Stats):
                        size = stream_size
                        if size is not None:
                            self._notify(self._listener.on_stats, StreamStats(
                                size[0], size[1], message.fps, message.latency_avg_us / 1000,
                                message.latency_max_us / 1000, message.dropped, message.rtt_us / 1000))
                    elif isinstance(message, protocol.KeyframeRequest):
                        keyframe_requests += 1
                        if keyframe_requests >= 2:
                            self._log("Keyframe requested by the tablet: next IDR within 1 s (fixed GOP)")
                    elif isinstance(message, protocol.Input):
                        with injector_lock:
                            target = pointer_injector
                        if target is not None:
                            try:
                                target.handle(message)
                            except Exception as e:  # noqa: BLE001 — le tactile ne doit jamais interrompre la vidéo
                                if not input_failed:
                                    input_failed = True
                                    self._log(f"Touch failed, input ignored: {e}")
            except (EOFError, OSError, protocol.ProtocolError) as e:
                if not closing.is_set() and not self._stop_event.is_set():
                    self._log(f"Tablet disconnected ({e})")
            finally:
                disconnected.set()  # avant de lire `ffmpeg` : le thread du moteur vérifie ce drapeau après l'avoir lancé
                with contextlib.suppress(OSError):
                    sock.close()  # sous Windows, seul closesocket() interrompt un sendall bloqué dans stream()
                process = ffmpeg
                if process is not None:
                    with contextlib.suppress(OSError):
                        process.kill()

        def should_stop() -> bool:
            return self._stop_event.is_set() or disconnected.is_set()

        # Le lecteur d'abord : la tablette coupe après 5 s sans PONG, et préparer l'écran peut prendre jusqu'à 10 s.
        threading.Thread(target=read_tablet, name="tablet-reader", daemon=True).start()
        stderr_thread: threading.Thread | None = None
        send_failed = False
        try:
            capture = self._choose_capture(hello, outputs, should_stop)
            if capture is None or should_stop():
                return SessionResult(ffmpeg_died=False, sent_video=False, stderr_tail=[])
            with injector_lock:
                output, target_rect = capture
            if self._uses_display() and self._prepared_layout is not None:
                with self._relayout_lock, self._lock:
                    self._display_session = _DisplaySession(hello.dpi, retarget, self._prepared_layout)
                # Position/échelle changées pendant la préparation (relayout a renvoyé False) : appliquées maintenant.
                self._apply_latest_layout()
            command = ffmpeg_command(self._ffmpeg, encoder, output, self._config.fps, self._config.bitrate)
            ffmpeg = self._deps.popen(command, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                      stderr=subprocess.PIPE, creationflags=tools.NO_WINDOW)
            with self._lock:
                self._active_ffmpeg = ffmpeg
                if self._stop_event.is_set():
                    ffmpeg.kill()
            if disconnected.is_set():  # la tablette est partie pendant le lancement : le lecteur n'a pas vu ffmpeg
                with contextlib.suppress(OSError):
                    ffmpeg.kill()
            self._set_state(State.STREAMING, msg("state.starting_stream"))
            stderr_thread = threading.Thread(target=pump_stderr, name="ffmpeg-stderr", daemon=True)
            stderr_thread.start()
            try:
                stream(ffmpeg.stdout, send, self._config.fps, disconnected, on_stream_size, self._log)
            except OSError:
                send_failed = True  # sendall a échoué : la tablette est partie
        finally:
            with self._lock:
                self._display_session = None
            with injector_lock:
                session_over = True
                if pointer_injector is not None:
                    self._close_injector(pointer_injector)  # lève tous les contacts : rien ne reste « posé » dans Windows
                    pointer_injector = None
            tablet_gone = send_failed or disconnected.is_set()
            if ffmpeg is not None:
                with contextlib.suppress(OSError):
                    ffmpeg.kill()
                with contextlib.suppress(subprocess.TimeoutExpired):
                    ffmpeg.wait(timeout=FFMPEG_WAIT_S)
            closing.set()
            self._close_socket(sock)
            with self._lock:
                self._active_ffmpeg = None
            # Écran virtuel (prepare a été appelé, même s'il a échoué) : éteint après la grâce, annulée si la tablette
            # revient ; Quit (stop(immediate_display_release=True)) : éteint tout de suite, ici aussi, car stop() a
            # pu l'éteindre pendant qu'un appel Windows de prepare le rallumait (sans effet s'il est déjà éteint).
            if self._uses_display():
                if self._immediate_release:
                    self._release_display(immediate=True)
                    self._immediate_release_done = True
                else:
                    self._release_display(immediate=False)
        died = not tablet_gone and not self._stop_event.is_set()
        if died and stderr_thread is not None:
            stderr_thread.join(timeout=0.5)  # laisse le pump finir de lire avant de rendre la fin du stderr
        return SessionResult(died, sent_video.is_set(), list(stderr_tail))

    # --- utilitaires ---

    def _close_socket(self, sock: socket.socket) -> None:
        with self._lock:
            if self._active_sock is sock:
                self._active_sock = None
        with contextlib.suppress(OSError):
            sock.close()

    def _close_injector(self, target: Any) -> None:
        try:
            target.close()
        except Exception as e:  # noqa: BLE001 — ne doit jamais empêcher la fermeture de la session
            self._log(f"Closing touch failed: {e}")

    def _set_state(self, state: State, detail: Msg) -> None:
        if (state, detail) == (self._state, self._detail):
            return
        self._state = state
        self._detail = detail
        self._notify(self._listener.on_state, state, detail)

    def _log(self, line: str) -> None:
        self._notify(self._listener.on_log, line)

    @staticmethod
    def _notify(callback: Callable[..., None], *args: Any) -> None:
        """A failing listener must never kill an engine thread (nowhere to report it: the listener is what failed)."""
        try:
            callback(*args)
        except Exception:  # noqa: BLE001
            pass
