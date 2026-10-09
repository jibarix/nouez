"""nouez: MCP server that lets Claude Code talk to Codex sessions.

Tools
  StartConsultant        reuse the repo's consultant, or start a read-only one, shown in a pane
  ListConsultants        Codex sessions on the local app-server daemon
  SendConsultantMessage  send a message into one of them and return its reply
  GetConsultantReply     read (or wait for) a reply sent with wait=false
  WatchConsultant        open a session in a terminal window
  StopConsultant         archive a session that StartConsultant started

Transport to Codex: `codex app-server proxy` relays stdio to the daemon's control
socket, which speaks JSON-RPC over WebSocket. Standard library only.
"""

import base64
import glob
import json
import math
import os
import queue
import re
import shlex
import shutil
import struct
import subprocess
import sys
import tempfile
import threading
import time
import urllib.parse
import urllib.request

SERVER_NAME = "nouez"
SERVER_VERSION = "0.3.2"
# MCP protocol versions this server answers to, newest first. Nothing nouez uses changed
# between them; a client asking for any other version is offered the newest.
PROTOCOL_VERSIONS = ("2025-11-25", "2025-06-18", "2025-03-26")
POLL_SECONDS = 1.5
MAX_FRAME_BYTES = 64 * 1024 * 1024
RECENT_SAVED_THREADS = 50  # how far back to look for unloaded bridge consultants
REPLY_LOOKBACK = 100  # how many recent turns GetConsultantReply searches for a turn id
MAX_WAIT_SECONDS = 4 * 60 * 60  # ceiling on any wait, until_done included, so a hung turn can't pin a call
MAX_REPLY_CHARS = 60_000  # longer replies are cut here; the full text is saved to a file
PARTIAL_CHARS = 4_000  # how much of a still-running turn's output a timeout shows (the most recent part)
BRIDGE_SOURCE = "nouez"  # threadSource tag on sessions started by StartConsultant
SANDBOX = "read-only"
# How Codex 0.160.1 reports a session whose history isn't written yet: before the first
# message (titled or not), and in the moment the first turn's rollout file is created.
NO_HISTORY_ERRORS = ("not materialized", "missing source rollout", "no rollout found", "is empty",
                     "list_turns is not supported yet")
_stdout_lock = threading.Lock()
_send_locks = {}  # thread id -> lock, so concurrent sends can't both start a turn
_send_locks_guard = threading.Lock()
_watch_pending = set()  # consultants to open in a terminal once their first turn starts
_unwatched = set()  # StartConsultant sessions started with watch=false: no automatic pane
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


def number(args, key, default):
    """A non-negative number of seconds, capped at MAX_WAIT_SECONDS."""
    value = args.get(key, default)
    try:
        if isinstance(value, bool):
            raise ValueError
        seconds = float(value)
        if not math.isfinite(seconds) or seconds < 0:
            raise ValueError
    except (TypeError, ValueError):
        raise BridgeError(f"`{key}` must be a number of seconds, 0 or more, not {value!r}.") from None
    return min(seconds, MAX_WAIT_SECONDS)


