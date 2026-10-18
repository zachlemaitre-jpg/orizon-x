"""A Frame session: sends a folder's images and videos to the device, one file ahead, and obeys its frame.* actions.

One worker thread does everything (scanning, preparing, sending), fed by a queue of commands: start, the device's
actions, setting changes from the PC window, stop. Files go as FRAME_FILE chunks of at most 1 MiB, the first two at
the start and one more for each frame.next / frame.failed, so the device always holds the next file already.
"""
from __future__ import annotations

import queue
import random
import threading
import time
from collections import OrderedDict
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

import protocol
from frame import prepare as prepare_module
from frame.playlist import Playlist, is_video, scan_folder

INTERVALS = (5, 10, 30, 60, 300, 900, 3600)  # seconds an image stays up: 5 s .. 1 h
FITS = protocol.FRAME_FITS  # "crop" fills the screen, "fit" shows the whole image
AHEAD = 2  # files sent at the start; afterwards one per frame.next / frame.failed
RESCAN_S = 10.0  # an empty or unreadable folder is read again this often
STOP_JOIN_S = 3.0
REMEMBERED_FILES = 64  # file id -> path kept for frame.failed

SendState = Callable[[int, str, "str | None", int, str, bool], None]  # epoch, status, folder, interval_s, fit, paused
SendFileChunk = Callable[[int, int, int, int, int, bytes], None]  # epoch, id, kind, total, offset, data


@dataclass(frozen=True)
class FrameConfig:
    folder: str | None = None
    interval_s: int = 30
    fit: str = "crop"


class _FileProblem(Exception):
    """A file that could not be read or prepared: skipped."""


class _Interrupted(Exception):
    """A folder change is waiting: the file in flight is abandoned (it stays in the playlist)."""


