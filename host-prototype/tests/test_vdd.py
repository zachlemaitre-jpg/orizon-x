import os
import tempfile
import threading
import time
import unittest
import uuid
import xml.etree.ElementTree as ET
from pathlib import Path
from unittest import mock

import vdd

# Copie de la structure du vrai C:\VirtualDisplayDriver\vdd_settings.xml (commentaires, tabulations, ’ compris),
# plus une section inconnue avec attribut pour vérifier qu'on ne la perd pas.
REAL_XML = """<?xml version='1.0' encoding='utf-8'?>
<vdd_settings>
    <monitors>
        <count>2</count>
    </monitors>
    <gpu>
        <friendlyname>default</friendlyname>
    </gpu>
\t<global>
\t\t<!--These are global refreshrates, any you add in here, will be replicated to all resolutions-->
\t\t<g_refresh_rate>60</g_refresh_rate>
\t\t<g_refresh_rate>90</g_refresh_rate>
\t\t<g_refresh_rate>120</g_refresh_rate>
\t</global>
    <resolutions>
        <!-- TabX : Galaxy Tab S10 FE+ (natif) et alternative 16:10 -->
        <resolution>
            <width>2880</width>
            <height>1800</height>
            <refresh_rate>60</refresh_rate>
        </resolution>
        <resolution>
            <width>1920</width>
            <height>1080</height>
            <refresh_rate>30</refresh_rate>
        </resolution>


    </resolutions>
    <options>
\t\t<CustomEdid>false</CustomEdid> <!-- Custom Edid should be named "user_edid.bin"! This does not support emulating resolutions!-->
\t\t<HardwareCursor>true</HardwareCursor>
\t\t<HDRPlus>false</HDRPlus> <!-- If you have SDR10 bit enabled, HDRPlus wont work - there’s a conflict -->
\t\t<logging>false</logging>
        <!-- DEBUG LOGGING FOR EXPERTS ONLY!-->
        <debuglogging>false</debuglogging>
\t</options>
    <custom_section kind="unknown"><foo bar="baz">keep me</foo></custom_section>
</vdd_settings>"""


class XmlTestCase(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())
        self.path = self.dir / "vdd_settings.xml"
        self.backup = self.dir / "vdd_settings.xml.bak-orizonx"

    def write_xml(self, text=REAL_XML):
        self.path.write_text(text, encoding="utf-8")

    def controller(self, transport=None):
        return vdd.VddController(settings_path=self.path, transport=transport)

    def root(self):
        return ET.parse(self.path).getroot()

    def leftovers(self):
        """Files in the folder other than the XML and its backup (temp files that should not survive)."""
        return sorted(p.name for p in self.dir.iterdir() if p not in (self.path, self.backup))


class CommonResolutionsTest(unittest.TestCase):
    def test_spec_list_all_at_60_hz(self):
        self.assertEqual(len(vdd.COMMON_RESOLUTIONS), 21)
        self.assertEqual(vdd.COMMON_RESOLUTIONS[0], (2880, 1800, 60))
        self.assertIn((1600, 2560, 60), vdd.COMMON_RESOLUTIONS)
        self.assertIn((2732, 2048, 60), vdd.COMMON_RESOLUTIONS)
        self.assertTrue(all(hz == 60 for _w, _h, hz in vdd.COMMON_RESOLUTIONS))
        self.assertEqual(len(set(vdd.COMMON_RESOLUTIONS)), 21)


class ReadResolutionsTest(XmlTestCase):
    def test_reads_resolutions_in_order(self):
        self.write_xml()
        self.assertEqual(self.controller().read_resolutions(), [(2880, 1800, 60), (1920, 1080, 30)])

    def test_missing_file_gives_empty_list(self):
        self.assertEqual(self.controller().read_resolutions(), [])

    def test_malformed_entries_are_skipped(self):
        self.write_xml("<vdd_settings><resolutions>"
                       "<resolution><width>abc</width><height>1</height><refresh_rate>60</refresh_rate></resolution>"
                       "<resolution><width>800</width><height>600</height></resolution>"
                       "<resolution><width>1280</width><height>800</height><refresh_rate>60</refresh_rate></resolution>"
                       "</resolutions></vdd_settings>")
        self.assertEqual(self.controller().read_resolutions(), [(1280, 800, 60)])

    def test_invalid_xml_raises_vdd_error(self):
        self.write_xml("<vdd_settings><resolutions>")
        with self.assertRaises(vdd.VddError):
            self.controller().read_resolutions()


