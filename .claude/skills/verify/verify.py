"""Verify a nouez change: cheap static checks on the diff, then nouez run for real.

    python -I .claude/skills/verify/verify.py static     checks on the working tree, a few seconds
    python -I .claude/skills/verify/verify.py live       doctor, MCP handshake, a real consultant
    python -I .claude/skills/verify/verify.py live --sessions
                                                         also opens, closes and resumes a real
                                                         Claude Code session (opens a window)

Exit code 0 when every check passed, 1 otherwise. The live checks start server.py from this
working copy, so they test the code on disk, not the server Claude Code has loaded. What they
start is stopped or closed again, also when a check fails: the consultant, found by this run's
title if its start failed, and each nouez-verify session running up to 60s after the last open.
A session that registers later still is left running; a later run refuses to start once it shows.
"""
import ast
import json
import os
import re
import subprocess
import sys
import threading
import time

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
SERVER = os.path.join(ROOT, "server.py")
SESSION_NAME = "nouez-verify"
CONNECTED = "Checked: it is running and connected to Remote Control."
failures = []


def report(ok, what, detail=""):
    print(("[ok]   " if ok else "[FAIL] ") + what + (f": {detail}" if detail else ""), flush=True)
    if not ok:
        failures.append(what)
    return ok


def git(*args):
    return subprocess.run(["git", "-C", ROOT, *args], capture_output=True, text=True,
                          encoding="utf-8").stdout


def read(name):
    with open(os.path.join(ROOT, name), encoding="utf-8") as f:
        return f.read()


# ---------------------------------------------------------------- static checks

def changed_files():
    """Tracked files that differ from HEAD, plus untracked ones. -z: names with spaces or
    non-ASCII characters come through unquoted."""
    names = git("diff", "--name-only", "-z", "HEAD").split("\0") \
        + git("ls-files", "-z", "--others", "--exclude-standard").split("\0")
    return sorted({n for n in names if n and os.path.isfile(os.path.join(ROOT, n))})


def check_shadowing(files):
    """Two top-level definitions with one name: the later silently replaces the earlier."""
    bad = []
    for name in files:
        if not name.endswith(".py"):
            continue
        try:
            tree = ast.parse(read(name))
        except SyntaxError as e:
            bad.append(f"{name} doesn't parse: {e}")
            continue
        seen = {}
        for node in tree.body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                if node.name in seen:
                    bad.append(f"{name}: {node.name} defined at lines {seen[node.name]} and {node.lineno}")
                seen.setdefault(node.name, node.lineno)
    report(not bad, "no top-level name defined twice", "; ".join(bad))


def strip_comments(text):
    """The text as TeX reads it: from an unescaped % to the end of the line dropped, lines kept."""
    out, i = [], 0
    while i < len(text):
        c = text[i]
        if c == "\\":
            out.append(text[i:i + 2])
            i += 2
        elif c == "%":
            end = text.find("\n", i)
            i = len(text) if end < 0 else end
        else:
            out.append(c)
            i += 1
    return "".join(out)


def code_spans(text):
    """(line, content) of each \\code{...}: braces balanced, across lines, comments left out. One
    pass reads a backslash with what follows, so \\\\code (a line break, then the word) isn't one."""
    text = strip_comments(text)
    i = 0
    while i < len(text):
        m = re.compile(r"\\(?:code\s*\{|[A-Za-z]+|.)", re.S).match(text, i)
        if not m:
            i += 1
            continue
        i = m.end()
        if not m.group().startswith("\\code") or not m.group().endswith("{"):
            continue
        depth, content = 1, []
        while i < len(text) and depth:
            c = text[i]
            if c == "\\":
                content.append(text[i:i + 2])
                i += 2
                continue
            depth += {"{": 1, "}": -1}.get(c, 0)
            if depth:
                content.append(c)
            i += 1
        yield text.count("\n", 0, m.start()) + 1, "".join(content)


