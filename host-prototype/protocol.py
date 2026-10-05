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
INPUT = 0x85

DEVICE_TOUCH = 1
DEVICE_PEN = 2
MAX_TOUCH_CONTACTS = 10
# bits de Contact.flags
CONTACT_CONTACT = 0x01
CONTACT_IN_RANGE = 0x02
CONTACT_BARREL = 0x04
CONTACT_CANCELED = 0x08

FLAG_KEY = 0x01
FLAG_CODEC_CONFIG = 0x02
CODEC_H264 = 1

_CONFIG = struct.Struct(">BHHH")
_U64 = struct.Struct(">Q")
_PONG = struct.Struct(">QQ")
_HELLO = struct.Struct(">4sHHHH")
_STATS = struct.Struct(">HIIII")
_INPUT_HEAD = struct.Struct(">BB")
_CONTACT = struct.Struct(">BBHHHbb")


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


@dataclass(frozen=True)
class Contact:
    id: int
    flags: int
    x: int
    y: int
    pressure: int
    tilt_x: int
    tilt_y: int


@dataclass(frozen=True)
class Input:
    device: int
    contacts: tuple[Contact, ...]


TabletMessage = Hello | Ping | KeyframeRequest | Stats | Input


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
                raise ProtocolError(f"invalid magic: {magic!r}")
            return Hello(version, width, height, dpi)
        if msg_type == PING:
            return Ping(*_U64.unpack(payload))
        if msg_type == KEYFRAME_REQ:
            if payload:
                raise ProtocolError(f"KEYFRAME_REQ with a {len(payload)}-byte payload (expected: empty)")
            return KeyframeRequest()
        if msg_type == STATS:
            return Stats(*_STATS.unpack(payload))
        if msg_type == INPUT:
            return _decode_input(payload)
    except struct.error as e:
        raise ProtocolError(f"invalid payload for type 0x{msg_type:02x}: {e}") from e
    return None


def _decode_input(payload: bytes) -> Input:
    if len(payload) < _INPUT_HEAD.size:
        raise ProtocolError(f"INPUT too short: {len(payload)} bytes")
    device, count = _INPUT_HEAD.unpack_from(payload)
    max_count = {DEVICE_TOUCH: MAX_TOUCH_CONTACTS, DEVICE_PEN: 1}.get(device)
    if max_count is None:
        raise ProtocolError(f"INPUT: unknown device {device}")
    if count > max_count:
        raise ProtocolError(f"INPUT: {count} contacts for device {device} (max {max_count})")
    if len(payload) != _INPUT_HEAD.size + _CONTACT.size * count:
        raise ProtocolError(f"INPUT: {len(payload)} bytes for {count} contact(s)")
    contacts = tuple(
        Contact(*_CONTACT.unpack_from(payload, _INPUT_HEAD.size + i * _CONTACT.size)) for i in range(count)
    )
    return Input(device, contacts)


def _read_exact(stream: BinaryIO, size: int) -> bytes:
    data = bytearray()
    while len(data) < size:
        chunk = stream.read(size - len(data))
        if not chunk:
            raise EOFError("connection closed")
        data += chunk
    return bytes(data)


def read_message(stream: BinaryIO) -> TabletMessage:
    """Reads the next known message, skipping unknown types. Raises EOFError at end of stream."""
    while True:
        msg_type, _flags, _reserved, length = HEADER.unpack(_read_exact(stream, HEADER.size))
        if length > MAX_PAYLOAD:
            raise ProtocolError(f"payload too large: {length} bytes")
        message = decode_payload(msg_type, _read_exact(stream, length))
        if message is not None:
            return message
