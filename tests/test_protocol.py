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
import time
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
import server  # noqa: E402

server.CONNECT_SECONDS = 0  # OpenClaudeSession tests look for the new session once, not for 15 s


class Server:
    """server.py in a subprocess, spoken to one JSON-RPC line at a time."""

    def __init__(self, env=None):
        self.proc = subprocess.Popen(
            [sys.executable, "-I", "-B", os.path.join(ROOT, "server.py")],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
            encoding="utf-8", cwd=ROOT, env=env or {**os.environ, "NOUEZ_NO_UPDATE_CHECK": "1"},
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

    def test_instructions_leave_model_choice_to_the_user(self):
        reply = self.server.request(1, "initialize", {"protocolVersion": server.PROTOCOL_VERSIONS[0], "capabilities": {}})
        text = reply["result"]["instructions"]
        self.assertIn("only when the user asks or the user's own instructions", text)
        self.assertIn("send the usual values again", text)

    def test_initialize_with_the_release_check_on(self):
        # The check runs, but a cached failed lookup from just now keeps it off the network.
        cache = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, cache)
        os.mkdir(os.path.join(cache, "nouez"))
        with open(os.path.join(cache, "nouez", "latest-release.json"), "w", encoding="utf-8") as f:
            json.dump({"checked": time.time(), "latest": None}, f)
        env = {**os.environ, "LOCALAPPDATA": cache, "XDG_CACHE_HOME": cache}
        env.pop("NOUEZ_NO_UPDATE_CHECK", None)
        live = Server(env)
        self.addCleanup(live.close)
        reply = live.request(1, "initialize", {"protocolVersion": server.PROTOCOL_VERSIONS[0], "capabilities": {}})
        self.assertIn("result", reply)
        self.assertEqual(live.request(2, "ping"), {"jsonrpc": "2.0", "id": 2, "result": {}})
        with self.assertRaises(queue.Empty):
            live.recv(timeout=0.5)  # one answer to initialize, nothing more

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
        self.assertEqual(read_only, {"ListConsultants", "GetConsultantReply", "GetConsultantHistory", "ListClaudeSessions"})
        destructive = {name for name, a in tools.items() if a.get("destructiveHint")}
        self.assertEqual(destructive, {"StopConsultant", "CloseClaudeSession"})

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