def check_tex(files):
    """TeX turns -- into an en dash, so \\code{--flag} prints as -flag; write \\code{-{}-flag}."""
    bad = [f"{name}:{line}" for name in files if name.endswith(".tex")
           for line, span in code_spans(read(name)) if "--" in span]
    report(not bad, "no -- inside \\code{} in TeX", ", ".join(bad))
    if "docs/architecture.tex" in files:
        # Only a hint that it was rebuilt: the PDF must differ from HEAD's and be no older than the
        # source. Whether it shows the new text is for a person (or Claude) to look at.
        changed = "docs/architecture.pdf" in files
        newer = os.path.getmtime(os.path.join(ROOT, "docs", "architecture.pdf")) >= \
            os.path.getmtime(os.path.join(ROOT, "docs", "architecture.tex"))
        report(changed and newer, "architecture.pdf rebuilt after architecture.tex",
               "" if changed and newer else "run pdflatex twice in docs/, then look at the changed pages")


def check_versions(files):
    version = re.search(r'^SERVER_VERSION = "([^"]+)"', read("server.py"), re.M).group(1)
    tag = git("describe", "--tags", "--abbrev=0").strip()
    if "server.py" in files and tag == f"v{version}":
        report(False, "version bumped", f"server.py changed but SERVER_VERSION is still {version}, the latest tag")
        return
    changelog = read("CHANGELOG.md")
    if f"## [{version}]" not in changelog:
        report(True, "version", f"{version} not released yet; docs are checked once CHANGELOG has its section")
        return
    v = re.escape(version)
    bad = [where for where, ok in (
        ("README Tested with", f"| nouez | {version} |" in read("README.md")),
        ("architecture.tex title", f"nouez}} {version}" in read("docs/architecture.tex")),
        ("CHANGELOG Unreleased link", re.search(rf"^\[Unreleased\]: \S+/compare/v{v}\.\.\.HEAD\s*$", changelog, re.M)),
        ("CHANGELOG version link", re.search(rf"^\[{v}\]: \S+/compare/v\S+\.\.\.v{v}\s*$", changelog, re.M)),
    ) if not ok]
    report(not bad, f"version {version} everywhere", "missing in " + ", ".join(bad) if bad else "")


def static():
    files = changed_files()
    print(f"{len(files)} changed file(s): {', '.join(files) or 'none'}")
    check_shadowing(files)
    check_tex(files)
    check_versions(files)


# ---------------------------------------------------------------- live checks

class Client:
    """A minimal MCP client over stdio, for server.py from this working copy."""

    def __init__(self):
        self.proc = subprocess.Popen([sys.executable, SERVER], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                     stderr=subprocess.DEVNULL, text=True, encoding="utf-8", cwd=ROOT,
                                     env={**os.environ, "NOUEZ_NO_USAGE_LOG": "1"})  # checks aren't usage
        self.next_id, self.replies, self.lock = 0, {}, threading.Condition()
        threading.Thread(target=self._read, daemon=True).start()

    def _read(self):
        for line in self.proc.stdout:
            try:
                msg = json.loads(line)
            except ValueError:
                continue
            if "id" in msg and "method" not in msg:
                with self.lock:
                    self.replies[msg["id"]] = msg
                    self.lock.notify_all()

    def request(self, method, params, timeout=60):
        with self.lock:
            self.next_id += 1
            rid = self.next_id
        self.proc.stdin.write(json.dumps({"jsonrpc": "2.0", "id": rid, "method": method, "params": params}) + "\n")
        self.proc.stdin.flush()
        with self.lock:
            if not self.lock.wait_for(lambda: rid in self.replies, timeout):
                raise TimeoutError(f"{method} had no answer after {timeout}s")
            return self.replies.pop(rid)

    def call(self, tool, timeout=120, **args):
        """A tool's result text, and whether it was an error. A timeout counts as an error."""
        try:
            msg = self.request("tools/call", {"name": tool, "arguments": args}, timeout)
        except TimeoutError as e:
            return str(e), True
        result = msg.get("result") or {}
        text = "\n".join(c.get("text", "") for c in result.get("content", []))
        return text or json.dumps(msg.get("error")), bool(result.get("isError") or "error" in msg)

    def close(self):
        self.proc.stdin.close()
        try:
            self.proc.wait(10)
        except subprocess.TimeoutExpired:
            self.proc.kill()


