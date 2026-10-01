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
        self.assertEqual(split_all(SAMPLE, 7), split_all(SAMPLE, len(SAMPLE)))

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


if __name__ == "__main__":
    unittest.main()