class NouezUpdateTest(unittest.TestCase):
    def setUp(self):
        folder = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, folder)
        self.cache = os.path.join(folder, "nouez", "latest-release.json")
        patch = mock.patch.object(server, "release_cache_file", return_value=self.cache)
        patch.start()
        self.addCleanup(patch.stop)

    def notice(self, latest, current="0.9.0"):
        with mock.patch.object(server, "_nouez_latest", latest), \
             mock.patch.object(server, "_nouez_noted", False), \
             mock.patch.object(server, "SERVER_VERSION", current):
            return server.nouez_update_notice(), server.nouez_update_notice()

    def test_newer_release_told_once(self):
        first, second = self.notice("0.10.0")
        self.assertIn("nouez 0.10.0 is out; this server is 0.9.0", first)
        self.assertIn("releases/tag/v0.10.0", first)
        self.assertIn("go ahead with the consultation", first)
        self.assertIn("/mcp", first)
        if os.path.exists(os.path.join(ROOT, ".git")):
            self.assertIn("pull --ff-only`", first)
            self.assertIn("don't discard", first)
        self.assertEqual(second, "")

    def test_nothing_when_current_newer_or_unknown(self):
        self.assertEqual(self.notice("0.9.0")[0], "")
        self.assertEqual(self.notice("0.8.0")[0], "")
        self.assertEqual(self.notice(None)[0], "")

    def test_fresh_cache_skips_github(self):
        os.makedirs(os.path.dirname(self.cache))
        with open(self.cache, "w", encoding="utf-8") as f:
            json.dump({"checked": 1000, "latest": "0.9.1"}, f)
        with mock.patch.object(server, "fetch_latest_release") as fetch:
            self.assertEqual(server.latest_release(now=1000 + 3600), "0.9.1")
        fetch.assert_not_called()

    def test_stale_or_bad_cache_looks_up_and_saves(self):
        os.makedirs(os.path.dirname(self.cache))
        for cache in ({"checked": 1000, "latest": "0.9.1"}, {"checked": 1000, "latest": "; rm -rf"}, ["x"]):
            with open(self.cache, "w", encoding="utf-8") as f:
                json.dump(cache, f)
            with mock.patch.object(server, "fetch_latest_release", return_value="0.9.2") as fetch:
                self.assertEqual(server.latest_release(now=1000 + 2 * 86400), "0.9.2")
            fetch.assert_called_once()
            with open(self.cache, encoding="utf-8") as f:
                self.assertEqual(json.load(f), {"checked": 1000 + 2 * 86400, "latest": "0.9.2"})

    def test_lookup_failure_is_silent_and_waits_an_hour(self):
        with mock.patch.object(server, "fetch_latest_release", side_effect=OSError("offline")) as fetch:
            self.assertIsNone(server.latest_release(now=5))
            self.assertIsNone(server.latest_release(now=5 + 1800))  # another server, half an hour on
            self.assertEqual(fetch.call_count, 1)
            self.assertIsNone(server.latest_release(now=5 + 3600))
            self.assertEqual(fetch.call_count, 2)
        with open(self.cache, encoding="utf-8") as f:
            self.assertEqual(json.load(f), {"checked": 5 + 3600, "latest": None})
        self.assertEqual(os.listdir(os.path.dirname(self.cache)), ["latest-release.json"])

    def test_odd_cache_is_not_trusted(self):
        os.makedirs(os.path.dirname(self.cache))
        for text in ('{"checked": 1000, "latest": "0.%s.0"}' % ("9" * 5000),
                     '{"checked": 1e400, "latest": "0.9.1"}', '{"checked": NaN, "latest": "0.9.1"}',
                     '{"checked": true, "latest": "0.9.1"}', '{"checked": 1000, "latest": "0.9.1", "x": "%s"}' % ("y" * 5000)):
            with open(self.cache, "w", encoding="utf-8") as f:
                f.write(text)
            self.assertEqual(server.read_release_cache(self.cache, 1000), (False, None), text[:60])
            with mock.patch.object(server, "fetch_latest_release", return_value=None):
                self.assertIsNone(server.latest_release(now=1000))

    def test_save_failure_leaves_nothing_behind(self):
        os.makedirs(os.path.dirname(self.cache))
        with mock.patch.object(server.os, "replace", side_effect=OSError("locked")):
            server.save_release_cache(self.cache, 1, "0.9.1")
        self.assertEqual(os.listdir(os.path.dirname(self.cache)), [])

    def test_concurrent_writers_each_use_their_own_temporary_file(self):
        def save(n):
            for i in range(20):
                server.save_release_cache(self.cache, n * 100 + i, "0.9.%d" % n)
        threads = [threading.Thread(target=save, args=(n,)) for n in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        fresh, latest = server.read_release_cache(self.cache, 400)
        self.assertIn(latest, {"0.9.0", "0.9.1", "0.9.2", "0.9.3"})
        self.assertEqual([n for n in os.listdir(os.path.dirname(self.cache)) if n.endswith(".tmp")], [])

    def test_thread_start_failure_is_contained(self):
        with mock.patch.dict(os.environ, {"NOUEZ_NO_UPDATE_CHECK": ""}), \
             mock.patch.object(server.threading, "Thread") as thread:
            thread.return_value.start.side_effect = RuntimeError("can't start new thread")
            server.start_release_check()  # doesn't raise

    def test_notice_failure_cannot_fail_the_consultation(self):
        with mock.patch.object(server, "nouez_update_notice", side_effect=ValueError("odd")):
            self.assertEqual(server.safe_nouez_update_notice(), "")
        self.assertEqual(self.notice("0.%s.0" % ("9" * 5000))[0], "")

    def notice_in(self, folder, git, latest="0.10.0"):
        real_exists = os.path.exists
        with mock.patch.object(server.os.path, "abspath", return_value=os.path.join(folder, "server.py")), \
             mock.patch.object(server.os.path, "exists",
                               side_effect=lambda p: git if p == os.path.join(folder, ".git") else real_exists(p)):
            return self.notice(latest)[0]

    def test_hostile_folder_names_are_not_put_in_a_command(self):
        base = "C:\\Users\\you" if os.name == "nt" else "/home/you"
        for name in ("$(Write-Output injected)", "`calc`", '"quoted"', "a;b"):
            text = self.notice_in(os.path.join(base, name, "nouez"), True)
            self.assertIn("git -C '", text)
            command = text.split("`git -C ")[1].split("` in a shell")[0]
            self.assertTrue(command.startswith("'") and command.endswith("' pull --ff-only"), command)
            self.assertEqual(command.count("'"), 2)
        for name in ("it's", "it’s; Write-Output INJECTED; #", "‘a", "‚b", "‛c", "a\nb"):
            text = self.notice_in(os.path.join(base, name, "nouez"), True)
            self.assertNotIn("git -C", text)
            self.assertIn("git pull themselves", text)

    def test_git_failure_stops_before_reconnect(self):
        text = self.notice_in(os.path.join(os.path.abspath(os.sep), "x", "nouez"), True)
        self.assertLess(text.index("If git fails"), text.index("Only after the pull succeeds"))
        self.assertLess(text.index("Only after the pull succeeds"), text.index("/mcp"))
        self.assertIn("don't ask them to reconnect", text)

    def test_download_notice_without_git(self):
        text = self.notice_in(os.path.join(os.path.abspath(os.sep), "x", "nouez"), False)
        self.assertNotIn("git -C", text)
        self.assertNotIn("pull", text)
        self.assertIn("download it from https://github.com/jibarix/nouez/releases/tag/v0.10.0", text)
        self.assertIn("/mcp", text)

    def test_github_answer_parsed(self):
        def answer(body):
            resp = mock.MagicMock()
            resp.__enter__.return_value.read.return_value = json.dumps(body).encode()
            return resp
        with mock.patch.object(server.urllib.request, "urlopen", return_value=answer({"tag_name": "v1.2.3"})) as op:
            self.assertEqual(server.fetch_latest_release(), "1.2.3")
        req = op.call_args[0][0]
        self.assertEqual(req.full_url, server.RELEASES_URL)
        self.assertTrue(req.get_header("User-agent").startswith("nouez/"))
        for body in ({"tag_name": "v1.2.3`; echo"}, {"tag_name": None}, ["v1.2.3"], {"tag_name": "1.2.3"},
                     {"tag_name": "v1.2.%s" % ("3" * 50)}):
            with mock.patch.object(server.urllib.request, "urlopen", return_value=answer(body)):
                self.assertIsNone(server.fetch_latest_release())

    def test_opt_out(self):
        for value, off in (("", False), ("0", False), ("false", False), ("1", True), ("yes", True)):
            self.assertEqual(server.update_check_off({"NOUEZ_NO_UPDATE_CHECK": value}), off)
        self.assertFalse(server.update_check_off({}))
        with mock.patch.dict(os.environ, {"NOUEZ_NO_UPDATE_CHECK": "1"}), \
             mock.patch.object(server, "latest_release") as latest, \
             mock.patch.object(server.threading, "Thread") as thread:
            server.check_for_release()
            server.start_release_check()
        latest.assert_not_called()
        thread.assert_not_called()


class TrustTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp)
        self.config = os.path.join(self.tmp, "config")
        os.mkdir(self.config)
        self.state = os.path.join(self.config, ".claude.json")
        self.data_home = os.path.join(self.tmp, "data")
        patch = mock.patch.dict(server.os.environ, {"CLAUDE_CONFIG_DIR": self.config, "LOCALAPPDATA": self.data_home,
                                                    "XDG_STATE_HOME": self.data_home})
        patch.start()
        self.addCleanup(patch.stop)
        self.projects = os.path.join(self.tmp, "Projects")
        self.plain = os.path.join(self.projects, "plain", "sub")
        self.repo = os.path.join(self.projects, "repo")
        os.makedirs(self.plain)
        os.makedirs(os.path.join(self.repo, ".git"))
        os.makedirs(os.path.join(self.repo, "src"))
        self.write({"numStartups": 3, "projects": {self.slash(self.projects): {"hasTrustDialogAccepted": True},
                                                   "other": {"allowedTools": ["x"]}}, "é": "ü"})

    def slash(self, p):
        return p.replace("\\", "/") if os.name == "nt" else p

    def write(self, data):
        with open(self.state, "w", encoding="utf-8") as f:
            f.write(json.dumps(data, indent=2, ensure_ascii=False))

    def read(self):
        with open(self.state, encoding="utf-8") as f:
            return json.load(f)

    def test_trust_reaches_plain_folders_but_not_repositories(self):
        self.assertTrue(server.folder_trusted(self.plain))
        self.assertFalse(server.folder_trusted(self.repo))
        self.assertFalse(server.folder_trusted(os.path.join(self.repo, "src")))
        self.assertFalse(server.folder_trusted(self.tmp))

    def worktree(self, gitdir, commondir):
        wt = os.path.join(self.tmp, "wt")
        os.makedirs(gitdir)
        os.mkdir(wt)
        with open(os.path.join(wt, ".git"), "w") as f:
            f.write(f"gitdir: {gitdir}\n")
        if commondir is not None:
            with open(os.path.join(gitdir, "commondir"), "w") as f:
                f.write(commondir + "\n")
        return wt

    def test_worktree_is_keyed_on_the_main_checkout(self):
        wt = self.worktree(os.path.join(self.repo, ".git", "worktrees", "wt"), "../..")
        self.assertEqual(server.trust_key(wt), (self.repo, True))

    def test_worktree_with_a_separate_git_dir_is_unknown(self):
        meta = os.path.join(self.tmp, "metadata")
        wt = self.worktree(os.path.join(meta, "worktrees", "wt"), "../..")
        self.assertEqual(server.trust_key(wt), (None, True))
        self.assertIsNone(server.folder_trusted(wt))

    def test_separate_git_dir_named_dot_git_is_unknown(self):
        # git init --separate-git-dir=<metadata>/.git: the folder holding it is no checkout.
        common = os.path.join(self.tmp, "metadata", ".git")
        wt = self.worktree(os.path.join(common, "worktrees", "wt"), "../..")
        self.assertEqual(server.trust_key(wt), (None, True))
        self.assertIsNone(server.folder_trusted(wt))

    def test_worktree_files_are_checked_in_the_worktree(self):
        wt = self.worktree(os.path.join(self.repo, ".git", "worktrees", "wt"), "../..")
        with open(os.path.join(wt, ".mcp.json"), "w") as f:
            f.write("{}")
        os.makedirs(os.path.join(wt, ".claude"))
        with open(os.path.join(wt, ".claude", "settings.json"), "w") as f:
            f.write("{}")
        self.write({"projects": {self.slash(self.repo): {"hasTrustDialogAccepted": True}}})
        with mock.patch.object(server, "open_window", return_value="a window") as open_window:
            out = server.open_claude_session({"cwd": wt})
        os.remove(open_window.call_args[0][1][-1])
        self.assertIn(".mcp.json servers are approved separately", out)
        self.assertNotIn("settings.json", out)  # the repository itself is trusted exactly

    def test_submodule_is_its_own_repository(self):
        wt = self.worktree(os.path.join(self.repo, ".git", "modules", "sub"), None)
        self.assertEqual(server.trust_key(wt), (wt, True))

    def test_unreadable_state_is_unknown(self):
        os.remove(self.state)
        self.assertIsNone(server.folder_trusted(self.plain))

    def open(self, args):
        with mock.patch.object(server, "open_window", return_value="a window") as open_window:
            out = server.open_claude_session(args)
        for call in open_window.call_args_list:
            os.remove(call[0][1][-1])
        return out, open_window.called

    def backups(self):
        folder = server.trust_backup_dir()
        return sorted(os.listdir(folder)) if os.path.isdir(folder) else []

    def test_claude_state_is_written_only_when_the_user_trusts(self):
        with open(self.state, encoding="utf-8") as f:
            before = f.read()
        out, opened = self.open({"cwd": self.repo})
        self.assertFalse(opened)
        self.assertIn("trust=true", out)
        self.open({"cwd": self.repo, "open_untrusted": True})
        self.open({"cwd": self.plain})
        with open(self.state, encoding="utf-8") as f:
            self.assertEqual(f.read(), before)
        self.assertEqual(os.listdir(self.config), [".claude.json"])
        self.assertEqual(self.backups(), [])

    def test_trust_records_the_repository_and_backs_up_first(self):
        with open(self.state, encoding="utf-8") as f:
            before = f.read()
        out, opened = self.open({"cwd": os.path.join(self.repo, "src"), "trust": True})
        self.assertTrue(opened)
        self.assertIn("Recorded the user's trust in " + self.slash(self.repo), out)
        self.assertNotIn("Warning", out)
        data = self.read()
        self.assertIs(data["projects"][self.slash(self.repo)]["hasTrustDialogAccepted"], True)
        self.assertEqual(data["numStartups"], 3)  # everything else is kept
        self.assertEqual(data["projects"]["other"], {"allowedTools": ["x"]})
        self.assertEqual(data["é"], "ü")
        [backup] = self.backups()
        self.assertIn(backup, out)
        with open(os.path.join(server.trust_backup_dir(), backup), encoding="utf-8") as f:
            self.assertEqual(f.read(), before)
        self.assertEqual(os.listdir(self.config), [".claude.json"])  # no temporary file left behind
        # Already trusted: nothing more is written or backed up.
        out, _ = self.open({"cwd": self.repo, "trust": True})
        self.assertNotIn("Recorded", out)
        self.assertEqual(len(self.backups()), 1)

    def test_only_the_newest_backups_are_kept(self):
        for i in range(server.TRUST_BACKUPS_KEPT + 3):
            folder = os.path.join(self.projects, f"p{i}")
            os.mkdir(folder)
            server.trust_folder(folder)
        self.assertEqual(len(self.backups()), server.TRUST_BACKUPS_KEPT)
        self.assertTrue(all(server.folder_trusted(os.path.join(self.projects, f"p{i}"))
                            for i in range(server.TRUST_BACKUPS_KEPT + 3)))

    def test_trust_is_refused_where_claude_code_doesnt_keep_it(self):
        with open(self.state, encoding="utf-8") as f:
            before = f.read()
        with mock.patch.object(server.os.path, "expanduser", side_effect=lambda p: p.replace("~", self.plain)):
            with self.assertRaisesRegex(server.BridgeError, "home folder"):
                server.trust_folder(self.plain)
        meta = os.path.join(self.tmp, "metadata", ".git")
        wt = self.worktree(os.path.join(meta, "worktrees", "wt"), "../..")
        with self.assertRaisesRegex(server.BridgeError, "git layout is unusual"):
            server.trust_folder(wt)
        self.write([1, 2])
        with self.assertRaisesRegex(server.BridgeError, "Nothing was changed"):
            server.trust_folder(self.repo)
        self.write({"projects": {}})
        with open(self.state, "a", encoding="utf-8") as f:
            f.write("garbage")
        with self.assertRaisesRegex(server.BridgeError, "Nothing was changed"):
            server.trust_folder(self.repo)
        self.assertEqual(self.backups(), [])
        self.write(json.loads(before))

    def test_values_that_cant_be_written_back_leave_the_file_alone(self):
        for text in ('{"big": 1e400, "projects": {}}', '{"odd": "\\ud800", "projects": {}}',
                     '{"nan": NaN, "projects": {}}'):
            with open(self.state, "w", encoding="utf-8") as f:
                f.write(text)
            with self.assertRaisesRegex(server.BridgeError, "Nothing was changed"):
                server.trust_folder(self.repo)
            with open(self.state, encoding="utf-8") as f:
                self.assertEqual(f.read(), text)
            self.assertEqual(os.listdir(self.config), [".claude.json"])
        self.assertEqual(self.backups(), [])

    def test_a_failed_write_leaves_no_temporary_file(self):
        with mock.patch.object(server.os, "replace", side_effect=OSError("busy")), \
                mock.patch.object(server.time, "sleep"):
            with self.assertRaisesRegex(server.BridgeError, "kept changing"):
                server.trust_folder(self.repo)
        self.assertEqual(os.listdir(self.config), [".claude.json"])

    def test_relative_backup_folders_are_ignored(self):
        with mock.patch.dict(server.os.environ, {"LOCALAPPDATA": "rel", "XDG_STATE_HOME": "rel"}):
            folder = server.trust_backup_dir()
        self.assertTrue(os.path.isabs(folder))
        self.assertNotIn(os.path.join("rel", "nouez"), folder)

    def test_backups_another_server_removed_are_skipped(self):
        real = os.path.getmtime
        def gone(path):
            if path.endswith(".bak") and os.path.basename(path).startswith(".claude.json.0"):
                raise FileNotFoundError(path)
            return real(path)
        os.makedirs(server.trust_backup_dir())
        open(os.path.join(server.trust_backup_dir(), ".claude.json.0-vanished.bak"), "w").close()
        with mock.patch.object(server.os.path, "getmtime", side_effect=gone):
            name, backup = server.trust_folder(self.repo)
        self.assertTrue(os.path.exists(backup))
        self.assertTrue(server.folder_trusted(self.repo))

    def test_a_name_that_reads_as_an_option_opens_nothing(self):
        target = os.path.join(self.plain, "new-folder")
        for name in ("--dangerously-skip-permissions", "-x", "a;b", "a\nb", "x" * 65):
            with mock.patch.object(server, "open_window") as open_window:
                with self.assertRaises(server.BridgeError) as caught:
                    server.open_claude_session({"cwd": target, "name": name, "create": True})
            self.assertIn("Nothing was opened", str(caught.exception))
            open_window.assert_not_called()
            self.assertFalse(os.path.exists(target))

    def test_session_names_from_folders(self):
        self.assertEqual(server.session_name_from("my project"), "my project")
        self.assertEqual(server.session_name_from("análisis 2"), "análisis 2")
        self.assertEqual(server.session_name_from("--x;y"), "x-y")
        self.assertEqual(server.session_name_from("---"), "claude")
        self.assertTrue(server.CLAUDE_SESSION_NAME.fullmatch(server.session_name_from("a" * 100)))

    def test_inherited_trust_notes_what_may_still_ask(self):
        os.makedirs(os.path.join(self.plain, ".claude"))
        for name in (os.path.join(".claude", "settings.json"), ".mcp.json"):
            with open(os.path.join(self.plain, name), "w") as f:
                f.write("{}")
        with mock.patch.object(server, "open_window", return_value="a window") as open_window:
            out = server.open_claude_session({"cwd": self.plain})
        os.remove(open_window.call_args[0][1][-1])
        self.assertIn(".claude/settings.json may bring the trust question back", out)
        self.assertIn(".mcp.json servers are approved separately", out)
        # Trusted exactly: only the MCP servers may still ask.
        self.write({"projects": {self.slash(self.plain): {"hasTrustDialogAccepted": True}}})
        with mock.patch.object(server, "open_window", return_value="a window") as open_window:
            out = server.open_claude_session({"cwd": self.plain})
        os.remove(open_window.call_args[0][1][-1])
        self.assertNotIn("settings.json", out)
        self.assertIn(".mcp.json", out)


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

    def __init__(self, threads, turns=None, fail_after_start=False, answer=None):
        self.threads = {t["id"]: t for t in threads}
        self.answer = answer  # if set, a started turn completes at once with this reply
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
            self.started = params
            turn = {"id": "turn-new", "status": "inProgress",
                    "items": [user(params["input"][0]["text"]), agent("working on it", "commentary")]}
            if self.answer:
                turn = {**turn, "status": "completed", "items": [user(params["input"][0]["text"]), agent(self.answer, "final_answer")]}
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
        self.assertIn("pass model to SendConsultantMessage", out)

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

    def test_model_and_effort_go_to_the_new_turn(self):
        thread = self.consultant("tune01")
        daemon = self.use(FakeDaemon([thread]))
        out = server.send_consultant_message(
            {"to": thread["id"], "message": "hi", "wait": 0, "model": "gpt-6-astra", "effort": "xhigh"})
        self.assertEqual(daemon.started["model"], "gpt-6-astra")
        self.assertEqual(daemon.started["effort"], "xhigh")
        self.assertIn("on model gpt-6-astra, effort xhigh", out)
        self.assertEqual(daemon.started["sandboxPolicy"], {"type": "readOnly"})
        self.assertEqual(daemon.started["approvalPolicy"], "never")
        self.assertIn("keeps for later messages until changed", out)

    def test_a_quick_reply_still_says_the_setting_changed(self):
        thread = self.consultant("tune05")
        self.use(FakeDaemon([thread], answer="the answer"))
        out = server.send_consultant_message({"to": thread["id"], "message": "hi", "effort": "xhigh"})
        self.assertIn("the answer", out)
        self.assertIn("now runs on effort xhigh until changed", out)

    def test_provider_model_ids_pass(self):
        thread = self.consultant("tune06")
        for model in ("gpt-oss:20b", "org/model-1", "gpt-6-astra"):
            daemon = self.use(FakeDaemon([thread]))
            server.send_consultant_message({"to": thread["id"], "message": "hi", "wait": 0, "model": model})
            self.assertEqual(daemon.started["model"], model)

    def test_without_model_or_effort_the_turn_keeps_its_settings(self):
        thread = self.consultant("tune02")
        daemon = self.use(FakeDaemon([thread]))
        out = server.send_consultant_message({"to": thread["id"], "message": "hi", "wait": 0, "effort": ""})
        self.assertNotIn("model", daemon.started)
        self.assertNotIn("effort", daemon.started)
        self.assertNotIn("until changed", out)

    def test_bad_model_or_effort_is_refused_before_sending(self):
        thread = self.consultant("tune03")
        for key, value in (("model", "-c x"), ("model", "a\tb"), ("effort", "very high"), ("effort", 3)):
            daemon = self.use(FakeDaemon([thread]))
            with self.assertRaises(server.BridgeError) as caught:
                server.send_consultant_message({"to": thread["id"], "message": "hi", key: value})
            self.assertIn(f"`{key}` must be", str(caught.exception))
            self.assertNotIn("turn/start", daemon.calls)

    def test_model_or_effort_on_a_busy_consultant_sends_nothing(self):
        thread = self.consultant("tune04")
        running = {"id": "turn-1", "status": "inProgress", "items": [user("q")]}
        daemon = self.use(FakeDaemon([thread], {thread["id"]: [running]}))
        with self.assertRaises(server.BridgeError) as caught:
            server.send_consultant_message({"to": thread["id"], "message": "more", "effort": "high"})
        self.assertIn("Nothing was sent", str(caught.exception))
        self.assertNotIn("turn/steer", daemon.calls)
        self.assertNotIn("turn/start", daemon.calls)

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
        # The user's own session keeps its own sandbox and approvals.
        self.assertNotIn("sandboxPolicy", daemon.started)
        self.assertNotIn("approvalPolicy", daemon.started)

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


