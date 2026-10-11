import ctypes
import importlib.util
import sys
import unittest

from actions import bt_info, wifi_info
from actions.base import ProviderError
from actions.bt_info import BluetoothInfoProvider
from actions.wifi_info import WifiInfoProvider, WlanError

HAS_ENUMERATION = importlib.util.find_spec("winrt") is not None and \
    importlib.util.find_spec("winrt.windows.devices.enumeration") is not None

GUID_A = "{00000000-0000-0000-0000-00000000000a}"
GUID_B = "{00000000-0000-0000-0000-00000000000b}"


class FakeWlan:
    """wlanapi stand-in: interfaces = [(guid, state)], ssids = {guid: bytes | WlanError}."""

    def __init__(self, interfaces=(), ssids=None, open_error=None):
        self.interfaces = list(interfaces)
        self.ssids = ssids or {}
        self.open_error = open_error
        self.opened = 0
        self.closed = 0
        self.queried = []

    def open(self):
        if self.open_error:
            raise self.open_error
        self.opened += 1
        return "H"

    def enum_interfaces(self, handle):
        assert handle == "H"
        return list(self.interfaces)

    def current_ssid(self, handle, guid):
        assert handle == "H"
        self.queried.append(guid)
        value = self.ssids[guid]
        if isinstance(value, Exception):
            raise value
        return value

    def close(self, handle):
        assert handle == "H"
        self.closed += 1


CONNECTED, DISCONNECTED = wifi_info.WLAN_INTERFACE_STATE_CONNECTED, 4


class WifiInfoTest(unittest.TestCase):
    def test_ssid_of_the_connected_interface(self):
        wlan = FakeWlan([(GUID_A, CONNECTED)], {GUID_A: b"Maison"})
        self.assertEqual(WifiInfoProvider(wlan).snapshot(), {"available": True, "ssid": "Maison"})
        self.assertEqual((wlan.opened, wlan.closed), (1, 1))

    def test_no_interface_gives_empty_ssid(self):
        self.assertEqual(WifiInfoProvider(FakeWlan()).snapshot(), {"available": True, "ssid": ""})

    def test_disconnected_interface_is_not_queried(self):
        wlan = FakeWlan([(GUID_A, DISCONNECTED)], {GUID_A: b"Old"})
        self.assertEqual(WifiInfoProvider(wlan).snapshot()["ssid"], "")
        self.assertEqual(wlan.queried, [])

    def test_first_connected_interface_wins(self):
        wlan = FakeWlan([(GUID_A, DISCONNECTED), (GUID_B, CONNECTED)], {GUID_A: b"A", GUID_B: b"Bureau"})
        self.assertEqual(WifiInfoProvider(wlan).snapshot()["ssid"], "Bureau")

    def test_query_refused_gives_empty_ssid_and_still_closes(self):
        # Windows 11 24H2+ : sans l'autorisation de localisation, WlanQueryInterface renvoie ERROR_ACCESS_DENIED.
        wlan = FakeWlan([(GUID_A, CONNECTED)], {GUID_A: WlanError("WlanQueryInterface", 5)})
        self.assertEqual(WifiInfoProvider(wlan).snapshot(), {"available": True, "ssid": ""})
        self.assertEqual(wlan.closed, 1)

    def test_query_refused_on_one_interface_tries_the_next(self):
        wlan = FakeWlan([(GUID_A, CONNECTED), (GUID_B, CONNECTED)],
                        {GUID_A: WlanError("WlanQueryInterface", 5), GUID_B: b"Bureau"})
        self.assertEqual(WifiInfoProvider(wlan).snapshot()["ssid"], "Bureau")

    def test_utf8_ssid_and_invalid_bytes(self):
        wlan = FakeWlan([(GUID_A, CONNECTED)], {GUID_A: "Café".encode()})
        self.assertEqual(WifiInfoProvider(wlan).snapshot()["ssid"], "Café")
        wlan = FakeWlan([(GUID_A, CONNECTED)], {GUID_A: b"\xffAB"})
        self.assertEqual(WifiInfoProvider(wlan).snapshot()["ssid"], "�AB")

    def test_wlan_service_not_running_is_unavailable(self):
        wlan = FakeWlan(open_error=WlanError("WlanOpenHandle", wifi_info.ERROR_SERVICE_NOT_ACTIVE))
        self.assertEqual(WifiInfoProvider(wlan).snapshot(), {"available": False})

    def test_other_open_failure_is_a_provider_error(self):
        wlan = FakeWlan(open_error=WlanError("WlanOpenHandle", 87))
        with self.assertRaises(ProviderError):
            WifiInfoProvider(wlan).snapshot()

    def test_enumeration_failure_is_a_provider_error_and_closes(self):
        wlan = FakeWlan()
        wlan.enum_interfaces = lambda handle: (_ for _ in ()).throw(WlanError("WlanEnumInterfaces", 8))
        with self.assertRaises(ProviderError):
            WifiInfoProvider(wlan).snapshot()
        self.assertEqual(wlan.closed, 1)

    def test_without_wlanapi_the_provider_is_unavailable(self):
        self.assertEqual(WifiInfoProvider(wlan=None).snapshot(), {"available": False})

    def test_no_action_any_id_is_logged_and_ignored(self):
        wlan = FakeWlan([(GUID_A, CONNECTED)], {GUID_A: b"Maison"})
        with self.assertLogs("orizonx.actions.wifi_info", level="WARNING") as logs:
            self.assertIsNone(WifiInfoProvider(wlan).handle({"id": "wifi.set", "value": True}))
        self.assertIn("wifi.set", logs.output[0])
        self.assertEqual(wlan.opened, 0)

    def test_wlan_error_is_a_provider_error_with_its_code(self):
        e = WlanError("WlanOpenHandle", 1062)
        self.assertIsInstance(e, ProviderError)
        self.assertEqual(e.code, 1062)


