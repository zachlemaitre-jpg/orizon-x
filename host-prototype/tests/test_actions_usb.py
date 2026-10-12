import ctypes
import os
import unittest

from actions import usb
from actions.base import ProviderError
from actions.usb import UsbError, UsbProvider

DISK = usb.FILE_DEVICE_DISK


class FakeUsbApi:
    """Simulated Win32 layer.

    drives = {"E": {"type": DRIVE_REMOVABLE, "bus": BusTypeUsb, "label": "KINGSTON", "free": 1, "total": 2,
                    "number": (FILE_DEVICE_DISK, 2, 1)}}
    disks = [(devinst, interface path, (device type, device number))]
    parents = {devinst: parent devinst}
    eject_results = list of (CONFIGRET, veto type, veto name), consumed one per attempt (last one repeats).
    fail = {method name: error code} makes that method raise UsbError.
    """

    def __init__(self, drives=None, disks=None, parents=None, eject_results=None, fail=None):
        self.drives = drives or {}
        self.disks = disks or []
        self.parents = parents or {}
        self.eject_results = list(eject_results or [(usb.CR_SUCCESS, usb.PNP_VetoTypeUnknown, "")])
        self.fail = fail or {}
        self.calls = []
        self.opened = []

    def _call(self, name, *args):
        self.calls.append((name,) + args)
        if name in self.fail:
            raise UsbError(name, self.fail[name])

    def logical_drives(self):
        self._call("logical_drives")
        mask = 0
        for letter in self.drives:
            mask |= 1 << (ord(letter) - ord("A"))
        return mask

    def drive_type(self, root):
        self._call("drive_type", root)
        return self.drives[root[0]]["type"]

    def bus_type(self, device_path):
        self._call("bus_type", device_path)
        drive = self.drives[device_path[4]]
        if drive.get("bus") is None:
            raise UsbError("DeviceIoControl(IOCTL_STORAGE_QUERY_PROPERTY)", 1)
        return drive["bus"]

    def volume_label(self, root):
        self._call("volume_label", root)
        return self.drives[root[0]].get("label", "")

    def disk_space(self, root):
        self._call("disk_space", root)
        drive = self.drives[root[0]]
        if drive.get("no_media"):
            raise UsbError("GetDiskFreeSpaceExW", 21)
        return drive["free"], drive["total"]

    def device_number(self, path):
        self._call("device_number", path)
        if path.startswith("\\\\.\\") and len(path) == 6:
            number = self.drives[path[4]].get("number")
        else:
            number = next((d[2] + (0,) for d in self.disks if d[1] == path), None)
        if number is None:
            raise UsbError("DeviceIoControl(IOCTL_STORAGE_GET_DEVICE_NUMBER)", 1)
        return number

    def disk_interfaces(self):
        self._call("disk_interfaces")
        return [(devinst, path) for devinst, path, _number in self.disks]

    def get_parent(self, devinst):
        self._call("get_parent", devinst)
        return self.parents[devinst]

    def request_eject(self, devinst):
        self._call("request_eject", devinst)
        if len(self.eject_results) > 1:
            return self.eject_results.pop(0)
        return self.eject_results[0]

    def removable_media(self, device_path):
        self._call("removable_media", device_path)
        return self.drives[device_path[4]].get("removable", False)

    def startfile(self, path):
        self._call("startfile", path)
        self.opened.append(path)


def kingston(**extra):
    drive = {"type": usb.DRIVE_REMOVABLE, "bus": usb.BusTypeUsb, "label": "KINGSTON",
             "free": 12884901888, "total": 31914983424, "number": (DISK, 2, 1)}
    drive.update(extra)
    return drive


