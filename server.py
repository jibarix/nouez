"""nouez: MCP server that lets Claude Code talk to Codex sessions.

Tools
  StartConsultant        reuse the repo's consultant, or start a read-only one, shown in a pane
  ListConsultants        Codex sessions on the local app-server daemon
  SendConsultantMessage  send a message into one of them and return its reply
  GetConsultantReply     read (or wait for) a reply sent with wait=0
  WatchConsultant        open a session in a terminal window
  StopConsultant         archive a session that StartConsultant started
  OpenClaudeSession      open a new terminal running a fresh Claude Code session with Remote Control
  ListClaudeSessions     the Claude Code sessions running on this computer
  CloseClaudeSession     close one of them (never the caller)

Command line
  server.py wait <thread_id> <turn_id>   wait for a turn to end and print its reply, for a client
                                         to run in the background so the reply wakes it
  server.py claude <spec.json>           start that Claude Code session (run by OpenClaudeSession)
  server.py allow-rule                   print the Claude Code permission rules that let the
                                         waiter run without asking

Transport to Codex: `codex app-server proxy` relays stdio to the daemon's control
socket, which speaks JSON-RPC over WebSocket. Standard library only.
"""

import base64
import glob
import json
import math
import os
import queue
import reprlib
import re
import shlex
import shutil
import signal
import struct
import subprocess
import sys
import tempfile
import threading
import time
import urllib.parse
import urllib.request

SERVER_NAME = "nouez"
SERVER_VERSION = "0.10.0"
# MCP protocol versions this server answers to, newest first. Nothing nouez uses changed
# between them; a client asking for any other version is offered the newest.
PROTOCOL_VERSIONS = ("2025-11-25", "2025-06-18", "2025-03-26")
POLL_SECONDS = 1.5
MAX_FRAME_BYTES = 64 * 1024 * 1024
RECENT_SAVED_THREADS = 50  # how far back to look for unloaded bridge consultants
REPLY_LOOKBACK = 100  # how many recent turns GetConsultantReply searches for a turn id
MAX_WAIT_SECONDS = 4 * 60 * 60  # ceiling on any wait, wait="done" included, so a hung turn can't pin a call
MAX_REPLY_CHARS = 60_000  # longer replies are cut here; the full text is saved to a file
WAITER_REPLY_CHARS = 20_000  # the same for the waiter, whose output reaches Claude through a shell tool
WAITER_RETRIES = 3  # connection failures in a row the waiter rides out (a daemon restart, say)
WAITER_SECONDS = 25 * 60  # one waiter run; under Claude Code's 30-minute default for background commands
SEND_WAIT_SECONDS = 5  # SendConsultantMessage's default wait: a quick answer fits, a long one doesn't hold the caller
PARTIAL_CHARS = 4_000  # how much of a still-running turn's output a timeout shows (the most recent part)
PROGRESS_SECONDS = 10  # least time between two progress notifications for one call
BRIDGE_SOURCE = "nouez"  # threadSource tag on sessions started by StartConsultant
SANDBOX = "read-only"
RELEASES_URL = "https://api.github.com/repos/jibarix/nouez/releases/latest"
RELEASE_PAGE = "https://github.com/jibarix/nouez/releases/tag/v{}"
RELEASE_CHECK_SECONDS = 24 * 60 * 60  # how long a looked-up latest release is trusted
RELEASE_RETRY_SECONDS = 60 * 60  # how long after a failed lookup the next one waits
RELEASE_TIMEOUT = 3  # seconds each network step of the lookup may block; it runs in the background
# How Codex 0.160.1 reports a session whose history isn't written yet: before the first
# message (titled or not), and in the moment the first turn's rollout file is created.
NO_HISTORY_ERRORS = ("not materialized", "missing source rollout", "no rollout found", "is empty",
                     "list_turns is not supported yet")
_stdout_lock = threading.Lock()
_send_locks = {}  # thread id -> lock, so concurrent sends can't both start a turn
_send_locks_guard = threading.Lock()
_watch_pending = set()  # consultants to open in a terminal once their first turn starts
_unwatched = set()  # StartConsultant sessions started with watch=false: no automatic pane
_update_noted = set()  # latest Codex versions StartConsultant has already told about
_nouez_latest = None  # the latest nouez release found this process, e.g. "0.9.0"
_nouez_noted = False  # whether StartConsultant has told about it
_cancel_events = {}  # MCP request id -> Event set by notifications/cancelled
_cancel_guard = threading.Lock()
_client_caps = {}  # capabilities Claude Code advertised in initialize
_client_roots = None  # Claude Code's workspace folders (roots/list), or None until fetched
_client_requests = {}  # id of a request we sent to Claude Code -> [Event, response]
_client_guard = threading.Lock()
_client_ids = iter(range(1, 1 << 62))


def log(*args):
    print("[consultants]", *args, file=sys.stderr, flush=True)


class BridgeError(Exception):
    pass


class DaemonDown(BridgeError):
    pass


class Cancelled(Exception):
    pass


def check_cancel(cancel):
    if cancel is not None and cancel.is_set():
        raise Cancelled()


def flag(args, key, default=False):
    """A boolean argument. Accepts JSON booleans and the strings "true"/"false"; anything else is
    an error rather than truthy, so "false" can't turn into an unlimited wait."""
    value = args.get(key, default)
    if isinstance(value, bool):
        return value
    if isinstance(value, str) and value.strip().lower() in ("true", "false"):
        return value.strip().lower() == "true"
    raise BridgeError(f"`{key}` must be true or false, not {value!r}.")


def wait_seconds(args, default):
    """How long to wait for a turn: `wait` is a number of seconds (0 = don't wait) or "done" (until
    the turn ends), capped at MAX_WAIT_SECONDS. The options it replaced are refused, not guessed at."""
    for old, new in (("until_done", 'wait="done"'), ("timeout_seconds", "wait=<seconds>")):
        if old in args:
            raise BridgeError(f"`{old}` was replaced by `wait` in nouez 0.4: pass {new}.")
    value = args.get("wait", default)
    if isinstance(value, str) and value.strip().lower() == "done":
        return MAX_WAIT_SECONDS
    try:
        if isinstance(value, bool):
            raise ValueError
        seconds = float(value)
        if not math.isfinite(seconds) or seconds < 0:
            raise ValueError
    except (TypeError, ValueError, OverflowError):
        raise BridgeError(f"`wait` must be a number of seconds, 0 or more (0 = don't wait), or \"done\", "
                          f"not {reprlib.repr(value)}.") from None
    return min(seconds, MAX_WAIT_SECONDS)


def target(args):
    """The consultant to address. `name` is accepted too: StartConsultant returns a name, and
    callers sometimes pass it under that key."""
    value = args.get("to") or args.get("name") or ""
    if not value:
        raise BridgeError("`to` is required: the consultant name StartConsultant returned, or its thread id.")
    return value


def kill_tree(proc):
    if proc.poll() is not None:
        return
    if os.name == "nt":
        try:
            subprocess.run(["taskkill", "/F", "/T", "/PID", str(proc.pid)], stdin=subprocess.DEVNULL,
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=10)
        except (OSError, subprocess.SubprocessError):
            pass
    if proc.poll() is None:
        proc.kill()


def run_text(argv, timeout=20):
    """A command's stdout, or "" if it fails or times out. Unlike subprocess.run, this can't hang:
    on Windows, run() kills only the direct child at the timeout and then waits for the pipes to
    close, which never happens while a grandchild (git's cmd shim, an npm .cmd shim) holds them."""
    try:
        proc = subprocess.Popen(argv, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                stderr=subprocess.DEVNULL, text=True)
    except OSError:
        return ""
    try:
        return proc.communicate(timeout=timeout)[0] or ""
    except subprocess.TimeoutExpired:
        kill_tree(proc)  # abandon the pipe readers rather than wait on them
        return ""


# --- Codex app-server client -------------------------------------------------

DAEMON_START_SECONDS = 20  # how long to wait for a daemon we started to accept connections


def start_daemon(exe):
    """Run `codex app-server daemon start`, which does nothing if the daemon is already up.
    No pipes and no kill on timeout: the daemon outlives this command, and would hold a pipe
    open or die with the tree."""
    log("Codex daemon not reachable; starting it")
    env = daemon_env(os.environ) if os.name == "nt" else None
    try:
        subprocess.Popen([exe, "app-server", "daemon", "start"], stdin=subprocess.DEVNULL,
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, env=env).wait(timeout=30)
    except (OSError, subprocess.TimeoutExpired):
        pass


GIT_BASH_VARIABLES = ("MSYSTEM", "SHELL", "EXEPATH")  # set by Git Bash for its own shell


def daemon_env(environ):
    """The Windows environment to start the daemon with, or None to inherit `environ`. Under Git
    Bash (MSYSTEM is set; Claude Code's Bash tool runs the waiter there) the daemon, and with it
    `codex app-server daemon update`, would inherit MSYS's PATH: the updater's bare `tar` then finds
    GNU tar, which reads `C:` as a remote host, and the update fails. So drop Git Bash's variables
    and the PATH folders holding msys-2.0.dll; a PATH the user set up without MSYSTEM is left alone."""
    if not environ.get("MSYSTEM"):
        return None
    env = {k: v for k, v in environ.items() if k.upper() not in GIT_BASH_VARIABLES}
    for key in [k for k in env if k.upper() == "PATH"]:
        env[key] = ";".join(p for p in env[key].split(";")
                            if p and not os.path.isfile(os.path.join(p, "msys-2.0.dll")))
    return env