def short(text, n=300):
    text = " ".join(text.split())
    return text if len(text) <= n else text[:n] + "..."


def find_consultant(client, title):
    """After a start that failed or timed out: the consultant carrying this run's title, the only
    proof that it is ours. A consultant without it is never guessed at (it may be someone else's);
    StartConsultant keeps the id when naming fails, so an untitled one of ours is unlikely."""
    for _ in range(3):
        text, err = client.call("ListConsultants", cwd=ROOT)
        if not err:
            for block in text.split("\n- "):
                if re.search(rf"^\s*title: {re.escape(title)}\s*$", block, re.M):
                    match = re.search(r"^\s*id: (\S+)", block, re.M)
                    if match:
                        return match.group(1)
        time.sleep(5)
    return None


def check_consultant(client):
    token = time.strftime("verify-%Y%m%d-%H%M%S-") + os.urandom(3).hex()
    title = f"nouez {token}"
    text, err = client.call("StartConsultant", timeout=180, cwd=ROOT, new=True, watch=False, title=title,
                            instructions="You are a test. Answer in one word.")
    match = re.search(r"^\s*id: (\S+)", text, re.M) if text.startswith("Started ") else None
    thread = match.group(1) if match else None
    try:
        if not report(not err and bool(thread), "StartConsultant starts a new consultant", "" if thread else short(text)):
            return
        text, err = client.call("SendConsultantMessage", timeout=400, to=thread, wait="done",
                                message=f"{token}: reply with the single word ok, nothing else.")
        reply = text.split(":", 1)[1].strip() if text.startswith("Reply from ") else ""
        report(not err and re.match(r"ok\b", reply, re.I) is not None, "SendConsultantMessage gets a finished reply",
               short(text, 200))
        text, err = client.call("GetConsultantHistory", to=thread)
        report(not err and token in text, "GetConsultantHistory lists the turn", "" if token in text else short(text))
    finally:
        # A start that failed or timed out may still have made the consultant.
        thread = thread or find_consultant(client, title)
        if thread:
            text, err = client.call("StopConsultant", to=thread)
            report(not err, "StopConsultant stops it", "" if not err else short(text))
        elif err:
            print(f"       No consultant titled {title!r} was found. If ListConsultants shows one this run "
                  "started without a title, stop it; nothing else was stopped.")


def verify_sessions():
    """The running nouez-verify sessions in this repo, as server.py sees them (process identity checked)."""
    sys.path.insert(0, ROOT)
    import server
    return [s for s in server.claude_sessions()
            if s["name"] == SESSION_NAME and server.same_folder(s["cwd"], ROOT)]


def transcript(session_id):
    folder = re.sub(r"[^A-Za-z0-9]", "-", ROOT)
    base = os.environ.get("CLAUDE_CONFIG_DIR") or os.path.expanduser("~/.claude")
    return os.path.join(base, "projects", folder, f"{session_id}.jsonl")


def answered(session_id):
    """Whether the transcript has the answer asked for: an assistant text saying ok. Commentary
    before a tool call ("I'll check that") doesn't count, and neither does thinking."""
    try:
        with open(transcript(session_id), encoding="utf-8") as f:
            for line in f:
                try:
                    entry = json.loads(line)
                except ValueError:
                    continue
                content = (entry.get("message") or {}).get("content") if entry.get("type") == "assistant" else None
                if isinstance(content, list) and any(c.get("type") == "text" and
                                                     re.fullmatch(r"\W*ok\W*", c.get("text", ""), re.I)
                                                     for c in content if isinstance(c, dict)):
                    return True
    except OSError:
        pass
    return False


def wait_for(test, seconds):
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        value = test()
        if value:
            return value
        time.sleep(2)
    return test()


LATE_START_SECONDS = 60  # how long after an open this keeps watching for a slow session to show up
last_open = [0.0]


