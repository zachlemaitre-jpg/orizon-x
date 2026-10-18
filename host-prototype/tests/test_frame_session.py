import random
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

import protocol
from frame import prepare as prepare_module
from frame import session as session_module
from frame.session import INTERVALS, FrameConfig, FrameSession

MIB = 1024 * 1024


def wait_until(predicate, timeout=5.0):
    deadline = time.monotonic() + timeout
    while not predicate():
        if time.monotonic() > deadline:
            raise AssertionError("délai dépassé")
        time.sleep(0.005)


class Listener:
    def __init__(self):
        self.calls = []

    def on_frame_settings(self, interval_s, fit, paused):
        self.calls.append((interval_s, fit, paused))


class Rig:
    """A FrameSession over a real temp folder, with fake prepare / codec / sends that record what the device gets."""

    def __init__(self, test, names=(), folder_name="Photos", interval_s=30, fit="crop", image_bytes=None,
                 codecs=None, start=True, **kwargs):
        temp = tempfile.TemporaryDirectory()
        test.addCleanup(temp.cleanup)
        self.test = test
        self.root = Path(temp.name) / folder_name
        self.root.mkdir()
        self.events = []  # ("state", args) and ("chunk", args), in order
        self.logs = []
        self.listener = Listener()
        self.image_bytes = image_bytes or (lambda path: b"JPEG:" + path.name.encode())
        self.codecs = codecs or {}
        self.prepared = []
        self.send_error = None
        self.chunk_hook = None
        for name in names:
            self.add(name)
        self.session = FrameSession(self._state, self._chunk, self.logs.append,
                                    FrameConfig(str(self.root), interval_s, fit), (2560, 1600), "ffmpeg.exe",
                                    self.listener, prepare_image=self._prepare, video_codec=self._codec,
                                    rng=random.Random(3), rescan_s=kwargs.pop("rescan_s", 60.0), **kwargs)
        test.addCleanup(self.session.stop)
        if start:
            self.session.start()
            self.idle()

    def add(self, name, size=None):
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"v" * size if size else b"x")
        return path

    def _prepare(self, path, screen):
        self.test.assertEqual(screen, (2560, 1600))
        self.prepared.append(path.name)
        result = self.image_bytes(path)
        if isinstance(result, Exception):
            raise result
        return result

    def _codec(self, ffmpeg, path):
        self.test.assertEqual(ffmpeg, "ffmpeg.exe")
        return self.codecs.get(path.name, "h264")

    def _state(self, *args):
        if self.send_error is not None:
            raise self.send_error
        self.events.append(("state", args))

    def _chunk(self, *args):
        if self.chunk_hook is not None:
            self.chunk_hook(args)
        if self.send_error is not None:
            raise self.send_error
        self.events.append(("chunk", args))

    def idle(self):
        self.test.assertTrue(self.session.wait_idle())

    def act(self, **action):
        self.session.handle(action)
        self.idle()

    def states(self):
        return [args for kind, args in self.events if kind == "state"]

    def chunks(self):
        return [args for kind, args in self.events if kind == "chunk"]

    def files(self):
        """[(epoch, id, kind, total, bytes)] of the complete files received, in order."""
        files = {}
        order = []
        for epoch, file_id, kind, total, offset, data in self.chunks():
            key = (epoch, file_id)
            if key not in files:
                files[key] = [kind, total, bytearray()]
                order.append(key)
            entry = files[key]
            self.test.assertEqual(offset, len(entry[2]))  # in order, no gap
            entry[2] += data
        return [(e, i, files[(e, i)][0], files[(e, i)][1], bytes(files[(e, i)][2])) for e, i in order]


