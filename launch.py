"""nouez's launcher for the Claude Code plugin: the MCP server the plugin names.

    py -3 -I ${CLAUDE_PLUGIN_ROOT}/launch.py ${CLAUDE_PLUGIN_DATA}

The plugin's own folder changes with each version, and Claude Code removes old ones. So this copies
the plugin's server.py to DATA/app/server.py, one path that stays put (the waiter's allow rules, the
status line, the hooks and the phone dispatcher's sign-in start all name it), and only ever to a
higher version: a session still on an older plugin never takes a newer copy back. Beside it,
DATA/app/plugin.json tells every run of that server.py that it is the plugin.

Then it runs that server.py and passes the MCP messages through, so that a session that is already
open moves to a newer copy by itself: on a request from Claude Code once a newer one is in place, it
asks the server `nouez/idle` and, only when nothing is under way there, ends it and starts the new
one, giving it the session's initialize again. Nothing is handed over: the idle answer says nothing
is lost. Standard library only, Python 3.9+, and kept small: an open session keeps the launcher it
started with.
"""
import json
import os
import queue
import re
import stat
import subprocess
import sys
import threading
import time

VERSION = re.compile(rb'^SERVER_VERSION = "(\d+)\.(\d+)\.(\d+)"', re.M)
IDLE_METHOD = "nouez/idle"
ASK_EVERY = 10  # seconds between two idle questions while the server isn't idle
ASK_SECONDS = 15  # how long an idle answer may take: none is a no
STOP_SECONDS = 10  # how long the old server gets to end once its input is closed
REPLAY_SECONDS = 30  # how long the new server may take to answer the initialize it is given again
REPLACE_TRIES = 20


def log(*args):
    print("[nouez launch]", *args, file=sys.stderr, flush=True)


def version_of(raw):
    """(major, minor, patch) of a server.py's bytes, or None."""
    m = VERSION.search(raw or b"")
    return tuple(int(x) for x in m.groups()) if m else None


def read_bytes(path):
    try:
        with open(path, "rb") as f:
            return f.read()
    except OSError:
        return None


def write_atomic(path, raw):
    """Write `raw` to `path` through a file of its own beside it, read back, then moved into place;
    a replace Windows refuses while another process reads the file is tried again."""
    tmp = f"{path}.{os.getpid()}.tmp"
    if is_link(tmp):
        os.remove(tmp)  # the link itself, never what it points to
    try:
        with os.fdopen(os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0), 0o600),
                       "wb") as f:
            f.write(raw)
        if read_bytes(tmp) != raw:
            raise OSError(f"{tmp} didn't read back as written")
        for attempt in range(REPLACE_TRIES):
            try:
                os.replace(tmp, path)
                return
            except PermissionError:
                if attempt == REPLACE_TRIES - 1:
                    raise
                time.sleep(0.1)
    finally:
        if os.path.exists(tmp):
            os.remove(tmp)


def is_link(path):
    """Whether `path` is a symbolic link or, on Windows, a junction or other reparse point."""
    try:
        st = os.lstat(path)
    except OSError:
        return False
    return stat.S_ISLNK(st.st_mode) or bool(getattr(st, "st_file_attributes", 0) & 0x400)


class LinkRefused(OSError):
    """The data folder or its app folder is a link: nouez neither writes nor runs anything there."""


class InstallLock:
    """One launcher at a time copies into DATA/app (a locked byte; the system frees it if one dies)."""

    def __init__(self, path):
        self.path = path

    def __enter__(self):
        self.fd = os.open(self.path, os.O_RDWR | os.O_CREAT, 0o600)
        if os.name == "nt":
            import msvcrt
            deadline = time.monotonic() + 30
            while True:
                try:
                    msvcrt.locking(self.fd, msvcrt.LK_NBLCK, 1)
                    return self
                except OSError:
                    if time.monotonic() > deadline:
                        raise
                    time.sleep(0.1)
        import fcntl
        fcntl.flock(self.fd, fcntl.LOCK_EX)
        return self

    def __exit__(self, *exc):
        if os.name == "nt":
            import msvcrt
            os.lseek(self.fd, 0, os.SEEK_SET)
            msvcrt.locking(self.fd, msvcrt.LK_UNLCK, 1)
        os.close(self.fd)


