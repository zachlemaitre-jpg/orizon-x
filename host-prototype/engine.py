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

PREPARING_DETAIL = "Préparation de la capture…"
WAITING_APP_DETAIL = "Tablette branchée : ouvre Orizon X dessus."
_ADB_TIMEOUT_PROBLEM = "adb ne répond pas (délai dépassé)."

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
                     "résolution, ou choisis un autre écran (réglage Écran dans l'appli, --output N en ligne de "
                     f"commande) :\n{describe_outputs(outputs)}")


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
    """(encoder, log line). 'auto' probes NVENC then AMF; a forced encoder is trusted as is.

    Raises _Stopped instead of running the next probe once should_stop() turns true.
    """
    if choice != "auto":
        return choice, f"Encodeur : {ENCODER_NAMES[choice]} (forcé)"
    unavailable: list[str] = []
    for name in AUTO_ORDER:
        if should_stop():
            raise _Stopped
        if probe_encoder(ffmpeg, name, run):
            suffix = f" ({', '.join(unavailable)} indisponible)" if unavailable else ""
            return name, f"Encodeur : {ENCODER_NAMES[name]}{suffix}"
        unavailable.append(ENCODER_NAMES[name])
    raise FatalError("Aucun encodeur matériel H.264 (AMF/NVENC) disponible.")


def adb_problem(adb: str, run: Run = subprocess.run) -> str | None:
    """None if exactly one authorized device is ready, else a message saying what to do."""
    try:
        result = run([adb, "devices"], capture_output=True, text=True, creationflags=tools.NO_WINDOW,
                     timeout=ADB_TIMEOUT_S)
    except subprocess.TimeoutExpired:
        return _ADB_TIMEOUT_PROBLEM
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
    try:
        result = run([adb, "forward", f"tcp:{protocol.PORT}", f"tcp:{protocol.PORT}"],
                     capture_output=True, text=True, creationflags=tools.NO_WINDOW, timeout=ADB_TIMEOUT_S)
    except subprocess.TimeoutExpired:
        return _ADB_TIMEOUT_PROBLEM
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


@dataclass
class Deps:
    """Everything the engine touches outside Python; tests swap in fakes."""
    run: Run = subprocess.run
    popen: Callable[..., Any] = subprocess.Popen
    create_connection: Callable[..., socket.socket] = socket.create_connection
    create_injector: Callable[[int, int, Callable[[str], None]], Any] = injector.create_for_stream
    poll_s: float = 1.0
    retry_delay_s: float = RETRY_DELAY_S


@dataclass(frozen=True)
class SessionResult:
    ffmpeg_died: bool  # ffmpeg s'est arrêté seul (ni la tablette ni stop())
    sent_video: bool
    stderr_tail: list[str]