class HostWindowTests(unittest.TestCase):
    def test_title_ignores_the_spinner(self):
        self.assertTrue(server._same_title("◐ Fix the build", "✳ Fix the build"))
        self.assertTrue(server._same_title("Fix the build", "Fix the build"))
        self.assertFalse(server._same_title("◐ Fix the build", "◐ Other session"))

    def test_unknown_window_gets_a_window_of_its_own(self):
        with mock.patch.object(server, "wt_host_window", return_value=None), \
                mock.patch.object(server.subprocess, "Popen") as popen:
            how = server.run_in_host_window("wt", ".", ["cmd", "a;b"])
        self.assertEqual(popen.call_args[0][0], ["wt", "-w", "new", "cmd", "a\\;b"])
        self.assertIn("new Windows Terminal window", how)

    def test_semicolons_are_escaped_for_wt(self):
        self.assertEqual(server.wt_escape("demo;calc.exe;"), "demo\\;calc.exe\\;")
        with mock.patch.object(server.shutil, "which", return_value="wt"), \
                mock.patch.object(server.os, "name", "nt"), \
                mock.patch.object(server.subprocess, "Popen") as popen:
            server.open_window("C:/a;b", ["claude"], "Claude: x;calc")
        self.assertEqual(popen.call_args[0][0],
                         ["wt", "-w", "new", "-d", "C:/a\\;b", "--title", "Claude: x\\;calc", "claude"])