class WlanStructTest(unittest.TestCase):
    """The ctypes layout of WLAN_CONNECTION_ATTRIBUTES (wlanapi.h) and the SSID extraction."""

    def test_layout(self):
        attrs = wifi_info.WLAN_CONNECTION_ATTRIBUTES
        # isState, wlanConnectionMode (2 DWORD) + strProfileName WCHAR[256]
        self.assertEqual(attrs.wlanAssociationAttributes.offset, 8 + 512)
        assoc = wifi_info.WLAN_ASSOCIATION_ATTRIBUTES
        self.assertEqual(assoc.dot11Ssid.offset, 0)
        self.assertEqual(ctypes.sizeof(wifi_info.DOT11_SSID), 36)
        self.assertEqual(ctypes.sizeof(assoc), 36 + 4 + 6 + 2 + 4 * 5)
        self.assertEqual(ctypes.sizeof(attrs), 520 + ctypes.sizeof(assoc) + 16)
        self.assertEqual(ctypes.sizeof(wifi_info.WLAN_INTERFACE_INFO), 16 + 512 + 4)

    def test_ssid_bytes_uses_the_length(self):
        attrs = wifi_info.WLAN_CONNECTION_ATTRIBUTES()
        ssid = attrs.wlanAssociationAttributes.dot11Ssid
        ssid.uSSIDLength = 6
        ctypes.memmove(ssid.ucSSID, b"Maison\0junk", 11)
        self.assertEqual(wifi_info.ssid_bytes(attrs), b"Maison")

    def test_ssid_bytes_clamps_a_bad_length(self):
        attrs = wifi_info.WLAN_CONNECTION_ATTRIBUTES()
        ssid = attrs.wlanAssociationAttributes.dot11Ssid
        ssid.uSSIDLength = 200
        ctypes.memmove(ssid.ucSSID, b"x" * 32, 32)
        self.assertEqual(wifi_info.ssid_bytes(attrs), b"x" * 32)


