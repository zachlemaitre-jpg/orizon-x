import json
import os
import shutil
import tempfile
import threading
import time
import unittest

from actions import claude_app_ui as ui_mod
from actions import claude_code
from actions.claude_app_ui import ClaudeAppReader, ClaudeAppUi, Node, parse_panel
from actions.claude_code import ClaudeCodeProvider, GitStats

NB = "\u00a0"
NNB = "\u202f"

# conversation texts that must never appear in anything the provider produces
LEAKS = ["SECRET-CONVERSATION-LINE-1", "my password is hunter2", "Résultats de la conversation privée",
         "DETAILED-PRIVATE-REPLY"]


def T(depth, name):
    return Node(depth, "Text", name)


def B(depth, name):
    return Node(depth, "Button", name)


def G(depth, name):
    return Node(depth, "Group", name)


def conversation(depth=38):
    return [Node(depth, "ListItem", LEAKS[0]), T(depth + 1, LEAKS[0]), T(depth, LEAKS[1]),
            Node(depth, "ListItem", "Modifications;"), Node(depth, "ListItem", "Résultats;"),
            T(depth, "Messages"), T(depth, "540.3k"), T(depth, LEAKS[2]), T(depth, LEAKS[3]),
            T(depth, "Limite de session and Hebdomadaire, with “vu à HH:MM”.")]


def filler(n):
    return [Node(40, "Other", "") for _ in range(n)]


def fr_panel():
    return [
        G(30, "Détails de la session"),
        G(33, "Environnement"), B(36, "Environnement"), B(35, "Réorganiser la carte Environnement"),
        G(33, "Contexte"), B(36, "Contexte"), B(35, "Réorganiser la carte Contexte"),
        T(35, f"61{NB}% utilisé"), T(35, "614.3k / 1M"),
        T(35, "Messages"), T(35, "540.3k"), T(35, f"54,0{NB}%"),
        T(35, "System tools"), T(35, "23.2k"), T(35, f"2,3{NB}%"),
        B(35, f"MCP tools 12.3k 1,2{NB}% Gérer les connecteurs"),
        T(36, "MCP tools"), T(36, "12.3k"), T(36, f"1,2{NB}%"), T(36, "Gérer les connecteurs"),
        B(35, f"Skills 7.7k 0,8{NB}% Gérer les Skills"),
        T(36, "Skills"), T(36, "7.7k"), T(36, f"0,8{NB}%"), T(36, "Gérer les Skills"),
        T(35, "System prompt"), T(35, "4.3k"), T(35, f"0,4{NB}%"),
        B(35, f"Custom agents 374 0,0{NB}% Afficher les agents personnalisés"),
        T(36, "Custom agents"), T(36, "374"), T(36, f"0,0{NB}%"),
        B(35, f"Memory files 342 0,0{NB}% Afficher les fichiers de mémoire"),
        T(36, "Memory files"), T(36, "342"), T(36, f"0,0{NB}%"),
        T(35, "Depuis la dernière mise à jour"), T(35, "25.8k"), T(35, f"2,6{NB}%"),
        T(35, "Autocompact buffer"), T(35, "33k"), T(35, f"3,3{NB}%"),
        T(35, "Free space"), T(35, "352.7k"), T(35, f"35,3{NB}%"),
        T(35, "MCP tools (deferred)"), T(35, "88.3k"),
        T(35, "System tools (deferred)"), T(35, "20.7k"),
        T(36, "174"), T(36, "2"), T(36, "3"), T(36, "350k tokens avant compactage automatique"),
        B(36, "Compacter la session"),
        G(33, "Connecteurs 1 connecté(s)"), B(36, "Connecteurs 1 connecté(s)"),
        T(37, "Connecteurs"), T(37, "1 connecté(s)"), B(35, "Réorganiser la carte Connecteurs"),
        G(33, "Résultats"), B(36, "Résultats"), B(35, "Réorganiser la carte Résultats"),
        Node(37, "ListItem", "plan.md"), T(38, "plan.md"), Node(37, "ListItem", "src/app.py"), T(38, "src/app.py"),
        G(33, "Modifications"), B(36, "Modifications"), B(35, "Réorganiser la carte Modifications"),
        B(38, f"Ouvrir les modifications, 2{NNB}198 ajoutées, 9 supprimées"),
    ]


def fr_tree(extra=(), usage=True, title_filler=True):
    nodes = filler(40) + conversation() + fr_panel()
    nodes += list(extra)
    if usage:
        nodes.append(B(32, f"Utilisation : 44{NB}% de la limite de session et Réinitialisation dans 1 h 10 min"))
    return nodes


def en_tree():
    nodes = filler(40) + conversation() + [
        G(30, "Session details"),
        G(33, "Context"), B(36, "Context"),
        T(35, "61 % used"), T(35, "598.5k / 1M"),
        T(35, "Messages"), T(35, "540.3k"), T(35, "54.0 %"),
        T(35, "Free space"), T(35, "352.7k"), T(35, "35.3 %"),
        T(35, "MCP tools (deferred)"), T(35, "88.3k"),
        G(33, "Connectors 2 connected"), T(37, "2 connected"),
        G(33, "Results"), T(38, "notes.txt"),
        G(33, "Changes"), B(38, "Open changes, 1,204 added, 31 removed"),
        B(32, "Usage: 12% of session limit and Resets in 3 h"),
        B(32, "Weekly: 34% of weekly limit and Resets Sat 11:00"),
    ]
    return nodes