class StartTest(unittest.TestCase):
    def test_state_first_then_two_files_ahead(self):
        rig = Rig(self, ["a.jpg", "b.jpg", "c.jpg"])
        self.assertEqual(rig.events[0], ("state", (1, "ok", "Photos", 30, "crop", False)))
        files = rig.files()
        self.assertEqual([(f[0], f[1], f[2]) for f in files], [(1, 1, 1), (1, 2, 1)])
        self.assertEqual(len(rig.events), 1 + len(rig.chunks()))
        self.assertEqual(len(rig.states()), 1)
        for _epoch, _id, _kind, total, data in files:
            self.assertEqual(total, len(data))
            self.assertTrue(data.startswith(b"JPEG:"))

    def test_each_next_sends_one_more_file_with_increasing_ids(self):
        rig = Rig(self, ["a.jpg", "b.jpg", "c.jpg"])
        rig.act(id="frame.next")
        rig.act(id="frame.next")
        rig.act(id="frame.next")
        self.assertEqual([f[1] for f in rig.files()], [1, 2, 3, 4, 5])
        self.assertEqual(len(rig.states()), 1)  # a next changes no state

    def test_every_file_of_a_round_comes_before_a_repeat(self):
        rig = Rig(self, ["a.jpg", "b.jpg", "c.jpg"])
        rig.act(id="frame.next")
        names = [f[4][5:].decode() for f in rig.files()]
        self.assertEqual(sorted(names), ["a.jpg", "b.jpg", "c.jpg"])

    def test_settings_from_the_config_are_in_the_state(self):
        rig = Rig(self, ["a.jpg"], interval_s=300, fit="fit")
        self.assertEqual(rig.states()[0], (1, "ok", "Photos", 300, "fit", False))

    def test_the_folder_name_is_the_last_part_of_the_path(self):
        rig = Rig(self, ["a.jpg"], folder_name="Vacances été")
        self.assertEqual(rig.states()[0][2], "Vacances été")

    def test_the_images_are_prepared_for_the_device_screen(self):
        rig = Rig(self, ["a.jpg"])
        self.assertTrue(rig.prepared)  # Rig._prepare asserts the screen is the HELLO one

    def test_default_deps_are_the_real_ones(self):
        FrameSession(lambda *a: None, lambda *a: None, lambda line: None, FrameConfig(), (1, 1), "ffmpeg")
        self.assertEqual(INTERVALS, (5, 10, 30, 60, 300, 900, 3600))
        self.assertEqual(FrameConfig(), FrameConfig(None, 30, "crop"))


