"""Phase-1 relay: ffmpeg (ddagrab + hardware H.264) -> TABX protocol -> tablet through adb forward.

Usage: py relay.py --encoder nvenc|amf [--output auto|N] [--fps 60] [--bitrate 30M]
       py relay.py --list-outputs
"""
from __future__ import annotations

import argparse
import collections
import re
import shutil
import socket
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import BinaryIO, Callable

import annexb
import injector
import protocol


class SocketReader:
    """Minimal binary reader over recv(). Unlike makefile(), it lets sock.close() abort a blocked recv on Windows."""

    def __init__(self, sock: socket.socket) -> None:
        self._sock = sock

    def read(self, size: int) -> bytes:
        return self._sock.recv(size)


ADB_FALLBACK = Path.home() / "AppData" / "Local" / "Android" / "Sdk" / "platform-tools" / "adb.exe"

ENCODERS = {
    "nvenc": ["-c:v", "h264_nvenc", "-preset", "p1", "-tune", "ull", "-zerolatency", "1", "-delay", "0"],
    # AMF : -usage ultralowlatency/lowlatency ignorent -g (une seule IDR) ; sans -usage, -latency 1 donne la basse latence en gardant le GOP.
    # -aud 0 : sinon AMF ajoute ses propres AUD, en double avec ceux du bsf h264_metadata.
    "amf": ["-c:v", "h264_amf", "-latency", "1", "-quality", "speed", "-aud", "0"],
}


def now_us() -> int:
    # perf_counter (QueryPerformanceCounter) : time.monotonic n'a que ~15,6 ms de résolution sous Windows avant 3.13.
    return time.perf_counter_ns() // 1000


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Relais TABX phase 1 : écran PC -> tablette via adb")
    parser.add_argument("--encoder", choices=sorted(ENCODERS),
                        help="nvenc (sur secteur, GPU NVIDIA) ou amf (sur batterie, iGPU AMD)")
    parser.add_argument("--output", type=output_choice, default="auto",
                        help="numéro de l'écran capturé (voir --list-outputs), ou 'auto' (défaut) : "
                             "l'écran qui a la taille de la tablette")
    parser.add_argument("--fps", type=int, default=60)
    parser.add_argument("--bitrate", default="30M")
    parser.add_argument("--list-outputs", action="store_true", help="liste les écrans capturables puis quitte")
    args = parser.parse_args()
    if not args.list_outputs and args.encoder is None:
        parser.error("--encoder est requis (sauf avec --list-outputs)")
    return args


def output_choice(value: str) -> str:
    if value == "auto" or value.isdigit():
        return value
    raise argparse.ArgumentTypeError("attendu : 'auto' ou un numéro d'écran")


Outputs = list[tuple[int, tuple[int, int] | None]]

_ONLY_DEFAULT_GPU = ("Seuls les écrans du GPU par défaut sont listés "
                     "(sur un portable hybride, ceux branchés sur l'autre GPU n'apparaissent pas).")