class ParseTest(unittest.TestCase):
    def test_french_panel(self):
        app = parse_panel("OrizonX App", fr_tree(), 1000)
        self.assertEqual(app["session_title"], "OrizonX App")
        self.assertEqual(app["seen_at"], 1000)
        ctx = app["context"]
        self.assertEqual((ctx["percent"], ctx["used"], ctx["window"]), (61, "614.3k", "1M"))
        names = [i["name"] for i in ctx["items"]]
        self.assertEqual(names, ["Messages", "System tools", "MCP tools", "Skills", "System prompt", "Custom agents",
                                 "Memory files", "Depuis la dernière mise à jour", "Autocompact buffer", "Free space"])
        self.assertEqual(ctx["items"][0], {"name": "Messages", "tokens": "540.3k", "percent": "54,0 %"})
        self.assertEqual(ctx["items"][2], {"name": "MCP tools", "tokens": "12.3k", "percent": "1,2 %"})
        self.assertEqual(ctx["items"][5], {"name": "Custom agents", "tokens": "374", "percent": "0,0 %"})
        self.assertEqual(ctx["deferred"], [{"name": "MCP tools (deferred)", "tokens": "88.3k"},
                                            {"name": "System tools (deferred)", "tokens": "20.7k"}])
        self.assertEqual(app["connected"], 1)
        self.assertEqual(app["results"], ["plan.md", "src/app.py"])
        self.assertEqual(app["changes"], {"added": 2198, "removed": 9})
        self.assertEqual(app["usage"], {"session": {"percent": 44, "reset": "1 h 10 min"}, "weekly": None,
                                        "session_seen_at": 1000, "weekly_seen_at": None})
        self.assertNotIn("tasks", app)
        json.dumps(app)

    def test_english_panel_with_a_weekly_limit(self):
        app = parse_panel("Some chat", en_tree(), 5)
        self.assertEqual(app["context"]["percent"], 61)
        self.assertEqual((app["context"]["used"], app["context"]["window"]), ("598.5k", "1M"))
        self.assertEqual([i["name"] for i in app["context"]["items"]], ["Messages", "Free space"])
        self.assertEqual(app["context"]["deferred"], [{"name": "MCP tools (deferred)", "tokens": "88.3k"}])
        self.assertEqual(app["connected"], 2)
        self.assertEqual(app["results"], ["notes.txt"])
        self.assertEqual(app["changes"], {"added": 1204, "removed": 31})
        self.assertEqual(app["usage"]["session"], {"percent": 12, "reset": "3 h"})
        self.assertEqual(app["usage"]["weekly"], {"percent": 34, "reset": "Sat 11:00"})
        self.assertEqual(app["usage"]["weekly_seen_at"], 5)

    def test_no_conversation_text_leaks(self):
        app = parse_panel("A title", fr_tree(), 1)
        text = json.dumps(app, ensure_ascii=False)
        for leak in LEAKS:
            self.assertNotIn(leak, text)
        # the "Messages / 540.3k" pair of the conversation (outside the Context card) adds nothing
        self.assertEqual([i["name"] for i in app["context"]["items"]].count("Messages"), 1)

    def test_nodes_outside_the_cards_are_ignored(self):
        nodes = filler(5) + conversation() + [B(30, f"Utilisation : 7{NB}% de la limite de session et Réinitialisation dans 2 min")]
        app = parse_panel("t", nodes, 1)
        self.assertIsNone(app["context"])
        self.assertEqual(app["results"], [])
        self.assertIsNone(app["changes"])
        self.assertIsNone(app["connected"])
        self.assertEqual(app["usage"]["session"], {"percent": 7, "reset": "2 min"})

    def test_conversation_wording_alone_is_not_usage(self):
        nodes = filler(5) + [T(38, "Limite de session and Hebdomadaire, with “vu à HH:MM”."),
                             T(38, "Utilisation du CPU à 90 % pendant la session"), B(38, "Hebdomadaire 50 %")]
        self.assertIsNone(parse_panel("t", nodes, 1))

    def test_nothing_found_is_none(self):
        self.assertIsNone(parse_panel("t", filler(200), 1))
        self.assertIsNone(parse_panel("t", [], 1))

    def test_missing_parts_are_none(self):
        nodes = filler(100) + [G(33, "Résultats"), T(38, "only.txt")]
        app = parse_panel("t", nodes, 1)
        self.assertEqual(app["results"], ["only.txt"])
        self.assertIsNone(app["context"])
        self.assertEqual(app["usage"], {"session": None, "weekly": None, "session_seen_at": None,
                                        "weekly_seen_at": None})

    def test_changes_from_plus_and_minus_texts(self):
        nodes = filler(100) + [G(33, "Modifications"), T(36, "+2140"), T(36, "−9")]
        self.assertEqual(parse_panel("t", nodes, 1)["changes"], {"added": 2140, "removed": 9})
        nodes = filler(100) + [G(33, "Modifications"), T(36, "+5")]
        self.assertEqual(parse_panel("t", nodes, 1)["changes"], {"added": 5, "removed": 0})
        nodes = filler(100) + [G(33, "Modifications"), B(36, "Modifications"), G(33, "Résultats"), T(38, "a.txt")]
        self.assertIsNone(parse_panel("t", nodes, 1)["changes"])

    def test_results_are_deduplicated_capped_and_clipped(self):
        names = [f"file{i}.txt" for i in range(60)]
        nodes = filler(100) + [G(33, "Résultats"), B(35, "Réorganiser la carte Résultats")]
        for n in names:
            nodes += [Node(37, "ListItem", n), T(38, n)]
        nodes += [T(38, "x" * 300)]
        app = parse_panel("t", nodes, 1)
        self.assertEqual(app["results"], names[:ui_mod.MAX_RESULTS])
        nodes = filler(100) + [G(33, "Résultats"), T(38, "y" * 300)]
        self.assertIsNone(parse_panel("t", nodes, 1))  # too long to be a file name: dropped, nothing else there

    def test_context_without_the_total(self):
        nodes = filler(100) + [G(33, "Contexte"), T(35, f"61{NB}% utilisé"), T(35, "Messages"), T(35, "540.3k"),
                               T(35, f"54,0{NB}%")]
        ctx = parse_panel("t", nodes, 1)["context"]
        self.assertEqual((ctx["percent"], ctx["used"], ctx["window"]), (61, None, None))
        self.assertEqual(ctx["items"], [{"name": "Messages", "tokens": "540.3k", "percent": "54,0 %"}])

    def test_percentages_not_pairing_with_labels_do_not_shift_the_rows(self):
        nodes = filler(100) + [G(33, "Contexte"), T(35, "Messages"), T(35, "1.0k"), T(35, "Free space"), T(35, "2.0k"),
                               T(35, "3,0 %")]
        items = parse_panel("t", nodes, 1)["context"]["items"]
        self.assertEqual(items, [{"name": "Free space", "tokens": "2.0k", "percent": "3,0 %"}])

    def test_the_title_is_the_session_toolbar_button_not_the_window_title(self):
        nodes = [B(20, "OrizonX App, renommer la session")] + fr_tree()
        self.assertEqual(parse_panel("Claude", nodes, 1)["session_title"], "OrizonX App")
        nodes = [B(20, "Chat about things, rename session")] + en_tree()
        self.assertEqual(parse_panel("Claude", nodes, 1)["session_title"], "Chat about things")
        nodes = [B(20, "A, B, renommer la session")] + fr_tree()
        self.assertEqual(parse_panel("Claude", nodes, 1)["session_title"], "A, B")
        self.assertEqual(parse_panel("Claude", fr_tree(), 1)["session_title"], "Claude")  # no such button: the window

    def test_counts_below_the_deferred_rows_are_not_context_slices(self):
        nodes = filler(100) + [G(33, "Contexte"), T(35, "Free space"), T(35, "346.1k"), T(35, f"34,6{NB}%"),
                               T(35, "MCP tools (deferred)"), T(35, "88.3k"),
                               T(36, "Outils MCP"), T(36, "174"), T(36, "Fichiers mémoire"), T(36, "2")]
        ctx = parse_panel("t", nodes, 1)["context"]
        self.assertEqual([i["name"] for i in ctx["items"]], ["Free space"])
        self.assertEqual([d["name"] for d in ctx["deferred"]], ["MCP tools (deferred)"])

    def test_session_title_is_clipped(self):
        self.assertEqual(len(parse_panel("t" * 500, fr_tree(), 1)["session_title"]), 120)


