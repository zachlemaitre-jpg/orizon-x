"""Phase-1 relay: ffmpeg (ddagrab + hardware H.264) -> TABX protocol -> tablet through adb forward.

Usage: py relay.py --encoder nvenc|amf [--output 0] [--fps 60] [--bitrate 30M]
"""
from __future__ import annotations

import argparse
import collections
import shutil
import socket
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import BinaryIO, Callable

import annexb
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
    parser.add_argument("--encoder", choices=sorted(ENCODERS), required=True,
                        help="nvenc (sur secteur, GPU NVIDIA) ou amf (sur batterie, iGPU AMD)")
    parser.add_argument("--output", type=int, default=0, help="index de l'écran capturé (ddagrab output_idx)")
    parser.add_argument("--fps", type=int, default=60)
    parser.add_argument("--bitrate", default="30M")
    return parser.parse_args()


def ffmpeg_command(args: argparse.Namespace) -> list[str]:
    return [
        "ffmpeg", "-nostdin", "-hide_banner", "-loglevel", "warning",
        # hwdownload : sur le portable hybride l'écran est sur l'AMD et NVENC sur la NVIDIA (corrigé en phase 2).
        "-f", "lavfi", "-i", f"ddagrab=output_idx={args.output}:framerate={args.fps},hwdownload,format=bgra",
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


def setup_adb_forward(adb: str) -> None:
    out = subprocess.run([adb, "devices"], capture_output=True, text=True, check=True).stdout
    states = [line.split("\t")[1] for line in out.splitlines()[1:] if "\t" in line]
    if not states:
        sys.exit("Aucune tablette détectée : branche le câble USB et active le débogage USB.")
    if "unauthorized" in states:
        sys.exit("Tablette non autorisée : accepte la demande de débogage USB sur l'écran de la tablette.")
    if states.count("device") != 1:
        sys.exit(f"Il faut exactement une tablette prête. État actuel : {states}")
    result = subprocess.run([adb, "forward", f"tcp:{protocol.PORT}", f"tcp:{protocol.PORT}"],
                            capture_output=True, text=True)
    if result.returncode != 0:
        sys.exit(f"adb forward a échoué : {result.stderr.strip()}")


def connect() -> tuple[socket.socket, SocketReader, protocol.Hello]:
    """Connects through adb forward and waits for HELLO, retrying while the app isn't listening."""
    announced = False
    while True:
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
            if not announced:
                print("En attente de l'app sur la tablette (ouvre TabX)…")
                announced = True
            time.sleep(1)
            continue
        if not isinstance(hello, protocol.Hello):
            sys.exit(f"Premier message inattendu de la tablette : {hello}")
        if hello.version != protocol.VERSION:
            sys.exit(f"Protocole incompatible : tablette v{hello.version}, relais v{protocol.VERSION}. "
                     "Mets à jour l'app ou le relais.")
        return sock, rfile, hello


def stream(source: BinaryIO, send: Callable[[bytes], None], fps: int, stop: threading.Event) -> None:
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
                    send(protocol.encode_config(size[0], size[1], fps))
                    print(f"Flux : {size[0]}x{size[1]} @ {fps} fps")
                codec_config = annexb.START_CODE + info.sps + annexb.START_CODE + info.pps
                send(protocol.encode_video(now_us(), codec_config, protocol.FLAG_CODEC_CONFIG))
                last_sps = info.sps
                last_pps = info.pps
            if info.is_idr and info.sps is None and last_sps is not None:
                unit = annexb.insert_parameter_sets(unit, last_sps, last_pps)
            send(protocol.encode_video(now_us(), unit, protocol.FLAG_KEY if info.is_idr else 0))


def run_session(sock: socket.socket, rfile: SocketReader, args: argparse.Namespace) -> None:
    """Streams until the tablet disconnects. Exits the program if ffmpeg stops on its own."""
    send_lock = threading.Lock()

    def send(data: bytes) -> None:
        with send_lock:
            sock.sendall(data)

    def send_pong(t_tab_us: int) -> None:
        with send_lock:  # l'horodatage est pris sous le verrou : pas d'attente entre la mesure et l'envoi
            sock.sendall(protocol.encode_pong(t_tab_us, now_us()))

    ffmpeg = subprocess.Popen(ffmpeg_command(args), stdin=subprocess.DEVNULL,
                              stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    stderr_tail: collections.deque[str] = collections.deque(maxlen=20)
    disconnected = threading.Event()
    closing = threading.Event()  # posé quand le relais ferme lui-même le socket : pas de message d'erreur parasite

    def pump_stderr() -> None:
        try:
            for line in ffmpeg.stderr:
                text = line.decode(errors="replace").rstrip()
                stderr_tail.append(text)
                print(f"[ffmpeg] {text}")
        except (OSError, ValueError):
            pass  # le thread ne doit jamais mourir tant que ffmpeg écrit

    def read_tablet() -> None:
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
                    print("Keyframe demandée : prochaine IDR sous 1 s (GOP fixe en phase 1)")
        except (EOFError, OSError, protocol.ProtocolError) as e:
            if not closing.is_set():
                print(f"Tablette déconnectée ({e})")
        finally:
            disconnected.set()
            sock.close()  # sous Windows, seul closesocket() interrompt un sendall bloqué dans stream()
            ffmpeg.kill()

    threading.Thread(target=pump_stderr, daemon=True).start()
    threading.Thread(target=read_tablet, daemon=True).start()
    send_failed = False
    try:
        stream(ffmpeg.stdout, send, args.fps, disconnected)
    except OSError:
        send_failed = True  # sendall a échoué : la tablette est partie
    finally:
        tablet_gone = send_failed or disconnected.is_set()
        ffmpeg.kill()
        ffmpeg.wait()
        closing.set()
        sock.close()
    if not tablet_gone:
        print("ffmpeg s'est arrêté de lui-même. Dernières lignes :", *stderr_tail, sep="\n  ")
        sys.exit(1)


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    args = parse_args()
    if shutil.which("ffmpeg") is None:
        sys.exit("ffmpeg introuvable : winget install Gyan.FFmpeg, puis rouvre le terminal.")
    adb = find_adb()
    try:
        while True:
            setup_adb_forward(adb)
            sock, rfile, hello = connect()
            print(f"Tablette connectée : écran {hello.width}x{hello.height}, {hello.dpi} dpi")
            run_session(sock, rfile, args)
            print("Nouvelle tentative de connexion…")
    except KeyboardInterrupt:
        print("\nArrêt.")


if __name__ == "__main__":
    main()