def this_pc(**drives):
    """C: = internal NVMe system disk (disk 0), D: = SATA data disk (disk 1), plus the given drives."""
    layout = {
        "C": {"type": usb.DRIVE_FIXED, "bus": usb.BusTypeNvme, "label": "Windows", "free": 1, "total": 2,
              "number": (DISK, 0, 3)},
        "D": {"type": usb.DRIVE_FIXED, "bus": usb.BusTypeSata, "label": "Data", "free": 3, "total": 4,
              "number": (DISK, 1, 1)},
    }
    layout.update(drives)
    return layout


DISKS = [
    (100, r"\\?\scsi#disk&ven_nvme#0", (DISK, 0)),
    (101, r"\\?\scsi#disk&ven_sata#1", (DISK, 1)),
    (102, r"\\?\usbstor#disk&ven_kingston#2", (DISK, 2)),
]
PARENTS = {100: 10, 101: 11, 102: 12}


def provider(api, **kwargs):
    kwargs.setdefault("sleep", lambda _s: None)
    return UsbProvider(api=api, **kwargs)


class SnapshotTests(unittest.TestCase):
    def test_lists_usb_drives_with_label_and_space(self):
        api = FakeUsbApi(drives=this_pc(E=kingston()))
        self.assertEqual(provider(api).snapshot(), {"available": True, "drives": [
            {"drive": "E:", "label": "KINGSTON", "free_bytes": 12884901888, "total_bytes": 31914983424,
             "kind": "stick"}]})

    def test_non_usb_drives_are_excluded(self):
        api = FakeUsbApi(drives=this_pc(
            F={"type": usb.DRIVE_REMOVABLE, "bus": usb.BusTypeSd, "label": "SDCARD", "free": 1, "total": 2},
            G={"type": usb.DRIVE_CDROM, "bus": usb.BusTypeUsb, "label": "DVD", "free": 0, "total": 5},
            Z={"type": usb.DRIVE_REMOTE, "bus": usb.BusTypeUsb, "label": "share", "free": 1, "total": 2}))
        self.assertEqual(provider(api).snapshot(), {"available": True, "drives": []})
        # Optical and network drives are never even opened.
        self.assertNotIn(("bus_type", "\\\\.\\G:"), api.calls)
        self.assertNotIn(("bus_type", "\\\\.\\Z:"), api.calls)

    def test_usb_fixed_disk_is_listed(self):
        api = FakeUsbApi(drives=this_pc(H=kingston(type=usb.DRIVE_FIXED, label="", free=5, total=9)))
        self.assertEqual(provider(api).snapshot()["drives"],
                         [{"drive": "H:", "label": "", "free_bytes": 5, "total_bytes": 9, "kind": "disk"}])

    def kinds(self, **drives):
        return {d["drive"]: d["kind"] for d in provider(FakeUsbApi(drives=this_pc(**drives))).snapshot()["drives"]}

    def test_kind_removable_drive_type_is_a_stick(self):
        self.assertEqual(self.kinds(E=kingston()), {"E:": "stick"})

    def test_kind_fixed_drive_reporting_removable_media_is_a_stick(self):
        self.assertEqual(self.kinds(E=kingston(type=usb.DRIVE_FIXED, removable=True)), {"E:": "stick"})

    def test_kind_fixed_drive_with_fixed_media_is_a_disk(self):
        self.assertEqual(self.kinds(H=kingston(type=usb.DRIVE_FIXED, removable=False)), {"H:": "disk"})

    def test_kind_removable_drive_type_wins_over_descriptor(self):
        self.assertEqual(self.kinds(E=kingston(removable=False)), {"E:": "stick"})

    def test_kind_mixed_drives(self):
        self.assertEqual(self.kinds(E=kingston(), H=kingston(type=usb.DRIVE_FIXED), G=kingston(
            type=usb.DRIVE_FIXED, removable=True)), {"E:": "stick", "G:": "stick", "H:": "disk"})

    def test_kind_descriptor_failure_on_fixed_drive_falls_back_to_disk(self):
        api = FakeUsbApi(drives=this_pc(H=kingston(type=usb.DRIVE_FIXED, removable=True)),
                         fail={"removable_media": 1})
        self.assertEqual(provider(api).snapshot()["drives"],
                         [dict(drive="H:", label="KINGSTON", free_bytes=12884901888, total_bytes=31914983424,
                               kind="disk")])

    def test_drives_sorted_by_letter(self):
        api = FakeUsbApi(drives=this_pc(G=kingston(label="B"), E=kingston(label="A")))
        self.assertEqual([d["drive"] for d in provider(api).snapshot()["drives"]], ["E:", "G:"])

    def test_bus_query_failure_skips_drive(self):
        api = FakeUsbApi(drives=this_pc(E=kingston(bus=None)))
        self.assertEqual(provider(api).snapshot()["drives"], [])

    def test_empty_card_reader_slot_is_skipped(self):
        api = FakeUsbApi(drives=this_pc(E=kingston(no_media=True)))
        self.assertEqual(provider(api).snapshot()["drives"], [])

    def test_label_failure_gives_empty_label(self):
        api = FakeUsbApi(drives=this_pc(E=kingston()), fail={"volume_label": 1})
        self.assertEqual(provider(api).snapshot()["drives"][0]["label"], "")

    def test_no_drive_at_all(self):
        self.assertEqual(provider(FakeUsbApi()).snapshot(), {"available": True, "drives": []})

    def test_logical_drives_failure_raises(self):
        # The hub turns a raising provider into an unavailable one.
        api = FakeUsbApi(drives=this_pc(), fail={"logical_drives": 5})
        with self.assertRaises(UsbError):
            provider(api).snapshot()
        self.assertTrue(issubclass(UsbError, ProviderError))