class PopoverTest(unittest.TestCase):
    """The usage popover makes the weekly line readable: one line, or a label followed by its own texts."""

    def parse(self, nodes):
        anchor = [G(33, "Résultats"), T(38, "keep.txt"), Node(30, "Other", "")]  # so that an app object exists
        return parse_panel("t", filler(100) + anchor + nodes, 77)["usage"]

    def test_label_then_value_texts(self):
        usage = self.parse([T(40, "Limite de session"), T(40, f"44{NB}% utilisé"), T(40, "Réinitialisation dans 1 h 10 min"),
                            T(40, "Hebdomadaire · tous les modèles"), T(40, f"34{NB}% utilisé"),
                            T(40, "Réinitialisation sam. 11:00")])
        self.assertEqual(usage["session"], {"percent": 44, "reset": "1 h 10 min"})
        self.assertEqual(usage["weekly"], {"percent": 34, "reset": "sam. 11:00"})
        self.assertEqual(usage["weekly_seen_at"], 77)

    def test_one_composite_line(self):
        usage = self.parse([B(40, f"Hebdomadaire · tous les modèles 34{NB}% utilisé Réinitialisation sam. 11:00")])
        self.assertEqual(usage["weekly"], {"percent": 34, "reset": "sam. 11:00"})

    def test_english_popover(self):
        usage = self.parse([T(40, "Weekly · all models"), T(40, "21% used"), T(40, "Resets Sat 11:00 AM")])
        self.assertEqual(usage["weekly"], {"percent": 21, "reset": "Sat 11:00 AM"})

    def test_a_label_without_its_values_is_not_a_limit(self):
        usage = self.parse([T(40, "Hebdomadaire · tous les modèles"), T(40, "Limite de session"),
                            T(40, f"44{NB}% utilisé"), T(40, "Réinitialisation dans 3 min")])
        self.assertIsNone(usage["weekly"])  # the next label ends the weekly lines: the 44 % is the session's
        self.assertEqual(usage["session"], {"percent": 44, "reset": "3 min"})

    def test_values_far_below_a_label_are_not_picked_up(self):
        usage = self.parse([T(40, "Hebdomadaire")] + [T(40, "x")] * 10 + [T(40, f"50{NB}%"), T(40, "Réinitialisation demain")])
        self.assertIsNone(usage["weekly"])

    def test_the_status_button_line_is_still_the_session_limit(self):
        usage = self.parse([B(32, f"Utilisation : 76{NB}% de la limite de session et Réinitialisation dans 48 min")])
        self.assertEqual(usage["session"], {"percent": 76, "reset": "48 min"})
        self.assertIsNone(usage["weekly"])


class TasksTest(unittest.TestCase):
    def card(self, rows):
        nodes = [G(33, "Tâches en arrière-plan"), G(34, ""), G(35, ""), B(36, "Tâches en arrière-plan"),
                 B(35, "Réorganiser la carte Tâches en arrière-plan")]
        for name, elapsed, running in rows:
            nodes += [B(36, f"Ouvrir {name} dans Tâches en arrière-plan"), G(37, ""), T(38, name)]
            if elapsed:
                nodes.append(T(37, elapsed))
            if running:
                nodes.append(B(36, "Arrêter cette tâche"))
        return nodes

    def test_running_tasks(self):
        nodes = filler(100) + self.card([("Creative bar Task 1 PC", "3min 46s", True),
                                         ("Creative bar Task 2 Android", "3min 46s", True)]) + [B(36, "3 terminé(s)")]
        app = parse_panel("t", nodes, 1)
        self.assertEqual(app["tasks"], [{"name": "Creative bar Task 1 PC", "status": "running", "elapsed": "3min 46s"},
                                        {"name": "Creative bar Task 2 Android", "status": "running", "elapsed": "3min 46s"}])
        self.assertEqual(app["tasks_done"], 3)

    def test_a_row_without_a_stop_button_is_completed(self):
        nodes = filler(100) + self.card([("Old one", "12s", False), ("Live one", "1h 2min", True)])
        tasks = parse_panel("t", nodes, 1)["tasks"]
        self.assertEqual([(t["name"], t["status"]) for t in tasks], [("Old one", "completed"), ("Live one", "running")])

    def test_the_card_without_rows_gives_an_empty_list(self):
        nodes = filler(100) + self.card([])
        self.assertEqual(parse_panel("t", nodes, 1)["tasks"], [])
        self.assertNotIn("tasks_done", parse_panel("t", nodes, 1))

    def test_no_card_no_key(self):
        self.assertNotIn("tasks", parse_panel("t", fr_tree(), 1))

    def test_english_card(self):
        nodes = filler(100) + [G(33, "Background tasks"), B(36, "Open Build the thing in Background tasks"),
                               T(38, "Build the thing"), T(37, "5s"), B(36, "Stop this task"), B(36, "1 completed")]
        app = parse_panel("t", nodes, 1)
        self.assertEqual(app["tasks"], [{"name": "Build the thing", "status": "running", "elapsed": "5s"}])
        self.assertEqual(app["tasks_done"], 1)

    def test_at_most_ten_rows_and_clipped_names(self):
        nodes = filler(100) + self.card([(f"task {i}", "1s", True) for i in range(15)])
        self.assertEqual(len(parse_panel("t", nodes, 1)["tasks"]), 10)
        nodes = filler(100) + self.card([("n" * 300, "1s", True)])
        self.assertEqual(len(parse_panel("t", nodes, 1)["tasks"][0]["name"]), 120)

    def test_the_card_alone_is_enough_for_an_app_object(self):
        app = parse_panel("t", filler(100) + self.card([("a", "1s", True)]), 1)
        self.assertIsNotNone(app)
        self.assertIsNone(app["context"])


