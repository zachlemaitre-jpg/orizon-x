import unittest

from actions import context_profiles as cp
from actions import keys
from actions.context import ContextProvider
from actions.foreground import ForegroundApp

US_SCAN = lambda ch: {"-": 0xBD, "=": 0xBB, "/": 0xBF, "`": 0xC0, ";": 0xBA}.get(ch, -1)  # noqa: E731


def app(exe, title="Window", hwnd=42):
    return ForegroundApp(exe, "Cls", title, 1, hwnd)


# profile -> {button id: (icon, en, fr, shortcut, hidden)}; UIA buttons are in UIA below
CHAT = {
    "claude_app": ["cl.app.new", "cl.app.search", "cl.app.sidebar", "cl.app.input", "cl.app.stop"],
    "claude_web": ["cl.web.new", "cl.web.search", "cl.web.sidebar", "cl.web.input", "cl.web.stop"],
    "chatgpt": ["gpt.new", "gpt.search", "gpt.sidebar", "gpt.copy_reply", "gpt.copy_code", "gpt.input", "gpt.stop"],
    "gemini": ["gem.new", "gem.search", "gem.sidebar", "gem.copy_reply", "gem.input", "gem.stop"],
}
VISIBLE = {
    "claude_app": ["cl.app.new", "cl.app.search", "cl.app.sidebar", "cl.app.stop"],
    "claude_web": ["cl.web.stop"],
    "chatgpt": CHAT["chatgpt"],
    "gemini": ["gem.new", "gem.stop"],
}
SHORTCUTS = {
    "gpt.new": "Ctrl+Shift+O", "gpt.search": "Ctrl+K", "gpt.sidebar": "Ctrl+Shift+S", "gpt.copy_reply": "Ctrl+Shift+C",
    "gpt.copy_code": "Ctrl+Shift+OEM_1", "gpt.input": "Shift+Esc", "gpt.stop": "Esc",
    "gem.new": "Ctrl+Shift+O", "gem.stop": "Esc", "cl.app.stop": "Esc", "cl.web.stop": "Esc",
}
UIA = {"cl.app.new": ("Nouveau", "New"), "cl.app.search": ("Rechercher", "Search"),
       "cl.app.sidebar": ("Masquer la barre latérale", "Afficher la barre latérale", "Hide sidebar", "Show sidebar")}
LABELS = {  # suffix -> (en, fr, icon)
    "new": ("New chat", "Nouvelle discussion", "chat_new"), "search": ("Search", "Rechercher", "search"),
    "sidebar": ("Sidebar", "Barre latérale", "sidebar"), "copy_reply": ("Copy reply", "Copier la réponse", "copy_reply"),
    "copy_code": ("Copy code", "Copier le code", "copy_code"), "input": ("Input", "Zone de saisie", "input_focus"),
    "stop": ("Stop", "Arrêter", "stop"),
}


def suffix(button_id):
    return button_id.rsplit(".", 1)[-1]


