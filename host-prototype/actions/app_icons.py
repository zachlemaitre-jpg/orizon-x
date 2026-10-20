"""The icon of the app in front, or of the site open in its browser tab (context bar, spec 2026-10-19 app-icon §2).

``AppIconProvider.icon_id(app, profile, url)`` answers at once, never blocking: the sha1 hex of the icon's PNG when it
is ready, else None (the extraction or the download runs in the provider's own worker thread, and a later call finds the
icon). ``artwork_bytes(icon_id)`` gives the PNG (96 x 96) for the hub, which sends it as a MEDIA_ARTWORK (actions.hub).

Sources:

* a native app: the icon of its exe as Windows shows it. ``SHDefExtractIconW(path, 0, 0, &hicon, NULL, 256)``, then
  ``ExtractIconExW`` (large icon) if that fails; the HICON becomes a ``QImage`` (``QImage.fromHICON``), then a 96 px
  PNG; ``DestroyIcon`` is called in every case;
* a site: only for the profiles that a browser tab's URL picks (``SITE_PROFILES``: canva, figma). The PC fetches
  ``https://<host>/favicon.ico`` then ``https://<host>/apple-touch-icon.png`` (3 s, 512 KiB at most, HTTPS only, no
  cookie, a neutral User-Agent), decoded by ``QImage``. The request goes only to the site the user already has open.
  While the favicon is not there (and after it failed) the icon of the browser's exe stands in for it;
* any other browser tab (the generic browser profile): the icon of the browser's exe.

Caches: in memory by exe path or host; the favicons also on disk, ``%LOCALAPPDATA%\\OrizonX\\icons\\<host>.png``,
valid 7 days (an expired file is used when the new download fails). A failure is remembered 10 minutes.

Qt is imported lazily, in the worker thread, by ``QtImaging`` (never at module import: importing winrt before PySide6
crashes Python). The Win32 and Qt layers and the downloader are injectable for the tests.
"""
from __future__ import annotations

import hashlib
import logging
import os
import queue
import re
import sys
import threading
import time
import urllib.error
import urllib.request
from collections import OrderedDict
from typing import Any, Callable, Optional

from actions import context_profiles
from actions.browser_url import host_of

_log = logging.getLogger("orizonx.actions.app_icons")

ICON_SIZE = 96
SITE_PROFILES = frozenset({"canva", "figma", "claude_web", "chatgpt", "gemini"})
FETCH_TIMEOUT_S = 3.0
FETCH_MAX_BYTES = 512 * 1024
DISK_VALID_S = 7 * 24 * 3600.0
FAILURE_MEMORY_S = 10 * 60.0
USER_AGENT = "Mozilla/5.0"
FAVICON_PATHS = ("/favicon.ico", "/apple-touch-icon.png")
_MAX_IMAGES = 64
_HOST_OK = re.compile(r"^[a-z0-9](?:[a-z0-9\-]*[a-z0-9])?(?:\.[a-z0-9](?:[a-z0-9\-]*[a-z0-9])?)+$")
_IP = re.compile(r"^\d+(?:\.\d+){3}$")

Fetcher = Callable[[str], Optional[bytes]]


# --- real layers ------------------------------------------------------------------------------------------------

ICON_SIZE_REQUEST = 256  # LOWORD of SHDefExtractIconW's nIconSize: the large icon, as big as the exe offers