def probe_outputs(max_outputs: int = 8) -> Outputs:
    """Captures one frame per ddagrab output (default D3D11 adapter) and returns (index, (width, height))."""
    outputs: Outputs = []
    for index in range(max_outputs):
        result = subprocess.run(
            ["ffmpeg", "-nostdin", "-hide_banner", "-f", "lavfi",
             "-i", f"ddagrab=output_idx={index}:framerate=1,hwdownload,format=bgra",
             "-frames:v", "1", "-f", "null", "-"],
            capture_output=True, text=True, errors="replace",
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
            print(f"Écran capturé : --output {index} ({width}x{height}, choisi automatiquement)")
            return index
    sys.exit(f"Aucun écran en {width}x{height} (taille de la tablette). Règle l'écran virtuel à cette résolution, "
             f"ou choisis-en un avec --output N :\n{describe_outputs(outputs)}")


def ffmpeg_command(args: argparse.Namespace, output: int) -> list[str]:
    return [
        "ffmpeg", "-nostdin", "-hide_banner", "-loglevel", "warning",
        # hwdownload : sur le portable hybride l'écran est sur l'AMD et NVENC sur la NVIDIA (corrigé en phase 2).
        "-f", "lavfi", "-i", f"ddagrab=output_idx={output}:framerate={args.fps},hwdownload,format=bgra",
        *ENCODERS[args.encoder],
        "-rc", "cbr", "-b:v", args.bitrate, "-bf", "0", "-g", str(args.fps),
        "-bsf:v", "h264_metadata=aud=insert", "-f", "h264", "-",
    ]


def find_adb() -> str:
    found = shutil.which("adb")
    if found:
        return found
    if ADB_FALLBACK.exists():
        return str(ADB_FALLBACK)
    sys.exit("adb introuvable : installe Android platform-tools ou ajoute-le au PATH.")


def adb_problem(adb: str) -> str | None:
    """None if exactly one authorized device is ready, else a message saying what to do."""
    out = subprocess.run([adb, "devices"], capture_output=True, text=True, check=True).stdout
    states = [line.split("\t")[1] for line in out.splitlines()[1:] if "\t" in line]
    if not states:
        return "Aucune tablette détectée : branche le câble USB et active le débogage USB."
    if "unauthorized" in states:
        return "Tablette non autorisée : accepte la demande de débogage USB sur l'écran de la tablette."
    if states.count("device") != 1:
        return f"Il faut exactement une tablette prête. État actuel : {states}"
    return None


def ensure_forward(adb: str) -> str | None:
    """(Re)creates the adb forward; returns a message if it can't. adb drops forwards when the device reconnects."""
    problem = adb_problem(adb)
    if problem is not None:
        return problem
    result = subprocess.run([adb, "forward", f"tcp:{protocol.PORT}", f"tcp:{protocol.PORT}"],
                            capture_output=True, text=True)
    if result.returncode != 0:
        return f"adb forward a échoué : {result.stderr.strip()}"
    return None


def connect(adb: str) -> tuple[socket.socket, SocketReader, protocol.Hello]:
    """Waits for a tablet, redoing the adb forward on each try, then connects and waits for HELLO."""
    last_message: str | None = None

    def wait(message: str) -> None:
        nonlocal last_message
        if message != last_message:
            print(message)
            last_message = message
        time.sleep(1)

    while True:
        problem = ensure_forward(adb)
        if problem is not None:
            wait(problem)
            continue
        sock = None
        try:
            sock = socket.create_connection(("127.0.0.1", protocol.PORT), timeout=2)
            sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
            # adb accepte la connexion locale même si rien n'écoute sur la tablette : seul le HELLO prouve que l'app est là.
            rfile = SocketReader(sock)
            hello = protocol.read_message(rfile)
            sock.settimeout(None)
        except (OSError, EOFError, protocol.ProtocolError):
            if sock is not None:
                sock.close()
            wait("En attente de l'app sur la tablette (ouvre TabX)…")
            continue
        if not isinstance(hello, protocol.Hello):
            sys.exit(f"Premier message inattendu de la tablette : {hello}")
        if hello.version != protocol.VERSION:
            sys.exit(f"Protocole incompatible : tablette v{hello.version}, relais v{protocol.VERSION}. "
                     "Mets à jour l'app ou le relais.")
        return sock, rfile, hello


def stream(source: BinaryIO, send: Callable[[bytes], None], fps: int, stop: threading.Event,
           on_size: Callable[[int, int], None]) -> None:
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
                        print(f"SPS illisible ({e}) : unité ignorée")
                        bad_sps = info.sps
                    continue
                if new_size != size:
                    size = new_size
                    on_size(size[0], size[1])
                    send(protocol.encode_config(size[0], size[1], fps))
                    print(f"Flux : {size[0]}x{size[1]} @ {fps} fps")
                codec_config = annexb.START_CODE + info.sps + annexb.START_CODE + info.pps
                send(protocol.encode_video(now_us(), codec_config, protocol.FLAG_CODEC_CONFIG))
                last_sps = info.sps
                last_pps = info.pps
            if info.is_idr and info.sps is None and last_sps is not None:
                unit = annexb.insert_parameter_sets(unit, last_sps, last_pps)
            send(protocol.encode_video(now_us(), unit, protocol.FLAG_KEY if info.is_idr else 0))


def run_session(sock: socket.socket, rfile: SocketReader, args: argparse.Namespace, output: int) -> None:
    """Streams until the tablet disconnects. Exits the program if ffmpeg stops on its own."""
    send_lock = threading.Lock()

    def send(data: bytes) -> None:
        with send_lock:
            sock.sendall(data)

    def send_pong(t_tab_us: int) -> None:
        with send_lock:  # l'horodatage est pris sous le verrou : pas d'attente entre la mesure et l'envoi
            sock.sendall(protocol.encode_pong(t_tab_us, now_us()))

    ffmpeg = subprocess.Popen(ffmpeg_command(args, output), stdin=subprocess.DEVNULL,
                              stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    stderr_tail: collections.deque[str] = collections.deque(maxlen=20)
    disconnected = threading.Event()
    keyframe_requests = 0  # la tablette en envoie une juste après chaque CONFIG (normal) : on ne journalise que les suivantes
    closing = threading.Event()  # posé quand le relais ferme lui-même le socket : pas de message d'erreur parasite
    pointer_injector: injector.Injector | None = None
    injector_lock = threading.Lock()

    def on_stream_size(width: int, height: int) -> None:
        nonlocal pointer_injector
        with injector_lock:
            if pointer_injector is not None:
                pointer_injector.close()
            pointer_injector = injector.create_for_stream(width, height)

    def pump_stderr() -> None:
        try:
            for line in ffmpeg.stderr:
                text = line.decode(errors="replace").rstrip()
                stderr_tail.append(text)
                print(f"[ffmpeg] {text}")
        except (OSError, ValueError):
            pass  # le thread ne doit jamais mourir tant que ffmpeg écrit

    def read_tablet() -> None:
        nonlocal keyframe_requests
        try:
            while True:
                message = protocol.read_message(rfile)
                if isinstance(message, protocol.Ping):
                    send_pong(message.t_tab_us)
                elif isinstance(message, protocol.Stats):
                    print(f"{message.fps:3d} fps | latence moy {message.latency_avg_us / 1000:5.1f} ms, "
                          f"max {message.latency_max_us / 1000:5.1f} ms | perdues {message.dropped} | "
                          f"RTT {message.rtt_us / 1000:.2f} ms")
                elif isinstance(message, protocol.KeyframeRequest):
                    keyframe_requests += 1
                    if keyframe_requests >= 2:
                        print("Keyframe demandée par la tablette : prochaine IDR sous 1 s (GOP fixe)")
                elif isinstance(message, protocol.Input):
                    with injector_lock:
                        target = pointer_injector
                    if target is not None:
                        target.handle(message)
        except (EOFError, OSError, protocol.ProtocolError) as e:
            if not closing.is_set():
                print(f"Tablette déconnectée ({e})")
        finally:
            disconnected.set()
            sock.close()  # sous Windows, seul closesocket() interrompt un sendall bloqué dans stream()
            ffmpeg.kill()

    stderr_thread = threading.Thread(target=pump_stderr, daemon=True)
    stderr_thread.start()
    threading.Thread(target=read_tablet, daemon=True).start()
    send_failed = False
    try:
        stream(ffmpeg.stdout, send, args.fps, disconnected, on_stream_size)
    except OSError:
        send_failed = True  # sendall a échoué : la tablette est partie
    finally:
        with injector_lock:
            if pointer_injector is not None:
                pointer_injector.close()  # lève tous les contacts : rien ne reste « posé » dans Windows
                pointer_injector = None
        tablet_gone = send_failed or disconnected.is_set()
        ffmpeg.kill()
        ffmpeg.wait()
        closing.set()
        sock.close()
    if not tablet_gone:
        stderr_thread.join(timeout=0.5)  # laisse le pump finir de lire avant d'afficher la fin du stderr
        print("ffmpeg s'est arrêté de lui-même. Dernières lignes :", *stderr_tail, sep="\n  ")
        sys.exit(1)


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    injector.enable_dpi_awareness()  # coordonnées en pixels physiques (écran virtuel à 200 %)
    args = parse_args()
    if shutil.which("ffmpeg") is None:
        sys.exit("ffmpeg introuvable : winget install Gyan.FFmpeg, puis rouvre le terminal.")
    if args.list_outputs:
        print(describe_outputs(probe_outputs()))
        return
    adb = find_adb()
    try:
        while True:
            # Sondage avant la connexion : une fois le HELLO reçu, la tablette attend des PONG (5 s de silence = coupure).
            outputs = probe_outputs() if args.output == "auto" else []
            sock, rfile, hello = connect(adb)
            print(f"Tablette connectée : écran {hello.width}x{hello.height}, {hello.dpi} dpi")
            output = pick_output(args.output, outputs, hello.width, hello.height)
            run_session(sock, rfile, args, output)
            print("Nouvelle tentative de connexion…")
    except KeyboardInterrupt:
        print("\nArrêt.")


if __name__ == "__main__":
    main()
