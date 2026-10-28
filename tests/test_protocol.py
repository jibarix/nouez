"""Protocol tests for nouez. Standard library only; no Codex daemon needed.

Run from the repo root: python -m unittest discover tests
"""

import contextlib
import io
import json
import os
import queue
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
import server  # noqa: E402


class Server:
    """server.py in a subprocess, spoken to one JSON-RPC line at a time."""

    def __init__(self):
        self.proc = subprocess.Popen(
            [sys.executable, "-I", "-B", os.path.join(ROOT, "server.py")],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
            encoding="utf-8", cwd=ROOT,
        )
        self.lines = queue.Queue()
        threading.Thread(target=self._read, daemon=True).start()

    def _read(self):
        for line in self.proc.stdout:
            self.lines.put(json.loads(line))

    def send(self, msg):
        self.proc.stdin.write((msg if isinstance(msg, str) else json.dumps(msg)) + "\n")
        self.proc.stdin.flush()

    def recv(self, timeout=10):
        return self.lines.get(timeout=timeout)

    def request(self, msg_id, method, params=None):
        msg = {"jsonrpc": "2.0", "id": msg_id, "method": method}
        if params is not None:
            msg["params"] = params
        self.send(msg)
        return self.recv()

    def close(self):
        self.proc.stdin.close()
        self.proc.wait(10)
        self.proc.stdout.close()


class ProtocolTest(unittest.TestCase):
    def setUp(self):
        self.server = Server()
        self.addCleanup(self.server.close)

    def assert_alive(self):
        self.assertEqual(self.server.request("alive", "ping"), {"jsonrpc": "2.0", "id": "alive", "result": {}})

    def test_negotiates_supported_version(self):
        for requested in server.PROTOCOL_VERSIONS:
            reply = self.server.request(1, "initialize", {"protocolVersion": requested, "capabilities": {}})
            self.assertEqual(reply["result"]["protocolVersion"], requested)

    def test_unknown_version_gets_latest_supported(self):
        reply = self.server.request(1, "initialize", {"protocolVersion": "1900-01-01", "capabilities": {}})
        self.assertEqual(reply["result"]["protocolVersion"], server.PROTOCOL_VERSIONS[0])

    def test_non_object_message_is_invalid_request(self):
        self.server.send("[]")
        self.assertEqual(self.server.recv()["error"]["code"], -32600)
        self.server.send('"hello"')
        self.assertEqual(self.server.recv()["error"]["code"], -32600)
        self.assert_alive()

    def test_unhashable_id_is_invalid_request(self):
        self.server.send({"jsonrpc": "2.0", "id": [1], "method": "tools/call", "params": {}})
        self.assertEqual(self.server.recv()["error"]["code"], -32600)
        self.assert_alive()

    def test_malformed_cancel_is_ignored(self):
        for params in (["x"], "x", {"requestId": [1]}, {"requestId": {"a": 1}}):
            self.server.send({"jsonrpc": "2.0", "method": "notifications/cancelled", "params": params})
        self.assert_alive()

    def test_parse_error(self):
        self.server.send("{not json")
        self.assertEqual(self.server.recv()["error"]["code"], -32700)
        self.assert_alive()

    def test_non_object_params_get_invalid_params(self):
        reply = self.server.request(2, "tools/call", ["x"])
        self.assertEqual(reply["id"], 2)
        self.assertEqual(reply["error"]["code"], -32602)
        self.assert_alive()

    def test_non_object_arguments_get_invalid_params(self):
        reply = self.server.request(3, "tools/call", {"name": "ListConsultants", "arguments": ["x"]})
        self.assertEqual(reply["error"]["code"], -32602)

    def test_unknown_tool(self):
        reply = self.server.request(4, "tools/call", {"name": "Nope", "arguments": {}})
        self.assertEqual(reply["error"]["code"], -32602)

    def test_unknown_method(self):
        self.assertEqual(self.server.request(5, "nope/nope")["error"]["code"], -32601)

    def test_negative_wait_is_a_tool_error(self):
        reply = self.server.request(6, "tools/call", {"name": "SendConsultantMessage", "arguments": {
            "to": "x", "message": "hi", "wait": -5}})
        self.assertTrue(reply["result"]["isError"])
        self.assertIn("0 or more", reply["result"]["content"][0]["text"])

    def test_wait_schema_takes_seconds_or_done(self):
        tools = {t["name"]: t for t in self.server.request(11, "tools/list")["result"]["tools"]}
        for name in ("SendConsultantMessage", "GetConsultantReply"):
            props = tools[name]["inputSchema"]["properties"]
            self.assertEqual([s["type"] for s in props["wait"]["anyOf"]], ["number", "string"])
            self.assertFalse({"until_done", "timeout_seconds"} & set(props))

    def test_tools_list_schemas_are_objects(self):
        tools = self.server.request(7, "tools/list")["result"]["tools"]
        self.assertEqual({t["name"] for t in tools}, set(server.HANDLERS))
        for tool in tools:
            self.assertEqual(tool["inputSchema"]["type"], "object")

    def test_annotations(self):
        tools = {t["name"]: t["annotations"] for t in self.server.request(8, "tools/list")["result"]["tools"]}
        read_only = {name for name, a in tools.items() if a.get("readOnlyHint")}
        self.assertEqual(read_only, {"ListConsultants", "GetConsultantReply"})
        destructive = {name for name, a in tools.items() if a.get("destructiveHint")}
        self.assertEqual(destructive, {"StopConsultant"})

    def test_null_id_is_invalid_request(self):
        self.server.send({"jsonrpc": "2.0", "id": None, "method": "ping"})
        reply = self.server.recv()
        self.assertEqual(reply["error"]["code"], -32600)
        self.assertIsNone(reply["id"])
        self.assert_alive()

    def test_empty_array_params_are_invalid(self):
        self.assertEqual(self.server.request(9, "ping", [])["error"]["code"], -32602)
        reply = self.server.request(10, "tools/call", {"name": "ListConsultants", "arguments": []})
        self.assertEqual(reply["error"]["code"], -32602)


