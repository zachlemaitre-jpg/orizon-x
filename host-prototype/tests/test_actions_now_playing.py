import hashlib
import threading
import unittest

import protocol
from actions import now_playing as np_mod
from actions.base import ProviderError
from actions.now_playing import MediaInfo, NowPlayingProvider, WinRTNowPlayingApi, app_name

try:
    import winrt.windows.media.control  # noqa: F401
    import winrt.windows.storage.streams  # noqa: F401
    _HAS_WINRT_MEDIA = True
except ImportError:
    _HAS_WINRT_MEDIA = False

SPOTIFY ="SpotifyAB.SpotifyMusic_zpdnekdrzrea0!Spotify"
PNG = b"\x89PNG\r\n\x1a\n" + b"cover-1"
PNG2 = b"\x89PNG\r\n\x1a\n" + b"cover-2"


def sha1(data):
    return hashlib.sha1(data).hexdigest()


class FakeApi:
    """MediaApi stand-in: `info` is the current session (None: no session); `thumb` is what a thumbnail read gives."""

    def __init__(self, info=None, thumb=PNG):
        self.info = info
        self.thumb = thumb
        self.raises = None
        self.calls = 0
        self.reads = 0
        self.max_bytes = []

    def current(self, want_thumbnail, max_bytes):
        self.calls += 1
        self.max_bytes.append(max_bytes)
        if self.raises:
            raise self.raises
        if self.info is None:
            return None
        key = (self.info["app_id"], self.info["title"], self.info["artist"], self.info["album"])
        read = want_thumbnail(key)
        if read:
            self.reads += 1
        return MediaInfo(thumbnail=self.thumb if read else None, thumbnail_read=read, **self.info)


def track(title="UN BESO", artist="M4GN", album="UN BESO", app_id=SPOTIFY, playing=True):
    return {"app_id": app_id, "title": title, "artist": artist, "album": album, "playing": playing}


class SnapshotTest(unittest.TestCase):
    def test_no_session_is_unavailable(self):
        provider = NowPlayingProvider(api=FakeApi(None))
        self.assertEqual(provider.snapshot(), {"available": False})

    def test_without_winrt_is_unavailable(self):
        provider = NowPlayingProvider(api=None)
        self.assertEqual(provider.snapshot(), {"available": False})
        self.assertIsNone(provider.artwork_bytes("x"))

    def test_session_gives_the_full_section(self):
        provider = NowPlayingProvider(api=FakeApi(track()))
        self.assertEqual(provider.snapshot(), {
            "available": True, "app": "Spotify", "title": "UN BESO", "artist": "M4GN", "album": "UN BESO",
            "playing": True, "artwork": sha1(PNG)})

    def test_paused_is_not_playing(self):
        provider = NowPlayingProvider(api=FakeApi(track(playing=False)))
        self.assertIs(provider.snapshot()["playing"], False)

    def test_artwork_bytes_by_id(self):
        provider = NowPlayingProvider(api=FakeApi(track()))
        snap = provider.snapshot()
        self.assertEqual(provider.artwork_bytes(snap["artwork"]), PNG)
        self.assertIsNone(provider.artwork_bytes("0" * 40))
        self.assertIsNone(provider.artwork_bytes(None))

    def test_no_thumbnail_gives_null_artwork(self):
        provider = NowPlayingProvider(api=FakeApi(track(), thumb=None))
        self.assertIsNone(provider.snapshot()["artwork"])

    def test_empty_thumbnail_gives_null_artwork(self):
        provider = NowPlayingProvider(api=FakeApi(track(), thumb=b""))
        self.assertIsNone(provider.snapshot()["artwork"])

    def test_the_thumbnail_bound_leaves_room_for_the_id_in_the_frame(self):
        api = FakeApi(track())
        NowPlayingProvider(api=api).snapshot()
        self.assertEqual(api.max_bytes, [protocol.MAX_ARTWORK - 1 - 40])

    def test_oversized_thumbnail_is_dropped(self):
        big = b"\x00" * (protocol.MAX_ARTWORK - 40)  # one byte too many for a 40-char id
        provider = NowPlayingProvider(api=FakeApi(track(), thumb=big))
        snap = provider.snapshot()
        self.assertIsNone(snap["artwork"])
        self.assertIsNone(provider.artwork_bytes(sha1(big)))

    def test_largest_thumbnail_is_kept_and_encodable(self):
        big = b"\x00" * (protocol.MAX_ARTWORK - 41)
        provider = NowPlayingProvider(api=FakeApi(track(), thumb=big))
        snap = provider.snapshot()
        self.assertEqual(snap["artwork"], sha1(big))
        protocol.encode_media_artwork(snap["artwork"], provider.artwork_bytes(snap["artwork"]))

    def test_empty_title_and_artist_is_unavailable(self):
        provider = NowPlayingProvider(api=FakeApi(track(title="", artist="", album="")))
        self.assertEqual(provider.snapshot(), {"available": False})

    def test_artist_only_is_available(self):
        provider = NowPlayingProvider(api=FakeApi(track(title="", artist="Radio FIP", album="")))
        snap = provider.snapshot()
        self.assertTrue(snap["available"])
        self.assertEqual((snap["title"], snap["artist"], snap["album"]), ("", "Radio FIP", ""))

    def test_texts_are_stripped_none_safe_and_truncated(self):
        api = FakeApi(track(title="  Titre  ", artist=None, album="x" * 1000))
        snap = NowPlayingProvider(api=api).snapshot()
        self.assertEqual(snap["title"], "Titre")
        self.assertEqual(snap["artist"], "")
        self.assertEqual(snap["album"], "x" * np_mod.MAX_TEXT)

    def test_api_error_becomes_provider_error(self):
        api = FakeApi(track())
        api.raises = OSError("RPC_E_DISCONNECTED")
        with self.assertRaises(ProviderError):
            NowPlayingProvider(api=api).snapshot()

    def test_provider_error_passes_through(self):
        api = FakeApi(track())
        api.raises = ProviderError("timeout")
        with self.assertRaises(ProviderError):
            NowPlayingProvider(api=api).snapshot()

    def test_state_is_json_encodable(self):
        provider = NowPlayingProvider(api=FakeApi(track()))
        protocol.encode_actions_state({"v": 1, "now_playing": provider.snapshot()})


