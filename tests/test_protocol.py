"""Protocol tests for nouez. Standard library only; no Codex daemon needed.

Run from the repo root: python -m unittest discover tests
"""

import json
import os
import queue
import subprocess
import sys
import threading
import unittest

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

    def test_negative_timeout_is_a_tool_error(self):
        reply = self.server.request(6, "tools/call", {"name": "SendConsultantMessage", "arguments": {
            "to": "x", "message": "hi", "timeout_seconds": -5}})
        self.assertTrue(reply["result"]["isError"])
        self.assertIn("0 or more", reply["result"]["content"][0]["text"])

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
    def test_number_rejects_negative_and_non_finite(self):
        for value in (-1, "-5", float("nan"), float("inf"), "x", True):
            with self.assertRaises(server.BridgeError):
                server.number({"t": value}, "t", 0)

    def test_number_is_capped(self):
        self.assertEqual(server.number({"t": 10 ** 9}, "t", 0), server.MAX_WAIT_SECONDS)

    def test_until_done_is_capped(self):
        self.assertEqual(server.wait_seconds({"until_done": True}, 0), server.MAX_WAIT_SECONDS)


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
        original = server.CodexClient
        server.CodexClient = daemon
        self.addCleanup(setattr, server, "CodexClient", original)
        return daemon

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

    def test_send_timeout_shows_output_so_far(self):
        tid = "0199aaaa-0000-0000-0000-000000idle01"
        self.use(FakeDaemon([{"id": tid, "cwd": ROOT}]))
        out = server.send_consultant_message({"to": tid, "message": "hi", "timeout_seconds": 0})
        self.assertIn("still working on turn turn-new; this is not a reply", out)
        self.assertIn("Don't send the message again", out)
        self.assertTrue(out.endswith("working on it"))

    def test_steered_timeout_hides_output_from_before_the_message(self):
        tid = "0199aaaa-0000-0000-0000-000000busy01"
        running = {"id": "turn-1", "status": "inProgress", "items": [user("q"), agent("answer to q")]}
        self.use(FakeDaemon([{"id": tid, "cwd": ROOT}], {tid: [running]}))
        out = server.send_consultant_message({"to": tid, "message": "more", "timeout_seconds": 0})
        self.assertIn("steered into the running turn", out)
        self.assertNotIn("answer to q", out)

    def test_failure_after_delivery_says_delivered(self):
        tid = "0199aaaa-0000-0000-0000-000000fail01"
        self.use(FakeDaemon([{"id": tid, "cwd": ROOT}], fail_after_start=True))
        with self.assertRaises(server.BridgeError) as caught:
            server.send_consultant_message({"to": tid, "message": "hi"})
        self.assertTrue(str(caught.exception).startswith("Delivered to "))
        self.assertIn("Don't send the message again", str(caught.exception))


if __name__ == "__main__":
    unittest.main()
