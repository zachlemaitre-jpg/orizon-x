import importlib.util
import os
import struct
import tempfile
import unittest
from pathlib import Path

HAVE_QT = importlib.util.find_spec("PySide6") is not None
if HAVE_QT:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from app import make_icons

PNG_MAGIC = b"\x89PNG\r\n\x1a\n"


@unittest.skipUnless(HAVE_QT, "PySide6 absent")
class IconsTest(unittest.TestCase):
    def test_write_ico_directory_points_at_each_png(self):
        path = Path(tempfile.mkdtemp()) / "x.ico"
        images = [(16, PNG_MAGIC + b"a"), (256, PNG_MAGIC + b"bb")]
        make_icons.write_ico(path, images)
        data = path.read_bytes()
        self.assertEqual(struct.unpack_from("<HHH", data), (0, 1, 2))
        for i, (size, png) in enumerate(images):
            width, height, _c, _r, planes, bits, length, offset = struct.unpack_from("<BBBBHHII", data, 6 + 16 * i)
            self.assertEqual((width, height), (size % 256, size % 256))
            self.assertEqual((planes, bits, length), (1, 32, len(png)))
            self.assertEqual(data[offset:offset + length], png)

    def test_rounded_icon_has_transparent_corners_and_opaque_centre(self):
        from PySide6.QtGui import QImage
        source = QImage(str(make_icons.SOURCE))
        image = make_icons.rounded(source, 64)
        self.assertEqual((image.width(), image.height()), (64, 64))
        self.assertEqual(image.pixelColor(0, 0).alpha(), 0)
        self.assertEqual(image.pixelColor(32, 32).alpha(), 255)

    def test_committed_assets_exist(self):
        self.assertTrue((make_icons.ASSETS / "orizonx.png").is_file())
        self.assertTrue((make_icons.ASSETS / "orizonx.ico").read_bytes().startswith(b"\x00\x00\x01\x00"))


if __name__ == "__main__":
    unittest.main()
