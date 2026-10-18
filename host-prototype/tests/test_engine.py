import hashlib
import json
import os
import queue
import re
import socket
import subprocess
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

import dxgi_outputs
import engine
import protocol
from frame.session import FrameConfig
import tools
from inputstate import Rect
from messages import msg
from virtual_display import PrepareResult

CODECS = {"nvenc": "h264_nvenc", "amf": "h264_amf", "qsv": "h264_qsv", "x264": "libx264"}
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


def device_info_frame(role="actions", kind="phone", name="Pixel 8", app="1.0", video=None, lang=None):
    fields = {"role": role, "kind": kind, "name": name, "app": app}
    if video is not None:
        fields["video"] = video
    if lang is not None:
        fields["lang"] = lang
    payload = json.dumps(fields).encode()
    return protocol._frame(protocol.DEVICE_INFO, 0, payload)


def action_frame(**fields):
    return protocol._frame(protocol.ACTION, 0, json.dumps(fields).encode())


def keyframe_request_frame():
    return protocol._frame(protocol.KEYFRAME_REQ, 0, b"")


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
            name = next(n for n, codec in CODECS.items() if codec in joined)
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
    """The tablet end of a socket pair: sends HELLO at once (then `after_hello`, e.g. a DEVICE_INFO frame) and
    records every frame the PC sends."""

    def __init__(self, version=protocol.VERSION, after_hello=b""):
        self.pc, self.tab = socket.socketpair()
        self.frames = queue.Queue()
        self.tab.sendall(hello_frame(version) + after_hello)
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
    after_hello: bytes each new tablet sends right after its HELLO (a DEVICE_INFO frame, for instance).
    """

    def __init__(self, version=protocol.VERSION, after_hello=b""):
        self.version = version
        self.after_hello = after_hello
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
        tablet = FakeTablet(self.version, self.after_hello)
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


class FakeHub:
    """actions.hub.ActionsHub stand-in: records start/stop and the actions; the test calls `send` itself."""

    def __init__(self, send, log, handle_error=None, send_artwork=None, lang="fr"):
        self.lang = lang
        self.send = send
        self.send_artwork = send_artwork
        self.log = log
        self.handle_error = handle_error
        self.handled = []
        self.started = threading.Event()
        self.stopped = threading.Event()

    def start(self):
        self.started.set()

    def stop(self):
        self.stopped.set()

    def handle(self, action):
        self.handled.append(action)
        if self.handle_error is not None:
            raise self.handle_error


class FakeHubs:
    """Deps.actions_hub_factory stand-in: one FakeHub per Actions session."""

    def __init__(self, handle_error=None):
        self.handle_error = handle_error
        self.created = []

    def __call__(self, send, log, send_artwork=None, lang="fr"):
        hub = FakeHub(send, log, self.handle_error, send_artwork, lang)
        self.created.append(hub)
        return hub

    def first(self, timeout=5.0):
        wait_until(lambda: self.created, timeout)
        return self.created[0]


class FakeFrameSession:
    """frame.session.FrameSession stand-in: records start/stop, the frame.* actions and the configs it is given."""

    def __init__(self, args, handle_error=None):
        (self.send_state, self.send_file_chunk, self.log, self.config, self.screen, self.ffmpeg,
         self.listener) = args
        self.handle_error = handle_error
        self.handled = []
        self.configs = []
        self.started = threading.Event()
        self.stopped = threading.Event()

    def start(self):
        self.started.set()

    def stop(self):
        self.stopped.set()

    def handle(self, action):
        self.handled.append(action)
        if self.handle_error is not None:
            raise self.handle_error

    def set_config(self, folder, interval_s, fit):
        self.configs.append((folder, interval_s, fit))


class FakeFrameSessions:
    """Deps.frame_session_factory stand-in: one FakeFrameSession per Frame session."""

    def __init__(self, handle_error=None):
        self.handle_error = handle_error
        self.created = []

    def __call__(self, *args):
        session = FakeFrameSession(args, self.handle_error)
        self.created.append(session)
        return session

    def first(self, timeout=5.0):
        wait_until(lambda: self.created, timeout)
        return self.created[0]


PRIMARY = Rect(0, 0, 2560, 1600)
VDD_RECT = Rect(2560, 0, 2880, 1800)


class FakeDisplay:
    """virtual_display.VirtualDisplay stand-in. block=True: prepare() waits for `proceed` (or should_stop)."""

    def __init__(self, result=None, error=None, block=False, on_prepare=None):
        self.result = result or PrepareResult(VDD_RECT, True, (2880, 1800))
        self.layout_result = VDD_RECT  # où apply_layout dit que l'écran se trouve ensuite (exception : levée)
        self.layout_flags = []  # move / rescale de chaque apply_layout
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

    def apply_layout(self, position, scale, dpi, move=True, rescale=True):
        self.calls.append(("apply_layout", position, scale, dpi))
        self.layout_flags.append({"move": move, "rescale": rescale})
        if isinstance(self.layout_result, Exception):
            raise self.layout_result
        return self.layout_result

    def layouts(self):
        return [c for c in self.calls if c[0] == "apply_layout"]

    def releases(self):
        return [c for c in self.calls if c[0] == "release"]

    def prepares(self):
        return [c for c in self.calls if c[0] == "prepare"]


class GatedLayoutDisplay(FakeDisplay):
    """The first apply_layout blocks (Windows moving the screen) until the test opens `gate`."""

    def __init__(self):
        super().__init__()
        self.applying = threading.Event()
        self.gate = threading.Event()

    def apply_layout(self, position, scale, dpi, move=True, rescale=True):
        result = super().apply_layout(position, scale, dpi, move=move, rescale=rescale)
        if len(self.layouts()) == 1:
            self.applying.set()
            self.gate.wait(5)
        return result


class StuckPrepareDisplay(FakeDisplay):
    """prepare() is inside a Windows call: it ignores should_stop until the test sets `proceed`."""

    def prepare(self, width, height, dpi, position, scale, first_time, should_stop):
        self.calls.append(("prepare", width, height, dpi, position, scale, first_time))
        self.entered.set()
        self.proceed.wait(5)
        self.calls.append(("screen on",))
        return self.result


class WaitCountingLock:
    """threading.Lock that counts the threads that had to wait for it (tests see them queued)."""

    def __init__(self):
        self._lock = threading.Lock()
        self._cond = threading.Condition()
        self.waiting = 0

    def acquire(self, blocking=True, timeout=-1):
        if self._lock.acquire(blocking=False):
            return True
        with self._cond:
            self.waiting += 1
            self._cond.notify_all()
        return self._lock.acquire(blocking, timeout)

    def release(self):
        self._lock.release()

    __enter__ = acquire

    def __exit__(self, *exc):
        self.release()
        return False

    def wait_for_waiters(self, count, timeout=5.0):
        with self._cond:
            return self._cond.wait_for(lambda: self.waiting >= count, timeout)


class Recorder:
    def __init__(self):
        self.states = []
        self.logs = []
        self.stats = []
        self.displays = []
        self.frame_settings = []
        self._cond = threading.Condition()

    def on_display(self, info):
        with self._cond:
            self.displays.append(info)
            self._cond.notify_all()

    def on_frame_settings(self, interval_s, fit, paused):
        with self._cond:
            self.frame_settings.append((interval_s, fit, paused))
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


def no_dxgi():
    raise dxgi_outputs.DxgiError("CreateDXGIFactory1", 0x887A0004)


def dxgi_list(*names, adapter=0):
    """DXGI stand-in listing these GDI names as outputs 0, 1, … of one adapter."""
    return [dxgi_outputs.Output(adapter, f"GPU {adapter}", i, name, Rect(0, 0, 1, 1), True)
            for i, name in enumerate(names)]


def make_engine(test, run=None, popen=None, connect=None, injectors=None, config=engine.Config(encoder="amf"),
                recorder=None, monitors=None, dxgi=no_dxgi, retry_delay_s=0.0, hubs=None,
                device_info_timeout_s=0.05, frames=None, **engine_args):
    """engine_args: display, first_time, on_layout_applied (RelayEngine keywords).

    dxgi: Deps.list_outputs; the default fails, so the screen is found by probing ddagrab (FakeRun.outputs).
    hubs: Deps.actions_hub_factory (a FakeHubs by default: no test ever builds the real providers).
    frames: Deps.frame_session_factory (a FakeFrameSessions by default: no test builds the real session).
    device_info_timeout_s: short by default, so that sessions without DEVICE_INFO (screen role) start quickly.
    """
    recorder = recorder or Recorder()
    listed = [(PRIMARY, True, r"\\.\DISPLAY1"), (VDD_RECT, False, r"\\.\DISPLAY9")] if monitors is None else monitors
    deps = engine.Deps(
        run=run or FakeRun(),
        popen=popen or FakePopen(live),
        create_connection=connect or FakeConnect(),
        create_injector=injectors or FakeInjectors(),
        monitors=lambda: list(listed),
        list_outputs=dxgi,
        poll_s=0.01,
        retry_delay_s=retry_delay_s,
        actions_hub_factory=hubs or FakeHubs(),
        frame_session_factory=frames or FakeFrameSessions(),
        device_info_timeout_s=device_info_timeout_s,
    )
    relay = engine.RelayEngine(config, recorder, ffmpeg="ffmpeg.exe", adb="adb.exe", deps=deps, **engine_args)
    test.addCleanup(relay.stop)
    return relay, recorder


def ddagrab_probes(run):
    """The one-frame ddagrab runs of probe_outputs (not the capture, which goes through popen)."""
    return [cmd for cmd, _kwargs in run.calls if "-frames:v" in cmd and any("ddagrab" in str(c) for c in cmd)]


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

    def test_tablet_leaving_is_logged_once_even_when_the_video_send_notices_it_first(self):
        stdout = FedStdout()

        def fed():
            ffmpeg = FakeFfmpeg()
            ffmpeg.stdout = stdout
            return ffmpeg

        connect = FakeConnect()
        relay, rec = make_engine(self, connect=connect, popen=FakePopen(fed))
        relay.start()
        stdout.feed(SAMPLE)
        tablet = first_tablet(connect)
        tablet.next_message(protocol.CONFIG)
        connect.refuse = True
        tablet.leave()
        for _ in range(20):  # de la vidéo pendant le départ : l'envoi échoue, peut-être avant que le lecteur le voie
            stdout.feed(SAMPLE)
        rec.wait_for(lambda: rec.last_state() is State.WAITING_APP)
        self.assertEqual(len([line for line in rec.logs if line.startswith("Tablet disconnected")]), 1)

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

    def test_subprocesses_never_run_in_the_app_folder(self):
        """adb's server inherits its cwd and would keep the app folder locked (rename, update, uninstall)."""
        import tempfile
        run, popen = FakeRun(), FakePopen(live)
        relay, rec = make_engine(self, run=run, popen=popen, config=engine.Config(encoder="auto"))
        relay.start()
        rec.wait_state(State.STREAMING)
        self.assertTrue(any(cmd[1:] == ["devices"] for cmd, _ in run.calls))
        self.assertTrue(any(cmd[1] == "forward" for cmd, _ in run.calls))
        self.assertTrue(popen.calls)
        for cmd, kwargs in run.calls + popen.calls:
            self.assertEqual(kwargs.get("cwd"), tempfile.gettempdir(), cmd)  # bare tool names -> temp folder
            self.assertNotEqual(os.path.realpath(kwargs["cwd"]), os.path.realpath(tools.app_dir()), cmd)


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
        popen, connect = FakePopen(dead), FakeConnect()
        relay, rec = make_engine(self, popen=popen, connect=connect)
        relay.start()
        self.assertEqual(self.assert_fatal(rec, relay, "error.ffmpeg_keeps_stopping"),
                         msg("error.ffmpeg_keeps_stopping", count=engine.MAX_FFMPEG_FAILURES, last="boom"))
        self.assertEqual(len(popen.calls), engine.MAX_FFMPEG_FAILURES)
        self.assertEqual(len(connect.tablets), 1)  # relancé dans la session, sans reconnecter la tablette
        connect.tablets[0].wait_closed()

    def test_session_with_video_resets_the_failure_count(self):
        popen, connect = FakePopen(dead, video_then_dead, dead), FakeConnect()
        relay, rec = make_engine(self, popen=popen, connect=connect)
        relay.start()
        self.assertEqual(self.assert_fatal(rec, relay, "error.ffmpeg_keeps_stopping").args["last"], "boom")
        self.assertEqual(len(popen.calls), 5)
        self.assertEqual(len(connect.tablets), 1)

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
                                 first_time=lambda: True,
                                 on_layout_applied=lambda *layout: layout_applied.append(layout))
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
                                                           on_layout_applied=lambda *layout: applied.append(layout))
        first.leave()
        wait_until(lambda: len(connect.tablets) == 2)
        connect.tablets[1].next_message(protocol.CONFIG)
        self.assertEqual([call[6] for call in display.prepares()], [True, False])
        self.assertEqual(len(asked), 2)
        self.assertEqual(applied, [("left", "150")])  # la paire appliquée, gardée par l'appli
        self.assertEqual(display.layouts(), [])

    def test_relayout_while_streaming_moves_the_screen_touch_follows_and_the_capture_restarts(self):
        moved = Rect(-160, 1600, 2880, 1800)
        applied = []
        display = FakeDisplay()
        display.layout_result = moved
        popen, injectors = FakePopen(live), FakeInjectors()
        relay, rec, connect, tablet = self.streaming_engine(display, popen=popen, injectors=injectors,
                                                            on_layout_applied=lambda *layout: applied.append(layout),
                                                            retry_delay_s=30)
        wait_until(lambda: injectors.created)
        self.assertTrue(relay.relayout("below", "200"))
        self.assertEqual(display.layouts(), [("apply_layout", "below", "200", 274)])
        self.assertEqual(display.layout_flags, [{"move": True, "rescale": True}])
        self.assertEqual(injectors.rects[:2], [VDD_RECT, moved])
        self.assertTrue(injectors.created[0].closed)  # contacts levés à l'ancien emplacement
        self.assertEqual(applied, [("below", "200")])
        # Déplacer l'écran coupe ddagrab (DXGI_ERROR_ACCESS_LOST) : la capture est relancée tout de suite,
        # sur la même connexion.
        tablet.next_message(protocol.CONFIG)
        self.assertEqual(len(popen.calls), 2)
        self.assertTrue(popen.procs[0].killed.is_set())
        self.assertEqual(output_index(popen.calls[1]), 1)
        self.assertEqual(len(connect.tablets), 1)
        self.assertIn("Restarting the capture (screen moved)", rec.logs)
        wait_until(lambda: len(injectors.created) == 3)
        self.assertEqual(injectors.rects, [VDD_RECT, moved, moved])
        tablet.send(touch_frame((0, 1, 100, 100, 0, 0, 0)))
        wait_until(lambda: injectors.created[2].handled)
        self.assertEqual(injectors.created[0].handled, [])
        self.assertEqual(len(display.prepares()), 1)
        self.assertEqual(display.releases(), [])
        self.assertIs(rec.last_state(), State.STREAMING)

    def test_relayout_during_prepare_is_not_applied_then_works_once_streaming(self):
        moved = Rect(0, -1800, 2880, 1800)
        display = FakeDisplay(block=True)
        display.layout_result = moved
        run, appear = self.vdd_run()
        display.on_prepare = appear
        injectors, connect = FakeInjectors(), FakeConnect()
        relay, rec = make_engine(self, run=run, injectors=injectors, connect=connect, config=self.EXTEND,
                                 display=display)
        relay.start()
        self.assertTrue(display.entered.wait(5))
        self.assertFalse(relay.relayout("above", "auto"))  # écran en préparation : rien à déplacer encore
        self.assertEqual(display.layouts(), [])
        display.proceed.set()
        first_tablet(connect).next_message(protocol.CONFIG)
        wait_until(lambda: injectors.created)
        self.assertTrue(relay.relayout("above", "auto"))
        self.assertEqual(injectors.rects[-1], moved)

    def test_relayout_without_a_session_is_kept_for_the_next_first_time_layout(self):
        display = FakeDisplay()
        run, appear = self.vdd_run()
        display.on_prepare = appear
        connect = FakeConnect()
        relay, rec = make_engine(self, run=run, connect=connect, config=self.EXTEND, display=display,
                                 first_time=lambda: True)
        self.assertFalse(relay.relayout("above", "125"))
        relay.start()
        first_tablet(connect).next_message(protocol.CONFIG)
        self.assertEqual(display.prepares(), [("prepare", 2880, 1800, 274, "above", "125", True)])
        self.assertEqual(display.layouts(), [])

    def test_relayout_after_the_tablet_left_does_nothing(self):
        display, injectors = FakeDisplay(), FakeInjectors()
        relay, rec, connect, tablet = self.streaming_engine(display, injectors=injectors)
        wait_until(lambda: injectors.created)
        connect.refuse = True
        tablet.leave()
        rec.wait_for(lambda: rec.last_state() is State.WAITING_APP)
        self.assertFalse(relay.relayout("left", "auto"))
        self.assertEqual(display.layouts(), [])
        self.assertEqual(len(injectors.created), 1)

    def test_relayout_in_duplicate_mode_does_nothing(self):
        display, connect, injectors = FakeDisplay(), FakeConnect(), FakeInjectors()
        relay, rec = make_engine(self, connect=connect, injectors=injectors, display=display,
                                 config=engine.Config(encoder="amf", mode="duplicate"))
        relay.start()
        first_tablet(connect).next_message(protocol.CONFIG)
        wait_until(lambda: injectors.created)
        self.assertFalse(relay.relayout("left", "auto"))
        self.assertEqual(display.calls, [])

    def test_quick_relayouts_are_coalesced_and_end_on_the_latest_values(self):
        display, injectors = GatedLayoutDisplay(), FakeInjectors()
        applied = []
        relay, rec, _connect, _tablet = self.streaming_engine(
            display, injectors=injectors, on_layout_applied=lambda *layout: applied.append(layout))
        wait_until(lambda: injectors.created)
        queue_lock = WaitCountingLock()
        relay._relayout_lock = queue_lock
        threads = [threading.Thread(target=relay.relayout, args=("below", "200"))]
        threads[0].start()
        self.assertTrue(display.applying.wait(5))  # Windows déplace l'écran pour le 1er changement
        for count, args in enumerate((("above", "125"), ("right", "175")), start=1):
            thread = threading.Thread(target=relay.relayout, args=args)
            thread.start()
            threads.append(thread)
            self.assertTrue(queue_lock.wait_for_waiters(count))  # en file derrière le 1er
        display.gate.set()
        for thread in threads:
            thread.join(5)
        # Le changement intermédiaire n'est jamais appliqué ; le dernier l'est une seule fois.
        self.assertEqual(display.layouts(), [("apply_layout", "below", "200", 274),
                                             ("apply_layout", "right", "175", 274)])
        self.assertEqual(applied, [("below", "200"), ("right", "175")])
        self.assertTrue(relay.relayout("right", "175"))  # déjà là : rien de plus
        self.assertEqual(len(display.layouts()), 2)

    def test_layout_changed_while_preparing_is_applied_once_the_screen_is_on(self):
        for first_time in (True, False):
            with self.subTest(first_time=first_time):
                moved = Rect(0, -1800, 2880, 1800)
                display = FakeDisplay(block=True)
                display.layout_result = moved
                run, appear = self.vdd_run()
                display.on_prepare = appear
                injectors, connect, applied = FakeInjectors(), FakeConnect(), []
                relay, rec = make_engine(self, run=run, injectors=injectors, connect=connect, config=self.EXTEND,
                                         display=display, first_time=lambda: first_time,
                                         on_layout_applied=lambda *layout: applied.append(layout))
                relay.start()
                self.assertTrue(display.entered.wait(5))
                self.assertFalse(relay.relayout("above", "150"))  # pas encore d'écran à déplacer
                display.proceed.set()
                first_tablet(connect).next_message(protocol.CONFIG)
                wait_until(lambda: injectors.created)
                self.assertEqual(display.prepares(), [("prepare", 2880, 1800, 274, "left", "150", first_time)])
                self.assertEqual(display.layouts(), [("apply_layout", "above", "150", 274)])
                self.assertEqual(display.layout_flags, [{"move": True, "rescale": False}])
                self.assertEqual(applied, ([("left", "150")] if first_time else []) + [("above", "150")])
                self.assertEqual(injectors.rects, [moved])  # le tactile vise directement le nouvel emplacement
                relay.stop()

    def test_scale_only_relayout_keeps_the_position_the_touch_contacts_and_the_capture(self):
        display, injectors, popen = FakeDisplay(), FakeInjectors(), FakePopen(live)
        relay, rec, _connect, _tablet = self.streaming_engine(display, injectors=injectors, popen=popen)
        wait_until(lambda: injectors.created)
        self.assertTrue(relay.relayout("left", "200"))  # même côté : seule l'échelle change
        self.assertEqual(display.layout_flags, [{"move": False, "rescale": True}])
        self.assertEqual(len(injectors.created), 1)  # même rectangle : pas de nouvel injecteur
        self.assertFalse(injectors.created[0].closed)  # aucun contact levé
        self.assertEqual(len(popen.calls), 1)  # l'écran n'a pas bougé : la capture continue
        self.assertFalse(popen.procs[0].killed.is_set())

    def test_layout_not_applied_is_not_saved(self):
        for result in (None, OSError("SetDisplayConfig failed")):
            with self.subTest(result=result):
                display, injectors, applied = FakeDisplay(), FakeInjectors(), []
                display.layout_result = result
                relay, rec, _connect, _tablet = self.streaming_engine(
                    display, injectors=injectors, on_layout_applied=lambda *layout: applied.append(layout))
                wait_until(lambda: injectors.created)
                self.assertFalse(relay.relayout("below", "200"))
                self.assertEqual(applied, [])
                self.assertEqual(len(injectors.created), 1)
                display.layout_result = VDD_RECT  # nouvel essai des mêmes valeurs : réappliquées
                self.assertTrue(relay.relayout("below", "200"))
                self.assertEqual(applied, [("below", "200")])
                relay.stop()

    def test_quit_while_prepare_is_stuck_turns_the_screen_off_when_it_ends(self):
        display = StuckPrepareDisplay(block=True)
        relay, rec = make_engine(self, config=self.EXTEND, display=display)
        self.addCleanup(display.proceed.set)
        relay.start()
        self.assertTrue(display.entered.wait(5))
        with mock.patch.object(engine, "STOP_TIMEOUT_S", 0.05):
            relay.stop(immediate_display_release=True)  # n'attend pas la fin de l'appel Windows
        self.assertTrue(relay.is_running())
        self.assertEqual(display.releases(), [("release", True)])
        display.proceed.set()  # l'appel finit et l'écran s'allume après l'extinction de Quit
        self.assertTrue(relay.wait(5))
        self.assertEqual(display.calls[-2:], [("screen on",), ("release", True)])

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


