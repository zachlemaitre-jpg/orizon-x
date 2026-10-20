import json
import os
import shutil
import tempfile
import unittest

from actions import claude_code
from actions.claude_code import ClaudeCodeProvider, RealFs


class CountingFs(RealFs):
    """The real file system on a temp folder, counting the bytes read from the session files."""

    def __init__(self):
        self.reads = []

    def read_range(self, path, start, end):
        data = super().read_range(path, start, end)
        self.reads.append((os.path.basename(path), start, len(data)))
        return data

    def bytes_read(self, name=None):
        return sum(n for p, _s, n in self.reads if name is None or p == name)


class Clock:
    def __init__(self, t=2_000_000_000.0):
        self.t = t

    def __call__(self):
        return self.t


def iso(text):
    from datetime import datetime
    return int(datetime.fromisoformat(text.replace("Z", "+00:00")).timestamp())


def line(**record):
    return json.dumps(record, ensure_ascii=False)


def user(**kw):
    base = {"type": "user", "cwd": r"C:\Users\me\proj\app", "gitBranch": "main", "entrypoint": "cli",
            "permissionMode": "default", "timestamp": "2026-10-19T10:00:00.000Z",
            "message": {"role": "user", "content": "hello"}}
    base.update(kw)
    return line(**base)


def assistant(text="done", model="claude-opus-5", usage=None, **kw):
    base = {"type": "assistant", "cwd": r"C:\Users\me\proj\app", "gitBranch": "main", "entrypoint": "cli",
            "effort": "high", "timestamp": "2026-10-19T10:00:05.000Z",
            "message": {"role": "assistant", "model": model,
                        "usage": usage or {"input_tokens": 10, "cache_read_input_tokens": 200,
                                           "cache_creation_input_tokens": 30, "output_tokens": 5},
                        "content": [{"type": "text", "text": text}]}}
    base.update(kw)
    return line(**base)


class Base(unittest.TestCase):
    def setUp(self):
        self.home = tempfile.mkdtemp(prefix="orizonx-claude-test-")
        self.addCleanup(shutil.rmtree, self.home, ignore_errors=True)
        self.root = os.path.join(self.home, ".claude", "projects")
        self.fs = CountingFs()
        self.clock = Clock()
        self.logs = []
        self.n = 0
        self.provider = self.make()

    def make(self, **kw):
        return ClaudeCodeProvider(home=self.home, clock=self.clock, fs=self.fs, log=self.logs.append, **kw)

    def write(self, name, lines, project="proj-a", age=100.0, mode="w"):
        folder = os.path.join(self.root, project)
        os.makedirs(folder, exist_ok=True)
        path = os.path.join(folder, name + ".jsonl")
        with open(path, mode + "b") as f:
            f.write(("\n".join(lines) + "\n").encode("utf-8"))
        mtime = self.clock.t - age
        os.utime(path, (mtime, mtime))
        return path

    def append(self, path, lines, age=1.0, raw=None):
        with open(path, "ab") as f:
            f.write(raw if raw is not None else ("\n".join(lines) + "\n").encode("utf-8"))
        mtime = self.clock.t - age
        os.utime(path, (mtime, mtime))

    def sessions(self, provider=None):
        snap = (provider or self.provider).snapshot()
        self.assertTrue(snap["available"], snap)
        return snap["sessions"]

    def one(self, lines, **kw):
        self.write("abcdef12-0000", lines, **kw)
        sessions = self.sessions()
        self.assertEqual(len(sessions), 1)
        return sessions[0]


class AvailabilityTest(Base):
    def test_no_projects_folder_is_unavailable(self):
        self.assertEqual(self.provider.snapshot(), {"available": False})

    def test_empty_projects_folder_is_available_with_nothing(self):
        os.makedirs(self.root)
        self.assertEqual(self.provider.snapshot(), {"available": True, "sessions": [], "connectors": []})

    def test_the_snapshot_is_json(self):
        self.write("s1", [user(), assistant()])
        json.dumps(self.provider.snapshot())


