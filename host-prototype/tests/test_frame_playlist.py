import os
import random
import tempfile
import unittest
from pathlib import Path

from frame import playlist
from frame.playlist import FolderUnreadable, Playlist, scan_folder


def touch(root, *names):
    for name in names:
        path = Path(root, name)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"x")


def hide(path, attributes):
    import ctypes
    if not ctypes.windll.kernel32.SetFileAttributesW(str(path), attributes):
        raise OSError("SetFileAttributesW failed")


class ScanFolderTest(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = temp.name

    def names(self):
        return [p.relative_to(self.root).as_posix() for p in scan_folder(self.root)]

    def test_extension_sets(self):
        self.assertEqual(playlist.IMAGE_EXTS, {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".gif"})
        self.assertEqual(playlist.VIDEO_EXTS, {".mp4", ".m4v", ".mov", ".webm", ".mkv"})

    def test_keeps_images_and_videos_only_case_insensitively_and_sorted(self):
        touch(self.root, "b.JPG", "a.png", "c.Mp4", "d.txt", "e.docx", "noext", "f.gif", "g.WEBM")
        self.assertEqual(self.names(), ["a.png", "b.JPG", "c.Mp4", "f.gif", "g.WEBM"])

    def test_includes_subfolders(self):
        touch(self.root, "top.jpg", "sub/one.png", "sub/deep/two.mkv", "empty/readme.txt")
        self.assertEqual(self.names(), ["sub/deep/two.mkv", "sub/one.png", "top.jpg"])

    def test_skips_dot_names_files_and_folders(self):
        touch(self.root, ".hidden.jpg", ".git/a.jpg", "ok.jpg")
        self.assertEqual(self.names(), ["ok.jpg"])

    @unittest.skipUnless(os.name == "nt", "Windows file attributes")
    def test_skips_hidden_and_system_files_and_folders(self):
        touch(self.root, "visible.jpg", "hid.jpg", "sys.jpg", "hidden_dir/a.jpg", "system_dir/b.jpg", "ok_dir/c.jpg")
        hide(Path(self.root, "hid.jpg"), 0x2)  # FILE_ATTRIBUTE_HIDDEN
        hide(Path(self.root, "sys.jpg"), 0x4)  # FILE_ATTRIBUTE_SYSTEM
        hide(Path(self.root, "hidden_dir"), 0x2)
        hide(Path(self.root, "system_dir"), 0x4)
        self.assertEqual(self.names(), ["ok_dir/c.jpg", "visible.jpg"])

    def test_missing_root_is_unreadable(self):
        with self.assertRaises(FolderUnreadable):
            scan_folder(Path(self.root, "nope"))

    def test_a_file_as_root_is_unreadable(self):
        touch(self.root, "a.jpg")
        with self.assertRaises(FolderUnreadable):
            scan_folder(Path(self.root, "a.jpg"))

    def test_empty_folder_is_not_an_error(self):
        self.assertEqual(scan_folder(self.root), [])


def paths(*names):
    return [Path(n) for n in names]


class PlaylistTest(unittest.TestCase):
    def make(self, files, seed=1):
        """A playlist over `files` (a list the test can change), with a fixed shuffle."""
        self.files = None if files is None else list(files)
        self.scans = 0

        def scan(folder):
            self.scans += 1
            if self.files is None:
                raise FolderUnreadable("gone")
            return list(self.files)

        return Playlist("folder", scan=scan, rng=random.Random(seed))

    def round_of(self, pl, count):
        return [pl.next() for _ in range(count)]

    def test_each_file_once_per_round(self):
        pl = self.make(paths("a", "b", "c", "d", "e"))
        first = self.round_of(pl, 5)
        self.assertEqual(sorted(first), paths("a", "b", "c", "d", "e"))
        second = self.round_of(pl, 5)
        self.assertEqual(sorted(second), paths("a", "b", "c", "d", "e"))

    def test_order_is_shuffled(self):
        orders = {tuple(self.round_of(self.make(paths(*"abcdef"), seed), 6)) for seed in range(10)}
        self.assertGreater(len(orders), 1)

    def test_the_last_file_of_a_round_never_starts_the_next(self):
        for seed in range(300):
            pl = self.make(paths("a", "b", "c"), seed)
            previous = self.round_of(pl, 3)[-1]
            for _ in range(5):
                current = self.round_of(pl, 3)
                self.assertNotEqual(current[0], previous, seed)
                previous = current[-1]

    def test_two_files_alternate(self):
        pl = self.make(paths("a", "b"))
        seen = self.round_of(pl, 8)
        self.assertTrue(all(x != y for x, y in zip(seen, seen[1:])), seen)

    def test_single_file_repeats(self):
        pl = self.make(paths("a"))
        self.assertEqual(self.round_of(pl, 3), paths("a", "a", "a"))
        self.assertEqual(pl.status, "ok")

    def test_folder_is_read_at_creation_and_at_each_round(self):
        pl = self.make(paths("a", "b"))
        self.assertEqual(self.scans, 1)
        self.round_of(pl, 2)
        self.assertEqual(self.scans, 1)  # the round is not over until the next call
        pl.next()
        self.assertEqual(self.scans, 2)

    def test_new_files_appear_at_the_next_round(self):
        pl = self.make(paths("a", "b"))
        self.round_of(pl, 2)
        self.files = paths("a", "b", "c")
        self.assertEqual(sorted(self.round_of(pl, 3)), paths("a", "b", "c"))

    def test_deleted_files_leave_at_the_next_round(self):
        pl = self.make(paths("a", "b", "c"))
        self.round_of(pl, 3)
        self.files = paths("a", "c")
        self.assertEqual(sorted(self.round_of(pl, 2)), paths("a", "c"))

    def test_remove_drops_the_file_from_the_round_and_for_good(self):
        pl = self.make(paths("a", "b", "c"))
        first = pl.next()
        victim = next(p for p in paths("a", "b", "c") if p != first)
        pl.remove(victim)
        rest = [pl.next()]
        self.assertNotIn(victim, rest)
        for _ in range(6):
            self.assertNotEqual(pl.next(), victim)

    def test_removing_every_file_gives_empty(self):
        pl = self.make(paths("a", "b"))
        for p in (pl.next(), pl.next()):
            pl.remove(p)
        self.assertIsNone(pl.next())
        self.assertEqual(pl.status, "empty")

    def test_status_ok_empty_unreadable(self):
        pl = self.make(paths("a"))
        self.assertEqual(pl.status, "ok")
        self.files = []
        pl.next()
        self.assertIsNone(pl.next())
        self.assertEqual(pl.status, "empty")
        self.files = None
        self.assertIsNone(pl.next())
        self.assertEqual(pl.status, "unreadable")
        self.files = paths("z")
        self.assertEqual(pl.next(), Path("z"))
        self.assertEqual(pl.status, "ok")

    def test_status_is_known_right_after_creation(self):
        self.assertEqual(self.make([]).status, "empty")
        self.assertEqual(self.make(None).status, "unreadable")

    def test_default_scan_reads_the_real_folder(self):
        with tempfile.TemporaryDirectory() as root:
            touch(root, "a.jpg", "b.png", "c.txt")
            pl = Playlist(root)
            self.assertEqual(sorted(p.name for p in (pl.next(), pl.next())), ["a.jpg", "b.png"])
            self.assertEqual(Playlist(Path(root, "missing")).status, "unreadable")


if __name__ == "__main__":
    unittest.main()