def fed_ffmpeg(stdout, stderr_lines=()):
    """A factory for a capture whose output the test feeds (feed(b"") = ffmpeg exits on its own)."""
    def factory():
        ffmpeg = FakeFfmpeg(stderr_lines=stderr_lines)
        ffmpeg.stdout = stdout
        return ffmpeg
    return factory


class CaptureRestartTest(unittest.TestCase):
    """ffmpeg exiting on its own while the tablet stays: a new capture in the same session, no reconnection."""

    EXTEND = DisplayTest.EXTEND

    def test_ffmpeg_dying_mid_session_restarts_the_capture_on_the_same_connection(self):
        connect, popen, injectors = FakeConnect(), FakePopen(video_then_dead, live), FakeInjectors()
        relay, rec = make_engine(self, connect=connect, popen=popen, injectors=injectors, retry_delay_s=30)
        relay.start()
        tablet = first_tablet(connect)
        tablet.next_message(protocol.CONFIG)
        tablet.next_message(protocol.CONFIG)  # 2e capture, sans le délai de reconnexion (30 s ici)
        self.assertEqual(len(popen.calls), 2)
        self.assertEqual(output_index(popen.calls[1]), 0)
        self.assertTrue(popen.procs[0].killed.is_set())
        self.assertEqual(len(connect.tablets), 1)  # une seule connexion : la tablette n'a envoyé qu'un HELLO
        tablet.send(ping_frame(77))  # le même socket est toujours ouvert et servi
        _type, _flags, payload = tablet.next_message(protocol.PONG)
        self.assertEqual(protocol._PONG.unpack(payload)[0], 77)
        self.assertIn("ffmpeg stopped on its own. Last lines:\n  fin", rec.logs)
        self.assertIn("Restarting the capture (ffmpeg stopped on its own)", rec.logs)
        self.assertNotIn("Trying to connect again…", rec.logs)
        self.assertFalse(any(line.startswith("Tablet disconnected") for line in rec.logs))
        self.assertIs(rec.last_state(), State.STREAMING)
        self.assertNotIn(State.WAITING_APP, [s for s, _ in rec.states])
        wait_until(lambda: len(injectors.created) == 2)
        self.assertTrue(injectors.created[0].closed)

    def test_restart_finds_the_virtual_screen_output_again(self):
        stdout = FedStdout()
        names = [r"\\.\DISPLAY1", r"\\.\DISPLAY9"]
        run, connect = FakeRun(outputs=((0, (2560, 1600)),)), FakeConnect()  # sonder ne trouverait pas l'écran
        popen = FakePopen(fed_ffmpeg(stdout, ["AcquireNextFrame failed: 887a0026"]), live)
        display = FakeDisplay(on_prepare=lambda: None)
        relay, rec = make_engine(self, run=run, popen=popen, connect=connect, config=self.EXTEND, display=display,
                                 dxgi=lambda: dxgi_list(*names))
        relay.start()
        stdout.feed(SAMPLE)
        tablet = first_tablet(connect)
        tablet.next_message(protocol.CONFIG)
        self.assertEqual(output_index(popen.calls[0]), 1)
        names.insert(1, r"\\.\DISPLAY5")  # l'écran virtuel est maintenant la sortie #2
        stdout.feed(b"")  # ddagrab a perdu l'accès : ffmpeg s'arrête
        tablet.next_message(protocol.CONFIG)
        self.assertEqual(output_index(popen.calls[1]), 2)
        self.assertEqual(ddagrab_probes(run), [])
        self.assertEqual(len(connect.tablets), 1)
        self.assertEqual(len(display.prepares()), 1)
        self.assertEqual(display.releases(), [])
        self.assertIn("ffmpeg stopped on its own. Last lines:\n  AcquireNextFrame failed: 887a0026", rec.logs)
        self.assertIn(r"ddagrab output of \\.\DISPLAY9: #2 (from DXGI)", rec.logs)

    def test_repeated_deaths_without_video_end_in_error_without_reconnecting(self):
        popen, connect = FakePopen(dead), FakeConnect()
        relay, rec = make_engine(self, popen=popen, connect=connect)
        relay.start()
        rec.wait_state(State.ERROR)
        self.assertEqual(rec.states[-1], (State.ERROR, msg("error.ffmpeg_keeps_stopping",
                                                            count=engine.MAX_FFMPEG_FAILURES, last="boom")))
        self.assertEqual(len(popen.calls), engine.MAX_FFMPEG_FAILURES)
        self.assertEqual(len(connect.tablets), 1)
        self.assertEqual(rec.logs.count("Restarting the capture (ffmpeg stopped on its own)"),
                         engine.MAX_FFMPEG_FAILURES - 1)
        connect.tablets[0].wait_closed()

    def test_restarts_without_video_wait_between_tries(self):
        starts = []

        def timed():
            starts.append(time.monotonic())
            return dead()

        relay, rec = make_engine(self, popen=FakePopen(timed), retry_delay_s=0.3)
        relay.start()
        rec.wait_state(State.ERROR)
        self.assertEqual(len(starts), engine.MAX_FFMPEG_FAILURES)
        self.assertGreaterEqual(starts[2] - starts[1], 0.29)

    def test_tablet_leaving_while_waiting_to_restart_ends_the_session(self):
        popen, connect = FakePopen(dead), FakeConnect()
        relay, rec = make_engine(self, popen=popen, connect=connect, retry_delay_s=30)
        relay.start()
        wait_until(lambda: len(popen.calls) == 2)  # la 2e capture est morte : attente avant la 3e
        connect.refuse = True
        connect.tablets[0].leave()
        rec.wait_for(lambda: rec.last_state() is State.WAITING_APP)
        self.assertEqual(len(popen.calls), 2)
        self.assertNotIn(State.ERROR, [s for s, _ in rec.states])

    def test_stop_while_waiting_to_restart(self):
        popen = FakePopen(dead)
        relay, rec = make_engine(self, popen=popen, retry_delay_s=30)
        relay.start()
        wait_until(lambda: len(popen.calls) == 2)
        started = time.monotonic()
        relay.stop()
        self.assertLess(time.monotonic() - started, engine.STOP_TIMEOUT_S)
        self.assertFalse(relay.is_running())
        self.assertEqual(rec.states[-1], (State.STOPPED, msg("state.stopped")))
        self.assertEqual(len(popen.calls), 2)

    def test_move_during_session_start_captures_the_moved_screen_once(self):
        moved = Rect(0, -1800, 2880, 1800)
        display = FakeDisplay(block=True, on_prepare=lambda: None)
        display.layout_result = moved
        names = [r"\\.\DISPLAY1", r"\\.\DISPLAY9"]
        popen, connect, injectors = FakePopen(live), FakeConnect(), FakeInjectors()
        relay, rec = make_engine(self, popen=popen, connect=connect, injectors=injectors, config=self.EXTEND,
                                 display=display, dxgi=lambda: dxgi_list(*names),
                                 monitors=[(PRIMARY, True, r"\\.\DISPLAY1"), (moved, False, r"\\.\DISPLAY9")])
        relay.start()
        self.assertTrue(display.entered.wait(5))
        self.assertFalse(relay.relayout("above", "150"))  # appliqué dès que la session est en place
        display.proceed.set()
        first_tablet(connect).next_message(protocol.CONFIG)
        wait_until(lambda: injectors.created)
        self.assertEqual(display.layouts(), [("apply_layout", "above", "150", 274)])
        self.assertEqual(len(popen.calls), 1)  # pas de capture lancée puis tuée pour rien
        self.assertEqual(output_index(popen.calls[0]), 1)
        self.assertEqual(injectors.rects, [moved])


