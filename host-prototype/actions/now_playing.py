"""The "now playing" provider (spec Actions mode §7): the Windows media session (Spotify, a browser, Deezer, VLC...).

WinRT ``Windows.Media.Control``, all on the WinRT worker (actions.winrt_call), in ONE worker call per poll:
``GlobalSystemMediaTransportControlsSessionManager.request_async()`` then ``get_current_session()``;
``try_get_media_properties_async()`` for title / artist / album_title / thumbnail; ``get_playback_info()
.playback_status`` (PLAYING -> ``playing``). The thumbnail (an ``IRandomAccessStreamReference``) is read with
``open_read_async()`` and a ``Windows.Storage.Streams.DataReader``, at most ``max_bytes`` (a bigger stream is not
read at all) and each WinRT wait bounded by OP_TIMEOUT_S. No WinRT object is kept between polls.

The thumbnail is read only on the first ARTWORK_READS polls of a track (a track = app + title + artist + album; a
play/pause is not a new track). The first read happens with the poll that sees the new track, so the previous
cover is dropped at once; the next reads catch a cover the app publishes a little after its title (or replaces).
A re-read that finds no thumbnail keeps the cover already read.

Snapshot: ``{"available": True, "app", "title", "artist", "album", "playing": bool, "artwork": sha1 hex | None}``,
or ``{"available": False}`` with no session (or a session with neither title nor artist) and without WinRT.
``artwork_bytes(artwork_id)`` gives the image of the current cover (the raw JPEG/PNG from Windows) for the hub,
which sends it as MEDIA_ARTWORK before the state that references it. No action (``handle()`` ignores any id; the
media keys stay with actions.media).
"""
from __future__ import annotations

import hashlib
import logging
import re
import threading
from dataclasses import dataclass
from typing import Any, Callable, Optional, Protocol

import protocol
from actions import winrt_call
from actions.base import ProviderError

_log = logging.getLogger("orizonx.actions.now_playing")

OP_TIMEOUT_S = 2.0
# request_async + media properties + thumbnail open + thumbnail load, each bounded by OP_TIMEOUT_S
CALL_TIMEOUT_S = 4 * OP_TIMEOUT_S
ARTWORK_READS = 3
MAX_TEXT = 256
SHA1_HEX_LEN = 40
MAX_IMAGE = protocol.MAX_ARTWORK - 1 - SHA1_HEX_LEN  # the whole MEDIA_ARTWORK payload stays <= MAX_ARTWORK

_PLAYING = 4  # GlobalSystemMediaTransportControlsSessionPlaybackStatus.PLAYING

TrackKey = tuple  # (app_id, title, artist, album)

# lower-cased substring of the AppUserModelID -> friendly name; first match wins
_APP_NAMES = (
    ("spotify", "Spotify"),
    ("msedge", "Edge"),
    ("microsoftedge", "Edge"),
    ("chrome", "Chrome"),
    ("firefox", "Firefox"),
    ("308046b0af4a39cb", "Firefox"),  # Firefox's AUMID is a hash of its install folder (64-bit default)
    ("e7cf176e110c211b", "Firefox"),  # (32-bit default)
    ("deezer", "Deezer"),
    ("vlc", "VLC"),
    ("zunemusic", "Windows Media Player"),
    ("mediaplayer", "Windows Media Player"),
    ("wmplayer", "Windows Media Player"),
    ("applemusic", "Apple Music"),
    ("itunes", "iTunes"),
    ("zunevideo", "Movies & TV"),
    ("brave", "Brave"),
    ("opera", "Opera"),
    ("tidal", "TIDAL"),
    ("amazonmusic", "Amazon Music"),
)


def app_name(aumid: Optional[str]) -> str:
    """A readable name for a session's source_app_user_model_id (see _APP_NAMES; else the exe stem)."""
    if not aumid:
        return ""
    aumid = aumid.strip()
    low = aumid.lower()
    for token, name in _APP_NAMES:
        if token in low:
            return name
    if "!" in aumid:  # packaged app: Publisher.App_hash!AppId
        family = aumid.split("!", 1)[0].split("_", 1)[0]
        return family.rsplit(".", 1)[-1] or aumid
    stem = re.split(r"[\\/]", aumid)[-1]
    if stem.lower().endswith(".exe"):
        stem = stem[:-4]
    return stem or aumid


@dataclass(frozen=True)
class MediaInfo:
    app_id: str
    title: str
    artist: str
    album: str
    playing: bool
    thumbnail: Optional[bytes]  # None: no thumbnail, too big, unreadable, or not read this time
    thumbnail_read: bool  # want_thumbnail said yes (whatever the outcome)


class MediaApi(Protocol):
    def current(self, want_thumbnail: Callable[[TrackKey], bool], max_bytes: int) -> Optional[MediaInfo]:
        """The current media session (None if there is none). want_thumbnail(key) decides whether the thumbnail
        is read in this call; a thumbnail over max_bytes is not read."""


def _text(value: Any) -> str:
    return value if isinstance(value, str) else ""


