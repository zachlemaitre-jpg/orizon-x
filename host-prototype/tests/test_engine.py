import queue
import re
import socket
import subprocess
import threading
import time
import unittest
from pathlib import Path

import engine
import protocol
import tools
from inputstate import Rect
from messages import msg
from virtual_display import PrepareResult

SAMPLE = (Path(__file__).parent / "sample.h264").read_bytes()
State = engine.State


def hello_frame(version=protocol.VERSION, width=2880, height=1800, dpi=274):
    return protocol._frame(protocol.HELLO, 0, protocol._HELLO.pack(protocol.MAGIC, version, width, height, dpi))


def stats_frame(fps=60, avg_us=18000, max_us=40000, dropped=0, rtt_us=500):
    return protocol._frame(protocol.STATS, 0, protocol._STATS.pack(fps, avg_us, max_us, dropped, rtt_us))


def ping_frame(t_tab_us):
    return protocol._frame(protocol.PING, 0, protocol._U64.pack(t_tab_us))


def touch_frame(*contacts):
    payload = protocol._INPUT_HEAD.pack(protocol.DEVICE_TOUCH, len(contacts))
    payload += b"".join(protocol._CONTACT.pack(*c) for c in contacts)
    return protocol._frame(protocol.INPUT, 0, payload)


def wait_until(predicate, timeout=5.0):
    deadline = time.monotonic() + timeout
    while not predicate():
        if time.monotonic() > deadline:
            raise AssertionError("délai dépassé")
        time.sleep(0.01)


class FakeRun:
    """Answers the adb and ffmpeg probe commands the engine runs."""

    def __init__(self, devices="R52\tdevice", outputs=((0, (2880, 1800)),), encoders_ok=("amf",)):
        self.devices = devices
        self.outputs = dict(outputs)
        self.encoders_ok = encoders_ok
        self.calls = []

    def __call__(self, cmd, **kwargs):
        self.calls.append((cmd, kwargs))
        joined = " ".join(str(c) for c in cmd)
        text = kwargs.get("text", False)

        def done(code, stdout="", stderr=""):
            if not text:
                stdout, stderr = stdout.encode(), stderr.encode()
            return subprocess.CompletedProcess(cmd, code, stdout, stderr)

        if cmd[1:] == ["devices"]:
            return done(0, f"List of devices attached\n{self.devices}\n")
        if cmd[1] == "forward":
            return done(0)
        match = re.search(r"ddagrab=output_idx=(\d+)", joined)
        if match:
            size = self.outputs.get(int(match.group(1)))
            if size is None:
                return done(1, stderr="Failed to enumerate DXGI output")
            return done(0, stderr=f"Stream #0:0: Video: bgra, {size[0]}x{size[1]}")
        if "color=" in joined:
            name = "nvenc" if "h264_nvenc" in joined else "amf"
            return done(0 if name in self.encoders_ok else 1)
        raise AssertionError(f"commande inattendue : {cmd}")


class BlockingProbeRun(FakeRun):
    """The NVENC probe blocks until the test releases it, like a GPU slow to wake up."""

    def __init__(self):
        super().__init__(encoders_ok=("amf",))
        self.probing = threading.Event()
        self.release = threading.Event()

    def __call__(self, cmd, **kwargs):
        if "h264_nvenc" in cmd:
            self.probing.set()
            self.release.wait(5)
        return super().__call__(cmd, **kwargs)


class FakeStdout:
    def __init__(self, data, hold_open):
        self._data = data
        self._hold_open = hold_open
        self._closed = threading.Event()

    def read1(self, size):
        if self._data:
            chunk, self._data = self._data[:size], self._data[size:]
            return chunk
        if self._hold_open:
            self._closed.wait()
        return b""

    def close(self):
        self._closed.set()


class FedStdout:
    """A live capture whose output the test feeds chunk by chunk; ends when killed."""

    def __init__(self):
        self._chunks = queue.Queue()

    def feed(self, data):
        self._chunks.put(data)

    def read1(self, size):
        return self._chunks.get()

    def close(self):
        self._chunks.put(b"")


class FakeFfmpeg:
    """hold_open=True: a live capture that only ends when killed. False: ffmpeg exits on its own after `data`."""

    def __init__(self, data=b"", hold_open=True, stderr_lines=()):
        self.stdout = FakeStdout(data, hold_open)
        self.stderr = [line.encode() + b"\n" for line in stderr_lines]
        self.killed = threading.Event()
        self.waits = []

    def kill(self):
        self.killed.set()
        self.stdout.close()

    def wait(self, timeout=None):
        self.waits.append(timeout)
        return 0


class FakePopen:
    """One factory per session; the last factory is reused for any further session."""

    def __init__(self, *factories):
        self.factories = list(factories)
        self.calls = []
        self.procs = []

    def __call__(self, cmd, **kwargs):
        self.calls.append((cmd, kwargs))
        factory = self.factories[min(len(self.calls), len(self.factories)) - 1]
        proc = factory()
        self.procs.append(proc)
        return proc