class DxgiOutputChoiceTest(unittest.TestCase):
    """The captured screen's ddagrab index comes from the DXGI list (instant); probing ddagrab is the fallback."""

    EXTEND = DisplayTest.EXTEND

    def start(self, run, dxgi, display=None, config=None, monitors=None):
        connect, popen, injectors = FakeConnect(), FakePopen(live), FakeInjectors()
        relay, rec = make_engine(self, run=run, popen=popen, connect=connect, injectors=injectors, dxgi=dxgi,
                                 config=config or self.EXTEND, display=display, monitors=monitors)
        relay.start()
        first_tablet(connect).next_message(protocol.CONFIG)
        wait_until(lambda: injectors.created)
        return popen, rec, injectors

    def test_virtual_screen_output_comes_from_dxgi_without_probing(self):
        run = FakeRun(outputs=((0, (2560, 1600)),))  # sonder ne trouverait pas l'écran virtuel
        popen, rec, injectors = self.start(run, lambda: dxgi_list(r"\\.\DISPLAY1", r"\\.\DISPLAY9"),
                                           display=FakeDisplay(on_prepare=lambda: None))
        self.assertEqual(output_index(popen.calls[0]), 1)
        self.assertEqual(ddagrab_probes(run), [])
        self.assertIn(r"ddagrab output of \\.\DISPLAY9: #1 (from DXGI)", rec.logs)
        self.assertIn("Captured screen: #1 (virtual screen 2880x1800)", rec.logs)
        self.assertEqual(injectors.rects, [VDD_RECT])

    def test_dxgi_failure_falls_back_to_probing(self):
        run = FakeRun(outputs=((0, (2560, 1600)), (1, (2880, 1800))))
        popen, rec, _injectors = self.start(run, no_dxgi, display=FakeDisplay(on_prepare=lambda: None))
        self.assertEqual(output_index(popen.calls[0]), 1)
        self.assertEqual(len(ddagrab_probes(run)), 3)  # #0, #1, puis #2 qui marque la fin
        self.assertIn("ddagrab output not known from DXGI (DXGI list unavailable: "
                      "CreateDXGIFactory1 failed (HRESULT 0x887A0004)): probing each output", rec.logs)

    def test_virtual_screen_on_another_adapter_is_found_by_probing(self):
        run = FakeRun(outputs=((0, (2560, 1600)), (1, (2880, 1800))))
        dxgi = lambda: dxgi_list(r"\\.\DISPLAY1") + dxgi_list(r"\\.\DISPLAY9", adapter=1)  # noqa: E731
        popen, rec, _injectors = self.start(run, dxgi, display=FakeDisplay(on_prepare=lambda: None))
        self.assertEqual(output_index(popen.calls[0]), 1)
        self.assertTrue(ddagrab_probes(run))
        self.assertIn(r"ddagrab output not known from DXGI (\\.\DISPLAY9 is on adapter #1 (GPU 1), "
                      "not ddagrab's default adapter (GPU 0)): probing each output", rec.logs)

    def test_virtual_screen_not_listed_yet_is_found_by_probing(self):
        run = FakeRun(outputs=((0, (2560, 1600)), (1, (2880, 1800))))
        popen, rec, _injectors = self.start(run, lambda: dxgi_list(r"\\.\DISPLAY1"),
                                            display=FakeDisplay(on_prepare=lambda: None))
        self.assertEqual(output_index(popen.calls[0]), 1)
        self.assertIn(r"ddagrab output not known from DXGI (\\.\DISPLAY9 is not listed by DXGI): probing each output",
                      rec.logs)

    def test_duplicate_mode_finds_the_main_screen_from_dxgi_without_any_probe(self):
        left = Rect(-1920, 0, 1920, 1080)
        run = FakeRun(outputs=())
        popen, rec, injectors = self.start(run, lambda: dxgi_list(r"\\.\DISPLAY2", r"\\.\DISPLAY1"),
                                           config=engine.Config(encoder="amf", mode="duplicate"),
                                           display=FakeDisplay(),
                                           monitors=[(left, False, r"\\.\DISPLAY2"), (PRIMARY, True, r"\\.\DISPLAY1")])
        self.assertEqual(output_index(popen.calls[0]), 1)
        self.assertEqual(ddagrab_probes(run), [])  # ni avant la connexion, ni pendant la session
        self.assertIn("Captured screen: #1 (main screen 2560x1600)", rec.logs)
        self.assertEqual(injectors.rects, [PRIMARY])