class OpenTests(unittest.TestCase):
    def test_open_starts_explorer_on_root(self):
        api = FakeUsbApi(drives=this_pc(E=kingston()))
        self.assertIsNone(provider(api).handle({"id": "usb.open", "drive": "E:"}))
        self.assertEqual(api.opened, ["E:\\"])

    def test_open_accepts_lowercase_and_backslash(self):
        for drive in ("e:", "E:\\", "e"):
            api = FakeUsbApi(drives=this_pc(E=kingston()))
            self.assertIsNone(provider(api).handle({"id": "usb.open", "drive": drive}), drive)
            self.assertEqual(api.opened, ["E:\\"], drive)

    def test_open_refuses_non_usb_drive(self):
        api = FakeUsbApi(drives=this_pc())
        self.assertEqual(provider(api).handle({"id": "usb.open", "drive": "C:"}), "usb_failed")
        self.assertEqual(api.opened, [])

    def test_open_refuses_unknown_or_malformed_drive(self):
        for drive in ("Q:", "C:\\Windows", "..", "", None, 5, "EE:"):
            api = FakeUsbApi(drives=this_pc(E=kingston()))
            self.assertEqual(provider(api).handle({"id": "usb.open", "drive": drive}), "usb_failed", drive)
            self.assertEqual(api.opened, [], drive)
        api = FakeUsbApi(drives=this_pc(E=kingston()))
        self.assertEqual(provider(api).handle({"id": "usb.open"}), "usb_failed")

    def test_open_failure(self):
        api = FakeUsbApi(drives=this_pc(E=kingston()), fail={"startfile": 2})
        self.assertEqual(provider(api).handle({"id": "usb.open", "drive": "E:"}), "usb_failed")

    def test_startfile_oserror_is_failure(self):
        class Raising(FakeUsbApi):
            def startfile(self, path):
                raise OSError(2, "not found")

        api = Raising(drives=this_pc(E=kingston()))
        self.assertEqual(provider(api).handle({"id": "usb.open", "drive": "E:"}), "usb_failed")