class FakeTablet:
    """The tablet end of a socket pair: sends HELLO at once and records every frame the PC sends."""

    def __init__(self, version=protocol.VERSION):
        self.pc, self.tab = socket.socketpair()
        self.frames = queue.Queue()
        self.tab.sendall(hello_frame(version))
        threading.Thread(target=self._drain, daemon=True).start()

    def _drain(self):
        reader = self.tab.makefile("rb")
        try:
            while True:
                head = reader.read(protocol.HEADER.size)
                if len(head) < protocol.HEADER.size:
                    break
                msg_type, flags, _reserved, length = protocol.HEADER.unpack(head)
                self.frames.put((msg_type, flags, reader.read(length)))
        except (OSError, ValueError):
            pass
        finally:
            reader.close()
            self.tab.close()  # le PC a fermé : on libère aussi le bout tablette (pas de ResourceWarning)
        self.frames.put(None)

    def next_message(self, of_type, timeout=5.0):
        deadline = time.monotonic() + timeout
        while True:
            frame = self.frames.get(timeout=max(0.01, deadline - time.monotonic()))
            if frame is None:
                raise AssertionError("connexion fermée par le PC")
            if frame[0] == of_type:
                return frame

    def wait_closed(self, timeout=5.0):
        deadline = time.monotonic() + timeout
        while True:
            if self.frames.get(timeout=max(0.01, deadline - time.monotonic())) is None:
                return

    def send(self, data):
        self.tab.sendall(data)

    def leave(self):
        self.tab.shutdown(socket.SHUT_RDWR)


class FakeConnect:
    """socket.create_connection stand-in: each call hands the engine a new FakeTablet, or refuses.

    silent=True mimics adb with no app listening on the tablet: the connection is accepted, then closed without HELLO.
    """

    def __init__(self, version=protocol.VERSION):
        self.version = version
        self.refuse = False
        self.silent = False
        self.silent_calls = 0
        self.tablets = []

    def __call__(self, address, timeout=None):
        if self.refuse:
            raise ConnectionRefusedError("refusé")
        if self.silent:
            self.silent_calls += 1
            pc, tab = socket.socketpair()
            tab.close()
            return pc
        tablet = FakeTablet(self.version)
        self.tablets.append(tablet)
        return tablet.pc


class FakeInjector:
    def __init__(self, width, height, error=None):
        self.width = width
        self.height = height
        self.error = error
        self.handled = []
        self.closed = False

    def handle(self, message):
        self.handled.append(message)
        if self.error is not None:
            raise self.error

    def close(self):
        self.closed = True


class FakeInjectors:
    def __init__(self, error=None):
        self.error = error
        self.created = []
        self.rects = []  # écran visé passé par le moteur (None : trouvé par la taille du flux)

    def __call__(self, width, height, log, rect=None):
        injector = FakeInjector(width, height, self.error)
        self.created.append(injector)
        self.rects.append(rect)
        return injector


PRIMARY = Rect(0, 0, 2560, 1600)
VDD_RECT = Rect(2560, 0, 2880, 1800)


class FakeDisplay:
    """virtual_display.VirtualDisplay stand-in. block=True: prepare() waits for `proceed` (or should_stop)."""

    def __init__(self, result=None, error=None, block=False, on_prepare=None):
        self.result = result or PrepareResult(VDD_RECT, True, (2880, 1800))
        self.error = error
        self.on_prepare = on_prepare
        self.calls = []
        self.entered = threading.Event()
        self.proceed = threading.Event()
        self.saw_stop = threading.Event()
        if not block:
            self.proceed.set()

    def prepare(self, width, height, dpi, position, scale, first_time, should_stop):
        self.calls.append(("prepare", width, height, dpi, position, scale, first_time))
        self.entered.set()
        while not self.proceed.wait(0.01):
            if should_stop():
                self.saw_stop.set()
                return None
        if self.error is not None:
            raise self.error
        if self.on_prepare is not None:
            self.on_prepare()
        return self.result

    def release(self, immediate=False):
        self.calls.append(("release", immediate))

    def releases(self):
        return [c for c in self.calls if c[0] == "release"]

    def prepares(self):
        return [c for c in self.calls if c[0] == "prepare"]


class Recorder:
    def __init__(self):
        self.states = []
        self.logs = []
        self.stats = []
        self.displays = []
        self._cond = threading.Condition()

    def on_display(self, info):
        with self._cond:
            self.displays.append(info)
            self._cond.notify_all()

    def on_state(self, state, detail):
        with self._cond:
            self.states.append((state, detail))
            self._cond.notify_all()

    def on_log(self, line):
        with self._cond:
            self.logs.append(line)
            self._cond.notify_all()

    def on_stats(self, stats):
        with self._cond:
            self.stats.append(stats)
            self._cond.notify_all()

    def wait_for(self, predicate, timeout=5.0):
        with self._cond:
            if not self._cond.wait_for(predicate, timeout):
                raise AssertionError(f"délai dépassé ; états : {self.states}")

    def wait_state(self, state, timeout=5.0):
        self.wait_for(lambda: any(s is state for s, _ in self.states), timeout)

    def last_state(self):
        return self.states[-1][0] if self.states else None


def live():
    return FakeFfmpeg(SAMPLE)


def dead():
    return FakeFfmpeg(b"", hold_open=False, stderr_lines=["boom"])


def video_then_dead():
    return FakeFfmpeg(SAMPLE, hold_open=False, stderr_lines=["fin"])