class CodexClient:
    """One short-lived connection to the Codex app-server daemon."""

    def __init__(self, timeout=15):
        exe = shutil.which("codex")
        if not exe:
            raise BridgeError("`codex` CLI not found on PATH.")
        self.timeout = timeout
        self.next_id = 1
        self.q = queue.Queue()
        self._write_lock = threading.Lock()
        try:
            self._connect(exe)
        except DaemonDown:
            # Nothing is listening: start the daemon ourselves and wait for its socket.
            start_daemon(exe)
            deadline = time.monotonic() + DAEMON_START_SECONDS
            while True:
                try:
                    self._connect(exe)
                    break
                except DaemonDown:
                    if time.monotonic() >= deadline:
                        raise
                    time.sleep(0.5)
        try:
            threading.Thread(target=self._reader, daemon=True).start()
            # userAgent carries the daemon's version and codexHome its install root.
            self.info = self.request("initialize", {"clientInfo": {"name": "nouez", "version": SERVER_VERSION}})
            self.notify("initialized")
        except Exception:
            self.close()
            raise

    def _connect(self, exe):
        self.proc = subprocess.Popen(
            [exe, "app-server", "proxy"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
        )
        try:
            self._handshake()
        except Exception:
            self.close()
            raise

    def _handshake(self):
        # Read the upgrade response on a side thread and wait with a deadline. Killing a hung
        # proxy doesn't reliably unblock a read: a grandchild can keep the pipe open.
        result = {}

        def read_header():
            try:
                header = b""
                while not header.endswith(b"\r\n\r\n"):
                    c = self.proc.stdout.read(1)
                    if not c:
                        result["eof"] = True
                        return
                    header += c
                result["header"] = header
            except (OSError, ValueError):
                result["eof"] = True

        try:
            key = base64.b64encode(os.urandom(16)).decode()
            self.proc.stdin.write(
                (
                    "GET / HTTP/1.1\r\nHost: localhost\r\nUpgrade: websocket\r\n"
                    f"Connection: Upgrade\r\nSec-WebSocket-Key: {key}\r\n"
                    "Sec-WebSocket-Version: 13\r\n\r\n"
                ).encode()
            )
            self.proc.stdin.flush()
        except OSError:
            result["eof"] = True
        if not result:
            reader = threading.Thread(target=read_header, daemon=True)
            reader.start()
            reader.join(self.timeout)
        if result.get("eof"):
            raise DaemonDown(
                "Codex app-server daemon is not reachable, and starting it did not help. Run "
                "`codex app-server daemon start` in a terminal to see why, or open a Codex session."
            )
        if "header" not in result:
            raise BridgeError(f"Codex app-server proxy did not respond within {self.timeout}s.")
        header = result["header"]
        if b" 101 " not in header.split(b"\r\n", 1)[0]:
            raise BridgeError(f"WebSocket upgrade refused: {header[:200]!r}")

    def _read_exact(self, n):
        buf = b""
        while len(buf) < n:
            chunk = self.proc.stdout.read(n - len(buf))
            if not chunk:
                raise EOFError
            buf += chunk
        return buf

    def _reader(self):
        partial = b""
        try:
            while True:
                head = self._read_exact(2)
                fin, opcode = head[0] & 0x80, head[0] & 0x0F
                length = head[1] & 0x7F
                if length == 126:
                    length = struct.unpack(">H", self._read_exact(2))[0]
                elif length == 127:
                    length = struct.unpack(">Q", self._read_exact(8))[0]
                if length + len(partial) > MAX_FRAME_BYTES:
                    raise ValueError("message too large")
                mask = self._read_exact(4) if head[1] & 0x80 else None
                data = self._read_exact(length)
                if mask:
                    data = bytes(b ^ mask[i % 4] for i, b in enumerate(data))
                if opcode == 0x8:
                    break
                if opcode == 0x9:
                    self._send_frame(data, 0xA)
                elif opcode in (0x0, 0x1):
                    partial += data
                    if fin:
                        self.q.put(json.loads(partial))
                        partial = b""
        except (EOFError, OSError, ValueError):
            pass
        self.q.put(None)

    def _send_frame(self, data, opcode=0x1):
        mask = os.urandom(4)
        n = len(data)
        if n < 126:
            header = bytes([0x80 | opcode, 0x80 | n])
        elif n < 65536:
            header = bytes([0x80 | opcode, 0x80 | 126]) + struct.pack(">H", n)
        else:
            header = bytes([0x80 | opcode, 0x80 | 127]) + struct.pack(">Q", n)
        masked = bytes(b ^ mask[i % 4] for i, b in enumerate(data))
        # The reader thread answers pings while a request may be writing.
        with self._write_lock:
            self.proc.stdin.write(header + mask + masked)
            self.proc.stdin.flush()

    def notify(self, method, params=None):
        msg = {"method": method}
        if params is not None:
            msg["params"] = params
        self._send_frame(json.dumps(msg).encode())

    def request(self, method, params):
        rid = self.next_id
        self.next_id += 1
        self._send_frame(json.dumps({"id": rid, "method": method, "params": params}).encode())
        deadline = time.monotonic() + self.timeout
        while time.monotonic() < deadline:
            try:
                msg = self.q.get(timeout=0.5)
            except queue.Empty:
                continue
            if msg is None:
                raise BridgeError(f"Codex daemon closed the connection during {method}.")
            if msg.get("id") == rid and "method" not in msg:
                if "error" in msg:
                    raise BridgeError(f"{method} failed: {msg['error'].get('message', msg['error'])}")
                return msg.get("result", {})
        raise BridgeError(f"{method} timed out after {self.timeout}s.")

    def close(self):
        kill_tree(self.proc)


# --- Consultant logic --------------------------------------------------------


def short_name(thread):
    cwd = (thread.get("cwd") or "").rstrip("\\/")
    base = os.path.basename(cwd) or "codex"
    return f"codex-{base}-{thread['id'][-6:]}".lower()


def is_bridge(thread):
    return thread.get("threadSource") == BRIDGE_SOURCE


def status_label(thread):
    if not thread.get("_loaded"):
        return "idle (unloaded; reloads on the next message)"
    status = thread.get("status") or {}
    kind = status.get("type", "unknown")
    if kind == "active":
        flags = status.get("activeFlags") or []
        return "busy" + (f" ({', '.join(flags)})" if flags else "")
    return kind


def read_thread(client, tid):
    """The thread, or None if the daemon doesn't know it. Connection failures still raise."""
    try:
        return client.request("thread/read", {"threadId": tid}).get("thread") or None
    except BridgeError as e:
        if "timed out" in str(e) or "closed the connection" in str(e):
            raise
        return None


def load_consultants(client, include_all=False):
    """Sessions loaded on the daemon, plus recent bridge consultants the daemon has unloaded.
    The daemon unloads idle sessions with no subscriber after about a minute."""
    ids, cursor = [], None
    while True:
        page = client.request("thread/loaded/list", {"cursor": cursor} if cursor else {})
        ids += page.get("data", [])
        cursor = page.get("nextCursor")
        if not cursor:
            break
    consultants = []
    for tid in ids:
        thread = read_thread(client, tid)
        if not thread:
            continue
        # Hide Codex-internal threads (subagents, guardian reviews) unless asked.
        if not include_all and (thread.get("ephemeral") or thread.get("parentThreadId")):
            continue
        thread["_loaded"] = True
        consultants.append(thread)
    # thread/list omits threadSource, so read each recent unloaded session to find ours.
    saved = client.request("thread/list", {"limit": RECENT_SAVED_THREADS}).get("data", [])
    for summary in saved:
        if summary["id"] in ids:
            continue
        thread = read_thread(client, summary["id"])
        if thread and is_bridge(thread):
            thread["_loaded"] = False
            consultants.append(thread)
    return consultants


def resolve(client, target, exact_only=False):
    """The session `target` names. exact_only (for destructive tools) skips id prefix/suffix matches."""
    target = target.strip().lower()
    threads = load_consultants(client, include_all=True)
    exact = [t for t in threads if target in (t["id"].lower(), short_name(t))]
    if len(exact) == 1:
        return exact[0]
    if exact:
        # Names keep only the id's last six characters, so two sessions can share one.
        ids = ", ".join(t["id"] for t in exact)
        raise BridgeError(f"'{target}' names more than one session. Use the full thread id: {ids}")
    partial = [] if exact_only else [
        t for t in threads if t["id"].lower().startswith(target) or t["id"].lower().endswith(target)]
    if len(partial) == 1:
        return partial[0]
    if partial:
        raise BridgeError(f"'{target}' is ambiguous. Matches: {', '.join(short_name(t) for t in partial)}")
    # An older consultant addressed by its full id.
    thread = read_thread(client, target)
    if thread:
        thread["_loaded"] = False
        return thread
    names = ", ".join(short_name(t) for t in threads) or "none"
    exact_note = " Use its exact name or full thread id." if exact_only else ""
    raise BridgeError(f"No Codex session named '{target}'.{exact_note} Sessions: {names}")


def ensure_loaded(client, thread):
    """(Re)load the session. Always resume rather than trust the loaded snapshot, which can go
    stale if the daemon unloads it meanwhile. Resume keeps its saved sandbox and approval policy."""
    try:
        client.request("thread/resume", {"threadId": thread["id"], "excludeTurns": True})
    except BridgeError as e:
        # A session with no history can't be resumed; it is the freshly started, still-loaded one.
        if not any(s in str(e) for s in NO_HISTORY_ERRORS):
            raise
    thread["_loaded"] = True


def list_turns(client, thread_id, limit):
    """Most recent turns first. A fresh session has no turns yet, and the daemon refuses
    thread/turns/list until its first turn is written: treat that as empty."""
    try:
        params = {"threadId": thread_id, "limit": limit, "sortDirection": "desc"}
        return client.request("thread/turns/list", params).get("data", [])
    except BridgeError as e:
        if any(s in str(e) for s in NO_HISTORY_ERRORS):
            return []
        raise


def latest_turn(client, thread_id):
    data = list_turns(client, thread_id, 1)
    return data[0] if data else None


def find_turn(client, thread_id, turn_id, limit=10):
    return next((t for t in list_turns(client, thread_id, limit) if t.get("id") == turn_id), None)


def user_texts(turn):
    return [c.get("text", "") for i in turn.get("items", []) if i.get("type") == "userMessage"
            for c in (i.get("content") or [])]


def continuation(client, tid, turn_id, text):
    """The turn that carried on an interrupted one, if it visibly contains our message.
    A steer that lands early can interrupt a turn and continue in a new one; matching on
    our own text avoids returning a reply meant for someone else."""
    newer = []
    for t in list_turns(client, tid, 10):  # newest first
        if t["id"] == turn_id:
            break
        newer.append(t)
    return next((t for t in reversed(newer) if any(text in u for u in user_texts(t))), None)


def turn_reply(turn):
    messages = [i for i in turn.get("items", []) if i.get("type") == "agentMessage"]
    finals = [m["text"] for m in messages if m.get("phase") == "final_answer"]
    return "\n\n".join(finals or [m.get("text", "") for m in messages[-1:]])


def wait_for_turn(client, tid, turn_id, timeout, cancel, text=None, on_poll=None):
    """Poll until the turn finishes. Returns (done, turn_id, turn): on timeout, done is False and
    turn is the last snapshot seen (or None). With `text` (the message we sent), follow an
    interrupted turn into its continuation; turn_id is then the continuation's id. on_poll(turn_id,
    turn) is called with each snapshot of a turn still running."""
    deadline = time.monotonic() + timeout
    grace = None  # an interrupted turn's continuation may take a moment to be listed
    while True:
        turn = find_turn(client, tid, turn_id)
        if on_poll and turn and turn.get("status") == "inProgress":
            on_poll(turn_id, turn)
        if turn and turn.get("status") == "interrupted" and text:
            nxt = continuation(client, tid, turn_id, text)
            if nxt:
                turn_id, grace = nxt["id"], None
                continue
            grace = grace or time.monotonic() + 5
            if time.monotonic() < grace:
                check_cancel(cancel)
                time.sleep(0.5)
                continue
        if turn and turn.get("status") != "inProgress":
            return True, turn_id, turn
        if time.monotonic() >= deadline:
            return False, turn_id, turn
        check_cancel(cancel)
        time.sleep(POLL_SECONDS)


def cap_reply(turn_id, reply, limit=MAX_REPLY_CHARS):
    """The reply, or its first `limit` characters with the rest saved to a file the caller can read."""
    if len(reply) <= limit:
        return reply
    folder = os.path.join(tempfile.gettempdir(), "nouez")
    path = os.path.join(folder, re.sub(r"[^0-9A-Za-z-]", "_", turn_id) + ".md")
    try:
        os.makedirs(folder, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write(reply)
        where = f"The full reply is saved in {path}."
    except OSError as e:
        where = f"The full reply could not be saved ({e}); read it in the consultant's pane."
    omitted = len(reply) - limit
    return f"{reply[:limit]}\n\n[Truncated: {omitted} more characters. {where}]"


def partial_output(turn):
    """What a running turn has written since its latest user message, newest part kept.
    Every agent message counts, whatever its phase: a final_answer isn't final until the turn ends."""
    items = (turn or {}).get("items") or []
    last_user = max((i for i, item in enumerate(items) if item.get("type") == "userMessage"), default=-1)
    text = "\n\n".join(item.get("text", "") for item in items[last_user + 1:]
                       if item.get("type") == "agentMessage" and item.get("text"))
    if len(text) > PARTIAL_CHARS:
        text = f"[... {len(text) - PARTIAL_CHARS} earlier characters omitted]\n{text[-PARTIAL_CHARS:]}"
    return text


def still_working(name, turn_id, turn, advice):
    """The answer for a turn that hasn't ended: clearly not a reply, with its output so far."""
    out = f"{name} is still working on turn {turn_id}; this is not a reply. {advice}"
    partial = partial_output(turn)
    if partial:
        out += ("\n\nOutput so far (a snapshot of the running turn; it may change and is not "
                f"the final answer):\n{partial}")
    return out


def waiter_prefix():
    """The start of every waiter command: this interpreter and this file, with absolute paths.
    A path is quoted only if it has a space, so the command runs as is in bash and PowerShell
    alike and a permission rule can match it by prefix."""
    def q(path):
        path = path.replace("\\", "/")
        return f'"{path}"' if " " in path else path
    return f"{q(sys.executable)} -I {q(os.path.abspath(__file__))} wait"


def waiter_command(thread_id, turn_id):
    """The shell command that waits for a turn and prints its reply."""
    cmd = f"{waiter_prefix()} {thread_id} {turn_id}"
    return cmd + ("\n(In PowerShell, put & and a space before it.)" if cmd.startswith('"') else "")


def allow_rules():
    """Claude Code permission rules matching every waiter command of this install, one per shell tool."""
    return [f"{tool}({waiter_prefix()} *)" for tool in ("Bash", "PowerShell")]


def read_later(thread_id, turn_id):
    """What to do about a reply that isn't ready: leave the caller free, and have the reply wake it."""
    return ("Don't wait for the reply. To be woken when it is ready, run this as a background command "
            "(in Claude Code: the Bash or PowerShell tool with run_in_background); it exits with the reply when the "
            f"turn ends:\n{waiter_command(thread_id, turn_id)}\nThen tell the user the consultation is "
            "under way and carry on with other work or end your turn. If you can't run background "
            f"commands, read the reply later with GetConsultantReply (turn_id {turn_id}).")


def progress_reporter(progress, name):
    """An on_poll for wait_for_turn that reports the wait as MCP progress, or None without a token."""
    if not progress:
        return None
    started = time.monotonic()

    def report(turn_id, turn):
        latest = partial_output(turn).strip().splitlines()[-1:]
        note = f": {latest[0][:150]}" if latest else ""
        progress(f"{name} is working on turn {turn_id} (waited {time.monotonic() - started:.0f}s){note}")
    return report


def format_turn(name, turn, limit=MAX_REPLY_CHARS):
    reply = cap_reply(turn["id"], turn_reply(turn), limit)
    if turn["status"] != "completed":
        err = (turn.get("error") or {}).get("message", "")
        hint = ("\nIf the message was folded into a later turn, read it with GetConsultantReply."
                if turn["status"] == "interrupted" else "")
        return f"{name}: turn {turn['id']} {turn['status']}. {err}\nPartial reply:\n{reply or '(none)'}{hint}"
    return f"Reply from {name}:\n\n{reply or '(no text reply)'}"


def send_lock(tid):
    with _send_locks_guard:
        return _send_locks.setdefault(tid, threading.Lock())


def set_watch(tid, on=True):
    with _send_locks_guard:
        (_watch_pending.add if on else _watch_pending.discard)(tid)


def wants_pane(thread):
    """StartConsultant sessions are shown beside Claude Code unless started with watch=false.
    Sessions the user opened already have their own terminal."""
    with _send_locks_guard:
        return is_bridge(thread) and thread["id"] not in _unwatched


def take_watch(tid):
    """Atomically claim a pending watch request, so only one sender opens the window."""
    with _send_locks_guard:
        if tid in _watch_pending:
            _watch_pending.discard(tid)
            return True
        return False


def version_of(text):
    m = re.search(r"(\d+\.\d+\.\d+[^\s;)]*)", text or "")
    return m.group(1) if m else None


def codex_version(exe):
    return version_of(run_text([shutil.which(exe) or exe, "--version"], timeout=10))


def viewer_codex(info):
    """The `codex` to open a viewer with, plus a warning to show if it may not match the daemon.
    Codex auto-updates its managed daemon apart from the codex on PATH, and a viewer whose
    version differs can refuse to attach ("incompatible feature set") and offer to restart the
    shared daemon. So run the daemon's own binary when it can be found."""
    info = info or {}
    version = version_of((info.get("userAgent") or "").split("/", 1)[-1])
    home = info.get("codexHome")
    if version and home:
        exe = "codex.exe" if os.name == "nt" else "codex"
        pattern = os.path.join(glob.escape(home), "packages", "app-server-daemon", "releases",
                               glob.escape(version) + "-*", "bin", exe)
        for path in sorted(glob.glob(pattern)):
            if codex_version(path) == version:
                return path, ""
    on_path = codex_version("codex")
    if version and on_path and on_path != version:
        return "codex", (f" Warning: the codex CLI on PATH is {on_path} but the daemon is {version}, so the "
                         "window may ask to restart the daemon. Choose Cancel (restarting interrupts running "
                         f"consultants) and update the codex CLI to {version}.")
    return "codex", ""


def version_key(version):
    return tuple(int(n) for n in re.findall(r"\d+", version.split("-", 1)[0])[:3])


def update_notice(info):
    """A note for the result when the codex CLI or the daemon is behind the latest Codex release,
    or "" (also once it has been given in this server process). The latest version comes from
    the cache Codex keeps for its own update check, so nothing goes over the network; a version
    the user dismissed in Codex isn't raised again."""
    info = info or {}
    home = info.get("codexHome")
    if not home:
        return ""
    try:
        with open(os.path.join(home, "version.json"), encoding="utf-8") as f:
            cache = json.load(f)
        latest = version_of(cache.get("latest_version"))
    except (OSError, ValueError, AttributeError):
        return ""
    if not latest or cache.get("dismissed_version") == latest:
        return ""
    with _send_locks_guard:
        if latest in _update_noted:
            return ""
    daemon = version_of((info.get("userAgent") or "").split("/", 1)[-1])
    cli = codex_version("codex")
    behind = [(what, v) for what, v in (("the codex CLI on PATH", cli), ("the app-server daemon", daemon))
              if v and version_key(v) < version_key(latest)]
    if not behind:
        return ""
    with _send_locks_guard:
        _update_noted.add(latest)
    steps = []
    if any(what.startswith("the codex CLI") for what, _ in behind):
        steps.append("`codex update` updates the CLI")
    if any(what.startswith("the app-server daemon") for what, _ in behind):
        steps.append("`codex app-server daemon update` updates the daemon, which may interrupt running "
                     "Codex work, consultants and the user's own sessions included")
    return (f"Codex {latest} is out; " + " and ".join(f"{what} is {v}" for what, v in behind) + ". "
            "Tell the user and go ahead with the consultation. Only if the user asks you to update, "
            "run these in a shell: " + "; ".join(steps) + ".")


RELEASE_VERSION = re.compile(r"\d{1,6}\.\d{1,6}\.\d{1,6}")
RELEASE_CACHE_BYTES = 4096  # a cache file bigger than this isn't nouez's


def update_check_off(env=None):
    """Whether the user turned off the nouez release check with NOUEZ_NO_UPDATE_CHECK."""
    value = (os.environ if env is None else env).get("NOUEZ_NO_UPDATE_CHECK", "").strip().lower()
    return value not in ("", "0", "false", "no")


def release_cache_file():
    """Where the latest release looked up is kept, in the user's own cache folder."""
    if os.name == "nt":
        base = os.environ.get("LOCALAPPDATA") or os.path.expanduser(os.path.join("~", "AppData", "Local"))
    else:
        base = os.environ.get("XDG_CACHE_HOME") or os.path.expanduser(os.path.join("~", ".cache"))
    return os.path.join(base, "nouez", "latest-release.json")


def fetch_latest_release():
    """The version of the latest nouez release on GitHub, e.g. "0.9.0" for the tag "v0.9.0",
    or None. GitHub's latest-release answer leaves out drafts and pre-releases."""
    req = urllib.request.Request(RELEASES_URL, headers={
        "Accept": "application/vnd.github+json", "User-Agent": f"nouez/{SERVER_VERSION}"})
    with urllib.request.urlopen(req, timeout=RELEASE_TIMEOUT) as r:
        data = json.loads(r.read(1_000_000).decode("utf-8"))
    tag = data.get("tag_name") if isinstance(data, dict) else None
    if isinstance(tag, str) and tag.startswith("v") and RELEASE_VERSION.fullmatch(tag[1:]):
        return tag[1:]
    return None


def read_release_cache(path, now):
    """(fresh, latest) from the cache file. A successful lookup stays fresh for a day, a
    failed one (latest None) for an hour; anything unreadable or odd is not fresh."""
    try:
        with open(path, encoding="utf-8") as f:
            text = f.read(RELEASE_CACHE_BYTES + 1)
        if len(text) > RELEASE_CACHE_BYTES:
            return False, None
        cache = json.loads(text)
        checked, latest = cache["checked"], cache["latest"]
        if isinstance(checked, bool) or not isinstance(checked, (int, float)) or not math.isfinite(checked):
            return False, None
        if latest is not None and not (isinstance(latest, str) and RELEASE_VERSION.fullmatch(latest)):
            return False, None
        keep = RELEASE_CHECK_SECONDS if latest else RELEASE_RETRY_SECONDS
        return 0 <= now - checked < keep, latest
    except (OSError, ValueError, KeyError, TypeError, OverflowError):
        return False, None


def save_release_cache(path, now, latest):
    """Write the cache through a temporary file of its own, so servers starting together
    don't write into the same file; a failure leaves no temporary file behind."""
    tmp = None
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        fd, tmp = tempfile.mkstemp(prefix="latest-release.", suffix=".tmp", dir=os.path.dirname(path))
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump({"checked": now, "latest": latest}, f)
        os.replace(tmp, path)
        tmp = None
    except OSError:
        pass
    finally:
        if tmp:
            try:
                os.remove(tmp)
            except OSError:
                pass


def latest_release(now=None):
    """The latest nouez release: from the cache file if it's fresh, otherwise from GitHub.
    The answer is saved for next time, and so is a failure, so an offline computer or a rate
    limit means one attempt an hour rather than one per server. None if there's no answer."""
    now = time.time() if now is None else now
    path = release_cache_file()
    fresh, latest = read_release_cache(path, now)
    if fresh:
        return latest
    try:
        latest = fetch_latest_release()
    except Exception:  # offline, a proxy, a rate limit, a bad answer: say nothing
        latest = None
    save_release_cache(path, now, latest)
    return latest


def check_for_release():
    global _nouez_latest
    if update_check_off():
        return
    try:
        latest = latest_release()
    except Exception:  # an optional check: never let it surface anywhere
        return
    if latest:
        with _send_locks_guard:
            _nouez_latest = latest


def start_release_check():
    """Look up the latest nouez release in the background, so no tool call waits for it. A
    thread that can't start just means no check: the initialize answer is already sent."""
    if update_check_off():
        return
    try:
        threading.Thread(target=check_for_release, daemon=True).start()
    except Exception as e:
        log(f"release check not started: {e}")


def shell_literal(path):
    """The path in single quotes, which PowerShell, Bash and zsh all read literally, or None if
    it holds a single quote or a control character (those would need shell-specific quoting).
    PowerShell also ends a single-quoted string at the typographic quotes ‘ ’ ‚ ‛."""
    if any(c in "'‘’‚‛" or ord(c) < 32 or ord(c) == 127 for c in path):
        return None
    return f"'{path}'"


def nouez_update_notice():
    """A note for StartConsultant's result when a newer nouez is released, or "" (also once it
    has been given in this server process)."""
    global _nouez_noted
    with _send_locks_guard:
        latest = _nouez_latest
        if (not latest or _nouez_noted or not RELEASE_VERSION.fullmatch(latest)
                or version_key(latest) <= version_key(SERVER_VERSION)):
            return ""
        _nouez_noted = True
    folder = os.path.dirname(os.path.abspath(__file__))
    page = RELEASE_PAGE.format(latest)
    shown = folder.replace("\\", "/") if os.name == "nt" else folder
    quoted = shell_literal(shown)
    reconnect = ("ask the user to run /mcp and reconnect consultants, which loads the new "
                 "version; the Codex consultants keep their sessions.")
    if os.path.exists(os.path.join(folder, ".git")) and quoted:
        how = (f"run `git -C {quoted} pull` in a shell. If git fails (local changes, a conflict, "
               "no branch checked out), stop there: tell the user what git said, don't ask them "
               "to reconnect, and don't discard, stash or switch anything without the user's say. "
               "Only after the pull succeeds, " + reconnect)
    elif os.path.exists(os.path.join(folder, ".git")):
        how = (f"tell the user to run git pull themselves in the nouez folder {json.dumps(shown)}, "
               "whose name needs quoting this notice doesn't attempt; once it succeeds, " + reconnect)
    else:
        how = f"tell the user to download it from {page} into {json.dumps(shown)}; then " + reconnect
    return (f"nouez {latest} is out; this server is {SERVER_VERSION}. What changed: {page}. "
            "Tell the user and go ahead with the consultation. Only if the user asks you to update, "
            + how)


def safe_nouez_update_notice():
    """nouez_update_notice, but an optional note can never fail a consultation."""
    try:
        return nouez_update_notice()
    except Exception as e:
        log(f"nouez update notice skipped: {e}")
        return ""


def viewer_running(thread_id):
    """Whether some `codex resume <id>` is already showing the session, whether open_terminal
    started it or the user did. Errs toward False, so a failed check still opens a window."""
    if not re.fullmatch(r"[0-9A-Za-z-]+", thread_id):
        return False
    if os.name == "nt":
        ps = ("@(Get-CimInstance Win32_Process -Filter \"Name='codex.exe'\" | Where-Object "
              f"{{ $_.CommandLine -like '* resume {thread_id}*' }}).Count")
        out = run_text(["powershell", "-NoProfile", "-NonInteractive", "-Command", ps]).strip()
        return out.isdigit() and int(out) > 0
    return bool(run_text(["pgrep", "-f", f"codex[^ ]* resume {thread_id}"]).split())


_console_lock = threading.Lock()  # AttachConsole is per process, so one lookup at a time


def _wt_user32():
    import ctypes
    from ctypes import wintypes
    user32, kernel32 = ctypes.windll.user32, ctypes.windll.kernel32
    kernel32.GetConsoleWindow.restype = wintypes.HWND
    user32.GetWindow.restype = wintypes.HWND
    user32.GetWindow.argtypes = [wintypes.HWND, ctypes.c_uint]
    user32.GetForegroundWindow.restype = wintypes.HWND
    user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.c_void_p]
    for name in ("GetClassNameW", "GetWindowTextW"):
        getattr(user32, name).argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
    for name in ("SetForegroundWindow", "BringWindowToTop", "IsIconic", "IsWindow", "IsHungAppWindow"):
        getattr(user32, name).argtypes = [wintypes.HWND]
    user32.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
    return ctypes, user32, kernel32


def _window_text(ctypes, user32, hwnd, getter="GetWindowTextW"):
    buf = ctypes.create_unicode_buffer(512)
    getattr(user32, getter)(hwnd, buf, 512)
    return buf.value


def process_table():
    """Windows: {pid: (parent pid, exe name)} for every running process, or {} if it can't be read."""
    import ctypes
    from ctypes import wintypes

    class Entry(ctypes.Structure):
        _fields_ = [("dwSize", wintypes.DWORD), ("cntUsage", wintypes.DWORD),
                    ("th32ProcessID", wintypes.DWORD), ("th32DefaultHeapID", ctypes.c_void_p),
                    ("th32ModuleID", wintypes.DWORD), ("cntThreads", wintypes.DWORD),
                    ("th32ParentProcessID", wintypes.DWORD), ("pcPriClassBase", ctypes.c_long),
                    ("dwFlags", wintypes.DWORD), ("szExeFile", ctypes.c_wchar * 260)]

    kernel32 = ctypes.windll.kernel32
    kernel32.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
    kernel32.Process32FirstW.argtypes = kernel32.Process32NextW.argtypes = [wintypes.HANDLE, ctypes.c_void_p]
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    snap = kernel32.CreateToolhelp32Snapshot(0x2, 0)  # TH32CS_SNAPPROCESS
    if not snap or snap == wintypes.HANDLE(-1).value:
        return {}
    table = {}
    try:
        entry = Entry()
        entry.dwSize = ctypes.sizeof(Entry)
        ok = kernel32.Process32FirstW(snap, ctypes.byref(entry))
        while ok:
            table[entry.th32ProcessID] = (entry.th32ParentProcessID, entry.szExeFile)
            ok = kernel32.Process32NextW(snap, ctypes.byref(entry))
    finally:
        kernel32.CloseHandle(snap)
    return table


def _ancestor_pids(table=None):
    """Windows: this process's parent, grandparent and so on, nearest first."""
    table = table if table is not None else process_table()
    chain, pid = [], table.get(os.getpid(), (None,))[0]
    while pid and pid in table and pid not in chain and len(chain) < 16:
        chain.append(pid)
        pid = table[pid][0]
    return chain


def _kernel32():
    import ctypes
    from ctypes import wintypes
    kernel32 = ctypes.windll.kernel32
    kernel32.OpenProcess.restype = wintypes.HANDLE
    kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel32.GetProcessTimes.argtypes = [wintypes.HANDLE] + [ctypes.POINTER(wintypes.FILETIME)] * 4
    kernel32.GetExitCodeProcess.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
    kernel32.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
    kernel32.WaitForSingleObject.restype = wintypes.DWORD
    kernel32.TerminateProcess.argtypes = [wintypes.HANDLE, ctypes.c_uint]
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    return ctypes, wintypes, kernel32


QUERY, SYNCHRONIZE, TERMINATE = 0x1000, 0x100000, 0x0001


def open_process(pid, access=QUERY):
    """Windows: a handle to a process, or None. While it is open, the pid can't go to another process."""
    _, _, kernel32 = _kernel32()
    return kernel32.OpenProcess(access, False, pid) or None


def handle_start(handle):
    """Windows: the creation time (100 ns units since 1601) of a process that is still running, or None."""
    ctypes, wintypes, kernel32 = _kernel32()
    times = [wintypes.FILETIME() for _ in range(4)]
    code = wintypes.DWORD()
    if not kernel32.GetProcessTimes(handle, *[ctypes.byref(t) for t in times]):
        return None
    if kernel32.GetExitCodeProcess(handle, ctypes.byref(code)) and code.value != 259:  # STILL_ACTIVE
        return None
    return (times[0].dwHighDateTime << 32) | times[0].dwLowDateTime


def close_handle(handle):
    if handle:
        _kernel32()[2].CloseHandle(handle)


def process_start(pid):
    """Windows: a running process's creation time in 100 ns units since 1601, or None if it isn't running."""
    handle = open_process(pid)
    if not handle:
        return None
    try:
        return handle_start(handle)
    finally:
        close_handle(handle)


def wait_handle(handle, seconds):
    """Windows: whether the process ended within `seconds`."""
    return _kernel32()[2].WaitForSingleObject(handle, int(seconds * 1000)) == 0  # WAIT_OBJECT_0


def wt_host_window():
    """Windows: the Windows Terminal window showing Claude Code, as (hwnd, console title), or None.
    Claude Code starts this server without a console, so borrow the console of the nearest
    ancestor that has one (Claude Code's). In Windows Terminal that console's window is a hidden
    pseudo-console window owned by the terminal window it is shown in, even after the tab is
    dragged to another window."""
    try:
        ctypes, user32, kernel32 = _wt_user32()
        from ctypes import wintypes
        kernel32.GetStdHandle.restype = wintypes.HANDLE
        kernel32.SetStdHandle.argtypes = [wintypes.DWORD, wintypes.HANDLE]
        with _console_lock:
            own = kernel32.GetConsoleWindow()
            candidates = [None] if own else _ancestor_pids()
            # AttachConsole and FreeConsole replace the standard handles, which carry the MCP pipes
            # and are what subprocess hands to children, so put them back after every attempt.
            std = [(n, kernel32.GetStdHandle(n)) for n in (-10 & 0xFFFFFFFF, -11 & 0xFFFFFFFF, -12 & 0xFFFFFFFF)]
            for pid in candidates:
                if pid is not None:
                    kernel32.FreeConsole()
                    attached = kernel32.AttachConsole(pid)
                    for n, h in std:
                        kernel32.SetStdHandle(n, h)
                    if not attached:
                        continue
                try:
                    console = kernel32.GetConsoleWindow()
                    if not console:
                        continue
                    owner = user32.GetWindow(console, 4)  # GW_OWNER
                    if not owner or _window_text(ctypes, user32, owner, "GetClassNameW") != "CASCADIA_HOSTING_WINDOW_CLASS":
                        return None
                    title = ctypes.create_unicode_buffer(512)
                    kernel32.GetConsoleTitleW(title, 512)
                    return owner, title.value
                finally:
                    if pid is not None:
                        kernel32.FreeConsole()
                        for n, h in std:
                            kernel32.SetStdHandle(n, h)
    except (OSError, AttributeError, ValueError):
        pass
    return None


def _same_title(a, b):
    # Claude Code animates a spinner at the start of its title, so compare what follows it.
    strip = lambda s: re.sub(r"^\W+", "", s or "").strip()
    return strip(a) == strip(b)


def _activate_window(ctypes, user32, kernel32, hwnd):
    """Bring a window to the foreground, even from this background process. Returns whether it is."""
    foreground = user32.GetForegroundWindow()
    if foreground == hwnd:
        return True
    me = kernel32.GetCurrentThreadId()
    other = user32.GetWindowThreadProcessId(foreground, None) if foreground else 0
    # Sharing the foreground thread's input state lifts the rule that only it may change focus. It
    # also makes this thread wait on that one, so skip it when the foreground window isn't responding
    # (activation then usually fails, and the caller falls back to a new window).
    hung = bool(foreground and user32.IsHungAppWindow(foreground))
    attached = bool(other and other != me and not hung and user32.AttachThreadInput(me, other, True))
    try:
        if user32.IsIconic(hwnd):
            user32.ShowWindow(hwnd, 9)  # SW_RESTORE
        user32.BringWindowToTop(hwnd)
        user32.SetForegroundWindow(hwnd)
    finally:
        if attached:
            user32.AttachThreadInput(me, other, False)
    for _ in range(10):
        if user32.GetForegroundWindow() == hwnd:
            return True
        time.sleep(0.05)
    return False


def wt_escape(arg):
    """wt.exe splits its command line into several commands at every `;`, even inside a quoted
    argument, unless it is escaped as `\\;`."""
    return arg.replace(";", "\\;")


def run_in_host_window(wt, cwd, command):
    """Windows Terminal: open `command` in a pane of Claude Code's own window, not whichever
    window was used last. wt.exe can't name a window by its handle, only by "-w 0", the most
    recently used one, so bring Claude Code's window to the front for the moment wt.exe runs,
    then give the focus back. Returns a description of where it opened."""
    command = [wt_escape(a) for a in command]
    host = wt_host_window()
    ctypes, user32, kernel32 = _wt_user32()
    previous = user32.GetForegroundWindow()
    if not host or not _activate_window(ctypes, user32, kernel32, host[0]):
        # Opening it in another session's window is worse than a window of its own.
        subprocess.Popen([wt, "-w", "new", *command], cwd=cwd, stdin=subprocess.DEVNULL,
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        why = "couldn't be brought to the front" if host else "couldn't be found"
        return f"a new Windows Terminal window (Claude Code's window {why})"
    hwnd, console_title = host
    # split-pane splits the window's selected tab; if that isn't Claude Code's, open a tab instead.
    in_view = _same_title(_window_text(ctypes, user32, hwnd), console_title)
    action, how = (["split-pane", "-V"], "a Windows Terminal split pane") if in_view else \
                  (["new-tab"], "a new tab in Claude Code's Windows Terminal window")
    try:
        subprocess.Popen([wt, "-w", "0", *action, *command], cwd=cwd, stdin=subprocess.DEVNULL,
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).wait(timeout=10)
        time.sleep(0.5)  # wt.exe hands the request to the running terminal; let it land first
    except subprocess.TimeoutExpired:
        pass
    finally:
        if previous and previous != hwnd and user32.IsWindow(previous):
            _activate_window(ctypes, user32, kernel32, previous)
    return how


def open_terminal(cwd, thread_id, codex="codex"):
    """Open `codex resume <id>` beside Claude Code: a split pane when Claude Code runs in
    Windows Terminal or tmux, otherwise a new terminal window. Returns a description of what opened."""
    if not re.fullmatch(r"[0-9A-Za-z-]+", thread_id):
        raise BridgeError(f"Refusing to open a terminal for an unexpected thread id: {thread_id!r}")
    cwd = cwd if cwd and os.path.isdir(cwd) else os.getcwd()
    resume = [codex, "resume", thread_id]
    kwargs = {"cwd": cwd, "stdin": subprocess.DEVNULL, "stdout": subprocess.DEVNULL, "stderr": subprocess.DEVNULL}
    tmux = shutil.which("tmux") if os.environ.get("TMUX") else None
    if tmux:
        argv, how = [tmux, "split-window", "-h", "-c", cwd, shlex.join(resume)], "a tmux split pane"
    elif os.name == "nt":
        # codex on PATH is usually an npm .cmd shim, so run it through cmd; /k keeps errors on screen.
        wt = shutil.which("wt")
        if wt and os.environ.get("WT_SESSION"):
            return run_in_host_window(wt, cwd, ["-d", cwd, "--title", "Codex consultant", "cmd", "/k", *resume])
        elif wt:
            argv = [wt, "-w", "new", *map(wt_escape, ["-d", cwd, "--title", "Codex consultant", "cmd", "/k", *resume])]
            how = "Windows Terminal"
        else:
            argv, how = ["cmd", "/c", "start", "Codex consultant", "cmd", "/k", *resume], "a console window"
    elif sys.platform == "darwin":
        script = f"cd {shlex.quote(cwd)} && {shlex.join(resume)}"
        argv, how = ["osascript", "-e", f"tell application \"Terminal\" to do script {json.dumps(script)}",
                     "-e", "tell application \"Terminal\" to activate"], "Terminal"
        kwargs["start_new_session"] = True
    else:
        term = shutil.which("x-terminal-emulator") or shutil.which("gnome-terminal") or shutil.which("xterm")
        if not term:
            raise BridgeError(f"No terminal emulator found. Run this yourself: codex resume {thread_id}")
        flag = "--" if term.endswith("gnome-terminal") else "-e"
        argv, how = [term, flag, *resume], os.path.basename(term)
        kwargs["start_new_session"] = True
    subprocess.Popen(argv, **kwargs)
    return how


def show_viewer(thread, info, quiet=False):
    """Open a terminal showing the session unless one already does. Returns a sentence
    ("" with quiet=True when it was already open)."""
    tid, name = thread["id"], short_name(thread)
    if viewer_running(tid):
        return "" if quiet else f"{name} is already open in a terminal; no new one was opened."
    codex, warning = viewer_codex(info)
    return f"Opened {name} in {open_terminal(thread.get('cwd'), tid, codex)}.{warning}"


def end_process(pid, code):
    """Windows: terminate a process with a chosen exit code."""
    import ctypes
    kernel32 = ctypes.windll.kernel32
    handle = kernel32.OpenProcess(0x0001, False, pid)  # PROCESS_TERMINATE
    if handle:
        kernel32.TerminateProcess(handle, code)
        kernel32.CloseHandle(handle)


def close_terminals(thread_id):
    """Best effort: end `codex resume <id>` processes so their windows close. Returns how many."""
    if not re.fullmatch(r"[0-9A-Za-z-]+", thread_id):
        return 0
    if os.name == "nt":
        # Only the cmd windows open_terminal started, running codex by name or by full path.
        # Each output line: the cmd pid, then its children.
        ps = ("Get-CimInstance Win32_Process -Filter \"Name='cmd.exe'\" | Where-Object "
              f"{{ $_.CommandLine -like '*/k *codex* resume {thread_id}' }} | ForEach-Object {{ "
              "$p = $_.ProcessId; "
              "$k = @(Get-CimInstance Win32_Process -Filter \"ParentProcessId=$p\" | ForEach-Object { $_.ProcessId }); "
              "\"$p $k\" }")
        out = run_text(["powershell", "-NoProfile", "-NonInteractive", "-Command", ps])
        shells = [line.split() for line in out.splitlines() if line.strip()]
        for pids in shells:
            for child in pids[1:]:
                run_text(["taskkill", "/PID", child, "/T", "/F"])
            # Windows Terminal closes a pane by itself only on a clean exit, so end cmd with code 0.
            if pids[0].isdigit():
                end_process(int(pids[0]), 0)
        return len(shells)
    pattern = f"codex[^ ]* resume {thread_id}"
    pids = run_text(["pgrep", "-f", pattern]).split()
    if pids:
        run_text(["pkill", "-f", pattern])
    return len(pids)


# Variables Claude Code sets for the commands it runs, tying them to its session. A `claude` that
# inherits them takes itself for a child session and, among other things, doesn't save its
# transcript. Only these go: other CLAUDE_CODE_* variables are the user's settings (a token, a
# provider) and stay.
CLAUDE_SESSION_VARS = frozenset((
    "CLAUDECODE", "CLAUDE_PID", "CLAUDE_EFFORT", "AI_AGENT", "CLAUDE_CODE_CHILD_SESSION",
    "CLAUDE_CODE_SESSION_ID", "CLAUDE_CODE_BRIDGE_SESSION_ID", "CLAUDE_CODE_MESSAGING_SOCKET",
    "CLAUDE_CODE_MESSAGING_TOKEN", "CLAUDE_CODE_ENTRYPOINT", "CLAUDE_CODE_EXECPATH",
    "CLAUDE_CODE_SESSION_ATTENDED", "CLAUDE_CODE_SSE_PORT",
))


def fresh_claude_env(env):
    """`env` without the variables that tie a process to the Claude Code session that started it."""
    return {k: v for k, v in env.items() if k.upper() not in CLAUDE_SESSION_VARS}


def claude_config_dir(env=None):
    """Where Claude Code keeps its settings and session registry."""
    env = os.environ if env is None else env
    return env.get("CLAUDE_CONFIG_DIR") or os.path.join(os.path.expanduser("~"), ".claude")


def claude_state_file(env=None):
    """Claude Code's state file, with the folders the user has trusted."""
    env = os.environ if env is None else env
    if env.get("CLAUDE_CONFIG_DIR"):
        return os.path.join(env["CLAUDE_CONFIG_DIR"], ".claude.json")
    return os.path.join(os.path.expanduser("~"), ".claude.json")


def find_program(name, path):
    """An executable on `path`, ignoring the current folder and relative entries. Windows looks in
    the current folder first, and here that is the project, which could ship its own `claude`."""
    exts = [""]
    if os.name == "nt":
        exts = [e for e in (os.environ.get("PATHEXT") or ".COM;.EXE;.BAT;.CMD").split(";") if e]
    for folder in (path or "").split(os.pathsep):
        folder = folder.strip().strip('"')
        if not folder or not os.path.isabs(folder):
            continue
        for ext in exts:
            candidate = os.path.join(folder, name + ext)
            if os.path.isfile(candidate) and (os.name == "nt" or os.access(candidate, os.X_OK)):
                return candidate
    return None


def close_marker(pid):
    """A file CloseClaudeSession leaves to tell the helper that it ended this claude on purpose."""
    return os.path.join(tempfile.gettempdir(), f"nouez-closed-{pid}")


def run_claude(spec_path):
    """The `claude` subcommand: start an interactive Claude Code session with Remote Control, as if
    the user had opened a terminal and typed it. Reads its settings from a file OpenClaudeSession
    wrote, so no prompt text passes through a command line."""
    try:
        with open(spec_path, encoding="utf-8") as f:
            spec = json.load(f)
    finally:
        try:
            os.remove(spec_path)
        except OSError:
            pass
    env = fresh_claude_env(os.environ)
    exe = find_program("claude", env.get("PATH"))
    if not exe:
        print("claude isn't on PATH. Open a terminal and run claude yourself.")
        input("Press Enter to close.")
        return 1
    name = spec["name"]
    argv = [exe, "--remote-control", name, "--name", name]
    if spec.get("model"):
        argv += ["--model", spec["model"]]
    if spec.get("effort"):
        argv += ["--effort", spec["effort"]]
        env["CLAUDE_CODE_EFFORT_LEVEL"] = spec["effort"]  # it outranks --effort, so one inherited can't win
    if spec.get("prompt"):
        argv += ["--", spec["prompt"]]  # so a prompt starting with "-" can't pass for an option
    child = subprocess.Popen(argv, cwd=spec["cwd"], env=env)
    code = child.wait()
    marker = close_marker(child.pid)
    if os.path.exists(marker):
        # CloseClaudeSession ended it. Exit cleanly so the terminal closes this window.
        try:
            os.remove(marker)
        except OSError:
            pass
        return 0
    return code


def open_window(cwd, argv, title):
    """Run `argv` in a new terminal window. Returns a description of what opened."""
    kwargs = {"cwd": cwd, "stdin": subprocess.DEVNULL, "stdout": subprocess.DEVNULL, "stderr": subprocess.DEVNULL}
    if os.name == "nt":
        wt = shutil.which("wt")
        if wt:
            subprocess.Popen([wt, "-w", "new", *map(wt_escape, ["-d", cwd, "--title", title, *argv])], **kwargs)
            return "a new Windows Terminal window"
        subprocess.Popen(argv, cwd=cwd, creationflags=subprocess.CREATE_NEW_CONSOLE)
        return "a new console window"
    if sys.platform == "darwin":
        script = f"cd {shlex.quote(cwd)} && {shlex.join(argv)}"
        subprocess.Popen(["osascript", "-e", f"tell application \"Terminal\" to do script {json.dumps(script)}"],
                         start_new_session=True, **kwargs)
        return "a new Terminal window"
    term = shutil.which("x-terminal-emulator") or shutil.which("gnome-terminal") or shutil.which("xterm")
    if not term:
        raise BridgeError("No terminal emulator found.")
    subprocess.Popen([term, "--" if term.endswith("gnome-terminal") else "-e", *argv], start_new_session=True, **kwargs)
    return os.path.basename(term)


def trust_key(path):
    """The folder Claude Code keys its trust for `path` on, and whether it is in git. In git it is
    the repository's root (for a linked worktree, the main checkout's root), and the trust covers
    the whole repository; outside git it is the folder, and the trust covers the folders inside it
    except git repositories. The key is None for a worktree whose main checkout can't be told."""
    root = git_root(path)
    if not root:
        return os.path.abspath(path), False
    dotgit = os.path.join(root, ".git")
    if os.path.isfile(dotgit):  # a linked worktree or a submodule: `gitdir: <path>`
        try:
            with open(dotgit, encoding="utf-8") as f:
                m = re.match(r"gitdir:\s*(.+)", f.read().strip())
            if not m:
                return None, True
            gitdir = os.path.normpath(os.path.join(root, m.group(1).strip()))
            commondir = os.path.join(gitdir, "commondir")
            if not os.path.isfile(commondir):
                return root, True  # a submodule (its own repository) or a separate git dir
            with open(commondir, encoding="utf-8") as f:
                common = os.path.normpath(os.path.join(gitdir, f.read().strip()))
        except (OSError, UnicodeError):
            return None, True
        return _main_checkout(common), True
    return root, True


def _main_checkout(common):
    """The main checkout whose .git is the common git dir `common`, or None if that can't be told.
    A separate git dir (`git init --separate-git-dir`) can itself be named .git, in a folder that
    is no checkout, and git records no link back to the checkout; so the folder counts only when
    its .git is that directory and it holds something besides it."""
    if os.path.basename(common) != ".git" or not os.path.isdir(common):
        return None
    candidate = os.path.dirname(common)
    try:
        if not os.path.samefile(os.path.join(candidate, ".git"), common):
            return None
        if not any(name != ".git" for name in os.listdir(candidate)):
            return None  # only the git data: a separate git dir's holder, not a checkout
    except OSError:
        return None
    return candidate


def _trust_norm(p):
    return os.path.normcase(os.path.abspath(p)).rstrip("\\/")


def folder_trusted(path):
    """Whether Claude Code would start in `path` without asking whether to trust it (None if unknown):
    the user accepted the trust dialog for its repository, or, outside git, for it or a folder above it."""
    try:
        with open(claude_state_file(), encoding="utf-8") as f:
            projects = json.load(f).get("projects") or {}
        trusted = {_trust_norm(p) for p, v in projects.items() if isinstance(v, dict) and v.get("hasTrustDialogAccepted")}
    except (OSError, ValueError, AttributeError, TypeError):
        return None
    key, in_git = trust_key(path)
    if key is None:
        return None
    key = _trust_norm(key)
    if in_git:
        return key in trusted  # a folder above a repository doesn't cover it
    return any(key == p or key.startswith(p + os.sep) for p in trusted)


CLAUDE_MODEL = "opus"     # the model sessions OpenClaudeSession opens start with: the latest Opus
CLAUDE_EFFORT = "medium"  # and their effort level
CLAUDE_EFFORTS = ("low", "medium", "high", "xhigh", "max")
CLAUDE_MODEL_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9._\[\]-]{0,99}")  # an alias or full name, never an option
TRUST_BACKUPS_KEPT = 20  # dated copies of Claude Code's state file kept before nouez's changes


def trust_backup_dir():
    """Where nouez keeps its copies of Claude Code's state file: the user's own, private data folder."""
    if os.name == "nt":
        base, fallback = os.environ.get("LOCALAPPDATA"), os.path.join("~", "AppData", "Local")
    else:
        base, fallback = os.environ.get("XDG_STATE_HOME"), os.path.join("~", ".local", "state")
    if not base or not os.path.isabs(base):  # a relative one would put the copies in the project
        base = os.path.expanduser(fallback)
    return os.path.join(base, "nouez", "claude-json-backups")


def backup_claude_state(text):
    """Save `text` (the state file as read) to a new dated backup, check it, and keep only the newest
    TRUST_BACKUPS_KEPT. Returns the backup's path."""
    folder = trust_backup_dir()
    os.makedirs(folder, mode=0o700, exist_ok=True)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    fd, path = tempfile.mkstemp(prefix=f".claude.json.{stamp}.", suffix=".bak", dir=folder)  # private (0600)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as f:
            f.write(text)
        with open(path, encoding="utf-8", newline="") as f:
            if f.read() != text:
                raise OSError("the copy doesn't match")
    except OSError as e:
        try:
            os.remove(path)
        except OSError:
            pass
        raise BridgeError(f"Couldn't back up Claude Code's settings to {folder}: {e}. Nothing was changed.")
    dated = []
    for other in glob.glob(os.path.join(glob.escape(folder), ".claude.json.*.bak")):
        try:
            dated.append((os.path.getmtime(other), other))
        except OSError:
            pass  # another nouez server removed it meanwhile
    for _, extra in sorted(dated)[:-TRUST_BACKUPS_KEPT]:
        if extra != path:
            try:
                os.remove(extra)
            except OSError:
                pass
    return path


def exactly_trusted(key):
    """Whether Claude Code's state file records trust for `key` itself (not just a folder above it)."""
    exact = _trust_norm(key)
    try:
        with open(claude_state_file(), encoding="utf-8") as f:
            projects = json.load(f).get("projects") or {}
        return any(_trust_norm(p) == exact and isinstance(v, dict) and v.get("hasTrustDialogAccepted") is True
                   for p, v in projects.items())
    except (OSError, ValueError, AttributeError, TypeError):
        return False


def trust_folder(path):
    """Record the user's trust in `path` as Claude Code's trust dialog does:
    projects["<folder>"].hasTrustDialogAccepted = true in its state file, where the folder is the
    repository root in git (a linked worktree's main checkout). Before each change the file is copied
    to a new dated backup; only that one value changes; the file is checked again just before it is
    replaced, and read back after. Returns (folder, backup or None); None if it was already trusted."""
    key, _ = trust_key(path)
    if key is None:
        raise BridgeError("Not recording trust: nouez can't tell which folder Claude Code keeps the trust "
                          "for here (the git layout is unusual). Nothing was changed; the user can answer "
                          "the trust question on the computer.")
    norm_key = _trust_norm(key)
    home = _trust_norm(os.path.expanduser("~"))
    if norm_key == home or os.path.dirname(norm_key) == norm_key or norm_key == _trust_norm(claude_config_dir()):
        raise BridgeError(f"Not trusting {key}: Claude Code doesn't record trust for the home folder, a "
                          "drive's root or its own folder, so choose a project folder.")
    state = claude_state_file()
    backup = None
    for attempt in range(3):
        try:
            with open(state, encoding="utf-8", newline="") as f:
                text = f.read()
            data = json.loads(text)
        except (OSError, ValueError) as e:
            raise BridgeError(f"Couldn't read {state}: {e}. Nothing was changed.")
        projects = data.get("projects") if isinstance(data, dict) else None
        if projects is None and isinstance(data, dict):
            projects = data["projects"] = {}
        if not isinstance(projects, dict):
            raise BridgeError(f"{state} isn't laid out as expected (no projects table). Nothing was changed.")
        name = next((p for p in projects if _trust_norm(p) == norm_key), None)
        if name is not None and isinstance(projects[name], dict) and projects[name].get("hasTrustDialogAccepted") is True:
            return name, backup
        if name is not None and not isinstance(projects[name], dict):
            raise BridgeError(f"{state} has an unexpected entry for {name}. Nothing was changed.")
        name = name or (key.replace("\\", "/") if os.name == "nt" else key)
        projects.setdefault(name, {})["hasTrustDialogAccepted"] = True
        try:
            # allow_nan=False: a number too big for a float (1e400) must not come back as Infinity,
            # which isn't JSON; encode(): a lone surrogate escape can't be written as UTF-8.
            new = json.dumps(data, indent=2, ensure_ascii=False, allow_nan=False)
            new.encode("utf-8")
            same = json.loads(new) == data
        except (ValueError, UnicodeError):
            same = False
        if not same:
            raise BridgeError(f"{state} has values nouez can't write back unchanged. Nothing was changed.")
        backup = backup_claude_state(text)
        with open(state, encoding="utf-8", newline="") as f:
            if f.read() != text:
                continue  # a Claude Code session wrote it meanwhile: start over from its version
        # A temporary file of its own beside the state file, so two servers can't write into one.
        fd, tmp = tempfile.mkstemp(prefix=".claude.json.", suffix=".nouez-tmp", dir=os.path.dirname(state))
        replaced = False
        try:
            with os.fdopen(fd, "w", encoding="utf-8", newline="") as f:
                f.write(new)
            os.replace(tmp, state)
            replaced = True
        except OSError:
            pass
        finally:
            if not replaced:
                try:
                    os.remove(tmp)
                except OSError:
                    pass
        if not replaced:
            time.sleep(0.2)
            continue
        time.sleep(0.5)  # then make sure no session wrote over it
        if exactly_trusted(key):
            return name, backup
    raise BridgeError(f"Couldn't record the trust for {key}: {state} kept changing (other Claude Code "
                      f"sessions write it). Its last version before nouez's change is backed up in "
                      f"{backup or trust_backup_dir()}. Try again, or answer the trust question on the computer.")


def open_claude_session(args, cancel=None, progress=None):
    cwd = args.get("cwd")
    if not isinstance(cwd, str) or not os.path.isabs(cwd):
        raise BridgeError("cwd must be an absolute path.")
    cwd = os.path.abspath(cwd)
    created = False
    if flag(args, "create") and not os.path.exists(cwd):
        parent = os.path.dirname(cwd)
        if not os.path.isdir(parent):
            raise BridgeError(f"Can't create {cwd}: its parent folder {parent} doesn't exist.")
        os.mkdir(cwd)
        created = True
    if not os.path.isdir(cwd):
        raise BridgeError("cwd must be the absolute path of an existing folder "
                          "(or pass create=true to make a new one).")
    name = args.get("name") or os.path.basename(cwd.rstrip("\\/")) or "claude"
    prompt = args.get("prompt") or ""
    if not isinstance(name, str) or not isinstance(prompt, str):
        raise BridgeError("name and prompt must be strings.")
    model = args.get("model") or CLAUDE_MODEL
    effort = args.get("effort") or CLAUDE_EFFORT
    if not isinstance(model, str) or not CLAUDE_MODEL_NAME.fullmatch(model):
        raise BridgeError("model must be a Claude Code model alias (such as opus or sonnet) or a model's full name.")
    if effort not in CLAUDE_EFFORTS:
        raise BridgeError("effort must be one of " + ", ".join(CLAUDE_EFFORTS) + ".")
    notes = [f"Created the folder {cwd}."] if created else []
    trusted = folder_trusted(cwd)
    key, in_git = trust_key(cwd)
    if flag(args, "trust") and not (key and exactly_trusted(key)):
        recorded, backup = trust_folder(cwd)
        if backup:
            notes.append(f"Recorded the user's trust in {recorded} in Claude Code's settings "
                         f"({claude_state_file()}), as its trust dialog would. The file as it was is "
                         f"backed up in {backup}.")
        trusted = folder_trusted(cwd)
    if trusted is False and not flag(args, "open_untrusted"):
        return " ".join(notes + [
            f"Not opened: Claude Code hasn't been trusted in {key}"
            + (" (a git repository is trusted on its own, not through a folder above it)" if in_git else "")
            + ", so a session there would wait at the trust question on the computer and couldn't "
            "connect to the Claude app until someone answers it. Ask the user whether they trust this "
            "folder: trusting it lets its Claude Code settings, hooks and MCP servers run. Only if they "
            "say yes, call OpenClaudeSession again with trust=true, which records their answer in Claude "
            "Code's settings as the trust dialog would (backing the file up first). If they're at the "
            "computer and would rather answer Claude Code's own question there, use open_untrusted=true."])
    asks = []
    if trusted and key:
        exact_trusted = exactly_trusted(key)
        project = git_root(cwd) or cwd  # the launched checkout: a worktree has its own files
        if not exact_trusted and os.path.isfile(os.path.join(project, ".claude", "settings.json")):
            asks.append("its .claude/settings.json may bring the trust question back (allow rules and "
                        "additional directories need the folder itself trusted, not just a folder above it; "
                        "trust=true, if the user says they trust it, records that)")
        if os.path.isfile(os.path.join(project, ".mcp.json")):
            asks.append("its .mcp.json servers are approved separately, so Claude Code may ask before "
                        "connecting them")
    fd, spec = tempfile.mkstemp(prefix="nouez-claude-", suffix=".json")
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump({"cwd": cwd, "name": name, "prompt": prompt, "model": model, "effort": effort}, f)
    try:
        how = open_window(cwd, [sys.executable, "-I", os.path.abspath(__file__), "claude", spec], f"Claude: {name}")
    except Exception:
        os.remove(spec)
        raise
    out = " ".join(notes + [
        f"Opened {how} in {cwd} running Claude Code ({model}, {effort} effort) with Remote Control, named \"{name}\". It is a "
        "normal session: its transcript is saved and it can be resumed later. It appears in the "
        "Claude app's session list under that name once it connects, in a few seconds."])
    if trusted is False:
        out += (" Warning: Claude Code hasn't been trusted in this folder yet, so the new session is "
                "waiting at the trust question on the computer and won't connect until someone answers it there.")
    elif trusted is None:
        out += (" Note: nouez can't tell whether Claude Code has been trusted in this folder (its settings "
                "couldn't be read, or the git layout is unusual). If it hasn't, the session is waiting at "
                "the trust question on the computer.")
    elif asks:
        out += " Note: the session may wait for an answer on the computer: " + "; ".join(asks) + "."
    return out


def claude_sessions():
    """The Claude Code sessions running on this computer, from the registry Claude Code keeps in
    ~/.claude/sessions (one <pid>.json per process; not a documented format, so read defensively).
    A file can outlive its process, so only those whose process is still the one that wrote it count."""
    folder = os.path.join(claude_config_dir(), "sessions")
    table = process_table() if os.name == "nt" else {}
    sessions = []
    for path in glob.glob(os.path.join(glob.escape(folder), "*.json")):
        try:
            with open(path, encoding="utf-8") as f:
                info = json.load(f)
            pid = int(info["pid"])
        except (OSError, ValueError, KeyError, TypeError):
            continue
        if not isinstance(info, dict) or info.get("kind", "interactive") != "interactive":
            continue
        started = helper = helper_start = None
        if os.name == "nt":
            # The entry counts only if its process was created when the entry says: a pid can be reused.
            recorded = str(info.get("procStart") or "")
            started = process_start(pid)
            if not recorded.isdigit() or started is None or int(recorded) != started:
                continue
            parent = table.get(pid, (None, ""))[0]
            parent_exe = table.get(parent, (None, ""))[1].lower() if parent else ""
            if parent_exe.startswith("python") and _is_nouez_helper(parent):
                helper_start = process_start(parent)
                # A parent is older than its child; a younger one took over a dead parent's pid.
                if helper_start is not None and helper_start <= started:
                    helper = parent
        else:
            try:
                os.kill(pid, 0)
            except ProcessLookupError:
                continue
            except PermissionError:
                pass
        sessions.append({"pid": pid, "name": str(info.get("name") or "?"), "cwd": info.get("cwd") or "?",
                         "status": info.get("status") or "?", "session_id": info.get("sessionId"),
                         "remote": bool(info.get("bridgeSessionId")), "helper": helper,
                         "start": started, "helper_start": helper_start})
    return sorted(sessions, key=lambda s: s["name"].lower())


def end_session(target):
    """End a session's claude process and its children, and the helper window around it if
    OpenClaudeSession opened it. Raises BridgeError if the process is still running afterwards."""
    pid = target["pid"]
    if os.name != "nt":
        try:
            os.kill(pid, signal.SIGTERM)
        except ProcessLookupError:
            return
        except PermissionError as e:
            raise BridgeError(f"Couldn't close {target['name']} (pid {pid}): {e}")
        for _ in range(50):
            time.sleep(0.1)
            try:
                os.kill(pid, 0)
            except ProcessLookupError:
                return
        raise BridgeError(f"{target['name']} (pid {pid}) is still running after being asked to quit.")
    # Hold handles from the identity check to the end, so neither pid can pass to another process.
    handle = open_process(pid, QUERY | SYNCHRONIZE | TERMINATE)
    helper = open_process(target["helper"], QUERY | SYNCHRONIZE | TERMINATE) if target.get("helper") else None
    marker, closed = close_marker(pid), False
    try:
        if not handle or handle_start(handle) != target["start"]:
            raise BridgeError(f"{target['name']} (pid {pid}) has already ended.")
        if helper and handle_start(helper) != target["helper_start"]:
            close_handle(helper)
            helper = None
        if helper:
            with open(marker, "w"):
                pass
        result = subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"], capture_output=True, text=True,
                                timeout=30, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        if not wait_handle(handle, 5):
            _kernel32()[2].TerminateProcess(handle, 1)
            if not wait_handle(handle, 2):
                detail = (result.stderr or result.stdout).strip()
                raise BridgeError(f"Couldn't close {target['name']} (pid {pid}). {detail}".strip())
        # The helper exits by itself, cleanly, once it sees the marker; make sure of it.
        if helper and not wait_handle(helper, 3):
            # Windows Terminal closes a window by itself only on a clean exit, so end it with code 0.
            _kernel32()[2].TerminateProcess(helper, 0)
        closed = True
    except subprocess.TimeoutExpired:
        raise BridgeError(f"taskkill didn't finish closing {target['name']} (pid {pid}).")
    finally:
        close_handle(handle)
        close_handle(helper)
        if not closed and os.path.exists(marker):
            try:
                os.remove(marker)
            except OSError:
                pass


def _is_nouez_helper(pid):
    """Whether a process is the `server.py claude` helper OpenClaudeSession runs, which owns the window."""
    if os.name != "nt" or not isinstance(pid, int):
        return False
    ps = f"(Get-CimInstance Win32_Process -Filter \"ProcessId={pid}\").CommandLine"
    line = run_text(["powershell", "-NoProfile", "-NonInteractive", "-Command", ps], timeout=20)
    return " claude " in line and "nouez-claude-" in line


def own_claude_pids():
    """Pids of the processes above this server, among them the Claude Code session it serves."""
    return set(_ancestor_pids()) if os.name == "nt" else {os.getppid()}


def describe_sessions(sessions, own):
    if not sessions:
        return "No Claude Code sessions are running on this computer."
    rows = []
    for s in sessions:
        notes = [s["status"]]
        if s["remote"]:
            notes.append("Remote Control")
        if s["helper"]:
            notes.append("opened by OpenClaudeSession")
        if s["pid"] in own:
            notes.append("this session")
        rows.append(f"- {s['name']} (pid {s['pid']}): {s['cwd']} [{', '.join(notes)}]")
    return "Claude Code sessions running on this computer:\n" + "\n".join(rows)


def list_claude_sessions(args, cancel=None, progress=None):
    return describe_sessions(claude_sessions(), own_claude_pids())


def close_claude_session(args, cancel=None, progress=None):
    name, pid = args.get("name"), args.get("pid")
    if not name and pid is None:
        raise BridgeError("Pass the name or pid of the session to close. ListClaudeSessions lists them.")
    if pid is not None and (isinstance(pid, bool) or not isinstance(pid, int)):
        raise BridgeError("pid must be an integer.")
    sessions, own = claude_sessions(), own_claude_pids()
    matches = [s for s in sessions if (pid is None or s["pid"] == pid) and (not name or s["name"] == name)]
    if not matches:
        raise BridgeError("No running Claude Code session matches. " + describe_sessions(sessions, own))
    if len(matches) > 1:
        raise BridgeError(f"Several sessions are named {name}: "
                          + ", ".join(f"pid {s['pid']} in {s['cwd']}" for s in matches) + ". Pass pid to pick one.")
    target = matches[0]
    if target["pid"] in own:
        raise BridgeError("That is the session you are running in; it can't close itself.")
    end_session(target)
    where = "and its window" if target["helper"] else "(its terminal stays open at the shell prompt)"
    resume = f"claude --resume {target['session_id']}" if target["session_id"] else "claude --resume"
    return (f"Closed {target['name']} (pid {target['pid']}) {where}. Its transcript is kept: "
            f"`{resume}` in {target['cwd']} picks it up again.")


def git_root(path):
    """The git work tree containing `path`, or None. Looks for `.git` (a directory, or a file in
    worktrees and submodules) instead of running git, which can hang."""
    current = os.path.abspath(path)
    while True:
        if os.path.exists(os.path.join(current, ".git")):
            return current
        parent = os.path.dirname(current)
        if parent == current:
            return None
        current = parent


def is_under(path, root):
    a, b = os.path.normcase(os.path.abspath(path)), os.path.normcase(os.path.abspath(root))
    try:
        return os.path.commonpath([a, b]) == b
    except ValueError:  # different drives
        return False


def repo_root(path):
    """Where consultants for `path` are looked for: its git work tree. Outside git, the Claude Code
    workspace folder (MCP root) that contains it, so a subfolder finds the consultant started at
    the project's top; failing that, `path` itself."""
    path = os.path.abspath(path)
    found = git_root(path)
    if found:
        return found
    containing = [r for r in client_roots() if is_under(path, r)]
    return max(containing, key=len) if containing else path  # innermost, if roots nest


def in_repo(thread, root):
    cwd = thread.get("cwd")
    return bool(cwd) and is_under(cwd, root)


def repo_consultants(client, cwd):
    root = repo_root(cwd)
    return root, [t for t in load_consultants(client) if in_repo(t, root)]


def default_cwd():
    roots = client_roots()
    return roots[0] if roots else os.getcwd()


def format_threads(threads):
    lines = []
    for t in threads:
        lines.append(
            f"- {short_name(t)}\n"
            f"    id: {t['id']}\n"
            f"    cwd: {t.get('cwd')}\n"
            f"    model: {t.get('model')} ({t.get('modelProvider')})\n"
            f"    status: {status_label(t)}\n"
            f"    started by: {'StartConsultant' if is_bridge(t) else 'user'}"
            + (f"\n    title: {t['name']}" if t.get("name") else "")
        )
    return "\n".join(lines)


def list_consultants(args, cancel=None, progress=None):
    include_all = flag(args, "include_all")
    client = CodexClient()
    try:
        if args.get("cwd"):
            root, threads = repo_consultants(client, args["cwd"])
        else:
            root, threads = None, load_consultants(client, include_all)
    finally:
        client.close()
    if not threads:
        where = f" in {root}" if root else ""
        return f"No Codex sessions{where}. Start one with StartConsultant, or open Codex in a terminal."
    if root:
        return f"{len(threads)} Codex session(s) in {root}:\n" + format_threads(threads)
    return f"{len(threads)} Codex session(s):\n" + format_threads(threads)


def start_consultant(args, cancel=None, progress=None):
    cwd = os.path.abspath(args.get("cwd") or default_cwd())
    if not os.path.isdir(cwd):
        raise BridgeError(f"cwd is not a directory: {cwd}")
    # Consultants audit, validate and research; they never edit. No terminal is attached to
    # answer approval prompts, so never ask; the read-only sandbox is the limit.
    params = {"cwd": cwd, "sandbox": SANDBOX, "approvalPolicy": "never", "threadSource": BRIDGE_SOURCE}
    if args.get("model"):
        params["model"] = args["model"]
    if args.get("instructions"):
        params["developerInstructions"] = args["instructions"]

    watch, new = flag(args, "watch", True), flag(args, "new")
    existing, users, has_turns = [], [], False
    client = CodexClient()
    try:
        if not new:
            # Reuse before starting: a consultant already in this repo keeps its context, and a
            # duplicate splits the conversation across sessions. Only our own sessions are reused:
            # they were created read-only, while a user's session keeps the user's permissions.
            root, found = repo_consultants(client, cwd)
            existing = sorted((t for t in found if is_bridge(t)),
                              key=lambda t: t.get("updatedAt") or 0, reverse=True)
            users = [t for t in found if not is_bridge(t)]
        if existing:
            thread = existing[0]
            has_turns = bool(latest_turn(client, thread["id"]))
            info = client.info
        else:
            thread = client.request("thread/start", params)["thread"]
            if args.get("title"):
                client.request("thread/name/set", {"threadId": thread["id"], "name": args["title"]})
        notice = "\n".join(n for n in (safe_nouez_update_notice(), update_notice(client.info)) if n)
    finally:
        client.close()

    name = short_name(thread)
    # The latest StartConsultant call decides whether the session gets an automatic pane.
    with _send_locks_guard:
        (_unwatched.discard if watch else _unwatched.add)(thread["id"])
    user_note = (f"\nThe user's own Codex sessions in this repo were not used (they keep the user's "
                 f"permissions). Message one only if the user asks you to, with "
                 f"allow_user_session=true:\n{format_threads(users)}"
                 if users else "")
    if not existing:
        return (
            f"Started {name}\n"
            f"    id: {thread['id']}\n"
            f"    cwd: {thread.get('cwd')}\n"
            f"    model: {thread.get('model')} ({thread.get('modelProvider')})\n"
            f"    sandbox: {SANDBOX}\n"
            + ("A pane showing it opens beside Claude Code when you send its first message.\n" if watch else "")
            + "Send it work with SendConsultantMessage."
            + user_note
            + (f"\n{notice}" if notice else "")
        )

    if not watch:
        pane = ""
    elif not has_turns:
        pane = "A pane showing it opens beside Claude Code when you send its first message."
    else:
        try:
            pane = show_viewer(thread, info)
        except (BridgeError, OSError) as e:
            pane = f"Could not open a terminal: {e}"
    others = existing[1:]
    ignored = [k for k in ("model", "title", "instructions") if args.get(k)]
    return (
        f"Using {name}, which already works in {root}; nothing new was started.\n"
        + format_threads([thread]) + "\n"
        + (pane + "\n" if pane else "")
        + (f"Ignored {', '.join(ignored)}: they apply only to a new session (new=true).\n" if ignored else "")
        + "Send it work with SendConsultantMessage."
        + (f"\nOther consultants in this repo:\n{format_threads(others)}" if others else "")
        + user_note
        + "\nOnly if the user asks for a separate consultant, call StartConsultant with new=true."
        + (f"\n{notice}" if notice else "")
    )


def send_consultant_message(args, cancel=None, progress=None):
    to = target(args)
    message = args.get("message") or ""
    if not message:
        raise BridgeError("`message` is required.")
    timeout = wait_seconds(args, SEND_WAIT_SECONDS)
    allow_user = flag(args, "allow_user_session")
    sender = args.get("from") or "Claude Code"
    text = f"[Message from {sender} via the consultants bridge]\n\n{message}"

    client = CodexClient()
    try:
        thread = resolve(client, to)
        tid, name = thread["id"], short_name(thread)
        if not (is_bridge(thread) or allow_user):
            # Our consultants are read-only; a session the user opened has the user's permissions.
            raise BridgeError(
                f"{name} is a Codex session the user opened, not a read-only consultant: it keeps the "
                "user's own permissions and may be able to edit files. Nothing was sent. Only if the "
                "user asked you to message this session, send again with allow_user_session=true; "
                "otherwise use StartConsultant.")
        with send_lock(tid):
            # Last point a cancellation can still stop the message from being delivered.
            check_cancel(cancel)
            ensure_loaded(client, thread)
            current = latest_turn(client, tid)
            if current and current.get("status") == "inProgress":
                # Session is mid-turn: steer the running turn instead of queueing a new one.
                client.request("turn/steer", {"threadId": tid, "expectedTurnId": current["id"], "input": [{"type": "text", "text": text}]})
                turn_id, mode = current["id"], "steered into the running turn"
            else:
                started = client.request("turn/start", {"threadId": tid, "input": [{"type": "text", "text": text}]})
                turn_id, mode = started["turn"]["id"], "started a new turn"
                # turns/list lags turn/start. Hold the lock until the turn is listed, or a
                # concurrent send would see the session idle and its turn/start would
                # interrupt this one.
                deadline = time.monotonic() + 10
                try:
                    while not find_turn(client, tid, turn_id) and time.monotonic() < deadline:
                        time.sleep(0.2)
                except (BridgeError, OSError):
                    pass  # delivered already; the wait below reports a lasting failure as such
            # Codex can only show a session once it has a turn, so the pane opens here. Inside
            # the lock, so concurrent sends can't open two.
            watching = ""
            if take_watch(tid) or wants_pane(thread):
                try:
                    shown = show_viewer(thread, client.info, quiet=True)
                    watching = f" {shown}" if shown else ""
                except (BridgeError, OSError) as e:
                    watching = f" Could not open a terminal: {e}"
        if not timeout:
            return f"Delivered to {name} ({mode}, turn {turn_id}).{watching} {read_later(tid, turn_id)}"
        try:
            done, turn_id, turn = wait_for_turn(client, tid, turn_id, timeout, cancel, text,
                                                progress_reporter(progress, name))
        except (BridgeError, OSError) as e:
            # The message is already in the session; a plain error would invite a resend.
            raise BridgeError(f"Delivered to {name} ({mode}, turn {turn_id}), but waiting for the reply "
                              f"failed: {e} Don't send the message again; read the reply with "
                              f"GetConsultantReply (turn_id {turn_id}).") from None
        if done:
            return format_turn(name, turn) + (f"\n\n({watching.strip()})" if watching else "")
        return still_working(
            name, turn_id, turn,
            f"Delivered ({mode}), but no reply within {timeout:.0f}s. Don't send the message again. "
            f"{read_later(tid, turn_id)}")
    finally:
        client.close()


def get_consultant_reply(args, cancel=None, progress=None):
    to = target(args)
    timeout = wait_seconds(args, 0)
    client = CodexClient()
    try:
        thread = resolve(client, to)
        tid, name = thread["id"], short_name(thread)
        turn_id = args.get("turn_id")
        turn = find_turn(client, tid, turn_id, REPLY_LOOKBACK) if turn_id else latest_turn(client, tid)
        if not turn:
            if turn_id:
                return f"{name} has no turn {turn_id} among its {REPLY_LOOKBACK} most recent turns."
            return f"{name} has no messages yet."
        if turn.get("status") == "inProgress":
            done = False
            if timeout > 0:
                done, _, last = wait_for_turn(client, tid, turn["id"], timeout, cancel,
                                              on_poll=progress_reporter(progress, name))
                turn = last or turn  # the newest snapshot, for the partial output
            if not done:
                return still_working(name, turn["id"], turn,
                                     f"To be woken when it is ready, run in the background:\n"
                                     f"{waiter_command(tid, turn['id'])}\nOr check again later with "
                                     f"turn_id {turn['id']}; pass wait=\"done\" only if the user wants "
                                     "you to wait for it.")
        out = format_turn(name, turn)
        latest = latest_turn(client, tid)
        if turn["status"] == "interrupted" and latest and latest["id"] != turn["id"]:
            out += (f"\nA later turn exists ({latest['id']}, {latest['status']}). If your message "
                    "continued there, read it by omitting turn_id.")
        return out
    finally:
        client.close()


def watch_consultant(args, cancel=None, progress=None):
    to = target(args)
    client = CodexClient()
    try:
        thread = resolve(client, to)
        has_turns = bool(latest_turn(client, thread["id"]))
        info = client.info
    finally:
        client.close()
    tid, name = thread["id"], short_name(thread)
    if not has_turns:
        # Codex can't resume a session before its first message. If a send slipped in
        # between the check above and this flag, open now rather than wait for the next one.
        set_watch(tid)
        client = CodexClient()
        try:
            has_turns = bool(latest_turn(client, tid))
        finally:
            client.close()
        if not (has_turns and take_watch(tid)):
            return f"{name} has no messages yet; a terminal window will open when you send the first one."
    return show_viewer(thread, info)


def stop_consultant(args, cancel=None, progress=None):
    to = target(args)
    client = CodexClient()
    try:
        thread = resolve(client, to, exact_only=True)
        name = short_name(thread)
        if not is_bridge(thread):
            raise BridgeError(f"{name} was not started by StartConsultant. Close it from its own terminal.")
        client.request("thread/archive", {"threadId": thread["id"]})
    finally:
        client.close()
    set_watch(thread["id"], False)
    with _send_locks_guard:
        _unwatched.discard(thread["id"])
    closed = close_terminals(thread["id"])
    return (f"Stopped {name} (archived)."
            + (f" Closed {closed} terminal window(s) showing it." if closed else "")
            + f" To bring it back: codex unarchive {thread['id']}, "
            f"then codex resume {thread['id']}.")


# --- MCP stdio server --------------------------------------------------------

INSTRUCTIONS = (
    "Whenever the user asks for a Codex consultant, call StartConsultant with cwd set to your "
    "working directory, even if you don't remember one being open (earlier context may have been "
    "compacted). It reuses a consultant it started earlier in this repo, keeping its context, or "
    "starts a new read-only one; it never picks a Codex session the user opened. Talk to it with "
    "SendConsultantMessage, passing the name it returns as `to`. Pass new=true only when the user "
    "asks for a separate consultant. Message a session the user opened only when the user asks you "
    "to, with allow_user_session=true. SendConsultantMessage returns about 5 seconds after delivery, "
    "usually before the reply is ready; replies often take minutes. Do not wait for one. Instead run "
    "the waiter command the result gives as a background command (in Claude Code: the Bash or "
    "PowerShell tool with run_in_background), tell the user the consultation is under way, and carry on with other "
    "work or end your turn so the user can keep working. The waiter exits with the reply when the "
    "turn ends, which wakes you; then act on the reply or report it. Without background commands, "
    "read the reply with GetConsultantReply and the returned turn_id when the user asks or when you "
    "next need it. Pass wait=\"done\" only if the user asks you to wait "
    "for the reply. A result that says 'still working' is not a reply, even if it shows output so "
    "far: never treat it as done."
)

TO_SCHEMA = {"type": "string", "description": "Consultant name, thread id, or unique id prefix/suffix."}


def wait_schema(default):
    return {"anyOf": [{"type": "number", "minimum": 0, "maximum": MAX_WAIT_SECONDS},
                      {"type": "string", "enum": ["done"]}],
            "description": (f"How long to wait for the reply: a number of seconds (0 = don't wait), or "
                            f"\"done\" to wait until the turn ends, up to 4 hours. Default {default}. "
                            "If the turn is still running when the wait ends, the result shows its "
                            "output so far, which is not the reply.")}
EXACT_TO_SCHEMA = {"type": "string", "description": "Consultant name or full thread id (exact match only)."}

TOOLS = [
    {
        "name": "StartConsultant",
        "description": (
            "Get a Codex consultant for a repo: reuse one that StartConsultant started there earlier "
            "(keeping its context), or start a new one. Call it whenever you need a consultant. "
            "Consultants run on the local Codex app-server daemon in a read-only sandbox and never ask "
            "for approvals: they can read files and run read-only commands for auditing, validation "
            "and research, but cannot edit anything. Codex sessions the user opened are never reused; "
            "they are listed in the result. Returns the consultant's name: pass it as `to` to the "
            "other tools. Unless watch=false, the session is shown beside Claude Code (Windows "
            "Terminal or tmux split pane, otherwise a new window) once it has its first message. "
            "The result says so if the codex CLI or the daemon is behind the latest Codex release."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "cwd": {"type": "string", "description": "Absolute path of the project Codex should work in. Pass your working directory. Default: Claude Code's first workspace folder."},
                "model": {"type": "string", "description": "Codex model for a new session. Default: the user's Codex config. Ignored when an existing consultant is reused."},
                "title": {"type": "string", "description": "Session title for a new session, shown in Codex. Ignored when an existing consultant is reused."},
                "instructions": {"type": "string", "description": "Standing instructions for a new consultant's role. Ignored when an existing consultant is reused."},
                "watch": {"type": "boolean", "description": "Show the session in a pane beside Claude Code so the user can watch it work. Default true; pass false only if the user doesn't want a pane. Applies to later sends too."},
                "new": {"type": "boolean", "description": "Start a new session even though a consultant already works in this repo. Default false. Use only when the user asked for a separate consultant."},
            },
        },
        "annotations": {"readOnlyHint": False, "destructiveHint": False},
    },
    {
        "name": "ListConsultants",
        "description": (
            "List Codex sessions (consultants) on this machine: sessions loaded on the local Codex "
            "app-server daemon plus recent StartConsultant sessions it has unloaded. Each row gives "
            "the name to pass to the other tools, the working directory, model, status, and who started it. "
            "Pass cwd to see only the sessions working in that repo."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "cwd": {
                    "type": "string",
                    "description": "Only list sessions whose working directory is inside the git work tree containing this path (nested repos included). Outside git: inside the Claude Code workspace folder that contains it, or inside the path itself.",
                },
                "include_all": {
                    "type": "boolean",
                    "description": "Also show Codex-internal threads (subagents, guardian reviews). Default false. Ignored with cwd, which always hides them.",
                },
            },
        },
        "annotations": {"readOnlyHint": True, "openWorldHint": False},
    },
    {
        "name": "SendConsultantMessage",
        "description": (
            "Send a message into a Codex session. By default it waits 5 seconds, enough to confirm delivery "
            "and return a quick reply; a longer answer is read later with GetConsultantReply, without waiting for it. "
            "The message appears in that session as a new user turn (or steers the running turn if busy). "
            "Address it by the name from ListConsultants, the thread id, or a unique id prefix/suffix. "
            "Sessions the user opened are refused unless allow_user_session=true: they keep the user's "
            "own permissions and may be able to edit files. May open the session's pane beside Claude Code."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "to": TO_SCHEMA,
                "message": {"type": "string", "description": "The message to send."},
                "from": {"type": "string", "description": "Sender label shown to Codex, e.g. your session name. Default 'Claude Code'."},
                "wait": wait_schema(SEND_WAIT_SECONDS),
                "allow_user_session": {"type": "boolean", "description": "Allow sending to a Codex session the user opened (not started by StartConsultant). Default false. Set it only when the user asked you to message that session."},
            },
            "required": ["to", "message"],
        },
        "annotations": {"readOnlyHint": False, "destructiveHint": False},
    },
    {
        "name": "GetConsultantReply",
        "description": (
            "Read a consultant's reply without sending anything: the latest turn, or a specific turn id "
            "returned by SendConsultantMessage (searched among the 100 most recent turns). Use after "
            "a send that came back before the reply. By default it returns at once, with the reply or a "
            "'still working' note. Only when the user wants you to wait, pass wait=\"done\": the call "
            "returns when the turn ends (polled every 1.5 s), or with an error or after 4 hours, so a "
            "client that runs long calls in the background is notified soon after the reply is ready. "
            "While the turn runs, the result shows its output so far, which is not the reply."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "to": TO_SCHEMA,
                "turn_id": {"type": "string", "description": "Turn id to read. Default: the latest turn."},
                "wait": wait_schema(0),
            },
            "required": ["to"],
        },
        # Its one write is nouez's own copy of an over-long reply in the temp folder.
        "annotations": {"readOnlyHint": True, "openWorldHint": False},
    },
    {
        "name": "WatchConsultant",
        "description": (
            "Open a Codex session beside Claude Code (a split pane in Windows Terminal or tmux, otherwise a new terminal window) on the user's machine (`codex resume <id>`), "
            "so the user can watch it work or type into it. Does nothing if a terminal already shows it. "
            "If the session has no messages yet, the window opens when the next SendConsultantMessage "
            "delivers one."
        ),
        "inputSchema": {"type": "object", "properties": {"to": TO_SCHEMA}, "required": ["to"]},
        "annotations": {"readOnlyHint": False, "destructiveHint": False, "idempotentHint": True, "openWorldHint": False},
    },
    {
        "name": "StopConsultant",
        "description": (
            "Stop a Codex session that StartConsultant started: archive it, and end the `codex resume` "
            "processes showing it so their terminal windows close (best effort). Needs the exact name "
            "or full thread id. Refuses sessions without the StartConsultant tag, such as ones the "
            "user opened (a guard against mistakes, not a security boundary)."
        ),
        "inputSchema": {"type": "object", "properties": {"to": EXACT_TO_SCHEMA}, "required": ["to"]},
        "annotations": {"readOnlyHint": False, "destructiveHint": True, "openWorldHint": False},
    },
    {
        "name": "OpenClaudeSession",
        "description": (
            "Open a new terminal window on the user's computer and start an interactive Claude Code "
            "session there with Remote Control, so the user can pick it up from the Claude app on "
            "their phone or the web. Use when the user asks for a new Claude Code session, for "
            "example for another project. The session starts as if the user had typed `claude` in a "
            "fresh terminal: its transcript is saved, unlike a `claude` started from your own shell, "
            "which inherits this session's environment. If Claude Code hasn't been trusted in the "
            "folder, nothing is opened and the result says what to ask the user. Only when the user says "
            "they trust the folder, pass trust=true: nouez records that in Claude Code's settings as its "
            "trust dialog would, after backing the file up."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "cwd": {"type": "string", "description": "Absolute path of the project folder the session works in."},
                "create": {"type": "boolean", "description": "Create the folder if it doesn't exist (its parent must exist). Use when the user asks for a session in a new folder."},
                "trust": {"type": "boolean", "description": "true: the user has said, in this conversation, that they trust this folder; record that in Claude Code's settings before opening, as its trust dialog would. Never set it on your own judgment. Default false."},
                "open_untrusted": {"type": "boolean", "description": "Open the window even though Claude Code hasn't been trusted in the folder, so the user can answer the trust question on the computer. Default false. Set it only when the user asks for that."},
                "model": {"type": "string", "description": "Claude Code model alias or full name. Default: opus (the latest Opus). Set it only when the user asks for another model."},
                "effort": {"type": "string", "enum": list(CLAUDE_EFFORTS), "description": "Effort level. Default: medium. Set it only when the user asks for another."},
                "name": {"type": "string", "description": "Session name, shown in the Claude app's session list. Default: the folder's name."},
                "prompt": {"type": "string", "description": "Optional first message for the new session. Leave it out unless the user gave one."},
            },
            "required": ["cwd"],
        },
        "annotations": {"readOnlyHint": False, "destructiveHint": False, "openWorldHint": False},
    },
    {
        "name": "ListClaudeSessions",
        "description": (
            "List the Claude Code sessions running on the user's computer, whoever started them: each "
            "one's name, process id, folder and status, whether it has Remote Control, and which one "
            "is you. Use it when the user asks which sessions are open, or before CloseClaudeSession."
        ),
        "inputSchema": {"type": "object", "properties": {}},
        "annotations": {"readOnlyHint": True, "openWorldHint": False},
    },
    {
        "name": "CloseClaudeSession",
        "description": (
            "Close one Claude Code session running on the user's computer, for example a stuck one: "
            "end its claude process. A session OpenClaudeSession opened also gets its window closed; "
            "for others, the terminal stays open at the shell prompt. The transcript is kept, so the "
            "session can be resumed. Close only sessions the user named for closing: list them with "
            "ListClaudeSessions, show the user the list, and wait for them to choose. To close several, "
            "call it once per session. It never closes the session you run in."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "The session's name, as ListClaudeSessions shows it."},
                "pid": {"type": "integer", "description": "The session's process id from ListClaudeSessions, to pick one of several with the same name."},
            },
        },
        "annotations": {"readOnlyHint": False, "destructiveHint": True, "openWorldHint": False},
    },
]

