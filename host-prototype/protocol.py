"""TABX protocol v1, PC side. Reference: protocol/PROTOCOL.md."""
from __future__ import annotations

import json
import struct
from dataclasses import dataclass
from typing import BinaryIO

VERSION = 1
PORT = 27183
MAGIC = b"TABX"
MAX_PAYLOAD = 16 * 1024 * 1024
MAX_JSON = 64 * 1024  # largest JSON payload (DEVICE_INFO, ACTION, ACTIONS_STATE)
MAX_ARTWORK = 512 * 1024  # largest MEDIA_ARTWORK payload (id length byte + id + image)
MAX_ARTWORK_ID = 255
HEADER = struct.Struct(">BBHI")

# PC -> tablet
CONFIG = 0x01
VIDEO = 0x02
PONG = 0x03
ACTIONS_STATE = 0x04
MEDIA_ARTWORK = 0x05
# tablet -> PC
HELLO = 0x81
PING = 0x82
KEYFRAME_REQ = 0x83
STATS = 0x84
INPUT = 0x85
DEVICE_INFO = 0x86
ACTION = 0x87

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


@dataclass(frozen=True)
class DeviceInfo:
    role: str
    kind: str
    name: str
    app: str


@dataclass(frozen=True)
class Action:
    fields: dict  # the decoded JSON object; "id" is always a str


TabletMessage = Hello | Ping | KeyframeRequest | Stats | Input | DeviceInfo | Action


def _frame(msg_type: int, flags: int, payload: bytes) -> bytes:
    return HEADER.pack(msg_type, flags, 0, len(payload)) + payload


def encode_config(width: int, height: int, fps: int) -> bytes:
    return _frame(CONFIG, 0, _CONFIG.pack(CODEC_H264, width, height, fps))


def encode_video(pts_us: int, data: bytes, flags: int = 0) -> bytes:
    return _frame(VIDEO, flags, _U64.pack(pts_us) + data)


def encode_pong(t_tab_us: int, t_pc_us: int) -> bytes:
    return _frame(PONG, 0, _PONG.pack(t_tab_us, t_pc_us))


def encode_actions_state(state: dict) -> bytes:
    """Frames the complete Actions state as compact UTF-8 JSON. Raises ValueError if it cannot be encoded or exceeds MAX_JSON."""
    try:
        payload = json.dumps(state, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode("utf-8")
    except (TypeError, ValueError) as e:
        raise ValueError(f"ACTIONS_STATE is not encodable as JSON: {e}") from e
    if len(payload) > MAX_JSON:
        raise ValueError(f"ACTIONS_STATE too large: {len(payload)} bytes (max {MAX_JSON})")
    return _frame(ACTIONS_STATE, 0, payload)


def _artwork_id_bytes(artwork_id: str) -> bytes:
    if not isinstance(artwork_id, str):
        raise ValueError(f"MEDIA_ARTWORK id must be a str, not {type(artwork_id).__name__}")
    try:
        raw = artwork_id.encode("ascii")
    except UnicodeEncodeError as e:
        raise ValueError(f"MEDIA_ARTWORK id is not ASCII: {artwork_id!r}") from e
    if not 1 <= len(raw) <= MAX_ARTWORK_ID:
        raise ValueError(f"MEDIA_ARTWORK id is {len(raw)} bytes (1..{MAX_ARTWORK_ID})")
    return raw


def max_artwork_image(artwork_id: str) -> int:
    """The largest image that fits in a MEDIA_ARTWORK with this id (ValueError for an invalid id)."""
    return MAX_ARTWORK - 1 - len(_artwork_id_bytes(artwork_id))


def encode_media_artwork(artwork_id: str, image: bytes) -> bytes:
    """Frames a cover image: payload = u8 len(id), the ASCII id, the raw image (JPEG/PNG as Windows gives it).

    ValueError for an id that is not 1..255 ASCII characters, an empty image, or a whole payload over MAX_ARTWORK."""
    raw_id = _artwork_id_bytes(artwork_id)
    image = bytes(image)
    if not image:
        raise ValueError("MEDIA_ARTWORK with an empty image")
    size = 1 + len(raw_id) + len(image)
    if size > MAX_ARTWORK:
        raise ValueError(f"MEDIA_ARTWORK too large: {size} bytes (max {MAX_ARTWORK})")
    return _frame(MEDIA_ARTWORK, 0, bytes([len(raw_id)]) + raw_id + image)


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
        if msg_type == DEVICE_INFO:
            return _decode_device_info(payload)
        if msg_type == ACTION:
            return _decode_action(payload)
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


def _reject_constant(name: str):
    raise ValueError(f"non-finite number {name}")


def _decode_json_object(name: str, payload: bytes) -> dict:
    if len(payload) > MAX_JSON:
        raise ProtocolError(f"{name} too large: {len(payload)} bytes (max {MAX_JSON})")
    try:
        value = json.loads(payload.decode("utf-8"), parse_constant=_reject_constant)
    except (UnicodeDecodeError, ValueError, RecursionError) as e:  # JSONDecodeError is a ValueError
        raise ProtocolError(f"{name}: invalid JSON payload: {e}") from e
    if not isinstance(value, dict):
        raise ProtocolError(f"{name}: payload is not a JSON object")
    return value


def _decode_device_info(payload: bytes) -> DeviceInfo:
    obj = _decode_json_object("DEVICE_INFO", payload)
    for key in ("role", "kind", "name", "app"):
        if not isinstance(obj.get(key), str):
            raise ProtocolError(f"DEVICE_INFO: field {key!r} missing or not a string")
    return DeviceInfo(obj["role"], obj["kind"], obj["name"], obj["app"])


def _decode_action(payload: bytes) -> Action:
    obj = _decode_json_object("ACTION", payload)
    if not isinstance(obj.get("id"), str):
        raise ProtocolError("ACTION: field 'id' missing or not a string")
    return Action(obj)


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
