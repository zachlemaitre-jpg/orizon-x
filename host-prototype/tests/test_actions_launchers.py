import json
import os
import sys
import unittest
from unittest import mock

from actions import launchers
from actions.launchers import LaunchersProvider

LOCAL = r"C:\Users\me\AppData\Local"
ROAMING = r"C:\Users\me\AppData\Roaming"
UPDATER = os.path.join(LOCAL, "Discord", "Update.exe")
SPOTIFY = os.path.join(ROAMING, "Spotify", "Spotify.exe")
DOWNLOADS = r"C:\Users\me\Downloads"


class FakeFs:
    def __init__(self, files=(), dirs=()):
        self.files = set(files)
        self.dirs = set(dirs)

    def isfile(self, path):
        return path in self.files

    def isdir(self, path):
        return path in self.dirs

    def listdir(self, path):
        prefix = path.rstrip("\\") + "\\"
        names = {p[len(prefix):].split("\\")[0] for p in self.files | self.dirs if p.startswith(prefix)}
        return sorted(names)


class FakeLauncher:
    def __init__(self):
        self.started = []
        self.spawned = []
        self.error = None

    def startfile(self, target):
        if self.error:
            raise self.error
        self.started.append(target)

    def popen(self, args):
        if self.error:
            raise self.error
        self.spawned.append(args)


class FakeIcons:
    def __init__(self):
        self.calls = []
        self.images = {}

    def icon_id(self, app, profile, url):
        self.calls.append((app.path, profile.id, url))
        return "id-" + os.path.basename(os.path.dirname(app.path)) + "-" + os.path.basename(app.path)

    def artwork_bytes(self, icon_id):
        return self.images.get(icon_id)


class Clock:
    def __init__(self):
        self.t = 100.0

    def __call__(self):
        return self.t


def make(files=(), dirs=(), protocols=(), downloads=DOWNLOADS):
    fs = FakeFs(files, dirs | {downloads} if isinstance(dirs, set) else set(dirs) | {downloads})
    launcher, icons, clock, logs = FakeLauncher(), FakeIcons(), Clock(), []
    provider = LaunchersProvider(env={"LOCALAPPDATA": LOCAL, "APPDATA": ROAMING}, fs=fs,
                                 registry=lambda name: name in protocols, launcher=launcher, icons=icons,
                                 downloads=lambda: downloads, clock=clock, log=logs.append)
    return provider, fs, launcher, icons, clock, logs


def open_(provider, target):
    return provider.handle({"id": "launch.open", "target": target})


class SnapshotTest(unittest.TestCase):
    def test_settings_and_downloads_are_always_there(self):
        p, *_ = make()
        snap = p.snapshot()
        self.assertEqual(snap, {"settings": True, "discord": False, "spotify": False, "downloads": True,
                                "icons": {"discord": None, "spotify": None}})
        json.dumps(snap)

    def test_discord_and_spotify_when_installed(self):
        p, *_ = make(files={UPDATER, SPOTIFY})
        snap = p.snapshot()
        self.assertTrue(snap["discord"] and snap["spotify"])

    def test_the_protocols_count_when_there_is_no_exe(self):
        p, *_ = make(protocols={"discord", "spotify"})
        snap = p.snapshot()
        self.assertTrue(snap["discord"] and snap["spotify"])
        self.assertEqual(snap["icons"], {"discord": None, "spotify": None})  # no exe to take an icon from

    def test_only_the_registered_protocol_counts(self):
        p, *_ = make(protocols={"spotify"})
        snap = p.snapshot()
        self.assertEqual((snap["discord"], snap["spotify"]), (False, True))

    def test_detection_is_cached_for_sixty_seconds(self):
        p, fs, _, _, clock, _ = make(files={UPDATER})
        self.assertTrue(p.snapshot()["discord"])
        fs.files.clear()
        clock.t += 59
        self.assertTrue(p.snapshot()["discord"])
        clock.t += 2
        self.assertFalse(p.snapshot()["discord"])
        fs.files.add(SPOTIFY)
        self.assertFalse(p.snapshot()["spotify"])  # cached again
        clock.t += 61
        self.assertTrue(p.snapshot()["spotify"])

    def test_icons_come_from_the_real_exe_of_each_app(self):
        newest = os.path.join(LOCAL, "Discord", "app-1.0.10", "Discord.exe")
        older = os.path.join(LOCAL, "Discord", "app-1.0.9", "Discord.exe")
        p, _, _, icons, _, _ = make(files={UPDATER, newest, older, SPOTIFY})
        snap = p.snapshot()
        self.assertIn((newest, "generic", None), icons.calls)   # 1.0.10 is newer than 1.0.9
        self.assertIn((SPOTIFY, "generic", None), icons.calls)
        self.assertEqual(snap["icons"]["discord"], "id-app-1.0.10-Discord.exe")
        self.assertEqual(snap["icons"]["spotify"], "id-Spotify-Spotify.exe")

    def test_without_a_versioned_exe_the_updater_gives_the_icon(self):
        p, _, _, icons, _, _ = make(files={UPDATER})
        p.snapshot()
        self.assertEqual(icons.calls[0][0], UPDATER)

    def test_a_failing_icon_provider_does_not_break_the_section(self):
        p, _, _, icons, _, logs = make(files={SPOTIFY})
        icons.icon_id = lambda *a: (_ for _ in ()).throw(OSError("Qt"))
        self.assertEqual(p.snapshot()["icons"]["spotify"], None)
        self.assertTrue(logs)

    def test_artwork_bytes_goes_to_the_icon_provider(self):
        p, _, _, icons, _, _ = make()
        icons.images["abc"] = b"PNG"
        self.assertEqual(p.artwork_bytes("abc"), b"PNG")
        self.assertIsNone(p.artwork_bytes("nope"))
        self.assertIsNone(p.artwork_bytes(None))