HANDLERS = {
    "StartConsultant": start_consultant,
    "ListConsultants": list_consultants,
    "SendConsultantMessage": send_consultant_message,
    "GetConsultantReply": get_consultant_reply,
    "WatchConsultant": watch_consultant,
    "StopConsultant": stop_consultant,
    "OpenClaudeSession": open_claude_session,
    "ListClaudeSessions": list_claude_sessions,
    "CloseClaudeSession": close_claude_session,
}


def write_message(out):
    with _stdout_lock:
        sys.stdout.write(json.dumps(out) + "\n")
        sys.stdout.flush()


def respond(msg_id, result=None, error=None):
    out = {"jsonrpc": "2.0", "id": msg_id}
    if error is not None:
        out["error"] = error
    else:
        out["result"] = result
    write_message(out)


class Progress:
    """notifications/progress for one tools/call whose request carried a progressToken. At most one
    every PROGRESS_SECONDS, none once the call is cancelled; `progress` only ever increases. A
    failed write stops the notifications, never the wait."""

    def __init__(self, token, cancel):
        self.token, self.cancel, self.count, self.last = token, cancel, 0, None
        self.broken = False

    def __call__(self, message):
        now = time.monotonic()
        if self.broken or self.cancel.is_set() or (
                self.last is not None and now - self.last < PROGRESS_SECONDS):
            return
        self.last, self.count = now, self.count + 1
        try:
            write_message({"jsonrpc": "2.0", "method": "notifications/progress", "params": {
                "progressToken": self.token, "progress": self.count, "message": message}})
        except Exception:
            self.broken = True