class RelayEngine:
    """Runs the relay loop in its own thread until stop() or a fatal error (state ERROR)."""

    def __init__(self, config: Config, listener: Listener, *, ffmpeg: str, adb: str,
                 deps: Deps | None = None) -> None:
        self._config = config
        self._listener = listener
        self._ffmpeg = ffmpeg
        self._adb = adb
        self._deps = deps or Deps()
        self._lock = threading.Lock()
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._active_sock: socket.socket | None = None
        self._active_ffmpeg: Any = None
        self._state = State.STOPPED
        self._detail = ""
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
            # Une instance relancée réannonce ses états et son encodeur, même identiques à ceux d'avant.
            self._state = State.STOPPED
            self._detail = ""
            self._last_encoder_line = None
            self._thread = threading.Thread(target=self._run, name="relay-engine", daemon=True)
            self._thread.start()

    def stop(self) -> None:
        """Blocks up to STOP_TIMEOUT_S: kills ffmpeg, closes the socket, lifts every touch contact."""
        with self._lock:
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

    def wait(self, timeout: float | None = None) -> bool:
        """True once the engine thread has ended."""
        thread = self._thread
        if thread is None:
            return True
        thread.join(timeout)
        return not thread.is_alive()

    # --- thread du moteur ---

    def _run(self) -> None:
        error: str | None = None
        try:
            self._loop()
        except FatalError as e:
            error = str(e)
        except Exception as e:  # noqa: BLE001 — l'appli ne doit jamais planter : on montre l'erreur
            self._log(traceback.format_exc().rstrip())
            error = f"Erreur inattendue : {e}"
        finally:
            # Avant d'annoncer la fin : un listener qui relance sur ERROR ne doit jamais faire tourner deux ffmpeg.
            self._release_active()
        if error is not None:
            self._set_state(State.ERROR, error)
        else:
            self._set_state(State.STOPPED, "Arrêté.")

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
            # Sondage avant la connexion : une fois le HELLO reçu, la tablette attend des PONG (5 s de silence = coupure).
            outputs = (probe_outputs(self._ffmpeg, run=self._deps.run, should_stop=should_stop)
                       if self._config.output == "auto" else [])
            if self._stop_event.is_set():
                return
            connection = self._connect()
            if connection is None:
                return
            sock, rfile, hello = connection
            self._log(f"Tablette connectée : écran {hello.width}x{hello.height}, {hello.dpi} dpi")
            try:
                output = pick_output(self._config.output, outputs, hello.width, hello.height)
            except FatalError:
                self._close_socket(sock)
                raise
            if self._config.output == "auto":
                self._log(f"Écran capturé : n° {output} ({hello.width}x{hello.height}, choisi automatiquement)")
            result = self._session(sock, rfile, hello, encoder, output)
            if self._stop_event.is_set():
                return
            if result.ffmpeg_died:
                self._log("ffmpeg s'est arrêté de lui-même. Dernières lignes :\n  " + "\n  ".join(result.stderr_tail))
                failures = 0 if result.sent_video else failures + 1
                if failures >= MAX_FFMPEG_FAILURES:
                    last = result.stderr_tail[-1] if result.stderr_tail else "aucun message"
                    raise FatalError(f"ffmpeg s'arrête sans cesse ({failures} fois de suite). Dernier message : {last}")
                self._stop_event.wait(self._deps.retry_delay_s)
            else:
                failures = 0
            self._log("Nouvelle tentative de connexion…")

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
                raise FatalError(f"Premier message inattendu de la tablette : {hello}")
            if hello.version != protocol.VERSION:
                self._close_socket(sock)
                raise FatalError(f"Protocole incompatible : tablette v{hello.version}, PC v{protocol.VERSION}. "
                                 "Mets à jour l'app ou le relais.")
            return sock, rfile, hello
        return None

    def _wait_for_app(self) -> None:
        self._set_state(State.WAITING_APP, WAITING_APP_DETAIL)
        self._stop_event.wait(self._deps.poll_s)

    def _session(self, sock: socket.socket, rfile: SocketReader, hello: protocol.Hello, encoder: str,
                 output: int) -> SessionResult:
        """Streams until the tablet leaves, stop() is called, or ffmpeg exits on its own."""
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
        command = ffmpeg_command(self._ffmpeg, encoder, output, self._config.fps, self._config.bitrate)
        ffmpeg = self._deps.popen(command, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                  stderr=subprocess.PIPE, creationflags=tools.NO_WINDOW)
        with self._lock:
            self._active_ffmpeg = ffmpeg
            if self._stop_event.is_set():
                ffmpeg.kill()
        self._set_state(State.STREAMING, "Démarrage du flux…")
        stderr_tail: collections.deque[str] = collections.deque(maxlen=20)
        disconnected = threading.Event()
        closing = threading.Event()  # posé quand le relais ferme lui-même le socket : pas de message d'erreur parasite
        keyframe_requests = 0  # la tablette en envoie une juste après chaque CONFIG (normal) : on ne journalise que les suivantes
        input_failed = False  # un échec d'injection n'est journalisé qu'une fois par session
        stream_size: tuple[int, int] | None = None
        pointer_injector: Any = None
        injector_lock = threading.Lock()

        def on_stream_size(width: int, height: int) -> None:
            nonlocal pointer_injector, stream_size
            stream_size = (width, height)
            self._set_state(State.STREAMING, f"Flux {width}×{height}")
            with injector_lock:
                if pointer_injector is not None:
                    self._close_injector(pointer_injector)
                    pointer_injector = None
                try:
                    pointer_injector = self._deps.create_injector(width, height, self._log)
                except Exception as e:  # noqa: BLE001 — le tactile ne doit jamais interrompre la vidéo
                    self._log(f"Tactile désactivé : {e}. La vidéo continue.")
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
                            self._log("Keyframe demandée par la tablette : prochaine IDR sous 1 s (GOP fixe)")
                    elif isinstance(message, protocol.Input):
                        with injector_lock:
                            target = pointer_injector
                        if target is not None:
                            try:
                                target.handle(message)
                            except Exception as e:  # noqa: BLE001 — le tactile ne doit jamais interrompre la vidéo
                                if not input_failed:
                                    input_failed = True
                                    self._log(f"Tactile en échec, entrées ignorées : {e}")
            except (EOFError, OSError, protocol.ProtocolError) as e:
                if not closing.is_set() and not self._stop_event.is_set():
                    self._log(f"Tablette déconnectée ({e})")
            finally:
                disconnected.set()
                with contextlib.suppress(OSError):
                    sock.close()  # sous Windows, seul closesocket() interrompt un sendall bloqué dans stream()
                with contextlib.suppress(OSError):
                    ffmpeg.kill()

        stderr_thread = threading.Thread(target=pump_stderr, name="ffmpeg-stderr", daemon=True)
        stderr_thread.start()
        threading.Thread(target=read_tablet, name="tablet-reader", daemon=True).start()
        send_failed = False
        try:
            stream(ffmpeg.stdout, send, self._config.fps, disconnected, on_stream_size, self._log)
        except OSError:
            send_failed = True  # sendall a échoué : la tablette est partie
        finally:
            with injector_lock:
                if pointer_injector is not None:
                    self._close_injector(pointer_injector)  # lève tous les contacts : rien ne reste « posé » dans Windows
                    pointer_injector = None
            tablet_gone = send_failed or disconnected.is_set()
            with contextlib.suppress(OSError):
                ffmpeg.kill()
            with contextlib.suppress(subprocess.TimeoutExpired):
                ffmpeg.wait(timeout=FFMPEG_WAIT_S)
            closing.set()
            self._close_socket(sock)
            with self._lock:
                self._active_ffmpeg = None
        died = not tablet_gone and not self._stop_event.is_set()
        if died:
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
            self._log(f"Fermeture du tactile en échec : {e}")

    def _set_state(self, state: State, detail: str) -> None:
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