class ArgumentTest(unittest.TestCase):
    def test_wait_rejects_bad_values(self):
        for value in (-1, "-5", float("nan"), float("inf"), 10 ** 400, "x", True, False, None):
            with self.assertRaises(server.BridgeError):
                server.wait_seconds({"wait": value}, 0)

    def test_wait_values(self):
        self.assertEqual(server.wait_seconds({}, 600), 600)
        self.assertEqual(server.wait_seconds({"wait": 0}, 600), 0)
        self.assertEqual(server.wait_seconds({"wait": "30"}, 600), 30)
        self.assertEqual(server.wait_seconds({"wait": 10 ** 9}, 0), server.MAX_WAIT_SECONDS)
        self.assertEqual(server.wait_seconds({"wait": "done"}, 0), server.MAX_WAIT_SECONDS)

    def test_replaced_options_are_refused(self):
        for old in ({"until_done": True}, {"timeout_seconds": 5}):
            with self.assertRaises(server.BridgeError) as caught:
                server.wait_seconds(old, 0)
            self.assertIn("replaced by `wait`", str(caught.exception))


class ProgressTest(unittest.TestCase):
    def setUp(self):
        self.sent = []
        original = server.write_message
        server.write_message = self.sent.append
        self.addCleanup(setattr, server, "write_message", original)

    def test_token_from_meta(self):
        cancel = threading.Event()
        self.assertIsNone(server.progress_for({}, cancel))
        self.assertIsNone(server.progress_for({"_meta": {"progressToken": True}}, cancel))
        self.assertEqual(server.progress_for({"_meta": {"progressToken": 7}}, cancel).token, 7)

    def test_throttled_increasing_and_silent_after_cancel(self):
        cancel = threading.Event()
        progress = server.Progress("tok", cancel)
        progress("a")
        progress("b")  # within PROGRESS_SECONDS: dropped
        progress.last -= server.PROGRESS_SECONDS
        progress("c")
        self.assertEqual([m["params"]["message"] for m in self.sent], ["a", "c"])
        self.assertEqual([m["params"]["progress"] for m in self.sent], [1, 2])
        self.assertEqual(self.sent[0]["method"], "notifications/progress")
        self.assertEqual(self.sent[0]["params"]["progressToken"], "tok")
        progress.last -= server.PROGRESS_SECONDS
        cancel.set()
        progress("d")
        self.assertEqual(len(self.sent), 2)

    def test_failed_write_stops_progress_not_the_wait(self):
        progress = server.Progress("tok", threading.Event())
        with mock.patch.object(server, "write_message", side_effect=OSError("closed")) as write:
            progress("a")  # must not raise
            progress.last -= server.PROGRESS_SECONDS
            progress("b")
        self.assertEqual(write.call_count, 1)


