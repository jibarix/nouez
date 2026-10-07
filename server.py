"""nouez: MCP server that lets Claude Code talk to Codex sessions.

Tools
  StartConsultant        start a background Codex session (no terminal needed)
  ListConsultants        Codex sessions on the local app-server daemon
  SendConsultantMessage  send a message into one of them and return its reply
  GetConsultantReply     read (or wait for) a reply sent with wait=false
  WatchConsultant        open a session in a terminal window
  StopConsultant         archive a session that StartConsultant started

Transport to Codex: `codex app-server proxy` relays stdio to the daemon's control
socket, which speaks JSON-RPC over WebSocket. Standard library only.
"""

import base64
import json
import os
import queue
import re
import shlex
import shutil
import struct
import subprocess
import sys
import threading
import time

SERVER_NAME = "nouez"
SERVER_VERSION = "0.1.0"
POLL_SECONDS = 1.5
MAX_FRAME_BYTES = 64 * 1024 * 1024
RECENT_SAVED_THREADS = 50  # how far back to look for unloaded bridge consultants
REPLY_LOOKBACK = 100  # how many recent turns GetConsultantReply searches for a turn id
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
_cancel_events = {}  # MCP request id -> Event set by notifications/cancelled
_cancel_guard = threading.Lock()


def log(*args):
    print("[consultants]", *args, file=sys.stderr, flush=True)


class BridgeError(Exception):
    pass


class Cancelled(Exception):
    pass


def check_cancel(cancel):
    if cancel is not None and cancel.is_set():
        raise Cancelled()


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
            self.request("initialize", {"clientInfo": {"name": "nouez", "version": SERVER_VERSION}})
            self.notify("initialized")
        except Exception:
            self.close()
            raise

    def _handshake(self):
        # A hung proxy would block the reads below forever; kill it after the timeout.
        timed_out = threading.Event()
        timer = threading.Timer(self.timeout, lambda: (timed_out.set(), self.close()))
        timer.start()
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
            header = b""
            while not header.endswith(b"\r\n\r\n"):
                c = self.proc.stdout.read(1)
                if not c and timed_out.is_set():
                    raise OSError
                if not c:
                    raise BridgeError(
                        "Codex app-server daemon is not reachable. Start it with "
                        "`codex app-server daemon start`, or open a Codex session."
                    )
                header += c
        except OSError:
            raise BridgeError(f"Codex app-server proxy did not respond within {self.timeout}s.")
        finally:
            timer.cancel()
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
        if self.proc.poll() is None:
            if os.name == "nt":
                subprocess.run(["taskkill", "/F", "/T", "/PID", str(self.proc.pid)], capture_output=True)
            else:
                self.proc.kill()


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


def resolve(client, target):
    target = target.strip().lower()
    threads = load_consultants(client, include_all=True)
    exact = [t for t in threads if target in (t["id"].lower(), short_name(t))]
    if exact:
        return exact[0]
    partial = [t for t in threads if t["id"].lower().startswith(target) or t["id"].lower().endswith(target)]
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
    raise BridgeError(f"No Codex session named '{target}'. Sessions: {names}")


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
    """Poll until the turn finishes. Returns the finished turn, or None on timeout.
    With `text` (the message we sent), follow an interrupted turn into its continuation."""
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
            return turn
        if time.time() >= deadline:
            return None
        check_cancel(cancel)
        time.sleep(POLL_SECONDS)


def format_turn(name, turn):
    reply = turn_reply(turn)
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


def take_watch(tid):
    """Atomically claim a pending watch request, so only one sender opens the window."""
    with _send_locks_guard:
        if tid in _watch_pending:
            _watch_pending.discard(tid)
            return True
        return False


