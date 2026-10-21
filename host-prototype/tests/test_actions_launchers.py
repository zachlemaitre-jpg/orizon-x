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
STORE_ROOT = r"C:\Program Files\WindowsApps\SpotifyAB.SpotifyMusic_1.305.3058.0_x64__zpdnekdrzrea0"
STORE_EXE = os.path.join(STORE_ROOT, "Spotify.exe")


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


class FakeWindows:
    """Fake window functions: nothing real is ever read or minimized."""

    def __init__(self, front=0, classes=None, exes=None, children=None, folders=None):
        self.front = front
        self.classes = classes or {}      # hwnd -> window class
        self.exes = exes or {}            # hwnd -> full path of its process exe
        self.children = children or {}    # hwnd -> exe base names of its child windows
        self.folders = folders or {}      # hwnd -> Explorer folder
        self.minimized = []
        self.error = None

    def _check(self):
        if self.error:
            raise self.error

    def foreground_window(self):
        self._check()
        return self.front

    def window_class(self, hwnd):
        return self.classes.get(hwnd, "")

    def window_pid(self, hwnd):
        return hwnd  # the pid is the hwnd, process_exe maps it back

    def process_exe(self, pid):
        return self.exes.get(pid)

    def child_exes(self, hwnd):
        return list(self.children.get(hwnd, []))

    def explorer_folder(self, hwnd):
        self._check()
        return self.folders.get(hwnd)

    def minimize(self, hwnd):
        self.minimized.append(hwnd)


class FakeFront:
    """Fake Explorer window layer: no key is pressed and no window is touched."""

    def __init__(self, appears_after=0, hwnd=42, foreground=0, calls=None):
        self.appears_after, self.hwnd, self.fg = appears_after, hwnd, foreground
        self.calls = calls if calls is not None else []
        self.finds = []
        self.raised = []

    def prepare(self):
        self.calls.append("prepare")

    def find(self, path):
        self.finds.append(path)
        return self.hwnd if len(self.finds) > self.appears_after else 0

    def foreground(self):
        return self.fg

    def raise_(self, hwnd):
        self.raised.append(hwnd)
        return True


class Clock:
    def __init__(self):
        self.t = 100.0

    def __call__(self):
        return self.t


def make(files=(), dirs=(), protocols=(), downloads=DOWNLOADS, packages=(), windows=None, front=None):
    fs = FakeFs(files, dirs | {downloads} if isinstance(dirs, set) else set(dirs) | {downloads})
    launcher, icons, clock, logs = FakeLauncher(), FakeIcons(), Clock(), []
    provider = LaunchersProvider(env={"LOCALAPPDATA": LOCAL, "APPDATA": ROAMING}, fs=fs,
                                 registry=lambda name: name in protocols, launcher=launcher, icons=icons,
                                 downloads=lambda: downloads, clock=clock, log=logs.append,
                                 packages=lambda prefix: [r for r in packages if prefix == "SpotifyAB.SpotifyMusic_"],
                                 windows=windows if windows is not None else FakeWindows(),
                                 front=front if front is not None else FakeFront(), sleep=lambda _s: None)
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


class StoreSpotifyTest(unittest.TestCase):
    def test_the_store_package_exe_gives_the_icon_and_the_launch_stays_the_protocol(self):
        p, _, launcher, icons, _, _ = make(files={STORE_EXE}, protocols={"spotify"}, packages=[STORE_ROOT])
        snap = p.snapshot()
        self.assertTrue(snap["spotify"])
        self.assertEqual(snap["icons"]["spotify"], "id-" + os.path.basename(STORE_ROOT) + "-Spotify.exe")
        self.assertEqual(icons.calls, [(STORE_EXE, "generic", None)])
        self.assertIsNone(open_(p, "spotify"))
        self.assertEqual((launcher.started, launcher.spawned), (["spotify:"], []))

    def test_the_classic_exe_wins_over_the_store_package(self):
        p, _, launcher, icons, _, _ = make(files={SPOTIFY, STORE_EXE}, packages=[STORE_ROOT])
        p.snapshot()
        self.assertEqual(icons.calls, [(SPOTIFY, "generic", None)])
        open_(p, "spotify")
        self.assertEqual(launcher.spawned, [[SPOTIFY]])

    def test_a_package_without_a_readable_exe_leaves_the_icon_empty(self):
        p, *_ = make(protocols={"spotify"}, packages=[STORE_ROOT])
        self.assertEqual(p.snapshot()["icons"]["spotify"], None)

    def test_the_first_package_with_an_exe_is_used(self):
        newer = STORE_ROOT.replace("1.305", "1.400")
        p, _, _, icons, _, _ = make(files={STORE_EXE}, packages=[newer, STORE_ROOT])
        self.assertTrue(p.snapshot()["spotify"])
        self.assertEqual(icons.calls[0][0], STORE_EXE)

    def test_a_store_package_alone_counts_as_installed(self):
        p, _, launcher, *_ = make(files={STORE_EXE}, packages=[STORE_ROOT])
        self.assertTrue(p.snapshot()["spotify"])
        self.assertIsNone(open_(p, "spotify"))
        self.assertEqual(launcher.started, ["spotify:"])

    def test_a_failing_registry_lookup_does_not_break_the_snapshot(self):
        p, _, _, _, _, logs = make(protocols={"spotify"})
        p._packages = lambda prefix: (_ for _ in ()).throw(OSError("registry"))
        self.assertEqual(p.snapshot()["icons"]["spotify"], None)
        self.assertTrue(p.snapshot()["spotify"])
        self.assertTrue(logs)

    def test_the_lookup_only_asks_for_spotify_packages(self):
        asked = []
        p, *_ = make()
        p._packages = lambda prefix: asked.append(prefix) or []
        p.snapshot()
        self.assertEqual(asked, ["SpotifyAB.SpotifyMusic_"])


