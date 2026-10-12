import ctypes
import os
import unittest
from pathlib import Path
import tempfile

import vdd_device
from vdd_device import DeviceInfo, VddDeviceError

ENUM = r"SYSTEM\CurrentControlSet\Enum\ROOT\DISPLAY"
CLASS = r"SYSTEM\CurrentControlSet\Control\Class"
DISPLAY_GUID = "{4d36e968-e325-11ce-bfc1-08002be10318}"


class FakeRegistry:
    """HKLM as a dict {key path: {value name: value}}; subkeys come from the paths."""

    def __init__(self, keys):
        self.keys = {path.lower(): (path, values) for path, values in keys.items()}

    def subkeys(self, path):
        prefix = path.lower() + "\\"
        if path.lower() not in self.keys and not any(k.startswith(prefix) for k in self.keys):
            raise OSError(2, "key not found")
        names = []
        for key, (original, _values) in self.keys.items():
            if key.startswith(prefix):
                name = original[len(prefix):].split("\\")[0]
                if name not in names:
                    names.append(name)
        return names

    def value(self, path, name):
        entry = self.keys.get(path.lower())
        return None if entry is None else entry[1].get(name)


def this_pc_registry(**extra):
    """The layout observed on the user's PC (docs/notes/vdd-control.md §3)."""
    keys = {
        ENUM + r"\0000": {"HardwareID": ["Root\\MttVDD"], "Driver": DISPLAY_GUID + r"\0004"},
        CLASS + "\\" + DISPLAY_GUID + r"\0004": {"InfPath": "oem114.inf", "DriverVersion": "11.30.4.434"},
    }
    keys.update(extra)
    return FakeRegistry(keys)


VDD_0000 = DeviceInfo(instance_id=r"ROOT\DISPLAY\0000", hardware_ids=("Root\\MttVDD",),
                      driver_key=DISPLAY_GUID + r"\0004", inf_name="oem114.inf", driver_version="11.30.4.434")


class FakeApi:
    """Records every Win32 call; `fail` = {method name: Windows error code} makes that call raise."""

    def __init__(self, admin=True, fail=None, pnputil_results=None, reboot=False):
        self.admin = admin
        self.reboot = reboot
        self.fail = fail or {}
        self.pnputil_results = list(pnputil_results or [])
        self.calls = []

    def _call(self, name, *args):
        self.calls.append((name,) + args)
        if name in self.fail:
            raise VddDeviceError(name, self.fail[name])

    def is_admin(self):
        self.calls.append(("is_admin",))
        return self.admin

    def inf_class(self, inf_path):
        self._call("inf_class", inf_path)
        return "GUID-DISPLAY", "Display"

    def create_info_list(self, class_guid):
        self._call("create_info_list", class_guid)
        return "HSET"

    def create_device_info(self, hset, class_name, class_guid):
        self._call("create_device_info", hset, class_name, class_guid)
        return "DEV"

    def set_hardware_id(self, hset, dev, hardware_id):
        self._call("set_hardware_id", hset, dev, hardware_id)

    def register_device(self, hset, dev):
        self._call("register_device", hset, dev)

    def update_driver(self, hardware_id, inf_path):
        self._call("update_driver", hardware_id, inf_path)
        return self.reboot

    def open_device(self, hset, instance_id):
        self._call("open_device", hset, instance_id)
        return "DEV:" + instance_id

    def remove_device(self, hset, dev):
        self._call("remove_device", hset, dev)

    def destroy_info_list(self, hset):
        self._call("destroy_info_list", hset)

    def pnputil(self, args):
        self.calls.append(("pnputil",) + tuple(args))
        return self.pnputil_results.pop(0) if self.pnputil_results else (0, "ok")

    def names(self):
        return [call[0] for call in self.calls]


