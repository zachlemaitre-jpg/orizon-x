import argparse
import ctypes
import logging
import unittest

from app import admin, elevate
from vdd_device import DeviceInfo, VddDeviceError
from vdd import COMMON_RESOLUTIONS, VddError

LOG = logging.getLogger("orizonx.test-admin")
VDD_DEVICE = DeviceInfo(instance_id=r"ROOT\DISPLAY\0000", hardware_ids=("Root\\MttVDD",), driver_key=None,
                        inf_name="oem42.inf", driver_version="1.0")


class FakeVdd:
    def __init__(self, fail=None):
        self.calls = []
        self.fail = fail or {}
        self.settings_path = r"C:\VirtualDisplayDriver\vdd_settings.xml"

    def _call(self, name, *args):
        self.calls.append((name,) + args)
        if name in self.fail:
            raise self.fail[name]
        return True

    def set_gpu_in_xml(self, name):
        return self._call("gpu", name)

    def ensure_single_monitor(self):
        return self._call("single")

    def add_resolutions(self, resolutions):
        return self._call("resolutions", list(resolutions))


class FakeDevice:
    """vdd_device stand-in: never touches SetupAPI or pnputil."""

    def __init__(self, present=True, fail=None, admin=True, reboot=False):
        self.present = present
        self.fail = fail or {}
        self.admin = admin
        self.reboot = reboot
        self.calls = []

    def _call(self, name, *args):
        self.calls.append((name,) + args)
        if name in self.fail:
            raise self.fail[name]

    def is_admin(self):
        self.calls.append(("is_admin",))
        return self.admin

    def find_device(self):
        self.calls.append(("find",))
        return VDD_DEVICE if self.present else None

    def install_driver(self, inf):
        self._call("install", inf)
        return self.reboot

    def remove_driver(self):
        self._call("remove")

    def restart_device(self):
        self._call("restart")


class FakeCommands:
    """admin.run_command stand-in: records the command lines, never starts a process (no real icacls)."""

    def __init__(self, result=(0, "Successfully processed 1 files; Failed processing 0 files"), error=None):
        self.calls = []
        self.result = result
        self.error = error

    def __call__(self, args):
        self.calls.append(list(args))
        if self.error is not None:
            raise self.error
        return self.result


class FakeDisplay:
    def __init__(self, vdd, log):
        self.vdd = vdd
        self.log = log
        self.cleaned = 0
        FakeDisplay.made.append(self)

    def cleanup_on_start(self):
        self.cleaned += 1


def parse(*argv):
    parser = argparse.ArgumentParser()
    admin.add_arguments(parser)
    return parser.parse_args(list(argv))


class ParseTest(unittest.TestCase):
    def test_no_admin_flag_means_the_normal_app(self):
        self.assertFalse(admin.requested(parse()))

    def test_each_flag_is_an_admin_command(self):
        for argv in (["--cleanup"], ["--configure-vdd"], ["--configure-vdd", "--restart"], ["--restart"],
                     ["--install-driver", r"C:\x\MttVDD.inf"], ["--remove-driver"], ["--add-resolution", "2560x1600"]):
            with self.subTest(argv=argv):
                self.assertTrue(admin.requested(parse(*argv)))

    def test_commands_are_exclusive(self):
        with self.assertRaises(SystemExit), _quiet():
            parse("--cleanup", "--remove-driver")

    def test_size_parsing(self):
        self.assertEqual(admin.parse_size("2560x1600"), (2560, 1600))
        self.assertEqual(admin.parse_size("1600X2560"), (1600, 2560))
        for bad in ("2560", "x1600", "0x10", "2560x-1", "abcxdef", "99999x100"):
            with self.subTest(bad=bad), self.assertRaises(argparse.ArgumentTypeError):
                admin.parse_size(bad)


class _quiet:
    """argparse writes its usage error to stderr: silence it in the test output."""

    def __enter__(self):
        import io
        import sys
        self._saved = sys.stderr
        sys.stderr = io.StringIO()

    def __exit__(self, *exc):
        import sys
        sys.stderr = self._saved
        return False