class DetectionTest(unittest.TestCase):
    def test_exes(self):
        for exe, pid in (("claude.exe", "claude_app"), ("Claude.EXE", "claude_app"), ("ChatGPT.exe", "chatgpt"),
                         ("CHATGPT.EXE", "chatgpt")):
            with self.subTest(exe):
                self.assertEqual(cp.match(app(exe)).id, pid)

    def test_hosts_in_a_browser(self):
        cases = {"claude.ai/chat/abc": "claude_web", "https://claude.ai/new": "claude_web",
                 "chatgpt.com/c/123": "chatgpt", "https://www.chatgpt.com/": "chatgpt",
                 "chat.openai.com/chat": "chatgpt", "gemini.google.com/app": "gemini",
                 "https://gemini.google.com/app/abc?x=1": "gemini"}
        for exe in ("chrome.exe", "msedge.exe", "firefox.exe"):
            for url, pid in cases.items():
                with self.subTest(exe=exe, url=url):
                    self.assertEqual(cp.match(app(exe, "Some title"), url).id, pid)

    def test_the_rest_of_google_and_lookalikes_stay_the_browser(self):
        for url in ("www.google.com/search?q=gemini", "google.com", "mail.google.com", "gemini.google.com.evil.org/x",
                    "notgemini.google.com", "fakeclaude.ai", "claude.ai.evil.org", "chat.openai.com.evil.org",
                    "openai.com", "example.org/claude.ai", "chatgpt.com.fr"):
            with self.subTest(url):
                self.assertEqual(cp.match(app("chrome.exe", "x"), url).id, "browser")

    def test_url_is_ignored_outside_browsers(self):
        self.assertEqual(cp.match(app("notepad.exe"), "claude.ai").id, "generic")
        self.assertEqual(cp.match(app("claude.exe"), "gemini.google.com").id, "claude_app")

    def test_canva_and_figma_still_win_on_their_own_hosts(self):
        self.assertEqual(cp.match(app("chrome.exe"), "canva.com/x").id, "canva")
        self.assertEqual(cp.match(app("chrome.exe", "Figma board"), "claude.ai/new").id, "claude_web")  # the host first

    def test_display_names(self):
        for exe, url, name in (("claude.exe", None, "Claude"), ("ChatGPT.exe", None, "ChatGPT"),
                               ("chrome.exe", "claude.ai/new", "Claude"), ("chrome.exe", "chatgpt.com", "ChatGPT"),
                               ("chrome.exe", "gemini.google.com/app", "Gemini")):
            for lang in ("en", "fr"):
                with self.subTest(exe=exe, url=url, lang=lang):
                    self.assertEqual(cp.display_name(app(exe), lang, url), name)
        self.assertEqual(cp.display_name(app("chrome.exe"), "en", "www.google.com"), "Chrome")


class DataTest(unittest.TestCase):
    def test_one_chat_page_per_profile_with_the_spec_buttons(self):
        for pid, ids in CHAT.items():
            with self.subTest(pid):
                profile = cp.profile_by_id(pid)
                self.assertEqual([p.id for p in profile.pages], ["chat"])
                self.assertEqual(profile.pages[0].labels, {"en": "Chat", "fr": "Chat"})
                self.assertEqual([b.id for b in profile.pages[0].buttons], ids)

    def test_labels_icons_and_shortcuts(self):
        for pid, ids in CHAT.items():
            for b in cp.profile_by_id(pid).pages[0].buttons:
                with self.subTest(b.id):
                    en, fr, icon = LABELS[suffix(b.id)]
                    self.assertEqual((b.labels["en"], b.labels["fr"], b.icon), (en, fr, icon))
                    if b.id in SHORTCUTS:
                        self.assertEqual(b.shortcut, SHORTCUTS[b.id])
                        self.assertEqual(b.uia, ())
                        self.assertFalse(b.hidden)

    def test_new_icons_are_known(self):
        for name in ("chat_new", "sidebar", "copy_reply", "copy_code", "input_focus", "stop", "search"):
            self.assertIn(name, cp.ICON_NAMES)

    def test_visible_and_hidden_buttons(self):
        for pid, ids in CHAT.items():
            profile = cp.profile_by_id(pid)
            with self.subTest(pid):
                self.assertEqual([b.id for b in profile.buttons], VISIBLE[pid])
                hidden = [b.id for b in profile.pages[0].buttons if b.hidden]
                self.assertEqual(sorted(hidden), sorted(set(ids) - set(VISIBLE[pid])))
                for b in profile.pages[0].buttons:
                    if b.hidden:
                        self.assertEqual((b.shortcut, b.uia), ("", ()))

    def test_uia_buttons_of_the_claude_app(self):
        by_id = {b.id: b for b in cp.profile_by_id("claude_app").pages[0].buttons}
        for button_id, names in UIA.items():
            self.assertEqual(by_id[button_id].uia, names)
            self.assertEqual(by_id[button_id].shortcut, "")
            self.assertFalse(by_id[button_id].hidden)

    def test_ids_are_unique_across_every_profile(self):
        ids = [b.id for p in cp.PROFILES for page in p.pages for b in page.buttons]
        self.assertEqual(len(ids), len(set(ids)))
        for pid, group in CHAT.items():
            for i in group:
                self.assertTrue(i.startswith(("cl.", "gpt.", "gem.")))

    def test_shortcuts_parse_with_a_fake_layout(self):
        for pid in CHAT:
            for b in cp.profile_by_id(pid).buttons:
                if b.uia:
                    continue
                with self.subTest(b.id):
                    self.assertTrue(keys.parse_shortcut(b.shortcut, US_SCAN))

    def test_copy_code_is_sent_by_key_position_not_by_layout(self):
        def never(ch):
            raise AssertionError("the layout must not be consulted")
        events = keys.parse_shortcut("Ctrl+Shift+OEM_1", never)
        down = [vk for vk, f in events if not f & keys.KEYEVENTF_KEYUP]
        self.assertEqual(down, [keys.VK_CONTROL, keys.VK_SHIFT, 0xBA])  # VK_OEM_1: the ; key of a US keyboard

    def test_fake_send_input_receives_the_chatgpt_shortcuts(self):
        sent = []

        def fake(count, events, size):
            sent.append([(e.u.ki.wVk, e.u.ki.dwFlags) for e in events])
            return count
        for b in cp.profile_by_id("chatgpt").buttons:
            sent.clear()
            self.assertTrue(keys.send_shortcut(b.shortcut, fake, US_SCAN), b.id)
            self.assertEqual(len(sent), 1)