class FieldsTest(Base):
    def test_every_field(self):
        s = self.one([
            line(type="custom-title", customTitle="Fix the bug", sessionId="x"),
            user(permissionMode="plan", timestamp="2026-10-19T10:00:00.000Z"),
            assistant("The answer", model="claude-opus-5", timestamp="2026-10-19T10:00:07.000Z"),
            line(type="last-prompt", lastPrompt="do the thing", sessionId="x"),
            line(type="file-history-snapshot", snapshot={"trackedFileBackups": {
                r"C:\Users\me\proj\app\src\b.py": {}, r"C:\Users\me\proj\app\a.py": {}, r"D:\elsewhere\z.txt": {}}}),
        ])
        self.assertEqual(s["id"], "abcdef12-0000")
        self.assertEqual(s["title"], "Fix the bug")
        self.assertEqual((s["project"], s["branch"]), ("app", "main"))
        self.assertEqual(s["model"], "claude-opus-5")
        self.assertEqual((s["effort"], s["mode"]), ("high", "plan"))
        self.assertEqual(s["tokens"], 240)
        self.assertEqual(s["last_prompt"], "do the thing")
        self.assertEqual(s["last_result"], "The answer")
        self.assertEqual(s["files"], ["D:/elsewhere/z.txt", "a.py", "src/b.py"])  # relative to cwd, sorted
        self.assertEqual(s["entry"], "cli")
        self.assertEqual(s["status"], "idle")
        self.assertEqual(s["updated"], iso("2026-10-19T10:00:07Z"))
        self.assertEqual(set(s), {"id", "title", "project", "branch", "updated", "status", "model", "effort", "mode",
                                  "tokens", "last_prompt", "last_result", "files", "entry"})

    def test_the_last_one_wins(self):
        s = self.one([
            line(type="custom-title", customTitle="First"), line(type="custom-title", customTitle="Second"),
            user(cwd="/old/one", gitBranch="a", permissionMode="default"),
            assistant("one", model="m1", effort="low", usage={"input_tokens": 1}),
            assistant("two", model="m2", effort="max", usage={"input_tokens": 2, "cache_read_input_tokens": 3}),
            line(type="last-prompt", lastPrompt="p1"), line(type="last-prompt", lastPrompt="p2"),
            user(cwd="/new/two", gitBranch="b", permissionMode="acceptEdits"),
        ])
        self.assertEqual((s["title"], s["project"], s["branch"], s["mode"]), ("Second", "two", "b", "acceptEdits"))
        self.assertEqual((s["model"], s["effort"], s["tokens"], s["last_result"], s["last_prompt"]),
                         ("m2", "max", 5, "two", "p2"))

    def test_title_falls_back_to_the_slug_then_the_short_id(self):
        s = self.one([user(slug="cool-slug-name"), assistant()])
        self.assertEqual(s["title"], "cool-slug-name")
        self.write("deadbeef-1111-2222", [user(), assistant()], project="proj-b", age=50)
        by_id = {x["id"]: x for x in self.sessions()}
        self.assertEqual(by_id["deadbeef-1111-2222"]["title"], "deadbeef")

    def test_custom_title_beats_a_later_slug(self):
        s = self.one([line(type="custom-title", customTitle="Mine"), user(slug="later-slug")])
        self.assertEqual(s["title"], "Mine")

    def test_requested_model_beats_the_message_model(self):
        s = self.one([user(), assistant(model="claude-sonnet-x", requestedModel="opus[1m]")])
        self.assertEqual(s["model"], "opus[1m]")

    def test_synthetic_models_and_empty_usage_do_not_overwrite(self):
        s = self.one([user(), assistant("real", model="claude-opus-5"),
                      assistant("error", model="<synthetic>", usage={"input_tokens": 0})])
        self.assertEqual(s["model"], "claude-opus-5")
        self.assertEqual(s["tokens"], 240)

    def test_last_result_is_the_last_assistant_with_a_text_block(self):
        tool_only = line(type="assistant", message={"role": "assistant", "model": "m", "content": [
            {"type": "tool_use", "name": "Bash", "input": {}}], "usage": {"input_tokens": 1}})
        s = self.one([user(), assistant("the real answer"), tool_only])
        self.assertEqual(s["last_result"], "the real answer")

    def test_text_blocks_are_concatenated_and_other_blocks_skipped(self):
        rec = line(type="assistant", message={"role": "assistant", "model": "m", "usage": {"input_tokens": 1}, "content": [
            {"type": "thinking", "thinking": "hmm"}, {"type": "text", "text": "Hello "},
            {"type": "tool_use", "name": "X"}, {"type": "text", "text": "world"}]})
        self.assertEqual(self.one([rec])["last_result"], "Hello world")

    def test_truncations(self):
        s = self.one([user(), assistant("r" * 5000), line(type="last-prompt", lastPrompt="p" * 1000)])
        self.assertEqual(len(s["last_result"]), 1500)
        self.assertTrue(s["last_result"].endswith("…"))
        self.assertEqual(len(s["last_prompt"]), 300)

    def test_text_at_the_limit_is_kept_whole(self):
        s = self.one([assistant("x" * 1500), line(type="last-prompt", lastPrompt="y" * 300)])
        self.assertEqual(len(s["last_result"]), 1500)
        self.assertNotIn("…", s["last_result"])
        self.assertEqual(s["last_prompt"], "y" * 300)

    def test_files_are_capped_at_twenty_and_sorted(self):
        backups = {f"C:/Users/me/proj/app/f{i:02d}.txt": {} for i in range(30)}
        s = self.one([user(), line(type="file-history-snapshot", snapshot={"trackedFileBackups": backups})])
        self.assertEqual(s["files"], [f"f{i:02d}.txt" for i in range(20)])

    def test_the_last_snapshot_replaces_the_previous_ones(self):
        s = self.one([user(), line(type="file-history-snapshot", snapshot={"trackedFileBackups": {"a.txt": {}}}),
                      line(type="file-history-snapshot", snapshot={"trackedFileBackups": {"b.txt": {}}})])
        self.assertEqual(s["files"], ["b.txt"])

    def test_entry_point(self):
        self.assertEqual(self.one([user(entrypoint="claude-desktop")])["entry"], "desktop")
        self.write("zzz", [user(entrypoint="vscode")], project="p3", age=500)
        by_id = {x["id"]: x for x in self.sessions()}
        self.assertEqual(by_id["zzz"]["entry"], "cli")

    def test_updated_is_the_latest_timestamp_else_the_file_time(self):
        s = self.one([user(timestamp="2026-10-19T10:00:00Z"), assistant(timestamp="2026-10-19T09:00:00Z")])
        self.assertEqual(s["updated"], iso("2026-10-19T10:00:00Z"))
        self.write("no-ts", [line(type="custom-title", customTitle="x")], project="p2", age=90)
        by_id = {x["id"]: x for x in self.sessions()}
        self.assertEqual(by_id["no-ts"]["updated"], int(self.clock.t - 90))

    def test_unknown_fields_are_empty(self):
        s = self.one([line(type="custom-title", customTitle="Only a title")])
        self.assertEqual((s["model"], s["effort"], s["mode"], s["branch"], s["project"], s["last_prompt"],
                          s["last_result"], s["files"]), ("", "", "", "", "", "", "", []))
        self.assertIsNone(s["tokens"])
        self.assertEqual(s["entry"], "cli")

    def test_invalid_lines_are_ignored(self):
        path = self.write("bad", [user(), "{not json", "", "[1,2]", "null", '"text"', assistant("ok")])
        s = self.sessions()[0]
        self.assertEqual(s["last_result"], "ok")
        self.assertTrue(os.path.exists(path))

    def test_non_string_values_do_not_break_the_parse(self):
        weird = [line(type="user", cwd=5, gitBranch=["x"], permissionMode={"a": 1}, timestamp=12),
                 line(type="assistant", message="not a dict", effort=3, requestedModel=7),
                 line(type="assistant", message={"content": "not a list", "usage": "nope"}),
                 line(type="custom-title", customTitle=3), line(type="last-prompt", lastPrompt=None),
                 line(type="file-history-snapshot", snapshot=[1]), user(), assistant("fine")]
        s = self.one(weird)
        self.assertEqual(s["last_result"], "fine")


