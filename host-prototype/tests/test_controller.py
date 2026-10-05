import importlib.util
import os
import threading
import time
import unittest

HAVE_QT = importlib.util.find_spec("PySide6") is not None
if HAVE_QT:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtCore import QCoreApplication
    from PySide6.QtWidgets import QApplication

    from app.controller import Controller

import tools
from engine import Config, DisplayInfo, State
from inputstate import Rect
from messages import msg


class FakeEngine:
    instances = []

    def __init__(self, config, listener):
        self.config = config
        self.listener = listener
        self.running = False
        self.stopping = threading.Event()
        self.stopped = threading.Event()
        self.announced = threading.Event()  # premier état transmis au listener
        self.stop_calls = []  # valeur de immediate_display_release à chaque stop()
        self.relayouts = []
        FakeEngine.instances.append(self)

    def start(self):
        self.running = True

        def announce():
            self.listener.on_state(State.WAITING_DEVICE, msg("adb.no_device"))
            self.announced.set()

        # comme le vrai moteur : les rappels arrivent depuis un autre thread
        threading.Thread(target=announce, daemon=True).start()

    def stop(self, immediate_display_release=False):
        self.stop_calls.append(immediate_display_release)
        self.stopping.set()
        time.sleep(0.2)  # le vrai stop() bloque jusqu'à 3 s
        self.running = False
        self.stopped.set()
        self.listener.on_state(State.STOPPED, msg("state.stopped"))

    def is_running(self):
        return self.running

    def relayout(self, position, scale):
        self.relayouts.append((position, scale))
        return True


def pump_until(predicate, timeout=3.0):
    deadline = time.monotonic() + timeout
    while not predicate():
        if time.monotonic() > deadline:
            raise AssertionError("délai dépassé")
        QCoreApplication.processEvents()
        time.sleep(0.005)