class OpenClaudeSessionTests(unittest.TestCase):
    def test_only_session_variables_are_dropped(self):
        env = {"PATH": "p", "CLAUDECODE": "1", "CLAUDE_CODE_CHILD_SESSION": "1", "CLAUDE_CODE_SESSION_ID": "x",
               "CLAUDE_PID": "1", "AI_AGENT": "a", "CLAUDE_CODE_MESSAGING_TOKEN": "t",
               "ANTHROPIC_MODEL": "m", "CLAUDE_CODE_OAUTH_TOKEN": "o", "CLAUDE_CODE_USE_BEDROCK": "1"}
        self.assertEqual(server.fresh_claude_env(env),
                         {"PATH": "p", "ANTHROPIC_MODEL": "m", "CLAUDE_CODE_OAUTH_TOKEN": "o",
                          "CLAUDE_CODE_USE_BEDROCK": "1"})

    def test_claude_is_not_taken_from_the_project(self):
        with tempfile.TemporaryDirectory() as project, tempfile.TemporaryDirectory() as bin_dir:
            name = "claude.exe" if os.name == "nt" else "claude"
            for folder in (project, bin_dir):
                path = os.path.join(folder, name)
                with open(path, "w") as f:
                    f.write("")
                os.chmod(path, 0o755)
            cwd = os.getcwd()
            os.chdir(project)
            try:
                found = server.find_program("claude", os.pathsep.join([".", "", "relative", bin_dir]))
            finally:
                os.chdir(cwd)
        self.assertEqual(os.path.dirname(found), bin_dir)

    def run_helper(self, prompt, returncode=0, closed=False, extra=None):
        fd, spec = tempfile.mkstemp(prefix="nouez-claude-", suffix=".json")
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(dict({"cwd": ROOT, "name": "n", "prompt": prompt}, **(extra or {})), f)
        child = mock.Mock(pid=999999)
        child.wait.return_value = returncode
        marker = server.close_marker(999999)
        if closed:
            open(marker, "w").close()
        with mock.patch.object(server, "find_program", return_value="claude"), \
                mock.patch.object(server.subprocess, "Popen", return_value=child) as popen:
            code = server.run_claude(spec)
        self.assertFalse(os.path.exists(spec))
        self.assertFalse(os.path.exists(marker))
        self.child_env = popen.call_args[1]["env"]
        return popen.call_args[0][0], code

    def test_prompt_cannot_become_an_option(self):
        argv, _ = self.run_helper("--dangerously-skip-permissions")
        self.assertEqual(argv, ["claude", "--remote-control", "n", "--name", "n", "--", "--dangerously-skip-permissions"])
        argv, _ = self.run_helper("")
        self.assertEqual(argv, ["claude", "--remote-control", "n", "--name", "n"])

    def test_model_and_effort_are_passed_on(self):
        with mock.patch.dict(server.os.environ, {"CLAUDE_CODE_EFFORT_LEVEL": "high"}):
            argv, _ = self.run_helper("hi", extra={"model": "opus", "effort": "medium"})
        self.assertEqual(argv, ["claude", "--remote-control", "n", "--name", "n", "--model", "opus",
                                "--effort", "medium", "--", "hi"])
        self.assertEqual(self.child_env["CLAUDE_CODE_EFFORT_LEVEL"], "medium")  # it outranks --effort

    def test_sessions_start_on_opus_at_medium_effort(self):
        def spec_of(args):
            with mock.patch.object(server, "open_window", return_value="a window") as open_window, \
                    mock.patch.object(server, "folder_trusted", return_value=True):
                out = server.open_claude_session(dict({"cwd": ROOT}, **args))
            path = open_window.call_args[0][1][-1]
            with open(path, encoding="utf-8") as f:
                spec = json.load(f)
            os.remove(path)
            return spec, out
        spec, out = spec_of({})
        self.assertEqual((spec["model"], spec["effort"]), ("opus", "medium"))
        self.assertIn("(opus, medium effort)", out)
        spec, _ = spec_of({"model": "claude-sonnet-5-5", "effort": "high"})
        self.assertEqual((spec["model"], spec["effort"]), ("claude-sonnet-5-5", "high"))
        for bad in ({"model": "--dangerously-skip-permissions"}, {"model": "opus sonnet"}, {"model": 5},
                    {"effort": "huge"}, {"effort": True}):
            with self.assertRaises(server.BridgeError):
                spec_of(bad)

    def test_helper_exits_cleanly_when_closed_on_purpose(self):
        self.assertEqual(self.run_helper("", returncode=1, closed=True)[1], 0)
        self.assertEqual(self.run_helper("", returncode=1)[1], 1)

    def test_cwd_must_be_an_existing_absolute_folder(self):
        for cwd in (None, "relative", os.path.join(ROOT, "no-such-folder")):
            with self.assertRaises(server.BridgeError):
                server.open_claude_session({"cwd": cwd})

    def test_spec_is_passed_by_file(self):
        with mock.patch.object(server, "open_window", return_value="a window") as open_window, \
                mock.patch.object(server, "folder_trusted", return_value=True):
            out = server.open_claude_session({"cwd": ROOT, "prompt": "a; b \"c\""})
        argv = open_window.call_args[0][1]
        self.assertEqual(argv[-2], "claude")
        with open(argv[-1], encoding="utf-8") as f:
            self.assertEqual(json.load(f), {"cwd": os.path.abspath(ROOT), "name": os.path.basename(ROOT),
                                            "prompt": "a; b \"c\"", "model": "opus", "effort": "medium"})
        os.remove(argv[-1])
        self.assertIn("Remote Control", out)

    def test_untrusted_folder_isnt_opened_without_an_answer(self):
        with mock.patch.object(server, "open_window") as open_window, \
                mock.patch.object(server, "folder_trusted", return_value=False):
            out = server.open_claude_session({"cwd": ROOT})
        open_window.assert_not_called()
        self.assertIn("Not opened", out)
        self.assertIn("open_untrusted=true", out)
        self.assertIn("a git repository is trusted on its own", out)  # ROOT is a checkout

    def test_open_untrusted_opens_with_a_warning(self):
        with mock.patch.object(server, "open_window", return_value="a window") as open_window, \
                mock.patch.object(server, "folder_trusted", return_value=False):
            out = server.open_claude_session({"cwd": ROOT, "open_untrusted": True})
        os.remove(open_window.call_args[0][1][-1])
        self.assertIn("waiting at the trust question", out)

    def test_unknown_trust_opens_with_a_note(self):
        with mock.patch.object(server, "open_window", return_value="a window") as open_window, \
                mock.patch.object(server, "folder_trusted", return_value=None):
            out = server.open_claude_session({"cwd": ROOT})
        os.remove(open_window.call_args[0][1][-1])
        self.assertIn("can't tell whether Claude Code has been trusted", out)

    def test_create_a_new_folder(self):
        with tempfile.TemporaryDirectory() as parent:
            cwd = os.path.join(parent, "economic recession")
            with mock.patch.object(server, "open_window") as open_window, \
                    mock.patch.object(server, "folder_trusted", return_value=False):
                out = server.open_claude_session({"cwd": cwd, "create": True})
            self.assertTrue(os.path.isdir(cwd))
            open_window.assert_not_called()
            self.assertIn("Created the folder", out)
            self.assertIn("Not opened", out)
            with mock.patch.object(server, "open_window", return_value="a window") as open_window, \
                    mock.patch.object(server, "folder_trusted", return_value=True):
                out = server.open_claude_session({"cwd": cwd, "create": True})
            os.remove(open_window.call_args[0][1][-1])
            self.assertNotIn("Created", out)  # already there
            self.assertNotIn("Note", out)
            with self.assertRaises(server.BridgeError):  # parent must exist
                server.open_claude_session({"cwd": os.path.join(parent, "a", "b"), "create": True})

    @unittest.skipUnless(os.name == "nt", "Windows checks the process creation time")
    def test_registry_entries_need_a_matching_start_time(self):
        with tempfile.TemporaryDirectory() as config:
            os.mkdir(os.path.join(config, "sessions"))
            for pid, start in ((11, 123), (12, None), (13, "unknown"), (14, 999)):
                entry = {"pid": pid, "name": f"s{pid}", "kind": "interactive"}
                if start is not None:
                    entry["procStart"] = str(start)
                with open(os.path.join(config, "sessions", f"{pid}.json"), "w") as f:
                    json.dump(entry, f)
            with mock.patch.dict(server.os.environ, {"CLAUDE_CONFIG_DIR": config}), \
                    mock.patch.object(server, "process_table", return_value={}), \
                    mock.patch.object(server, "process_start", return_value=123):
                names = [s["name"] for s in server.claude_sessions()]
        self.assertEqual(names, ["s11"])

    def session(self, name, pid, helper=None):
        return {"name": name, "pid": pid, "cwd": "C:/p", "status": "idle", "session_id": f"s{pid}",
                "remote": True, "helper": helper, "start": 1, "helper_start": 0 if helper else None}

    def test_list_marks_this_session(self):
        out = server.describe_sessions([self.session("other", 41, helper=40), self.session("me", 51)], {51})
        self.assertIn("other (pid 41): C:/p [idle, Remote Control, opened by OpenClaudeSession]", out)
        self.assertIn("me (pid 51): C:/p [idle, Remote Control, this session]", out)

    def test_close_refuses_unknown_and_own_sessions(self):
        running = [self.session("other", 41), self.session("me", 51)]
        with mock.patch.object(server, "claude_sessions", return_value=running), \
                mock.patch.object(server, "own_claude_pids", return_value={51}), \
                mock.patch.object(server, "end_session") as end:
            for args in ({}, {"name": "typed-by-hand"}, {"name": "me"}, {"pid": 51}, {"pid": True}):
                with self.assertRaises(server.BridgeError):
                    server.close_claude_session(args)
            end.assert_not_called()

    def test_close_needs_pid_when_names_repeat(self):
        running = [self.session("x", 41), self.session("x", 61, helper=60)]
        with mock.patch.object(server, "claude_sessions", return_value=running), \
                mock.patch.object(server, "own_claude_pids", return_value=set()), \
                mock.patch.object(server, "end_session") as end:
            with self.assertRaises(server.BridgeError):
                server.close_claude_session({"name": "x"})
            out = server.close_claude_session({"name": "x", "pid": 61})
        self.assertIn("pid 61) and its window", out)
        self.assertIn("claude --resume s61", out)
        end.assert_called_once_with(running[1])

    @unittest.skipUnless(os.name == "nt", "Windows process handles")
    def test_end_session_checks_identity_and_result(self):
        proc = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
        try:
            start = server.process_start(proc.pid)
            target = {"name": "t", "pid": proc.pid, "start": start + 1, "helper": None}
            with self.assertRaises(server.BridgeError):
                server.end_session(target)  # another process now holds that pid
            self.assertIsNone(proc.poll())
            server.end_session(dict(target, start=start))
            self.assertIsNotNone(proc.wait(timeout=5))
            with self.assertRaises(server.BridgeError):
                server.end_session(dict(target, start=start))  # already gone
        finally:
            proc.kill()
            proc.wait()