class StatusAndSelectionTest(Base):
    def test_status_follows_the_age_of_the_file(self):
        self.write("fresh", [user()], age=14.0)
        self.write("stale", [user()], project="p2", age=16.0)
        by_id = {s["id"]: s for s in self.sessions()}
        self.assertEqual((by_id["fresh"]["status"], by_id["stale"]["status"]), ("working", "idle"))
        self.clock.t += 2.0
        by_id = {s["id"]: s for s in self.sessions()}
        self.assertEqual(by_id["fresh"]["status"], "idle")

    def test_the_twelve_most_recent_files_of_all_projects(self):
        for i in range(15):
            self.write(f"s{i:02d}", [user()], project=f"proj-{i % 3}", age=1000 - i * 10)
        ids = [s["id"] for s in self.sessions()]
        self.assertEqual(ids, [f"s{i:02d}" for i in range(14, 2, -1)])  # newest first

    def test_subfolders_and_other_files_are_ignored(self):
        self.write("main", [user()], age=50)
        folder = os.path.join(self.root, "proj-a")
        os.makedirs(os.path.join(folder, "main", "subagents"))
        with open(os.path.join(folder, "main", "subagents", "agent-1.jsonl"), "wb") as f:
            f.write((user() + "\n").encode())
        os.makedirs(os.path.join(folder, "memory"))
        with open(os.path.join(folder, "notes.txt"), "wb") as f:
            f.write(b"x")
        os.makedirs(os.path.join(folder, "folder.jsonl"))
        with open(os.path.join(self.root, "stray.jsonl"), "wb") as f:  # not inside a project folder
            f.write(b"x")
        self.assertEqual([s["id"] for s in self.sessions()], ["main"])

    def test_an_unreadable_session_is_skipped(self):
        self.write("ok", [user()], age=10)
        self.write("gone", [user()], project="p2", age=5)
        real = self.fs.read_range

        def flaky(path, start, end):
            if path.endswith("gone.jsonl"):
                raise PermissionError("locked")
            return real(path, start, end)
        self.fs.read_range = flaky
        self.assertEqual([s["id"] for s in self.sessions()], ["ok"])
        self.assertTrue(self.logs)