def open_terminal(cwd, thread_id):
    """Open `codex resume <id>` beside Claude Code: a split pane when Claude Code runs in
    Windows Terminal or tmux, otherwise a new terminal window. Returns a description of what opened."""
    cwd = cwd if cwd and os.path.isdir(cwd) else os.getcwd()
    resume = ["codex", "resume", thread_id]
    kwargs = {"cwd": cwd, "stdin": subprocess.DEVNULL, "stdout": subprocess.DEVNULL, "stderr": subprocess.DEVNULL}
    tmux = shutil.which("tmux") if os.environ.get("TMUX") else None
    if tmux:
        argv, how = [tmux, "split-window", "-h", "-c", cwd, shlex.join(resume)], "a tmux split pane"
    elif os.name == "nt":
        # codex is usually an npm .cmd shim, so run it through cmd; /k keeps errors on screen.
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
    run = {"capture_output": True, "text": True, "timeout": 20}
    try:
        if os.name == "nt":
            # Only the cmd windows open_terminal started. Each output line: the cmd pid, then its children.
            ps = ("Get-CimInstance Win32_Process -Filter \"Name='cmd.exe'\" | Where-Object "
                  f"{{ $_.CommandLine -like '*/k codex resume {thread_id}' }} | ForEach-Object {{ "
                  "$p = $_.ProcessId; "
                  "$k = @(Get-CimInstance Win32_Process -Filter \"ParentProcessId=$p\" | ForEach-Object { $_.ProcessId }); "
                  "\"$p $k\" }")
            out = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", ps], **run).stdout
            shells = [line.split() for line in out.splitlines() if line.strip()]
            for pids in shells:
                for child in pids[1:]:
                    subprocess.run(["taskkill", "/PID", child, "/T", "/F"], **run)
                # Windows Terminal closes a pane by itself only on a clean exit, so end cmd with code 0.
                end_process(int(pids[0]), 0)
            return len(shells)
        pattern = f"codex[^ ]* resume {thread_id}"
        pids = subprocess.run(["pgrep", "-f", pattern], **run).stdout.split()
        if pids:
            subprocess.run(["pkill", "-f", pattern], **run)
        return len(pids)
    except (OSError, subprocess.SubprocessError):
        return 0


def list_consultants(args, cancel=None):
    client = CodexClient()
    try:
        threads = load_consultants(client, bool(args.get("include_all")))
    finally:
        client.close()
    if not threads:
        return "No Codex sessions. Start one with StartConsultant, or open Codex in a terminal."
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
    return f"{len(threads)} Codex session(s):\n" + "\n".join(lines)


def start_consultant(args, cancel=None):
    cwd = os.path.abspath(args.get("cwd") or os.getcwd())
    if not os.path.isdir(cwd):
        raise BridgeError(f"cwd is not a directory: {cwd}")
    # Consultants audit, validate and research; they never edit. No terminal is attached to
    # answer approval prompts, so never ask; the read-only sandbox is the limit.
    params = {"cwd": cwd, "sandbox": SANDBOX, "approvalPolicy": "never", "threadSource": BRIDGE_SOURCE}
    if args.get("model"):
        params["model"] = args["model"]
    if args.get("instructions"):
        params["developerInstructions"] = args["instructions"]

    client = CodexClient()
    try:
        thread = client.request("thread/start", params)["thread"]
        if args.get("title"):
            client.request("thread/name/set", {"threadId": thread["id"], "name": args["title"]})
    finally:
        client.close()
    watch = bool(args.get("watch"))
    if watch:
        set_watch(thread["id"])
    return (
        f"Started {short_name(thread)}\n"
        f"    id: {thread['id']}\n"
        f"    cwd: {thread.get('cwd')}\n"
        f"    model: {thread.get('model')} ({thread.get('modelProvider')})\n"
        f"    sandbox: {SANDBOX}\n"
        + ("A terminal window will open when you send its first message.\n" if watch else "")
        + "Send it work with SendConsultantMessage."
    )


def send_consultant_message(args, cancel=None):
    target = args.get("to") or ""
    message = args.get("message") or ""
    if not target or not message:
        raise BridgeError("Both `to` and `message` are required.")
    wait = args.get("wait", True)
    timeout = float(args.get("timeout_seconds", 600))
    sender = args.get("from") or "Claude Code"
    text = f"[Message from {sender} via the consultants bridge]\n\n{message}"

    client = CodexClient()
    try:
        thread = resolve(client, target)
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
                while not find_turn(client, tid, turn_id) and time.time() < deadline:
                    time.sleep(0.2)
        watching = ""
        if take_watch(tid):
            try:
                watching = f" Opened it in {open_terminal(thread.get('cwd'), tid)}."
            except (BridgeError, OSError) as e:
                watching = f" Could not open a terminal: {e}"
        if not wait:
            return (f"Delivered to {name} ({mode}, turn {turn_id}).{watching} Not waiting; "
                    "read the reply later with GetConsultantReply.")
        turn = wait_for_turn(client, tid, turn_id, timeout, cancel, text)
        if turn:
            return format_turn(name, turn) + (f"\n\n({watching.strip()})" if watching else "")
        return (f"Delivered to {name} ({mode}), but no reply within {timeout:.0f}s. Turn {turn_id} is "
                "still running; read it later with GetConsultantReply.")
    finally:
        client.close()