class ReplyTest(unittest.TestCase):
    def test_long_reply_is_truncated_and_saved(self):
        text = "a" * (server.MAX_REPLY_CHARS + 123)
        turn = {"id": "turn-test-truncate", "status": "completed",
                "items": [{"type": "agentMessage", "phase": "final_answer", "text": text}]}
        out = server.format_turn("codex-x", turn)
        self.assertIn("[Truncated: 123 more characters.", out)
        path = os.path.join(server.tempfile.gettempdir(), "nouez", "turn-test-truncate.md")
        self.addCleanup(os.remove, path)
        with open(path, encoding="utf-8") as f:
            self.assertEqual(f.read(), text)

    def test_short_reply_is_untouched(self):
        self.assertEqual(server.cap_reply("t", "short"), "short")


class DaemonStartTest(unittest.TestCase):
    def connect(self, failures):
        """A CodexClient whose first `failures` connections find no daemon; returns start_daemon's mock."""
        attempts = iter([server.DaemonDown("down")] * failures)

        def fake_connect(client, exe):
            client.proc = mock.Mock()
            for error in attempts:
                raise error

        patches = (mock.patch.object(server.shutil, "which", return_value="codex"),
                   mock.patch.object(server.CodexClient, "_connect", fake_connect),
                   mock.patch.object(server.CodexClient, "_reader"),
                   mock.patch.object(server.CodexClient, "request", return_value={}),
                   mock.patch.object(server.CodexClient, "notify"),
                   mock.patch.object(server, "DAEMON_START_SECONDS", 0.01),
                   mock.patch.object(server.time, "sleep"))
        for patch in patches:
            patch.start()
            self.addCleanup(patch.stop)
        start = mock.patch.object(server, "start_daemon").start()
        self.addCleanup(mock.patch.stopall)
        return start

    def test_running_daemon_is_not_started(self):
        start = self.connect(0)
        server.CodexClient()
        start.assert_not_called()

    def test_missing_daemon_is_started_once_then_retried(self):
        start = self.connect(2)
        server.CodexClient()
        start.assert_called_once_with("codex")

    def test_gives_up_when_the_daemon_never_comes_up(self):
        start = self.connect(1000)
        with self.assertRaises(server.DaemonDown):
            server.CodexClient()
        start.assert_called_once_with("codex")