class ParsingTest(unittest.TestCase):
    def test_parse_hardware_ids(self):
        self.assertEqual(vdd_device.parse_hardware_ids(["Root\\MttVDD", ""]), ("Root\\MttVDD",))
        self.assertEqual(vdd_device.parse_hardware_ids("Root\\MttVDD"), ("Root\\MttVDD",))
        self.assertEqual(vdd_device.parse_hardware_ids("A\0B\0\0"), ("A", "B"))
        self.assertEqual(vdd_device.parse_hardware_ids(None), ())
        self.assertEqual(vdd_device.parse_hardware_ids(5), ())

    def test_is_vdd_is_case_insensitive(self):
        self.assertTrue(vdd_device.is_vdd(("ROOT\\MTTVDD",)))
        self.assertTrue(vdd_device.is_vdd(("Other", "root\\mttvdd")))
        self.assertFalse(vdd_device.is_vdd(("Root\\MttVDD2",)))
        self.assertFalse(vdd_device.is_vdd(()))

    def test_oem_inf_name_accepts_only_driver_store_names(self):
        self.assertEqual(vdd_device.oem_inf_name("oem114.inf"), "oem114.inf")
        self.assertEqual(vdd_device.oem_inf_name("OEM7.INF"), "OEM7.INF")
        for bad in ("mttvdd.inf", "oem.inf", r"C:\x\oem1.inf", "oem1.inf /force", "", None, 3):
            with self.subTest(bad=bad):
                self.assertIsNone(vdd_device.oem_inf_name(bad))

    def test_hardware_id_multi_sz(self):
        self.assertEqual(vdd_device.multi_sz("Root\\MttVDD"), "Root\\MttVDD\0\0".encode("utf-16le"))

    def test_pnputil_path(self):
        self.assertEqual(vdd_device.pnputil_path(r"C:\Windows", wow64=False), r"C:\Windows\System32\pnputil.exe")
        self.assertEqual(vdd_device.pnputil_path(r"C:\Windows", wow64=True), r"C:\Windows\Sysnative\pnputil.exe")

    def test_pnputil_runs_outside_the_app_folder(self):
        import subprocess
        from unittest import mock
        done = subprocess.CompletedProcess(["x"], 0, stdout=b"ok", stderr=b"")
        api = object.__new__(vdd_device.Win32DeviceApi)
        with mock.patch.object(vdd_device.subprocess, "run", return_value=done) as run:
            self.assertEqual(api.pnputil(["/enum-drivers"]), (0, "ok"))
        cwd = run.call_args.kwargs["cwd"]
        self.assertEqual(cwd, vdd_device.tools.tool_cwd(run.call_args.args[0][0]))
        self.assertNotEqual(os.path.realpath(cwd), os.path.realpath(vdd_device.tools.app_dir()))

    def test_error_text_carries_the_windows_code(self):
        error = VddDeviceError("install_driver", 5, "SetupDiCreateDeviceInfoW")
        self.assertEqual(error.winerror, 5)
        self.assertEqual(error.operation, "install_driver")
        self.assertIn("install_driver failed", str(error))
        self.assertIn("SetupDiCreateDeviceInfoW", str(error))
        self.assertIn("Windows error 5", str(error))

    def test_setupapi_codes_are_shown_in_hex(self):
        self.assertIn("0xE000020B", str(VddDeviceError("remove_driver", 0xE000020B)))

    def test_struct_sizes(self):
        self.assertEqual(ctypes.sizeof(vdd_device.GUID), 16)
        self.assertEqual(ctypes.sizeof(vdd_device.SP_DEVINFO_DATA), 32 if ctypes.sizeof(ctypes.c_void_p) == 8 else 28)
        self.assertEqual(ctypes.sizeof(vdd_device.SP_CLASSINSTALL_HEADER), 8)
        self.assertEqual(ctypes.sizeof(vdd_device.SP_REMOVEDEVICE_PARAMS), 16)

    def test_is_admin_asks_the_api(self):
        self.assertFalse(vdd_device.is_admin(api=FakeApi(admin=False)))
        self.assertTrue(vdd_device.is_admin(api=FakeApi(admin=True)))


