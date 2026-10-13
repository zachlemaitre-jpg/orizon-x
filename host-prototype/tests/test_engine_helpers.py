import os
import subprocess
import tempfile
import unittest
from pathlib import Path

import engine
import protocol
import tools
from messages import msg

OUTPUTS = [(0, (2560, 1600)), (1, (2880, 1800)), (2, None)]
CODECS = {"nvenc": "h264_nvenc", "amf": "h264_amf", "qsv": "h264_qsv", "x264": "libx264"}


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
            name = next(n for n, codec in CODECS.items() if codec in joined)
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
        error = raised.exception.msg
        self.assertEqual(error, msg("error.no_matching_screen", width=1920, height=1200,
                                    outputs=engine.describe_outputs(OUTPUTS)))
        self.assertIn("Aucun écran en 1920x1200", error.text("fr"))
        self.assertIn("--output 1 : 2880x1800", error.text("fr"))
        self.assertIn("ou choisis un autre écran (réglage Écran dans l'appli, --output N en ligne de commande) :\n",
                      error.text("fr"))
        self.assertIn("No screen at 1920x1200", str(raised.exception))
        self.assertIn("--output 1: 2880x1800", str(raised.exception))
        self.assertIn("or pick another screen (Screen setting in the app, --output N on the command line):\n",
                      str(raised.exception))


class DescribeOutputsTest(unittest.TestCase):
    def test_one_line_per_screen_then_the_gpu_note(self):
        self.assertEqual(engine.describe_outputs(OUTPUTS), msg("outputs.list", lines=[
            msg("outputs.line", index=0, width=2560, height=1600),
            msg("outputs.line", index=1, width=2880, height=1800),
            msg("outputs.line_unknown", index=2),
        ]))

    def test_no_screen(self):
        self.assertEqual(engine.describe_outputs([]), msg("outputs.none"))


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
        self.assertEqual(cmd[cmd.index("-rc") + 1], "cbr")
        self.assertNotIn("-maxrate", cmd)

    def test_qsv_arguments(self):
        cmd = engine.ffmpeg_command("ffmpeg", "qsv", 0, 60, "30M")
        self.assertEqual(cmd[cmd.index("-c:v"):cmd.index("-c:v") + 2], ["-c:v", "h264_qsv"])
        for option, value in (("-preset", "veryfast"), ("-look_ahead", "0"), ("-async_depth", "1"),
                              ("-pix_fmt", "nv12"), ("-b:v", "30M"), ("-maxrate", "30M"), ("-bf", "0"), ("-g", "60")):
            self.assertEqual(cmd[cmd.index(option) + 1], value, option)
        self.assertNotIn("-rc", cmd)  # h264_qsv n'a pas d'option -rc : maxrate = b:v donne le débit constant

    def test_x264_arguments(self):
        cmd = engine.ffmpeg_command("ffmpeg", "x264", 0, 30, "20M")
        self.assertEqual(cmd[cmd.index("-c:v"):cmd.index("-c:v") + 2], ["-c:v", "libx264"])
        for option, value in (("-preset", "ultrafast"), ("-tune", "zerolatency"), ("-profile:v", "high"),
                              ("-x264-params", "keyint=30:min-keyint=30:scenecut=0"), ("-b:v", "20M"),
                              ("-maxrate", "20M"), ("-bufsize", "10M"), ("-bf", "0"), ("-g", "30")):
            self.assertEqual(cmd[cmd.index(option) + 1], value, option)
        # bgra -> yuv420p explicite : sans lui x264 choisit le 4:4:4 et refuse le profil high
        self.assertEqual(cmd[cmd.index("-pix_fmt") + 1], "yuv420p")
        self.assertNotIn("-rc", cmd)
        self.assertEqual(cmd[-3:], ["-f", "h264", "-"])

    def test_x264_keyframe_interval_follows_the_fps(self):
        cmd = engine.ffmpeg_command("ffmpeg", "x264", 0, 24, "8M")
        self.assertEqual(cmd[cmd.index("-x264-params") + 1], "keyint=24:min-keyint=24:scenecut=0")

    def test_bufsize_with_a_suffixed_or_plain_bitrate(self):
        for bitrate, bufsize in (("12M", "6M"), ("8000k", "4000k"), ("9000000", "4500000")):
            with self.subTest(bitrate=bitrate):
                cmd = engine.ffmpeg_command("ffmpeg", "x264", 0, 30, bitrate)
                self.assertEqual(cmd[cmd.index("-bufsize") + 1], bufsize)

    def test_no_scale_by_default(self):
        cmd = engine.ffmpeg_command("ffmpeg", "x264", 3, 30, "8M")
        self.assertIn("ddagrab=output_idx=3:framerate=30,hwdownload,format=bgra", cmd)

    def test_scale_is_added_after_the_download(self):
        cmd = engine.ffmpeg_command("ffmpeg", "x264", 3, 30, "8M", scale=(1920, 1200))
        self.assertIn("ddagrab=output_idx=3:framerate=30,hwdownload,format=bgra,scale=1920:1200:flags=bilinear", cmd)