class FakeUi:
    def __init__(self, nodes=None):
        self.nodes = nodes if nodes is not None else fr_tree()
        self.walks = []
        self.invoked = []
        self.invoke_result = True
        self.error = None

    def walk(self, hwnd):
        self.walks.append(hwnd)
        if self.error:
            raise self.error
        return list(self.nodes)

    def invoke(self, hwnd, names):
        self.invoked.append((hwnd, names))
        if self.error:
            raise self.error
        return self.invoke_result

    def toggle(self, hwnd, pattern):
        self.toggled_views = getattr(self, "toggled_views", [])
        self.toggled_views.append((hwnd, pattern))
        if self.error:
            raise self.error
        return self.invoke_result

    def expand(self, hwnd, pattern, wait_s=0.0):
        self.expanded = getattr(self, "expanded", [])
        self.expanded.append((hwnd, pattern, wait_s))
        if self.error:
            raise self.error
        return self.invoke_result

    def ensure_on(self, hwnd, names):
        self.toggled = getattr(self, "toggled", [])
        self.toggled.append((hwnd, names))
        if getattr(self, "toggle_error", None):
            raise self.toggle_error
        return True


class ReaderTest(unittest.TestCase):
    def test_a_warm_tree_is_parsed(self):
        reader = ClaudeAppReader(FakeUi())
        app = reader.read(7, "OrizonX App", 99.7)
        self.assertEqual((app["session_title"], app["seen_at"]), ("OrizonX App", 99))
        self.assertFalse(reader.warming_up)

    def test_fewer_than_a_hundred_elements_is_a_tree_not_awake_yet(self):
        reader = ClaudeAppReader(FakeUi(fr_panel()[:20]))
        self.assertIsNone(reader.read(7, "t", 1))
        self.assertTrue(reader.warming_up)
        self.assertEqual(ui_mod.WARMUP_MIN_NODES, 100)
        reader = ClaudeAppReader(FakeUi(filler(99)))
        self.assertIsNone(reader.read(7, "t", 1))
        self.assertTrue(reader.warming_up)

    def test_errors_give_none_and_are_logged_once(self):
        logs = []
        ui = FakeUi()
        ui.error = OSError("COM")
        reader = ClaudeAppReader(ui, logs.append)
        for _ in range(3):
            self.assertIsNone(reader.read(7, "t", 1))
        self.assertEqual(len(logs), 1)
        self.assertFalse(reader.warming_up)

    def test_the_real_layer_does_not_import_comtypes_here(self):
        self.assertFalse(hasattr(ui_mod, "comtypes"))
        ClaudeAppUi()  # building it touches no UI Automation


class FakeWin32:
    def __init__(self, hwnd=77, title="OrizonX App"):
        self.hwnd, self.title = hwnd, title
        self.calls = []

    def find_window(self):
        self.calls.append("find")
        return self.hwnd

    def window_title(self, hwnd):
        return self.title

    def is_iconic(self, hwnd):
        return False

    def restore(self, hwnd):
        self.calls.append("restore")

    def set_foreground(self, hwnd):
        self.calls.append("foreground")
        return True

    def alt_tap(self):
        self.calls.append("alt")


class Clock:
    def __init__(self):
        self.t = 2_000_000_000.0

    def __call__(self):
        return self.t


class ProviderBase(unittest.TestCase):
    def setUp(self):
        self.home = tempfile.mkdtemp(prefix="orizonx-claudeapp-test-")
        self.addCleanup(shutil.rmtree, self.home, ignore_errors=True)
        folder = os.path.join(self.home, ".claude", "projects", "p")
        os.makedirs(folder)
        self.cwd = os.path.join(self.home, "work")
        os.makedirs(self.cwd)
        with open(os.path.join(folder, "s1.jsonl"), "wb") as f:
            f.write((json.dumps({"type": "user", "cwd": self.cwd, "gitBranch": "main",
                                 "timestamp": "2026-10-19T10:00:00Z"}) + "\n").encode())
        self.clock = Clock()
        self.logs = []
        self.ui = FakeUi()
        self.win32 = FakeWin32()
        self.git_calls = []
        self.git_result = (0, " 3 files changed, 40 insertions(+), 5 deletions(-)\n")
        self.provider = ClaudeCodeProvider(home=self.home, clock=self.clock, win32=self.win32, ui=self.ui,
                                           log=self.logs.append, git_runner=self.git, git_threaded=False)

    def git(self, args, cwd, timeout):
        self.git_calls.append((args, cwd, timeout))
        return self.git_result

    def act(self, action_id, **kw):
        return self.provider.handle(dict(id=action_id, **kw))