class AddResolutionsTest(XmlTestCase):
    def test_adds_missing_resolutions_once(self):
        self.write_xml()
        ctl = self.controller()
        self.assertTrue(ctl.add_resolutions([(2560, 1600, 60), (2880, 1800, 60), (1920, 1080, 60)]))
        self.assertEqual(ctl.read_resolutions(),
                         [(2880, 1800, 60), (1920, 1080, 30), (2560, 1600, 60), (1920, 1080, 60)])
        self.assertFalse(ctl.add_resolutions([(2560, 1600, 60), (1920, 1080, 60)]))
        self.assertEqual(len(ctl.read_resolutions()), 4)

    def test_duplicates_in_the_request_are_added_once(self):
        self.write_xml()
        ctl = self.controller()
        self.assertTrue(ctl.add_resolutions([(1280, 800, 60), (1280, 800, 60)]))
        self.assertEqual(ctl.read_resolutions().count((1280, 800, 60)), 1)

    def test_nothing_to_add_leaves_file_untouched(self):
        self.write_xml()
        before = self.path.read_bytes()
        self.assertFalse(self.controller().add_resolutions([(2880, 1800, 60)]))
        self.assertEqual(self.path.read_bytes(), before)
        self.assertFalse(self.backup.exists())

    def test_keeps_comments_unknown_sections_and_other_settings(self):
        self.write_xml()
        self.controller().add_resolutions([(2560, 1600, 60)])
        text = self.path.read_text(encoding="utf-8")
        self.assertIn("<!--These are global refreshrates", text)
        self.assertIn("<!-- TabX : Galaxy Tab S10 FE+ (natif) et alternative 16:10 -->", text)
        self.assertIn("there’s a conflict", text)
        self.assertIn('<custom_section kind="unknown"><foo bar="baz">keep me</foo></custom_section>', text)
        root = self.root()
        self.assertEqual([e.text for e in root.iter("g_refresh_rate")], ["60", "90", "120"])
        self.assertEqual(root.findtext("gpu/friendlyname"), "default")
        self.assertEqual(root.findtext("options/HardwareCursor"), "true")
        self.assertEqual(root.findtext("monitors/count"), "2")  # add_resolutions ne touche pas au nombre d'écrans

    def test_new_resolution_is_written_with_the_driver_element_names(self):
        self.write_xml()
        self.controller().add_resolutions([(2560, 1600, 60)])
        last = self.root().findall("resolutions/resolution")[-1]
        self.assertEqual([(c.tag, c.text) for c in last],
                         [("width", "2560"), ("height", "1600"), ("refresh_rate", "60")])

    def test_never_writes_self_closing_elements(self):
        # Le réécriveur XML du pilote casse sur <x/> : même un élément vide doit rester <x></x>.
        self.write_xml("<vdd_settings><gpu><friendlyname></friendlyname></gpu><resolutions/></vdd_settings>")
        self.controller().add_resolutions([(1280, 800, 60)])
        text = self.path.read_text(encoding="utf-8")
        self.assertNotIn("/>", text)
        self.assertIn("<friendlyname></friendlyname>", text)

    def test_writes_utf8_declaration(self):
        self.write_xml()
        self.controller().add_resolutions([(2560, 1600, 60)])
        self.assertTrue(self.path.read_bytes().startswith(b"<?xml version='1.0' encoding='utf-8'?>"))

    def test_new_resolution_is_indented_like_its_siblings(self):
        self.write_xml()
        self.controller().add_resolutions([(2560, 1600, 60)])
        text = self.path.read_text(encoding="utf-8")
        self.assertIn("        <resolution>\n            <width>2560</width>\n"
                      "            <height>1600</height>\n            <refresh_rate>60</refresh_rate>\n"
                      "        </resolution>\n    </resolutions>", text)

    def test_creates_resolutions_section_when_absent(self):
        self.write_xml("<vdd_settings><monitors><count>1</count></monitors></vdd_settings>")
        ctl = self.controller()
        self.assertTrue(ctl.add_resolutions([(1280, 800, 60)]))
        self.assertEqual(ctl.read_resolutions(), [(1280, 800, 60)])

    def test_missing_file_is_created_from_a_minimal_template(self):
        self.path = self.dir / "sub" / "vdd_settings.xml"  # dossier absent (installation neuve)
        ctl = self.controller()
        self.assertTrue(ctl.add_resolutions([(2880, 1800, 60)]))
        root = self.root()
        self.assertEqual(root.tag, "vdd_settings")
        self.assertEqual(root.findtext("monitors/count"), "1")
        self.assertEqual(root.findtext("gpu/friendlyname"), "default")
        self.assertEqual([e.text for e in root.iter("g_refresh_rate")], ["60"])
        self.assertEqual(root.findtext("options/logging"), "false")
        self.assertEqual(ctl.read_resolutions(), [(1920, 1080, 60), (2880, 1800, 60)])
        self.assertFalse((self.path.parent / "vdd_settings.xml.bak-orizonx").exists())

    def test_rejects_invalid_values(self):
        self.write_xml()
        for bad in [(0, 1080, 60), (1920, -1, 60), (1920, 1080, 0)]:
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                self.controller().add_resolutions([bad])


