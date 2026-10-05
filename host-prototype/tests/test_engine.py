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

    def __call__(self, width, height, log):
        injector = FakeInjector(width, height, self.error)
        self.created.append(injector)
        return injector


class Recorder:
    def __init__(self):
        self.states = []
        self.logs = []
        self.stats = []
        self._cond = threading.Condition()

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
                recorder=None):
    recorder = recorder or Recorder()
    deps = engine.Deps(
        run=run or FakeRun(),
        popen=popen or FakePopen(live),
        create_connection=connect or FakeConnect(),
        create_injector=injectors or FakeInjectors(),
        poll_s=0.01,
        retry_delay_s=0.0,
    )
    relay = engine.RelayEngine(config, recorder, ffmpeg="ffmpeg.exe", adb="adb.exe", deps=deps)
    test.addCleanup(relay.stop)
    return relay, recorder


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
        self.assertIn("Tablette connectée : écran 2880x1800, 274 dpi", rec.logs)
        self.assertIn("Écran capturé : n° 0 (2880x1800, choisi automatiquement)", rec.logs)

    def test_first_state_is_shown_before_the_probes(self):
        run = BlockingProbeRun()
        relay, rec = make_engine(self, run=run, config=engine.Config(encoder="auto"))
        self.addCleanup(run.release.set)  # avant le stop() du nettoyage (ordre inverse)
        relay.start()
        self.assertTrue(run.probing.wait(5))
        self.assertEqual(rec.states, [(State.WAITING_DEVICE, "Préparation de la capture…")])

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
        failures = [line for line in rec.logs if line.startswith("Tactile en échec")]
        self.assertEqual(failures, ["Tactile en échec, entrées ignorées : pilote absent"])
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
        self.assertEqual(rec.states[-1], (State.WAITING_APP, engine.WAITING_APP_DETAIL))
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
        rec.wait_for(lambda: any("Aucune tablette détectée" in detail for _, detail in rec.states))
        self.assertEqual(rec.states[0], (State.WAITING_DEVICE, "Préparation de la capture…"))
        run.devices = "R52\tdevice"
        rec.wait_state(State.STREAMING)

    def test_waits_for_app_when_nothing_answers(self):
        connect = FakeConnect()
        connect.refuse = True
        relay, rec = make_engine(self, connect=connect)
        relay.start()
        rec.wait_state(State.WAITING_APP)
        self.assertEqual(rec.states[-1][1], engine.WAITING_APP_DETAIL)

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
        self.assertTrue(any(line.startswith("Tablette déconnectée") for line in rec.logs))

    def test_auto_encoder_falls_back_to_amf(self):
        popen = FakePopen(live)
        relay, rec = make_engine(self, run=FakeRun(encoders_ok=("amf",)), popen=popen,
                                 config=engine.Config(encoder="auto"))
        relay.start()
        rec.wait_state(State.STREAMING)
        self.assertIn("h264_amf", popen.calls[0][0])
        self.assertIn("Encodeur : AMF (NVENC indisponible)", rec.logs)

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
        self.assertIs(rec.last_state(), State.STOPPED)
        tablet.wait_closed()
        self.assertFalse(any(line.startswith("Tablette déconnectée") for line in rec.logs))

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
                if line.startswith("Tablette connectée"):
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
        self.assertEqual(rec.logs.count("Encodeur : AMF (forcé)"), 2)  # l'instance relancée repart de zéro

    def test_start_twice_is_harmless(self):
        popen = FakePopen(live)
        relay, rec = make_engine(self, popen=popen)
        relay.start()
        relay.start()
        rec.wait_state(State.STREAMING)
        time.sleep(0.1)
        self.assertEqual(len(popen.calls), 1)


class FatalTest(unittest.TestCase):
    def assert_fatal(self, rec, relay, text):
        rec.wait_state(State.ERROR)
        self.assertIn(text, rec.states[-1][1])
        self.assertTrue(relay.wait(2.0))
        self.assertIs(relay.state, State.ERROR)

    def test_incompatible_protocol(self):
        relay, rec = make_engine(self, connect=FakeConnect(version=99))
        relay.start()
        self.assert_fatal(rec, relay, "Protocole incompatible")

    def test_no_screen_with_tablet_size(self):
        relay, rec = make_engine(self, run=FakeRun(outputs=((0, (1920, 1080)),)))
        relay.start()
        self.assert_fatal(rec, relay, "--output 0 : 1920x1080")
        self.assertIn("ou choisis un autre écran (réglage Écran dans l'appli, --output N en ligne de commande) :",
                      rec.states[-1][1])

    def test_no_encoder(self):
        relay, rec = make_engine(self, run=FakeRun(encoders_ok=()), config=engine.Config(encoder="auto"))
        relay.start()
        self.assert_fatal(rec, relay, "Aucun encodeur matériel H.264")

    def test_ffmpeg_dying_three_times_without_video(self):
        popen = FakePopen(dead)
        relay, rec = make_engine(self, popen=popen)
        relay.start()
        self.assert_fatal(rec, relay, "boom")
        self.assertEqual(len(popen.calls), engine.MAX_FFMPEG_FAILURES)

    def test_session_with_video_resets_the_failure_count(self):
        popen = FakePopen(dead, video_then_dead, dead)
        relay, rec = make_engine(self, popen=popen)
        relay.start()
        self.assert_fatal(rec, relay, "boom")
        self.assertEqual(len(popen.calls), 5)

    def test_unexpected_exception_becomes_an_error_state(self):
        def explode(cmd, **kwargs):
            raise RuntimeError("panne")

        relay, rec = make_engine(self, popen=explode)
        relay.start()
        self.assert_fatal(rec, relay, "Erreur inattendue : panne")
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
        self.assert_fatal(rec, relay, "Erreur inattendue : wait en panne")
        self.assertTrue(popen.procs[0].killed.is_set())
        # le filet de _run a tué puis attendu ffmpeg (1 s max) avant d'annoncer ERROR
        self.assertEqual(rec.waits_at_error[1:], [1])
        tablet.wait_closed()

    def test_same_error_is_reported_again_after_a_restart(self):
        relay, rec = make_engine(self, connect=FakeConnect(version=99))
        relay.start()
        self.assert_fatal(rec, relay, "Protocole incompatible")
        relay.start()
        rec.wait_for(lambda: sum(1 for s, _ in rec.states if s is State.ERROR) == 2)


if __name__ == "__main__":
    unittest.main()