class ThumbnailReadsTest(unittest.TestCase):
    def test_thumbnail_read_only_on_the_first_polls_of_a_track(self):
        api = FakeApi(track())
        provider = NowPlayingProvider(api=api)
        for _ in range(10):
            provider.snapshot()
        self.assertEqual(api.calls, 10)
        self.assertEqual(api.reads, np_mod.ARTWORK_READS)

    def test_new_track_reads_again(self):
        api = FakeApi(track())
        provider = NowPlayingProvider(api=api)
        for _ in range(5):
            provider.snapshot()
        api.info = track(title="Autre")
        api.thumb = PNG2
        snap = provider.snapshot()
        self.assertEqual(api.reads, np_mod.ARTWORK_READS + 1)
        self.assertEqual(snap["artwork"], sha1(PNG2))
        self.assertEqual(provider.artwork_bytes(sha1(PNG2)), PNG2)
        self.assertIsNone(provider.artwork_bytes(sha1(PNG)))

    def test_play_pause_is_not_a_new_track(self):
        api = FakeApi(track())
        provider = NowPlayingProvider(api=api)
        for _ in range(5):
            provider.snapshot()
        api.info = track(playing=False)
        provider.snapshot()
        self.assertEqual(api.reads, np_mod.ARTWORK_READS)

    def test_each_part_of_the_key_counts(self):
        for change in ({"artist": "B"}, {"album": "C"}, {"app_id": "vlc.exe"}):
            with self.subTest(change):
                api = FakeApi(track())
                provider = NowPlayingProvider(api=api)
                for _ in range(5):
                    provider.snapshot()
                api.info = track(**change)
                provider.snapshot()
                self.assertEqual(api.reads, np_mod.ARTWORK_READS + 1)

    def test_track_change_clears_the_previous_cover_at_once(self):
        api = FakeApi(track())
        provider = NowPlayingProvider(api=api)
        provider.snapshot()
        api.info = track(title="Autre")
        api.thumb = None  # the app has not published the new cover yet
        self.assertIsNone(provider.snapshot()["artwork"])
        self.assertIsNone(provider.artwork_bytes(sha1(PNG)))

    def test_late_cover_is_picked_up_by_a_re_read(self):
        api = FakeApi(track(), thumb=None)
        provider = NowPlayingProvider(api=api)
        self.assertIsNone(provider.snapshot()["artwork"])
        api.thumb = PNG
        self.assertEqual(provider.snapshot()["artwork"], sha1(PNG))

    def test_stale_cover_replaced_by_a_re_read(self):
        api = FakeApi(track())
        provider = NowPlayingProvider(api=api)
        self.assertEqual(provider.snapshot()["artwork"], sha1(PNG))
        api.thumb = PNG2
        self.assertEqual(provider.snapshot()["artwork"], sha1(PNG2))

    def test_failed_re_read_keeps_the_cover(self):
        api = FakeApi(track())
        provider = NowPlayingProvider(api=api)
        provider.snapshot()
        api.thumb = None
        self.assertEqual(provider.snapshot()["artwork"], sha1(PNG))

    def test_cover_kept_after_the_reads(self):
        api = FakeApi(track())
        provider = NowPlayingProvider(api=api)
        snaps = [provider.snapshot() for _ in range(np_mod.ARTWORK_READS + 3)]
        self.assertEqual({s["artwork"] for s in snaps}, {sha1(PNG)})
        self.assertEqual(provider.artwork_bytes(sha1(PNG)), PNG)

    def test_session_gone_then_same_track_reads_again(self):
        api = FakeApi(track())
        provider = NowPlayingProvider(api=api)
        for _ in range(5):
            provider.snapshot()
        api.info = None
        self.assertEqual(provider.snapshot(), {"available": False})
        self.assertIsNone(provider.artwork_bytes(sha1(PNG)))
        api.info = track()
        self.assertEqual(provider.snapshot()["artwork"], sha1(PNG))
        self.assertEqual(api.reads, np_mod.ARTWORK_READS + 1)

    def test_handle_does_nothing(self):
        api = FakeApi(track())
        provider = NowPlayingProvider(api=api)
        self.assertIsNone(provider.handle({"id": "media.play_pause"}))
        self.assertEqual(api.calls, 0)


