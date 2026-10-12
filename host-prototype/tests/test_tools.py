import os
import subprocess
import tempfile
import unittest
from pathlib import Path

import tools
from messages import msg

EXE = ".exe" if os.name == "nt" else ""


def touch(directory: Path, name: str) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{name}{EXE}"
    path.write_bytes(b"")
    return path


class FindToolTest(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        self.bundled = self.root / "tools"
        self.sdk = self.root / "sdk"
        self.on_path = self.root / "path"

    def find(self, name, path_hit=True):
        def which(tool):
            candidate = self.on_path / f"{tool}{EXE}"
            return str(candidate) if path_hit and candidate.exists() else None
        return tools.find_tool(name, bundled_dir=self.bundled, sdk_dir=self.sdk, which=which)

    def test_ffmpeg_prefers_bundled_copy(self):
        bundled = touch(self.bundled, "ffmpeg")
        touch(self.on_path, "ffmpeg")
        self.assertEqual(self.find("ffmpeg"), str(bundled))

    def test_ffmpeg_falls_back_to_path(self):
        on_path = touch(self.on_path, "ffmpeg")
        self.assertEqual(self.find("ffmpeg"), str(on_path))

    def test_adb_prefers_path_then_sdk_then_bundled(self):
        bundled = touch(self.bundled, "adb")
        self.assertEqual(self.find("adb"), str(bundled))
        sdk = touch(self.sdk, "adb")
        self.assertEqual(self.find("adb"), str(sdk))
        on_path = touch(self.on_path, "adb")
        self.assertEqual(self.find("adb"), str(on_path))

    def test_missing_tool_raises_readable_error(self):
        with self.assertRaises(tools.ToolMissing) as raised:
            self.find("ffmpeg")
        self.assertEqual(raised.exception.msg, msg("tools.ffmpeg_missing"))
        self.assertIn("ffmpeg introuvable", raised.exception.msg.text("fr"))
        self.assertIn("ffmpeg not found", str(raised.exception))
        with self.assertRaises(tools.ToolMissing) as raised:
            self.find("adb")
        self.assertEqual(raised.exception.msg, msg("tools.adb_missing"))
        self.assertIn("adb introuvable", raised.exception.msg.text("fr"))
        self.assertIn("adb not found", str(raised.exception))

    def test_unknown_tool_is_a_programming_error(self):
        with self.assertRaises(ValueError):
            self.find("ffprobe")


class NoWindowTest(unittest.TestCase):
    def test_flag_matches_platform(self):
        expected = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
        self.assertEqual(tools.NO_WINDOW, expected)


class ToolCwdTest(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp()).resolve()
        self.app = self.root / "app"
        (self.app / "tools").mkdir(parents=True)
        self.sdk = self.root / "sdk"
        self.sdk.mkdir()

    def cwd(self, exe):
        return tools.tool_cwd(str(exe), app_folder=self.app)

    def test_external_tool_runs_in_its_own_folder(self):
        self.assertEqual(self.cwd(self.sdk / "adb.exe"), str(self.sdk))

    def test_bare_name_runs_in_the_temp_folder(self):
        self.assertEqual(tools.tool_cwd("adb"), tempfile.gettempdir())
        self.assertEqual(tools.tool_cwd("ffmpeg.exe"), tempfile.gettempdir())

    def test_tool_in_the_app_folder_or_below_runs_in_the_temp_folder(self):
        self.assertEqual(self.cwd(self.app / "tools" / "adb.exe"), tempfile.gettempdir())
        self.assertEqual(self.cwd(self.app / "adb.exe"), tempfile.gettempdir())

    def test_missing_folder_runs_in_the_temp_folder(self):
        self.assertEqual(self.cwd(self.root / "gone" / "adb.exe"), tempfile.gettempdir())

    def test_default_app_folder_is_the_real_one(self):
        inside = tools.app_dir() / "tools" / "adb.exe"
        self.assertEqual(tools.tool_cwd(str(inside)), tempfile.gettempdir())
        self.assertNotEqual(Path(tools.tool_cwd(str(tools.app_dir() / "x.exe"))).resolve(), tools.app_dir())


class AppDirTest(unittest.TestCase):
    def test_dev_app_dir_is_host_prototype(self):
        self.assertEqual(tools.app_dir(), Path(tools.__file__).resolve().parent)


if __name__ == "__main__":
    unittest.main()