def progress_for(params, cancel):
    meta = params.get("_meta")
    token = meta.get("progressToken") if isinstance(meta, dict) else None
    if isinstance(token, (str, int)) and not isinstance(token, bool):
        return Progress(token, cancel)
    return None


def client_request(method, params, timeout=5):
    """Send a request to Claude Code and wait for its result (None on error or timeout). Never
    call this from main(): main() is the loop that reads the response."""
    with _client_guard:
        req_id = f"nouez-{next(_client_ids)}"
        waiter = _client_requests[req_id] = [threading.Event(), None]
    write_message({"jsonrpc": "2.0", "id": req_id, "method": method, "params": params})
    waiter[0].wait(timeout)
    with _client_guard:
        _client_requests.pop(req_id, None)
    response = waiter[1] or {}
    return response.get("result")


def path_from_uri(uri):
    parsed = urllib.parse.urlparse(uri)
    if parsed.scheme != "file":
        return None
    return os.path.abspath(urllib.request.url2pathname(parsed.path))


def refresh_roots():
    """Ask Claude Code for its workspace folders. An unanswered request counts as no roots, so a
    client that never replies costs one timeout, not one per tool call."""
    global _client_roots
    result = client_request("roots/list", {})
    roots = [path_from_uri(r.get("uri", "")) for r in (result or {}).get("roots", [])]
    _client_roots = [r for r in roots if r]