class WatchTest(ProviderBase):
    def test_no_app_section_until_the_device_watches(self):
        self.assertNotIn("app", self.provider.snapshot())
        self.assertEqual(self.ui.walks, [])
        self.assertEqual(self.win32.calls, [])

    def test_watching_reads_the_panel(self):
        self.assertIsNone(self.act("claude.watch", open=True))
        snap = self.provider.snapshot()
        self.assertEqual(snap["app"]["session_title"], "OrizonX App")
        self.assertEqual(snap["app"]["context"]["percent"], 61)
        self.assertEqual(self.ui.walks, [77])
        json.dumps(snap)

    def test_at_most_every_three_seconds(self):
        self.act("claude.watch", open=True)
        self.provider.snapshot()
        for _ in range(2):
            self.clock.t += 1.0
            self.assertIn("app", self.provider.snapshot())  # the last read is kept
        self.assertEqual(len(self.ui.walks), 1)
        self.clock.t += 1.1
        self.provider.snapshot()
        self.assertEqual(len(self.ui.walks), 2)

    def test_a_tree_not_awake_is_tried_again_after_a_second(self):
        self.ui.nodes = filler(24)
        self.act("claude.watch", open=True)
        self.assertNotIn("app", self.provider.snapshot())
        self.clock.t += 1.1
        self.ui.nodes = fr_tree()
        self.assertIn("app", self.provider.snapshot())
        self.assertEqual(len(self.ui.walks), 2)

    def test_closing_clears_and_stops_reading(self):
        self.act("claude.watch", open=True)
        self.provider.snapshot()
        self.act("claude.watch", open=False)
        self.clock.t += 10
        self.assertNotIn("app", self.provider.snapshot())
        self.assertEqual(len(self.ui.walks), 1)
        self.act("claude.watch", open=True)
        self.assertIn("app", self.provider.snapshot())  # a fresh read at once

    def test_no_claude_window_no_app(self):
        self.win32.hwnd = 0
        self.act("claude.watch", open=True)
        self.assertNotIn("app", self.provider.snapshot())
        self.assertEqual(self.ui.walks, [])

    def test_an_unreadable_panel_means_no_app_section(self):
        self.ui.error = OSError("COM")
        self.act("claude.watch", open=True)
        self.assertNotIn("app", self.provider.snapshot())

    def test_watch_needs_a_boolean(self):
        for value in (1, "yes", None):
            self.assertIsNone(self.act("claude.watch", open=value))
        self.assertIsNone(self.act("claude.watch"))
        self.provider.snapshot()
        self.assertEqual(self.ui.walks, [])

    def test_no_conversation_text_in_the_whole_section(self):
        self.act("claude.watch", open=True)
        text = json.dumps(self.provider.snapshot(), ensure_ascii=False)
        for leak in LEAKS:
            self.assertNotIn(leak, text)

    def test_results_tail_goes_first_when_the_section_is_too_big(self):
        nodes = filler(100) + [G(33, "Résultats")] + [T(38, f"{i:02d}-" + "é" * 110) for i in range(40)]
        self.ui.nodes = nodes
        self.act("claude.watch", open=True)
        snap = self.provider.snapshot()
        self.assertLessEqual(len(json.dumps(snap, ensure_ascii=False, separators=(",", ":")).encode()),
                             claude_code.SECTION_MAX_BYTES)
        self.assertEqual(len(snap["app"]["results"]), 40)  # fits: untouched
        # now with a long last_result for the session: the app results are shortened before anything else
        for i in range(12):
            folder = os.path.join(self.home, ".claude", "projects", f"q{i}")
            os.makedirs(folder, exist_ok=True)
            rec = {"type": "assistant", "cwd": self.cwd, "timestamp": "2026-10-19T10:00:05Z",
                   "message": {"model": "m", "usage": {"input_tokens": 1}, "content": [{"type": "text", "text": "é" * 1500}]}}
            with open(os.path.join(folder, f"x{i}.jsonl"), "wb") as f:
                f.write((json.dumps(rec) + "\n").encode())
        self.clock.t += 5
        snap = self.provider.snapshot()
        size = len(json.dumps(snap, ensure_ascii=False, separators=(",", ":")).encode())
        self.assertLessEqual(size, claude_code.SECTION_MAX_BYTES)
        self.assertLess(len(snap["app"]["results"]), 40)
        self.assertEqual(snap["app"]["results"], [f"{i:02d}-" + "é" * 110 for i in range(len(snap["app"]["results"]))])
        self.assertTrue(any(len(s["last_result"]) == 1500 for s in snap["sessions"]))  # sessions kept their text


class SidebarActionsTest(ProviderBase):
    def test_the_four_buttons(self):
        cases = {"claude.new": ("Nouveau", "New"), "claude.artifacts": ("Artéfacts", "Artefacts", "Artifacts"),
                 "claude.customize": ("Personnalisation", "Customize"), "claude.more": ("Plus", "More")}
        for action_id, names in cases.items():
            with self.subTest(action_id):
                self.ui.invoked.clear()
                self.win32.calls.clear()
                self.assertIsNone(self.act(action_id))
                self.assertEqual(self.ui.invoked, [(77, names)])
                self.assertIn("foreground", self.win32.calls)

    def test_the_app_is_brought_to_the_front_before_the_invoke(self):
        order = []
        self.win32.set_foreground = lambda h: order.append("front") or True
        self.ui.invoke = lambda h, names: order.append("invoke") or True
        self.act("claude.new")
        self.assertEqual(order, ["front", "invoke"])

    def test_open_invokes_the_item_with_that_title(self):
        self.assertIsNone(self.act("claude.open", title="  ANIMA3.1 "))
        self.assertEqual(self.ui.invoked, [(77, ("ANIMA3.1",))])

    def test_a_button_that_is_not_there_is_the_ui_notice(self):
        self.ui.invoke_result = False
        self.assertEqual(self.act("claude.new"), "claude_ui_not_found")
        self.assertEqual(self.act("claude.open", title="Gone"), "claude_ui_not_found")
        self.assertTrue(self.logs)

    def test_a_layer_error_is_the_ui_notice(self):
        self.ui.error = OSError("COM")
        self.assertEqual(self.act("claude.more"), "claude_ui_not_found")

    def test_app_not_running_is_the_other_notice_and_nothing_is_invoked(self):
        self.win32.hwnd = 0
        self.assertEqual(self.act("claude.new"), "claude_not_running")
        self.assertEqual(self.act("claude.open", title="x"), "claude_not_running")
        self.assertEqual(self.ui.invoked, [])

    def test_bad_titles_are_refused_without_touching_the_app(self):
        for title in (None, "", "   ", 5, ["a"], "t" * 500):
            with self.subTest(title):
                self.assertEqual(self.act("claude.open", title=title), "claude_ui_not_found")
        self.assertEqual(self.ui.invoked, [])
        self.assertEqual(self.win32.calls, [])

    def test_focus_still_works(self):
        self.assertIsNone(self.act("claude.focus"))
        self.assertEqual(self.ui.invoked, [])