class WinRTNowPlayingApi:
    """The real queries, through pywinrt on the WinRT worker thread."""

    def __init__(self, worker: Optional[winrt_call.WinRTWorker] = None, manager_cls: Any = None,
                 data_reader: Any = None) -> None:
        if manager_cls is None:  # ImportError -> provider unavailable
            from winrt.windows.media.control import GlobalSystemMediaTransportControlsSessionManager as manager_cls
        if data_reader is None:
            from winrt.windows.storage.streams import DataReader as data_reader
        self._manager_cls = manager_cls
        self._data_reader = data_reader
        self._worker = worker or winrt_call.WORKER

    def current(self, want_thumbnail: Callable[[TrackKey], bool], max_bytes: int) -> Optional[MediaInfo]:
        def query() -> Optional[MediaInfo]:
            manager = winrt_call.wait_op(self._manager_cls.request_async(), OP_TIMEOUT_S)
            session = manager.get_current_session()
            if session is None:
                return None
            props = winrt_call.wait_op(session.try_get_media_properties_async(), OP_TIMEOUT_S)
            app_id = _text(session.source_app_user_model_id)
            title, artist, album = _text(props.title), _text(props.artist), _text(props.album_title)
            playing = int(session.get_playback_info().playback_status) == _PLAYING
            read = bool(want_thumbnail((app_id, title, artist, album)))
            thumbnail = self._read_thumbnail(props.thumbnail, max_bytes) if read else None
            return MediaInfo(app_id, title, artist, album, playing, thumbnail, read)
        return self._worker.run(query, CALL_TIMEOUT_S)

    def _read_thumbnail(self, ref: Any, max_bytes: int) -> Optional[bytes]:
        """On the worker. None when there is no thumbnail, it is empty or too big, or reading it failed."""
        if ref is None:
            return None
        stream = reader = None
        try:
            stream = winrt_call.wait_op(ref.open_read_async(), OP_TIMEOUT_S)
            size = int(stream.size)
            if size <= 0:
                return None
            if size > max_bytes:
                _log.info("now_playing: thumbnail of %d bytes over %d, not sent", size, max_bytes)
                return None
            reader = self._data_reader(stream.get_input_stream_at(0))
            loaded = int(winrt_call.wait_op(reader.load_async(size), OP_TIMEOUT_S))
            if loaded <= 0:
                return None
            buf = bytearray(min(loaded, size))
            reader.read_bytes(buf)
            return bytes(buf)
        except Exception as e:  # noqa: BLE001 - WinRT error (OSError), timeout: the text is still worth showing
            _log.info("now_playing: thumbnail unreadable: %r", e)
            return None
        finally:
            for obj in (reader, stream):
                if obj is not None:
                    try:
                        obj.close()
                    except Exception:  # noqa: BLE001
                        pass


def _default_api() -> Optional[MediaApi]:
    try:
        return WinRTNowPlayingApi()
    except ImportError as e:
        _log.info("now_playing unavailable: %s", e)
        return None


_DEFAULT = object()


class NowPlayingProvider:
    """The current media session and its cover (see the module docstring)."""

    def __init__(self, api: Any = _DEFAULT) -> None:
        self._api: Optional[MediaApi] = _default_api() if api is _DEFAULT else api
        self._lock = threading.Lock()
        self._key: Optional[TrackKey] = None
        self._reads_left = 0
        self._artwork_id: Optional[str] = None
        self._artwork: Optional[bytes] = None

    def _want_thumbnail(self, key: TrackKey) -> bool:
        return key != self._key or self._reads_left > 0

    def _forget(self) -> None:
        self._key = None
        self._reads_left = 0
        self._artwork_id = None
        self._artwork = None

    def snapshot(self) -> dict:
        if self._api is None:
            return {"available": False}
        with self._lock:
            try:
                info = self._api.current(self._want_thumbnail, MAX_IMAGE)
            except ProviderError:
                raise
            except Exception as e:  # noqa: BLE001 - WinRT error (OSError)
                raise ProviderError(f"now_playing: media session query failed: {e!r}") from e
            if info is None:
                self._forget()
                return {"available": False}
            key = (info.app_id, info.title, info.artist, info.album)
            if key != self._key:
                self._forget()
                self._key = key
                self._reads_left = ARTWORK_READS
            if info.thumbnail_read:
                self._reads_left = max(0, self._reads_left - 1)
                image = info.thumbnail
                if image and len(image) <= MAX_IMAGE:
                    self._artwork = bytes(image)
                    self._artwork_id = hashlib.sha1(self._artwork).hexdigest()
            title, artist = _text(info.title).strip()[:MAX_TEXT], _text(info.artist).strip()[:MAX_TEXT]
            if not title and not artist:
                return {"available": False}
            return {"available": True, "app": app_name(info.app_id)[:MAX_TEXT], "title": title, "artist": artist,
                    "album": _text(info.album).strip()[:MAX_TEXT], "playing": bool(info.playing),
                    "artwork": self._artwork_id}

    def artwork_bytes(self, artwork_id: Optional[str]) -> Optional[bytes]:
        """The image of the current cover if artwork_id is its id, else None."""
        with self._lock:
            if artwork_id is not None and artwork_id == self._artwork_id:
                return self._artwork
            return None

    def handle(self, action: dict) -> Optional[str]:
        """No action here (media.* goes to the media provider): any id is logged and ignored."""
        _log.warning("now_playing: unknown action %r ignored", action.get("id"))
        return None
