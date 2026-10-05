import contextlib
import io
import unittest
from unittest import mock

import engine
import relay
from messages import msg


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
    def test_prints_details_logs_and_stats_in_english(self):
        out = io.StringIO()
        listener = relay.PrintListener()
        with contextlib.redirect_stdout(out):
            listener.on_state(engine.State.WAITING_APP, engine.WAITING_APP_DETAIL)
            listener.on_log("[ffmpeg] warning")
            listener.on_stats(engine.StreamStats(2880, 1800, 60, 18.25, 40.0, 2, 0.5))
        self.assertEqual(out.getvalue().splitlines(), [
            "Tablet plugged in. Open Orizon X on it.",
            "[ffmpeg] warning",
            " 60 fps | latency avg  18.2 ms, max  40.0 ms | dropped 2 | RTT 0.50 ms",
        ])

    def test_prints_only_the_states_that_say_what_to_do(self):
        out = io.StringIO()
        listener = relay.PrintListener()
        with contextlib.redirect_stdout(out):
            listener.on_state(engine.State.WAITING_DEVICE, msg("adb.no_device"))
            listener.on_state(engine.State.STREAMING, msg("state.streaming", width=2880, height=1800))  # doublon du journal
            listener.on_state(engine.State.ERROR, msg("error.protocol_mismatch", tablet=9, pc=1))
            listener.on_state(engine.State.STOPPED, msg("state.stopped"))  # doublon de « Stopping. »
        self.assertEqual(out.getvalue().splitlines(), [
            "No tablet found. Plug in the USB cable and turn on USB debugging.",
            "Incompatible protocol: tablet v9, PC v1. Update the app or the relay.",
        ])


class FakeEngine:
    def __init__(self, config, listener, *, ffmpeg, adb):
        self.config = config
        self.state = engine.State.ERROR
        listener.on_state(engine.State.ERROR, msg("error.protocol_mismatch", tablet=9, pc=1))

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
        self.assertIn("Incompatible protocol", out)

    def test_missing_tool_exits_with_1(self):
        def missing(name):
            raise relay.tools.ToolMissing(msg("tools.ffmpeg_missing"))
        with mock.patch.object(relay.tools, "find_tool", side_effect=missing), \
                mock.patch.object(relay.injector, "enable_dpi_awareness"), \
                contextlib.redirect_stderr(io.StringIO()) as err:
            self.assertEqual(relay.main([]), 1)
        self.assertIn("ffmpeg not found", err.getvalue())

    def test_list_outputs_prints_english(self):
        outputs = [(0, (2880, 1800))]
        with mock.patch.object(relay.engine, "probe_outputs", return_value=outputs):
            code, out = self.run_main(["--list-outputs"])
        self.assertEqual(code, 0)
        self.assertTrue(out.startswith("--output 0: 2880x1800\nOnly screens on the default GPU are listed"), out)


if __name__ == "__main__":
    unittest.main()