def make_engine(test, run=None, popen=None, connect=None, injectors=None, config=engine.Config(encoder="amf"),
                recorder=None, monitors=None, **engine_args):
    """engine_args: display, first_time, on_layout_applied (RelayEngine keywords)."""
    recorder = recorder or Recorder()
    listed = [(PRIMARY, True, r"\\.\DISPLAY1"), (VDD_RECT, False, r"\\.\DISPLAY9")] if monitors is None else monitors
    deps = engine.Deps(
        run=run or FakeRun(),
        popen=popen or FakePopen(live),
        create_connection=connect or FakeConnect(),
        create_injector=injectors or FakeInjectors(),
        monitors=lambda: list(listed),
        poll_s=0.01,
        retry_delay_s=0.0,
    )
    relay = engine.RelayEngine(config, recorder, ffmpeg="ffmpeg.exe", adb="adb.exe", deps=deps, **engine_args)
    test.addCleanup(relay.stop)
    return relay, recorder


def output_index(popen_call):
    return int(re.search(r"ddagrab=output_idx=(\d+)", " ".join(popen_call[0])).group(1))


def first_tablet(connect, timeout=5.0):
    deadline = time.monotonic() + timeout
    while not connect.tablets:
        if time.monotonic() > deadline:
            raise AssertionError("aucune connexion")
        time.sleep(0.01)
    return connect.tablets[0]


class StreamingTest(unittest.TestCase):
    def test_streams_and_reports_stats_with_stream_size(self):
        connect, injectors = FakeConnect(), FakeInjectors()
        relay, rec = make_engine(self, connect=connect, injectors=injectors)
        relay.start()
        tablet = first_tablet(connect)
        _type, _flags, payload = tablet.next_message(protocol.CONFIG)
        _codec, width, height, fps = protocol._CONFIG.unpack(payload)
        tablet.next_message(protocol.VIDEO)
        tablet.send(stats_frame())
        rec.wait_for(lambda: rec.stats)
        stats = rec.stats[0]
        self.assertEqual((stats.width, stats.height, stats.fps), (width, height, 60))
        self.assertAlmostEqual(stats.latency_avg_ms, 18.0)
        self.assertEqual(fps, 60)
        self.assertEqual([(i.width, i.height) for i in injectors.created], [(width, height)])
        self.assertIs(rec.last_state(), State.STREAMING)
        self.assertIn("Tablet connected: screen 2880x1800, 274 dpi", rec.logs)
        self.assertIn("Captured screen: #0 (2880x1800, picked automatically)", rec.logs)

    def test_first_state_is_shown_before_the_probes(self):
        run = BlockingProbeRun()
        relay, rec = make_engine(self, run=run, config=engine.Config(encoder="auto"))
        self.addCleanup(run.release.set)  # avant le stop() du nettoyage (ordre inverse)
        relay.start()
        self.assertTrue(run.probing.wait(5))
        self.assertEqual(rec.states, [(State.WAITING_DEVICE, msg("state.preparing_capture"))])

    def test_ping_gets_a_pong_with_the_same_tablet_time(self):
        connect = FakeConnect()
        relay, rec = make_engine(self, connect=connect)
        relay.start()
        tablet = first_tablet(connect)
        tablet.send(ping_frame(123456789))
        _type, _flags, payload = tablet.next_message(protocol.PONG)
        t_tab_us, _t_pc_us = protocol._PONG.unpack(payload)
        self.assertEqual(t_tab_us, 123456789)

    def test_input_goes_to_the_injector(self):
        connect, injectors = FakeConnect(), FakeInjectors()
        relay, rec = make_engine(self, connect=connect, injectors=injectors)
        relay.start()
        tablet = first_tablet(connect)
        tablet.next_message(protocol.CONFIG)  # l'injecteur est créé avant l'envoi du CONFIG
        down = protocol.CONTACT_CONTACT | protocol.CONTACT_IN_RANGE
        tablet.send(touch_frame((3, down, 100, 200, 512, 0, 0)))
        wait_until(lambda: injectors.created[0].handled)
        self.assertEqual(injectors.created[0].handled, [
            protocol.Input(protocol.DEVICE_TOUCH, (protocol.Contact(3, down, 100, 200, 512, 0, 0),))])

    def test_failing_injector_is_logged_once_and_video_keeps_flowing(self):
        stdout = FedStdout()

        def fed():
            ffmpeg = FakeFfmpeg()
            ffmpeg.stdout = stdout
            return ffmpeg

        connect, injectors = FakeConnect(), FakeInjectors(error=RuntimeError("pilote absent"))
        relay, rec = make_engine(self, connect=connect, injectors=injectors, popen=FakePopen(fed))
        relay.start()
        stdout.feed(SAMPLE)
        tablet = first_tablet(connect)
        tablet.next_message(protocol.CONFIG)
        down = protocol.CONTACT_CONTACT | protocol.CONTACT_IN_RANGE
        tablet.send(touch_frame((0, down, 10, 10, 0, 0, 0)))
        tablet.send(touch_frame((0, down, 20, 20, 0, 0, 0)))
        wait_until(lambda: len(injectors.created[0].handled) == 2)
        failures = [line for line in rec.logs if line.startswith("Touch failed")]
        self.assertEqual(failures, ["Touch failed, input ignored: pilote absent"])
        after_failure = engine.now_us()
        stdout.feed(SAMPLE)
        while True:  # une image horodatée après l'échec prouve que la vidéo continue
            _type, _flags, payload = tablet.next_message(protocol.VIDEO)
            if protocol._U64.unpack_from(payload)[0] >= after_failure:
                break
        self.assertIs(rec.last_state(), State.STREAMING)

    def test_adb_accepting_then_closing_without_hello_means_app_not_open(self):
        connect, popen = FakeConnect(), FakePopen(live)
        connect.silent = True
        relay, rec = make_engine(self, connect=connect, popen=popen)
        relay.start()
        rec.wait_state(State.WAITING_APP)
        self.assertEqual(rec.states[-1], (State.WAITING_APP, msg("state.waiting_app")))
        self.assertGreaterEqual(connect.silent_calls, 1)
        self.assertEqual(popen.calls, [])

    def test_listener_exceptions_never_stop_the_engine(self):
        class FailingRecorder(Recorder):
            def on_state(self, state, detail):
                super().on_state(state, detail)
                raise RuntimeError("listener en panne")

            def on_log(self, line):
                super().on_log(line)
                raise RuntimeError("listener en panne")

        connect = FakeConnect()
        relay, rec = make_engine(self, connect=connect, recorder=FailingRecorder())
        relay.start()
        tablet = first_tablet(connect)
        tablet.next_message(protocol.CONFIG)
        tablet.next_message(protocol.VIDEO)
        self.assertTrue(relay.is_running())
        self.assertIs(rec.last_state(), State.STREAMING)

    def test_waits_for_device_then_streams(self):
        run = FakeRun(devices="")
        relay, rec = make_engine(self, run=run)
        relay.start()
        rec.wait_for(lambda: (State.WAITING_DEVICE, msg("adb.no_device")) in rec.states)
        self.assertEqual(rec.states[0], (State.WAITING_DEVICE, msg("state.preparing_capture")))
        run.devices = "R52\tdevice"
        rec.wait_state(State.STREAMING)

    def test_waits_for_app_when_nothing_answers(self):
        connect = FakeConnect()
        connect.refuse = True
        relay, rec = make_engine(self, connect=connect)
        relay.start()
        rec.wait_state(State.WAITING_APP)
        self.assertEqual(rec.states[-1][1], msg("state.waiting_app"))

    def test_returns_to_waiting_when_tablet_leaves(self):
        connect, injectors, popen = FakeConnect(), FakeInjectors(), FakePopen(live)
        relay, rec = make_engine(self, connect=connect, injectors=injectors, popen=popen)
        relay.start()
        tablet = first_tablet(connect)
        tablet.next_message(protocol.CONFIG)
        connect.refuse = True
        tablet.leave()
        rec.wait_for(lambda: rec.last_state() is State.WAITING_APP)
        self.assertTrue(popen.procs[0].killed.is_set())
        self.assertTrue(injectors.created[0].closed)
        self.assertTrue(any(line.startswith("Tablet disconnected") for line in rec.logs))

    def test_auto_encoder_falls_back_to_amf(self):
        popen = FakePopen(live)
        relay, rec = make_engine(self, run=FakeRun(encoders_ok=("amf",)), popen=popen,
                                 config=engine.Config(encoder="auto"))
        relay.start()
        rec.wait_state(State.STREAMING)
        self.assertIn("h264_amf", popen.calls[0][0])
        self.assertIn("Encoder: AMF (NVENC unavailable)", rec.logs)

    def test_subprocesses_never_open_a_console(self):
        run, popen = FakeRun(), FakePopen(live)
        relay, rec = make_engine(self, run=run, popen=popen, config=engine.Config(encoder="auto"))
        relay.start()
        rec.wait_state(State.STREAMING)
        for cmd, kwargs in run.calls + popen.calls:
            self.assertEqual(kwargs.get("creationflags"), tools.NO_WINDOW, cmd)