class AppNameTest(unittest.TestCase):
    def test_known_apps(self):
        cases = {
            SPOTIFY: "Spotify",
            "Spotify.exe": "Spotify",
            "Chrome": "Chrome",
            "chrome.exe": "Chrome",
            "MSEdge": "Edge",
            "msedge.exe": "Edge",
            "308046B0AF4A39CB": "Firefox",
            "E7CF176E110C211B": "Firefox",
            "firefox.exe": "Firefox",
            "Deezer.62021768415AF_q7m17pa7q8kj0!Deezer.Music": "Deezer",
            "deezer.exe": "Deezer",
            "vlc.exe": "VLC",
            "C:\\Program Files\\VideoLAN\\VLC\\vlc.exe": "VLC",
            "Microsoft.ZuneMusic_8wekyb3d8bbwe!Microsoft.ZuneMusic": "Windows Media Player",
            "Microsoft.Windows.MediaPlayer32": "Windows Media Player",
            "AppleInc.AppleMusicWin_nzyj5cx40ttqa!App": "Apple Music",
            "AppleInc.iTunes_nzyj5cx40ttqa!iTunes": "iTunes",
            "Brave": "Brave",
            "opera.exe": "Opera",
            "TIDAL.exe": "TIDAL",
            "foobar2000.exe": "foobar2000",
            "Microsoft.ZuneVideo_8wekyb3d8bbwe!Microsoft.ZuneVideo": "Movies & TV",
        }
        for aumid, name in cases.items():
            with self.subTest(aumid):
                self.assertEqual(app_name(aumid), name)

    def test_unknown_exe_gives_its_stem(self):
        self.assertEqual(app_name("MusicBee.exe"), "MusicBee")
        self.assertEqual(app_name("D:\\Apps\\Strawberry\\strawberry.EXE"), "strawberry")
        self.assertEqual(app_name("C:/apps/foo/Bar.exe"), "Bar")

    def test_unknown_package_gives_the_app_part(self):
        self.assertEqual(app_name("Contoso.SuperPlayer_abc123!App"), "SuperPlayer")

    def test_plain_unknown_id_is_kept(self):
        self.assertEqual(app_name("SomePlayer"), "SomePlayer")

    def test_empty(self):
        self.assertEqual(app_name(""), "")
        self.assertEqual(app_name(None), "")