def close_verify_sessions(client):
    """Close every nouez-verify session, and keep watching for LATE_START_SECONDS after the last open
    for one that starts late. That bounds the wait; it doesn't prove no later start: nothing ties a
    window to the session it will become. A session registering later still is left running; a
    later run refuses to start if it has registered by then."""
    closed = set()
    while True:
        for s in verify_sessions():
            if s["pid"] not in closed:
                text, err = client.call("CloseClaudeSession", pid=s["pid"])
                report(not err, f"CloseClaudeSession closes pid {s['pid']}", "" if not err else short(text))
                closed.add(s["pid"])
        if time.monotonic() >= last_open[0] + LATE_START_SECONDS:
            break
        time.sleep(2)
    return report(bool(wait_for(lambda: not verify_sessions(), 30)),
                  f"no nouez-verify session runs {LATE_START_SECONDS}s after the last open")


def open_and_check(client, what, **args):
    """Open a session; return its registry entry once it runs connected to Remote Control."""
    last_open[0] = time.monotonic()
    text, err = client.call("OpenClaudeSession", timeout=90, cwd=ROOT, name=SESSION_NAME,
                            model="haiku", effort="low", **args)
    last_open[0] = time.monotonic()
    report(not err and CONNECTED in text, f"OpenClaudeSession {what} and connects", short(text, 200))
    found = wait_for(verify_sessions, 30)
    entry = found[0] if found and len(found) == 1 else None
    report(entry is not None and entry["remote"], f"the session it {what.split()[0]} runs with Remote Control",
           f"{len(found or [])} running")
    return entry


def check_sessions(client):
    if verify_sessions():
        report(False, "session checks", f"a session named {SESSION_NAME} already runs here; close it first")
        return
    try:
        entry = open_and_check(client, "opens a session", prompt="Reply with the single word ok.")
        sid = entry and entry["session_id"]
        if not sid:
            return
        if not report(wait_for(lambda: answered(sid), 120), "the session answered its first prompt", sid):
            return
        if not close_verify_sessions(client):
            return
        entry = open_and_check(client, "resumes it", resume=sid)
        report(entry is not None and entry["session_id"] == sid, "the resumed session keeps its id",
               f"{sid} -> {entry and entry['session_id']}")
    finally:
        close_verify_sessions(client)


def live(sessions):
    doctor = subprocess.run([sys.executable, SERVER, "doctor"], capture_output=True, text=True, encoding="utf-8", cwd=ROOT)
    report(doctor.returncode == 0, "server.py doctor",
           "" if doctor.returncode == 0 else short(doctor.stdout + doctor.stderr, 600))
    client = Client()
    try:
        init = client.request("initialize", {"protocolVersion": "2025-06-18", "capabilities": {},
                                             "clientInfo": {"name": "nouez-verify", "version": "1"}})
        version = (init.get("result") or {}).get("serverInfo", {}).get("version")
        report(bool(version), "initialize", f"nouez {version}")
        client.proc.stdin.write(json.dumps({"jsonrpc": "2.0", "method": "notifications/initialized"}) + "\n")
        client.proc.stdin.flush()
        tools = {t["name"] for t in client.request("tools/list", {})["result"]["tools"]}
        expected = {"StartConsultant", "ListConsultants", "SendConsultantMessage", "GetConsultantReply",
                    "GetConsultantHistory", "WatchConsultant", "StopConsultant", "OpenClaudeSession",
                    "ListClaudeSessions", "CloseClaudeSession"}
        report(expected <= tools, "tools/list has every tool", ", ".join(sorted(expected - tools)))
        check_consultant(client)
        if sessions:
            check_sessions(client)
    finally:
        client.close()


if __name__ == "__main__":
    mode = sys.argv[1:2]
    if mode == ["static"]:
        static()
    elif mode == ["live"]:
        live("--sessions" in sys.argv[2:])
    else:
        sys.exit(__doc__)
    print(f"\n{'All checks passed.' if not failures else f'{len(failures)} check(s) failed.'}")
    sys.exit(1 if failures else 0)