def get_consultant_reply(args, cancel=None):
    target = args.get("to") or ""
    if not target:
        raise BridgeError("`to` is required.")
    timeout = float(args.get("timeout_seconds", 0))
    client = CodexClient()
    try:
        thread = resolve(client, target)
        tid, name = thread["id"], short_name(thread)
        turn_id = args.get("turn_id")
        turn = find_turn(client, tid, turn_id, REPLY_LOOKBACK) if turn_id else latest_turn(client, tid)
        if not turn:
            if turn_id:
                return f"{name} has no turn {turn_id} among its {REPLY_LOOKBACK} most recent turns."
            return f"{name} has no messages yet."
        if turn.get("status") == "inProgress":
            done = wait_for_turn(client, tid, turn["id"], timeout, cancel) if timeout > 0 else None
            if not done:
                return f"{name} is still working on turn {turn['id']}."
            turn = done
        out = format_turn(name, turn)
        latest = latest_turn(client, tid)
        if turn["status"] == "interrupted" and latest and latest["id"] != turn["id"]:
            out += f"\nA later turn exists ({latest['id']}, {latest['status']}); read it by omitting turn_id."
        return out
    finally:
        client.close()


def watch_consultant(args, cancel=None):
    target = args.get("to") or ""
    if not target:
        raise BridgeError("`to` is required.")
    client = CodexClient()
    try:
        thread = resolve(client, target)
        has_turns = bool(latest_turn(client, thread["id"]))
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
    return f"Opened {name} in {open_terminal(thread.get('cwd'), tid)}."


def stop_consultant(args, cancel=None):
    target = args.get("to") or ""
    if not target:
        raise BridgeError("`to` is required.")
    client = CodexClient()
    try:
        thread = resolve(client, target)
        name = short_name(thread)
        if not is_bridge(thread):
            raise BridgeError(f"{name} was not started by StartConsultant. Close it from its own terminal.")
        client.request("thread/archive", {"threadId": thread["id"]})
    finally:
        client.close()
    set_watch(thread["id"], False)
    closed = close_terminals(thread["id"])
    return (f"Stopped {name} (archived)."
            + (f" Closed {closed} terminal window(s) showing it." if closed else "")
            + f" To bring it back: codex unarchive {thread['id']}, "
            f"then codex resume {thread['id']}.")


# --- MCP stdio server --------------------------------------------------------

TO_SCHEMA = {"type": "string", "description": "Consultant name, thread id, or unique id prefix/suffix."}

