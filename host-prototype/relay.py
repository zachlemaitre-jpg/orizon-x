"""Relay CLI (debug mode): the same engine as the Orizon X PC app, logging to the terminal in English.

Usage: py relay.py [--encoder auto|nvenc|amf] [--output auto|N] [--fps 60] [--bitrate 30M]
       py relay.py --list-outputs
"""
from __future__ import annotations

import argparse
import sys

import engine
import injector
import tools
from messages import Msg


def output_choice(value: str) -> str:
    if value == "auto" or value.isdigit():
        return value
    raise argparse.ArgumentTypeError("expected 'auto' or a screen number")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Orizon X relay: PC screen -> tablet over adb")
    parser.add_argument("--encoder", choices=engine.ENCODER_CHOICES, default="auto",
                        help="auto (default: NVENC if available, else AMF), nvenc or amf")
    parser.add_argument("--output", type=output_choice, default="auto",
                        help="number of the captured screen (see --list-outputs), or 'auto' (default): "
                             "the screen that has the tablet's size")
    parser.add_argument("--fps", type=int, default=60)
    parser.add_argument("--bitrate", default="30M")
    parser.add_argument("--list-outputs", action="store_true", help="list the capturable screens and exit")
    return parser.parse_args(argv)


class PrintListener:
    """Engine listener that prints logs, stats and the states that tell the user what to do."""

    # STREAMING et STOPPED doublonnent les lignes de journal (« Stream: … ») et le « Stopping. » du Ctrl+C.
    PRINTED_STATES = frozenset({engine.State.WAITING_DEVICE, engine.State.WAITING_APP, engine.State.ERROR})

    def on_state(self, state: engine.State, detail: Msg) -> None:
        if state in self.PRINTED_STATES:
            print(detail.text("en"))

    def on_log(self, line: str) -> None:
        print(line)

    def on_stats(self, stats: engine.StreamStats) -> None:
        print(engine.format_stats(stats))


def main(argv: list[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    injector.enable_dpi_awareness()  # coordonnées en pixels physiques (écran virtuel à 200 %)
    args = parse_args(argv)
    try:
        ffmpeg = tools.find_tool("ffmpeg")
        if args.list_outputs:
            print(engine.describe_outputs(engine.probe_outputs(ffmpeg)).text("en"))
            return 0
        adb = tools.find_tool("adb")
    except tools.ToolMissing as e:
        print(e, file=sys.stderr)
        return 1
    config = engine.Config(output=args.output, encoder=args.encoder, fps=args.fps, bitrate=args.bitrate)
    relay = engine.RelayEngine(config, PrintListener(), ffmpeg=ffmpeg, adb=adb)
    relay.start()
    try:
        while not relay.wait(0.5):  # attente par tranches : Ctrl+C reste pris en compte sous Windows
            pass
    except KeyboardInterrupt:
        print("\nStopping.")
        relay.stop()
        return 0
    return 1 if relay.state is engine.State.ERROR else 0


if __name__ == "__main__":
    sys.exit(main())