class EncoderTablesTest(unittest.TestCase):
    def test_choices_and_order(self):
        self.assertEqual(engine.ENCODER_CHOICES, ("auto", "nvenc", "amf", "qsv", "x264"))
        self.assertEqual(engine.AUTO_ORDER, ("nvenc", "amf", "qsv", "x264"))
        self.assertEqual(set(engine.ENCODERS), {"nvenc", "amf", "qsv", "x264"})
        self.assertEqual(engine.ENCODER_NAMES["qsv"], "QuickSync")
        self.assertEqual(engine.ENCODER_NAMES["x264"], "x264")


class FitWidthTest(unittest.TestCase):
    def test_smaller_or_equal_sizes_are_unchanged(self):
        self.assertEqual(engine.fit_width((1920, 1200), 1920), (1920, 1200))
        self.assertEqual(engine.fit_width((1280, 800), 1920), (1280, 800))

    def test_wider_sizes_keep_the_aspect_ratio(self):
        self.assertEqual(engine.fit_width((2880, 1800), 1920), (1920, 1200))
        self.assertEqual(engine.fit_width((2560, 1600), 1920), (1920, 1200))
        self.assertEqual(engine.fit_width((3840, 2160), 1920), (1920, 1080))

    def test_height_is_a_multiple_of_8(self):
        self.assertEqual(engine.fit_width((2000, 1200), 1920), (1920, 1152))


class BitrateTest(unittest.TestCase):
    def test_formula(self):
        self.assertEqual(engine.auto_bitrate(2400, 1500, 60), 19_440_000)
        self.assertEqual(engine.auto_bitrate(2880, 1800, 60), 27_993_600)

    def test_bounds(self):
        self.assertEqual(engine.auto_bitrate(1920, 1200, 30), 8_000_000)  # 6,2 Mb/s relevé à 8
        self.assertEqual(engine.auto_bitrate(320, 200, 30), 8_000_000)
        self.assertEqual(engine.auto_bitrate(3840, 2400, 60), 40_000_000)
        self.assertEqual(engine.auto_bitrate(7680, 4320, 60), 40_000_000)

    def test_auto_setting_is_computed(self):
        self.assertEqual(engine.resolve_bitrate("auto", 2400, 1500, 60), "19440000")

    def test_a_fixed_setting_wins(self):
        self.assertEqual(engine.resolve_bitrate("30M", 2400, 1500, 60), "30M")
        self.assertEqual(engine.resolve_bitrate("5000k", 3840, 2400, 60), "5000k")

    def test_default_config_is_auto(self):
        self.assertEqual(engine.Config().bitrate, "auto")