class StopTest(unittest.TestCase):
    def test_stop_while_waiting(self):
        relay, rec = make_engine(self, run=FakeRun(devices=""))
        relay.start()
        rec.wait_state(State.WAITING_DEVICE)
        started = time.monotonic()
        relay.stop()
        self.assertLess(time.monotonic() - started, engine.STOP_TIMEOUT_S)
        self.assertFalse(relay.is_running())
        self.assertIs(rec.last_state(), State.STOPPED)

    def test_stop_while_streaming_releases_everything(self):
        connect, injectors, popen = FakeConnect(), FakeInjectors(), FakePopen(live)
        relay, rec = make_engine(self, connect=connect, injectors=injectors, popen=popen)
        relay.start()
        tablet = first_tablet(connect)
        tablet.next_message(protocol.CONFIG)
        started = time.monotonic()
        relay.stop()
        self.assertLess(time.monotonic() - started, engine.STOP_TIMEOUT_S)
        self.assertFalse(relay.is_running())
        self.assertTrue(popen.procs[0].killed.is_set())
        self.assertTrue(injectors.created[0].closed)
        self.assertEqual(rec.states[-1], (State.STOPPED, msg("state.stopped")))
        tablet.wait_closed()
        self.assertFalse(any(line.startswith("Tablet disconnected") for line in rec.logs))

    def test_stop_during_encoder_probe_skips_the_remaining_probes(self):
        run = BlockingProbeRun()
        relay, rec = make_engine(self, run=run, config=engine.Config(encoder="auto"))
        self.addCleanup(run.release.set)
        relay.start()
        self.assertTrue(run.probing.wait(5))
        releaser = threading.Timer(0.2, run.release.set)  # la sonde finit pendant que stop() attend
        releaser.start()
        self.addCleanup(releaser.join)
        started = time.monotonic()
        relay.stop()
        self.assertLess(time.monotonic() - started, engine.STOP_TIMEOUT_S)
        self.assertFalse(relay.is_running())
        self.assertEqual(len(run.calls), 1, run.calls)  # ni sonde AMF, ni sondage des écrans, ni adb
        self.assertIn("h264_nvenc", run.calls[0][0])
        self.assertIs(rec.last_state(), State.STOPPED)

    def test_stop_before_ffmpeg_starts_does_not_start_it(self):
        class StopOnConnect(Recorder):
            relay = None

            def on_log(self, line):
                super().on_log(line)
                if line.startswith("Tablet connected"):
                    self.relay.stop()  # depuis le thread du moteur : pose le drapeau sans attendre

        popen = FakePopen(live)
        relay, rec = make_engine(self, popen=popen, recorder=StopOnConnect())
        rec.relay = relay
        relay.start()
        self.assertTrue(relay.wait(5))
        self.assertEqual(popen.calls, [])
        self.assertNotIn(State.STREAMING, [s for s, _ in rec.states])
        self.assertIs(rec.last_state(), State.STOPPED)

    def test_can_start_again_after_stop(self):
        relay, rec = make_engine(self)
        relay.start()
        rec.wait_state(State.STREAMING)
        relay.stop()
        relay.start()
        rec.wait_for(lambda: sum(1 for s, _ in rec.states if s is State.STREAMING) >= 2)
        self.assertEqual(rec.logs.count("Encoder: AMF (forced)"), 2)  # l'instance relancée repart de zéro

    def test_start_twice_is_harmless(self):
        popen = FakePopen(live)
        relay, rec = make_engine(self, popen=popen)
        relay.start()
        relay.start()
        rec.wait_state(State.STREAMING)
        time.sleep(0.1)
        self.assertEqual(len(popen.calls), 1)