class Win32RemoveDeviceTest(unittest.TestCase):
    """remove_device does what `devcon remove` does: DIF_REMOVE with global scope through the class installer.

    The SetupAPI functions are replaced by recording fakes: nothing is removed."""

    def make(self, set_ok=1, call_ok=1):
        api = object.__new__(vdd_device.Win32DeviceApi)
        self.calls = []

        def set_params(hset, dev, header, size):
            params = ctypes.cast(header, ctypes.POINTER(vdd_device.SP_REMOVEDEVICE_PARAMS)).contents
            self.calls.append(("SetupDiSetClassInstallParamsW", hset, params.ClassInstallHeader.cbSize,
                               params.ClassInstallHeader.InstallFunction, params.Scope, params.HwProfile, size))
            return set_ok

        def call_installer(function, hset, dev):
            self.calls.append(("SetupDiCallClassInstaller", function, hset))
            return call_ok

        api._f = {"SetupDiSetClassInstallParamsW": set_params, "SetupDiCallClassInstaller": call_installer}
        return api

    def test_sets_global_remove_params_then_calls_the_class_installer(self):
        self.make().remove_device(1234, vdd_device.SP_DEVINFO_DATA())
        self.assertEqual(self.calls, [
            ("SetupDiSetClassInstallParamsW", 1234, 8, vdd_device.DIF_REMOVE, vdd_device.DI_REMOVEDEVICE_GLOBAL, 0, 16),
            ("SetupDiCallClassInstaller", vdd_device.DIF_REMOVE, 1234),
        ])
        self.assertEqual((vdd_device.DIF_REMOVE, vdd_device.DI_REMOVEDEVICE_GLOBAL), (0x05, 0x1))

    def test_failures_raise_with_the_function_name(self):
        with self.assertRaises(VddDeviceError) as caught:
            self.make(set_ok=0).remove_device(1, vdd_device.SP_DEVINFO_DATA())
        self.assertEqual(caught.exception.operation, "SetupDiSetClassInstallParamsW")
        self.assertEqual([c[0] for c in self.calls], ["SetupDiSetClassInstallParamsW"])
        with self.assertRaises(VddDeviceError) as caught:
            self.make(call_ok=0).remove_device(1, vdd_device.SP_DEVINFO_DATA())
        self.assertEqual(caught.exception.operation, "SetupDiCallClassInstaller(DIF_REMOVE)")


class FindDeviceTest(unittest.TestCase):
    def test_finds_device_and_its_driver_package(self):
        self.assertEqual(vdd_device.find_device(this_pc_registry()), VDD_0000)

    def test_ignores_other_root_display_devices(self):
        registry = FakeRegistry({
            ENUM + r"\0000": {"HardwareID": ["Root\\SomethingElse"]},
            ENUM + r"\0001": {"HardwareID": ["root\\mttvdd"]},
        })
        device = vdd_device.find_device(registry)
        self.assertEqual(device.instance_id, r"ROOT\DISPLAY\0001")
        self.assertIsNone(device.driver_key)
        self.assertIsNone(device.inf_name)

    def test_lists_every_duplicate(self):
        registry = this_pc_registry(**{ENUM + r"\0001": {"HardwareID": ["Root\\MttVDD"]}})
        self.assertEqual([d.instance_id for d in vdd_device.find_devices(registry)],
                         [r"ROOT\DISPLAY\0000", r"ROOT\DISPLAY\0001"])

    def test_no_root_display_key_means_no_device(self):
        self.assertIsNone(vdd_device.find_device(FakeRegistry({})))

    def test_unreadable_values_are_tolerated(self):
        registry = FakeRegistry({ENUM + r"\0000": {"HardwareID": None}})
        self.assertIsNone(vdd_device.find_device(registry))