class DaemonEnvTest(unittest.TestCase):
    def folders(self):
        """An MSYS folder (holds msys-2.0.dll, like Git\\usr\\bin) and a plain one."""
        root = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, root)
        msys, plain = os.path.join(root, "usr-bin"), os.path.join(root, "system32")
        for folder in (msys, plain):
            os.mkdir(folder)
        open(os.path.join(msys, "msys-2.0.dll"), "w").close()
        return msys, plain

    def test_git_bash_environment_is_cleaned(self):
        msys, plain = self.folders()
        env = server.daemon_env({"MSYSTEM": "MINGW64", "SHELL": r"C:\Program Files\Git\bin\bash.exe",
                                 "EXEPATH": r"C:\Program Files\Git\bin", "CODEX_HOME": r"C:\codex",
                                 "PATH": f"{msys};{plain};;{msys}"})
        self.assertEqual(env, {"CODEX_HOME": r"C:\codex", "PATH": plain})

    def test_outside_git_bash_the_environment_is_inherited(self):
        msys, plain = self.folders()
        self.assertIsNone(server.daemon_env({"PATH": f"{msys};{plain}"}))
        self.assertIsNone(server.daemon_env({"MSYSTEM": "", "PATH": plain}))

    def test_daemon_is_started_with_the_cleaned_environment(self):
        with mock.patch.object(server.os, "name", "nt"), \
             mock.patch.dict(server.os.environ, {"MSYSTEM": "MINGW64"}), \
             mock.patch.object(server.subprocess, "Popen") as popen:
            server.start_daemon("codex")
        env = popen.call_args.kwargs["env"]
        self.assertNotIn("MSYSTEM", {k.upper() for k in env})


class UpdateNoticeTest(unittest.TestCase):
    def notice(self, cache, cli="0.163.0", daemon="0.162.1", home=True):
        folder = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, folder)
        if cache is not None:
            with open(os.path.join(folder, "version.json"), "w", encoding="utf-8") as f:
                json.dump(cache, f)
        info = {"userAgent": f"codex_app_server/{daemon} (Windows 11)", **({"codexHome": folder} if home else {})}
        with mock.patch.object(server, "codex_version", return_value=cli), \
             mock.patch.object(server, "_update_noted", set()):
            return server.update_notice(info), server.update_notice(info)

    def test_behind_cli_and_daemon(self):
        first, second = self.notice({"latest_version": "0.165.0"})
        self.assertIn("Codex 0.165.0 is out", first)
        self.assertIn("CLI on PATH is 0.163.0", first)
        self.assertIn("daemon is 0.162.1", first)
        self.assertIn("`codex update`", first)
        self.assertIn("`codex app-server daemon update`", first)
        self.assertIn("go ahead with the consultation", first)
        self.assertEqual(second, "")  # told once per server process

    def test_only_the_part_that_is_behind(self):
        out = self.notice({"latest_version": "0.165.0"}, cli="0.165.0")[0]
        self.assertNotIn("`codex update`", out)
        self.assertIn("daemon update", out)

    def test_nothing_when_current_dismissed_or_unknown(self):
        self.assertEqual(self.notice({"latest_version": "0.165.0"}, cli="0.165.0", daemon="0.165.0")[0], "")
        self.assertEqual(self.notice({"latest_version": "0.165.0"}, cli="0.170.0", daemon="0.166.0")[0], "")
        self.assertEqual(self.notice({"latest_version": "0.165.0", "dismissed_version": "0.165.0"})[0], "")
        self.assertEqual(self.notice(None)[0], "")
        self.assertEqual(self.notice({"latest_version": "0.165.0"}, home=False)[0], "")
        self.assertEqual(self.notice({"latest_version": None})[0], "")
        self.assertEqual(self.notice(["not", "an", "object"])[0], "")

    def test_versions_compare_as_numbers(self):
        self.assertLess(server.version_key("0.99.0"), server.version_key("0.165.0"))
        self.assertEqual(server.version_key("0.165.0-alpha.1"), (0, 165, 0))


class FakeClient:
    """Just enough of CodexClient for resolve()."""

    def __init__(self, threads):
        self.threads = {t["id"]: t for t in threads}

    def request(self, method, params):
        if method == "thread/loaded/list":
            return {"data": list(self.threads)}
        if method == "thread/read":
            if params["threadId"] not in self.threads:
                raise server.BridgeError("thread/read failed: not found")
            return {"thread": dict(self.threads[params["threadId"]])}
        if method == "thread/list":
            return {"data": []}
        raise AssertionError(method)


