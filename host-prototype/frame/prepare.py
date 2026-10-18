"""Getting a folder file ready for the device: images reduced to JPEG, videos checked for a codec it can play."""
from __future__ import annotations

import re
import subprocess
from pathlib import Path
from typing import Callable

import tools

VIDEO_CODECS = frozenset({"h264", "hevc", "vp8", "vp9"})  # what the device's MediaPlayer plays
MAX_VIDEO_BYTES = 2 * 1024**3
JPEG_QUALITY = 90
CODEC_PROBE_TIMEOUT_S = 10

_VIDEO_STREAM = re.compile(r"Stream #\S+: Video: (\w+)")


class PrepareError(Exception):
    """A file that cannot be prepared (unreadable, not an image Qt can decode…)."""


def cover_size(size: tuple[int, int], screen: tuple[int, int]) -> tuple[int, int]:
    """The size an image is reduced to: its short side no longer than the screen's long side, same aspect ratio.

    The image then still covers the screen in either orientation. A smaller image is never enlarged.
    """
    width, height = size
    limit = max(screen)
    short = min(width, height)
    if short <= limit:
        return size
    factor = limit / short
    return max(1, round(width * factor)), max(1, round(height * factor))


def prepare_image(path: Path, screen: tuple[int, int]) -> bytes:
    """The image as JPEG (quality 90), turned upright by its EXIF orientation and reduced by cover_size.

    Raises PrepareError when Qt cannot read it. Qt is imported here, not at module level.
    """
    from PySide6.QtCore import QBuffer, QByteArray, QIODevice, QSize
    from PySide6.QtGui import QColor, QImage, QImageReader, QPainter

    reader = QImageReader(str(path))
    reader.setAutoTransform(True)
    size = reader.size()  # already upright: Qt applies the EXIF orientation to it
    if not size.isValid() or size.isEmpty():
        raise PrepareError(reader.errorString() or "unreadable image")
    target = cover_size((size.width(), size.height()), screen)
    if target != (size.width(), size.height()):
        reader.setScaledSize(QSize(*target))
    image = reader.read()
    if image.isNull():
        raise PrepareError(reader.errorString() or "unreadable image")
    if image.hasAlphaChannel():  # JPEG has none: transparency is shown on black, like the screen behind it
        flat = QImage(image.size(), QImage.Format.Format_RGB32)
        flat.fill(QColor("black"))
        painter = QPainter(flat)
        painter.drawImage(0, 0, image)
        painter.end()
        image = flat
    data = QByteArray()
    buffer = QBuffer(data)
    buffer.open(QIODevice.OpenModeFlag.WriteOnly)
    if not image.save(buffer, "JPEG", JPEG_QUALITY):
        raise PrepareError("cannot encode the image as JPEG")
    return bytes(data.data())


def video_codec(ffmpeg: str, path: Path, run: Callable[..., subprocess.CompletedProcess] = subprocess.run) -> str | None:
    """The codec of the first video stream, read from `ffmpeg -i` (which exits with 1: no output file); else None."""
    try:
        result = run([ffmpeg, "-hide_banner", "-nostdin", "-i", str(path)],
                     capture_output=True, text=True, errors="replace", creationflags=tools.NO_WINDOW,
                     timeout=CODEC_PROBE_TIMEOUT_S, cwd=tools.tool_cwd(ffmpeg))
    except (OSError, subprocess.SubprocessError):
        return None
    match = _VIDEO_STREAM.search(result.stderr or "")
    return match.group(1).lower() if match else None
