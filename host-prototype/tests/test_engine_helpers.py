import subprocess
import unittest

import engine
import tools

OUTPUTS = [(0, (2560, 1600)), (1, (2880, 1800)), (2, None)]


class FakeRun:
    """Records commands; answers with the given return code per encoder / adb output."""

    def __init__(self, ok_encoders=(), adb_stdout="", adb_code=0, adb_stderr="", forward_code=None,
                 forward_hangs=False):
        self.ok_encoders = ok_encoders
        self.adb_stdout = adb_stdout
        self.adb_code = adb_code
        self.adb_stderr = adb_stderr
        self.forward_code = forward_code
        self.forward_hangs = forward_hangs
        self.calls = []

    def __call__(self, cmd, **kwargs):
        self.calls.append((cmd, kwargs))
        joined = " ".join(cmd)
        if "color=" in joined:
            name = "nvenc" if "h264_nvenc" in joined else "amf"
            return subprocess.CompletedProcess(cmd, 0 if name in self.ok_encoders else 1, b"", b"")
        if cmd[1:] == ["devices"]:
            return subprocess.CompletedProcess(cmd, self.adb_code, self.adb_stdout, self.adb_stderr)
        if cmd[1] == "forward" and self.forward_hangs:
            raise subprocess.TimeoutExpired(cmd, kwargs.get("timeout"))
        if cmd[1] == "forward" and self.forward_code is not None:
            return subprocess.CompletedProcess(cmd, self.forward_code, "", "")
        raise AssertionError(cmd)


class PickOutputTest(unittest.TestCase):
    def test_explicit_index_is_used_as_is(self):
        self.assertEqual(engine.pick_output("2", OUTPUTS, 2880, 1800), 2)

    def test_auto_picks_screen_with_tablet_size(self):
        self.assertEqual(engine.pick_output("auto", OUTPUTS, 2880, 1800), 1)

    def test_auto_without_match_is_fatal_with_the_list(self):
        with self.assertRaises(engine.FatalError) as raised:
            engine.pick_output("auto", OUTPUTS, 1920, 1200)
        self.assertIn("Aucun écran en 1920x1200", str(raised.exception))
        self.assertIn("--output 1 : 2880x1800", str(raised.exception))
        self.assertIn("ou choisis un autre écran (réglage Écran dans l'appli, --output N en ligne de commande) :\n",
                      str(raised.exception))


class ProbeOutputsTest(unittest.TestCase):
    def test_stop_returns_the_outputs_found_so_far(self):
        calls = []

        def run(cmd, **kwargs):
            calls.append(cmd)
            return subprocess.CompletedProcess(cmd, 0, "", "Stream #0:0: Video: bgra, 2880x1800")

        outputs = engine.probe_outputs("ffmpeg", run=run, should_stop=lambda: len(calls) >= 2)
        self.assertEqual(outputs, [(0, (2880, 1800)), (1, (2880, 1800))])
        self.assertEqual(len(calls), 2)

    def test_a_hung_probe_ends_the_list(self):
        calls = []

        def run(cmd, **kwargs):
            calls.append(kwargs.get("timeout"))
            if len(calls) == 2:
                raise subprocess.TimeoutExpired(cmd, kwargs.get("timeout"))
            return subprocess.CompletedProcess(cmd, 0, "", "Stream #0:0: Video: bgra, 2880x1800")

        self.assertEqual(engine.probe_outputs("ffmpeg", run=run), [(0, (2880, 1800))])
        self.assertEqual(calls, [engine.ENCODER_PROBE_TIMEOUT_S] * 2)


class FfmpegCommandTest(unittest.TestCase):
    def test_uses_given_path_encoder_output_and_rate(self):
        cmd = engine.ffmpeg_command("C:/x/ffmpeg.exe", "amf", 3, 60, "30M")
        self.assertEqual(cmd[0], "C:/x/ffmpeg.exe")
        self.assertIn("ddagrab=output_idx=3:framerate=60,hwdownload,format=bgra", cmd)
        self.assertIn("h264_amf", cmd)
        self.assertEqual(cmd[cmd.index("-b:v") + 1], "30M")
        self.assertEqual(cmd[cmd.index("-g") + 1], "60")
        self.assertEqual(cmd[-3:], ["-f", "h264", "-"])