class GpuNameTest(unittest.TestCase):
    def test_the_adapter_driving_the_primary_display(self):
        adapters = [("AMD Radeon(TM) 890M Graphics", r"PCI\VEN_1002&DEV_150E", 0x5),
                    ("NVIDIA GeForce RTX 5070 Laptop GPU", r"PCI\VEN_10DE&DEV_2D18", 0x0),
                    ("Virtual Display Driver", "Root\\MttVDD", 0x1)]
        self.assertEqual(admin.primary_gpu_name(lambda: adapters), "AMD Radeon(TM) 890M Graphics")

    def test_the_virtual_display_is_never_chosen(self):
        adapters = [("Virtual Display Driver", "ROOT\\MTTVDD", 0x5), ("Intel(R) UHD", r"PCI\VEN_8086", 0x1)]
        self.assertIsNone(admin.primary_gpu_name(lambda: adapters))

    def test_no_primary(self):
        self.assertIsNone(admin.primary_gpu_name(lambda: []))

    def test_real_struct_size(self):
        self.assertEqual(ctypes.sizeof(admin.DISPLAY_DEVICEW), 840)


class RunTest(unittest.TestCase):
    def setUp(self):
        FakeDisplay.made = []
        self.vdd = FakeVdd()
        self.device = FakeDevice()
        self.commands = FakeCommands()

    def run_admin(self, *argv, gpu="AMD Radeon(TM) 890M Graphics"):
        with self.assertLogs(LOG, "INFO") as logs:
            code = admin.run(parse(*argv), log=LOG, vdd_factory=lambda: self.vdd, device=self.device,
                             display_factory=FakeDisplay, gpu_name=lambda: gpu, run_command=self.commands)
        self.logs = "\n".join(logs.output)
        return code

    def test_cleanup_turns_the_virtual_screen_off(self):
        self.assertEqual(self.run_admin("--cleanup"), 0)
        self.assertEqual([d.cleaned for d in FakeDisplay.made], [1])
        self.assertIs(FakeDisplay.made[0].vdd, self.vdd)
        self.assertEqual(self.device.calls, [])
        self.assertEqual(self.vdd.calls, [])

    def test_configure_vdd_writes_gpu_single_monitor_and_resolutions_without_restart(self):
        self.assertEqual(self.run_admin("--configure-vdd"), 0)
        self.assertEqual(self.vdd.calls, [("gpu", "AMD Radeon(TM) 890M Graphics"), ("single",),
                                          ("resolutions", list(COMMON_RESOLUTIONS))])
        self.assertEqual(self.device.calls, [])

    def test_configure_vdd_with_restart_restarts_an_existing_device(self):
        self.assertEqual(self.run_admin("--configure-vdd", "--restart"), 0)
        self.assertEqual(self.device.calls, [("find",), ("restart",)])

    def test_configure_vdd_with_restart_and_no_device_does_not_restart(self):
        self.device.present = False
        self.assertEqual(self.run_admin("--configure-vdd", "--restart"), 0)
        self.assertEqual(self.device.calls, [("find",)])

    def test_configure_vdd_without_gpu_keeps_the_xml_gpu(self):
        self.assertEqual(self.run_admin("--configure-vdd", gpu=None), 0)
        self.assertEqual([c[0] for c in self.vdd.calls], ["single", "resolutions"])
        self.assertIn("GPU", self.logs)

    def test_configure_vdd_failure_is_exit_1_and_logged(self):
        self.vdd.fail["resolutions"] = VddError("access denied")
        self.assertEqual(self.run_admin("--configure-vdd", "--restart"), 1)
        self.assertIn("access denied", self.logs)
        self.assertEqual(self.device.calls, [])  # pas de redémarrage après un échec

    def test_configure_vdd_grants_users_modify_on_the_settings_folder(self):
        self.assertEqual(self.run_admin("--configure-vdd"), 0)
        self.assertEqual(len(self.commands.calls), 1)
        exe, folder, grant, rights = self.commands.calls[0]
        self.assertEqual(exe.lower().rsplit("\\", 1)[-1], "icacls.exe")
        self.assertEqual((folder, grant, rights), (r"C:\VirtualDisplayDriver", "/grant", "*S-1-5-32-545:(OI)(CI)M"))
        self.assertIn("Successfully processed", self.logs)

    def test_configure_vdd_grant_follows_the_resolved_settings_path(self):
        self.vdd.settings_path = r"D:\Custom Folder\vdd_settings.xml"   # VDDPATH
        self.assertEqual(self.run_admin("--configure-vdd", "--restart"), 0)
        self.assertEqual(self.commands.calls[0][1], r"D:\Custom Folder")

    def test_configure_vdd_grant_comes_after_the_xml_and_before_the_restart(self):
        order = []
        self.vdd._call = lambda name, *args: order.append(name) or True
        self.commands.result = (0, "")
        real_call = self.commands.__call__

        class Recording(FakeCommands):
            def __call__(inner, args):
                order.append("icacls")
                return real_call(args)

        self.device.restart_device = lambda: order.append("restart")
        self.run_admin_with(Recording(), "--configure-vdd", "--restart")
        self.assertEqual(order, ["gpu", "single", "resolutions", "icacls", "restart"])

    def run_admin_with(self, commands, *argv):
        with self.assertLogs(LOG, "INFO"):
            return admin.run(parse(*argv), log=LOG, vdd_factory=lambda: self.vdd, device=self.device,
                             display_factory=FakeDisplay, gpu_name=lambda: "GPU", run_command=commands)

    def test_configure_vdd_grant_failure_is_logged_and_exit_stays_0(self):
        self.commands.result = (5, "Access is denied.")
        self.assertEqual(self.run_admin("--configure-vdd", "--restart"), 0)
        self.assertIn("Access is denied.", self.logs)
        self.assertIn("5", self.logs)
        self.assertEqual(self.device.calls, [("find",), ("restart",)])   # la suite continue

    def test_configure_vdd_grant_that_cannot_start_is_logged_and_exit_stays_0(self):
        self.commands.error = OSError("icacls.exe not found")
        self.assertEqual(self.run_admin("--configure-vdd"), 0)
        self.assertIn("icacls.exe not found", self.logs)

    def test_configure_vdd_xml_failure_is_still_exit_1_but_the_grant_is_tried(self):
        self.vdd.fail["resolutions"] = VddError("access denied")
        self.assertEqual(self.run_admin("--configure-vdd"), 1)
        self.assertEqual(len(self.commands.calls), 1)

    def test_other_commands_do_not_touch_the_acl(self):
        for argv in (("--cleanup",), ("--install-driver", "MttVDD.inf"), ("--remove-driver",),
                     ("--add-resolution", "2800x1752")):
            self.run_admin(*argv)
        self.assertEqual(self.commands.calls, [])

    def test_default_command_runner_hides_the_window_and_returns_code_and_text(self):
        import subprocess
        from unittest import mock
        done = subprocess.CompletedProcess(["x"], 0, stdout=b"ok", stderr=b"")
        with mock.patch.object(admin.subprocess, "run", return_value=done) as run:
            self.assertEqual(admin.system_command(["icacls.exe", r"C:\x"]), (0, "ok"))
        kwargs = run.call_args.kwargs
        self.assertEqual(kwargs["creationflags"], admin.tools.NO_WINDOW)
        self.assertIs(kwargs["stdin"], subprocess.DEVNULL)

    def test_install_driver(self):
        self.assertEqual(self.run_admin("--install-driver", r"C:\Program Files\Orizon X\vdd\MttVDD.inf"), 0)
        self.assertEqual(self.device.calls, [("install", r"C:\Program Files\Orizon X\vdd\MttVDD.inf")])
        self.assertNotIn("Windows must restart", self.logs)

    def test_install_driver_needing_a_reboot_says_so(self):
        self.device.reboot = True
        self.assertEqual(self.run_admin("--install-driver", "MttVDD.inf"), 0)
        self.assertIn("Windows must restart", self.logs)

    def test_restart_alone_is_an_error(self):
        self.assertEqual(self.run_admin("--restart"), 1)
        self.assertIn("--restart only goes with --configure-vdd", self.logs)
        self.assertEqual((self.vdd.calls, self.device.calls), ([], []))

    def test_add_resolution_without_admin_rights_leaves_the_xml_alone(self):
        self.device.admin = False
        self.assertEqual(self.run_admin("--add-resolution", "2800x1752"), 1)
        self.assertEqual(self.vdd.calls, [])
        self.assertEqual(self.device.calls, [("is_admin",)])
        self.assertIn("administrator", self.logs)

    def test_xml_commands_log_the_settings_file(self):
        self.vdd.settings_path = r"D:\VDD\vdd_settings.xml"
        for argv in (["--configure-vdd"], ["--add-resolution", "2800x1752"]):
            with self.subTest(argv=argv):
                self.run_admin(*argv)
                self.assertIn(r"D:\VDD\vdd_settings.xml", self.logs)

    def test_install_driver_failure(self):
        self.device.fail["install"] = VddDeviceError("install_driver", 5, "administrator rights required")
        self.assertEqual(self.run_admin("--install-driver", "MttVDD.inf"), 1)
        self.assertIn("administrator rights required", self.logs)

    def test_remove_driver(self):
        self.assertEqual(self.run_admin("--remove-driver"), 0)
        self.assertEqual(self.device.calls, [("remove",)])

    def test_remove_driver_failure(self):
        self.device.fail["remove"] = VddDeviceError("remove_driver", 2)
        self.assertEqual(self.run_admin("--remove-driver"), 1)

    def test_add_resolution_adds_it_at_60_hz_then_restarts_the_device(self):
        self.assertEqual(self.run_admin("--add-resolution", "2800x1752"), 0)
        self.assertEqual(self.vdd.calls, [("resolutions", [(2800, 1752, 60)])])
        self.assertEqual(self.device.calls, [("is_admin",), ("restart",)])

    def test_add_resolution_restart_failure(self):
        self.device.fail["restart"] = VddDeviceError("restart_device", 1168, "no Root\\MttVDD device")
        self.assertEqual(self.run_admin("--add-resolution", "2800x1752"), 1)
        self.assertIn("no Root\\MttVDD device", self.logs)

    def test_unexpected_errors_are_exit_1(self):
        self.vdd.fail["resolutions"] = RuntimeError("boom")
        self.assertEqual(self.run_admin("--add-resolution", "2800x1752"), 1)
        self.assertIn("boom", self.logs)


