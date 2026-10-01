"""H.264 Annex-B helpers: access-unit splitting on AUD, NAL listing, SPS size parsing."""
from __future__ import annotations

from dataclasses import dataclass

START_CODE = b"\x00\x00\x00\x01"
_START_3 = b"\x00\x00\x01"
_AUD_MARK = b"\x00\x00\x01\x09"  # an AUD always has nal_ref_idc == 0, so its header byte is exactly 0x09

NAL_IDR = 5
NAL_SPS = 7
NAL_PPS = 8
NAL_AUD = 9


class AccessUnitSplitter:
    """Splits a streamed Annex-B byte stream into access units.

    Every access unit must start with an AUD (ffmpeg: -bsf:v h264_metadata=aud=insert).
    A unit is emitted only once the next AUD arrives. Bytes before the first AUD are dropped.
    """

    def __init__(self) -> None:
        self._buf = bytearray()
        self._synced = False
        self._search_from = 0

    def feed(self, chunk: bytes) -> list[bytes]:
        self._buf += chunk
        units: list[bytes] = []
        while True:
            idx = self._buf.find(_AUD_MARK, self._search_from)
            if idx < 0:
                # Keep the last bytes searchable: a mark may straddle two chunks.
                self._search_from = max(self._search_from, len(self._buf) - len(_AUD_MARK) + 1)
                return units
            start = idx - 1 if idx > 0 and self._buf[idx - 1] == 0 else idx  # include 4-byte start code
            if self._synced:
                units.append(bytes(self._buf[:start]))
            self._synced = True
            del self._buf[:start]
            self._search_from = idx - start + len(_AUD_MARK)

    def flush(self) -> bytes | None:
        """Returns the pending (last) unit, if any, and resets the splitter."""
        unit = bytes(self._buf) if self._synced and self._buf else None
        self._buf.clear()
        self._synced = False
        self._search_from = 0
        return unit


def split_nals(data: bytes) -> list[bytes]:
    """Returns the NAL units of an Annex-B buffer (header byte first, start codes removed)."""
    nals: list[bytes] = []
    pos = data.find(_START_3)
    while pos >= 0:
        begin = pos + len(_START_3)
        nxt = data.find(_START_3, begin)
        nal = data[begin : len(data) if nxt < 0 else nxt].rstrip(b"\x00")
        if nal:
            nals.append(nal)
        pos = nxt
    return nals


@dataclass(frozen=True)
class AccessUnitInfo:
    is_idr: bool
    sps: bytes | None
    pps: bytes | None


def describe(unit: bytes) -> AccessUnitInfo:
    is_idr = False
    sps = pps = None
    for nal in split_nals(unit):
        nal_type = nal[0] & 0x1F
        if nal_type == NAL_IDR:
            is_idr = True
        elif nal_type == NAL_SPS and sps is None:
            sps = nal
        elif nal_type == NAL_PPS and pps is None:
            pps = nal
    return AccessUnitInfo(is_idr, sps, pps)