class AdditionsTest(HandlerTest):
    """0.12.0: more said in results, and options used only when asked for."""

    def done(self, tid, text, sender="Claude Code", status="completed", **extra):
        msg = f"[Message from {sender} via the consultants bridge]\n\n{text}"
        return {"id": tid, "status": status, "startedAt": int(time.time()) - 120, "durationMs": 4000,
                "items": [user(msg), agent(f"answer to {text}\nmore", "final_answer")], **extra}

    def test_failed_turn_says_codex_failed_and_resending_is_safe(self):
        turn = {"id": "t1", "status": "failed", "error": {"message": "stream disconnected"}, "items": [user("q")]}
        out = server.format_turn("codex-x", turn)
        self.assertIn("turn t1 failed. stream disconnected", out)
        self.assertIn("inside Codex", out)
        self.assertIn("got no answer", out)
        self.assertIn("Sending the message again is safe", out)
        self.assertNotIn("inside Codex", server.format_turn("codex-x", dict(turn, status="interrupted")))

    def test_truncated_reply_points_to_offset_paging(self):
        out = server.cap_reply("turn-test-offset", "a" * 50, 10)
        self.addCleanup(os.remove, os.path.join(server.tempfile.gettempdir(), "nouez", "turn-test-offset.md"))
        self.assertIn("GetConsultantReply (turn_id turn-test-offset, offset 10)", out)

    def test_reply_reads_from_an_offset(self):
        thread = self.consultant("page01")
        turn = {"id": "turn-1", "status": "completed", "items": [user("q"), agent("0123456789", "final_answer")]}
        self.use(FakeDaemon([thread], {thread["id"]: [turn]}))
        with mock.patch.object(server, "MAX_REPLY_CHARS", 4):
            out = server.get_consultant_reply({"to": thread["id"], "turn_id": "turn-1", "offset": 3})
        self.assertIn("characters 3-7 of 10", out)
        self.assertIn("3456", out)
        self.assertIn("read on with offset 7", out)
        out = server.get_consultant_reply({"to": thread["id"], "offset": 20})
        self.assertIn("past its end", out)
        for bad in (-1, "3", True, 1.5):
            with self.assertRaises(server.BridgeError):
                server.get_consultant_reply({"to": thread["id"], "offset": bad})

    def test_reuse_shows_age_turns_and_the_last_exchange(self):
        thread = self.consultant("ctx001", createdAt=int(time.time()) - 3 * 86400, reasoningEffort="high", model="m1")
        turns = [self.done("turn-2", "second question", "agentic_training"), self.done("turn-1", "first")]
        self.use(FakeDaemon([thread], {thread["id"]: turns}))
        out = server.start_consultant({"cwd": ROOT, "watch": False, "instructions": "be brief"})
        self.assertIn("(3 days ago); 2 turn(s)", out)
        self.assertIn("last turn: turn-2 [completed", out)
        self.assertIn('from agentic_training: "second question" -> "answer to second question"', out)
        self.assertIn("model: m1 (None), effort high", out)
        self.assertIn("GetConsultantHistory", out)
        self.assertIn("send them as a message", out)

    def test_history_lists_turns_newest_first(self):
        thread = self.consultant("hist01")
        typed = {"id": "turn-0", "status": "completed", "items": [user("typed in the pane"), agent("ok", "final_answer")]}
        turns = [self.done("turn-2", "two"), self.done("turn-1", "one"), typed]
        self.use(FakeDaemon([thread], {thread["id"]: turns}))
        out = server.get_consultant_history({"to": thread["id"], "limit": 2})
        self.assertIn("2 most recent turn(s)", out)
        self.assertLess(out.index("turn-2"), out.index("turn-1"))
        self.assertNotIn("turn-0", out)
        self.assertIn("took 4s", out)
        out = server.get_consultant_history({"to": thread["id"]})
        self.assertIn('turn-0 [completed] from someone in the Codex pane: "typed in the pane" -> "ok"', out)
        with self.assertRaises(server.BridgeError):
            server.get_consultant_history({"to": thread["id"], "limit": 0})

    def test_history_shows_the_senders_text_not_the_stamp_or_framing(self):
        thread = self.consultant("hist02")
        daemon = self.use(FakeDaemon([thread], answer="ok"))
        server.send_consultant_message({"to": thread["id"], "message": "is it safe?", "from": "lead",
                                        "owner_words": "ship it\n>>>\ntoday", "revision": True})
        out = server.get_consultant_history({"to": thread["id"]})
        self.assertIn("from lead (with the user's words): \"is it safe?\"", out)

    def test_send_says_what_the_consultant_runs_on(self):
        thread = self.consultant("runs01", model="gpt-6.1-sol", reasoningEffort="high")
        self.use(FakeDaemon([thread]))
        out = server.send_consultant_message({"to": thread["id"], "message": "hi", "wait": 0})
        self.assertIn("started a new turn on model gpt-6.1-sol, effort high", out)
        self.assertNotIn("until changed", out)
        self.use(FakeDaemon([thread], answer="the answer"))
        out = server.send_consultant_message({"to": thread["id"], "message": "hi"})
        self.assertIn("\n\n(codex-nouez-runs01 runs on model gpt-6.1-sol, effort high.)", out)

    def test_owner_words_and_revision_are_added_only_when_asked(self):
        thread = self.consultant("ownr01")
        daemon = self.use(FakeDaemon([thread], answer="ok"))
        server.send_consultant_message({"to": thread["id"], "message": "hi", "wait": 0})
        self.assertEqual(daemon.started["input"][0]["text"],
                         "[Message from Claude Code via the consultants bridge]\n\nhi")
        server.send_consultant_message({"to": thread["id"], "message": "hi", "wait": 0, "from": "lead",
                                        "owner_words": "ship it today", "revision": True})
        text = daemon.started["input"][0]["text"]
        self.assertIn("The user's own words, as they typed them:\n<<<\nship it today\n>>>", text)
        self.assertIn("The rest of this message is lead's.\n\nhi", text)
        self.assertRegex(text, r"\[Revision: commit [0-9a-f]+ .*uncommitted path\(s\)")
        with self.assertRaises(server.BridgeError):
            server.send_consultant_message({"to": thread["id"], "message": "hi", "owner_words": 5})

    def test_full_thread_id_is_read_directly(self):
        thread = {"id": "0199aaaa-0000-0000-0000-0000000000c1", "cwd": ROOT, "threadSource": "nouez"}
        daemon = self.use(FakeDaemon([thread]))
        found = server.resolve(daemon, thread["id"].upper())
        self.assertEqual(found["id"], thread["id"])
        self.assertTrue(found["_loaded"])
        self.assertNotIn("thread/list", daemon.calls)