class GitStatsTest(unittest.TestCase):
    def make(self, results, **kw):
        self.calls = []
        self.clock = Clock()

        def runner(args, cwd, timeout):
            self.calls.append((args, cwd, timeout))
            for key, result in results:
                if key in args:
                    return result
            return (1, "")
        return GitStats(runner, clock=self.clock, isdir=kw.pop("isdir", lambda p: True), threaded=kw.pop("threaded", False),
                        log=lambda _l: None)

    def test_diff_against_the_merge_base_with_main(self):
        git = self.make([("merge-base", (0, "abc123\n")), ("diff", (0, " 2 files changed, 2140 insertions(+), 9 deletions(-)\n"))])
        self.assertEqual(git.get(r"C:\w\proj"), {"added": 2140, "removed": 9})
        merge = [c for c in self.calls if "merge-base" in c[0]]
        self.assertEqual(merge[0][0], ["git", "merge-base", "HEAD", "main"])
        diff = [c for c in self.calls if "diff" in c[0]][0]
        self.assertEqual(diff[0][-1], "abc123")
        for flag in ("--shortstat", "--no-ext-diff", "core.fsmonitor=false"):
            self.assertIn(flag, diff[0])
        self.assertNotIn("status", diff[0])  # untracked files are not counted
        self.assertEqual(diff[1], r"C:\w\proj")  # run in the folder, never through a shell string

    def test_master_when_there_is_no_main(self):
        git = self.make([("master", (0, "def456\n")), ("diff", (0, " 1 file changed, 3 insertions(+)\n"))])
        self.assertEqual(git.get("/w"), {"added": 3, "removed": 0})
        self.assertEqual([c[0][3] for c in self.calls if "merge-base" in c[0]], ["main", "master"])
        self.assertEqual([c for c in self.calls if "diff" in c[0]][0][0][-1], "def456")

    def test_head_when_neither_branch_exists(self):
        git = self.make([("diff", (0, " 1 file changed, 4 deletions(-)\n"))])
        self.assertEqual(git.get("/w"), {"added": 0, "removed": 4})
        self.assertEqual([c for c in self.calls if "diff" in c[0]][0][0][-1], "HEAD")

    def test_no_change_is_zero_zero(self):
        git = self.make([("merge-base", (0, "abc\n")), ("diff", (0, ""))])
        self.assertEqual(git.get("/w"), {"added": 0, "removed": 0})

    def test_not_a_repository_or_git_missing_is_none(self):
        self.assertIsNone(self.make([("diff", (128, "fatal: not a git repository"))]).get("/w"))
        self.assertIsNone(self.make([("diff", None), ("merge-base", None)]).get("/w"))
        self.assertIsNone(self.make([], isdir=lambda p: False).get("/gone"))
        git = self.make([])
        self.assertIsNone(git.get(""))
        self.assertIsNone(git.get("bad\0path"))

    def test_cached_for_thirty_seconds(self):
        git = self.make([("diff", (0, " 1 file changed, 1 insertion(+)\n"))])
        git.get("/w")
        n = len(self.calls)
        self.clock.t += 29
        git.get("/w")
        self.assertEqual(len(self.calls), n)
        self.clock.t += 2
        git.get("/w")
        self.assertGreater(len(self.calls), n)

    def test_a_failure_is_cached_too(self):
        git = self.make([])
        git.get("/w")
        n = len(self.calls)
        git.get("/w")
        self.assertEqual(len(self.calls), n)

    def test_the_same_folder_with_other_slashes_shares_the_cache(self):
        git = self.make([("diff", (0, " 1 file changed, 1 insertion(+)\n"))])
        git.get(r"C:\W\Proj")
        n = len(self.calls)
        git.get("c:/w/proj/")
        self.assertEqual(len(self.calls), n)

    def test_the_background_thread_never_blocks_the_caller(self):
        gate, entered = threading.Event(), threading.Event()

        def slow(args, cwd, timeout):
            entered.set()
            gate.wait(5)
            return (0, " 1 file changed, 7 insertions(+)\n")

        git = GitStats(slow, threaded=True, isdir=lambda p: True, log=lambda _l: None)
        started = time.monotonic()
        self.assertIsNone(git.get("/w"))
        self.assertLess(time.monotonic() - started, 1.0)
        self.assertTrue(entered.wait(5))
        self.assertIsNone(git.get("/w"))  # still computing: no second job
        gate.set()
        self.assertTrue(git.wait_idle(5))
        self.assertEqual(git.get("/w"), {"added": 7, "removed": 0})

    def test_the_default_runner_survives_a_missing_git_and_a_bad_folder(self):
        self.assertIsNone(claude_code.default_git_runner(["git-does-not-exist-xyz", "--version"], os.getcwd(), 2))