# --- the WinRT layer, over fake pywinrt objects ---

class FakeOp:
    def __init__(self, result=None, status=1, error=None):
        self.result, self.status, self.error = result, status, error
        self.waits = []
        self.cancelled = False

    def wait(self, timeout):
        self.waits.append(timeout)
        return self.status

    def cancel(self):
        self.cancelled = True

    def get_results(self):
        if self.error:
            raise self.error
        return self.result


class FakeStream:
    def __init__(self, data, content_type="image/png"):
        self.data = data
        self.size = len(data)
        self.content_type = content_type
        self.closed = False

    def get_input_stream_at(self, position):
        assert position == 0
        return self

    def close(self):
        self.closed = True


class FakeReader:
    instances = []

    def __init__(self, stream):
        self.stream = stream
        self.loads = []
        self.closed = False
        self.load_status = 1
        FakeReader.instances.append(self)

    def load_async(self, count):
        self.loads.append(count)
        return FakeOp(min(count, len(self.stream.data)), status=self.load_status)

    def read_bytes(self, buf):
        buf[:] = self.stream.data[:len(buf)]

    def close(self):
        self.closed = True


class FakeThumbRef:
    def __init__(self, stream):
        self.stream = stream
        self.opens = 0

    def open_read_async(self):
        self.opens += 1
        return FakeOp(self.stream)


class FakeProps:
    def __init__(self, title="T", artist="A", album_title="L", thumbnail=None):
        self.title, self.artist, self.album_title, self.thumbnail = title, artist, album_title, thumbnail


class FakePlayback:
    def __init__(self, status):
        self.playback_status = status


class FakeSession:
    def __init__(self, aumid=SPOTIFY, props=None, status=4):
        self.source_app_user_model_id = aumid
        self.props = props or FakeProps()
        self.status = status

    def try_get_media_properties_async(self):
        return FakeOp(self.props)

    def get_playback_info(self):
        return FakePlayback(self.status)


class FakeManager:
    def __init__(self, session):
        self.session = session

    def get_current_session(self):
        return self.session


class FakeManagerClass:
    def __init__(self, session):
        self.manager = FakeManager(session)
        self.requests = 0

    def request_async(self):
        self.requests += 1
        return FakeOp(self.manager)


class FakeWorker:
    def __init__(self):
        self.timeouts = []
        self.threads = []

    def run(self, fn, timeout_s):
        self.timeouts.append(timeout_s)
        self.threads.append(threading.get_ident())
        return fn()


