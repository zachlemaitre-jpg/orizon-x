import ctypes
import unittest

from actions import keys, media

VK_CONTROL, VK_MENU, VK_SHIFT, VK_LWIN = 0x11, 0x12, 0x10, 0x5B
UP = keys.KEYEVENTF_KEYUP
EXT = keys.KEYEVENTF_EXTENDEDKEY


class FakeSendInput:
    def __init__(self, result=None):
        self.calls = []
        self.result = result

    def __call__(self, count, array, size):
        events = [(array[i].type, array[i].u.ki.wVk, array[i].u.ki.wScan, array[i].u.ki.dwFlags,
                   array[i].u.ki.time, array[i].u.ki.dwExtraInfo) for i in range(count)]
        self.calls.append((count, size, events))
        return count if self.result is None else self.result


def qwerty_scan(ch):
    """A VkKeyScanW stand-in for a US layout (low byte = VK, high byte = shift state)."""
    table = {
        "-": 0xBD, "=": 0xBB, "/": 0xBF, "`": 0xC0, ",": 0xBC, ".": 0xBE, ";": 0xBA,
        "+": 0xBB | (1 << 8),
    }
    return table.get(ch, -1)


def azerty_scan(ch):
    """A simulated French AZERTY layout: '-' is unshifted on the 6 key, '=' unshifted, '+' and '/' need Shift,
    '`' needs AltGr (Ctrl+Alt)."""
    table = {
        "-": 0x36, "=": 0xBB, "+": 0xBB | (1 << 8), "/": 0xDF | (1 << 8),
        "`": 0xDE | (6 << 8),
    }
    return table.get(ch, -1)


def send(shortcut, scan=qwerty_scan):
    fake = FakeSendInput()
    result = keys.send_shortcut(shortcut, send_input=fake, vk_scan=scan)
    return result, fake


def events_of(shortcut, scan=qwerty_scan):
    result, fake = send(shortcut, scan)
    assert result is True, result
    assert len(fake.calls) == 1
    return [(vk, flags) for (_t, vk, _s, flags, _time, _x) in fake.calls[0][2]]


class StructTest(unittest.TestCase):
    def test_input_struct_sizes_on_x64(self):
        self.assertEqual(ctypes.sizeof(keys.INPUT), 40)
        self.assertEqual(ctypes.sizeof(keys.KEYBDINPUT), 24)

    def test_constants(self):
        self.assertEqual(keys.INPUT_KEYBOARD, 1)
        self.assertEqual(keys.KEYEVENTF_KEYUP, 0x0002)
        self.assertEqual(keys.KEYEVENTF_EXTENDEDKEY, 0x0001)

    def test_media_shares_the_struct_definitions(self):
        self.assertIs(media.INPUT, keys.INPUT)
        self.assertIs(media.KEYBDINPUT, keys.KEYBDINPUT)


class SequenceTest(unittest.TestCase):
    def test_single_key(self):
        self.assertEqual(events_of("Space"), [(0x20, 0), (0x20, UP)])

    def test_function_key(self):
        self.assertEqual(events_of("F5"), [(0x74, 0), (0x74, UP)])

    def test_escape_aliases(self):
        self.assertEqual(events_of("Esc"), [(0x1B, 0), (0x1B, UP)])
        self.assertEqual(events_of("Escape"), [(0x1B, 0), (0x1B, UP)])

    def test_letters_and_digits(self):
        self.assertEqual(events_of("B"), [(0x42, 0), (0x42, UP)])
        self.assertEqual(events_of("b"), [(0x42, 0), (0x42, UP)])
        self.assertEqual(events_of("7"), [(0x37, 0), (0x37, UP)])

    def test_modifier_then_key_released_in_reverse_order(self):
        self.assertEqual(events_of("Ctrl+Shift+P"), [
            (VK_CONTROL, 0), (VK_SHIFT, 0), (0x50, 0), (0x50, UP), (VK_SHIFT, UP), (VK_CONTROL, UP)])

    def test_alt_and_win(self):
        self.assertEqual(events_of("Alt+Shift+B"), [
            (VK_MENU, 0), (VK_SHIFT, 0), (0x42, 0), (0x42, UP), (VK_SHIFT, UP), (VK_MENU, UP)])
        self.assertEqual(events_of("Win+D"), [(VK_LWIN, EXT), (0x44, 0), (0x44, UP), (VK_LWIN, EXT | UP)])
        self.assertEqual(events_of("Win+Shift+S"), [
            (VK_LWIN, EXT), (VK_SHIFT, 0), (0x53, 0), (0x53, UP), (VK_SHIFT, UP), (VK_LWIN, EXT | UP)])

    def test_case_and_spaces_around_names_are_tolerated(self):
        self.assertEqual(events_of("ctrl + s"), events_of("Ctrl+S"))
        self.assertEqual(events_of("CONTROL+S"), events_of("Ctrl+S"))

    def test_arrows_are_extended(self):
        self.assertEqual(events_of("Left"), [(0x25, EXT), (0x25, EXT | UP)])
        self.assertEqual(events_of("Right"), [(0x27, EXT), (0x27, EXT | UP)])
        self.assertEqual(events_of("Up"), [(0x26, EXT), (0x26, EXT | UP)])
        self.assertEqual(events_of("Alt+Left"), [(VK_MENU, 0), (0x25, EXT), (0x25, EXT | UP), (VK_MENU, UP)])
        self.assertEqual(events_of("Ctrl+Right"),
                         [(VK_CONTROL, 0), (0x27, EXT), (0x27, EXT | UP), (VK_CONTROL, UP)])

    def test_other_extended_keys(self):
        for name, vk in (("Home", 0x24), ("End", 0x23), ("PageUp", 0x21), ("PageDown", 0x22),
                         ("Insert", 0x2D), ("Delete", 0x2E), ("Down", 0x28)):
            with self.subTest(name):
                self.assertEqual(events_of(name), [(vk, EXT), (vk, EXT | UP)])

    def test_non_extended_named_keys(self):
        for name, vk in (("Enter", 0x0D), ("Tab", 0x09), ("Backspace", 0x08), ("F2", 0x71), ("F12", 0x7B)):
            with self.subTest(name):
                self.assertEqual(events_of(name), [(vk, 0), (vk, UP)])

    def test_one_send_input_call_with_the_struct_size(self):
        _, fake = send("Ctrl+C")
        count, size, events = fake.calls[0]
        self.assertEqual((count, size), (4, 40))
        self.assertTrue(all(e[0] == 1 and e[2] == 0 and e[4] == 0 and e[5] == 0 for e in events))