class ShowViewsTest(ProviderBase):
    def test_the_patterns_match_the_real_names_and_nothing_else(self):
        import re
        usage = re.compile(ui_mod.USAGE_BUTTON, re.I)
        for name in ("Utilisation : 76 % de la limite de session et Réinitialisation dans 48 min",
                     "Utilisation: 4 % de la limite de session", "Usage: 12% of session limit and Resets in 3 h"):
            self.assertTrue(usage.search(name), name)
        for name in ("Utilisation du CPU", "Limite d'utilisation de session bientôt atteinte", "Compacter la session"):
            self.assertFalse(usage.search(name), name)
        context = re.compile(ui_mod.CONTEXT_HEADER, re.I)
        for name in ("Contexte", "Context", "Contexte 64 %", "Context 7 %"):  # collapsed card shows its percent
            self.assertTrue(context.search(name), name)
        for name in ("Contexte détaillé", "Réorganiser la carte Contexte", "Environnement"):
            self.assertFalse(context.search(name))

    def test_show_usage_brings_the_app_up_then_toggles_the_usage_button(self):
        order = []
        self.win32.set_foreground = lambda h: order.append("front") or True
        self.ui.toggle = lambda h, p: order.append(("toggle", h, p)) or True
        self.assertIsNone(self.act("claude.show_usage"))
        self.assertEqual(order, ["front", ("toggle", 77, ui_mod.USAGE_BUTTON)])

    def test_show_context_shows_the_rail_then_expands_the_context_card(self):
        self.assertIsNone(self.act("claude.show_context"))
        self.assertEqual(self.ui.toggled, [(77, ui_mod.RAIL_TOGGLES)])
        self.assertEqual(self.ui.expanded, [(77, ui_mod.CONTEXT_HEADER, 1.0)])  # waits a moment for the rail to appear
        self.assertIn("Panneau des sessions", ui_mod.RAIL_TOGGLES)

    def test_a_missing_rail_toggle_is_not_fatal_for_the_context(self):
        self.ui.toggle_error = OSError("no toggle")
        self.assertIsNone(self.act("claude.show_context"))
        self.assertEqual(len(self.ui.expanded), 1)

    def test_not_found_is_the_ui_notice_and_not_running_the_other(self):
        self.ui.invoke_result = False
        self.assertEqual(self.act("claude.show_usage"), "claude_ui_not_found")
        self.assertEqual(self.act("claude.show_context"), "claude_ui_not_found")
        self.ui.error = OSError("COM")
        self.assertEqual(self.act("claude.show_usage"), "claude_ui_not_found")
        self.win32.hwnd = 0
        self.ui.error = None
        self.assertEqual(self.act("claude.show_usage"), "claude_not_running")
        self.assertEqual(self.act("claude.show_context"), "claude_not_running")

    def test_nothing_is_clicked_with_the_mouse(self):
        self.act("claude.show_usage")
        self.assertEqual(self.ui.invoked, [])  # only the pattern-based calls above


class CompactTest(ProviderBase):
    def test_compact_brings_the_app_up_then_invokes_the_panel_button(self):
        order = []
        self.win32.set_foreground = lambda h: order.append("front") or True
        self.ui.invoke = lambda h, names: order.append(("invoke", h, names)) or True
        self.assertIsNone(self.act("claude.compact"))
        self.assertEqual(order, ["front", ("invoke", 77, ("Compacter la session", "Compact session"))])

    def test_compact_failures(self):
        self.ui.invoke_result = False
        self.assertEqual(self.act("claude.compact"), "claude_ui_not_found")
        self.ui.error = OSError("COM")
        self.assertEqual(self.act("claude.compact"), "claude_ui_not_found")
        self.win32.hwnd = 0
        self.ui.error = None
        self.assertEqual(self.act("claude.compact"), "claude_not_running")

    def test_the_names_are_the_real_button_names(self):
        self.assertIn("Compacter la session", ui_mod.COMPACT_NAMES)  # read on the real tree
        self.assertIn("Compact session", ui_mod.COMPACT_NAMES)


class FakeElement:
    def __init__(self, name, ctype, expand_state=None, children=()):
        self.CurrentName = name
        self.CurrentControlType = ctype
        self.expand_state = expand_state
        self.children = list(children)
        self.calls = []

    def GetCurrentPropertyValue(self, prop):
        if prop == "prop_expand":
            return self.expand_state is not None
        return False

    def GetCurrentPattern(self, pattern_id):
        return self

    def QueryInterface(self, iface):
        return self

    @property
    def CurrentExpandCollapseState(self):
        return self.expand_state

    def Expand(self):
        self.calls.append("Expand")
        self.expand_state = 1

    def Collapse(self):
        self.calls.append("Collapse")
        self.expand_state = 0


class FakeWalker:
    def __init__(self):
        self.parent = {}

    def register(self, element):
        for child in element.children:
            self.parent[id(child)] = element
            self.register(child)

    def GetFirstChildElement(self, element):
        return element.children[0] if element.children else None

    def GetNextSiblingElement(self, element):
        parent = self.parent.get(id(element))
        if parent is None:
            return None
        siblings = parent.children
        i = siblings.index(element)
        return siblings[i + 1] if i + 1 < len(siblings) else None


class ToggleLayerTest(unittest.TestCase):
    """UiaLayer.expand_matching on a fake UI Automation: expand when collapsed, collapse when expanded (toggle)."""

    BUTTON = 50000

    def layer(self, state):
        import threading
        from actions.browser_url import UiaLayer
        button = FakeElement("Utilisation : 76 % de la limite de session et Réinitialisation dans 48 min", self.BUTTON, state)
        other = FakeElement("Utilisation du CPU", self.BUTTON, 0)
        root = FakeElement("Claude", 0, None, [other, FakeElement("bar", 0, None, [button])])
        walker = FakeWalker()
        walker.register(root)

        class Uia:
            RawViewWalker = walker

            def ElementFromHandle(self, hwnd):
                return root

        client = type("Client", (), {
            "UIA_GroupControlTypeId": 1, "UIA_TextControlTypeId": 2, "UIA_ButtonControlTypeId": self.BUTTON,
            "UIA_ListItemControlTypeId": 4, "UIA_ToolBarControlTypeId": 5, "UIA_TreeItemControlTypeId": 6,
            "UIA_HyperlinkControlTypeId": 7, "UIA_IsExpandCollapsePatternAvailablePropertyId": "prop_expand",
            "UIA_IsInvokePatternAvailablePropertyId": "prop_invoke", "UIA_ExpandCollapsePatternId": 1,
            "UIA_InvokePatternId": 2, "IUIAutomationExpandCollapsePattern": object,
            "IUIAutomationInvokePattern": object})
        layer = UiaLayer()
        layer._uia, layer._client, layer._thread = Uia(), client, threading.get_ident()
        return layer, button

    def test_collapsed_is_expanded_by_both_modes(self):
        for toggle in (False, True):
            layer, button = self.layer(0)
            self.assertTrue(layer.expand_matching(1, ui_mod.USAGE_BUTTON, 0.0, toggle))
            self.assertEqual(button.calls, ["Expand"])

    def test_expanded_is_collapsed_only_when_toggling(self):
        layer, button = self.layer(1)
        self.assertTrue(layer.expand_matching(1, ui_mod.USAGE_BUTTON, 0.0, False))
        self.assertEqual(button.calls, [])  # show_context: already open, left alone
        self.assertTrue(layer.expand_matching(1, ui_mod.USAGE_BUTTON, 0.0, True))
        self.assertEqual(button.calls, ["Collapse"])

    def test_toggling_twice_goes_back_and_forth(self):
        layer, button = self.layer(0)
        for _ in range(3):
            layer.expand_matching(1, ui_mod.USAGE_BUTTON, 0.0, True)
        self.assertEqual(button.calls, ["Expand", "Collapse", "Expand"])

    def test_no_such_button(self):
        layer, button = self.layer(0)
        self.assertFalse(layer.expand_matching(1, r"^Rien$", 0.0, True))
        self.assertEqual(button.calls, [])