class BackupAndAtomicWriteTest(XmlTestCase):
    def test_backup_is_made_once_from_the_original(self):
        self.write_xml()
        original = self.path.read_bytes()
        ctl = self.controller()
        ctl.add_resolutions([(2560, 1600, 60)])
        self.assertEqual(self.backup.read_bytes(), original)
        ctl.add_resolutions([(1280, 800, 60)])
        ctl.set_gpu_in_xml("AMD Radeon(TM) 890M Graphics")
        self.assertEqual(self.backup.read_bytes(), original)

    def test_existing_backup_is_never_overwritten(self):
        self.write_xml()
        self.backup.write_bytes(b"older backup")
        self.controller().add_resolutions([(2560, 1600, 60)])
        self.assertEqual(self.backup.read_bytes(), b"older backup")

    def test_atomic_write_leaves_no_temp_file(self):
        self.write_xml()
        ctl = self.controller()
        ctl.add_resolutions([(2560, 1600, 60)])
        ctl.ensure_single_monitor()
        ctl.set_gpu_in_xml("NVIDIA GeForce RTX 5070 Laptop GPU")
        self.assertEqual(self.leftovers(), [])

    def test_failed_replace_keeps_original_and_removes_temp(self):
        self.write_xml()
        before = self.path.read_bytes()
        with mock.patch.object(vdd.os, "replace", side_effect=PermissionError("locked")):
            with self.assertRaises(vdd.VddError):
                self.controller().add_resolutions([(2560, 1600, 60)])
        self.assertEqual(self.path.read_bytes(), before)
        self.assertEqual(self.leftovers(), [])


class SingleMonitorTest(XmlTestCase):
    def test_forces_count_to_one(self):
        self.write_xml()
        ctl = self.controller()
        self.assertTrue(ctl.ensure_single_monitor())
        self.assertEqual(self.root().findtext("monitors/count"), "1")
        self.assertFalse(ctl.ensure_single_monitor())

    def test_zero_becomes_one(self):
        self.write_xml(REAL_XML.replace("<count>2</count>", "<count>0</count>"))
        self.assertTrue(self.controller().ensure_single_monitor())
        self.assertEqual(self.root().findtext("monitors/count"), "1")

    def test_creates_monitors_section_when_absent(self):
        self.write_xml("<vdd_settings><resolutions></resolutions></vdd_settings>")
        self.assertTrue(self.controller().ensure_single_monitor())
        self.assertEqual(self.root().findtext("monitors/count"), "1")

    def test_keeps_everything_else(self):
        self.write_xml()
        self.controller().ensure_single_monitor()
        self.assertEqual(self.controller().read_resolutions(), [(2880, 1800, 60), (1920, 1080, 30)])
        self.assertIn("keep me", self.path.read_text(encoding="utf-8"))


