import importlib.util
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

HAVE_QT = importlib.util.find_spec("PySide6") is not None
if HAVE_QT:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtCore import QBuffer, QByteArray, QIODevice
    from PySide6.QtGui import QColor, QImage, QImageIOHandler, QImageReader, QImageWriter, QPainter

from frame import prepare
from frame.prepare import PrepareError, cover_size, video_codec


class CoverSizeTest(unittest.TestCase):
    def test_images_whose_short_side_fits_the_long_side_of_the_screen_are_kept(self):
        self.assertEqual(cover_size((1600, 1200), (2560, 1600)), (1600, 1200))
        self.assertEqual(cover_size((2560, 1000), (2560, 1600)), (2560, 1000))
        self.assertEqual(cover_size((2560, 2560), (2560, 1600)), (2560, 2560))  # exactly the limit
        self.assertEqual(cover_size((100, 100), (2560, 1600)), (100, 100))  # never enlarged

    def test_a_larger_short_side_is_reduced_to_the_long_side_of_the_screen(self):
        self.assertEqual(cover_size((4000, 3000), (2560, 1600)), (3413, 2560))
        self.assertEqual(cover_size((3000, 4000), (2560, 1600)), (2560, 3413))  # a portrait photo keeps its format
        self.assertEqual(cover_size((6000, 6000), (1600, 2560)), (2560, 2560))

    def test_the_screen_orientation_does_not_matter(self):
        self.assertEqual(cover_size((4000, 3000), (1600, 2560)), cover_size((4000, 3000), (2560, 1600)))

    def test_both_sides_are_rounded(self):
        self.assertEqual(cover_size((100000, 3), (2, 1)), (66667, 2))
        self.assertEqual(cover_size((100000, 4), (2, 1)), (50000, 2))


def completed(stderr, code=1):
    return subprocess.CompletedProcess([], code, "", stderr)


class RecordingRun:
    def __init__(self, result=None, error=None):
        self.result, self.error, self.calls = result, error, []

    def __call__(self, cmd, **kwargs):
        self.calls.append((cmd, kwargs))
        if self.error is not None:
            raise self.error
        return self.result


H264 = """Input #0, mov,mp4,m4a,3gp,3g2,mj2, from 'a.mp4':
  Duration: 00:00:01.00, start: 0.000000, bitrate: 52 kb/s
  Stream #0:0[0x1](und): Video: h264 (High) (avc1 / 0x31637661), yuv420p(progressive), 320x240 [SAR 1:1 DAR 4:3], 49 kb/s, 25 fps
At least one output file must be specified
"""


class VideoCodecTest(unittest.TestCase):
    def codec(self, stderr):
        return video_codec("ffmpeg.exe", Path("a.mp4"), run=RecordingRun(completed(stderr)))

    def test_reads_the_first_video_stream(self):
        self.assertEqual(self.codec(H264), "h264")
        self.assertEqual(self.codec("  Stream #0:0(eng): Audio: aac (LC)\n"
                                    "  Stream #0:1(eng): Video: hevc (Main) (hev1 / 0x31766568), yuv420p10le, 3840x2160\n"),
                         "hevc")
        self.assertEqual(self.codec("  Stream #0:0: Video: vp9 (Profile 0), yuv420p(tv), 640x360, 30 fps"), "vp9")
        self.assertEqual(self.codec("  Stream #0:0: Video: av1 (libdav1d) (Main), yuv420p, 1280x720"), "av1")
        self.assertEqual(self.codec("  Stream #0:0: Video: vp8, yuv420p, 640x480"), "vp8")

    def test_no_video_stream_or_an_error_gives_none(self):
        self.assertIsNone(self.codec("  Stream #0:0: Audio: mp3, 44100 Hz, stereo"))
        self.assertIsNone(self.codec("a.mp4: Invalid data found when processing input"))
        self.assertIsNone(self.codec(""))

    def test_failure_to_run_gives_none(self):
        for error in (OSError("no ffmpeg"), subprocess.TimeoutExpired("ffmpeg", 10)):
            with self.subTest(error=error):
                self.assertIsNone(video_codec("ffmpeg.exe", Path("a.mp4"), run=RecordingRun(error=error)))

    def test_how_ffmpeg_is_run(self):
        run = RecordingRun(completed(H264))
        video_codec("ffmpeg.exe", Path("clips/a.mp4"), run=run)
        (cmd, kwargs), = run.calls
        self.assertEqual(cmd, ["ffmpeg.exe", "-hide_banner", "-nostdin", "-i", str(Path("clips/a.mp4"))])
        self.assertEqual(kwargs["timeout"], 10)
        self.assertEqual(kwargs["creationflags"], prepare.tools.NO_WINDOW)
        self.assertEqual(kwargs["cwd"], prepare.tools.tool_cwd("ffmpeg.exe"))
        self.assertTrue(kwargs["capture_output"])

    def test_supported_codecs(self):
        self.assertEqual(prepare.VIDEO_CODECS, {"h264", "hevc", "vp8", "vp9"})
        self.assertEqual(prepare.MAX_VIDEO_BYTES, 2 * 1024**3)