class FakeShell:
    """ShellExecuteExW and process-handle stand-in."""

    def __init__(self, ok=True, error=0, exit_code=0, finishes=True, process="process"):
        self.ok = ok
        self.error = error
        self.code = exit_code
        self.finishes = finishes
        self.process = process
        self.calls = []

    def shell_execute(self, verb, file, parameters, show, hwnd=None):
        self.calls.append(("shell", verb, file, parameters, show, hwnd))
        return (self.process if self.ok else None), self.error

    def wait(self, process, timeout_ms):
        self.calls.append(("wait", process, timeout_ms))
        return self.finishes

    def exit_code(self, process):
        self.calls.append(("exit_code", process))
        return self.code

    def close(self, process):
        self.calls.append(("close", process))


class ElevateTest(unittest.TestCase):
    def test_packaged_app_runs_itself(self):
        self.assertEqual(elevate.self_command(["--add-resolution", "2800x1752"], frozen=True,
                                              executable=r"C:\Program Files\Orizon X\OrizonX.exe"),
                         (r"C:\Program Files\Orizon X\OrizonX.exe", "--add-resolution 2800x1752"))

    def test_source_checkout_runs_the_script_with_the_same_python(self):
        file, params = elevate.self_command(["--add-resolution", "2800x1752"], frozen=False,
                                            executable=r"D:\T App\.venv\Scripts\python.exe",
                                            script=r"D:\T App\orizonx_pc.py", exists=lambda p: False)
        self.assertEqual((file, params), (r"D:\T App\.venv\Scripts\python.exe",
                                          '"D:\\T App\\orizonx_pc.py" --add-resolution 2800x1752'))

    def test_source_checkout_prefers_pythonw(self):
        file, _params = elevate.self_command(["--cleanup"], frozen=False, executable=r"D:\v\python.exe",
                                             script=r"D:\orizonx_pc.py", exists=lambda p: p == r"D:\v\pythonw.exe")
        self.assertEqual(file, r"D:\v\pythonw.exe")

    def test_runs_as_admin_hidden_and_returns_the_exit_code(self):
        shell = FakeShell(exit_code=0)
        self.assertEqual(elevate.run_as_admin("OrizonX.exe", "--add-resolution 2800x1752", api=shell), 0)
        self.assertEqual(shell.calls[0], ("shell", "runas", "OrizonX.exe", "--add-resolution 2800x1752",
                                          elevate.SW_HIDE, None))
        self.assertEqual([c[0] for c in shell.calls], ["shell", "wait", "exit_code", "close"])

    def test_the_owner_window_is_given_so_the_uac_prompt_comes_to_the_front(self):
        shell = FakeShell()
        elevate.run_as_admin("OrizonX.exe", "--x", hwnd=0x1234, api=shell)
        self.assertEqual(shell.calls[0][-1], 0x1234)

    def test_no_process_handle_is_an_explicit_error_not_a_timeout(self):
        for process in (None, 0):
            with self.subTest(process=process):
                shell = FakeShell(process=process)
                with self.assertRaises(OSError) as caught:
                    elevate.run_as_admin("OrizonX.exe", "--x", api=shell)
                self.assertNotIsInstance(caught.exception, TimeoutError)
                self.assertIn("no process handle", str(caught.exception))
                self.assertEqual([c[0] for c in shell.calls], ["shell"])  # rien à attendre ni à fermer

    def test_a_failed_wait_is_an_error_not_a_timeout(self):
        class FailingWaitShell(FakeShell):
            def wait(self, process, timeout_ms):
                raise OSError(6, "invalid handle")

        shell = FailingWaitShell()
        with self.assertRaises(OSError) as caught:
            elevate.run_as_admin("OrizonX.exe", "--x", api=shell)
        self.assertNotIsInstance(caught.exception, TimeoutError)
        self.assertEqual(shell.calls[-1], ("close", "process"))

    def test_add_resolution_passes_the_owner_window(self):
        seen = []
        elevate.add_resolution(2800, 1752, hwnd=77, run=lambda f, p, hwnd=None: seen.append(hwnd) or 1,
                               command=lambda args: ("exe", " ".join(args)))
        self.assertEqual(seen, [77])

    def test_uac_refused_is_none(self):
        shell = FakeShell(ok=False, error=elevate.ERROR_CANCELLED)
        self.assertIsNone(elevate.run_as_admin("OrizonX.exe", "--x", api=shell))
        self.assertEqual(len(shell.calls), 1)

    def test_other_launch_errors_raise(self):
        with self.assertRaises(OSError):
            elevate.run_as_admin("OrizonX.exe", "--x", api=FakeShell(ok=False, error=2))

    def test_a_process_that_never_ends_is_a_timeout(self):
        shell = FakeShell(finishes=False)
        with self.assertRaises(TimeoutError):
            elevate.run_as_admin("OrizonX.exe", "--x", api=shell, timeout_s=1)
        self.assertEqual(shell.calls[-1], ("close", "process"))

    def test_struct_size(self):
        self.assertEqual(ctypes.sizeof(elevate.SHELLEXECUTEINFOW), 112 if ctypes.sizeof(ctypes.c_void_p) == 8 else 60)

    def test_add_resolution_waits_for_the_driver_after_success(self):
        calls, ready = [], iter([False, False, True])
        clock = [0.0]

        def run(file, params, hwnd=None):
            calls.append((file, params))
            return 0

        def sleep(s):
            clock[0] += s

        code = elevate.add_resolution(2800, 1752, run=run, driver_ready=lambda: next(ready),
                                      sleep=sleep, clock=lambda: clock[0], command=lambda args: ("exe", " ".join(args)))
        self.assertEqual(code, 0)
        self.assertEqual(calls, [("exe", "--add-resolution 2800x1752")])
        self.assertEqual(clock[0], 2 * elevate.READY_POLL_S)

    def test_add_resolution_refused_or_failed_does_not_wait(self):
        for result in (None, 1):
            with self.subTest(result=result):
                waited = []
                code = elevate.add_resolution(2800, 1752, run=lambda f, p, hwnd=None: result,
                                              driver_ready=lambda: waited.append(1) or True,
                                              command=lambda args: ("exe", " ".join(args)))
                self.assertEqual((code, waited), (result, []))

    def test_add_resolution_gives_up_waiting_after_the_timeout(self):
        clock = [0.0]

        def sleep(s):
            clock[0] += s

        code = elevate.add_resolution(2800, 1752, run=lambda f, p, hwnd=None: 0, driver_ready=lambda: False,
                                      sleep=sleep, clock=lambda: clock[0], command=lambda args: ("exe", " ".join(args)))
        self.assertEqual(code, 0)
        self.assertGreaterEqual(clock[0], elevate.READY_TIMEOUT_S)


if __name__ == "__main__":
    unittest.main()