class IncrementalTest(Base):
    def test_first_read_takes_the_last_two_mebibytes_and_skips_the_cut_line(self):
        head = line(type="custom-title", customTitle="Cut line title that must not be seen")
        filler = [line(type="queue-operation", content="z" * 1000, timestamp="2026-10-19T10:00:00Z") for _ in range(2500)]
        tail = [user(), assistant("the end")]
        path = self.write("big", [head] + filler + tail)
        size = os.path.getsize(path)
        self.assertGreater(size, 2 * 1024 * 1024)
        s = self.sessions()[0]
        self.assertEqual(s["last_result"], "the end")
        self.assertNotEqual(s["title"], "Cut line title that must not be seen")
        self.assertLessEqual(self.fs.bytes_read("big.jsonl"), 2 * 1024 * 1024)

    def test_a_cut_first_line_is_never_parsed_even_if_it_is_valid_json_at_the_boundary(self):
        # the window starts in the middle of a line whose tail is itself valid JSON
        inner = json.dumps({"type": "custom-title", "customTitle": "ghost"})
        padding = line(type="queue-operation", content=" " * 100, extra=inner)
        lines = [padding] * 30000 + [user(), assistant("last")]
        self.write("edge", lines)
        s = self.sessions()[0]
        self.assertEqual(s["title"], "edge")  # short id: the ghost title was not taken

    def test_small_files_are_read_from_the_start(self):
        self.write("small", [line(type="custom-title", customTitle="From the first line"), user()])
        self.assertEqual(self.sessions()[0]["title"], "From the first line")

    def test_second_snapshot_reads_nothing_when_nothing_changed(self):
        self.write("s", [user(), assistant()])
        self.sessions()
        self.fs.reads.clear()
        self.sessions()
        self.assertEqual(self.fs.reads, [])

    def test_only_the_appended_bytes_are_read(self):
        path = self.write("s", [user(), assistant("first")])
        self.sessions()
        before = os.path.getsize(path)
        extra = assistant("second")
        self.fs.reads.clear()
        self.append(path, [extra])
        s = self.sessions()[0]
        self.assertEqual(s["last_result"], "second")
        self.assertEqual(self.fs.bytes_read("s.jsonl"), len(extra.encode()) + 1)
        self.assertEqual(self.fs.reads[0][1], before)

    def test_a_line_being_written_is_completed_by_the_next_pass(self):
        path = self.write("s", [user(), assistant("first")])
        self.sessions()
        text = assistant("second")
        self.append(path, [], raw=(text[:40]).encode())
        self.assertEqual(self.sessions()[0]["last_result"], "first")  # half a line: waits
        self.append(path, [], raw=(text[40:] + "\n").encode())
        self.assertEqual(self.sessions()[0]["last_result"], "second")

    def test_a_last_line_without_newline_is_taken_when_it_is_complete_json(self):
        folder = os.path.join(self.root, "p")
        os.makedirs(folder)
        path = os.path.join(folder, "nonl.jsonl")
        with open(path, "wb") as f:
            f.write((user() + "\n" + assistant("no newline")).encode())
        self.assertEqual(self.sessions()[0]["last_result"], "no newline")
        self.fs.reads.clear()
        self.append(path, [assistant("next")], raw=("\n" + assistant("next") + "\n").encode())
        self.assertEqual(self.sessions()[0]["last_result"], "next")

    def test_a_shortened_file_is_read_again_from_scratch(self):
        path = self.write("s", [line(type="custom-title", customTitle="Old"), user(), assistant("a" * 200)])
        self.assertEqual(self.sessions()[0]["title"], "Old")
        self.write("s", [line(type="custom-title", customTitle="New")], age=3)
        s = self.sessions()[0]
        self.assertEqual(s["title"], "New")
        self.assertEqual(s["last_result"], "")  # nothing of the old content survives
        self.assertTrue(os.path.getsize(path) < 200)

    def test_a_replaced_file_of_the_same_size_is_read_again(self):
        path = self.write("s", [line(type="custom-title", customTitle="AAAA")], age=100)
        self.assertEqual(self.sessions()[0]["title"], "AAAA")
        self.write("s", [line(type="custom-title", customTitle="BBBB")], age=50)
        self.assertEqual(self.sessions()[0]["title"], "BBBB")

    def test_a_file_that_vanishes_disappears_from_the_list(self):
        path = self.write("s", [user()])
        self.assertEqual(len(self.sessions()), 1)
        os.remove(path)
        self.assertEqual(self.sessions(), [])

    def test_a_huge_append_is_read_through_the_window(self):
        path = self.write("s", [user(), assistant("old")])
        self.sessions()
        filler = [line(type="queue-operation", content="z" * 1000) for _ in range(2600)]
        self.fs.reads.clear()
        self.append(path, filler + [assistant("new")])
        self.assertEqual(self.sessions()[0]["last_result"], "new")
        self.assertLessEqual(self.fs.bytes_read("s.jsonl"), 2 * 1024 * 1024)