@unittest.skipUnless(HAVE_QT, "PySide6 absent")
class PrepareImageTest(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)

    def picture(self, name, width, height, transformation=None, fmt=b"jpeg"):
        """Left half red, right half blue."""
        image = QImage(width, height, QImage.Format.Format_RGB32)
        image.fill(QColor("red"))
        painter = QPainter(image)
        painter.fillRect(width // 2, 0, width - width // 2, height, QColor("blue"))
        painter.end()
        path = self.root / name
        writer = QImageWriter(str(path), fmt)
        if transformation is not None:
            writer.setTransformation(transformation)
        self.assertTrue(writer.write(image), writer.errorString())
        return path

    def decode(self, data):
        buffer = QBuffer()
        buffer.setData(QByteArray(data))
        buffer.open(QIODevice.OpenModeFlag.ReadOnly)
        reader = QImageReader(buffer)
        image = reader.read()
        self.assertFalse(image.isNull(), reader.errorString())
        return image

    def test_output_is_a_jpeg(self):
        data = prepare.prepare_image(self.picture("a.png", 100, 80, fmt=b"png"), (2560, 1600))
        self.assertEqual(data[:3], b"\xff\xd8\xff")
        self.assertEqual(self.decode(data).size().toTuple(), (100, 80))

    def test_a_large_image_is_reduced_keeping_its_format(self):
        data = prepare.prepare_image(self.picture("big.jpg", 400, 300), (100, 200))
        image = self.decode(data)
        self.assertEqual(image.size().toTuple(), (267, 200))
        self.assertEqual(image.pixelColor(2, 100).name(), "#fe0000")

    def test_a_small_image_is_not_enlarged(self):
        image = self.decode(prepare.prepare_image(self.picture("small.jpg", 120, 90), (1000, 2000)))
        self.assertEqual(image.size().toTuple(), (120, 90))

    def test_exif_orientation_is_applied_before_sizing(self):
        # Stored 400x300 with "rotate 90": upright it is 300x400 (portrait), left half red -> top half red.
        path = self.picture("phone.jpg", 400, 300, QImageIOHandler.Transformation.TransformationRotate90)
        upright = self.decode(prepare.prepare_image(path, (1600, 2560)))
        self.assertEqual(upright.size().toTuple(), (300, 400))
        self.assertEqual(upright.pixelColor(150, 5).name(), "#fe0000")
        self.assertEqual(upright.pixelColor(150, 395).name(), "#0000fe")
        reduced = self.decode(prepare.prepare_image(path, (100, 200)))  # short side 300 > 200
        self.assertEqual(reduced.size().toTuple(), (200, 267))
        self.assertEqual((reduced.pixelColor(100, 5).name(), reduced.pixelColor(100, 260).name()),
                         ("#fe0000", "#0000fe"))

    def test_transparency_is_flattened_on_black(self):
        image = QImage(20, 20, QImage.Format.Format_ARGB32)
        image.fill(QColor(0, 0, 0, 0))
        path = self.root / "t.png"
        image.save(str(path))
        out = self.decode(prepare.prepare_image(path, (100, 100)))
        self.assertLess(out.pixelColor(10, 10).red(), 8)

    def test_unreadable_files_raise_prepare_error(self):
        broken = self.root / "broken.jpg"
        broken.write_bytes(b"not an image at all")
        empty = self.root / "empty.png"
        empty.write_bytes(b"")
        for path in (broken, empty, self.root / "missing.jpg"):
            with self.subTest(path=path.name), self.assertRaises(PrepareError):
                prepare.prepare_image(path, (1000, 1000))


class LazyQtTest(unittest.TestCase):
    def test_the_module_does_not_import_qt_at_load(self):
        source = Path(prepare.__file__).read_text(encoding="utf-8")
        head = source.split("def prepare_image", 1)[0]
        self.assertNotIn("PySide6", head)


if __name__ == "__main__":
    unittest.main()