class EjectTests(unittest.TestCase):
    def api(self, **kwargs):
        kwargs.setdefault("drives", this_pc(E=kingston()))
        kwargs.setdefault("disks", DISKS)
        kwargs.setdefault("parents", PARENTS)
        return FakeUsbApi(**kwargs)

    def ejected(self, api):
        return [call[1] for call in api.calls if call[0] == "request_eject"]

    def test_success_ejects_parent_of_matching_disk(self):
        api = self.api()
        self.assertIsNone(provider(api).handle({"id": "usb.eject", "drive": "E:"}))
        self.assertIn(("device_number", "\\\\.\\E:"), api.calls)
        self.assertIn(("get_parent", 102), api.calls)
        self.assertEqual(self.ejected(api), [12])

    def test_veto_is_busy(self):
        api = self.api(eject_results=[(usb.CR_REMOVE_VETOED, usb.PNP_VetoOutstandingOpen, r"\Device\HarddiskVolume9")])
        self.assertEqual(provider(api).handle({"id": "usb.eject", "drive": "E:"}), "usb_busy")
        self.assertEqual(self.ejected(api), [12] * usb.EJECT_ATTEMPTS)

    def test_veto_with_success_code_is_busy(self):
        # CM_Request_Device_EjectW can return CR_SUCCESS and still fill in a veto.
        api = self.api(eject_results=[(usb.CR_SUCCESS, usb.PNP_VetoWindowsApp, "explorer.exe")])
        self.assertEqual(provider(api).handle({"id": "usb.eject", "drive": "E:"}), "usb_busy")

    def test_transient_veto_then_success(self):
        sleeps = []
        api = self.api(eject_results=[(usb.CR_REMOVE_VETOED, usb.PNP_VetoOutstandingOpen, ""),
                                      (usb.CR_SUCCESS, usb.PNP_VetoTypeUnknown, "")])
        result = UsbProvider(api=api, sleep=sleeps.append).handle({"id": "usb.eject", "drive": "E:"})
        self.assertIsNone(result)
        self.assertEqual(self.ejected(api), [12, 12])
        self.assertEqual(len(sleeps), 1)

    def test_already_removed_is_success(self):
        api = self.api(eject_results=[(usb.CR_REMOVE_VETOED, usb.PNP_VetoAlreadyRemoved, "")])
        self.assertIsNone(provider(api).handle({"id": "usb.eject", "drive": "E:"}))

    def test_other_configret_is_failed(self):
        api = self.api(eject_results=[(0x0D, usb.PNP_VetoTypeUnknown, "")])  # CR_NO_SUCH_DEVNODE
        self.assertEqual(provider(api).handle({"id": "usb.eject", "drive": "E:"}), "usb_failed")
        self.assertEqual(self.ejected(api), [12])  # no retry on a plain failure

    def test_unknown_drive_is_failed(self):
        api = self.api()
        self.assertEqual(provider(api).handle({"id": "usb.eject", "drive": "Q:"}), "usb_failed")
        self.assertEqual(self.ejected(api), [])

    def test_non_usb_drive_is_never_ejected(self):
        api = self.api()
        self.assertEqual(provider(api).handle({"id": "usb.eject", "drive": "C:"}), "usb_failed")
        self.assertEqual(self.ejected(api), [])

    def test_no_matching_disk_interface_is_failed(self):
        api = self.api(disks=DISKS[:2])
        self.assertEqual(provider(api).handle({"id": "usb.eject", "drive": "E:"}), "usb_failed")
        self.assertEqual(self.ejected(api), [])

    def test_unreadable_interface_is_skipped(self):
        broken = (99, r"\\?\broken", None)

        class Api(FakeUsbApi):
            def device_number(self, path):
                if path == broken[1]:
                    raise UsbError("CreateFileW", 5)
                return super().device_number(path)

        api = Api(drives=this_pc(E=kingston()), disks=[broken] + DISKS, parents=PARENTS)
        self.assertIsNone(provider(api).handle({"id": "usb.eject", "drive": "E:"}))
        self.assertEqual(self.ejected(api), [12])

    def test_volume_number_failure_is_failed(self):
        api = self.api(drives=this_pc(E=kingston(number=None)))
        self.assertEqual(provider(api).handle({"id": "usb.eject", "drive": "E:"}), "usb_failed")

    def test_non_disk_device_type_is_failed(self):
        api = self.api(drives=this_pc(E=kingston(number=(usb.FILE_DEVICE_CD_ROM, 2, 0))))
        self.assertEqual(provider(api).handle({"id": "usb.eject", "drive": "E:"}), "usb_failed")
        self.assertEqual(self.ejected(api), [])

    def test_enumeration_failure_is_failed(self):
        api = self.api(fail={"disk_interfaces": 13})
        self.assertEqual(provider(api).handle({"id": "usb.eject", "drive": "E:"}), "usb_failed")

    def test_parent_failure_is_failed(self):
        api = self.api(fail={"get_parent": 0x0D})
        self.assertEqual(provider(api).handle({"id": "usb.eject", "drive": "E:"}), "usb_failed")
        self.assertEqual(self.ejected(api), [])

    def test_failures_are_logged(self):
        lines = []
        api = self.api(eject_results=[(usb.CR_REMOVE_VETOED, usb.PNP_VetoOutstandingOpen, "explorer.exe")])
        UsbProvider(api=api, sleep=lambda _s: None, log=lines.append).handle({"id": "usb.eject", "drive": "E:"})
        self.assertTrue(any("E:" in line and "explorer.exe" in line for line in lines), lines)