class OpenedSessionCheckTest(unittest.TestCase):
    def open(self, sessions_seen, tmp):
        with mock.patch.object(server, "open_window", return_value="a window") as open_window, \
             mock.patch.object(server, "folder_trusted", return_value=True), \
             mock.patch.object(server, "trust_key", return_value=(tmp, False)), \
             mock.patch.object(server, "exactly_trusted", return_value=True), \
             mock.patch.object(server, "claude_sessions", side_effect=sessions_seen):
            out = server.open_claude_session({"cwd": tmp})
        os.remove(open_window.call_args[0][1][-1])
        return out

    def session(self, pid, cwd, remote):
        return {"pid": pid, "name": f"s{pid}", "cwd": cwd, "remote": remote}

    def test_reports_connection_and_an_existing_session(self):
        with tempfile.TemporaryDirectory() as tmp:
            old = self.session(1, tmp, True)
            out = self.open([[old], [old, self.session(2, tmp, True)]], tmp)
            self.assertIn("already running in this folder: s1 (pid 1)", out)
            self.assertIn("connected to Remote Control", out)

    def test_reports_a_session_that_hasnt_connected(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = self.open([[], [self.session(2, tmp, False)]], tmp)
            self.assertIn("hadn't connected to Remote Control", out)
            self.assertNotIn("already running", out)
            out = self.open([[], []], tmp)
            self.assertIn("hadn't shown up as a running session", out)

    def test_a_failing_check_still_opens(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = self.open(OSError("unreadable"), tmp)
            self.assertIn("Opened a window", out)


if __name__ == "__main__":
    unittest.main()
