"""TABX protocol v1, PC side. Reference: protocol/PROTOCOL.md."""
from __future__ import annotations

import struct
from dataclasses import dataclass
from typing import BinaryIO

VERSION = 1
PORT = 27183
MAGIC = b"TABX"
MAX_PAYLOAD = 16 * 1024 * 1024
HEADER = struct.Struct(">BBHI")

# PC -> tablet
CONFIG = 0x01
VIDEO = 0x02
PONG = 0x03
# tablet -> PC
HELLO = 0x81
PING = 0x82
KEYFRAME_REQ = 0x83
STATS = 0x84

FLAG_KEY = 0x01
FLAG_CODEC_CONFIG = 0x02
CODEC_H264 = 1

_CONFIG = struct.Struct(">BHHH")
_U64 = struct.Struct(">Q")
_PONG = struct.Struct(">QQ")
_HELLO = struct.Struct(">4sHHHH")
_STATS = struct.Struct(">HIIII")


class ProtocolError(Exception):
    pass


@dataclass(frozen=True)
class Hello:
    version: int
    width: int
    height: int
    dpi: int


@dataclass(frozen=True)
class Ping:
    t_tab_us: int


@dataclass(frozen=True)
class KeyframeRequest:
    pass


@dataclass(frozen=True)
class Stats:
    fps: int
    latency_avg_us: int
    latency_max_us: int
    dropped: int
    rtt_us: int


TabletMessage = Hello | Ping | KeyframeRequest | Stats


def _frame(msg_type: int, flags: int, payload: bytes) -> bytes:
    return HEADER.pack(msg_type, flags, 0, len(payload)) + payload


def encode_config(width: int, height: int, fps: int) -> bytes:
    return _frame(CONFIG, 0, _CONFIG.pack(CODEC_H264, width, height, fps))


def encode_video(pts_us: int, data: bytes, flags: int = 0) -> bytes:
    return _frame(VIDEO, flags, _U64.pack(pts_us) + data)


def encode_pong(t_tab_us: int, t_pc_us: int) -> bytes:
    return _frame(PONG, 0, _PONG.pack(t_tab_us, t_pc_us))


def decode_payload(msg_type: int, payload: bytes) -> TabletMessage | None:
    """Decodes a tablet->PC payload. Returns None for unknown types."""
    try:
        if msg_type == HELLO:
            magic, version, width, height, dpi = _HELLO.unpack(payload)
            if magic != MAGIC:
                raise ProtocolError(f"magic invalide : {magic!r}")
            return Hello(version, width, height, dpi)
        if msg_type == PING:
            return Ping(*_U64.unpack(payload))
        if msg_type == KEYFRAME_REQ:
            return KeyframeRequest()
        if msg_type == STATS:
            return Stats(*_STATS.unpack(payload))
    except struct.error as e:
        raise ProtocolError(f"payload invalide pour le type 0x{msg_type:02x} : {e}") from e
    return None


def _read_exact(stream: BinaryIO, size: int) -> bytes:
    data = stream.read(size)
    if len(data) < size:
        raise EOFError("connexion fermée")
    return data


def read_message(stream: BinaryIO) -> TabletMessage:
    """Reads the next known message, skipping unknown types. Raises EOFError at end of stream."""
    while True:
        msg_type, _flags, _reserved, length = HEADER.unpack(_read_exact(stream, HEADER.size))
        if length > MAX_PAYLOAD:
            raise ProtocolError(f"payload trop gros : {length} octets")
        message = decode_payload(msg_type, _read_exact(stream, length))
        if message is not None:
            return message
