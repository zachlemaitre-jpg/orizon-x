"""The files of a folder in shuffled rounds: each file once per round, re-reading the folder at every round."""
from __future__ import annotations

import os
import random
import stat
from pathlib import Path
from typing import Callable

IMAGE_EXTS = frozenset({".jpg", ".jpeg", ".png", ".webp", ".bmp", ".gif"})  # a GIF is shown as a still image
VIDEO_EXTS = frozenset({".mp4", ".m4v", ".mov", ".webm", ".mkv"})
MEDIA_EXTS = IMAGE_EXTS | VIDEO_EXTS
_HIDDEN_OR_SYSTEM = stat.FILE_ATTRIBUTE_HIDDEN | stat.FILE_ATTRIBUTE_SYSTEM


class FolderUnreadable(Exception):
    """The folder is missing, deleted or cannot be listed."""


def is_video(path: Path) -> bool:
    return path.suffix.lower() in VIDEO_EXTS


def _hidden(entry: os.DirEntry) -> bool:
    if entry.name.startswith("."):
        return True
    try:
        return bool(getattr(entry.stat(follow_symlinks=False), "st_file_attributes", 0) & _HIDDEN_OR_SYSTEM)
    except OSError:
        return True  # cannot even be stat'ed: not worth showing


def _walk(folder: Path, files: list[Path], root: bool) -> None:
    try:
        with os.scandir(folder) as entries:
            listed = list(entries)
    except OSError as e:
        if root:
            raise FolderUnreadable(str(e)) from e
        return  # an unreadable subfolder is skipped, the rest of the folder still plays
    for entry in listed:
        if _hidden(entry):
            continue
        try:
            if entry.is_dir(follow_symlinks=False):
                _walk(Path(entry.path), files, False)
            elif entry.is_file() and Path(entry.name).suffix.lower() in MEDIA_EXTS:
                files.append(Path(entry.path))
        except OSError:
            continue


def scan_folder(folder: str | Path) -> list[Path]:
    """Every image and video under `folder` (subfolders included), without hidden or system files, sorted.

    Raises FolderUnreadable when `folder` itself cannot be listed.
    """
    files: list[Path] = []
    _walk(Path(folder), files, True)
    return sorted(files, key=lambda p: str(p).casefold())


class Playlist:
    """next() walks a shuffled round of the folder's files; an exhausted round re-reads the folder and reshuffles.

    The first file of a new round is never the last one played (when there are at least two files).
    remove(path) leaves a file out for the playlist's whole life (a file that could not be shown).
    status: "ok", "empty" (no usable file) or "unreadable" (the folder cannot be read), as of the last read.
    """

    def __init__(self, folder: str | Path, scan: Callable[[str | Path], list[Path]] = scan_folder,
                 rng: random.Random | None = None) -> None:
        self._folder = folder
        self._scan = scan
        self._rng = rng or random.Random()
        self._removed: set[Path] = set()
        self._pending: list[Path] = []
        self._last: Path | None = None
        self.status = "ok"
        self._new_round()

    def _new_round(self) -> None:
        try:
            files = [p for p in self._scan(self._folder) if p not in self._removed]
        except FolderUnreadable:
            self.status, self._pending = "unreadable", []
            return
        if not files:
            self.status, self._pending = "empty", []
            return
        self._rng.shuffle(files)
        if len(files) >= 2 and files[0] == self._last:
            files[0], files[1] = files[1], files[0]
        self.status, self._pending = "ok", files

    def next(self) -> Path | None:
        """The next file, or None when the folder is empty or unreadable (see status)."""
        if not self._pending:
            self._new_round()
        if not self._pending:
            return None
        self._last = self._pending.pop(0)
        return self._last

    def remove(self, path: Path) -> None:
        self._removed.add(path)
        self._pending = [p for p in self._pending if p != path]