class FilesTest(unittest.TestCase):
    def test_a_large_image_goes_in_one_mebibyte_chunks(self):
        data = bytes(range(256)) * (10 * MIB // 4 // 256)  # 2.5 MiB
        rig = Rig(self, ["a.jpg"], image_bytes=lambda path: data)
        first = [c for c in rig.chunks() if c[1] == 1]
        self.assertEqual([(c[4], len(c[5])) for c in first], [(0, MIB), (MIB, MIB), (2 * MIB, MIB // 2)])
        self.assertTrue(all(c[3] == len(data) and c[2] == protocol.FRAME_KIND_IMAGE for c in first))
        self.assertEqual(b"".join(c[5] for c in first), data)

    def test_an_image_of_exactly_one_chunk_is_one_chunk(self):
        rig = Rig(self, ["a.jpg"], image_bytes=lambda path: b"z" * MIB)
        self.assertEqual([(c[4], len(c[5])) for c in rig.chunks() if c[1] == 1], [(0, MIB)])

    def test_a_video_is_streamed_from_disk_as_is(self):
        rig = Rig(self, [], start=False)
        content = (bytes(range(251)) * (3 * MIB // 251))[:2 * MIB + MIB // 2]
        video = rig.add("clip.mp4")
        video.write_bytes(content)
        rig.session.start()
        rig.idle()
        first = [c for c in rig.chunks() if c[1] == 1]
        self.assertEqual([c[2] for c in first], [protocol.FRAME_KIND_VIDEO] * 3)
        self.assertEqual([(c[4], len(c[5])) for c in first], [(0, MIB), (MIB, MIB), (2 * MIB, MIB // 2)])
        self.assertEqual(b"".join(c[5] for c in first), content)
        self.assertEqual(rig.prepared, [])  # not run through the image path

    def test_the_four_supported_codecs_are_sent(self):
        names = ["a.mp4", "b.mkv", "c.webm", "d.mov"]
        rig = Rig(self, names, codecs={"a.mp4": "h264", "b.mkv": "hevc", "c.webm": "vp9", "d.mov": "vp8"},
                  start=False)
        rig.session.start()
        rig.idle()
        for _ in range(2):
            rig.act(id="frame.next")
        self.assertEqual(len(rig.files()), 4)

    def test_an_unsupported_video_codec_is_skipped_with_a_log_line(self):
        rig = Rig(self, ["a.mp4", "b.jpg", "c.jpg"], codecs={"a.mp4": "av1"})
        for _ in range(4):
            rig.act(id="frame.next")
        self.assertTrue(all(f[2] == protocol.FRAME_KIND_IMAGE for f in rig.files()))
        self.assertEqual(len(rig.files()), 6)
        self.assertEqual([line for line in rig.logs if "a.mp4" in line],
                         ["Frame: skipping a.mp4: video codec av1 not supported by the device"])  # only once: removed

    def test_an_unknown_video_codec_is_skipped(self):
        rig = Rig(self, ["a.mp4", "b.jpg"], codecs={"a.mp4": None})
        self.assertTrue(any("a.mp4" in line and "unknown" in line for line in rig.logs))

    def test_a_video_over_the_size_limit_is_skipped(self):
        with mock.patch.object(prepare_module, "MAX_VIDEO_BYTES", 10):
            rig = Rig(self, ["b.jpg"], start=False)
            rig.add("big.mp4", size=11)
            rig.session.start()
            rig.idle()
        self.assertTrue(any("big.mp4" in line and "larger" in line for line in rig.logs))
        self.assertTrue(all(f[2] == protocol.FRAME_KIND_IMAGE for f in rig.files()))

    def test_an_empty_video_is_skipped(self):
        rig = Rig(self, ["b.jpg"], start=False)
        (rig.root / "zero.mp4").write_bytes(b"")
        rig.session.start()
        rig.idle()
        self.assertTrue(any("zero.mp4" in line for line in rig.logs))

    def test_an_image_that_cannot_be_prepared_is_skipped_and_logged(self):
        def image_bytes(path):
            return prepare_module.PrepareError("bad pixels") if path.name == "bad.jpg" else b"ok" + path.name.encode()

        rig = Rig(self, ["bad.jpg", "good.jpg", "fine.png"], image_bytes=image_bytes)
        rig.act(id="frame.next")
        self.assertEqual(len(rig.files()), 3)
        self.assertEqual([line for line in rig.logs if "bad.jpg" in line], ["Frame: skipping bad.jpg: bad pixels"])
        self.assertTrue(all(b"bad" not in f[4] for f in rig.files()))

    def test_a_video_that_vanishes_before_sending_is_skipped(self):
        rig = Rig(self, ["b.jpg"], start=False)
        video = rig.add("gone.mp4")
        original = Path.open

        def fake_open(path, *args, **kwargs):
            if path == video:
                raise PermissionError("locked")
            return original(path, *args, **kwargs)

        with mock.patch.object(Path, "open", fake_open):
            rig.session.start()
            rig.idle()
        self.assertTrue(any("gone.mp4" in line and "locked" in line for line in rig.logs))
        self.assertEqual(len(rig.files()), 2)

    def test_all_files_failing_makes_the_folder_empty(self):
        rig = Rig(self, ["a.jpg", "b.jpg"], image_bytes=lambda path: prepare_module.PrepareError("nope"))
        self.assertEqual([s[1] for s in rig.states()], ["ok", "empty"])
        self.assertEqual(rig.chunks(), [])
        self.assertEqual(rig.states()[-1][:3], (1, "empty", "Photos"))


class FolderStatusTest(unittest.TestCase):
    def test_no_folder_sends_the_state_and_nothing_else(self):
        sent = []
        session = FrameSession(lambda *a: sent.append(("state", a)), lambda *a: sent.append(("chunk", a)),
                               lambda line: None, FrameConfig(None, 60, "fit"), (2560, 1600), "ffmpeg.exe")
        self.addCleanup(session.stop)
        session.start()
        self.assertTrue(session.wait_idle())
        self.assertEqual(sent, [("state", (1, "no_folder", None, 60, "fit", False))])
        session.handle({"id": "frame.next"})
        self.assertTrue(session.wait_idle())
        self.assertEqual(len(sent), 1)

    def test_an_empty_folder(self):
        rig = Rig(self, ["notes.txt"])
        self.assertEqual(rig.states(), [(1, "empty", "Photos", 30, "crop", False)])
        self.assertEqual(rig.chunks(), [])

    def test_an_unreadable_folder(self):
        rig = Rig(self, [], start=False)
        rig.root.rmdir()
        rig.session.start()
        rig.idle()
        self.assertEqual(rig.states(), [(1, "unreadable", "Photos", 30, "crop", False)])
        self.assertEqual(rig.chunks(), [])

    def test_an_empty_folder_is_read_again_and_plays_once_it_has_files(self):
        rig = Rig(self, [], rescan_s=0.05)
        self.assertEqual([s[1] for s in rig.states()], ["empty"])
        rig.add("a.jpg")
        wait_until(lambda: len(rig.files()) == 2)
        self.assertEqual([s[1] for s in rig.states()], ["empty", "ok"])
        order = [kind for kind, _args in rig.events]
        self.assertEqual(order, ["state", "state", "chunk", "chunk"])  # the state before the first file
        self.assertEqual(len(rig.states()), 2)  # no more states while it plays

    def test_an_unreadable_folder_that_comes_back_plays(self):
        rig = Rig(self, [], start=False, rescan_s=0.05)
        rig.root.rmdir()
        rig.session.start()
        rig.idle()
        rig.root.mkdir()
        rig.add("a.png")
        wait_until(lambda: [s[1] for s in rig.states()] == ["unreadable", "ok"] and len(rig.files()) == 2)

    def test_a_folder_deleted_during_play_becomes_unreadable_at_the_next_round(self):
        rig = Rig(self, ["a.jpg"], rescan_s=0.05)
        for child in rig.root.iterdir():
            child.unlink()
        rig.root.rmdir()
        rig.act(id="frame.next")
        wait_until(lambda: rig.states()[-1][1] == "unreadable")
        count = len(rig.states())
        time.sleep(0.2)  # re-read every 0.05 s, but the status does not change: no more states
        self.assertEqual(len(rig.states()), count)

    def test_a_folder_that_empties_shows_empty_at_the_next_round(self):
        rig = Rig(self, ["a.jpg"])
        (rig.root / "a.jpg").unlink()
        rig.act(id="frame.next")
        self.assertEqual(rig.states()[-1][1], "empty")


class SettingsActionsTest(unittest.TestCase):
    def test_pause_updates_the_state_and_tells_the_listener(self):
        rig = Rig(self, ["a.jpg"])
        rig.act(id="frame.pause", paused=True)
        self.assertEqual(rig.states()[-1], (1, "ok", "Photos", 30, "crop", True))
        self.assertEqual(rig.listener.calls, [(30, "crop", True)])
        rig.act(id="frame.pause", paused=False)
        self.assertEqual(rig.states()[-1][5], False)
        self.assertEqual(rig.listener.calls[-1], (30, "crop", False))

    def test_fit_updates_the_state_and_tells_the_listener(self):
        rig = Rig(self, ["a.jpg"])
        rig.act(id="frame.fit", fit="fit")
        self.assertEqual(rig.states()[-1], (1, "ok", "Photos", 30, "fit", False))
        self.assertEqual(rig.listener.calls, [(30, "fit", False)])

    def test_interval_updates_the_state_and_tells_the_listener(self):
        rig = Rig(self, ["a.jpg"])
        for value in INTERVALS:
            rig.act(id="frame.interval", interval_s=value)
            self.assertEqual(rig.states()[-1][3], value)
            self.assertEqual(rig.listener.calls[-1], (value, "crop", False))

    def test_settings_are_remembered_for_later_states(self):
        rig = Rig(self, ["a.jpg"])
        rig.act(id="frame.pause", paused=True)
        rig.act(id="frame.fit", fit="fit")
        rig.act(id="frame.interval", interval_s=900)
        rig.session.set_config(str(rig.root), 900, "fit")
        rig.idle()
        self.assertEqual(len(rig.states()), 4)  # the same settings again change nothing
        rig.session.set_config(str(rig.root.parent), 900, "fit")
        rig.idle()
        self.assertEqual(rig.states()[-1][:2] + rig.states()[-1][3:], (2, "ok", 900, "fit", True))

    def test_invalid_values_are_ignored_and_logged(self):
        rig = Rig(self, ["a.jpg"])
        before = len(rig.states())
        for action in ({"id": "frame.interval", "interval_s": 7}, {"id": "frame.interval", "interval_s": "30"},
                       {"id": "frame.interval", "interval_s": True}, {"id": "frame.interval"},
                       {"id": "frame.fit", "fit": "stretch"}, {"id": "frame.fit"},
                       {"id": "frame.pause", "paused": "yes"}, {"id": "frame.pause"},
                       {"id": "frame.unknown"}):
            with self.subTest(action=action):
                logs = len(rig.logs)
                rig.act(**action)
                self.assertEqual(len(rig.logs), logs + 1)
        self.assertEqual(len(rig.states()), before)
        self.assertEqual(rig.listener.calls, [])

    def test_a_failing_listener_does_not_stop_the_session(self):
        rig = Rig(self, ["a.jpg", "b.jpg"])
        rig.listener.on_frame_settings = mock.Mock(side_effect=RuntimeError("boom"))
        rig.act(id="frame.fit", fit="fit")
        self.assertTrue(any("boom" in line for line in rig.logs))
        rig.act(id="frame.next")
        self.assertEqual(len(rig.files()), 3)

    def test_without_a_listener_it_still_works(self):
        rig = Rig(self, ["a.jpg"])
        rig.session._listener = None
        rig.act(id="frame.fit", fit="fit")
        self.assertEqual(rig.states()[-1][4], "fit")


class FailedTest(unittest.TestCase):
    def test_failed_removes_that_file_and_sends_the_next(self):
        rig = Rig(self, ["a.jpg", "b.jpg", "c.jpg"])
        first = rig.files()[0]
        failed_name = first[4][5:].decode()
        rig.act(id="frame.failed", file=first[1])
        self.assertEqual(len(rig.files()), 3)
        for _ in range(8):
            rig.act(id="frame.next")
        later = [f[4][5:].decode() for f in rig.files()[2:]]
        self.assertNotIn(failed_name, later)
        self.assertTrue(any(failed_name in line for line in rig.logs))

    def test_failing_the_last_playable_file_makes_the_folder_empty(self):
        rig = Rig(self, ["a.jpg"])
        rig.act(id="frame.failed", file=1)
        rig.act(id="frame.failed", file=2)
        self.assertEqual(rig.states()[-1][1], "empty")

    def test_an_unknown_or_bad_file_id_is_ignored(self):
        rig = Rig(self, ["a.jpg", "b.jpg"])
        count = len(rig.files())
        for value in (99, "1", None, True, 1.0):
            with self.subTest(value=value):
                rig.act(id="frame.failed", file=value)
        self.assertEqual(len(rig.files()), count)

    def test_the_same_file_failing_twice_sends_only_one_more(self):
        rig = Rig(self, ["a.jpg", "b.jpg", "c.jpg"])
        rig.act(id="frame.failed", file=1)
        rig.act(id="frame.failed", file=1)
        self.assertEqual(len(rig.files()), 3)


class EpochTest(unittest.TestCase):
    def test_a_folder_change_starts_a_new_epoch_with_two_new_files(self):
        rig = Rig(self, ["a.jpg", "b.jpg"])
        other = rig.root.parent / "Other"
        other.mkdir()
        (other / "x.jpg").write_bytes(b"x")
        (other / "y.jpg").write_bytes(b"x")
        rig.session.set_config(str(other), 30, "crop")
        rig.idle()
        self.assertEqual(rig.states()[-1], (2, "ok", "Other", 30, "crop", False))
        files = rig.files()
        self.assertEqual([(f[0], f[1]) for f in files], [(1, 1), (1, 2), (2, 3), (2, 4)])  # ids keep increasing
        self.assertEqual({f[4][5:].decode() for f in files[2:]}, {"x.jpg", "y.jpg"})
        state_index = max(i for i, (kind, _a) in enumerate(rig.events) if kind == "state")
        self.assertTrue(all(kind == "chunk" and args[0] == 2 for kind, args in rig.events[state_index + 1:]))

    def test_clearing_the_folder_shows_no_folder_in_a_new_epoch(self):
        rig = Rig(self, ["a.jpg"])
        rig.session.set_config(None, 30, "crop")
        rig.idle()
        self.assertEqual(rig.states()[-1], (2, "no_folder", None, 30, "crop", False))
        rig.act(id="frame.next")
        self.assertEqual(len(rig.files()), 2)  # nothing more is sent

    def test_the_epoch_does_not_change_for_other_settings(self):
        rig = Rig(self, ["a.jpg"])
        rig.session.set_config(str(rig.root), 5, "fit")
        rig.idle()
        self.assertEqual(rig.states()[-1], (1, "ok", "Photos", 5, "fit", False))
        self.assertEqual(len(rig.files()), 2)  # no new files, the playlist goes on

    def test_the_same_config_again_sends_nothing(self):
        rig = Rig(self, ["a.jpg"])
        events = len(rig.events)
        rig.session.set_config(str(rig.root), 30, "crop")
        rig.idle()
        self.assertEqual(len(rig.events), events)

    def test_an_invalid_interval_or_fit_in_the_config_is_ignored(self):
        rig = Rig(self, ["a.jpg"])
        rig.session.set_config(str(rig.root), 7, "stretch")
        rig.idle()
        self.assertEqual(len(rig.states()), 1)
        self.assertEqual(len([line for line in rig.logs if "ignored" in line]), 2)

    def test_a_folder_change_cuts_the_file_in_flight(self):
        gate = threading.Event()
        reached = threading.Event()
        big = b"b" * (3 * MIB)

        def hook(args):
            if args[0] == 1 and args[4] == 0 and args[1] == 1:
                reached.set()
                gate.wait(5)

        rig = Rig(self, [], start=False, image_bytes=lambda path: big)
        rig.add("a.jpg")
        rig.chunk_hook = hook
        other = rig.root.parent / "Other"
        other.mkdir()
        (other / "x.jpg").write_bytes(b"x")
        rig.session.start()
        self.assertTrue(reached.wait(5))  # inside the first chunk of the first file
        rig.session.set_config(str(other), 30, "crop")
        gate.set()
        rig.idle()
        old = [c for c in rig.chunks() if c[0] == 1]
        self.assertLess(sum(len(c[5]) for c in old), 3 * MIB)  # the old file was not finished
        self.assertEqual(rig.states()[-1][:3], (2, "ok", "Other"))
        self.assertEqual({c[0] for c in rig.chunks()[len(old):]}, {2})

    def test_failed_for_a_file_of_the_old_epoch_is_ignored(self):
        rig = Rig(self, ["a.jpg", "b.jpg"])
        rig.session.set_config(None, 30, "crop")
        rig.idle()
        rig.act(id="frame.failed", file=1)
        self.assertEqual(len(rig.files()), 2)


class StopTest(unittest.TestCase):
    def test_stop_ends_the_thread(self):
        rig = Rig(self, ["a.jpg"])
        rig.session.stop()
        self.assertFalse(rig.session._thread.is_alive())
        rig.session.stop()  # twice is fine

    def test_stop_before_start_is_fine(self):
        rig = Rig(self, ["a.jpg"], start=False)
        rig.session.stop()

    def test_a_dead_connection_ends_the_session_quietly(self):
        rig = Rig(self, ["a.jpg", "b.jpg"], start=False)
        rig.send_error = ConnectionResetError("gone")
        rig.session.start()
        wait_until(lambda: not rig.session._thread.is_alive())
        self.assertEqual(rig.logs, [])
        self.assertEqual(rig.events, [])

    def test_a_dead_connection_after_some_files_ends_the_session_quietly(self):
        rig = Rig(self, ["a.jpg", "b.jpg"])
        rig.send_error = BrokenPipeError("gone")
        rig.session.handle({"id": "frame.next"})
        wait_until(lambda: not rig.session._thread.is_alive())
        self.assertEqual(rig.logs, [])

    def test_stop_cuts_a_file_being_sent(self):
        reached = threading.Event()
        release = threading.Event()

        def hook(args):
            reached.set()
            release.wait(5)

        rig = Rig(self, [], start=False, image_bytes=lambda path: b"b" * (3 * MIB))
        rig.add("a.jpg")
        rig.chunk_hook = hook
        rig.session.start()
        self.assertTrue(reached.wait(5))
        stopper = threading.Thread(target=rig.session.stop)
        stopper.start()
        time.sleep(0.05)
        release.set()
        stopper.join(5)
        self.assertFalse(rig.session._thread.is_alive())
        self.assertLess(len(rig.chunks()), 3)

    def test_an_unexpected_error_is_logged_and_the_session_goes_on(self):
        rig = Rig(self, ["a.jpg", "b.jpg"])
        with mock.patch.object(FrameSession, "_send_ahead", side_effect=RuntimeError("bug")):
            rig.act(id="frame.next")
        self.assertIn("Frame: RuntimeError: bug", rig.logs)
        rig.act(id="frame.next")
        self.assertEqual(len(rig.files()), 3)


class ModuleTest(unittest.TestCase):
    def test_constants(self):
        self.assertEqual(session_module.AHEAD, 2)
        self.assertEqual(session_module.RESCAN_S, 10.0)
        self.assertEqual(session_module.FITS, ("crop", "fit"))


if __name__ == "__main__":
    unittest.main()