class PunctuationTest(unittest.TestCase):
    def test_punctuation_resolved_through_the_layout_us(self):
        self.assertEqual(events_of("Ctrl+-"), [(VK_CONTROL, 0), (0xBD, 0), (0xBD, UP), (VK_CONTROL, UP)])
        self.assertEqual(events_of("Ctrl+="), [(VK_CONTROL, 0), (0xBB, 0), (0xBB, UP), (VK_CONTROL, UP)])
        self.assertEqual(events_of("Alt+="), [(VK_MENU, 0), (0xBB, 0), (0xBB, UP), (VK_MENU, UP)])
        self.assertEqual(events_of("Ctrl+/"), [(VK_CONTROL, 0), (0xBF, 0), (0xBF, UP), (VK_CONTROL, UP)])
        self.assertEqual(events_of("Ctrl+`"), [(VK_CONTROL, 0), (0xC0, 0), (0xC0, UP), (VK_CONTROL, UP)])

    def test_azerty_minus_is_the_digit_row_key(self):
        self.assertEqual(events_of("Ctrl+-", azerty_scan),
                         [(VK_CONTROL, 0), (0x36, 0), (0x36, UP), (VK_CONTROL, UP)])

    def test_layout_shift_state_adds_the_missing_modifier(self):
        self.assertEqual(events_of("Ctrl+/", azerty_scan), [
            (VK_CONTROL, 0), (VK_SHIFT, 0), (0xDF, 0), (0xDF, UP), (VK_SHIFT, UP), (VK_CONTROL, UP)])

    def test_layout_shift_state_already_requested_is_not_doubled(self):
        self.assertEqual(events_of("Shift+/", azerty_scan), [
            (VK_SHIFT, 0), (0xDF, 0), (0xDF, UP), (VK_SHIFT, UP)])

    def test_altgr_layout_state_adds_ctrl_and_alt(self):
        self.assertEqual(events_of("`", azerty_scan), [
            (VK_CONTROL, 0), (VK_MENU, 0), (0xDE, 0), (0xDE, UP), (VK_MENU, UP), (VK_CONTROL, UP)])

    def test_plus_key_itself(self):
        self.assertEqual(events_of("Ctrl++"), [
            (VK_CONTROL, 0), (VK_SHIFT, 0), (0xBB, 0), (0xBB, UP), (VK_SHIFT, UP), (VK_CONTROL, UP)])
        self.assertEqual(events_of("+"), [(VK_SHIFT, 0), (0xBB, 0), (0xBB, UP), (VK_SHIFT, UP)])

    def test_key_the_layout_does_not_have_is_an_error_and_sends_nothing(self):
        fake = FakeSendInput()
        with self.assertRaises(ValueError):
            keys.send_shortcut("Ctrl+;", send_input=fake, vk_scan=azerty_scan)
        self.assertEqual(fake.calls, [])


class PositionalKeyTest(unittest.TestCase):
    def test_oem_names_are_the_virtual_keys_whatever_the_layout(self):
        # VS Code binds Ctrl+` / Ctrl+/ to the key position, not to the character: never through VkKeyScanW
        for name, vk in (("OEM_3", 0xC0), ("OEM_2", 0xBF), ("oem_minus", 0xBD), ("OEM_PLUS", 0xBB),
                         ("OEM_1", 0xBA), ("OEM_COMMA", 0xBC), ("OEM_PERIOD", 0xBE), ("OEM_4", 0xDB),
                         ("OEM_5", 0xDC), ("OEM_6", 0xDD), ("OEM_7", 0xDE), ("OEM_8", 0xDF), ("OEM_102", 0xE2)):
            for scan in (qwerty_scan, azerty_scan):
                with self.subTest(name=name, scan=scan.__name__):
                    self.assertEqual(events_of("Ctrl+" + name, scan),
                                     [(VK_CONTROL, 0), (vk, 0), (vk, UP), (VK_CONTROL, UP)])


class InvalidTest(unittest.TestCase):
    def test_invalid_shortcuts_raise_and_send_nothing(self):
        for bad in ("", "   ", "Ctrl+", "Ctrl+Shift", "Foo+A", "Ctrl+F25", "Ctrl+Nothing", "A+B", "Ctrl+Ctrl+A",
                    None, 5):
            with self.subTest(bad=bad):
                fake = FakeSendInput()
                with self.assertRaises(ValueError):
                    keys.send_shortcut(bad, send_input=fake, vk_scan=qwerty_scan)
                self.assertEqual(fake.calls, [])


class ResultTest(unittest.TestCase):
    def test_partial_injection_returns_false(self):
        fake = FakeSendInput(result=0)
        self.assertFalse(keys.send_shortcut("Ctrl+C", send_input=fake, vk_scan=qwerty_scan))

    def test_full_injection_returns_true(self):
        result, _ = send("Ctrl+C")
        self.assertTrue(result)


if __name__ == "__main__":
    unittest.main()