def plugin_id(data):
    """nouez@<marketplace>, from the data folder Claude Code gives the plugin (<plugin>-<marketplace>)."""
    name = os.path.basename(os.path.normpath(data))
    market = name[len("nouez-"):] if name.startswith("nouez-") else name
    return "nouez@" + (re.sub(r"[^A-Za-z0-9._-]", "-", market) or "nouez")


def install(root, data):
    """Put the plugin's server.py at DATA/app/server.py unless one as new or newer is there (a
    --plugin-dir load, whose data folder ends in -inline, takes the same version with other bytes
    too), the marker first. The path to run."""
    app = os.path.join(data, "app")
    if is_link(data):  # nouez's files there are never written through a link, nor run from one
        raise LinkRefused(f"{data} is a link")
    os.makedirs(app, exist_ok=True)
    if is_link(app):
        raise LinkRefused(f"{app} is a link")
    target = os.path.join(app, "server.py")
    mine = read_bytes(os.path.join(root, "server.py"))
    if version_of(mine) is None:
        raise OSError(f"{root}/server.py isn't nouez's")
    with InstallLock(os.path.join(app, "install.lock")):
        marker = json.dumps({"id": plugin_id(data)}).encode("utf-8")
        if read_bytes(os.path.join(app, "plugin.json")) != marker:
            write_atomic(os.path.join(app, "plugin.json"), marker)
        there = read_bytes(target)
        have = version_of(there)
        inline = os.path.basename(os.path.normpath(data)).endswith("-inline")
        if have is None or version_of(mine) > have or (inline and version_of(mine) == have and mine != there):
            write_atomic(target, mine)
    return target


def dumps(msg):
    return json.dumps(msg, ensure_ascii=False).encode("utf-8")