class InstallDriverTest(unittest.TestCase):
    def setUp(self):
        self.inf = Path(tempfile.mkdtemp()) / "MttVDD.inf"
        self.inf.write_text("[Version]\n", encoding="ascii")
        self.empty = FakeRegistry({})

    def test_reboot_required_is_returned(self):
        for reboot in (False, True):
            with self.subTest(reboot=reboot):
                self.assertIs(vdd_device.install_driver(self.inf, api=FakeApi(reboot=reboot), registry=self.empty),
                              reboot)

    def test_creates_root_device_then_installs_driver(self):
        api = FakeApi()
        vdd_device.install_driver(self.inf, api=api, registry=self.empty)
        inf = str(self.inf.resolve())
        self.assertEqual(api.calls, [
            ("is_admin",),
            ("inf_class", inf),
            ("create_info_list", "GUID-DISPLAY"),
            ("create_device_info", "HSET", "Display", "GUID-DISPLAY"),
            ("set_hardware_id", "HSET", "DEV", "Root\\MttVDD"),
            ("register_device", "HSET", "DEV"),
            ("update_driver", "Root\\MttVDD", inf),
            ("destroy_info_list", "HSET"),
        ])

    def test_driver_failure_removes_the_new_device_and_reports_the_code(self):
        # Ex. : l'utilisateur refuse l'invite « SignPath Foundation » ; sans retrait, un nœud sans pilote resterait
        # et la détection croirait le pilote installé.
        api = FakeApi(fail={"update_driver": 1223})
        with self.assertRaises(VddDeviceError) as caught:
            vdd_device.install_driver(self.inf, api=api, registry=self.empty)
        self.assertEqual(caught.exception.winerror, 1223)
        self.assertEqual(caught.exception.operation, "install_driver")
        self.assertEqual(api.names()[-3:], ["update_driver", "remove_device", "destroy_info_list"])

    def test_registration_failure_still_frees_the_list(self):
        api = FakeApi(fail={"register_device": 5})
        with self.assertRaises(VddDeviceError) as caught:
            vdd_device.install_driver(self.inf, api=api, registry=self.empty)
        self.assertEqual(caught.exception.winerror, 5)
        self.assertNotIn("update_driver", api.names())
        self.assertNotIn("remove_device", api.names())
        self.assertEqual(api.names()[-1], "destroy_info_list")

    def test_refuses_when_a_device_already_exists(self):
        # devcon install créait un second adaptateur à chaque appel : on ne le refait pas.
        api = FakeApi()
        with self.assertRaises(VddDeviceError) as caught:
            vdd_device.install_driver(self.inf, api=api, registry=this_pc_registry())
        self.assertEqual(caught.exception.winerror, vdd_device.ERROR_ALREADY_EXISTS)
        self.assertIn(r"ROOT\DISPLAY\0000", str(caught.exception))
        self.assertNotIn("create_device_info", api.names())

    def test_needs_admin(self):
        api = FakeApi(admin=False)
        with self.assertRaises(VddDeviceError) as caught:
            vdd_device.install_driver(self.inf, api=api, registry=self.empty)
        self.assertEqual(caught.exception.winerror, vdd_device.ERROR_ACCESS_DENIED)
        self.assertEqual(api.names(), ["is_admin"])

    def test_missing_inf(self):
        api = FakeApi()
        with self.assertRaises(VddDeviceError) as caught:
            vdd_device.install_driver(self.inf.with_name("absent.inf"), api=api, registry=self.empty)
        self.assertEqual(caught.exception.winerror, vdd_device.ERROR_FILE_NOT_FOUND)
        self.assertNotIn("create_info_list", api.names())