TOOLS = [
    {
        "name": "StartConsultant",
        "description": (
            "Start a new Codex session (consultant) in the background, with no terminal needed. "
            "It runs on the local Codex app-server daemon in a read-only sandbox and never asks for "
            "approvals: it can read files and run read-only commands for auditing, validation and "
            "research, but cannot edit anything. Returns the name to pass to SendConsultantMessage."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "cwd": {"type": "string", "description": "Absolute path of the project Codex should work in. Pass your working directory; defaults to the bridge server's own."},
                "model": {"type": "string", "description": "Codex model. Default: the user's Codex config."},
                "title": {"type": "string", "description": "Optional session title shown in Codex."},
                "instructions": {"type": "string", "description": "Optional standing instructions for the consultant's role."},
                "watch": {"type": "boolean", "description": "Open the session in a terminal window when its first message is sent, so the user can watch it work. Default false."},
            },
        },
    },
    {
        "name": "ListConsultants",
        "description": (
            "List Codex sessions (consultants) on this machine: sessions loaded on the local Codex "
            "app-server daemon plus recent StartConsultant sessions it has unloaded. Each row gives "
            "the name to pass to the other tools, the working directory, model, status, and who started it."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "include_all": {
                    "type": "boolean",
                    "description": "Also show Codex-internal threads (subagents, guardian reviews). Default false.",
                }
            },
        },
    },
    {
        "name": "SendConsultantMessage",
        "description": (
            "Send a message into a Codex session and, by default, wait for and return its reply. "
            "The message appears in that session as a new user turn (or steers the running turn if busy). "
            "Address it by the name from ListConsultants, the thread id, or a unique id prefix/suffix."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "to": TO_SCHEMA,
                "message": {"type": "string", "description": "The message to send."},
                "from": {"type": "string", "description": "Sender label shown to Codex, e.g. your session name. Default 'Claude Code'."},
                "wait": {"type": "boolean", "description": "Wait for the reply. Default true. With false, read it later with GetConsultantReply."},
                "timeout_seconds": {"type": "number", "description": "Max seconds to wait for the reply. Default 600."},
            },
            "required": ["to", "message"],
        },
    },
    {
        "name": "GetConsultantReply",
        "description": (
            "Read a consultant's reply without sending anything: the latest turn, or a specific turn id "
            "returned by SendConsultantMessage (searched among the 100 most recent turns). Use after "
            "sending with wait=false or after a timeout."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "to": TO_SCHEMA,
                "turn_id": {"type": "string", "description": "Turn id to read. Default: the latest turn."},
                "timeout_seconds": {"type": "number", "description": "If the turn is still running, wait up to this long. Default 0 (don't wait)."},
            },
            "required": ["to"],
        },
    },
    {
        "name": "WatchConsultant",
        "description": (
            "Open a Codex session beside Claude Code (a split pane in Windows Terminal or tmux, otherwise a new terminal window) on the user's machine (`codex resume <id>`), "
            "so the user can watch it work or type into it. If the session has no messages yet, the "
            "window opens when the first one is sent."
        ),
        "inputSchema": {"type": "object", "properties": {"to": TO_SCHEMA}, "required": ["to"]},
    },
    {
        "name": "StopConsultant",
        "description": (
            "Stop a Codex session that StartConsultant started, by archiving it and closing any "
            "terminal window watching it. Refuses sessions "
            "without the StartConsultant tag, such as ones the user opened (a guard against "
            "mistakes, not a security boundary)."
        ),
        "inputSchema": {"type": "object", "properties": {"to": TO_SCHEMA}, "required": ["to"]},
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


def respond(msg_id, result=None, error=None):
    out = {"jsonrpc": "2.0", "id": msg_id}
    if error is not None:
        out["error"] = error
    else:
        out["result"] = result
    with _stdout_lock:
        sys.stdout.write(json.dumps(out) + "\n")
        sys.stdout.flush()


def handle(msg, cancel):
    method, msg_id, params = msg.get("method"), msg.get("id"), msg.get("params") or {}
    if msg_id is None:
        return  # notification
    if method == "initialize":
        respond(msg_id, {
            "protocolVersion": params.get("protocolVersion", "2025-06-18"),
            "capabilities": {"tools": {}},
            "serverInfo": {"name": SERVER_NAME, "version": SERVER_VERSION},
        })
    elif method == "ping":
        respond(msg_id, {})
    elif method == "tools/list":
        respond(msg_id, {"tools": TOOLS})
    elif method == "tools/call":
        handler = HANDLERS.get(params.get("name"))
        if not handler:
            respond(msg_id, error={"code": -32602, "message": f"Unknown tool: {params.get('name')}"})
            return
        try:
            text, is_error = handler(params.get("arguments") or {}, cancel), False
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
        if msg.get("method") == "notifications/cancelled":
            with _cancel_guard:
                event = _cancel_events.get((msg.get("params") or {}).get("requestId"))
            if event:
                event.set()
            continue
        # Register before starting the worker, so a cancellation that arrives first isn't lost.
        cancel = threading.Event()
        if msg.get("method") == "tools/call" and msg.get("id") is not None:
            with _cancel_guard:
                _cancel_events[msg["id"]] = cancel
        # Tool calls can block for minutes; run each request on its own thread.
        threading.Thread(target=handle, args=(msg, cancel), daemon=True).start()


if __name__ == "__main__":
    main()
