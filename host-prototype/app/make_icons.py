"""Builds app/assets/orizonx.png (256 px) and orizonx.ico (16-256 px) from extended/1x/icon_orizonx.png.

Run by build-pc.ps1; the outputs are committed so the app also runs from source without a build.
Usage: .venv\\Scripts\\python.exe app\\make_icons.py
"""
from __future__ import annotations

import os
import struct
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QBuffer, QByteArray, QIODevice, QRectF, Qt  # noqa: E402
from PySide6.QtGui import QGuiApplication, QImage, QPainter, QPainterPath  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "extended" / "1x" / "icon_orizonx.png"
ASSETS = Path(__file__).resolve().parent / "assets"
SIZES = (16, 20, 24, 32, 40, 48, 64, 128, 256)
CORNER_RATIO = 0.22  # coins arrondis façon icône d'app Windows 11


def rounded(source: QImage, size: int) -> QImage:
    image = QImage(size, size, QImage.Format.Format_ARGB32_Premultiplied)
    image.fill(Qt.GlobalColor.transparent)
    painter = QPainter(image)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
    path = QPainterPath()
    path.addRoundedRect(QRectF(0, 0, size, size), size * CORNER_RATIO, size * CORNER_RATIO)
    painter.setClipPath(path)
    painter.drawImage(QRectF(0, 0, size, size), source)
    painter.end()
    return image


def png_bytes(image: QImage) -> bytes:
    data = QByteArray()
    buffer = QBuffer(data)
    buffer.open(QIODevice.OpenModeFlag.WriteOnly)
    image.save(buffer, "PNG")
    buffer.close()
    return bytes(data)


def write_ico(path: Path, images: list[tuple[int, bytes]]) -> None:
    """ICO with PNG-compressed entries (supported since Windows Vista)."""
    header = struct.pack("<HHH", 0, 1, len(images))
    offset = len(header) + 16 * len(images)
    entries = b""
    payload = b""
    for size, png in images:
        # 0 dans l'en-tête signifie 256 px
        entries += struct.pack("<BBBBHHII", size % 256, size % 256, 0, 0, 1, 32, len(png), offset + len(payload))
        payload += png
    path.write_bytes(header + entries + payload)


def main() -> int:
    _app = QGuiApplication.instance() or QGuiApplication(sys.argv[:1])
    source = QImage(str(SOURCE))
    if source.isNull():
        print(f"logo introuvable : {SOURCE}", file=sys.stderr)
        return 1
    ASSETS.mkdir(exist_ok=True)
    rounded(source, 256).save(str(ASSETS / "orizonx.png"))
    write_ico(ASSETS / "orizonx.ico", [(size, png_bytes(rounded(source, size))) for size in SIZES])
    print(f"icônes écrites dans {ASSETS}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
