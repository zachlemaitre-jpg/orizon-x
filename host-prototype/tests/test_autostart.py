import os
import unittest

from app import autostart

TEST_KEY = r"Software\OrizonX-test\Run"


@unittest.skipUnless(os.name == "nt", "registre Windows uniquement")
class AutostartTest(unittest.TestCase):
    def tearDown(self):
        import winreg
        for path in (TEST_KEY, r"Software\OrizonX-test"):
            try:
                winreg.DeleteKey(winreg.HKEY_CURRENT_USER, path)
            except FileNotFoundError:
                pass

    EXE = r"C:\Apps\OrizonX\OrizonX.exe"

    def test_enable_then_disable(self):
        self.assertFalse(autostart.is_enabled(self.EXE, key_path=TEST_KEY))
        autostart.enable(self.EXE, TEST_KEY)
        self.assertTrue(autostart.is_enabled(self.EXE, key_path=TEST_KEY))
        self.assertEqual(autostart.registered_command(TEST_KEY), r'"C:\Apps\OrizonX\OrizonX.exe" --minimized')
        autostart.disable(TEST_KEY)
        self.assertFalse(autostart.is_enabled(self.EXE, key_path=TEST_KEY))

    def test_entry_for_another_exe_is_not_enabled(self):
        autostart.enable(r"D:\Ancien\OrizonX.exe", TEST_KEY)  # dossier de l'appli déplacé depuis
        self.assertFalse(autostart.is_enabled(self.EXE, key_path=TEST_KEY))
        self.assertTrue(autostart.is_stale(self.EXE, key_path=TEST_KEY))

    def test_missing_or_current_entry_is_not_stale(self):
        self.assertFalse(autostart.is_stale(self.EXE, key_path=TEST_KEY))
        autostart.enable(self.EXE, TEST_KEY)
        self.assertFalse(autostart.is_stale(self.EXE, key_path=TEST_KEY))

    def test_disable_when_absent_is_harmless(self):
        autostart.disable(TEST_KEY)
        self.assertFalse(autostart.is_enabled(self.EXE, key_path=TEST_KEY))

    def test_only_supported_in_packaged_app(self):
        self.assertFalse(autostart.supported())  # les tests tournent depuis les sources, pas depuis l'exe


if __name__ == "__main__":
    unittest.main()