class PlanStreamTest(unittest.TestCase):
    NATIVE = (2880, 1800)

    def plan(self, video=None, encoder="amf", fps=60, native=NATIVE):
        return engine.plan_stream(native, video, encoder, fps)

    def test_without_video_the_native_size_and_the_configured_fps(self):
        plan = self.plan()
        self.assertEqual((plan.size, plan.fps, plan.notes), ((2880, 1800), 60, []))

    def test_video_gives_the_size_and_the_fps(self):
        plan = self.plan(protocol.VideoCaps(2160, 1350, 30))
        self.assertEqual((plan.size, plan.fps), ((2160, 1350), 30))

    def test_fps_is_the_minimum_of_config_device_and_encoder(self):
        self.assertEqual(self.plan(protocol.VideoCaps(2880, 1800, 60), fps=45).fps, 45)
        self.assertEqual(self.plan(protocol.VideoCaps(2880, 1800, 30), fps=60).fps, 30)
        self.assertEqual(self.plan(protocol.VideoCaps(2880, 1800, 60), "x264", fps=60).fps, 30)
        self.assertEqual(self.plan(protocol.VideoCaps(2880, 1800, 60), "qsv", fps=60).fps, 60)

    def test_video_larger_than_the_screen_is_ignored(self):
        for video in (protocol.VideoCaps(3840, 1800, 60), protocol.VideoCaps(2880, 2400, 60)):
            plan = self.plan(video)
            self.assertEqual(plan.size, (2880, 1800))
            self.assertEqual(plan.fps, 60)
            self.assertTrue(any("ignored" in note for note in plan.notes), plan.notes)

    def test_x264_caps_the_width_and_keeps_the_aspect_ratio(self):
        plan = self.plan(encoder="x264")
        self.assertEqual((plan.size, plan.fps), ((1920, 1200), 30))
        self.assertEqual(plan.notes, ["x264 runs on the processor: 30 fps at most",
                                      "x264 runs on the processor: 1920x1200 at most"])

    def test_x264_caps_the_size_the_device_announced(self):
        self.assertEqual(self.plan(protocol.VideoCaps(2400, 1500, 60), "x264").size, (1920, 1200))
        plan = self.plan(protocol.VideoCaps(1280, 800, 60), "x264")
        self.assertEqual((plan.size, plan.fps), ((1280, 800), 30))

    def test_x264_below_its_limits_adds_no_processor_note(self):
        plan = self.plan(protocol.VideoCaps(1280, 800, 30), "x264", fps=30)
        self.assertEqual((plan.size, plan.fps), ((1280, 800), 30))
        self.assertFalse([note for note in plan.notes if "processor" in note], plan.notes)

    def test_other_encoders_have_no_limits(self):
        for encoder in ("nvenc", "amf", "qsv"):
            self.assertEqual(self.plan(encoder=encoder).size, (2880, 1800), encoder)


class ResolveEncoderTest(unittest.TestCase):
    def test_auto_prefers_nvenc(self):
        run = FakeRun(ok_encoders=("nvenc", "amf"))
        self.assertEqual(engine.resolve_encoder("ffmpeg", "auto", run), ("nvenc", "Encoder: NVENC"))

    def test_auto_falls_back_to_amf(self):
        run = FakeRun(ok_encoders=("amf",))
        self.assertEqual(engine.resolve_encoder("ffmpeg", "auto", run),
                         ("amf", "Encoder: AMF (NVENC unavailable)"))

    def test_auto_falls_back_to_quicksync_then_x264(self):
        run = FakeRun(ok_encoders=("qsv", "x264"))
        self.assertEqual(engine.resolve_encoder("ffmpeg", "auto", run),
                         ("qsv", "Encoder: QuickSync (NVENC, AMF unavailable)"))

    def test_only_x264_available_gives_x264(self):
        run = FakeRun(ok_encoders=("x264",))
        self.assertEqual(engine.resolve_encoder("ffmpeg", "auto", run),
                         ("x264", "Encoder: x264 (NVENC, AMF, QuickSync unavailable)"))
        self.assertEqual([next(c for c in CODECS.values() if c in " ".join(cmd)) for cmd, _ in run.calls],
                         ["h264_nvenc", "h264_amf", "h264_qsv", "libx264"])

    def test_forced_new_encoders_are_not_probed(self):
        run = FakeRun()
        self.assertEqual(engine.resolve_encoder("ffmpeg", "qsv", run), ("qsv", "Encoder: QuickSync (forced)"))
        self.assertEqual(engine.resolve_encoder("ffmpeg", "x264", run), ("x264", "Encoder: x264 (forced)"))
        self.assertEqual(run.calls, [])

    def test_probe_uses_each_encoders_own_arguments(self):
        for name, codec in (("qsv", "h264_qsv"), ("x264", "libx264")):
            run = FakeRun(ok_encoders=(name,))
            self.assertTrue(engine.probe_encoder("ffmpeg", name, run))
            cmd = run.calls[0][0]
            self.assertEqual(cmd[cmd.index("-c:v") + 1], codec)
            self.assertNotIn("{fps}", " ".join(cmd))
        run = FakeRun(ok_encoders=("x264",))
        engine.probe_encoder("ffmpeg", "x264", run)
        self.assertIn("yuv420p", run.calls[0][0])

    def test_auto_without_any_encoder_is_fatal(self):
        with self.assertRaises(engine.FatalError) as raised:
            engine.resolve_encoder("ffmpeg", "auto", FakeRun())
        self.assertEqual(raised.exception.msg, msg("error.no_encoder"))

    def test_forced_encoder_is_not_probed(self):
        run = FakeRun()
        self.assertEqual(engine.resolve_encoder("ffmpeg", "amf", run), ("amf", "Encoder: AMF (forced)"))
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
        self.assertEqual(self.problem("List of devices attached\n\n"), msg("adb.no_device"))

    def test_unauthorized(self):
        self.assertEqual(self.problem("List of devices attached\nR52\tunauthorized\n"), msg("adb.unauthorized"))

    def test_two_devices(self):
        self.assertEqual(self.problem("List of devices attached\nA\tdevice\nB\tdevice\n"),
                         msg("adb.not_exactly_one", states="device, device"))

    def test_adb_failure_is_a_message_not_a_crash(self):
        self.assertEqual(self.problem("", code=1, stderr="daemon not running"),
                         msg("adb.failed", error="daemon not running"))

    def test_adb_calls_have_a_timeout(self):
        run = FakeRun(adb_stdout="List of devices attached\nR52\tdevice\n", forward_code=0)
        self.assertIsNone(engine.ensure_forward("adb", run))
        self.assertEqual([kwargs.get("timeout") for _cmd, kwargs in run.calls], [10, 10])

    def test_adb_devices_hanging_is_a_message(self):
        def hung(cmd, **kwargs):
            raise subprocess.TimeoutExpired(cmd, kwargs.get("timeout"))
        self.assertEqual(engine.adb_problem("adb", hung), msg("adb.timeout"))

    def test_adb_forward_hanging_is_a_message(self):
        run = FakeRun(adb_stdout="List of devices attached\nR52\tdevice\n", forward_hangs=True)
        self.assertEqual(engine.ensure_forward("adb", run), msg("adb.timeout"))

    def test_adb_forward_failure_is_a_message(self):
        run = FakeRun(adb_stdout="List of devices attached\nR52\tdevice\n", forward_code=1)
        self.assertEqual(engine.ensure_forward("adb", run), msg("adb.forward_failed", error=""))