class ResolveTest(unittest.TestCase):
    client = FakeClient([{"id": "0199aaaa-bbbb-cccc-dddd-eeeeee123456", "cwd": "/repo"}])

    def test_prefix_matches_by_default(self):
        self.assertEqual(server.resolve(self.client, "0199aaaa")["cwd"], "/repo")

    def test_exact_only_refuses_prefix(self):
        with self.assertRaises(server.BridgeError) as caught:
            server.resolve(self.client, "0199aaaa", exact_only=True)
        self.assertIn("exact name or full thread id", str(caught.exception))

    def test_exact_only_accepts_name_and_full_id(self):
        self.assertTrue(server.resolve(self.client, "codex-repo-123456", exact_only=True))
        self.assertTrue(server.resolve(self.client, "0199aaaa-bbbb-cccc-dddd-eeeeee123456", exact_only=True))

    def test_shared_name_is_refused(self):
        client = FakeClient([{"id": "0199aaaa-0000-0000-0000-000000123456", "cwd": "/repo"},
                             {"id": "0199bbbb-0000-0000-0000-000000123456", "cwd": "/repo"}])
        for exact_only in (False, True):
            with self.assertRaises(server.BridgeError) as caught:
                server.resolve(client, "codex-repo-123456", exact_only=exact_only)
            self.assertIn("more than one session", str(caught.exception))
        self.assertEqual(server.resolve(client, "0199bbbb-0000-0000-0000-000000123456")["id"][:8], "0199bbbb")


def agent(text, phase=None):
    return {"type": "agentMessage", "phase": phase, "text": text}


def user(text):
    return {"type": "userMessage", "content": [{"type": "text", "text": text}]}


class PartialTest(unittest.TestCase):
    def test_only_output_since_the_latest_user_message(self):
        turn = {"items": [user("first"), agent("old answer", "final_answer"),
                          user("steered"), agent("looking", "commentary"), agent("draft", "final_answer")]}
        self.assertEqual(server.partial_output(turn), "looking\n\ndraft")

    def test_newest_part_is_kept(self):
        text = "x" * 10 + "y" * server.PARTIAL_CHARS
        out = server.partial_output({"items": [user("q"), agent(text)]})
        self.assertTrue(out.startswith("[... 10 earlier characters omitted]"))
        self.assertTrue(out.endswith("y" * server.PARTIAL_CHARS))

    def test_still_working_is_marked_not_a_reply(self):
        self.assertNotIn("Output so far", server.still_working("c", "t1", None, "Wait."))
        out = server.still_working("c", "t1", {"items": [user("q"), agent("half")]}, "Wait.")
        self.assertIn("this is not a reply", out)
        self.assertIn("Output so far", out)
        self.assertTrue(out.endswith("half"))


class FakeDaemon:
    """A daemon with threads and turns, for the tool handlers. Pass it as CodexClient."""

    def __init__(self, threads, turns=None, fail_after_start=False):
        self.threads = {t["id"]: t for t in threads}
        self.turns = turns or {}  # thread id -> turns, newest first
        self.fail_after_start = fail_after_start
        self.calls = []
        self.info = {}

    def __call__(self):
        return self

    def close(self):
        pass

    def request(self, method, params):
        self.calls.append(method)
        if method == "thread/loaded/list":
            return {"data": list(self.threads)}
        if method == "thread/read":
            return {"thread": dict(self.threads[params["threadId"]])}
        if method == "thread/list":
            return {"data": []}
        if method == "thread/start":
            thread = {"id": "0199ffff-0000-0000-0000-000000new001", "threadSource": "nouez", **params}
            self.threads[thread["id"]] = thread
            return {"thread": thread}
        if method == "thread/resume":
            return {}
        if method == "thread/turns/list":
            if self.fail_after_start and "turn/start" in self.calls:
                raise server.BridgeError("thread/turns/list timed out after 15s.")
            return {"data": self.turns.get(params["threadId"], [])[:params["limit"]]}
        if method == "turn/start":
            turn = {"id": "turn-new", "status": "inProgress",
                    "items": [user(params["input"][0]["text"]), agent("working on it", "commentary")]}
            self.turns.setdefault(params["threadId"], []).insert(0, turn)
            return {"turn": turn}
        if method == "turn/steer":
            running = self.turns[params["threadId"]][0]
            running["items"].append(user(params["input"][0]["text"]))
            return {"turnId": running["id"]}
        raise AssertionError(method)