class Proxy:
    """Claude Code <-> the server.py at `script`, moving to a newer one there when the server is idle."""

    def __init__(self, script, out=None, argv=None):
        self.script = script
        self.out = out or sys.stdout.buffer
        self.argv = argv or (lambda path: [sys.executable, "-I", path])
        self.events = queue.Queue()
        self.gen = 0
        self.child = None
        self.version = None
        self.seen = None  # (mtime, size) of the script when its version was last read
        self.found = None
        self.init = None  # the client's initialize, given again to each new server
        self.init_id = None
        self.initialized = False
        self.open = {}  # id given to the client -> (generation, the server's own id) of a server's request
        self.state = "normal"  # "asking" (idle asked), "replaying" (new server, initialize given again)
        self.code = None  # the exit code once a move failed and the session is over
        self.held = []  # what the client sent while a switch was under way
        self.deadline = 0
        self.next_ask = 0
        self.asked = 0

    # --- the server process ---

    def start(self):
        raw = read_bytes(self.script)
        self.version = version_of(raw)
        self.gen += 1
        self.child = subprocess.Popen(self.argv(self.script), stdin=subprocess.PIPE, stdout=subprocess.PIPE)
        threading.Thread(target=self.read_child, args=(self.child, self.gen), daemon=True).start()

    def read_child(self, proc, gen):
        for line in proc.stdout:
            self.events.put(("child", gen, line))
        self.events.put(("exit", gen, proc))

    def to_child(self, raw):
        try:
            self.child.stdin.write(raw.rstrip(b"\r\n") + b"\n")
            self.child.stdin.flush()
        except (OSError, ValueError):
            pass  # it ended: its exit comes as an event

    def to_client(self, raw):
        self.out.write(raw.rstrip(b"\r\n") + b"\n")
        self.out.flush()

    def newer(self):
        """The version at the script's path when it is higher than the running server's, else None."""
        try:
            st = os.stat(self.script)
        except OSError:
            return None
        if (st.st_mtime_ns, st.st_size) != self.seen:
            self.seen = (st.st_mtime_ns, st.st_size)
            self.found = version_of(read_bytes(self.script))
        return self.found if self.found and self.version and self.found > self.version else None

    # --- messages ---

    def run(self, stdin=None):
        stdin = stdin or sys.stdin.buffer

        def read_client():
            for line in stdin:
                self.events.put(("client", None, line))
            self.events.put(("eof", None, None))
        threading.Thread(target=read_client, daemon=True).start()
        self.start()
        while True:
            code = self.step()
            if code is not None:
                return code

    def step(self, timeout=1):
        """Handle one event, or none within `timeout`; the exit code once the session is over."""
        try:
            kind, gen, item = self.events.get(timeout=timeout)
        except queue.Empty:
            self.tick()
            return self.code
        if kind == "client":
            self.from_client(item)
        elif kind == "child" and gen == self.gen:
            self.from_child(item)
        elif kind == "exit" and gen == self.gen:
            return item.wait()  # the server ended by itself: so does this, as it would have
        elif kind == "eof":
            return self.stop(self.child)
        self.tick()
        return self.code

    def tick(self):
        if self.state == "asking" and time.monotonic() > self.deadline:
            log("no idle answer; staying on this version for now")
            self.resume()
        elif self.state == "replaying" and time.monotonic() > self.deadline:
            self.fail("it didn't answer initialize")

    def from_client(self, raw):
        try:
            msg = json.loads(raw)
        except ValueError:
            msg = None
        if not isinstance(msg, dict):
            self.to_child(raw) if self.state == "normal" else self.held.append(raw)
            return
        method, msg_id = msg.get("method"), msg.get("id")
        if method is None:  # an answer to a server's request
            gen, own = self.open.pop(msg_id, (None, None)) if isinstance(msg_id, str) else (None, None)
            if gen is None:
                self.to_child(raw)
            elif gen == self.gen:
                self.to_child(dumps({**msg, "id": own}))
            return  # one for a server that has ended goes nowhere
        if method == "notifications/cancelled":
            params = msg.get("params") if isinstance(msg.get("params"), dict) else {}
            target = params.get("requestId")
            kept = [m for m in self.held if not self.is_request(m, target)]
            if len(kept) != len(self.held):
                self.held = kept  # never sent: nothing to cancel
                return
            self.to_child(raw)
            return
        if self.state != "normal":
            self.held.append(raw)
            return
        if method == "initialize" and msg_id is not None:
            self.init, self.init_id = msg, msg_id
        elif method == "notifications/initialized":
            self.initialized = True
        elif msg_id is not None and self.newer() and time.monotonic() >= self.next_ask:
            self.asked += 1
            self.state, self.held, self.deadline = "asking", [raw], time.monotonic() + ASK_SECONDS
            self.to_child(dumps({"jsonrpc": "2.0", "id": f"launch-idle-{self.asked}", "method": IDLE_METHOD}))
            return
        self.to_child(raw)

    @staticmethod
    def is_request(raw, target):
        try:
            msg = json.loads(raw)
        except ValueError:
            return False
        return isinstance(msg, dict) and "method" in msg and target is not None and msg.get("id") == target

    def from_child(self, raw):
        try:
            msg = json.loads(raw)
        except ValueError:
            msg = None
        if not isinstance(msg, dict):
            self.to_client(raw)
            return
        msg_id = msg.get("id")
        if isinstance(msg_id, str) and msg_id.startswith("launch-"):
            self.own_answer(msg)
            return
        if "method" in msg and msg_id is not None:  # the server asks Claude Code (roots/list)
            given = f"launch{self.gen}-{msg_id}"
            self.open[given] = (self.gen, msg_id)
            self.to_client(dumps({**msg, "id": given}))
            return
        if msg_id is not None and msg_id == self.init_id and self.gen == 1 and isinstance(msg.get("result"), dict):
            # This launcher tells Claude Code when the tools may have changed (a new server).
            caps = msg["result"].setdefault("capabilities", {})
            if isinstance(caps, dict) and isinstance(caps.get("tools", {}), dict):
                caps["tools"] = {**caps.get("tools", {}), "listChanged": True}
                self.to_client(dumps(msg))
                return
        self.to_client(raw)

    def own_answer(self, msg):
        if self.state == "asking" and msg.get("id") == f"launch-idle-{self.asked}":
            result = msg.get("result") if isinstance(msg.get("result"), dict) else {}
            if result.get("idle") is True:
                self.switch()
                return
            self.resume()
            error = msg.get("error") if isinstance(msg.get("error"), dict) else {}
            if error.get("code") == -32601:  # a server from before nouez/idle: never asked again
                log("this nouez can't say when it is idle; it stays until the session ends")
                self.next_ask = float("inf")
        elif self.state == "replaying" and msg.get("id") == f"launch-init-{self.gen}":
            if "result" not in msg:
                self.fail(f"it refused initialize: {msg.get('error')}")
                return
            if self.initialized:
                self.to_child(dumps({"jsonrpc": "2.0", "method": "notifications/initialized"}))
            self.finish()

    def resume(self):
        """Not idle: what was held goes to the running server, and the question waits ASK_EVERY."""
        self.state, held, self.held = "normal", self.held, []
        self.next_ask = time.monotonic() + ASK_EVERY
        for raw in held:
            self.from_client(raw)

    def switch(self):
        old = self.child
        self.stop(old)
        self.open = {k: v for k, v in self.open.items() if v[0] != self.gen}
        before = self.version
        self.start()
        log(f"moved this session from nouez {'.'.join(map(str, before or ()))} to "
            f"{'.'.join(map(str, self.version or ()))}")
        if self.init is None:  # a 2026-07-28 client: each request carries what initialize would
            self.finish()
            return
        self.state, self.deadline = "replaying", time.monotonic() + REPLAY_SECONDS
        self.to_child(dumps({**self.init, "id": f"launch-init-{self.gen}"}))

    def finish(self):
        self.state, held, self.held = "normal", self.held, []
        for raw in held:
            self.from_client(raw)
        if self.init is not None:
            self.to_client(dumps({"jsonrpc": "2.0", "method": "notifications/tools/list_changed"}))

    def fail(self, why):
        """The new server can't take the session: each request held is answered with an error that
        says to reconnect, the server is ended, and so is this launcher (Claude Code then shows nouez
        as failed, and /mcp starts it again)."""
        log(f"couldn't move this session to nouez {'.'.join(map(str, self.version or ()))}: {why}")
        text = f"nouez couldn't start its new version ({why}); reconnect it with /mcp."
        for raw in self.held:
            try:
                msg = json.loads(raw)
            except ValueError:
                continue
            if isinstance(msg, dict) and msg.get("method") and msg.get("id") is not None:
                self.to_client(dumps({"jsonrpc": "2.0", "id": msg["id"], "error": {"code": -32603, "message": text}}))
        self.held, self.state = [], "failed"
        self.stop(self.child)
        self.code = 1

    def stop(self, proc):
        """Close the server's input, so it ends as when Claude Code closes it; end it if it doesn't."""
        try:
            proc.stdin.close()
        except OSError:
            pass
        try:
            return proc.wait(STOP_SECONDS)
        except subprocess.TimeoutExpired:
            proc.kill()
            return proc.wait()


def main(argv):
    if sys.version_info < (3, 9):
        log(f"nouez needs Python 3.9 or newer; `py -3` found {sys.version.split()[0]}.")
        return 1
    if len(argv) != 1:
        log("usage: launch.py <the plugin's data folder>")
        return 2
    root = os.path.dirname(os.path.abspath(__file__))
    data = os.path.abspath(argv[0])
    try:
        script = install(root, data)
    except LinkRefused as e:
        log(f"nouez doesn't start: {e}, and nouez neither writes nor runs anything through a link")
        return 1
    except OSError as e:
        log(f"couldn't put nouez in {data}: {e}")
        script = os.path.join(data, "app", "server.py")
        if version_of(read_bytes(script)) is None:
            return 1
        log("running the copy already there")
    return Proxy(script).run()


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