def client_roots():
    if _client_roots is None and "roots" in _client_caps:
        refresh_roots()
    return _client_roots or []


def invalid_params(msg_id, message):
    respond(msg_id, error={"code": -32602, "message": message})


def handle(msg, cancel):
    """Answer one request. Any request with an id gets a response, even if handling it fails."""
    try:
        dispatch(msg, cancel)
    except Exception as e:
        log("request error:", repr(e))
        if msg.get("id") is not None and not cancel.is_set():
            respond(msg["id"], error={"code": -32603, "message": f"Internal error: {e!r}"})


def dispatch(msg, cancel):
    method, msg_id, params = msg.get("method"), msg.get("id"), msg.get("params")
    params = {} if params is None else params
    if not isinstance(params, dict):
        if msg_id is not None:
            invalid_params(msg_id, "params must be an object.")
        return
    if msg_id is None:
        if method in ("notifications/initialized", "notifications/roots/list_changed") and "roots" in _client_caps:
            refresh_roots()
        return
    if method == "initialize":
        caps = params.get("capabilities")
        _client_caps.update(caps if isinstance(caps, dict) else {})
        requested = params.get("protocolVersion")
        respond(msg_id, {
            "protocolVersion": requested if requested in PROTOCOL_VERSIONS else PROTOCOL_VERSIONS[0],
            "capabilities": {"tools": {}},
            "serverInfo": {"name": SERVER_NAME, "version": SERVER_VERSION},
            "instructions": INSTRUCTIONS,
        })
        start_release_check()
    elif method == "ping":
        respond(msg_id, {})
    elif method == "tools/list":
        respond(msg_id, {"tools": TOOLS})
    elif method == "tools/call":
        handler = HANDLERS.get(params.get("name"))
        if not handler:
            invalid_params(msg_id, f"Unknown tool: {params.get('name')}")
            return
        arguments = params.get("arguments")
        arguments = {} if arguments is None else arguments
        if not isinstance(arguments, dict):
            invalid_params(msg_id, "arguments must be an object.")
            return
        try:
            text, is_error = handler(arguments, cancel, progress_for(params, cancel)), False
        except Cancelled:
            return  # the client cancelled the request and expects no response
        except BridgeError as e:
            text, is_error = str(e), True
        except Exception as e:  # keep the server alive on unexpected failures
            log("tool error:", repr(e))
            text, is_error = f"Unexpected error: {e!r}", True
        finally:
            with _cancel_guard:
                _cancel_events.pop(msg_id, None)
        if not cancel.is_set():
            respond(msg_id, {"content": [{"type": "text", "text": text}], "isError": is_error})
    else:
        respond(msg_id, error={"code": -32601, "message": f"Method not found: {method}"})