class FatalTest(unittest.TestCase):
    def assert_fatal(self, rec, relay, key):
        """Returns the error's Msg once the engine has ended in ERROR with that message key."""
        rec.wait_state(State.ERROR)
        detail = rec.states[-1][1]
        self.assertEqual(detail.key, key)
        self.assertTrue(relay.wait(2.0))
        self.assertIs(relay.state, State.ERROR)
        return detail

    def test_incompatible_protocol(self):
        relay, rec = make_engine(self, connect=FakeConnect(version=99))
        relay.start()
        detail = self.assert_fatal(rec, relay, "error.protocol_mismatch")
        self.assertEqual(detail, msg("error.protocol_mismatch", tablet=99, pc=protocol.VERSION))

    def test_no_screen_with_tablet_size(self):
        relay, rec = make_engine(self, run=FakeRun(outputs=((0, (1920, 1080)),)))
        relay.start()
        detail = self.assert_fatal(rec, relay, "error.no_matching_screen")
        self.assertEqual(detail.args["outputs"], engine.describe_outputs([(0, (1920, 1080))]))
        self.assertIn("--output 0 : 1920x1080", detail.text("fr"))
        self.assertIn("ou choisis un autre écran (réglage Écran dans l'appli, --output N en ligne de commande) :",
                      detail.text("fr"))

    def test_no_encoder(self):
        relay, rec = make_engine(self, run=FakeRun(encoders_ok=()), config=engine.Config(encoder="auto"))
        relay.start()
        self.assertEqual(self.assert_fatal(rec, relay, "error.no_encoder"), msg("error.no_encoder"))

    def test_ffmpeg_dying_three_times_without_video(self):
        popen = FakePopen(dead)
        relay, rec = make_engine(self, popen=popen)
        relay.start()
        self.assertEqual(self.assert_fatal(rec, relay, "error.ffmpeg_keeps_stopping"),
                         msg("error.ffmpeg_keeps_stopping", count=engine.MAX_FFMPEG_FAILURES, last="boom"))
        self.assertEqual(len(popen.calls), engine.MAX_FFMPEG_FAILURES)

    def test_session_with_video_resets_the_failure_count(self):
        popen = FakePopen(dead, video_then_dead, dead)
        relay, rec = make_engine(self, popen=popen)
        relay.start()
        self.assertEqual(self.assert_fatal(rec, relay, "error.ffmpeg_keeps_stopping").args["last"], "boom")
        self.assertEqual(len(popen.calls), 5)

    def test_unexpected_exception_becomes_an_error_state(self):
        def explode(cmd, **kwargs):
            raise RuntimeError("panne")

        relay, rec = make_engine(self, popen=explode)
        relay.start()
        detail = self.assert_fatal(rec, relay, "error.unexpected")
        self.assertEqual(detail, msg("error.unexpected", error="panne"))
        self.assertEqual(detail.text("fr"), "Erreur inattendue : panne")
        self.assertTrue(any("Traceback" in line for line in rec.logs))

    def test_unexpected_exception_in_a_session_cleans_up_before_the_error(self):
        class WaitFails(FakeFfmpeg):
            def wait(self, timeout=None):
                super().wait(timeout)
                if len(self.waits) == 1:
                    raise RuntimeError("wait en panne")
                return 0

        class CleanupRecorder(Recorder):
            waits_at_error = None

            def on_state(self, state, detail):
                if state is State.ERROR:
                    self.waits_at_error = list(popen.procs[0].waits)
                super().on_state(state, detail)

        connect, popen = FakeConnect(), FakePopen(lambda: WaitFails(SAMPLE))
        relay, rec = make_engine(self, connect=connect, popen=popen, recorder=CleanupRecorder())
        relay.start()
        tablet = first_tablet(connect)
        tablet.next_message(protocol.CONFIG)
        tablet.leave()
        self.assertEqual(self.assert_fatal(rec, relay, "error.unexpected"), msg("error.unexpected", error="wait en panne"))
        self.assertTrue(popen.procs[0].killed.is_set())
        # le filet de _run a tué puis attendu ffmpeg (1 s max) avant d'annoncer ERROR
        self.assertEqual(rec.waits_at_error[1:], [1])
        tablet.wait_closed()

    def test_same_error_is_reported_again_after_a_restart(self):
        relay, rec = make_engine(self, connect=FakeConnect(version=99))
        relay.start()
        self.assert_fatal(rec, relay, "error.protocol_mismatch")
        relay.start()
        rec.wait_for(lambda: sum(1 for s, _ in rec.states if s is State.ERROR) == 2)