class DeviceRoleTest(unittest.TestCase):
    """After HELLO the engine waits (at most Deps.device_info_timeout_s) for DEVICE_INFO: role actions starts an
    Actions session (hub, no virtual screen, no ffmpeg, no injector); anything else streams the screen."""

    EXTEND = DisplayTest.EXTEND

    def actions_engine(self, after_hello=None, hubs=None, **kwargs):
        """An engine in Extend mode with a virtual display, whose tablets say they are Actions devices."""
        connect = FakeConnect(after_hello=device_info_frame() if after_hello is None else after_hello)
        display, popen, injectors = FakeDisplay(), FakePopen(live), FakeInjectors()
        hubs = hubs or FakeHubs()
        run = FakeRun(outputs=((0, (2560, 1600)),))
        relay, rec = make_engine(self, run=run, popen=popen, connect=connect, injectors=injectors,
                                 config=self.EXTEND, display=display, hubs=hubs, device_info_timeout_s=5.0,
                                 **kwargs)
        relay.start()
        return relay, rec, connect, hubs, display, popen, injectors, run

    def test_default_device_info_timeout_is_one_second(self):
        self.assertEqual(engine.DEVICE_INFO_TIMEOUT_S, 1.0)
        self.assertEqual(engine.Deps().device_info_timeout_s, 1.0)

    def test_default_hub_factory_builds_the_actions_hub_with_the_default_providers(self):
        send, log = (lambda state: None), (lambda line: None)
        send_artwork = lambda artwork_id, image: None  # noqa: E731
        with mock.patch("actions.hub.default_providers", return_value={"clock": "c"}) as providers, \
                mock.patch("actions.hub.ActionsHub") as hub_class:
            hub = engine.Deps().actions_hub_factory(send, log, send_artwork)
        providers.assert_called_once_with(log, lang="fr")
        hub_class.assert_called_once_with({"clock": "c"}, send, send_artwork=send_artwork, log=log)
        self.assertIs(hub, hub_class.return_value)

    def test_default_hub_factory_passes_the_language_to_the_providers(self):
        send, log = (lambda state: None), (lambda line: None)
        with mock.patch("actions.hub.default_providers", return_value={"clock": "c"}) as providers, \
                mock.patch("actions.hub.ActionsHub"):
            engine.Deps().actions_hub_factory(send, log, lang="en")
        providers.assert_called_once_with(log, lang="en")

    def test_hub_factory_gets_the_device_language(self):
        for sent, expected in (("en", "en"), ("fr", "fr"), ("de", "fr"), (None, "fr")):
            with self.subTest(sent=sent):
                relay, rec, connect, hubs, *_ = self.actions_engine(after_hello=device_info_frame(lang=sent))
                self.assertEqual(hubs.first().lang, expected)
                relay.stop()

    def test_default_hub_factory_send_artwork_is_optional(self):
        send, log = (lambda state: None), (lambda line: None)
        with mock.patch("actions.hub.default_providers", return_value={"clock": "c"}), \
                mock.patch("actions.hub.ActionsHub") as hub_class:
            engine.Deps().actions_hub_factory(send, log)
        hub_class.assert_called_once_with({"clock": "c"}, send, send_artwork=None, log=log)

    def test_hub_gets_a_send_artwork_that_frames_media_artwork(self):
        relay, rec, connect, hubs, *_ = self.actions_engine()
        hub = hubs.first()
        rec.wait_state(State.ACTIONS)
        tablet = first_tablet(connect)
        self.assertTrue(callable(hub.send_artwork))
        artwork_id, image = "c" * 40, b"\x89PNG\r\n\x1a\n" + bytes(range(256)) * 4
        hub.send_artwork(artwork_id, image)
        _type, flags, payload = tablet.next_message(protocol.MEDIA_ARTWORK)
        self.assertEqual(flags, 0)
        self.assertEqual(payload, bytes([40]) + artwork_id.encode("ascii") + image)

    def test_send_artwork_errors_go_back_to_the_hub(self):
        relay, rec, connect, hubs, *_ = self.actions_engine()
        hub = hubs.first()
        rec.wait_state(State.ACTIONS)
        tablet = first_tablet(connect)
        with self.assertRaises(ValueError):
            hub.send_artwork("c" * 40, b"\x00" * protocol.MAX_ARTWORK)  # too big once the id is added
        with self.assertRaises(ValueError):
            hub.send_artwork("", b"img")
        hub.send({"v": 1})  # the connection is still usable
        tablet.next_message(protocol.ACTIONS_STATE)
        self.assertIs(rec.last_state(), State.ACTIONS)

    def test_real_hub_sends_the_cover_frame_before_the_state_that_references_it(self):
        from actions.hub import ActionsHub

        cover = b"\xff\xd8\xff\xe0" + b"jpeg" * 1000
        cover_id = hashlib.sha1(cover).hexdigest()

        class NowPlaying:
            def snapshot(self):
                return {"available": True, "app": "Spotify", "title": "T", "artist": "A", "album": "L",
                        "playing": True, "artwork": cover_id}

            def artwork_bytes(self, artwork_id):
                return cover if artwork_id == cover_id else None

            def handle(self, action):
                return None

        hubs = []

        def factory(send, log, send_artwork=None, lang="fr"):
            hub = ActionsHub({"now_playing": NowPlaying()}, send, send_artwork=send_artwork, log=log,
                             com_init=lambda: None, poll_fast_s=0.05, poll_slow_s=0.05)
            hubs.append(hub)
            return hub

        relay, rec, connect, *_ = self.actions_engine(hubs=factory)
        rec.wait_state(State.ACTIONS)
        tablet = first_tablet(connect)
        seen = []
        deadline = time.monotonic() + 5.0
        while not any(t == protocol.ACTIONS_STATE for t, _ in seen):
            frame = tablet.frames.get(timeout=max(0.01, deadline - time.monotonic()))
            self.assertIsNotNone(frame, "connexion fermée par le PC")
            if frame[0] in (protocol.MEDIA_ARTWORK, protocol.ACTIONS_STATE):
                seen.append((frame[0], frame[2]))
        self.assertEqual([t for t, _ in seen], [protocol.MEDIA_ARTWORK, protocol.ACTIONS_STATE])
        self.assertEqual(seen[0][1], bytes([40]) + cover_id.encode("ascii") + cover)
        state = json.loads(seen[1][1].decode("utf-8"))
        self.assertEqual(state["now_playing"]["artwork"], cover_id)
        # the cover goes once: the following states reference it without a new MEDIA_ARTWORK
        relay.stop()
        rest = []
        while True:
            frame = tablet.frames.get(timeout=5.0)
            if frame is None:
                break
            rest.append(frame[0])
        self.assertNotIn(protocol.MEDIA_ARTWORK, rest)

    def test_actions_role_never_touches_display_ffmpeg_or_injector(self):
        relay, rec, connect, hubs, display, popen, injectors, run = self.actions_engine()
        hub = hubs.first()
        self.assertTrue(hub.started.wait(5))
        rec.wait_state(State.ACTIONS)
        self.assertEqual(rec.states[-1], (State.ACTIONS, msg("state.actions", name="Pixel 8")))
        tablet = first_tablet(connect)
        down = protocol.CONTACT_CONTACT | protocol.CONTACT_IN_RANGE
        tablet.send(touch_frame((0, down, 10, 10, 0, 0, 0)))  # ignorés : ni injecteur, ni flux
        tablet.send(keyframe_request_frame())
        tablet.send(stats_frame())
        tablet.send(ping_frame(7))
        tablet.next_message(protocol.PONG)  # le lecteur a traité tout ce qui précède
        self.assertEqual(display.calls, [])
        self.assertEqual(popen.calls, [])
        self.assertEqual(injectors.created, [])
        self.assertEqual(ddagrab_probes(run), [])
        self.assertEqual(rec.stats, [])
        seen = [s for s, _ in rec.states]
        self.assertNotIn(State.PREPARING_DISPLAY, seen)
        self.assertNotIn(State.STREAMING, seen)
        self.assertIn("Device role: actions (Pixel 8, phone)", rec.logs)
        self.assertEqual(len(hubs.created), 1)
        self.assertTrue(relay.is_running())

    def test_action_is_routed_to_the_hub(self):
        relay, rec, connect, hubs, *_ = self.actions_engine()
        hub = hubs.first()
        rec.wait_state(State.ACTIONS)
        tablet = first_tablet(connect)
        tablet.send(action_frame(id="volume.set", value=0.5))
        tablet.send(action_frame(id="usb.eject", drive="E:"))
        wait_until(lambda: len(hub.handled) == 2)
        self.assertEqual(hub.handled, [{"id": "volume.set", "value": 0.5}, {"id": "usb.eject", "drive": "E:"}])

    def test_hub_send_reaches_the_tablet_as_actions_state(self):
        relay, rec, connect, hubs, *_ = self.actions_engine()
        hub = hubs.first()
        rec.wait_state(State.ACTIONS)
        tablet = first_tablet(connect)
        state = {"v": 1, "audio": {"available": True, "volume": 0.42, "muted": False}, "usb": []}
        hub.send(state)
        _type, flags, payload = tablet.next_message(protocol.ACTIONS_STATE)
        self.assertEqual(flags, 0)
        self.assertEqual(json.loads(payload.decode("utf-8")), state)
        hub.send({"v": 1, "usb": [{"drive": "E:", "label": "KINGSTON"}]})
        _type, _flags, payload = tablet.next_message(protocol.ACTIONS_STATE)
        self.assertEqual(json.loads(payload)["usb"], [{"drive": "E:", "label": "KINGSTON"}])

    def test_failing_send_or_hub_never_kills_the_reader(self):
        hubs = FakeHubs(handle_error=RuntimeError("hub en panne"))
        relay, rec, connect, hubs, *_ = self.actions_engine(hubs=hubs)
        hub = hubs.first()
        rec.wait_state(State.ACTIONS)
        tablet = first_tablet(connect)
        with self.assertRaises(ValueError):
            hub.send({"v": 1, "bad": float("nan")})  # non encodable : l'erreur va au hub, qui la journalise
        tablet.send(action_frame(id="volume.mute", value=True))
        tablet.send(action_frame(id="volume.mute", value=False))
        wait_until(lambda: len(hub.handled) == 2)
        tablet.send(ping_frame(99))
        _type, _flags, payload = tablet.next_message(protocol.PONG)
        self.assertEqual(protocol._PONG.unpack(payload)[0], 99)
        failures = [line for line in rec.logs if line.startswith("Actions: action failed")]
        self.assertEqual(failures, ["Actions: action failed: hub en panne"])  # une fois par session
        hub.send({"v": 1})
        tablet.next_message(protocol.ACTIONS_STATE)
        self.assertIs(rec.last_state(), State.ACTIONS)

    def test_ping_is_answered_in_an_actions_session(self):
        relay, rec, connect, hubs, *_ = self.actions_engine()
        rec.wait_state(State.ACTIONS)
        tablet = first_tablet(connect)
        tablet.send(ping_frame(5555))
        _type, _flags, payload = tablet.next_message(protocol.PONG)
        self.assertEqual(protocol._PONG.unpack(payload)[0], 5555)

    def test_no_device_info_within_the_timeout_streams_the_screen(self):
        connect, popen, hubs = FakeConnect(), FakePopen(live), FakeHubs()
        relay, rec = make_engine(self, connect=connect, popen=popen, hubs=hubs, device_info_timeout_s=0.2)
        relay.start()
        tablet = first_tablet(connect)
        connected = time.monotonic()
        tablet.next_message(protocol.CONFIG)
        self.assertGreaterEqual(time.monotonic() - connected, 0.15)  # le PC a bien attendu DEVICE_INFO
        rec.wait_state(State.STREAMING)
        self.assertEqual(hubs.created, [])
        self.assertEqual(len(popen.calls), 1)
        self.assertIn("No DEVICE_INFO within 0.2 s: screen role", rec.logs)
        self.assertNotIn(State.ACTIONS, [s for s, _ in rec.states])

    def test_device_info_after_the_timeout_is_ignored(self):
        connect, hubs = FakeConnect(), FakeHubs()
        relay, rec = make_engine(self, connect=connect, hubs=hubs, device_info_timeout_s=0.05)
        relay.start()
        tablet = first_tablet(connect)
        tablet.next_message(protocol.CONFIG)
        tablet.send(device_info_frame())
        rec.wait_for(lambda: "Late DEVICE_INFO ignored (role actions)" in rec.logs)
        self.assertEqual(hubs.created, [])
        self.assertIs(rec.last_state(), State.STREAMING)

    def test_explicit_screen_role_streams_without_waiting(self):
        connect = FakeConnect(after_hello=device_info_frame(role="screen", kind="tablet", name="Galaxy Tab S9"))
        popen, hubs = FakePopen(live), FakeHubs()
        relay, rec = make_engine(self, connect=connect, popen=popen, hubs=hubs, device_info_timeout_s=30.0)
        started = time.monotonic()
        relay.start()
        first_tablet(connect).next_message(protocol.CONFIG)
        self.assertLess(time.monotonic() - started, 10.0)  # n'a pas attendu les 30 s
        rec.wait_state(State.STREAMING)
        self.assertEqual(hubs.created, [])
        self.assertEqual(len(popen.calls), 1)
        self.assertIn("Device role: screen (Galaxy Tab S9, tablet)", rec.logs)

    def test_explicit_screen_role_with_a_virtual_display_prepares_it(self):
        relay, rec, connect, hubs, display, popen, _injectors, run = self.actions_engine(
            after_hello=device_info_frame(role="screen", kind="tablet", name="Galaxy Tab S9"),
            dxgi=lambda: dxgi_list(r"\\.\DISPLAY1", r"\\.\DISPLAY9"))
        first_tablet(connect).next_message(protocol.CONFIG)
        self.assertEqual(len(display.prepares()), 1)
        self.assertEqual(hubs.created, [])
        self.assertEqual(len(popen.calls), 1)

    def test_unknown_role_streams_the_screen(self):
        connect = FakeConnect(after_hello=device_info_frame(role="remote"))
        popen, hubs = FakePopen(live), FakeHubs()
        relay, rec = make_engine(self, connect=connect, popen=popen, hubs=hubs, device_info_timeout_s=5.0)
        relay.start()
        first_tablet(connect).next_message(protocol.CONFIG)
        self.assertEqual(hubs.created, [])
        self.assertIn("Device role: remote (Pixel 8, phone): unknown, screen role used", rec.logs)

    def test_action_in_a_screen_session_is_ignored(self):
        connect, injectors = FakeConnect(), FakeInjectors()
        relay, rec = make_engine(self, connect=connect, injectors=injectors)
        relay.start()
        tablet = first_tablet(connect)
        tablet.next_message(protocol.CONFIG)
        tablet.send(action_frame(id="volume.set", value=0.1))
        tablet.send(action_frame(id="volume.set", value=0.2))
        tablet.send(ping_frame(1))
        tablet.next_message(protocol.PONG)
        self.assertEqual([line for line in rec.logs if line.startswith("ACTION ignored")],
                         ["ACTION ignored: not an Actions session"])
        self.assertIs(rec.last_state(), State.STREAMING)

    def test_stop_stops_the_hub(self):
        relay, rec, connect, hubs, display, popen, *_ = self.actions_engine()
        hub = hubs.first()
        rec.wait_state(State.ACTIONS)
        tablet = first_tablet(connect)
        started = time.monotonic()
        relay.stop()
        self.assertLess(time.monotonic() - started, engine.STOP_TIMEOUT_S)
        self.assertFalse(relay.is_running())
        self.assertTrue(hub.stopped.is_set())
        self.assertEqual(rec.states[-1], (State.STOPPED, msg("state.stopped")))
        tablet.wait_closed()
        self.assertEqual(display.calls, [])  # rien à éteindre : l'écran virtuel n'a jamais servi
        self.assertEqual(popen.calls, [])
        self.assertFalse(any(line.startswith("Tablet disconnected") for line in rec.logs))

    def test_quit_in_an_actions_session_releases_nothing(self):
        relay, rec, connect, hubs, display, *_ = self.actions_engine()
        rec.wait_state(State.ACTIONS)
        relay.stop(immediate_display_release=True)
        self.assertTrue(hubs.created[0].stopped.is_set())
        self.assertEqual(display.calls, [])

    def test_tablet_leaving_stops_the_hub_and_waits_again(self):
        relay, rec, connect, hubs, display, popen, *_ = self.actions_engine()
        hub = hubs.first()
        rec.wait_state(State.ACTIONS)
        connect.refuse = True
        first_tablet(connect).leave()
        self.assertTrue(hub.stopped.wait(5))
        rec.wait_for(lambda: rec.last_state() is State.WAITING_APP)
        self.assertTrue(any(line.startswith("Tablet disconnected") for line in rec.logs))
        self.assertTrue(relay.is_running())
        self.assertEqual(display.calls, [])
        self.assertEqual(popen.calls, [])

    def test_a_new_actions_session_gets_a_new_hub(self):
        relay, rec, connect, hubs, *_ = self.actions_engine()
        first = hubs.first()
        rec.wait_state(State.ACTIONS)
        first_tablet(connect).leave()
        self.assertTrue(first.stopped.wait(5))
        wait_until(lambda: len(hubs.created) == 2)
        self.assertTrue(hubs.created[1].started.wait(5))
        self.assertFalse(hubs.created[1].stopped.is_set())

    def test_stop_while_waiting_for_device_info_ends_quickly(self):
        connect, popen, hubs = FakeConnect(), FakePopen(live), FakeHubs()
        relay, rec = make_engine(self, connect=connect, popen=popen, hubs=hubs, device_info_timeout_s=30.0)
        relay.start()
        rec.wait_for(lambda: any(line.startswith("Tablet connected") for line in rec.logs))
        started = time.monotonic()
        relay.stop()
        self.assertLess(time.monotonic() - started, engine.STOP_TIMEOUT_S)
        self.assertFalse(relay.is_running())
        self.assertEqual(popen.calls, [])
        self.assertEqual(hubs.created, [])
        self.assertIs(rec.last_state(), State.STOPPED)

    def test_tablet_leaving_while_waiting_for_device_info_ends_the_session(self):
        connect, popen, hubs = FakeConnect(), FakePopen(live), FakeHubs()
        relay, rec = make_engine(self, connect=connect, popen=popen, hubs=hubs, device_info_timeout_s=30.0)
        relay.start()
        tablet = first_tablet(connect)
        rec.wait_for(lambda: any(line.startswith("Tablet connected") for line in rec.logs))
        connect.refuse = True
        tablet.leave()
        rec.wait_for(lambda: rec.last_state() is State.WAITING_APP, timeout=5.0)
        self.assertEqual(popen.calls, [])
        self.assertEqual(hubs.created, [])