class ResolveEncoderTest(unittest.TestCase):
    def test_auto_prefers_nvenc(self):
        run = FakeRun(ok_encoders=("nvenc", "amf"))
        self.assertEqual(engine.resolve_encoder("ffmpeg", "auto", run), ("nvenc", "Encodeur : NVENC"))

    def test_auto_falls_back_to_amf(self):
        run = FakeRun(ok_encoders=("amf",))
        self.assertEqual(engine.resolve_encoder("ffmpeg", "auto", run),
                         ("amf", "Encodeur : AMF (NVENC indisponible)"))

    def test_auto_without_any_encoder_is_fatal(self):
        with self.assertRaises(engine.FatalError) as raised:
            engine.resolve_encoder("ffmpeg", "auto", FakeRun())
        self.assertIn("Aucun encodeur matériel H.264", str(raised.exception))

    def test_forced_encoder_is_not_probed(self):
        run = FakeRun()
        self.assertEqual(engine.resolve_encoder("ffmpeg", "amf", run), ("amf", "Encodeur : AMF (forcé)"))
        self.assertEqual(run.calls, [])

    def test_stop_between_probes_skips_the_next_one(self):
        run = FakeRun(ok_encoders=("amf",))
        with self.assertRaises(engine._Stopped):
            engine.resolve_encoder("ffmpeg", "auto", run, should_stop=lambda: len(run.calls) >= 1)
        self.assertEqual(len(run.calls), 1)
        self.assertIn("h264_nvenc", run.calls[0][0])

    def test_probe_runs_without_console(self):
        run = FakeRun(ok_encoders=("nvenc",))
        engine.probe_encoder("ffmpeg", "nvenc", run)
        cmd, kwargs = run.calls[0]
        self.assertEqual(kwargs["creationflags"], tools.NO_WINDOW)
        self.assertEqual(kwargs["timeout"], 10)
        self.assertIn("h264_nvenc", cmd)

    def test_probe_timeout_counts_as_unavailable(self):
        def slow(cmd, **kwargs):
            raise subprocess.TimeoutExpired(cmd, 15)
        self.assertFalse(engine.probe_encoder("ffmpeg", "amf", slow))


class AdbProblemTest(unittest.TestCase):
    def problem(self, stdout, code=0, stderr=""):
        return engine.adb_problem("adb", FakeRun(adb_stdout=stdout, adb_code=code, adb_stderr=stderr))

    def test_ready(self):
        self.assertIsNone(self.problem("List of devices attached\nR52\tdevice\n"))

    def test_no_device(self):
        self.assertIn("Aucune tablette détectée", self.problem("List of devices attached\n\n"))

    def test_unauthorized(self):
        self.assertIn("non autorisée", self.problem("List of devices attached\nR52\tunauthorized\n"))

    def test_two_devices(self):
        self.assertIn("exactement une tablette",
                      self.problem("List of devices attached\nA\tdevice\nB\tdevice\n"))

    def test_adb_failure_is_a_message_not_a_crash(self):
        self.assertIn("adb ne répond pas", self.problem("", code=1, stderr="daemon not running"))

    def test_adb_calls_have_a_timeout(self):
        run = FakeRun(adb_stdout="List of devices attached\nR52\tdevice\n", forward_code=0)
        self.assertIsNone(engine.ensure_forward("adb", run))
        self.assertEqual([kwargs.get("timeout") for _cmd, kwargs in run.calls], [10, 10])

    def test_adb_devices_hanging_is_a_message(self):
        def hung(cmd, **kwargs):
            raise subprocess.TimeoutExpired(cmd, kwargs.get("timeout"))
        self.assertEqual(engine.adb_problem("adb", hung), "adb ne répond pas (délai dépassé).")

    def test_adb_forward_hanging_is_a_message(self):
        run = FakeRun(adb_stdout="List of devices attached\nR52\tdevice\n", forward_hangs=True)
        self.assertEqual(engine.ensure_forward("adb", run), "adb ne répond pas (délai dépassé).")


class FormatStatsTest(unittest.TestCase):
    def test_same_line_as_the_old_relay(self):
        stats = engine.StreamStats(2880, 1800, 60, 18.25, 40.0, 2, 0.5)
        self.assertEqual(engine.format_stats(stats),
                         " 60 fps | latence moy  18.2 ms, max  40.0 ms | perdues 2 | RTT 0.50 ms")


if __name__ == "__main__":
    unittest.main()