def run_waiter(thread_id, turn_id):
    """`server.py wait <thread_id> <turn_id>`: wait until the turn ends, print its reply, return the
    exit code. Run as a background command, its exit wakes the client with the reply. Rides out a
    few failed connections, such as a daemon restart, rather than give up on a long turn."""
    deadline = time.monotonic() + WAITER_SECONDS
    failures = 0  # in a row: reset by each connection that works
    while True:
        try:
            client = CodexClient()
            try:
                thread = resolve(client, thread_id, exact_only=True)
                tid, name = thread["id"], short_name(thread)
                failures = 0
                turn = find_turn(client, tid, turn_id, REPLY_LOOKBACK)
                if not turn:
                    print(f"{name} has no turn {turn_id} among its {REPLY_LOOKBACK} most recent turns.")
                    return 1
                if turn.get("status") == "inProgress":  # a running turn is among the newest few
                    done, turn_id, turn = wait_for_turn(client, tid, turn_id,
                                                        max(0, deadline - time.monotonic()), None)
                else:
                    done = True
            finally:
                client.close()
        except (BridgeError, OSError) as e:
            failures += 1
            left = deadline - time.monotonic()
            if failures > WAITER_RETRIES or left <= 0:
                print(f"Stopped waiting for turn {turn_id}: {e} Read the reply with GetConsultantReply "
                      f"(to {thread_id}, turn_id {turn_id}).")
                return 1
            time.sleep(min(10, left))
            continue
        if not done:
            print(still_working(name, turn_id, turn, f"Waited {WAITER_SECONDS // 60} minutes. To keep "
                                "waiting, run the same command again in the background:\n"
                                f"{waiter_command(tid, turn_id)}"))
            return 0
        print(f"The consultant's turn has ended (thread {tid}, turn {turn_id}).\n")
        print(format_turn(name, turn, WAITER_REPLY_CHARS))
        return 0