@unittest.skipUnless(sys.platform == "win32", "wlanapi is Windows only")
class RealWifiReadOnlyTest(unittest.TestCase):
    def test_snapshot(self):
        snap = WifiInfoProvider().snapshot()
        self.assertIn("available", snap)
        if snap["available"]:
            self.assertIsInstance(snap["ssid"], str)


class FakeBluetooth:
    def __init__(self, endpoints=(), error=None):
        self.list = list(endpoints)
        self.error = error

    def endpoints(self):
        if self.error:
            raise self.error
        return list(self.list)


class BluetoothInfoTest(unittest.TestCase):
    def test_only_connected_devices(self):
        api = FakeBluetooth([("Casque", True), ("Clavier", False), ("Souris", None)])
        self.assertEqual(BluetoothInfoProvider(api).snapshot(), {"available": True, "connected": ["Casque"]})

    def test_names_are_deduplicated_and_sorted(self):
        # un appareil classique + BLE apparaît deux fois
        api = FakeBluetooth([("MX Master 4", True), ("buds", True), ("MX Master 4", True), ("Alpha", True)])
        self.assertEqual(BluetoothInfoProvider(api).snapshot()["connected"], ["Alpha", "buds", "MX Master 4"])

    def test_blank_names_are_skipped(self):
        api = FakeBluetooth([("", True), ("  ", True), (" Casque ", True)])
        self.assertEqual(BluetoothInfoProvider(api).snapshot()["connected"], ["Casque"])

    def test_nothing_connected(self):
        self.assertEqual(BluetoothInfoProvider(FakeBluetooth()).snapshot(), {"available": True, "connected": []})

    def test_query_failure_is_a_provider_error(self):
        for error in (OSError("0x8007048F"), TimeoutError()):
            with self.assertRaises(ProviderError):
                BluetoothInfoProvider(FakeBluetooth(error=error)).snapshot()

    def test_without_winrt_the_provider_is_unavailable(self):
        self.assertEqual(BluetoothInfoProvider(api=None).snapshot(), {"available": False})

    def test_no_action_any_id_is_logged_and_ignored(self):
        with self.assertLogs("orizonx.actions.bt_info", level="WARNING") as logs:
            self.assertIsNone(BluetoothInfoProvider(FakeBluetooth()).handle({"id": "bluetooth.set"}))
        self.assertIn("bluetooth.set", logs.output[0])

    def test_aqs_selects_paired_or_cached_bluetooth_and_ble_without_inquiry(self):
        aqs = bt_info.CONNECTED_AQS
        self.assertIn('System.Devices.Aep.ProtocolId:="{e0cbf06c-cd8b-4647-bb8a-263b43f0f974}"', aqs)  # classique
        self.assertIn('System.Devices.Aep.ProtocolId:="{bb7bb05e-5972-42b5-94fc-76eaa7084d49}"', aqs)  # BLE
        # Sans IssueInquiry:=False, FindAllAsync lance une recherche Bluetooth et ne finit pas avant ~20 s.
        self.assertIn("System.Devices.Aep.Bluetooth.IssueInquiry:=System.StructuredQueryType.Boolean#False", aqs)
        self.assertIn("System.Devices.Aep.IsConnected:=System.StructuredQueryType.Boolean#True", aqs)
        self.assertEqual(bt_info.IS_CONNECTED, "System.Devices.Aep.IsConnected")


@unittest.skipUnless(HAS_ENUMERATION, "winrt Windows.Devices.Enumeration not installed")
class RealBluetoothReadOnlyTest(unittest.TestCase):
    def test_snapshot(self):
        snap = BluetoothInfoProvider().snapshot()
        self.assertTrue(snap["available"])
        self.assertTrue(all(isinstance(n, str) and n for n in snap["connected"]))


if __name__ == "__main__":
    unittest.main()