class RemoveDriverTest(unittest.TestCase):
    def test_removes_device_then_deletes_driver_package(self):
        api = FakeApi()
        vdd_device.remove_driver(api=api, registry=this_pc_registry())
        self.assertEqual(api.calls, [
            ("is_admin",),
            ("create_info_list", None),
            ("open_device", "HSET", r"ROOT\DISPLAY\0000"),
            ("remove_device", "HSET", r"DEV:ROOT\DISPLAY\0000"),
            ("destroy_info_list", "HSET"),
            ("pnputil", "/delete-driver", "oem114.inf", "/uninstall"),
        ])

    def test_removes_every_duplicate_and_each_package_once(self):
        registry = this_pc_registry(**{ENUM + r"\0001": {"HardwareID": ["Root\\MttVDD"],
                                                          "Driver": DISPLAY_GUID + r"\0004"}})
        api = FakeApi()
        vdd_device.remove_driver(api=api, registry=registry)
        removed = [c[2] for c in api.calls if c[0] == "open_device"]
        self.assertEqual(removed, [r"ROOT\DISPLAY\0000", r"ROOT\DISPLAY\0001"])
        self.assertEqual([c for c in api.calls if c[0] == "pnputil"],
                         [("pnputil", "/delete-driver", "oem114.inf", "/uninstall")])

    def test_nothing_installed_is_not_an_error(self):
        api = FakeApi()
        vdd_device.remove_driver(api=api, registry=FakeRegistry({}))
        self.assertEqual(api.names(), ["is_admin"])

    def test_device_removal_failure_keeps_the_driver_package(self):
        api = FakeApi(fail={"remove_device": 0xE000020B})
        with self.assertRaises(VddDeviceError) as caught:
            vdd_device.remove_driver(api=api, registry=this_pc_registry())
        self.assertEqual(caught.exception.winerror, 0xE000020B)
        self.assertEqual(caught.exception.operation, "remove_driver")
        self.assertNotIn("pnputil", api.names())
        self.assertEqual(api.names()[-1], "destroy_info_list")

    def test_pnputil_failure_raises_with_its_exit_code(self):
        api = FakeApi(pnputil_results=[(2, "Échec de la suppression du package de pilotes")])
        with self.assertRaises(VddDeviceError) as caught:
            vdd_device.remove_driver(api=api, registry=this_pc_registry())
        self.assertEqual(caught.exception.winerror, 2)
        self.assertIn("Échec", str(caught.exception))

    def test_reboot_required_counts_as_success(self):
        vdd_device.remove_driver(api=FakeApi(pnputil_results=[(3010, "")]), registry=this_pc_registry())

    def test_suspicious_inf_name_is_never_passed_to_pnputil(self):
        registry = this_pc_registry(**{CLASS + "\\" + DISPLAY_GUID + r"\0004": {"InfPath": "mttvdd.inf"}})
        api = FakeApi()
        vdd_device.remove_driver(api=api, registry=registry)
        self.assertIn("remove_device", api.names())
        self.assertNotIn("pnputil", api.names())

    def test_needs_admin(self):
        api = FakeApi(admin=False)
        with self.assertRaises(VddDeviceError):
            vdd_device.remove_driver(api=api, registry=this_pc_registry())
        self.assertEqual(api.names(), ["is_admin"])


class RestartDeviceTest(unittest.TestCase):
    def test_restarts_by_instance_id(self):
        api = FakeApi()
        vdd_device.restart_device(api=api, registry=this_pc_registry())
        self.assertEqual(api.calls, [("is_admin",), ("pnputil", "/restart-device", r"ROOT\DISPLAY\0000")])

    def test_no_device_raises_not_found(self):
        with self.assertRaises(VddDeviceError) as caught:
            vdd_device.restart_device(api=FakeApi(), registry=FakeRegistry({}))
        self.assertEqual(caught.exception.winerror, vdd_device.ERROR_NOT_FOUND)

    def test_failure_raises_with_exit_code(self):
        with self.assertRaises(VddDeviceError) as caught:
            vdd_device.restart_device(api=FakeApi(pnputil_results=[(5, "Accès refusé")]),
                                      registry=this_pc_registry())
        self.assertEqual(caught.exception.winerror, 5)
        self.assertEqual(caught.exception.operation, "restart_device")

    def test_needs_admin(self):
        api = FakeApi(admin=False)
        with self.assertRaises(VddDeviceError):
            vdd_device.restart_device(api=api, registry=this_pc_registry())
        self.assertEqual(api.names(), ["is_admin"])


@unittest.skipUnless(os.name == "nt", "registre Windows uniquement")
class RealRegistrySmokeTest(unittest.TestCase):
    """Read-only: scans HKLM for the VDD device installed on the developer's PC."""

    def test_finds_the_installed_vdd(self):
        device = vdd_device.find_device()
        if device is None and not Path(r"C:\VirtualDisplayDriver").exists():
            self.skipTest("VDD not installed on this PC")
        self.assertIsNotNone(device)
        self.assertIn("root\\mttvdd", [h.lower() for h in device.hardware_ids])
        self.assertTrue(device.instance_id.upper().startswith("ROOT\\DISPLAY\\"))

    def test_win32_layer_binds_its_functions(self):
        # Charge setupapi/newdev et pose les signatures ; seul is_admin() est appelé (lecture seule).
        api = vdd_device.Win32DeviceApi()
        self.assertIsInstance(api.is_admin(), bool)


if __name__ == "__main__":
    unittest.main()
