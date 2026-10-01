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
                if not self._synced:
                    # Bytes before the first AUD are dropped anyway: keep only what a straddling mark needs
                    # (4 bytes, so a 4-byte start code's leading zero survives).
                    del self._buf[: max(0, len(self._buf) - len(_AUD_MARK))]
                    self._search_from = 0
                else:
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


_HIGH_PROFILES = {100, 110, 122, 244, 44, 83, 86, 118, 128, 138, 139, 134, 135}


class _BitReader:
    def __init__(self, rbsp: bytes) -> None:
        self._data = rbsp
        self._pos = 0

    def u(self, bits: int) -> int:
        value = 0
        for _ in range(bits):
            if self._pos >> 3 >= len(self._data):
                raise ValueError("SPS tronqué")
            byte =self._data[self._pos >> 3]
            value = (value << 1) | ((byte >> (7 - (self._pos & 7))) & 1)
            self._pos += 1
        return value

    def ue(self) -> int:
        zeros = 0
        while self.u(1) == 0:
            zeros += 1
        return (1 << zeros) - 1 + self.u(zeros)

    def se(self) -> int:
        k = self.ue()
        return (k + 1) // 2 if k % 2 else -(k // 2)


def _skip_scaling_list(reader: _BitReader, size: int) -> None:
    last = nxt = 8
    for _ in range(size):
        if nxt != 0:
            nxt = (last + reader.se() + 256) % 256
        last = last if nxt == 0 else nxt


def parse_sps_size(sps: bytes) -> tuple[int, int]:
    """Returns the displayed (width, height) of an SPS NAL (header byte included), cropping applied. Raises ValueError if truncated."""
    r = _BitReader(sps[1:].replace(b"\x00\x00\x03", b"\x00\x00"))  # remove emulation prevention bytes
    profile_idc = r.u(8)
    r.u(16)  # constraint flags + level_idc
    r.ue()  # seq_parameter_set_id
    chroma_format_idc = 1
    separate_colour_plane = 0
    if profile_idc in _HIGH_PROFILES:
        chroma_format_idc = r.ue()
        if chroma_format_idc == 3:
            separate_colour_plane = r.u(1)
        r.ue()  # bit_depth_luma_minus8
        r.ue()  # bit_depth_chroma_minus8
        r.u(1)  # qpprime_y_zero_transform_bypass_flag
        if r.u(1):  # seq_scaling_matrix_present_flag
            for i in range(8 if chroma_format_idc != 3 else 12):
                if r.u(1):
                    _skip_scaling_list(r, 16 if i < 6 else 64)
    r.ue()  # log2_max_frame_num_minus4
    poc_type = r.ue()
    if poc_type == 0:
        r.ue()  # log2_max_pic_order_cnt_lsb_minus4
    elif poc_type == 1:
        r.u(1)
        r.se()
        r.se()
        for _ in range(r.ue()):
            r.se()
    r.ue()  # max_num_ref_frames
    r.u(1)  # gaps_in_frame_num_value_allowed_flag
    width_mbs = r.ue() + 1
    height_map_units = r.ue() + 1
    frame_mbs_only = r.u(1)
    if not frame_mbs_only:
        r.u(1)  # mb_adaptive_frame_field_flag
    r.u(1)  # direct_8x8_inference_flag
    width = width_mbs * 16
    height = (2 - frame_mbs_only) * height_map_units * 16
    if r.u(1):  # frame_cropping_flag
        left, right, top, bottom = r.ue(), r.ue(), r.ue(), r.ue()
        chroma_array_type = 0 if separate_colour_plane else chroma_format_idc
        sub_w, sub_h = {1: (2, 2), 2: (2, 1), 3: (1, 1)}.get(chroma_array_type, (1, 1))
        crop_x = 1 if chroma_array_type == 0 else sub_w
        crop_y = (2 - frame_mbs_only) * (1 if chroma_array_type == 0 else sub_h)
        width -= (left + right) * crop_x
        height -= (top + bottom) * crop_y
    return width, height
