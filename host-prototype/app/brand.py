"""Orizon X identity: the MAZAGLA title font and the white vector logo."""
from __future__ import annotations

import logging
from pathlib import Path

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QFontDatabase, QGuiApplication, QPainter, QPixmap
from PySide6.QtSvg import QSvgRenderer

ASSETS = Path(__file__).resolve().parent / "assets"
FONT_PATH = ASSETS / "mazagla.otf"
LOGO_PATH = ASSETS / "logo.svg"

logger = logging.getLogger("orizonx")
_family: str | None = None


def load_brand_font(path: Path = FONT_PATH, cache: bool = True) -> str:
    """Family name of the title font (loaded once); the default UI family if the file can't be loaded."""
    global _family
    if cache and _family is not None:
        return _family
    font_id = QFontDatabase.addApplicationFont(str(path))
    families = QFontDatabase.applicationFontFamilies(font_id) if font_id >= 0 else []
    if families:
        family = families[0]
    else:
        logger.warning("Police du titre introuvable (%s) : police système utilisée", path)
        family = QGuiApplication.font().family()
    if cache:
        _family = family
    return family


def logo_pixmap(size_px: int, device_pixel_ratio: float) -> QPixmap:
    """The white logo, size_px logical pixels wide, rendered at the screen's real resolution."""
    physical = round(size_px * device_pixel_ratio)
    pixmap = QPixmap(physical, physical)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    QSvgRenderer(str(LOGO_PATH)).render(painter, QRectF(0, 0, physical, physical))
    painter.end()
    pixmap.setDevicePixelRatio(device_pixel_ratio)
    return pixmap