class FrameRoleTest(unittest.TestCase):
    """Role frame: a Frame session (no virtual screen, no ffmpeg, no injector); frame.* actions go to it."""

    EXTEND = DeviceRoleTest.EXTEND

    def frame_engine(self, frames=None, after_hello=None, listener=None, **kwargs):
        connect = FakeConnect(after_hello=device_info_frame(role="frame", kind="tablet", name="Galaxy Tab")
                              if after_hello is None else after_hello)
        display, popen, injectors = FakeDisplay(), FakePopen(live), FakeInjectors()
        frames = frames or FakeFrameSessions()
        run = FakeRun(outputs=((0, (2560, 1600)),))
        relay, rec = make_engine(self, run=run, popen=popen, connect=connect, injectors=injectors, config=self.EXTEND,
                                 display=display, frames=frames, device_info_timeout_s=5.0, recorder=listener,
                                 **kwargs)
        relay.start()
        return relay, rec, connect, frames, display, popen, injectors, run

    def test_default_factory_builds_a_frame_session(self):
        from frame.session import FrameConfig, FrameSession

        session = engine.Deps().frame_session_factory(lambda *a: None, lambda *a: None, lambda line: None,
                                                      FrameConfig("D:\\Photos", 60, "fit"), (2880, 1800), "ffmpeg.exe")
        self.assertIsInstance(session, FrameSession)
        self.assertEqual(session._screen, (2880, 1800))
        self.assertEqual((session._folder, session._interval_s, session._fit), ("D:\\Photos", 60, "fit"))

    def test_the_session_gets_the_hello_screen_size_the_config_and_ffmpeg(self):
        relay, rec, connect, frames, *_ = self.frame_engine()
        session = frames.first()
        self.assertTrue(session.started.wait(5))
        self.assertEqual(session.screen, (2880, 1800))  # HELLO of FakeTablet
        self.assertEqual(session.ffmpeg, "ffmpeg.exe")
        self.assertEqual(session.config, FrameConfig())  # nothing set: no folder, 30 s, crop
        self.assertTrue(callable(session.send_state) and callable(session.send_file_chunk) and callable(session.log))
        self.assertIsNotNone(session.listener)
        self.assertEqual(len(frames.created), 1)

    def test_state_and_log_line(self):
        relay, rec, connect, frames, *_ = self.frame_engine()
        rec.wait_state(State.FRAME)
        self.assertEqual(rec.states[-1], (State.FRAME, msg("state.frame", name="Galaxy Tab")))
        self.assertIn("Device role: frame (Galaxy Tab, tablet)", rec.logs)
        self.assertTrue(relay.is_running())

    def test_frame_role_never_touches_display_ffmpeg_or_injector(self):
        relay, rec, connect, frames, display, popen, injectors, run = self.frame_engine()
        rec.wait_state(State.FRAME)
        tablet = first_tablet(connect)
        down = protocol.CONTACT_CONTACT | protocol.CONTACT_IN_RANGE
        tablet.send(touch_frame((0, down, 10, 10, 0, 0, 0)))
        tablet.send(keyframe_request_frame())
        tablet.send(stats_frame())
        tablet.send(ping_frame(7))
        tablet.next_message(protocol.PONG)
        self.assertEqual(display.calls, [])
        self.assertEqual(popen.calls, [])
        self.assertEqual(injectors.created, [])
        self.assertEqual(ddagrab_probes(run), [])
        seen = [s for s, _ in rec.states]
        self.assertNotIn(State.PREPARING_DISPLAY, seen)
        self.assertNotIn(State.STREAMING, seen)
        self.assertNotIn(State.ACTIONS, seen)

    def test_frame_actions_are_routed_to_the_session(self):
        relay, rec, connect, frames, *_ = self.frame_engine()
        session = frames.first()
        rec.wait_state(State.FRAME)
        tablet = first_tablet(connect)
        tablet.send(action_frame(id="frame.next"))
        tablet.send(action_frame(id="frame.pause", paused=True))
        tablet.send(action_frame(id="frame.fit", fit="fit"))
        tablet.send(action_frame(id="frame.interval", interval_s=300))
        tablet.send(action_frame(id="frame.failed", file=4))
        wait_until(lambda: len(session.handled) == 5)
        self.assertEqual(session.handled, [{"id": "frame.next"}, {"id": "frame.pause", "paused": True},
                                           {"id": "frame.fit", "fit": "fit"},
                                           {"id": "frame.interval", "interval_s": 300},
                                           {"id": "frame.failed", "file": 4}])

    def test_other_actions_are_not_for_the_frame_session(self):
        relay, rec, connect, frames, *_ = self.frame_engine()
        session = frames.first()
        rec.wait_state(State.FRAME)
        tablet = first_tablet(connect)
        tablet.send(action_frame(id="volume.set", value=0.1))
        tablet.send(action_frame(id="volume.set", value=0.2))
        tablet.send(ping_frame(1))
        tablet.next_message(protocol.PONG)
        self.assertEqual(session.handled, [])
        self.assertEqual([line for line in rec.logs if line.startswith("ACTION ignored")],
                         ["ACTION ignored: not an Actions session"])

    def test_frame_actions_outside_a_frame_session_are_ignored_once(self):
        hubs = FakeHubs()
        connect = FakeConnect(after_hello=device_info_frame())  # role actions
        relay, rec = make_engine(self, connect=connect, hubs=hubs, device_info_timeout_s=5.0)
        relay.start()
        hub = hubs.first()
        rec.wait_state(State.ACTIONS)
        tablet = first_tablet(connect)
        tablet.send(action_frame(id="frame.next"))
        tablet.send(action_frame(id="frame.next"))
        tablet.send(action_frame(id="volume.set", value=0.5))
        wait_until(lambda: len(hub.handled) == 1)
        self.assertEqual(hub.handled, [{"id": "volume.set", "value": 0.5}])  # the hub never sees frame.*
        self.assertEqual([line for line in rec.logs if line.startswith("ACTION ignored")],
                         ["ACTION ignored: not a Frame session"])

    def test_frame_action_in_a_screen_session_is_ignored(self):
        connect, frames = FakeConnect(), FakeFrameSessions()
        relay, rec = make_engine(self, connect=connect, frames=frames)
        relay.start()
        tablet = first_tablet(connect)
        tablet.next_message(protocol.CONFIG)
        tablet.send(action_frame(id="frame.next"))
        tablet.send(ping_frame(1))
        tablet.next_message(protocol.PONG)
        self.assertEqual(frames.created, [])
        self.assertIn("ACTION ignored: not a Frame session", rec.logs)
        self.assertIs(rec.last_state(), State.STREAMING)

    def test_a_failing_session_never_kills_the_reader(self):
        frames = FakeFrameSessions(handle_error=RuntimeError("session en panne"))
        relay, rec, connect, frames, *_ = self.frame_engine(frames=frames)
        session = frames.first()
        rec.wait_state(State.FRAME)
        tablet = first_tablet(connect)
        tablet.send(action_frame(id="frame.next"))
        tablet.send(action_frame(id="frame.next"))
        wait_until(lambda: len(session.handled) == 2)
        tablet.send(ping_frame(99))
        _type, _flags, payload = tablet.next_message(protocol.PONG)
        self.assertEqual(protocol._PONG.unpack(payload)[0], 99)
        self.assertEqual([line for line in rec.logs if line.startswith("Frame: action failed")],
                         ["Frame: action failed: session en panne"])  # once per session
        self.assertIs(rec.last_state(), State.FRAME)

    def test_the_session_sends_frame_state_and_frame_file_to_the_device(self):
        relay, rec, connect, frames, *_ = self.frame_engine()
        session = frames.first()
        rec.wait_state(State.FRAME)
        tablet = first_tablet(connect)
        session.send_state(3, "ok", "Photos", 30, "crop", False)
        _type, flags, payload = tablet.next_message(protocol.FRAME_STATE)
        self.assertEqual(flags, 0)
        self.assertEqual(payload, protocol.encode_frame_state(3, "ok", "Photos", 30, "crop", False)[protocol.HEADER.size:])
        session.send_file_chunk(3, 7, 1, 10, 5, bytes([6, 7, 8, 9, 10]))
        _type, flags, payload = tablet.next_message(protocol.FRAME_FILE)
        self.assertEqual(flags, 0)
        self.assertEqual(payload, protocol.encode_frame_file(3, 7, 1, 10, 5, bytes([6, 7, 8, 9, 10]))[protocol.HEADER.size:])

    def test_send_errors_go_back_to_the_session(self):
        relay, rec, connect, frames, *_ = self.frame_engine()
        session = frames.first()
        rec.wait_state(State.FRAME)
        tablet = first_tablet(connect)
        with self.assertRaises(ValueError):
            session.send_state(3, "weird", None, 30, "crop", False)
        with self.assertRaises(ValueError):
            session.send_file_chunk(3, 7, 9, 10, 0, b"x")  # unknown kind
        with self.assertRaises(ValueError):
            session.send_file_chunk(3, 7, 1, 10, 0, b"")
        session.send_state(3, "empty", None, 30, "crop", False)  # the connection is still usable
        tablet.next_message(protocol.FRAME_STATE)

    def test_set_frame_config_before_the_session_is_the_sessions_config(self):
        connect = FakeConnect(after_hello=device_info_frame(role="frame"))
        frames = FakeFrameSessions()
        relay, rec = make_engine(self, connect=connect, frames=frames, device_info_timeout_s=5.0)
        relay.set_frame_config("D:\\Photos", 900, "fit")
        relay.start()
        session = frames.first()
        self.assertEqual(session.config, FrameConfig("D:\\Photos", 900, "fit"))
        self.assertEqual(session.configs, [])  # given at creation, not again

    def test_set_frame_config_reaches_the_live_session_and_the_next_one(self):
        relay, rec, connect, frames, *_ = self.frame_engine()
        first = frames.first()
        rec.wait_state(State.FRAME)
        relay.set_frame_config("D:\\Photos", 60, "fit")
        relay.set_frame_config(None, 5, "crop")
        self.assertEqual(first.configs, [("D:\\Photos", 60, "fit"), (None, 5, "crop")])
        relay.set_frame_config("E:\\Clips", 300, "fit")
        first_tablet(connect).leave()
        self.assertTrue(first.stopped.wait(5))
        relay.set_frame_config("E:\\Clips", 900, "crop")  # between two sessions: nothing to tell, only kept
        self.assertEqual(len(first.configs), 3)
        wait_until(lambda: len(frames.created) == 2)
        self.assertEqual(frames.created[1].config, FrameConfig("E:\\Clips", 900, "crop"))

    def test_an_empty_folder_setting_means_no_folder(self):
        relay, rec, connect, frames, *_ = self.frame_engine()
        session = frames.first()
        relay.set_frame_config("", 30, "crop")
        self.assertEqual(session.configs, [(None, 30, "crop")])

    def test_settings_changed_on_the_device_reach_the_listener_and_are_remembered(self):
        relay, rec, connect, frames, *_ = self.frame_engine()
        session = frames.first()
        rec.wait_state(State.FRAME)
        relay.set_frame_config("D:\\Photos", 30, "crop")
        session.listener.on_frame_settings(900, "fit", True)
        rec.wait_for(lambda: rec.frame_settings)
        self.assertEqual(rec.frame_settings, [(900, "fit", True)])
        first_tablet(connect).leave()
        self.assertTrue(session.stopped.wait(5))
        wait_until(lambda: len(frames.created) == 2)  # the same device comes back: new session, remembered settings
        self.assertEqual(frames.created[1].config, FrameConfig("D:\\Photos", 900, "fit"))  # not the pause

    def test_a_listener_without_on_frame_settings_is_fine(self):
        listener = NoDisplayListener()
        connect = FakeConnect(after_hello=device_info_frame(role="frame"))
        frames = FakeFrameSessions()
        relay, rec = make_engine(self, connect=connect, frames=frames, device_info_timeout_s=5.0,
                                 recorder=listener)
        relay.start()
        session = frames.first()
        listener.rec.wait_state(State.FRAME)
        session.listener.on_frame_settings(300, "fit", False)
        tablet = first_tablet(connect)
        tablet.send(ping_frame(5))
        tablet.next_message(protocol.PONG)
        self.assertIs(listener.rec.last_state(), State.FRAME)

    def test_stop_stops_the_session(self):
        relay, rec, connect, frames, display, popen, *_ = self.frame_engine()
        session = frames.first()
        rec.wait_state(State.FRAME)
        tablet = first_tablet(connect)
        started = time.monotonic()
        relay.stop()
        self.assertLess(time.monotonic() - started, engine.STOP_TIMEOUT_S)
        self.assertFalse(relay.is_running())
        self.assertTrue(session.stopped.is_set())
        self.assertEqual(rec.states[-1], (State.STOPPED, msg("state.stopped")))
        tablet.wait_closed()
        self.assertEqual(display.calls, [])
        self.assertEqual(popen.calls, [])
        relay.set_frame_config("D:\\Photos", 30, "crop")  # nobody to tell any more: no error
        self.assertEqual(session.configs, [])

    def test_quit_in_a_frame_session_releases_no_display(self):
        relay, rec, connect, frames, display, *_ = self.frame_engine()
        rec.wait_state(State.FRAME)
        relay.stop(immediate_display_release=True)
        self.assertTrue(frames.created[0].stopped.is_set())
        self.assertEqual(display.calls, [])

    def test_tablet_leaving_stops_the_session_and_waits_again(self):
        relay, rec, connect, frames, display, popen, *_ = self.frame_engine()
        session = frames.first()
        rec.wait_state(State.FRAME)
        connect.refuse = True
        first_tablet(connect).leave()
        self.assertTrue(session.stopped.wait(5))
        rec.wait_for(lambda: rec.last_state() is State.WAITING_APP)
        self.assertTrue(relay.is_running())
        self.assertEqual(display.calls, [])
        self.assertEqual(popen.calls, [])

    def test_a_failing_session_stop_is_logged_not_fatal(self):
        class BadStop(FakeFrameSession):
            def stop(self):
                super().stop()
                raise RuntimeError("stop raté")

        class BadFrames(FakeFrameSessions):
            def __call__(self, *args):
                session = BadStop(args)
                self.created.append(session)
                return session

        relay, rec, connect, frames, *_ = self.frame_engine(frames=BadFrames())
        rec.wait_state(State.FRAME)
        relay.stop()
        self.assertIn("Frame: session stop failed: stop raté", rec.logs)
        self.assertIs(rec.last_state(), State.STOPPED)

    def test_the_real_session_sends_the_state_then_two_files_then_one_per_next(self):
        import random
        import tempfile
        from frame.session import FrameSession

        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        folder = Path(temp.name) / "Photos"
        folder.mkdir()
        for name in ("a.jpg", "b.jpg", "c.jpg"):
            (folder / name).write_bytes(b"x")

        def factory(send_state, send_file_chunk, log, config, screen, ffmpeg, listener):
            return FrameSession(send_state, send_file_chunk, log, config, screen, ffmpeg, listener,
                                prepare_image=lambda path, size: b"JPEG-" + path.name.encode(),
                                rng=random.Random(1))

        connect = FakeConnect(after_hello=device_info_frame(role="frame", kind="tablet", name="Galaxy Tab"))
        relay, rec = make_engine(self, connect=connect, frames=factory, device_info_timeout_s=5.0)
        relay.set_frame_config(str(folder), 60, "fit")
        relay.start()
        tablet = first_tablet(connect)
        _t, _f, payload = tablet.next_message(protocol.FRAME_STATE)
        self.assertEqual(json.loads(payload), {"epoch": 1, "status": "ok", "folder": "Photos", "interval_s": 60,
                                               "fit": "fit", "paused": False})
        files = []
        for _ in range(2):
            _t, _f, payload = tablet.next_message(protocol.FRAME_FILE)
            files.append(protocol._FRAME_FILE_HEAD.unpack(payload[:protocol._FRAME_FILE_HEAD.size]))
        self.assertEqual([(f[0], f[1], f[2]) for f in files], [(1, 1, 1), (1, 2, 1)])
        tablet.send(action_frame(id="frame.next"))
        _t, _f, payload = tablet.next_message(protocol.FRAME_FILE)
        self.assertEqual(protocol._FRAME_FILE_HEAD.unpack(payload[:protocol._FRAME_FILE_HEAD.size])[1], 3)
        tablet.send(action_frame(id="frame.interval", interval_s=300))
        _t, _f, payload = tablet.next_message(protocol.FRAME_STATE)
        self.assertEqual(json.loads(payload)["interval_s"], 300)
        rec.wait_for(lambda: rec.frame_settings == [(300, "fit", False)])
        relay.stop()
        tablet.wait_closed()