class SetGpuTest(XmlTestCase):
    def test_sets_friendly_name(self):
        self.write_xml()
        ctl = self.controller()
        self.assertTrue(ctl.set_gpu_in_xml("AMD Radeon(TM) 890M Graphics"))
        self.assertEqual(self.root().findtext("gpu/friendlyname"), "AMD Radeon(TM) 890M Graphics")
        self.assertFalse(ctl.set_gpu_in_xml("AMD Radeon(TM) 890M Graphics"))

    def test_creates_gpu_section_when_absent(self):
        self.write_xml("<vdd_settings><monitors><count>1</count></monitors></vdd_settings>")
        self.assertTrue(self.controller().set_gpu_in_xml("Intel(R) UHD Graphics"))
        self.assertEqual(self.root().findtext("gpu/friendlyname"), "Intel(R) UHD Graphics")

    def test_rejects_empty_name(self):
        self.write_xml()
        with self.assertRaises(ValueError):
            self.controller().set_gpu_in_xml("  ")


class IsInstalledTest(unittest.TestCase):
    def test_pong_means_installed_and_ping_is_the_only_command(self):
        sent = []

        def transport(message):
            sent.append(message)
            return b"PONG"

        self.assertTrue(vdd.VddController(transport=transport).is_installed())
        self.assertEqual(sent, ["PING"])

    def test_pong_among_log_lines_still_counts(self):
        reply = b"2026-10-05 [INFO] Client Handling Enabled\nPONG"
        self.assertTrue(vdd.VddController(transport=lambda _m: reply).is_installed())

    def test_other_reply_means_not_installed(self):
        self.assertFalse(vdd.VddController(transport=lambda _m: b"").is_installed())
        self.assertFalse(vdd.VddController(transport=lambda _m: b"NOPE").is_installed())

    def test_transport_error_means_not_installed(self):
        for error in (vdd.VddError("no pipe"), OSError(2, "not found"), TimeoutError()):
            def transport(_m, error=error):
                raise error
            with self.subTest(error=error):
                self.assertFalse(vdd.VddController(transport=transport).is_installed())


# --- vrai client de canal nommé, contre un faux serveur qui imite le pilote (jamais le vrai canal) ---

if os.name == "nt":
    import ctypes
    from ctypes import wintypes

    _k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    _k32.CreateNamedPipeW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, wintypes.DWORD,
                                      wintypes.DWORD, wintypes.DWORD, wintypes.DWORD, wintypes.LPVOID]
    _k32.CreateNamedPipeW.restype = wintypes.HANDLE
    _k32.ConnectNamedPipe.argtypes = [wintypes.HANDLE, wintypes.LPVOID]
    _k32.ConnectNamedPipe.restype = wintypes.BOOL
    _k32.ReadFile.argtypes = [wintypes.HANDLE, wintypes.LPVOID, wintypes.DWORD,
                              ctypes.POINTER(wintypes.DWORD), wintypes.LPVOID]
    _k32.ReadFile.restype = wintypes.BOOL
    _k32.WriteFile.argtypes = [wintypes.HANDLE, wintypes.LPCVOID, wintypes.DWORD,
                               ctypes.POINTER(wintypes.DWORD), wintypes.LPVOID]
    _k32.WriteFile.restype = wintypes.BOOL
    _k32.DisconnectNamedPipe.argtypes = [wintypes.HANDLE]
    _k32.DisconnectNamedPipe.restype = wintypes.BOOL
    _k32.CloseHandle.argtypes = [wintypes.HANDLE]
    _k32.CloseHandle.restype = wintypes.BOOL