class HandleTests(unittest.TestCase):
    def test_unknown_id_is_ignored(self):
        lines = []
        api = FakeUsbApi(drives=this_pc(E=kingston()))
        self.assertIsNone(UsbProvider(api=api, log=lines.append).handle({"id": "usb.format", "drive": "E:"}))
        self.assertEqual(api.opened, [])
        self.assertNotIn("request_eject", [c[0] for c in api.calls])
        self.assertTrue(lines)


class PureTests(unittest.TestCase):
    def test_normalize_drive(self):
        self.assertEqual(usb.normalize_drive("e:"), "E")
        self.assertEqual(usb.normalize_drive("E:\\"), "E")
        self.assertEqual(usb.normalize_drive("e"), "E")
        for bad in ("", "1:", "EE", "E:/x", "C:\\Windows", None, 3, "é:"):
            self.assertIsNone(usb.normalize_drive(bad), bad)

    def test_letters(self):
        self.assertEqual(usb.letters(0b10101), ["A", "C", "E"])
        self.assertEqual(usb.letters(1 << 25), ["Z"])
        self.assertEqual(usb.letters(0), [])

    def test_veto_name(self):
        self.assertEqual(usb.veto_name(usb.PNP_VetoOutstandingOpen), "PNP_VetoOutstandingOpen")
        self.assertEqual(usb.veto_name(99), "veto 99")


