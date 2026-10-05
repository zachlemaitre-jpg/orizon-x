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

from engine import Config, State


class FakeEngine:
    instances = []

    def __init__(self, config, listener):
        self.config = config
        self.listener = listener
        self.running = False
        self.stopping = threading.Event()
        self.stopped = threading.Event()
        self.announced = threading.Event()  # premier état transmis au listener
        FakeEngine.instances.append(self)

    def start(self):
        self.running = True

        def announce():
            self.listener.on_state(State.WAITING_DEVICE, "branche")
            self.announced.set()

        # comme le vrai moteur : les rappels arrivent depuis un autre thread
        threading.Thread(target=announce, daemon=True).start()

    def stop(self):
        self.stopping.set()
        time.sleep(0.2)  # le vrai stop() bloque jusqu'à 3 s
        self.running = False
        self.stopped.set()
        self.listener.on_state(State.STOPPED, "Arrêté.")

    def is_running(self):
        return self.running


def pump_until(predicate, timeout=3.0):
    deadline = time.monotonic() + timeout
    while not predicate():
        if time.monotonic() > deadline:
            raise AssertionError("délai dépassé")
        QCoreApplication.processEvents()
        time.sleep(0.005)


@unittest.skipUnless(HAVE_QT, "PySide6 absent (lancer avec .venv\Scripts\python.exe)")
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
        self.assertEqual((state, detail), (State.WAITING_DEVICE, "branche"))
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
        self.assertLess(time.monotonic() - started, 0.1)
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
        self.assertLess(time.monotonic() - started, 0.1)
        worker.join(2)
        self.assertFalse(worker.is_alive())
        self.assertEqual(len(FakeEngine.instances), 2)  # le start du redémarrage n'en a pas créé un 3ᵉ
        self.assertEqual(FakeEngine.instances[1].config, new_config)

    def test_late_callbacks_from_a_replaced_engine_are_ignored(self):
        late_sent = threading.Event()

        class LateStopEngine(FakeEngine):
            def stop(self):
                self.running = False
                self.stopped.set()

                def late():  # le STOPPED de l'ancien moteur arrive après le premier état du nouveau
                    deadline = time.monotonic() + 2
                    while len(FakeEngine.instances) < 2 and time.monotonic() < deadline:
                        time.sleep(0.005)
                    FakeEngine.instances[-1].announced.wait(2)
                    self.listener.on_state(State.STOPPED, "Arrêté.")
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

    def test_factory_failure_becomes_error_state(self):
        def failing(config, listener):
            raise RuntimeError("ffmpeg introuvable.")
        controller = Controller(failing, Config())
        controller.start()
        pump_until(lambda: controller.state is State.ERROR)
        self.assertEqual(controller.detail, "ffmpeg introuvable.")

    def test_start_after_error_creates_a_new_engine(self):
        self.controller.start()
        FakeEngine.instances[0].running = False  # le moteur s'est arrêté seul (ERROR)
        self.controller.start()
        self.assertEqual(len(FakeEngine.instances), 2)

    def test_stop_blocking_waits_for_the_engine(self):
        self.controller.start()
        self.controller.stop_blocking()
        self.assertTrue(FakeEngine.instances[0].stopped.is_set())


if __name__ == "__main__":
    unittest.main()
