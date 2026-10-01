import unittest
from pathlib import Path

import annexb

SAMPLE = (Path(__file__).parent / "sample.h264").read_bytes()
AUD_4 = b"\x00\x00\x00\x01\x09"


def split_all(data: bytes, chunk_size: int) -> list[bytes]:
    splitter = annexb.AccessUnitSplitter()
    units: list[bytes] = []
    for i in range(0, len(data), chunk_size):
        units += splitter.feed(data[i : i + chunk_size])
    last = splitter.flush()
    if last is not None:
        units.append(last)
    return units


class SplitterTest(unittest.TestCase):
    def test_sample_splits_into_30_units(self):
        self.assertEqual(len(split_all(SAMPLE, 1000)), 30)

    def test_every_unit_starts_with_aud(self):
        for unit in split_all(SAMPLE, 1000):
            self.assertTrue(unit.startswith(AUD_4), unit[:8].hex())

    def test_units_reassemble_to_input(self):
        self.assertEqual(b"".join(split_all(SAMPLE, 1000)), SAMPLE)

    def test_chunk_size_does_not_change_result(self):
        expected = split_all(SAMPLE, len(SAMPLE))
        for chunk_size in (1, 2, 3, 4, 5, 7, 65536):
            with self.subTest(chunk_size=chunk_size):
                self.assertEqual(split_all(SAMPLE, chunk_size), expected)

    def test_three_byte_start_code_aud(self):
        units = split_all(SAMPLE.replace(AUD_4, b"\x00\x00\x01\x09"), 1000)
        self.assertEqual(len(units), 30)
        self.assertTrue(all(unit.startswith(b"\x00\x00\x01\x09") for unit in units))

    def test_flush_returns_last_unit_then_resets(self):
        splitter = annexb.AccessUnitSplitter()
        self.assertIsNone(splitter.flush())
        units = splitter.feed(SAMPLE)
        last = splitter.flush()
        self.assertEqual(b"".join(units) + last, SAMPLE)
        self.assertIsNone(splitter.flush())

    def test_garbage_without_aud_is_not_buffered(self):
        splitter = annexb.AccessUnitSplitter()
        for _ in range(100):
            self.assertEqual(splitter.feed(b"\xff" * 65536), [])
        self.assertLessEqual(len(splitter._buf), 4)
        units = splitter.feed(SAMPLE) + [splitter.flush()]
        self.assertEqual(len(units), 30)
        self.assertTrue(units[0].startswith(AUD_4))

    def test_bytes_before_first_aud_are_dropped(self):
        units = split_all(b"\xff\xfe\x00" + SAMPLE, 1000)
        self.assertEqual(len(units), 30)
        self.assertTrue(units[0].startswith(AUD_4))

    def test_nothing_emitted_before_second_aud(self):
        splitter = annexb.AccessUnitSplitter()
        second_aud = SAMPLE.find(AUD_4, 1)
        self.assertEqual(splitter.feed(SAMPLE[:second_aud]), [])


class DescribeTest(unittest.TestCase):
    def setUp(self):
        self.units = split_all(SAMPLE, 1000)

    def test_idr_every_10_frames(self):
        idr = [i for i, unit in enumerate(self.units) if annexb.describe(unit).is_idr]
        self.assertEqual(idr, [0, 10, 20])

    def test_idr_unit_carries_sps_and_pps(self):
        info = annexb.describe(self.units[0])
        self.assertEqual(info.sps[0] & 0x1F, annexb.NAL_SPS)
        self.assertEqual(info.pps[0] & 0x1F, annexb.NAL_PPS)

    def test_non_idr_unit_has_no_sps(self):
        self.assertIsNone(annexb.describe(self.units[1]).sps)

    def test_split_nals_strips_start_codes(self):
        nals = annexb.split_nals(self.units[0])
        self.assertEqual(nals[0][0] & 0x1F, annexb.NAL_AUD)
        self.assertTrue(all(nal[:3] != b"\x00\x00\x01" for nal in nals))

    def test_insert_parameter_sets_after_aud(self):
        first = annexb.describe(self.units[0])
        out = annexb.insert_parameter_sets(self.units[1], first.sps, first.pps)
        types = [nal[0] & 0x1F for nal in annexb.split_nals(out)]
        original = [nal[0] & 0x1F for nal in annexb.split_nals(self.units[1])]
        self.assertEqual(types, [annexb.NAL_AUD, annexb.NAL_SPS, annexb.NAL_PPS] + original[1:])
        self.assertEqual(annexb.describe(out).sps, first.sps)
        self.assertEqual(out.replace(annexb.START_CODE + first.sps + annexb.START_CODE + first.pps, b""), self.units[1])


class SpsTest(unittest.TestCase):
    def test_sample_size_applies_frame_cropping(self):
        units = split_all(SAMPLE, 1000)
        sps = annexb.describe(units[0]).sps
        self.assertEqual(annexb.parse_sps_size(sps), (320, 180))

    def test_baseline_sps_without_cropping(self):
        # Baseline profile 66, 1280x720 (80x45 macroblocks), frame_mbs_only, no cropping.
        # Bits after the 3 fixed bytes: sps_id ue(0)=1, log2_max_frame_num-4 ue(0)=1, poc_type ue(2)=011,
        # max_num_ref ue(1)=010, gaps u1=0, width_mbs-1 ue(79), height_map-1 ue(44),
        # frame_mbs_only=1, direct_8x8=1, cropping=0, vui=0, stop bit.
        bits = "1" + "1" + "011" + "010" + "0" + _ue(79) + _ue(44) + "1" + "1" + "0" + "0" + "1"
        bits += "0" * (-len(bits) % 8)
        payload = int(bits, 2).to_bytes(len(bits) // 8, "big")
        sps = bytes([0x67, 66, 0xC0, 31]) + payload
        self.assertEqual(annexb.parse_sps_size(sps), (1280, 720))

    def test_truncated_sps_raises_value_error(self):
        sps = annexb.describe(split_all(SAMPLE, 1000)[0]).sps
        with self.assertRaises(ValueError):
            annexb.parse_sps_size(sps[:6])

    def test_baseline_sps_with_bottom_cropping(self):
        # (width_mbs, height_map_units, crop_bottom, expected): 1080 is coded as 1088, 1800 as 1808 (4:2:0 crop unit = 2 lines).
        cases = [(120, 68, 4, (1920, 1080)), (180, 113, 4, (2880, 1800)), (160, 100, 0, (2560, 1600))]
        for width_mbs, height_map_units, crop_bottom, expected in cases:
            with self.subTest(expected=expected):
                cropping = ("1" + _ue(0) + _ue(0) + _ue(0) + _ue(crop_bottom)) if crop_bottom else "0"
                bits = ("1" + "1" + "011" + "010" + "0" + _ue(width_mbs - 1) + _ue(height_map_units - 1)
                        + "1" + "1" + cropping + "0" + "1")
                bits += "0" * (-len(bits) % 8)
                sps = bytes([0x67, 66, 0xC0, 40]) + int(bits, 2).to_bytes(len(bits) // 8, "big")
                self.assertEqual(annexb.parse_sps_size(sps), expected)


def _ue(value: int) -> str:
    code = bin(value + 1)[2:]
    return "0" * (len(code) - 1) + code


if __name__ == "__main__":
    unittest.main()