@unittest.skipUnless(HAVE_QT, r"PySide6 absent (lancer avec .venv\Scripts\python.exe)")
class ControllerTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QCoreApplication.instance() or QApplication([])  # QApplication : test_window/test_tray partagent le processus

    def setUp(self):
        FakeEngine.instances.clear()
        self.controller = Controller(FakeEngine, Config())
        self.received = []
        self.controller.state_changed.connect(
            lambda state, detail: self.received.append((state, detail, threading.current_thread())))

    def test_callbacks_from_other_threads_arrive_on_the_qt_thread(self):
        self.controller.start()
        pump_until(lambda: self.received)
        state, detail, thread = self.received[0]
        self.assertEqual((state, detail), (State.WAITING_DEVICE, msg("adb.no_device")))
        self.assertIs(thread, threading.main_thread())
        self.assertIs(self.controller.state, State.WAITING_DEVICE)

    def test_start_twice_creates_one_engine(self):
        self.controller.start()
        self.controller.start()
        self.assertEqual(len(FakeEngine.instances), 1)

    def test_stop_does_not_block_the_qt_thread(self):
        self.controller.start()
        started = time.monotonic()
        worker = self.controller.stop()
        self.assertLess(time.monotonic() - started, 0.5)
        worker.join(2)
        pump_until(lambda: self.controller.state is State.STOPPED)

    def test_restart_stops_then_starts_with_new_config(self):
        self.controller.start()
        new_config = Config(output="1", encoder="amf")
        self.controller.restart(new_config).join(2)
        self.assertEqual(len(FakeEngine.instances), 2)
        self.assertTrue(FakeEngine.instances[0].stopped.is_set())
        self.assertEqual(FakeEngine.instances[1].config, new_config)
        self.assertEqual(self.controller.config, new_config)

    def test_commands_during_a_restart_do_not_wait_for_the_old_engine(self):
        self.controller.start()
        new_config = Config(output="1", encoder="amf")
        worker = self.controller.restart(new_config)
        self.assertTrue(FakeEngine.instances[0].stopping.wait(2))
        started = time.monotonic()
        self.controller.start()  # clic pendant le redémarrage : le thread Qt ne doit pas rester figé
        self.assertLess(time.monotonic() - started, 0.5)
        worker.join(2)
        self.assertFalse(worker.is_alive())
        self.assertEqual(len(FakeEngine.instances), 2)  # le start du redémarrage n'en a pas créé un 3ᵉ
        self.assertEqual(FakeEngine.instances[1].config, new_config)

    def test_late_callbacks_from_a_replaced_engine_are_ignored(self):
        late_sent = threading.Event()

        class LateStopEngine(FakeEngine):
            def stop(self, immediate_display_release=False):
                self.running = False
                self.stopped.set()

                def late():  # le STOPPED de l'ancien moteur arrive après le premier état du nouveau
                    deadline = time.monotonic() + 2
                    while len(FakeEngine.instances) < 2 and time.monotonic() < deadline:
                        time.sleep(0.005)
                    FakeEngine.instances[-1].announced.wait(2)
                    self.listener.on_state(State.STOPPED, msg("state.stopped"))
                    late_sent.set()

                threading.Thread(target=late, daemon=True).start()

        def factory(config, listener):
            return (FakeEngine if FakeEngine.instances else LateStopEngine)(config, listener)

        controller = Controller(factory, Config())
        received = []
        controller.state_changed.connect(lambda state, detail: received.append(state))
        controller.start()
        pump_until(lambda: received)
        controller.restart(Config(encoder="amf")).join(2)
        self.assertTrue(late_sent.wait(3))
        pump_until(lambda: len(received) >= 2)
        deadline = time.monotonic() + 0.1
        while time.monotonic() < deadline:  # laisse arriver un éventuel signal en retard
            QCoreApplication.processEvents()
            time.sleep(0.005)
        self.assertEqual(received, [State.WAITING_DEVICE, State.WAITING_DEVICE])
        self.assertIs(controller.state, State.WAITING_DEVICE)

    def test_stopped_engine_still_reports_stopped(self):
        self.controller.start()
        pump_until(lambda: self.received)
        self.controller.stop().join(2)
        pump_until(lambda: self.controller.state is State.STOPPED)

    def test_initial_state_is_stopped(self):
        self.assertEqual((self.controller.state, self.controller.detail), (State.STOPPED, msg("state.stopped")))

    def test_factory_failure_becomes_error_state(self):
        def failing(config, listener):
            raise RuntimeError("panne")
        controller = Controller(failing, Config())
        controller.start()
        pump_until(lambda: controller.state is State.ERROR)
        self.assertEqual(controller.detail, msg("error.unexpected", error="panne"))

    def test_missing_tool_shows_its_own_message(self):
        def failing(config, listener):
            raise tools.ToolMissing(msg("tools.ffmpeg_missing"))
        controller = Controller(failing, Config())
        controller.start()
        pump_until(lambda: controller.state is State.ERROR)
        self.assertEqual(controller.detail, msg("tools.ffmpeg_missing"))

    def test_start_after_error_creates_a_new_engine(self):
        self.controller.start()
        FakeEngine.instances[0].running = False  # le moteur s'est arrêté seul (ERROR)
        self.controller.start()
        self.assertEqual(len(FakeEngine.instances), 2)

    def test_stop_blocking_waits_for_the_engine(self):
        self.controller.start()
        self.controller.stop_blocking()
        self.assertTrue(FakeEngine.instances[0].stopped.is_set())

    def test_immediate_display_release_reaches_the_engine(self):
        self.controller.start()
        self.controller.stop(immediate_display_release=True).join(2)
        self.controller.start()
        self.controller.stop_blocking(immediate_display_release=True)
        self.controller.start()
        self.controller.restart(Config(mode="duplicate"), immediate_display_release=True).join(2)
        self.controller.stop_blocking()
        self.assertEqual([engine.stop_calls for engine in FakeEngine.instances], [[True], [True], [True], [False]])

    def test_display_info_is_forwarded_on_the_qt_thread(self):
        infos = []
        self.controller.display_changed.connect(lambda info: infos.append((info, threading.current_thread())))
        self.controller.start()
        info = DisplayInfo((2880, 1800), (2560, 1600), False, Rect(2560, 0, 2560, 1600))
        threading.Thread(target=FakeEngine.instances[0].listener.on_display, args=(info,)).start()
        pump_until(lambda: infos)
        self.assertEqual(infos, [(info, threading.main_thread())])

    def test_display_info_from_a_replaced_engine_is_ignored(self):
        infos = []
        self.controller.display_changed.connect(infos.append)
        self.controller.start()
        old_listener = FakeEngine.instances[0].listener
        self.controller.restart(Config(encoder="amf")).join(2)
        old_listener.on_display(DisplayInfo((2880, 1800), (2880, 1800), True, Rect(0, 0, 2880, 1800)))
        new = DisplayInfo((1920, 1200), (1920, 1200), True, Rect(0, 0, 1920, 1200))
        FakeEngine.instances[1].listener.on_display(new)
        pump_until(lambda: infos)
        deadline = time.monotonic() + 0.1
        while time.monotonic() < deadline:
            QCoreApplication.processEvents()
            time.sleep(0.005)
        self.assertEqual(infos, [new])

    def test_relayout_reaches_the_running_engine_and_the_next_config(self):
        self.controller.start()
        self.controller.relayout("left", "150").join(2)
        self.assertEqual(FakeEngine.instances[0].relayouts, [("left", "150")])
        self.assertEqual((self.controller.config.position, self.controller.config.scale), ("left", "150"))
        self.controller.restart(Config(encoder="amf", position="left", scale="150")).join(2)
        self.assertEqual(FakeEngine.instances[1].relayouts, [])  # aucun appel en double sur le nouveau moteur

    def test_quick_relayouts_are_coalesced_in_order_and_end_on_the_latest(self):
        entered, gate = threading.Event(), threading.Event()

        class SlowRelayoutEngine(FakeEngine):
            def relayout(self, position, scale):
                super().relayout(position, scale)
                if len(self.relayouts) == 1:  # Windows déplace l'écran : environ une seconde
                    entered.set()
                    gate.wait(5)
                return True

        controller = Controller(SlowRelayoutEngine, Config())
        controller.start()
        worker = controller.relayout("left", "150")
        self.assertTrue(entered.wait(2))
        self.assertIs(controller.relayout("above", "125"), worker)  # un seul fil de relayout à la fois
        self.assertIs(controller.relayout("below", "175"), worker)
        gate.set()
        worker.join(2)
        self.assertFalse(worker.is_alive())
        engine = FakeEngine.instances[0]
        # L'intermédiaire n'est jamais envoyé ; le dernier l'est, une fois, après le premier.
        self.assertEqual(engine.relayouts, [("left", "150"), ("below", "175")])
        again = controller.relayout("right", "auto")  # le fil fini, un nouveau prend le relais
        self.assertIsNot(again, worker)
        again.join(2)
        self.assertEqual(engine.relayouts[-1], ("right", "auto"))

    def test_relayout_without_an_engine_only_updates_the_config(self):
        self.assertIsNone(self.controller.relayout("below", "auto"))
        self.assertEqual(self.controller.config, Config(position="below", scale="auto"))
        self.controller.start()
        self.assertEqual(FakeEngine.instances[0].config.position, "below")

    def test_stop_during_a_restart_cancels_the_new_engine(self):
        self.controller.start()
        worker = self.controller.restart(Config(encoder="amf"))
        self.assertTrue(FakeEngine.instances[0].stopping.wait(2))
        self.controller.stop()  # Arrêter pendant que l'ancien moteur s'arrête : le redémarrage n'en crée pas d'autre
        worker.join(2)
        self.assertFalse(worker.is_alive())
        self.assertEqual(len(FakeEngine.instances), 1)
        pump_until(lambda: self.controller.state is State.STOPPED)

    def test_stop_blocking_waits_for_a_pending_restart(self):
        self.controller.start()
        worker = self.controller.restart(Config(encoder="amf"))
        self.assertTrue(FakeEngine.instances[0].stopping.wait(2))
        self.controller.stop_blocking()  # Quitter : l'ancienne session doit avoir levé ses contacts
        self.assertFalse(worker.is_alive())
        self.assertTrue(FakeEngine.instances[0].stopped.is_set())
        self.assertEqual(len(FakeEngine.instances), 1)

if __name__ == "__main__":
    unittest.main()