class Tracker:
    def __init__(self, current=None):
        self.app = current

    def current(self):
        return self.app


class FakeUrls:
    def __init__(self, url=None):
        self.value = url

    def url(self, hwnd, title=""):
        return self.value


class FakeTabs:
    def __init__(self, tabs=()):
        self.value = list(tabs)

    def tabs(self, hwnd, title=""):
        return list(self.value)

    def select(self, hwnd, index, title):
        return True


class NoIcons:
    def icon_id(self, app, profile, url):
        return None

    def artwork_bytes(self, icon_id):
        return None


class ProviderTest(unittest.TestCase):
    def setUp(self):
        self.tracker = Tracker()
        self.urls = FakeUrls()
        self.sent = []
        self.invoked = []
        self.invoke_result = True
        self.logs = []
        self.provider = self.make("fr")

    def make(self, lang):
        return ContextProvider(tracker=self.tracker, send_shortcut=lambda s: self.sent.append(s) or True,
                               log=self.logs.append, lang=lang, url_reader=self.urls, icons=NoIcons(),
                               tabs_reader=FakeTabs(), uia_invoker=self.invoke)

    def invoke(self, hwnd, names):
        self.invoked.append((hwnd, names))
        return self.invoke_result

    def press(self, button):
        return self.provider.handle({"id": "context.press", "button": button})

    def front(self, exe, url=None, title="Window"):
        self.tracker.app = app(exe, title)
        self.urls.value = url

    def test_snapshot_shows_only_the_visible_buttons(self):
        for exe, url, pid in (("claude.exe", None, "claude_app"), ("chrome.exe", "claude.ai/new", "claude_web"),
                              ("ChatGPT.exe", None, "chatgpt"), ("chrome.exe", "gemini.google.com/app", "gemini")):
            with self.subTest(pid):
                self.front(exe, url)
                snap = self.provider.snapshot()
                self.assertEqual(snap["profile"], pid)
                chat = next(p for p in snap["pages"] if p["id"] == "chat")
                self.assertEqual([b["id"] for b in chat["buttons"]], VISIBLE[pid])
                self.assertEqual(snap["buttons"], chat["buttons"])
                for b in chat["buttons"]:
                    self.assertEqual(set(b), {"id", "icon", "label"})

    def test_labels_follow_the_language(self):
        self.front("ChatGPT.exe")
        fr = self.provider.snapshot()["pages"][0]["buttons"][0]
        en = self.make("en").snapshot()["pages"][0]["buttons"][0]
        self.assertEqual((fr["label"], en["label"]), ("Nouvelle discussion", "New chat"))
        self.assertEqual(self.provider.snapshot()["pages"][0]["label"], "Chat")

    def test_in_a_browser_the_tabs_page_comes_last(self):
        self.provider._tabs_reader = FakeTabs([type("T", (), {"index": 0, "title": "Chat", "active": True})()])
        self.front("chrome.exe", "chatgpt.com/c/1")
        snap = self.provider.snapshot()
        self.assertEqual([p["id"] for p in snap["pages"]], ["chat", "tabs"])
        self.front("ChatGPT.exe")
        self.assertEqual([p["id"] for p in self.provider.snapshot()["pages"]], ["chat"])  # the native app: never

    def test_shortcut_buttons_are_sent(self):
        self.front("ChatGPT.exe")
        for button_id, shortcut in SHORTCUTS.items():
            if not button_id.startswith("gpt."):
                continue
            self.sent.clear()
            self.assertIsNone(self.press(button_id))
            self.assertEqual(self.sent, [shortcut])

    def test_stop_is_escape_in_every_profile(self):
        for exe, url, button in (("claude.exe", None, "cl.app.stop"), ("chrome.exe", "claude.ai", "cl.web.stop"),
                                 ("chrome.exe", "gemini.google.com", "gem.stop"), ("ChatGPT.exe", None, "gpt.stop")):
            self.front(exe, url)
            self.sent.clear()
            self.assertIsNone(self.press(button))
            self.assertEqual(self.sent, ["Esc"])

    def test_uia_buttons_invoke_the_sidebar_elements_of_the_foreground_window(self):
        self.front("claude.exe")
        for button_id, names in UIA.items():
            self.invoked.clear()
            self.assertIsNone(self.press(button_id))
            self.assertEqual(self.invoked, [(42, names)])
        self.assertEqual(self.sent, [])  # no key is sent for them

    def test_a_uia_button_that_is_not_found_gives_the_ui_notice(self):
        self.front("claude.exe")
        self.invoke_result = False
        self.assertEqual(self.press("cl.app.new"), "claude_ui_not_found")
        self.assertTrue(self.logs)

    def test_a_layer_error_gives_the_ui_notice(self):
        self.front("claude.exe")
        self.provider._uia_invoker = lambda hwnd, names: (_ for _ in ()).throw(OSError("COM"))
        self.assertEqual(self.press("cl.app.sidebar"), "claude_ui_not_found")

    def test_a_hidden_button_is_refused(self):
        hidden = {"claude_app": ("claude.exe", None, ["cl.app.input"]),
                  "claude_web": ("chrome.exe", "claude.ai", ["cl.web.new", "cl.web.search", "cl.web.sidebar", "cl.web.input"]),
                  "gemini": ("chrome.exe", "gemini.google.com", ["gem.search", "gem.sidebar", "gem.copy_reply", "gem.input"])}
        for pid, (exe, url, ids) in hidden.items():
            self.front(exe, url)
            for button_id in ids:
                with self.subTest(button_id):
                    self.logs.clear()
                    self.assertIsNone(self.press(button_id))
                    self.assertEqual(self.sent, [])
                    self.assertEqual(self.invoked, [])
                    self.assertEqual(len(self.logs), 1)

    def test_a_button_of_another_profile_is_refused(self):
        self.front("ChatGPT.exe")
        self.assertIsNone(self.press("gem.new"))
        self.assertIsNone(self.press("cl.app.stop"))
        self.assertEqual(self.sent, [])
        self.front("chrome.exe", "www.google.com")
        self.assertIsNone(self.press("gpt.new"))
        self.assertEqual(self.sent, [])

    def test_the_default_invoker_is_the_shared_lazy_uia_layer(self):
        provider = ContextProvider(tracker=self.tracker, log=self.logs.append, url_reader=self.urls, icons=NoIcons(),
                                   tabs_reader=FakeTabs())
        self.assertTrue(callable(provider._uia_invoker))  # nothing of comtypes is loaded by building it


if __name__ == "__main__":
    unittest.main()