class FrameSession:
    """send_state / send_file_chunk may raise OSError (the device left: the session ends quietly) or ValueError.

    config: the settings at the start. screen: the device's (width, height) from HELLO, which sizes the images.
    listener: optional, with on_frame_settings(interval_s, fit, paused), called when the device changes a setting.
    prepare_image, video_codec, scan, rng: replaceable for tests.
    """

    def __init__(self, send_state: SendState, send_file_chunk: SendFileChunk, log: Callable[[str], None],
                 config: FrameConfig, screen: tuple[int, int], ffmpeg: str, listener: Any = None, *,
                 prepare_image: Callable[[Path, tuple[int, int]], bytes] = prepare_module.prepare_image,
                 video_codec: Callable[[str, Path], str | None] = prepare_module.video_codec,
                 scan: Callable[[Any], list[Path]] = scan_folder, rng: random.Random | None = None,
                 rescan_s: float = RESCAN_S) -> None:
        self._send_state_cb = send_state
        self._send_chunk = send_file_chunk
        self._log = log
        self._screen = screen
        self._ffmpeg = ffmpeg
        self._listener = listener
        self._prepare_image = prepare_image
        self._video_codec = video_codec
        self._scan = scan
        self._rng = rng
        self._rescan_s = rescan_s
        self._folder = config.folder or None
        self._interval_s = config.interval_s if config.interval_s in INTERVALS else 30
        self._fit = config.fit if config.fit in FITS else "crop"
        self._paused = False  # every session starts playing
        self._epoch = 1
        self._next_id = 1
        self._playlist: Playlist | None = None
        self._status = "no_folder"
        self._paths: OrderedDict[int, Path] = OrderedDict()
        self._retry_at = 0.0
        self._commands: queue.Queue[tuple] = queue.Queue()
        self._stopping = threading.Event()
        self._interrupt = threading.Event()  # a folder change is waiting: a file in flight is abandoned
        self._requested_folder = self._folder  # the latest folder asked for (any thread); _folder is the worker's
        self._request_lock = threading.Lock()
        self._thread = threading.Thread(target=self._run, name="frame-session", daemon=True)

    # --- called from any thread ---

    def start(self) -> None:
        self._commands.put(("start",))
        self._thread.start()

    def stop(self) -> None:
        self._stopping.set()
        self._interrupt.set()
        self._commands.put(("stop",))
        if self._thread.is_alive() and self._thread is not threading.current_thread():
            self._thread.join(STOP_JOIN_S)

    def handle(self, action: dict) -> None:
        """A frame.* ACTION from the device (its reader thread: never blocks)."""
        self._commands.put(("action", action))

    def set_config(self, folder: str | None, interval_s: int, fit: str) -> None:
        """The PC window changed a setting (or the engine hands over the saved ones): applied at once."""
        folder = folder or None
        with self._request_lock:
            if folder != self._requested_folder:
                self._requested_folder = folder
                self._interrupt.set()
        self._commands.put(("config", folder, interval_s, fit))

    def wait_idle(self, timeout: float = 5.0) -> bool:
        """True once every command queued so far has been dealt with (for tests)."""
        done = threading.Event()
        self._commands.put(("barrier", done))
        return done.wait(timeout)

    # --- worker thread ---

    def _run(self) -> None:
        while not self._stopping.is_set():
            timeout = max(0.0, self._retry_at - time.monotonic()) if self._retrying() else None
            try:
                command = self._commands.get(timeout=timeout)
            except queue.Empty:
                command = ("retry",)
            if command[0] == "stop":
                return
            try:
                self._dispatch(command)
            except OSError:
                self._stopping.set()  # the device left: the engine notices and ends the session
                return
            except Exception as e:  # noqa: BLE001 — a bad command must not stop the slideshow
                self._log(f"Frame: {type(e).__name__}: {e}")

    def _dispatch(self, command: tuple) -> None:
        kind = command[0]
        if kind == "start":
            self._begin()
        elif kind == "action":
            self._on_action(command[1])
        elif kind == "config":
            self._on_config(*command[1:])
        elif kind == "retry":
            self._retry()
        elif kind == "barrier":
            command[1].set()

    def _retrying(self) -> bool:
        return self._playlist is not None and self._status in ("empty", "unreadable")

    def _begin(self) -> None:
        """(Re)starts the playlist for the current folder: the state first, then the first two files."""
        self._paths.clear()
        if self._folder is None:
            self._playlist = None
            self._status = "no_folder"
            self._send_state()
            return
        self._playlist = Playlist(self._folder, self._scan, self._rng)
        self._status = self._playlist.status
        self._send_state()
        self._note_status()
        if self._status == "ok":
            self._send_ahead(AHEAD)

    def _folder_name(self) -> str | None:
        if self._folder is None:
            return None
        return Path(self._folder).name or self._folder

    def _send_state(self) -> None:
        try:
            self._send_state_cb(self._epoch, self._status, self._folder_name(), self._interval_s, self._fit,
                                self._paused)
        except ValueError as e:
            self._log(f"Frame: cannot send the state: {e}")

    def _note_status(self) -> None:
        if self._status == "empty":
            self._log("Frame: no image or video in the folder")
        elif self._status == "unreadable":
            self._log("Frame: cannot read the folder")
        if self._status in ("empty", "unreadable"):
            self._retry_at = time.monotonic() + self._rescan_s

    def _set_status(self, status: str) -> None:
        if status != self._status:
            self._status = status
            self._send_state()
            self._note_status()

    def _retry(self) -> None:
        self._retry_at = time.monotonic() + self._rescan_s
        if self._retrying():
            self._send_ahead(AHEAD)

    # --- files ---

    def _send_ahead(self, count: int) -> None:
        playlist = self._playlist
        assert playlist is not None
        sent = 0
        while sent < count and not self._stopping.is_set() and not self._interrupt.is_set():
            path = playlist.next()
            if path is None:
                self._set_status(playlist.status)  # empty or unreadable
                return
            try:
                kind, total, data = self._prepare(path)
            except _FileProblem as e:
                self._log(f"Frame: skipping {path.name}: {e}")
                playlist.remove(path)
                continue
            self._set_status("ok")
            try:
                self._send_file(path, kind, total, data)
            except _Interrupted:
                return
            except _FileProblem as e:
                self._log(f"Frame: skipping {path.name}: {e}")
                playlist.remove(path)
                continue
            sent += 1

    def _prepare(self, path: Path) -> tuple[int, int, bytes | None]:
        """(kind, total size, bytes for an image / None for a video streamed from disk), or _FileProblem."""
        if is_video(path):
            try:
                size = path.stat().st_size
            except OSError as e:
                raise _FileProblem(str(e)) from e
            if size <= 0:
                raise _FileProblem("empty file")
            if size > prepare_module.MAX_VIDEO_BYTES:
                raise _FileProblem(f"video larger than {prepare_module.MAX_VIDEO_BYTES // 1024**3} GiB")
            codec = self._video_codec(self._ffmpeg, path)
            if codec not in prepare_module.VIDEO_CODECS:
                raise _FileProblem(f"video codec {codec or 'unknown'} not supported by the device")
            return protocol.FRAME_KIND_VIDEO, size, None
        try:
            data = self._prepare_image(path, self._screen)
        except Exception as e:  # noqa: BLE001 — PrepareError, but also whatever Qt or the disk throws
            raise _FileProblem(str(e) or type(e).__name__) from e
        if not data:
            raise _FileProblem("empty image")
        return protocol.FRAME_KIND_IMAGE, len(data), data

    def _send_file(self, path: Path, kind: int, total: int, data: bytes | None) -> None:
        """Sends the file as chunks of at most 1 MiB. _FileProblem if it cannot be read, _Interrupted if cut short."""
        file_id = self._next_id
        self._next_id += 1
        self._paths[file_id] = path
        while len(self._paths) > REMEMBERED_FILES:
            self._paths.popitem(last=False)
        epoch = self._epoch
        chunk_size = protocol.MAX_FRAME_CHUNK
        offset = 0
        source = None
        try:
            if data is None:
                try:
                    source = path.open("rb")
                except OSError as e:
                    raise _FileProblem(str(e)) from e
            while offset < total:
                if self._stopping.is_set():
                    raise OSError("session stopped")
                if self._interrupt.is_set():
                    # A folder change is waiting: the device drops this file with the old epoch anyway.
                    raise _Interrupted
                if source is None:
                    chunk = data[offset:offset + chunk_size]
                else:
                    try:
                        chunk = source.read(min(chunk_size, total - offset))
                    except OSError as e:
                        raise _FileProblem(str(e)) from e
                    if not chunk:
                        raise _FileProblem("the file got shorter while it was sent")
                self._send_chunk(epoch, file_id, kind, total, offset, chunk)
                offset += len(chunk)
        finally:
            if source is not None:
                source.close()

    # --- actions and settings ---

    def _on_action(self, action: dict) -> None:
        action_id = action.get("id")
        if action_id == "frame.next":
            if self._playlist is not None:
                self._send_ahead(1)
        elif action_id == "frame.failed":
            self._on_failed(action.get("file"))
        elif action_id == "frame.pause":
            paused = action.get("paused")
            if not isinstance(paused, bool):
                self._log(f"Frame: frame.pause ignored: paused must be true or false, not {paused!r}")
                return
            self._paused = paused
            self._settings_changed_by_device()
        elif action_id == "frame.fit":
            fit = action.get("fit")
            if fit not in FITS:
                self._log(f"Frame: frame.fit ignored: fit must be one of {FITS}, not {fit!r}")
                return
            self._fit = fit
            self._settings_changed_by_device()
        elif action_id == "frame.interval":
            interval = action.get("interval_s")
            if isinstance(interval, bool) or interval not in INTERVALS:
                self._log(f"Frame: frame.interval ignored: {interval!r} is not one of {INTERVALS}")
                return
            self._interval_s = interval
            self._settings_changed_by_device()
        else:
            self._log(f"Frame: unknown action {action_id!r} ignored")

    def _on_failed(self, file_id: Any) -> None:
        path = self._paths.pop(file_id, None) if isinstance(file_id, int) and not isinstance(file_id, bool) else None
        if path is None:
            self._log(f"Frame: frame.failed for an unknown file ({file_id!r}) ignored")
            return
        self._log(f"Frame: the device could not show {path.name}: removed from the playlist")
        if self._playlist is not None:
            self._playlist.remove(path)
            self._send_ahead(1)

    def _settings_changed_by_device(self) -> None:
        self._send_state()
        listener = getattr(self._listener, "on_frame_settings", None)
        if listener is not None:
            try:
                listener(self._interval_s, self._fit, self._paused)
            except Exception as e:  # noqa: BLE001 — the listener is not the session's business
                self._log(f"Frame: settings listener failed: {e}")

    def _on_config(self, folder: str | None, interval_s: int, fit: str) -> None:
        """Settings from the PC window. A new folder starts a new epoch; the other settings only update the state."""
        with self._request_lock:
            if folder == self._requested_folder:
                self._interrupt.clear()  # no newer folder change is waiting behind this one
        if interval_s not in INTERVALS or isinstance(interval_s, bool):
            self._log(f"Frame: interval {interval_s!r} ignored: not one of {INTERVALS}")
            interval_s = self._interval_s
        if fit not in FITS:
            self._log(f"Frame: fit {fit!r} ignored: not one of {FITS}")
            fit = self._fit
        settings_changed = (interval_s, fit) != (self._interval_s, self._fit)
        self._interval_s, self._fit = interval_s, fit
        if folder != self._folder:
            self._folder = folder
            self._epoch += 1
            self._begin()
        elif settings_changed:
            self._send_state()