class WinRTApiTest(unittest.TestCase):
    def setUp(self):
        FakeReader.instances = []

    def api(self, session):
        self.manager_cls = FakeManagerClass(session)
        self.worker = FakeWorker()
        return WinRTNowPlayingApi(worker=self.worker, manager_cls=self.manager_cls, data_reader=FakeReader)

    def test_no_session(self):
        self.assertIsNone(self.api(None).current(lambda key: True, 1000))

    def test_reads_properties_status_and_thumbnail(self):
        stream = FakeStream(PNG)
        session = FakeSession(props=FakeProps("T", "A", "L", FakeThumbRef(stream)), status=4)
        info = self.api(session).current(lambda key: True, 1000)
        self.assertEqual(info, MediaInfo(app_id=SPOTIFY, title="T", artist="A", album="L", playing=True,
                                         thumbnail=PNG, thumbnail_read=True))
        reader = FakeReader.instances[0]
        self.assertEqual(reader.loads, [len(PNG)])
        self.assertTrue(reader.closed and stream.closed)
        self.assertEqual(len(self.worker.timeouts), 1)  # one worker call per poll

    def test_paused_and_other_statuses_are_not_playing(self):
        for status in (0, 1, 2, 3, 5):
            with self.subTest(status):
                info = self.api(FakeSession(status=status)).current(lambda key: False, 1000)
                self.assertIs(info.playing, False)

    def test_want_thumbnail_gets_the_track_key_and_false_skips_the_read(self):
        ref = FakeThumbRef(FakeStream(PNG))
        session = FakeSession(props=FakeProps("T", "A", "L", ref))
        keys = []
        info = self.api(session).current(lambda key: keys.append(key) or False, 1000)
        self.assertEqual(keys, [(SPOTIFY, "T", "A", "L")])
        self.assertEqual(ref.opens, 0)
        self.assertIsNone(info.thumbnail)
        self.assertIs(info.thumbnail_read, False)

    def test_no_thumbnail_reference(self):
        info = self.api(FakeSession(props=FakeProps(thumbnail=None))).current(lambda key: True, 1000)
        self.assertIsNone(info.thumbnail)
        self.assertIs(info.thumbnail_read, True)

    def test_oversized_stream_is_not_read(self):
        stream = FakeStream(b"\x00" * 2000)
        session = FakeSession(props=FakeProps(thumbnail=FakeThumbRef(stream)))
        info = self.api(session).current(lambda key: True, 1000)
        self.assertIsNone(info.thumbnail)
        self.assertIs(info.thumbnail_read, True)
        self.assertEqual(FakeReader.instances, [])
        self.assertTrue(stream.closed)

    def test_empty_stream(self):
        session = FakeSession(props=FakeProps(thumbnail=FakeThumbRef(FakeStream(b""))))
        info = self.api(session).current(lambda key: True, 1000)
        self.assertIsNone(info.thumbnail)

    def test_thumbnail_failure_keeps_the_text(self):
        class BrokenRef:
            def open_read_async(self):
                return FakeOp(error=OSError("E_FAIL"))
        session = FakeSession(props=FakeProps("T", "A", "L", BrokenRef()))
        info = self.api(session).current(lambda key: True, 1000)
        self.assertEqual((info.title, info.thumbnail, info.thumbnail_read), ("T", None, True))

    def test_thumbnail_load_timeout_keeps_the_text(self):
        class SlowReader(FakeReader):
            def __init__(self, stream):
                super().__init__(stream)
                self.load_status = 0  # still running at the deadline
        stream = FakeStream(PNG)
        session = FakeSession(props=FakeProps("T", "A", "L", FakeThumbRef(stream)))
        api = WinRTNowPlayingApi(worker=FakeWorker(), manager_cls=FakeManagerClass(session), data_reader=SlowReader)
        info = api.current(lambda key: True, 1000)
        self.assertEqual((info.title, info.thumbnail), ("T", None))
        self.assertTrue(stream.closed)

    def test_waits_are_bounded(self):
        stream = FakeStream(PNG)
        session = FakeSession(props=FakeProps(thumbnail=FakeThumbRef(stream)))
        api = self.api(session)
        api.current(lambda key: True, 1000)
        self.assertEqual(self.worker.timeouts, [np_mod.CALL_TIMEOUT_S])
        self.assertGreaterEqual(np_mod.CALL_TIMEOUT_S, np_mod.OP_TIMEOUT_S * 4)

    def test_properties_error_raises(self):
        class BadSession(FakeSession):
            def try_get_media_properties_async(self):
                return FakeOp(error=OSError("RPC"))
        with self.assertRaises(OSError):
            self.api(BadSession()).current(lambda key: True, 1000)

    def test_none_texts_become_empty(self):
        info = self.api(FakeSession(props=FakeProps(None, None, None))).current(lambda key: False, 1000)
        self.assertEqual((info.title, info.artist, info.album), ("", "", ""))

    @unittest.skipUnless(_HAS_WINRT_MEDIA, "winrt-Windows.Media.Control not installed")
    def test_constructor_imports_the_real_classes_without_calling_winrt(self):
        worker = FakeWorker()
        WinRTNowPlayingApi(worker=worker)
        self.assertEqual(worker.timeouts, [])

    def test_constructor_without_winrt_raises_import_error(self):
        import builtins
        real_import = builtins.__import__

        def fake_import(name, *args, **kwargs):
            if name.startswith("winrt"):
                raise ImportError("no winrt")
            return real_import(name, *args, **kwargs)
        builtins.__import__ = fake_import
        try:
            with self.assertRaises(ImportError):
                WinRTNowPlayingApi(worker=FakeWorker())
            self.assertIsNone(np_mod._default_api())
            self.assertEqual(NowPlayingProvider().snapshot(), {"available": False})
        finally:
            builtins.__import__ = real_import


if __name__ == "__main__":
    unittest.main()