class ToolCwdTest(unittest.TestCase):
    """Every adb / ffmpeg call runs in the tool's own folder (never the app folder): adb's server inherits it."""

    def setUp(self):
        self.folder = tempfile.mkdtemp()
        self.adb = os.path.join(self.folder, "adb.exe")
        self.ffmpeg = os.path.join(self.folder, "ffmpeg.exe")

    def assert_all_in_folder(self, run):
        self.assertTrue(run.calls)
        for cmd, kwargs in run.calls:
            self.assertEqual(kwargs.get("cwd"), str(Path(self.folder).resolve()), cmd)

    def test_adb_devices_and_forward(self):
        run = FakeRun(adb_stdout="List of devices attached\nR52\tdevice\n", forward_code=0)
        self.assertIsNone(engine.ensure_forward(self.adb, run))
        self.assertEqual(len(run.calls), 2)
        self.assert_all_in_folder(run)

    def test_bare_adb_runs_in_the_temp_folder(self):
        run = FakeRun(adb_stdout="List of devices attached\n\n")
        engine.adb_problem("adb", run)
        self.assertEqual(run.calls[0][1]["cwd"], tempfile.gettempdir())

    def test_ffmpeg_probes(self):
        run = FakeRun(ok_encoders=("nvenc",))
        engine.probe_encoder(self.ffmpeg, "nvenc", run)

        def probe(cmd, **kwargs):
            run.calls.append((cmd, kwargs))
            return subprocess.CompletedProcess(cmd, 0, "", "Stream #0:0: Video: bgra, 2880x1800")

        engine.probe_outputs(self.ffmpeg, max_outputs=1, run=probe)
        self.assertEqual(len(run.calls), 2)
        self.assert_all_in_folder(run)


class FormatStatsTest(unittest.TestCase):
    def test_one_english_line(self):
        stats = engine.StreamStats(2880, 1800, 60, 18.25, 40.0, 2, 0.5)
        self.assertEqual(engine.format_stats(stats),
                         " 60 fps | latency avg  18.2 ms, max  40.0 ms | dropped 2 | RTT 0.50 ms")


if __name__ == "__main__":
    unittest.main()
