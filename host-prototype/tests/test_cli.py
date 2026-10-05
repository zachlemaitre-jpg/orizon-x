import contextlib
import io
import unittest
from unittest import mock

import engine
import relay


class ParseArgsTest(unittest.TestCase):
    def test_encoder_defaults_to_auto(self):
        args = relay.parse_args([])
        self.assertEqual((args.encoder, args.output, args.fps, args.bitrate), ("auto", "auto", 60, "30M"))

    def test_explicit_values(self):
        args = relay.parse_args(["--encoder", "amf", "--output", "2", "--fps", "30", "--bitrate", "20M"])
        self.assertEqual((args.encoder, args.output, args.fps, args.bitrate), ("amf", "2", 30, "20M"))

    def test_output_choice_rejects_garbage(self):
        with self.assertRaises(Exception):
            relay.output_choice("deux")


class PrintListenerTest(unittest.TestCase):
    def test_prints_details_logs_and_stats(self):
        out = io.StringIO()
        listener = relay.PrintListener()
        with contextlib.redirect_stdout(out):
            listener.on_state(engine.State.WAITING_APP, engine.WAITING_APP_DETAIL)
            listener.on_log("[ffmpeg] warning")
            listener.on_stats(engine.StreamStats(2880, 1800, 60, 18.25, 40.0, 2, 0.5))
        self.assertEqual(out.getvalue().splitlines(), [
            engine.WAITING_APP_DETAIL,
            "[ffmpeg] warning",
            " 60 fps | latence moy  18.2 ms, max  40.0 ms | perdues 2 | RTT 0.50 ms",
        ])


class FakeEngine:
    def __init__(self, config, listener, *, ffmpeg, adb):
        self.config = config
        self.state = engine.State.ERROR
        listener.on_state(engine.State.ERROR, "Protocole incompatible")

    def start(self):
        pass

    def wait(self, timeout=None):
        return True

    def stop(self):
        pass


class MainTest(unittest.TestCase):
    def run_main(self, argv):
        with mock.patch.object(relay.tools, "find_tool", side_effect=lambda name: f"{name}.exe"), \
                mock.patch.object(relay.engine, "RelayEngine", FakeEngine), \
                mock.patch.object(relay.injector, "enable_dpi_awareness"), \
                contextlib.redirect_stdout(io.StringIO()) as out:
            code = relay.main(argv)
        return code, out.getvalue()

    def test_error_state_exits_with_1(self):
        code, out = self.run_main(["--encoder", "amf"])
        self.assertEqual(code, 1)
        self.assertIn("Protocole incompatible", out)

    def test_missing_tool_exits_with_1(self):
        def missing(name):
            raise relay.tools.ToolMissing("ffmpeg introuvable.")
        with mock.patch.object(relay.tools, "find_tool", side_effect=missing), \
                mock.patch.object(relay.injector, "enable_dpi_awareness"), \
                contextlib.redirect_stderr(io.StringIO()) as err:
            self.assertEqual(relay.main([]), 1)
        self.assertIn("ffmpeg introuvable", err.getvalue())


if __name__ == "__main__":
    unittest.main()