class HandlerTest(unittest.TestCase):
    def use(self, daemon):
        self.panes = []
        # Never open a real terminal from a test.
        fake_viewer = lambda thread, info, quiet=False: self.panes.append(thread["id"]) or "Opened (test)."
        for attr, value in (("CodexClient", daemon), ("POLL_SECONDS", 0.01), ("show_viewer", fake_viewer)):
            self.addCleanup(setattr, server, attr, getattr(server, attr))
            setattr(server, attr, value)
        return daemon

    def consultant(self, tag, **extra):
        return {"id": f"0199aaaa-0000-0000-0000-000000{tag}", "cwd": ROOT, "threadSource": "nouez", **extra}

    def test_start_never_reuses_a_user_session(self):
        mine = {"id": "0199aaaa-0000-0000-0000-000000user01", "cwd": ROOT}
        daemon = self.use(FakeDaemon([mine]))
        out = server.start_consultant({"cwd": ROOT, "watch": False})
        self.assertIn("thread/start", daemon.calls)
        self.assertTrue(out.startswith("Started "))
        self.assertIn("were not used", out)
        self.assertIn(server.short_name(mine), out)

    def test_start_reuses_its_own_consultant(self):
        ours = {"id": "0199aaaa-0000-0000-0000-000000ours01", "cwd": ROOT, "threadSource": "nouez"}
        daemon = self.use(FakeDaemon([ours]))
        out = server.start_consultant({"cwd": ROOT, "watch": False, "model": "m"})
        self.assertNotIn("thread/start", daemon.calls)
        self.assertTrue(out.startswith(f"Using {server.short_name(ours)}"))
        self.assertIn("Ignored model", out)

    def test_start_tells_about_a_codex_update_and_goes_on(self):
        for existing in ([], [self.consultant("ours02")]):
            self.use(FakeDaemon(existing))
            with mock.patch.object(server, "update_notice", return_value="Codex 9.9.9 is out.") as notice:
                out = server.start_consultant({"cwd": ROOT, "watch": False})
            notice.assert_called_once()
            self.assertTrue(out.endswith("\nCodex 9.9.9 is out."))
            self.assertIn("Send it work with SendConsultantMessage.", out)

    def test_send_timeout_shows_output_so_far(self):
        thread = self.consultant("idle01")
        self.use(FakeDaemon([thread]))
        out = server.send_consultant_message({"to": thread["id"], "message": "hi", "wait": 0.01})
        self.assertIn("still working on turn turn-new; this is not a reply", out)
        self.assertIn("Don't send the message again", out)
        self.assertIn("Don't wait for the reply", out)
        self.assertIn("GetConsultantReply (turn_id turn-new)", out)
        self.assertTrue(out.endswith("working on it"))

    def test_wait_zero_returns_after_delivery(self):
        thread = self.consultant("idle02")
        daemon = self.use(FakeDaemon([thread]))
        out = server.send_consultant_message({"to": thread["id"], "message": "hi", "wait": 0})
        self.assertTrue(out.startswith("Delivered to "))
        self.assertIn("Don't wait for the reply", out)
        self.assertIn("GetConsultantReply (turn_id turn-new)", out)
        self.assertIn("turn/start", daemon.calls)

    def test_steered_timeout_hides_output_from_before_the_message(self):
        thread = self.consultant("busy01")
        running = {"id": "turn-1", "status": "inProgress", "items": [user("q"), agent("answer to q")]}
        self.use(FakeDaemon([thread], {thread["id"]: [running]}))
        out = server.send_consultant_message({"to": thread["id"], "message": "more", "wait": 0.01})
        self.assertIn("steered into the running turn", out)
        self.assertNotIn("answer to q", out)

    def test_failure_after_delivery_says_delivered(self):
        thread = self.consultant("fail01")
        self.use(FakeDaemon([thread], fail_after_start=True))
        with self.assertRaises(server.BridgeError) as caught:
            server.send_consultant_message({"to": thread["id"], "message": "hi"})
        self.assertTrue(str(caught.exception).startswith("Delivered to "))
        self.assertIn("Don't send the message again", str(caught.exception))

    def test_user_session_needs_allow_user_session(self):
        mine = {"id": "0199aaaa-0000-0000-0000-000000user02", "cwd": ROOT}
        daemon = self.use(FakeDaemon([mine]))
        with self.assertRaises(server.BridgeError) as caught:
            server.send_consultant_message({"to": mine["id"], "message": "hi", "wait": 0})
        self.assertIn("allow_user_session=true", str(caught.exception))
        self.assertNotIn("turn/start", daemon.calls)
        out = server.send_consultant_message({"to": mine["id"], "message": "hi", "wait": 0,
                                              "allow_user_session": True})
        self.assertTrue(out.startswith("Delivered to "))

    def test_send_offers_the_waiter(self):
        thread = self.consultant("wait01")
        self.use(FakeDaemon([thread]))
        out = server.send_consultant_message({"to": thread["id"], "message": "hi", "wait": 0})
        self.assertIn("run_in_background", out)
        self.assertIn(f'server.py wait {thread["id"]} turn-new\n', out)

    def test_waiter_command_quotes_only_paths_with_spaces(self):
        with mock.patch.object(server.sys, "executable", r"C:\Py\python.exe"), \
             mock.patch.object(server.os.path, "abspath", return_value=r"C:\My Tools\server.py"):
            self.assertEqual(server.waiter_command("t1", "u1"),
                             'C:/Py/python.exe -I "C:/My Tools/server.py" wait t1 u1')

    def run_waiter(self, *args):
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            code = server.run_waiter(*args)
        return code, buf.getvalue()

    def test_allow_rules_match_the_waiter_command(self):
        cmd = server.waiter_command("t1", "u1")
        for rule in server.allow_rules():
            prefix = rule[rule.index("(") + 1:-len(" *)")]
            self.assertTrue(cmd.startswith(prefix + " "), (rule, cmd))
        self.assertEqual([r.split("(")[0] for r in server.allow_rules()], ["Bash", "PowerShell"])

    def test_waiter_hands_over_before_the_background_timeout(self):
        thread = self.consultant("wait07")
        running = {"id": "turn-1", "status": "inProgress", "items": [user("q")]}
        self.use(FakeDaemon([thread], {thread["id"]: [running]}))
        with mock.patch.object(server, "WAITER_SECONDS", 0.05):
            code, out = self.run_waiter(thread["id"], "turn-1")
        self.assertEqual(code, 0)
        self.assertIn("still working", out)
        self.assertIn(f"run the same command again in the background:\n", out)
        self.assertIn(f"wait {thread['id']} turn-1", out)

    def test_waiter_prints_the_reply(self):
        thread = self.consultant("wait02")
        done = {"id": "turn-1", "status": "completed", "items": [user("q"), agent("the answer", "final_answer")]}
        self.use(FakeDaemon([thread], {thread["id"]: [done]}))
        code, out = self.run_waiter(thread["id"], "turn-1")
        self.assertEqual(code, 0)
        self.assertIn("turn has ended", out)
        self.assertIn("the answer", out)

    def test_waiter_returns_an_old_finished_turn_at_once(self):
        thread = self.consultant("wait05")
        newer = [{"id": f"turn-{n}", "status": "completed", "items": []} for n in range(20)]
        old = {"id": "turn-old", "status": "completed", "items": [user("q"), agent("old answer", "final_answer")]}
        self.use(FakeDaemon([thread], {thread["id"]: newer + [old]}))
        code, out = self.run_waiter(thread["id"], "turn-old")
        self.assertEqual(code, 0)
        self.assertIn("old answer", out)

    def test_waiter_refuses_an_unknown_turn(self):
        thread = self.consultant("wait03")
        self.use(FakeDaemon([thread]))
        code, out = self.run_waiter(thread["id"], "turn-nope")
        self.assertEqual(code, 1)
        self.assertIn("has no turn turn-nope", out)

    def test_waiter_gives_up_after_repeated_connection_failures(self):
        def down():
            raise server.DaemonDown("down")
        self.use(down)
        with mock.patch.object(server.time, "sleep") as sleep:
            code, out = self.run_waiter("0199aaaa-0000-0000-0000-000000wait04", "turn-1")
        self.assertEqual(code, 1)
        self.assertEqual(sleep.call_count, server.WAITER_RETRIES)
        self.assertIn("Stopped waiting for turn turn-1", out)

    def test_waiter_rides_out_os_errors(self):
        def broken():
            raise BrokenPipeError("pipe closed")
        self.use(broken)
        with mock.patch.object(server.time, "sleep"):
            code, out = self.run_waiter("0199aaaa-0000-0000-0000-000000wait06", "turn-1")
        self.assertEqual(code, 1)
        self.assertIn("pipe closed", out)

    def test_waits_report_progress(self):
        thread = self.consultant("prog01")
        self.use(FakeDaemon([thread]))
        notes = []
        server.send_consultant_message({"to": thread["id"], "message": "hi", "wait": 0.01}, None, notes.append)
        self.assertTrue(notes)
        self.assertIn("is working on turn turn-new", notes[0])
        self.assertTrue(notes[0].endswith(": working on it"))
        notes.clear()
        server.get_consultant_reply({"to": thread["id"], "wait": 0.01}, None, notes.append)
        self.assertIn("is working on turn turn-new", notes[0])


