"""Protocol tests for nouez. Standard library only; no Codex daemon needed.

Run from the repo root: python -m unittest discover tests
"""

import contextlib
import glob
import hashlib
import io
import json
import ntpath
import os
import queue
import re
import shutil
import signal
import subprocess
import sys
import tempfile
import threading
import time
import types
import unittest
import urllib.error
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
import server  # noqa: E402


def setUpModule():
    # Whether this machine has Codex mustn't change the results: tests take it as installed unless
    # they say otherwise. Set directly, not with a started patch, which a test's
    # mock.patch.stopall would stop too.
    real = server.codex_installed
    server.codex_installed = lambda: True
    unittest.addModuleCleanup(setattr, server, "codex_installed", real)
    # Tests that send a legacy request through dispatch take the handshake as done, as a client's
    # would be; the test of requests before it uses an Event of its own.
    server._initialized.set()
    unittest.addModuleCleanup(server._initialized.clear)

# Tests never write to the user's usage log; the log's own tests turn it back on for a temp file.
os.environ["NOUEZ_NO_USAGE_LOG"] = "1"
# Nor run `claude auth status`: whether this machine's sign-in ends soon mustn't change a result.
os.environ["NOUEZ_NO_LOGIN_CHECK"] = "1"

# Tests never see the user's own Antigravity consultants; AgyTest points this at its own folder.
_AGY_EMPTY = tempfile.mkdtemp(prefix="nouez-test-agy-")
server.agy_root = lambda: os.path.join(_AGY_EMPTY, "agy")
# Nor nouez's Codex lock files.
_CODEX_LOCKS = tempfile.mkdtemp(prefix="nouez-test-codex-locks-")
server.codex_lock_folder = lambda create=False: _CODEX_LOCKS

server.CONNECT_SECONDS = 0  # OpenClaudeSession tests look for the new session once, not for 15 s

# Tests never see this computer's own phone dispatcher, nor its sign-in task or other Remote Control
# servers; DispatcherTest points these at its own folders.
_REAL_DISPATCHER = {name: getattr(server, name) for name in ("dispatcher_installed", "other_remote_controls")}
_REAL_FILELOCK = server.FileLock
_REAL_DISPATCHER_TRUSTED, _REAL_FOLDER_TRUSTED = server.dispatcher_trusted, server.folder_trusted
_REAL_NOUEZ_SCRIPT, _REAL_DEFAULT_FOLDER = server.nouez_script, server.dispatcher_default_folder
_DISPATCHER_EMPTY = tempfile.mkdtemp(prefix="nouez-test-dispatcher-")
server._dispatcher_root[:] = [os.path.join(_DISPATCHER_EMPTY, "cache")]
os.makedirs(server._dispatcher_root[0], exist_ok=True)
server.dispatcher_default_folder = lambda: os.path.join(_DISPATCHER_EMPTY, "Projects", "dispatcher")
server.dispatcher_installed = lambda check_off=True, want=None: "no"
server.other_remote_controls = lambda own=None: []
# Nor this computer's own Claude Code settings: a setup's status line offer reads them (#52).
_REAL_STATUSLINE_OFFER = server.statusline_offer
server.statusline_offer = lambda dry_run, add, out=print, ask=None: None

# Tests never open a real terminal window: one that reaches a launcher without mocking Popen fails.
_REAL_POPEN = subprocess.Popen


def _no_real_window(real):
    def guarded(argv, *args, **kwargs):
        stub = isinstance(argv, list) and argv[:2] == [sys.executable, "-c"]  # a test's own stand-in
        if server.subprocess.Popen is _REAL_POPEN and not stub:
            raise AssertionError(f"a test would open a real window: {argv!r}")
        return real(argv, *args, **kwargs)
    return guarded


server.launch = _no_real_window(server.launch)
server.launch_console = _no_real_window(server.launch_console)



def dir_link(target, link):
    """A link to a folder: a symbolic link, or on Windows without the right to make one, a junction."""
    try:
        os.symlink(target, link, target_is_directory=True)
    except OSError:
        if os.name != "nt":
            raise
        import _winapi
        _winapi.CreateJunction(target, link)


def file_link(test, target, link):
    try:
        os.symlink(target, link)
    except (OSError, NotImplementedError):
        test.skipTest("this account can't make symbolic links")


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

    def handshake(self):
        """A legacy client's initialize, which every request but ping needs before it (Codex round 2)."""
        reply = self.server.request("init", "initialize", {"protocolVersion": server.PROTOCOL_VERSIONS[0],
                                                           "capabilities": {}})
        self.assertIn("result", reply)

    def test_negotiates_supported_version(self):
        for requested in server.PROTOCOL_VERSIONS:
            reply = self.server.request(1, "initialize", {"protocolVersion": requested, "capabilities": {}})
            self.assertEqual(reply["result"]["protocolVersion"], requested)

    def test_instructions_choose_by_the_budget(self):
        reply = self.server.request(1, "initialize", {"protocolVersion": server.PROTOCOL_VERSIONS[0], "capabilities": {}})
        text = reply["result"]["instructions"]
        self.assertIn("call ConsultantBudget with its kind", text)
        self.assertIn("unless the user named others or the user's own instructions route otherwise", text)
        self.assertIn("which applies the suggested model and effort", text)
        self.assertIn("never take a 'still working' result for one", text)
        self.assertLess(len(text), 1500)  # the moments to consult and what to call; the rest is in the tools

    def test_only_claude_code_is_offered_the_background_waiter(self):
        # A client that says it is another program reads replies with GetConsultantReply; Claude Code,
        # and a client that doesn't say, get the waiter command. The client is recorded in the usage log.
        self.addCleanup(server._client_info.clear)
        for name, waiter in (("claude-code", True), ("Claude-Code", True), (None, True), ("other-host", False)):
            with self.subTest(name=name):
                server._client_info.clear()
                if name:
                    server._client_info["name"] = name
                text = server.read_later("thread-1", "turn-1")
                self.assertEqual(" wait thread-1 turn-1" in text, waiter)
                self.assertIn("GetConsultantReply (turn_id turn-1)", text)
        # Codex finding 9: GetConsultantReply on a turn still running gives the same advice.
        turn = {"id": "turn-1", "status": "inProgress", "items": [agent("so far", "commentary")]}
        for name, waiter in (("claude-code", True), ("other-host", False)):
            with self.subTest(polling=name):
                server._client_info.clear()
                server._client_info["name"] = name
                text = server.still_working_reply("c", "thread-1", turn)
                self.assertEqual(" wait thread-1 turn-1" in text, waiter)
                self.assertIn("heck again later with turn_id turn-1", text)
        # A request's own _meta clientInfo wins over the handshake's.
        server._client_info.clear()
        server._client_info.update(name="claude-code")
        server._request.client = {"name": "other-host"}
        self.addCleanup(setattr, server._request, "client", None)
        self.assertFalse(server.background_waiter())
        log = os.path.join(tempfile.mkdtemp(), "usage-log.jsonl")
        self.addCleanup(shutil.rmtree, os.path.dirname(log))
        with mock.patch.dict(os.environ, {"NOUEZ_NO_USAGE_LOG": ""}):
            server.record_usage({"event": "send"}, path=log)
        with open(log, encoding="utf-8") as f:
            self.assertEqual(json.loads(f.readline())["client"], "other-host")

    def test_initialize_records_the_client(self):
        self.addCleanup(server._client_info.clear)
        sent = []
        with mock.patch.object(server, "respond", lambda i, result=None, error=None: sent.append(result)), \
                mock.patch.object(server, "start_release_check", lambda *a, **k: None), \
                mock.patch.object(server, "start_pane_cleanup", lambda: None), \
                mock.patch.object(server, "login_state", lambda *a, **k: None):
            server.dispatch({"id": 1, "method": "initialize", "params": {
                "protocolVersion": server.PROTOCOL_VERSIONS[0], "capabilities": {},
                "clientInfo": {"name": "other-host", "version": "1.0", "extra": "x"}}}, threading.Event())
        self.assertEqual(server._client_info, {"name": "other-host", "version": "1.0"})
        self.assertFalse(server.background_waiter())
        self.assertIn("never take a 'still working' result", sent[0]["instructions"])

    def test_mcp_2026_07_28_requests_alongside_the_handshake(self):
        # A request with the 2026-07-28 _meta is handled on its own: discovery, results marked
        # complete with the server named, no legacy capabilities, roots or client inherited.
        self.addCleanup(server._client_info.clear)
        self.addCleanup(server._client_caps.clear)
        sent = []
        modern = {server.META_VERSION: "2026-07-28", server.META_CAPS: {}}

        def call(method, params=None, msg_id=1):
            sent.clear()
            server.dispatch({"id": msg_id, "method": method, "params": params or {}}, threading.Event())
            return sent[-1]
        with mock.patch.object(server, "respond", lambda i, result=None, error=None: sent.append((result, error))), \
                mock.patch.object(server, "start_release_check", lambda *a, **k: None), \
                mock.patch.object(server, "start_pane_cleanup", lambda: None), \
                mock.patch.object(server, "login_state", lambda *a, **k: None):
            server._client_caps.update({"roots": {}, "elicitation": {}})
            server._client_info.update({"name": "claude-code"})
            result, error = call("server/discover", {"_meta": modern})
            self.assertIsNone(error)
            self.assertEqual(result["resultType"], "complete")
            self.assertEqual(result["supportedVersions"][0], "2026-07-28")
            self.assertIn("2025-11-25", result["supportedVersions"])
            self.assertEqual((result["ttlMs"], result["cacheScope"]), (0, "private"))
            self.assertEqual(result["_meta"][server.META_SERVER]["name"], "nouez")
            self.assertIn("Consult whenever the user asks", result["instructions"])
            result, error = call("tools/list", {"_meta": modern})
            self.assertEqual((result["resultType"], result["ttlMs"]), ("complete", 0))
            self.assertEqual(result["tools"], server.TOOLS)
            # The legacy path is unchanged: no resultType, and initialize never offers 2026-07-28.
            self.assertNotIn("resultType", call("tools/list")[0])
            self.assertEqual(call("initialize", {"protocolVersion": "2026-07-28"})[0]["protocolVersion"],
                             server.PROTOCOL_VERSIONS[0])
            # Errors: an unsupported version, missing capabilities, discovery without _meta, gone methods.
            result, error = call("tools/list", {"_meta": {server.META_VERSION: "2099-01-01", server.META_CAPS: {}}})
            self.assertEqual(error["code"], -32022)
            self.assertEqual(error["data"]["requested"], "2099-01-01")
            self.assertIn("2026-07-28", error["data"]["supported"])
            self.assertEqual(call("tools/list", {"_meta": {server.META_VERSION: "2026-07-28"}})[1]["code"], -32602)
            # Any of its keys makes a request a 2026-07-28 one: with the version missing or not a
            # string it is refused, never run under the legacy rules.
            for meta in ({server.META_CAPS: {}}, {server.META_CLIENT: {"name": "x"}},
                         {server.META_VERSION: 20260728, server.META_CAPS: {}}):
                with self.subTest(meta=meta):
                    self.assertEqual(call("tools/list", {"_meta": meta})[1]["code"], -32602)
            registered = server._cancel_events["refused-1"] = threading.Event()  # as route registers a tools/call
            server.dispatch({"id": "refused-1", "method": "tools/call", "params": {
                "name": "Probe", "_meta": {server.META_CAPS: {}}}}, registered)
            self.assertEqual(sent[-1][1]["code"], -32602)
            self.assertNotIn("refused-1", server._cancel_events)  # released though no tool ran
            self.assertEqual(call("server/discover")[1]["code"], -32602)
            for gone in ("ping", "initialize"):
                self.assertEqual(call(gone, {"_meta": modern})[1]["code"], -32601)
            # A tools/call: complete, and nothing inherited from the handshake.
            seen = {}

            def probe(args, cancel, progress):
                seen.update(client=server.client_info(), caps=server.client_caps(), roots=server.client_roots(),
                            waiter=server.background_waiter())
                return "done"
            with mock.patch.dict(server.HANDLERS, {"Probe": probe}), \
                    mock.patch.object(server, "refresh_roots", lambda: self.fail("no roots/list")):
                result, error = call("tools/call", {"name": "Probe", "_meta": dict(
                    modern, **{server.META_CLIENT: {"name": "other-host", "version": "2"}})})
                self.assertEqual(result["resultType"], "complete")
                self.assertEqual(result["content"][0]["text"], "done")
                # Never the handshake's roots, nor the folder it started nouez in, which may hold
                # other projects (Codex round 2, finding 6).
                self.assertEqual(seen, {"client": {"name": "other-host", "version": "2"}, "caps": {},
                                        "roots": [], "waiter": False})
                call("tools/call", {"name": "Probe", "_meta": modern})
                self.assertEqual(seen["client"], {})  # not the handshake's claude-code
                self.assertTrue(seen["waiter"])  # a client that doesn't say who it is
            # An approval: the prompt goes back as input_required, and only the retry that echoes its
            # requestState, once, for the same question, is taken as the answer.
            def ask(args, cancel, progress):
                server.user_approves(args.get("q", "Send it?"), "NOUEZ_ASK_USER_SESSION", cancel)
                return "approved"
            asking = dict(modern, **{server.META_CAPS: {"elicitation": {}}})
            with mock.patch.dict(server.HANDLERS, {"Ask": ask}), \
                    mock.patch.object(server, "client_request", lambda *a, **k: self.fail("no server requests")):
                # A client that can't show a form (no elicitation in its own _meta, or URL mode only)
                # gets the capability error, not a prompt it can't show.
                for caps in ({}, {"elicitation": {"url": {}}}, {"elicitation": None}):
                    with self.subTest(caps=caps):
                        result, error = call("tools/call", {"name": "Ask", "_meta": dict(modern, **{
                            server.META_CAPS: caps})})
                        self.assertIsNone(result)
                        self.assertEqual(error["code"], -32021)
                        self.assertEqual(error["data"]["requiredCapabilities"], {"elicitation": {"form": {}}})
                result, _ = call("tools/call", {"name": "Ask", "_meta": dict(modern, **{
                    server.META_CAPS: {"elicitation": {"form": {}}}})})
                self.assertEqual(result["resultType"], "input_required")
                result, _ = call("tools/call", {"name": "Ask", "_meta": asking})
                self.assertEqual(result["resultType"], "input_required")
                prompt = result["inputRequests"][server.ASK_KEY]
                self.assertEqual((prompt["method"], prompt["params"]["message"]), ("elicitation/create", "Send it?"))
                state = result["requestState"]
                yes = {server.ASK_KEY: {"action": "accept", "content": {}}}
                # A made-up state, the right one for another question, or for the same question in a
                # call with any other argument (one the prompt doesn't show), gets a new prompt, not a yes.
                for retry in ({"requestState": "made-up", "inputResponses": yes},
                              {"requestState": state, "inputResponses": yes, "arguments": {"extra": "x"}},
                              {"requestState": state, "inputResponses": yes, "arguments": {"q": "Other?"}}):
                    result, _ = call("tools/call", {"name": "Ask", "_meta": asking, **retry})
                    self.assertEqual(result["resultType"], "input_required")
                state = result["requestState"]
                result, _ = call("tools/call", {"name": "Ask", "_meta": asking, "arguments": {"q": "Other?"},
                                                "requestState": state, "inputResponses": yes})
                self.assertEqual((result["resultType"], result["content"][0]["text"]), ("complete", "approved"))
                result, _ = call("tools/call", {"name": "Ask", "_meta": asking, "arguments": {"q": "Other?"},
                                                "requestState": state, "inputResponses": yes})
                self.assertEqual(result["resultType"], "input_required")  # each answer is taken once
                result, _ = call("tools/call", {"name": "Ask", "_meta": asking, "requestState": result["requestState"],
                                                "arguments": {"q": "Other?"}, "inputResponses": {
                                                    server.ASK_KEY: {"action": "decline"}}})
                self.assertTrue(result["isError"])
                self.assertIn("declined", result["content"][0]["text"])

    def test_mcp_2026_07_28_over_stdio(self):
        # Neon N5: the whole exchange through server.py's own stdin and stdout, with no handshake:
        # discovery, the tools, an approval asked as input_required and declined, the capability error.
        plain = tempfile.mkdtemp(prefix="nouez-test-stdio-")
        self.addCleanup(shutil.rmtree, plain, True)
        new = os.path.join(plain, "fresh")
        proc = Server(env={**os.environ, "NOUEZ_NO_UPDATE_CHECK": "1", "NOUEZ_ASK_TRUST": "1"})
        self.addCleanup(proc.close)
        meta = {server.META_VERSION: "2026-07-28", server.META_CLIENT: {"name": "claude-code", "version": "2"},
                server.META_CAPS: {"elicitation": {"form": {}, "url": {}}}}
        result = proc.request("d", "server/discover", {"_meta": meta})["result"]
        self.assertEqual((result["resultType"], result["supportedVersions"][0]), ("complete", "2026-07-28"))
        result = proc.request("l", "tools/list", {"_meta": meta})["result"]
        self.assertIn("OpenClaudeSession", [t["name"] for t in result["tools"]])
        call = {"name": "OpenClaudeSession", "arguments": {"cwd": new, "create": True, "trust": True}, "_meta": meta}
        asked = proc.request("c1", "tools/call", call)["result"]
        self.assertEqual(asked["resultType"], "input_required")
        prompt = asked["inputRequests"][server.ASK_KEY]
        self.assertEqual(prompt["params"]["mode"], "form")
        self.assertEqual(prompt["params"]["requestedSchema"], {"type": "object", "properties": {}})
        self.assertFalse(os.path.exists(new))
        reply = proc.request("c2", "tools/call", {**call, "requestState": asked["requestState"],
                                                   "inputResponses": {server.ASK_KEY: {"action": "decline"}}})
        self.assertTrue(reply["result"]["isError"])
        self.assertIn("declined", reply["result"]["content"][0]["text"])
        self.assertFalse(os.path.exists(new))
        no_form = {**meta, server.META_CAPS: {"elicitation": {"url": {}}}}
        error = proc.request("c3", "tools/call", {**call, "_meta": no_form})["error"]
        self.assertEqual((error["code"], error["data"]), (-32021, {"requiredCapabilities": {"elicitation": {"form": {}}}}))
        self.assertFalse(os.path.exists(new))
        self.assertEqual(proc.request("p", "ping", {"_meta": meta})["error"]["code"], -32601)

    def test_instructions_consult_unasked_only_with_a_consultant_cli(self):
        # A clone with no CLAUDE.md or skill still gets reviews, bug hunts and critiques unasked;
        # without a consultant CLI, or with NOUEZ_NO_AUTO_CONSULT=1, that part is left out.
        for codex, agy, off, auto in ((True, None, "", True), (False, "agy", "", True), (False, None, "", False),
                                      (True, "agy", "1", False), (True, None, "0", True)):
            env = {"NOUEZ_NO_AUTO_CONSULT": off}  # set every time, so the caller's own value can't leak in
            with self.subTest(codex=codex, agy=agy, env=env), \
                    mock.patch.object(server, "codex_installed", lambda: codex), \
                    mock.patch.object(server, "agy_command", lambda env=None: agy), \
                    mock.patch.dict(os.environ, env):
                text = server.server_instructions()
                self.assertEqual(server.AUTO_CONSULT in text, auto)
                self.assertTrue(text.startswith(server.INSTRUCTIONS_HEAD))
                self.assertTrue(text.endswith(server.INSTRUCTIONS))
                self.assertIn("Consult whenever the user asks", text)
        self.assertIn("revision=true", server.AUTO_CONSULT)
        self.assertIn("own instructions say otherwise", server.AUTO_CONSULT)
        self.assertIn("ConsultantBudget", server.AUTO_CONSULT)
        self.assertIn("Skip one, saying so, when ConsultantBudget says none has room", server.AUTO_CONSULT)

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
        self.handshake()
        reply = self.server.request(3, "tools/call", {"name": "ListConsultants", "arguments": ["x"]})
        self.assertEqual(reply["error"]["code"], -32602)

    def test_unknown_tool(self):
        self.handshake()
        reply = self.server.request(4, "tools/call", {"name": "Nope", "arguments": {}})
        self.assertEqual(reply["error"]["code"], -32602)

    def test_unknown_method(self):
        self.handshake()
        self.assertEqual(self.server.request(5, "nope/nope")["error"]["code"], -32601)

    def test_negative_wait_is_a_tool_error(self):
        self.handshake()
        reply = self.server.request(6, "tools/call", {"name": "SendConsultantMessage", "arguments": {
            "to": "x", "message": "hi", "wait": -5}})
        self.assertTrue(reply["result"]["isError"])
        self.assertIn("0 or more", reply["result"]["content"][0]["text"])

    def test_wait_schema_takes_seconds_or_done(self):
        self.handshake()
        tools = {t["name"]: t for t in self.server.request(11, "tools/list")["result"]["tools"]}
        for name in ("SendConsultantMessage", "GetConsultantReply"):
            props = tools[name]["inputSchema"]["properties"]
            self.assertEqual([s["type"] for s in props["wait"]["anyOf"]], ["number", "string"])
            self.assertFalse({"until_done", "timeout_seconds"} & set(props))

    def test_tools_list_schemas_are_objects(self):
        self.handshake()
        tools = self.server.request(7, "tools/list")["result"]["tools"]
        self.assertEqual({t["name"] for t in tools}, set(server.HANDLERS))
        for tool in tools:
            self.assertEqual(tool["inputSchema"]["type"], "object")

    def test_annotations(self):
        self.handshake()
        tools = {t["name"]: t["annotations"] for t in self.server.request(8, "tools/list")["result"]["tools"]}
        read_only = {name for name, a in tools.items() if a.get("readOnlyHint")}
        self.assertEqual(read_only, {"ListConsultants", "GetConsultantReply", "GetConsultantHistory", "ListClaudeSessions",
                                     "ListProjects", "ConsultantBudget"})
        destructive = {name for name, a in tools.items() if a.get("destructiveHint")}
        self.assertEqual(destructive, {"StopConsultant", "CloseClaudeSession"})

    def test_null_id_is_invalid_request(self):
        self.server.send({"jsonrpc": "2.0", "id": None, "method": "ping"})
        reply = self.server.recv()
        self.assertEqual(reply["error"]["code"], -32600)
        self.assertIsNone(reply["id"])
        self.assert_alive()

    def test_empty_array_params_are_invalid(self):
        self.handshake()
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
        root = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, root, True)
        with mock.patch.object(server, "nouez_cache_dir", lambda: root):
            out = server.format_turn("codex-x", turn)
        self.assertIn("[Truncated: 123 more characters.", out)
        path = os.path.join(root, "replies", "reply-turn-test-truncate.md")  # 0.18.0: not in the shared temp folder
        self.assertIn(path, out)
        with open(path, encoding="utf-8") as f:
            self.assertEqual(f.read(), text)
        if os.name != "nt":
            self.assertEqual(os.stat(path).st_mode & 0o777, 0o600)

    def test_old_reply_files_are_pruned(self):
        root = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, root, True)
        folder = os.path.join(root, "replies")
        os.makedirs(folder)
        old, new = os.path.join(folder, "reply-old.md"), os.path.join(folder, "reply-new.md")
        # 0.18.0: names nouez doesn't give (an ordinary notes.md too) are kept, however old
        mine, notes = os.path.join(folder, "notes.txt"), os.path.join(folder, "notes.md")
        for f in (old, new, mine, notes):
            open(f, "w").close()
        for f in (old, mine, notes):
            os.utime(f, (time.time() - 30 * 86400,) * 2)
        with mock.patch.object(server, "nouez_cache_dir", lambda: root):
            server.cap_reply("turn-x", "a" * 50, 10)
        self.assertEqual(sorted(os.listdir(folder)), ["notes.md", "notes.txt", "reply-new.md", "reply-turn-x.md"])

    def test_reply_folder_junction_is_not_followed(self):
        """0.18.0: a junction or other reparse point (which islink doesn't see on Windows) counts as a link."""
        root = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, root, True)
        os.makedirs(os.path.join(root, "replies"))
        real_lstat = os.lstat
        def lstat(p, *a, **k):
            st = real_lstat(p, *a, **k)
            if os.path.basename(p) != "replies":
                return st
            return mock.Mock(st_mode=st.st_mode, st_file_attributes=0x400)
        with mock.patch.object(server, "nouez_cache_dir", lambda: root), mock.patch.object(server.os, "lstat", lstat):
            self.assertFalse(server.plain_folder(os.path.join(root, "replies")))
            out = server.cap_reply("turn-j", "a" * 50, 10)
        self.assertIn("could not be saved", out)
        self.assertEqual(os.listdir(os.path.join(root, "replies")), [])

    @unittest.skipIf(os.name == "nt", "symlinks need privileges on Windows")
    def test_reply_folder_link_is_not_followed(self):
        """0.18.0: a replies folder that is a link is neither written nor pruned."""
        root, elsewhere = tempfile.mkdtemp(), tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, root, True)
        self.addCleanup(shutil.rmtree, elsewhere, True)
        victim = os.path.join(elsewhere, "reply-old.md")
        open(victim, "w").close()
        os.utime(victim, (time.time() - 30 * 86400,) * 2)
        os.symlink(elsewhere, os.path.join(root, "replies"))
        with mock.patch.object(server, "nouez_cache_dir", lambda: root):
            out = server.cap_reply("turn-y", "a" * 50, 10)
        self.assertIn("could not be saved", out)
        self.assertEqual(os.listdir(elsewhere), ["reply-old.md"])

    def test_cache_dir_is_absolute_and_private(self):
        home = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, home, True)
        var = "LOCALAPPDATA" if os.name == "nt" else "XDG_CACHE_HOME"
        with mock.patch.dict(os.environ, {var: "relative/cache", "HOME": home, "USERPROFILE": home}):
            root = server.nouez_cache_dir()
        self.assertTrue(os.path.isabs(root), root)
        self.assertNotIn("relative", root)
        if os.name != "nt":
            self.assertEqual(os.stat(root).st_mode & 0o777, 0o700)

    @unittest.skipIf(os.name == "nt", "POSIX ownership")
    def test_cache_dir_of_another_user_is_not_used(self):
        """0.18.0: a nouez folder someone else owns is never written to; a private one replaces it."""
        home = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, home, True)
        real_open, real_fstat, theirs = os.open, os.fstat, set()
        def fake_open(path, *a, **k):
            fd = real_open(path, *a, **k)
            # a closed fd's number is given out again, so each open says whose folder it is
            (theirs.add if os.path.basename(path) == "nouez" else theirs.discard)(fd)
            return fd
        def fstat(fd):
            st = real_fstat(fd)
            if fd not in theirs:
                return st
            return os.stat_result((st.st_mode, st.st_ino, st.st_dev, st.st_nlink, os.getuid() + 1, *st[5:]))
        tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, tmp, True)
        with mock.patch.dict(os.environ, {"XDG_CACHE_HOME": home}), mock.patch.object(server, "_private_roots", {}), \
                mock.patch.object(server.os, "open", fake_open), mock.patch.object(server.os, "fstat", fstat), \
                mock.patch.object(server.tempfile, "gettempdir", lambda: tmp), \
                contextlib.redirect_stderr(io.StringIO()) as err:
            root = server.nouez_cache_dir()
        # One fallback for every process of this user, so the status line, top and waiters agree.
        self.assertEqual(root, os.path.join(tmp, f"nouez-{os.getuid()}"))
        self.assertEqual(os.stat(root).st_mode & 0o777, 0o700)
        self.assertIn("isn't a folder of yours", err.getvalue())

    @unittest.skipIf(os.name == "nt", "symlinks need privileges on Windows")
    def test_cache_dir_that_is_a_link_is_not_used(self):
        """0.18.0: a link of the user's own to a folder of theirs is refused too, and its target left as it was."""
        home, target, tmp = tempfile.mkdtemp(), tempfile.mkdtemp(), tempfile.mkdtemp()
        for d in (home, target, tmp):
            self.addCleanup(shutil.rmtree, d, True)
        os.chmod(target, 0o755)
        os.symlink(target, os.path.join(home, "nouez"))
        with mock.patch.dict(os.environ, {"XDG_CACHE_HOME": home}), mock.patch.object(server, "_private_roots", {}), \
                mock.patch.object(server.tempfile, "gettempdir", lambda: tmp), contextlib.redirect_stderr(io.StringIO()) as err:
            root = server.nouez_cache_dir()
        self.assertEqual(root, os.path.join(tmp, f"nouez-{os.getuid()}"))
        self.assertEqual(os.stat(target).st_mode & 0o777, 0o755)
        self.assertIn("isn't a folder of yours", err.getvalue())

    @unittest.skipIf(os.name == "nt", "POSIX permissions")
    def test_cache_dir_in_a_folder_others_can_change_is_not_used(self):
        """0.18.0: another user could swap the folder later, so it isn't used."""
        home, tmp = tempfile.mkdtemp(), tempfile.mkdtemp()
        for d in (home, tmp):
            self.addCleanup(shutil.rmtree, d, True)
        os.chmod(home, 0o777)
        with mock.patch.dict(os.environ, {"XDG_CACHE_HOME": home}), mock.patch.object(server, "_private_roots", {}), \
                mock.patch.object(server.tempfile, "gettempdir", lambda: tmp), contextlib.redirect_stderr(io.StringIO()) as err:
            root = server.nouez_cache_dir()
        self.assertEqual(root, os.path.join(tmp, f"nouez-{os.getuid()}"))
        self.assertIn("other users can change", err.getvalue())

    def test_drive_less_paths_are_not_absolute(self):
        """0.18.0: on Windows `\\tools` is on the current drive, so it isn't taken as absolute."""
        with mock.patch.object(server.os, "name", "nt"), mock.patch.object(server.os, "path", ntpath):
            self.assertFalse(server.rooted("\\tools"))
            self.assertFalse(server.rooted("tools"))
            self.assertTrue(server.rooted("C:\\tools"))
            self.assertTrue(server.rooted("\\\\server\\share\\tools"))
            self.assertIsNone(server.find_program("agy", "\\tools"))

    def test_short_reply_is_untouched(self):
        self.assertEqual(server.cap_reply("t", "short"), "short")


class DaemonStartTest(unittest.TestCase):
    def connect(self, failures):
        """A CodexClient whose first `failures` connections find no daemon (None: none ever does);
        returns start_daemon's mock."""
        attempts = (iter(lambda: server.DaemonDown("down"), None) if failures is None
                    else iter([server.DaemonDown("down")] * failures))

        def fake_connect(client, exe):
            client.proc = mock.Mock()
            for error in attempts:
                raise error

        patches = (mock.patch.object(server, "which", return_value="codex"),
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
        # Never up, not a large count: Windows' clock moves in ~15 ms steps, so a fast machine
        # could use up any count before the deadline passes and then connect.
        start = self.connect(None)
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
             mock.patch.object(server, "_nouez_noted", None), \
             mock.patch.object(server, "SERVER_VERSION", current):
            return server.nouez_update_notice(), server.nouez_update_notice()

    def test_each_newer_release_is_told_once(self):
        """0.24.0: a server that runs for days tells about a later release too, not only the first."""
        with mock.patch.object(server, "_nouez_latest", "0.10.0"), \
             mock.patch.object(server, "_nouez_noted", None), \
             mock.patch.object(server, "SERVER_VERSION", "0.9.0"):
            self.assertIn("nouez 0.10.0 is out", server.nouez_update_notice())
            self.assertEqual(server.nouez_update_notice(), "")
            server._nouez_latest = "0.11.0"
            self.assertIn("nouez 0.11.0 is out", server.nouez_update_notice())
            self.assertEqual(server.nouez_update_notice(), "")

    def test_the_dispatcher_says_how_to_update_at_the_computer(self):
        """0.24.0: in the phone dispatcher the notice says the update takes the computer and a new
        `dispatcher install`, which ends its chats; nothing is run from the phone. The mark is
        set only for the dispatcher's claude, never for a session it opens."""
        with mock.patch.dict(os.environ, {"NOUEZ_DISPATCHER": "1"}):
            first, second = self.notice("0.10.0")
        self.assertIn("this dispatcher runs 0.9.0", first)
        self.assertIn("dispatcher install", first)
        self.assertIn("don't run anything for it here", first)
        self.assertNotIn("/mcp", first)
        self.assertEqual(second, "")
        env = server.dispatcher_env(sys.executable, None, {"PATH": "", "NOUEZ_DISPATCHER": "0"})
        self.assertTrue(server.in_dispatcher(env))
        self.assertNotIn("NOUEZ_DISPATCHER", server.fresh_claude_env(env))
        self.assertFalse(server.in_dispatcher({}))

    def test_the_dispatchers_tools_carry_the_notice(self):
        """0.24.0: in the dispatcher, its tools' results carry the notice, and each call may look for
        a release again (an hour apart at most); elsewhere, and for other tools, nothing changes."""
        sent, calls = [], []
        tools = {"ListProjects": lambda args, cancel, progress: "listed",
                 "GetConsultantReply": lambda args, cancel, progress: "reply"}

        def call(name):
            server.handle({"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                           "params": {"name": name, "arguments": {}}}, threading.Event())
            return sent.pop()["content"][0]["text"]

        with mock.patch.dict(server.HANDLERS, tools), \
             mock.patch.object(server, "respond", lambda msg_id, result=None, error=None: sent.append(result)), \
             mock.patch.object(server, "start_release_check", lambda again_after=None: calls.append(again_after)), \
             mock.patch.object(server, "_nouez_latest", "0.10.0"), \
             mock.patch.object(server, "_nouez_noted", None), \
             mock.patch.object(server, "SERVER_VERSION", "0.9.0"):
            with mock.patch.dict(os.environ, {"NOUEZ_DISPATCHER": ""}):
                self.assertEqual(call("ListProjects"), "listed")
            with mock.patch.dict(os.environ, {"NOUEZ_DISPATCHER": "1"}):
                self.assertEqual(call("GetConsultantReply"), "reply")
                self.assertEqual(calls, [])
                text = call("ListProjects")
                self.assertTrue(text.startswith("listed\n\nnouez 0.10.0 is out"), text)
                self.assertEqual(call("ListProjects"), "listed")
                self.assertEqual(calls, [3600, 3600])
                server._nouez_latest = "0.11.0"  # a call cancelled meanwhile leaves the notice for the next
                cancelled = threading.Event()
                server.HANDLERS["ListProjects"] = lambda args, cancel, progress: cancelled.set() or "listed"
                server.handle({"jsonrpc": "2.0", "id": 2, "method": "tools/call",
                               "params": {"name": "ListProjects", "arguments": {}}}, cancelled)
                self.assertEqual(sent, [])

                def fails(args, cancel, progress):  # as a StartConsultant that read the notice, then failed
                    server.safe_nouez_update_notice()
                    raise server.BridgeError("no daemon")
                server.HANDLERS["GetConsultantReply"] = fails
                self.assertEqual(call("GetConsultantReply"), "no daemon")
                server.HANDLERS["ListProjects"] = lambda args, cancel, progress: "listed"
                self.assertIn("nouez 0.11.0 is out", call("ListProjects"))

    def test_a_long_running_server_looks_again_hourly(self):
        clock = [1000.0]
        with mock.patch.dict(os.environ, {"NOUEZ_NO_UPDATE_CHECK": ""}), \
             mock.patch.object(server, "_release_check", {"running": False, "started": None}), \
             mock.patch.object(server.time, "monotonic", lambda: clock[0]), \
             mock.patch.object(server.threading, "Thread") as thread:
            server.start_release_check()
            server.start_release_check(again_after=3600)  # one already running
            self.assertEqual(thread.call_count, 1)
            server._release_check["running"] = False
            clock[0] += 100
            server.start_release_check(again_after=3600)
            self.assertEqual(thread.call_count, 1)
            clock[0] += 3600
            server.start_release_check(again_after=3600)
            self.assertEqual(thread.call_count, 2)

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

    def test_a_linked_cache_is_not_read(self):
        """0.26.1: the release cache is read like nouez's other cache files, never through a link."""
        os.makedirs(os.path.dirname(self.cache))
        elsewhere = os.path.join(os.path.dirname(self.cache), "elsewhere.json")
        with open(elsewhere, "w", encoding="utf-8") as f:
            json.dump({"checked": 1000, "latest": "0.9.1"}, f)
        self.assertEqual(server.read_release_cache(elsewhere, 1000), (True, "0.9.1"))
        with open(elsewhere, "w", encoding="utf-8") as f:  # a valid object padded past the limit
            f.write(json.dumps({"checked": 1000, "latest": "0.9.1"}).ljust(server.RELEASE_CACHE_BYTES) + "junk")
        self.assertEqual(server.read_release_cache(elsewhere, 1000), (False, None))
        self.assertIsNone(server.read_json_file(elsewhere, server.RELEASE_CACHE_BYTES))
        file_link(self, elsewhere, self.cache)
        self.assertEqual(server.read_release_cache(self.cache, 1000), (False, None))

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
            opener = mock.MagicMock()
            opener.open.return_value = resp
            return opener
        with mock.patch.object(server, "web_opener", return_value=answer({"tag_name": "v1.2.3"})) as op:
            self.assertEqual(server.fetch_latest_release(), "1.2.3")
        req = op.return_value.open.call_args[0][0]
        self.assertEqual(req.full_url, server.RELEASES_URL)
        self.assertTrue(req.get_header("User-agent").startswith("nouez/"))
        self.assertEqual(sorted(k.lower() for k in req.headers), ["accept", "user-agent"])  # nothing else is sent
        for body in ({"tag_name": "v1.2.3`; echo"}, {"tag_name": None}, ["v1.2.3"], {"tag_name": "1.2.3"},
                     {"tag_name": "v1.2.%s" % ("3" * 50)}):
            with mock.patch.object(server, "web_opener", return_value=answer(body)):
                self.assertIsNone(server.fetch_latest_release())

    def test_redirect_to_another_site_is_refused(self):
        """0.22.0: a redirect to another host or port is refused, so a key header never goes there."""
        import http.server
        got = []

        class Other(http.server.BaseHTTPRequestHandler):
            def do_GET(self):
                got.append(dict(self.headers))
                self.send_response(200)
                self.end_headers()
                self.wfile.write(b"{}")

            def log_message(self, *a):
                pass

        other = http.server.HTTPServer(("127.0.0.1", 0), Other)
        target = f"http://127.0.0.1:{other.server_address[1]}/stolen"

        class First(Other):
            def do_GET(self):
                if self.path.startswith("/same"):
                    return Other.do_GET(self)
                self.send_response(302)
                self.send_header("Location", "/same" if self.path.startswith("/here") else target)
                self.end_headers()

        first = http.server.HTTPServer(("127.0.0.1", 0), First)
        for srv in (other, first):
            threading.Thread(target=srv.serve_forever, daemon=True).start()
        try:
            base = f"http://127.0.0.1:{first.server_address[1]}"
            with mock.patch.object(server, "RELEASES_URL", base + "/away"), \
                 mock.patch.object(server, "AA_MODELS_URL", base + "/here"):
                with self.assertRaises(urllib.error.HTTPError):
                    server.fetch_json(base + "/away", {"x-api-key": "k-secret"}, 5, 1000)
                self.assertEqual(got, [])  # the other server never heard from nouez
                self.assertEqual(server.fetch_json(base + "/here?page=1", {"x-api-key": "k-secret"}, 5, 1000), {})
                self.assertEqual(len(got), 1)  # a redirect on the same site is followed
                with self.assertRaisesRegex(OSError, "no web request"):  # any other address: never asked
                    server.fetch_json(target, {"x-api-key": "k-secret"}, 5, 1000)
                self.assertEqual(len(got), 1)
        finally:
            for srv in (other, first):
                srv.shutdown()
                srv.server_close()

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
        server._trust_reports.clear()
        self.addCleanup(server._trust_reports.clear)
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
        self.assertFalse(opened)  # 0.19.0: the folder's report comes first
        self.assertIn("Not trusted yet", out)
        self.assertEqual(self.backups(), [])
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

    def test_backups_never_go_through_a_link(self):
        """0.22.0: a linked backup folder isn't written through, and then nothing is changed."""
        outside = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, outside, True)
        folder = server.trust_backup_dir()
        os.makedirs(os.path.dirname(folder))
        dir_link(outside, folder)
        with open(self.state, encoding="utf-8") as f:
            before = f.read()
        with self.assertRaisesRegex(server.BridgeError, "Nothing was changed"):
            server.trust_folder(self.plain)
        self.assertEqual(os.listdir(outside), [])
        with open(self.state, encoding="utf-8") as f:
            self.assertEqual(f.read(), before)

    def test_doctor_says_where_the_copies_are_and_how_to_put_one_back(self):
        """0.28.0: doctor lists nouez's copies of Claude Code's state file; links aren't counted."""
        self.assertIsNone(server.trust_backups_report())
        server.trust_folder(self.plain)
        server.trust_folder(self.repo)
        outside = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, outside, True)
        dir_link(outside, os.path.join(server.trust_backup_dir(), ".claude.json.19990101-000000.x.bak"))
        text = server.trust_backups_report()
        self.assertTrue(text.startswith("2 copies of this profile's state file"), text)
        self.assertIn(server.trust_backup_dir(), text)
        self.assertIn("close every Claude Code window, then copy it over " + server.claude_state_file() + ".", text)
        self.assertIn("undoes everything Claude Code saved there since", text)
        self.assertNotIn("other cop", text)
        # Codex 0.28 review, round 2: a copy of another profile's file, or one from before 0.28.0 (no
        # tag), is only counted, never offered for putting back over this profile's.
        with open(os.path.join(server.trust_backup_dir(), ".claude.json.20200101-000000.abc.bak"), "w") as f:
            f.write("{}")
        self.assertIn("2 copies of this profile's state file", server.trust_backups_report())
        self.assertIn(" 1 other copy is of another Claude Code profile's state file, or from before 0.28.0",
                      server.trust_backups_report())
        with mock.patch.dict(server.os.environ, {"CLAUDE_CONFIG_DIR": os.path.join(outside, "work")}):
            text = server.trust_backups_report()
        self.assertTrue(text.startswith("nouez has no copy of this profile's state file"), text)
        self.assertIn("3 other copies are of another", text)
        self.assertNotIn("To put one back", text)

    def test_a_linked_backup_is_neither_counted_nor_removed(self):
        """0.22.0: only nouez's own backup files are trimmed."""
        server.trust_folder(self.plain)
        folder = server.trust_backup_dir()
        outside = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, outside, True)
        link = os.path.join(folder, ".claude.json.19990101-000000.x.bak")
        dir_link(outside, link)
        with mock.patch.object(server, "TRUST_BACKUPS_KEPT", 1):
            server.trust_folder(self.repo)
        self.assertTrue(server.is_link(link))
        self.assertEqual(len([b for b in self.backups() if not server.is_link(os.path.join(folder, b))]), 1)

    def test_trust_written_as_a_link_moves_in_is_taken_back(self):
        """0.26.1: in the dispatcher, the folder is checked again right after the trust is written; if a
        link has taken its place meanwhile, the record is set back to false and the call refused."""
        outside = os.path.join(self.tmp, "outside")
        os.mkdir(outside)
        real = server.trust_folder

        def swap_after(path, expect=None):
            done = real(path, expect=expect)
            os.rename(self.repo, os.path.join(self.projects, "moved"))
            dir_link(outside, self.repo)
            return done
        with mock.patch.dict(server.os.environ, {"NOUEZ_DISPATCHER": "1", "NOUEZ_DISPATCHER_PROJECTS": self.projects}):
            self.open({"cwd": self.repo})  # the report, then the yes
            with mock.patch.object(server, "trust_folder", swap_after),                     self.assertRaisesRegex(server.BridgeError, "taken back.*backed up in"):
                self.open({"cwd": self.repo, "trust": True})
        data = self.read()
        self.assertIs(data["projects"][self.slash(self.repo)]["hasTrustDialogAccepted"], False)
        self.assertFalse(server.exactly_trusted(self.repo))
        self.assertEqual((data["numStartups"], data["é"], data["projects"]["other"]), (3, "ü", {"allowedTools": ["x"]}))

    def test_the_user_can_turn_trust_writing_off(self):
        """0.22.0: with NOUEZ_NO_TRUST_WRITE=1, nouez never records trust, asked or not."""
        for value, off in (("", False), ("0", False), ("no", False), ("1", True), ("yes", True)):
            self.assertEqual(server.trust_write_off({"NOUEZ_NO_TRUST_WRITE": value}), off)
        with open(self.state, encoding="utf-8") as f:
            before = f.read()
        with mock.patch.dict(server.os.environ, {"NOUEZ_NO_TRUST_WRITE": "1"}):
            out, opened = self.open({"cwd": self.repo})
            self.assertFalse(opened)
            self.assertIn("NOUEZ_NO_TRUST_WRITE=1", out)  # Claude isn't told to ask for a yes it can't use
            for _ in range(2):  # the second call, after the report, is refused too
                with self.assertRaisesRegex(server.BridgeError, "NOUEZ_NO_TRUST_WRITE=1"):
                    self.open({"cwd": self.repo, "trust": True})
            with self.assertRaisesRegex(server.BridgeError, "NOUEZ_NO_TRUST_WRITE=1"):
                server.trust_folder(self.repo)
            new = os.path.join(os.path.dirname(self.repo), "made-for-nothing")
            with self.assertRaisesRegex(server.BridgeError, "NOUEZ_NO_TRUST_WRITE=1"):
                self.open({"cwd": new, "create": True, "trust": True})
            self.assertFalse(os.path.exists(new))  # refused before the folder was made
        with open(self.state, encoding="utf-8") as f:
            self.assertEqual(f.read(), before)
        self.assertEqual(self.backups(), [])

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
        made = os.path.join(wt, "new")  # 0.26.1: refused before create=true makes the folder
        with self.assertRaisesRegex(server.BridgeError, "git layout is unusual"):
            self.open({"cwd": made, "create": True, "trust": True})
        self.assertFalse(os.path.exists(made))
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

    def unchanged(self):
        with open(self.state, encoding="utf-8") as f:
            return f.read()

    def test_several_spellings_of_one_folder_are_refused(self):
        """0.26.3: two entries for one folder (here with and without a trailing slash): nouez can't
        tell which one Claude Code reads, so it records neither and changes nothing."""
        data = self.read()
        data["projects"][self.slash(self.repo)] = {"allowedTools": []}
        data["projects"][self.slash(self.repo) + "/"] = {}
        self.write(data)
        before = self.unchanged()
        with self.assertRaisesRegex(server.BridgeError, "2 entries.*Nothing was changed"):
            server.trust_folder(self.repo)
        self.assertEqual(self.unchanged(), before)
        self.assertEqual(self.backups(), [])

    def test_an_entry_for_another_folder_on_disk_is_neither_reused_nor_trust(self):
        """0.26.3: an entry that reads the same but is another folder on disk (on Windows, a
        case-sensitive folder's `repo` beside its `REPO`) doesn't count as trust and isn't the one written."""
        lookalike = self.slash(self.repo) + "/"
        data = self.read()
        data["projects"][lookalike] = {"hasTrustDialogAccepted": True}
        self.write(data)
        real = server._same_entry
        with mock.patch.object(server, "_same_entry", lambda name, key: name != lookalike and real(name, key)), \
                mock.patch.object(server.time, "sleep"):
            name, backup = server.trust_folder(self.repo)
        self.assertEqual(name, self.slash(self.repo))
        self.assertIsNotNone(backup)
        with mock.patch.object(server, "_same_entry", lambda name, key: name != lookalike and real(name, key)):
            data = self.read()
            del data["projects"][name]
            self.write(data)
            self.assertFalse(server.exactly_trusted(self.repo))  # nor does the reading side take it for trust
            self.assertFalse(server.folder_trusted(self.repo))
            data["projects"][lookalike.rstrip("/") + "/plain/"] = {"hasTrustDialogAccepted": True}
            self.write(data)
            self.assertTrue(server.folder_trusted(self.plain))  # through the trusted Projects above
            data["projects"] = {lookalike: {"hasTrustDialogAccepted": True}}
            self.write(data)
            self.assertFalse(server.folder_trusted(os.path.join(self.repo, "src")))
        data["projects"][name] = {"hasTrustDialogAccepted": True}
        self.write(data)
        projects = self.read()["projects"]
        self.assertEqual((projects[name], projects[lookalike]),
                         ({"hasTrustDialogAccepted": True}, {"hasTrustDialogAccepted": True}))

    def test_trust_another_session_records_meanwhile_isnt_taken_for_nouezs(self):
        """0.26.3: if a Claude Code session records the same trust while nouez writes, nouez returns
        no backup (its own write isn't the one in effect), so nothing it does next takes that trust back."""
        real = server.backup_claude_state

        def and_a_session_writes(text, state):
            done = real(text, state)
            data = self.read()
            data["projects"][self.slash(self.repo)] = {"hasTrustDialogAccepted": True}
            self.write(data)
            return done
        with mock.patch.object(server, "backup_claude_state", and_a_session_writes):
            self.assertEqual(server.trust_folder(self.repo), (self.slash(self.repo), None))
        self.assertTrue(server.exactly_trusted(self.repo))

    def test_taking_trust_back_touches_only_the_entry_nouez_wrote(self):
        """0.26.3: the take-back sets false only on the entry named exactly as nouez wrote it; trust
        recorded under another spelling stays."""
        data = self.read()
        data["projects"][self.slash(self.repo) + "/"] = {"hasTrustDialogAccepted": True}
        self.write(data)
        before = self.unchanged()
        self.assertEqual(server._record_trust(self.slash(self.repo), False), (self.slash(self.repo), None))
        self.assertEqual(self.unchanged(), before)
        self.assertEqual(self.backups(), [])

    def test_a_write_that_cant_be_read_back_says_so(self):
        """0.26.3: once written, the entry itself is read back; if it can't be, nouez says so and names
        the backup, rather than taking the trust as recorded or retrying over it."""
        with mock.patch.object(server, "recorded_trust", return_value=None), mock.patch.object(server.time, "sleep"):
            with self.assertRaisesRegex(server.BridgeError, "couldn't read it back.*backed up in"):
                server.trust_folder(self.repo)
        self.assertEqual(len(self.backups()), 1)

    def test_trust_that_cant_be_read_is_unknown(self):
        """0.26.3: an unreadable state file is neither trust nor its absence: trust=true is refused at
        once, with no report asking the user for a yes nouez couldn't act on, and nothing changed."""
        with open(self.state, "a", encoding="utf-8") as f:
            f.write("garbage")
        before = self.unchanged()
        with mock.patch.dict(server.os.environ, {"NOUEZ_ASK_TRUST": "1"}), \
                mock.patch.object(server, "user_approves") as approves:
            for _ in range(2):
                with self.assertRaisesRegex(server.BridgeError, "couldn't read Claude Code's state file"):
                    self.open({"cwd": self.repo, "trust": True})
            new = os.path.join(self.projects, "brand-new")
            with self.assertRaisesRegex(server.BridgeError, "couldn't read Claude Code's state file"):
                self.open({"cwd": new, "create": True, "trust": True})
        approves.assert_not_called()
        self.assertFalse(os.path.exists(new))  # nothing made, nothing asked
        os.remove(self.state)  # a missing file records no trust: the report comes, as before
        out, opened = self.open({"cwd": self.repo, "trust": True})
        self.assertIn("Not trusted yet", out)
        self.assertFalse(opened)
        with open(self.state, "w", encoding="utf-8") as f:
            f.write(before)
        self.assertEqual(self.unchanged(), before)
        self.assertEqual(self.backups(), [])
        self.assertIsNone(server.exactly_trusted(self.projects))
        self.assertIsNone(server.recorded_trust(self.slash(self.projects)))
        self.write({"projects": {self.slash(self.repo) + "/": {"hasTrustDialogAccepted": True}}})
        self.assertTrue(server.exactly_trusted(self.repo))
        self.assertFalse(server.recorded_trust(self.slash(self.repo)))  # that one entry only

    def test_a_projects_folder_holding_what_nouez_protects_is_refused(self):
        """0.26.3: the dispatcher's projects folder can't be a drive's root, or be or hold the home
        folder, Claude Code's settings folder or nouez's cache, also through a link."""
        home = os.path.join(self.tmp, "home")
        os.mkdir(home)
        os.makedirs(self.data_home, exist_ok=True)
        env = {"HOME": home, "USERPROFILE": home, "XDG_CACHE_HOME": self.data_home}
        with mock.patch.dict(server.os.environ, env):
            problem = server.projects_folder_problem
            self.assertIn("drive's root", problem(os.path.abspath(os.sep)))
            for folder, says in ((self.tmp, "your home folder"), (home, "your home folder"),
                                 (self.config, "Claude Code's settings folder"),
                                 (self.data_home, "nouez's cache folder")):
                with self.subTest(folder=folder):
                    self.assertIn(says, problem(folder))
            for folder in (self.projects, os.path.join(home, "Projects"), os.path.join(self.data_home, "other")):
                self.assertIsNone(problem(folder))
            link = os.path.join(self.projects, "to-home")
            dir_link(home, link)
            self.assertIn("your home folder", problem(link))
            real_config = os.path.join(self.projects, "private", "config")
            os.makedirs(real_config)
            linked_config = os.path.join(self.tmp, "linked-config")
            dir_link(real_config, linked_config)
            with mock.patch.object(server, "claude_config_dir", lambda: linked_config):
                self.assertIn("Claude Code's settings folder", problem(self.projects))  # where it really is
            fallback = os.path.join(self.projects, "nouez-fallback")
            os.makedirs(fallback)
            with mock.patch.object(server.tempfile, "gettempdir", lambda: fallback),                     mock.patch.object(server, "nouez_cache_dir", side_effect=AssertionError("makes the folder")):
                self.assertIn("the temporary folder nouez's cache can fall back to", problem(self.projects))
            os.rmdir(linked_config) if os.name == "nt" else os.unlink(linked_config)
            self.assertIn("records no trust at all", server.dispatcher_trust_problem(
                self.repo, {"NOUEZ_DISPATCHER": "1", "NOUEZ_DISPATCHER_PROJECTS": self.tmp}))
            os.rmdir(link) if os.name == "nt" else os.unlink(link)

    def test_a_new_folder_is_checked_again_just_before_it_is_made(self):
        """0.26.3: in the dispatcher, create=true with trust checks where the folder would go again
        right before making it, as the folders stand after the user's prompt: a link put in meanwhile
        is refused and nothing is made through it."""
        outside = os.path.join(self.tmp, "outside")
        os.mkdir(outside)
        parent = os.path.join(self.projects, "swap")
        os.mkdir(parent)
        new = os.path.join(parent, "new")

        def approve_and_swap(*args, **kwargs):
            os.rename(parent, os.path.join(self.projects, "moved"))
            dir_link(outside, parent)
        with mock.patch.dict(server.os.environ, {"NOUEZ_DISPATCHER": "1", "NOUEZ_DISPATCHER_PROJECTS": self.projects,
                                                 "NOUEZ_ASK_TRUST": "1"}), \
                mock.patch.object(server, "user_approves", approve_and_swap):
            with self.assertRaisesRegex(server.BridgeError, "phone dispatcher"):
                self.open({"cwd": new, "create": True, "trust": True})
        self.assertEqual(os.listdir(outside), [])
        os.rmdir(parent) if os.name == "nt" else os.unlink(parent)

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
        # 0.19.0: trusted only through a folder above it, with settings of its own: asked first,
        # with the report, rather than opened to wait at the trust question.
        out, opened = self.open({"cwd": self.plain})
        self.assertFalse(opened)
        self.assertIn("trusted only through a folder above it", out)
        self.assertIn("nothing that runs or allows anything", out)
        out, opened = self.open({"cwd": self.plain, "open_untrusted": True})
        self.assertTrue(opened)
        self.assertIn(".claude/settings.json may bring the trust question back", out)
        self.assertIn(".mcp.json servers are approved separately", out)
        # trust=true after the report records it and opens one window.
        out, opened = self.open({"cwd": self.plain, "trust": True})
        self.assertTrue(opened)
        self.assertIn("Recorded the user's trust", out)
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

    def test_every_wait_that_ends_early_says_the_turn_runs_on(self):
        """0.26.1: GetConsultantReply on a running turn, with or without the waiter, and the waiter
        out of time, say the turn is still working and isn't a reply (the sends' timeouts and the
        waiters' stalls have their own tests)."""
        turn = {"id": "t1", "status": "inProgress", "items": [user("q")]}
        for waiter in (True, False):
            with self.subTest(waiter=waiter), mock.patch.object(server, "background_waiter", lambda: waiter):
                self.assertIn("still working on turn t1; this is not a reply",
                              server.still_working_reply("c", "0199aaaa-0000-0000-0000-000000000001", turn))
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            server.print_unfinished("c", "0199aaaa-0000-0000-0000-000000000001", "t1", turn,
                                    types.SimpleNamespace(stalled=False, limit=600))
        self.assertIn("still working on turn t1; this is not a reply", buf.getvalue())
        self.assertIn("To keep waiting", buf.getvalue())


class FakeDaemon:
    """A daemon with threads and turns, for the tool handlers. Pass it as CodexClient."""

    def __init__(self, threads, turns=None, fail_after_start=False, answer=None):
        self.threads = {t["id"]: t for t in threads}
        self.answer = answer  # if set, a started turn completes at once with this reply
        self.turns = turns or {}  # thread id -> turns, newest first
        self.fail_after_start = fail_after_start
        self.calls = []
        self.info = {}

    def __call__(self, on_spawn=None):  # as CodexClient(): a ConsultationFeed passes on_spawn
        return self

    def close(self):
        pass

    def request(self, method, params):
        self.calls.append(method)
        if method == "thread/loaded/list":
            return {"data": list(self.threads)}
        if method == "thread/read":
            if params["threadId"] not in self.threads:
                raise server.BridgeError(f"thread not found: {params['threadId']}")
            return {"thread": dict(self.threads[params["threadId"]])}
        if method == "thread/list":
            return {"data": []}
        if method == "thread/start":
            self.thread_started = params
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
        if method == "turn/interrupt":
            for turn in self.turns.get(params["threadId"], []):
                if turn["id"] == params["turnId"]:
                    turn["status"] = "interrupted"
            return {}
        if method == "thread/archive":
            self.archived = params["threadId"]
            return {}
        raise AssertionError(method)


class HandlerTest(unittest.TestCase):
    def use(self, daemon):
        for attr, value in (("CodexClient", daemon), ("POLL_SECONDS", 0.01),
                            ("_delivered", {})):  # turn ids repeat across tests
            self.addCleanup(setattr, server, attr, getattr(server, attr))
            setattr(server, attr, value)
        return daemon

    def consultant(self, tag, **extra):
        return {"id": f"0199aaaa-0000-0000-0000-000000{tag}", "cwd": ROOT, "threadSource": "nouez", **extra}

    def test_stop_ends_a_running_turn(self):
        # Checked live 2026-11-25: turn/interrupt returns {}, the turn reads "interrupted" within a
        # second, Codex doesn't carry it on, and the next message gets a reply.
        c = self.consultant("st0001")
        running = {"id": "turn-run", "status": "inProgress", "items": [user("q")]}
        daemon = self.use(FakeDaemon([c], {c["id"]: [running]}))
        out = server.stop_consultant({"to": c["id"], "turn_only": True})
        self.assertIn(f"Ended {server.short_name(c)}'s running turn (turn-run)", out)
        self.assertEqual(running["status"], "interrupted")
        self.assertNotIn("thread/archive", daemon.calls)
        self.assertIn("has no turn running", server.stop_consultant({"to": c["id"], "turn_only": True}))
        running["status"] = "inProgress"  # a full stop ends the turn before archiving
        out = server.stop_consultant({"to": c["id"]})
        self.assertIn(f"Stopped {server.short_name(c)} (archived). Ended its running turn.", out)
        self.assertEqual((running["status"], daemon.archived), ("interrupted", c["id"]))
        self.assertLess(daemon.calls.index("turn/interrupt"), daemon.calls.index("thread/archive"))

    def test_stop_never_touches_a_user_session(self):
        """0.26.1: StopConsultant refuses a Codex session the user opened, running turn or not, and
        neither interrupts nor archives it."""
        mine = {"id": "0199aaaa-0000-0000-0000-000000user02", "cwd": ROOT}
        idle = {"id": "0199aaaa-0000-0000-0000-000000user03", "cwd": ROOT}  # no turn running
        running = {"id": "turn-user", "status": "inProgress", "items": [user("q")]}
        done = {"id": "turn-done", "status": "completed", "items": [user("q"), agent("a", "final_answer")]}
        daemon = self.use(FakeDaemon([mine, idle], {mine["id"]: [running], idle["id"]: [done]}))
        for session in (mine, idle):
            for turn_only in (True, False):
                with self.subTest(session=session["id"], turn_only=turn_only), \
                        self.assertRaisesRegex(server.BridgeError, "was not started by StartConsultant"):
                    server.stop_consultant({"to": session["id"], "turn_only": turn_only})
        self.assertEqual(running["status"], "inProgress")
        self.assertFalse({"turn/interrupt", "thread/archive"} & set(daemon.calls))

    def test_an_interrupt_that_doesnt_take(self):
        c = self.consultant("st0002")
        daemon = self.use(FakeDaemon([c], {c["id"]: [{"id": "turn-run", "status": "inProgress", "items": []}]}))
        real = daemon.request
        daemon.request = lambda method, params: {} if method == "turn/interrupt" else real(method, params)
        with mock.patch.object(server, "INTERRUPT_SECONDS", 0.2), \
                self.assertRaisesRegex(server.BridgeError, "couldn't confirm it ended"):
            server.stop_consultant({"to": c["id"]})
        self.assertNotIn("thread/archive", daemon.calls)

    def test_a_turn_that_finishes_as_it_is_stopped(self):
        # Codex refuses to interrupt a turn that has just finished; the stop goes on.
        c = self.consultant("st0003")
        running = {"id": "turn-run", "status": "inProgress", "items": []}
        daemon = self.use(FakeDaemon([c], {c["id"]: [running]}))
        real = daemon.request

        def finishing(method, params):
            if method == "turn/interrupt":
                running["status"] = "completed"
                raise server.BridgeError("no active turn to interrupt")
            return real(method, params)
        daemon.request = finishing
        self.assertIn("finished by itself", server.stop_consultant({"to": c["id"], "turn_only": True}))
        running["status"] = "inProgress"
        out = server.stop_consultant({"to": c["id"]})
        self.assertIn("(archived). Its turn had just finished.", out)
        self.assertEqual(daemon.archived, c["id"])
        # A refusal while the turn still runs is reported, and nothing is archived.
        running["status"], daemon.archived = "inProgress", None
        daemon.request = lambda m, p: (_ for _ in ()).throw(server.BridgeError("refused")) \
            if m == "turn/interrupt" else real(m, p)
        with self.assertRaisesRegex(server.BridgeError, "refused"):
            server.stop_consultant({"to": c["id"]})
        self.assertIsNone(daemon.archived)

    def test_the_interrupted_turn_is_followed_by_its_id(self):
        # A newer turn of other work doesn't hide the ended one, and is left running; a continuation
        # that carries the ended turn on (no message, rootTurnId naming it) is ended too.
        c = self.consultant("st0004")
        running = {"id": "turn-run", "status": "inProgress", "items": [user("q")]}
        daemon = self.use(FakeDaemon([c], {c["id"]: [running]}))
        real = daemon.request
        other = {"id": "turn-other", "status": "inProgress", "items": [user("someone else")]}

        def with_other(method, params):
            out = real(method, params)
            if method == "turn/interrupt" and params["turnId"] == "turn-run":
                daemon.turns[c["id"]].insert(0, other)
            return out
        daemon.request = with_other
        self.assertIn("Ended", server.stop_consultant({"to": c["id"], "turn_only": True}))
        self.assertEqual(other["status"], "inProgress")
        carried = {"id": "turn-carried", "status": "inProgress", "rootTurnId": "turn-run2", "items": []}
        running2 = {"id": "turn-run2", "status": "inProgress", "items": [user("q2")]}
        daemon.turns[c["id"]] = [running2]

        def with_continuation(method, params):
            out = real(method, params)
            if method == "turn/interrupt" and params["turnId"] == "turn-run2":
                daemon.turns[c["id"]].insert(0, carried)
            return out
        daemon.request = with_continuation
        server.stop_consultant({"to": c["id"], "turn_only": True})
        self.assertEqual((running2["status"], carried["status"]), ("interrupted", "interrupted"))
        # Followed hop by hop: an interrupted continuation that was itself carried on.
        a = {"id": "turn-a", "status": "inProgress", "items": [user("q3")]}
        b = {"id": "turn-b", "status": "interrupted", "rootTurnId": "turn-a", "items": []}
        last = {"id": "turn-c", "status": "inProgress", "rootTurnId": "turn-a", "items": []}
        daemon.turns[c["id"]] = [a]

        def chained(method, params):
            out = real(method, params)
            if method == "turn/interrupt" and params["turnId"] == "turn-a":
                daemon.turns[c["id"]][:0] = [last, b]
            return out
        daemon.request = chained
        server.stop_consultant({"to": c["id"], "turn_only": True})
        self.assertEqual(last["status"], "interrupted")

    def test_a_stop_checks_before_each_interrupt(self):
        c = self.consultant("st0006")
        running = {"id": "turn-run", "status": "inProgress", "items": []}
        daemon = self.use(FakeDaemon([c], {c["id"]: [running]}))
        cancel, real = threading.Event(), daemon.request

        def cancelling(method, params):
            if method == "thread/turns/list":
                cancel.set()  # cancelled while the turn is looked up
            return real(method, params)
        daemon.request = cancelling
        with self.assertRaises(server.Cancelled):
            server.stop_consultant({"to": c["id"]}, cancel=cancel)
        self.assertNotIn("turn/interrupt", daemon.calls)
        self.assertEqual(running["status"], "inProgress")

    def test_a_consultant_that_cant_be_read_again_is_left_alone(self):
        c = self.consultant("st0007")
        running = {"id": "turn-run", "status": "inProgress", "items": []}
        daemon = self.use(FakeDaemon([c], {c["id"]: [running]}))
        with mock.patch.object(server, "resolve", lambda client, to, **kw: dict(c)), \
                mock.patch.object(server, "read_thread", lambda client, tid: None):
            for call in (lambda: server.stop_consultant({"to": c["id"]}),
                         lambda: server.send_consultant_message({"kind": "other", "to": c["id"], "message": "hi"})):
                with self.assertRaisesRegex(server.BridgeError, "Couldn't read .* again"):
                    call()
        self.assertFalse({"turn/interrupt", "thread/archive", "turn/start", "turn/steer"} & set(daemon.calls))

    def test_a_stop_waits_for_a_send_in_another_session(self):
        c = self.consultant("st0005")
        daemon = self.use(FakeDaemon([c], {c["id"]: []}))
        with mock.patch.object(server, "LOCK_SECONDS", 0.2), server.codex_lock(c["id"]), \
                self.assertRaisesRegex(server.BridgeError, "Another Claude Code session"):
            server.stop_consultant({"to": c["id"]})
        self.assertNotIn("thread/archive", daemon.calls)
        # And a send after a stop that came first is refused rather than reviving the consultant.
        daemon.threads[c["id"]]["path"] = "/home/u/.codex/archived_sessions/rollout.jsonl"
        with mock.patch.object(server, "resolve", lambda client, to, **kw: dict(c)), \
                self.assertRaisesRegex(server.BridgeError, "was stopped"):
            server.send_consultant_message({"kind": "other", "to": c["id"], "message": "hi"})
        self.assertNotIn("turn/start", daemon.calls)

    def test_start_never_reuses_a_user_session(self):
        mine = {"id": "0199aaaa-0000-0000-0000-000000user01", "cwd": ROOT}
        daemon = self.use(FakeDaemon([mine]))
        out = server.start_consultant({"cwd": ROOT})
        self.assertIn("thread/start", daemon.calls)
        # 0.26.1: the literal values, so a change to the constants can't pass unseen.
        self.assertEqual((daemon.thread_started["sandbox"], daemon.thread_started["approvalPolicy"]),
                         ("read-only", "never"))
        self.assertTrue(out.startswith("Started "))
        self.assertIn("were not used", out)
        self.assertIn(server.short_name(mine), out)

    def test_start_keeps_the_consultant_when_its_title_cant_be_set(self):
        # A daemon error, and a proxy pipe that broke after thread/start.
        for error in (server.BridgeError("thread/name/set timed out after 15s."), BrokenPipeError(32, "Broken pipe")):
            with self.subTest(error=type(error).__name__):
                daemon = self.use(FakeDaemon([]))
                plain = daemon.request

                def request(method, params, plain=plain, error=error):
                    if method == "thread/name/set":
                        raise error
                    return plain(method, params)
                daemon.request = request
                out = server.start_consultant({"cwd": ROOT, "title": "t"})
                self.assertTrue(out.startswith("Started "))
                self.assertIn("0199ffff-0000-0000-0000-000000new001", out)
                self.assertIn("title couldn't be set", out)

    def test_start_reuses_its_own_consultant(self):
        ours = {"id": "0199aaaa-0000-0000-0000-000000ours01", "cwd": ROOT, "threadSource": "nouez"}
        daemon = self.use(FakeDaemon([ours]))
        out = server.start_consultant({"cwd": ROOT, "model": "m"})
        self.assertNotIn("thread/start", daemon.calls)
        self.assertTrue(out.startswith(f"Using {server.short_name(ours)}"))
        self.assertIn("Ignored model", out)
        self.assertIn("pass model to SendConsultantMessage", out)

    def test_start_tells_about_a_codex_update_and_goes_on(self):
        for existing in ([], [self.consultant("ours02")]):
            self.use(FakeDaemon(existing))
            with mock.patch.object(server, "update_notice", return_value="Codex 9.9.9 is out.") as notice:
                out = server.start_consultant({"cwd": ROOT})
            notice.assert_called_once()
            self.assertTrue(out.endswith("\nCodex 9.9.9 is out."))
            self.assertIn("Send it work with SendConsultantMessage.", out)

    def test_send_timeout_shows_output_so_far(self):
        thread = self.consultant("idle01")
        self.use(FakeDaemon([thread]))
        out = server.send_consultant_message({"kind": "other", "to": thread["id"], "message": "hi", "wait": 0.01})
        self.assertIn("still working on turn turn-new; this is not a reply", out)
        self.assertIn("Don't send the message again", out)
        self.assertIn("Don't wait for the reply", out)
        self.assertIn("GetConsultantReply (turn_id turn-new)", out)
        self.assertTrue(out.endswith("working on it"))

    def test_wait_zero_returns_after_delivery(self):
        thread = self.consultant("idle02")
        daemon = self.use(FakeDaemon([thread]))
        out = server.send_consultant_message({"kind": "other", "to": thread["id"], "message": "hi", "wait": 0})
        self.assertTrue(out.startswith("Delivered to "))
        self.assertIn("Don't wait for the reply", out)
        self.assertIn("GetConsultantReply (turn_id turn-new)", out)
        self.assertIn("turn/start", daemon.calls)

    def test_model_and_effort_go_to_the_new_turn(self):
        thread = self.consultant("tune01")
        daemon = self.use(FakeDaemon([thread]))
        out = server.send_consultant_message(
            {"kind": "other", "to": thread["id"], "message": "hi", "wait": 0, "model": "gpt-6-astra", "effort": "xhigh"})
        self.assertEqual(daemon.started["model"], "gpt-6-astra")
        self.assertEqual(daemon.started["effort"], "xhigh")
        self.assertIn("on model gpt-6-astra, effort xhigh", out)
        self.assertEqual(daemon.started["sandboxPolicy"], {"type": "readOnly"})
        self.assertEqual(daemon.started["approvalPolicy"], "never")
        self.assertIn("keeps for later messages until changed", out)

    def test_a_quick_reply_still_says_the_setting_changed(self):
        thread = self.consultant("tune05")
        self.use(FakeDaemon([thread], answer="the answer"))
        out = server.send_consultant_message({"kind": "other", "to": thread["id"], "message": "hi", "effort": "xhigh"})
        self.assertIn("the answer", out)
        self.assertIn("now runs on effort xhigh until changed", out)

    def test_provider_model_ids_pass(self):
        thread = self.consultant("tune06")
        for model in ("gpt-oss:20b", "org/model-1", "gpt-6-astra"):
            daemon = self.use(FakeDaemon([thread]))
            server.send_consultant_message({"kind": "other", "to": thread["id"], "message": "hi", "wait": 0, "model": model})
            self.assertEqual(daemon.started["model"], model)

    def test_without_model_or_effort_the_turn_keeps_its_settings(self):
        thread = self.consultant("tune02")
        daemon = self.use(FakeDaemon([thread]))
        out = server.send_consultant_message({"kind": "other", "to": thread["id"], "message": "hi", "wait": 0, "effort": ""})
        self.assertNotIn("model", daemon.started)
        self.assertNotIn("effort", daemon.started)
        self.assertNotIn("until changed", out)

    def test_a_send_without_model_or_effort_takes_nouezs_pick(self):
        """0.26.0: nouez applies the kind's suggestion itself; a named model or effort wins, a user's
        own session is never routed, and a busy consultant is steered without it."""
        pick = {"provider": "codex", "model": "gpt-6.2-astra", "effort": "high",
                "why": ["Astra at high scores best for reviews"], "notes": []}
        thread = self.consultant("tune06")
        daemon = self.use(FakeDaemon([thread]))
        with mock.patch.object(server, "send_route", return_value=pick) as route:
            out = server.send_consultant_message({"kind": "review", "to": thread["id"], "message": "hi", "wait": 0})
        route.assert_called_once()
        self.assertEqual((daemon.started["model"], daemon.started["effort"]), ("gpt-6.2-astra", "high"))
        self.assertIn("nouez's pick for a review: Astra at high scores best for reviews", out)
        daemon = self.use(FakeDaemon([thread]))
        with mock.patch.object(server, "send_route", return_value=pick) as route:
            server.send_consultant_message({"kind": "review", "to": thread["id"], "message": "hi", "wait": 0,
                                            "effort": "xhigh"})
        route.assert_not_called()
        self.assertEqual(daemon.started["effort"], "xhigh")
        self.assertNotIn("model", daemon.started)
        running = {"id": "turn-1", "status": "inProgress", "items": [user("q")]}
        daemon = self.use(FakeDaemon([thread], {thread["id"]: [running]}))
        with mock.patch.object(server, "send_route", return_value=pick), \
                mock.patch.object(server, "_bridge_turns", {"turn-1"}):
            out = server.send_consultant_message({"kind": "review", "to": thread["id"], "message": "more", "wait": 0})
        self.assertIn("steered", out)
        self.assertIn("turn/steer", daemon.calls)

    def test_a_reported_limit_with_no_credits_refuses_a_new_turn(self):
        """0.28.1: a Codex quota that reports its limit reached and no credits refuses a new turn with
        nothing sent, saying where to go; credits not reported, or a message added to a running turn,
        goes ahead; a forecast only adds a note."""
        now = time.time()

        def limits(reached, credits, used=100):
            return {"rateLimits": {"primary": {"usedPercent": used, "windowDurationMins": 10080,
                                               "resetsAt": int(now + 2 * 86400)},
                                   "rateLimitReachedType": reached, "credits": credits}}

        class Limited(FakeDaemon):
            def __init__(self, *a, rl=None, **k):
                super().__init__(*a, **k)
                self.rl = rl

            def request(self, method, params):
                if method == "account/rateLimits/read":
                    self.calls.append(method)
                    return self.rl
                if method == "model/list":
                    return {"data": []}
                return super().request(method, params)
        thread = self.consultant("lim001")
        none_left = limits("weekly", {"hasCredits": False, "unlimited": False})
        daemon = self.use(Limited([thread], rl=none_left))
        with mock.patch.object(server, "agy_command", lambda env=None: None), \
                self.assertRaisesRegex(server.BridgeError, "no credits to go past it.*Nothing was sent"):
            server.send_consultant_message({"kind": "review", "to": thread["id"], "message": "hi", "wait": 0,
                                            "effort": "high"})
        self.assertNotIn("turn/start", daemon.calls)
        daemon = self.use(Limited([thread], rl=limits("weekly", None)))  # credits not reported: Codex decides
        out = server.send_consultant_message({"kind": "review", "to": thread["id"], "message": "hi", "wait": 0,
                                              "effort": "high"})
        self.assertIn("turn/start", daemon.calls)
        self.assertIn("(Usage: Codex reports its limit reached (weekly): this turn may fail", out)
        running = {"id": "turn-1", "status": "inProgress", "items": [user("q")]}
        daemon = self.use(Limited([thread], {thread["id"]: [running]}, rl=none_left))
        with mock.patch.object(server, "_bridge_turns", {"turn-1"}):
            out = server.send_consultant_message({"kind": "review", "to": thread["id"], "message": "more", "wait": 0})
        self.assertIn("turn/steer", daemon.calls)
        self.assertNotIn("Usage:", out)
        # a steer reads no usage before it goes, so never waits for it (the log's snapshot comes after)
        self.assertNotIn("account/rateLimits/read", daemon.calls[:daemon.calls.index("turn/steer")])
        daemon = self.use(Limited([thread], rl=limits(None, None, used=80)))  # 80% five days in: runs out first
        out = server.send_consultant_message({"kind": "review", "to": thread["id"], "message": "hi", "wait": 0,
                                              "effort": "high"})
        self.assertIn("turn/start", daemon.calls)
        self.assertIn("(Usage: Codex: its weekly window runs out before its reset at this rate.", out)

    def test_a_send_with_no_pick_keeps_the_consultants_settings(self):
        """0.26.1: when the usage can't be read, or no subscription has room, a send of any kind goes
        ahead on the consultant's current model and effort, and says nothing of a pick."""
        with mock.patch.object(server, "claude_budget", side_effect=RuntimeError("unreadable")):
            self.assertIsNone(server.send_route("review", "codex"))
        thread = self.consultant("tune07")
        daemon = self.use(FakeDaemon([thread]))
        with mock.patch.object(server, "send_route", return_value=None):
            out = server.send_consultant_message({"kind": "review", "to": thread["id"], "message": "hi", "wait": 0})
        self.assertNotIn("model", daemon.started)
        self.assertNotIn("effort", daemon.started)
        self.assertNotIn("nouez's pick", out)

    def test_bad_model_or_effort_is_refused_before_sending(self):
        thread = self.consultant("tune03")
        for key, value in (("model", "-c x"), ("model", "a\tb"), ("effort", "very high"), ("effort", 3)):
            daemon = self.use(FakeDaemon([thread]))
            with self.assertRaises(server.BridgeError) as caught:
                server.send_consultant_message({"kind": "other", "to": thread["id"], "message": "hi", key: value})
            self.assertIn(f"`{key}` must be", str(caught.exception))
            self.assertNotIn("turn/start", daemon.calls)

    def test_model_or_effort_on_a_busy_consultant_sends_nothing(self):
        thread = self.consultant("tune04")
        running = {"id": "turn-1", "status": "inProgress", "items": [user("q")]}
        daemon = self.use(FakeDaemon([thread], {thread["id"]: [running]}))
        with self.assertRaises(server.BridgeError) as caught:
            server.send_consultant_message({"kind": "other", "to": thread["id"], "message": "more", "effort": "high"})
        self.assertIn("Nothing was sent", str(caught.exception))
        self.assertNotIn("turn/steer", daemon.calls)
        self.assertNotIn("turn/start", daemon.calls)

    def test_the_values_a_busy_consultant_has_dont_stop_a_steer(self):
        """0.24.0: Claude passes ConsultantBudget's suggestion with every message, so the model and
        effort the running turn already has are no change, and the message is steered in."""
        thread = self.consultant("tune05", model="gpt-6.2-astra", reasoningEffort="high")
        running = {"id": "turn-1", "status": "inProgress", "items": [user("q")]}
        daemon = self.use(FakeDaemon([thread], {thread["id"]: [running]}))
        with mock.patch.object(server, "_bridge_turns", {"turn-1"}), mock.patch.object(server, "_delivered", {}):
            out = server.send_consultant_message({"kind": "other", "to": thread["id"], "message": "more", "wait": 0,
                                                  "model": "gpt-6.2-astra", "effort": "high"})
            with self.assertRaisesRegex(server.BridgeError, "can't change its effort"):
                server.send_consultant_message({"kind": "other", "to": thread["id"], "message": "other", "wait": 0,
                                                "model": "gpt-6.2-astra", "effort": "xhigh"})
        self.assertIn("steered into the running turn", out)
        self.assertEqual(daemon.calls.count("turn/steer"), 1)

    def test_steered_timeout_hides_output_from_before_the_message(self):
        thread = self.consultant("busy01")
        running = {"id": "turn-1", "status": "inProgress",
                   "items": [user("[Message from Claude Code via the consultants bridge]\nq"), agent("answer to q")]}
        self.use(FakeDaemon([thread], {thread["id"]: [running]}))
        with mock.patch.object(server, "_bridge_turns", {"turn-1"}):
            out = server.send_consultant_message({"kind": "other", "to": thread["id"], "message": "more", "wait": 0.01})
        self.assertIn("steered into the running turn", out)
        self.assertNotIn("answer to q", out)

    def test_the_same_message_again_isnt_steered_twice(self):
        """0.20.0: a repeated send, as after a dropped connection, gets the running turn's receipt."""
        thread = self.consultant("busy05")
        running = {"id": "turn-1", "status": "inProgress",
                   "items": [user("[Message from Claude Code via the consultants bridge]\n\nq")]}
        daemon = self.use(FakeDaemon([thread], {thread["id"]: [running]}))
        with mock.patch.object(server, "_bridge_turns", {"turn-1"}), mock.patch.object(server, "_delivered", {}):
            first = server.send_consultant_message({"kind": "other", "to": thread["id"], "message": "more", "wait": 0})
            running["items"].pop()  # thread/turns/list's summary doesn't show a steer
            again = server.send_consultant_message({"kind": "other", "to": thread["id"], "message": "more", "wait": 0})
            tuned = server.send_consultant_message({"kind": "other", "to": thread["id"], "message": "more", "wait": 0, "effort": "high"})
        self.assertIn("steered into the running turn", first)
        self.assertEqual(daemon.calls.count("turn/steer"), 1)
        self.assertNotIn("turn/start", daemon.calls)
        self.assertIn("already in the running turn, so it wasn't sent again", again)
        self.assertIn("turn turn-1", again)
        self.assertIn("the running turn keeps its effort", tuned)  # not refused: nothing new to send

    def test_text_nouez_didnt_deliver_isnt_a_repeat(self):
        """0.20.0: the same text typed in the pane started a turn nouez didn't, so it is refused as
        any such turn is, not taken for a message already delivered."""
        thread = self.consultant("busy06")
        running = {"id": "turn-1", "status": "inProgress",
                   "items": [user("[Message from Claude Code via the consultants bridge]\n\nmore")]}
        daemon = self.use(FakeDaemon([thread], {thread["id"]: [running]}))
        with mock.patch.object(server, "_delivered", {}):
            with self.assertRaisesRegex(server.BridgeError, "didn't start.*Nothing was sent"):
                server.send_consultant_message({"kind": "other", "to": thread["id"], "message": "more", "wait": 0})
        self.assertNotIn("turn/steer", daemon.calls)

    def test_a_repeat_that_ends_doesnt_claim_new_settings(self):
        """0.20.0: a repeat with effort whose turn ends within the wait says the turn kept its
        settings, not that the consultant now runs on new ones."""
        thread = self.consultant("busy07")
        text = "[Message from Claude Code via the consultants bridge]\n\nmore"
        running = {"id": "turn-1", "status": "inProgress", "items": [user(text)]}
        daemon = self.use(FakeDaemon([thread], {thread["id"]: [running]}))
        plain, lists = daemon.request, []

        def request(method, params):
            if method == "thread/turns/list":
                lists.append(1)
                if len(lists) == 3:
                    running.update(status="completed", items=[user(text), agent("done", "final_answer")])
            return plain(method, params)
        daemon.request = request
        with mock.patch.object(server, "_bridge_turns", {"turn-1"}), \
                mock.patch.object(server, "_delivered", {"turn-1": {text}}):
            out = server.send_consultant_message({"kind": "other", "to": thread["id"], "message": "more", "wait": 5, "effort": "high"})
        self.assertIn("done", out)
        self.assertIn("already in turn turn-1, so it wasn't sent again, and the turn kept its effort", out)
        self.assertNotIn("now runs on", out)
        self.assertFalse({"turn/steer", "turn/start"} & set(daemon.calls))

    def test_a_repeat_names_the_turn_it_was_delivered_to(self):
        """0.20.0: followed to Codex's continuation, a repeat still names the turn nouez's record
        has it in, not the continuation, which may hold no message at all."""
        thread = self.consultant("busy08")
        text = "[Message from Claude Code via the consultants bridge]\n\nmore"
        running = {"id": "turn-1", "rootTurnId": "turn-1", "status": "inProgress", "items": [user(text)]}
        daemon = self.use(FakeDaemon([thread], {thread["id"]: [running]}))
        cont = {"id": "turn-2", "rootTurnId": "turn-1", "status": "completed",
                "items": [agent("carried-on answer", "final_answer")]}
        plain, lists = daemon.request, []

        def request(method, params):
            if method == "thread/turns/list":
                lists.append(1)
                if len(lists) == 3:
                    running["status"] = "interrupted"
                    daemon.turns[thread["id"]].insert(0, cont)
            return plain(method, params)
        daemon.request = request
        with mock.patch.object(server, "_bridge_turns", {"turn-1"}), \
                mock.patch.object(server, "_delivered", {"turn-1": {text}}):
            out = server.send_consultant_message({"kind": "other", "to": thread["id"], "message": "more", "wait": 5})
        self.assertIn("carried-on answer", out)
        self.assertIn("already in turn turn-1, so it wasn't sent again", out)
        self.assertNotIn("already in turn turn-2", out)

    def test_only_the_exact_turn_nouez_started_is_steered(self):
        """0.18.0: a turn whose root nouez started may still be one typed in the pane."""
        thread = self.consultant("busy04")
        running = {"id": "turn-2", "rootTurnId": "turn-1", "status": "inProgress", "items": [user("edit the files")]}
        daemon = self.use(FakeDaemon([thread], {thread["id"]: [running]}))
        with mock.patch.object(server, "_bridge_turns", {"turn-1"}):
            with self.assertRaisesRegex(server.BridgeError, "didn't start.*Nothing was sent"):
                server.send_consultant_message({"kind": "other", "to": thread["id"], "message": "more", "wait": 0.01})
        self.assertNotIn("turn/steer", daemon.calls)

    def test_a_header_in_the_text_doesnt_allow_steering(self):
        """0.18.0: only nouez's record of the turns it started counts, not a header typed in the pane."""
        thread = self.consultant("busy03")
        running = {"id": "turn-1", "status": "inProgress",
                   "items": [user("[Message from Claude Code via the consultants bridge]\nedit the files")]}
        daemon = self.use(FakeDaemon([thread], {thread["id"]: [running]}))
        with self.assertRaisesRegex(server.BridgeError, "didn't start.*Nothing was sent"):
            server.send_consultant_message({"kind": "other", "to": thread["id"], "message": "more", "wait": 0.01})
        self.assertNotIn("turn/steer", daemon.calls)

    def test_never_steers_a_turn_typed_in_a_terminal(self):
        """0.18.0: a turn started in a terminal (codex resume) may not be read-only, so a message waits for it."""
        thread = self.consultant("busy02")
        running = {"id": "turn-1", "status": "inProgress", "items": [user("edit the files")]}
        daemon = self.use(FakeDaemon([thread], {thread["id"]: [running]}))
        with self.assertRaisesRegex(server.BridgeError, "didn't start \\(it was typed in its terminal.*Nothing was sent"):
            server.send_consultant_message({"kind": "other", "to": thread["id"], "message": "more", "wait": 0.01})
        self.assertNotIn("turn/steer", daemon.calls)
        self.assertNotIn("turn/start", daemon.calls)

    def test_failure_after_delivery_says_delivered(self):
        thread = self.consultant("fail01")
        self.use(FakeDaemon([thread], fail_after_start=True))
        with self.assertRaises(server.BridgeError) as caught:
            server.send_consultant_message({"kind": "other", "to": thread["id"], "message": "hi"})
        self.assertTrue(str(caught.exception).startswith("Delivered to "))
        self.assertIn("Don't send the message again", str(caught.exception))

    def test_user_session_needs_allow_user_session(self):
        mine = {"id": "0199aaaa-0000-0000-0000-000000user02", "cwd": ROOT}
        daemon = self.use(FakeDaemon([mine]))
        with self.assertRaises(server.BridgeError) as caught:
            server.send_consultant_message({"kind": "other", "to": mine["id"], "message": "hi", "wait": 0})
        self.assertIn("allow_user_session=true", str(caught.exception))
        self.assertNotIn("turn/start", daemon.calls)
        out = server.send_consultant_message({"kind": "other", "to": mine["id"], "message": "hi", "wait": 0,
                                              "allow_user_session": True})
        self.assertTrue(out.startswith("Delivered to "))
        # The user's own session keeps its own sandbox and approvals.
        self.assertNotIn("sandboxPolicy", daemon.started)
        self.assertNotIn("approvalPolicy", daemon.started)

    def test_user_sessions_can_be_asked_about_or_turned_off(self):
        """0.26.0: NOUEZ_NO_USER_SESSIONS=1 never messages one; NOUEZ_ASK_USER_SESSION=1 asks the user in
        the client's own prompt, showing the message, before each one."""
        mine = {"id": "0199aaaa-0000-0000-0000-000000user03", "cwd": ROOT}
        daemon = self.use(FakeDaemon([mine]))
        asked, answers = [], []

        def prompt(method, params, timeout=5):
            asked.append((method, params["message"]))
            return {"action": answers.pop(0)} if answers else None

        def send():
            return server.send_consultant_message({"kind": "other", "to": mine["id"], "message": "hi  there",
                                                   "wait": 0, "allow_user_session": True})
        with mock.patch.dict(os.environ, {"NOUEZ_NO_USER_SESSIONS": "1"}):
            with self.assertRaisesRegex(server.BridgeError, "never to message one .NOUEZ_NO_USER_SESSIONS=1"):
                send()
        with mock.patch.dict(os.environ, {"NOUEZ_ASK_USER_SESSION": "1"}), \
                mock.patch.object(server, "client_request", prompt):
            with self.assertRaisesRegex(server.BridgeError, "can't show one"):  # no elicitation in this client
                send()
            with mock.patch.dict(server._client_caps, {"elicitation": {}}):
                answers.append("decline")
                with self.assertRaisesRegex(server.BridgeError, "The user declined"):
                    send()
                with self.assertRaisesRegex(server.BridgeError, "didn't answer"):
                    send()
                self.assertNotIn("turn/start", daemon.calls)
                answers.append("accept")
                self.assertTrue(send().startswith("Delivered to "))
        self.assertEqual(asked[0][0], "elicitation/create")
        self.assertIn("a Codex session you opened", asked[0][1])
        self.assertIn("hi there", asked[0][1])
        self.assertEqual(daemon.calls.count("turn/start"), 1)

    def test_send_offers_the_waiter(self):
        thread = self.consultant("wait01")
        self.use(FakeDaemon([thread]))
        out = server.send_consultant_message({"kind": "other", "to": thread["id"], "message": "hi", "wait": 0})
        self.assertIn("run_in_background", out)
        self.assertIn(f'server.py wait {thread["id"]} turn-new\n', out)

    def test_waiter_command_quotes_only_paths_with_spaces(self):
        # os.name pinned for each form, so the test reads the same on every system
        with mock.patch.object(server.sys, "executable", r"C:\Py\python.exe"), \
             mock.patch.object(server.os, "name", "nt"), \
             mock.patch.object(server.os.path, "abspath", return_value=r"C:\My Tools\server.py"):
            self.assertEqual(server.waiter_command("t1", "u1"),
                             'C:/Py/python.exe -I "C:/My Tools/server.py" wait t1 u1')
        with mock.patch.object(server.sys, "executable", "/usr/bin/python3"), \
             mock.patch.object(server.os, "name", "posix"), \
             mock.patch.object(server.os.path, "abspath", return_value="/home/me/My Tools/server.py"):
            self.assertEqual(server.waiter_command("t1", "u1"),
                             '/usr/bin/python3 -I "/home/me/My Tools/server.py" wait t1 u1')

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
        self.assertEqual([r.split("(")[0] for r in server.allow_rules()],
                         ["Bash", "PowerShell"] if os.name == "nt" else ["Bash"])

    def test_doctor_per_setup(self):
        """0.18.0: doctor reports each consultant CLI apart, and neither one is required."""
        def doctor(codex, agy, usage=None, login=(0, "Logged in using ChatGPT")):
            # the fake paths are POSIX ones; on Windows a path needs a drive to be rooted
            patcher = mock.patch.object(server, "rooted", lambda path: path.startswith("/"))
            patcher.start()
            self.addCleanup(patcher.stop)
            found = {"codex": codex, "claude": "/bin/claude", "wt": "wt"}
            with mock.patch.object(server, "which", lambda name, env=None: found.get(name)), \
                 mock.patch.object(server, "agy_command", lambda env=None: agy), \
                 mock.patch.object(server, "codex_version", lambda exe: "0.170.0"), \
                 mock.patch.object(server, "run_status", lambda argv, timeout=20: login), \
                 mock.patch.object(server, "run_text", lambda argv, timeout=20: "1.5.14"), \
                 mock.patch.object(server, "read_agy_usage", lambda: usage), \
                 mock.patch.object(server, "trust_backups_report", lambda: None), \
                 mock.patch.object(server, "CodexClient", FakeDaemon([])), \
                 mock.patch.object(server, "claude_config_dir", lambda: tempfile.gettempdir() + "/no-such-dir"),                  contextlib.redirect_stdout(io.StringIO()) as out:
                return server.run_doctor(), out.getvalue()
        code, out = doctor(None, None)
        self.assertEqual(code, 0, out)
        self.assertIn("consultations are off", out)
        self.assertIn("there is no", out)
        code, out = doctor(None, "/bin/agy", {"groups": []})
        self.assertEqual(code, 0, out)
        self.assertIn("Codex isn't installed", out)
        self.assertIn("1 of 1 installed consultant CLI(s) work; StartConsultant uses Antigravity", out)
        code, out = doctor(None, "/bin/agy", {"error": "agy: not signed in"})
        self.assertEqual(code, 1, out)
        self.assertRegex(out, "run `[^`]*/bin/agy[^`]*` once in a terminal to sign in, then `[^`]*/bin/agy[^`]* models`")
        code, out = doctor("/bin/codex", None, login=(1, "Not logged in"))
        self.assertEqual(code, 1, out)
        self.assertIn("Codex isn't signed in (Not logged in): run `codex login`.", out)
        code, out = doctor("/bin/codex", None)
        self.assertEqual(code, 0, out)
        self.assertIn("Antigravity isn't installed", out)
        code, out = doctor("/bin/codex", "/bin/agy", {"groups": []}, login=(1, "Not logged in"))
        self.assertEqual(code, 0, out)  # one working CLI is enough
        self.assertIn("[problem] Codex isn't signed in", out)
        self.assertIn("1 of 2 installed consultant CLI(s) work: the problem above only matters for that CLI", out)
        code, out = doctor(None, "/bin/agy", {"error": "agy didn't answer (TimeoutExpired)"})
        self.assertEqual(code, 1, out)
        self.assertIn("didn't answer within 60 seconds, so its sign-in is unknown", out)
        self.assertNotIn("to sign in, then", out)

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

    def test_reply_and_waiter_on_a_running_turn_say_it_runs_on(self):
        """0.26.1: through the entry points themselves, GetConsultantReply on a running turn (with
        and without a background waiter) and the waiter out of time say the turn still runs and
        what they show isn't a reply."""
        thread = self.consultant("wait09")
        running = {"id": "turn-1", "status": "inProgress", "items": [user("q"), agent("half", "commentary")]}
        self.use(FakeDaemon([thread], {thread["id"]: [running]}))
        for waiter in (True, False):
            with self.subTest(waiter=waiter), mock.patch.object(server, "background_waiter", lambda: waiter):
                out = server.get_consultant_reply({"to": thread["id"], "turn_id": "turn-1"})
                self.assertIn("still working on turn turn-1; this is not a reply", out)
        with mock.patch.object(server, "WAITER_SECONDS", 0.05), mock.patch.object(server, "STALL_SECONDS", 3600):
            code, out = self.run_waiter(thread["id"], "turn-1")
        self.assertEqual(code, 0)
        self.assertIn("still working on turn turn-1; this is not a reply", out)
        self.assertIn(f"wait {thread['id']} turn-1", out)

    def test_a_reply_is_looked_up_among_the_100_most_recent_turns(self):
        """0.26.1: GetConsultantReply finds a turn among the 100 most recent and says when it isn't
        there, rather than reading the whole conversation."""
        self.assertEqual(server.REPLY_LOOKBACK, 100)
        thread = self.consultant("look01")
        turns = [{"id": f"turn-{n}", "status": "completed", "items": [user("q"), agent(f"answer {n}", "final_answer")]}
                 for n in range(101, 0, -1)]  # newest first, as the daemon lists them
        self.use(FakeDaemon([thread], {thread["id"]: turns}))
        self.assertIn("answer 2", server.get_consultant_reply({"to": thread["id"], "turn_id": "turn-2"}))
        out = server.get_consultant_reply({"to": thread["id"], "turn_id": "turn-1"})
        self.assertIn("has no turn turn-1 among its 100 most recent turns", out)

    def test_waiter_says_when_a_turn_shows_nothing_new(self):
        """0.20.0: a turn that shows nothing new for STALL_SECONDS wakes Claude, rather than the
        waiter sitting silent for its whole 25 minutes."""
        thread = self.consultant("wait08")
        running = {"id": "turn-1", "status": "inProgress", "items": [user("q"), agent("looking", "commentary")]}
        self.use(FakeDaemon([thread], {thread["id"]: [running]}))
        with mock.patch.object(server, "STALL_SECONDS", 0.05):
            code, out = self.run_waiter(thread["id"], "turn-1")
        self.assertEqual(code, 0)
        self.assertIn("still working on turn turn-1; this is not a reply", out)
        self.assertIn("seen no change from", out)
        self.assertIn("for 0 minutes: it may be stuck, or still thinking or running a long command", out)
        self.assertIn(f"wait {thread['id']} turn-1", out)
        self.assertIn("StopConsultant stops the consultant", out)
        self.assertNotIn("schedule", out)

    def test_stall_advice_for_a_users_own_session(self):
        """0.20.0: StopConsultant refuses a session the user opened, so the advice sends them to its terminal."""
        mine = {"id": "0199aaaa-0000-0000-0000-000000user09", "cwd": ROOT}
        running = {"id": "turn-1", "status": "inProgress", "items": [user("q")]}
        self.use(FakeDaemon([mine], {mine["id"]: [running]}))
        with mock.patch.object(server, "STALL_SECONDS", 0.05):
            code, out = self.run_waiter(mine["id"], "turn-1")
        self.assertIn("seen no change from", out)
        self.assertIn("user's own Codex session, so they stop it from its terminal", out)
        self.assertNotIn("StopConsultant", out)

    def test_a_growing_rollout_is_activity(self):
        """0.20.0: the turn list shows only the first and last messages, so Codex's rollout file is
        what changes while a turn runs commands."""
        with tempfile.TemporaryDirectory() as d:
            rollout = os.path.join(d, "rollout.jsonl")
            with open(rollout, "w") as f:
                f.write("{}\n")
            watch = server.StallWatch(server.codex_activity(rollout), limit=0)
            turn = {"items": [user("q")]}
            self.assertFalse(watch("t", turn))
            with open(rollout, "a") as f:
                f.write("{}\n")
            self.assertFalse(watch("t", turn))  # same items, but the rollout grew
            self.assertTrue(watch("t", turn))
            gone = server.codex_activity(os.path.join(d, "missing.jsonl"))
            self.assertEqual(gone("t", turn)[0], None)

    def test_a_turn_that_keeps_changing_isnt_called_stuck(self):
        marks = iter(range(100))
        moving = server.StallWatch(lambda tid, turn: next(marks), limit=0)
        self.assertFalse(any(moving("t", None) for _ in range(5)))
        still = server.StallWatch(lambda tid, turn: "same", limit=0)
        self.assertFalse(still("t", None))  # the first look only sets the mark
        self.assertTrue(still("t", None))
        self.assertTrue(still.stalled)
        followed = server.StallWatch(lambda tid, turn: "same", limit=0)
        followed("t1", None)
        self.assertFalse(followed("t2", None))  # a continuation is a change

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

    def test_waiter_reports_an_unreadable_consultants_file(self):  # 0.18.0: a message, not a traceback
        with mock.patch.object(server, "agy_resolve", side_effect=server.BridgeError("can't read it")):
            code, out = self.run_waiter("t-x", "u-x")
        self.assertEqual((code, out.strip()), (1, "can't read it"))

    def test_waiter_gives_up_after_repeated_connection_failures(self):
        def down():
            raise server.DaemonDown("down")
        self.use(down)
        with mock.patch.object(server.time, "sleep") as sleep:
            code, out = self.run_waiter("0199aaaa-0000-0000-0000-000000wait04", "turn-1")
        self.assertEqual(code, 1)
        self.assertEqual(sleep.call_count, server.WAITER_RETRIES)
        self.assertIn("Stopped waiting for turn turn-1", out)
        self.assertIn(server.WAIT_ENDED, out)  # 0.26.0: the wait ended, not the turn

    def test_waiter_gives_up_on_a_daemon_that_connects_and_then_fails(self):
        """0.26.0: a connection that works but can't read the turns counts as a failure, so the
        waiter gives up after WAITER_RETRIES rather than retry until its deadline."""
        thread = self.consultant("wait06")
        daemon = self.use(FakeDaemon([thread]))
        real = daemon.request
        daemon.request = lambda m, p: (_ for _ in ()).throw(server.BridgeError("turns/list timed out.")) \
            if m == "thread/turns/list" else real(m, p)
        with mock.patch.object(server.time, "sleep") as sleep:
            code, out = self.run_waiter(thread["id"], "turn-1")
        self.assertEqual((code, sleep.call_count), (1, server.WAITER_RETRIES))
        self.assertIn(server.WAIT_ENDED, out)

    def test_waiter_rides_out_os_errors(self):
        def broken():
            raise BrokenPipeError("pipe closed")
        self.use(broken)
        with mock.patch.object(server.time, "sleep"):
            code, out = self.run_waiter("0199aaaa-0000-0000-0000-000000wait06", "turn-1")
        self.assertEqual(code, 1)
        self.assertIn("pipe closed", out)

    def restarted(self, tag, cont_status="completed"):
        """A consultant whose turn-1 a daemon restart cut off, carried on by Codex as turn-2."""
        thread = self.consultant(tag)
        cut = {"id": "turn-1", "status": "interrupted", "rootTurnId": "turn-1", "items": [user("q")]}
        cont = {"id": "turn-2", "status": cont_status, "rootTurnId": "turn-1",
                "items": [agent("carried-on answer", "final_answer")]}
        return thread, self.use(FakeDaemon([thread], {thread["id"]: [cont, cut]}))

    def appear_after(self, daemon, tid, lists, turn):
        """Make `turn` the newest turn of `tid` once thread/turns/list has been called `lists` times."""
        plain, seen = daemon.request, []

        def request(method, params):
            if method == "thread/turns/list":
                seen.append(1)
                if len(seen) == lists:
                    daemon.turns[tid].insert(0, turn)
            return plain(method, params)
        daemon.request = request

    def test_waiter_follows_a_turn_codex_carried_on(self):
        thread, _ = self.restarted("cont01")
        code, out = self.run_waiter(thread["id"], "turn-1")
        self.assertEqual(code, 0)
        self.assertIn("turn turn-2)", out)
        self.assertIn("carried-on answer", out)
        self.assertIn("Turn turn-1 was interrupted and Codex carried it on as turn turn-2", out)

    def test_waiter_follows_a_continuation_that_starts_late(self):
        thread = self.consultant("cont02")
        cut = {"id": "turn-1", "status": "interrupted", "items": [user("q")]}
        daemon = self.use(FakeDaemon([thread], {thread["id"]: [cut]}))
        self.appear_after(daemon, thread["id"], 4, {"id": "turn-2", "status": "completed", "rootTurnId": "turn-1",
                                                     "items": [agent("late answer", "final_answer")]})
        with mock.patch.object(server.time, "sleep"):
            code, out = self.run_waiter(thread["id"], "turn-1")
        self.assertIn("late answer", out)

    def test_waiter_follows_an_old_chain_to_its_end(self):
        # turn-1 cut off, carried on as turn-2, cut off again long ago, carried on as turn-3.
        thread = self.consultant("cont03")
        turns = [{"id": "turn-3", "status": "completed", "rootTurnId": "turn-1", "items": [agent("third", "final_answer")]},
                 {"id": "turn-2", "status": "interrupted", "rootTurnId": "turn-1", "items": [], "completedAt": 1000},
                 {"id": "turn-1", "status": "interrupted", "items": [user("q")]}]
        self.use(FakeDaemon([thread], {thread["id"]: turns}))
        with mock.patch.object(server.time, "sleep") as sleep:
            code, out = self.run_waiter(thread["id"], "turn-1")
        sleep.assert_not_called()
        self.assertIn("third", out)
        self.assertIn("carried it on as turn turn-3", out)

    def test_waiter_returns_an_interrupted_turn_at_once_once_a_later_turn_exists(self):
        # No timestamps, but a later turn that doesn't carry it on: no continuation can come now.
        thread = self.consultant("cont04")
        cut = {"id": "turn-1", "status": "interrupted", "items": [user("q")]}
        other = {"id": "turn-2", "status": "completed", "rootTurnId": "turn-2", "items": [user("new"), agent("other", "final_answer")]}
        self.use(FakeDaemon([thread], {thread["id"]: [other, cut]}))
        with mock.patch.object(server.time, "sleep") as sleep:
            code, out = self.run_waiter(thread["id"], "turn-1")
        sleep.assert_not_called()
        self.assertNotIn("turn-2", out)
        self.assertIn("turn-1 interrupted", out)

    def test_waiter_returns_an_old_interrupted_turn_at_once(self):
        thread = self.consultant("cont05")
        cut = {"id": "turn-1", "status": "interrupted", "items": [user("q")], "startedAt": 1000, "durationMs": 5000}
        self.use(FakeDaemon([thread], {thread["id"]: [cut]}))
        with mock.patch.object(server.time, "sleep") as sleep:
            code, out = self.run_waiter(thread["id"], "turn-1")
        sleep.assert_not_called()
        self.assertIn("turn-1 interrupted", out)

    def test_waiter_gives_up_on_a_continuation_after_the_grace(self):
        thread = self.consultant("cont06")
        cut = {"id": "turn-1", "status": "interrupted", "items": [user("q")]}  # no timestamps: maybe just now
        self.use(FakeDaemon([thread], {thread["id"]: [cut]}))
        with mock.patch.object(server, "CONTINUATION_GRACE", 0.05):
            code, out = self.run_waiter(thread["id"], "turn-1")
        self.assertEqual(code, 0)
        self.assertIn("turn-1 interrupted", out)

    def test_a_shared_root_alone_is_not_a_continuation(self):
        # turn-3 shares turn-2's root but doesn't come right after it, and turn-x isn't in the chain.
        thread = self.consultant("cont07")
        turns = [{"id": "turn-3", "status": "completed", "rootTurnId": "turn-1", "items": [user("other work"), agent("wrong", "final_answer")]},
                 {"id": "turn-x", "status": "completed", "rootTurnId": "turn-x", "items": [user("x"), agent("x", "final_answer")]},
                 {"id": "turn-2", "status": "interrupted", "rootTurnId": "turn-1", "items": []},
                 {"id": "turn-1", "status": "interrupted", "items": [user("q")]}]
        self.use(FakeDaemon([thread], {thread["id"]: turns}))
        code, out = self.run_waiter(thread["id"], "turn-2")
        self.assertNotIn("wrong", out)
        self.assertIn("turn-2 interrupted", out)
        self.assertEqual(server.next_in_chain(turns, turns[2]), None)

    def test_waiter_keeps_a_followed_turn_across_a_dropped_connection(self):
        thread = self.consultant("cont08")
        running = {"id": "turn-1", "status": "inProgress", "items": [user("q")]}
        cut = dict(running, status="interrupted")
        cont = {"id": "turn-2", "status": "inProgress", "rootTurnId": "turn-1", "items": []}
        daemon = self.use(FakeDaemon([thread], {thread["id"]: [running]}))
        plain, lists = daemon.request, []

        def request(method, params):
            if method == "thread/turns/list":
                lists.append(1)
                if len(lists) == 2:  # mid-wait, a restart cuts turn-1 off and Codex carries it on
                    daemon.turns[thread["id"]] = [cont, cut]
                if len(lists) == 3:  # after following turn-1 to turn-2, the connection drops
                    # and by the time it's back, turn-1 has left the listing
                    daemon.turns[thread["id"]] = [dict(cont, status="completed", items=[agent("kept", "final_answer")])]
                    raise BrokenPipeError("pipe closed")
            return plain(method, params)
        daemon.request = request
        with mock.patch.object(server.time, "sleep"):
            code, out = self.run_waiter(thread["id"], "turn-1")
        self.assertEqual(code, 0)
        self.assertIn("kept", out)
        self.assertIn("Turn turn-1 was interrupted and Codex carried it on as turn turn-2", out)
        self.assertIn("connection to the Codex daemon dropped", out)

    def test_waiter_says_when_the_daemon_was_updated(self):
        thread, daemon = self.restarted("cont09")
        final = daemon.turns[thread["id"]]
        daemon.turns[thread["id"]] = [{"id": "turn-1", "status": "inProgress", "items": [user("q")]}]
        plain, lists, versions = daemon.request, [], iter(["0.170.0", "0.171.0"])

        def request(method, params):
            if method == "thread/turns/list":
                lists.append(1)
                if len(lists) == 2:  # the update restarts the daemon mid-wait; Codex carries turn-1 on
                    daemon.turns[thread["id"]] = final
                    raise BrokenPipeError("pipe closed")
            return plain(method, params)
        daemon.request = request

        def connect():
            daemon.info = {"userAgent": f"codex_app_server/{next(versions)}"}
            return daemon
        self.use(connect)
        with mock.patch.object(server.time, "sleep"):
            code, out = self.run_waiter(thread["id"], "turn-1")
        self.assertEqual(code, 0)
        self.assertIn("carried-on answer", out)
        self.assertIn("changed version during the wait (0.170.0 -> 0.171.0)", out)

    def test_send_follows_its_message_into_a_continuation(self):
        thread = self.consultant("cont10")
        daemon = self.use(FakeDaemon([thread]))
        plain = daemon.request

        def request(method, params):
            out = plain(method, params)
            if method == "turn/start":  # the turn is cut off and our message carried into a new one
                turns = daemon.turns[thread["id"]]
                turns[0]["status"] = "interrupted"
                turns.insert(0, {"id": "turn-cont", "status": "completed",
                                 "items": [user(params["input"][0]["text"]), agent("steered answer", "final_answer")]})
            return out
        daemon.request = request
        out = server.send_consultant_message({"kind": "other", "to": thread["id"], "message": "hi", "wait": 5})
        self.assertIn("steered answer", out)

    def test_send_wait_bounds_the_grace(self):
        thread = self.consultant("cont11")
        daemon = self.use(FakeDaemon([thread]))
        plain = daemon.request

        def request(method, params):
            out = plain(method, params)
            if method == "turn/start":  # cut off at once, and never carried on
                daemon.turns[thread["id"]][0]["status"] = "interrupted"
            return out
        daemon.request = request
        started = time.monotonic()
        out = server.send_consultant_message({"kind": "other", "to": thread["id"], "message": "hi", "wait": 0.1})
        self.assertLess(time.monotonic() - started, 0.45)
        self.assertIn("turn-new interrupted", out)
        self.assertIn("GetConsultantReply with turn_id turn-new follows it there", out)

    def test_an_adjacent_turn_with_its_own_message_is_not_a_continuation(self):
        # turn-3 comes right after turn-2 and shares its root, but someone started it with other work.
        thread = self.consultant("cont18")
        turns = [{"id": "turn-3", "status": "completed", "rootTurnId": "turn-1", "items": [user("other work"), agent("wrong", "final_answer")]},
                 {"id": "turn-2", "status": "interrupted", "rootTurnId": "turn-1", "items": []},
                 {"id": "turn-1", "status": "interrupted", "items": [user("q")]}]
        self.use(FakeDaemon([thread], {thread["id"]: turns}))
        self.assertIsNone(server.next_in_chain(turns, turns[1]))
        self.assertIsNone(server.next_in_chain(turns, turns[1], "not there"))  # a send whose text is absent
        code, out = self.run_waiter(thread["id"], "turn-2")
        self.assertNotIn("wrong", out)
        out = server.get_consultant_reply({"to": thread["id"], "turn_id": "turn-2"})
        self.assertNotIn("wrong", out)

    def test_waiter_keeps_a_continuation_that_a_message_steers_later(self):
        thread = self.consultant("cont19")
        cut = {"id": "turn-1", "status": "interrupted", "items": [user("q")]}
        cont = {"id": "turn-2", "status": "inProgress", "rootTurnId": "turn-1", "items": []}
        daemon = self.use(FakeDaemon([thread], {thread["id"]: [cont, cut]}))
        plain, lists = daemon.request, []

        def request(method, params):
            if method == "thread/turns/list":
                lists.append(1)
                if len(lists) == 3:  # after the waiter followed turn-2, a message steers it, then it ends
                    cont.update(status="completed", items=[user("steer"), agent("steered on", "final_answer")])
            return plain(method, params)
        daemon.request = request
        with mock.patch.object(server.time, "sleep"):
            code, out = self.run_waiter(thread["id"], "turn-1")
        self.assertIn("steered on", out)
        self.assertIn("carried it on as turn turn-2", out)

    def test_reply_wait_finds_a_turn_pushed_out_of_the_newest_ten(self):
        thread = self.consultant("cont20")
        running = {"id": "turn-1", "status": "inProgress", "items": [user("q")]}
        daemon = self.use(FakeDaemon([thread], {thread["id"]: [running]}))
        plain, lists = daemon.request, []

        def request(method, params):
            if method == "thread/turns/list":
                lists.append(1)
                if len(lists) == 2:  # cut off and carried on, then a dozen other turns arrive
                    cont = {"id": "turn-2", "status": "completed", "rootTurnId": "turn-1",
                            "items": [agent("found it", "final_answer")]}
                    newer = [{"id": f"turn-n{n}", "status": "completed", "items": [user("x"), agent("x", "final_answer")]}
                             for n in range(12)]
                    daemon.turns[thread["id"]] = newer + [cont, dict(running, status="interrupted")]
            return plain(method, params)
        daemon.request = request
        with mock.patch.object(server.time, "sleep"):
            out = server.get_consultant_reply({"to": thread["id"], "turn_id": "turn-1", "wait": 5})
        self.assertIn("found it", out)

    def test_reply_shows_the_turn_codex_carried_on(self):
        thread, _ = self.restarted("cont12")
        out = server.get_consultant_reply({"to": thread["id"], "turn_id": "turn-1"})
        self.assertIn("Turn turn-1 was interrupted and Codex carried it on as turn turn-2", out)
        self.assertIn("carried-on answer", out)

    def test_an_offset_past_a_continuations_end_says_only_that(self):
        thread, _ = self.restarted("cont13")
        out = server.get_consultant_reply({"to": thread["id"], "turn_id": "turn-1", "offset": 10 ** 6})
        self.assertIn("past its end", out)
        self.assertNotIn("carried it on", out)  # no reply is shown, so there's nothing to introduce
        out = server.get_consultant_reply({"to": thread["id"], "turn_id": "turn-1", "offset": 1})
        self.assertTrue(out.startswith("(Turn turn-1 was interrupted and Codex carried it on as turn turn-2"), out)

    def test_reply_finds_a_continuation_among_older_turns(self):
        thread, daemon = self.restarted("cont13")
        newer = [{"id": f"turn-n{n}", "status": "completed", "items": [user("x"), agent("x", "final_answer")]} for n in range(12)]
        daemon.turns[thread["id"]] = newer + daemon.turns[thread["id"]]
        out = server.get_consultant_reply({"to": thread["id"], "turn_id": "turn-1"})
        self.assertIn("carried-on answer", out)

    def test_reply_with_a_wait_follows_a_continuation_that_starts_late(self):
        thread = self.consultant("cont14")
        cut = {"id": "turn-1", "status": "interrupted", "items": [user("q")]}
        daemon = self.use(FakeDaemon([thread], {thread["id"]: [cut]}))
        self.appear_after(daemon, thread["id"], 3, {"id": "turn-2", "status": "completed", "rootTurnId": "turn-1",
                                                     "items": [agent("late answer", "final_answer")]})
        out = server.get_consultant_reply({"to": thread["id"], "turn_id": "turn-1", "wait": 5})
        self.assertIn("late answer", out)
        self.assertIn("carried it on as turn turn-2", out)

    def test_reply_without_a_wait_returns_an_interrupted_turn_at_once(self):
        thread = self.consultant("cont15")
        cut = {"id": "turn-1", "status": "interrupted", "items": [user("q")]}
        self.use(FakeDaemon([thread], {thread["id"]: [cut]}))
        with mock.patch.object(server.time, "sleep") as sleep:
            out = server.get_consultant_reply({"to": thread["id"], "turn_id": "turn-1"})
        sleep.assert_not_called()
        self.assertIn("turn-1 interrupted", out)

    def test_reply_names_the_turn_it_ends_on(self):
        # turn-1 was carried on as turn-2, which is cut off in turn during the wait and carried on as turn-3.
        thread = self.consultant("cont16")
        cut = {"id": "turn-1", "status": "interrupted", "items": [user("q")]}
        running = {"id": "turn-2", "status": "inProgress", "rootTurnId": "turn-1", "items": []}
        daemon = self.use(FakeDaemon([thread], {thread["id"]: [running, cut]}))
        plain, lists = daemon.request, []

        def request(method, params):
            if method == "thread/turns/list":
                lists.append(1)
                if len(lists) == 3:
                    running["status"] = "interrupted"
                    daemon.turns[thread["id"]].insert(0, {"id": "turn-3", "status": "completed", "rootTurnId": "turn-1",
                                                          "items": [agent("final words", "final_answer")]})
            return plain(method, params)
        daemon.request = request
        out = server.get_consultant_reply({"to": thread["id"], "turn_id": "turn-1", "wait": 5})
        self.assertIn("final words", out)
        self.assertIn("carried it on as turn turn-3", out)
        self.assertNotIn("as turn turn-2", out)

    def test_history_names_a_turn_codex_carried_on(self):
        thread, daemon = self.restarted("cont17")
        out = server.get_consultant_history({"to": thread["id"]})
        self.assertIn("turn-2 [completed] Codex carrying on the work of turn turn-1, with no new message "
                      "-> \"carried-on answer\"", out)
        self.assertNotIn("someone typing in Codex", out.splitlines()[1])
        daemon.turns[thread["id"]][0]["items"].insert(0, user(
            "[Message from lead via the consultants bridge]\nand also this"))
        daemon.turns[thread["id"]].append({"id": "turn-0", "status": "completed", "items": []})
        out = server.get_consultant_history({"to": thread["id"]})
        self.assertIn('from lead: "and also this" (Codex carrying on the work of turn turn-1)', out)
        self.assertIn("turn-0 [completed] with no message", out)

    def test_waits_report_progress(self):
        thread = self.consultant("prog01")
        self.use(FakeDaemon([thread]))
        notes = []
        server.send_consultant_message({"kind": "other", "to": thread["id"], "message": "hi", "wait": 0.01}, None, notes.append)
        self.assertTrue(notes)
        self.assertIn("is working on turn turn-new", notes[0])
        self.assertTrue(notes[0].endswith(": working on it"))
        notes.clear()
        server.get_consultant_reply({"to": thread["id"], "wait": 0.01}, None, notes.append)
        self.assertIn("is working on turn turn-new", notes[0])


class ShellWordTest(unittest.TestCase):
    def test_shell_word_reads_back_in_each_shell(self):
        """0.18.0: a path with spaces, $, a backtick or a quote is one literal word in bash and PowerShell."""
        import base64
        paths = ["/opt/py/python3", "/My Tools/server.py", "/a$HOME/b`x`/s.py", "/O'Neil/s.py",
                 "/it's $HOME/q’s/s.py", "/x(y);z&w/s.py", "/José/s.py", '/say "hi"/s.py']
        folder = tempfile.mkdtemp()
        echo = os.path.join(folder, "echo it.py")  # a space, so its own path is quoted too
        with open(echo, "w", encoding="utf-8") as f:
            f.write("import sys\nsys.stdout.buffer.write(sys.argv[1].encode('utf-8'))\n")

        def line(shell, path):  # the waiter's shape: interpreter, script, argument
            words = [server.shell_word(x, shell) for x in (sys.executable, echo, path)]
            return ("& " if shell == "powershell" else "") + " ".join(words)
        shells = []
        bash = shutil.which("bash")
        if os.name == "nt":  # Git Bash, the shell Claude Code runs; System32's bash.exe is WSL's
            git, tops = shutil.which("git"), []
            while git and os.path.dirname(git) != git and len(tops) < 3:  # Git\cmd\git.exe, Git\mingw64\bin\git.exe
                git = os.path.dirname(git)
                tops.append(os.path.join(git, "bin", "bash.exe"))
            bash = next((b for b in tops[1:] if os.path.isfile(b)), None)
        if bash:
            shells.append(("bash", lambda cmd: [bash, "-c", cmd]))
        ps = shutil.which("powershell") or shutil.which("pwsh")
        if ps:
            shells.append(("powershell", lambda cmd: [ps, "-NoProfile", "-NonInteractive", "-EncodedCommand",
                                                      base64.b64encode(cmd.encode("utf-16-le")).decode()]))
        if not shells:
            self.skipTest("neither bash nor PowerShell is installed")
        for shell, argv in shells:
            for path in paths:
                if shell == "powershell" and '"' in path and os.name == "nt":
                    continue  # Windows paths can't hold a double quote, and PowerShell 5.1 drops it on the way to a program
                cmd = line(shell, path)
                env = dict(os.environ, MSYS_NO_PATHCONV="1", MSYS2_ARG_CONV_EXCL="*")  # Git Bash: leave /paths alone
                got = subprocess.run(argv(cmd), capture_output=True, timeout=60, env=env).stdout.decode("utf-8")
                self.assertEqual(got, path, (shell, cmd))
        self.assertIsNone(server.shell_word("/a\nb", "bash"))

    def test_waiter_command_per_shell(self):
        with mock.patch.object(server.sys, "executable", "/opt/py/python3"), \
             mock.patch.object(server.os.path, "abspath", return_value="/home/o'neil $x/nouez/server.py"):
            cmd = server.waiter_command("t1", "u1")
            self.assertIn("(In PowerShell: & /opt/py/python3 -I '/home/o''neil", cmd)
            with mock.patch.object(server.os, "name", "nt"):
                rules = server.allow_rules()
            self.assertEqual(len(rules), 2)
            self.assertIn("o'" + chr(92) + "''neil", rules[0])  # bash's escape of a single quote
            self.assertIn("o''neil", rules[1])  # PowerShell's


class LaunchTest(unittest.TestCase):
    """0.18.0: a pane or window whose launcher fails says so, rather than claiming it opened."""

    def test_launch_reports_failure(self):
        quick_fail = [sys.executable, "-c", "import sys; sys.stderr.write('no display: :0'); sys.exit(3)"]
        with self.assertRaises(server.BridgeError) as e:
            server.launch(quick_fail, "xterm", stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        self.assertIn("xterm didn't open (exit code 3: no display: :0)", str(e.exception))
        self.assertEqual(server.launch([sys.executable, "-c", "pass"], "Terminal"), "Terminal")
        slow = [sys.executable, "-c", "import time; time.sleep(5)"]
        import warnings
        with mock.patch.object(server, "LAUNCH_GRACE", 0.3), warnings.catch_warnings():
            warnings.simplefilter("ignore", ResourceWarning)  # the window process is left running, as a real one is
            started = time.monotonic()
            self.assertEqual(server.launch(slow, "kitty"), "kitty")  # still running: taken as open
            self.assertLess(time.monotonic() - started, 3)

    def test_applescript_gets_text_as_an_argument(self):
        script = '''cd '/tmp/a "b"' && codex resume x" & do shell script "touch /tmp/pwned'''
        argv = server.apple_terminal(script)
        self.assertEqual(argv[-1], script)
        source = " ".join(argv[1:-1])
        self.assertNotIn("pwned", source)
        self.assertIn("do script (item 1 of argv)", source)
        self.assertNotIn("activate", " ".join(server.apple_terminal("x", activate=False)))

    def test_linux_terminal(self):
        argv = ["claude", "--name", "x"]
        with mock.patch.object(server.sys, "platform", "linux"), mock.patch.object(server.os, "name", "posix"), \
                mock.patch.dict(server.os.environ, {"DISPLAY": ":0"}):
            with mock.patch.object(server, "which", lambda name, env=None: {"wezterm": "/usr/bin/wezterm"}.get(name)):
                self.assertEqual(server.linux_terminal(argv),
                                 (["/usr/bin/wezterm", "start", "--", "claude", "--name", "x"], "wezterm"))
            with mock.patch.object(server, "which", lambda name, env=None: None):
                with self.assertRaisesRegex(server.BridgeError,
                                            "No terminal emulator found \\(x-terminal-emulator, gnome-terminal, konsole"):
                    server.linux_terminal(argv)
            with mock.patch.object(server, "which", lambda name, env=None: {"xterm": "/usr/bin/xterm"}.get(name)), \
                    mock.patch.dict(server.os.environ, {"DISPLAY": "", "WAYLAND_DISPLAY": ""}):
                with self.assertRaisesRegex(server.BridgeError, "there is no display"):
                    server.linux_terminal(argv)

    def test_linux_terminals_and_display(self):
        found = {"kitty": "/usr/bin/kitty", "xterm": "/usr/bin/xterm"}
        with mock.patch.object(server, "which", lambda name, env=None: found.get(name)):
            self.assertEqual(server.terminal_emulator(), ("/usr/bin/kitty", []))
        with mock.patch.object(server, "which", lambda name, env=None: None):
            self.assertEqual(server.terminal_emulator(), (None, None))
        with mock.patch.object(server.sys, "platform", "linux"), mock.patch.object(server.os, "name", "posix"):
            with mock.patch.dict(server.os.environ, {"DISPLAY": "", "WAYLAND_DISPLAY": ""}):
                self.assertIn("no display", server.no_display())
            with mock.patch.dict(server.os.environ, {"WAYLAND_DISPLAY": "wayland-0"}):
                self.assertEqual(server.no_display(), "")

class PosixCloseTest(unittest.TestCase):
    """0.18.0: on macOS and Linux CloseClaudeSession signals only a confirmed Claude Code session."""

    def fake_ps(self, procs):
        def run_text(argv, timeout=20):
            if argv[0] != "ps":
                return ""
            field, pid = argv[2].rstrip("="), int(argv[-1])
            return str(procs.get(pid, {}).get(field, ""))
        return run_text

    def target(self, pid=500, registered=None):
        return {"pid": pid, "name": "work", "registered": registered if registered is not None else (time.time() - 60) * 1000}

    def setUp(self):
        self.real_match = server.registry_entry_matches
        patcher = mock.patch.object(server, "registry_entry_matches", lambda target: True)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_identity_checks(self):
        claude = {"ppid": 1, "etime": "02:00", "comm": "claude", "args": "claude --resume x"}
        node = {"ppid": 1, "etime": "1-00:00:00", "comm": "node", "args": "node /usr/lib/node_modules/@anthropic-ai/claude-code/cli.js"}
        native = {"ppid": 1, "etime": "02:00", "comm": "2.1.325", "args": "/home/u/.local/share/claude/versions/2.1.325"}
        other = {"ppid": 1, "etime": "02:00", "comm": "vim", "args": "vim notes"}
        young = {"ppid": 1, "etime": "00:10", "comm": "claude", "args": "claude"}
        helper = {"ppid": 1, "etime": "02:00", "comm": "claude-helper", "args": "claude-helper"}
        mention = {"ppid": 1, "etime": "02:00", "comm": "node", "args": "node build.js --out claude-code"}
        # 0.18.0: under claude/versions only a version the native installer names, not any program
        planted = {"ppid": 1, "etime": "02:00", "comm": "tool", "args": "/tmp/claude/versions/x/tool"}
        for proc, want in ((claude, ""), (node, ""), (native, ""), (other, "not Claude Code"), (young, "can't show that the process started before"),
                           (helper, "not Claude Code"), (mention, "not Claude Code"), (planted, "not Claude Code"),
                           (None, "has ended")):
            procs = {500: proc, 900: {"ppid": 1}} if proc else {900: {"ppid": 1}}
            with mock.patch.object(server, "run_text", self.fake_ps(procs)), mock.patch.object(server.os, "getppid", lambda: 900):
                got = server.posix_session_problem(self.target())
            self.assertIn(want, got) if want else self.assertEqual(got, "")
        with mock.patch.object(server, "run_text", self.fake_ps({500: claude})):
            self.assertIn("doesn't say when", server.posix_session_problem({"pid": 500, "name": "w", "registered": None}))
        # 0.18.0: an ancestor ps can't show means the caller can't be ruled out, so nothing is signalled.
        with mock.patch.object(server, "run_text", self.fake_ps({500: claude})), mock.patch.object(server.os, "getppid", lambda: 900):
            self.assertIn("can't rule out", server.posix_session_problem(self.target()))

    def test_a_replaced_registry_entry_is_refused(self):
        """0.18.0: a new Claude Code process with the pid writes its own entry; the old session is then gone."""
        folder = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, folder, True)
        os.makedirs(os.path.join(folder, "sessions"))
        target = {"pid": 500, "name": "work", "registered": 1000, "session_id": "s-1"}
        with mock.patch.object(server, "claude_config_dir", lambda: folder):
            self.assertFalse(self.real_match(target))
            for entry, want in (({"startedAt": 1000, "sessionId": "s-1"}, True),
                                ({"startedAt": 2000, "sessionId": "s-2"}, False)):
                with open(os.path.join(folder, "sessions", "500.json"), "w") as f:
                    json.dump({"pid": 500, **entry}, f)
                self.assertEqual(self.real_match(target), want)

    def test_an_ancestor_is_refused(self):
        procs = {700: {"ppid": 500, "etime": "02:00", "comm": "node", "args": "node nouez"},
                 500: {"ppid": 1, "etime": "05:00", "comm": "claude", "args": "claude"}}
        with mock.patch.object(server, "run_text", self.fake_ps(procs)), mock.patch.object(server.os, "getppid", lambda: 700):
            self.assertEqual(server.posix_ancestors(), [700, 500])
            self.assertIn("runs under", server.posix_session_problem(self.target()))

    def test_end_session_signals_only_when_confirmed(self):
        killed = []
        with mock.patch.object(server.os, "name", "posix"), mock.patch.object(server, "posix_session_problem", lambda t: "it has ended"), \
             mock.patch.object(server.os, "kill", lambda pid, sig: killed.append(pid), create=True):
            with self.assertRaises(server.BridgeError) as e:
                server.end_session(self.target())
        self.assertIn("Nothing was signalled", str(e.exception))
        self.assertEqual(killed, [])


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

    def test_failed_wt_is_reported(self):  # 0.18.0: a wt.exe that fails isn't taken for an open pane
        with mock.patch.object(server, "which", return_value="wt"), \
                mock.patch.object(server.os, "name", "nt"), \
                mock.patch.object(server.subprocess, "Popen") as popen:
            popen.return_value.wait.return_value = 1
            with self.assertRaisesRegex(server.BridgeError, "didn't open \\(exit code 1"):
                server.open_window("C:/a", ["claude"], "Claude: x")

    def test_console_without_wt_is_checked(self):
        """0.18.0: without wt, the console's own process is watched for a quick failure. 0.23.0: it
        leaves its job only under the phone dispatcher's supervisor."""
        for wait, want, under in ((mock.Mock(return_value=2), "closed at once \\(exit code 2", False),
                                  (mock.Mock(side_effect=subprocess.TimeoutExpired("x", 1)), None, False),
                                  (mock.Mock(side_effect=subprocess.TimeoutExpired("x", 1)), None, True)):
            with mock.patch.object(server, "which", return_value=None), mock.patch.object(server.os, "name", "nt"), \
                    mock.patch.object(server, "in_dispatcher_job", lambda: under), \
                    mock.patch.object(server.subprocess, "CREATE_NEW_CONSOLE", 16, create=True), \
                    mock.patch.object(server.subprocess, "Popen") as popen:
                popen.return_value.wait = wait
                if want:
                    with self.assertRaisesRegex(server.BridgeError, want):
                        server.open_window("C:/a", ["claude"], "Claude: x")
                else:
                    self.assertEqual(server.open_window("C:/a", ["claude"], "Claude: x"), "a new console window")
            self.assertEqual(popen.call_args.kwargs["creationflags"], 16 | (0x01000000 if under else 0))

    def test_semicolons_are_escaped_for_wt(self):
        self.assertEqual(server.wt_escape("demo;calc.exe;"), "demo\\;calc.exe\\;")
        with mock.patch.object(server, "which", return_value="wt"), \
                mock.patch.object(server.os, "name", "nt"), \
                mock.patch.object(server.subprocess, "Popen") as popen:
            popen.return_value.wait.return_value = 0
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

    def run_helper(self, prompt, returncode=0, closed=False, extra=None, exe="claude"):
        fd, spec = tempfile.mkstemp(prefix="nouez-claude-", suffix=".json")
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(dict({"cwd": ROOT, "name": "n", "prompt": prompt}, **(extra or {})), f)
        child = mock.Mock(pid=999999)
        child.wait.return_value = returncode
        marker = server.close_marker(999999)
        if closed:
            open(marker, "w").close()
        with mock.patch.object(server, "find_program", return_value=exe), \
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

    def test_batch_claude_gets_no_prompt(self):
        """0.18.0: cmd would read a prompt's quotes, % and & as its own syntax, so it is shown instead."""
        with contextlib.redirect_stdout(io.StringIO()) as out:
            argv, _ = self.run_helper('x" & calc & "', exe="C:/npm/claude.CMD")
        self.assertEqual(argv, ["C:/npm/claude.CMD", "--remote-control", "n", "--name", "n"])
        self.assertIn("Paste it into the session yourself", out.getvalue())
        self.assertIn('x" & calc & "', out.getvalue())

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

    def test_resume_is_passed_as_a_checked_id(self):
        sid = "4b4f3c8c-0010-4e93-a427-9db7032f2be3"
        argv, _ = self.run_helper("hi", extra={"resume": sid})
        self.assertEqual(argv, ["claude", "--remote-control", "n", "--name", "n", "--resume", sid, "--", "hi"])
        fd, spec = tempfile.mkstemp(prefix="nouez-claude-", suffix=".json")
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump({"cwd": ROOT, "name": "n", "prompt": "", "resume": "--dangerously-skip-permissions"}, f)
        with mock.patch.object(server, "find_program", return_value="claude"), \
                mock.patch.object(server.subprocess, "Popen") as popen, mock.patch("builtins.input"), \
                contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(server.run_claude(spec), 1)
        popen.assert_not_called()

    def open_resumed(self, config, resume, running=(), prompt=""):
        with mock.patch.dict(server.os.environ, {"CLAUDE_CONFIG_DIR": config}), \
                mock.patch.object(server, "open_window", return_value="a window") as open_window, \
                mock.patch.object(server, "folder_trusted", return_value=True), \
                mock.patch.object(server, "claude_sessions", return_value=list(running)):
            out = server.open_claude_session({"cwd": ROOT, "resume": resume, "prompt": prompt})
        path = open_window.call_args[0][1][-1]
        with open(path, encoding="utf-8") as f:
            spec = json.load(f)
        os.remove(path)
        return spec, out

    def test_transcript_labels_read_only_complete_records_at_the_edges(self):
        edge, cap = 256, 96

        def title(text):
            return json.dumps({"type": "custom-title", "customTitle": text}).encode()

        head = title("old") + b"\r\n"
        middle = b"x" * (8 * edge)
        # The tail starts at a valid-looking object, but it is part of an oversized line.
        branch = b'{"gitBranch":"wrong"}\n'
        tail = branch + b" " * (edge - len(branch) - len(title("latest")) - 1) + b"\n" + title("latest")

        class BoundedStream(io.BytesIO):
            total = 0

            def readline(self, size=-1):
                if not 0 < size <= cap + 1:
                    raise AssertionError(f"unbounded line read: {size}")
                data = super().readline(size)
                self.total += len(data)
                return data

        stream = BoundedStream(head + middle + tail)
        with mock.patch.object(server, "TRANSCRIPT_EDGE_BYTES", edge), \
                mock.patch.object(server, "TRANSCRIPT_LINE_BYTES", cap), \
                mock.patch("builtins.open", return_value=stream):
            self.assertEqual(server.transcript_labels("unused", None), ("latest", ""))
        self.assertEqual(stream.total, 2 * edge)
        stop = mock.Mock()
        stop.is_set.side_effect = [False, False, True]
        with self.assertRaises(server.Cancelled):
            list(server.transcript_lines(io.BytesIO(head + middle), stop))

    def test_transcript_folder_unknown_when_an_earlier_record_is_unreadable(self):
        # /work/a-b and /work/a_b share a transcript folder: a later record's folder isn't the
        # conversation's when the one before it was left out for its size or couldn't be parsed.
        self.assertEqual(server.transcript_folder("/work/a-b"), server.transcript_folder("/work/a_b"))
        big = json.dumps({"cwd": "/work/a-b", "pad": "x" * 200}).encode() + b"\n"
        later = json.dumps({"cwd": "/work/a_b"}).encode() + b"\n"
        with tempfile.TemporaryDirectory() as d, mock.patch.object(server, "TRANSCRIPT_LINE_BYTES", 100):
            for name, data, cwd in (("ok", b'{"type":"summary"}\n' + later, "/work/a_b"),
                                    ("big", big + later, None), ("bad", b'{"cwd": "/work/a-b"\n' + later, None),
                                    ("damaged", b'{"c\xffwd": "/work/a-b"}\n' + later, None)):
                path = os.path.join(d, name)
                with open(path, "wb") as f:
                    f.write(data)
                with self.subTest(name):
                    self.assertEqual(server.transcript_cwd(path), cwd)
                    self.assertEqual(server.ran_here(path, "/work/a_b"), bool(cwd))

    def test_list_saved_conversations(self):
        ids = [f"aaaaaaaa-0000-0000-0000-{i:012d}" for i in range(13)]
        busy = dict(self.session("busy", 41), session_id=ids[11].upper())
        with tempfile.TemporaryDirectory() as config, \
                mock.patch.dict(server.os.environ, {"CLAUDE_CONFIG_DIR": config}), \
                mock.patch.object(server, "claude_sessions", return_value=[busy]), \
                mock.patch.object(server, "own_claude_pids", return_value=set()), \
                mock.patch.object(server, "with_login_warning", side_effect=lambda text: text):
            cwd = os.path.join(config, "a-b")
            os.mkdir(cwd)
            folder = server.transcript_folder(cwd)
            os.makedirs(folder)
            for i, sid in enumerate(ids):
                path = os.path.join(folder, sid + ".jsonl")
                ran_in = os.path.join(config, "a_b") if i == 12 else cwd
                with open(path, "w", encoding="utf-8") as f:
                    f.write(json.dumps({"cwd": ran_in, "message": "private prompt"}) + "\n")
                    if i == 11:
                        for title in ("Old title", "New\ntitle --token synthetic-credential"):
                            f.write(json.dumps({"type": "custom-title", "customTitle": title}) + "\n")
                        f.write(json.dumps({"gitBranch": "topic"}) + "\n")
                os.utime(path, (1000 + i, 1000 + i))
            broken = "ffffffff-0000-0000-0000-000000000000"
            with open(os.path.join(folder, broken + ".jsonl"), "wb") as f:
                f.write(b"[" * 3000 + b"0" + b"]" * 3000 + b"\n")
            running = server.list_claude_sessions({})
            self.assertIn("busy (pid 41)", running)
            self.assertNotIn("Saved conversations", running)
            out = server.list_claude_sessions({"cwd": cwd})
            self.assertTrue(out.startswith(running))
            self.assertIn(f"{server.mtime_text(1011)} | {ids[11]} | open | title: New title --token *** | branch: topic", out)
            self.assertIn(f"{ids[10]} | not open", out)
            self.assertLess(out.index(ids[11]), out.index(ids[10]))
            self.assertIn(ids[2], out)
            for hidden in (ids[1], ids[12], broken, "private prompt", "Old title", "synthetic-credential"):
                self.assertNotIn(hidden, out)
            self.assertNotIn(ids[10], server.list_claude_sessions({"cwd": cwd, "limit": 1}))
            self.assertIn("No saved conversations", server.list_claude_sessions({"cwd": config}))
            two = server.list_claude_sessions({"cwd": cwd, "limit": 2.0})
            self.assertIn(ids[10], two)
            self.assertNotIn(ids[9], two)
            for bad in (0, 51, 2.5, True, "2"):
                with self.assertRaises(server.BridgeError):
                    server.list_claude_sessions({"cwd": cwd, "limit": bad})
            for args in ({"cwd": "relative"}, {"limit": 3}):
                with self.assertRaises(server.BridgeError):
                    server.list_claude_sessions(args)

    def test_resume_finds_the_conversation(self):
        old, new = "11111111-1111-1111-1111-111111111111", "22222222-2222-2222-2222-222222222222"
        with tempfile.TemporaryDirectory() as config:
            with mock.patch.dict(server.os.environ, {"CLAUDE_CONFIG_DIR": config}):
                folder = server.transcript_folder(os.path.abspath(ROOT))
            os.makedirs(folder)
            for i, sid in enumerate((old, new)):
                path = os.path.join(folder, sid + ".jsonl")
                with open(path, "w") as f:
                    f.write(json.dumps({"cwd": ROOT}) + "\n")
                os.utime(path, (1000 + i, 1000 + i))
            # 0.28: no "latest": the user always picks from ListClaudeSessions' list.
            with self.assertRaisesRegex(server.BridgeError, "ListClaudeSessions with cwd"):
                self.open_resumed(config, "latest")
            busy = dict(self.session("busy", 41), session_id=new)
            spec, out = self.open_resumed(config, old.upper())
            self.assertEqual(spec["resume"], old)
            self.assertIn(f"resumes conversation {old}", out)
            with mock.patch.object(server.os.path, "samefile", lambda a, b: False):  # a case-sensitive Repo and repo
                with self.assertRaisesRegex(server.BridgeError, "ran in"):
                    self.open_resumed(config, old)
            for bad, running in (("--fork-session", ()), (new, [busy]),
                                 ("33333333-3333-3333-3333-333333333333", ()), (5, ())):
                with self.assertRaises(server.BridgeError):
                    self.open_resumed(config, bad, running)
            other = os.path.join(config, "projects", "elsewhere")
            os.makedirs(other)
            third = "44444444-4444-4444-4444-444444444444"
            with open(os.path.join(other, third + ".jsonl"), "w") as f:
                f.write(json.dumps({"type": "summary"}) + "\n" + json.dumps({"cwd": "C:/elsewhere"}) + "\n")
            with self.assertRaisesRegex(server.BridgeError, "ran in C:/elsewhere"):
                self.open_resumed(config, third)
            with self.assertRaisesRegex(server.BridgeError, "pass its id as resume"):
                self.open_resumed(config, None, prompt="/resume " + old)

    def test_resume_checks_the_folder_each_transcript_recorded(self):
        # C:\a-b and C:\a_b share a transcript folder, so a file there can belong to another folder.
        mine, theirs = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee", "ffffffff-1111-2222-3333-444444444444"
        with tempfile.TemporaryDirectory() as config:
            with mock.patch.dict(server.os.environ, {"CLAUDE_CONFIG_DIR": config}):
                folder = server.transcript_folder(os.path.abspath(ROOT))
            os.makedirs(folder)
            for i, (sid, ran_in) in enumerate(((mine, ROOT), (theirs, ROOT + "_twin"))):
                path = os.path.join(folder, sid + ".jsonl")
                with open(path, "w") as f:
                    f.write(json.dumps({"cwd": ran_in}) + "\n")
                os.utime(path, (1000 + i, 1000 + i))
            spec, out = self.open_resumed(config, mine.upper())
            self.assertEqual(spec["resume"], mine)
            with self.assertRaisesRegex(server.BridgeError, "ran in .*_twin"):
                self.open_resumed(config, theirs)
            # A transcript that doesn't say where it ran isn't taken by its id: in this shared folder
            # it may be the twin's.
            unknown = "cccccccc-dddd-eeee-ffff-000000000000"
            path = os.path.join(folder, unknown + ".jsonl")
            with open(path, "w") as f:
                f.write(json.dumps({"type": "summary"}) + "\n")
            with self.assertRaisesRegex(server.BridgeError, "doesn't say which folder it ran in"):
                self.open_resumed(config, unknown)

    def test_resume_is_refused_when_running_sessions_cant_be_read(self):
        sid = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
        with mock.patch.object(server, "open_window") as open_window, \
                mock.patch.object(server, "folder_trusted", return_value=True), \
                mock.patch.object(server, "claude_sessions", side_effect=OSError("registry unreadable")):
            with self.assertRaisesRegex(server.BridgeError, "already open"):
                server.open_claude_session({"cwd": ROOT, "resume": sid})
            open_window.assert_not_called()
            open_window.return_value = "a window"
            server.open_claude_session({"cwd": ROOT})  # a new conversation still opens
        os.remove(open_window.call_args[0][1][-1])

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
                                            "prompt": "a; b \"c\"", "model": "opus", "effort": "medium",
                                            "arrange": True})
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
            self.made = out
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
            # 0.28 (#15): a made folder is a project: git (no sample hooks) and a starter CLAUDE.md,
            # with its trust report still empty.
            with open(os.path.join(cwd, "CLAUDE.md"), encoding="utf-8") as f:
                self.assertTrue(f.read().startswith("# economic recession\n\nWhat this project is"))
            if server.which("git"):
                self.assertIn("Made it a git repository", self.made)
                self.assertTrue(os.path.isdir(os.path.join(cwd, ".git")))
                self.assertFalse(os.path.exists(os.path.join(cwd, ".git", "hooks", "pre-commit.sample")))
            self.assertTrue(server.config_review([cwd])[0].startswith("No project"))
            # Inside a git work tree: no repository of its own. Without git: said, and it opens anyway.
            inner = os.path.join(cwd, "sub")
            with mock.patch.object(server, "open_window", return_value=None), \
                    mock.patch.object(server, "folder_trusted", return_value=False):
                out = server.open_claude_session({"cwd": inner, "create": True})
            self.assertFalse(os.path.exists(os.path.join(inner, ".git")))
            self.assertNotIn("git", out.split("Not opened")[0])
            alone = os.path.join(parent, "no-git")
            with mock.patch.object(server, "which", lambda name, env=None: None), \
                    mock.patch.object(server, "open_window", return_value=None), \
                    mock.patch.object(server, "folder_trusted", return_value=False):
                out = server.open_claude_session({"cwd": alone, "create": True})
            self.assertIn("git isn't installed, so it isn't a git repository yet.", out)
            # A CLAUDE.md already there is kept as it is.
            with open(os.path.join(alone, "CLAUDE.md"), "w", encoding="utf-8") as f:
                f.write("mine")
            self.assertTrue(server.start_project(alone)[-1].startswith("Couldn't write a starter CLAUDE.md"))
            with open(os.path.join(alone, "CLAUDE.md"), encoding="utf-8") as f:
                self.assertEqual(f.read(), "mine")
            if server.which("git"):
                # The user's GIT_TEMPLATE_DIR (which outranks init.templateDir) puts no hook in, and a
                # GIT_DIR in nouez's environment doesn't send git init to another repository.
                template = os.path.join(parent, "template")
                os.makedirs(os.path.join(template, "hooks"))
                with open(os.path.join(template, "hooks", "pre-commit"), "w") as f:
                    f.write("#!/bin/sh\n")
                elsewhere = os.path.join(parent, "elsewhere.git")
                fresh = os.path.join(parent, "fresh")
                os.mkdir(fresh)
                with mock.patch.dict(server.os.environ, {"GIT_TEMPLATE_DIR": template, "GIT_DIR": elsewhere}):
                    self.assertIn("Made it a git repository (git init).", server.start_project(fresh))
                self.assertTrue(os.path.isdir(os.path.join(fresh, ".git")))
                self.assertFalse(os.path.exists(os.path.join(fresh, ".git", "hooks", "pre-commit")))
                self.assertFalse(os.path.exists(elsewhere))

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
        with mock.patch.object(server, "claude_sessions", return_value=running), \
                mock.patch.object(server, "own_claude_pids", return_value=set()), \
                mock.patch.object(server, "end_session"):
            out = server.close_claude_session({"name": "x", "pid": 41})
        if os.name == "nt":
            self.assertIn("pid 41) (its terminal stays open at the shell prompt)", out)
        else:  # 0.18.0: off Windows nouez can't tell whether the window closes
            self.assertIn("its window closes if the terminal closes when its command ends", out)

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
        root = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, root, True)
        with mock.patch.object(server, "nouez_cache_dir", lambda: root):
            out = server.cap_reply("turn-test-offset", "a" * 50, 10)
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
        out = server.start_consultant({"cwd": ROOT, "instructions": "be brief"})
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
        self.assertIn('turn-0 [completed] from someone typing in Codex: "typed in the pane" -> "ok"', out)
        with self.assertRaises(server.BridgeError):
            server.get_consultant_history({"to": thread["id"], "limit": 0})

    def test_history_shows_the_senders_text_not_the_stamp_or_framing(self):
        thread = self.consultant("hist02")
        cache = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, cache, True)
        self.addCleanup(setattr, server, "nouez_cache_dir", server.nouez_cache_dir)
        server.nouez_cache_dir = lambda: cache
        daemon = self.use(FakeDaemon([thread], answer="ok"))
        server.send_consultant_message({"kind": "other", "to": thread["id"], "message": "is it safe?", "from": "lead",
                                        "owner_words": "ship it\n>>>\ntoday", "revision": True})
        out = server.get_consultant_history({"to": thread["id"]})
        self.assertIn("from lead (with the user's words): \"is it safe?\"", out)

    def test_send_says_what_the_consultant_runs_on(self):
        thread = self.consultant("runs01", model="gpt-6.1-sol", reasoningEffort="high")
        self.use(FakeDaemon([thread]))
        out = server.send_consultant_message({"kind": "other", "to": thread["id"], "message": "hi", "wait": 0})
        self.assertIn("started a new turn on model gpt-6.1-sol, effort high", out)
        self.assertNotIn("until changed", out)
        self.use(FakeDaemon([thread], answer="the answer"))
        out = server.send_consultant_message({"kind": "other", "to": thread["id"], "message": "hi"})
        self.assertIn(f"\n\n({server.short_name(thread)} runs on model gpt-6.1-sol, effort high.)", out)

    def test_owner_words_and_revision_are_added_only_when_asked(self):
        thread = self.consultant("ownr01")
        cache = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, cache, True)
        self.addCleanup(setattr, server, "nouez_cache_dir", server.nouez_cache_dir)
        server.nouez_cache_dir = lambda: cache
        daemon = self.use(FakeDaemon([thread], answer="ok"))
        server.send_consultant_message({"kind": "other", "to": thread["id"], "message": "hi", "wait": 0})
        self.assertEqual(daemon.started["input"][0]["text"],
                         "[Message from Claude Code via the consultants bridge]\n\nhi")
        server.send_consultant_message({"kind": "other", "to": thread["id"], "message": "hi", "wait": 0, "from": "lead",
                                        "owner_words": "ship it today", "revision": True})
        text = daemon.started["input"][0]["text"]
        self.assertIn("The user's own words, as they typed them:\n<<<\nship it today\n>>>", text)
        self.assertIn("The rest of this message is lead's.\n\nhi", text)
        # " on <branch>" only when a branch is checked out: CI checks a tag out detached
        self.assertRegex(text, r"\[Revision: commit [0-9a-f]+( on \S+)?, \d+ uncommitted path\(s\)")
        with self.assertRaises(server.BridgeError):
            server.send_consultant_message({"kind": "other", "to": thread["id"], "message": "hi", "owner_words": 5})

    def test_full_thread_id_is_read_directly(self):
        thread = {"id": "0199aaaa-0000-0000-0000-0000000000c1", "cwd": ROOT, "threadSource": "nouez"}
        daemon = self.use(FakeDaemon([thread]))
        found = server.resolve(daemon, thread["id"].upper())
        self.assertEqual(found["id"], thread["id"])
        self.assertTrue(found["_loaded"])
        self.assertNotIn("thread/list", daemon.calls)


class RevisionTest(unittest.TestCase):
    """revision: true takes the uncommitted diff once and names it by its digest."""

    def setUp(self):
        self.repo = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.repo, True)
        self.cache = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.cache, True)
        patcher = mock.patch.object(server, "nouez_cache_dir", lambda: self.cache)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.git("init", "-q")
        for key, value in (("user.name", "t"), ("user.email", "t@example.invalid"), ("core.autocrlf", "false"),
                           ("diff.noprefix", "true")):  # a user's diff settings don't change the diff taken
            self.git("config", key, value)
        self.put("app.py", "a = 1\nb = 2\n")
        self.git("add", "app.py")
        self.git("commit", "-q", "-m", "first")

    def git(self, *args):
        return subprocess.run(["git", "-C", self.repo, *args], check=True, capture_output=True, text=True).stdout

    def put(self, rel, data):
        path = os.path.join(self.repo, rel)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "wb") as f:
            f.write(data.encode("utf-8") if isinstance(data, str) else data)

    def saved(self, digest):
        return os.path.join(self.cache, server.PATCH_FOLDER, f"{digest}.patch")

    def test_a_clean_tree_has_no_diff(self):
        line, patch, digest = server.revision(self.repo)
        self.assertRegex(line, r"^\[Revision: commit [0-9a-f]+( on \S+)?, 0 uncommitted path\(s\)\. Name this revision")
        self.assertEqual((patch, digest), (b"", server.REVISION_CLEAN + server.git_head(self.repo)))  # nothing to diff, as git showed
        self.assertEqual(server.revision(os.path.join(self.repo, "nowhere")), ("", b"", ""))
        self.assertFalse(os.path.exists(os.path.join(self.cache, server.PATCH_FOLDER)))

    def test_branch_diff_uses_the_common_ancestor(self):
        ancestor = self.git("rev-parse", "HEAD").strip()
        self.git("checkout", "-qb", "base-side")
        self.put("base-only", "upstream\n")
        self.git("add", "base-only")
        self.git("commit", "-qm", "upstream change")
        self.git("tag", "-a", "release", "-m", "base tag")
        tip = self.git("rev-parse", "HEAD").strip()
        self.git("checkout", "-qb", "topic", ancestor)
        self.put("app.py", "a = 3\n")
        self.git("commit", "-qam", "topic change")
        head = self.git("rev-parse", "HEAD").strip()

        for base in (ancestor, "base-side", "release", tip):
            with self.subTest(base=base):
                line, patch, digest = server.revision(self.repo, base=base)
                self.assertIn(f"base {base!r}, merge base {ancestor} to HEAD {head} on topic", line)
                self.assertIn("0 uncommitted path(s)", line)
                self.assertIn("this range and that sha256", line)
                self.assertIn(b"+a = 3\n", patch)
                self.assertNotIn(b"base-only", patch)
                self.assertEqual(digest, hashlib.sha256(patch).hexdigest()[:16])
        self.put("notes", "uncommitted\n")
        line, patch, digest = server.revision(self.repo, base="base-side", inline_limit=100_000)
        self.assertIn("1 uncommitted path(s)", line)
        self.assertIn("is in this message", line)
        self.assertIn(b"+a = 3\n", patch)
        self.assertIn(b"+uncommitted\n", patch)
        with open(self.saved(digest), "rb") as f:
            self.assertEqual(f.read(), patch)
        line, patch, digest = server.revision(self.repo, base="base-side", take=False)
        self.assertIn(ancestor, line)
        self.assertEqual((patch, digest), (b"", ""))

    def test_branch_review_requires_a_valid_base_and_revision(self):
        with self.assertRaisesRegex(server.BridgeError, "base requires revision=true"):
            server.send_consultant_message({"kind": "other", "to": "reviewer", "message": "review", "base": "main"})
        with self.assertRaisesRegex(server.BridgeError, "attach_diff requires revision=true"):
            server.send_consultant_message({"kind": "review", "to": "reviewer", "message": "review", "attach_diff": True})
        # effort is a new Antigravity consultant's level; a Codex start that names one is refused, not ignored.
        with mock.patch.object(server, "codex_installed", lambda: True), \
                mock.patch.object(server, "CodexClient", lambda *a, **k: self.fail("nothing starts")):
            for provider in (None, "codex"):
                with self.assertRaisesRegex(server.BridgeError, "effort applies to a new Antigravity consultant only"):
                    server.start_consultant({"cwd": self.repo, "provider": provider, "effort": "high"})
        for base, error in (("unknown-branch", "resolve base"), ("--all", "not an option"), ("@", "revision expression")):
            with self.assertRaisesRegex(server.BridgeError, error):
                server.revision(self.repo, base=base)
        line, patch, digest = server.revision(self.repo, base="HEAD")
        self.assertIn("0 uncommitted path(s); nothing to review", line)
        self.assertEqual((patch, digest), (b"", server.REVISION_CLEAN + server.git_head(self.repo)))
        self.put("app.py", "changed\n")
        self.assertIn(b"+changed\n", server.revision(self.repo, base="HEAD")[1])

    def test_large_and_extra_untracked_files_are_named_not_sent(self):
        """0.26.1: an untracked file over 256 KB, and those past the 200th, are named in the revision
        line and left out of the diff."""
        self.assertEqual((server.PATCH_FILE_BYTES, server.PATCH_UNTRACKED_FILES), (256 * 1024, 200))
        self.put("at-limit.txt", "x" * (256 * 1024))
        self.put("big.txt", "y" * (256 * 1024 + 1))
        line, patch, _ = server.revision(self.repo)
        self.assertIn("big.txt (too large)", line)
        self.assertIn(b"at-limit.txt", patch)
        self.assertNotIn(b"big.txt", patch)
        os.remove(os.path.join(self.repo, "at-limit.txt"))
        os.remove(os.path.join(self.repo, "big.txt"))
        for n in range(3):
            self.put(f"f{n}.txt", f"{n}\n")
        with mock.patch.object(server, "PATCH_UNTRACKED_FILES", 2):  # the 200th, made small
            line, patch, _ = server.revision(self.repo)
        self.assertIn("f2.txt (over 2 untracked files)", line)
        self.assertIn(b"f1.txt", patch)
        self.assertNotIn(b"f2.txt", patch)

    def test_the_diff_is_taken_once_and_applies(self):
        self.put("app.py", "a = 1\nb = 3\n")
        self.put("new/notes.txt", "café\nlast line without a newline")
        self.put("empty.txt", "")
        self.put(".env", "TOKEN=hunter2\n")
        self.put("secrets/config.json", '{"key": "hunter2"}\n')
        self.put("logo.bin", b"\x89PNG\0\0")
        before = self.git("status", "--porcelain")
        line, patch, digest = server.revision(self.repo)
        self.assertEqual(self.git("status", "--porcelain"), before)  # nothing added to the real index
        self.assertRegex(digest, r"^[0-9a-f]{16}$")
        self.assertEqual(digest, hashlib.sha256(patch).hexdigest()[:16])
        self.assertIn(f"sha256 {digest}, 3 file(s)", line)
        self.assertIn("left out: .env (may hold secrets), secrets/config.json (may hold secrets), logo.bin (binary)", line)
        self.assertNotIn(b"hunter2", patch)
        self.assertIn(b"+b = 3\n", patch)
        self.assertIn("+café\n+last line without a newline\n\\ No newline at end of file\n".encode(), patch)
        self.assertTrue(server.REVISION_STAMP.match(line))
        self.assertIn(self.saved(digest), line)
        with open(self.saved(digest), "rb") as f:
            self.assertEqual(f.read(), patch)
        # the same tree, the same diff, from a subfolder too; a change, another
        self.assertEqual(server.revision(self.repo)[2], digest)
        self.assertEqual(server.revision(os.path.join(self.repo, "new"))[2], digest)
        self.put("app.py", "a = 1\nb = 4\n")
        self.assertNotEqual(server.revision(self.repo)[2], digest)
        # the saved diff is what was reviewed: it applies to the commit it names
        self.git("stash", "-u", "-q")
        self.git("apply", "--check", self.saved(digest))
        self.git("apply", self.saved(digest))
        with open(os.path.join(self.repo, "new", "notes.txt"), "rb") as f:
            self.assertEqual(f.read(), "café\nlast line without a newline".encode("utf-8"))

    def test_bytes_names_and_modes_are_kept(self):
        self.put("my notes.txt", "a\r\nb\r\n")
        self.put("latin.txt", b"caf\xe9\r\n")      # not UTF-8: in the diff as it is
        self.put("tab\there.txt" if os.name != "nt" else "q[1].txt", "x\n")
        self.put("art.png", b"\x89PNG\0")
        self.git("add", "art.png")                   # a binary file new to the index
        os.chmod(os.path.join(self.repo, "app.py"), 0o755)  # where git reads the mode (core.fileMode)
        self.git("update-index", "--chmod=+x", "app.py")   # and where it does without it (Windows)
        line, patch, digest = server.revision(self.repo)
        self.assertIn("art.png (binary)", line)
        self.assertIn(b"+a\r\n+b\r\n", patch)
        self.assertIn(b"+caf\xe9\r\n", patch)
        self.assertIn(b"new mode 100755", patch)
        line, inline, _ = server.revision(self.repo, inline_limit=100_000)
        self.assertIn("has bytes that aren't UTF-8", line)  # not attached with them replaced
        self.assertEqual(inline, b"")
        self.git("stash", "-u", "-q")
        self.git("apply", "--check", self.saved(digest))
        out = subprocess.run(["git", "-C", self.repo, "apply", "--numstat", self.saved(digest)],
                             capture_output=True, check=True).stdout
        self.assertIn(b"latin.txt", out)
        self.assertNotIn(b"art.png", out)            # a binary's change isn't in the diff

    def test_left_out_names_are_counted_not_kept(self):
        left_out = server.LeftOut()
        for n in range(1000):
            left_out.add(f"f{n}", "too large")
        self.assertEqual(len(left_out.names), server.PATCH_NAMES_SHOWN)
        self.assertTrue(str(left_out).endswith("f4 (too large), 995 more"))
        self.assertEqual(str(server.LeftOut()), "")

    def test_a_branch_or_path_with_a_bracket_is_still_stripped(self):
        self.git("checkout", "-q", "-b", "a]b")
        self.put("app.py", "changed\n")
        line, _, _ = server.revision(self.repo)
        self.assertIn(" on a]b, 1 uncommitted path(s)", line)
        self.assertEqual(server.REVISION_STAMP.sub("", line + "hi"), "hi")
        self.assertEqual(server.REVISION_STAMP.sub("", "[Revision: not a git repository, or no commits yet]\nhi"), "hi")

    def test_a_large_diff_is_described_not_attached(self):
        self.put("app.py", "x = 1\n" * 1000)
        line, patch, digest = server.revision(self.repo, inline_limit=1000)
        self.assertEqual((patch, digest), (b"", ""))
        self.assertIn("is too large to put in this message, so review the working tree", line)
        self.assertNotIn("Review that diff", line)
        self.assertNotIn("sha256", line)                 # no digest the consultant can't check
        self.assertEqual(server.revision(self.repo, take=False)[1:], (b"", ""))
        line, patch, digest = server.revision(self.repo, inline_limit=100_000)
        self.assertIn("is in this message, above the bridge header", line)
        self.assertTrue(patch)

    def test_a_failure_is_not_taken_for_no_changes(self):
        self.put("app.py", "changed\n")
        real = server.run_bytes
        failing = lambda argv, *a, **k: (None, "failed") if "diff" in argv else real(argv, *a, **k)
        with mock.patch.object(server, "run_bytes", failing):
            line, patch, digest = server.revision(self.repo)
        self.assertIn("couldn't take their diff (git diff failed), so review the working tree", line)
        self.assertEqual((patch, digest), (b"", ""))
        with mock.patch.object(server, "save_patch", side_effect=PermissionError("locked")):
            line, patch, digest = server.revision(self.repo)
        self.assertIn("couldn't save their diff (1 file(s), ", line)
        self.assertNotIn("sha256", line)
        self.assertEqual((patch, digest), (b"", ""))
        with mock.patch.object(server, "save_patch", side_effect=PermissionError("locked")):
            self.assertEqual(server.revision(self.repo, inline_limit=100_000)[1:], (b"", ""))
        with mock.patch.object(server.tempfile, "TemporaryDirectory", side_effect=OSError("disk full")):
            line, patch, digest = server.revision(self.repo)
        self.assertIn("couldn't take their diff (couldn't copy git's index to a temporary folder)", line)
        out, why = server.run_bytes([sys.executable, "-c", "print('x' * 100)"], limit=10)
        self.assertEqual((out, why), (None, "too large"))
        self.assertEqual(server.run_bytes([sys.executable, "-c", "import sys; sys.exit(3)"]), (None, "failed"))

    def test_settings_and_hooks_of_the_repo_are_not_used(self):
        self.git("config", "status.showUntrackedFiles", "no")
        hooks = os.path.join(self.repo, ".git", "hooks")
        os.makedirs(hooks, exist_ok=True)
        ran = os.path.join(self.cache, "hook-ran")
        for hook in ("post-index-change", "post-index-change.bat"):
            with open(os.path.join(hooks, hook), "w") as f:
                f.write(f"#!/bin/sh\necho x > '{ran}'\n")
            os.chmod(os.path.join(hooks, hook), 0o755)
        self.put("notes.md", "Subproject commit 0123abc-dirty\n")  # text that only looks like a submodule
        line, patch, digest = server.revision(self.repo)
        self.assertIn(", 1 uncommitted path(s)", line)
        self.assertIn(b"+Subproject commit 0123abc-dirty\n", patch)
        self.assertFalse(os.path.exists(ran))

    def test_old_diffs_are_removed(self):
        folder = os.path.join(self.cache, server.PATCH_FOLDER)
        os.makedirs(folder)
        old = os.path.join(folder, "0123456789abcdef.patch")
        with open(old, "w") as f:
            f.write("x")
        os.utime(old, (time.time() - (server.PATCH_KEEP_DAYS + 1) * 86400,) * 2)
        self.put("app.py", "changed\n")
        _, patch, digest = server.revision(self.repo)
        self.assertFalse(os.path.exists(old))
        self.assertEqual(os.listdir(folder), [f"{digest}.patch"])
        with open(self.saved(digest), "wb") as f:
            f.write(b"something else")               # a damaged copy isn't trusted
        server.revision(self.repo)
        with open(self.saved(digest), "rb") as f:
            self.assertEqual(f.read(), patch)


class HardeningTest(unittest.TestCase):
    """0.22.0: nouez's own folders, kept files and git calls."""

    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.dir, True)
        patcher = mock.patch.object(server, "nouez_cache_dir", return_value=self.dir)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.outside = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.outside, True)

    def old(self, path, days):
        with open(path, "w") as f:
            f.write("x")
        t = time.time() - days * 86400
        os.utime(path, (t, t))

    def test_folders_that_are_links_are_refused(self):
        dir_link(self.outside, os.path.join(self.dir, "replies"))
        with self.assertRaises(OSError):
            server.cache_folder("replies", "deeper", create=True)
        self.assertEqual(os.listdir(self.outside), [])  # nothing made where the link points

    def test_saved_json_never_goes_through_a_linked_folder(self):
        """0.22.0: a cache file nouez saves isn't written where a folder link on its way points."""
        dir_link(self.outside, os.path.join(self.dir, "agy"))
        self.assertFalse(server.write_json_atomic(os.path.join(self.dir, "agy", "abc", "consultant.json"), {}))
        self.assertTrue(server.write_json_atomic(os.path.join(self.dir, "fine", "x.json"), {"a": 1}))
        self.assertEqual(os.listdir(self.outside), [])

    @unittest.skipUnless(os.name == "nt", "Windows only: a file open for reading can't be replaced there")
    def test_saved_json_waits_for_a_reader_to_let_go(self):
        """0.26.1: a file another process has open can't be replaced on Windows, and the dispatcher's
        last state was lost when its status was read just then; the replace is tried again."""
        path = os.path.join(self.dir, "fine", "state.json")
        self.assertTrue(server.write_json_atomic(path, {"phase": "connected"}))
        reader = open(path, encoding="utf-8")  # as another process reading it holds it
        threading.Timer(0.2, reader.close).start()
        self.assertTrue(server.write_json_atomic(path, {"phase": "stopped"}))
        with open(path, encoding="utf-8") as f:
            self.assertEqual(json.load(f), {"phase": "stopped"})
        held = open(path, encoding="utf-8")
        self.addCleanup(held.close)
        with mock.patch.object(server.time, "sleep"):  # a reader that never lets go: given up, nothing left behind
            self.assertFalse(server.write_json_atomic(path, {"phase": "later"}))
        self.assertEqual(sorted(os.listdir(os.path.dirname(path))), ["state.json"])

    def test_a_linked_pane_key_is_replaced_not_read(self):
        """0.22.0: a pane key that is a link is neither read nor written through."""
        target = os.path.join(self.outside, "planted")
        with open(target, "wb") as f:
            f.write(b"p" * 32)
        file_link(self, target, os.path.join(self.dir, "pane-key"))
        with mock.patch.object(server, "_pane_key", None):
            key = server.pane_key()
        self.assertNotEqual(key, b"p" * 32)
        self.assertFalse(server.is_link(os.path.join(self.dir, "pane-key")))
        with open(target, "rb") as f:
            self.assertEqual(f.read(), b"p" * 32)

    def test_locks_are_never_taken_through_a_link(self):
        """0.22.0: a lock file, or an Antigravity folder, that is a link isn't opened."""
        lock = os.path.join(self.dir, "usage-log.jsonl.lock")
        dir_link(self.outside, lock)
        with self.assertRaisesRegex(OSError, "is a link"):
            with server.FileLock(lock, 1, "busy"):
                pass
        with mock.patch.object(server, "agy_root", return_value=os.path.join(self.dir, "agy")):
            os.makedirs(os.path.join(self.dir, "agy"))
            dir_link(self.outside, os.path.join(self.dir, "agy", "abc"))
            with self.assertRaises(OSError):
                with server.agy_lock("abc"):
                    pass
        self.assertEqual(os.listdir(self.outside), [])

    def test_partial_clones_take_no_diff_with_an_old_git(self):
        """0.22.0: a partial clone's diff is taken only by a git that can be told not to fetch."""
        repo = os.path.join(self.dir, "repo")
        os.makedirs(repo)
        for cmd in (["init", "-q"], ["config", "user.email", "t@example.invalid"], ["config", "user.name", "t"],
                    ["commit", "-q", "--allow-empty", "-m", "start"], ["config", "extensions.partialClone", "origin"]):
            subprocess.run(["git", "-C", repo, *cmd], check=True, capture_output=True)
        with open(os.path.join(repo, "new.txt"), "w") as f:
            f.write("hello\n")
        real = server.git_bytes

        def old_git(cmd, *a, **k):
            return (None, "unknown option") if "--no-lazy-fetch" in cmd else real(cmd, *a, **k)
        with mock.patch.object(server, "git_bytes", side_effect=old_git):
            line, diff, _ = server.revision(repo)
        self.assertIn("partial clone", line)
        self.assertEqual(diff, b"")
        subprocess.run(["git", "-C", repo, "config", "--unset", "extensions.partialClone"], check=True)
        subprocess.run(["git", "-C", repo, "config", "remote.origin.promisor", "2"], check=True)  # git: true
        with mock.patch.object(server, "git_bytes", side_effect=old_git):
            line, diff, _ = server.revision(repo)
        self.assertIn("partial clone", line)  # a promisor remote fetches too
        subprocess.run(["git", "-C", repo, "config", "--unset", "remote.origin.promisor"], check=True)
        with mock.patch.object(server, "git_bytes", side_effect=old_git):
            line, diff, _ = server.revision(repo)
        self.assertNotIn("partial clone", line)
        self.assertIn(b"hello", diff)  # nothing to fetch: an old git takes the diff
        subprocess.run(["git", "-C", repo, "config", "extensions.partialClone", "origin"], check=True)
        seen = []

        def new_git(cmd, *a, **k):
            seen.append(cmd)
            return real(cmd, *a, **k)
        with mock.patch.object(server, "git_bytes", side_effect=new_git):
            line, diff, _ = server.revision(repo)
        if diff:  # git 2.45 or later
            self.assertIn(b"hello", diff)
            self.assertTrue(all("--no-lazy-fetch" in c for c in seen if "diff" in c))
        made = server.cache_folder("a", "b", create=True)
        self.assertTrue(server.plain_folder(made))
        if os.name != "nt":
            self.assertEqual(os.stat(made).st_mode & 0o777, 0o700)

    def test_startup_removes_old_files_only(self):
        patches = server.cache_folder(server.PATCH_FOLDER, create=True)
        old, new, other = (os.path.join(patches, n) for n in ("0123456789abcdef.patch", "fedcba9876543210.patch",
                                                               "notes.txt"))
        self.old(old, server.PATCH_KEEP_DAYS + 1)
        self.old(new, 1)
        self.old(other, 400)
        server.tidy()
        self.assertEqual(sorted(os.listdir(patches)), ["fedcba9876543210.patch", "notes.txt"])
        # A patches folder that is a link isn't looked in
        shutil.rmtree(patches)
        planted = os.path.join(self.outside, "0123456789abcdef.patch")
        self.old(planted, 400)
        dir_link(self.outside, patches)
        server.tidy()
        self.assertTrue(os.path.exists(planted))

    def test_a_saved_diff_replaces_a_link(self):
        folder = server.cache_folder(server.PATCH_FOLDER, create=True)
        target = os.path.join(self.outside, "victim")
        with open(target, "wb") as f:
            f.write(b"same")
        file_link(self, target, os.path.join(folder, "0123456789abcdef.patch"))
        path = server.save_patch(b"same", "0123456789abcdef")
        self.assertFalse(os.path.islink(path))
        with open(path, "rb") as f:
            self.assertEqual(f.read(), b"same")

    def test_git_never_fetches_for_a_diff(self):
        with mock.patch.object(server, "run_bytes", return_value=(b"", "")) as run:
            server.git_bytes(["git", "status"], 5, env={"A": "1"})
        self.assertEqual(run.call_args.args[3], {"A": "1", "GIT_NO_LAZY_FETCH": "1"})

    def test_usage_file_keeps_only_the_windows(self):
        now = 1_000_000.0
        got = server.merge_claude_usage(None, {"five_hour": {"used_percentage": 5, "resets_at": now + 60, "who": "x"},
                                               "account": {"email": "someone@example.com"}}, now)
        self.assertEqual(got["rate_limits"], {"five_hour": {"used_percentage": 5, "resets_at": now + 60,
                                                            "observed": now}})

    @unittest.skipUnless(os.name == "nt", "Windows")
    def test_helper_check_reads_one_command_line(self):
        line = "python x claude --name nouez-claude-1"
        with mock.patch.object(server, "process_command_line", return_value=line) as cl, \
             mock.patch.object(server, "run_text") as run:
            self.assertTrue(server._is_nouez_helper(42))
        cl.assert_called_once_with(42)
        run.assert_not_called()  # no PowerShell
        with mock.patch.object(server, "process_command_line", return_value=None):
            self.assertFalse(server._is_nouez_helper(42))


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
            self.assertNotIn("trusted devices", out)  # only said of a resumed conversation
            with mock.patch.object(server, "claude_sessions", return_value=[self.session(2, tmp, False)]),                     mock.patch.object(server, "CONNECT_SECONDS", 0):
                self.assertIn("typing /remote-control in that window", server.connection_note(set(), tmp, resumed=True))
            out = self.open([[], []], tmp)
            self.assertIn("hadn't shown up as a running session", out)

    def test_a_failing_check_still_opens(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = self.open(OSError("unreadable"), tmp)
            self.assertIn("Opened a window", out)


class BudgetTest(unittest.TestCase):
    """ConsultantBudget: usage windows, the status line's file, and the Artificial Analysis cache."""

    NOW = 1_800_000_000

    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.dir, True)
        self.aa = os.path.join(self.dir, "aa-models.json")

    def test_window_pace(self):
        week = 7 * 86400
        # half the week gone, 30% used: lands at about 60%
        text = server.window_text("weekly", 30, self.NOW + week / 2, week, self.NOW)
        self.assertIn("30% used", text)
        self.assertIn("about 60% by the reset", text)
        # half gone, 80% used: runs out after another 1/8 week, before the reset
        text = server.window_text("weekly", 80, self.NOW + week / 2, week, self.NOW)
        self.assertIn("runs out in about 21h 0m, before the reset", text)
        self.assertIn("used up", server.window_text("weekly", 100, self.NOW + 60, week, self.NOW))
        # too early in the window to project
        self.assertNotIn("rate", server.window_text("weekly", 5, self.NOW + week - 60, week, self.NOW))
        for used, resets in ((None, self.NOW + 60), (True, self.NOW + 60), (5, self.NOW - 1), (5, float("nan"))):
            self.assertIsNone(server.window_text("weekly", used, resets, week, self.NOW))

    def test_a_weeks_first_morning_isnt_projected_through_its_nights(self):
        """0.28.2: in a week's first 16 hours its pace is the use so far over 16 hours, so a morning's
        work isn't carried through every night of the week; from then on, the use over the time gone."""
        week, h, now = 7 * 86400, 3600, self.NOW
        # Lee, 7.8% after 12.5 h: busy at about 84%, not "runs out" (a straight line said about 105%)
        resets = now + week - 12.5 * h
        self.assertEqual(server.window_pace(7.8, resets, week, now)[::2], ("at reset", "first day"))
        judged = server.window_level(7.8, resets, week, now)
        self.assertEqual((judged["level"], round(judged["pct"]), judged["basis"]), ("busy", 84, "first day"))
        self.assertEqual(server.usage_outlook_detail([(week, 7.8, resets)], now), ("busy", judged["pct"], "first day"))
        self.assertIn("about 84% by the reset (a first-day estimate", server.window_text("weekly", 7.8, resets, week, now))
        self.assertIn("(a first-day estimate)", server.pace_words(judged["pct"], judged["basis"]))
        shown = server.window_state(7.8, resets, week, now)
        self.assertEqual((shown["long"][-20:], shown["short"]), ("(first-day estimate)", "~84% day 1"))
        # Dana, 30% a day from the reset: at hour 9 the first-day pace still runs out
        resets = now + week - 9 * h
        self.assertEqual(server.window_level(11.25, resets, week, now)["level"], "runs out")
        shown = server.window_state(11.25, resets, week, now)
        self.assertEqual((shown["long"], shown["short"]), ("runs out in ~5d 6h (first-day estimate)", "day 1: out"))
        self.assertEqual(server.usage_outlook_detail([(week, 11.25, resets)], now)[1],
                         "its weekly window runs out before its reset at this rate (a first-day estimate)")
        # one pace from both sides of hour 16, and the plain pace after it
        at16 = server.window_pace(8, now + week - 16 * h, week, now)[1]
        self.assertAlmostEqual(at16, 8 * week / (16 * h))
        self.assertEqual(len(server.window_pace(8, now + week - 17 * h, week, now)), 2)
        # a 5-hour window keeps its straight line, and the first 5% of a week stays too early to tell
        self.assertEqual(server.window_pace(50, now + 3 * h, 5 * h, now), ("runs out", 2 * h))
        self.assertIsNone(server.window_pace(3, now + week - 8 * h, week, now))

    def test_a_reused_antigravity_reading_keeps_when_agy_answered(self):
        """0.28.2: a usage reading reused from agy's cache is logged as read when agy answered."""
        live = {"read_at": self.NOW - 60, "groups": [{"name": "Gemini Models", "buckets": [
            {"window": "weekly", "remaining_fraction": 0.9,
             "reset_time": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(self.NOW + 86400))}]}]}
        (q,) = server.agy_windows(live, self.NOW)
        self.assertEqual(q["sampled"], self.NOW - 60)
        with mock.patch.object(server.time, "time", lambda: self.NOW):
            meta = server.usage_snapshot(None, live)["usage_meta"]["antigravity"]
        self.assertEqual(meta["AG Gemini"]["weekly"]["sampled"], self.NOW - 60)
        # and routing and the screen judge it as of then: 7% 20 minutes into a 5-hour window runs out
        five = {"read_at": self.NOW - 80, "groups": [{"name": "Gemini Models", "buckets": [
            {"window": "5h", "remaining_fraction": 0.93, "reset_time": time.strftime(
                "%Y-%m-%dT%H:%M:%SZ", time.gmtime(self.NOW - 80 + 4 * 3600 + 40 * 60))}]}]}
        state = {}
        server.agy_budget(self.NOW, five, state)
        self.assertEqual(server.usage_outlook(state["groups"]["Gemini Models"], self.NOW)[0], "blocked")
        (entry,) = server.agy_group(self.NOW, five)["entries"]
        self.assertEqual(entry[2]["level"], "runs out")

    def test_one_reader_per_subscription(self):
        """0.26.4: routing, ConsultantBudget, the status screen and the usage log read each
        subscription's windows the one way, so they agree."""
        now, week, scr = self.NOW, 7 * 86400, server.Screen(False)
        # Codex says a limit is reached: routing is blocked, and the screen shows it, with no reset time
        rl = {"planType": "pro", "rateLimitReachedType": "workspace_credits_depleted",
              "primary": {"usedPercent": 20, "windowDurationMins": 10080, "resetsAt": now + 86400},
              "secondary": {"usedPercent": 99, "windowDurationMins": 300, "resetsAt": now - 1}}  # has reset
        got = server.codex_windows(rl, now)
        self.assertEqual([(q["label"], q["used"]) for q in got["windows"]], [("weekly", 20)])
        self.assertEqual(got["limit_reached"], "workspace_credits_depleted")
        state = {}
        server.codex_budget(mock.Mock(request=lambda m, p: {"rateLimits": rl} if m.startswith("account") else {}),
                            now, state)
        self.assertEqual(server.usage_outlook(state["windows"], now)[0], "blocked")
        (codex,) = [g for g in server.subscription_groups(now, {"rateLimits": rl}, None, os.path.join(self.dir, "x"))
                    if g["title"].startswith("Codex")]
        self.assertEqual(codex["title"], "Codex pro")
        self.assertEqual([label for _, label, _ in codex["entries"]], ["weekly", "limit"])
        rows = "\n".join(server.group_rows(scr, now, codex) + server.card_rows(scr, codex))
        self.assertIn("limit reached: workspace_credits_depleted", rows)
        self.assertEqual(rows.count("resets "), 1)  # the weekly window's only
        self.assertIn("100%", server.badge(scr, codex))
        # the daemon answered with no windows: no falling back to the session file
        saved = {"ts": now - 60, "primary": {"used_percent": 50, "window_minutes": 10080, "resets_at": now + 86400}}
        (codex,) = [g for g in server.subscription_groups(now, {"rateLimits": {}}, saved, os.path.join(self.dir, "x"))
                    if g["title"].startswith("Codex")]
        self.assertEqual(codex["entries"], [])
        self.assertEqual(codex["empty"], "no current usage windows: the daemon reports none")
        (codex,) = [g for g in server.subscription_groups(now, None, saved, os.path.join(self.dir, "x"))
                    if g["title"].startswith("Codex")]
        self.assertEqual(codex["entries"][0][2]["used"], 50)
        self.assertIsNone(server.codex_saved_windows({k: v for k, v in saved.items() if k != "ts"}, now))
        # Antigravity: rounded once, so 99.96% used is used up on the screen as for routing
        live = {"groups": [{"name": "Gemini Models", "buckets": [
            {"window": "weekly", "remaining_fraction": 0.0004, "reset_time": time.strftime(
                "%Y-%m-%dT%H:%M:%SZ", time.gmtime(now + 86400))},
            {"window": "5h", "remaining_fraction": 0.5, "reset_time": "2000-01-01T00:00:00Z"}]}]}  # has reset
        before = json.dumps(live)
        state = {}
        server.agy_budget(now, live, state)
        self.assertEqual(state["groups"]["Gemini Models"], [(week, 100.0, now + 86400, now)])
        (entry,) = server.agy_group(now, live)["entries"]
        self.assertEqual((entry[2]["used"], entry[2]["rank"]), (100.0, 3))
        self.assertEqual(json.dumps(live), before)  # agy's cached answer is never changed
        # the usage log leaves out a window that has reset, for Antigravity as for the others
        with mock.patch.object(server.time, "time", lambda: now):
            self.assertEqual(server.usage_snapshot(None, live)["usage"]["antigravity"], {"AG Gemini": {"weekly": 100.0}})
        # Claude Code: each window keeps when it was observed; the file's own time is for doctor
        path = os.path.join(self.dir, "claude.json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump({"saved": now - 600, "rate_limits": {
                "five_hour": {"used_percentage": 10, "resets_at": now + 3600, "observed": now - 60},
                "seven_day": {"used_percentage": 40, "resets_at": now + 86400}}}, f)
        quota = server.claude_quota(now, path)
        self.assertEqual((quota["status"], quota["saved"]), ("ok", now - 600))
        self.assertEqual([(q["label"], q["sampled"]) for q in quota["windows"]],
                         [("5-hour", now - 60), ("weekly", now - 600)])
        self.assertEqual(server.claude_quota(now, os.path.join(self.dir, "none"))["status"], "missing")

    def test_span_and_label(self):
        self.assertEqual(server.span_text(3 * 86400 + 5 * 3600 + 59), "3d 5h")
        self.assertEqual(server.span_text(4 * 3600 + 600), "4h 10m")
        self.assertEqual(server.span_text(-5), "0 min")
        self.assertEqual(server.window_label(300 * 60), "5-hour")
        self.assertEqual(server.window_label(10080 * 60), "weekly")

    def test_codex_budget(self):
        answers = {
            "account/rateLimits/read": {
                "rateLimits": {"planType": "pro",
                               "primary": {"usedPercent": 40, "windowDurationMins": 300, "resetsAt": self.NOW + 3600},
                               "secondary": {"usedPercent": "x", "windowDurationMins": 10080, "resetsAt": 1}},
                "rateLimitResetCredits": {"availableCount": 2}},
            "model/list": {"data": [
                {"id": "m-1", "isDefault": True, "defaultReasoningEffort": "low",
                 "supportedReasoningEfforts": [{"reasoningEffort": "low"}, {"reasoningEffort": "high"}]},
                {"id": "m-hidden", "hidden": True}, "junk"]},
        }
        client = mock.Mock()
        client.request.side_effect = lambda method, params: answers[method]
        text = "\n".join(server.codex_budget(client, self.NOW))
        self.assertIn("Codex (pro plan):", text)
        self.assertIn("5-hour window: 40% used", text)
        self.assertNotIn("weekly", text)
        self.assertIn("2 free full reset(s)", text)
        self.assertIn("m-1 (default): effort low, high (default low)", text)
        self.assertNotIn("m-hidden", text)

    def test_codex_budget_without_models(self):
        def request(method, params):
            if method == "model/list":
                raise server.BridgeError("no")
            return {}
        client = mock.Mock()
        client.request.side_effect = request
        self.assertEqual(server.codex_budget(client, self.NOW), ["Codex:", "  - no usage windows reported"])

    def test_the_prompt_hook_speaks_only_when_claude_code_is_busy(self):
        """0.26.0: `server.py hook` adds the hand-out line to each prompt past 70% on pace, from a
        fresh reading only, and says nothing otherwise; it never fails a prompt."""
        path = os.path.join(self.dir, "claude-usage.json")

        def save(used, days_left, age=0):
            with open(path, "w", encoding="utf-8") as f:
                json.dump({"saved": self.NOW - age, "rate_limits": {"seven_day": {
                    "used_percentage": used, "resets_at": self.NOW + days_left * 86400}}}, f)
        self.assertEqual(server.hook_text(self.NOW, path), "")  # no usage file
        save(10, 2)  # about 14%
        self.assertEqual(server.hook_text(self.NOW, path), "")
        save(60, 2)  # about 84%
        text = server.hook_text(self.NOW, path)
        self.assertTrue(text.startswith("nouez: Claude Code is on pace for about 84% of its week."), text)
        self.assertIn(server.HAND_OUT["busy"], text)
        save(80, 1)  # past 90%
        self.assertIn(server.HAND_OUT["tight"], server.hook_text(self.NOW, path))
        save(80, 1, age=server.CLAUDE_USAGE_STALE + 60)  # an old reading at 80% says nothing
        self.assertEqual(server.hook_text(self.NOW, path), "")
        save(93, 1, age=server.CLAUDE_USAGE_STALE + 60)  # 0.28.1: at 93% it is tight however old, as the screen says
        text = server.hook_text(self.NOW, path)
        self.assertIn("at 93% of its week or more (an old reading)", text)
        save(100, 1, age=server.CLAUDE_USAGE_STALE + 60)  # used up however old, and still said to be old
        self.assertIn("used up (an old reading)", server.hook_text(self.NOW, path))
        self.assertIn(server.HAND_OUT["tight"], text)
        save(60, 2)
        with mock.patch.dict(os.environ, {"NOUEZ_NO_AUTO_CONSULT": "1"}):
            self.assertEqual(server.hook_text(self.NOW, path), "")
        with mock.patch.object(server, "hook_text", side_effect=RuntimeError("boom")), \
                mock.patch.object(sys, "stdin", io.TextIOWrapper(io.BytesIO(b'{"prompt": "x"}'))), \
                contextlib.redirect_stdout(io.StringIO()) as out:
            self.assertEqual(server.run_hook([]), 0)
        self.assertEqual(out.getvalue(), "")

    def test_doctor_names_the_status_line_and_hook_to_add(self):
        """0.26.0: doctor says when no status line has saved Claude Code's usage lately, or no prompt
        hook is set, and prints the settings entry for each with this Python and server.py."""
        path = os.path.join(self.dir, "claude-usage.json")
        with mock.patch.object(server, "nouez_cache_dir", return_value=self.dir):
            (s_ok, s_text), (h_ok, h_text) = server.usage_setup_report({})
            self.assertIsNone(s_ok)
            self.assertIn('"statusLine"', s_text)
            self.assertIsNone(h_ok)
            self.assertIn(server.usage_command("hook"), json.loads(h_text.split("\n    ", 1)[1])["UserPromptSubmit"]
                          [0]["hooks"][0]["command"])
            with open(path, "w", encoding="utf-8") as f:
                json.dump({"saved": time.time() - 60, "rate_limits": {}}, f)
            hooked = {"hooks": {"UserPromptSubmit": [{"hooks": [{"type": "command",
                                                                 "command": server.usage_command("hook")}]}]}}
            self.assertEqual([ok for ok, _ in server.usage_setup_report(hooked)], [True, True])
        self.assertTrue(server.usage_command("hook").endswith("server.py hook"))
        # a Python PATH finds by name goes bare; another is its path, quoted when it has a space
        open(self.aa, "w").close()
        with mock.patch.object(server.sys, "executable", self.aa), \
                mock.patch.object(server.shutil, "which", return_value=self.aa):
            self.assertTrue(server.usage_command("hook").startswith("python3 "))
        spaced = os.path.join(self.dir, "Program Files", "python.exe")
        with mock.patch.object(server.sys, "executable", spaced), \
                mock.patch.object(server.shutil, "which", return_value=None):
            self.assertTrue(server.usage_command("hook").startswith('"' + spaced.replace("\\", "/") + '" '))
        self.assertIn("git apply", server.CONSULT_NOTES["bug-hunt"])
        self.assertIn("reading many files", server.CONSULT_NOTES["research"])

    def test_claude_budget(self):
        path = os.path.join(self.dir, "claude-usage.json")
        self.assertIn("not known", server.claude_budget(self.NOW, path)[0])
        with open(path, "w", encoding="utf-8") as f:
            f.write("{not json")
        self.assertIn("can't be read", server.claude_budget(self.NOW, path)[0])
        with open(path, "w", encoding="utf-8-sig") as f:
            json.dump({"saved": self.NOW - 3600, "rate_limits": {
                "five_hour": {"used_percentage": 12.5, "resets_at": self.NOW + 600},
                "seven_day": {"used_percentage": 50, "resets_at": self.NOW - 10}}}, f)
        lines = server.claude_budget(self.NOW, path)
        self.assertIn("saved 1h 0m ago) (old", lines[0])
        self.assertEqual(len(lines), 2)
        self.assertIn("5-hour window: 12.5% used", lines[1])
        with open(path, "w", encoding="utf-8") as f:
            json.dump({"saved": self.NOW, "rate_limits": {}}, f)
        self.assertIn("no current usage window", server.claude_budget(self.NOW, path)[0])

    def entry(self, name, creator, index, **extra):
        return {"name": name, "model_creator": {"name": creator},
                "evaluations": {"artificial_analysis_intelligence_index": index}, **extra}

    def test_aa_model_keeps_only_valid_fields(self):
        m = server.aa_model(self.entry("X", "OpenAI", 50.5, pricing={"price_1m_input_tokens": "1"},
                                       performance_v3={"mean_output_tokens_per_second": 80},
                                       release_date="2026-01-02T00:00"))
        self.assertEqual((m["name"], m["creator"], m["index"], m["input"], m["speed"], m["release"]),
                         ("X", "OpenAI", 50.5, None, 80, "2026-01-02"))
        self.assertIsNone(server.aa_model({"name": 3}))

    def test_aa_needs_a_key(self):
        fetch = mock.Mock()
        cache, note = server.aa_scores(self.NOW, env={}, path=self.aa, fetch=fetch)
        self.assertIn(server.AA_KEY_VARIABLE, note)
        fetch.assert_not_called()

    def test_aa_key_saved_after_start(self):
        # Not in this process's environment, but saved in the user's variables since it started.
        fetch = mock.Mock(return_value=(5, [server.aa_model(self.entry("GPT A", "OpenAI", 60))]))
        with mock.patch.dict(os.environ, {}, clear=False), \
                mock.patch.object(server, "saved_user_variable", return_value="saved") as saved:
            os.environ.pop(server.AA_KEY_VARIABLE, None)
            cache, note = server.aa_scores(self.NOW, path=self.aa, fetch=fetch)
        saved.assert_called_once_with(server.AA_KEY_VARIABLE)
        fetch.assert_called_once_with("saved")
        self.assertIsNone(note)
        # A test passing env never reads the saved variables.
        with mock.patch.object(server, "saved_user_variable") as saved:
            server.aa_scores(self.NOW, env={}, path=self.aa, fetch=fetch)
        saved.assert_not_called()

    def test_saved_user_variable_off_windows(self):
        with mock.patch.object(server.os, "name", "posix"):
            self.assertIsNone(server.saved_user_variable("X"))

    def test_aa_fetch_cache_and_retry(self):
        env = {server.AA_KEY_VARIABLE: " k "}
        models = [server.aa_model(self.entry("GPT A", "OpenAI", 60)),
                  server.aa_model(self.entry("Gem B", "Google", 55)),
                  server.aa_model(self.entry("Other", "Meta", 70))]
        fetch = mock.Mock(return_value=(4, models))
        cache, note = server.aa_scores(self.NOW, env=env, path=self.aa, fetch=fetch)
        fetch.assert_called_once_with("k")
        self.assertIsNone(note)
        # kept for a week
        server.aa_scores(self.NOW + 86400, env=env, path=self.aa, fetch=fetch)
        self.assertEqual(fetch.call_count, 1)
        text = "\n".join(server.aa_lines(server.read_aa_cache(self.aa), None, self.NOW + 86400))
        self.assertIn("Intelligence Index v4, fetched 1d 0h ago", text)
        self.assertIn("https://artificialanalysis.ai", text)
        self.assertIn("60.0  GPT A", text)
        self.assertNotIn("Other", text)
        # a week later the fetch fails: the old list stays, and the next try waits
        later = self.NOW + server.AA_REFRESH_SECONDS
        err = OSError("down")
        err.code = 429
        fetch.side_effect = err
        cache, note = server.aa_scores(later, env=env, path=self.aa, fetch=fetch)
        self.assertIn("daily request limit", note)
        self.assertEqual(len(cache["models"]), 3)
        server.aa_scores(later + 60, env=env, path=self.aa, fetch=fetch)
        self.assertEqual(fetch.call_count, 2)
        # refresh skips the wait
        server.aa_scores(later + 60, refresh=True, env=env, path=self.aa, fetch=fetch)
        self.assertEqual(fetch.call_count, 3)
        self.assertEqual(sorted(os.listdir(self.dir)), ["aa-models.json"])

    def test_aa_refresh_waits_an_hour(self):
        env = {server.AA_KEY_VARIABLE: "k"}
        fetch = mock.Mock(return_value=(None, [server.aa_model(self.entry("A", "Google", 1))]))
        server.aa_scores(self.NOW, env=env, path=self.aa, fetch=fetch)
        server.aa_scores(self.NOW + 60, refresh=True, env=env, path=self.aa, fetch=fetch)
        self.assertEqual(fetch.call_count, 1)
        server.aa_scores(self.NOW + 3600, refresh=True, env=env, path=self.aa, fetch=fetch)
        self.assertEqual(fetch.call_count, 2)

    def test_aa_cache_unreadable(self):
        with open(self.aa, "w", encoding="utf-8") as f:
            f.write('{"models": [1, {"name": "ok"}], "fetched": "x"}')
        self.assertEqual(server.read_aa_cache(self.aa)["models"], [{"name": "ok"}])
        with open(self.aa, "w", encoding="utf-8") as f:
            f.write("[]")
        self.assertEqual(server.read_aa_cache(self.aa), {})

    def test_handler_reports_codex_failure_inline(self):
        with mock.patch.object(server, "CodexClient", side_effect=server.BridgeError("daemon down")), \
             mock.patch.object(server, "claude_budget", return_value=["Claude Code: x"]), \
             mock.patch.object(server, "aa_scores", return_value=({}, "no key")), \
             mock.patch.object(server, "agy_budget", return_value=["Antigravity (Google): y"]):
            out = server.consultant_budget({})
        self.assertIn("Codex: usage unavailable (daemon down).", out)
        self.assertIn("Antigravity (Google): y", out)
        self.assertIn("Claude Code: x", out)
        self.assertIn("Model scores: no key.", out)

    def test_with_a_kind_only_what_to_do(self):
        """0.26.0: with a kind, the suggestion and its notes without the windows and scores;
        details=true shows them, and a sign-in warning always does."""
        with mock.patch.object(server, "CodexClient", side_effect=server.BridgeError("daemon down")), \
             mock.patch.object(server, "claude_budget", return_value=["Claude Code: x"]), \
             mock.patch.object(server, "login_lines", return_value=["  - signed in", "  Sign in again soon."]), \
             mock.patch.object(server, "aa_scores", return_value=({}, "no key")) as scores, \
             mock.patch.object(server, "agy_budget", return_value=["Antigravity (Google): y"]):
            out = server.consultant_budget({"kind": "review"})
            self.assertNotIn("Antigravity (Google): y", out)
            self.assertNotIn("Model scores", out)
            self.assertNotIn("signed in", out)
            self.assertIn("Sign in again soon.", out)
            self.assertIn("review: StartConsultant", out)
            self.assertIn("details=true", out)
            scores.assert_not_called()
            out = server.consultant_budget({"kind": "review", "details": True})
            self.assertIn("Antigravity (Google): y", out)
            self.assertIn("Model scores: no key.", out)

    def test_statusline_merge(self):
        """0.18.0: `server.py statusline` keeps each window's better reading with its own time."""
        now = 1_000_000.0
        five = {"used_percentage": 40, "resets_at": now + 3000}
        week = {"used_percentage": 20, "resets_at": now + 90000}
        # first save: both windows, seen now
        got = server.merge_claude_usage(None, {"five_hour": five, "seven_day": week}, now)
        self.assertEqual(got["saved"], now)
        self.assertEqual(got["rate_limits"]["five_hour"]["observed"], now)
        # an older session reports a lower percentage of the same window: the higher one stays, with its time
        older = {"five_hour": {"used_percentage": 30, "resets_at": now + 3005}, "seven_day": {**week, "used_percentage": 25}}
        got2 = server.merge_claude_usage(got, older, now + 60)
        self.assertEqual(got2["rate_limits"]["five_hour"]["used_percentage"], 40)
        self.assertEqual(got2["rate_limits"]["five_hour"]["observed"], now)
        self.assertEqual(got2["rate_limits"]["seven_day"]["used_percentage"], 25)
        self.assertEqual(got2["rate_limits"]["seven_day"]["observed"], now + 60)
        self.assertEqual(got2["saved"], now)  # the oldest reading shown, so an old number never looks fresh
        # a later window replaces a reading of the earlier one; a reset window is dropped
        later = {"five_hour": {"used_percentage": 2, "resets_at": now + 3000 + 18000}}
        got3 = server.merge_claude_usage(got2, later, now + 3100)
        self.assertEqual(got3["rate_limits"]["five_hour"]["used_percentage"], 2)
        self.assertEqual(got3["rate_limits"]["seven_day"]["used_percentage"], 25)  # kept: not reset, not reported
        # a window missing from the old file after it reset isn't brought back
        got4 = server.merge_claude_usage(got3, {"five_hour": later["five_hour"]}, now + 200000)
        self.assertNotIn("seven_day", got4["rate_limits"])
        # broken input
        self.assertEqual(server.merge_claude_usage("junk", {"five_hour": "x"}, now)["rate_limits"], {})
        # a window reported after its reset isn't saved as current, and huge numbers are no numbers
        past = {"five_hour": {"used_percentage": 99, "resets_at": now - 1}, "seven_day": {"used_percentage": 10 ** 400,
                                                                                        "resets_at": now + 9000}}
        self.assertEqual(server.merge_claude_usage(None, past, now)["rate_limits"], {})
        self.assertIsNone(server.number(10 ** 400))

    def test_each_window_keeps_its_own_time(self):
        """0.18.0: a kept old reading gives no pace, though the other window is fresh."""
        folder = tempfile.mkdtemp()
        path = os.path.join(folder, "claude-usage.json")
        now = time.time()
        saved = {"saved": now - 7200, "rate_limits": {
            "five_hour": {"used_percentage": 30, "resets_at": now + 3000, "observed": now - 60},
            "seven_day": {"used_percentage": 50, "resets_at": now + 90000, "observed": now - 7200}}}
        with open(path, "w", encoding="utf-8") as f:
            json.dump(saved, f)
        lines = server.claude_budget(now, path)
        five = next(l for l in lines if "5-hour" in l or "5h" in l)
        week = next(l for l in lines if "week" in l.lower() and l is not five)
        self.assertNotIn("an old reading", five)
        self.assertIn("old): at least", week)
        with open(path, "w", encoding="utf-8") as f:
            f.write("[" * 100000)  # nested past Python's recursion limit
        self.assertEqual(server.claude_budget(now, path), ["Claude Code: the saved usage file can't be read."])

    def test_statusline_command(self):
        """0.18.0: the command saves under a lock, prints a short line, and never fails."""
        folder = tempfile.mkdtemp()
        path = os.path.join(folder, "claude-usage.json")
        now = time.time()
        data = {"model": {"display_name": "Fable"}, "rate_limits": {"five_hour": {"used_percentage": 12.4, "resets_at": now + 600},
                                                                   "seven_day": {"used_percentage": 50, "resets_at": now + 9000}}}
        self.assertTrue(server.save_claude_usage(data, now, path))
        self.assertTrue(any("12.4% used" in line for line in server.claude_budget(now, path)))
        self.assertEqual(server.statusline_text(data), "Fable · 5h 12% · week 50%")
        self.assertEqual(server.statusline_text(None), "")
        # 0.18.0: a window that has reset isn't shown
        self.assertEqual(server.statusline_text(data, now + 1000), "Fable · week 50%")
        self.assertFalse(server.save_claude_usage({"model": {}}, now, path))
        # a busy file skips the save rather than waiting
        with mock.patch.object(server, "STATUSLINE_LOCK_SECONDS", 0.1):
            with server.FileLock(path + ".lock", 1, "busy"):
                if os.name == "nt":  # msvcrt locks are per handle, so a second lock in this process is refused
                    self.assertFalse(server.save_claude_usage(data, now, path))
        # end to end, with broken and good input
        for stdin, want in ((b"not json", ""), (json.dumps(data).encode(), "Fable")):
            env = dict(os.environ, LOCALAPPDATA=folder, XDG_CACHE_HOME=folder, PYTHONIOENCODING="utf-8")
            out = subprocess.run([sys.executable, "-I", server.__file__, "statusline"], input=stdin,
                                 capture_output=True, env=env, timeout=30)
            self.assertEqual(out.returncode, 0)
            self.assertIn(want, out.stdout.decode("utf-8"))
        self.assertTrue(os.path.exists(os.path.join(folder, "nouez", "claude-usage.json")))
        quiet = subprocess.run([sys.executable, "-I", server.__file__, "statusline", "--quiet"], input=json.dumps(data).encode(),
                               capture_output=True, env=env, timeout=30)
        self.assertEqual((quiet.returncode, quiet.stdout), (0, b""))

    def test_iso_seconds_on_every_python(self):
        """0.18.0: times parse the same on Python 3.9 and 3.10, whose fromisoformat is stricter."""
        base = 1795324643.0  # 2026-11-22T05:17:23Z
        for text, want in (("2026-11-22T05:17:23Z", base), ("2026-11-22T05:17:23.2Z", base + 0.2),
                           ("2026-11-22T05:17:23.207Z", base + 0.207), ("2026-11-22T05:17:23.207123Z", base + 0.207123),
                           ("2026-11-22T05:17:23.207123456Z", base + 0.207123), ("2026-11-22T05:17:23+00:00", base),
                           ("2026-11-22T00:17:23.5-05:00", base + 0.5), ("2026-11-22T06:17:23+0100", base),
                           ("2026-11-22 05:17:23z", base)):
            self.assertAlmostEqual(server.iso_seconds(text), want, places=5, msg=text)
        for bad in ("", "soon", "2026-11-22T25:00:00Z", None, 5):
            self.assertIsNone(server.iso_seconds(bad), bad)

    def test_budget_without_codex(self):
        with mock.patch.object(server, "codex_installed", lambda: False), \
             mock.patch.object(server, "CodexClient", side_effect=AssertionError("not called")), \
             mock.patch.object(server, "claude_budget", return_value=["Claude Code: x"]), \
             mock.patch.object(server, "aa_scores", return_value=({}, "no key")), \
             mock.patch.object(server, "agy_budget", return_value=None):
            out = server.consultant_budget({})
            self.assertIn("Codex: not installed.", out)
            self.assertNotIn("Codex", [g["title"] for g in server.subscription_groups(0, None, None, os.devnull)])
            saved = {"ts": 100, "plan": "plus", "primary": {"used_percent": 10, "window_minutes": 300,
                                                            "resets_at": 1000}}
            kept = server.subscription_groups(200, None, saved, os.devnull)[0]
            self.assertEqual(kept["title"], "Codex plus")
            self.assertIn("Codex isn't on PATH", kept["note"])
        self.assertIn("Codex", [g["title"] for g in server.subscription_groups(0, None, None, os.devnull)])



class UsageLogTest(HandlerTest):
    """0.14.0: the usage log and the `top` status screen."""

    NOW = 1_800_000_000

    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.dir, True)
        patcher = mock.patch.object(server, "nouez_cache_dir", return_value=self.dir)
        patcher.start()
        self.addCleanup(patcher.stop)
        env = mock.patch.dict(os.environ, {"NOUEZ_NO_USAGE_LOG": ""})
        env.start()
        self.addCleanup(env.stop)
        self.log = os.path.join(self.dir, server.USAGE_LOG_FILE)

    def events(self):
        return server.read_usage_log(self.log)

    def test_a_usage_log_line_that_isnt_utf8_is_skipped(self):
        with open(self.log, "wb") as f:
            f.write(b'{"ts": 1, "event": "send", "reason": "bad \xff byte"}\n{"ts": 2, "event": "send"}\n')
        self.assertEqual([e["ts"] for e in self.events()], [2])  # the next line is still read

    def test_verdicts(self):
        for text, want in (("Verdict: yes", "yes"), ("**Verdict:** CHANGES - two fixes", "changes"),
                           ("No changes needed, ready.", "yes"), ("GO", "yes"), ("NO-GO: tests fail", "no"),
                           ("Verdict: no, the plan assumes X", "no"), ("Yes with changes: see 2", "changes"),
                           ("\n\n  Blocked on the schema", "no"), ("Let me look at this.", None),
                           ("I made changes to the plan", None), ("", None), (None, None),
                           ("Looks fine.\nVerdict: no", "no"),  # 0.26.0: a labelled line under one without a verdict
                           ("Not approved: see 1", "no"), ("not ok yet", "no"), ("OK.", "yes"),
                           ("Okay, ship it", "yes"), ("OK, I will inspect the patch", None),
                           # a review that couldn't read its input approves nothing
                           ("Incomplete: no findings because the diff could not be read.", "incomplete"),
                           ("No findings: I can't read the diff.", "incomplete"),
                           ("No findings because I couldn’t read the full diff.", "incomplete"),
                           ("Not reviewed: server.py", "incomplete"), ("I couldn't find any issues; LGTM", "yes"),
                           # "incomplete" about the code under review isn't the review's own verdict
                           ("LGTM - the fix correctly rejects incomplete files.", "yes"),
                           # an explicit verdict is read from the word after its label
                           ("Verdict: CHANGES because the implementation is incomplete.", "changes"),
                           ("Verdict: yes. I couldn't read the tests", "yes"), ("Verdict: no changes needed", "yes"),
                           ("Verdict: yes, with changes.", "changes"), ("Verdict: yes (with changes).", "changes"),
                           ("Verdict: approved with no changes.", "yes"),
                           ("Verdict: yes. But the changes still need to be deployed.", "yes"),
                           ("No findings: I couldn't find the diff.", "incomplete"),
                           ("I couldn't find any changes that break callers; LGTM", "yes"),
                           ("Verdict — incomplete — couldn't open the patch", "incomplete"),
                           ("Verdict: NO-GO", "no"), ("Verdict: approve with nits", "yes"),
                           ("1. **Final verdict:** no-go", "no"), ("My verdict: yes", "yes"),
                           # only at the start of the line: quoted words don't override the reviewer
                           ("CHANGES: the parser reports 'Verdict: yes' for failures.", "changes"),
                           ("The verdict depends on the schema", None),
                           # 0.26.0: a labelled verdict a few lines down, under a first line without one
                           ("Reviewed commit abc.\n\nVerdict: CHANGES\n1. fix x", "changes"),
                           ("Reviewed commit abc.\n**Verdict:** yes", "yes"),
                           ("CHANGES: x.\nVerdict: yes", "changes"),  # the first line's verdict stands
                           ("a\nb\nc\nd\ne\nVerdict: yes", None),  # past the first five lines
                           ("Reviewed commit abc.\nNo issues in the parser.", None)):  # unlabelled: not read
            with self.subTest(text=text):
                self.assertEqual(server.verdict_of(text), want)
        for status in ("interrupted", "failed"):  # a turn that didn't finish concluded nothing
            self.assertEqual(server.verdict_of("Verdict: yes", status), "incomplete")

    def test_kind_and_reason_are_checked(self):
        self.assertEqual(server.kind_and_reason({}), (None, None))
        self.assertEqual(server.kind_and_reason({"kind": "review", "reason": "  a\n b  "}), ("review", "a b"))
        self.assertEqual(len(server.kind_and_reason({"reason": "x" * 900})[1]), server.REASON_CHARS)
        with self.assertRaisesRegex(server.BridgeError, "`kind` must be one of"):
            server.kind_and_reason({"kind": "chat"})
        with self.assertRaisesRegex(server.BridgeError, "`reason` must be a string"):
            server.kind_and_reason({"reason": 5})

    def test_a_bad_kind_sends_nothing(self):
        thread = self.consultant("kind01")
        daemon = self.use(FakeDaemon([thread]))
        with self.assertRaises(server.BridgeError):
            server.send_consultant_message({"to": thread["id"], "message": "hi", "kind": "nope"})
        self.assertNotIn("turn/start", daemon.calls)
        self.assertEqual(self.events(), [])

    def test_send_and_reply_are_logged(self):
        later = time.time() + 7 * 86400  # the send reads the real clock: windows that haven't reset
        with open(os.path.join(self.dir, server.CLAUDE_USAGE_FILE), "w", encoding="utf-8") as f:
            json.dump({"rate_limits": {"seven_day": {"used_percentage": 41, "resets_at": later}}}, f)
        thread = self.consultant("log001", model="gpt-a", reasoningEffort="high")
        daemon = self.use(FakeDaemon([thread], answer="Verdict: CHANGES\n1. fix x"))
        plain = daemon.request

        def request(method, params):
            if method == "account/rateLimits/read":
                # 0.26.4: a window past its reset is left out, as ConsultantBudget and top do
                return {"rateLimits": {"primary": {"usedPercent": 12, "windowDurationMins": 10080, "resetsAt": later},
                                       "secondary": {"usedPercent": 99, "windowDurationMins": 300, "resetsAt": 1}}}
            return plain(method, params)
        daemon.request = request
        out = server.send_consultant_message({"to": thread["id"], "message": "review this", "model": "gpt-b",
                                              "effort": "high", "kind": "review", "reason": "diff before commit"})
        self.assertIn("Verdict: CHANGES", out)
        send, reply = self.events()
        self.assertEqual(send["event"], "send")
        self.assertEqual((send["model"], send["effort"], send["changed"]), ("gpt-b", "high", ["model"]))
        self.assertEqual((send["kind"], send["reason"], send["mode"]), ("review", "diff before commit", "new"))
        self.assertEqual(send["usage"], {"codex": {"weekly": 12}, "claude": {"weekly": 41}})
        # 0.28.2: and beside each share, when that window resets and when it was read
        self.assertEqual(send["usage_meta"]["codex"]["weekly"]["resets_at"], round(later))
        self.assertEqual(send["usage_meta"]["claude"]["weekly"]["resets_at"], round(later))
        self.assertLessEqual(send["usage_meta"]["codex"]["weekly"]["sampled"], send["ts"] + 1)
        self.assertEqual(send["chars"], len("review this"))
        self.assertNotIn("review this", json.dumps(send))  # never the message itself
        self.assertEqual((reply["event"], reply["turn"], reply["verdict"]), ("reply", send["turn"], "changes"))
        self.assertNotIn("fix x", json.dumps(reply))

    def test_start_is_logged_and_the_log_can_be_turned_off(self):
        self.use(FakeDaemon([]))
        server.start_consultant({"cwd": ROOT})
        (start,) = self.events()
        self.assertEqual((start["event"], start["new"]), ("start", True))
        with mock.patch.dict(os.environ, {"NOUEZ_NO_USAGE_LOG": "1"}):
            server.record_usage({"event": "x"}, self.log)
        self.assertEqual(len(self.events()), 1)

    def test_log_is_rotated_and_never_raises(self):
        with mock.patch.object(server, "USAGE_LOG_BYTES", 10):
            server.record_usage({"event": "a", "pad": "x" * 20}, self.log)
            server.record_usage({"event": "b"}, self.log)
        self.assertEqual([e["event"] for e in self.events()], ["a", "b"])  # 0.16.0: the rotated file too
        with open(self.log, encoding="utf-8") as f:
            self.assertEqual([json.loads(x)["event"] for x in f], ["b"])
        self.assertEqual(len(glob.glob(os.path.join(self.dir, "usage-log-*.jsonl"))), 1)
        with mock.patch.object(server, "open", side_effect=OSError("disk full"), create=True):
            server.record_usage({"event": "c"}, self.log)  # logged to stderr, not raised

    def test_log_is_renamed_monthly_and_old_logs_go(self):
        """0.22.0: a log begun over a month ago is renamed; renamed logs go after a year or past the size cap."""
        now = self.NOW
        server.record_usage({"event": "a"}, self.log, now - 31 * 86400)
        server.record_usage({"event": "b"}, self.log, now)
        with open(self.log, encoding="utf-8") as f:
            self.assertEqual([json.loads(x)["event"] for x in f], ["b"])
        [first] = server.rotated_usage_logs(self.log)
        self.assertEqual([e["event"] for e in self.events()], ["a", "b"])
        # Renamed in the same second as another: a suffix, still read in order
        same = first[:-len(".jsonl")] + "-1.jsonl"
        with open(same, "w", encoding="utf-8") as f:
            f.write(json.dumps({"ts": now - 1, "event": "a2"}) + "\n")
        self.assertEqual([e["event"] for e in self.events()], ["a", "a2", "b"])
        # A year untouched: deleted; the current log never is
        old = os.path.join(self.dir, "usage-log-20200101-000000.jsonl")
        with open(old, "w", encoding="utf-8") as f:
            f.write(json.dumps({"ts": 1, "event": "ancient"}) + "\n")
        year = time.time() - (server.USAGE_LOG_KEEP_DAYS + 1) * 86400
        os.utime(old, (year, year))
        os.utime(self.log, (year, year))
        server.prune_usage_logs(self.log)
        self.assertFalse(os.path.exists(old))
        self.assertTrue(os.path.exists(self.log))
        # Past the size cap: the oldest go first
        with mock.patch.object(server, "USAGE_LOG_KEEP_BYTES", os.path.getsize(same)):
            server.prune_usage_logs(self.log)
        self.assertEqual(server.rotated_usage_logs(self.log), [same])

    def test_log_is_written_privately(self):
        """0.22.0: the log is this user's only, and never written through a link."""
        server.record_usage({"event": "a"}, self.log)
        if os.name != "nt":
            self.assertEqual(os.stat(self.log).st_mode & 0o777, 0o600)
        target = os.path.join(self.dir, "elsewhere.jsonl")
        open(target, "w").close()
        os.remove(self.log)
        file_link(self, target, self.log)
        server.record_usage({"event": "b"}, self.log)
        self.assertEqual(os.path.getsize(target), 0)

    def test_two_servers_rotating_lose_no_event(self):
        """0.22.0: servers writing and renaming the log at once keep every event, once."""
        code = ("import sys; sys.path.insert(0, sys.argv[1]); import server\n"
                "server.USAGE_LOG_BYTES = 300\n"
                "server.USAGE_LOG_WAIT = 60\n"  # a slow machine waits rather than skips
                "for i in range(60):\n"
                "    server.record_usage({'event': 'e', 'who': sys.argv[3], 'i': i}, sys.argv[2])\n")
        env = dict(os.environ, NOUEZ_NO_USAGE_LOG="")
        procs = [subprocess.Popen([sys.executable, "-I", "-c", code, ROOT, self.log, who], env=env)
                 for who in ("a", "b")]
        for proc in procs:
            self.assertEqual(proc.wait(60), 0)
        seen = [(e["who"], e["i"]) for e in self.events()]
        self.assertEqual(sorted(seen), sorted((who, i) for who in "ab" for i in range(60)))
        self.assertGreater(len(server.rotated_usage_logs(self.log)), 5)

    @unittest.skipUnless(hasattr(os, "mkfifo"), "named pipes are POSIX")
    def test_a_pipe_for_a_log_is_never_written(self):
        """0.22.0: a pipe where the log goes is skipped, not opened: the append would wait under the lock."""
        os.mkfifo(self.log)
        start = time.monotonic()
        server.record_usage({"event": "a"}, self.log)
        self.assertLess(time.monotonic() - start, 1.5)
        self.assertFalse(server.usage_log_due(self.log, self.NOW))

    def test_a_linked_log_is_never_read_or_renamed(self):
        """0.22.0: a log or renamed log that is a link (or a junction) is left alone."""
        outside = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, outside, True)
        dir_link(outside, self.log)
        dir_link(outside, os.path.join(self.dir, "usage-log-20261101-000000.jsonl"))
        self.assertFalse(server.usage_log_due(self.log, self.NOW))
        self.assertEqual(server.rotated_usage_logs(self.log), [])
        self.assertEqual(self.events(), [])
        server.rotate_usage_log(self.log, self.NOW)
        self.assertTrue(server.is_link(self.log))

    def test_log_summary(self):
        t = self.NOW
        ev = [{"ts": t, "event": "start", "new": True},
              {"ts": t + 1, "event": "send", "thread": "A", "turn": "1", "consultant": "ca", "project": "p",
               "model": "m", "effort": "high", "kind": "review", "reason": "r1", "mode": "new", "changed": ["effort"]},
              {"ts": t + 2, "event": "reply", "turn": "1", "status": "completed", "ms": 60000, "verdict": "changes"},
              {"ts": t + 3, "event": "reply", "turn": "1", "status": "completed", "ms": 60000, "verdict": "changes"},
              {"ts": t + 4, "event": "send", "thread": "A", "turn": "2", "consultant": "ca", "project": "p",
               "model": "m", "effort": "high", "kind": "re-check", "mode": "new"},
              {"ts": t + 5, "event": "reply", "turn": "2", "status": "completed", "ms": 120000, "verdict": "changes"},
              {"ts": t + 6, "event": "send", "thread": "A", "turn": "3", "consultant": "ca", "project": "p",
               "model": "m", "effort": "high", "mode": "steer"},
              {"ts": t + 7, "event": "reply", "turn": "3", "status": "completed", "ms": 30000, "verdict": "changes"},
              {"ts": t + 8, "event": "send", "thread": "B", "turn": "9", "consultant": "cb", "project": "q",
               "model": "n", "mode": "new"}]
        s = server.log_summary(ev)
        self.assertEqual((s["sends"], s["replies"], s["steered"], s["changed"], s["new_consultants"]), (4, 3, 1, 1, 1))
        self.assertEqual(s["models"]["m high"], 3)
        self.assertEqual(s["kinds"]["not given"], 2)
        self.assertEqual(s["verdicts"]["changes"], 3)
        self.assertEqual(s["loops"][0], {"thread": "A", "consultant": "ca", "project": "p", "rounds": 3,
                                         "changes_streak": 3})
        self.assertEqual(s["reply_seconds"][0], 60)
        self.assertEqual(server.log_summary(ev, since=t + 6)["sends"], 2)
        scr = server.Screen(False)
        text = "\n".join(server.consultation_rows(scr, s, 7))
        self.assertIn("4 messages (last 7 days)", text)
        self.assertIn("1 consultant(s) had 3+ CHANGES rounds in a row", text)
        # Each count with its share, of the messages (verdicts: of the replies read).
        self.assertRegex(text, r"m high +3  75%.*not given +2  50%.*changes +3 100%.*p +3  75%")
        self.assertEqual([server.share(n, t) for n, t in ((0, 4), (1, 400), (1, 3), (2, 0))], ["0%", "<1%", "33%", ""])
        self.assertIn("No consultations logged", "\n".join(server.consultation_rows(scr, server.log_summary([]), None)))

    def test_summary_counts_replies_to_the_periods_messages(self):
        """0.16.0: replies are those to the period's messages, read once; steering isn't a round."""
        t = self.NOW

        def send(ts, turn, **kw):
            return {"ts": t + ts, "event": "send", "thread": "A", "turn": turn, "consultant": "ca",
                    "project": "p", "model": "m", "effort": "high", "mode": "new", **kw}

        def reply(ts, turn, verdict="changes", **kw):
            return {"ts": t + ts, "event": "reply", "turn": turn, "status": "completed", "ms": 1000,
                    "verdict": verdict, **kw}
        ev = [send(0, "0"), reply(1, "0", "yes"), send(5, "5"), reply(20, "5", "yes"),
              send(10, "1", reason="old"), send(11, "1", mode="steer"), send(12, "1", mode="steer"),
              reply(13, "1"), reply(30, "0", "no"),  # turn 0 read again later: the first read stands
              send(14, "2", reason="new"), reply(15, "2", status="interrupted"),
              send(16, "3", model="gemini-4-neon-low", effort="low", provider="antigravity", kind="review"),
              send(17, "4", model="claude-x", effort="", provider="antigravity")]
        s = server.log_summary(ev, since=t + 10)
        self.assertEqual((s["sends"], s["replies"], s["other_replies"]), (6, 2, 1))
        # turn 2 was interrupted: logged as "changes" by an older version, it counts as incomplete
        self.assertEqual(dict(s["verdicts"]), {"changes": 1, "incomplete": 1})
        self.assertEqual(s["statuses"]["interrupted"], 1)
        self.assertEqual(s["loops"][0]["rounds"], 4)  # turns 1, 2, 3, 4: the steers are turn 1
        self.assertEqual(s["loops"][0]["changes_streak"], 1)
        self.assertEqual(list(s["reasons"]), ["new", "old"])
        self.assertEqual(s["models"]["gemini-4-neon low"], 1)
        self.assertEqual(s["models"]["claude-x (AG)"], 1)
        self.assertEqual(s["routes"][("review", "gemini-4-neon low")], 1)
        self.assertEqual(s["first_ts"], t + 10)
        text = "\n".join(server.consultation_rows(server.Screen(False), s, 7))
        self.assertIn("6 messages (last 7 days) · 2 of their replies read (1 interrupted)", text)
        self.assertIn("1 other replies read", text)
        only = server.log_summary(ev, since=t + 18)  # replies, no messages
        self.assertEqual("\n".join(server.consultation_rows(server.Screen(False), only, 7)),
                         "  0 messages (last 7 days) · 0 of their replies read · 1 other replies read")
        self.assertIn("review → gemini-4-neon low", text)
        self.assertNotIn("reasons given", "\n".join(server.consultation_rows(server.Screen(False), s, 7, True)))

    def test_rotated_logs_are_read_in_order(self):
        rotated = os.path.join(self.dir, "usage-log-20261101-000000.jsonl")
        self.write(rotated, ['{"ts": 1, "event": "old"}\n'])
        self.write(os.path.join(self.dir, "usage-log-other.jsonl"), ['{"ts": 2, "event": "not ours"}\n'])
        self.write(self.log, ['{"ts": 3, "event": "new"}\n'])
        self.assertEqual([e["event"] for e in self.events()], ["old", "new"])

    def test_window_rows_fit_and_use_the_sample_time(self):
        scr, now = server.Screen(False), self.NOW

        def window_row(owner, label, used, resets_at, length, now, sampled=None):
            return server.full_row(scr, owner, label, server.window_state(used, resets_at, length, now, sampled), now)
        self.assertEqual(server.window_pace(100, now + 3600, 7 * 86400, now - 86400 * 30), ("used up", None))
        row = window_row("Codex prolite", "weekly", 0.2, now + 3.5 * 86400, 7 * 86400, now)
        self.assertIn(" <1%", row)
        self.assertLessEqual(len(row), 100)
        # saved at half the window with 50% used: ~100% by the reset, whatever the clock says now
        fresh = window_row("Claude Code", "weekly", 40, now + 3 * 86400, 7 * 86400, now, now - 60)
        self.assertIn("pace: ~", fresh)
        old = window_row("Claude Code", "weekly", 40, now + 3 * 86400, 7 * 86400, now, now - 7200)
        self.assertIn("an old reading (2h 0m old): at least 40% by the reset", old)
        old = window_row("Claude Code", "weekly", 100, now + 3 * 86400, 7 * 86400, now, now - 7200)
        self.assertIn("used up at the last reading", old)
        fast = window_row("Codex", "weekly", 90, now + 3 * 86400, 7 * 86400, now)
        self.assertRegex(fast, r"runs out in ~\d")

    def write(self, path, lines, mode="w"):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, mode, encoding="utf-8", newline="\n") as f:
            f.write("".join(lines))

    def test_scan_counts_tokens_once_and_reads_on(self):
        claude, codex = os.path.join(self.dir, "claude"), os.path.join(self.dir, "codex")
        stamp = time.strftime("%Y-%m-%dT%H:%M:%S.000Z", time.gmtime(time.time() - 60))

        def reply(mid, out, model="claude-opus-5-5"):
            return json.dumps({"type": "assistant", "timestamp": stamp,
                               "message": {"id": mid, "model": model, "usage": {"output_tokens": out}}}) + "\n"
        main = os.path.join(claude, "proj", "s1.jsonl")
        self.write(main, [reply("m1", 100), reply("m1", 100), reply("m2", 50, "claude-haiku-5-5"),
                          '{"type":"user"}\n', reply("m3", 7)[:-1]])  # m1 written twice; m3 not finished
        self.write(os.path.join(claude, "proj", "s1", "subagents", "a.jsonl"), [reply("s1", 30)])

        def tokens(out, source=None):
            if source:
                return json.dumps({"timestamp": stamp, "type": "session_meta",
                                   "payload": {"thread_source": source}}) + "\n"
            return json.dumps({"timestamp": stamp, "type": "event_msg", "payload": {
                "type": "token_count", "info": {"total_token_usage": {"input_tokens": 10 * out, "output_tokens": out}},
                "rate_limits": {"plan_type": "pro", "primary": {"used_percent": 8.0, "window_minutes": 10080,
                                                                 "resets_at": time.time() + 86400}}}}) + "\n"
        ours = os.path.join(codex, "sessions", "2026", "rollout-a.jsonl")
        self.write(ours, [tokens(0, "nouez"), tokens(40), tokens(40), tokens(100)])  # running totals
        self.write(os.path.join(codex, "archived_sessions", "rollout-b.jsonl"), [tokens(0, "vscode"), tokens(25)])
        state = server.scan_usage({}, time.time(), claude, codex)
        (week,) = server.weekly_tokens(state).values()
        self.assertEqual((week["claude"], week["subagents"], week["consultants"], week["codex"]), (150, 30, 100, 25))
        self.assertEqual(week["models"], {"claude-opus-5-5": 130, "claude-haiku-5-5": 50})
        self.assertEqual(state["codex_limits"]["plan"], "pro")
        # read on from where it stopped: m3 finished, m1 again (split across the scan), new lines
        self.write(main, ["\n", reply("m1", 100), reply("m4", 5)], "a")
        self.write(ours, [tokens(130)], "a")
        state = server.scan_usage(state, time.time(), claude, codex)
        (week,) = server.weekly_tokens(state).values()
        self.assertEqual((week["claude"], week["consultants"]), (162, 130))
        # a rewritten (shorter) file is read again from the start
        self.write(main, [reply("x1", 9)])
        state = server.scan_usage(state, time.time(), claude, codex)
        (week,) = server.weekly_tokens(state).values()
        self.assertEqual(week["claude"], 9)
        # a file that's gone drops out
        os.remove(ours)
        state = server.scan_usage(state, time.time(), claude, codex)
        self.assertEqual(server.weekly_tokens(state)[server.week_of(time.time() - 60)]["consultants"], 0)

    def test_a_reply_copied_into_another_transcript_counts_once(self):
        """A forked subagent's transcript starts with its parent's history: those replies count once,
        in the first of the session's transcripts that has them, and a copy in another session's isn't
        one. Whatever changes between scans, the counts are those of a fresh scan."""
        claude, codex = os.path.join(self.dir, "claude"), os.path.join(self.dir, "codex")
        stamp = time.strftime("%Y-%m-%dT%H:%M:%S.000Z", time.gmtime(time.time() - 60))

        def reply(mid, out, **kw):
            return json.dumps({"type": "assistant", "timestamp": stamp, **kw,
                               "message": {"id": mid, "model": "m", "usage": {"output_tokens": out}}}) + "\n"

        def scan(state):
            state = server.scan_usage(state, time.time(), claude, codex)
            (week,) = server.weekly_tokens(state).values() or [{"claude": 0, "subagents": 0}]
            (anew,) = server.weekly_tokens(server.scan_usage({}, time.time(), claude, codex)).values() \
                or [{"claude": 0, "subagents": 0}]
            self.assertEqual((week["claude"], week["subagents"]), (anew["claude"], anew["subagents"]))
            return state, (week["claude"], week["subagents"])
        main = os.path.join(claude, "proj", "s1.jsonl")
        fork = os.path.join(claude, "proj", "s1", "subagents", "agent-f.jsonl")
        again = os.path.join(claude, "proj", "s1", "subagents", "agent-g.jsonl")
        self.write(fork, ['{"type":"fork-context-ref"}\n', reply("msg_parent0001", 30, isSidechain=True),
                          reply("msg_own0000001", 5, isSidechain=True)])
        self.write(main, [reply("msg_parent0001", 30), reply("msg_parent0002", 40)])
        # a reply with no time counts nowhere, and so doesn't keep its copy from counting
        self.write(again, [reply("msg_own0000001", 5), reply("msg_parent0002", 40), reply("msg_own0000002", 2),
                           reply("x_123456789abc", 3)])
        self.write(os.path.join(claude, "proj", "s1", "subagents", "agent-h.jsonl"),
                   [json.dumps({"type": "assistant", "message": {"id": "msg_own0000003", "usage": {"output_tokens": 9}}}) + "\n",
                    reply("y_123456789abc", 4)])  # ids that end alike are different replies
        self.write(os.path.join(claude, "other", "s2.jsonl"), [reply("msg_parent0001", 30)])  # not a copy
        state, counts = scan({})
        self.assertEqual(counts, (100, 14))  # 30 + 40 + 30; 5 + 2 + 3 + 4
        # read on: a copy added later isn't counted either
        self.write(fork, [reply("msg_parent0002", 40, isSidechain=True)], "a")
        state, counts = scan(state)
        self.assertEqual(counts, (100, 14))
        # the session's own transcript rewritten shorter: parent0002 now counts in the first fork that has it
        self.write(main, [reply("msg_parent0001", 30)])
        state, counts = scan(state)
        self.assertEqual(counts, (60, 54))
        # gone: its replies count in the forks
        os.remove(main)
        state, counts = scan(state)
        self.assertEqual(counts, (30, 84))
        # back, after its forks were read: its replies count in it again, not in the forks
        self.write(main, [reply("msg_parent0001", 30), reply("msg_parent0002", 40)])
        state, counts = scan(state)
        self.assertEqual(counts, (100, 14))
        # a transcript that can't be read: its session keeps the last scan's counts until it can
        self.write(fork, [reply("msg_own0000004", 6, isSidechain=True)], "a")
        lines = server.new_lines

        def unreadable(path, entry):
            if path == fork:
                raise PermissionError(path)
            return lines(path, entry)
        with mock.patch.object(server, "new_lines", unreadable):
            state = server.scan_usage(state, time.time(), claude, codex)
        (week,) = server.weekly_tokens(state).values()
        self.assertEqual((week["claude"], week["subagents"]), (100, 14))
        state, counts = scan(state)
        self.assertEqual(counts, (100, 20))

    def test_frame_and_once(self):
        scr = server.Screen(True)
        line = scr.paint("abcdef", "31") + "ghi"
        self.assertEqual(server.fit(line, 4), "\x1b[31mabcd\x1b[0m")
        self.assertEqual(server.ANSI.sub("", server.fit(line, 100)), "abcdefghi")
        self.assertEqual(server.bar(50, 4), "██░░")
        self.assertNotIn("\x1b[32m", server.painted_bar(scr, 0, 4, "32"))  # 0.16.0: an empty bar isn't coloured
        self.assertTrue(server.painted_bar(scr, 50, 4, "32").startswith("\x1b[32m██\x1b[0m"))
        now = time.time()
        live = {"rateLimits": {"planType": "pro", "primary": {"usedPercent": 30, "windowDurationMins": 10080,
                                                               "resetsAt": now + 3.5 * 86400}}}
        frame = "\n".join(server.top_frame(server.Screen(False), now, 7, live, {}, [], True, 120))
        self.assertIn("Codex pro", frame)
        # 0.17.0: from 149 columns, a card per subscription beside the other panels
        wide = server.top_frame(server.Screen(False), now, 7, live, {}, [], True, 200)
        self.assertTrue(all(server.visible(x) <= 200 for x in wide))
        self.assertRegex(wide[0], r"^nouez \S+   ● Codex 30%   ○ Claude \?")  # the top bar's badges
        self.assertRegex(wide[1], r"^╭─ Codex pro ─+╮ ╭─ CONSULTATIONS")
        self.assertRegex("\n".join(wide), r"│ weekly  .* 30%  ~60% pace  ")
        self.assertIn("[?] help", wide[-1])
        checking = server.top_frame(server.Screen(False), now, 7, live, {}, [], True, 100, {"checking": True})
        self.assertTrue(any("Antigravity" in x and "checking" in x for x in checking))
        # a short screen drops the optional lists first and keeps the latest week
        scan = {}
        ev = [{"ts": now, "event": "send", "turn": str(i), "thread": "A", "reason": f"r{i}", "kind": "review",
               "model": "m"} for i in range(5)]
        full = server.top_frame(server.Screen(False), now, 7, live, scan, ev, False, 100)
        short = server.top_frame(server.Screen(False), now, 7, live, scan, ev, False, 100, None, len(full) - 3)
        self.assertLessEqual(len(short), len(full) - 3)
        self.assertNotIn("  reasons given (latest first)", short)
        self.assertIn("OFFLOAD", "\n".join(short))
        tiny = server.top_frame(server.Screen(False), now, 7, live, scan, ev, False, 100, None, 12)
        self.assertLessEqual(len(tiny), 12)
        self.assertRegex(tiny[-3], server.week_of(now) + " ")  # the latest week, in a closed box
        self.assertTrue(tiny[-2].startswith("╰") and "[q] quit" in tiny[-1])
        self.assertEqual(sum(x.startswith("╭") for x in tiny), sum(x.startswith("╰") for x in tiny))
        least = server.top_frame(server.Screen(False), now, 7, live, scan, ev, False, 100, None, 6)
        self.assertEqual(len(least), 6)  # just OFFLOAD: its title, header and latest week
        self.assertRegex(least[3], server.week_of(now) + " ")
        exact = server.top_frame(server.Screen(False), now, 7, live, scan, ev, False, 100, None, 3)
        self.assertEqual(len(exact), 3)  # shorter still: cut, with the keys still last
        self.assertIn("[q] quit", exact[-1])
        self.assertIn("pace: ~60% by the reset", frame)
        self.assertIn("Claude Code     usage not known", frame)
        self.assertIn("Reading transcripts for the first time", frame)
        saved = {"ts": now - 600, "plan": "pro", "primary": {"used_percent": 95, "window_minutes": 300,
                                                             "resets_at": now + 3600}}
        frame = "\n".join(server.top_frame(server.Screen(False), now, None, None, {"codex_limits": saved}, [],
                                           False, 120))
        self.assertIn("runs out in", frame)
        self.assertIn("from Codex's last session file, 10 min ago", frame)
        self.assertIn("No Claude Code or Codex sessions", frame)
        # the command itself, on empty folders
        with mock.patch.object(server, "read_codex_usage", return_value=None), \
                mock.patch.object(server, "read_agy_usage", return_value=None), \
                mock.patch.object(server, "claude_config_dir", return_value=os.path.join(self.dir, "none")), \
                mock.patch.object(server, "codex_home", return_value=os.path.join(self.dir, "none")), \
                contextlib.redirect_stdout(io.StringIO()) as out:
            self.assertEqual(server.run_top(["--once", "--days", "30"]), 0)
            self.assertEqual(server.run_top(["--days", "x"]), 2)
        self.assertIn("No consultations logged (last 30 days)", out.getvalue())
        self.assertIn("NOTES", out.getvalue())  # 0.17.0: what the marks mean, at the end
        self.assertTrue(all(server.visible(x) <= server.TOP_PANEL for x in out.getvalue().splitlines()))
        self.assertTrue(os.path.exists(os.path.join(self.dir, server.SCAN_STATE_FILE)))

    def test_antigravity_rows(self):
        now = time.time()
        scr = server.Screen(False)

        def agy_rows(live):
            return server.group_rows(scr, now, server.agy_group(now, live))
        groups = server.subscription_groups(now, None, None, agy_live=None)
        self.assertNotIn("Antigravity", [g["title"] for g in groups])  # agy not installed: no rows at all
        self.assertIn("usage not known: agy: not signed in", agy_rows({"error": "agy: not signed in"})[0])

        def reset(secs):
            return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(now + secs))
        live = {"groups": [
            {"name": "Gemini Models", "buckets": [
                {"window": "weekly", "remaining_fraction": 0.25, "reset_time": reset(86400)},
                {"window": "5h", "remaining_fraction": 1, "reset_time": reset(3600)},
                {"window": "5h", "reset_time": reset(3600)}]},  # no fraction: left out
            {"name": "Claude and GPT models", "buckets": [
                {"window": "weekly", "remaining_fraction": 0.9, "reset_time": reset(-60)}]},  # past reset: left out
            {"name": "New group", "buckets": [
                {"window": "daily", "remaining_fraction": 0.5, "reset_time": reset(600)}]}]}
        text = "\n".join(agy_rows(live))
        self.assertRegex(text, r"^  Antigravity +\(Google's quota")
        self.assertRegex(text, r"\n    Gemini +weekly .* 75%")
        self.assertRegex(text, r"pace: ~8[78]% by the reset")  # 75% used in 6 of 7 days
        self.assertRegex(text, r"\n +5-hour .*  0%")
        self.assertNotRegex(text, r"Claude\+GPT +weekly")
        self.assertRegex(text, r"\n    New group +daily .* 50%")  # 0.26.4: its own name, as ConsultantBudget has it
        frame = "\n".join(server.top_frame(scr, now, 7, None, {}, [], False, 120, live))
        self.assertIn("│   Gemini ", frame)
        frame = server.top_frame(scr, now, 7, None, {}, [], False, 200, live)
        self.assertIn("● Gemini 75%", frame[0])  # the weekly window is the most used
        self.assertRegex("\n".join(frame), r"│ Gemini +│")  # a quota group's name on its own line in the card
        self.assertRegex("\n".join(frame), r"│ weekly  .* 75%  ~8[78]% pace ")

    def test_screen_parts(self):
        """0.17.0: cell widths, the gauge's marker, the badges, panels, the help view and --once."""
        scr, now = server.Screen(True), time.time()
        self.assertEqual(server.visible("日本a\u0301"), 5)  # wide characters 2, a combining mark 0
        self.assertEqual(server.fit("ab日本", 3), "ab")  # a wide character that doesn't fit goes whole
        self.assertEqual(server.visible(server.pad(scr.paint("日本", "31"), 7)), 7)
        self.assertEqual(server.unindent(scr.dim("  x")), "\x1b[90mx\x1b[0m")
        bar = server.painted_bar(scr, 50, 10, "32", 7)
        self.assertEqual(server.ANSI.sub("", bar), "█████░░┊░░")
        self.assertIn("\x1b[32m█████\x1b[0m", bar)
        state = server.window_state(30, now + 3.5 * 86400, 7 * 86400, now)
        self.assertAlmostEqual(state["gone"], 0.5)
        self.assertEqual((state["short"], state["colour"], state["rank"]), ("~60% pace", "32", 0))
        self.assertEqual(server.window_state(95, now + 3 * 86400, 7 * 86400, now)["rank"], 2)  # runs out
        self.assertEqual(server.window_state(100, now + 86400, 7 * 86400, now)["colour"], "31")
        self.assertEqual(server.window_state(10, now + 3 * 86400, 7 * 86400, now, now - 7200)["short"], "old reading")
        self.assertIsNone(server.window_state(10, now - 1, 7 * 86400, now))
        busy = server.window_state(50, now + 3 * 86400, 7 * 86400, now)  # ~88%: green
        late = server.window_state(80, now + 4 * 3600, 5 * 3600, now)  # runs out first
        plain = server.Screen(False)
        group = {"title": "Antigravity", "entries": [("Gemini", "weekly", busy), ("Claude+GPT", "5-hour", late)]}
        self.assertEqual(server.badge(plain, group), "● AG Claude+GPT 80% 5-hour")
        self.assertEqual(server.badge(plain, {"title": "Claude Code", "entries": [("", "weekly", busy)]}),
                         "● Claude 50% busy")  # 0.28.1: past 70% of the week is a word; the colour stays green
        self.assertEqual(server.badge(plain, {"title": "Antigravity", "entries": [], "checking": True}), "○ Gemini …")
        fine = server.window_state(40, now + 0.38 * 7 * 86400, 7 * 86400, now)  # ~65%
        other = server.window_state(30, now + 0.6 * 7 * 86400, 7 * 86400, now)  # ~75%: busy
        self.assertEqual(server.badge(plain, {"title": "Antigravity", "entries": [("Gemini", "weekly", fine),
                                                                                  ("Claude+GPT", "weekly", other)]}),
                         "● Gemini 40%")  # Codex 0.28.1 review: the busy group isn't the one shown
        claude = {"title": "Claude Code", "entries": [("", "weekly", busy)]}
        groups = [claude, {"title": "Antigravity", "entries": [("Claude+GPT", "weekly", fine)]}]
        with mock.patch.object(server, "login_badge", return_value=""), \
                mock.patch.object(server, "dispatcher_badge", return_value=""):
            wide = server.ANSI.sub("", server.top_bar(plain, groups, 7, now, 200))
            narrow = server.ANSI.sub("", server.top_bar(plain, groups, 7, now, len(wide.split("   ●")[0]) + 38))
        self.assertIn("● Claude 50% busy", wide)
        self.assertIn("● Claude 50%   ● AG Claude+GPT 40%", narrow)  # the word goes before a badge is cut
        rows = server.columns([("by model and effort", server.collections.Counter(
            {"claude-opus-5-5 (AG) high": 2, "claude-opus-5-5 (AG) medium": 1}))], (30,))
        self.assertIn("claude-opus-5… high", rows[1])  # cut to fit, the effort kept
        self.assertIn("claude-opus… medium", rows[2])
        self.assertTrue(server.badge(scr, group).startswith("\x1b[31m●"))
        self.assertLessEqual(server.visible(server.compact_row(scr, "weekly", late)), server.TOP_CARD - 4)
        box = server.panel(plain, "T", ["  ab", "日本"], 10)
        self.assertEqual(box, ["╭─ T ────╮", "│ ab     │", "│ 日本   │", "╰────────╯"])
        self.assertEqual(server.panel(server.Screen(False, False), "T", [], 7), ["┌─ T ─┐", "└─────┘"])
        self.assertTrue(server.fancy_terminal({"WT_SESSION": "1"}))
        self.assertEqual(server.fancy_terminal({}), os.name != "nt")
        self.assertEqual(server.sends_per_day([{"ts": now - 86400 - 5, "event": "send"}, {"ts": now, "event": "send"},
                                               {"ts": now, "event": "send", "mode": "steer"}], now, 3), [0, 1, 1])
        self.assertEqual(server.spark(plain, [0, 1, 4]), "·▂█")
        ev = [{"ts": now - 60, "event": "send", "turn": "1", "thread": "A", "kind": "review", "model": "m"}]
        frame = server.top_frame(plain, now, 7, None, {}, ev, False, 100)
        self.assertTrue(any(x.startswith("│ per day   ······▁") or x.startswith("│ per day   ······█")
                            for x in frame))
        helped = server.top_frame(plain, now, 7, None, {}, ev, False, 100, None, 40, "help")
        self.assertTrue(helped[1].startswith("╭─ HELP"))
        self.assertIn("[Esc] back", helped[-1])
        self.assertIn("log    ", "\n".join(helped))
        once = server.top_frame(plain, now, 7, None, {}, ev, False, server.TOP_PANEL, None, None, "once")
        self.assertTrue(once[-1].startswith("╰") and any(x.startswith("╭─ NOTES") for x in once))
        self.assertFalse(any("[q] quit" in x for x in once))  # nothing to press in a file
        self.assertTrue(all(server.visible(x) <= server.TOP_PANEL for x in once))

    def test_read_agy_usage(self):
        groups = [{"name": "Gemini Models", "buckets": []}]
        answer = json.dumps({"status": "SUCCESS", "num_turns": 0,
                             "command": {"name": "usage", "data": {"groups": groups}}})
        with mock.patch.object(server, "agy_command", return_value=None), \
                mock.patch.object(server.subprocess, "run") as run:
            self.assertIsNone(server.read_agy_usage())
            run.assert_not_called()
        with mock.patch.object(server, "agy_command", return_value="agy"), \
                mock.patch.object(server.subprocess, "run") as run:
            run.return_value = subprocess.CompletedProcess([], 0, "noise\n" + answer + "\n", "")
            with mock.patch.object(server.time, "time", lambda: 1000.0):
                self.assertEqual(server.read_agy_usage(), {"groups": groups, "read_at": 1000.0})
            argv = run.call_args.args[0]
            self.assertEqual(argv[:5], ["agy", "-p", "/usage", "--output-format", "json"])
            self.assertEqual(json.loads(argv[argv.index("--settings") + 1]), server.AGY_READ_ONLY)
            self.assertIs(run.call_args.kwargs["stdin"], subprocess.DEVNULL)
            # a reading is reused for a minute and a half, each send reading it, with when agy answered;
            # a failed one isn't kept
            with mock.patch.object(server.time, "time", lambda: 1060.0):
                self.assertEqual(server.read_agy_usage(), {"groups": groups, "read_at": 1000.0})
            self.assertEqual(run.call_count, 1)
            server._agy_usage["at"] -= server.AGY_USAGE_CACHE
            run.return_value = subprocess.CompletedProcess([], 1, "", "Error: You are not logged into Antigravity.\n")
            self.assertEqual(server.read_agy_usage(), {"error": "agy: Error: You are not logged into Antigravity."})
            run.side_effect = subprocess.TimeoutExpired("agy", 30)
            self.assertEqual(server.read_agy_usage(), {"error": "agy didn't answer (TimeoutExpired)"})
        server._agy_usage.update(at=0.0, agy=None, value=None)

    def test_agy_command(self):
        d = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, d, True)
        with mock.patch.object(server, "which", return_value="/bin/agy"):
            self.assertEqual(server.agy_command({"PATH": "x"}), "/bin/agy")
        with mock.patch.object(server, "which", return_value=None):
            self.assertIsNone(server.agy_command({"PATH": "x", "LOCALAPPDATA": d}))
            os.makedirs(os.path.join(d, "agy", "bin"))
            open(os.path.join(d, "agy", "bin", "agy.exe"), "w").close()
            want = os.path.join(d, "agy", "bin", "agy.exe") if os.name == "nt" else None
            self.assertEqual(server.agy_command({"PATH": "x", "LOCALAPPDATA": d}), want)

def agy_lines(*events):
    return "".join(json.dumps(e) + "\n" for e in events)


AGY_INIT = {"event": "init", "conversation_id": "conv-1234-abcd", "init": {"model": "gemini-4-neon-high"}}


def agy_result(text, status="SUCCESS", **extra):
    return {"event": "result", "result": {"conversation_id": "conv-1234-abcd", "status": status, "response": text,
                                          "duration_seconds": 7.5, "usage": {"input_tokens": 900, "output_tokens": 120,
                                                                             "thinking_tokens": 80, "total_tokens": 1020},
                                          **extra}}


class SuggestTest(unittest.TestCase):
    """0.24.0: ConsultantBudget suggests the provider, model and effort for each kind."""
    NOW = 1_800_000_000.0
    DAY = 86400
    EFFORTS = ["low", "medium", "high", "xhigh", "max"]

    def codex(self, used=10, days_left=5, models=None):
        gone = 7 - days_left  # a window that started (7 - days_left) days ago, used evenly
        week = (7 * self.DAY, used, self.NOW + days_left * self.DAY)
        listed = models if models is not None else ["gpt-6.2-sol", "gpt-6.2-astra"]
        return {"windows": [week] if gone else [],
                "models": {m: (self.EFFORTS, "low", i == 0) for i, m in enumerate(listed)}}

    def agy(self, gemini=10, claude=0, days_left=5, models=None):
        ids = models if models is not None else (
            [f"gemini-4-neon-{lv}" for lv in ("low", "medium", "high", "xhigh")]
            + [f"claude-opus-5-5-{lv}" for lv in ("low", "medium", "high")])
        reset = self.NOW + days_left * self.DAY
        return {"groups": {"Gemini Models": [(7 * self.DAY, gemini, reset)],
                           "Claude and GPT models": [(7 * self.DAY, claude, reset)]}, "models": ids}

    def pick(self, kind, **state):
        got = server.suggest_consultant(kind, state, self.NOW)
        return got.get("none") or (got["provider"], got["model"], got["effort"])

    def test_a_week_percent_that_isnt_a_pace_isnt_called_one(self):
        """0.26.4: an old reading, or one too early in the week to project from, is the least the
        week reaches, and the words say so; a projection is a pace."""
        week = 7 * self.DAY
        old = [(week, 95, self.NOW + 3 * self.DAY, self.NOW - 7200)]
        self.assertEqual(server.usage_outlook_detail(old, self.NOW), ("tight", 95, "old"))
        self.assertEqual(server.usage_outlook(old, self.NOW), ("tight", 95))  # its callers' two, unchanged
        self.assertEqual(server.claude_pace({"windows": old}, self.NOW),
                         ("tight", "at 95% of its week or more (an old reading)"))
        early = [(week, 75, self.NOW + week - 3600, self.NOW)]
        self.assertEqual(server.claude_pace({"windows": early}, self.NOW),
                         ("busy", "at 75% of its week or more (too early in the week for a pace)"))
        paced = [(week, 30, self.NOW + week / 2, self.NOW)]
        self.assertEqual(server.claude_pace({"windows": paced}, self.NOW), ("ok", "on pace for about 60% of its week"))
        self.assertEqual(server.usage_outlook_detail([], self.NOW), ("unknown", None, None))
        got = server.suggest_consultant("review", {"codex": self.codex(used=75, days_left=6.9)}, self.NOW)
        self.assertIn("Codex at 75% of its week or more (too early in the week for a pace)", got["why"])
        self.assertFalse(any("on pace" in w for w in got["why"]), got["why"])

    def test_one_judgment_per_window(self):
        """0.28.1: routing, ConsultantBudget, the hook and the status screen take one judgment of each
        window: an old reading's share used is the least the window reaches, coloured and routed by it."""
        week, reset = 7 * self.DAY, self.NOW + 3 * self.DAY
        old = self.NOW - 2 * server.CLAUDE_USAGE_STALE
        for used, level, colour in ((95, "tight", "33"), (80, "busy", "32"), (40, "fine", "32"), (100, "used up", "31")):
            judged = server.window_level(used, reset, week, self.NOW, old)
            screen = server.window_state(used, reset, week, self.NOW, old)
            self.assertEqual((judged["level"], judged["basis"]), (level, "old"))
            self.assertEqual((screen["level"], screen["colour"]), (level, colour))
            routed = server.usage_outlook_detail([(week, used, reset, old)], self.NOW)[0]
            self.assertEqual(routed, {"used up": "blocked", "fine": "ok"}.get(level, level))
        self.assertIn("at least 95% by the reset", server.window_state(95, reset, week, self.NOW, old)["long"])
        self.assertIsNone(server.window_level(50, self.NOW - 1, week, self.NOW))  # reset: counts nowhere
        five = 5 * 3600  # a 5-hour window on pace past 90% is named on Claude Code's line, as the screen's amber
        hot = [(week, 20, self.NOW + 4 * self.DAY, self.NOW), (five, 76, self.NOW + 3600, self.NOW)]
        self.assertIn("its 5-hour window on pace for about 95%", server.claude_pace({"windows": hot}, self.NOW)[1])
        self.assertEqual(server.window_state(76, self.NOW + 3600, five, self.NOW)["colour"], "33")

    def test_revision_picks_keep_off_claude_models(self):
        """0.28.1: with revision=true any kind keeps off Claude models, in ConsultantBudget as at the
        send; without it, a draft whose pick is Claude says how to get the other."""
        agy = {"antigravity": self.agy()}
        self.assertEqual(self.pick("draft", **agy)[1], "claude-opus-5-5")
        got = server.suggest_consultant("draft", agy, self.NOW, None, True)
        self.assertTrue(got["model"].startswith("gemini-"), got)
        lines = "\n".join(server.suggestion_lines("draft", agy, self.NOW))
        self.assertIn("ConsultantBudget with revision=true", lines)
        self.assertNotIn("ConsultantBudget with revision=true", "\n".join(server.suggestion_lines("draft", agy, self.NOW, None, True)))

    def test_quota_groups_come_from_agys_own_lists(self):
        """0.28.1: a model's Antigravity quota group is the one whose /usage list names its `agy models`
        display name, a level suffix taken off; a model no group (or two) lists has its usage not known;
        only when no group lists models, nouez's own guess."""
        live = {"groups": [
            {"name": "Gemini Models", "description": "Models within this group: Gemini 4 Neon, Gemini 4 Argon, Orchestrator (Neon)."},
            {"name": "Claude and GPT models", "description": "Models within this group: Claude Opus 5.5, GPT-OSS 120B"}]}
        names = {"gemini-4-neon-high": "Gemini 4 Neon (High)", "gemini-4-argon-low": "Gemini 4 Argon (Low)",
                 "gemini-pro-orchestrator-neon": "Orchestrator (Neon)", "claude-opus-5-5-high": "Claude Opus 5.5 (High)",
                 "gpt-oss-120b": "GPT-OSS 120B", "gemini-9-new": "Gemini 9 New"}
        members = server.agy_members(live)
        group = {m: server.agy_group_of(m, members, names) for m in
                 ("gemini-4-neon", "gemini-4-argon", "gemini-pro-orchestrator-neon", "claude-opus-5-5", "gpt-oss-120b", "gemini-9-new")}
        self.assertEqual(group, {"gemini-4-neon": "Gemini Models", "gemini-4-argon": "Gemini Models",
                                 "gemini-pro-orchestrator-neon": "Gemini Models", "claude-opus-5-5": "Claude and GPT models",
                                 "gpt-oss-120b": "Claude and GPT models", "gemini-9-new": None})
        self.assertEqual(server.quota_title("antigravity", "gemini-9-new", {"members": members, "names": names}),
                         "Antigravity (its quota group not known)")
        self.assertIsNone(server.provider_windows("antigravity", "gemini-9-new",
                                                  {"groups": {"Gemini Models": []}, "members": members, "names": names}))
        twice = {**members, "Other": {"Gemini 4 Neon"}}
        self.assertIsNone(server.agy_group_of("gemini-4-neon", twice, names))
        self.assertEqual(server.agy_group_of("claude-opus-5-5"), "Claude and GPT models")  # no lists: the guess

    def test_a_refusal_names_only_room_it_knows(self):
        """Codex 0.28.1 review: only a limit Codex reported refuses (a share at 100% alone is a note); a
        refusal says when no other consultant is set up, or Antigravity's usage isn't read yet, and never
        waits for a reading."""
        week = self.codex(used=100, days_left=2)
        refusal, note = server.send_check("review", "codex", "gpt-6.2-astra", {"codex": {**week, "credits": False}},
                                          self.NOW)
        self.assertIsNone(refusal)
        self.assertIn("this turn may fail unless its credits cover it", note)
        limited = {"codex": {**week, "limit": "weekly", "credits": False}}
        with mock.patch.object(server, "agy_command", lambda env=None: None):
            refusal, _ = server.send_check("review", "codex", "gpt-6.2-astra", limited, self.NOW)
        self.assertIn("No consultant other than Codex is set up, so none has room", refusal)
        with mock.patch.object(server, "agy_command", lambda env=None: "agy"), \
                mock.patch.object(server, "peek_agy_usage", return_value=None), \
                mock.patch.object(server, "read_agy_usage", side_effect=AssertionError("the send waited")):
            refusal, _ = server.send_check("review", "codex", "gpt-6.2-astra", limited, self.NOW)
        self.assertIn("Antigravity's usage isn't read yet: call ConsultantBudget", refusal)

    def test_known_room_comes_before_a_group_not_known(self):
        """Codex 0.28.1 review: a pick whose Antigravity quota group agy's lists don't name gives way to
        one with known room; the subject note's level drops while Gemini's week is tight, as a pick's."""
        st = self.agy()
        st = {**st, "members": {"Gemini Models": {"Gemini 4 Neon"}, "Claude and GPT models": {"GPT-OSS 120B"}},
              "names": {i: ("Gemini 4 Neon" if i.startswith("gemini") else "Claude Opus 5.5")
                        + f" ({i.rsplit('-', 1)[1].title()})" for i in st["models"]}}
        got = server.suggest_consultant("draft", {"antigravity": st}, self.NOW)
        self.assertTrue(got["model"].startswith("gemini-4-neon"), got)
        self.assertIn("Antigravity (its quota group not known): usage not known", got["why"])
        lines = "\n".join(server.suggestion_lines("review", {"codex": self.codex(),
                                                              "antigravity": self.agy(gemini=55, days_left=3)}, self.NOW))
        self.assertIn('effort "high", one level down while its week is tight.', lines)

    def test_antigravity_is_never_refused_for_its_quota(self):
        """0.28.1: agy never says whether AI credits can take a turn past a used-up group, so a send
        there only gets a note, with a group of room named; a forecast is a note too."""
        st = self.agy(claude=100)
        refusal, note = server.send_check("research", "antigravity", "claude-opus-5-5", {"antigravity": st}, self.NOW)
        self.assertIsNone(refusal)
        self.assertIn("this turn may fail unless your plan has AI credits", note)
        self.assertIn("For later turns, Antigravity's Gemini Models has room", note)
        self.assertNotIn("send again", note)
        _, note = server.send_check("research", "antigravity", "claude-opus-5-5", {"antigravity": st}, self.NOW,
                                    blind=True)
        self.assertNotIn("blind second opinion", note)  # it went ahead: nothing to tell the user
        cx = {"codex": {**self.codex(used=100, days_left=2), "limit": "weekly", "credits": False}}
        refusal, _ = server.send_check("review", "codex", "gpt-6.2-astra", cx, self.NOW, blind=True)
        self.assertIn("A blind second opinion here has to come from Codex", refusal)

    def test_the_route_at_send_stays_with_the_consultants_provider(self):
        """0.26.0: a send naming no model or effort takes the kind's suggestion, from that provider's
        usage alone; none for kind other, or when its usage can't be read."""
        def fill(key, value):
            return lambda now, *a, state=None, **k: state.update(value) or ["lines"]
        with mock.patch.object(server, "claude_budget", lambda now, path=None, state=None: []), \
                mock.patch.object(server, "codex_budget", lambda client, now, state: state.update(self.codex())), \
                mock.patch.object(server, "agy_budget", fill("antigravity", self.agy())):
            got = server.send_route("research", "codex", object(), self.NOW)
            self.assertEqual((got["provider"], got["model"], got["effort"]), ("codex", "gpt-6.2-astra", "xhigh"))
            got = server.send_route("plan-critique", "antigravity", None, self.NOW)
            self.assertEqual((got["provider"], got["model"], got["effort"]), ("antigravity", "gemini-4-neon", "xhigh"))
            self.assertIsNone(server.send_route("other", "codex", object(), self.NOW))
            # Codex finding 6: after "ask Gemini" (ConsultantBudget with provider antigravity), the
            # send's own pick keeps to Gemini, as the suggestion did, until a message of that kind
            # reaches it (0.28), the half hour is up unused, or the user names another provider; a
            # lookup that names none (round 2) keeps it.
            self.addCleanup(server._named.clear)
            got = server.send_route("fact-check", "antigravity", None, self.NOW)
            self.assertEqual(got["model"], "claude-opus-5-5")
            with mock.patch.object(server, "codex_installed", lambda: False), \
                    mock.patch.object(server, "agy_command", lambda env=None: None):
                server.consultant_budget({"kind": "fact-check", "provider": "antigravity"})
                got = server.send_route("fact-check", "antigravity", None, self.NOW)
                self.assertEqual(got["model"], "gemini-4-neon")
                self.assertEqual(server.send_route("fact-check", "codex", object(), self.NOW)["provider"], "codex")
                server._named["fact-check"] = ("antigravity", time.monotonic() - 1)  # the half hour is up
                self.assertEqual(server.send_route("fact-check", "antigravity", None, self.NOW)["model"],
                                 "claude-opus-5-5")
                server.consultant_budget({"kind": "fact-check", "provider": "antigravity"})
                server.consultant_budget({"kind": "fact-check"})
                self.assertEqual(server.send_route("fact-check", "antigravity", None, self.NOW)["model"],
                                 "gemini-4-neon")
                server.consultant_budget({"kind": "fact-check", "provider": "codex"})
                self.assertFalse(server.named_provider("fact-check", "antigravity"))
                self.assertEqual(server.send_route("fact-check", "antigravity", None, self.NOW)["model"],
                                 "claude-opus-5-5")
                # 0.28: one message. Reading it doesn't spend it; a delivery of that kind to that
                # provider does, and a delivery elsewhere or of another kind doesn't.
                server.consultant_budget({"kind": "fact-check", "provider": "antigravity"})
                server.send_route("fact-check", "antigravity", None, self.NOW)
                server.use_named("fact-check", "codex")
                server.use_named("research", "antigravity")
                self.assertTrue(server.named_provider("fact-check", "antigravity"))
                server.use_named("fact-check", "antigravity")
                self.assertFalse(server.named_provider("fact-check", "antigravity"))
        with mock.patch.object(server, "claude_budget", lambda now, path=None, state=None: []), \
                mock.patch.object(server, "codex_budget", side_effect=server.BridgeError("daemon down")):
            self.assertIsNone(server.send_route("review", "codex", object(), self.NOW))
        with mock.patch.object(server, "claude_budget", lambda now, path=None, state=None: []), \
                mock.patch.object(server, "codex_budget",
                                  lambda client, now, state: state.update(self.codex(used=100, days_left=2))):
            self.assertIsNone(server.send_route("review", "codex", object(), self.NOW))  # no room: as it is

    def test_both_installed_with_room(self):
        both = {"codex": self.codex(), "antigravity": self.agy()}
        self.assertEqual(self.pick("review", **both), ("codex", "gpt-6.2-astra", "high"))
        self.assertEqual(self.pick("quick-check", **both), ("codex", "gpt-6.2-sol", "low"))
        self.assertEqual(self.pick("re-check", **both), ("codex", "gpt-6.2-sol", "medium"))
        self.assertEqual(self.pick("research", **both), ("antigravity", "claude-opus-5-5", "high"))  # 0.28
        self.assertEqual(self.pick("plan-critique", **both), ("antigravity", "gemini-4-neon", "xhigh"))
        self.assertEqual(self.pick("fact-check", **both), ("codex", "gpt-6.2-astra", "high"))
        self.assertEqual(self.pick("other", **both), ("codex", "gpt-6.2-sol", "low"))

    def test_one_provider(self):
        self.assertEqual(self.pick("plan-critique", codex=self.codex()), ("codex", "gpt-6.2-astra", "high"))
        agy = {"antigravity": self.agy()}
        self.assertEqual(self.pick("review", **agy), ("antigravity", "gemini-4-neon", "high"))
        self.assertEqual(self.pick("fact-check", **agy), ("antigravity", "claude-opus-5-5", "high"))
        self.assertEqual(self.pick("other", **agy), ("antigravity", "gemini-4-neon", "high"))
        # "ask Gemini": Antigravity's Gemini models only, so a fact check doesn't go to Claude Opus
        got = server.suggest_consultant("fact-check", agy, self.NOW, only="antigravity")
        self.assertEqual((got["provider"], got["model"]), ("antigravity", "gemini-4-neon"))
        # ... nor through the default model, when agy lists no Gemini one
        opus = {"antigravity": self.agy(models=["claude-opus-5-5-high"])}
        got = server.suggest_consultant("fact-check", opus, self.NOW, only="antigravity")
        self.assertEqual(got, {"none": "Antigravity lists no Gemini model"})
        # Neon listed at one level only: that level, so StartConsultant doesn't ask for high
        self.assertEqual(self.pick("other", antigravity=self.agy(models=["gemini-4-neon-low"])),
                         ("antigravity", "gemini-4-neon", "low"))
        self.assertEqual(self.pick("review"), "no consultant CLI is installed")
        lines = server.suggestion_lines(None, {"codex": None, "antigravity": None}, self.NOW)
        self.assertEqual(len(lines), 1)
        self.assertIn("need the Codex or Antigravity CLI", lines[0])
        named = server.suggestion_lines("review", {"claude": {}}, self.NOW, "antigravity")
        self.assertIn("Antigravity isn't installed", named[0])

    def test_used_up_or_running_out(self):
        # used up: the other provider; both used up: none, with why
        both = {"codex": self.codex(used=100), "antigravity": self.agy()}
        self.assertEqual(self.pick("review", **both), ("antigravity", "gemini-4-neon", "high"))
        none = self.pick("review", codex=self.codex(used=100), antigravity=self.agy(gemini=100))
        self.assertIn("Codex gpt-6.2-astra: its weekly window is used up", none)
        self.assertIn("Antigravity gemini-4-neon", none)
        # 2 of 7 days gone and 50% used: runs out before the reset
        self.assertEqual(self.pick("review", codex=self.codex(used=50))[:5], "Codex")
        # the Gemini group used up, the Claude and GPT one free: research moves there
        self.assertEqual(self.pick("research", antigravity=self.agy(gemini=100)),
                         ("antigravity", "claude-opus-5-5", "high"))
        text = server.suggestion_lines("review", {"codex": self.codex(used=100), "antigravity": None,
                                                  "claude": {}}, self.NOW)
        self.assertIn("none has room", text[2])
        self.assertIn("Skip it, and tell the user", text[2])

    def test_tight_and_unused_weeks(self):
        # Codex tight (6 of 7 days gone, 80% used: about 93%), Gemini fine: the review moves
        tight = self.codex(used=80, days_left=1)
        got = server.suggest_consultant("review", {"codex": tight, "antigravity": self.agy()}, self.NOW)
        self.assertEqual((got["provider"], got["effort"]), ("antigravity", "high"))
        self.assertIn("Codex is on pace for about 93% of its week", got["why"])
        # no other provider: the same, one level down
        got = server.suggest_consultant("review", {"codex": tight}, self.NOW)
        self.assertEqual((got["model"], got["effort"]), ("gpt-6.2-astra", "medium"))
        self.assertIn("one level down while its week is tight", got["why"])
        # 0.26.1: a model that doesn't list the level below keeps its effort
        tight["models"] = {m: (("low", "high", "xhigh"), "low", i == 0)
                           for i, m in enumerate(["gpt-6.2-sol", "gpt-6.2-astra"])}
        got = server.suggest_consultant("review", {"codex": tight}, self.NOW)
        self.assertEqual((got["model"], got["effort"]), ("gpt-6.2-astra", "high"))
        self.assertNotIn("one level down while its week is tight", got["why"])
        # Gemini past 70%, Codex's week ending within two days half unused: the critique goes to Codex
        busy = self.agy(gemini=60, days_left=2)  # 5 of 7 days gone: about 84%
        spare = self.codex(used=30, days_left=1)  # about 35% at a reset a day away
        got = server.suggest_consultant("plan-critique", {"codex": spare, "antigravity": busy}, self.NOW)
        self.assertEqual((got["provider"], got["model"]), ("codex", "gpt-6.2-astra"))
        self.assertTrue(any("would go unused" in w for w in got["why"]), got["why"])
        # but a fact check stays with the first choice
        got = server.suggest_consultant("fact-check", {"codex": self.codex(used=60, days_left=2),
                                                       "antigravity": self.agy(gemini=10, claude=10, days_left=1)},
                                        self.NOW)
        self.assertEqual(got["provider"], "codex")

    def test_research_and_drafts_go_to_antigravitys_claude_models(self):
        """0.28 (#26): research and drafts run on Antigravity's Claude and GPT quota whenever it has
        room, sparing Claude Code's and Codex's; research names Codex for a page's text, since
        Antigravity can't open a page. A tight Claude and GPT week hands them on. Reviews never go there."""
        codex, agy = self.codex(), self.agy()
        both = {"codex": codex, "antigravity": agy, "claude": {}}
        self.assertEqual(self.pick("research", **both), ("antigravity", "claude-opus-5-5", "high"))
        self.assertEqual(self.pick("draft", **both), ("antigravity", "claude-opus-5-5", "high"))
        self.assertEqual(self.pick("research", codex=codex), ("codex", "gpt-6.2-astra", "xhigh"))
        self.assertEqual(self.pick("draft", codex=codex), ("codex", "gpt-6.2-astra", "high"))
        tight = self.agy(claude=100)  # the Claude and GPT week used up
        self.assertEqual(self.pick("draft", codex=codex, antigravity=tight), ("antigravity", "gemini-4-neon", "high"))
        self.assertEqual(self.pick("research", codex=codex, antigravity=tight), ("codex", "gpt-6.2-astra", "xhigh"))
        got = server.suggest_consultant("draft", {"antigravity": agy}, self.NOW, only="antigravity")
        self.assertEqual(got["model"], "gemini-4-neon")  # "ask Gemini": never a Claude model
        lines = "\n".join(server.suggestion_lines("research", both, self.NOW))
        self.assertIn("can't open a page", lines)
        self.assertIn('goes to Codex: provider "codex", model "gpt-6.2-astra", effort "xhigh"', lines)
        self.assertIn("Gemini 4 Neon scores best", lines)
        self.assertNotIn("goes to Codex", "\n".join(server.suggestion_lines("research", {"antigravity": agy,
                                                                                            "claude": {}}, self.NOW)))
        draft = "\n".join(server.suggestion_lines("draft", both, self.NOW))
        self.assertIn("unified diff", draft)
        self.assertIn("draft", server.CONSULT_KINDS)
        for kind in ("review", "re-check", "bug-hunt", "plan-critique"):
            self.assertNotEqual(self.pick(kind, **both)[1], "claude-opus-5-5")
        self.assertIn("kind draft", server.HAND_OUT["busy"])
        self.assertEqual(server.behind_schedule([(7 * self.DAY, 10, self.NOW + 2 * self.DAY)], self.NOW),
                         100 * 5 / 7 - 10)
        self.assertIsNone(server.behind_schedule([(5 * 3600, 10, self.NOW + 3600)], self.NOW))

    def test_usage_that_would_go_unused_goes_first(self):
        """0.25.0: a week under 60% at a reset within three days takes research and quick checks
        even when the first choice has room; Antigravity's two quota groups count apart."""
        codex = self.codex()  # about 35% at a reset five days away: room, nothing to spend
        sonnet = [f"gemini-4-neon-{lv}" for lv in ("low", "high", "xhigh")] + ["claude-opus-5-5-high",
                                                                                "claude-sonnet-5-5-low"]
        # Gemini at 50% with two days left (about 70%), the Claude and GPT group idle
        agy = self.agy(gemini=50, claude=0, days_left=2, models=sonnet)
        got = server.suggest_consultant("research", {"codex": codex, "antigravity": agy}, self.NOW)
        self.assertEqual((got["provider"], got["model"], got["effort"]), ("antigravity", "claude-opus-5-5", "high"))
        self.assertIn("Antigravity's Claude and GPT models resets within 3 days at about 0% of its week, "
                      "so the rest would go unused", got["why"])
        self.assertTrue(any("switches to this model" in n for n in got["notes"]), got["notes"])
        self.assertEqual(self.pick("quick-check", codex=codex, antigravity=agy),
                         ("antigravity", "claude-sonnet-5-5", "low"))
        # never reviews, bug hunts, plan critiques or fact checks: they keep their first choice
        for kind, first in (("review", "codex"), ("bug-hunt", "codex"), ("re-check", "codex"),
                            ("fact-check", "codex"), ("plan-critique", "antigravity")):
            got = server.suggest_consultant(kind, {"codex": codex, "antigravity": agy}, self.NOW)
            self.assertEqual(got["provider"], first, kind)
            self.assertNotEqual(got["model"], "claude-opus-5-5", kind)
        # four days to the reset: not unused yet, but 0.26.0 sends interchangeable work to the
        # subscription furthest behind an even pace: the idle group 43 points behind, Codex 19
        later = self.agy(gemini=50, claude=0, days_left=4, models=sonnet)
        got = server.suggest_consultant("quick-check", {"codex": codex, "antigravity": later}, self.NOW)
        self.assertEqual((got["provider"], got["model"]), ("antigravity", "claude-sonnet-5-5"))
        self.assertIn("Antigravity's Claude and GPT models is 43 points behind an even pace through its week",
                      got["why"])
        # less than 15 points further behind than the first choice: it stays
        near = self.agy(gemini=50, claude=25, days_left=4, models=sonnet)  # 18 behind, Codex 19
        self.assertEqual(self.pick("quick-check", codex=codex, antigravity=near), ("codex", "gpt-6.2-sol", "low"))
        for kind in ("review", "bug-hunt", "plan-critique", "fact-check"):  # quality first: never moved
            self.assertNotEqual(self.pick(kind, codex=codex, antigravity=later)[1], "claude-opus-5-5", kind)
        # both would go unused: the one that resets first
        soon = self.codex(used=10, days_left=1)
        self.assertEqual(self.pick("research", codex=soon, antigravity=agy), ("codex", "gpt-6.2-astra", "xhigh"))
        # Gemini tight, the other group calm: Antigravity's quick check moves to it, not one level down
        tight = self.agy(gemini=80, claude=0, days_left=1, models=sonnet)
        got = server.suggest_consultant("quick-check", {"antigravity": tight}, self.NOW)
        self.assertEqual((got["model"], got["effort"]), ("claude-sonnet-5-5", "low"))
        self.assertIn("Antigravity's Gemini Models is on pace for about 93% of its week", got["why"])
        # "ask Gemini" never moves to the Claude group
        got = server.suggest_consultant("research", {"antigravity": agy}, self.NOW, only="antigravity")
        self.assertEqual(got["model"], "gemini-4-neon")
        # a tie in reset time keeps the first choice
        both_spare = {"codex": self.codex(used=10, days_left=2), "antigravity": self.agy(gemini=10, days_left=2)}
        self.assertEqual(self.pick("quick-check", **both_spare), ("codex", "gpt-6.2-sol", "low"))
        # unknown usage is said as such, not as room
        unknown = {"codex": {"windows": [], "models": None}, "antigravity": agy}
        got = server.suggest_consultant("quick-check", unknown, self.NOW)
        self.assertEqual(got["model"], "claude-sonnet-5-5")
        self.assertIn("Codex: usage not known", got["why"])
        # work that checks Claude's own never goes to a Claude model, not even through the default
        # model of an Antigravity that lists only Opus, with Codex tight or absent
        opus_only = self.agy(claude=0, days_left=2, models=["claude-opus-5-5-high"])
        for kind in server.INDEPENDENT_KINDS:
            for st in ({"codex": self.codex(used=80, days_left=1), "antigravity": opus_only},
                       {"antigravity": opus_only}):
                got = server.suggest_consultant(kind, st, self.NOW)
                self.assertNotEqual(got.get("model"), "claude-opus-5-5", (kind, st.keys()))
        self.assertIn("shares the author's blind spots", self.pick("review", antigravity=opus_only))

    def test_models_not_listed(self):
        # a newer version of the family is used; a missing family falls back to the default model
        newer = self.codex(models=["gpt-6.3-sol", "gpt-6.3-astra", "gpt-6.10-astra"])
        self.assertEqual(self.pick("review", codex=newer), ("codex", "gpt-6.10-astra", "high"))
        got = server.suggest_consultant("review", {"codex": self.codex(models=["other-1"])}, self.NOW)
        self.assertEqual((got["model"], got["effort"]), ("other-1", "low"))
        self.assertIn("gpt-6.2-astra isn't listed, so the default model", got["notes"])
        # an effort the model doesn't list: the closest listed one below it, always named, since a
        # reused consultant would otherwise keep a level the new model may not have
        st = self.codex()
        st["models"]["gpt-6.2-astra"] = (["low", "medium"], "low", False)
        got = server.suggest_consultant("review", {"codex": st}, self.NOW)
        self.assertEqual(got["effort"], "medium")
        self.assertIn("gpt-6.2-astra has no high level, so medium", got["notes"])
        self.assertEqual(server.listed_level("low", ["high", "xhigh"]), "high")
        self.assertIsNone(server.listed_level("high", []))
        # Antigravity without Neon: a listed Gemini model, not a default agy can't run
        got = server.suggest_consultant("other", {"antigravity": self.agy(models=["gemini-4-carbon-low"])}, self.NOW)
        self.assertEqual((got["model"], got["effort"]), ("gemini-4-carbon", "low"))
        # no model list at all: the pick as is; agy without opus: neon for the fact check
        self.assertEqual(self.pick("review", codex={"windows": [], "models": None}),
                         ("codex", "gpt-6.2-astra", "high"))
        self.assertEqual(self.pick("fact-check", antigravity=self.agy(models=["gemini-4-neon-high"])),
                         ("antigravity", "gemini-4-neon", "high"))
        self.assertEqual(server.newest_of_family("claude-opus-5-5", ["claude-opus-5-5", "claude-opus-6-0"]),
                         "claude-opus-6-0")
        self.assertIsNone(server.newest_of_family("plain", ["plain"]))

    def test_unknown_usage_and_claude(self):
        got = server.suggest_consultant("review", {"codex": {"windows": [], "models": None}}, self.NOW)
        self.assertIn("Codex: usage not known", got["why"])
        o = server.claude_outlook
        self.assertIn("isn't known", o({}, self.NOW))
        self.assertIn(server.HAND_OUT["busy"], o({"windows": [(7 * self.DAY, 60, self.NOW + 2 * self.DAY,
                                                               self.NOW)]}, self.NOW))  # about 84%
        self.assertIn("put off optional work", o({"windows": [(7 * self.DAY, 80, self.NOW + self.DAY, self.NOW)]},
                                                  self.NOW))
        # 0.26.0: under 70% bulky work still goes out
        self.assertEqual(o({"windows": [(7 * self.DAY, 12, self.NOW + 3 * self.DAY, self.NOW)]}, self.NOW),
                         f"Claude Code: on pace for about 21% of its week. {server.HAND_OUT['ok']} "
                         f"{server.HAND_OUT_LOCAL}")
        # Claude's window used up or running out: said, not a crash
        for used in (100, 90):
            line = o({"windows": [(5 * 3600, used, self.NOW + 4 * 3600, self.NOW)]}, self.NOW)
            self.assertIn(server.HAND_OUT["tight"], line)
            self.assertIn("window", line)
        # an old reading gives no pace, only the least the week will reach: never spare
        old = self.NOW - 3600
        self.assertEqual(server.usage_outlook([(7 * self.DAY, 30, self.NOW + self.DAY, old)], self.NOW),
                         ("ok", None))
        self.assertEqual(server.usage_outlook([(7 * self.DAY, 80, self.NOW + self.DAY, old)], self.NOW),
                         ("busy", 80))

    def test_lines_for_one_kind(self):
        state = {"codex": self.codex(), "antigravity": self.agy(), "claude": {}}
        lines = server.suggestion_lines("review", state, self.NOW)
        text = "\n".join(lines)
        self.assertIn('review: StartConsultant provider "codex", model "gpt-6.2-astra"; SendConsultantMessage '
                      'model "gpt-6.2-astra", effort "high", kind "review".', text)
        self.assertIn("nouez counts the rounds", text)
        self.assertIn('blind', text)
        self.assertIn('second_opinion_of', text)
        self.assertIn('The other provider now: provider "antigravity", model "gemini-4-neon", effort "high".', text)
        self.assertIn('Gemini 4 Neon scores best (Artificial Analysis by subject): provider "antigravity", '
                      'model "gemini-4-neon", effort "xhigh".', text)
        # 0.26.1: each kind's own note reaches Claude with its suggestion, in its own words.
        self.assertIn("Ask for every finding in the first round", text)
        # The advice itself, written here and not read from CONSULT_NOTES, so a note emptied or
        # dropped there fails.
        for kind, said in (("review", "Ask for every finding in the first round"),
                           ("re-check", "send the review's model and effort again"),
                           ("bug-hunt", "draft the fix as a unified diff"),
                           ("review", "Ask it to weigh each finding itself before giving it"),
                           ("review", "whether a user in a normal setup would meet it"),
                           ("review", "its verdict is CHANGES only for them"),
                           ("re-check", "only one a user in a normal setup would meet"),
                           ("bug-hunt", "the scenario where a user meets it, and whether one in a normal setup"),
                           ("plan-critique", "giving only those a user in a normal setup would meet"),
                           ("bug-hunt", "git apply"),
                           ("plan-critique", "whether any premise, assumption or framing is wrong"),
                           ("research", "Ask for a short answer with its sources"),
                           ("fact-check", "Ask for its sources, and check the ones you will rely on")):
            with self.subTest(kind=kind, said=said):
                self.assertIn(said, "\n".join(server.suggestion_lines(kind, state, self.NOW)))
        # an Antigravity suggestion names the model and level for StartConsultant too
        agy = server.suggestion_lines("plan-critique", state, self.NOW)
        self.assertIn('StartConsultant provider "antigravity", model "gemini-4-neon", effort "xhigh"; ', "\n".join(agy))
        # Gemini used up, Carbon only listed: no Neon note and no blind Antigravity review
        state["antigravity"] = self.agy(gemini=100, models=["gemini-4-carbon-low"])
        text = "\n".join(server.suggestion_lines("research", state, self.NOW))
        self.assertNotIn("Gemini 4 Neon scores best", text)
        text = "\n".join(server.suggestion_lines("review", state, self.NOW))
        self.assertNotIn("The other provider now", text)
        every = server.suggestion_lines(None, state, self.NOW)
        self.assertEqual(sum(line.startswith("  ") and '; SendConsultantMessage' in line for line in every),
                         len(server.CONSULT_KINDS) - 1)
        self.assertNotIn("blind", "\n".join(every))

    def test_budget_takes_kind_and_provider(self):
        with mock.patch.object(server, "codex_installed", lambda: False), \
             mock.patch.object(server, "claude_budget", return_value=["Claude Code: x"]), \
             mock.patch.object(server, "aa_scores", return_value=({}, "no key")), \
             mock.patch.object(server, "agy_budget", return_value=[]):
            self.assertIn("Nothing to suggest", server.consultant_budget({"kind": "review"}))
            with self.assertRaises(server.BridgeError):
                server.consultant_budget({"kind": "chat"})
            with self.assertRaises(server.BridgeError):
                server.consultant_budget({"provider": "other"})
        schema = next(t for t in server.TOOLS if t["name"] == "ConsultantBudget")["inputSchema"]["properties"]
        self.assertEqual(schema["kind"]["enum"], list(server.CONSULT_KINDS))
        self.assertEqual(schema["provider"]["enum"], list(server.PROVIDERS))


class AgyTest(unittest.TestCase):
    """0.15.0: consultants on the Antigravity CLI, with a fake agy process."""

    MODELS = ["gemini-4-neon-high", "gemini-4-neon-low", "gemini-4-neon-xhigh", "gemini-pro-orchestrator-neon",
              "gemini-3.8-flash-low"]

    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.dir, True)
        self.work = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.work, True)
        for name, value in (("nouez_cache_dir", lambda: self.dir), ("agy_root", lambda: os.path.join(self.dir, "agy")),
                            ("agy_command", lambda env=None: "agy"), ("agy_models", lambda env=None, now=None: self.MODELS),
                            ("agy_spawn", self.spawn), ("POLL_SECONDS", 0.01), ("CodexClient", FakeDaemon([])), ("read_agy_usage", lambda: None),
                            ("revision", lambda cwd, take=True, inline_limit=None, base=None: ("[Revision: commit abc. Name this revision in your answer.]\n",
                                                                       b"--- a/x\n+++ b/x\n" if take else b"", "d1g3st" if take else ""))):
            patcher = mock.patch.object(server, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        env = mock.patch.dict(os.environ, {"NOUEZ_NO_USAGE_LOG": ""})
        env.start()
        self.addCleanup(env.stop)
        self.log = os.path.join(self.dir, server.USAGE_LOG_FILE)
        self.runs = []      # (argv, cwd, stdin text) per spawned turn
        self.replies = []   # what each fake run writes: a list of events, or None to keep running
        self.running = False

    def spawn(self, argv, cwd, stdin_path, out_path, err_path):
        with open(stdin_path, encoding="utf-8") as f:
            self.runs.append((argv, cwd, f.read()))
        events = self.replies.pop(0) if self.replies else None
        with open(out_path, "w", encoding="utf-8") as f:
            f.write(agy_lines(AGY_INIT, *(events or [])))
        open(err_path, "w").close()
        self.running = events is None
        return mock.Mock(pid=4242)

    def alive(self, meta):
        return self.running

    def start(self, **args):
        out = server.start_consultant({"cwd": self.work, "provider": "antigravity", **args})
        return out, out.split()[1].rstrip(",.")

    def events(self):
        with open(self.log, encoding="utf-8") as f:
            return [json.loads(line) for line in f]

    def test_model_ids(self):
        known = self.MODELS
        self.assertEqual(server.agy_model_id("gemini-4-neon-high", known=known), "gemini-4-neon-high")
        self.assertEqual(server.agy_model_id("gemini-4-neon-high", effort="low", known=known), "gemini-4-neon-low")
        self.assertEqual(server.agy_model_id("gemini-4-neon-low", "gemini-4-neon", known=known), "gemini-4-neon-low")
        self.assertEqual(server.agy_model_id("gemini-4-neon-high", "gemini-3.8-flash", "low", known), "gemini-3.8-flash-low")
        self.assertEqual(server.agy_model_id("gemini-4-neon-high", "gemini-pro-orchestrator-neon", known=known),
                         "gemini-pro-orchestrator-neon")
        self.assertEqual(server.agy_model_id("gemini-4-neon-high", "gemini-4-neon-xhigh"), "gemini-4-neon-xhigh")
        with self.assertRaisesRegex(server.BridgeError, "has no model 'gemini-3.8-flash-high'. It lists"):
            server.agy_model_id("gemini-4-neon-high", "gemini-3.8-flash", known=known)
        with self.assertRaisesRegex(server.BridgeError, "`effort` must be one of"):
            server.agy_model_id("gemini-4-neon-high", effort="ultra")
        with self.assertRaisesRegex(server.BridgeError, "`model` must be an Antigravity model id"):
            server.agy_model_id("gemini-4-neon-high", "Gemini 4; rm -rf")
        self.assertEqual(server.agy_model_families(known),
                         "gemini-4-neon (low, high, xhigh), gemini-pro-orchestrator-neon, gemini-3.8-flash (low)")

    def test_start_reuse_and_provider(self):
        with self.assertRaisesRegex(server.BridgeError, "`provider` must be one of codex, antigravity"):
            server.start_consultant({"cwd": self.work, "provider": "gemini"})
        out, name = self.start(effort="low", title="t", instructions="Be brief.")
        self.assertTrue(name.startswith("agy-"))
        self.assertIn("model: gemini-4-neon-low (Antigravity)", out)
        self.assertIn("read-only", out)
        again, same = self.start(model="gemini-4-neon")
        self.assertEqual(same, name)
        self.assertIn("nothing new was started", again)
        self.assertIn("Ignored model", again)
        _, other = self.start(new=True)
        self.assertNotEqual(other, name)
        listed = server.list_consultants({"cwd": self.work})
        self.assertEqual(sum(line.startswith("- ") for line in listed.splitlines()), 2)
        self.assertIn(name, listed)
        self.assertEqual([e["provider"] for e in self.events() if e["event"] == "start"], ["antigravity"] * 2)
        with mock.patch.object(server, "agy_command", lambda env=None: None):
            with self.assertRaisesRegex(server.BridgeError, "Antigravity CLI .* can't be found"):
                server.start_consultant({"cwd": tempfile.gettempdir(), "provider": "antigravity", "new": True})
            with self.assertRaisesRegex(server.BridgeError, "Antigravity CLI .* can't be found"):
                server.start_consultant({"cwd": self.work, "provider": "antigravity"})  # not "Using ..."

    def test_without_codex(self):
        """0.18.0: with only agy installed, the tools work without naming a provider."""
        no_codex = mock.patch.object(server, "codex_installed", lambda: False)
        no_codex.start()
        self.addCleanup(no_codex.stop)
        listed = server.list_consultants({"cwd": self.work})
        self.assertIn("No consultants in", listed)
        self.assertIn("Codex isn't installed", listed)
        self.assertIn("Start an Antigravity consultant", listed)
        with self.assertRaisesRegex(server.BridgeError, "No consultant named 'nobody'.*none is running"):
            server.send_consultant_message({"kind": "other", "to": "nobody", "message": "hi"})
        with mock.patch.object(server, "agy_command", lambda env=None: None):
            with self.assertRaisesRegex(server.BridgeError, "No consultant named 'nobody'. Neither Codex nor Antigravity"):
                server.send_consultant_message({"kind": "other", "to": "nobody", "message": "hi"})
        out = server.start_consultant({"cwd": self.work, "model": "gpt-6.2-astra"})
        self.assertIn("Codex isn't installed, so this is an Antigravity consultant (model 'gpt-6.2-astra'", out)
        self.assertIn("model: gemini-4-neon-high (Antigravity)", out)
        name = out.split("Started ")[1].split()[0]
        again = server.start_consultant({"cwd": self.work})
        self.assertIn("Codex isn't installed, so this is an Antigravity consultant.", again)
        self.assertIn(f"Using {name}", again)
        with mock.patch.object(server, "agy_models", lambda env=None, now=None: None):  # agy models timed out
            unsure = server.start_consultant({"cwd": self.work, "model": "gpt-6.2-astra"})
        self.assertIn("'gpt-6.2-astra' can't be checked: `agy models` didn't answer, so its default is used", unsure)
        self.assertIn(f"Using {name}", unsure)
        self.assertIn(name, server.list_consultants({"cwd": self.work}))
        for tool in (server.send_consultant_message, server.get_consultant_history, server.stop_consultant):
            with self.assertRaisesRegex(server.BridgeError, f"No consultant named 'nobody'.*exist: {name}"):
                tool({"to": "nobody", "message": "hi", "kind": "other"})
        with self.assertRaisesRegex(server.BridgeError, "Codex isn't installed: .*pass provider antigravity"):
            server.start_consultant({"cwd": self.work, "provider": "codex"})
        with mock.patch.object(server, "agy_command", lambda env=None: None):
            with self.assertRaisesRegex(server.BridgeError, "neither Codex .* nor Antigravity .*session tools still work"):
                server.start_consultant({"cwd": self.work})
            elsewhere = tempfile.mkdtemp()
            self.addCleanup(shutil.rmtree, elsewhere, True)
            self.assertIn("consultations are off", server.list_consultants({"cwd": elsewhere}))

    def test_work_that_checks_claude_never_runs_on_a_claude_model(self):
        """0.26.0: an independent kind on a consultant left on a Claude model moves to Gemini; a Claude
        model passed for one, or a diff sent as kind other, is refused; and every send needs a kind."""
        self.MODELS = self.MODELS + ["claude-opus-5-5"]
        _, name = self.start(model="claude-opus-5-5")
        self.assertEqual(server.agy_resolve(name)["model"], "claude-opus-5-5")
        for args, why in (({"kind": "review", "model": "claude-opus-5-5"}, "a review goes to a model of another"),
                          ({"kind": "other", "revision": True}, "a message with revision=true goes .*model=gemini-4-neon"),
                          ({}, "`kind` is required")):
            with self.assertRaisesRegex(server.BridgeError, why):
                server.send_consultant_message({"to": name, "message": "x", "wait": 0, **args})
        self.assertEqual(self.runs, [])
        self.replies = [[agy_result("ok\n")]]
        out = server.send_consultant_message({"to": name, "message": "x", "wait": 5, "kind": "plan-critique"})
        argv = self.runs[0][0]
        self.assertEqual(argv[argv.index("--model") + 1], "gemini-4-neon-xhigh")
        self.assertIn(f"{name} was on claude-opus-5-5, a Claude model", out)
        self.assertEqual(server.agy_resolve(name)["model"], "gemini-4-neon-xhigh")

    def test_a_forecast_never_stops_the_move_off_a_claude_model(self):
        """Codex 0.28.1 review: a review on a consultant left on Opus moves to Gemini even when Gemini's
        week runs out at this rate, as the same send naming Gemini would go, with the usage note."""
        self.MODELS = self.MODELS + ["claude-opus-5-5"]
        _, name = self.start(model="claude-opus-5-5")
        now = time.time()
        hot = {"antigravity": {"groups": {"Gemini Models": [(7 * 86400, 95, now + 3 * 86400)],
                                          "Claude and GPT models": [(7 * 86400, 10, now + 3 * 86400)]},
                               "models": self.MODELS}}
        self.replies = [[agy_result("ok\n")]]
        with mock.patch.object(server, "send_route", return_value=None), \
                mock.patch.object(server, "send_usage", return_value=hot):
            out = server.send_consultant_message({"to": name, "message": "x", "wait": 5, "kind": "review"})
        argv = self.runs[0][0]
        self.assertTrue(argv[argv.index("--model") + 1].startswith("gemini-"), argv)
        self.assertIn("runs out before its reset at this rate", out)

    def test_a_send_without_model_or_effort_takes_nouezs_pick(self):
        """0.26.0: on Antigravity too, a send naming neither runs on the kind's suggestion."""
        self.MODELS = self.MODELS + ["claude-opus-5-5-high"]
        _, name = self.start()
        pick = {"provider": "antigravity", "model": "claude-opus-5-5", "effort": "high",
                "why": ["on Google's quota, not Claude Code's"], "notes": []}
        self.replies = [[agy_result("ok\n")]]
        with mock.patch.object(server, "send_route", return_value=pick) as route:
            out = server.send_consultant_message({"to": name, "message": "x", "wait": 5, "kind": "research"})
        route.assert_called_once_with("research", "antigravity", revision=False, usage={})
        argv = self.runs[0][0]
        self.assertEqual(argv[argv.index("--model") + 1], "claude-opus-5-5-high")
        self.assertIn("runs on claude-opus-5-5-high, nouez's pick for a research.", out)

    def test_nouezs_own_claude_pick_for_a_diff_moves_to_gemini(self):
        """Codex 0.28 review, finding 3: a draft of branch changes (revision=true) whose pick at send is
        Opus runs on Gemini, at Gemini's own level (round 2), not Opus's; only a Claude model the caller
        passed is refused."""
        self.MODELS = self.MODELS + ["claude-opus-5-5-low"]
        _, name = self.start()
        pick = {"provider": "antigravity", "model": "claude-opus-5-5", "effort": "low",
                "why": ["Claude's own family writes code best"], "notes": []}
        self.replies = [[agy_result("ok\n")]]
        with mock.patch.object(server, "send_route", return_value=pick):
            out = server.send_consultant_message({"to": name, "message": "x", "wait": 5, "kind": "draft",
                                                  "revision": True})
        argv = self.runs[0][0]
        self.assertEqual(argv[argv.index("--model") + 1], "gemini-4-neon-high")
        self.assertIn("runs on gemini-4-neon-high instead", out)
        with self.assertRaisesRegex(server.BridgeError, "goes to a model of another family"):
            server.send_consultant_message({"to": name, "message": "x", "wait": 0, "kind": "draft",
                                            "revision": True, "model": "claude-opus-5-5-low"})
        self.assertEqual(len(self.runs), 1)

    def test_a_named_gemini_never_runs_on_another_model(self):
        """Codex round 2, finding 5: after "ask Gemini", a send nouez can't move to a Gemini model
        (none has room) is refused rather than left on the consultant's Claude model."""
        self.MODELS = self.MODELS + ["claude-opus-5-5"]
        _, name = self.start(model="claude-opus-5-5")
        self.addCleanup(server._named.clear)
        server._named["research"] = ("antigravity", time.monotonic() + 60)
        with mock.patch.object(server, "send_route", return_value=None), \
                self.assertRaisesRegex(server.BridgeError, "The user named Gemini for this research"):
            server.send_consultant_message({"to": name, "message": "x", "wait": 0, "kind": "research"})
        self.assertEqual(self.runs, [])
        self.assertTrue(server.named_provider("research", "antigravity"))  # refused: still waiting for its one send
        self.replies = [[agy_result("ok\n")]]  # a model the user accepted, passed outright, goes ahead
        server.send_consultant_message({"to": name, "message": "x", "wait": 5, "kind": "research",
                                        "model": "claude-opus-5-5"})
        self.assertEqual(len(self.runs), 1)
        self.assertFalse(server.named_provider("research", "antigravity"))  # 0.28: that was its one message

    def test_the_diff_goes_in_by_default(self):
        """0.28 (#47): an Antigravity consultant runs no git, so revision=true puts the diff in the
        message unless attach_diff is false; true without revision, or a non-boolean, is refused."""
        _, name = self.start()
        self.replies = [[agy_result("ok\n")], [agy_result("ok\n")]]
        server.send_consultant_message({"to": name, "message": "x", "wait": 5, "kind": "review", "revision": True})
        self.assertIn("(sha256 d1g3st), as nouez took it:", json.loads(self.runs[0][2])["message"]["content"])
        server.send_consultant_message({"to": name, "message": "x", "wait": 5, "kind": "review", "revision": True,
                                        "attach_diff": False})
        self.assertNotIn("as nouez took it", json.loads(self.runs[1][2])["message"]["content"])
        for bad, why in ((True, "attach_diff requires revision=true"), ("yes", "must be true or false")):
            with self.assertRaisesRegex(server.BridgeError, why):
                server.send_consultant_message({"to": name, "message": "x", "wait": 0, "kind": "review",
                                                "attach_diff": bad})
        self.assertEqual(len(self.runs), 2)

    def test_send_reply_history_stop(self):
        _, name = self.start(instructions="Answer in French.")
        self.replies = [[{"event": "step_update", "step_update": {"text_delta": "pomme"}}, agy_result("pomme\n")]]
        out = server.send_consultant_message({"to": name, "message": "Which fruit?", "wait": 5, "kind": "quick-check",
                                              "owner_words": "fruit?", "revision": True, "attach_diff": True})
        self.assertIn(f"Reply from {name}:\n\npomme", out)
        argv, cwd, sent = self.runs[0]
        self.assertEqual(cwd, self.work)
        self.assertEqual(argv[-2:], ["-p", ""])
        self.assertEqual(json.loads(argv[argv.index("--settings") + 1]), server.AGY_READ_ONLY)
        # 0.26.1: the entries themselves, so dropping one from the constant can't pass unseen.
        self.assertLessEqual({"write_file(*)", "command(*)", "mcp(*)", "execute_url(*)"},
                             set(json.loads(argv[argv.index("--settings") + 1])["permissions"]["deny"]))
        self.assertIn("--disable-slash-commands", argv)
        self.assertEqual(argv[argv.index("--model") + 1], "gemini-4-neon-high")
        self.assertEqual(argv[argv.index("--print-timeout") + 1], "30m")
        self.assertNotIn("--conversation", argv)
        content = json.loads(sent)["message"]["content"]
        self.assertEqual(json.loads(sent)["event"], "user")
        self.assertTrue(content.startswith(server.AGY_PREAMBLE))
        # 0.26.1: the first brief's own words, so a rule dropped from the constant can't pass unseen
        for said in ("You are a read-only consultant", "writing or editing files, running commands and MCP "
                     "tools are denied", "Don't schedule tasks or start background work"):
            self.assertIn(said, content)
        self.assertIn("<<<\nAnswer in French.\n>>>", content)
        self.assertIn("The diff named in the revision line below (sha256 d1g3st), as nouez took it:\n<<<\n--- a/x\n"
                      "+++ b/x\n>>>\n\n[Message from Claude Code via the consultants bridge]\n[Revision: commit abc. Name", content)
        self.assertIn("The user's own words, as they typed them:\n<<<\nfruit?\n>>>", content)

        # The next turn continues the conversation, on a new level, without the preamble; it runs on.
        self.replies = [None]
        with mock.patch.object(server, "agy_alive", self.alive):
            out = server.send_consultant_message({"kind": "other", "to": name, "message": "And now?", "effort": "low", "wait": 0})
            self.assertIn("Delivered to", out)
            self.assertIn(f"server.py wait {server.agy_resolve(name)['id']} ", out)
            argv, _, sent = self.runs[1]
            self.assertEqual(argv[argv.index("--conversation") + 1], "conv-1234-abcd")
            self.assertEqual(json.loads(argv[argv.index("--settings") + 1]), server.AGY_READ_ONLY)  # every turn
            self.assertEqual(argv[argv.index("--model") + 1], "gemini-4-neon-low")
            self.assertFalse(json.loads(sent)["message"]["content"].startswith(server.AGY_PREAMBLE))
            # 0.26.0: the read-only rules again on every later turn
            self.assertTrue(json.loads(sent)["message"]["content"].startswith(server.AGY_REMINDER))
            for said in ("still a read-only consultant", "Don't write files, run commands, schedule tasks",
                         "start background work"):  # the reminder's words, not only the constant
                self.assertIn(said, json.loads(sent)["message"]["content"])
            with self.assertRaisesRegex(server.BridgeError, "still working on turn .* nothing was sent"):
                server.send_consultant_message({"kind": "other", "to": name, "message": "Third", "wait": 0})
            self.assertEqual(len(self.runs), 2)
            busy = server.get_consultant_reply({"to": name})
            self.assertIn("this is not a reply", busy)
            self.assertIn("working", server.list_consultants({}))
            history = server.get_consultant_history({"to": name})
            self.assertRegex(history, r"\[inProgress, .*\] from Claude Code: \"And now\?\"")
            self.assertRegex(history, r"\[completed, .*took 7s\] from Claude Code \(with the user's words\): "
                                      r"\"Which fruit\?\" -> \"pomme\"")
            self.assertEqual(server.agy_resolve(name)["model"], "gemini-4-neon-low")
            with mock.patch.object(server, "agy_end_process", return_value=True) as kill:
                stopped = server.stop_consultant({"to": name})
            self.assertEqual(kill.call_args.args[0]["pid"], 4242)
        self.assertIn("Ended its running turn", stopped)
        self.assertIn("agy --conversation conv-1234-abcd", stopped)
        self.assertIsNone(server.agy_resolve(name))
        cid = [e for e in self.events() if e["event"] == "start"][0]["thread"]
        last = server.agy_turns(cid, 1)[0]
        self.assertEqual(last["status"], "interrupted")

        # The log: sends with provider and model, a reply with tokens. Never the message text.
        # A send's usage snapshot is written from a thread, so wait for both. Only this consultant's
        # count: a thread left from an earlier test can write late into this test's log.
        deadline = time.monotonic() + 10
        while True:
            events = self.events()
            sends = [e for e in events if e["event"] == "send" and e["thread"] == cid]
            if len(sends) >= 2 or time.monotonic() > deadline:
                break
            time.sleep(0.05)
        self.assertEqual([(e["provider"], e["model"], e["effort"]) for e in sends],
                         [("antigravity", "gemini-4-neon-high", "high"), ("antigravity", "gemini-4-neon-low", "low")])
        self.assertEqual(sends[1]["changed"], ["effort"])  # 0.16.0: high to low is the level, not the model
        reply = [e for e in events if e["event"] == "reply" and e["thread"] == cid][0]
        self.assertEqual((reply["provider"], reply["tokens"]["output_tokens"], reply["ms"]), ("antigravity", 120, 7500))
        with open(self.log, encoding="utf-8") as f:
            self.assertNotIn("Which fruit", f.read())

    def test_turn_outcomes(self):
        _, name = self.start()
        cid = server.agy_resolve(name)["id"]
        cases = [
            ([agy_result("", status="ERROR", error="quota exhausted")], "failed", "Antigravity: quota exhausted"),
            ([agy_result("half", finished_reason="print_timeout")], "interrupted", "Antigravity ended the turn at nouez's 30m limit"),
            ([], "failed", "agy ended without a result: boom"),
        ]
        for events, status, error in cases:
            with self.subTest(status=status, error=error):
                self.replies = [events]
                with mock.patch.object(server, "agy_alive", lambda meta: False):
                    server.send_consultant_message({"kind": "other", "to": name, "message": "x", "wait": 0})
                    tid = server.agy_turn_ids(cid)[0]
                    with open(os.path.join(server.agy_folder(cid), "turns", tid + ".err"), "w") as f:
                        f.write("starting\nboom\n")
                    out = server.get_consultant_reply({"to": name})
                self.assertIn(f"turn {tid} {status}. {error}", out)
                if status == "failed":
                    self.assertIn("failed in Antigravity", out)
                    self.assertNotIn("Codex", out)

    def test_waiter(self):
        _, name = self.start()
        rec = server.agy_resolve(name)
        self.replies = [[agy_result("done here")]]
        server.send_consultant_message({"kind": "other", "to": name, "message": "x", "wait": 0})
        tid = server.agy_turn_ids(rec["id"])[0]
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            self.assertEqual(server.run_waiter(rec["id"], tid), 0)
            self.assertEqual(server.run_waiter(rec["id"], "0199aaaa-0000-0000-0000-000000000000"), 1)
        self.assertIn("The consultant's turn has ended (Antigravity consultant", out.getvalue())
        self.assertIn("done here", out.getvalue())
        self.assertIn("has no turn 0199aaaa", out.getvalue())
        self.assertIn("characters 2-9 of 9", server.get_consultant_reply({"to": name, "offset": 2}))

    def test_conversation_id_is_never_an_option(self):
        _, name = self.start()
        cid = server.agy_resolve(name)["id"]
        for conv, want in (("--dangerously-skip-permissions", None), ("-abcdefgh", None), ("short", None),
                           ("a b c d e f g h", None), ("conv-1234-abcd", "conv-1234-abcd")):
            with self.subTest(conv=conv):
                self.replies = [[agy_result("ok")]]
                with mock.patch.object(server, "agy_alive", lambda meta: False):
                    server.send_consultant_message({"kind": "other", "to": name, "message": "x", "wait": 0})
                # The newest turn's events name this conversation; older turns name only rejected ones.
                with open(os.path.join(server.agy_folder(cid), "turns", server.agy_turn_ids(cid)[0] + ".jsonl"),
                          "w", encoding="utf-8") as f:
                    f.write(agy_lines({"event": "result", "conversation_id": conv, "result": {"status": "SUCCESS"}}))
                self.assertEqual(server.agy_conversation(cid), want)

    def test_resolve(self):
        _, a = self.start()
        _, b = self.start(new=True)
        ra, rb = server.agy_resolve(a), server.agy_resolve(b)
        self.assertEqual(server.agy_resolve(ra["id"][-6:]), ra)
        self.assertEqual(server.agy_resolve(ra["id"][:8]) if ra["id"][:8] != rb["id"][:8] else ra, ra)
        self.assertIsNone(server.agy_resolve(ra["id"][-6:], exact_only=True))
        self.assertIsNone(server.agy_resolve("codex-nouez-abcdef"))
        self.assertIsNone(server.agy_resolve(""))

    def test_names_never_clash(self):
        """0.15.1: a name another consultant has gets more of the id; a name two share is refused."""
        cid = "01a20315-4fb3-73b3-bb66-75ebdee30b97"
        self.assertEqual(server.agy_name(self.work, cid), f"agy-{os.path.basename(self.work).lower()}-e30b97")
        taken = {server.agy_name(self.work, cid)}
        self.assertTrue(server.agy_name(self.work, cid, taken).endswith("-75ebdee30b97"[-8:]))
        _, a = self.start()
        _, b = self.start(new=True)
        rb = server.agy_resolve(b)
        server.agy_save({**rb, "name": a})  # two consultants named alike, as by an older nouez
        with self.assertRaisesRegex(server.BridgeError, "names several Antigravity consultants"):
            server.agy_resolve(a)
        self.assertEqual(server.agy_resolve(rb["id"])["id"], rb["id"])

    def test_result_written_as_agy_exits_is_read(self):
        """0.15.1: agy is seen ended before its output is read, so a result written just before
        it exits is never taken for a failure."""
        _, name = self.start()
        cid = server.agy_resolve(name)["id"]
        self.replies = [None]
        server.send_consultant_message({"kind": "other", "to": name, "message": "x", "wait": 0})
        tid = server.agy_turn_ids(cid)[0]
        out = os.path.join(server.agy_folder(cid), "turns", tid + ".jsonl")

        def finishes(meta):  # the result lands, then agy exits, between the check and the read
            with open(out, "a", encoding="utf-8") as f:
                f.write(agy_lines(agy_result("just in time")))
            return False
        with mock.patch.object(server, "agy_alive", finishes):
            turn = server.agy_turn(cid, tid)
        self.assertEqual(turn["status"], "completed")
        meta = server.read_json_file(os.path.join(server.agy_folder(cid), "turns", tid + ".json"))
        self.assertNotIn("shown", meta)  # the message is read from .in, so the record stays small
        self.assertEqual(turn["items"][0]["content"][0]["text"],
                         "[Message from Claude Code via the consultants bridge]\n\nx")

    def test_waiter_says_when_agy_writes_nothing_new(self):
        """0.20.0: agy adds an event every few seconds, so a turn file that stops growing may be
        stuck, as on agy's schedule tool."""
        _, name = self.start()
        cid = server.agy_resolve(name)["id"]
        self.replies = [None]
        server.send_consultant_message({"kind": "other", "to": name, "message": "x", "wait": 0})
        tid = server.agy_turn_ids(cid)[0]
        buf = io.StringIO()
        with mock.patch.object(server, "agy_alive", lambda meta: True), \
                mock.patch.object(server, "STALL_SECONDS", 0.05), contextlib.redirect_stdout(buf):
            code = server.run_waiter(cid, tid)
        self.assertEqual(code, 0)
        self.assertIn(f"still working on turn {tid}; this is not a reply", buf.getvalue())
        self.assertIn("agy's schedule tool", buf.getvalue())
        self.assertIn(f"wait {cid} {tid}", buf.getvalue())

    def test_launch_failure_and_bad_model(self):
        _, name = self.start()
        rec = server.agy_resolve(name)

        def broken(*a):
            raise FileNotFoundError("no such program")
        with mock.patch.object(server, "agy_spawn", broken):
            with self.assertRaisesRegex(server.BridgeError, "Could not start agy"):
                server.send_consultant_message({"kind": "other", "to": name, "message": "x", "wait": 0})
        turn = server.agy_turns(rec["id"], 1)[0]
        self.assertEqual(turn["status"], "failed")
        self.assertIn("Could not start agy: no such program", turn["error"]["message"])
        self.assertNotIn("StopConsultant", turn["error"]["message"])
        server.agy_save({**rec, "model": "--dangerously-skip-permissions"})  # an edited record
        with self.assertRaisesRegex(server.BridgeError, "has no valid model"):
            server.send_consultant_message({"kind": "other", "to": name, "message": "x", "wait": 0})
        self.assertEqual(self.runs, [])

    def test_lock_and_stopped_consultant(self):
        """0.15.1: one lock per consultant across nouez servers; a send re-reads the consultant under it."""
        _, name = self.start()
        rec = server.agy_resolve(name)
        with mock.patch.object(server, "LOCK_SECONDS", 0.3):
            with server.agy_lock(rec["id"]):
                with self.assertRaisesRegex(server.BridgeError, "Another Claude Code session"):
                    with server.agy_lock(rec["id"]):
                        pass
                with self.assertRaisesRegex(server.BridgeError, "Another Claude Code session"):
                    server.send_consultant_message({"kind": "other", "to": name, "message": "x", "wait": 0})
        self.assertEqual(self.runs, [])
        server.agy_save({**rec, "stopped": time.time()})  # stopped by another session after resolving
        with self.assertRaisesRegex(server.BridgeError, "was stopped; nothing was sent"):
            server.send_agy_message(rec, {}, "x", "Claude Code", None, 0, None, None, None, None)
        self.assertEqual(self.runs, [])

    def test_stopping_only_the_turn_keeps_the_consultant(self):
        _, name = self.start()
        cid = server.agy_resolve(name)["id"]
        self.assertIn("has no turn running", server.stop_consultant({"to": name, "turn_only": True}))
        self.replies = [None]
        with mock.patch.object(server, "agy_alive", self.alive):
            server.send_consultant_message({"kind": "other", "to": name, "message": "x", "wait": 0})
            with mock.patch.object(server, "agy_end_process", return_value=True):
                out = server.stop_consultant({"to": name, "turn_only": True})
        self.assertIn("Ended agy-", out)
        self.assertIn("takes the next message", out)
        self.assertFalse(server.agy_resolve(name).get("stopped"))  # still there for the next message
        self.assertEqual(server.agy_turns(cid, 1)[0]["status"], "interrupted")

    def test_failed_stop_changes_nothing(self):
        _, name = self.start()
        cid = server.agy_resolve(name)["id"]
        self.replies = [None]
        with mock.patch.object(server, "agy_alive", self.alive):
            server.send_consultant_message({"kind": "other", "to": name, "message": "x", "wait": 0})
            with mock.patch.object(server, "agy_end_process", return_value=False):
                with self.assertRaisesRegex(server.BridgeError, "Couldn't stop .*pid 4242.*Nothing was stopped"):
                    server.stop_consultant({"to": name})
            self.assertFalse(server.agy_resolve(name).get("stopped"))
            self.assertEqual(server.agy_turns(cid, 1)[0]["status"], "inProgress")
            path = os.path.join(server.agy_folder(cid), "turns", server.agy_turn_ids(cid)[0] + ".json")
            self.assertNotIn("stopping", server.read_json_file(path))
            seen = []

            def ends(meta):  # while it is being ended: still running, so still in progress
                seen.append((server.read_json_file(path), server.agy_turns(cid, 1)[0]["status"]))
                self.running = False
                return True
            with mock.patch.object(server, "agy_end_process", ends):
                self.assertIn("Ended its running turn", server.stop_consultant({"to": name}))
        (during, status), = seen
        self.assertTrue(during.get("stopping"))
        self.assertNotIn("stopped", during)  # written only once agy has ended (round 3, point 2)
        self.assertEqual(status, "inProgress")
        self.assertTrue(server.read_json_file(path).get("stopped"))
        self.assertEqual(server.agy_turns(cid, 1)[0]["status"], "interrupted")
        self.assertIsNone(server.agy_resolve(name))

    def test_stop_during_a_read_is_a_stop(self):
        """A reader that loaded the turn just before a stop marked it names it stopped, not failed."""
        _, name = self.start()
        cid = server.agy_resolve(name)["id"]
        self.replies = [None]
        with mock.patch.object(server, "agy_alive", self.alive):
            server.send_consultant_message({"kind": "other", "to": name, "message": "x", "wait": 0})
        tid = server.agy_turn_ids(cid)[0]
        path = os.path.join(server.agy_folder(cid), "turns", tid + ".json")

        def stopped_meanwhile(meta):  # the stop marks the turn and ends agy between the reads
            server.write_json_atomic(path, {**meta, "stopping": True, "stopped": True})
            return False
        with mock.patch.object(server, "agy_alive", stopped_meanwhile):
            self.assertEqual(server.agy_turn(cid, tid)["status"], "interrupted")

    def test_failed_stop_clears_its_mark_after_a_failed_save(self):
        _, name = self.start()
        cid = server.agy_resolve(name)["id"]
        self.replies = [None]
        real, fails = server.write_json_atomic, [1]

        def flaky(path, data):  # the first save that takes the mark back fails
            if path.endswith(".json") and "turns" in path and not data.get("stopping") and fails:
                fails.pop()
                return False
            return real(path, data)
        with mock.patch.object(server, "agy_alive", self.alive):
            server.send_consultant_message({"kind": "other", "to": name, "message": "x", "wait": 0})
            with mock.patch.object(server, "agy_end_process", return_value=False), \
                 mock.patch.object(server, "write_json_atomic", flaky), mock.patch.object(server.time, "sleep"):
                with self.assertRaises(server.BridgeError):
                    server.stop_consultant({"to": name})
        self.assertEqual(fails, [])
        path = os.path.join(server.agy_folder(cid), "turns", server.agy_turn_ids(cid)[0] + ".json")
        self.assertNotIn("stopping", server.read_json_file(path))

    def test_unsaved_model_said_on_a_reply(self):
        """0.15.1: a reply that came back on a model nouez couldn't save says so (round 3, point 3)."""
        _, name = self.start()
        self.replies = [[agy_result("ok")]]
        with mock.patch.object(server, "agy_save", side_effect=server.BridgeError("disk full")):
            out = server.send_consultant_message({"kind": "other", "to": name, "message": "x", "effort": "low", "wait": 5})
        self.assertIn("ok", out)
        self.assertIn("couldn't save it as", out)
        self.assertEqual(server.agy_resolve(name)["model"], "gemini-4-neon-high")

    def test_unsaved_pid_ends_agy(self):
        _, name = self.start()
        cid = server.agy_resolve(name)["id"]
        real = server.write_json_atomic
        writes = []

        def pid_write_fails(path, data):
            if path.endswith(".json") and os.sep + "turns" + os.sep in path:
                writes.append(path)
                if len(writes) == 2:  # the write that records the pid
                    return False
            return real(path, data)
        with mock.patch.object(server, "write_json_atomic", pid_write_fails), \
                mock.patch.object(server, "agy_end_unsaved", return_value=True) as end:
            with self.assertRaisesRegex(server.BridgeError, "agy was ended and nothing was sent"):
                server.send_consultant_message({"kind": "other", "to": name, "message": "x", "wait": 0})
        self.assertEqual(end.call_args.args[0].pid, 4242)
        self.assertEqual(server.agy_turn_ids(cid), [])  # no turn left looking as if it were starting
        with mock.patch.object(server, "LOCK_SECONDS", 0.2), server.agy_lock(None):
            with self.assertRaisesRegex(server.BridgeError, "starting an Antigravity consultant"):
                self.start(new=True)

    @unittest.skipUnless(os.name == "nt", "Windows process handles")
    def test_stop_ends_only_the_process_nouez_started(self):
        proc = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
        self.addCleanup(proc.wait)
        self.addCleanup(proc.kill)
        handle = server.open_process(proc.pid)
        meta = {"pid": proc.pid, "pid_start": server.handle_start(handle), "image": server.handle_image(handle),
                "started": time.time()}
        server.close_handle(handle)
        self.assertTrue(server.agy_alive(meta))
        # (changed fields, counts as running, agy_end_process's answer); never ended in any of these
        for wrong, alive, ended in (({"pid_start": meta["pid_start"] + 1}, False, True),  # pid now another's
                                    ({"image": "C:\\other\\agy.exe"}, False, True),   # another program
                                    ({"pid_start": None}, True, False),                 # can't be checked
                                    ({"image": None}, True, False),
                                    ({"image": None, "started": time.time() - 3 * 3600}, False, False)):
            with self.subTest(wrong=wrong):
                self.assertEqual(server.agy_alive({**meta, **wrong}), alive)
                self.assertEqual(server.agy_end_process({**meta, **wrong}), ended)
                self.assertIsNone(proc.poll())
        # Its times can't be read but it runs: unknown, never taken for ended (round 3, point 1)
        with mock.patch.object(server, "handle_start", return_value=None):
            self.assertTrue(server.agy_alive(meta))
            self.assertFalse(server.agy_end_process(meta))
            self.assertEqual(server.agy_identity(meta)[0], "unknown")
        self.assertIsNone(proc.poll())
        self.assertTrue(server.agy_end_process(meta))
        self.assertIsNotNone(proc.wait(timeout=5))
        self.assertFalse(server.agy_alive(meta))

    def test_budget_and_offload(self):
        now = time.time()

        def reset(secs):
            return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(now + secs))
        live = {"groups": [{"name": "Gemini Models", "buckets": [
            {"window": "weekly", "remaining_fraction": 0.75, "reset_time": reset(3 * 86400)}]}]}
        text = "\n".join(server.agy_budget(now, live))
        self.assertIn("Antigravity (Google;", text)
        self.assertRegex(text, r"Gemini Models: weekly window: 25(\.0)?% used")
        self.assertIn("gemini-4-neon (low, high, xhigh)", text)
        failed = server.agy_budget(now, {"error": "agy: not signed in"})
        self.assertEqual(failed[0], "Antigravity: usage not known (agy: not signed in).")
        self.assertIn("gemini-4-neon (low, high, xhigh)", failed[1])  # models even when the quota call fails
        installed = os.path.join(self.dir, "agy.exe")
        with mock.patch.object(server, "agy_command", lambda env=None: installed), \
             mock.patch.object(server, "which", lambda name, env=None: None):
            self.assertEqual(server.agy_shown(), ("& " if os.name == "nt" else "") + f"'{installed}'")
        with mock.patch.object(server, "agy_command", lambda env=None: installed), \
             mock.patch.object(server, "which", lambda name, env=None: installed):
            self.assertEqual(server.agy_shown(), "agy")
        with mock.patch.object(server, "read_agy_usage", lambda: None):
            self.assertEqual(server.agy_budget(now), [])
        self.assertEqual(server.usage_snapshot(None, live)["usage"]["antigravity"], {"AG Gemini": {"weekly": 25.0}})

        week = server.week_of(now)
        replies = [{"event": "reply", "ts": now, "turn": "t1", "provider": "antigravity", "tokens": {"output_tokens": 3000}},
                   {"event": "reply", "ts": now, "turn": "t1", "provider": "antigravity", "tokens": {"output_tokens": 3000}},
                   {"event": "reply", "ts": now, "turn": "t2", "status": "completed", "ms": 10}]
        summary = server.log_summary(replies)
        self.assertEqual(summary["gemini_week"], {week: 3000})
        scr = server.Screen(False)
        weeks = {week: {"claude": 9000, "subagents": 0, "consultants": 0, "codex": 0, "models": {}}}
        rows = "\n".join(server.offload_rows(scr, weeks, {}, False, summary["gemini_week"]))
        self.assertIn("Antigravity", rows)
        self.assertRegex(rows, r"sends +share")
        self.assertRegex(rows, week + r" .* 3k +— .* 25%")  # no log before this week: sends not known
        self.assertTrue(all(len(x) <= 100 for x in rows.splitlines()))
        rows = "\n".join(server.offload_rows(scr, weeks, {week: 2}, False, {}, now, {week}))
        self.assertRegex(rows, week + r" .* — +2 ")  # Antigravity replies that reported no tokens
        rows = "\n".join(server.offload_rows(scr, weeks, {week: 2}, False, {week: 3000}, now, {week}))
        self.assertRegex(rows, week + r" .* 3k\+ +2 ")  # some did, some didn't
        rows = "\n".join(server.offload_rows(scr, {}, {week: 2}, False, {}, now))
        self.assertRegex(rows, "(?m)" + week + r" .* 2 +—$")  # a week with messages only is shown, with no share
        sent = [{"event": "send", "ts": now, "turn": "t8", "provider": "antigravity"}]  # no reply yet
        self.assertEqual(server.log_summary(sent)["gemini_unknown"], {week})
        # the tokens go to the week the message was sent, not the week its reply was read
        later = [{"event": "send", "ts": now - 8 * 86400, "turn": "t9"},
                 {"event": "reply", "ts": now, "turn": "t9", "provider": "antigravity", "tokens": {"output_tokens": 5}}]
        self.assertEqual(server.log_summary(later)["gemini_week"], {server.week_of(now - 8 * 86400): 5})
        only = "\n".join(server.offload_rows(scr, {}, {}, False, {week: 1000}))
        self.assertRegex(only, week + r" .*100%")



    def test_turns_of_long_stopped_consultants_go(self):
        """0.22.0: AGY_TURN_KEEP_DAYS after a stop, its turn files go; consultant.json keeps the conversation."""
        _, name = self.start()
        _, other = self.start(new=True)
        for who in (name, other):
            self.replies = [[agy_result("ok\n")]]
            server.send_consultant_message({"kind": "other", "to": who, "message": "hi", "wait": 5})
        cid = server.agy_resolve(name)["id"]
        running = os.path.join(self.dir, "agy", server.agy_resolve(other)["id"], "turns")
        turns = os.path.join(self.dir, "agy", cid, "turns")
        self.assertEqual(len(os.listdir(turns)), 4)  # .in, .json, .jsonl, .err
        if os.name != "nt":
            self.assertEqual(os.stat(turns).st_mode & 0o777, 0o700)
        server.stop_consultant({"to": name})
        server.prune_agy_turns(time.time())  # just stopped: kept
        self.assertEqual(len(os.listdir(turns)), 4)
        server.prune_agy_turns(time.time() + (server.AGY_TURN_KEEP_DAYS + 1) * 86400)
        self.assertEqual(os.listdir(turns), [])
        rec = server.read_json_file(os.path.join(self.dir, "agy", cid, "consultant.json"))
        self.assertEqual(rec["conversation"], "conv-1234-abcd")
        self.assertTrue(rec["turns_removed"])
        self.assertEqual(len(os.listdir(running)), 4)  # a consultant still in use keeps its turns

    def test_turns_that_couldnt_be_deleted_are_tried_again(self):
        """0.22.0: a turn file that can't be deleted leaves the consultant to try at the next start."""
        _, name = self.start()
        self.replies = [[agy_result("ok\n")]]
        server.send_consultant_message({"kind": "other", "to": name, "message": "hi", "wait": 5})
        cid = server.agy_resolve(name)["id"]
        turns = os.path.join(self.dir, "agy", cid, "turns")
        server.stop_consultant({"to": name})
        later = time.time() + (server.AGY_TURN_KEEP_DAYS + 1) * 86400
        with mock.patch.object(server.os, "remove", side_effect=PermissionError("in use")):
            server.prune_agy_turns(later)
        rec = server.read_json_file(os.path.join(self.dir, "agy", cid, "consultant.json"))
        self.assertNotIn("turns_removed", rec)
        self.assertEqual(rec["conversation"], "conv-1234-abcd")  # kept before anything went
        self.assertEqual(len(os.listdir(turns)), 4)
        server.prune_agy_turns(later)
        self.assertEqual(os.listdir(turns), [])
        rec = server.read_json_file(os.path.join(self.dir, "agy", cid, "consultant.json"))
        self.assertTrue(rec["turns_removed"])

    def test_turn_files_never_go_through_a_link(self):
        """0.22.0: a turns folder that is a link isn't written through; nothing is sent."""
        _, name = self.start()
        cid = server.agy_resolve(name)["id"]
        outside = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, outside, True)
        dir_link(outside, os.path.join(self.dir, "agy", cid, "turns"))
        with self.assertRaisesRegex(server.BridgeError, "Nothing was sent"):
            server.send_consultant_message({"kind": "other", "to": name, "message": "hi", "wait": 0})
        self.assertEqual(os.listdir(outside), [])
        self.assertEqual(self.runs, [])

class ReviewRoundsTest(unittest.TestCase):
    """0.26.0: nouez counts review rounds on the same work, and sends a blind second opinion."""

    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.dir, True)
        self.head = "a" * 40
        for attr, value in (("nouez_cache_dir", lambda: self.dir), ("git_head", lambda cwd: self.head),
                            ("POLL_SECONDS", 0.01), ("_delivered", {})):
            patcher = mock.patch.object(server, attr, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        self.thread = {"id": "0199aaaa-0000-0000-0000-000000rnd001", "cwd": ROOT, "threadSource": "nouez"}

    def use(self, daemon):
        patcher = mock.patch.object(server, "CodexClient", daemon)
        patcher.start()
        self.addCleanup(patcher.stop)
        return daemon

    def review(self, **args):
        return server.send_consultant_message({"to": self.thread["id"], "message": "Review commit abc.",
                                               "kind": "review", "wait": 5, **args})

    def test_rounds_count_and_the_third_asking_for_changes_says_to_stop(self):
        self.use(FakeDaemon([self.thread], answer="Verdict: CHANGES\n1. fix x"))
        first, second, third = self.review(), self.review(), self.review()
        self.assertNotIn("(nouez: this is round", first + second)
        self.assertIn("(nouez: this is round 3 of review on the same work, and it still asks for changes.", third)
        self.assertIn("round 4 of review on the same work", self.review())
        chain = server.review_chain(self.thread["id"])
        self.assertEqual((chain["rounds"], chain["brief"], chain["revision"]), (4, "Review commit abc.", False))
        # The note is read with the reply too, and only for the chain's latest turn.
        self.assertIn("round 4", server.round_note(self.thread["id"], "turn-new", "changes"))
        self.assertEqual(server.round_note(self.thread["id"], "turn-old", "changes"), "")
        self.assertEqual(server.round_note(self.thread["id"], "turn-new", "yes"), "")

    def test_a_round_past_three_is_refused_only_when_the_user_says_so(self):
        self.use(FakeDaemon([self.thread], answer="CHANGES: fix x"))
        for _ in range(3):
            self.review()
        with mock.patch.dict(os.environ, {"NOUEZ_REVIEW_ROUNDS_STOP": "1"}):
            self.assertIn("another is refused", server.round_note(self.thread["id"], "turn-new", "changes"))
            with self.assertRaisesRegex(server.BridgeError, "round 4 of review .* Nothing was sent"):
                self.review()
            # Other kinds aren't counted.
            server.send_consultant_message({"to": self.thread["id"], "message": "q", "kind": "quick-check", "wait": 5})

    def test_a_chain_starts_over_on_an_ok_a_new_commit_or_a_day_later(self):
        cid, latest = "c-1", {"id": "t", "status": "completed", "items": [agent("Verdict: CHANGES", "final_answer")]}
        ok = {"id": "t", "status": "completed", "items": [agent("Verdict: yes", "final_answer")]}

        def send(turn, now=1000.0, kind="review"):
            chain = server.next_review_round(cid, "c", ROOT, kind, [turn] if turn else [], now)
            server.save_review_round(cid, chain, "t", "brief " + kind, {}, now)
            return chain and chain["rounds"]
        self.assertEqual([send(None), send(latest), send(latest, kind="re-check")], [1, 2, 3])
        self.assertIsNone(send(latest, kind="quick-check"))
        self.assertEqual(server.review_chain(cid)["brief"], "brief review")  # the first round's brief
        self.assertEqual(send(ok), 1)
        self.assertEqual(send(latest), 2)
        self.head = "b" * 40
        self.assertEqual(send(latest), 1)
        self.assertEqual(send(latest, now=1000.0 + server.REVIEW_CHAIN_HOURS * 3600), 1)
        running = {"id": "t", "status": "inProgress", "items": [agent("Verdict: yes", "final_answer")]}
        self.assertEqual(send(running, now=1000.0 + server.REVIEW_CHAIN_HOURS * 3600), 2)  # not a verdict yet
        chain = server.next_review_round(cid, "c", ROOT, "review", None, 1000.0 + 3 * server.REVIEW_CHAIN_HOURS * 3600)
        server.save_review_round(cid, chain, "t", "x" * (server.REVIEW_BRIEF_CHARS + 1), {}, 0)
        self.assertIsNone(server.review_chain(cid)["brief"])  # too long to keep

    def test_the_verdict_is_the_chain_s_own(self):
        # Codex finding 8: another consultation in between neither ends nor revives a chain.
        cid, now = "c-2", 1000.0

        def turn(tid, verdict):
            return {"id": tid, "status": "completed", "items": [agent(f"Verdict: {verdict}", "final_answer")]}

        def send(recent, kind="review", tid="t1"):
            chain = server.next_review_round(cid, "c", ROOT, kind, recent, now)
            server.save_review_round(cid, chain, tid, "brief " + kind, {}, now)
            return chain and chain["rounds"]
        self.assertEqual(send([]), 1)
        # The review asked for changes; a quick check after it ended in a yes.
        self.assertEqual(send([turn("q1", "yes"), turn("t1", "CHANGES")]), 2)
        # The chain's last round was approved; an unrelated reply after it asks for changes.
        self.assertEqual(send([turn("q2", "CHANGES"), turn("t1", "yes")]), 1)
        # Codex round 2, finding 7: the chain's last round is out of sight (20 other turns since), so
        # its verdict is unknown: an OK can't be told from changes, and the chain starts over.
        self.assertEqual(send([turn("q3", "CHANGES")]), 1)
        self.assertEqual(send([turn("t1", "CHANGES")]), 2)
        # A round Codex cut off and carried on: the continuation's verdict counts.
        cut = {"id": "t1", "status": "interrupted", "items": [agent("Verdict: CHANGES", "final_answer")]}
        with mock.patch.object(server, "next_in_chain", lambda turns, t, text=None: turn("t1b", "yes")
                               if t["id"] == "t1" else None):
            self.assertEqual(send([turn("t1b", "yes"), cut]), 1)

    def test_bug_hunts_and_critiques_keep_their_brief_uncounted(self):
        # Codex finding 5: Budget offers a second opinion for these, so their brief is kept, but
        # their rounds aren't counted, and a review after one starts a review chain of its own.
        cid, now = "c-3", 1000.0
        changes = {"id": "t", "status": "completed", "items": [agent("Verdict: CHANGES", "final_answer")]}
        for kind in ("bug-hunt", "plan-critique"):
            with self.subTest(kind=kind):
                for _ in range(2):
                    chain = server.next_review_round(cid, "c", ROOT, kind, [changes], now)
                    self.assertEqual((chain["kind"], chain["rounds"]), (kind, 1))
                    server.save_review_round(cid, chain, "t", "hunt " + kind, {}, now)
                self.assertEqual(server.review_chain(cid)["brief"], "hunt " + kind)
                chain = server.next_review_round(cid, "c", ROOT, "re-check", [changes], now)
                self.assertEqual((chain["kind"], chain["rounds"]), ("re-check", 1))
        self.assertIsNone(server.next_review_round(cid, "c", ROOT, "quick-check", [changes], now))

    def test_old_review_chains_are_pruned(self):
        folder = os.path.join(self.dir, "review-rounds")
        os.makedirs(folder)
        names = ["chain-old.json", "chain-new.json", "chain-old.ab12.tmp", "notes.json"]
        for n in names:
            open(os.path.join(folder, n), "w").close()
        for n in ("chain-old.json", "chain-old.ab12.tmp", "notes.json"):
            os.utime(os.path.join(folder, n), (time.time() - 30 * 86400,) * 2)
        server.prune_replies()
        self.assertEqual(sorted(os.listdir(folder)), ["chain-new.json", "notes.json"])

    def test_a_steered_round_has_no_second_opinion(self):
        # Codex round 2, finding 4: a message steered into the running round's turn (here a bug hunt
        # into a review) means the kept brief isn't all that turn was asked.
        running = {"id": "turn-1", "status": "inProgress", "items": []}
        daemon = self.use(FakeDaemon([self.thread], {self.thread["id"]: [running]}))
        server.write_json_atomic(server.review_chain_path(self.thread["id"], create=True),
                                 {"kind": "review", "brief": "Review commit abc.", "rounds": 1, "turns": ["turn-1"]})
        self.assertIsNone(server.steered_review_round(self.thread["id"], "turn-0"))  # not the chain's turn
        self.assertNotIn("steered", server.review_chain(self.thread["id"]))
        self.assertIsNone(server.steered_review_round("no-chain-here", "turn-1"))
        # Codex rounds 3 and 4, finding 4: marked before the steer goes, and nothing goes when the chain
        # can't be marked, or is there but can't be read.
        bug_hunt = {"to": self.thread["id"], "message": "Find why x fails.", "kind": "bug-hunt", "wait": 0}
        for name, value in (("write_json_atomic", False), ("read_json_file", None)):
            with self.subTest(failing=name), mock.patch.object(server, "_bridge_turns", {"turn-1"}), \
                    mock.patch.object(server, name, return_value=value), \
                    self.assertRaisesRegex(server.BridgeError, "couldn't record that a message was added"):
                server.send_consultant_message(bug_hunt)
        self.assertEqual(daemon.calls.count("turn/steer"), 0)
        # A steer the daemon refuses outright added nothing, so the chain is put back as it was.
        real = daemon.request

        def refuse(method, params):
            if method == "turn/steer":
                raise server.BridgeError("turn/steer failed: no active turn")
            return real(method, params)
        with mock.patch.object(server, "_bridge_turns", {"turn-1"}), mock.patch.object(daemon, "request", refuse), \
                self.assertRaisesRegex(server.BridgeError, "no active turn"):
            server.send_consultant_message(bug_hunt)
        self.assertNotIn("steered", server.review_chain(self.thread["id"]))
        with mock.patch.object(server, "_bridge_turns", {"turn-1"}):
            out = server.send_consultant_message({"to": self.thread["id"], "message": "Find why x fails.",
                                                  "kind": "bug-hunt", "wait": 0})
        self.assertIn("steered into the running turn", out)
        self.assertEqual(daemon.calls.count("turn/steer"), 1)
        self.assertTrue(server.review_chain(self.thread["id"])["steered"])
        agy = {"id": "agy-2", "name": "agy-nouez-2", "cwd": ROOT}
        with mock.patch.object(server, "agy_resolve", lambda to, exact_only=False: agy if to == "agy-nouez-2" else None), \
                self.assertRaisesRegex(server.BridgeError, "had another message added to it while it ran"):
            server.send_consultant_message({"to": "agy-nouez-2", "kind": "review",
                                            "second_opinion_of": self.thread["id"]})

    def test_second_opinion_sends_the_first_brief_blind(self):
        other = {"id": "0199aaaa-0000-0000-0000-000000rnd002", "cwd": ROOT, "threadSource": "nouez"}
        daemon = self.use(FakeDaemon([self.thread, other], answer="Verdict: CHANGES"))
        self.review(revision=False)
        agy = {"id": "agy-1", "name": "agy-nouez-1", "cwd": ROOT}
        found = lambda to, exact_only=False: agy if to in ("agy-nouez-1", "agy-1") else None
        with mock.patch.object(server, "agy_resolve", found):
            for args, why in (({"message": "my findings"}, "leave out message and owner_words"),
                              ({}, "a Codex consultant, and a second opinion comes from the other provider")):
                with self.assertRaisesRegex(server.BridgeError, why):
                    server.send_consultant_message({"to": other["id"], "kind": "review",
                                                    "second_opinion_of": self.thread["id"], **args})
            with self.assertRaisesRegex(server.BridgeError, "no first brief of a consultation by agy-nouez-1"):
                server.send_consultant_message({"to": other["id"], "kind": "review", "second_opinion_of": "agy-nouez-1"})
            # From a Codex review to an Antigravity consultant: the brief is what is sent.
            sent = mock.Mock(return_value="sent")
            with mock.patch.object(server, "send_agy_message", sent):
                server.send_consultant_message({"to": "agy-nouez-1", "kind": "review", "second_opinion_of": self.thread["id"]})
            self.assertEqual(sent.call_args[0][2], "Review commit abc.")
        # A Codex consultant that has had messages isn't blind.
        server.write_json_atomic(server.review_chain_path("agy-1", create=True),
                                 {"brief": "Check it.", "rounds": 1, "turns": ["agy-t1"]})
        agy_recent = [{"id": "agy-t1", "status": "completed", "items": []}]
        with mock.patch.object(server, "agy_resolve", found), \
                mock.patch.object(server, "agy_turns", lambda cid, limit: agy_recent), \
                self.assertRaisesRegex(server.BridgeError, "has had messages already"):
            server.send_consultant_message({"to": self.thread["id"], "kind": "review", "second_opinion_of": "agy-nouez-1"})
        # Codex finding 5: once the first consultant has had another message, its kept brief is
        # no longer the one it is working on, so nothing is sent.
        later = [{"id": "agy-t2", "status": "completed", "items": []}] + agy_recent
        with mock.patch.object(server, "agy_resolve", found), \
                mock.patch.object(server, "agy_turns", lambda cid, limit: later), \
                self.assertRaisesRegex(server.BridgeError, "has had another message since"):
            server.send_consultant_message({"to": other["id"], "kind": "review", "second_opinion_of": "agy-nouez-1"})
        with mock.patch.object(server, "agy_resolve", found), \
                mock.patch.object(server, "agy_turns", lambda cid, limit: agy_recent):
            server.send_consultant_message({"to": other["id"], "kind": "review", "second_opinion_of": "agy-nouez-1",
                                            "wait": 5})
        self.assertIn("Check it.", daemon.started["input"][0]["text"])
        self.assertNotIn("Review commit abc.", daemon.started["input"][0]["text"])
        # A caller can't hand nouez the saved work itself.
        with mock.patch.object(server, "second_opinion", lambda a, to: self.fail("not blind")), \
                mock.patch.object(server, "revision_for", lambda a, cwd, **k: self.assertNotIn("_work", a) or
                                  ("", b"", "")):
            server.send_consultant_message({"to": other["id"], "message": "m", "kind": "quick-check",
                                            "revision": True, "_work": {"patch": "0" * 16}, "wait": 0})

    def test_a_second_opinion_reviews_the_same_diff(self):
        # Codex finding 4: the diff the first review was sent with is the one the second gets,
        # in the same repository; when it can't be had, nothing is sent.
        repo = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, repo, True)
        patch = b"diff --git a/x b/x\n--- a/x\n+++ b/x\n@@ -1 +1 @@\n-a\n+b\n"
        digest = hashlib.sha256(patch).hexdigest()[:16]
        folder = server.cache_folder(server.PATCH_FOLDER, create=True)
        with open(os.path.join(folder, digest + ".patch"), "wb") as f:
            f.write(patch)
        work = {"repo": repo, "patch": digest, "head": self.head}
        with mock.patch.object(server, "git_root", lambda cwd: cwd), \
                mock.patch.object(server, "revision", lambda *a, **k: self.fail("not taken again")):
            stamp, sent, got = server.revision_for({"_work": work}, repo, take=True, inline_limit=10_000)
            self.assertEqual((sent, got), (patch, digest))
            self.assertIn(f"sha256 {digest}", stamp)
            self.assertIn(f"[Revision: commit {self.head[:7]};", stamp)  # Codex round 4: the commit reviewed
            self.assertIn("the diff the first review was sent with is in this message", stamp)
            stamp, sent, _ = server.revision_for({"_work": work}, repo, take=False)
            self.assertEqual(sent, b"")
            self.assertIn("is saved as", stamp)
            with self.assertRaisesRegex(server.BridgeError, "too large to put in a message"):
                server.revision_for({"_work": work}, repo, inline_limit=10)
            with self.assertRaisesRegex(server.BridgeError, "review other work than the first one did"):
                server.revision_for({"_work": work}, self.dir)  # another repository
            with self.assertRaisesRegex(server.BridgeError, "no longer has the diff"):
                server.revision_for({"_work": dict(work, patch="f" * 16)}, repo)
            with open(os.path.join(folder, digest + ".patch"), "ab") as f:
                f.write(b"+changed\n")
            with self.assertRaisesRegex(server.BridgeError, "no longer has the diff"):
                server.revision_for({"_work": work}, repo)  # the saved file isn't that diff any more
        # A first review of a clean commit: the same commit and still nothing uncommitted, or nothing is sent.
        a, b = "a" * 40, "b" * 40
        clean = ("[Revision: ...]\n", b"", server.REVISION_CLEAN + a)
        found = [clean]
        with mock.patch.object(server, "git_root", lambda cwd: cwd), \
                mock.patch.object(server, "revision", lambda *args, **k: found[0]):
            self.assertEqual(server.revision_for({"_work": dict(work, patch=None, clean=a)}, repo), clean)
            # Codex round 2, finding 3: a first review that had changes nouez took no diff of (an
            # Antigravity review without attach_diff), or was outside git, can't be shown again,
            # even once the changes are gone.
            with self.assertRaisesRegex(server.BridgeError, "sent without a diff of its uncommitted changes"):
                server.revision_for({"_work": dict(work, patch=None)}, repo)
            # Codex round 3, finding 3: the commit is the one revision() found clean, not one read apart.
            for now in (("[Revision: ...]\n", b"", server.REVISION_CLEAN + b),
                        ("[Revision: ..., 1 uncommitted path(s)]\n", b"", "")):
                found[0] = now
                with self.assertRaisesRegex(server.BridgeError, "The work has changed since the first review"):
                    server.revision_for({"_work": dict(work, patch=None, clean=a)}, repo)
        server.save_review_round("c-5", server.next_review_round("c-5", "c", repo, "review", []), "t", "Review it.",
                                 {"revision": True}, cwd=repo, digest=server.REVISION_CLEAN + a)
        self.assertEqual((server.review_chain("c-5")["patch"], server.review_chain("c-5")["clean"]), (None, a))
        # The chain keeps the repository and the diff its first round was sent with.
        chain = server.next_review_round("c-4", "c", repo, "review", [])
        server.save_review_round("c-4", chain, "t", "Review it.", {"revision": True}, cwd=repo, digest=digest)
        kept = server.review_chain("c-4")
        self.assertEqual((kept["patch"], kept["revision"]), (digest, True))
        self.assertTrue(server.same_folder(kept["repo"], repo))


class PaneTest(unittest.TestCase):
    """0.23.0: the Codex panes earlier versions opened are found from Windows' own process list
    (not WMI) and closed once when a server starts."""
    TID = "01a2ffff-0000-7000-8000-00000000abcd"

    def setUp(self):
        key = mock.patch.object(server, "_pane_key", b"k" * 32)  # never the user's real key
        key.start()
        self.addCleanup(key.stop)

    def test_old_panes(self):
        t, u = self.TID, self.TID[:-1] + "e"
        table = {10: (1, "cmd.exe"), 11: (10, "codex.exe"), 12: (1, "codex.exe"), 13: (1, "codex.exe"),
                 14: (1, "cmd.exe"), 15: (14, "codex.exe"), 16: (1, "python.exe"), 17: (1, "codex.exe"),
                 18: (1, "cmd.exe"), 19: (18, "node.exe"), 20: (19, "codex.exe"), 21: (1, "cmd.exe"),
                 22: (1, "cmd.exe"), 23: (1, "cmd.exe"), 24: (1, "cmd.exe"), 25: (1, "cmd.exe"), 26: (1, "cmd.exe"),
                 27: (1, "cmd.exe"), 28: (1, "cmd.exe")}
        up = f"-c nouez_pane={server.pane_token(t)} -c check_for_update_on_startup=false"
        old = "-c check_for_update_on_startup=false"  # the options alone, as a user could type them
        lines = {10: f'cmd.exe /d /s /k "codex resume {t} {up}"', 11: f"C:\\x\\codex.exe resume {t}",
                 12: f"codex resume {t}", 13: f"codex resume {t}0",  # another id
                 14: "cmd /k", 15: f'"codex.exe" resume "{t}"', 16: f"x resume {t}",
                 17: f'codex exec "then run codex resume {t} please"',  # words in a prompt
                 # npm's shim: cmd -> node -> codex.exe, with quoted paths that have spaces
                 18: f'cmd /d /s /k ""C:\\Program Files\\nodejs\\codex.cmd" resume {t} {up} -c "projects={{\'c:\\a b\'=1}}""',
                 19: "node codex.js", 20: f"C:\\n\\codex.exe resume {t}",
                 21: f'cmd /k echo codex resume {t}', 22: f"cmd /c codex resume {t}",
                 # shells the user typed: no options, other options, or more commands after it
                 23: f"cmd /k codex resume {t}", 24: f'cmd /d /s /k "codex resume {t} --yolo"',
                 25: f'cmd /d /s /k "codex resume {t} {up} & del x"',
                 26: rf"cmd /k C:\c\codex.exe resume {t} {old}",  # typed, or a pane before the token
                 27: f'cmd /d /s /k "codex resume {t} {old} -c projects={{}}"',
                 28: f'cmd /d /s /k "codex resume {t} -c nouez_pane=p{"0" * 32} {old}"',  # a wrong token
                 # the last versions' panes: attached to the daemon, from a path with spaces
                 29: f'C:\\WINDOWS\\system32\\cmd.exe /d /s /k ""C:\\Program Files\\c\\codex.exe" resume {u} '
                     f'-c nouez_pane={server.pane_token(u)} --remote unix:// -c check_for_update_on_startup=false"'}
        table[29] = (1, "cmd.exe")
        self.assertEqual(server.old_panes(table, lines.get), {10: t, 18: t, 29: u})  # only panes nouez opened
        self.assertNotEqual(server.pane_token(t), server.pane_token(t[:-1] + "e"))
        self.assertIsNone(server.pane_thread(lines[10].replace(t, u)))  # another thread's token

    def test_pane_key_is_made_once(self):
        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(server, "nouez_cache_dir", return_value=tmp):
            server._pane_key = None
            first = server.pane_key()
            with open(os.path.join(tmp, "pane-key"), "rb") as f:
                self.assertEqual(f.read(), first)
            server._pane_key = None
            self.assertEqual(server.pane_key(), first)  # another server reads the same key
            with open(os.path.join(tmp, "pane-key"), "wb") as f:
                f.write(b"short")  # a key cut short: replaced, and every server reads the new one
            server._pane_key = None
            fixed = server.pane_key()
            with open(os.path.join(tmp, "pane-key"), "rb") as f:
                self.assertEqual(f.read(), fixed)
            self.assertEqual(len(fixed), 32)
            self.assertNotEqual(fixed, first)
            self.assertEqual(sorted(os.listdir(tmp)), ["pane-key", "pane-key.lock"])  # no temporary file left
            os.remove(os.path.join(tmp, "pane-key"))
            server._pane_key = None
            def first_wins(src, dst):
                with open(dst, "wb") as f:
                    f.write(b"z" * 32)
            real_open = server.os.open

            def first_wins_lock(path, *a):
                if path.endswith(".lock"):  # another server makes its key while this one waits
                    first_wins(None, os.path.join(tmp, "pane-key"))
                return real_open(path, *a)
            with mock.patch.object(server.os, "open", side_effect=first_wins_lock):
                won = server.pane_key()  # read again under the lock: the other server's key is used
            self.assertEqual(won, b"z" * 32)
            server._pane_key = None
            with mock.patch.object(server.os, "makedirs", side_effect=PermissionError("no")):
                own = server.pane_key()  # unusable cache: this server's own
            self.assertEqual(len(own), 32)

    def test_posix_cleanup_kills_only_tokened_panes(self):
        # 41: the terminal emulator running `-e codex resume ...`; 42: codex, from a path with a space.
        # 43: codex, but another session's. 44: a wrong token. 45: codex asked about a pane's command,
        # its words in one argument. 46: ended before it could be held.
        token = server.pane_token(self.TID)
        pane = ["/opt/Codex Tools/bin/codex", "resume", self.TID, "-c", f"nouez_pane={token}", "-c", "x=1"]
        argvs = {41: ["/usr/bin/x-terminal-emulator", "-e", *pane], 42: pane, 43: ["codex", "resume", "other"],
                 44: ["codex", "resume", self.TID, "-c", "nouez_pane=p" + "0" * 32],
                 45: ["codex", "exec", " ".join(pane)]}
        real_open, held, signalled, closed = open, {}, [], []

        def pidfd_open(pid):
            if pid not in argvs:
                raise ProcessLookupError(pid)
            held[100 + pid] = pid
            return 100 + pid

        def fake_open(path, *a, **k):
            m = re.fullmatch(r"/proc/(\d+)/cmdline", str(path))
            if not m:
                return real_open(path, *a, **k)
            return io.BytesIO(b"".join(arg.encode() + b"\0" for arg in argvs[int(m.group(1))]))
        with mock.patch.object(server.sys, "platform", "linux"), \
             mock.patch.object(server.os, "pidfd_open", pidfd_open, create=True), \
             mock.patch.object(server.os, "listdir", return_value=["41", "42", "43", "44", "45", "46", "self"]), \
             mock.patch.object(server.os, "close", side_effect=closed.append), \
             mock.patch.object(server.os, "name", "posix"), mock.patch("builtins.open", fake_open), \
             mock.patch.object(server.signal, "pidfd_send_signal", create=True,
                               side_effect=lambda fd, sig: signalled.append(held[fd])), \
             mock.patch.object(server.signal, "SIGTERM", 15):
            self.assertEqual(server.close_old_panes(), 1)
        self.assertEqual(signalled, [42])  # through the pidfd held while its arguments were read
        self.assertEqual(sorted(closed), [141, 142, 143, 144, 145])  # every pidfd closed
        self.assertEqual(server.pane_argv(pane), self.TID)
        self.assertIsNone(server.pane_argv(pane[:4]))
        self.assertIsNone(server.pane_argv(["codex", "resume", self.TID, "-c", f"nouez_pane={token}\u00e9"]))
        with mock.patch.object(server.os, "name", "posix"), mock.patch.object(server.sys, "platform", "darwin"), \
             mock.patch.object(server.os, "listdir") as listdir:
            self.assertEqual(server.close_old_panes(), 0)  # macOS: no handle that outlasts a pid, so none
        listdir.assert_not_called()

    def test_only_the_viewer_counts(self):
        # A pane's shell is ended only while nothing but the viewer and its console runs in it.
        t, token = self.TID, server.pane_token(self.TID)
        self.assertTrue(server.is_viewer(f'"C:\\x\\codex.exe" resume {t} -c nouez_pane={token} --remote unix://', t))
        self.assertTrue(server.is_viewer(
            f'"C:\\n\\node.exe" "C:\\npm\\codex\\bin\\codex.js" resume {t} -c nouez_pane={token}', t))
        for line in (f"codex resume {t}", f"node other.js resume {t} -c nouez_pane={token}",
                     f"codex resume {t} -c nouez_pane={server.pane_token(t[:-1] + 'e')}", "python app.py", None):
            self.assertFalse(server.is_viewer(line, t), line)

    def test_windows_arguments(self):
        split = server.split_windows_args
        self.assertEqual(split(r'"C:\Program Files\c.exe" resume  id -c "a b\\" x\"y'),
                         [r"C:\Program Files\c.exe", "resume", "id", "-c", "a b\\", 'x"y'])
        self.assertEqual(split('a "" b'), ["a", "", "b"])
        self.assertEqual(server.shell_command('cmd /d /s /k ""C:\\a b\\c.exe" r "x y""'), '"C:\\a b\\c.exe" r "x y"')
        self.assertEqual(server.shell_command("C:\\WINDOWS\\system32\\cmd.exe /K codex resume x"), "codex resume x")
        self.assertIsNone(server.shell_command("cmd /c codex resume x"))

    @unittest.skipUnless(os.name == "nt", "Windows process list")
    def test_command_line_and_end_tree(self):
        sleep = [sys.executable, "-c", "import time; time.sleep(60)"]
        older = subprocess.Popen(sleep)  # started before the root: never its child
        self.addCleanup(older.wait)
        self.addCleanup(older.kill)
        time.sleep(0.05)
        proc = subprocess.Popen([sys.executable, "-c", "import subprocess, sys, time; "
                                 "subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)']); time.sleep(60)",
                                 "resume", self.TID])
        self.addCleanup(proc.wait)
        self.addCleanup(proc.kill)
        line = server.process_command_line(proc.pid)
        self.assertTrue(line.endswith(f"resume {self.TID}"), line)
        self.assertIsNone(server.process_command_line(0))
        deadline = time.time() + 10
        while time.time() < deadline:
            table = server.process_table()
            kids = [p for p, (parent, _) in table.items() if parent == proc.pid]
            if kids:
                break
            time.sleep(0.1)
        self.assertTrue(kids)
        real_open = server.open_process
        handle = server.open_process(proc.pid, server.QUERY | server.SYNCHRONIZE | server.TERMINATE)
        self.addCleanup(server.close_handle, handle)
        self.assertTrue(server.process_command_line(handle=handle).endswith(f"resume {self.TID}"))
        # Only this test's own processes are in reach. One that started before the root isn't
        # its child; one that started after it but has another parent (a pid reused since the
        # snapshot) is caught by the second snapshot.
        newer = subprocess.Popen(sleep)
        self.addCleanup(newer.wait)
        self.addCleanup(newer.kill)
        table[older.pid] = table[newer.pid] = (proc.pid, "python.exe")
        reach = {proc.pid, *kids, older.pid, newer.pid}
        refused = []
        with mock.patch.object(server, "open_process",
                               side_effect=lambda pid, *a: real_open(pid, *a) if pid in reach else None):
            # Something besides the viewer runs in it: nothing is ended.
            self.assertFalse(server.end_tree(handle, proc.pid, table, allowed=lambda h, exe: refused.append(exe)))
            self.assertTrue(refused)
            # A process the first snapshot didn't name, started in it since: nothing is ended either.
            started = lambda: {**server.process_table(), 4: (proc.pid, "cmd.exe")}
            self.assertFalse(server.end_tree(handle, proc.pid, table, snapshot=started, allowed=lambda h, exe: True))
            # A second snapshot that failed checks nothing: nothing is ended.
            self.assertFalse(server.end_tree(handle, proc.pid, table, snapshot=dict, allowed=lambda h, exe: True))
            self.assertEqual(server.process_table().get(kids[0], (None,))[0], proc.pid)
            self.assertTrue(server.end_tree(handle, proc.pid, table))
        time.sleep(0.5)
        self.assertNotEqual(server.process_table().get(kids[0], (None,))[0], proc.pid)  # its pid may be reused
        self.assertIsNone(older.poll())
        self.assertIsNone(newer.poll())
        self.assertIsNone(proc.poll())  # end_tree leaves the root itself to its caller

    @unittest.skipUnless(os.name == "nt", "Windows process handles")
    def test_exit_code_259_is_an_end(self):
        proc = subprocess.Popen([sys.executable, "-c", "import sys; sys.exit(259)"])
        proc.wait(timeout=30)
        handle = server.open_process(proc.pid, server.QUERY | server.SYNCHRONIZE)
        self.addCleanup(server.close_handle, handle)
        self.assertTrue(server.handle_exited(handle))
        self.assertIsNone(server.handle_start(handle))
        bare = server.open_process(proc.pid)  # no SYNCHRONIZE: 259 can't be told from running
        self.addCleanup(server.close_handle, bare)
        self.assertIsNone(server.handle_exited(bare))


class TopReloadTest(unittest.TestCase):
    """0.16.0: the status screen starts again on an updated server.py."""

    def test_reload_waits_for_a_finished_file_that_compiles(self):
        folder = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, folder, True)
        path = os.path.join(folder, "server.py")

        def write(text, ns):
            with open(path, "w", encoding="utf-8") as f:
                f.write(text)
            os.utime(path, ns=(ns, ns))
        write("x = 1\n", 10**18)
        started = seen = server.source_stamp(path)
        self.assertEqual(server.top_reload_due(path, started, seen), (False, started))  # unchanged
        write("x = 22\n", 2 * 10**18)
        due, seen = server.top_reload_due(path, started, seen)
        self.assertFalse(due)  # changed: waits one round in case it is still being written
        write("def broken(:\n", 3 * 10**18)
        due, seen = server.top_reload_due(path, started, seen)
        due, seen = server.top_reload_due(path, started, seen)
        self.assertFalse(due)  # stable but doesn't compile: keep the screen running
        for cut in ("", "x = 1\n\ndef run_top(argv):\n    return 0\n"):  # empty, or cut short: compiles
            write(cut, 4 * 10**18 + len(cut))
            due, seen = server.top_reload_due(path, started, seen)
            due, seen = server.top_reload_due(path, started, seen)
            self.assertFalse(due, repr(cut))
        write('x = 1\n\ndef run_top(argv):\n    return 0\n\nif __name__ == "__main__":\n    pass\n', 5 * 10**18)
        due, seen = server.top_reload_due(path, started, seen)
        self.assertFalse(due)
        self.assertTrue(server.top_reload_due(path, started, seen)[0])
        os.remove(path)
        self.assertFalse(server.top_reload_due(path, started, seen)[0])

    def test_period_is_kept_whole(self):
        # The longest period is the most a restart can carry; a longer one is refused, not cut.
        seen = []
        with mock.patch.object(server, "read_scan_state", return_value={}), \
             mock.patch.object(server, "scan_usage"), mock.patch.object(server, "write_json_atomic"), \
             mock.patch.object(server, "read_codex_usage"), mock.patch.object(server, "read_agy_usage"), \
             mock.patch.object(server, "read_usage_log", return_value=[]), \
             mock.patch.object(server, "top_frame", side_effect=lambda scr, now, days, *a: seen.append(days) or []), \
             mock.patch("builtins.print"):
            for asked in ("65535", "30"):
                self.assertEqual(server.run_top(["--once", "--days", asked]), 0)
            for bad in (["--days", "70000"], ["--days", "-1"], ["--since", "1"], ["--since", "a:b"],
                        ["--page", "consultations"], ["--page", "x"]):
                self.assertEqual(server.run_top(["--once", *bad]), 2, bad)
        self.assertEqual(seen, [0xFFFF, 30])

    def test_screen_tells_its_supervisor(self):
        # q ends the window; an update restarts it, with the period the screen had then.
        root = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, root, True)

        def screen(keys, due, argv=("--screen", "--supervised", "--days", "7")):
            keys, due = iter(keys), iter(due)
            with mock.patch.object(server, "read_scan_state", return_value={}), \
                 mock.patch.object(server, "nouez_cache_dir", lambda: root), \
                 mock.patch.object(server.ConsultationFeed, "run"), \
                 mock.patch.object(server, "scan_usage"), mock.patch.object(server, "write_json_atomic"), \
                 mock.patch.object(server, "read_codex_usage"), mock.patch.object(server, "read_agy_usage"), \
                 mock.patch.object(server, "read_usage_log", return_value=[]), \
                 mock.patch.object(server, "top_frame", return_value=[]), \
                 mock.patch.object(server, "enable_ansi", return_value=False), \
                 mock.patch.object(server, "read_key", side_effect=lambda t, wake=None: next(keys)), \
                 mock.patch.object(server, "top_reload_due", side_effect=lambda *a: (next(due), (1, 1))), \
                 mock.patch.object(server.sys.stdin, "isatty", return_value=False), \
                 mock.patch.object(server.sys, "stdout", io.StringIO()):
                return server.run_top(list(argv))
        self.assertEqual(screen(["q"], [False]), server.TOP_QUIT)
        self.assertEqual(screen([None], [False, True]), server.TOP_RELOAD)  # period unchanged
        periods = list(server.TOP_PERIODS.values())
        self.assertEqual(screen(["a"], [False, True]), server.TOP_RELOAD + 1 + periods.index(None))
        self.assertEqual(screen(["3"], [False, True]), server.TOP_RELOAD + 1 + periods.index(30))
        self.assertEqual(screen(["c"], [False, True]), server.reload_code(7, "consultations", 7))
        self.assertLess(server.reload_code(None, server.TOP_PAGES[-1], 7), 128)  # an exit code any system keeps
        # A screen started by 0.22.0's supervisor, which knows only the usage page's codes up to 75:
        old = ("--screen", "--days", "7")
        self.assertEqual(screen(["c"], [False, True], old), server.TOP_RELOAD)
        self.assertEqual(screen(["3"], [False, True], old), server.TOP_RELOAD + 1 + periods.index(30))
        with mock.patch.object(server, "nouez_cache_dir", lambda: root), \
             mock.patch.object(server, "supervise_top", return_value=0) as sup:
            self.assertEqual(server.run_top(["--days", "7"]), 0)  # on every system
            sup.assert_called_once_with(["--days", "7"])
            holder = server.hold_status_screen()
            try:
                with mock.patch.object(server, "show_status_window", return_value=False), \
                     mock.patch("builtins.print") as said:
                    self.assertEqual(server.run_top(["--days", "30", "--page", "consultations"]), 0)
            finally:
                server.release_status_screen(holder)
            sup.assert_called_once()  # no second screen
            self.assertIn("already open", said.call_args[0][0])
        command = server.cache_json(os.path.join(root, "status-command.json"))
        self.assertEqual((command["page"], command["days"]), ("consultations", 30))

    def test_failed_update_keeps_the_window(self):
        for failed in (1, 0):  # a crash, or a file cut short that does nothing and exits cleanly
            self.window_waits(failed)

    def window_waits(self, failed):
        codes = [server.TOP_RELOAD, failed, server.TOP_QUIT]  # reloaded, the new file fails, the next one runs

        class Child:
            def __init__(self, argv):
                pass

            def wait(self):
                return codes.pop(0)
        due = iter([(False, (1, 1)), (True, (2, 2))])
        with mock.patch.object(server.subprocess, "Popen", Child), \
             mock.patch.object(server.time, "sleep"), \
             mock.patch.object(server, "top_reload_due", side_effect=lambda *a: next(due)), \
             mock.patch("builtins.print") as said:
            self.assertEqual(server.supervise_top([]), 0)
        self.assertIn(f"ended with code {failed}", said.call_args[0][0])
        self.assertEqual(codes, [])

    def test_ctrl_c_closes_the_window(self):
        # Ctrl+C reaching the supervisor means quit, whatever code the screen then ends with
        # (it may not have reached its own quit handler yet).
        class Child:
            def __init__(self, argv):
                self.calls = 0

            def wait(self, timeout=None):
                self.calls += 1
                if self.calls == 1:
                    raise KeyboardInterrupt
                return 1
        with mock.patch.object(server.subprocess, "Popen", Child):
            self.assertEqual(server.supervise_top([]), 0)

        class Deaf(Child):  # an interrupt sent to the supervisor alone: the screen is ended for it
            ended = []

            def wait(self, timeout=None):
                if timeout is None:
                    if not self.ended:
                        raise KeyboardInterrupt
                    return -15
                if not self.ended:
                    raise server.subprocess.TimeoutExpired("screen", timeout)
                return -15

            def poll(self):
                return None if not self.ended else -15

            def terminate(self):
                self.ended.append("terminate")
        with mock.patch.object(server.subprocess, "Popen", Deaf):
            self.assertEqual(server.supervise_top([]), 0)
        self.assertEqual(Deaf.ended, ["terminate"])

    def test_ending_top_ends_the_screen(self):
        # Elsewhere than Windows, SIGTERM or SIGHUP to the supervisor ends the screen first.
        handlers, ended = {}, []

        class Child:
            def __init__(self, argv):
                pass

            def poll(self):
                return None

            def terminate(self):
                ended.append("terminate")

            def wait(self, timeout=None):
                if timeout is None:
                    handlers[server.signal.SIGTERM](server.signal.SIGTERM, None)
                ended.append("reaped")
                return 0
        with mock.patch.object(server.os, "name", "posix"), \
             mock.patch.object(server.signal, "SIGHUP", 1, create=True), \
             mock.patch.object(server.signal, "signal", side_effect=lambda n, h: handlers.__setitem__(n, h)), \
             mock.patch.object(server.subprocess, "Popen", Child):
            self.assertEqual(server.supervise_top([]), 128 + server.signal.SIGTERM)
        self.assertEqual(ended, ["terminate", "reaped"])  # reaped outside the interrupted wait
        self.assertEqual(set(handlers), {server.signal.SIGTERM, 1})

        class Starting(Child):  # the signal comes while the screen is being started
            def __init__(self, argv):
                handlers[1](1, None)

            def wait(self, timeout=None):
                ended.append("reaped")
                return 0
        ended.clear()
        with mock.patch.object(server.os, "name", "posix"), \
             mock.patch.object(server.signal, "SIGHUP", 1, create=True), \
             mock.patch.object(server.signal, "signal", side_effect=lambda n, h: handlers.__setitem__(n, h)), \
             mock.patch.object(server.subprocess, "Popen", Starting):
            self.assertEqual(server.supervise_top([]), 128 + 1)
        self.assertEqual(ended, ["terminate", "reaped"])

    def test_failed_update_watches_from_what_it_ran(self):
        # A fix written between the failed screen's start and its failure is due at once: the
        # window compares with the version the screen was started on, not the file at failure.
        codes, argvs, calls = [server.TOP_RELOAD, 1, server.TOP_QUIT], [], []

        class Child:
            def __init__(self, argv):
                argvs.append(argv)

            def wait(self):
                return codes.pop(0)
        stamps = iter([(1, 1), (2, 2), (3, 3)])
        with mock.patch.object(server.subprocess, "Popen", Child), \
             mock.patch.object(server.time, "sleep"), \
             mock.patch.object(server, "source_stamp", side_effect=lambda p: next(stamps)), \
             mock.patch.object(server, "top_reload_due", side_effect=lambda *a: calls.append(a) or (True, (4, 4))), \
             mock.patch("builtins.print"):
            self.assertEqual(server.supervise_top([]), 0)
        self.assertEqual([a[a.index("--since") + 1] for a in argvs], ["1:1", "2:2", "3:3"])
        self.assertEqual(calls[0][1:], ((2, 2), (2, 2)))

    def test_supervisor_restarts_with_the_period(self):
        periods = list(server.TOP_PERIODS.values())
        codes = [server.TOP_RELOAD + 1 + periods.index(30), server.TOP_RELOAD + 1 + periods.index(None),
                 server.TOP_RELOAD, server.TOP_QUIT]
        argvs = []

        class Child:
            def __init__(self, argv):
                argvs.append(argv)

            def wait(self):
                return codes.pop(0)
        with mock.patch.object(server.subprocess, "Popen", Child):
            self.assertEqual(server.supervise_top(["--days", "7"]), 0)
        self.assertEqual([server.top_args(a[a.index("top") + 1:]) for a in argvs],
                         [["--days", "7"], ["--days", "30"], ["--days", "0"], ["--days", "0"]])
        self.assertTrue(all("--screen" in a and "--since" in a for a in argvs))
        self.assertTrue(all(a[0] == sys.executable for a in argvs))
        codes[:] = [3]
        with mock.patch.object(server.subprocess, "Popen", Child):
            self.assertEqual(server.supervise_top([]), 3)  # a crash ends it with the screen's code
        codes[:] = [2]
        with mock.patch.object(server.subprocess, "Popen", Child):
            self.assertEqual(server.supervise_top(["--days", "x"]), 2)  # so does a usage error


class RoundTwoFixesTest(unittest.TestCase):
    def test_codex_version_needs_a_codex_it_can_find(self):
        """0.18.0: no bare `codex`, which could run one in the project folder."""
        with mock.patch.object(server, "which", return_value=None):
            self.assertIsNone(server.codex_version("codex"))

    def test_usage_log_skips_a_window_that_has_reset(self):
        """0.18.0: the log records only windows that haven't reset, as the budget shows them."""
        root = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, root, True)
        now = time.time()
        with open(os.path.join(root, server.CLAUDE_USAGE_FILE), "w", encoding="utf-8") as f:
            json.dump({"rate_limits": {"five_hour": {"used_percentage": 100, "resets_at": now - 60},
                                       "seven_day": {"used_percentage": 40, "resets_at": now + 9000}}}, f)
        client = mock.Mock(request=mock.Mock(side_effect=server.BridgeError("down")))
        with mock.patch.object(server, "nouez_cache_dir", lambda: root):
            snap = server.usage_snapshot(client)
        self.assertEqual(snap["usage"].get("claude"), {server.window_label(7 * 86400): 40})

    def test_usage_log_judges_resets_after_the_daemon_answers(self):
        """0.26.4: a Claude window that resets while the daemon answers is left out."""
        root = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, root, True)
        with open(os.path.join(root, server.CLAUDE_USAGE_FILE), "w", encoding="utf-8") as f:
            json.dump({"rate_limits": {"seven_day": {"used_percentage": 98, "resets_at": 101}}}, f)
        clock = [100.0]

        def request(method, params):
            clock[0] = 102.0  # the answer comes after the reset
            return {"rateLimits": {"primary": {"usedPercent": 12, "windowDurationMins": 10080, "resetsAt": 101.5},
                                   "secondary": {"usedPercent": 30, "windowDurationMins": 300, "resetsAt": 500}}}
        with mock.patch.object(server, "nouez_cache_dir", lambda: root),                 mock.patch.object(server.time, "time", lambda: clock[0]):
            snap = server.usage_snapshot(mock.Mock(request=request))
        five = server.window_label(300 * 60)
        self.assertEqual(snap, {"usage": {"codex": {five: 30}},
                                "usage_meta": {"codex": {five: {"resets_at": 500, "sampled": 102.0}}}})


class SignInTest(unittest.TestCase):
    """0.19.0: Claude Code's sign-in end, from `claude auth status --text`, warned of a week ahead."""

    LINE = "Sign-in ends: between 2026-12-05 and 2026-12-08 (2026-12-08T20:59:30.320Z)"

    def setUp(self):
        self.cache = tempfile.mkdtemp(prefix="nouez-test-login-")
        self.addCleanup(shutil.rmtree, self.cache, True)
        for patch in (mock.patch.object(server, "nouez_cache_dir", return_value=self.cache),
                      mock.patch.object(server, "credentials_stamp", return_value=None),
                      mock.patch.dict(os.environ, {"NOUEZ_NO_LOGIN_CHECK": ""}),
                      mock.patch.object(server, "_login_next", 0.0), mock.patch.object(server, "_login_memo", None),
                      mock.patch.object(server, "_login_checking", False)):
            patch.start()
            self.addCleanup(patch.stop)
        server._login_idle.set()

    def save(self, checked, line=LINE, context=None):
        found = server.parse_login_line(line) or {}
        server.write_json_atomic(os.path.join(self.cache, server.LOGIN_CACHE_FILE),
                                 {"checked": checked, "credentials": None,
                                  "context": context or server.login_context(), **found})
        return found

    def settle(self):
        for _ in range(100):
            if not server._login_checking:
                break
            time.sleep(0.05)

    def test_the_line_is_read_and_the_rest_dropped(self):
        found = server.parse_login_line("Login method: Claude Max account\nEmail: a@b.c\n" + self.LINE + "\n")
        self.assertEqual(found["line"], self.LINE)
        end = server.iso_seconds("2026-12-08T20:59:30.320Z")
        self.assertEqual(found["last"], end)
        self.assertEqual(found["first"], end - 3 * 86400)  # the earlier date is 3 days before the end
        self.assertIsNone(server.parse_login_line("Login method: API key\n"))
        odd = server.parse_login_line("Sign-in ends: any day now")
        self.assertEqual((odd["first"], odd["last"]), (None, None))

    def test_each_form_claude_code_prints(self):
        end = server.iso_seconds("2026-12-08T20:59:30.320Z")
        soon = server.parse_login_line("Sign-in ends: any day now, by 2026-12-08 (2026-12-08T20:59:30.320Z)")
        self.assertEqual((soon["first"], soon["last"]), (end - 3 * 86400, end))
        gone = server.parse_login_line("Sign-in may have ended: between 2026-12-05 and 2026-12-08 (2026-12-08T20:59:30.320Z)")
        self.assertIn("has ended", server.login_warning(end + 1, gone))
        # Without the exact end, the later date counts to its end, not its start.
        bare = server.parse_login_line("Sign-in ends: between 2026-12-05 and 2026-12-08")
        self.assertEqual(bare["last"], time.mktime((2026, 12, 9, 0, 0, 0, 0, 0, -1)))
        self.assertEqual(bare["first"], time.mktime((2026, 12, 5, 0, 0, 0, 0, 0, -1)))
        self.assertEqual(server.parse_login_line("Sign-in ends: \x1b[31mred")["line"], "Sign-in ends: [31mred")

    def test_days_are_calendar_days_and_the_seventh_counts(self):
        state = server.parse_login_line("Sign-in ends: between 2026-12-05 and 2026-12-08")
        week_before = time.mktime((2026, 11, 28, 0, 0, 0, 0, 0, -1))
        self.assertEqual(server.login_days(state, week_before), 7)
        self.assertIn("in 7 days", server.login_warning(week_before, state))
        self.assertEqual(server.login_warning(week_before - 1, state), "")
        self.assertEqual(server.login_days(state, time.mktime((2026, 12, 4, 23, 59, 0, 0, 0, -1))), 1)

    def test_warned_only_within_a_week_of_the_earlier_date(self):
        found = self.save(time.time())
        first = found["first"]
        with mock.patch.object(server, "check_login"):
            self.assertEqual(server.login_warning(first - 8 * 86400), "")
            soon = server.login_warning(first - 3 * 86400 + 60)
            self.assertIn("in 3 days", soon)
            self.assertIn("renew before", soon)
            self.assertIn("claude auth login", soon)
            self.assertIn("today", server.login_warning(first - 60))
            self.assertIn("may already have ended", server.login_warning(first + 60))
            self.assertIn("may already have ended", server.login_warning(first + 86400 + 60))
            self.assertIn("has ended", server.login_warning(found["last"] + 1))

    def test_an_old_reading_is_read_again_in_the_background(self):
        self.save(time.time() - server.LOGIN_CHECK_SECONDS - 1)
        with mock.patch.object(server, "read_login_line", return_value={"line": "Sign-in ends: later", "first": None,
                                                                        "last": None}):
            server.login_state()
            self.settle()
            self.assertEqual(server.login_state()["line"], "Sign-in ends: later")

    def test_a_new_sign_in_is_noticed(self):
        self.save(time.time())
        with mock.patch.object(server, "credentials_stamp", return_value=12345.0), \
                mock.patch.object(server, "read_login_line", return_value={}) as read:
            server.login_state(wait=True)
        read.assert_called_once()

    def test_the_top_bar_keeps_the_sign_in_badge_whole(self):
        found = self.save(time.time())
        now = found["first"] - 12 * 86400
        when = time.strftime("%b %d", time.localtime(found["first"])).replace(" 0", " ")
        busy = {"rank": 3, "used": 95.0, "colour": "31"}
        groups = [{"title": t, "entries": [(sub, "5-hour", busy)]}
                  for t, sub in (("Codex", None), ("Claude Code", None), ("Antigravity", "Claude+GPT"))]
        scr = server.Screen(False)
        with mock.patch.object(server, "check_login"):
            for width in (60, 100, 104, 200):
                line = server.top_bar(scr, groups, 7, now, width)
                self.assertIn(f"● sign-in {when}, 12d", line, (width, line))
                self.assertLessEqual(server.visible(line), width, (width, line))

    def test_off_with_the_switch(self):
        self.save(time.time())
        with mock.patch.dict(os.environ, {"NOUEZ_NO_LOGIN_CHECK": "1"}):
            self.assertIsNone(server.login_state())
            self.assertEqual(server.with_login_warning("list"), "list")

    def test_badge_and_budget_lines(self):
        found = self.save(time.time())
        first = found["first"]
        scr = mock.Mock(paint=lambda text, colour: f"<{colour}>{text}")
        with mock.patch.object(server, "check_login"):
            when = time.strftime("%b %d", time.localtime(first)).replace(" 0", " ")
            day_start = time.mktime(time.localtime(first)[:3] + (0, 0, 1, 0, 0, -1))
            if day_start < first:  # the renewal day, before its exact moment: "today", as the warning says
                self.assertEqual(server.login_badge(scr, day_start), f"<31>● sign-in {when}, today")
            self.assertEqual(server.login_badge(scr, first - 8 * 86400), f"<90>● sign-in {when}, 8d")
            self.assertEqual(server.login_badge(scr, first - 3 * 86400 + 60), f"<33>● sign-in {when}, 3d")
            self.assertEqual(server.login_badge(scr, first - 86400), f"<31>● sign-in {when}, 1d")
            self.assertEqual(server.login_badge(scr, found["last"] + 1), "<31>● sign-in ended")
            self.assertEqual(server.login_badge(scr, first + 3600), "<31>● sign-in ending")
            self.assertEqual(server.login_lines(first - 8 * 86400), ["  - " + self.LINE])
            lines = server.login_lines(first - 86400 + 60)
            self.assertEqual(lines[0], "  - " + self.LINE)
            self.assertIn("ends soon", lines[1])

    def test_another_sign_ins_reading_is_not_used(self):
        self.save(time.time(), context={"config": "elsewhere", "env": []})
        with mock.patch.object(server, "check_login") as check:
            self.assertIsNone(server.login_state())
        check.assert_called_once()
        with mock.patch.dict(os.environ, {"ANTHROPIC_API_KEY": "sk-test"}):
            self.assertEqual(server.login_context()["env"], ["ANTHROPIC_API_KEY"])
            self.assertNotIn("sk-test", json.dumps(server.login_context()))

    def test_waits_for_a_reading_under_way(self):
        self.save(time.time() - server.LOGIN_CHECK_SECONDS - 1)
        server._login_checking = True
        server._login_idle.clear()
        self.addCleanup(server._login_idle.set)

        def finish():
            time.sleep(0.2)
            self.save(time.time(), line="Sign-in ends: fresh")
            server._login_checking = False
            server._login_idle.set()
        threading.Thread(target=finish).start()
        self.assertEqual(server.login_state(wait=True)["line"], "Sign-in ends: fresh")

    def test_a_reading_that_cant_be_saved_isnt_repeated_at_once(self):
        with mock.patch.object(server, "write_json_atomic", side_effect=OSError("disk full")), \
                mock.patch.object(server, "read_login_line", return_value={"line": "Sign-in ends: x"}) as read:
            first = server.login_state(wait=True)
            server.login_state(wait=True)
        read.assert_called_once()
        self.assertEqual(first["line"], "Sign-in ends: x")  # this process keeps its own reading

    def test_a_save_that_returns_false_counts_as_not_saved(self):
        self.save(time.time() - server.LOGIN_CHECK_SECONDS - 1, line="Sign-in ends: old")
        with mock.patch.object(server, "write_json_atomic", return_value=False), \
                mock.patch.object(server, "read_login_line", return_value={"line": "Sign-in ends: fresh"}) as read:
            first = server.login_state(wait=True)
            server.login_state(wait=True)
        read.assert_called_once()  # not read again at once, though the file still holds the old one
        self.assertEqual(first["line"], "Sign-in ends: fresh")  # the newer reading, not the stale file
        self.assertGreater(server._login_next, time.time() + 60)

    def test_the_reading_runs_in_the_home_folder(self):
        with mock.patch.object(server, "find_program", return_value="claude"), \
                mock.patch.object(server.subprocess, "run",
                                  return_value=mock.Mock(stdout="Sign-in ends: x")) as run:
            server.read_login_line()
        self.assertEqual(run.call_args.kwargs["cwd"], os.path.expanduser("~"))

    def test_one_reading_per_request(self):
        self.save(time.time() - server.LOGIN_CHECK_SECONDS - 1)
        with mock.patch.object(server, "read_login_line", return_value={"line": self.LINE}) as read:
            server.login_lines(time.time())
        read.assert_called_once()

    def test_tools_carry_the_warning(self):
        with mock.patch.object(server, "login_warning", return_value="Claude Code's sign-in ends soon."), \
                mock.patch.object(server, "claude_sessions", return_value=[]):
            self.assertIn("ends soon", server.list_claude_sessions({}))


class ConfigReportTest(unittest.TestCase):
    """0.19.0: what an untrusted folder's project settings would run, read before the user is asked."""

    def folder(self, settings=None, local=None, mcp=None):
        d = tempfile.mkdtemp(prefix="nouez-test-config-")
        self.addCleanup(shutil.rmtree, d, True)
        os.mkdir(os.path.join(d, ".claude"))
        for rel, value in ((os.path.join(".claude", "settings.json"), settings),
                           (os.path.join(".claude", "settings.local.json"), local), (".mcp.json", mcp)):
            if value is not None:
                with open(os.path.join(d, rel), "w", encoding="utf-8") as f:
                    f.write(value if isinstance(value, str) else json.dumps(value))
        return d

    def test_everything_that_runs_is_listed(self):
        d = self.folder(settings={"hooks": {"SessionStart": [{"hooks": [{"type": "command", "command": "sh go.sh"}]}]},
                                  "statusLine": {"type": "command", "command": "status.sh"},
                                  "apiKeyHelper": "key.sh", "env": {"PATH": "secret-ish"},
                                  "permissions": {"allow": ["Bash(*)"], "defaultMode": "bypassPermissions"},
                                  "enableAllProjectMcpServers": True, "brandNewKey": 1, "model": "opus"},
                        mcp={"mcpServers": {"tools": {"command": "node", "args": ["srv.js"]}}})
        report = server.config_review([d])[0]
        for part in ("SessionStart: sh go.sh", "statusLine runs: status.sh", "apiKeyHelper runs: key.sh",
                     "env sets (1, values not shown): PATH", "pre-approves: Bash(*)", "bypassPermissions",
                     "enableAllProjectMcpServers", "other settings: brandNewKey", "tools: runs node srv.js"):
            self.assertIn(part, report)
        self.assertNotIn("secret-ish", report)
        self.assertNotIn("model", report)

    def test_permission_rules_are_masked(self):
        """0.22.0: a credential in a permission rule is shown as ***, like one in a command."""
        d = self.folder(settings={"permissions": {"allow": ['Bash(curl -H "Authorization: Bearer abc123" https://x)',
                                                            "Read(./src/**)"],
                                                  "deny": ["Bash(deploy --token=zz9)"],
                                                  "ask": "WebFetch(https://u:pw77@intranet/)"}})
        report = server.config_review([d])[0]
        for secret in ("abc123", "zz9", "pw77"):
            self.assertNotIn(secret, report)
        self.assertIn("Bearer ***", report)
        self.assertIn("Read(./src/**)", report)

    def test_header_secrets_without_a_space_and_unknown_fields_are_masked(self):
        """0.22.0: X-API-Key:value is masked, and so is a secret in a permissions field nouez doesn't know."""
        d = self.folder(settings={"permissions": {"allow": ["Bash(curl -H X-API-Key:EXAMPLE1 https://x)"],
                                                  "brandNew": ["Authorization: Bearer EXAMPLE2"]}})
        report = server.config_review([d])[0]
        for secret in ("EXAMPLE1", "EXAMPLE2"):
            self.assertNotIn(secret, report)
        self.assertIn("brandNew", report)
        d = self.folder(settings={"permissions": "Authorization: Bearer EXAMPLE3"})
        self.assertNotIn("EXAMPLE3", server.config_review([d])[0])
        d = self.folder(settings={"hooks": {"Stop": [{"hooks": [{"type": "prompt", "prompt": "use token=EXAMPLE4"},
                                                                 "Authorization: Bearer EXAMPLE5"]}]}})
        report = server.config_review([d])[0]
        for secret in ("EXAMPLE4", "EXAMPLE5"):
            self.assertNotIn(secret, report)
        self.assertIn("prompt prompt: use token=***", report)

    def test_a_file_changed_while_read_is_unreadable(self):
        """0.22.0: when the path no longer names the file nouez opened, what was read isn't used."""
        d = self.folder(settings={"hooks": {}})
        path = os.path.join(d, ".claude", "settings.json")
        real = os.lstat

        def swapped(p, *a, **k):
            st = real(p, *a, **k)
            if os.path.normcase(os.path.abspath(p)) != os.path.normcase(os.path.abspath(path)):
                return st
            fields = list(st)
            fields[stat_ino] += 1
            return os.stat_result(fields)
        stat_ino = 1
        with mock.patch.object(server.os, "lstat", side_effect=swapped):
            state, data = server.read_config_file(path)
        self.assertEqual((state, data), ("unreadable: it changed while nouez read it", None))
        self.assertIsNotNone(server.read_config_file(path)[1])

    def test_linked_settings_are_not_read(self):
        """0.22.0: a settings folder or file that is a link isn't followed, and blocks trust from here."""
        outside = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, outside, True)
        with open(os.path.join(outside, "settings.json"), "w") as f:
            json.dump({"hooks": {"SessionStart": [{"hooks": [{"type": "command", "command": "sh hidden.sh"}]}]}}, f)
        d = tempfile.mkdtemp(prefix="nouez-test-config-")
        self.addCleanup(shutil.rmtree, d, True)
        dir_link(outside, os.path.join(d, ".claude"))
        report, _, complete = server.config_review([d])
        self.assertIn("is a link, which nouez doesn't follow", report)
        self.assertNotIn("hidden.sh", report)
        self.assertFalse(complete)
        d2 = self.folder()
        file_link(self, os.path.join(outside, "settings.json"), os.path.join(d2, ".mcp.json"))
        report, _, complete = server.config_review([d2])
        self.assertIn("is a link", report)
        self.assertFalse(complete)

    def test_an_unreadable_file_is_never_none(self):
        report, _, complete = server.config_review([self.folder(local="{broken")])
        self.assertIn("couldn't be read", report)
        self.assertNotIn("No project settings", report)
        self.assertFalse(complete)
        d = self.folder()
        os.mkdir(os.path.join(d, ".mcp.json"))  # not a file
        report, _, complete = server.config_review([d])
        self.assertIn(".mcp.json: couldn't be read", report)
        self.assertFalse(complete)

    @unittest.skipUnless(hasattr(os, "mkfifo"), "named pipes")
    def test_a_pipe_is_not_waited_on(self):
        d = self.folder()
        os.mkfifo(os.path.join(d, ".mcp.json"))
        report, _, complete = server.config_review([d])
        self.assertIn("not a regular file", report)
        self.assertFalse(complete)

    def test_details_that_matter_are_shown_and_secrets_hidden(self):
        d = self.folder(settings={"hooks": {"PreToolUse": [{"matcher": "Bash", "hooks": [
                                      {"type": "command", "command": "check.sh --token abc123"}]}]},
                                  "enabledPlugins": {"good@market": True, "bad@market": False},
                                  "extraKnownMarketplaces": {"market": {"source": {"source": "github", "repo": "o/r"}}},
                                  "apiKeyHelper": "echo \x1b]8;;evil\u202e"},
                        mcp={"mcpServers": {"db": {"command": "npx", "args": ["db", "--api-key", "sk-live-1"],
                                                   "env": {"DB_PASSWORD": "hunter2"}},
                                            "web": {"type": "http", "url": "https://u:pw@x.test/mcp?key=k1",
                                                    "headers": {"Authorization": "Bearer t"}}}})
        report = server.config_review([d])[0]
        for part in ("PreToolUse [Bash]: check.sh --token ***", "good@market (on)", "bad@market (off)",
                     "market from", "o/r", "db: runs npx db --api-key ***", "env DB_PASSWORD (values not shown)",
                     "web: http https://***@x.test/mcp?key=***", "headers Authorization", "\\u001b", "\\u202e",
                     "shown as ***"):
            self.assertIn(part, report)
        for secret in ("abc123", "sk-live-1", "hunter2", "pw@", "k1", "Bearer", "\x1b", "\u202e"):
            self.assertNotIn(secret, report)

    def test_a_long_report_says_it_is_a_summary(self):
        d = self.folder(settings={"permissions": {"allow": [f"Bash(cmd{i})" for i in range(30)]}})
        report = server.config_review([d])[0]
        self.assertIn("and 10 more", report)
        self.assertIn("This is a summary", report)
        self.assertNotIn("summary", server.config_review([self.folder(settings={"apiKeyHelper": "a.sh"})])[0])

    def test_the_fingerprint_sees_what_the_report_doesnt(self):
        d = self.folder(settings={"env": {"A": "1"}})
        text, before, _ = server.config_review([d])
        with open(os.path.join(d, ".claude", "settings.json"), "w") as f:
            json.dump({"env": {"A": "2"}}, f)
        text2, after, _ = server.config_review([d])
        self.assertEqual(text, text2)
        self.assertNotEqual(before, after)

    def test_no_settings(self):
        d = tempfile.mkdtemp(prefix="nouez-test-config-")
        self.addCleanup(shutil.rmtree, d, True)
        self.assertIn("No project settings", server.config_review([d])[0])

    def test_both_folders_once(self):
        a, b = self.folder(settings={"apiKeyHelper": "a.sh"}), self.folder(settings={"apiKeyHelper": "b.sh"})
        report = server.config_review([a, b, a])[0]
        self.assertIn("a.sh", report)
        self.assertIn("b.sh", report)
        self.assertEqual(report.count("a.sh"), 1)


class ApprovalRetryTest(unittest.TestCase):
    """0.26.0: the opt-in approvals end to end on 2026-07-28. The prompt goes back as input_required,
    nothing happens before the answer, and only the same call, answered, goes ahead."""

    def setUp(self):
        self.sent = []
        for patch in (mock.patch.object(server, "respond",
                                        lambda i, result=None, error=None: self.sent.append((result, error))),
                      mock.patch.object(server, "client_request", lambda *a, **k: self.fail("no server requests"))):
            patch.start()
            self.addCleanup(patch.stop)
        server._asked.clear()
        self.addCleanup(server._asked.clear)
        self.meta = {server.META_VERSION: "2026-07-28", server.META_CAPS: {"elicitation": {}}}

    def call(self, name, arguments, **extra):
        self.sent.clear()
        server.dispatch({"id": 1, "method": "tools/call", "params": {
            "name": name, "arguments": arguments, "_meta": self.meta, **extra}}, threading.Event())
        result, error = self.sent[-1]
        self.assertIsNone(error)
        return result

    def answer(self, asked, action, name, arguments):
        response = {"action": action, **({"content": {}} if action == "accept" else {})}
        return self.call(name, arguments, requestState=asked["requestState"],
                         inputResponses={server.ASK_KEY: response})

    def test_create_and_trust_asks_before_the_folder_is_made(self):
        # Neon N3: a decline, or a prompt never answered, leaves no folder behind.
        plain = tempfile.mkdtemp(prefix="nouez-test-plain-")
        self.addCleanup(shutil.rmtree, plain, True)
        new = os.path.join(plain, "fresh")
        args = {"cwd": new, "create": True, "trust": True}
        with mock.patch.dict(os.environ, {"NOUEZ_ASK_TRUST": "1"}), \
                mock.patch.object(server, "trust_folder", return_value=(new, None)) as trust, \
                mock.patch.object(server, "open_window") as window, \
                mock.patch.object(server, "folder_trusted", return_value=False), \
                mock.patch.object(server, "exactly_trusted", return_value=False):
            first = self.call("OpenClaudeSession", args)
            self.assertEqual(first["resultType"], "input_required")
            self.assertIn(f"Create {new} and record that you trust it?",
                          first["inputRequests"][server.ASK_KEY]["params"]["message"])
            self.assertFalse(os.path.exists(new))
            declined = self.answer(first, "decline", "OpenClaudeSession", args)
            self.assertTrue(declined["isError"])
            self.assertIn("declined", declined["content"][0]["text"])
            self.assertFalse(os.path.exists(new))
            trust.assert_not_called()
            done = self.answer(self.call("OpenClaudeSession", args), "accept", "OpenClaudeSession", args)
            self.assertEqual(done["resultType"], "complete")
            self.assertIn(f"Created the folder {new}.", done["content"][0]["text"])
            self.assertTrue(os.path.isdir(new))
            trust.assert_called_once()  # asked once: the made folder isn't asked about again
            window.assert_not_called()  # folder_trusted still says no in this test

    def test_an_answer_after_the_prompt_expired_approves_nothing(self):
        """0.26.1: a prompt's id is good for ASK_SECONDS (10 minutes); an answer that comes later is
        asked again, with a new id, and nothing is done."""
        self.assertEqual(server.ASK_SECONDS, 600)
        plain = tempfile.mkdtemp(prefix="nouez-test-plain-")
        self.addCleanup(shutil.rmtree, plain, True)
        new = os.path.join(plain, "late")
        args = {"cwd": new, "create": True, "trust": True}
        now = time.monotonic()
        with mock.patch.dict(os.environ, {"NOUEZ_ASK_TRUST": "1"}), \
                mock.patch.object(server, "trust_folder", return_value=(new, None)) as trust, \
                mock.patch.object(server, "open_window"), \
                mock.patch.object(server, "folder_trusted", return_value=False), \
                mock.patch.object(server, "exactly_trusted", return_value=False):
            with mock.patch.object(server.time, "monotonic", return_value=now):
                first = self.call("OpenClaudeSession", args)
            with mock.patch.object(server.time, "monotonic", return_value=now + server.ASK_SECONDS + 1):
                late = self.answer(first, "accept", "OpenClaudeSession", args)
            self.assertEqual(late["resultType"], "input_required")
            self.assertNotEqual(late["requestState"], first["requestState"])
            self.assertFalse(os.path.exists(new))
            trust.assert_not_called()

    def test_a_user_session_message_is_approved_for_that_call_only(self):
        # Codex finding 1, Neon N2: changing the message past what the prompt shows, or any other
        # argument, makes it another call, asked about again.
        mine = {"id": "0199aaaa-0000-0000-0000-000000user04", "cwd": ROOT}
        daemon = FakeDaemon([mine])
        args = {"kind": "other", "to": mine["id"], "message": "a" * 600 + " tail", "wait": 0,
                "allow_user_session": True}
        with mock.patch.dict(os.environ, {"NOUEZ_ASK_USER_SESSION": "1"}), \
                mock.patch.object(server, "CodexClient", daemon), \
                mock.patch.object(server, "POLL_SECONDS", 0.01), mock.patch.object(server, "_delivered", {}):
            first = self.call("SendConsultantMessage", args)
            self.assertEqual(first["resultType"], "input_required")
            question = first["inputRequests"][server.ASK_KEY]["params"]["message"]
            self.assertIn(f"(session {mine['id']})", question)
            self.assertIn("... (105 more characters not shown)", question)
            self.assertNotIn("turn/start", daemon.calls)
            changed = dict(args, message="a" * 600 + " else")
            again = self.answer(first, "accept", "SendConsultantMessage", changed)
            self.assertEqual(again["resultType"], "input_required")
            self.assertEqual(again["inputRequests"][server.ASK_KEY]["params"]["message"], question)
            self.assertNotIn("turn/start", daemon.calls)
            done = self.answer(again, "accept", "SendConsultantMessage", changed)
            self.assertEqual(done["resultType"], "complete")
            self.assertTrue(done["content"][0]["text"].startswith("Delivered to "))
            self.assertEqual(daemon.calls.count("turn/start"), 1)
            self.assertIn(" else", daemon.started["input"][0]["text"])

    def test_a_user_session_approval_covers_the_diff_it_names(self):
        # Codex round 2, finding 1: the diff is taken before the question and named in it, so an edit
        # made while the question is open is asked about again, and the diff sent is the one shown.
        mine = {"id": "0199aaaa-0000-0000-0000-000000user05", "cwd": ROOT}
        daemon = FakeDaemon([mine])
        args = {"kind": "other", "to": mine["id"], "message": "Review it.", "wait": 0, "revision": True,
                "allow_user_session": True}
        stamps = iter(["[Revision: commit abc; diff sha256 1111]\n", "[Revision: commit abc; diff sha256 2222]\n",
                       "[Revision: commit abc; diff sha256 2222]\n"])
        with mock.patch.dict(os.environ, {"NOUEZ_ASK_USER_SESSION": "1"}), \
                mock.patch.object(server, "CodexClient", daemon), \
                mock.patch.object(server, "revision_for", lambda a, cwd, **k: (next(stamps), b"", "1" * 16)), \
                mock.patch.object(server, "POLL_SECONDS", 0.01), mock.patch.object(server, "_delivered", {}):
            first = self.call("SendConsultantMessage", args)
            self.assertIn("sha256 1111", first["inputRequests"][server.ASK_KEY]["params"]["message"])
            again = self.answer(first, "accept", "SendConsultantMessage", args)  # edited in between
            self.assertEqual(again["resultType"], "input_required")
            self.assertIn("sha256 2222", again["inputRequests"][server.ASK_KEY]["params"]["message"])
            self.assertNotIn("turn/start", daemon.calls)
            done = self.answer(again, "accept", "SendConsultantMessage", args)
            self.assertEqual(done["resultType"], "complete")
            self.assertIn("sha256 2222", daemon.started["input"][0]["text"])
            # Codex round 3, finding 1: with no diff saved (nor a clean commit), the stamp can only say
            # "review the working tree", which may change after the yes: nothing is asked or sent.
            stamps = iter(["[Revision: commit abc; nouez couldn't save their diff, so review the working tree]\n"])
            with mock.patch.object(server, "revision_for", lambda a, cwd, **k: (next(stamps), b"", "")):
                refused = self.call("SendConsultantMessage", args)
            self.assertTrue(refused["isError"])
            self.assertIn("couldn't save their diff", refused["content"][0]["text"])
            self.assertEqual(daemon.calls.count("turn/start"), 1)

    def test_calls_need_a_handshake_or_the_protocol_s_own_meta(self):
        # Codex round 2, finding 2: a request with any of the protocol's _meta keys is a 2026-07-28 one
        # and needs its version; one with none runs only after initialize.
        ran = []
        with mock.patch.dict(server.HANDLERS, {"Probe": lambda a, c, p: ran.append(1) or "done"}), \
                mock.patch.object(server, "_initialized", threading.Event()):
            self.sent.clear()
            server.dispatch({"id": 1, "method": "tools/call", "params": {
                "name": "Probe", "_meta": {"io.modelcontextprotocol/logLevel": "info"}}}, threading.Event())
            self.assertEqual(self.sent[-1][1]["code"], -32602)
            server.dispatch({"id": 2, "method": "tools/call", "params": {"name": "Probe"}}, threading.Event())
            self.assertEqual(self.sent[-1][1]["code"], -32600)
            self.assertEqual(ran, [])
            # Codex round 3, finding 2: server/discover is the new version's own, so without its _meta
            # it gets that version's -32602 even before any initialize.
            server.dispatch({"id": 4, "method": "server/discover", "params": {}}, threading.Event())
            self.assertEqual(self.sent[-1][1]["code"], -32602)
            server._initialized.set()
            server.dispatch({"id": 3, "method": "tools/call", "params": {"name": "Probe"}}, threading.Event())
            self.assertEqual(self.sent[-1][0]["content"][0]["text"], "done")
            # A 2025-11-25 key under the same prefix (a task's) leaves a request a legacy one.
            server.dispatch({"id": 5, "method": "tools/call", "params": {"name": "Probe", "_meta": {
                "io.modelcontextprotocol/related-task": {"taskId": "t1"}}}}, threading.Event())
            self.assertEqual(self.sent[-1][0]["content"][0]["text"], "done")
            self.assertEqual(len(ran), 2)
        # A finished request drops its own cancellation, never a newer one that reuses its id.
        older, newer = threading.Event(), threading.Event()
        with mock.patch.object(server, "_cancel_events", {7: newer}):
            server.forget_cancel(7, older)
            self.assertIs(server._cancel_events.get(7), newer)
            server.forget_cancel(7, newer)
            self.assertNotIn(7, server._cancel_events)

    def test_an_update_notice_waits_for_a_result_it_can_go_in(self):
        # Neon N1: an input_required result carries no text, so the notice isn't marked as given.
        kept = []

        def notice(pending=None):
            pending.append(lambda: kept.append(1))
            return "nouez 9.9 is out"

        def ask(args, cancel, progress):
            server.user_approves("Go?", "NOUEZ_ASK_TRUST", cancel)
            return "went"
        with mock.patch.object(server, "in_dispatcher", lambda: True), \
                mock.patch.object(server, "safe_nouez_update_notice", notice), \
                mock.patch.object(server, "start_release_check", lambda *a, **k: None), \
                mock.patch.dict(server.HANDLERS, {"Ask": ask}), \
                mock.patch.object(server, "DISPATCHER_TOOLS", ("Ask",)):
            first = self.call("Ask", {})
            self.assertEqual(first["resultType"], "input_required")
            self.assertEqual(kept, [])
            done = self.answer(first, "accept", "Ask", {})
            self.assertEqual(done["content"][0]["text"], "went\n\nnouez 9.9 is out")
            self.assertEqual(kept, [1])


class TrustReportFirstTest(unittest.TestCase):
    """0.19.0: trust=true records trust only once nouez has given the folder's report."""

    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="nouez-test-trust-")
        self.addCleanup(shutil.rmtree, self.dir, True)
        os.mkdir(os.path.join(self.dir, ".git"))
        self.write({"apiKeyHelper": "key.sh"})
        server._trust_reports.clear()
        self.addCleanup(server._trust_reports.clear)
        for patch in (mock.patch.object(server, "folder_trusted", return_value=False),
                      mock.patch.object(server, "exactly_trusted", return_value=False)):
            patch.start()
            self.addCleanup(patch.stop)

    def write(self, settings):
        os.makedirs(os.path.join(self.dir, ".claude"), exist_ok=True)
        with open(os.path.join(self.dir, ".claude", "settings.json"), "w", encoding="utf-8") as f:
            json.dump(settings, f)

    def test_trust_on_the_first_call_gives_the_report(self):
        with mock.patch.object(server, "trust_folder") as trust, mock.patch.object(server, "open_window") as window:
            out = server.open_claude_session({"cwd": self.dir, "trust": True})
        trust.assert_not_called()
        window.assert_not_called()
        self.assertIn("Not trusted yet", out)
        self.assertIn("apiKeyHelper runs: key.sh", out)

    def test_trust_after_the_report_is_recorded(self):
        with mock.patch.object(server, "trust_folder", return_value=(self.dir, None)) as trust, \
                mock.patch.object(server, "open_window") as window:
            first = server.open_claude_session({"cwd": self.dir})
            server.open_claude_session({"cwd": self.dir, "trust": True})
        self.assertIn("apiKeyHelper runs: key.sh", first)
        trust.assert_called_once()
        window.assert_not_called()  # folder_trusted still says no in this test

    def test_the_dispatcher_records_trust_only_inside_its_projects_folder(self):
        """0.26.1: in the phone dispatcher, code (not only its instructions) keeps trust inside its
        projects folder: a folder outside it, the folder itself, or an unknown one is refused with
        nothing changed or made; outside the dispatcher the projects folder plays no part."""
        parent = tempfile.mkdtemp(prefix="nouez-test-projects-")  # not the temporary folder itself, refused
        self.addCleanup(shutil.rmtree, parent, True)
        shutil.move(self.dir, os.path.join(parent, "repo"))
        self.dir = os.path.join(parent, "repo")
        other = tempfile.mkdtemp(prefix="nouez-test-elsewhere-")
        self.addCleanup(shutil.rmtree, other, True)
        mark = {"NOUEZ_DISPATCHER": "1"}
        os.mkdir(os.path.join(self.dir, "x"))  # macOS and Linux go through it for `x/..`
        self.assertIsNone(server.dispatcher_trust_problem(self.dir, {"NOUEZ_DISPATCHER_PROJECTS": other}))
        self.assertIsNone(server.dispatcher_trust_problem(self.dir, {**mark, "NOUEZ_DISPATCHER_PROJECTS": parent}))
        for env, says in (({**mark, "NOUEZ_DISPATCHER_PROJECTS": other}, "isn't one"),
                          ({**mark, "NOUEZ_DISPATCHER_PROJECTS": self.dir}, "isn't one"),
                          ({**mark, "NOUEZ_DISPATCHER_PROJECTS": os.path.join(self.dir, "x", "..", "..")}, None),
                          (mark, "can't tell which folder"),
                          ({**mark, "NOUEZ_DISPATCHER_PROJECTS": "relative"}, "can't tell which folder")):
            with self.subTest(env=env):
                problem = server.dispatcher_trust_problem(self.dir, env)
                if says is None:  # a folder further up still holds it
                    self.assertIsNone(problem)
                    continue
                self.assertIn(says, problem)
        # Inside means both as written and with links resolved: a link from outside into the
        # projects folder isn't inside (trust would be kept for the link's path), nor one leading out.
        inner = os.path.join(other, "inner")
        os.mkdir(inner)
        into, out_of = os.path.join(self.dir, "into"), os.path.join(other, "out-of")
        dir_link(inner, into)
        dir_link(self.dir, out_of)
        boxed = {**mark, "NOUEZ_DISPATCHER_PROJECTS": other}
        self.assertIsNone(server.dispatcher_trust_problem(inner, boxed))
        self.assertIn("isn't one", server.dispatcher_trust_problem(into, boxed))
        self.assertIn("isn't one", server.dispatcher_trust_problem(out_of, boxed))
        # 0.26.1: spelled exactly as the projects folder is, with no link below it, even one that
        # leads inside, since it could be pointed elsewhere once the trust is kept for its path.
        within = os.path.join(other, "within")
        dir_link(inner, within)
        self.assertIn("no link below it", server.dispatcher_trust_problem(within, boxed))
        self.assertIn("isn't one", server.dispatcher_trust_problem(os.path.join(within, "sub"), boxed))
        # 0.26.3: spelled in another case with no link above it (git keeps a worktree's main checkout
        # as it was typed), the folder on disk counts: on Windows, where case doesn't count, inside.
        respelled = other.replace("nouez-test-elsewhere", "NOUEZ-test-elsewhere")
        problem = server.dispatcher_trust_problem(os.path.join(respelled, "inner"), boxed)
        if os.name == "nt":
            self.assertIsNone(problem)
        else:  # realpath keeps the case as written there, and Linux tells the two apart
            self.assertIn("isn't one", problem)
        lower = {**mark, "NOUEZ_DISPATCHER_PROJECTS": other[0].lower() + other[1:]}  # a drive letter's case is no spelling
        self.assertIsNone(server.dispatcher_trust_problem(inner, lower))
        for link in (into, out_of, within):  # the links only, not what they lead to
            os.rmdir(link) if os.name == "nt" else os.unlink(link)
        self.assertTrue(os.path.isdir(inner))
        with mock.patch.object(server, "trust_folder", return_value=(self.dir, None)) as trust, \
                mock.patch.object(server, "open_window"):
            with mock.patch.dict(os.environ, {**mark, "NOUEZ_DISPATCHER_PROJECTS": other}):
                report = server.open_claude_session({"cwd": self.dir})  # the report alone is still given
                self.assertIn("phone dispatcher", report)
                self.assertIn("open_untrusted=true", report)
                self.assertNotIn("call OpenClaudeSession again with trust=true", report)
                with self.assertRaisesRegex(server.BridgeError, "phone dispatcher.*Nothing was changed"):
                    server.open_claude_session({"cwd": self.dir, "trust": True})
                new = os.path.join(parent, "nouez-test-not-made")
                with self.assertRaisesRegex(server.BridgeError, "phone dispatcher"):
                    server.open_claude_session({"cwd": new, "create": True, "trust": True})
                self.assertFalse(os.path.exists(new))  # refused before the folder was made
                trust.assert_not_called()
            with mock.patch.dict(os.environ, {**mark, "NOUEZ_DISPATCHER_PROJECTS": parent}):
                server.open_claude_session({"cwd": self.dir, "trust": True})
            trust.assert_called_once()
        # A worktree's trust is kept for its main checkout, which is checked too: here the worktree
        # is inside the projects folder (`other`) and its main checkout (self.dir) isn't.
        worktree = os.path.join(other, "wt")
        os.mkdir(worktree)
        with mock.patch.object(server, "trust_key", return_value=(self.dir, True)), \
                mock.patch.object(server, "trust_folder") as trust, \
                mock.patch.dict(os.environ, {**mark, "NOUEZ_DISPATCHER_PROJECTS": other}):
            with self.assertRaisesRegex(server.BridgeError, "isn't one"):
                server.open_claude_session({"cwd": worktree, "trust": True})
            new = os.path.join(worktree, "new")  # a new folder in it is trusted with that checkout too
            with self.assertRaisesRegex(server.BridgeError, "isn't one"):
                server.open_claude_session({"cwd": new, "create": True, "trust": True})
            self.assertFalse(os.path.exists(new))  # refused before the folder was made
            trust.assert_not_called()

    def test_with_ask_trust_the_user_approves_each_recording(self):
        """0.26.0: NOUEZ_ASK_TRUST=1 asks in the client's own prompt, naming the report shown, before
        each recording of trust; settings changed while it is open record nothing."""
        asked, answers = [], []

        def prompt(method, params, timeout=5):
            asked.append(params["message"])
            if answers and answers[0] == "change":
                self.write({"apiKeyHelper": "changed.sh"})
                answers[0] = "accept"
            return {"action": answers.pop(0)} if answers else None
        with mock.patch.dict(os.environ, {"NOUEZ_ASK_TRUST": "1"}), \
                mock.patch.dict(server._client_caps, {"elicitation": {}}), \
                mock.patch.object(server, "client_request", prompt), \
                mock.patch.object(server, "trust_folder", return_value=(self.dir, None)) as trust, \
                mock.patch.object(server, "open_window"):
            first = server.open_claude_session({"cwd": self.dir})
            tag = re.search(r"\(report ([0-9a-f]{12}): nouez's prompt names this id\)", first).group(1)
            answers.append("decline")
            with self.assertRaisesRegex(server.BridgeError, "The user declined"):
                server.open_claude_session({"cwd": self.dir, "trust": True})
            trust.assert_not_called()
            self.assertIn(f"(report {tag})", asked[0])
            answers.append("accept")
            server.open_claude_session({"cwd": self.dir, "trust": True})
            trust.assert_called_once()
            answers.append("change")
            with self.assertRaisesRegex(server.BridgeError, "changed while nouez's prompt was open"):
                server.open_claude_session({"cwd": self.dir, "trust": True})
            trust.assert_called_once()
        self.assertNotIn("(report ", server.open_claude_session({"cwd": self.dir}))  # only with the setting

    def test_a_changed_folder_is_reported_again(self):
        with mock.patch.object(server, "trust_folder", return_value=(self.dir, None)) as trust:
            server.open_claude_session({"cwd": self.dir})
            self.write({"apiKeyHelper": "other.sh"})
            out = server.open_claude_session({"cwd": self.dir, "trust": True})
        trust.assert_not_called()
        self.assertIn("changed since", out)
        self.assertIn("other.sh", out)

    def test_a_folder_made_by_the_call_needs_no_report(self):
        plain = tempfile.mkdtemp(prefix="nouez-test-plain-")
        self.addCleanup(shutil.rmtree, plain, True)
        new = os.path.join(plain, "fresh")
        with mock.patch.object(server, "trust_folder", return_value=(new, None)) as trust, \
                mock.patch.object(server, "open_window") as window:
            server.open_claude_session({"cwd": new, "create": True, "trust": True})
        trust.assert_called_once()
        window.assert_not_called()  # folder_trusted still says no in this test

    def test_a_folder_made_inside_a_repository_still_needs_the_report(self):
        new = os.path.join(self.dir, "fresh")
        with mock.patch.object(server, "trust_folder") as trust, mock.patch.object(server, "open_window") as window:
            out = server.open_claude_session({"cwd": new, "create": True, "trust": True})
        trust.assert_not_called()
        window.assert_not_called()
        self.assertIn("Not trusted yet", out)
        self.assertIn("apiKeyHelper runs: key.sh", out)

    def test_the_folder_the_session_starts_in_is_reported(self):
        sub = os.path.join(self.dir, "sub")
        os.makedirs(os.path.join(sub, ".claude"))
        with open(os.path.join(sub, ".claude", "settings.json"), "w") as f:
            json.dump({"statusLine": {"command": "sub.sh"}}, f)
        out = server.open_claude_session({"cwd": sub})
        self.assertIn("statusLine runs: sub.sh", out)
        self.assertIn("apiKeyHelper runs: key.sh", out)

    def test_a_changed_value_the_report_doesnt_show_is_reported_again(self):
        self.write({"env": {"A": "1"}})
        with mock.patch.object(server, "trust_folder", return_value=(self.dir, None)) as trust:
            server.open_claude_session({"cwd": self.dir})
            self.write({"env": {"A": "2"}})
            out = server.open_claude_session({"cwd": self.dir, "trust": True})
        trust.assert_not_called()
        self.assertIn("changed since", out)

    def test_unreadable_settings_are_never_trusted_from_here(self):
        with open(os.path.join(self.dir, ".mcp.json"), "w") as f:
            f.write("{broken")
        with mock.patch.object(server, "trust_folder") as trust:
            first = server.open_claude_session({"cwd": self.dir})
            out = server.open_claude_session({"cwd": self.dir, "trust": True})
        trust.assert_not_called()
        self.assertIn("couldn't be read", first)
        self.assertIn("won't record trust", first)
        self.assertIn("Not trusted", out)

    def test_a_cancelled_call_shows_nothing_so_remembers_nothing(self):
        cancel = threading.Event()
        cancel.set()
        with self.assertRaises(server.Cancelled):
            server.open_claude_session({"cwd": self.dir}, cancel)
        self.assertEqual(server._trust_reports, {})

    def test_a_call_cancelled_after_it_finished_remembers_nothing(self):
        cancel = threading.Event()
        server._cancel_events["c1"] = cancel

        def late_cancel(text):  # the cancellation arrives as the result is put together
            cancel.set()
            return text
        msg = {"jsonrpc": "2.0", "id": "c1", "method": "tools/call",
               "params": {"name": "OpenClaudeSession", "arguments": {"cwd": self.dir}}}
        with mock.patch.object(server, "with_login_warning", side_effect=late_cancel), \
                mock.patch.object(server, "respond") as respond:
            server.dispatch(msg, cancel)
        respond.assert_not_called()
        self.assertEqual(server._trust_reports, {})
        server._cancel_events.pop("c1", None)
        with mock.patch.object(server, "respond", side_effect=OSError("pipe closed")):  # a failed write
            with self.assertRaises(OSError):
                server.dispatch(msg, threading.Event())
        self.assertEqual(server._trust_reports, {})
        with mock.patch.object(server, "respond") as respond:  # and one that isn't cancelled is kept
            server.dispatch(msg, threading.Event())
        respond.assert_called_once()
        self.assertEqual(len(server._trust_reports), 1)

    def test_report_paths_show_characters_that_dont_print(self):
        odd = os.path.join(self.dir, "a\u202eb")
        os.makedirs(os.path.join(odd, ".claude"))
        with open(os.path.join(odd, ".claude", "settings.json"), "w") as f:
            json.dump({"env": {"A": "1"}}, f)
        report = server.config_review([odd])[0]
        self.assertIn("a\\u202eb", report)
        self.assertNotIn("\u202e", report)

    def test_trust_is_written_only_for_the_folder_the_user_was_asked_about(self):
        other = tempfile.mkdtemp(prefix="nouez-test-other-")
        self.addCleanup(shutil.rmtree, other, True)
        with mock.patch.object(server, "trust_key", return_value=(other, False)):
            with self.assertRaisesRegex(server.BridgeError, "Nothing was changed"):
                server.trust_folder(self.dir, expect=self.dir)


class ListProjectsTest(unittest.TestCase):
    """0.19.0: ListProjects lists the folders beside the session's own, read from disk."""

    def setUp(self):
        self.root = tempfile.mkdtemp(prefix="nouez-test-projects-")
        self.addCleanup(shutil.rmtree, self.root, True)
        for name in ("alpha", "beta", ".hidden", "dispatcher"):
            os.mkdir(os.path.join(self.root, name))
        os.mkdir(os.path.join(self.root, "alpha", ".git"))
        with open(os.path.join(self.root, "beta", ".mcp.json"), "w") as f:
            f.write("{}")
        with open(os.path.join(self.root, "notes.txt"), "w") as f:
            f.write("x")
        for patch in (mock.patch.object(server, "default_cwd", return_value=os.path.join(self.root, "dispatcher")),
                      mock.patch.object(server, "trusted_folders", return_value={server._trust_norm(os.path.join(self.root, "alpha"))}),
                      mock.patch.object(server, "claude_sessions", return_value=[
                          {"name": "alpha-work", "cwd": os.path.join(self.root, "alpha", "src")}])):
            patch.start()
            self.addCleanup(patch.stop)

    def test_lists_the_folders_beside_its_own(self):
        out = server.list_projects({})
        self.assertIn(f"Folders in {self.root} (3; hidden folders left out: 1)", out)
        self.assertIn("- alpha [git; trusted; running: alpha-work]", out)
        self.assertIn("- beta [not trusted; has .mcp.json]", out)
        self.assertIn("this session's folder", out)
        self.assertNotIn("notes.txt", out)
        self.assertNotIn(".hidden", out)

    def test_a_folder_reached_through_a_link_doesnt_make_links_of_its_folders(self):
        # macOS's temp folder is under /var, a link to /private/var; CI's Windows temp is RUNNER~1
        outer = tempfile.mkdtemp(prefix="nouez-test-via-")
        self.addCleanup(shutil.rmtree, outer, True)
        via = os.path.join(outer, "via")
        try:
            if os.name == "nt":
                import _winapi
                _winapi.CreateJunction(self.root, via)
            else:
                os.symlink(self.root, via)
        except OSError as e:
            self.skipTest(f"can't make a link here: {e}")
        out = server.list_projects({"folder": via})
        self.assertIn("- beta [", out)
        self.assertNotIn("a link to", out)
        if os.name != "nt":  # a folder that is a link is still marked
            os.symlink(outer, os.path.join(self.root, "gamma"))
            self.assertIn(f"- gamma [a link to {os.path.realpath(outer)}", server.list_projects({"folder": via}))

    def test_folders_windows_marks_hidden_are_left_out(self):
        with mock.patch.object(server, "hidden_on_windows", side_effect=lambda p: p.endswith("beta")):
            out = server.list_projects({})
        self.assertNotIn("beta", out)
        self.assertIn("hidden folders left out: 2", out)

    @unittest.skipUnless(os.name == "nt", "Windows file attributes")
    def test_the_hidden_attribute_is_read(self):
        import ctypes
        path = os.path.join(self.root, "beta")
        self.assertFalse(server.hidden_on_windows(path))
        ctypes.windll.kernel32.SetFileAttributesW(path, 0x2)
        self.assertTrue(server.hidden_on_windows(path))

    def test_another_folder(self):
        out = server.list_projects({"folder": os.path.join(self.root, "alpha")})
        self.assertIn("No folders in", out)
        with self.assertRaises(server.BridgeError):
            server.list_projects({"folder": "relative"})


class StatusScreenTest(unittest.TestCase):
    """0.19.0: OpenStatusScreen opens `top` in the home folder."""

    def setUp(self):
        root = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, root, True)
        for name, value in (("nouez_cache_dir", lambda: root),  # none open, then the new one is
                            ("status_screen_open", mock.Mock(side_effect=[False, True, True]))):
            patch = mock.patch.object(server, name, value)
            patch.start()
            self.addCleanup(patch.stop)

    def test_opens_top_in_the_home_folder(self):
        with mock.patch.object(server, "open_window", return_value="a new window") as window:
            out = server.open_status_screen({"days": 30})
        cwd, argv, _ = window.call_args[0]
        self.assertEqual(cwd, os.path.expanduser("~"))
        self.assertEqual(argv[-7:], [os.path.abspath(server.__file__), "top", "--arranged", "--days", "30",
                                     "--page", "usage"])
        self.assertIn("ConsultantBudget", out)

    def test_a_whole_number_sent_as_a_float_is_taken(self):
        with mock.patch.object(server, "open_window", return_value="a new window") as window:
            server.open_status_screen({"days": 7.0})
        self.assertEqual(window.call_args[0][1][-3], "7")

    def test_only_the_screens_periods(self):
        for bad in (2, True, "7", 7.5):
            with self.assertRaises(server.BridgeError):
                server.open_status_screen({"days": bad})


class ConsultationsPageTest(unittest.TestCase):
    """0.23.0: the status screen's consultations page, which replaces the Codex panes."""

    CODEX = "0199aaaa-0000-0000-0000-00000000c0de"

    def thread(self, tid, cwd, status="idle", updated=100, bridge=True):
        return {"id": tid, "cwd": cwd, "model": "gpt-6.2-astra", "reasoningEffort": "high",
                "status": {"type": status}, "updatedAt": updated,
                "threadSource": server.BRIDGE_SOURCE if bridge else "cli"}

    def test_overview_lists_only_nouez_consultants_working_first(self):
        mine = self.thread(self.CODEX, "/w/alpha", updated=300)
        busy = self.thread(self.CODEX[:-4] + "beef", "/w/beta", status="active", updated=100)
        users = self.thread(self.CODEX[:-4] + "0001", "/w/alpha", updated=999, bridge=False)
        rec = {"id": "0199bbbb-0000-0000-0000-0000000a9e01", "name": "agy-alpha-9e01", "cwd": "/w/alpha",
               "model": "gemini-4-neon-xhigh", "created": 50}
        events = [{"event": "send", "thread": self.CODEX, "turn": "t1", "kind": "review", "ts": 1},
                  {"event": "reply", "thread": self.CODEX, "turn": "t1", "status": "completed", "verdict": "changes", "ts": 2},
                  {"event": "send", "thread": busy["id"], "turn": "t2", "kind": "research", "ts": 3},
                  {"event": "send", "thread": rec["id"], "turn": "a2", "kind": "plan-critique", "ts": 4},
                  {"event": "reply", "thread": rec["id"], "turn": "a1", "status": "completed", "verdict": "yes", "ts": 5}]
        latest = {self.CODEX: {"id": "t1", "status": "completed"},
                  busy["id"]: {"id": "t2", "status": "inProgress", "startedAt": time.time() - 700},
                  rec["id"]: {"id": "a2", "status": "completed"}}
        events.append({"event": "reply", "thread": self.CODEX, "turn": "older", "verdict": "yes"})
        rows = server.consultant_overview([mine, busy, users], [rec], events, latest)
        self.assertEqual([r["state"] for r in rows], ["long run", "idle", "done"])
        self.assertEqual([r["id"] for r in rows], [busy["id"], self.CODEX, rec["id"]])  # never the user's session
        self.assertTrue(rows[0]["busy"])
        self.assertEqual((rows[1]["kind"], rows[1]["verdict"]), ("review", "changes"))
        self.assertEqual((rows[0]["kind"], rows[0]["verdict"]), ("research", None))  # still working
        # The reply on record is to an earlier message than the last one sent: no verdict yet.
        self.assertEqual((rows[2]["kind"], rows[2]["verdict"]), ("plan-critique", None))
        self.assertEqual((rows[2]["model"], rows[2]["effort"]), ("gemini-4-neon", "xhigh"))
        running = {"id": "a3", "status": "inProgress", "startedAt": 400, "items": []}
        rows = server.consultant_overview([], [rec], [], {rec["id"]: running})
        self.assertTrue(rows[0]["busy"])
        self.assertEqual(rows[0]["updated"], 400)

    def test_phone_list_puts_unread_before_idle_without_message_text(self):
        idle = self.thread(self.CODEX, "/w/alpha")
        review = self.thread(self.CODEX[:-4] + "beef", "/w/beta")
        turn = {"id": "t", "status": "completed", "items": [server_agent("private reply")]}
        idle["name"], review["name"] = "First", "Review title"
        user = dict(idle, id="user", threadSource="cli", name="User title")
        daemon = FakeDaemon([idle, review, user], {review["id"]: [turn]})
        events = [{"event": "send", "thread": review["id"], "turn": "t", "kind": "review"}]
        with mock.patch.object(server, "CodexClient", daemon), mock.patch.object(server, "codex_installed", return_value=True), \
                mock.patch.object(server, "agy_consultants", return_value=[]), \
                mock.patch.object(server, "read_usage_log", return_value=events), \
                mock.patch.dict(os.environ, {"NOUEZ_NO_USAGE_LOG": ""}):
            listed = server.list_consultants({})
            self.assertTrue(listed.startswith("- done, no reply logged"))
            self.assertIn("/w/beta", listed.splitlines()[0])
            self.assertIn("Review title", listed.splitlines()[0])
            self.assertIn("User title", listed.splitlines()[-1])
            self.assertNotIn("private reply", listed)
            now = time.time()
            daemon.turns[idle["id"]] = [turn]
            for thread, delta in ((idle, -1), (review, 1)):
                events.append(dict(event="reply", thread=thread["id"], turn="t", verdict="changes",
                                   ts=now-server.ATTENTION_SECONDS+delta))
            with mock.patch.object(time, "time", return_value=now):
                self.assertIn("Review title", server.list_consultants({}).splitlines()[0])
            with mock.patch.object(server, "latest_turn", side_effect=[server.BridgeError("lost"), turn]):
                listed = server.list_consultants({})
                self.assertIn("- unknown", listed)
                self.assertIn("- changes", listed)
            with mock.patch.dict(os.environ, {"NOUEZ_NO_USAGE_LOG": "1"}), \
                    mock.patch.object(server, "read_usage_log", side_effect=AssertionError("log is off")):
                listed = server.list_consultants({})
            self.assertNotIn("no reply logged", listed)
            self.assertIn("Verdicts aren't tracked", listed)

    def test_overview_inherits_only_an_actual_continuation(self):
        thread = self.thread(self.CODEX, ROOT)
        root = {"id": "root", "status": "interrupted"}
        end = {"id": "end", "rootTurnId": "root", "status": "completed"}
        send = {"thread": self.CODEX, "turn": "root", "event": "send", "kind": "review"}
        for history, pending in (([end, root], True), ([end, {"id": "other"}, root], False)):
            daemon = FakeDaemon([thread], {self.CODEX: history})
            latest = server.codex_overview_turns(daemon, [thread])
            row, = server.consultant_overview([thread], [], [send], latest)
            self.assertEqual(row["pending"], pending)
            self.assertEqual(row["kind"], "review" if pending else None)

    def test_completed_agy_turn_before_send_log(self):
        rec = {"id": "agy"}
        with mock.patch.dict(os.environ, {"NOUEZ_NO_USAGE_LOG": ""}):
            row, = server.consultant_overview([], [rec], [], {"agy": {"id": "t", "status": "completed"}})
        self.assertTrue(row["pending"])

    def test_turn_text_is_plain_and_in_order(self):
        turn = {"status": "completed", "items": [
            {"type": "userMessage", "content": [{"type": "text", "text":
                "[Message from Claude Code via the consultants bridge]\n\nReview \x1b[2Jthis‮ diff"}]},
            {"type": "reasoning", "summary": ["Reading the diff"]},
            {"type": "reasoning", "summary": []},
            {"type": "commandExecution", "command": "pwsh -c git diff", "exitCode": 1,
             "commandActions": [{"type": "unknown", "command": "git diff"}]},
            {"type": "webSearch", "query": "codex resume"},
            {"type": "agentMessage", "phase": "final_answer", "text": "Verdict: yes\n\tall good"}]}
        self.assertEqual([(label, text) for _, label, text in server.turn_paragraphs(turn)],
                         [("from Claude Code", "Review \x1b[2Jthis‮ diff"), ("thinking", "Reading the diff"),
                          ("", "$ git diff (exit 1)"), ("search", "codex resume"), ("reply", "Verdict: yes\n\tall good")])
        lines = server.turn_lines(server.Screen(False), turn, 40)
        self.assertIs(server.turn_lines(server.Screen(False), turn, 40), lines)  # laid out once per turn read
        self.assertIn("Review [2Jthis diff", lines)  # no escape or bidi control reaches the terminal
        self.assertIn("    all good", lines)
        self.assertFalse(any("\x1b" in line or "\t" in line for line in lines))
        long = server.turn_lines(server.Screen(False), {"items": [server_agent("word " * 30)]}, 20)
        self.assertTrue(all(server.visible(line) <= 20 for line in long))
        running = server.turn_lines(server.Screen(False), {"status": "inProgress", "items": [server_agent("so far")]}, 40)
        self.assertEqual(running[-1], "working…")

    def test_strings_from_a_consultant_or_a_log_are_made_safe(self):
        owner = ("The user's own words, as they typed them:\n<<<\nkeep the\x1b[31m old API\n>>>\n\n"
                 "The rest of this message is Claude Code's.\n\n")
        turn = {"status": "failed", "error": {"message": "bad\x1b]0;title\x07 turn"}, "items": [
            {"type": "userMessage", "content": [{"type": "text", "text":
                "[Message from Cl\x1b[2Jaude via the consultants bridge]\n\n" + owner + "Review it"}]}]}
        paragraphs = [(label, text) for _, label, text in server.turn_paragraphs(turn)]
        self.assertEqual(paragraphs, [("the user's words, passed on from Cl\x1b[2Jaude", "keep the\x1b[31m old API"),
                                      ("from Cl\x1b[2Jaude", "Review it")])
        lines = server.turn_lines(server.Screen(True), turn, 60)
        text = server.ANSI.sub("", "\n".join(lines))
        self.assertNotIn("\x1b", text)
        self.assertNotIn("\x07", text)
        self.assertIn("keep the[31m old API", text)
        row = {**self.rows(1)[0], "kind": "re\x1b[2Jview", "verdict": "y\x1bes", "command": "codex\x1b[2J resume x"}
        lines, _ = server.consultations_frame(server.Screen(False), 200, [row], ((row["provider"], row["id"]),
                                              {"status": "odd\x1b[2J", "items": []}), "lost\x1b[2J", (row["provider"], row["id"]),
                                              0, 120, 30, "T", "K")
        self.assertFalse(any("\x1b" in line for line in lines))

    def test_wrapping_is_one_pass(self):
        text = ("word " * 4000).strip()
        start = time.monotonic()
        pieces = server.wrap_cells(text, 80)
        self.assertLess(time.monotonic() - start, 1)
        self.assertTrue(all(server.visible(p) <= 80 for p in pieces))
        self.assertEqual(" ".join(pieces), text)  # cut at spaces, nothing lost
        self.assertEqual(server.wrap_cells("x" * 25, 10), ["x" * 10, "x" * 10, "x" * 5])
        self.assertEqual(server.wrap_cells("漢字" * 6, 5), ["漢字", "漢字", "漢字", "漢字", "漢字", "漢字"])
        self.assertEqual(server.wrap_cells("", 10), [""])

    def test_older_consultants_from_the_usage_log(self):
        old = self.CODEX[:-4] + "0010"
        stopped = self.CODEX[:-4] + "0012"  # StopConsultant archived it; thread/read still returns it
        daemon = FakeDaemon([self.thread(self.CODEX, ROOT), self.thread(old, ROOT),
                             dict(self.thread(stopped, ROOT), path=os.path.join("codex", "archived_sessions", "r.jsonl"))], {})
        events = [{"event": "send", "thread": stopped, "turn": "t"},
                  {"event": "send", "thread": old, "turn": "t"}, {"event": "send", "thread": "agy-x", "provider": "antigravity"},
                  {"event": "send", "thread": self.CODEX[:-4] + "0011", "user_session": True}]
        self.assertEqual(server.logged_codex_threads(events), [old, stopped])
        with mock.patch.object(server, "CodexClient", daemon), mock.patch.object(server, "read_usage_log", return_value=events), \
             mock.patch.object(server, "RECENT_SAVED_THREADS", 0), mock.patch.object(server, "loaded_ids", return_value=[]), \
             mock.patch.object(server, "agy_consultants", return_value=[]), \
             mock.patch.dict(os.environ, {"NOUEZ_NO_USAGE_LOG": ""}):
            feed = server.ConsultationFeed()
            feed.show(None, True)
            feed._list()
            self.assertEqual(server.resolve(daemon, server.short_name(daemon.threads[old]))["id"], old)
            with self.assertRaises(server.BridgeError):
                server.resolve(daemon, server.short_name(daemon.threads[stopped]))
            with self.assertRaisesRegex(server.BridgeError, r"was stopped \(archived\).*codex unarchive"):
                server.resolve(daemon, stopped)  # nor by its full id
            # StartConsultant reuses the consultant the list shows, rather than starting a second one.
            self.assertEqual([t["id"] for t in server.repo_consultants(daemon, ROOT)[1]], [old])
        self.assertEqual([r["id"] for r in feed.state()[0]], [old])  # past the recent list, still shown
        self.assertTrue(feed.state()[0][0]["command"].startswith(f"codex resume {old}"))

    def test_a_name_shared_with_an_older_consultant(self):
        # Names keep the id's last six characters: a recent consultant and a logged older one can
        # share one, and a stop must not pick the recent one silently.
        twin = "0199bbbb" + self.CODEX[8:]
        daemon = FakeDaemon([self.thread(self.CODEX, ROOT), self.thread(twin, ROOT)], {})
        name = server.short_name(daemon.threads[self.CODEX])
        self.assertEqual(name, server.short_name(daemon.threads[twin]))
        with mock.patch.object(server, "read_usage_log", return_value=[{"event": "send", "thread": twin, "turn": "t"}]), \
             mock.patch.object(server, "RECENT_SAVED_THREADS", 0), \
             mock.patch.object(server, "loaded_ids", return_value=[self.CODEX]), \
             mock.patch.dict(os.environ, {"NOUEZ_NO_USAGE_LOG": ""}):
            with self.assertRaisesRegex(server.BridgeError, "names more than one session"):
                server.resolve(daemon, name, exact_only=True)
            self.assertEqual(server.resolve(daemon, twin)["id"], twin)

    def test_feed_closing_while_it_connects(self):
        feed = server.ConsultationFeed(lambda: None)
        proxies = []

        class Client:  # a proxy started, its handshake still waiting, when the screen quits
            def __init__(self, on_spawn):
                self.close = mock.Mock()
                proxies.append(self)
                on_spawn(self)
                feed.close()
                self.close.assert_called_once()  # ended by close() itself, before the handshake returns
        with mock.patch.object(server, "CodexClient", Client):
            with self.assertRaises(server.BridgeError):
                feed._codex()
            self.assertIsNone(feed.client)
            self.assertIsNone(feed.starting)
            with self.assertRaises(server.BridgeError):  # closed: a proxy started now is refused
                feed._spawned(mock.Mock())

    def test_feed_close_ends_its_connection(self):
        closed = threading.Event()

        class Client:
            info = {}

            def close(self):
                closed.set()
        feed = server.ConsultationFeed()
        feed.client = Client()
        thread = threading.Thread(target=feed.run, daemon=True)
        with mock.patch.object(feed, "_list"), mock.patch.object(feed, "_read_turn"):
            thread.start()
            feed.close(thread)
        self.assertTrue(closed.is_set())
        self.assertFalse(thread.is_alive())

    def rows(self, n):
        return [{"provider": "codex", "id": f"0199aaaa-0000-0000-0000-{i:012d}", "name": f"codex-p{i}-{i:06d}",
                 "cwd": f"/w/p{i}", "model": "gpt-6.2-astra", "effort": "high", "busy": i == 0, "state": "working" if i == 0 else "idle",
                 "updated": 100 - i, "kind": None, "verdict": "yes" if i else None} for i in range(n)]

    def test_frame_fills_the_height_and_shows_the_selection(self):
        scr, rows = server.Screen(False), self.rows(20)
        for row in rows:
            row["command"] = server.resume_command(row)  # as the feed reads it
        key = ("codex", rows[15]["id"])
        turn = (key, {"status": "completed", "items": [server_agent("\n".join(f"line {i}" for i in range(100)))]})
        for height in (12, 24, 40):
            lines, scroll = server.consultations_frame(scr, 200, rows, turn, None, key, 0, 100, height, "TOP", "KEYS")
            self.assertEqual(len(lines), height)
            self.assertEqual((lines[0], lines[-1]), ("TOP", "KEYS"))
            self.assertTrue(any("> codex-p15-000015" in line for line in lines), height)  # scrolled into view
            self.assertTrue(any("line 99" in line for line in lines))  # the end of the turn, followed
            self.assertIn(f"codex resume {rows[15]['id']}", "\n".join(lines))
        lines, scroll = server.consultations_frame(scr, 200, rows, turn, None, key, 10 ** 9, 100, 40, "TOP", "KEYS")
        self.assertTrue(any("line 0" in line for line in lines))  # Home: the start, the scroll clamped
        self.assertLess(scroll, 100)
        other = ("codex", rows[3]["id"])  # selected, but its turn not read yet
        lines, _ = server.consultations_frame(scr, 200, rows, turn, None, other, 0, 100, 40, "TOP", "KEYS")
        self.assertIn("Reading its latest turn", "\n".join(lines))
        for state, text in ((None, "Reading the consultants"), ([], "No consultants yet")):
            lines, _ = server.consultations_frame(scr, 200, state, None, "Codex: down", None, 0, 100, 10, "T", "K")
            self.assertEqual(len(lines), 10)
            self.assertIn(text, "\n".join(lines))
            self.assertIn("Codex: down", "\n".join(lines))

    def test_resume_command(self):
        row = self.rows(1)[0]
        self.assertEqual(server.resume_command(row), f"codex resume {row['id']}")
        home = tempfile.mkdtemp(suffix=" with space")
        self.addCleanup(shutil.rmtree, home, True)
        os.makedirs(os.path.join(home, "app-server-control"))
        sock = os.path.join(home, "app-server-control", "app-server-control.sock")
        self.assertEqual(server.resume_command(row, home), f"codex resume {row['id']}")  # no socket there
        open(sock, "w").close()
        command = server.resume_command(row, home)
        words = server.split_windows_args(command) if os.name == "nt" else server.shlex.split(command)
        shown = sock.replace("\\", "/") if os.name == "nt" else sock  # both shells read / on Windows
        self.assertEqual(words, ["codex", "resume", row["id"], "--remote", "unix://" + shown])
        if os.name == "nt":
            self.assertIn('"unix://', command)  # PowerShell's quoting, not the C runtime's
        odd = "C:/it$s" if os.name == "nt" else "/it$s"
        with mock.patch.object(server.os.path, "exists", return_value=True):  # $ kept from the shell
            self.assertTrue(server.resume_command(row, odd).endswith(
                f" --remote 'unix://{odd}/app-server-control/app-server-control.sock'"))
        agy = {**row, "provider": "antigravity"}
        with mock.patch.object(server, "agy_conversation", return_value="conv-1"), \
                mock.patch.object(server, "agy_shown", return_value="agy"):
            self.assertEqual(server.resume_command(agy), "agy --conversation conv-1")
        with mock.patch.object(server, "agy_conversation", return_value="conv-1"), \
                mock.patch.object(server, "agy_shown", return_value="& 'C:/A B/agy.exe'"):
            self.assertEqual(server.resume_command(agy), "& 'C:/A B/agy.exe' --conversation conv-1")  # as typed
        with mock.patch.object(server, "agy_conversation", return_value=None):
            self.assertEqual(server.resume_command(agy), "")

    def test_feed_reads_the_running_turn_until_it_ends(self):
        tid = self.CODEX
        daemon = FakeDaemon([self.thread(tid, ROOT, status="active")],
                            {tid: [{"id": "t1", "status": "inProgress", "items": []}]})
        with mock.patch.object(server, "CodexClient", daemon), mock.patch.object(server, "read_usage_log", return_value=[]):
            feed = server.ConsultationFeed()
            feed._list()
            self.assertNotIn("thread/turns/list", daemon.calls)
            key = ("codex", tid)
            feed.show(key, True)
            feed._read_turn(key)
            self.assertEqual(feed.state()[1], (key, daemon.turns[tid][0]))
            reads = daemon.calls.count("thread/turns/list")
            daemon.turns[tid][0]["status"] = "completed"
            daemon.threads[tid]["status"] = {"type": "idle"}
            feed._read_turn(key)  # the list still says working: read again
            feed._list()
            feed._read_turn(key)  # ended: read once more, as the list now says
            feed._read_turn(key)
            self.assertEqual(daemon.calls.count("thread/turns/list"), reads + 3)
            self.assertEqual(feed.state()[1][1]["status"], "completed")

    def test_feed_survives_a_lost_daemon(self):
        class Lost:
            def __init__(self, on_spawn=None):
                raise server.BridgeError("closed the connection")
        feed = server.ConsultationFeed()
        feed.rows = self.rows(2)
        with mock.patch.object(server, "CodexClient", Lost), mock.patch.object(server, "read_usage_log", return_value=[]):
            feed._guarded(feed._list)
        rows, _, error = feed.state()
        self.assertEqual(len(rows), 2)  # the Codex consultants last seen stay
        self.assertIn("closed the connection", error)
        self.assertIsNone(feed.client)

    def test_keys_by_name(self):
        if os.name == "nt":
            fake = mock.Mock(kbhit=lambda: True, getwch=iter(["\xe0", "P", "\x00", "I", "\xe0", "X"]).__next__)
            with mock.patch.dict(sys.modules, {"msvcrt": fake}):
                self.assertEqual([server.read_key(1) for _ in range(3)], ["down", "pgup", ""])
        self.assertEqual(server.POSIX_KEYS[b"[A"], "up")
        self.assertEqual(server.POSIX_KEYS[b"[6~"], "pgdn")
        wake = threading.Event()
        wake.set()
        start = time.monotonic()
        with mock.patch.object(server.os, "name", "nt"), \
                mock.patch.dict(sys.modules, {"msvcrt": mock.Mock(kbhit=lambda: False)}):
            self.assertIsNone(server.read_key(5, wake))
        self.assertLess(time.monotonic() - start, 2)

    def test_reload_keeps_page_and_period(self):
        periods = list(server.TOP_PERIODS.values())
        cases = [(30, "usage", 7, ["--days", "30"]), (None, "consultations", 7, ["--days", "0", "--page", "consultations"]),
                 (14, "consultations", 14, ["--days", "14", "--page", "consultations"]),
                 (14, "usage", 14, ["--days", "14"])]
        for days, page, given, expect in cases:
            code = server.reload_code(days, page, given)
            self.assertLess(code, 128)
            self.assertGreater(code, server.TOP_RELOAD)
            self.assertEqual(server.reload_args(["--days", str(given), "--page", "consultations"], code), expect)
        self.assertEqual(server.reload_args(["--days", "7"], server.TOP_RELOAD), ["--days", "7"])
        self.assertEqual(server.reload_code(None, "consultations", None),
                         server.TOP_RELOAD + 1 + 2 * (len(periods) + 1) - 1)

    def test_single_status_screen(self):
        root = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, root, True)
        with mock.patch.object(server, "nouez_cache_dir", lambda: root):
            self.assertFalse(server.status_screen_open())
            holder = server.hold_status_screen()
            self.assertIsNotNone(holder)
            self.assertIsNone(server.hold_status_screen())  # a second screen runs, but isn't the one
            self.assertTrue(server.status_screen_open())
            self.assertIsNone(server.take_status_screen())  # held: the open screen is switched instead
            with mock.patch.object(server, "open_window") as window, \
                    mock.patch.object(server, "show_status_window", return_value=False):
                out = server.open_status_screen({"page": "consultations"})
                window.assert_not_called()
                self.assertIn("already open", out)
                command = server.cache_json(server.status_command_file())
                self.assertEqual((command["page"], "days" in command), ("consultations", False))
                server.open_status_screen({"days": 30})
                command2 = server.cache_json(server.status_command_file())
                self.assertEqual((command2["page"], command2["days"]), ("usage", 30))
                self.assertGreater(command2["seq"], command["seq"])
            server.release_status_screen(holder)
            self.assertFalse(server.status_screen_open())
            self.assertFalse(os.path.exists(server.status_screen_file()))
            # A screen that can't note its id doesn't keep the lock: requests would go to whatever
            # id a crashed screen left in the file.
            server.write_json_atomic(server.status_screen_file(), {"pid": 1, "id": "crashed"})
            with mock.patch.object(server, "write_json_atomic", return_value=False):
                self.assertIs(server.hold_status_screen(), False)
            self.assertFalse(server.status_screen_open())
            self.assertFalse(os.path.exists(server.status_screen_file()))
            # The open screen closed between a failed try and the check: tried again, not run unlocked.
            lock = object()
            with mock.patch.object(server, "hold_status_screen", side_effect=[None, lock]), \
                    mock.patch.object(server.time, "sleep"):
                self.assertIs(server.take_status_screen(), lock)
            with mock.patch.object(server, "hold_status_screen", return_value=None), \
                    mock.patch.object(server, "status_screen_open", return_value=False), \
                    mock.patch.object(server.time, "sleep"):
                self.assertIs(server.take_status_screen(), False)  # a cache that holds no lock
            server.release_status_screen(False)
            # A request is addressed to the screen open when it is written, never to the next one.
            holder = server.hold_status_screen()
            first = server.cache_json(server.status_screen_file())["id"]
            self.assertTrue(server.write_status_command({"page": "consultations"}))
            self.assertEqual(server.cache_json(server.status_command_file())["screen"], first)
            server.release_status_screen(holder)
            self.assertIsNone(server.write_status_command({"page": "usage"}))  # none open: nothing written
            self.assertEqual(server.cache_json(server.status_command_file())["page"], "consultations")
            # A screen registers between requests: while one is being written, it waits.
            writing = server.FileLock(os.path.join(root, "status-command.lock"), 0, "")
            writing.__enter__()
            got = []
            opening = threading.Thread(target=lambda: got.append(server.hold_status_screen()))
            opening.start()
            opening.join(0.5)
            self.assertEqual(got, [])
            self.assertFalse(server.status_screen_open())
            writing.__exit__(None, None, None)
            opening.join(10)
            holder = got[0]
            self.assertIsNotNone(holder)
            self.assertNotEqual(server.cache_json(server.status_screen_file())["id"], first)
            # Writers at once take turns: each gets its own number, even on a clock that hasn't moved.
            base = server.command_seq(server.status_command_file())
            with mock.patch.object(server.time, "time_ns", return_value=1):
                done = []
                writers = [threading.Thread(target=lambda: done.append(server.write_status_command({"days": 1})))
                           for _ in range(8)]
                for w in writers:
                    w.start()
                for w in writers:
                    w.join(30)
            self.assertEqual(done, [True] * 8)
            self.assertEqual(server.cache_json(server.status_command_file())["seq"], base + 8)
            # A request not applied yet is kept: a later one adds to it, a bare `top` leaves it.
            def pending():
                command = server.cache_json(server.status_command_file())
                return command.get("page"), command.get("days")
            self.assertTrue(server.write_status_command({"page": "consultations", "days": 30}))
            self.assertTrue(server.write_status_command({}))
            self.assertEqual(pending(), ("consultations", 30))
            self.assertTrue(server.write_status_command({"days": 7}))
            self.assertEqual(pending(), ("consultations", 7))
            mark = server.cache_json(server.status_screen_file())
            server.write_json_atomic(server.status_screen_file(),  # the screen applied it
                                     {**mark, "applied": server.command_seq(server.status_command_file())})
            self.assertTrue(server.write_status_command({"days": 1}))
            self.assertEqual(pending(), (None, 1))
            # A screen that closed between the failed try and the request: the next try runs it.
            with mock.patch.object(server, "take_status_screen", side_effect=[None, "lock"]), \
                    mock.patch.object(server, "write_status_command", return_value=None):
                self.assertEqual(server.take_or_switch([]), ("lock", None))
            # A screen restarted by a 0.22.0 supervisor while this one is open hands it the page.
            with mock.patch.object(server, "read_scan_state", return_value={}), \
                    mock.patch.object(server, "agy_command", return_value=None), \
                    mock.patch.object(server, "show_status_window", return_value=True), \
                    mock.patch.object(server.sys, "stdout", io.StringIO()):
                self.assertEqual(server.run_top(["--screen", "--days", "7", "--page", "consultations"]),
                                 server.TOP_QUIT)
            self.assertEqual(server.cache_json(server.status_command_file())["page"], "consultations")
            server.release_status_screen(holder)
            with mock.patch.object(server, "open_window", return_value="a new window") as window, \
                    mock.patch.object(server, "status_screen_open", side_effect=[False, False, True, True]):
                out = server.open_status_screen({"page": "consultations"})
            self.assertEqual(window.call_args[0][1][-4:], ["--days", "7", "--page", "consultations"])
            self.assertIn("on its consultations page", out)
            clock = iter(range(0, 1000, 2))
            with mock.patch.object(server, "open_window", return_value="a new window"), \
                    mock.patch.object(server, "status_screen_open", return_value=False), \
                    mock.patch.object(server.time, "sleep"), \
                    mock.patch.object(server.time, "monotonic", side_effect=lambda: next(clock)):
                out = server.open_status_screen({})
            self.assertIn("hadn't started yet", out)  # not reported as open
            with self.assertRaises(server.BridgeError):
                server.open_status_screen({"page": "panes"})

    def test_screen_follows_a_command(self):
        # OpenStatusScreen's command switches the open screen's page and period; a restart keeps them.
        root = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, root, True)

        screen_id = [""]  # the id the supervisor gives the screen

        def run(early=None, late=None):
            drawn = []

            def keys(timeout, wake):
                if len(drawn) == 1 and late:
                    server.write_json_atomic(server.status_command_file(), late)
                    self.assertTrue(wake.wait(5))  # the screen noticed it at once, not on its next refresh
                elif len(drawn) == 1:
                    time.sleep(1.2)  # the command thread has read the file by now
                return None
            if early:  # written after the supervisor took the lock, before this screen polls
                server.write_json_atomic(server.status_command_file(), early)
            with mock.patch.object(server, "read_scan_state", return_value={}), \
                 mock.patch.object(server, "scan_usage"), \
                 mock.patch.object(server, "read_codex_usage"), mock.patch.object(server, "read_agy_usage"), \
                 mock.patch.object(server, "read_usage_log", return_value=[]), \
                 mock.patch.object(server.ConsultationFeed, "run"), \
                 mock.patch.object(server, "top_frame", side_effect=lambda *a: drawn.append("usage") or []), \
                 mock.patch.object(server, "consultations_frame",
                                   side_effect=lambda *a: drawn.append("consultations") or ([], 0)), \
                 mock.patch.object(server, "enable_ansi", return_value=False), \
                 mock.patch.object(server, "read_key", side_effect=keys), \
                 mock.patch.object(server, "top_reload_due", side_effect=lambda *a: (len(drawn) >= 2, (1, 1))), \
                 mock.patch.object(server.sys.stdin, "isatty", return_value=False), \
                 mock.patch.dict(server.os.environ, {"NOUEZ_STATUS_SCREEN": screen_id[0]}), \
                 mock.patch.object(server.sys, "stdout", io.StringIO()):
                return server.run_top(["--screen", "--supervised", "--days", "7"]), drawn
        with mock.patch.object(server, "nouez_cache_dir", lambda: root):
            server.write_json_atomic(server.status_command_file(), {"seq": 5, "page": "consultations"})
            holder = server.hold_status_screen()  # as the supervisor does
            me = server.cache_json(server.status_screen_file())["id"]
            self.assertEqual(holder.screen_id, me)
            screen_id[0] = me
            try:
                stale = run()  # a request from before this screen opened isn't applied
                self.assertEqual(stale[1], ["usage", "usage"])
                other = {"seq": time.time_ns(), "page": "consultations", "screen": "another screen's"}
                self.assertEqual(run(early=other)[1], ["usage", "usage"])  # nor one for another screen
                late = {"seq": time.time_ns(), "page": "consultations", "days": 30, "screen": me}
                self.assertEqual(run(late=late), (server.reload_code(30, "consultations", 7), ["usage", "consultations"]))
                self.assertEqual(server.cache_json(server.status_screen_file())["applied"], late["seq"])
                self.assertEqual(run()[1], ["usage", "usage"])  # applied already: not again after a restart
                screen_id[0] = "this screen's"  # the file names another screen: nothing applied
                self.assertEqual(run(early={"seq": time.time_ns(), "page": "consultations", "screen": me})[1],
                                 ["usage", "usage"])
                screen_id[0] = me
                early = {"seq": time.time_ns(), "page": "consultations", "screen": me}
                code, drawn = run(early=early)
                self.assertEqual(drawn[-1], "consultations")
            finally:
                server.release_status_screen(holder)

    def test_old_pane_cleanup_runs_in_the_background(self):
        done = threading.Event()
        with mock.patch.object(server, "close_old_panes", side_effect=lambda: done.set() or 2), \
                mock.patch.object(server, "log") as log:
            server.start_pane_cleanup()
            self.assertTrue(done.wait(5))
            for _ in range(100):
                if log.called:
                    break
                time.sleep(0.01)
        self.assertIn("closed 2 Codex pane(s)", log.call_args[0][0])
        with mock.patch.object(server, "close_old_panes", side_effect=OSError("denied")), \
                mock.patch.object(server, "log") as log:
            server.start_pane_cleanup()
            for _ in range(100):
                if log.called:
                    break
                time.sleep(0.01)
        self.assertIn("skipped: denied", log.call_args[0][0])


def server_agent(text, phase="final_answer"):
    return {"type": "agentMessage", "phase": phase, "text": text}


class FakeScreen:
    """Two screens side by side, the first with a 40-pixel taskbar, and windows that go where
    they are put unless told to refuse (refuse: Windows takes the move but the window stays;
    dead: Windows refuses it, as for a terminal that doesn't respond)."""

    MONITORS = {1: (0, 0, 1920, 1040), 2: (1920, 0, 3840, 1080)}

    def __init__(self):
        self.windows, self.refuse, self.dead, self.blind, self.moves = {}, set(), set(), set(), []

    def add(self, hwnd, rect):
        self.windows[hwnd] = {"rect": rect, "usable": True, "owner": hwnd}

    def owner(self, console):
        return self.windows[console]["owner"] if console in self.windows else 0

    def is_wt(self, hwnd):
        return hwnd in self.windows

    def usable(self, hwnd):
        return self.windows[hwnd]["usable"]

    def rects(self, hwnd):
        r = self.windows[hwnd]["rect"]
        return r, r

    def centre(self, hwnd):
        if hwnd in self.blind:  # its rectangle can't be read just now
            return None
        l, t, r, b = self.windows[hwnd]["rect"]
        return (l + r) // 2, (t + b) // 2

    def monitor_at(self, point):
        return next((m for m, (l, t, r, b) in self.MONITORS.items()
                     if l <= point[0] < r and t <= point[1] < (1080 if m == 1 else b)), 0)

    def monitor_of(self, hwnd):
        l, t, r, b = self.windows[hwnd]["rect"]
        return self.monitor_at(((l + r) // 2, (t + b) // 2)) or 1

    def device(self, monitor):
        return f"DISPLAY{monitor}" if monitor in self.MONITORS else None

    def monitor_named(self, device):
        return next((m for m in self.MONITORS if f"DISPLAY{m}" == device), 0)

    def primary(self):
        return 1

    def work_area(self, monitor):
        return self.MONITORS.get(monitor)

    def scale(self, monitor):
        return 1.0

    def place(self, hwnd, box):
        self.moves.append(hwnd)
        if hwnd in self.dead:
            return False
        if hwnd not in self.refuse:
            self.windows[hwnd]["rect"] = tuple(box)
        return True


class ArrangeTest(unittest.TestCase):
    """0.23.0: nouez arranges the windows it opened in a grid on one screen (Windows)."""

    def setUp(self):
        self.cache = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.cache, True)
        self.starts = {}
        for patch in (mock.patch.object(server, "nouez_cache_dir", return_value=self.cache),
                      mock.patch.object(server, "process_start", side_effect=lambda pid: self.starts.get(pid))):
            patch.start()
            self.addCleanup(patch.stop)
        self.screen = FakeScreen()

    def open(self, hwnd, rect=(100, 100, 900, 600), kind="claude"):
        """A window registered as a helper would: hwnd doubles as its console, pid and slot."""
        self.screen.add(hwnd, rect)
        self.starts[hwnd] = 1000 + hwnd
        server.write_json_atomic(os.path.join(server.windows_folder(create=True), f"{hwnd}-{1000 + hwnd}.json"),
                                 {"hwnd": hwnd, "console": hwnd, "pid": hwnd, "start": 1000 + hwnd,
                                  "kind": kind, "slot": hwnd, "box": None, "left": False})

    def test_the_status_screen_is_never_arranged(self):
        """0.26.2: the status screen's window stays recorded, for OpenStatusScreen to bring it forward,
        but isn't moved and takes no room: the one session window gets the whole screen."""
        self.open(1, (10, 10, 500, 400), kind="status")
        self.open(2, (600, 50, 1200, 500))
        out = server.arrange_pass(self.screen, explicit=True)
        self.assertEqual(out["windows"], 1)
        self.assertEqual(self.where(), {1: (10, 10, 500, 400), 2: (0, 0, 1920, 1040)})
        self.assertEqual([e["hwnd"] for _, e in server.arrange_entries()], [2])
        self.assertEqual([e["hwnd"] for _, e in server.arrange_entries(status=True)], [1, 2])

    def close(self, hwnd):
        del self.starts[hwnd]  # the helper ended
        del self.screen.windows[hwnd]

    def where(self):
        return {h: w["rect"] for h, w in self.screen.windows.items()}

    def test_grid_shapes(self):
        shapes = [server.grid_columns(n, 2560, 1392, 560, 320) for n in range(1, 7)]
        self.assertEqual(shapes, [[1], [1, 1], [1, 2], [2, 2], [1, 2, 2], [2, 2, 2]])
        self.assertEqual(server.grid_columns(9, 1920, 1040, 840, 480), [2, 2])  # only 4 fit at 150%
        self.assertEqual(server.grid_columns(3, 500, 300, 560, 320), [])
        for columns in ([1], [1, 2], [2, 3, 3], [3, 3, 3, 3]):
            boxes = server.grid_boxes(columns, 7, 11, 1001, 703)
            self.assertEqual(len(boxes), sum(columns))
            self.assertEqual(sum((r - l) * (b - t) for l, t, r, b in boxes), 1001 * 703)  # no gap
            for i, a in enumerate(boxes):  # and no overlap
                for b in boxes[i + 1:]:
                    self.assertFalse(a[0] < b[2] and b[0] < a[2] and a[1] < b[3] and b[1] < a[3])

    def test_windows_fill_one_screen_and_close_up(self):
        self.open(1)
        server.arrange_pass(self.screen)
        self.assertEqual(self.where(), {1: (100, 100, 900, 600)})  # one window is left alone
        self.open(2)
        self.open(3)
        out = server.arrange_pass(self.screen)
        self.assertEqual(out["arranged"], 3)
        self.assertEqual(self.where(), {1: (0, 0, 960, 1040), 2: (960, 0, 1920, 520), 3: (960, 520, 1920, 1040)})
        self.close(1)
        server.arrange_pass(self.screen)  # the others move up, in the same order: no swap
        self.assertEqual(self.where(), {2: (0, 0, 960, 1040), 3: (960, 0, 1920, 1040)})
        self.close(2)
        self.close(3)
        server.arrange_pass(self.screen)
        self.assertEqual(os.listdir(server.windows_folder()), [])  # entries and screen.json gone

    def test_moved_by_hand(self):
        for h in (1, 2, 3):
            self.open(h)
        server.arrange_pass(self.screen)
        self.screen.windows[1]["rect"] = (1000, 600, 1900, 1000)  # dropped on window 3's box
        server.arrange_pass(self.screen)
        self.assertEqual(self.where()[3], (0, 0, 960, 1040))
        self.assertEqual(self.where()[1], (960, 520, 1920, 1040))
        self.screen.windows[2]["rect"] = (1000, 60, 1900, 500)  # nudged inside its own box: goes back
        server.arrange_pass(self.screen)
        self.assertEqual(self.where()[2], (960, 0, 1920, 520))
        self.screen.windows[2]["rect"] = (2000, 100, 2800, 600)  # taken to the other screen: stays there
        server.arrange_pass(self.screen)
        self.assertEqual(self.where(), {3: (0, 0, 960, 1040), 1: (960, 0, 1920, 1040), 2: (2000, 100, 2800, 600)})
        server.arrange_pass(self.screen)
        self.assertEqual(self.where()[2], (2000, 100, 2800, 600))
        out = server.arrange_pass(self.screen, explicit=True)  # ArrangeWindows brings it back
        self.assertEqual((out["arranged"], out["left"]), (3, 0))
        self.assertEqual(self.where()[2][2], 1920)

    def test_minimized_and_refusing_windows(self):
        for h in (1, 2, 3):
            self.open(h)
        server.arrange_pass(self.screen)
        self.screen.windows[2]["usable"] = False  # minimized: the others take its room
        out = server.arrange_pass(self.screen)
        self.assertEqual(out["skipped"], 1)
        self.assertEqual(self.where()[3], (960, 0, 1920, 1040))
        self.screen.windows[2]["usable"] = True
        self.screen.windows[2]["owner"] = 3  # its tab was dragged into window 3
        server.arrange_pass(self.screen)
        self.assertEqual(self.where()[3], (960, 0, 1920, 1040))
        self.screen.windows[2]["owner"] = 2
        self.screen.windows[2]["rect"] = (1000, 40, 1800, 480)  # off its box, though not dropped on another
        memory = {}
        self.screen.refuse.add(2)  # a window that won't take its box is tried a few times, then left
        for _ in range(4):
            server.arrange_pass(self.screen, memory=memory)
        self.assertEqual(self.screen.moves.count(2), 1 + server.ARRANGE_TRIES)
        self.assertEqual(self.where()[3], (960, 520, 1920, 1040))  # and it isn't swapped with its neighbour

    def test_screen_is_kept_and_chosen_again(self):
        self.open(1, (2000, 100, 2800, 600))
        self.open(2, (100, 100, 900, 600))
        server.arrange_pass(self.screen)  # the oldest window's screen
        self.assertEqual(self.where(), {1: (1920, 0, 2880, 1080), 2: (2880, 0, 3840, 1080)})
        self.screen.MONITORS = {1: (0, 0, 1920, 1040)}  # that screen was unplugged
        self.screen.windows[1]["rect"], self.screen.windows[2]["rect"] = (0, 0, 900, 500), (900, 0, 1800, 500)
        server.arrange_pass(self.screen)
        self.assertEqual(self.where(), {1: (0, 0, 960, 1040), 2: (960, 0, 1920, 1040)})  # none left the grid

    def entry(self, hwnd):
        with open(os.path.join(server.windows_folder(), f"{hwnd}-{1000 + hwnd}.json"), encoding="utf-8") as f:
            return json.load(f)

    def test_refused_moves_dont_swap_windows_back_and_forth(self):
        for h in (1, 2):
            self.open(h)
        server.arrange_pass(self.screen)
        self.screen.dead.update((1, 2))  # from now on Windows refuses every move
        self.screen.windows[1]["rect"] = (1000, 100, 1900, 900)  # dropped on window 2's box
        memory, slots = {}, []
        for _ in range(5):
            out = server.arrange_pass(self.screen, memory=memory)
            slots.append((self.entry(1)["slot"], self.entry(2)["slot"]))
        self.assertEqual(slots[1:], [slots[0]] * 4)  # swapped once, as asked, then left alone
        self.assertEqual(out["arranged"], 0)  # neither holds its new box, so neither counts
        self.assertEqual([self.screen.moves.count(h) for h in (1, 2)], [1 + server.ARRANGE_TRIES] * 2)
        self.assertEqual([self.entry(h)["box"] for h in (1, 2)], [None, None])

    def test_a_window_is_marked_left_only_when_seen_on_another_screen(self):
        for h in (1, 2):
            self.open(h)
        server.arrange_pass(self.screen)
        self.screen.blind.add(1)  # where it is can't be read: not taken as moved to another screen
        server.arrange_pass(self.screen)
        self.assertFalse(self.entry(1)["left"])
        self.screen.blind.clear()
        self.screen.windows[2]["rect"] = (2000, 100, 2800, 600)  # Windows moved it: screens changed
        server.arrange_pass(self.screen, reconcile=True)
        self.assertFalse(self.entry(2)["left"])
        self.assertEqual(self.where()[2], (960, 0, 1920, 1040))  # back in the grid

    def test_screen_is_pinned_by_its_name(self):
        self.open(1, (2000, 100, 2800, 600))
        self.open(2, (2100, 100, 2900, 600))
        server.arrange_pass(self.screen)
        with open(server.screen_file(), encoding="utf-8") as f:
            self.assertEqual(json.load(f), {"device": "DISPLAY2"})
        # The screens were rearranged: DISPLAY2 is now on the left, where DISPLAY1 was.
        self.screen.MONITORS = {2: (0, 0, 1920, 1080), 1: (1920, 0, 3840, 1040)}
        self.screen.windows[1]["rect"], self.screen.windows[2]["rect"] = (0, 0, 960, 1080), (960, 0, 1920, 1080)
        server.arrange_pass(self.screen)
        self.assertEqual(self.where(), {1: (0, 0, 960, 1080), 2: (960, 0, 1920, 1080)})

    def test_cache_files_are_not_read_or_deleted_through_a_link(self):
        elsewhere = os.path.join(self.cache, "elsewhere.json")
        with open(elsewhere, "w", encoding="utf-8") as f:
            json.dump({"auto": True}, f)
        file_link(self, elsewhere, server.arrange_settings_file())
        self.assertFalse(server.arrange_auto())  # the link isn't read
        os.makedirs(server.windows_folder(create=True), exist_ok=True)
        file_link(self, elsewhere, server.screen_file())
        server.remove_cache_file(server.screen_file())
        server.arrange_pass(self.screen)  # no window: it clears the pin, but not through a link
        self.assertTrue(os.path.exists(elsewhere))

    def test_registering_never_stops_the_window(self):
        with mock.patch.object(server.os, "name", "nt"), \
                mock.patch.object(server.threading.Thread, "start", side_effect=RuntimeError("no threads")):
            self.starts[os.getpid()] = 1
            entry = server.WindowEntry("claude")
            entry.close()
        self.assertIsNone(entry.path)
        with mock.patch.object(server.os, "name", "nt"), \
                mock.patch.object(server, "process_start", side_effect=OSError("denied")):
            server.WindowEntry("status").close()

    @unittest.skipUnless(os.name == "nt", "the arranger runs on Windows only")
    def test_arranger_hands_over_only_after_a_clean_end(self):
        server.write_json_atomic(server.arrange_settings_file(), {"auto": True})
        tag = f"nouez-test-{os.getpid()}"
        for code in (0, 1, RuntimeError("no window")):
            arranger = mock.Mock()
            arranger.return_value.run.side_effect = [code] if isinstance(code, Exception) else None
            arranger.return_value.run.return_value = code
            with mock.patch.object(server, "ARRANGE_MUTEX", "Local\\" + tag + "-m"), \
                    mock.patch.object(server, "ARRANGE_WAKE", "Local\\" + tag + "-w"), \
                    mock.patch.object(server, "Arranger", arranger), \
                    mock.patch.object(server, "arrange_entries", return_value=[("p", {})]), \
                    mock.patch.object(server, "wake_arranger") as wake:
                server.run_arrange([])
            self.assertEqual(wake.call_count, 1 if code == 0 else 0, code)

    def test_dead_and_broken_entries_are_deleted(self):
        self.open(1)
        folder = server.windows_folder()
        with open(os.path.join(folder, "5-6.json"), "w") as f:
            f.write('{"hwnd": "x"}')
        del self.starts[1]
        server.arrange_entries()
        self.assertEqual(os.listdir(folder), [])

    def test_arrange_windows_tool(self):
        if os.name != "nt":
            with self.assertRaises(server.BridgeError) as e:
                server.arrange_windows({})
            self.assertIn("Windows only", str(e.exception))
            return
        for bad in (1, "yes"):
            with self.assertRaises(server.BridgeError):
                server.arrange_windows({"auto": bad})
        self.assertFalse(server.arrange_auto())
        with mock.patch.object(server, "wake_arranger") as wake:
            out = server.arrange_windows({"auto": False})
        wake.assert_called_once_with(start=False)
        self.assertFalse(server.arrange_auto())
        self.assertIn("off", out)
        done = mock.Mock(stdout='{"windows": 3, "arranged": 2, "not_fitting": 1, "left": 0, "skipped": 0}\n')
        with mock.patch.object(server.subprocess, "run", return_value=done) as run, \
                mock.patch.object(server, "wake_arranger") as wake:
            out = server.arrange_windows({})
            self.assertIn("Arranged 2 of the 3", out)
            self.assertIn("is off", out)
            wake.assert_not_called()
            self.assertEqual(run.call_args[0][0][-2:], ["arrange", "--once"])
            run.reset_mock()
            out = server.arrange_windows({"auto": True})
        self.assertEqual(run.call_args[0][0][-2:], ["arrange", "--once"])
        wake.assert_called_once_with()
        self.assertTrue(server.arrange_auto())
        self.assertIn("Arranged 2 of the 3", out)
        self.assertIn("1 didn't fit", out)
        with mock.patch.object(server.subprocess, "run", return_value=mock.Mock(stdout='{"error": "busy"}\n')), \
                self.assertRaises(server.BridgeError):
            server.arrange_windows({})

    def test_only_nouezs_windows_register(self):
        with mock.patch.object(server, "WindowEntry") as entry, \
                mock.patch.object(server, "supervise_top", return_value=0) as top:
            server.run_top(["--arranged", "--days", "7"])
            server.run_top(["--days", "7"])
        top.assert_called_with(["--days", "7"])
        entry.assert_called_once_with("status")
        entry.return_value.close.assert_called_once_with()
        with mock.patch.object(server, "open_window", return_value="a window") as window, \
                mock.patch.object(server, "folder_trusted", return_value=True):
            server.open_claude_session({"cwd": ROOT})
        path = window.call_args[0][1][-1]
        with open(path, encoding="utf-8") as f:
            self.assertIs(json.load(f)["arrange"], True)
        child = mock.Mock(pid=999998)
        child.wait.return_value = 0
        with mock.patch.object(server, "find_program", return_value="claude"), \
                mock.patch.object(server.subprocess, "Popen", return_value=child), \
                mock.patch.object(server, "WindowEntry") as entry:
            server.run_claude(path)
        entry.assert_called_once_with("claude")
        entry.return_value.close.assert_called_once_with()


class FakeClaude:
    """A stand-in for `claude remote-control`: prints `lines`, then exits with `code`, or with
    code None runs until ended."""

    def __init__(self, lines=(), code=0):
        self.stdout = io.BytesIO(b"".join(line.encode() + b"\n" for line in lines))
        self.code, self.pid, self.ended = code, 4242, False

    def poll(self):
        return self.code if self.code is not None else (-15 if self.ended else None)

    def wait(self, timeout=None):
        if self.code is None and not self.ended:
            if timeout is None:
                raise AssertionError("waited forever on a claude that runs until ended")
            time.sleep(min(timeout, 0.01))
            raise subprocess.TimeoutExpired("claude", timeout)
        return self.poll()


class FakeJob:
    def __init__(self):
        self.closed = False

    def assign(self, proc):
        return True

    def resume(self, proc):
        return True

    def close(self):
        self.closed = True


class CountingStop(threading.Event):
    """A stop event whose waits return at once, recorded; it is set after `waits` of them."""

    def __init__(self, waits):
        super().__init__()
        self.waits, self.left = [], waits

    def wait(self, timeout=None):
        self.waits.append(timeout)
        self.left -= 1
        if self.left <= 0:
            self.set()
        return self.is_set()


FAKE_CLAUDE = r'''import os, subprocess, sys, time
folder = os.getcwd()
count = os.path.join(folder, "runs")
n = int(open(count).read()) + 1 if os.path.exists(count) else 1
open(count, "w").write(str(n))
open(os.path.join(folder, "argv"), "w").write(" ".join(sys.argv[1:]))
out = sys.stdout.buffer
out.write("\u00b7|\u00b7 Connecting \u00b7 dispatcher\r".encode())
out.flush()
left = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(120)"])
open(os.path.join(folder, "left-%d" % n), "w").write(str(left.pid))
out.write("\u00b7\u2714\ufe0e\u00b7 Connected \u00b7 dispatcher\n".encode())
out.flush()
go = os.path.join(folder, "go-%d" % n)  # the first run ends once the test has seen it
deadline = time.time() + (60 if n == 1 else 120)
while time.time() < deadline and not (n == 1 and os.path.exists(go)):
    time.sleep(0.05)
sys.exit(3)
'''  # a stand-in claude for the supervisor


class DispatcherTest(unittest.TestCase):
    """0.23.0: `server.py dispatcher` keeps Claude Code's Remote Control server running for the
    phone app, and installs itself to start at sign-in on Windows, macOS and Linux."""

    def setUp(self):
        self.home = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.home, True)
        self.cache = os.path.join(self.home, "cache")
        self.projects = os.path.join(self.home, "Projects")
        os.makedirs(self.projects)
        self.folder = os.path.join(self.projects, "dispatcher")
        os.makedirs(self.cache)
        for patch in (mock.patch.object(server, "nouez_cache_dir", return_value=self.cache),
                      mock.patch.object(server, "_dispatcher_root", [self.cache]),
                      mock.patch.object(server, "dispatcher_default_folder", lambda: self.folder),
                      mock.patch.object(server, "dispatcher_installed", _REAL_DISPATCHER["dispatcher_installed"]),
                      mock.patch.object(server, "other_remote_controls", lambda own=None: []),
                      mock.patch.object(server, "consultants_registered", lambda folder: True),
                      mock.patch.object(server, "dispatcher_trusted", lambda folder, state_file=None: False),
                      mock.patch.object(server, "_dispatcher_seen", [0.0, (False, None)]),
                      mock.patch.object(server, "nouez_script", lambda path: "other" not in path)):
            patch.start()
            self.addCleanup(patch.stop)

    def read(self, name):
        with open(os.path.join(self.cache, name), encoding="utf-8") as f:
            return f.read()

    def state(self):
        return json.loads(self.read("dispatcher.json"))

    # --- running claude ---

    def test_claude_is_found_where_its_installer_puts_it(self):
        bin_dir = os.path.join(self.home, ".local", "bin")
        os.makedirs(bin_dir)
        exe = os.path.join(bin_dir, "claude.exe" if os.name == "nt" else "claude")
        with open(exe, "w") as f:
            f.write("")
        os.chmod(exe, 0o755)
        with mock.patch.object(server, "which", lambda name, env=None: None), \
                mock.patch.object(server, "claude_install_folders", lambda: [bin_dir]):
            self.assertEqual(server.dispatcher_claude(), exe)
            os.remove(exe)
            self.assertIsNone(server.dispatcher_claude())
        with mock.patch.object(server, "which", lambda name, env=None: "/bin/claude"):
            self.assertEqual(server.dispatcher_claude(), "/bin/claude")

    def test_output_is_logged_once_and_tells_when_it_connects(self):
        state = server.DispatcherState(self.folder)
        state.save(claude_pid=1)
        linked = threading.Event()
        redraws = "\x1b[2K\r\x1b[32m·✔︎· Connected · dispatcher\x1b[0m\r" * 3
        lines = [b"Remote Control starting\n", redraws.encode() + b"\n", b"Remote Control starting\n",
                 "·|· Reconnecting · dispatcher\n".encode(), redraws.encode() + b"\n"]
        server.dispatcher_output(io.BytesIO(b"".join(lines)), state, linked)
        self.assertTrue(linked.is_set())
        log = self.read("dispatcher-claude.log")
        self.assertEqual(log.count("Connected · dispatcher"), 1, log)
        self.assertEqual(log.count("Remote Control starting"), 1, log)
        self.assertNotIn("\x1b", log)
        self.assertEqual(self.state()["phase"], "connected")
        self.assertIn("lost Remote Control", self.read("dispatcher.log"))
        self.assertIsNotNone(self.state()["connected_since"])

    def test_a_word_that_merely_contains_connected_doesnt_count(self):
        state = server.DispatcherState(self.folder)
        state.save(claude_pid=1)
        linked = threading.Event()
        text = (b"Not yet Disconnected\nUnconnected peers: 0\nWaiting for Connected status\n"
                b"Connectedness check failed\nConnected\n")
        server.dispatcher_output(io.BytesIO(text), state, linked)
        self.assertFalse(linked.is_set())
        self.assertFalse(self.state()["connected"])

    def test_only_the_status_line_says_whether_claude_is_connected(self):
        """0.23.0: the line claude remote-control redraws, `·✔︎· Connected · dispatcher`; a line that
        only mentions the word, or a status cut off before the name begins, says nothing."""
        for line, want in (("·✔︎· Connected · dispatcher", True), ("·✔︎· Reconnected · dispatcher", True),
                           ("·|· Connecting · dispatcher", False), ("·|· Reconnecting · dispatcher", False),
                           ("·|· Disconnected · dispatcher", False), ("Not connected · dispatcher", False),
                           ("·✔︎· Connected · d", True), ("·✔︎· Connected", None), ("·✔︎· Connected · ", None),
                           ("Connected", None), ("Waiting for Connected status", None),
                           ("Connectedness check failed", None), ("Not yet Disconnected", None),
                           ("Status: Connected · fine", None), ("", None)):
            self.assertIs(server.dispatcher_link(line), want, line)

    def test_a_status_redrawn_with_no_line_end_is_read_at_once(self):
        """0.23.0: claude redraws its status with carriage returns and never ends the line; the
        reader sees it while the pipe is still open."""
        state = server.DispatcherState(self.folder)
        run = state.begin(1)
        linked = threading.Event()
        r, w = os.pipe()
        stream = os.fdopen(r, "rb")
        self.addCleanup(stream.close)
        reader = threading.Thread(target=server.dispatcher_output, args=(stream, state, linked, run), daemon=True)
        reader.start()
        try:
            os.write(w, "\x1b[2K\r\x1b[32m·✔︎· Connected · dispatcher\x1b[0m\r".encode())
            self.assertTrue(linked.wait(5))
            self.assertTrue(self.state()["connected"])
        finally:
            os.close(w)
            reader.join(5)
        self.assertFalse(reader.is_alive())

    def test_not_connected_is_down_and_an_old_run_changes_nothing(self):
        state = server.DispatcherState(self.folder)
        run = state.begin(1)
        linked = threading.Event()
        server.dispatcher_output(io.BytesIO("·✔︎· Connected · dispatcher\n·|· Not connected · dispatcher\n".encode()),
                                 state, linked, run)
        self.assertEqual(self.state()["phase"], "reconnecting")
        state.end(0)
        state.begin(2)
        self.assertFalse(state.link(True, run))  # the reader of the run before
        self.assertFalse(self.state()["connected"])

    @unittest.skipIf(not hasattr(os, "mkfifo"), "needs pipes in the file system")
    def test_logs_are_never_written_through_a_pipe_or_a_link(self):
        os.makedirs(self.cache, exist_ok=True)
        path = os.path.join(self.cache, "dispatcher.log")
        os.mkfifo(path)
        writer = threading.Thread(target=server.append_capped, args=(path, "line"), daemon=True)
        writer.start()
        writer.join(5)
        self.assertFalse(writer.is_alive(), "waited on a pipe")
        os.remove(path)
        secret = os.path.join(self.home, "secret")
        with open(secret, "w") as f:
            f.write("private words")
        os.symlink(secret, path)
        server.append_capped(path, "line")
        with open(secret) as f:
            self.assertEqual(f.read(), "private words")
        out = []
        server.dispatcher_status_text(out.append)
        self.assertNotIn("private words", "\n".join(out))
        os.remove(path)
        with open(path, "w") as f:
            f.write("x" * 100)
        os.symlink(secret, path + ".1")
        server.append_capped(path, "line", cap=10)  # no move onto a link
        self.assertTrue(os.path.islink(path + ".1"))
        with open(secret) as f:
            self.assertEqual(f.read(), "private words")

    @unittest.skipIf(os.name == "nt", "process groups")
    def test_ending_claude_ends_what_it_left_running(self):
        """0.23.0: claude, exited already, is collected only after the last signal to its group,
        and only once nothing else runs in it; a member that has ended but that nobody has
        collected yet (an orphan waiting on PID 1) doesn't count."""
        proc = subprocess.Popen(["sh", "-c", "sleep 60 & echo $!; exit 0"], start_new_session=True,
                                stdout=subprocess.PIPE)
        self.addCleanup(proc.stdout.close)
        child = int(proc.stdout.readline())
        deadline = time.monotonic() + 10
        while not server.exited_unreaped(proc):
            self.assertLess(time.monotonic(), deadline)
            time.sleep(0.05)
        self.assertIsNone(proc.returncode)  # exited, not collected: its id is still its group's
        self.assertIn(child, server.group_members(proc.pid, proc.pid))
        server.end_dispatcher_claude(proc)
        self.assertEqual(proc.returncode, 0)
        self.assertEqual(server.group_members(proc.pid, proc.pid), [])

    @unittest.skipIf(os.name == "nt", "process groups")
    def test_an_exit_is_seen_without_collecting_the_process(self):
        proc = subprocess.Popen(["sh", "-c", "exit 3"])
        deadline = time.monotonic() + 10
        while not server.exited_unreaped(proc):
            self.assertLess(time.monotonic(), deadline)
            time.sleep(0.05)
        self.assertIsNone(proc.returncode)
        os.kill(proc.pid, 0)  # still there, uncollected
        self.assertEqual(proc.wait(5), 3)
        self.assertTrue(server.exited_unreaped(proc))

    @unittest.skipIf(not hasattr(os, "waitid"), "waitid")
    def test_a_stopped_claude_hasnt_exited(self):
        proc = subprocess.Popen(["sh", "-c", "sleep 30"])
        self.addCleanup(lambda: (proc.kill(), proc.wait()))
        stopped = mock.Mock(si_code=os.CLD_STOPPED)
        with mock.patch.object(server.os, "waitid", lambda *a: stopped):
            self.assertFalse(server.exited_unreaped(proc))
        with mock.patch.object(server.os, "waitid", lambda *a: mock.Mock(si_code=os.CLD_KILLED)):
            self.assertTrue(server.exited_unreaped(proc))

    @unittest.skipIf(os.name == "nt", "macOS and Linux")
    def test_an_exit_is_never_collected_to_see_it(self):
        """0.23.0: when waitid can't look, the process table tells of claude's exit, and claude
        isn't collected meanwhile, so its group's id stays its own."""
        proc = subprocess.Popen(["sh", "-c", "exit 3"])
        deadline = time.monotonic() + 10
        while not server.is_zombie(proc.pid):
            self.assertLess(time.monotonic(), deadline)
            time.sleep(0.05)

        def denied(*a):
            raise PermissionError("denied")
        with mock.patch.object(server.os, "waitid", denied, create=True):
            self.assertTrue(server.exited_unreaped(proc))
            with mock.patch.object(server, "is_zombie", lambda pid: False):
                self.assertFalse(server.exited_unreaped(proc))
        self.assertIsNone(proc.returncode)
        self.assertEqual(proc.wait(5), 3)
        running = subprocess.Popen(["sh", "-c", "sleep 30"])
        self.addCleanup(lambda: (running.kill(), running.wait()))
        self.assertFalse(server.is_zombie(running.pid))

    @unittest.skipIf(os.name == "nt", "macOS and Linux")
    def test_a_claude_collected_elsewhere_isnt_signalled(self):
        """0.23.0: claude collected by something else (SIGCHLD ignored, say) may have left its id to
        another process: its group isn't signalled. The supervisor doesn't ignore SIGCHLD."""
        proc = subprocess.Popen(["sh", "-c", "exit 0"])
        proc.wait(5)
        proc.returncode = None  # as if collected by something else

        def gone(*a):
            raise ChildProcessError("no child")
        with mock.patch.object(server.os, "waitid", gone, create=True), \
                mock.patch.object(server.select, "kqueue", None, create=True), \
                mock.patch.object(server.os, "killpg") as killpg:
            server.end_dispatcher_claude(proc)
        killpg.assert_not_called()
        self.assertTrue(proc._nouez_lost)
        self.assertIn("its group isn't signalled", self.read("dispatcher.log"))
        if threading.current_thread() is threading.main_thread():
            saved = {s: signal.getsignal(s) for s in (signal.SIGTERM, signal.SIGHUP, signal.SIGINT, signal.SIGCHLD)}
            self.addCleanup(lambda: [signal.signal(s, h) for s, h in saved.items()])
            signal.signal(signal.SIGCHLD, signal.SIG_IGN)
            with mock.patch.object(server, "supervisor_job", lambda: (None, None)), \
                    mock.patch.object(server, "dispatcher_may_start", lambda *a: False):
                self.assertEqual(server.run_dispatcher_supervisor(self.folder), 0)
            self.assertEqual(signal.getsignal(signal.SIGCHLD), signal.SIG_DFL)

    @unittest.skipIf(not hasattr(server.select, "kqueue"), "kqueue (macOS)")
    def test_a_kqueue_that_cant_be_made_leaves_claude_uncollected(self):
        """0.23.0: out of descriptors, say: the process table tells of the exit instead."""
        proc = subprocess.Popen(["sh", "-c", "exit 3"])

        def full():
            raise OSError(24, "Too many open files")
        with mock.patch.object(server.select, "kqueue", full):
            deadline = time.monotonic() + 10
            while not server.exited_kqueue(proc):
                self.assertLess(time.monotonic(), deadline)
                time.sleep(0.05)
        self.assertIsNone(proc.returncode)
        self.assertEqual(proc.wait(5), 3)

    @unittest.skipIf(not hasattr(server.select, "kqueue"), "kqueue (macOS)")
    def test_an_exit_is_seen_through_a_kqueue_without_collecting(self):
        """0.23.0: macOS before Python 3.13 has no waitid: a kqueue tells of the exit, both for a
        claude watched while it runs and for one that has exited before the first look."""
        for pause in (0, 0.5):
            proc = subprocess.Popen(["sh", "-c", "sleep 0.2; exit 3"])
            time.sleep(pause)
            deadline = time.monotonic() + 10
            while not server.exited_kqueue(proc):
                self.assertLess(time.monotonic(), deadline, pause)
                time.sleep(0.05)
            self.assertIsNone(proc.returncode, pause)
            os.kill(proc.pid, 0)  # still there, uncollected
            self.assertTrue(server.exited_kqueue(proc))
            self.assertEqual(proc.wait(5), 3)

    @unittest.skipIf(os.name != "nt", "Windows jobs")
    def test_a_job_holds_claude_from_its_start_and_ends_what_it_started(self):
        job = server.KillOnCloseJob()
        code = ("import subprocess, sys, time; p = subprocess.Popen([sys.executable, '-c', 'import time; "
                "time.sleep(60)']); print(p.pid, flush=True); time.sleep(60)")
        proc = subprocess.Popen([sys.executable, "-c", code], stdout=subprocess.PIPE,
                                creationflags=subprocess.CREATE_NO_WINDOW | 0x4)
        self.addCleanup(proc.kill)
        self.assertTrue(job.assign(proc))
        self.assertTrue(job.resume(proc))
        child = int(proc.stdout.readline())
        proc.stdout.close()
        server.end_dispatcher_claude(proc, job)
        self.assertIsNotNone(proc.wait(5))
        alive = subprocess.run(["tasklist", "/FI", f"PID eq {child}", "/NH"], capture_output=True, text=True).stdout
        self.assertNotIn(str(child), alive)
        job.close()  # again: nothing happens

    @unittest.skipIf(os.name != "nt", "Windows jobs")
    def test_a_named_job_tells_processes_theyre_under_the_supervisor(self):
        """0.23.0: the supervisor's own job is named in dispatcher.json; what runs in it knows it is
        under the dispatcher, and only there leaves its job for the windows it starts."""
        name = f"Local\\nouez-dispatcher-test-{os.getpid()}-{time.time_ns()}"
        job = server.KillOnCloseJob(name)
        self.addCleanup(job.close)
        with self.assertRaises(OSError):
            server.KillOnCloseJob(name)  # someone else's of that name is never joined
        server.DispatcherState(self.folder, job=name).save()
        code = (f"import sys; sys.path.insert(0, {ROOT!r}); import server; "
                f"server._dispatcher_root[:] = [{self.cache!r}]; print(server.in_dispatcher_job())")
        inside = subprocess.Popen([sys.executable, "-I", "-c", code], stdout=subprocess.PIPE, text=True,
                                  creationflags=subprocess.CREATE_NO_WINDOW | 0x4)
        self.addCleanup(inside.kill)
        self.assertTrue(job.assign(inside))
        self.assertTrue(job.resume(inside))
        self.assertEqual(inside.communicate(timeout=60)[0].strip(), "True")
        outside = subprocess.run([sys.executable, "-I", "-c", code], capture_output=True, text=True, timeout=60)
        self.assertEqual(outside.stdout.strip(), "False")

    def test_what_nouez_starts_leaves_its_job_only_under_the_dispatcher(self):
        flags = []

        def popen(argv, **kwargs):
            flags.append(kwargs.get("creationflags", 0))
            return mock.Mock()
        with mock.patch.object(server.os, "name", "nt"), mock.patch.object(server.subprocess, "Popen", popen):
            for under in (False, True):
                with mock.patch.object(server, "in_dispatcher_job", lambda: under):
                    server.popen_outside_job(["x"], creationflags=0x10)
            with mock.patch.object(server, "in_dispatcher_job", lambda: False):
                server.popen_outside_job(["x"], always=True, creationflags=0x10)
        self.assertEqual(flags, [0x10, 0x10 | 0x01000000, 0x10 | 0x01000000])
        self.assertFalse(server.in_dispatcher_job())  # no supervisor's job named here

    def test_the_dispatchers_folder_follows_no_environment_variable(self):
        """0.23.0: the supervisor started at sign-in and the commands run from any shell use the same
        files, whatever LOCALAPPDATA or XDG_CACHE_HOME say."""
        elsewhere = os.path.join(self.home, "elsewhere")
        with mock.patch.object(server, "_dispatcher_root", []), \
                mock.patch.dict(server.os.environ, {"LOCALAPPDATA": elsewhere, "XDG_CACHE_HOME": elsewhere}):
            if os.name == "nt":
                with mock.patch.object(server, "known_folder",
                                       lambda known: self.home if known == server.FOLDERID_LOCAL_APPDATA else None):
                    found = server.dispatcher_dir()
                self.assertEqual(found, os.path.join(self.home, "nouez"))
                self.assertTrue(server.plain_folder(found))
                self.assertTrue(server.rooted(server.known_folder(server.FOLDERID_LOCAL_APPDATA)))
                self.assertTrue(server.rooted(server.known_folder(server.FOLDERID_DOWNLOADS)))
            else:
                import pwd
                with mock.patch.object(pwd, "getpwuid", lambda uid: mock.Mock(pw_dir=self.home)):
                    found = server.dispatcher_dir()
                self.assertEqual(found, os.path.join(self.home, ".cache", "nouez"))
                self.assertEqual(os.stat(found).st_mode & 0o777, 0o700)
            self.assertEqual(server.dispatcher_file("dispatcher.lock"), os.path.join(found, "dispatcher.lock"))
        self.assertFalse(os.path.exists(elsewhere))

    def test_the_claude_environment(self):
        exe = os.path.join(self.home, "bin", "claude")
        env = server.dispatcher_env(exe, self.home, {"PATH": os.pathsep.join(["/usr/bin", "/bin"]), "CLAUDECODE": "1"})
        self.assertEqual(env["PATH"].split(os.pathsep)[0], os.path.dirname(exe))
        self.assertEqual(env["CLAUDE_CONFIG_DIR"], self.home)
        self.assertNotIn("CLAUDECODE", env)
        env = server.dispatcher_env(exe, None, {"PATH": os.path.dirname(exe)})
        self.assertEqual(env["PATH"], os.path.dirname(exe))
        self.assertNotIn("CLAUDE_CONFIG_DIR", env)
        self.assertNotIn("NOUEZ_DISPATCHER_PROJECTS", env)
        env = server.dispatcher_env(exe, None, {"PATH": ""}, projects=[self.home])
        self.assertEqual((env["NOUEZ_DISPATCHER"], env["NOUEZ_DISPATCHER_PROJECTS"]), ("1", self.home))
        # 0.27.0: several, or none, as a JSON list; one stays its path, as a 0.26 supervisor passes it.
        two = [self.home, self.cache]
        self.assertEqual(server.dispatcher_env(exe, None, {"PATH": ""}, projects=two)["NOUEZ_DISPATCHER_PROJECTS"],
                         json.dumps(two))
        self.assertEqual(server.dispatcher_env(exe, None, {"PATH": ""}, projects=[])["NOUEZ_DISPATCHER_PROJECTS"],
                         "[]")
        # Neither reaches a session the dispatcher opens.
        self.assertFalse({"NOUEZ_DISPATCHER", "NOUEZ_DISPATCHER_PROJECTS"} & set(server.fresh_claude_env(env)))

    def test_a_log_that_cant_move_aside_stops_growing(self):
        path = os.path.join(self.cache, "dispatcher.log")
        os.makedirs(path + ".1")  # not a regular file: nothing is moved onto it
        for i in range(30):
            server.append_capped(path, f"line {i} " + "x" * 50, cap=500)
        self.assertLessEqual(os.path.getsize(path), 500 + 100)
        self.assertTrue(os.path.isdir(path + ".1"))

    def test_logs_move_aside_past_their_cap(self):
        path = os.path.join(self.cache, "dispatcher.log")
        for i in range(30):
            server.append_capped(path, f"line {i} " + "x" * 50, cap=500)
        self.assertTrue(os.path.isfile(path + ".1"))
        self.assertLessEqual(os.path.getsize(path), 500 + 100)
        self.assertIn("line 29", self.read("dispatcher.log"))

    def run_supervisor(self, procs, stop, connect_within=None, job=FakeJob):
        os.makedirs(self.folder, exist_ok=True)
        started = []

        def popen(argv, **kwargs):
            started.append((argv, kwargs))
            return procs.pop(0)
        patches = [mock.patch.object(server, "dispatcher_claude", lambda env=None: "/bin/claude"),
                   mock.patch.object(server, "KillOnCloseJob", job),
                   mock.patch.object(server, "end_dispatcher_claude",
                                     lambda proc, job=None: setattr(proc, "ended", True))]
        if connect_within is not None:
            patches.append(mock.patch.object(server, "DISPATCHER_CONNECT_WITHIN", connect_within))
        with contextlib.ExitStack() as stack:
            for p in patches:
                stack.enter_context(p)
            code = server.supervise_dispatcher(self.folder, stop, popen=popen)
        return code, started

    def test_a_claude_that_ends_at_once_is_started_again_later_not_in_a_loop(self):
        stop = CountingStop(3)
        code, started = self.run_supervisor([FakeClaude(code=1) for _ in range(3)], stop)
        self.assertEqual(code, 0)
        self.assertEqual(stop.waits, [30, 60, 120])  # doubling from 30 s, each wait interruptible
        argv, kwargs = started[0]
        self.assertEqual(argv, ["/bin/claude", "remote-control", "--name", "dispatcher", "--spawn", "same-dir"])
        self.assertEqual(kwargs["cwd"], self.folder)
        self.assertIs(kwargs["stdin"], subprocess.DEVNULL)
        self.assertNotIn("CLAUDECODE", kwargs["env"])
        self.assertTrue(kwargs.get("start_new_session") or kwargs.get("creationflags"))
        self.assertEqual(self.state()["phase"], "stopped")
        self.assertIn("claude exited with code 1", self.read("dispatcher.log"))

    def test_a_long_run_resets_the_wait(self):
        stop = CountingStop(3)
        clock = iter(range(0, 10 ** 6, 400))  # each look at the clock is 400 s on
        with mock.patch.object(server.time, "monotonic", lambda: next(clock)):
            self.run_supervisor([FakeClaude(code=0) for _ in range(3)], stop)
        self.assertEqual(stop.waits, [30, 30, 30])

    def test_a_claude_not_connected_in_time_is_ended(self):
        stop = CountingStop(1)
        claude = FakeClaude(["Do you trust this folder?"], code=None)
        self.run_supervisor([claude], stop, connect_within=0)
        self.assertTrue(claude.ended)
        self.assertIn("isn't connected after 0 s; ending it", self.read("dispatcher.log"))

    def test_stopping_ends_claude(self):
        stop = threading.Event()

        class Stopped(FakeClaude):  # stopped once claude runs: Windows waits on it, elsewhere it is polled
            def wait(self, timeout=None):
                stop.set()
                return super().wait(timeout)

            def poll(self):
                stop.set()
                return super().poll()
        claude = Stopped(["·✔︎· Connected · dispatcher"], code=None)
        code, _ = self.run_supervisor([claude], stop)
        self.assertEqual(code, 0)
        self.assertTrue(claude.ended)
        self.assertIn("stopping claude", self.read("dispatcher.log"))

    def test_an_untied_claude_is_ended_not_left_behind(self):
        class NoJob(FakeJob):
            def assign(self, proc):
                return False
        os.makedirs(self.folder)
        claude = FakeClaude(code=None)
        state = server.DispatcherState(self.folder)
        jobs, envs = [], []
        with mock.patch.object(server, "dispatcher_claude", lambda env=None: "/bin/claude"), \
                mock.patch.object(server, "end_dispatcher_claude", lambda proc, job=None: setattr(proc, "ended", True)):
            self.assertIsNone(server.run_dispatcher_once(self.folder, threading.Event(), state,
                                                         popen=lambda argv, **kw: envs.append(kw["env"]) or claude,
                                                         new_job=lambda: jobs.append(NoJob()) or jobs[-1]))
        self.assertTrue(claude.ended)
        self.assertTrue(jobs[0].closed)
        # 0.26.1: its nouez learns the projects folder, the only place it records trust.
        self.assertEqual(envs[0]["NOUEZ_DISPATCHER_PROJECTS"], os.path.dirname(self.folder))

    def test_each_run_has_its_own_job(self):
        jobs = []

        def new_job():
            jobs.append(FakeJob())
            return jobs[-1]
        with mock.patch.object(server.os, "name", "nt"), \
                mock.patch.object(server.subprocess, "CREATE_NO_WINDOW", 0x08000000, create=True):
            self.run_supervisor([FakeClaude(code=1) for _ in range(2)], CountingStop(2), job=new_job)
        self.assertEqual(len(jobs), 2)
        self.assertTrue(all(job.closed for job in jobs))

    def test_one_supervisor_at_a_time(self):
        with server.FileLock(os.path.join(self.cache, "dispatcher.lock"), 0, "busy"), \
                mock.patch.object(server, "FileLock", lambda path, seconds, busy: _REAL_FILELOCK(path, 0, busy)), \
                mock.patch.object(server, "supervise_dispatcher") as supervise:
            self.assertEqual(server.run_dispatcher_supervisor(self.folder), 0)
        supervise.assert_not_called()
        self.assertIn("another dispatcher supervisor is running", self.read("dispatcher.log"))

    def start_supervisor(self, sign_in=True):
        """run_dispatcher_supervisor in a thread, with supervise_dispatcher recorded, not run."""
        os.makedirs(self.folder, exist_ok=True)
        calls, result = [], []
        patches = [mock.patch.object(server, "supervise_dispatcher",
                                     lambda folder, stop, config_dir=None, state=None: calls.append(state) or 0),
                   mock.patch.object(server, "supervisor_job", lambda: (None, None))]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)
        thread = threading.Thread(target=lambda: result.append(
            server.run_dispatcher_supervisor(self.folder, None, sign_in)), daemon=True)
        thread.start()
        return thread, calls, result

    def wait_for_state(self, **want):
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            with contextlib.suppress(OSError, ValueError, KeyError):
                state = self.state()
                if all(state.get(k) == v for k, v in want.items()):
                    return state
            time.sleep(0.05)
        self.fail(f"dispatcher.json never showed {want}")

    def test_a_supervisor_waits_for_install_and_heeds_a_stop_meanwhile(self):
        """0.23.0: a supervisor holds back claude while an install or uninstall works; one asked to
        stop meanwhile exits without starting it."""
        with server.FileLock(os.path.join(self.cache, "dispatcher-install.lock"), 0, "busy"):
            thread, calls, result = self.start_supervisor()
            state = self.wait_for_state(sign_in=True, phase="starting")
            self.assertTrue(server.wait_for_supervisor(self.folder, None, state["since"], seconds=0))
            self.assertTrue(server.wait_for_supervisor(self.folder, None, state["since"], pid=os.getpid(), seconds=0))
            self.assertFalse(server.wait_for_supervisor(self.folder, None, state["since"], pid=os.getpid() + 1,
                                                        seconds=0))
            self.assertEqual(server.wait_for_supervisor(self.folder, self.home, state["since"], seconds=0), "other")
            self.assertEqual(server.wait_for_supervisor(self.home, None, state["since"], seconds=0), "other")
            others = []
            self.assertEqual(server.wait_for_supervisor(self.home, None, state["since"], seconds=0, others=others),
                             "other")
            self.assertEqual(others, [(os.getpid(), state["since"])])
            self.assertFalse(server.wait_for_supervisor(self.home, None, state["since"], seconds=0, others=others))
            self.assertFalse(server.wait_for_supervisor(self.folder, None, state["since"], seconds=0, others=others))
            self.assertFalse(server.wait_for_supervisor(self.folder, None, state["since"] + 5, seconds=0))
            with open(os.path.join(self.cache, "dispatcher.stop"), "w"):
                pass
            thread.join(10)
        self.assertEqual(result, [0])
        self.assertEqual(calls, [])
        self.assertEqual(self.state()["phase"], "stopped")
        self.assertIn("asked to stop before claude started", self.read("dispatcher.log"))

    def test_a_sign_in_start_that_comes_after_uninstall_exits(self):
        with mock.patch.object(server, "dispatcher_installed", lambda check_off=True, want=None: "no"):
            thread, calls, result = self.start_supervisor()
            thread.join(10)
        self.assertEqual((result, calls), ([0], []))
        self.assertIn("sign-in start is gone", self.read("dispatcher.log"))

    def test_a_supervisor_deletes_a_stale_stop_request_and_starts(self):
        request = os.path.join(self.cache, "dispatcher.stop")
        with open(request, "w"):
            pass
        with mock.patch.object(server, "dispatcher_installed", lambda check_off=True, want=None: "yes"):
            thread, calls, result = self.start_supervisor()
            thread.join(10)
        self.assertEqual(result, [0])
        self.assertEqual(len(calls), 1)
        self.assertIs(calls[0].value["sign_in"], True)
        self.assertFalse(os.path.lexists(request))
        thread, calls, result = self.start_supervisor(sign_in=False)  # by hand: no sign-in start needed
        thread.join(10)
        self.assertEqual((result, len(calls)), ([0], 1))

    def test_a_stop_request_that_isnt_a_plain_file(self):
        """0.23.0: a folder or a link named dispatcher.stop is no request: a supervisor doesn't start,
        install and uninstall say so, and doctor and status show it."""
        request = os.path.join(self.cache, "dispatcher.stop")
        os.makedirs(request)
        thread, calls, result = self.start_supervisor()
        thread.join(10)
        self.assertEqual((result, calls), ([0], []))
        self.assertIn("isn't a plain file", self.read("dispatcher.log"))
        stop = threading.Event()
        watcher = threading.Thread(target=server.watch_stop_request, args=(request, stop), daemon=True)
        watcher.start()
        time.sleep(1.5)
        self.assertFalse(stop.is_set())
        stop.set()
        watcher.join(5)
        out = []
        with server.FileLock(os.path.join(self.cache, "dispatcher.lock"), 0, "busy"):
            self.assertFalse(server.stop_dispatcher(out.append, seconds=5))
        self.assertIn("isn't a plain file", out[-1])
        self.assertTrue(os.path.isdir(request))
        self.assertTrue(any("dispatcher.stop isn't a plain file" in p for p in server.dispatcher_cache_problems()))
        out = []
        server.dispatcher_status_text(out.append)
        self.assertTrue(any(line.startswith("Problem:") for line in out), out)

    def test_the_supervisor_end_to_end(self):
        """0.23.0: the real supervisor, in a process of its own, against a stand-in claude that
        prints the status line and leaves a process running: the first run exits with code 3, what
        it left is ended before the second starts, and a stop request ends the supervisor, the
        second run and what that left."""
        os.makedirs(self.folder, exist_ok=True)
        bin_dir = os.path.join(self.home, "bin")
        os.makedirs(bin_dir)
        fake = os.path.join(bin_dir, "fake_claude.py")
        with open(fake, "w", encoding="utf-8") as f:
            f.write(FAKE_CLAUDE)
        if os.name == "nt":
            with open(os.path.join(bin_dir, "claude.cmd"), "w") as f:
                f.write(f'@"{sys.executable}" "{fake}" %*\n@exit /b %errorlevel%\n')
        else:
            launcher = os.path.join(bin_dir, "claude")
            with open(launcher, "w") as f:
                f.write(f'#!/bin/sh\nexec "{sys.executable}" "{fake}" "$@"\n')
            os.chmod(launcher, 0o755)
        code = (f"import sys; sys.path.insert(0, {ROOT!r}); import server; "
                f"server._dispatcher_root[:] = [{self.cache!r}]; server.DISPATCHER_FIRST_WAIT = 1; "
                f"sys.exit(server.run_dispatcher_supervisor({self.folder!r}))")
        env = {**os.environ, "PATH": bin_dir + os.pathsep + os.environ.get("PATH", "")}
        supervisor = subprocess.Popen([sys.executable, "-I", "-c", code], env=env,
                                      **({"creationflags": subprocess.CREATE_NO_WINDOW} if os.name == "nt" else {}))
        self.addCleanup(lambda: supervisor.poll() is None and supervisor.kill())

        def alive(pid):
            if os.name == "nt":
                return pid in server.process_table()
            seen = subprocess.run(["ps", "-o", "stat=", "-p", str(pid)], capture_output=True, text=True).stdout
            return bool(seen.strip()) and not seen.strip().startswith("Z")

        def until(check, what, seconds=60):
            deadline = time.monotonic() + seconds
            while time.monotonic() < deadline:
                with contextlib.suppress(OSError, ValueError, KeyError):
                    found = check()
                    if found:
                        return found
                self.assertIsNone(supervisor.poll(), f"the supervisor exited while waiting for {what}")
                time.sleep(0.1)
            self.fail(f"never saw {what}; log: {self.read('dispatcher.log')}")
        def text(name):
            with open(os.path.join(self.folder, name)) as f:
                return f.read()
        first = until(lambda: self.state()["connected"] and self.state()["claude_pid"], "the first run connected")
        left = [int(text("left-1"))]
        with open(os.path.join(self.folder, "go-1"), "w"):
            pass
        until(lambda: text("runs") == "2" and os.path.exists(os.path.join(self.folder, "left-2")), "the second run")
        self.assertFalse(alive(left[0]), "the first run's leftover process outlived it")
        second = until(lambda: self.state()["connected"] and self.state()["claude_pid"] != first
                       and self.state()["claude_pid"], "the second run connected")
        left.append(int(text("left-2")))
        self.assertEqual(text("argv"), " ".join(server.DISPATCHER_ARGS))
        self.assertIn("claude exited with code 3", self.read("dispatcher.log"))
        out = []
        self.assertTrue(server.stop_dispatcher(out.append, seconds=60), out)
        self.assertEqual(supervisor.wait(30), 0)
        until(lambda: not any(alive(pid) for pid in (second, *left)), "everything the runs started end", 15)
        state = self.state()
        self.assertEqual((state["phase"], state["connected"], state["claude_pid"]), ("stopped", False, None))
        self.assertFalse(os.path.lexists(os.path.join(self.cache, "dispatcher.stop")))

    def test_status_summary_and_badge(self):
        scr = mock.Mock(paint=lambda text, colour: f"<{colour}>{text}")
        self.assertEqual(server.dispatcher_status(), (False, None))
        self.assertEqual(server.dispatcher_badge(scr), "")
        state = server.DispatcherState(self.folder)
        state.save(phase="connected", connected=True, connected_since=time.time())
        with server.FileLock(os.path.join(self.cache, "dispatcher.lock"), 0, "busy"):
            running, found = server.dispatcher_status()
            self.assertIs(running, True)
            self.assertIn("connected to Remote Control since", server.dispatcher_summary(running, found))
            server._dispatcher_seen[0] = 0.0
            self.assertEqual(server.dispatcher_badge(scr), "<32>● dispatcher")
            state.save(phase="waiting", last_exit=1, next_start=time.time() + 60)
            server._dispatcher_seen[0] = 0.0
            self.assertEqual(server.dispatcher_badge(scr), "<33>● dispatcher not connected")
            self.assertIn("starts again at", server.dispatcher_summary(*server.dispatcher_status()))
        server._dispatcher_seen[0] = 0.0
        self.assertEqual(server.dispatcher_badge(scr), "<31>● dispatcher stopped")  # ended without stopping
        state.save(phase="stopped")  # stopped as asked: uninstall, or a sign-in start after it
        server._dispatcher_seen[0] = 0.0
        self.assertEqual(server.dispatcher_badge(scr), "")
        self.assertEqual(server.dispatcher_summary(False, {"phase": "stopped"}), "the dispatcher isn't running")
        state.save(phase="failed")  # couldn't check its sign-in start
        server._dispatcher_seen[0] = 0.0
        self.assertEqual(server.dispatcher_badge(scr), "<31>● dispatcher stopped")
        self.assertIn("couldn't tell whether nouez's sign-in start is there",
                      server.dispatcher_summary(False, {"phase": "failed"}))
        self.assertEqual(server.dispatcher_summary(False, {"phase": "waiting", "last_exit_at": None}),
                         "the dispatcher isn't running")

    def test_setup_quotes_the_folder_for_powershell(self):
        """0.23.0: on Windows setup says how to get to the folder in PowerShell: one single-quoted
        string, where PowerShell also takes the curly single quotes as quotes, and $ is plain."""
        self.assertEqual(server.powershell_quoted("D:\\O\u2019Neil's $x \u2018y\u201b"),
                         "'D:\\O\u2019\u2019Neil''s $x \u2018\u2018y\u201b\u201b'")

    def test_the_dispatchers_folder_needs_trust_of_its_own(self):
        """0.23.0: the folder has its own shared settings, so Claude Code asks again there when only a
        folder above it is trusted: setup, install and doctor don't count that trust."""
        state = os.path.join(self.home, ".claude.json")
        os.makedirs(self.folder)
        for projects, want in (({self.projects: {"hasTrustDialogAccepted": True}}, False),
                               ({self.folder: {"hasTrustDialogAccepted": True}}, True), ({}, False)):
            with open(state, "w", encoding="utf-8") as f:
                json.dump({"projects": projects}, f)
            with mock.patch.object(server, "dispatcher_trusted", _REAL_DISPATCHER_TRUSTED), \
                    mock.patch.object(server, "folder_trusted", _REAL_FOLDER_TRUSTED), \
                    mock.patch.object(server, "git_root", lambda path: None), \
                    mock.patch.object(server, "claude_state_file", lambda env=None: state):
                self.assertIs(server.dispatcher_trusted(self.folder), want, projects)
                out = []
                server.dispatcher_setup(self.folder, out=out.append)
            self.assertEqual("doesn't count" in "\n".join(out), not want, out)
        self.assertIs(_REAL_DISPATCHER_TRUSTED(os.path.join(self.home, "missing")), False)
        # doctor: the profile the supervisor runs with, not this shell's
        other = os.path.join(self.home, "other-profile")
        os.makedirs(other)
        with open(os.path.join(other, ".claude.json"), "w", encoding="utf-8") as f:
            json.dump({"projects": {self.folder: {"hasTrustDialogAccepted": True}}}, f)
        with open(os.path.join(self.folder, "CLAUDE.md"), "w"):
            pass
        for config_dir, shell, said in ((other, None, "Claude Code is trusted there"),
                                        (None, None, "isn't trusted there itself"),
                                        (None, other, "Claude Code is trusted there")):  # run by hand from it
            with mock.patch.dict(server.os.environ, {"CLAUDE_CONFIG_DIR": shell} if shell else {}), \
                    mock.patch.object(server, "claude_state_file",
                                      lambda env=None: os.path.join((env or {}).get("CLAUDE_CONFIG_DIR") or self.home,
                                                                    ".claude.json") if env is not None else
                                      os.path.join(os.environ.get("CLAUDE_CONFIG_DIR") or self.home, ".claude.json")):
                server.DispatcherState(self.folder, config_dir).save(phase="stopped")
            lines = []
            with mock.patch.object(server, "dispatcher_trusted", _REAL_DISPATCHER_TRUSTED), \
                    mock.patch.object(server, "folder_trusted", _REAL_FOLDER_TRUSTED), \
                    mock.patch.object(server, "git_root", lambda path: None), \
                    mock.patch.object(server, "dispatcher_installed", lambda check_off=True, want=None: "no"), \
                    mock.patch.object(server, "claude_state_file",
                                      lambda env=None: os.path.join((env or {}).get("CLAUDE_CONFIG_DIR") or self.home,
                                                                    ".claude.json") if env is not None else state):
                server.dispatcher_report(lambda ok, text: lines.append(text))
            self.assertTrue(any(said in line for line in lines), (config_dir, lines))

    def test_the_top_bar_shows_the_dispatcher_and_keeps_the_sign_in_badge(self):
        groups = [{"title": "Codex", "entries": [(None, "weekly", {"rank": 1, "used": 10.0, "colour": "32"})]}]
        scr = server.Screen(False)
        with mock.patch.object(server, "dispatcher_badge", lambda scr: "● dispatcher"), \
                mock.patch.object(server, "login_badge", lambda scr, now: "● sign-in Dec 5, 11d"):
            line = server.top_bar(scr, groups, 7, time.time(), 200)
            self.assertLess(line.index("● dispatcher"), line.index("Codex"))
            narrow = server.top_bar(scr, groups, 7, time.time(), 40)
            self.assertIn("● sign-in Dec 5, 11d", narrow)
            self.assertLessEqual(server.visible(narrow), 40)

    def test_the_supervisor_adds_rules_an_update_brought(self):
        """0.24.0: a folder with every rule an earlier nouez gave gets the rules for tools added
        since, before claude starts, backed up first, and each only once, so one the user removes
        stays removed. A folder whose rules the user changed, or that setup never gave them, is
        left alone."""
        out = []
        add = lambda: server.add_missing_dispatcher_rules(self.folder, out.append)
        self.assertEqual(add(), [])  # no folder yet
        os.makedirs(os.path.join(self.folder, ".claude"))
        settings = os.path.join(self.folder, ".claude", "settings.json")

        def write(rules):
            with open(settings, "w", encoding="utf-8") as f:
                json.dump({"permissions": {"allow": ["Bash(git status)"] + rules}, "theme": "dark"}, f)

        def allowed():
            with open(settings, encoding="utf-8") as f:
                data = json.load(f)
            self.assertEqual(data["theme"], "dark")
            return data["permissions"]["allow"]

        self.assertEqual(add(), [])  # no file
        write([])
        self.assertEqual(add(), [])  # never set up
        new = "mcp__consultants__ListConsultants"
        earlier = [r for r in server.dispatcher_rules() if r != new]
        write(earlier[1:])
        self.assertEqual(add(), [])  # the user took one out: left to setup
        write(earlier)
        self.assertEqual(add(), [new])
        self.assertEqual(allowed(), ["Bash(git status)"] + earlier + [new])
        backups = [n for n in os.listdir(os.path.dirname(settings)) if n.endswith(".bak")]
        self.assertEqual(len(backups), 1, backups)
        self.assertEqual(add(), [])  # nothing more to add
        write(earlier)  # the user removes it again
        self.assertEqual(add(), [])
        self.assertEqual(allowed(), ["Bash(git status)"] + earlier)
        key = server.folder_identity(self.folder)
        self.assertEqual(json.loads(self.read("dispatcher-rules.json")), {key: [new]})
        record = os.path.join(self.cache, "dispatcher-rules.json")
        with open(record, "w", encoding="utf-8") as f:
            f.write("{not json")  # notes it can't read: nothing is added, never "no notes"
        self.assertEqual(add(), [])
        self.assertEqual(allowed(), ["Bash(git status)"] + earlier)
        self.assertTrue(any("delete it to start again" in line for line in out), out)
        os.remove(record)
        write(earlier + [new])  # granted by setup or the user: noted, so never added back
        self.assertEqual(add(), [])
        self.assertEqual(json.loads(self.read("dispatcher-rules.json")), {key: [new]})
        write(earlier)
        self.assertEqual(add(), [])
        os.remove(record)
        with open(settings, "w", encoding="utf-8") as f:
            f.write("{not json")
        self.assertEqual(add(), [])
        self.assertTrue(any("isn't valid JSON" in line for line in out), out)

    def test_setup_notes_the_rules_it_grants(self):
        """A rule `setup` grants counts as added, so the supervisor never puts it back once the user
        takes it out."""
        code, out = self.setup()
        self.assertEqual(code, 0, out)
        new = "mcp__consultants__ListConsultants"
        self.assertEqual(json.loads(self.read("dispatcher-rules.json")),
                         {server.folder_identity(self.folder): [new]})
        settings = os.path.join(self.folder, ".claude", "settings.json")
        with open(settings, encoding="utf-8") as f:
            data = json.load(f)
        data["permissions"]["allow"].remove(new)
        with open(settings, "w", encoding="utf-8") as f:
            json.dump(data, f)
        self.assertEqual(server.add_missing_dispatcher_rules(self.folder, lambda line: None), [])

    # --- setup ---

    def setup(self, *args, **kwargs):
        out = []
        code = server.dispatcher_setup(self.folder, *args, out=out.append, **kwargs)
        return code, "\n".join(out)

    def test_setup_and_install_refuse_a_projects_folder_holding_claude_codes_settings(self):
        """0.26.3: the folder that holds the dispatcher's is where the phone can record trust, so
        setup refuses one that holds Claude Code's settings folder, and install lists it as a problem."""
        settings = os.path.join(self.projects, ".claude")
        with mock.patch.object(server, "claude_config_dir", lambda: settings):
            code, out = self.setup()
        self.assertEqual(code, 1, out)
        self.assertIn("Claude Code's settings folder", out)
        self.assertIn("--projects DIR", out)
        self.assertIn("--no-projects", out)
        self.assertFalse(os.path.exists(self.folder))
        self.assertEqual(self.setup()[0], 0)
        with mock.patch.object(server, "claude_config_dir", lambda: settings):
            code, out, ran, popen = self.install("linux")
        self.assertEqual(code, 1, out)
        self.assertIn("--projects", out)  # 0.27.0: names the folders, or --no-projects
        popen.assert_not_called()

    def test_setup_makes_the_folder_its_instructions_and_rules(self):
        code, out = self.setup()
        self.assertEqual(code, 0, out)
        with open(os.path.join(self.folder, "CLAUDE.md"), encoding="utf-8") as f:
            md = f.read()
        # 0.27.0: no folder in it; ListProjects names the projects folders.
        self.assertIn("directly inside one of the projects\n  folders `ListProjects` names", md)
        self.assertNotIn(self.projects, md)
        self.assertIn(f"The phone can open and trust projects inside {self.projects}.", out)
        # 0.26.1: the rules the code doesn't hold, in the words the dispatcher gets.
        self.assertIn("If it isn't\ninside one of the projects folders `ListProjects` names, or nouez can't tell, "
                      "decline.", md)
        self.assertIn("Don't start consultants or consult from this session.", md)
        self.assertIn("Close one with `CloseClaudeSession` only when the user\n  names it.", md)
        self.assertNotIn("{projects}", md)
        self.assertNotIn("dangerously", md.lower())
        with open(os.path.join(self.folder, ".claude", "settings.json"), encoding="utf-8") as f:
            allow = json.load(f)["permissions"]["allow"]
        self.assertEqual(allow, [f"mcp__consultants__{t}" for t in server.DISPATCHER_TOOLS])
        self.assertIn("claude remote-control --name dispatcher --spawn same-dir", out)
        self.assertIn("Don't use this run from the phone: it is plain Claude Code", out)  # 0.26.1
        code, out = self.setup()
        self.assertIn("already allows", out)
        self.assertIn("kept as it is", out)
        self.assertNotIn("isn't the one this nouez writes", out)
        self.assertIsNone(server.dispatcher_md_note(self.folder))

    def test_setup_keeps_the_users_files_and_backs_up_what_it_changes(self):
        os.makedirs(os.path.join(self.folder, ".claude"))
        with open(os.path.join(self.folder, "CLAUDE.md"), "w", encoding="utf-8") as f:
            f.write("my own")
        settings = os.path.join(self.folder, ".claude", "settings.json")
        raw = b'{"model": "opus", "permissions": {"allow": ["Bash(ls *)", "mcp__consultants__ListProjects"]}}'
        with open(settings, "wb") as f:
            f.write(raw)
        code, out = self.setup()
        self.assertEqual(code, 0, out)
        with open(os.path.join(self.folder, "CLAUDE.md"), encoding="utf-8") as f:
            self.assertEqual(f.read(), "my own")
        # One that isn't the current nouez's (an older one, or edited) is kept, with how to take the new one.
        self.assertIn("isn't the one this nouez writes", out)
        self.assertIn("rename it", out)
        self.assertIsNone(server.dispatcher_md_note(self.projects))  # no CLAUDE.md there: no note
        with open(settings, encoding="utf-8") as f:
            data = json.load(f)
        self.assertEqual(data["model"], "opus")
        self.assertEqual(data["permissions"]["allow"][:2], ["Bash(ls *)", "mcp__consultants__ListProjects"])
        self.assertEqual(len(data["permissions"]["allow"]), 1 + len(server.DISPATCHER_TOOLS))
        backups = glob.glob(settings + ".nouez-*.bak")
        self.assertEqual(len(backups), 1)
        with open(backups[0], "rb") as f:
            self.assertEqual(f.read(), raw)

    def test_setup_refuses_settings_it_cant_change_safely(self):
        os.makedirs(os.path.join(self.folder, ".claude"))
        settings = os.path.join(self.folder, ".claude", "settings.json")
        for raw in (b'{"permissions": {', b'{"permissions": {"allow": "all"}}', b"[]"):
            with open(settings, "wb") as f:
                f.write(raw)
            code, out = self.setup()
            self.assertEqual(code, 1, out)
            self.assertIn("fix it first", out)
            with open(settings, "rb") as f:
                self.assertEqual(f.read(), raw)
        self.assertFalse(os.path.exists(os.path.join(self.folder, "CLAUDE.md")))

    def test_setup_changes_nothing_when_the_settings_change_meanwhile(self):
        os.makedirs(os.path.join(self.folder, ".claude"))
        settings = os.path.join(self.folder, ".claude", "settings.json")
        with open(settings, "wb") as f:
            f.write(b'{"permissions": {"allow": []}}')
        edited = b'{"permissions": {"allow": [], "deny": ["Bash"]}}'
        real = server.backup_file

        def backup_then_edit(folder, raw, name="settings.json"):
            copy = real(folder, raw, name)
            with open(settings, "wb") as f:
                f.write(edited)
            return copy
        with mock.patch.object(server, "backup_file", backup_then_edit):
            code, out = self.setup()
        self.assertEqual(code, 1, out)
        self.assertIn("changed while setup ran", out)
        with open(settings, "rb") as f:
            self.assertEqual(f.read(), edited)
        self.assertEqual([n for n in os.listdir(os.path.dirname(settings)) if n.endswith(".tmp")], [])

    def test_settings_are_never_reached_through_a_linked_claude_folder(self):
        """0.23.0: setup and doctor read and write .claude/settings.json only in a .claude that is a
        plain folder, checked before anything is read or made."""
        os.makedirs(self.folder)
        with open(os.path.join(self.folder, "CLAUDE.md"), "w") as f:
            f.write("mine")
        elsewhere = os.path.join(self.home, "elsewhere")
        os.makedirs(elsewhere)
        with open(os.path.join(elsewhere, "settings.json"), "wb") as f:
            f.write(b'{"permissions": {"allow": []}}')
        dir_link(elsewhere, os.path.join(self.folder, ".claude"))
        with self.assertRaises(OSError):
            server.SettingsFolder(self.folder)
        code, out = self.setup()
        self.assertEqual(code, 1, out)
        self.assertIn("is a link", out)
        self.assertEqual(sorted(os.listdir(elsewhere)), ["settings.json"])
        with mock.patch.object(server, "dispatcher_installed", lambda check_off=True, want=None: "no"):
            said = self.report()
        self.assertTrue(any("couldn't check the dispatcher's settings" in text for _, text in said), said)

    def test_settings_go_through_one_folder(self):
        os.makedirs(self.folder)
        with server.SettingsFolder(self.folder) as settings:
            self.assertFalse(settings.exists)
            self.assertIsNone(settings.read("settings.json"))
        with server.SettingsFolder(self.folder, create=True) as settings:
            self.assertTrue(settings.exists)
            with settings.create("a.tmp") as f:
                f.write(b"{}")
            with self.assertRaises(FileExistsError):
                settings.create("a.tmp")
            settings.replace("a.tmp", "settings.json")
            self.assertEqual(settings.read("settings.json"), b"{}")
            settings.remove("settings.json")
            self.assertIsNone(settings.read("settings.json"))

    def test_setup_dry_run_changes_nothing(self):
        code, out = self.setup(dry_run=True)
        self.assertEqual(code, 0, out)
        self.assertIn("Would make", out)
        self.assertFalse(os.path.exists(self.folder))

    def test_setup_says_when_nouez_isnt_registered(self):
        with mock.patch.object(server, "consultants_registered", lambda folder: False):
            code, out = self.setup()
        self.assertEqual(code, 0)
        self.assertIn("doesn't run nouez as `consultants`", out)

    def test_setup_refuses_a_linked_folder(self):
        target = os.path.join(self.home, "elsewhere")
        os.makedirs(target)
        dir_link(target, self.folder)
        code, out = self.setup()
        self.assertEqual(code, 1)
        self.assertIn("is a link", out)
        self.assertEqual(os.listdir(target), [])

    def test_options(self):
        opts = server.dispatcher_options(["--folder", self.folder, "--dry-run"], {"folder", "dry-run"})
        self.assertEqual(opts, {"folder": self.folder, "config-dir": None, "dry-run": True, "force": False,
                                "sign-in": False, "projects": None, "statusline": False})
        opts = server.dispatcher_options(["--config-dir", self.home], {"folder", "config-dir"})
        self.assertEqual(opts["config-dir"], self.home)
        for argv in (["--config-dir", "relative"], ["--config-dir", self.home]):
            with self.assertRaises(ValueError):
                server.dispatcher_options(argv, {"folder", "config-dir"} if argv[1] == "relative" else {"folder"})
        with mock.patch.object(server, "run_dispatcher_supervisor") as run:
            server.run_dispatcher(["run", "--folder", self.folder, "--config-dir", self.home])
        run.assert_called_once_with(self.folder, self.home, False, None)
        with mock.patch.object(server, "run_dispatcher_supervisor") as run:
            server.run_dispatcher(["run", "--folder", self.folder, "--sign-in"])
        run.assert_called_once_with(self.folder, None, True, None)
        with self.assertRaises(ValueError):
            server.dispatcher_options(["--sign-in"], {"folder", "dry-run", "force"})
        self.assertEqual(server.dispatcher_options([], set())["folder"], self.folder)
        for argv in (["--force"], ["--folder"], ["--folder", "relative"], ["extra"]):
            with self.assertRaises(ValueError):
                server.dispatcher_options(argv, {"folder", "dry-run"})
        with contextlib.redirect_stdout(io.StringIO()) as out:
            self.assertEqual(server.run_dispatcher(["bogus"]), 2)
        self.assertIn("usage: server.py dispatcher setup", out.getvalue())

    # --- sign-in starts ---

    def test_the_windows_task(self):
        import xml.etree.ElementTree as ET
        argv = ["C:\\Py thon\\pythonw.exe", "-I", "C:\\nouez\\server.py", "dispatcher", "run",
                "--folder", "C:\\Users\\me\\R&D <x>\\dispatcher"]
        xml = server.windows_task_xml(argv, "PC\\me")
        root = ET.fromstring(xml.encode("utf-16"))
        ns = {"t": "http://schemas.microsoft.com/windows/2004/02/mit/task"}
        self.assertEqual(root.find("t:Settings/t:MultipleInstancesPolicy", ns).text, "IgnoreNew")
        self.assertEqual(root.find("t:Settings/t:ExecutionTimeLimit", ns).text, "PT0S")
        self.assertEqual(root.find("t:Settings/t:DisallowStartIfOnBatteries", ns).text, "false")
        self.assertEqual(root.find("t:Principals/t:Principal/t:RunLevel", ns).text, "LeastPrivilege")
        self.assertEqual(root.find("t:Triggers/t:LogonTrigger/t:UserId", ns).text, "PC\\me")
        self.assertEqual(root.find("t:Actions/t:Exec/t:Command", ns).text, argv[0])
        self.assertEqual(root.find("t:Actions/t:Exec/t:Arguments", ns).text, subprocess.list2cmdline(argv[1:]))

    def test_the_launch_agent(self):
        import plistlib
        argv = ["/usr/bin/python3", "-I", "/n/server.py", "dispatcher", "run", "--folder", "/u/dispatcher"]
        plist = plistlib.loads(server.launch_agent(argv, "/Users/me/.local/bin:/usr/bin"))
        self.assertEqual(plist["ProgramArguments"], argv)
        self.assertEqual(plist["KeepAlive"], {"SuccessfulExit": False})
        self.assertTrue(plist["RunAtLoad"])
        self.assertEqual(plist["EnvironmentVariables"]["PATH"], "/Users/me/.local/bin:/usr/bin")

    def test_the_autostart_entry(self):
        entry = server.autostart_entry(["/usr/bin/python3", "-I", "/home/me/My Tools/server.py", "run"])
        self.assertIn('Exec=/usr/bin/python3 -I "/home/me/My Tools/server.py" run\n', entry)
        self.assertIn("NoDisplay=true", entry)
        for bad in ('/home/me/a"b', "/home/me/$HOME", "/home/me/100%", "/home/me/a\\b"):
            with self.assertRaises(ValueError):
                server.autostart_entry(["/usr/bin/python3", bad])

    def test_the_sign_in_start_is_known_by_its_whole_command(self):
        """0.23.0: nouez's sign-in start runs exactly what dispatcher_command makes; anything else of
        that name is someone else's, and install and uninstall leave it alone."""
        ours = server.dispatcher_argv_ours
        posix = ["/usr/bin/python3", "-I", "/n/server.py", "dispatcher", "run", "--folder", "/u/d", "--sign-in"]
        win = ["C:\\Py thon\\pythonw.exe", "-I", "C:\\nouez\\server.py", "dispatcher", "run", "--folder",
               "C:\\Users\\me\\dispatcher", "--sign-in"]
        self.assertTrue(ours(posix, windows=False))
        self.assertTrue(ours(posix[:7] + ["--config-dir", "/u/.claude", "--sign-in"], windows=False))
        self.assertTrue(ours(win, windows=True))
        self.assertTrue(ours(["/opt/py/bin/python3.12"] + posix[1:], windows=False))
        self.assertTrue(ours(server.dispatcher_command(sys.executable, os.path.abspath(self.folder))))
        for bad in (["/usr/bin/example"] + posix[1:], ["python3"] + posix[1:], posix[:1] + posix[2:],
                    posix[:2] + ["/n/other.py"] + posix[3:], posix[:2] + ["n/server.py"] + posix[3:],
                    posix[:6] + ["u/d", "--sign-in"], posix[:7], posix + ["--extra"],
                    posix[:7] + ["--config-dir", "rel", "--sign-in"], posix[:7] + ["--force", "x", "--sign-in"],
                    posix[:6] + ["/u/d", "--config-dir"], posix[:2] + ["/other/server.py"] + posix[3:],
                    ["/usr/bin/python3", "dispatcher", "run"], "not a list", None):
            self.assertFalse(ours(bad, windows=False), bad)
        self.assertFalse(ours(["\\Python\\pythonw.exe"] + win[1:], windows=True))  # no drive
        self.assertFalse(ours(win, windows=False))

    def test_a_failed_settings_write_leaves_no_partial_copy(self):
        """0.23.0: the new settings file is removed when writing it fails, and on Windows nothing
        is removed once the folder or .claude is no longer a plain folder."""
        os.makedirs(self.folder)
        claude = os.path.join(self.folder, ".claude")

        class Failing:
            def __init__(self, f):
                self.f = f

            def __enter__(self):
                return self

            def __exit__(self, *exc):
                self.f.close()

            def write(self, data):
                raise OSError("disk full")
        with server.SettingsFolder(self.folder, create=True) as settings:
            real = settings.create
            settings.create = lambda name: Failing(real(name))
            with self.assertRaises(OSError):
                server.write_settings(settings, {"permissions": {"allow": []}}, None, lambda line: None)
        self.assertEqual(os.listdir(claude), [])
        if os.name == "nt":
            with server.SettingsFolder(self.folder) as settings:
                with open(os.path.join(claude, "kept.tmp"), "w"):
                    pass
                with mock.patch.object(settings, "check", side_effect=OSError("a link now")):
                    settings.remove("kept.tmp")
                self.assertTrue(os.path.exists(os.path.join(claude, "kept.tmp")))
                settings.remove("kept.tmp")
                self.assertFalse(os.path.exists(os.path.join(claude, "kept.tmp")))

    def test_a_late_run_for_another_folder_is_stopped_and_the_new_one_started_again(self):
        """0.23.0: a run of the old sign-in start that took the lock during install, for another
        folder or profile, is asked to stop and the new supervisor started again, so one runs."""
        for seen, stops, want, started in ((["other", True], True, True, 2), (["other"], False, None, 1),
                                           ([False, False, False], True, False, 3)):
            starts, out = [], []
            with mock.patch.object(server, "wait_for_supervisor", lambda *a, others, projects: seen.pop(0)), \
                    mock.patch.object(server, "stop_dispatcher", lambda out: stops):
                result = server.start_new_supervisor(lambda: starts.append(7) or 7, self.folder, None, 0, False,
                                                     out.append)
            self.assertIs(result, want, out)
            self.assertEqual(len(starts), started)
            self.assertEqual(any("set up differently (another folder, projects folders or profile) took the lock" in line for line in out), started < 3)
            self.assertEqual(any("that supervisor didn't stop" in line for line in out), not stops)
        self.assertIsNone(server.start_new_supervisor(lambda: False, self.folder, None, 0, False, print))
        # the one asked to stop leaves its record until the new one writes its own: it isn't stopped too
        other = {"pid": 5, "since": 100.0, "folder": self.home, "config_dir": None, "sign_in": True, "phase": "starting"}
        new = dict(other, pid=7, since=101.0, folder=self.folder, projects=[os.path.dirname(self.folder)],
                   projects_given=False, script=os.path.abspath(server.__file__))
        records = iter([other, dict(other, phase="stopped"), other, new])
        stopped = []
        with mock.patch.object(server, "dispatcher_status", lambda: (True, next(records))), \
                mock.patch.object(server, "stop_dispatcher", lambda out: stopped.append(1) or True), \
                mock.patch.object(server.time, "sleep", lambda s: None):
            self.assertIs(server.start_new_supervisor(lambda: None, self.folder, None, 50, False, out.append), True)
        self.assertEqual(stopped, [1])
        with mock.patch.object(server, "wait_for_supervisor") as wait:
            self.assertIs(server.start_new_supervisor(lambda: None, self.folder, None, 0, True, print), True)
        wait.assert_not_called()

    def test_only_nouezs_own_server_py_counts(self):
        """0.23.0: a sign-in start running another program's server.py, or one that is gone, isn't
        nouez's; with a command to match, a start of nouez's for another folder or profile isn't
        the one asked about."""
        real = _REAL_NOUEZ_SCRIPT
        self.assertTrue(real(os.path.join(ROOT, "server.py")))
        other = os.path.join(self.home, "server.py")
        with open(other, "w") as f:
            f.write('"""another program"""\n')
        self.assertFalse(real(other))
        self.assertFalse(real(os.path.join(self.home, "gone", "server.py")))
        self.assertFalse(real(self.home))
        if hasattr(os, "mkfifo"):
            fifo = os.path.join(self.home, "fifo", "server.py")
            os.makedirs(os.path.dirname(fifo))
            os.mkfifo(fifo)
            self.assertFalse(real(fifo))  # no writer: open() would wait for one
        want = ["", "-I", "/n/server.py", "dispatcher", "run", "--folder", "/u/d", "--sign-in"]
        argv = ["/usr/bin/python3"] + want[1:]
        self.assertTrue(server.same_command(argv, want))
        self.assertTrue(server.same_command(argv, None))
        self.assertFalse(server.same_command(argv[:6] + ["/u/e", "--sign-in"], want))
        self.assertFalse(server.same_command(argv[:7] + ["--config-dir", "/u/c", "--sign-in"], want))
        self.assertFalse(server.same_command(argv[:2] + ["/m/server.py"] + argv[3:], want))
        path = os.path.join(self.home, "auto", "n.desktop")
        os.makedirs(os.path.dirname(path))
        with open(path, "w") as f:
            f.write(server.autostart_entry(argv))
        with mock.patch.object(server, "autostart_path", lambda: path):
            self.assertEqual(server.autostart_state(want), "yes")
            self.assertEqual(server.autostart_state(want[:6] + ["/u/e", "--sign-in"]), "other")

    def test_a_supervisor_started_at_sign_in_needs_its_own_sign_in_start(self):
        """0.23.0: one started at sign-in starts claude only while nouez's sign-in start runs its
        own folder and profile; one for another folder, or one it can't tell about, makes it exit."""
        asked = []

        def installed(check_off=True, want=None):
            asked.append(want)
            return "yes" if want == server.dispatcher_command("", self.folder) else "other"
        with mock.patch.object(server, "dispatcher_installed", installed):
            thread, calls, result = self.start_supervisor()
            thread.join(10)
        self.assertEqual((result, len(calls)), ([0], 1))
        self.assertEqual(asked, [server.dispatcher_command("", self.folder)])
        with mock.patch.object(server, "dispatcher_installed", lambda check_off=True, want=None: "other"):
            thread, calls, result = self.start_supervisor()
            thread.join(10)
        self.assertEqual((result, calls), ([0], []))
        self.assertIn("now starts another folder or profile", self.read("dispatcher.log"))
        with mock.patch.object(server, "dispatcher_installed", lambda check_off=True, want=None: None), \
                mock.patch.object(server, "DISPATCHER_SIGN_IN_TRIES", 1):
            thread, calls, result = self.start_supervisor()
            thread.join(10)
        self.assertEqual((result, calls), ([0], []))
        self.assertIn("can't tell whether nouez's sign-in start is there", self.read("dispatcher.log"))
        self.assertEqual(self.state()["phase"], "failed")  # not asked to stop: the badge stays red

    def test_a_supervisor_without_its_job_doesnt_start_claude(self):
        def no_job():
            raise OSError("denied")
        os.makedirs(self.folder)
        with mock.patch.object(server, "supervisor_job", no_job), mock.patch.object(server.signal, "signal"), \
                mock.patch.object(server, "supervise_dispatcher") as supervise:
            self.assertEqual(server.run_dispatcher_supervisor(self.folder), 1)
        supervise.assert_not_called()
        self.assertIn("can't run the supervisor in a job of its own (denied)", self.read("dispatcher.log"))
        if os.name != "nt":
            self.assertEqual(server.supervisor_job(), (None, None))

    def test_the_autostart_entry_is_found_where_install_put_it(self):
        """0.23.0: Linux: install records where it wrote the entry, so a shell with another
        XDG_CONFIG_HOME finds the same one; uninstall forgets it."""
        record = os.path.join(self.cache, "dispatcher-autostart")
        name = server.DISPATCHER_AUTOSTART
        put = os.path.join(self.home, "elsewhere", "autostart", name)
        with mock.patch.dict(server.os.environ, {"XDG_CONFIG_HOME": os.path.join(self.home, ".xdg")}):
            default = server.autostart_path()
            self.assertEqual(default, os.path.join(self.home, ".xdg", "autostart", name))
            with open(record, "w") as f:
                f.write(put + "\n")
            self.assertEqual(server.autostart_path(), put)
            for text in (os.path.join("relative", "autostart", name), os.path.join(self.home, "autostart", "other.desktop"),
                         os.path.join(self.home, "x", name)):
                with open(record, "w") as f:
                    f.write(text + "\n")
                with self.assertRaises(OSError, msg=text):
                    server.autostart_path()
            for raw in (b"/x/\xff/autostart/" + name.encode(),
                        os.path.join(self.home, "a\0", "autostart", name).encode()):
                with open(record, "wb") as f:  # not as install writes it
                    f.write(raw + b"\n")
                with self.assertRaises(OSError, msg=raw):
                    server.autostart_path()
            out = []
            with mock.patch.object(server, "dispatcher_change_lock", lambda dry_run: contextlib.nullcontext()), \
                    mock.patch.object(server, "stop_dispatcher", lambda out: True), \
                    mock.patch.object(server.os, "name", "posix"), mock.patch.object(server.sys, "platform", "linux"):
                self.assertEqual(server.dispatcher_uninstall(out=out.append), 1)
                status = []
                self.assertEqual(server.dispatcher_status_text(status.append), 0)
                with mock.patch.object(server, "other_remote_controls", lambda own: []), \
                        mock.patch.object(server, "SettingsFolder", mock.Mock(side_effect=OSError("not here"))):
                    server.dispatcher_report(lambda ok, text: status.append(text))
            self.assertNotIn("no dispatcher is set up", "\n".join(status))
            self.assertIn("couldn't tell whether it starts at sign-in (", "\n".join(status))
            self.assertIn("doesn't name an autostart entry", "\n".join(out))
            self.assertIn("Starts at sign-in: can't tell (", "\n".join(status))
            self.assertIn("doesn't name an autostart entry", "\n".join(status))
            self.assertTrue(os.path.exists(record))  # where the entry went is still to be found
            os.remove(record)
            self.assertEqual(server.autostart_path(), default)
        self.setup()
        saved, a = os.path.join(self.cache, "dispatcher-path"), os.path.abspath
        claude = os.path.dirname(a("/opt/bin/claude"))  # where install finds claude here
        with mock.patch.dict(server.os.environ, {"PATH": os.pathsep.join(
                [a("/usr/bin"), claude, "rel/bin", a("/bin"), a("/usr/bin")])}):
            self.install("linux", claude=a("/opt/bin/claude"))
        with open(record) as f:
            self.assertEqual(f.read(), os.path.join(self.home, "auto", "n.desktop") + "\n")
        with open(saved) as f:  # claude's folder first, though PATH had it second; no relative folder
            self.assertEqual(f.read(), os.pathsep.join([claude, a("/usr/bin"), a("/bin")]) + "\n")
        for name in (record, saved):
            os.remove(name)
        with mock.patch.object(server, "DISPATCHER_PATH_BYTES", len(claude) + 1), \
                mock.patch.dict(server.os.environ, {"PATH": a("/usr/bin")}):  # claude's folder alone fits
            code, out, _, popen = self.install("linux", claude=a("/opt/bin/claude"))
        self.assertEqual(code, 1)
        self.assertIn("Nothing was installed: this PATH can't be saved for the sign-in start (", out)
        popen.assert_not_called()
        self.assertFalse(os.path.exists(record) or os.path.exists(saved))

    def test_a_sign_in_start_on_linux_uses_the_path_install_saved(self):
        """0.23.0: an autostart entry can't carry a PATH, so install saves one (above) and a
        supervisor the sign-in start ran puts it ahead of the desktop's."""
        saved, a = os.path.join(self.cache, "dispatcher-path"), os.path.abspath
        desktop = os.pathsep.join([a("/usr/bin"), "rel", a("/bin")])

        def path_after(sign_in=True, platform="linux", osname="posix"):
            with mock.patch.dict(server.os.environ, {"PATH": desktop}), \
                    mock.patch.object(server.os, "name", osname), mock.patch.object(server.sys, "platform", platform):
                server.use_saved_path(sign_in)
                return server.os.environ["PATH"], server.dispatcher_cache_problems()

        def write(raw):
            with open(saved, "wb") as f:
                f.write(raw)
        self.assertEqual(path_after(), (desktop, []))  # none saved: as it was
        nvm = os.path.join(a("/home/me/.nvm"), "bin ")  # a name may end with a space
        write(os.pathsep.join([nvm, a("/usr/bin")]).encode() + b"\n")
        self.assertEqual(path_after(), (os.pathsep.join([nvm, a("/usr/bin"), a("/bin")]), []))
        self.assertEqual(path_after(sign_in=False)[0], desktop)  # started by hand: its own PATH
        self.assertEqual(path_after(platform="darwin")[0], desktop)  # the launch agent carries it
        self.assertEqual(path_after(platform="win32", osname="nt")[0], desktop)
        write(b"\n")  # no folder saved
        self.assertEqual(path_after(), (desktop, []))
        sep = os.pathsep.encode()
        for raw in (a("/x/").encode() + b"\xff\n", a("/a").encode() + b"\n" + a("/b").encode() + b"\n",
                    a("/a").encode() + b"\0\n", a("/a").encode(), a("/a").encode() + sep + b"rel\n",
                    a("/a").encode() + b"\n\n", b"/" + b"x" * server.DISPATCHER_PATH_BYTES + b"\n"):
            write(raw)
            path, problems = path_after()
            self.assertEqual(path, desktop, raw)  # not used, and told
            self.assertEqual(len(problems), 1, raw)
            self.assertIn("dispatcher-path", problems[0])
            self.assertIn("a sign-in start uses the desktop's PATH until then", problems[0])
        with self.assertRaises(ValueError):
            server.saved_path_record(a("/opt/bin"), a("/a\nb"))
        with self.assertRaises(ValueError):  # it would come back as two folders
            server.saved_path_record(a("/home/claude") + os.pathsep + "profile/bin", "")
        self.assertEqual(server.saved_path_record("", ""), b"\n")

    def install(self, platform, osname="posix", force=False, dry_run=False, trusted=True, installed="no",
                pythonw="C:\\Python\\pythonw.exe", config_dir=None, service=(113, "Could not find service"),
                bootstrap=(), claude="/opt/bin/claude", projects=None):
        bootstrap = list(bootstrap)
        out, ran, real_command, is_trusted = [], [], server.dispatcher_command, trusted

        def command(python, folder, config_dir=None, projects=None):  # a macOS or Linux one, wherever the test runs
            argv = real_command(python, folder, config_dir, projects)
            return argv if osname == "nt" else [a.replace("\\", "/") for a in argv]
        env = {k: v for k, v in os.environ.items() if k != "CLAUDE_CONFIG_DIR"}
        if config_dir:
            env["CLAUDE_CONFIG_DIR"] = config_dir

        def run_status(argv, timeout=20, raw=False):
            ran.append(argv)
            if argv[1:2] == ["bootstrap"] and bootstrap:
                return bootstrap.pop(0)
            if argv[1:2] != ["print"]:
                return 0, ""
            return service.pop(0) if isinstance(service, list) else service
        with mock.patch.object(server, "dispatcher_claude", lambda env=None: claude), \
                mock.patch.object(server, "LAUNCH_AGENT_UNLOAD_TRIES", 2), \
                mock.patch.object(server, "LAUNCH_AGENT_BOOTSTRAP_TRIES", 2), \
                mock.patch.object(server, "dispatcher_trusted", lambda folder, state_file=None: is_trusted), \
                mock.patch.object(server, "pythonw_path", lambda: pythonw), \
                mock.patch.object(server, "dispatcher_command", command), \
                mock.patch.object(server, "dispatcher_installed", lambda check_off=True, want=None: installed), \
                mock.patch.object(server, "wait_for_supervisor", lambda *a, **k: True), \
                mock.patch.object(server, "windows_account", lambda: ("S-1-5-21-1", "PC\\me")), \
                mock.patch.object(server, "system_program", lambda name: name), \
                mock.patch.object(server, "dispatcher_change_lock", lambda dry_run: contextlib.nullcontext()), \
                mock.patch.dict(server.os.environ, env, clear=True), \
                mock.patch.object(server, "run_status", run_status), \
                mock.patch.object(server.subprocess, "Popen") as popen, \
                mock.patch.object(server, "launch_agent_path", lambda: os.path.join(self.home, "LA", "agent.plist")), \
                mock.patch.object(server, "autostart_path", lambda: os.path.join(self.home, "auto", "n.desktop")), \
                mock.patch.object(server.os, "getuid", lambda: 501, create=True), \
                mock.patch.object(server.os, "name", osname), mock.patch.object(server.sys, "platform", platform):
            code = server.dispatcher_install(self.folder, dry_run=dry_run, force=force, out=out.append,
                                             projects=projects)
        return code, "\n".join(out), ran, popen

    def test_install_checks_first(self):
        code, out, ran, popen = self.install("linux")
        self.assertEqual(code, 1)
        self.assertIn("isn't set up: run `server.py dispatcher setup`", out)
        self.assertEqual(ran, [])
        self.setup()
        code, out, ran, popen = self.install("linux", trusted=False)
        self.assertEqual(code, 1)
        self.assertIn("isn't trusted", out)
        popen.assert_not_called()
        code, out, ran, popen = self.install("linux", trusted=False, force=True)
        self.assertEqual(code, 0, out)

    def test_install_on_each_system(self):
        self.setup()
        code, out, ran, _ = self.install("win32", "nt")
        self.assertEqual(code, 0, out)
        self.assertEqual(ran[0][:5], ["schtasks.exe", "/Create", "/TN", "nouez dispatcher", "/XML"])
        self.assertEqual(ran[1], ["schtasks.exe", "/Run", "/TN", "nouez dispatcher"])
        self.assertRegex(os.path.basename(ran[0][5]), r"^dispatcher-task-.+\.xml$")
        self.assertFalse(os.path.exists(ran[0][5]), "the task's XML is deleted after")
        plist = os.path.join(self.home, "LA", "agent.plist")
        code, out, ran, _ = self.install("darwin")
        self.assertEqual(code, 0, out)
        self.assertEqual(ran[-2:], [["/bin/launchctl", "enable", "gui/501/io.github.jibarix.nouez.dispatcher"],
                                    ["/bin/launchctl", "bootstrap", "gui/501", plist]])
        self.assertNotIn("bootout", str(ran))
        self.assertTrue(os.path.isfile(plist))
        code, out, ran, popen = self.install("linux")
        self.assertEqual(code, 0, out)
        self.assertTrue(os.path.isfile(os.path.join(self.home, "auto", "n.desktop")))
        self.assertEqual(popen.call_args[0][0][-5:], ["dispatcher", "run", "--folder",
                                                            self.folder.replace("\\", "/"), "--sign-in"])
        code, out, ran, popen = self.install("linux", dry_run=True)
        self.assertIn("Would start now", out)
        popen.assert_not_called()
        code, out, ran, popen = self.install("linux", config_dir=self.home)
        self.assertEqual(code, 0, out)
        self.assertEqual(popen.call_args[0][0][-3:], ["--config-dir", self.home.replace("\\", "/"), "--sign-in"])

    def test_install_on_macos_unloads_only_nouezs_launch_agent(self):
        """0.23.0: what launchd has loaded under the label is unloaded only when it came from
        nouez's plist; one from elsewhere, or one launchd can't be asked about, stops install."""
        self.setup()
        plist = os.path.join(self.home, "LA", "agent.plist")
        loaded, gone = (0, f"gui/501/x = {{\n\tpath = {plist}\n}}"), (113, "Could not find service")
        code, out, ran, _ = self.install("darwin", service=[loaded, loaded, gone])
        self.assertEqual(code, 0, out)
        self.assertEqual([argv[1] for argv in ran[1:]], ["bootout", "print", "print", "enable", "bootstrap"])
        code, out, ran, _ = self.install("darwin", service=[loaded] * 3)  # launchd doesn't let go: no bootstrap
        self.assertEqual(code, 1, out)
        self.assertIn("still has", out)
        self.assertNotIn("bootstrap", str(ran))
        busy = (5, "Bootstrap failed: 5: Input/output error")
        code, out, ran, _ = self.install("darwin", service=[loaded, gone], bootstrap=[busy])  # 5 for a moment
        self.assertEqual(code, 0, out)
        self.assertEqual([argv[1] for argv in ran[1:]], ["bootout", "print", "enable", "bootstrap", "bootstrap"])
        code, out, ran, _ = self.install("darwin", service=[loaded, gone], bootstrap=[busy, busy])
        self.assertEqual(code, 1, out)
        self.assertIn("Couldn't load the launch agent: Bootstrap failed: 5", out)
        os.remove(plist)
        code, out, ran, _ = self.install("darwin", bootstrap=[busy])  # nothing was unloaded: no second try
        self.assertEqual(code, 1, out)
        self.assertEqual([argv[1] for argv in ran].count("bootstrap"), 1)
        for service, said in (((0, "x = {\n\tpath = /Library/LaunchAgents/other.plist\n}"), "leaves it alone"),
                              ((0, "x = {\n}"), "leaves it alone"), ((5, "Operation not permitted"), "Couldn't tell")):
            os.remove(plist)
            code, out, ran, _ = self.install("darwin", service=service)
            self.assertEqual(code, 1, out)
            self.assertIn(said, out)
            self.assertEqual(len(ran), 1, ran)  # only the look
            self.assertFalse(os.path.exists(plist))
            with open(plist, "w"):
                pass

    def test_install_leaves_alone_what_isnt_nouezs(self):
        self.setup()
        for installed, said in (("other", "isn't nouez's"), (None, "couldn't tell")):
            code, out, ran, popen = self.install("win32", "nt", force=True, installed=installed)
            self.assertEqual(code, 1, out)
            self.assertIn(said, out)
            self.assertEqual(ran, [])
        code, out, ran, popen = self.install("win32", "nt", force=True, pythonw=None)
        self.assertEqual(code, 1, out)
        self.assertIn("no pythonw.exe", out)
        self.assertNotIn("--force installs anyway", out)
        self.assertEqual(ran, [])

    def test_whose_the_windows_task_is(self):
        argv = ["C:\\Python\\pythonw.exe", "-I", "C:\\nouez\\server.py", "dispatcher", "run", "--folder", "C:\\d",
                "--sign-in"]
        xml = server.windows_task_xml(argv, "PC\\me")
        users = {"s-1-5-21-1-1001", "pc\\me", "me"}

        def state(text, encoding="ascii", ids=users):
            return server.task_xml_state(text.encode(encoding), ids)
        console = xml.replace("\n", "\r\r\n")  # what schtasks prints through a pipe
        self.assertEqual(state(xml, "utf-16"), "yes")
        self.assertEqual(state(console), "yes")
        # Task Scheduler keeps the principal as the user's SID
        stored = xml.replace("<Principal id=\"Author\">\n      <UserId>PC\\me</UserId>",
                             "<Principal id=\"Author\">\n      <UserId>S-1-5-21-1-1001</UserId>")
        self.assertNotEqual(stored, xml)
        self.assertEqual(state(stored), "yes")
        off = xml.replace("    <Enabled>true</Enabled>\n    <Hidden>", "    <Enabled>false</Enabled>\n    <Hidden>")
        self.assertEqual(state(off, "utf-16"), "off")
        trigger_off = xml.replace("      <Enabled>true</Enabled>", "      <Enabled>false</Enabled>")
        self.assertEqual(state(trigger_off), "off")
        for other in (xml.replace("nouez:", "Mine:"), xml.replace("dispatcher run", "other"),
                      xml.replace("C:\\Python\\pythonw.exe", "C:\\Tools\\example.exe"),
                      xml.replace("--sign-in", "--sign-in --more"),
                      xml.replace("<Principal id=\"Author\">\n      <UserId>PC\\me</UserId>",
                                  "<Principal id=\"Author\">\n      <UserId>S-1-5-21-9-500</UserId>"),
                      xml.replace("</Exec>", "</Exec>\n    <Exec><Command>C:\\x.exe</Command></Exec>")):
            self.assertNotEqual(other, xml)
            self.assertEqual(state(other), "other", other)
        self.assertIsNone(state("ERROR: no"))
        rene = [a.replace("C:\\nouez", "C:\\Users\\Ren\u00e9 \u65e5\u672c") for a in argv]
        named = server.windows_task_xml(rene, "PC\\me").replace("\n", "\r\r\n")
        self.assertEqual(state(named, "utf-8"), "yes")
        self.assertIsNone(state(named.replace("\u65e5\u672c", ""), "cp850"))  # not the code page asked for
        asked = []

        def run_status(command, timeout=20, raw=False):
            asked.append(command)
            return 0, named.encode("utf-8")
        with mock.patch.object(server, "run_status", run_status), \
                mock.patch.object(server, "windows_user_ids", lambda: users):
            self.assertEqual(server.windows_task_state(["", *rene[1:]]), "yes")
            self.assertEqual(server.windows_task_state(["", *argv[1:]]), "other")
        self.assertIn(" 65001 >nul 2>nul & ", asked[0])
        self.assertIn(f'/Query /TN "{server.DISPATCHER_TASK}" /XML', asked[0])
        self.assertIsNone(state(xml, ids=set()))  # whose it is can't be told
        if os.name == "nt":
            sid, account = server.windows_account()
            self.assertTrue(sid.startswith("S-1-"), sid)
            self.assertIn(sid.lower(), server.windows_user_ids())

    def test_whose_the_autostart_entry_and_launch_agent_are(self):
        path = os.path.join(self.home, "auto", "n.desktop")
        os.makedirs(os.path.dirname(path))
        with mock.patch.object(server, "autostart_path", lambda: path):
            self.assertEqual(server.autostart_state(), "no")
            entry = server.autostart_entry(["/usr/bin/python3", "-I", "/n/server.py", "dispatcher", "run",
                                            "--folder", "/u/dispatcher", "--sign-in"])
            for text, want in ((entry, "yes"), (entry + "Hidden=true\n", "off"),
                               (entry.replace("X-GNOME-Autostart-enabled=true", "X-GNOME-Autostart-enabled=false"), "off"),
                               ("[Desktop Entry]\nExec=/usr/bin/other\n", "other"),
                               ("[Desktop Entry]\nExec=/usr/bin/example dispatcher run\n", "other"),
                               (entry.replace("/usr/bin/python3", "/usr/bin/example"), "other"),
                               (entry + "Exec=/usr/bin/other\n", "other"),
                               (entry.replace("--sign-in", "--sign-in 'unclosed"), "other")):
                with open(path, "w") as f:
                    f.write(text)
                self.assertEqual(server.autostart_state(), want, text)
        import plistlib
        agent = os.path.join(self.home, "LA", "agent.plist")
        os.makedirs(os.path.dirname(agent))
        disabled = []
        status = [0]
        argv = ["/usr/bin/python3", "-I", "/n/server.py", "dispatcher", "run", "--folder", "/u/d", "--sign-in"]
        with mock.patch.object(server, "launch_agent_path", lambda: agent), \
                mock.patch.object(server.os, "getuid", lambda: 501, create=True), \
                mock.patch.object(server, "run_status", lambda argv, timeout=20: (status[0], "".join(disabled))):
            self.assertEqual(server.launch_agent_state(), "no")
            with open(agent, "wb") as f:
                f.write(server.launch_agent(argv, "/usr/bin"))
            self.assertEqual(server.launch_agent_state(), "yes")
            disabled.append('disabled services = {\n\t"io.github.jibarix.nouez.dispatcher" => disabled\n}')
            self.assertEqual(server.launch_agent_state(), "off")
            self.assertEqual(server.launch_agent_state(check_off=False), "yes")
            status[0] = 1
            self.assertIsNone(server.launch_agent_state())  # launchctl couldn't say: not "yes"
            status[0] = 0
            for plist in ({"Label": "someone.else", "ProgramArguments": argv},
                          {"Label": "io.github.jibarix.nouez.dispatcher", "Program": "/usr/bin/example",
                           "ProgramArguments": argv},
                          {"Label": "io.github.jibarix.nouez.dispatcher", "ProgramArguments": ["/usr/bin/example", "dispatcher", "run"]}):
                with open(agent, "wb") as f:
                    f.write(plistlib.dumps(plist))
                self.assertEqual(server.launch_agent_state(), "other")

    def test_the_supervisor_is_asked_to_stop_never_ended_by_a_process_id(self):
        request = os.path.join(self.cache, "dispatcher.stop")
        stop, locked = threading.Event(), threading.Event()

        def supervisor():
            with server.FileLock(os.path.join(self.cache, "dispatcher.lock"), 0, "busy"):
                locked.set()
                server.watch_stop_request(request, stop)
        thread = threading.Thread(target=supervisor, daemon=True)
        thread.start()
        self.addCleanup(stop.set)
        self.assertTrue(locked.wait(5))
        out = []
        with mock.patch.object(server.os, "kill") as kill:
            self.assertTrue(server.stop_dispatcher(out.append, seconds=10))
        kill.assert_not_called()
        thread.join(5)
        self.assertTrue(stop.is_set())
        self.assertIn("Stopped the dispatcher supervisor.", out)
        self.assertFalse(os.path.lexists(request))
        self.assertIn("asked to stop", self.read("dispatcher.log"))

    def test_a_supervisor_that_doesnt_stop_or_cant_be_told(self):
        out = []
        with server.FileLock(os.path.join(self.cache, "dispatcher.lock"), 0, "busy"):
            self.assertFalse(server.stop_dispatcher(out.append, seconds=1))
        self.assertIn("still running after 1 s", out[-1])
        self.assertFalse(os.path.lexists(os.path.join(self.cache, "dispatcher.stop")))
        with mock.patch.object(server, "dispatcher_status", lambda: (None, None)):
            self.assertFalse(server.stop_dispatcher(out.append))
        self.assertIn("Can't tell whether a dispatcher supervisor runs", out[-1])

    def test_uninstall_removes_only_nouezs_start(self):
        out = []
        with mock.patch.object(server, "dispatcher_installed", lambda check_off=True, want=None: "other"), \
                mock.patch.object(server, "run_status") as run:
            self.assertEqual(server.dispatcher_uninstall(out=out.append), 1)
        run.assert_not_called()
        self.assertIn("isn't nouez's", out[0])
        path = os.path.join(self.home, "auto", "n.desktop")
        os.makedirs(os.path.dirname(path))
        with open(path, "w") as f:
            f.write("x")
        out = []
        record, saved = os.path.join(self.cache, "dispatcher-autostart"), os.path.join(self.cache, "dispatcher-path")
        with open(record, "w") as f:
            f.write(path + "\n")
        with open(saved, "w") as f:
            f.write("/opt/bin\n")
        with mock.patch.object(server, "dispatcher_installed", lambda check_off=True, want=None: "yes"), \
                mock.patch.object(server, "autostart_path", lambda: path), mock.patch.object(server, "dispatcher_change_lock", lambda dry_run: contextlib.nullcontext()), \
                mock.patch.object(server.os, "name", "posix"), mock.patch.object(server.sys, "platform", "linux"):
            self.assertEqual(server.dispatcher_uninstall(out=out.append), 0, out)
        self.assertFalse(os.path.exists(path))
        self.assertFalse(os.path.exists(record))
        self.assertFalse(os.path.exists(saved))

    def test_uninstall_on_macos_deletes_the_plist_only_once_launchd_has_let_go(self):
        plist = os.path.join(self.home, "LA", "agent.plist")
        os.makedirs(os.path.dirname(plist))
        loaded = (0, f"x = {{\n\tpath = {plist}\n}}")
        for looks, code, kept in (([loaded, (113, "Could not find service")], 0, False),
                                  ([loaded, loaded, (113, "Could not find service")], 0, False),  # let go late
                                  ([loaded] * 3, 1, True),
                                  ([(0, "x = {\n\tpath = /elsewhere.plist\n}")], 1, True),
                                  ([(5, "Operation not permitted")], 1, True),
                                  ([(113, "Could not find service")], 0, False)):
            with open(plist, "w"):
                pass
            ran, out, answers = [], [], list(looks)

            def run_status(argv, timeout=20, raw=False):
                ran.append(argv)
                return answers.pop(0) if argv[1] == "print" else (0, "")
            with mock.patch.object(server, "dispatcher_installed", lambda check_off=True, want=None: "yes"), \
                    mock.patch.object(server, "launch_agent_path", lambda: plist), \
                    mock.patch.object(server, "run_status", run_status), \
                    mock.patch.object(server, "LAUNCH_AGENT_UNLOAD_TRIES", 2), \
                    mock.patch.object(server, "dispatcher_change_lock", lambda dry_run: contextlib.nullcontext()), \
                    mock.patch.object(server.os, "getuid", lambda: 501, create=True), \
                    mock.patch.object(server.os, "name", "posix"), mock.patch.object(server.sys, "platform", "darwin"):
                self.assertEqual(server.dispatcher_uninstall(out=out.append), code, (looks, out))
            self.assertEqual(os.path.exists(plist), kept, (looks, out))
            self.assertEqual(answers, [], looks)
            self.assertEqual(any(argv[1] == "bootout" for argv in ran), looks[0] is loaded, (looks, ran))

    def test_one_install_or_uninstall_at_a_time(self):
        out = []
        with server.FileLock(os.path.join(self.cache, "dispatcher-install.lock"), 0, "busy"), \
                mock.patch.object(server, "FileLock", lambda path, seconds, busy: _REAL_FILELOCK(path, 0, busy)), \
                mock.patch.object(server, "dispatcher_installed") as installed:
            self.assertEqual(server.dispatcher_uninstall(out=out.append), 1)
        installed.assert_not_called()
        self.assertIn("another `server.py dispatcher install` or `uninstall` is running", out[-1])

    # --- doctor ---

    def report(self):
        said = []
        server.dispatcher_report(lambda ok, text, cli=False: said.append((ok, text)))
        return said

    def test_doctor_with_no_dispatcher_says_so_once(self):
        with mock.patch.object(server, "dispatcher_installed", lambda check_off=True, want=None: "no"):
            said = self.report()
        self.assertEqual(len(said), 1)
        self.assertIsNone(said[0][0])
        self.assertIn("no dispatcher is set up", said[0][1])

    def test_doctor_flags_an_installed_dispatcher_that_doesnt_run(self):
        self.setup()
        with mock.patch.object(server, "dispatcher_installed", lambda check_off=True, want=None: "yes"), \
                mock.patch.object(server, "folder_trusted", lambda path, trusted=None: True), \
                mock.patch.object(server, "other_remote_controls", lambda own=None: [(77, "dispatcher")]):
            said = self.report()
        problems = [text for ok, text in said if ok is False]
        self.assertEqual(len(problems), 1, said)
        self.assertIn("the dispatcher isn't running", problems[0])
        self.assertTrue(any("another `claude remote-control` runs (pid 77, named 'dispatcher')" in text
                            for _, text in said), said)
        with mock.patch.object(server, "dispatcher_installed", lambda check_off=True, want=None: "off"):
            said = self.report()
        self.assertTrue(any("turned off" in text and "`server.py dispatcher install` turns it back on" in text
                            for _, text in said), said)

    def test_other_remote_control_servers_are_found_by_their_command(self):
        """0.23.0: on macOS and Linux each process's arguments are read as it got them, so a prompt
        is never taken for a server's name; where only ps's joined line is there, no name is shown."""
        claude = "/usr/local/bin/claude"
        args = {10: [claude, "remote-control", "--name", "dispatcher", "--spawn", "same-dir"],
                11: [claude, "--remote-control", "work"],
                12: ["/usr/local/bin/claude-helper", "remote-control"],
                13: ["/usr/bin/vim", "remote-control.md"],
                14: [claude, "remote-control", "--name", "dispatcher"],
                15: [claude, "-p", "explain remote-control to me"],
                16: [claude, "--verbose", "remote-control"],
                17: [claude, "-p", "remote-control --name PRIVATE_WORD"],
                18: [claude, "--print", "remote-control", "--name", "PRIVATE_WORD"],
                19: None}
        for platform in ("linux", "darwin"):
            with mock.patch.object(server.os, "name", "posix"), mock.patch.object(server.sys, "platform", platform), \
                    mock.patch.object(server, "process_ids", lambda: list(args)), \
                    mock.patch.object(server, "process_args", lambda pid: args[pid]):
                found = _REAL_DISPATCHER["other_remote_controls"](own=14)
            self.assertEqual(found, [(10, "dispatcher"), (16, "")], platform)  # never the rest of a command line
        ps = "".join(f"  {pid} {' '.join(argv)}\n" for pid, argv in args.items() if argv)
        with mock.patch.object(server.os, "name", "posix"), mock.patch.object(server.sys, "platform", "sunos5"), \
                mock.patch.object(server, "run_text", lambda argv, timeout=20: ps):
            found = _REAL_DISPATCHER["other_remote_controls"](own=14)
        self.assertEqual(found, [(10, None), (16, None)])
        for words, want in ((["remote-control"], ""), (["--name", "x"], None), (["-p", "remote-control"], None),
                            (["--print=yes", "remote-control"], None), (["remote-control", "--name=a b"], "a b")):
            self.assertEqual(server.remote_control_name(words), want, words)

    @unittest.skipIf(not sys.platform.startswith("linux") and sys.platform != "darwin", "native arguments")
    def test_a_process_arguments_are_read_as_it_got_them(self):
        proc = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)", "two words", ""])
        self.addCleanup(proc.wait)
        self.addCleanup(proc.kill)
        deadline = time.monotonic() + 10
        while (server.process_args(proc.pid) or [])[-3:] != ["import time; time.sleep(30)", "two words", ""]:
            self.assertLess(time.monotonic(), deadline, server.process_args(proc.pid))
            time.sleep(0.05)
        self.assertIn(proc.pid, server.process_ids())


class ProjectsFoldersTest(unittest.TestCase):
    """0.27.0: the dispatcher's projects folders: any number of them named with --projects, or none
    with --no-projects, or the folder above the dispatcher's as before; checked by setup and
    install, passed to the dispatcher's nouez, and kept by a later install."""

    real_default_folder = staticmethod(_REAL_DEFAULT_FOLDER)
    setUp = DispatcherTest.setUp
    setup = DispatcherTest.setup
    install = DispatcherTest.install

    def roots(self, *names):
        made = []
        for name in names:
            path = os.path.join(self.home, name)
            os.makedirs(path, exist_ok=True)
            made.append(path)
        return made

    def home_at(self, home):
        return mock.patch.dict(os.environ, {"HOME": home, "USERPROFILE": home})

    def write_state(self, **value):
        with open(os.path.join(self.cache, "dispatcher.json"), "w", encoding="utf-8") as f:
            json.dump({"folder": self.folder, "phase": "running", **value}, f)

    def test_the_options(self):
        a, b = self.roots("a", "b")
        both = {"folder", "projects"}
        opts = server.dispatcher_options(["--projects", a, "--projects", os.path.join(b, "x", "..")], both)
        self.assertEqual(opts["projects"], [a, b])
        self.assertEqual(server.dispatcher_options(["--no-projects"], both)["projects"], [])
        self.assertIsNone(server.dispatcher_options([], both)["projects"])
        self.assertEqual(len(server.dispatcher_options(["--projects", a] * 20, both)["projects"]), 20)
        odd = a + os.pathsep + "x"  # a folder's name may hold the path separator
        self.assertEqual(server.dispatcher_options(["--projects", odd], both)["projects"], [odd])
        for argv in (["--projects", a, "--no-projects"], ["--no-projects", "--projects", a],
                     ["--projects", "relative"], ["--projects"],
                     ["--projects", a] * 21):
            with self.subTest(argv=argv), self.assertRaises(ValueError):
                server.dispatcher_options(argv, both)
        for argv in (["--projects", a], ["--no-projects"]):
            with self.assertRaises(ValueError):  # not for uninstall or status
                server.dispatcher_options(argv, {"dry-run"})
        with mock.patch.object(server, "run_dispatcher_supervisor") as run:
            server.run_dispatcher(["run", "--folder", self.folder, "--projects", a, "--sign-in"])
        run.assert_called_once_with(self.folder, None, True, [a])
        with mock.patch.object(server, "dispatcher_setup", return_value=0) as setup:
            server.run_dispatcher(["setup", "--no-projects", "--statusline"])
        setup.assert_called_once_with(self.folder, False, projects=[], statusline=True, ask=input)
        with mock.patch.object(server, "dispatcher_install", return_value=0) as install:
            server.run_dispatcher(["install", "--projects", a, "--projects", b])
        install.assert_called_once_with(self.folder, False, False, projects=[a, b])

    def test_which_folders_can_be_projects_folders(self):
        a, b = self.roots("a", "b")
        sub = os.path.join(a, "sub")
        os.mkdir(sub)
        problem = server.dispatcher_roots_problem
        self.assertIsNone(problem(self.folder, None))
        self.assertIsNone(problem(self.folder, [a, b]))
        self.assertIsNone(problem(self.folder, []))
        self.assertIn("isn't a folder", problem(self.folder, [os.path.join(self.home, "gone")]))
        self.assertIn("the same folder as", problem(self.folder, [a, a]))
        self.assertIn("the same folder as", problem(self.folder, [a, os.path.join(sub, "..")]))
        self.assertIn("inside", problem(self.folder, [a, sub]))
        self.assertIn("inside", problem(self.folder, [sub, a]))
        link, into = os.path.join(self.home, "link"), os.path.join(self.home, "into")
        try:
            dir_link(a, link)
            dir_link(sub, into)
        except OSError as e:
            self.skipTest(f"can't make a link here: {e}")
        self.assertIn("the same folder as", problem(self.folder, [a, link]))
        self.assertIn("inside", problem(self.folder, [into, b, a]))
        self.assertIn("a drive's root", problem(self.folder, [b, os.path.abspath(os.sep)]))
        self.assertIn("the temporary folder", problem(self.folder, [tempfile.gettempdir()]))
        me = os.path.join(a, "me")
        os.mkdir(me)
        with self.home_at(me):
            self.assertIn("your home folder", problem(self.folder, [b, a]))
            self.assertIsNone(problem(self.folder, [b]))
        with self.home_at(b):
            os.mkdir(os.path.join(b, ".nouez"))
            self.assertIn("nouez's own folder", problem(self.folder, [os.path.join(b, ".nouez")]))
        with mock.patch.object(server, "claude_config_dir", lambda: os.path.join(b, ".claude")):
            self.assertIn("Claude Code's settings folder", problem(self.folder, [a, b]))
        # without --projects, the folder above the dispatcher's, which must exist and be fit
        missing = problem(os.path.join(self.home, "nope", "dispatcher"), None)
        self.assertIn("doesn't exist", missing)
        self.assertIn("--projects", missing)
        unfit = problem(os.path.join(tempfile.gettempdir(), "dispatcher"), None)
        self.assertIn("Without --projects", unfit)
        self.assertIn("--no-projects", unfit)

    def test_without_a_projects_folder_the_dispatcher_goes_in_nouezs_own(self):
        """No ~/Projects: the dispatcher's folder is ~/.nouez/dispatcher, setup asks for the
        projects folders (or none) and makes ~/.nouez; a later ~/Projects doesn't move it."""
        home = os.path.join(self.home, "h")
        os.mkdir(home)
        a, = self.roots("work")
        with self.home_at(home):
            folder = self.real_default_folder()
            self.assertEqual(folder, os.path.join(home, ".nouez", "dispatcher"))
            out = []
            self.assertEqual(server.dispatcher_setup(folder, out=out.append), 1)
            self.assertIn("--projects", "\n".join(out))
            self.assertFalse(os.path.exists(os.path.join(home, ".nouez")))
            out = []
            self.assertEqual(server.dispatcher_setup(folder, dry_run=True, out=out.append, projects=[a]), 0, out)
            self.assertIn(f"Would make {os.path.join(home, '.nouez')}.", out)
            self.assertFalse(os.path.exists(os.path.join(home, ".nouez")))
            out = []
            self.assertEqual(server.dispatcher_setup(folder, out=out.append, projects=[a]), 0, out)
            self.assertTrue(os.path.isfile(os.path.join(folder, "CLAUDE.md")))
            self.assertIn(f"The phone can open and trust projects inside {a}.", out)
            self.assertTrue(any(server.shlex.join(["--projects", a]) in line for line in out), out)
            os.mkdir(os.path.join(home, "Projects"))
            self.assertEqual(self.real_default_folder(), folder, "a dispatcher set up there stays the default")
            shutil.rmtree(os.path.join(home, ".nouez"))
            # 0.28 (#2): a new install goes in ~/.nouez/dispatcher even with a ~/Projects, and a bare
            # setup lists the folders that look like they hold projects, choosing none.
            self.assertEqual(self.real_default_folder(), folder)
            out = []
            self.assertEqual(server.dispatcher_setup(folder, out=out.append), 1)
            said = "\n".join(out)
            self.assertNotIn("doesn't exist. Make it", said)  # Neon: ~/.nouez is made by setup, not the user
            self.assertIn(f"  {os.path.join(home, 'Projects')} (0 trusted projects)", said)
            self.assertFalse(os.path.exists(os.path.join(home, ".nouez")))
            os.mkdir(os.path.join(home, ".nouez"))
            os.mkdir(os.path.join(home, ".nouez", "dispatcher"))
            os.mkdir(os.path.join(home, "Projects", "dispatcher"))
            self.assertEqual(self.real_default_folder(), folder, "a folder that merely appears doesn't take its place")
            with open(os.path.join(folder, "CLAUDE.md"), "w"):
                pass
            self.assertEqual(self.real_default_folder(), folder)
            with open(os.path.join(home, "Projects", "dispatcher", "CLAUDE.md"), "w"):
                pass
            self.assertEqual(self.real_default_folder(), os.path.join(home, "Projects", "dispatcher"),
                             "both set up: the one from before 0.27")

    def test_the_projects_folders_a_bare_setup_suggests(self):
        """0.28 (#2): folders holding two or more trusted projects (a folder inside a git
        repository counting as the repository), each once, most projects first; none that
        couldn't be a projects folder."""
        top = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, top, True)
        work, other, repo = (os.path.join(top, n) for n in ("work", "other", os.path.join("code", "repo")))
        for p in (os.path.join(work, "a"), os.path.join(work, "b"), os.path.join(work, "c"),
                  os.path.join(other, "d"), os.path.join(top, "code", "e"), os.path.join(repo, ".git"),
                  os.path.join(repo, "sub")):
            os.makedirs(p)
        trusted = [os.path.join(work, "a"), os.path.join(work, "b"), os.path.join(work, "b") + os.sep,
                   os.path.join(work, "c"), os.path.join(other, "d"), os.path.join(top, "code", "e"),
                   os.path.join(repo, "sub"), os.path.join(top, "gone", "f"), os.path.join(top, "gone", "g")]
        state = os.path.join(top, ".claude.json")
        with open(state, "w", encoding="utf-8") as f:
            json.dump({"projects": {p: {"hasTrustDialogAccepted": True} for p in trusted}}, f)
        with mock.patch.object(server.os.path, "expanduser", side_effect=lambda p: p.replace("~", top)):
            got = server.projects_folder_candidates(state)
        self.assertEqual(got, [(work, 3), (os.path.join(top, "code"), 2)])
        text = server.pick_projects_text(os.path.join(top, ".nouez", "dispatcher"), state)
        self.assertIn("nothing is chosen for you", text)

    def test_setup_offers_the_status_line_and_adds_it_only_on_a_yes(self):
        """0.28 (#52): with no status line in Claude Code's settings, setup offers nouez's: on a
        terminal it asks, elsewhere it says how; it is added only with --statusline or a yes, after
        a copy, keeping the other settings. One of the user's own is kept."""
        top = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, top, True)
        config = os.path.join(top, "claude-profile")
        path = os.path.join(config, "settings.json")
        offer = _REAL_STATUSLINE_OFFER
        tty = mock.Mock(isatty=lambda: True)
        with mock.patch.dict(server.os.environ, {"CLAUDE_CONFIG_DIR": config}):
            out = []
            offer(False, True, out.append)
            self.assertIn("isn't there yet", out[-1])
            os.mkdir(config)
            with open(path, "w", encoding="utf-8") as f:
                json.dump({"model": "opus"}, f)
            out, asked = [], []
            offer(True, True, out.append, asked.append)
            self.assertIn("Would offer", out[-1])
            pipe = mock.Mock(isatty=lambda: False)
            with mock.patch.object(server.sys, "stdin", pipe), mock.patch.object(server.sys, "stdout", pipe):
                offer(False, False, out.append, lambda q: asked.append(q) or "y")  # not a terminal: no question
            self.assertEqual(asked, [])
            self.assertIn("--statusline", out[-1])
            with mock.patch.object(server.sys, "stdin", tty), mock.patch.object(server.sys, "stdout", tty):
                offer(False, False, out.append, lambda q: asked.append(q) or "n")
                self.assertIn("Optional:", out[-1])
                with open(path, encoding="utf-8") as f:
                    self.assertNotIn("statusLine", json.load(f))
                offer(False, False, out.append, lambda q: asked.append(q) or " Yes ")
            self.assertEqual(len(asked), 2)
            self.assertIn("[y/N]", asked[0])
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
            self.assertEqual(data["model"], "opus")
            self.assertTrue(server.ours_statusline(data["statusLine"]))
            self.assertEqual(data["statusLine"]["command"], server.usage_command("statusline"))
            self.assertEqual(len(glob.glob(os.path.join(config, "settings.json.nouez-*.bak"))), 1)
            offer(False, True, out.append)
            self.assertIn("already has nouez's status line", out[-1])
            own = {"statusLine": {"type": "command", "command": "~/bin/my-line.sh"}}
            with open(path, "w", encoding="utf-8") as f:
                json.dump(own, f)
            offer(False, True, out.append)
            self.assertIn("of your own; it is kept", out[-1])
            self.assertIn("statusline --quiet", out[-1])
            with open(path, encoding="utf-8") as f:
                self.assertEqual(json.load(f), own)
        self.assertEqual(server.dispatcher_options(["--statusline"], {"statusline"})["statusline"], True)
        with self.assertRaises(ValueError):
            server.dispatcher_options(["--statusline"], {"folder"})  # install has no --statusline

    def test_setup_and_install_with_several_projects_folders(self):
        a, b = self.roots("work", "Mes projets \u00e9")
        code, out = self.setup(projects=[a, b])
        self.assertEqual(code, 0, out)
        self.assertIn(f"The phone can open and trust projects inside {a}, {b}.", out)
        self.assertIn(server.shlex.join(["server.py", "dispatcher", "install", "--projects", a, "--projects", b]),
                      out)
        with open(os.path.join(self.folder, "CLAUDE.md"), encoding="utf-8") as f:
            self.assertIsNone(server.dispatcher_md_note(self.folder), f.read())
        code, out, ran, popen = self.install("linux", projects=[a, b])
        self.assertEqual(code, 0, out)
        argv = popen.call_args[0][0]
        self.assertEqual(argv[argv.index("--folder") + 2:],
                         ["--projects", a.replace("\\", "/"), "--projects", b.replace("\\", "/"), "--sign-in"])
        code, out, ran, popen = self.install("linux", projects=[a, a])
        self.assertEqual(code, 1, out)
        self.assertIn("the same folder as", out)
        popen.assert_not_called()

    def test_setup_and_install_with_no_projects_folders(self):
        code, out = self.setup(projects=[])
        self.assertEqual(code, 0, out)
        self.assertIn("With --no-projects", out)
        self.assertIn("server.py dispatcher install --no-projects", out)
        code, out, ran, popen = self.install("linux", projects=[])
        self.assertEqual(code, 0, out)
        self.assertEqual(popen.call_args[0][0][-2:], ["--no-projects", "--sign-in"])

    def test_install_keeps_the_projects_folders_it_was_given(self):
        a, b = self.roots("work", "more")
        self.setup()
        self.write_state(projects=[a], projects_given=True)
        code, out, ran, popen = self.install_beside_running("linux")
        self.assertEqual(code, 0, out)
        self.assertIn(f"keeps the projects folders it was given: {a}.", out)
        self.assertEqual(popen.call_args[0][0][-3:], ["--projects", a.replace("\\", "/"), "--sign-in"])
        code, out, ran, popen = self.install("linux", projects=[b])  # named ones replace them
        self.assertNotIn("keeps", out)
        self.assertEqual(popen.call_args[0][0][-3:], ["--projects", b.replace("\\", "/"), "--sign-in"])
        self.write_state(projects=[], projects_given=True)
        code, out, ran, popen = self.install_beside_running("linux")
        self.assertIn("it was given: none (--no-projects).", out)
        self.assertEqual(popen.call_args[0][0][-2:], ["--no-projects", "--sign-in"])
        for state in ({"projects": [self.projects], "projects_given": False},  # the folder above, as by default
                      {"projects": [a], "projects_given": True, "folder": os.path.join(a, "dispatcher")},
                      {"projects": ["relative"], "projects_given": True},
                      {"projects": a, "projects_given": True},
                      {"projects": [a], "projects_given": True, "config_dir": self.home},  # another profile's
                      {"projects": [a], "projects_given": True, "phase": "stopped"},
                      {"projects": [os.path.join(a, str(i)) for i in range(21)], "projects_given": True}):
            with self.subTest(state=state):
                self.write_state(**state)
                code, out, ran, popen = self.install_beside_running("linux")
                self.assertEqual(code, 0, out)
                self.assertNotIn("keeps", out)
                self.assertNotIn("--projects", popen.call_args[0][0])
        self.write_state(projects=[a], projects_given=True)
        code, out, ran, popen = self.install("linux")  # a supervisor that has stopped is no guide
        self.assertEqual(code, 0, out)
        self.assertNotIn("--projects", popen.call_args[0][0])
        code, out, ran, popen = self.install_beside_running("linux", changed={"projects": [b], "projects_given": True})
        self.assertEqual(code, 1, out)
        self.assertIn("the running dispatcher changed while install was checking", out)
        popen.assert_not_called()
        self.write_state(projects=[self.projects], projects_given=False)  # nothing to keep at first
        code, out, ran, popen = self.install_beside_running("linux", changed={"projects": [], "projects_given": True})
        self.assertEqual(code, 1, out)
        self.assertIn("the running dispatcher changed while install was checking", out)
        popen.assert_not_called()

    def install_beside_running(self, platform, changed=None, **kw):
        """install while dispatcher.json's supervisor runs; `changed`: what it records once
        install holds the lock, as when another install replaced it meanwhile."""
        with open(os.path.join(self.cache, "dispatcher.json"), encoding="utf-8") as f:
            first = json.load(f)
        calls = []

        def status():
            calls.append(1)
            return (True, first) if len(calls) == 1 else (len(calls) == 2, dict(first, **(changed or {})))
        with mock.patch.object(server, "dispatcher_status", status):
            return self.install(platform, **kw)

    def test_the_command_is_capped(self):
        self.setup()
        with mock.patch.object(server, "DISPATCHER_COMMAND_MAX", 40):
            code, out, ran, popen = self.install("linux")
        self.assertEqual(code, 1, out)
        self.assertIn("longer than 40 characters", out)
        popen.assert_not_called()
        long = [os.path.join("C:\\" if os.name == "nt" else "/", "p" * 200, str(i)) for i in range(20)]
        argv = server.dispatcher_command(sys.executable, self.folder, None, long)
        self.assertLess(len(subprocess.list2cmdline(argv)), server.DISPATCHER_COMMAND_MAX)

    def test_the_command_and_its_shape(self):
        a, b = self.roots("a", "b c")
        argv = server.dispatcher_command(sys.executable, self.folder, None, [a, b])
        self.assertEqual(argv[6:], [self.folder, "--projects", a, "--projects", b, "--sign-in"])
        self.assertTrue(server.dispatcher_argv_ours(argv))
        self.assertEqual(server.command_projects(argv), [a, b])
        none = server.dispatcher_command(sys.executable, self.folder, self.home, [])
        self.assertEqual(none[7:], ["--no-projects", "--config-dir", self.home, "--sign-in"])
        self.assertTrue(server.dispatcher_argv_ours(none))
        self.assertEqual(server.command_projects(none), [])
        self.assertIsNone(server.command_projects(server.dispatcher_command(sys.executable, self.folder)))
        ours = server.dispatcher_argv_ours
        base = ["/usr/bin/python3", "-I", "/opt/nouez/server.py", "dispatcher", "run", "--folder",
                "/home/me/Projects/dispatcher"]
        for tail, want in ((["--sign-in"], True),  # as 0.26 installed it
                           (["--config-dir", "/home/me/.claude-work", "--sign-in"], True),
                           (["--projects", "/home/me/work", "--sign-in"], True),
                           (["--projects", "/home/me/work", "--projects", "/srv/Mes projets \u00e9", "--config-dir",
                             "/c", "--sign-in"], True),
                           (["--no-projects", "--sign-in"], True),
                           (["--no-projects", "--config-dir", "/c", "--sign-in"], True),
                           (["--projects", "/a"] * 20 + ["--sign-in"], True),
                           (["--projects", "/a"] * 21 + ["--sign-in"], False),
                           (["--projects", "work", "--sign-in"], False),
                           (["--projects", "/a:b", "--sign-in"], True),
                           (["--projects", "/a", "--no-projects", "--sign-in"], False),
                           (["--no-projects", "--projects", "/a", "--sign-in"], False),
                           (["--no-projects", "--no-projects", "--sign-in"], False),
                           (["--projects", "--sign-in"], False),
                           (["--config-dir", "/c", "--projects", "/a", "--sign-in"], False),
                           (["--projects", "/a", "--sign-in", "--projects", "/b"], False)):
            with self.subTest(tail=tail):
                self.assertIs(ours(base + tail, windows=False), want)
        wbase = ["C:\\Py\\pythonw.exe", "-I", "C:\\nouez\\server.py", "dispatcher", "run", "--folder",
                 "C:\\Users\\me\\Projects\\dispatcher"]
        self.assertTrue(ours(wbase + ["--projects", "D:\\work", "--sign-in"], windows=True))
        self.assertTrue(ours(wbase + ["--projects", "D:\\a;b", "--sign-in"], windows=True))
        self.assertFalse(ours(wbase + ["--projects", "\\work", "--sign-in"], windows=True))

    def test_the_environment_and_trust_with_several_roots(self):
        a, b, c = self.roots("a", "b", "c")
        inside = []
        for root in (a, b, c):
            inside.append(os.path.join(root, "p"))
            os.mkdir(inside[-1])
        mark, var = {"NOUEZ_DISPATCHER": "1"}, "NOUEZ_DISPATCHER_PROJECTS"
        env = {**mark, var: json.dumps([a, b])}
        self.assertEqual(server.dispatcher_projects(env), [a, b])
        self.assertEqual(server.dispatcher_projects({**mark, var: "[]"}), [])
        self.assertIsNone(server.dispatcher_projects(mark))
        self.assertIsNone(server.dispatcher_projects({**mark, var: ""}))
        self.assertIsNone(server.dispatcher_projects({**mark, var: json.dumps([a, "relative"])}))
        for bad in ("[", "[1]", '{"a": 1}', "relative"):
            self.assertIsNone(server.dispatcher_projects({**mark, var: bad}), bad)
        legacy = a + os.pathsep + b  # one folder, as a 0.26 supervisor passes it, never split
        self.assertEqual(server.dispatcher_projects({**mark, var: legacy}), [legacy])
        self.assertIsNone(server.dispatcher_projects({var: a}), "outside the dispatcher")
        trust = server.dispatcher_trust_problem
        self.assertIsNone(trust(inside[0], env))
        self.assertIsNone(trust(inside[1], env))
        refused = trust(inside[2], env)
        self.assertIn(f"one of {a}, {b}", refused)
        self.assertIn("isn't one", refused)
        self.assertIn("--no-projects", trust(inside[0], {**mark, var: "[]"}))
        self.assertIn("isn't one", trust(inside[0], {**mark, var: legacy}), "a 0.26 folder isn't split in two")
        self.assertIn("can't tell which folders those are", trust(inside[0], mark))
        temp = tempfile.gettempdir()
        self.assertIsNone(trust(inside[0], {**mark, var: json.dumps([temp, a])}),
                          "a projects folder that can't hold trust is passed over, not the others")
        self.assertIn("isn't one", trust(os.path.join(self.home, "x"), {**mark, var: json.dumps([temp, a])}))
        self.assertIn("records no trust at all", trust(inside[0], {**mark, var: temp}))
        self.assertIn("none of whose projects folders",
                      trust(inside[0], {**mark, var: json.dumps([temp, os.path.abspath(os.sep)])}))

    def test_wait_for_supervisor_knows_it_by_its_projects_folders_too(self):
        a, = self.roots("a")
        state = {"pid": 7, "since": 10.0, "folder": self.folder, "config_dir": None, "sign_in": True,
                 "phase": "running", "projects": [a], "projects_given": True,
                 "script": os.path.abspath(server.__file__)}
        with mock.patch.object(server, "dispatcher_status", lambda: (True, dict(state))):
            wait = server.wait_for_supervisor
            self.assertIs(wait(self.folder, None, 5, projects=[a], seconds=0), True)
            self.assertEqual(wait(self.folder, None, 5, projects=[], seconds=0), "other")
            self.assertEqual(wait(self.folder, None, 5, seconds=0), "other")
            state["projects"] = [self.projects]  # the folder above, but named: another command
            self.assertEqual(wait(self.folder, None, 5, seconds=0), "other")
            self.assertIs(wait(self.folder, None, 5, projects=[self.projects], seconds=0), True)
            state["projects_given"] = False
            self.assertIs(wait(self.folder, None, 5, seconds=0), True)
            state["script"] = os.path.join(self.home, "old", "server.py")  # another clone's
            self.assertEqual(wait(self.folder, None, 5, seconds=0), "other")
            state["script"] = os.path.abspath(server.__file__)
            del state["projects"]  # one from before 0.27
            self.assertEqual(wait(self.folder, None, 5, seconds=0), "other")

    def test_dispatcher_status_keeps_the_spelling_of_the_projects_folders(self):
        a, = self.roots("Mixed Case")
        out = []
        with mock.patch.object(server, "dispatcher_status", lambda: (True, {"folder": self.folder, "projects": [a]})), \
                mock.patch.object(server, "dispatcher_installed", lambda check_off=True, want=None: "yes"):
            server.dispatcher_status_text(out=out.append)
        self.assertIn(f"Projects folders (trust can be recorded inside): {a}", out)

    def test_the_supervisor_records_its_projects_folders_and_its_server(self):
        a, = self.roots("a")
        value = server.DispatcherState(self.folder, projects=[a]).value
        self.assertEqual((value["projects"], value["projects_given"]), ([a], True))
        self.assertEqual(value["script"], os.path.abspath(server.__file__))
        value = server.DispatcherState(self.folder).value
        self.assertEqual((value["projects"], value["projects_given"]), ([self.projects], False))
        self.assertIn(a, server.projects_text([a]))
        self.assertIn("--no-projects", server.projects_text([]))


class ListProjectsFoldersTest(unittest.TestCase):
    """0.27.0: in the dispatcher, ListProjects lists each projects folder. 0.28: its `recent` list is
    gone (resume lists a folder's conversations instead)."""

    def setUp(self):
        self.base = tempfile.mkdtemp(prefix="nouez-test-roots-")
        self.addCleanup(shutil.rmtree, self.base, True)
        self.a, self.b = os.path.join(self.base, "a"), os.path.join(self.base, "b")
        self.here = os.path.join(self.a, "dispatcher")
        for path in (self.here, os.path.join(self.a, "alpha", ".git"), os.path.join(self.a, "alpha", "src"),
                     os.path.join(self.b, "gamma"), os.path.join(self.b, "delta"), os.path.join(self.b, "quiet"),
                     os.path.join(self.base, "claude"), os.path.join(self.base, "elsewhere")):
            os.makedirs(path)
        self.state = os.path.join(self.base, "claude.json")
        for patch in (mock.patch.object(server, "default_cwd", return_value=self.here),
                      mock.patch.object(server, "trusted_folders", return_value=set()),
                      mock.patch.object(server, "claude_sessions", return_value=[]),
                      mock.patch.object(server, "claude_state_file", lambda env=None: self.state),
                      mock.patch.object(server, "claude_config_dir", lambda: os.path.join(self.base, "claude")),
                      mock.patch.dict(os.environ, {"NOUEZ_DISPATCHER": "1",
                                                   "NOUEZ_DISPATCHER_PROJECTS": json.dumps([self.a, self.b])})):
            patch.start()
            self.addCleanup(patch.stop)

    def chat(self, cwd, when, session="s1", ran_in=None):
        folder = server.transcript_folder(cwd)
        os.makedirs(folder, exist_ok=True)
        path = os.path.join(folder, session + ".jsonl")
        with open(path, "w") as f:
            f.write(json.dumps({"cwd": ran_in or cwd}) + "\n")
        os.utime(path, (when, when))

    def test_each_projects_folder_is_listed(self):
        out = server.list_projects({})
        self.assertIn(f"Folders in {self.a} (2):", out)
        self.assertIn(f"Folders in {self.b} (3):", out)
        self.assertIn("- gamma [", out)
        self.assertIn("this session's folder", out)
        with mock.patch.object(server, "PROJECTS_SHOWN", 3):
            out = server.list_projects({})
        self.assertIn("- … and more, not listed", out)
        self.assertNotIn("- quiet [", out)
        with mock.patch.dict(os.environ, {"NOUEZ_DISPATCHER_PROJECTS": json.dumps([self.a, "/gone" if os.name != "nt" else "C:\\gone-nouez"])}):
            out = server.list_projects({})
        self.assertIn("- alpha [", out)
        self.assertIn("isn't a folder", out)
        with mock.patch.dict(os.environ, {"NOUEZ_DISPATCHER_PROJECTS": "[]"}):
            self.assertIn("set up with no projects folders", server.list_projects({}))
        self.assertIn("- gamma [", server.list_projects({"folder": self.b}), "folder still lists one")

    def test_a_transcript_ran_in_the_same_folder_not_one_spelled_alike(self):
        cwd = os.path.join(self.b, "gamma")
        self.chat(cwd, 1000)
        transcript = os.path.join(server.transcript_folder(cwd), "s1.jsonl")
        self.assertTrue(server.ran_here(transcript, cwd))
        with mock.patch.object(server.os.path, "samefile", lambda a, b: False):  # a case-sensitive Repo and repo
            self.assertFalse(server.ran_here(transcript, cwd))
        with mock.patch.object(server.os.path, "samefile", side_effect=FileNotFoundError("gone")):
            self.assertTrue(server.ran_here(transcript, cwd))
        with mock.patch.object(server.os.path, "samefile", side_effect=PermissionError("denied")):
            self.assertFalse(server.ran_here(transcript, cwd))
        self.assertFalse(server.ran_here(transcript, os.path.join(self.b, "delta")))

    def test_the_recent_list_is_gone_and_says_where_to_look(self):
        with self.assertRaises(server.BridgeError) as e:
            server.list_projects({"recent": True})
        self.assertIn("ListClaudeSessions with cwd", str(e.exception))
        tool = next(x for x in server.TOOLS if x["name"] == "ListProjects")
        self.assertNotIn("recent", tool["inputSchema"]["properties"])


class ClonePlaceTest(unittest.TestCase):
    """0.27.0: doctor, setup and install say when nouez runs from a folder that may be emptied, and
    doctor whether what Claude Code and the dispatcher run names this server.py."""

    def setUp(self):
        self.base = tempfile.mkdtemp(prefix="nouez-test-place-")
        self.addCleanup(shutil.rmtree, self.base, True)
        self.here = os.path.abspath(server.__file__)

    def test_a_clone_in_the_temporary_or_downloads_folder(self):
        temp = os.path.join(tempfile.gettempdir(), "nouez", "server.py")
        self.assertIn("the temporary folder", server.clone_place_note(temp))
        home = os.path.join(self.base, "home")
        with mock.patch.dict(os.environ, {"HOME": home, "USERPROFILE": home}), \
                mock.patch.object(server.tempfile, "gettempdir", lambda: os.path.join(self.base, "tmp")), \
                mock.patch.object(server, "known_folder", side_effect=OSError("none")):
            os.makedirs(os.path.join(home, "Downloads", "nouez"))
            note = server.clone_place_note(os.path.join(home, "Downloads", "nouez", "server.py"))
            self.assertIn("the Downloads folder", note)
            self.assertIn("register it again", note)
            self.assertIsNone(server.clone_place_note(os.path.join(home, "nouez", "server.py")))

    def test_a_known_folder_without_windows_libraries_is_an_oserror(self):
        real = __import__

        def no_ctypes(name, *args, **kwargs):
            if name.startswith("ctypes"):
                raise ImportError("cannot import name 'FormatError' from '_ctypes'")
            return real(name, *args, **kwargs)
        with mock.patch("builtins.__import__", no_ctypes):
            with self.assertRaises(OSError):
                server.known_folder(server.FOLDERID_DOWNLOADS)
        if os.name != "nt":
            with self.assertRaises(OSError):  # ctypes without WinDLL
                server.known_folder(server.FOLDERID_DOWNLOADS)
        with mock.patch.object(server.os, "name", "nt"), mock.patch("builtins.__import__", no_ctypes), \
                mock.patch.object(server.tempfile, "gettempdir", lambda: os.path.join(self.base, "tmp")):
            self.assertIsNone(server.clone_place_note(os.path.join(self.base, "nouez", "server.py")))

    def test_the_server_paths_a_command_names(self):
        for command, want in (("Bash(python -I /home/me/nouez/server.py wait *)", ["/home/me/nouez/server.py"]),
                              ('Bash(python -I "C:\\My Files\\nouez\\server.py" wait *)',
                               ["C:\\My Files\\nouez\\server.py"]),
                              ("python '/opt/n z/server.py' statusline", ["/opt/n z/server.py"]),
                              ("python C:/n/server.py hook && echo /x/server.pyc", ["C:/n/server.py"]),
                              ('python -I "C:\\Bob\'s Files\\nouez\\server.py" hook',
                               ["C:\\Bob's Files\\nouez\\server.py"]),
                              ("python '/opt/say \"hi\"/server.py' hook", ['/opt/say "hi"/server.py']),
                              ("python server.py wait 1", []), (None, [])):
            with self.subTest(command=command):
                self.assertEqual(server.scripts_in(command), want)

    def test_doctor_checks_the_stored_paths_name_this_server(self):
        state = os.path.join(self.base, "claude.json")
        here = self.here.replace("\\", "/")
        other = os.path.join(self.base, "old", "server.py")

        def report(settings, registered=(), running=None):
            with open(state, "w", encoding="utf-8") as f:
                json.dump({"mcpServers": {"consultants": {"command": "python", "args": ["-I", *registered]}}}, f)
            with mock.patch.object(server, "claude_state_file", lambda env=None: state), \
                    mock.patch.object(server, "dispatcher_status", lambda: (bool(running), running)):
                return server.script_paths_report(settings)
        self.assertIsNone(report({}))
        rule = {"permissions": {"allow": [f"Bash(python -I {here} wait *)", "Bash(ls *)"]}}
        self.assertEqual(report(rule, [self.here]),
                         (True, "the `consultants` registration and a waiter allow rule name this server.py"))
        self.assertEqual(report(rule), (True, "a waiter allow rule names this server.py"))
        ok, text = report(dict(rule, statusLine={"command": f'python "{other}" statusline'}),
                          running={"script": other})
        self.assertIsNone(ok)
        self.assertIn(f"the status line runs {other}", text)
        self.assertIn(f"the running dispatcher runs {other}", text)
        self.assertIn(f"not this nouez ({self.here})", text)
        self.assertIn("change the path in Claude Code's settings.json", text)
        self.assertIn("run `server.py dispatcher install` from here", text)
        self.assertNotIn("register nouez again", text)
        ok, text = report({"hooks": {"UserPromptSubmit": [{"hooks": [{"command": f"python -I {other} hook"}]}]}},
                          [self.here])
        self.assertIn("the prompt hook runs", text)
        self.assertNotIn("registration", text)
        text = report({}, [other])[1]
        self.assertIn("the `consultants` registration runs", text)
        self.assertIn("register nouez again from here (README, Setup).", text)
        self.assertNotIn("settings.json", text)


if __name__ == "__main__":
    unittest.main()