class NoDisplayListener:
    """A listener without the optional on_display callback (the CLI's PrintListener has none)."""

    def __init__(self):
        self.rec = Recorder()

    def on_state(self, state, detail):
        self.rec.on_state(state, detail)

    def on_log(self, line):
        self.rec.on_log(line)

    def on_stats(self, stats):
        self.rec.on_stats(stats)


class DisplayTest(unittest.TestCase):
    """Extend mode with a virtual display: reader first, then PREPARING_DISPLAY, prepare, probe, ffmpeg."""

    EXTEND = engine.Config(encoder="amf", position="left", scale="150")

    def vdd_run(self):
        """ddagrab sees only the main screen until the virtual screen is prepared, then the VDD output as #1."""
        run = FakeRun(outputs=((0, (2560, 1600)),))
        return run, lambda: run.outputs.__setitem__(1, (2880, 1800))

    def streaming_engine(self, display, config=None, **kwargs):
        run, appear = self.vdd_run()
        if display.on_prepare is None:
            display.on_prepare = appear
        connect = kwargs.pop("connect", FakeConnect())
        relay, rec = make_engine(self, run=run, connect=connect, config=config or self.EXTEND, display=display,
                                 **kwargs)
        relay.start()
        tablet = first_tablet(connect)
        tablet.next_message(protocol.CONFIG)
        return relay, rec, connect, tablet

    def test_config_defaults(self):
        config = engine.Config()
        self.assertEqual((config.mode, config.position, config.scale), ("extend", "right", "auto"))

    def test_ping_is_answered_while_the_screen_is_prepared(self):
        run, appear = self.vdd_run()
        display = FakeDisplay(block=True, on_prepare=appear)
        connect, popen = FakeConnect(), FakePopen(live)
        relay, rec = make_engine(self, run=run, connect=connect, popen=popen, config=self.EXTEND, display=display)
        self.addCleanup(display.proceed.set)
        relay.start()
        tablet = first_tablet(connect)
        self.assertTrue(display.entered.wait(5))
        rec.wait_state(State.PREPARING_DISPLAY)
        tablet.send(ping_frame(424242))
        _type, _flags, payload = tablet.next_message(protocol.PONG)
        self.assertEqual(protocol._PONG.unpack(payload)[0], 424242)
        self.assertEqual(popen.calls, [])  # ffmpeg ne démarre qu'une fois l'écran prêt
        display.proceed.set()
        tablet.next_message(protocol.CONFIG)
        self.assertEqual(len(popen.calls), 1)
        self.assertEqual(output_index(popen.calls[0]), 1)

    def test_states_prepare_arguments_and_capture_of_the_virtual_screen(self):
        injectors = FakeInjectors()
        display = FakeDisplay()
        relay, rec, _connect, _tablet = self.streaming_engine(display, injectors=injectors)
        wait_until(lambda: injectors.created)
        states = [s for s, _ in rec.states]
        preparing = states.index(State.PREPARING_DISPLAY)
        self.assertLess(preparing, states.index(State.STREAMING))
        self.assertEqual(rec.states[preparing][1], msg("state.preparing_display"))
        self.assertEqual(rec.states[preparing][1].text("en"), "Preparing the screen…")
        self.assertEqual(rec.states[preparing][1].text("fr"), "Préparation de l'écran…")
        self.assertEqual(display.prepares(), [("prepare", 2880, 1800, 274, "left", "150", False)])
        self.assertEqual(injectors.rects, [VDD_RECT])  # le tactile vise l'écran virtuel, pas un écran de même taille
        self.assertIn("Captured screen: #1 (virtual screen 2880x1800)", rec.logs)
        self.assertEqual(display.releases(), [])

    def test_virtual_screen_output_when_the_main_screen_has_the_same_size(self):
        main, vdd = Rect(0, 0, 2880, 1800), Rect(2880, 0, 2880, 1800)
        for monitors, expected in (([(main, True, "D1"), (vdd, False, "D9")], 1),
                                   ([(vdd, False, "D9"), (main, True, "D1")], 0)):
            with self.subTest(monitors=monitors):
                popen, injectors = FakePopen(live), FakeInjectors()
                display = FakeDisplay(result=PrepareResult(vdd, True, (2880, 1800)))
                connect = FakeConnect()
                relay, rec = make_engine(self, run=FakeRun(outputs=((0, (2880, 1800)), (1, (2880, 1800)))),
                                         connect=connect, popen=popen, injectors=injectors, monitors=monitors,
                                         config=self.EXTEND, display=display)
                relay.start()
                first_tablet(connect).next_message(protocol.CONFIG)
                wait_until(lambda: injectors.created)
                self.assertEqual(output_index(popen.calls[0]), expected)
                self.assertEqual(injectors.rects, [vdd])
                relay.stop()

    def test_no_ddagrab_output_at_the_prepared_size_is_fatal(self):
        popen = FakePopen(live)
        display = FakeDisplay(on_prepare=lambda: None)
        relay, rec = make_engine(self, run=FakeRun(outputs=((0, (2560, 1600)),)), popen=popen, config=self.EXTEND,
                                 display=display)
        relay.start()
        rec.wait_state(State.ERROR)
        self.assertEqual(rec.states[-1][1], msg("display.not_capturable", width=2880, height=1800,
                                                 outputs=engine.describe_outputs([(0, (2560, 1600))])))
        self.assertTrue(relay.wait(2))
        self.assertEqual(popen.calls, [])
        self.assertEqual(display.releases(), [("release", False)])

    def test_prepare_error_stops_the_engine_with_its_message(self):
        popen = FakePopen(live)
        display = FakeDisplay(error=engine.FatalError(msg("display.timeout")))
        relay, rec = make_engine(self, popen=popen, config=self.EXTEND, display=display)
        relay.start()
        rec.wait_state(State.ERROR)
        self.assertEqual(rec.states[-1], (State.ERROR, msg("display.timeout")))
        self.assertTrue(relay.wait(2))
        self.assertIs(relay.state, State.ERROR)
        self.assertEqual(popen.calls, [])
        self.assertEqual(display.releases(), [("release", False)])  # l'écran a pu s'allumer : il s'éteindra

    def test_stop_during_prepare_ends_quietly(self):
        layout_applied = []
        popen, connect = FakePopen(live), FakeConnect()
        display = FakeDisplay(block=True)
        relay, rec = make_engine(self, popen=popen, connect=connect, config=self.EXTEND, display=display,
                                 first_time=lambda: True, on_layout_applied=lambda: layout_applied.append(1))
        relay.start()
        self.assertTrue(display.entered.wait(5))
        started = time.monotonic()
        relay.stop()
        self.assertLess(time.monotonic() - started, engine.STOP_TIMEOUT_S)
        self.assertFalse(relay.is_running())
        self.assertTrue(display.saw_stop.is_set())
        self.assertEqual(rec.states[-1], (State.STOPPED, msg("state.stopped")))
        self.assertNotIn(State.ERROR, [s for s, _ in rec.states])
        self.assertEqual(popen.calls, [])
        self.assertEqual(layout_applied, [])  # rien n'a été disposé
        self.assertEqual(display.releases(), [("release", False)])
        first_tablet(connect).wait_closed()

    def test_tablet_leaving_during_prepare_ends_the_session(self):
        popen, connect = FakePopen(live), FakeConnect()
        display = FakeDisplay(block=True)
        relay, rec = make_engine(self, popen=popen, connect=connect, config=self.EXTEND, display=display)
        relay.start()
        tablet = first_tablet(connect)
        self.assertTrue(display.entered.wait(5))
        connect.refuse = True
        tablet.leave()
        rec.wait_for(lambda: rec.last_state() is State.WAITING_APP)
        self.assertTrue(display.saw_stop.is_set())
        self.assertEqual(popen.calls, [])
        self.assertEqual(display.releases(), [("release", False)])
        self.assertTrue(relay.is_running())

    def test_release_with_grace_when_the_tablet_leaves(self):
        display = FakeDisplay()
        relay, rec, connect, tablet = self.streaming_engine(display)
        connect.refuse = True
        tablet.leave()
        rec.wait_for(lambda: rec.last_state() is State.WAITING_APP)
        self.assertEqual(display.releases(), [("release", False)])

    def test_normal_stop_releases_with_grace(self):
        display = FakeDisplay()
        relay, rec, _connect, _tablet = self.streaming_engine(display)
        relay.stop()
        self.assertFalse(relay.is_running())
        self.assertEqual(display.releases(), [("release", False)])

    def test_quit_releases_immediately(self):
        display = FakeDisplay()
        relay, rec, _connect, _tablet = self.streaming_engine(display)
        relay.stop(immediate_display_release=True)
        self.assertFalse(relay.is_running())
        self.assertEqual(display.releases(), [("release", True)])
        self.assertEqual(rec.states[-1], (State.STOPPED, msg("state.stopped")))

    def test_quit_during_the_grace_delay_releases_immediately(self):
        display = FakeDisplay()
        relay, rec, connect, tablet = self.streaming_engine(display)
        connect.refuse = True
        tablet.leave()
        rec.wait_for(lambda: rec.last_state() is State.WAITING_APP)
        relay.stop(immediate_display_release=True)
        self.assertEqual(display.releases(), [("release", False), ("release", True)])

    def test_restart_after_quit_uses_the_grace_again(self):
        display = FakeDisplay()
        relay, rec, connect, _tablet = self.streaming_engine(display)
        relay.stop(immediate_display_release=True)
        relay.start()
        wait_until(lambda: len(connect.tablets) == 2)
        connect.tablets[1].next_message(protocol.CONFIG)
        relay.stop()
        self.assertEqual(display.releases(), [("release", True), ("release", False)])

    def test_display_info_reports_an_exact_mode(self):
        display = FakeDisplay()
        relay, rec, _connect, _tablet = self.streaming_engine(display)
        rec.wait_for(lambda: rec.displays)
        self.assertEqual(rec.displays, [engine.DisplayInfo((2880, 1800), (2880, 1800), True, VDD_RECT)])

    def test_nearest_mode_is_logged_and_reported(self):
        smaller = Rect(2560, 0, 2560, 1600)
        display = FakeDisplay(result=PrepareResult(smaller, False, (2560, 1600)), on_prepare=lambda: None)
        connect, injectors = FakeConnect(), FakeInjectors()
        relay, rec = make_engine(self, run=FakeRun(outputs=((0, (2560, 1600)), (1, (2560, 1600)))),
                                 connect=connect, injectors=injectors, config=self.EXTEND, display=display,
                                 monitors=[(PRIMARY, True, "D1"), (smaller, False, "D9")])
        relay.start()
        first_tablet(connect).next_message(protocol.CONFIG)
        rec.wait_for(lambda: rec.displays)
        self.assertEqual(rec.displays, [engine.DisplayInfo((2880, 1800), (2560, 1600), False, smaller)])
        self.assertIn("Virtual screen: no 2880x1800 mode, nearest is 2560x1600 (black bars on the tablet)", rec.logs)
        wait_until(lambda: injectors.created)
        self.assertEqual(injectors.rects, [smaller])

    def test_listener_without_on_display_still_streams(self):
        listener = NoDisplayListener()
        display = FakeDisplay(result=PrepareResult(VDD_RECT, False, (2880, 1800)))
        relay, _rec, _connect, _tablet = self.streaming_engine(display, recorder=listener)
        listener.rec.wait_state(State.STREAMING)
        self.assertTrue(relay.is_running())

    def test_layout_is_applied_the_first_time_only(self):
        applied, asked = [], []

        def first_time():
            asked.append(1)
            return not applied

        display = FakeDisplay()
        relay, rec, connect, first = self.streaming_engine(display, first_time=first_time,
                                                           on_layout_applied=lambda: applied.append(1))
        first.leave()
        wait_until(lambda: len(connect.tablets) == 2)
        connect.tablets[1].next_message(protocol.CONFIG)
        self.assertEqual([call[6] for call in display.prepares()], [True, False])
        self.assertEqual(len(asked), 2)
        self.assertEqual(applied, [1])

    def test_duplicate_mode_captures_the_main_screen_without_the_virtual_display(self):
        left = Rect(-1920, 0, 1920, 1080)
        popen, injectors, display, connect = FakePopen(live), FakeInjectors(), FakeDisplay(), FakeConnect()
        relay, rec = make_engine(self, run=FakeRun(outputs=((0, (1920, 1080)), (1, (2560, 1600)))), popen=popen,
                                 injectors=injectors, connect=connect, monitors=[(left, False, "D2"), (PRIMARY, True, "D1")],
                                 config=engine.Config(encoder="amf", mode="duplicate"), display=display)
        relay.start()
        tablet = first_tablet(connect)
        tablet.next_message(protocol.CONFIG)
        wait_until(lambda: injectors.created)
        self.assertEqual(output_index(popen.calls[0]), 1)
        self.assertEqual(injectors.rects, [PRIMARY])
        self.assertIn("Captured screen: #1 (main screen 2560x1600)", rec.logs)
        self.assertNotIn(State.PREPARING_DISPLAY, [s for s, _ in rec.states])
        connect.refuse = True
        tablet.leave()
        rec.wait_for(lambda: rec.last_state() is State.WAITING_APP)
        relay.stop(immediate_display_release=True)
        self.assertEqual(display.calls, [])

    def test_duplicate_mode_falls_back_to_output_0(self):
        popen, injectors = FakePopen(live), FakeInjectors()
        relay, rec = make_engine(self, run=FakeRun(outputs=((0, (1920, 1080)),)), popen=popen, injectors=injectors,
                                 monitors=[(PRIMARY, True, "D1")], config=engine.Config(encoder="amf", mode="duplicate"))
        relay.start()
        wait_until(lambda: injectors.created)
        self.assertEqual(output_index(popen.calls[0]), 0)
        self.assertEqual(injectors.rects, [None])  # écran principal non reconnu : le tactile cherche par la taille

    def test_duplicate_mode_keeps_an_explicit_output(self):
        popen = FakePopen(live)
        relay, rec = make_engine(self, popen=popen, config=engine.Config(encoder="amf", mode="duplicate", output="3"))
        relay.start()
        rec.wait_state(State.STREAMING)
        self.assertEqual(output_index(popen.calls[0]), 3)


if __name__ == "__main__":
    unittest.main()