def option(command, name):
    return command[command.index(name) + 1]


class VideoCapsTest(unittest.TestCase):
    """DEVICE_INFO.video: the virtual screen is prepared at the size the tablet decodes, at its fps; x264 adds its
    own limits; the bitrate is automatic; the Auto scale follows the capture/native ratio."""

    NATIVE = (2880, 1800)
    SMALL = {"width": 2160, "height": 1350, "fps": 60}
    SMALL_RECT = Rect(2560, 0, 2160, 1350)

    def extend(self, video=None, config=None, size=NATIVE, rect=VDD_RECT, role="screen", **kwargs):
        """An Extend session whose tablet announces `video`; the virtual screen comes up as `rect`."""
        run = FakeRun(outputs=((0, (2560, 1600)),))
        display = FakeDisplay(result=PrepareResult(rect, True, size),
                              on_prepare=lambda: run.outputs.__setitem__(1, size))
        popen, injectors = FakePopen(live), FakeInjectors()
        connect = FakeConnect(after_hello=device_info_frame(role=role, video=video))
        config = config or engine.Config(encoder="amf", position="left", scale="150")
        relay, rec = make_engine(self, run=run, popen=popen, connect=connect, injectors=injectors, config=config,
                                 display=display, device_info_timeout_s=5.0, **kwargs)
        relay.start()
        tablet = first_tablet(connect)
        _type, _flags, payload = tablet.next_message(protocol.CONFIG)
        wait_until(lambda: injectors.created)
        return relay, rec, display, popen, injectors, tablet, protocol._CONFIG.unpack(payload)

    def test_without_video_nothing_changes(self):
        relay, rec, display, popen, injectors, _tablet, config = self.extend()
        self.assertEqual(display.prepares(), [("prepare", 2880, 1800, 274, "left", "150", False)])
        command = popen.calls[0][0]
        self.assertIn("ddagrab=output_idx=1:framerate=60,hwdownload,format=bgra", command)
        self.assertEqual((option(command, "-g"), option(command, "-rc")), ("60", "cbr"))
        self.assertEqual(config[3], 60)
        self.assertIn("Device video: not announced (native size)", rec.logs)
        self.assertNotIn("scale=", " ".join(command))

    def test_automatic_bitrate_without_video(self):
        _relay, rec, _display, popen, *_ = self.extend()
        self.assertEqual(option(popen.calls[0][0], "-b:v"), "27993600")  # 2880x1800 x 60 x 0.09
        self.assertIn("Bitrate: 28.0 Mb/s (auto)", rec.logs)

    def test_a_fixed_bitrate_wins(self):
        config = engine.Config(encoder="amf", bitrate="30M")
        _relay, rec, _display, popen, *_ = self.extend(config=config)
        self.assertEqual(option(popen.calls[0][0], "-b:v"), "30M")
        self.assertFalse([line for line in rec.logs if line.startswith("Bitrate")])

    def test_video_sets_the_virtual_screen_size_and_the_auto_scale_follows(self):
        config = engine.Config(encoder="amf", position="left", scale="auto")
        _relay, rec, display, popen, _injectors, _tablet, cfg = self.extend(
            self.SMALL, config=config, size=(2160, 1350), rect=self.SMALL_RECT)
        # dpi 274 x 2160/2880 = 205.5 -> 205 : Windows scale 150 % (200 % at the native size), same physical text size
        self.assertEqual(display.prepares(), [("prepare", 2160, 1350, 205, "left", "auto", False)])
        self.assertEqual(rec.displays[0].tablet_size, (2160, 1350))
        self.assertEqual(cfg[3], 60)
        self.assertEqual(option(popen.calls[0][0], "-b:v"), "15746400")  # 2160x1350 x 60 x 0.09
        self.assertIn("Device video: 2160x1350 at 60 fps", rec.logs)

    def test_relayout_keeps_using_the_corrected_dpi(self):
        relay, _rec, display, *_ = self.extend(self.SMALL, size=(2160, 1350), rect=self.SMALL_RECT)
        relay.relayout("left", "auto")
        self.assertEqual(display.layouts(), [("apply_layout", "left", "auto", 205)])

    def test_touch_targets_the_virtual_screen_at_the_reduced_size(self):
        _relay, _rec, _display, _popen, injectors, tablet, _cfg = self.extend(
            self.SMALL, size=(2160, 1350), rect=self.SMALL_RECT)
        self.assertEqual(injectors.rects, [self.SMALL_RECT])  # coordonnées normalisées : elles couvrent tout l'écran
        down = protocol.CONTACT_CONTACT | protocol.CONTACT_IN_RANGE
        tablet.send(touch_frame((0, down, 65535, 65535, 0, 0, 0)))
        wait_until(lambda: injectors.created[0].handled)

    def test_video_fps_lowers_the_frame_rate(self):
        _relay, rec, _display, popen, _inj, _tablet, cfg = self.extend({**self.SMALL, "fps": 30})
        command = popen.calls[0][0]
        self.assertEqual(cfg[3], 30)
        self.assertIn("framerate=30", " ".join(command))
        self.assertEqual(option(command, "-g"), "30")

    def test_the_configured_fps_still_limits(self):
        config = engine.Config(encoder="amf", fps=45)
        _relay, _rec, _display, popen, _inj, _tablet, cfg = self.extend(
            self.SMALL, config=config, size=(2160, 1350), rect=self.SMALL_RECT)
        self.assertEqual((cfg[3], option(popen.calls[0][0], "-g")), (45, "45"))

    def test_video_larger_than_the_screen_is_ignored(self):
        _relay, rec, display, *_ = self.extend({"width": 3840, "height": 2400, "fps": 60})
        self.assertEqual(display.prepares()[0][1:3], (2880, 1800))
        self.assertTrue([line for line in rec.logs if "ignored" in line])

    def test_invalid_video_behaves_like_no_video(self):
        _relay, _rec, display, popen, *_ = self.extend({"width": "big", "height": 1800, "fps": 60})
        self.assertEqual(display.prepares(), [("prepare", 2880, 1800, 274, "left", "150", False)])
        self.assertIn("framerate=60", " ".join(popen.calls[0][0]))

    def test_x264_caps_the_size_the_fps_and_sets_the_bitrate(self):
        config = engine.Config(encoder="x264", position="left", scale="auto")
        _relay, rec, display, popen, _inj, _tablet, cfg = self.extend(
            None, config=config, size=(1920, 1200), rect=Rect(2560, 0, 1920, 1200))
        command = popen.calls[0][0]
        self.assertEqual(display.prepares(), [("prepare", 1920, 1200, 182, "left", "auto", False)])  # 274x1920/2880
        self.assertEqual(cfg[3], 30)
        self.assertIn("framerate=30", " ".join(command))
        self.assertEqual(option(command, "-x264-params"), "keyint=30:min-keyint=30:scenecut=0")
        self.assertEqual(option(command, "-b:v"), "8000000")  # 1920x1200 x 30 x 0.09 = 6.2 Mb/s -> minimum 8
        self.assertNotIn("scale=", " ".join(command))
        self.assertIn("x264 runs on the processor: 30 fps at most", rec.logs)
        self.assertIn("x264 runs on the processor: 1920x1200 at most", rec.logs)

    def test_actions_sessions_do_not_prepare_a_screen(self):
        display, popen = FakeDisplay(), FakePopen(live)
        connect = FakeConnect(after_hello=device_info_frame(
            role="actions", video={"width": 1920, "height": 1200, "fps": 30}))
        relay, rec = make_engine(self, popen=popen, connect=connect, display=display,
                                 config=engine.Config(encoder="amf"), device_info_timeout_s=5.0)
        relay.start()
        rec.wait_state(State.ACTIONS)
        self.assertEqual(display.prepares(), [])
        self.assertEqual(popen.calls, [])

    def duplicate(self, encoder, video=None):
        popen, injectors, connect = FakePopen(live), FakeInjectors(), FakeConnect(
            after_hello=device_info_frame(role="screen", video=video))
        relay, rec = make_engine(self, run=FakeRun(outputs=((0, (2560, 1600)),)), popen=popen, injectors=injectors,
                                 connect=connect, monitors=[(PRIMARY, True, "D1")], device_info_timeout_s=5.0,
                                 config=engine.Config(encoder=encoder, mode="duplicate"))
        relay.start()
        first_tablet(connect).next_message(protocol.CONFIG)
        wait_until(lambda: injectors.created)
        return rec, popen, injectors

    def test_duplicate_keeps_the_main_screen_size_whatever_the_device_announces(self):
        _rec, popen, injectors = self.duplicate("amf", self.SMALL)
        command = popen.calls[0][0]
        self.assertNotIn("scale=", " ".join(command))
        self.assertEqual(injectors.rects, [PRIMARY])
        self.assertEqual(option(command, "-b:v"), str(engine.auto_bitrate(2560, 1600, 60)))

    def test_duplicate_with_x264_scales_the_capture_down(self):
        rec, popen, injectors = self.duplicate("x264")
        command = popen.calls[0][0]
        self.assertIn("ddagrab=output_idx=0:framerate=30,hwdownload,format=bgra,scale=1920:1200:flags=bilinear",
                      command)
        self.assertEqual(injectors.rects, [PRIMARY])  # le tactile couvre toujours l'écran principal en entier
        self.assertEqual(option(command, "-b:v"), "8000000")
        self.assertIn("Scaling the capture 2560x1600 to 1920x1200", rec.logs)


if __name__ == "__main__":
    unittest.main()