class Win32Icons:
    """The shell calls that give an HICON for an exe (0 when there is none). The caller destroys the handle."""

    def __init__(self) -> None:
        import ctypes
        from ctypes import wintypes
        self._ctypes = ctypes
        self._wintypes = wintypes
        shell32 = ctypes.WinDLL("shell32", use_last_error=True)
        user32 = ctypes.WinDLL("user32", use_last_error=True)
        self._sh_def = shell32.SHDefExtractIconW
        self._sh_def.argtypes = [wintypes.LPCWSTR, ctypes.c_int, wintypes.UINT, ctypes.POINTER(wintypes.HICON),
                                 ctypes.POINTER(wintypes.HICON), wintypes.UINT]
        self._sh_def.restype = ctypes.c_long
        self._extract_ex = shell32.ExtractIconExW
        self._extract_ex.argtypes = [wintypes.LPCWSTR, ctypes.c_int, ctypes.POINTER(wintypes.HICON),
                                     ctypes.POINTER(wintypes.HICON), wintypes.UINT]
        self._extract_ex.restype = wintypes.UINT
        self._destroy = user32.DestroyIcon
        self._destroy.argtypes = [wintypes.HICON]
        self._destroy.restype = wintypes.BOOL

    def sh_def_extract_icon(self, path: str) -> int:
        large = self._wintypes.HICON()
        hr = self._sh_def(path, 0, 0, self._ctypes.byref(large), None, ICON_SIZE_REQUEST)
        return int(large.value or 0) if hr == 0 else 0

    def extract_icon_ex(self, path: str) -> int:
        large = self._wintypes.HICON()
        count = self._extract_ex(path, 0, self._ctypes.byref(large), None, 1)
        return int(large.value or 0) if count else 0

    def destroy_icon(self, hicon: int) -> None:
        self._destroy(hicon)