def main():
    sys.stdin.reconfigure(encoding="utf-8")
    sys.stdout.reconfigure(encoding="utf-8")
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except ValueError:
            respond(None, error={"code": -32700, "message": "Parse error"})
            continue
        try:
            route(msg)
        except Exception as e:  # one bad line must never end the loop
            log("bad message:", repr(e))


def valid_id(value):
    return value is None or (isinstance(value, (str, int, float)) and not isinstance(value, bool))


def route(msg):
    """Hand one incoming message to the right place, without blocking the read loop."""
    # MCP request ids are never null; a request with "id": null would otherwise pass as a notification.
    null_id = isinstance(msg, dict) and "method" in msg and "id" in msg and msg["id"] is None
    if not isinstance(msg, dict) or not valid_id(msg.get("id")) or null_id:
        respond(None, error={"code": -32600, "message": "Invalid Request"})
        return
    if "method" not in msg:  # a response to a request we sent (roots/list)
        with _client_guard:
            waiter = _client_requests.get(msg.get("id"))
        if waiter:
            waiter[1] = msg
            waiter[0].set()
        return
    if msg["method"] == "notifications/cancelled":
        params = msg.get("params")
        request_id = params.get("requestId") if isinstance(params, dict) else None
        if valid_id(request_id):
            with _cancel_guard:
                event = _cancel_events.get(request_id)
            if event:
                event.set()
        return
    # Register before starting the worker, so a cancellation that arrives first isn't lost.
    cancel = threading.Event()
    if msg["method"] == "tools/call" and msg.get("id") is not None:
        with _cancel_guard:
            _cancel_events[msg["id"]] = cancel
    # Tool calls can block for minutes; run each request on its own thread.
    threading.Thread(target=handle, args=(msg, cancel), daemon=True).start()


if __name__ == "__main__":
    if sys.argv[1:2] == ["wait"]:
        if len(sys.argv) != 4:
            sys.exit("usage: server.py wait <thread_id> <turn_id>")
        sys.stdout.reconfigure(encoding="utf-8")
        sys.exit(run_waiter(sys.argv[2], sys.argv[3]))
    if sys.argv[1:2] == ["claude"]:
        if len(sys.argv) != 3:
            sys.exit("usage: server.py claude <spec.json>  (written by OpenClaudeSession)")
        sys.exit(run_claude(sys.argv[2]))
    if sys.argv[1:] == ["allow-rule"]:
        print("Add these to permissions.allow in ~/.claude/settings.json:")
        print(",\n".join(json.dumps(rule) for rule in allow_rules()))
        sys.exit(0)
    main()