class FakeDriverPipe:
    """One-client message pipe server that behaves like VDD's HandleClient: one ReadFile, reply, Disconnect at once."""

    def __init__(self, reply=b"PONG", delay_s=0.0, hold_s=0.0):
        self.name = rf"\\.\pipe\OrizonXTest-{os.getpid()}-{uuid.uuid4().hex}"
        self.reply = reply
        self.delay_s = delay_s  # création du canal retardée (fenêtre « pas d'instance » entre deux clients)
        self.hold_s = hold_s    # garde la connexion ouverte sans répondre (délai dépassé côté client)
        self.received = None
        self.ready = threading.Event()
        self.thread = threading.Thread(target=self._serve, daemon=True)
        self.thread.start()
        if not delay_s:
            self.ready.wait(2)

    def _serve(self):
        time.sleep(self.delay_s)
        handle = _k32.CreateNamedPipeW(self.name, 0x3, 0x4 | 0x2 | 0x0, 1, 512, 512, 0, None)
        self.ready.set()
        try:
            _k32.ConnectNamedPipe(handle, None)  # ERROR_PIPE_CONNECTED si le client est déjà là : OK
            buffer = ctypes.create_string_buffer(254)
            count = wintypes.DWORD()
            if _k32.ReadFile(handle, buffer, 254, ctypes.byref(count), None):
                self.received = buffer.raw[:count.value]
            time.sleep(self.hold_s)
            if self.reply:
                written = wintypes.DWORD()
                _k32.WriteFile(handle, self.reply, len(self.reply), ctypes.byref(written), None)
            _k32.DisconnectNamedPipe(handle)  # jette ce que le client n'a pas encore lu, comme le pilote
        finally:
            _k32.CloseHandle(handle)

    def join(self):
        self.thread.join(5)


@unittest.skipUnless(os.name == "nt", "canaux nommés Windows uniquement")
class PipeTransportTest(unittest.TestCase):
    def test_ping_round_trip_utf16_request(self):
        server = FakeDriverPipe(reply=b"PONG")
        reply = vdd.pipe_transport("PING", pipe_name=server.name, timeout=2.0)
        server.join()
        self.assertEqual(reply, b"PONG")
        self.assertEqual(server.received, b"P\x00I\x00N\x00G\x00")

    def test_controller_uses_the_pipe(self):
        server = FakeDriverPipe(reply=b"PONG")
        self.assertTrue(vdd.VddController(pipe_name=server.name).is_installed())
        server.join()

    def test_utf16_reply_is_returned_raw(self):
        reply = "SETTINGS DEBUG=false LOG=false\x00".encode("utf-16le")
        server = FakeDriverPipe(reply=reply)
        self.assertEqual(vdd.pipe_transport("GETSETTINGS", pipe_name=server.name), reply)
        server.join()

    def test_no_reply_and_disconnect_gives_empty_bytes(self):
        server = FakeDriverPipe(reply=b"")
        self.assertEqual(vdd.pipe_transport("PING", pipe_name=server.name, timeout=2.0), b"")
        server.join()

    def test_retries_while_the_pipe_does_not_exist_yet(self):
        server = FakeDriverPipe(reply=b"PONG", delay_s=0.15)
        self.assertEqual(vdd.pipe_transport("PING", pipe_name=server.name, timeout=2.0), b"PONG")
        server.join()

    def test_missing_pipe_raises_quickly(self):
        name = rf"\\.\pipe\OrizonXTest-absent-{uuid.uuid4().hex}"
        start = time.monotonic()
        with self.assertRaises(vdd.PipeError) as caught:
            vdd.pipe_transport("PING", pipe_name=name, timeout=2.0)
        self.assertLess(time.monotonic() - start, 1.5)
        self.assertEqual(caught.exception.winerror, 2)
        self.assertFalse(vdd.VddController(pipe_name=name).is_installed())

    def test_silent_server_times_out(self):
        server = FakeDriverPipe(reply=b"PONG", hold_s=1.0)
        start = time.monotonic()
        with self.assertRaises(vdd.PipeError):
            vdd.pipe_transport("PING", pipe_name=server.name, timeout=0.3)
        self.assertLess(time.monotonic() - start, 0.9)
        server.join()

    def test_message_too_long_is_refused(self):
        with self.assertRaises(ValueError):
            vdd.pipe_transport("X" * 128, pipe_name=r"\\.\pipe\unused")


if __name__ == "__main__":
    unittest.main()