class ReleaseTest(unittest.TestCase):
    """A change to server.py ships as a version: these fail until the version step is done."""

    def read(self, *parts):
        with open(os.path.join(ROOT, *parts), encoding="utf-8") as f:
            return f.read()

    def git(self, *args):
        try:
            return subprocess.run(["git", "-C", ROOT, *args], stdin=subprocess.DEVNULL, capture_output=True,
                                  text=True, timeout=20)
        except (OSError, subprocess.SubprocessError):
            self.skipTest("git is not available")

    def test_version_is_recorded_everywhere(self):
        version = server.SERVER_VERSION
        changelog = self.read("CHANGELOG.md")
        self.assertRegex(changelog, rf"(?m)^## \[{re.escape(version)}\] - \d{{4}}-\d\d-\d\d$")
        self.assertIn(f"\n[{version}]: ", changelog)
        self.assertIn(f"compare/v{version}...HEAD", changelog)
        self.assertIn(f"| nouez | {version} |", self.read("README.md"))
        self.assertIn(f"\\title{{\\textbf{{nouez}} {version}", self.read("docs", "architecture.tex"))

    def test_changed_server_has_a_new_version(self):
        tag = self.git("describe", "--tags", "--abbrev=0", "--match", "v*")
        if tag.returncode:
            self.skipTest("no version tag to compare with")
        tag = tag.stdout.strip()
        if self.git("diff", "--quiet", tag, "--", "server.py").returncode == 0:
            return
        self.assertNotEqual(
            f"v{server.SERVER_VERSION}", tag,
            f"server.py differs from {tag} but SERVER_VERSION is unchanged. Bump it and do the version "
            "step: CHANGELOG section, README table, docs/architecture.tex and PDF, tag, release.")


if __name__ == "__main__":
    unittest.main()