class LaunchTest(unittest.TestCase):
    def test_settings(self):
        p, _, launcher, *_ = make()
        self.assertIsNone(open_(p, "settings"))
        self.assertEqual(launcher.started, ["ms-settings:"])
        self.assertEqual(launcher.spawned, [])

    def test_discord_through_its_updater(self):
        p, _, launcher, *_ = make(files={UPDATER})
        self.assertIsNone(open_(p, "discord"))
        self.assertEqual(launcher.spawned, [[UPDATER, "--processStart", "Discord.exe"]])
        self.assertEqual(launcher.started, [])

    def test_discord_through_its_protocol(self):
        p, _, launcher, *_ = make(protocols={"discord"})
        self.assertIsNone(open_(p, "discord"))
        self.assertEqual(launcher.started, ["discord://"])

    def test_spotify_exe_then_store_protocol(self):
        p, _, launcher, *_ = make(files={SPOTIFY})
        self.assertIsNone(open_(p, "spotify"))
        self.assertEqual(launcher.spawned, [[SPOTIFY]])
        p, _, launcher, *_ = make(protocols={"spotify"})
        self.assertIsNone(open_(p, "spotify"))
        self.assertEqual(launcher.started, ["spotify:"])

    def test_downloads_opens_the_known_folder_in_explorer(self):
        p, _, launcher, *_ = make()
        self.assertIsNone(open_(p, "downloads"))
        self.assertEqual(launcher.spawned, [["explorer.exe", DOWNLOADS]])

    def test_a_missing_downloads_folder_is_app_not_found(self):
        p, _, launcher, *_ = make(downloads=None)
        self.assertEqual(open_(p, "downloads"), "app_not_found")
        p, fs, launcher, *_ = make()
        fs.dirs.discard(DOWNLOADS)
        self.assertEqual(open_(p, "downloads"), "app_not_found")
        self.assertEqual(launcher.spawned, [])

    def test_an_app_that_is_not_installed_is_app_not_found_and_nothing_runs(self):
        p, _, launcher, _, _, logs = make()
        self.assertEqual(open_(p, "discord"), "app_not_found")
        self.assertEqual(open_(p, "spotify"), "app_not_found")
        self.assertEqual((launcher.started, launcher.spawned), ([], []))
        self.assertTrue(logs)

    def test_a_tap_looks_again_even_within_the_cache_delay(self):
        p, fs, launcher, *_ = make()
        self.assertFalse(p.snapshot()["discord"])
        fs.files.add(UPDATER)  # installed a moment ago
        self.assertIsNone(open_(p, "discord"))
        self.assertEqual(len(launcher.spawned), 1)

    def test_a_launch_that_fails_is_app_not_found(self):
        p, _, launcher, _, _, logs = make(files={UPDATER, SPOTIFY})
        launcher.error = OSError("cannot start")
        for target in ("settings", "discord", "spotify", "downloads"):
            self.assertEqual(open_(p, target), "app_not_found", target)
        self.assertTrue(logs)

    def test_only_the_closed_list_is_accepted(self):
        p, _, launcher, _, _, logs = make(files={UPDATER, SPOTIFY})
        bad = ["cmd", "powershell", "Settings", "SETTINGS", " settings", "settings ", "../x", "C:\\Windows\\notepad.exe",
               "ms-settings:network", "http://evil", "", None, 5, ["discord"], {"a": 1}, True]
        for target in bad:
            logs.clear()
            self.assertIsNone(open_(p, target), repr(target))
            self.assertEqual(len(logs), 1, repr(target))
        self.assertEqual((launcher.started, launcher.spawned), ([], []))
        self.assertIsNone(p.handle({"id": "launch.open"}))
        self.assertIsNone(p.handle({"id": "launch.other", "target": "settings"}))
        self.assertEqual((launcher.started, launcher.spawned), ([], []))

    def test_the_real_launcher_never_opens_a_console_window_or_a_shell(self):
        with mock.patch.object(launchers.subprocess, "Popen") as popen:
            launchers.RealLauncher().popen(["x.exe", "--a"])
        args, kwargs = popen.call_args
        self.assertEqual(args[0], ["x.exe", "--a"])
        self.assertEqual(kwargs["creationflags"] & launchers.CREATE_NO_WINDOW, launchers.CREATE_NO_WINDOW)
        self.assertEqual(launchers.CREATE_NO_WINDOW, 0x08000000)
        self.assertFalse(kwargs["shell"])

    def test_the_real_startfile_uses_the_os(self):
        with mock.patch.object(launchers.os, "startfile", create=True) as startfile:
            launchers.RealLauncher().startfile("ms-settings:")
        startfile.assert_called_once_with("ms-settings:")


@unittest.skipUnless(sys.platform == "win32", "Win32 only")
class RealReadOnlyTest(unittest.TestCase):
    def test_the_downloads_known_folder_resolves(self):
        folder = launchers.downloads_folder()  # SHGetKnownFolderPath: read-only
        self.assertIsNotNone(folder)
        self.assertTrue(os.path.isabs(folder))

    def test_protocol_lookup_is_read_only_and_boolean(self):
        self.assertIsInstance(launchers.protocol_registered("ms-settings"), bool)
        self.assertFalse(launchers.protocol_registered("orizonx-no-such-protocol-xyz"))

    def test_the_default_provider_builds_and_reads_without_launching(self):
        p = LaunchersProvider(icons=FakeIcons())
        snap = p.snapshot()
        self.assertTrue(snap["settings"] and snap["downloads"])
        self.assertIsInstance(snap["discord"], bool)


if __name__ == "__main__":
    unittest.main()