class QtImaging:
    """HICON / image bytes to a 96 x 96 PNG with QImage (PySide6 imported on first use)."""

    def __init__(self, size: int = ICON_SIZE) -> None:
        self._size = size

    @staticmethod
    def _require_qt() -> None:
        """Qt is used when the app has already loaded it (it always has: the GUI imports QtGui at start). Importing
        PySide6 after winrt in the same process crashes Python (0xC0000005), so it is never imported here then."""
        if "PySide6.QtGui" not in sys.modules and "winrt" in sys.modules:
            raise RuntimeError("Qt is not loaded and winrt is: importing PySide6 now could crash the process")

    def hicon_to_png(self, hicon: int) -> Optional[bytes]:
        self._require_qt()
        from PySide6.QtGui import QImage
        return self._png(QImage.fromHICON(hicon))

    def decode_to_png(self, data: bytes) -> Optional[bytes]:
        self._require_qt()
        from PySide6.QtGui import QImage
        image = QImage()
        return self._png(image) if image.loadFromData(data) else None

    def _png(self, image: Any) -> Optional[bytes]:
        from PySide6.QtCore import QBuffer, QByteArray, QIODevice, QPoint, Qt
        from PySide6.QtGui import QImage, QPainter
        if image.isNull() or image.width() <= 0 or image.height() <= 0:
            return None
        size = self._size
        scaled = image.convertToFormat(QImage.Format.Format_ARGB32).scaled(
            size, size, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
        canvas = QImage(size, size, QImage.Format.Format_ARGB32)
        canvas.fill(0)
        painter = QPainter(canvas)
        painter.drawImage(QPoint((size - scaled.width()) // 2, (size - scaled.height()) // 2), scaled)
        painter.end()
        data = QByteArray()
        buffer = QBuffer(data)
        buffer.open(QIODevice.OpenModeFlag.WriteOnly)
        if not canvas.save(buffer, "PNG"):
            return None
        return bytes(data.data())


class _HttpsOnlyRedirects(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: ANN001
        if not newurl.lower().startswith("https://"):
            raise urllib.error.URLError(f"redirect to a non-HTTPS address refused: {newurl}")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def fetch_https(url: str, timeout: float = FETCH_TIMEOUT_S, max_bytes: int = FETCH_MAX_BYTES,
                opener: Any = None, clock: Callable[[], float] = time.monotonic) -> Optional[bytes]:
    """The body of an HTTPS address, or None: not HTTPS, no answer within ``timeout`` seconds in all, an HTTP error,
    more than ``max_bytes``. No cookie is stored or sent (a bare opener without a cookie processor)."""
    if not isinstance(url, str) or not url.lower().startswith("https://"):
        return None
    deadline = clock() + timeout
    try:
        if opener is None:
            opener = urllib.request.build_opener(_HttpsOnlyRedirects)
        request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "image/*,*/*;q=0.5"})
        with opener.open(request, timeout=timeout) as response:
            chunks: list = []
            total = 0
            while True:
                if clock() > deadline:
                    return None
                chunk = response.read(min(16384, max_bytes + 1 - total))
                if not chunk:
                    break
                total += len(chunk)
                if total > max_bytes:
                    return None
                chunks.append(chunk)
        return b"".join(chunks) or None
    except Exception:  # noqa: BLE001 - URLError, timeout, ssl, reset...: no icon, never an exception
        return None


# --- provider -----------------------------------------------------------------------------------------------------

def default_cache_dir() -> Optional[str]:
    base = os.environ.get("LOCALAPPDATA")
    return os.path.join(base, "OrizonX", "icons") if base else None


class AppIconProvider:
    def __init__(self, win32: Any = None, imaging: Any = None, fetcher: Optional[Fetcher] = None,
                 cache_dir: Any = "default", clock: Callable[[], float] = time.monotonic,
                 wall_clock: Callable[[], float] = time.time, log: Optional[Callable[[str], None]] = None,
                 threaded: bool = True) -> None:
        self._win32 = win32
        self._imaging = imaging
        self._fetch = fetcher or fetch_https
        self._cache_dir = default_cache_dir() if cache_dir == "default" else cache_dir
        self._clock = clock
        self._wall_clock = wall_clock
        self._log = log or _log.info
        self._threaded = threaded
        self._cond = threading.Condition()
        self._queue: "queue.Queue[tuple]" = queue.Queue()
        self._worker: Optional[threading.Thread] = None
        self._ready: dict = {}      # key -> icon id
        self._images: "OrderedDict[str, bytes]" = OrderedDict()  # icon id -> PNG
        self._failed: dict = {}     # key -> time of the last failure
        self._inflight: set = set()
        self._logged: set = set()

    # --- what the context provider and the hub use ---

    def icon_id(self, app: Any, profile: Any, url: Optional[str]) -> Optional[str]:
        """The id of the icon to show for ``app`` (the ``profile`` and tab ``url`` it was recognised with), or None
        while it is not ready or when there is none. Never blocks."""
        try:
            exe_key = self._exe_key(app)
            host = self._site_host(app, profile, url)
            if host is not None:
                found = self._lookup(("site", host), host)
                if found is not None:
                    return found
                if ("site", host) not in self._failed:
                    return None  # the favicon is on its way: no browser icon in the meantime
            return self._lookup(exe_key, getattr(app, "path", "")) if exe_key is not None else None
        except Exception as e:  # noqa: BLE001 - the bar works without an icon
            self._note("icon_id", e)
            return None

    def artwork_bytes(self, icon_id: Optional[str]) -> Optional[bytes]:
        if not icon_id:
            return None
        with self._cond:
            image = self._images.get(icon_id)
            if image is not None:
                self._images.move_to_end(icon_id)
            return image

    def wait_idle(self, timeout: float = 5.0) -> bool:
        """For tests: wait until the worker has nothing left to do."""
        with self._cond:
            return self._cond.wait_for(lambda: not self._inflight, timeout)

    # --- source choice ---

    @staticmethod
    def _exe_key(app: Any) -> Optional[tuple]:
        path = getattr(app, "path", "") if app is not None else ""
        return ("exe", path.lower()) if path else None

    @staticmethod
    def _site_host(app: Any, profile: Any, url: Optional[str]) -> Optional[str]:
        if app is None or profile is None or getattr(profile, "id", None) not in SITE_PROFILES:
            return None
        if not context_profiles.is_browser(app):
            return None
        host = host_of(url)
        if host is None or not _HOST_OK.match(host) or _IP.match(host):
            return None
        return host

    def _lookup(self, key: tuple, arg: str) -> Optional[str]:
        with self._cond:
            icon_id = self._ready.get(key)
            if icon_id is not None and icon_id in self._images:
                return icon_id
            failed_at = self._failed.get(key)
            retry = failed_at is None or self._clock() - failed_at >= FAILURE_MEMORY_S
            if key in self._inflight or not retry:
                return None
            self._inflight.add(key)
        self._submit(key, arg)
        with self._cond:  # an inline (unthreaded) job may already be done
            icon_id = self._ready.get(key)
            return icon_id if icon_id is not None and icon_id in self._images else None

    # --- worker ---

    def _submit(self, key: tuple, arg: str) -> None:
        if not self._threaded:
            self._run(key, arg)
            return
        if self._worker is None or not self._worker.is_alive():
            self._worker = threading.Thread(target=self._loop, name="orizonx-app-icons", daemon=True)
            self._worker.start()
        self._queue.put((key, arg))

    def _loop(self) -> None:
        while True:
            key, arg = self._queue.get()
            self._run(key, arg)

    def _run(self, key: tuple, arg: str) -> None:
        png: Optional[bytes] = None
        try:
            png = self._extract_exe(arg) if key[0] == "exe" else self._site_icon(arg)
        except Exception as e:  # noqa: BLE001
            self._note(key[0], e)
        with self._cond:
            if png:
                icon_id = hashlib.sha1(png).hexdigest()
                self._images[icon_id] = png
                self._images.move_to_end(icon_id)
                while len(self._images) > _MAX_IMAGES:
                    self._images.popitem(last=False)
                self._ready[key] = icon_id
                self._failed.pop(key, None)
            else:
                self._failed[key] = self._clock()
            self._inflight.discard(key)
            self._cond.notify_all()

    # --- exe icon ---

    def _layers(self) -> "tuple[Any, Any]":
        if self._win32 is None:
            self._win32 = Win32Icons()
        if self._imaging is None:
            self._imaging = QtImaging()
        return self._win32, self._imaging

    def _extract_exe(self, path: str) -> Optional[bytes]:
        win32, imaging = self._layers()
        for extract in (win32.sh_def_extract_icon, win32.extract_icon_ex):
            hicon = 0
            try:
                hicon = extract(path)
                if hicon:
                    png = imaging.hicon_to_png(hicon)
                    if png:
                        return png
            except Exception as e:  # noqa: BLE001 - try the next way
                self._note("exe icon", e)
            finally:
                if hicon:
                    try:
                        win32.destroy_icon(hicon)
                    except Exception as e:  # noqa: BLE001
                        self._note("DestroyIcon", e)
        return None

    # --- favicon ---

    def _disk_path(self, host: str) -> Optional[str]:
        return os.path.join(self._cache_dir, host + ".png") if self._cache_dir else None

    def _read_disk(self, host: str) -> "tuple[Optional[bytes], bool]":
        """(PNG, still valid) of the favicon cached on disk; (None, False) when there is none."""
        path = self._disk_path(host)
        try:
            if path and os.path.isfile(path):
                with open(path, "rb") as f:
                    data = f.read()
                if data:
                    return data, self._wall_clock() - os.path.getmtime(path) < DISK_VALID_S
        except OSError:
            pass
        return None, False

    def _write_disk(self, host: str, png: bytes) -> None:
        path = self._disk_path(host)
        if not path:
            return
        try:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            tmp = path + ".tmp"
            with open(tmp, "wb") as f:
                f.write(png)
            os.replace(tmp, path)
        except OSError as e:
            self._note("icon cache", e)

    def _site_icon(self, host: str) -> Optional[bytes]:
        cached, valid = self._read_disk(host)
        if cached and valid:
            return cached
        _, imaging = self._layers()
        for name in FAVICON_PATHS:
            url = f"https://{host}{name}"
            data = self._fetch(url)
            if not data or len(data) > FETCH_MAX_BYTES:
                continue
            try:
                png = imaging.decode_to_png(data)
            except Exception as e:  # noqa: BLE001
                self._note("favicon decode", e)
                png = None
            if png:
                self._write_disk(host, png)
                return png
        return cached  # an expired file beats nothing

    def _note(self, what: str, error: Exception) -> None:
        kind = (what, type(error).__name__)
        if kind not in self._logged:
            self._logged.add(kind)
            self._log(f"app icons: {what}: {type(error).__name__}: {error}")