class StructTests(unittest.TestCase):
    def test_struct_sizes(self):
        x64 = ctypes.sizeof(ctypes.c_void_p) == 8
        self.assertEqual(ctypes.sizeof(usb.GUID), 16)
        self.assertEqual(ctypes.sizeof(usb.STORAGE_DEVICE_NUMBER), 12)
        self.assertEqual(ctypes.sizeof(usb.STORAGE_PROPERTY_QUERY), 12)
        self.assertEqual(ctypes.sizeof(usb.STORAGE_DEVICE_DESCRIPTOR), 40)
        self.assertEqual(usb.STORAGE_DEVICE_DESCRIPTOR.BusType.offset, 28)
        self.assertEqual(ctypes.sizeof(usb.SP_DEVINFO_DATA), 32 if x64 else 28)
        self.assertEqual(ctypes.sizeof(usb.SP_DEVICE_INTERFACE_DATA), 32 if x64 else 28)
        self.assertEqual(usb.interface_detail_cbsize(), 8 if x64 else 6)

    def test_constants(self):
        self.assertEqual(usb.IOCTL_STORAGE_QUERY_PROPERTY, 0x2D1400)
        self.assertEqual(usb.IOCTL_STORAGE_GET_DEVICE_NUMBER, 0x2D1080)
        self.assertEqual(usb.BusTypeUsb, 7)
        guid = usb.GUID_DEVINTERFACE_DISK
        self.assertEqual((guid.Data1, guid.Data2, guid.Data3, bytes(guid.Data4)),
                         (0x53F56307, 0xB6BF, 0x11D0, bytes.fromhex("94f200a0c91efb8b")))

    def test_parse_bus_type(self):
        descriptor = usb.STORAGE_DEVICE_DESCRIPTOR()
        descriptor.Version = descriptor.Size = 40
        descriptor.BusType = usb.BusTypeUsb
        buffer = bytes(descriptor) + b"\0" * 100
        self.assertEqual(usb.parse_bus_type(buffer, len(buffer)), usb.BusTypeUsb)
        with self.assertRaises(UsbError):
            usb.parse_bus_type(buffer, 20)  # too short to hold BusType


class RemovableMediaDescriptorTests(unittest.TestCase):
    def descriptor(self, removable):
        descriptor = usb.STORAGE_DEVICE_DESCRIPTOR()
        descriptor.Version = descriptor.Size = 40
        descriptor.RemovableMedia = removable
        descriptor.BusType = usb.BusTypeUsb
        return bytes(descriptor) + b"\0" * 100

    def test_offset(self):
        self.assertEqual(usb.STORAGE_DEVICE_DESCRIPTOR.RemovableMedia.offset, 10)

    def test_parse_removable_media(self):
        for flag, expected in ((1, True), (0, False)):
            buffer = self.descriptor(flag)
            self.assertIs(usb.parse_removable_media(buffer, len(buffer)), expected)

    def test_parse_removable_media_reads_the_byte_at_offset_10(self):
        raw = bytearray(40)
        raw[10] = 1
        self.assertTrue(usb.parse_removable_media(bytes(raw), 40))
        raw[10], raw[9], raw[11] = 0, 1, 1  # neighbours (DeviceTypeModifier, CommandQueueing) do not count
        self.assertFalse(usb.parse_removable_media(bytes(raw), 40))

    def test_parse_removable_media_too_short(self):
        with self.assertRaises(UsbError):
            usb.parse_removable_media(self.descriptor(1), 10)


@unittest.skipUnless(os.name == "nt", "Windows only")
class RealWindowsReadOnlyTests(unittest.TestCase):
    """Read-only: lists this PC's drives. Never opens, never ejects."""

    def test_win32_api_loads_and_lists(self):
        snapshot = UsbProvider().snapshot()
        self.assertIs(snapshot["available"], True)
        for drive in snapshot["drives"]:
            self.assertRegex(drive["drive"], r"^[A-Z]:$")
            self.assertIsInstance(drive["label"], str)
            self.assertLessEqual(drive["free_bytes"], drive["total_bytes"])
            self.assertIn(drive["kind"], ("stick", "disk"))

    def test_system_drive_is_not_usb(self):
        system = os.environ.get("SystemDrive", "C:")
        drives = [d["drive"] for d in UsbProvider().snapshot()["drives"]]
        self.assertNotIn(system.upper(), drives)

    def test_real_disk_interfaces_resolve(self):
        api = usb.Win32UsbApi()
        interfaces = api.disk_interfaces()
        self.assertTrue(interfaces)
        devinst, path = interfaces[0]
        self.assertIsInstance(devinst, int)
        self.assertTrue(path.startswith("\\\\?\\"))
        self.assertIsInstance(api.get_parent(devinst), int)


if __name__ == "__main__":
    unittest.main()