class IndependentLimitsTest(ProviderBase):
    SESSION = B(32, f"Utilisation : 76{NB}% de la limite de session et Réinitialisation dans 48 min")
    WEEKLY = B(32, f"Utilisation : Hebdomadaire · tous les modèles : 62% et Réinitialisation le sam. 11:00")

    def read(self, button):
        self.ui.nodes = filler(120) + [G(33, "Résultats"), T(38, "a.txt"), Node(30, "Other", ""), button]
        self.clock.t += 4
        usage = self.provider.snapshot()["app"]["usage"]
        return usage, int(self.clock.t)

    def test_the_status_button_shows_one_limit_at_a_time(self):
        usage = parse_panel("t", filler(100) + [self.WEEKLY], 5)["usage"]
        self.assertEqual(usage["weekly"], {"percent": 62, "reset": "sam. 11:00"})
        self.assertIsNone(usage["session"])
        usage = parse_panel("t", filler(100) + [self.SESSION], 5)["usage"]
        self.assertEqual(usage["session"], {"percent": 76, "reset": "48 min"})
        self.assertIsNone(usage["weekly"])

    def test_each_limit_survives_a_read_that_brings_only_the_other(self):
        self.act("claude.watch", open=True)
        usage, t_session = self.read(self.SESSION)
        self.assertEqual((usage["session"]["percent"], usage["session_seen_at"]), (76, t_session))
        self.assertIsNone(usage["weekly"])
        self.assertIsNone(usage["weekly_seen_at"])
        usage, t_weekly = self.read(self.WEEKLY)
        self.assertEqual((usage["weekly"]["percent"], usage["weekly_seen_at"]), (62, t_weekly))
        self.assertEqual((usage["session"]["percent"], usage["session_seen_at"]), (76, t_session))  # kept, own time
        usage, _ = self.read(self.SESSION)
        self.assertEqual(usage["weekly_seen_at"], t_weekly)  # and the weekly one survives in turn
        self.assertEqual(usage["weekly"]["percent"], 62)

    def test_a_new_value_replaces_the_old_one_with_a_new_time(self):
        self.act("claude.watch", open=True)
        self.read(self.SESSION)
        usage, t = self.read(B(32, f"Utilisation : 81{NB}% de la limite de session et Réinitialisation dans 30 min"))
        self.assertEqual((usage["session"]["percent"], usage["session_seen_at"]), (81, t))

    def test_a_read_with_neither_keeps_both(self):
        self.act("claude.watch", open=True)
        self.read(self.SESSION)
        self.read(self.WEEKLY)
        usage, _ = self.read(T(32, "something else"))
        self.assertEqual((usage["session"]["percent"], usage["weekly"]["percent"]), (76, 62))

    def test_never_read_stays_none_with_no_time(self):
        self.act("claude.watch", open=True)
        usage, _ = self.read(T(32, "nothing"))
        self.assertEqual((usage["session"], usage["weekly"], usage["session_seen_at"], usage["weekly_seen_at"]),
                         (None, None, None, None))


class WeeklyKeptTest(ProviderBase):
    POPOVER = [T(40, "Hebdomadaire · tous les modèles"), T(40, f"34{NB}% utilisé"), T(40, "Réinitialisation sam. 11:00")]

    def read(self, nodes):
        self.ui.nodes = filler(120) + nodes + [B(32, f"Utilisation : 44{NB}% de la limite de session et Réinitialisation dans 1 h")]
        self.clock.t += 4
        return self.provider.snapshot()["app"]["usage"]

    def test_the_last_weekly_limit_survives_the_popover_closing(self):
        self.act("claude.watch", open=True)
        first = self.read(self.POPOVER)
        seen = int(self.clock.t)
        self.assertEqual(first["weekly"], {"percent": 34, "reset": "sam. 11:00"})
        self.assertEqual(first["weekly_seen_at"], seen)
        later = self.read([])
        self.assertEqual(later["weekly"], {"percent": 34, "reset": "sam. 11:00"})
        self.assertEqual(later["weekly_seen_at"], seen)  # its own time, not the time of this read
        self.assertEqual(later["session"]["percent"], 44)
        newer = self.read([T(40, "Hebdomadaire · tous les modèles"), T(40, f"36{NB}% utilisé"),
                           T(40, "Réinitialisation sam. 11:00")])
        self.assertEqual(newer["weekly"]["percent"], 36)
        self.assertEqual(newer["weekly_seen_at"], int(self.clock.t))

    def test_nothing_is_invented_before_a_weekly_limit_was_ever_seen(self):
        self.act("claude.watch", open=True)
        usage = self.read([])
        self.assertIsNone(usage["weekly"])
        self.assertIsNone(usage["weekly_seen_at"])


class ChangesTest(ProviderBase):
    def test_sessions_carry_their_changes(self):
        snap = self.provider.snapshot()
        self.assertEqual(snap["sessions"][0]["changes"], {"added": 40, "removed": 5})
        self.assertEqual(self.git_calls[0][1], self.cwd)

    def test_unknown_changes_are_none(self):
        self.git_result = None
        self.assertIsNone(self.provider.snapshot()["sessions"][0]["changes"])

    def test_changes_are_refreshed_after_thirty_seconds(self):
        self.provider.snapshot()
        n = len(self.git_calls)
        self.provider.snapshot()
        self.assertEqual(len(self.git_calls), n)


if __name__ == "__main__":
    unittest.main()