class SizeLimitTest(Base):
    def test_the_section_stays_within_the_budget_shortening_the_oldest_first(self):
        for i in range(12):
            self.write(f"s{i:02d}", [user(), assistant("é" * 1500), line(type="last-prompt", lastPrompt="p" * 300)],
                       project=f"p{i}", age=1000 - i * 10)
        snap = self.provider.snapshot()
        size = len(json.dumps(snap, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))
        self.assertLessEqual(size, claude_code.SECTION_MAX_BYTES)
        self.assertLess(claude_code.SECTION_MAX_BYTES, 64 * 1024)  # room left for the other sections of the state
        results = [s["last_result"] for s in snap["sessions"]]  # newest first
        self.assertEqual(results[0], "é" * 1500)  # the newest is whole
        lengths = [len(r) for r in results]
        self.assertTrue(any(n < 1500 for n in lengths))
        shortened = [i for i, n in enumerate(lengths) if n < 1500]
        self.assertEqual(shortened, list(range(min(shortened), 12)))  # shortened ones are the oldest
        json.dumps(snap)

    def test_a_small_section_is_untouched(self):
        for i in range(3):
            self.write(f"s{i}", [user(), assistant("x" * 1500)], project=f"p{i}", age=100 + i)
        self.assertTrue(all(len(s["last_result"]) == 1500 for s in self.provider.snapshot()["sessions"]))

    def test_multibyte_text_is_cut_on_a_character_boundary(self):
        for i in range(12):
            self.write(f"s{i:02d}", [user(), assistant("日本語" * 500)], project=f"p{i}", age=1000 - i * 10)
        snap = self.provider.snapshot()
        json.dumps(snap, ensure_ascii=False).encode("utf-8")  # no broken surrogate / partial character


SECRETS = ["sk-ant-oat01-SECRET-TOKEN", "hunter2-password", "oauth-access-123", "user@example.com",
           "https://secret.example.com/mcp?key=abc", "Bearer topsecretbearer", "C:\\Tools\\secret-server.exe",
           "ENV_SECRET_VALUE", "accountUuid-9999"]