class MinimizeTest(unittest.TestCase):
    """Open, then minimize (spec 4.4): the tap minimizes the window that is in front, else it launches."""

    def check(self, target, windows, minimized=True):
        p, _, launcher, *_ = make(files={UPDATER, SPOTIFY}, windows=windows)
        self.assertIsNone(open_(p, target))
        if minimized:
            self.assertEqual(windows.minimized, [windows.front])
            self.assertEqual((launcher.started, launcher.spawned), ([], []))
        else:
            self.assertEqual(windows.minimized, [])
            self.assertTrue(launcher.started or launcher.spawned)

    def test_discord_in_front_is_minimized(self):
        self.check("discord", FakeWindows(7, exes={7: LOCAL + r"\Discord\app-1\Discord.exe"}))

    def test_discord_not_in_front_is_launched(self):
        self.check("discord", FakeWindows(7, exes={7: r"C:\Windows\notepad.exe"}), minimized=False)

    def test_spotify_in_front_is_minimized_and_the_process_name_is_case_insensitive(self):
        self.check("spotify", FakeWindows(8, exes={8: r"C:\Program Files\WindowsApps\x\SPOTIFY.EXE"}))

    def test_spotify_does_not_match_discord_in_front(self):
        self.check("spotify", FakeWindows(7, exes={7: LOCAL + r"\Discord\Discord.exe"}), minimized=False)
        self.check("discord", FakeWindows(8, exes={8: ROAMING + r"\Spotify\Spotify.exe"}), minimized=False)

    def test_settings_by_its_own_process(self):
        self.check("settings", FakeWindows(9, exes={9: r"C:\Windows\ImmersiveControlPanel\SystemSettings.exe"}))

    def test_settings_by_an_application_frame_with_a_settings_child(self):
        host = r"C:\Windows\System32\ApplicationFrameHost.exe"
        self.check("settings", FakeWindows(9, classes={9: "ApplicationFrameWindow"}, exes={9: host},
                                           children={9: ["applicationframehost.exe", "systemsettings.exe"]}))

    def test_another_application_frame_is_not_settings(self):
        host = r"C:\Windows\System32\ApplicationFrameHost.exe"
        self.check("settings", FakeWindows(9, classes={9: "ApplicationFrameWindow"}, exes={9: host},
                                           children={9: ["calculatorapp.exe"]}), minimized=False)

    def test_a_settings_child_in_a_plain_window_does_not_count(self):
        self.check("settings", FakeWindows(9, classes={9: "Notepad"}, exes={9: r"C:\x\a.exe"},
                                           children={9: ["systemsettings.exe"]}), minimized=False)

    def test_downloads_explorer_window_on_the_downloads_folder(self):
        self.check("downloads", FakeWindows(5, classes={5: "CabinetWClass"}, exes={5: r"C:\Windows\explorer.exe"},
                                            folders={5: DOWNLOADS}))

    def test_downloads_compares_paths_case_insensitively_and_normalised(self):
        self.check("downloads", FakeWindows(5, classes={5: "CabinetWClass"}, folders={5: "c:/users/ME/downloads\\"}))

    def test_another_explorer_folder_is_not_downloads(self):
        self.check("downloads", FakeWindows(5, classes={5: "CabinetWClass"}, folders={5: r"C:\Users\me\Documents"}),
                   minimized=False)

    def test_an_explorer_folder_that_cannot_be_read_is_not_downloads(self):
        self.check("downloads", FakeWindows(5, classes={5: "CabinetWClass"}, folders={}), minimized=False)

    def test_a_non_explorer_window_on_downloads_is_not_downloads(self):
        self.check("downloads", FakeWindows(5, classes={5: "Notepad"}, folders={5: DOWNLOADS}), minimized=False)

    def test_no_foreground_window_launches(self):
        self.check("discord", FakeWindows(0), minimized=False)

    def test_a_failing_detection_falls_back_to_launching(self):
        windows = FakeWindows(7, exes={7: LOCAL + r"\Discord\Discord.exe"})
        windows.error = OSError("denied")
        p, _, launcher, _, _, logs = make(files={UPDATER}, windows=windows)
        self.assertIsNone(open_(p, "discord"))
        self.assertEqual(launcher.spawned, [[UPDATER, "--processStart", "Discord.exe"]])
        self.assertEqual(windows.minimized, [])
        self.assertTrue(logs)

    def test_a_failing_explorer_lookup_falls_back_to_launching(self):
        windows = FakeWindows(5, classes={5: "CabinetWClass"}, folders={5: DOWNLOADS})
        windows.error = RuntimeError("COM")
        p, _, launcher, *_ = make(windows=windows)
        self.assertIsNone(open_(p, "downloads"))
        self.assertEqual(launcher.spawned, [["explorer.exe", DOWNLOADS]])

    def test_a_front_window_is_minimized_even_when_the_app_is_not_detected(self):
        windows = FakeWindows(7, exes={7: LOCAL + r"\Discord\Discord.exe"})
        p, *_ = make(windows=windows)  # nothing installed according to the file system
        self.assertIsNone(open_(p, "discord"))
        self.assertEqual(windows.minimized, [7])

    def test_the_closed_list_still_refuses_unknown_targets_before_any_window_call(self):
        windows = FakeWindows(7, exes={7: LOCAL + r"\Discord\Discord.exe"})
        p, *_ = make(windows=windows)
        self.assertIsNone(open_(p, "cmd"))
        self.assertEqual(windows.minimized, [])

    def test_the_real_minimize_asks_for_sw_minimize(self):
        self.assertEqual(launchers.SW_MINIMIZE, 6)
        real = launchers.RealWindows.__new__(launchers.RealWindows)
        real._show = mock.Mock()
        real.minimize(1234)
        real._show.assert_called_once_with(1234, 6)


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

    def test_downloads_prepares_then_opens_then_raises_the_window(self):
        front = FakeFront(appears_after=2)
        order = []
        front.calls = order
        p, _, launcher, *_ = make(front=front)
        launcher.popen = lambda args: order.append("open")
        self.assertIsNone(open_(p, "downloads"))
        self.assertEqual(order, ["prepare", "open"])
        self.assertEqual(front.finds, [DOWNLOADS] * 3)
        self.assertEqual(front.raised, [42])

    def test_downloads_window_never_found_is_still_a_success(self):
        front = FakeFront(appears_after=10 ** 6)
        p, _, launcher, _, _, logs = make(front=front)
        self.assertIsNone(open_(p, "downloads"))
        self.assertEqual(launcher.spawned, [["explorer.exe", DOWNLOADS]])
        self.assertEqual(front.raised, [])
        self.assertTrue(any("folder front" in line for line in logs))

    def test_other_targets_do_not_touch_the_front(self):
        front = FakeFront()
        p, _, launcher, *_ = make(files={UPDATER}, front=front)
        open_(p, "settings")
        open_(p, "discord")
        self.assertEqual(front.calls, [])
        self.assertEqual(front.finds, [])

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

    def test_store_package_lookup_is_read_only(self):
        roots = launchers.store_package_roots("SpotifyAB.SpotifyMusic_")
        self.assertIsInstance(roots, list)
        self.assertEqual(launchers.store_package_roots("orizonx-no-such-package-xyz_"), [])

    def test_the_real_window_layer_builds_and_reads_only(self):
        windows = launchers.RealWindows()  # never minimize here: only the read-only calls
        self.assertIsInstance(windows.foreground_window(), int)
        self.assertIsInstance(windows.window_class(0), str)
        self.assertIsInstance(windows.child_exes(0), list)

    def test_the_default_provider_builds_and_reads_without_launching(self):
        p = LaunchersProvider(icons=FakeIcons())
        snap = p.snapshot()
        self.assertTrue(snap["settings"] and snap["downloads"])
        self.assertIsInstance(snap["discord"], bool)


if __name__ == "__main__":
    unittest.main()
