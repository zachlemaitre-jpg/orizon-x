import sys
import unittest

import dxgi_outputs
from dxgi_outputs import Output
from inputstate import Rect


def out(adapter, index, name, attached=True, rect=Rect(0, 0, 2560, 1600)):
    return Output(adapter=adapter, adapter_name=f"GPU {adapter}", index=index, device_name=name, rect=rect,
                  attached=attached)


class DdagrabOutputTest(unittest.TestCase):
    """ddagrab counts the raw EnumOutputs index on DXGI's default adapter (the first one listed)."""

    def test_index_on_the_default_adapter(self):
        outputs = [out(0, 0, r"\\.\DISPLAY1"), out(0, 1, r"\\.\DISPLAY10")]
        self.assertEqual(dxgi_outputs.ddagrab_output(r"\\.\DISPLAY10", outputs), (1, ""))
        self.assertEqual(dxgi_outputs.ddagrab_output(r"\\.\DISPLAY1", outputs), (0, ""))

    def test_name_is_compared_without_case(self):
        outputs = [out(0, 0, r"\\.\DISPLAY1"), out(0, 1, r"\\.\DISPLAY10")]
        self.assertEqual(dxgi_outputs.ddagrab_output(r"\\.\display10", outputs)[0], 1)

    def test_display1_does_not_match_display10(self):
        outputs = [out(0, 0, r"\\.\DISPLAY10")]
        index, reason = dxgi_outputs.ddagrab_output(r"\\.\DISPLAY1", outputs)
        self.assertIsNone(index)
        self.assertEqual(reason, r"\\.\DISPLAY1 is not listed by DXGI")

    def test_index_is_the_dxgi_one_not_the_position_in_the_list(self):
        # Une sortie non attachée garde son numéro : ddagrab ne la saute pas.
        outputs = [out(0, 0, r"\\.\DISPLAY1"), out(0, 1, r"\\.\DISPLAY2", attached=False), out(0, 2, r"\\.\DISPLAY9")]
        self.assertEqual(dxgi_outputs.ddagrab_output(r"\\.\DISPLAY9", outputs), (2, ""))

    def test_screen_on_another_adapter_is_not_capturable_by_ddagrab(self):
        outputs = [out(0, 0, r"\\.\DISPLAY1"), out(1, 0, r"\\.\DISPLAY3")]
        index, reason = dxgi_outputs.ddagrab_output(r"\\.\DISPLAY3", outputs)
        self.assertIsNone(index)
        self.assertEqual(reason, r"\\.\DISPLAY3 is on adapter #1 (GPU 1), not ddagrab's default adapter (GPU 0)")

    def test_output_not_attached_to_the_desktop(self):
        outputs = [out(0, 0, r"\\.\DISPLAY1"), out(0, 1, r"\\.\DISPLAY9", attached=False)]
        index, reason = dxgi_outputs.ddagrab_output(r"\\.\DISPLAY9", outputs)
        self.assertIsNone(index)
        self.assertEqual(reason, r"\\.\DISPLAY9 is not attached to the desktop")

    def test_nothing_listed(self):
        self.assertEqual(dxgi_outputs.ddagrab_output(r"\\.\DISPLAY1", []),
                         (None, r"\\.\DISPLAY1 is not listed by DXGI"))

    def test_empty_name(self):
        self.assertEqual(dxgi_outputs.ddagrab_output("", [out(0, 0, r"\\.\DISPLAY1")]),
                         (None, "no Windows screen name"))


@unittest.skipUnless(sys.platform == "win32", "DXGI only exists on Windows")
class RealEnumerationTest(unittest.TestCase):
    """Read-only: lists this PC's adapters and outputs (no ffmpeg, nothing changed)."""

    def test_primary_screen_is_listed(self):
        import injector
        primary = [name for _rect, is_primary, name in injector.monitors() if is_primary]
        self.assertEqual(len(primary), 1, injector.monitors())
        outputs = dxgi_outputs.enumerate_outputs()
        found = [o for o in outputs if o.device_name.lower() == primary[0].lower()]
        self.assertEqual(len(found), 1, outputs)
        self.assertTrue(found[0].attached)
        self.assertTrue(found[0].adapter_name)
        for o in outputs:  # numéros DXGI contigus par carte, à partir de 0
            same = [x.index for x in outputs if x.adapter == o.adapter]
            self.assertEqual(same, list(range(len(same))))

    def test_repeated_enumeration_gives_the_same_list(self):
        self.assertEqual(dxgi_outputs.enumerate_outputs(), dxgi_outputs.enumerate_outputs())


if __name__ == "__main__":
    unittest.main()