class ConnectorsTest(Base):
    def config(self, cwd, extra_projects=None):
        data = {
            "oauthAccount": {"emailAddress": "user@example.com", "accountUuid": "accountUuid-9999"},
            "userID": "hunter2-password", "primaryApiKey": "sk-ant-oat01-SECRET-TOKEN",
            "cachedGrowthBookFeatures": {"x": "oauth-access-123"},
            "mcpServers": {
                "github": {"type": "http", "url": "https://secret.example.com/mcp?key=abc",
                           "headers": {"Authorization": "Bearer topsecretbearer"}},
                "local-tool": {"command": "C:\\Tools\\secret-server.exe", "args": ["--token", "ENV_SECRET_VALUE"],
                               "env": {"API_KEY": "ENV_SECRET_VALUE"}},
                "events": {"type": "sse", "url": "https://secret.example.com/sse"},
            },
            "projects": {
                cwd.replace("\\", "/"): {"allowedTools": [], "mcpServers": {
                    "proj-db": {"type": "stdio", "command": "x", "env": {"PW": "hunter2-password"}}},
                    "lastSessionId": "accountUuid-9999"},
                "C:/other/unlisted": {"mcpServers": {"hidden": {"type": "http", "url": "https://secret.example.com"}}},
            },
        }
        data["projects"].update(extra_projects or {})
        with open(os.path.join(self.home, ".claude.json"), "w", encoding="utf-8") as f:
            json.dump(data, f)

    def listed_cwd(self):
        cwd = os.path.join(self.home, "work", "myproj")
        os.makedirs(cwd, exist_ok=True)
        self.write("s1", [user(cwd=cwd), assistant(cwd=cwd)])
        return cwd

    def test_only_names_types_and_scopes(self):
        cwd = self.listed_cwd()
        self.config(cwd)
        snap = self.provider.snapshot()
        got = {(c["name"], c["type"], c["scope"]) for c in snap["connectors"]}
        self.assertEqual(got, {("github", "http", "global"), ("local-tool", "stdio", "global"),
                               ("events", "sse", "global"), ("proj-db", "stdio", "myproj")})
        for c in snap["connectors"]:
            self.assertEqual(set(c), {"name", "type", "scope"})

    def test_no_secret_of_claude_json_ever_reaches_the_snapshot(self):
        cwd = self.listed_cwd()
        self.config(cwd)
        text = json.dumps(self.provider.snapshot(), ensure_ascii=False)
        for secret in SECRETS:
            self.assertNotIn(secret, text, secret)
        self.assertNotIn("oauth", text.lower())
        self.assertNotIn("hidden", text)  # the entry of a project that is not listed
        for log in self.logs:
            for secret in SECRETS:
                self.assertNotIn(secret, log)

    def test_the_mcp_json_of_the_project_is_read_with_the_same_restrictions(self):
        cwd = self.listed_cwd()
        with open(os.path.join(cwd, ".mcp.json"), "w", encoding="utf-8") as f:
            json.dump({"mcpServers": {"from-file": {"type": "http", "url": "https://secret.example.com/mcp?key=abc",
                                                    "headers": {"X": "Bearer topsecretbearer"}}},
                       "other": "ENV_SECRET_VALUE"}, f)
        snap = self.provider.snapshot()
        self.assertEqual(snap["connectors"], [{"name": "from-file", "type": "http", "scope": "myproj"}])
        text = json.dumps(snap)
        self.assertNotIn("secret", text.lower())

    def test_an_unknown_type_is_stdio(self):
        cwd = self.listed_cwd()
        with open(os.path.join(cwd, ".mcp.json"), "w", encoding="utf-8") as f:
            json.dump({"mcpServers": {"a": {"type": "websocket"}, "b": "not a dict", "c": {}}}, f)
        types = {c["name"]: c["type"] for c in self.provider.snapshot()["connectors"]}
        self.assertEqual(types, {"a": "stdio", "b": "stdio", "c": "stdio"})

    def test_at_most_thirty_connectors(self):
        cwd = self.listed_cwd()
        with open(os.path.join(self.home, ".claude.json"), "w", encoding="utf-8") as f:
            json.dump({"mcpServers": {f"srv{i:02d}": {"type": "http"} for i in range(50)}}, f)
        self.assertEqual(len(self.provider.snapshot()["connectors"]), 30)

    def test_missing_or_broken_files_give_no_connectors(self):
        cwd = self.listed_cwd()
        self.assertEqual(self.provider.snapshot()["connectors"], [])
        with open(os.path.join(self.home, ".claude.json"), "w", encoding="utf-8") as f:
            f.write("{broken")
        with open(os.path.join(cwd, ".mcp.json"), "w", encoding="utf-8") as f:
            f.write("[1, 2")
        self.assertEqual(self.provider.snapshot()["connectors"], [])
        with open(os.path.join(self.home, ".claude.json"), "w", encoding="utf-8") as f:
            json.dump(["not", "a", "dict"], f)
        self.assertEqual(self.provider.snapshot()["connectors"], [])

    def test_the_config_is_parsed_again_only_when_it_changes(self):
        cwd = self.listed_cwd()
        self.config(cwd)
        self.provider.snapshot()
        self.fs.reads.clear()
        self.provider.snapshot()
        self.assertEqual([r for r in self.fs.reads if r[0] == ".claude.json"], [])
        path = os.path.join(self.home, ".claude.json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump({"mcpServers": {"new": {"type": "sse"}}}, f)
        os.utime(path, (self.clock.t + 5, self.clock.t + 5))
        self.assertEqual(self.provider.snapshot()["connectors"], [{"name": "new", "type": "sse", "scope": "global"}])

    def test_projects_match_whatever_the_slashes_and_case(self):
        cwd = self.listed_cwd()
        self.config(cwd.upper().replace("\\", "/") + "/")
        scopes = {c["scope"] for c in self.provider.snapshot()["connectors"]}
        self.assertIn("myproj", scopes)

    def test_duplicates_are_listed_once(self):
        cwd = self.listed_cwd()
        self.write("s2", [user(cwd=cwd)], project="proj-b", age=60)
        with open(os.path.join(self.home, ".claude.json"), "w", encoding="utf-8") as f:
            json.dump({"mcpServers": {"a": {}}, "projects": {cwd.replace("\\", "/"): {"mcpServers": {"b": {}}}}}, f)
        names = sorted(c["name"] for c in self.provider.snapshot()["connectors"])
        self.assertEqual(names, ["a", "b"])


class FakeWin32:
    def __init__(self, hwnd=77, iconic=False, accept_after=0):
        self.hwnd, self.iconic, self.accept_after = hwnd, iconic, accept_after
        self.calls = []
        self.attempts = 0

    def find_window(self):
        self.calls.append("find")
        return self.hwnd

    def is_iconic(self, hwnd):
        self.calls.append(("iconic", hwnd))
        return self.iconic

    def restore(self, hwnd):
        self.calls.append(("restore", hwnd))

    def set_foreground(self, hwnd):
        self.attempts += 1
        self.calls.append(("foreground", hwnd))
        return self.attempts > self.accept_after

    def alt_tap(self):
        self.calls.append("alt")


class FocusTest(Base):
    def focus(self, win32):
        provider = self.make(win32=win32)
        return provider.handle({"id": "claude.focus"})

    def test_found_and_brought_to_the_front(self):
        w = FakeWin32()
        self.assertIsNone(self.focus(w))
        self.assertEqual(w.calls, ["find", ("iconic", 77), ("foreground", 77)])

    def test_a_minimised_window_is_restored_first(self):
        w = FakeWin32(iconic=True)
        self.assertIsNone(self.focus(w))
        self.assertEqual(w.calls, ["find", ("iconic", 77), ("restore", 77), ("foreground", 77)])

    def test_a_refusal_is_worked_around_with_alt_and_a_second_try(self):
        w = FakeWin32(accept_after=1)
        self.assertIsNone(self.focus(w))
        self.assertEqual(w.calls, ["find", ("iconic", 77), ("foreground", 77), "alt", ("foreground", 77)])

    def test_refused_twice_is_action_failed_and_logged(self):
        w = FakeWin32(accept_after=5)
        self.assertEqual(self.focus(w), "action_failed")
        self.assertEqual(w.attempts, 2)
        self.assertTrue(self.logs)

    def test_not_running_is_the_notice_and_nothing_else_happens(self):
        w = FakeWin32(hwnd=0)
        self.assertEqual(self.focus(w), "claude_not_running")
        self.assertEqual(w.calls, ["find"])

    def test_a_layer_that_raises_is_action_failed(self):
        class Boom(FakeWin32):
            def find_window(self):
                raise OSError("user32")
        self.assertEqual(self.focus(Boom()), "action_failed")

    def test_unknown_action_is_refused(self):
        w = FakeWin32()
        provider = self.make(win32=w)
        self.assertEqual(provider.handle({"id": "claude.other"}), "action_failed")
        self.assertEqual(w.calls, [])

    def test_the_real_layer_is_only_built_on_first_use(self):
        provider = self.make()
        self.assertIsNone(provider._win32)


if __name__ == "__main__":
    unittest.main()