def wait_seconds(args, default):
    """How long to wait for a turn: until_done means up to MAX_WAIT_SECONDS."""
    return MAX_WAIT_SECONDS if flag(args, "until_done") else number(args, "timeout_seconds", default)


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
        self.proc = subprocess.Popen(
            [exe, "app-server", "proxy"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
        )
        try:
            self._handshake()
            threading.Thread(target=self._reader, daemon=True).start()
            # userAgent carries the daemon's version and codexHome its install root.
            self.info = self.request("initialize", {"clientInfo": {"name": "nouez", "version": SERVER_VERSION}})
            self.notify("initialized")
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
            raise BridgeError(
                "Codex app-server daemon is not reachable. Start it with "
                "`codex app-server daemon start`, or open a Codex session."
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
        deadline = time.time() + self.timeout
        while time.time() < deadline:
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


def wait_for_turn(client, tid, turn_id, timeout, cancel, text=None):
    """Poll until the turn finishes. Returns (done, turn_id, turn): on timeout, done is False and
    turn is the last snapshot seen (or None). With `text` (the message we sent), follow an
    interrupted turn into its continuation; turn_id is then the continuation's id."""
    deadline = time.time() + timeout
    grace = None  # an interrupted turn's continuation may take a moment to be listed
    while True:
        turn = find_turn(client, tid, turn_id)
        if turn and turn.get("status") == "interrupted" and text:
            nxt = continuation(client, tid, turn_id, text)
            if nxt:
                turn_id, grace = nxt["id"], None
                continue
            grace = grace or time.time() + 5
            if time.time() < grace:
                check_cancel(cancel)
                time.sleep(0.5)
                continue
        if turn and turn.get("status") != "inProgress":
            return True, turn_id, turn
        if time.time() >= deadline:
            return False, turn_id, turn
        check_cancel(cancel)
        time.sleep(POLL_SECONDS)


def cap_reply(turn_id, reply):
    """The reply, or its first MAX_REPLY_CHARS with the rest saved to a file the caller can read."""
    if len(reply) <= MAX_REPLY_CHARS:
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
    omitted = len(reply) - MAX_REPLY_CHARS
    return f"{reply[:MAX_REPLY_CHARS]}\n\n[Truncated: {omitted} more characters. {where}]"


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


def format_turn(name, turn):
    reply = cap_reply(turn["id"], turn_reply(turn))
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
            # -w 0 is the most recently used Windows Terminal window, normally Claude Code's own.
            argv, how = [wt, "-w", "0", "split-pane", "-V", "-d", cwd, "--title", "Codex consultant",
                         "cmd", "/k", *resume], "a Windows Terminal split pane"
        elif wt:
            argv, how = [wt, "-w", "new", "-d", cwd, "--title", "Codex consultant", "cmd", "/k", *resume], "Windows Terminal"
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


def list_consultants(args, cancel=None):
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


def start_consultant(args, cancel=None):
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
    finally:
        client.close()

    name = short_name(thread)
    # The latest StartConsultant call decides whether the session gets an automatic pane.
    with _send_locks_guard:
        (_unwatched.discard if watch else _unwatched.add)(thread["id"])
    user_note = (f"\nThe user's own Codex sessions in this repo were not used (they keep the user's "
                 f"permissions); message one only if the user asks you to:\n{format_threads(users)}"
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
    )


def send_consultant_message(args, cancel=None):
    to = target(args)
    message = args.get("message") or ""
    if not message:
        raise BridgeError("`message` is required.")
    wait = flag(args, "wait", True)
    timeout = wait_seconds(args, 600)
    sender = args.get("from") or "Claude Code"
    text = f"[Message from {sender} via the consultants bridge]\n\n{message}"

    client = CodexClient()
    try:
        thread = resolve(client, to)
        tid, name = thread["id"], short_name(thread)
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
                deadline = time.time() + 10
                try:
                    while not find_turn(client, tid, turn_id) and time.time() < deadline:
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
        if not wait:
            return (f"Delivered to {name} ({mode}, turn {turn_id}).{watching} Not waiting; "
                    "read the reply later with GetConsultantReply.")
        try:
            done, turn_id, turn = wait_for_turn(client, tid, turn_id, timeout, cancel, text)
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
            f"Call GetConsultantReply with turn_id {turn_id} and until_done=true to be told when it finishes.")
    finally:
        client.close()


def get_consultant_reply(args, cancel=None):
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
                done, _, last = wait_for_turn(client, tid, turn["id"], timeout, cancel)
                turn = last or turn  # the newest snapshot, for the partial output
            if not done:
                return still_working(name, turn["id"], turn,
                                     f"Call again with turn_id {turn['id']} and until_done=true to be "
                                     "told when it finishes.")
        out = format_turn(name, turn)
        latest = latest_turn(client, tid)
        if turn["status"] == "interrupted" and latest and latest["id"] != turn["id"]:
            out += (f"\nA later turn exists ({latest['id']}, {latest['status']}). If your message "
                    "continued there, read it by omitting turn_id.")
        return out
    finally:
        client.close()


def watch_consultant(args, cancel=None):
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


def stop_consultant(args, cancel=None):
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
    "asks for a separate consultant. Message a session the user opened only when the user asks you to. "
    "For a long task, send with wait=false, then call GetConsultantReply with the returned turn_id "
    "and until_done=true; it returns when the turn ends, or with an error or after 4 hours. A "
    "result that says 'still working' is not a reply, even if it shows output so far: call "
    "GetConsultantReply with until_done=true again rather than treating it as done."
)

TO_SCHEMA = {"type": "string", "description": "Consultant name, thread id, or unique id prefix/suffix."}
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
            "Terminal or tmux split pane, otherwise a new window) once it has its first message."
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
            "Send a message into a Codex session and, by default, wait for and return its reply. "
            "The message appears in that session as a new user turn (or steers the running turn if busy). "
            "Address it by the name from ListConsultants, the thread id, or a unique id prefix/suffix. "
            "A session the user opened keeps the user's own permissions and may be able to edit files: "
            "message one only when the user asks you to. May open the session's pane beside Claude Code."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "to": TO_SCHEMA,
                "message": {"type": "string", "description": "The message to send."},
                "from": {"type": "string", "description": "Sender label shown to Codex, e.g. your session name. Default 'Claude Code'."},
                "wait": {"type": "boolean", "description": "Wait for the reply. Default true. With false, return once the message is delivered (timeout_seconds and until_done are then ignored) and read the reply later with GetConsultantReply."},
                "timeout_seconds": {"type": "number", "minimum": 0, "description": "Max seconds to wait for the reply after delivery. Default 600, at most 14400. On timeout the result shows the output so far, which is not the reply."},
                "until_done": {"type": "boolean", "description": "Wait until the turn ends, up to 4 hours (overrides timeout_seconds). Default false."},
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
            "sending with wait=false or after a timeout. For long turns pass until_done=true: the call "
            "returns when the turn ends (polled every 1.5 s), or with an error or after 4 hours, so a "
            "client that runs long calls in the background is notified soon after the reply is ready. "
            "While the turn runs, the result shows its output so far, which is not the reply."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "to": TO_SCHEMA,
                "turn_id": {"type": "string", "description": "Turn id to read. Default: the latest turn."},
                "timeout_seconds": {"type": "number", "minimum": 0, "description": "If the turn is still running, wait up to this long. Default 0 (don't wait), at most 14400."},
                "until_done": {"type": "boolean", "description": "If the turn is still running, wait until it ends, up to 4 hours (overrides timeout_seconds). Default false."},
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
]

HANDLERS = {
    "StartConsultant": start_consultant,
    "ListConsultants": list_consultants,
    "SendConsultantMessage": send_consultant_message,
    "GetConsultantReply": get_consultant_reply,
    "WatchConsultant": watch_consultant,
    "StopConsultant": stop_consultant,
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
            text, is_error = handler(arguments, cancel), False
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
    main()
