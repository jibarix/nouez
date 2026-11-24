"""Verify a nouez change: cheap static checks on the diff, then nouez run for real.

    python -I .claude/skills/verify/verify.py static     checks on the working tree, a few seconds
    python -I .claude/skills/verify/verify.py static --range BASE..HEAD
                                                         the same checks on the commits in a range
                                                         (CI: a push or a pull request)
    python -I .claude/skills/verify/verify.py live       doctor, MCP handshake, a real consultant
    python -I .claude/skills/verify/verify.py live --sessions
                                                         also opens, closes and resumes a real
                                                         Claude Code session (opens a window)
    python -I .claude/skills/verify/verify.py live --setups
                                                         also runs nouez as a newcomer would in
                                                         each setup: Codex only, Antigravity only,
                                                         both, neither (empty cache, the other CLI
                                                         hidden; one short Antigravity message)

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

RANGE = None  # "BASE..HEAD" with --range: the checks look at those commits, not the working tree


def changed_files():
    """Tracked files that differ from HEAD, plus untracked ones; with --range, the files the
    range's commits change. -z: names with spaces or non-ASCII characters come through unquoted."""
    if RANGE:
        done = subprocess.run(["git", "-C", ROOT, "diff", "--name-only", "-z", RANGE], capture_output=True,
                              text=True, encoding="utf-8")
        if done.returncode:
            sys.exit(f"git diff {RANGE} failed, so the range can't be checked: {done.stderr.strip()}")
        names = done.stdout.split("\0")
    else:
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


FUNCTIONS = (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)
COMPREHENSIONS = (ast.ListComp, ast.SetComp, ast.GeneratorExp, ast.DictComp)
TYPE_ALIASES = tuple(filter(None, [getattr(ast, "TypeAlias", None)]))  # `type X = ...`, Python 3.12+


def arguments(fn):
    a = fn.args
    return [*a.posonlyargs, *a.args, *a.kwonlyargs, *filter(None, [a.vararg, a.kwarg])]


def annotations(fn):
    """A function's parameter and return annotations (a lambda has none)."""
    if isinstance(fn, ast.Lambda):
        return []
    return [*filter(None, [x.annotation for x in arguments(fn)] + [fn.returns])]


def mangle(name, cls):
    """`name` as Python spells it inside class `cls`: a private __name there is _cls__name."""
    if cls and cls.strip("_") and name.startswith("__") and not name.endswith("__"):
        return f"_{cls.lstrip('_')}{name}"
    return name


def evaluated_around(node):
    """The parts of a nested function or class that run in the scope around it: decorators and
    defaults, or decorators, bases and keywords."""
    if isinstance(node, FUNCTIONS):
        a = node.args
        return [*getattr(node, "decorator_list", []), *a.defaults, *filter(None, a.kw_defaults)]
    return [*node.decorator_list, *node.bases, *node.keywords]


def type_params(node):
    """A generic function's, class's or type alias's type parameters (Python 3.12+), the scope they
    make around it, and the bounds and defaults read in that scope."""
    params = getattr(node, "type_params", None) or []
    parts = [x for t in params for x in (getattr(t, "bound", None), getattr(t, "default_value", None)) if x]
    return params, parts


def bindings(body, cls=None):
    """(how, name) for each name the statements `body` bind in their own scope, `how` being "bind",
    "del", "global" or "nonlocal". What a nested function, class or comprehension binds is its own,
    but a walrus in a comprehension, a default or a base binds here."""
    stack = list(body)
    while stack:
        node = stack.pop()
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            yield "bind", mangle(node.name, cls)
        if isinstance(node, (*FUNCTIONS, ast.ClassDef)):
            stack += evaluated_around(node)
            continue
        if isinstance(node, TYPE_ALIASES):
            yield "bind", mangle(node.name.id, cls)
            continue
        if isinstance(node, ast.comprehension):
            stack += [node.iter, *node.ifs]  # not its target: that is the comprehension's own
            continue
        if isinstance(node, ast.Name) and isinstance(node.ctx, (ast.Store, ast.Del)):
            yield ("del" if isinstance(node.ctx, ast.Del) else "bind"), mangle(node.id, cls)
        elif isinstance(node, (ast.Import, ast.ImportFrom)):
            for x in node.names:
                yield "bind", mangle((x.asname or x.name).split(".")[0], cls)
        elif isinstance(node, (ast.Global, ast.Nonlocal)):
            for n in node.names:
                yield type(node).__name__.lower(), mangle(n, cls)
        elif not isinstance(node, ast.alias):
            for field in ("name", "rest"):  # except E as x, and the names a match pattern captures
                if isinstance(getattr(node, field, None), str):
                    yield "bind", mangle(getattr(node, field), cls)
        stack += ast.iter_child_nodes(node)


def function_scope(body, params, cls):
    """A function's scope (kind, locals, globals): its parameters and what its body binds, less
    what it declares global or nonlocal, and the names it declares global."""
    found = list(bindings(body, cls))
    declared = {n for how, n in found if how in ("global", "nonlocal")}
    names = {mangle(p, cls) for p in params} | {n for how, n in found if how in ("bind", "del")}
    return "function", names - declared, {n for how, n in found if how == "global"}


def always_binds(stmt, cls):
    """The names a class-body statement binds whenever it runs: its targets, its def or class name,
    or what it imports; not a walrus inside it, which may not run."""
    if isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
        return {mangle(stmt.name, cls)}
    if isinstance(stmt, (ast.Import, ast.ImportFrom)):
        return {mangle((x.asname or x.name).split(".")[0], cls) for x in stmt.names}
    targets = stmt.targets if isinstance(stmt, ast.Assign) else [stmt.target] \
        if isinstance(stmt, ast.AugAssign) or isinstance(stmt, ast.AnnAssign) and stmt.value else []
    return {mangle(n.id, cls) for t in targets for n in ast.walk(t)
            if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Store)}


def reads_module(name, chain):
    """Whether a load of `name` in the innermost scope of `chain` reads the module's `name`. A class
    body's names are seen in that body and in the type-parameter scopes directly in it, not in its
    methods or comprehensions. Code a class runs later, such as a type alias's value, may find the
    class's name deleted by then and read the module's, so that counts as a module read too."""
    visible, later = True, False
    for kind, names, glob in reversed(chain):
        if kind == "class" and not visible:
            continue
        if kind == "module" or name in glob:
            return True
        if name in names:
            return kind == "class" and later
        visible = visible and kind in ("annotation", "later")
        later = later or kind == "later"
    return True


def module_reads(node, chain, found, cls=None):
    """Add to `found` the module-level names that `node`, in the scopes `chain` and inside class
    `cls`, reads or deletes."""
    params, parts = type_params(node)
    typed = chain + [("annotation", {mangle(t.name, cls) for t in params}, set())] if params else chain
    later = typed + [("later", set(), set())]  # bounds, defaults and an alias's value run when first used
    if isinstance(node, FUNCTIONS):
        body = node.body if isinstance(node.body, list) else [node.body]
        inner = typed + [function_scope(body, [x.arg for x in arguments(node)], cls)]
        triples = [(x, chain, cls) for x in evaluated_around(node)] + [(x, later, cls) for x in parts] \
            + [(x, typed, cls) for x in annotations(node)] + [(x, inner, cls) for x in body]
    elif isinstance(node, ast.ClassDef):
        triples = [(x, chain, cls) for x in node.decorator_list] + [(x, later, cls) for x in parts] \
            + [(x, typed, cls) for x in [*node.bases, *node.keywords]]
        # A class body reads its own name only once a statement has surely bound it. A name it binds,
        # deletes or declares global anywhere is otherwise looked up in the module, skipping the
        # functions around the class; one it declares nonlocal is theirs.
        found_here = list(bindings(node.body, node.name))
        unsure = {n for how, n in found_here if how != "bind"}
        to_module = {n for how, n in found_here if how != "nonlocal"} - {n for how, n in found_here if how == "nonlocal"}
        bound = set()
        for stmt in node.body:
            triples.append((stmt, typed + [("class", set(bound), to_module - bound)], node.name))
            bound |= always_binds(stmt, node.name) - unsure
    elif isinstance(node, TYPE_ALIASES):
        triples = [(x, later, cls) for x in [*parts, node.value]]
    elif isinstance(node, COMPREHENSIONS):
        gens = node.generators
        targets = {mangle(n.id, cls) for g in gens for n in ast.walk(g.target)
                   if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Store)}  # D[i] reads D and i
        elts = [node.key, node.value] if isinstance(node, ast.DictComp) else [node.elt]
        inner = chain + [("comprehension", targets, set())]  # a walrus binds in the scope around it
        # the first loop's source is read around the comprehension, the rest inside it
        triples = [(gens[0].iter, chain, cls)] + [(x, inner, cls) for g in gens for x in [g.target, *g.ifs]] \
            + [(g.iter, inner, cls) for g in gens[1:]] + [(x, inner, cls) for x in elts]
    else:
        # a del needs the name as much as a read; X += 1 reads X, though its target is a store
        name = node if isinstance(node, ast.Name) and isinstance(node.ctx, (ast.Load, ast.Del)) else \
            node.target if isinstance(node, ast.AugAssign) and isinstance(node.target, ast.Name) else None
        if name is not None and reads_module(mangle(name.id, cls), chain):
            found.add(mangle(name.id, cls))
        triples = [(x, chain, cls) for x in ast.iter_child_nodes(node)]
    for child, where, inside in triples:
        module_reads(child, where, found, inside)


def unused_names(source):
    """(line, name) for each top-level function, class or constant in `source` that nothing else in
    it reads. A top-level function or class that only refers to itself counts as unused, but its
    decorators, defaults, bases and annotations run before it binds its name, so they read the one
    before."""
    tree = ast.parse(source)
    defined = {}
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            defined.setdefault(node.name, node.lineno)
        elif isinstance(node, (ast.Assign, ast.AnnAssign, *TYPE_ALIASES)):
            targets = node.targets if isinstance(node, ast.Assign) else [getattr(node, "target", None) or node.name]
            for target in targets:
                for n in ast.walk(target):  # A, B = 1, 2 defines both
                    if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Store):
                        defined.setdefault(n.id, node.lineno)
    module = [("module", set(), set())]
    used = set()
    for node in tree.body:
        found = set()
        module_reads(node, module, found)
        if isinstance(node, (*FUNCTIONS, ast.ClassDef)):
            params, _ = type_params(node)
            typed = module + [("annotation", {t.name for t in params}, set())] if params else module
            early = annotations(node) if isinstance(node, FUNCTIONS) else [*node.bases, *node.keywords]
            before = set()
            for x, where in [(x, module) for x in evaluated_around(node) if x not in early] + [(x, typed) for x in early]:
                module_reads(x, where, before)
            found = found - {node.name} | before
        used |= found
    return sorted((line, n) for n, line in defined.items()
                  if n not in used and not (n.startswith("__") and n.endswith("__")))


def check_unused(files):
    """A top-level function, class or constant that nothing else in its own file uses: dead, or
    kept only for the tests, which should then test what the code really calls. Code that reads a
    name only through globals() or a string isn't seen."""
    bad = []
    for name in files:
        if not name.endswith(".py") or name.startswith("tests/"):
            continue
        try:
            bad += [f"{name}:{line} {n}" for line, n in unused_names(read(name))]
        except SyntaxError:
            continue  # check_shadowing reports it
    report(not bad, "no top-level name left unused", "; ".join(bad))


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
        # A checkout gives every file the same time, so in a range only "changed too" counts.
        newer = RANGE or os.path.getmtime(os.path.join(ROOT, "docs", "architecture.pdf")) >= \
            os.path.getmtime(os.path.join(ROOT, "docs", "architecture.tex"))
        report(changed and newer, "architecture.pdf rebuilt after architecture.tex",
               "" if changed and newer else "run pdflatex twice in docs/, then look at the changed pages")


def check_versions(files):
    version = re.search(r'^SERVER_VERSION = "([^"]+)"', read("server.py"), re.M).group(1)
    # The latest tag before the change: with a range, at its base, so a release commit that is
    # itself tagged isn't taken for a change without a new version.
    base = RANGE.split("..")[0] if RANGE else "HEAD"
    tag = git("describe", "--tags", "--abbrev=0", "--match", "v*", base).strip()
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
    print(f"{len(files)} changed file(s){' in ' + RANGE if RANGE else ''}: {', '.join(files) or 'none'}")
    check_shadowing(files)
    check_unused(files)
    check_tex(files)
    check_versions(files)


# ---------------------------------------------------------------- live checks

class Client:
    """A minimal MCP client over stdio, for server.py from this working copy."""

    def __init__(self, env=None, cwd=ROOT):
        self.proc = subprocess.Popen([sys.executable, "-I", SERVER], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                     stderr=subprocess.DEVNULL, text=True, encoding="utf-8", cwd=cwd,
                                     env=env or {**os.environ, "NOUEZ_NO_USAGE_LOG": "1"})  # checks aren't usage
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


def installed_clis():
    """(Codex, Antigravity) as server.py sees them here."""
    sys.path.insert(0, ROOT)
    import server
    return server.codex_installed(), bool(server.agy_command())


def check_consultant(client):
    token = time.strftime("verify-%Y%m%d-%H%M%S-") + os.urandom(3).hex()
    title = f"nouez {token}"
    codex, agy = installed_clis()
    text, err = client.call("StartConsultant", timeout=180, cwd=ROOT, new=True, watch=False, title=title,
                            instructions="You are a test. Answer in one word.")
    if not codex and not agy:  # Claude Code only: no consultant, and a plain message saying so
        report(err and "No consultant CLI is installed" in text,
               "StartConsultant says no consultant CLI is installed (neither is here)", short(text))
        return
    match = re.search(r"^\s*id: (\S+)", text, re.M) if "Started " in text else None
    thread = match.group(1) if match else None
    provider = "Codex" if codex else "Antigravity"
    try:
        if not report(not err and bool(thread) and (codex or "so this is an Antigravity consultant" in text),
                      f"StartConsultant starts a new {provider} consultant", "" if thread else short(text)):
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


EXPECTED_TOOLS = {"StartConsultant", "ListConsultants", "SendConsultantMessage", "GetConsultantReply",
                  "GetConsultantHistory", "WatchConsultant", "StopConsultant", "ConsultantBudget",
                  "OpenClaudeSession", "ListClaudeSessions", "CloseClaudeSession", "ListProjects",
                  "OpenStatusScreen"}


def live(sessions, setups=False):
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
        report(EXPECTED_TOOLS <= tools, "tools/list has every tool", ", ".join(sorted(EXPECTED_TOOLS - tools)))
        check_consultant(client)
        if sessions:
            check_sessions(client)
    finally:
        client.close()
    if setups:
        check_setups()


# ---------------------------------------------------------------- setups

PROGRAM_EXTS = ("", ".exe", ".cmd", ".bat", ".ps1", ".com")


def path_folders(value):
    """PATH's folders as server.py's which() reads them: empty entries dropped, quotes stripped."""
    return [d.strip().strip('"') for d in (value or "").split(os.pathsep) if d.strip().strip('"')]


def program_files(folder, name):
    return [f for f in (os.path.join(folder, name + e) for e in PROGRAM_EXTS) if os.path.isfile(f)]


def link_program(source, target):
    """Windows: the program itself in the mirror, so its arguments reach it as they are: a hard
    link, else a symbolic one, else a copy. None if none of them works."""
    import shutil
    for make in (os.link, os.symlink, shutil.copy2):
        try:
            make(source, target)
            return target
        except OSError:
            continue
    return None


def mirror_without(folder, hidden, into):
    """A folder with every program of `folder` except `hidden`: symlinks on macOS and Linux,
    one-line .cmd wrappers on Windows (a copied npm shim would look for its files beside the copy)."""
    os.makedirs(into, exist_ok=True)
    try:
        names = os.listdir(folder)
    except OSError:
        return into
    for name in names:
        stem, ext = os.path.splitext(name)
        source = os.path.join(folder, name)
        if (stem.lower() if os.name == "nt" else name) in hidden or not os.path.isfile(source):
            continue
        if os.name == "nt":
            target = os.path.join(into, name)
            # Native programs as themselves: a .cmd wrapper would pass their arguments through
            # cmd's parsing. Scripts keep a wrapper, since a copied npm shim looks for its files
            # beside itself.
            if ext.lower() in (".exe", ".com") and link_program(source, target):
                continue
            if ext.lower() in (".exe", ".cmd", ".bat", ".com") and not os.path.exists(os.path.join(into, stem + ".cmd")):
                with open(os.path.join(into, stem + ".cmd"), "w") as f:
                    f.write(f'@"{source}" %*\n')
        elif os.access(source, os.X_OK):
            os.symlink(source, os.path.join(into, name))
    return into


def setup_env(codex, agy, scratch):
    """The environment of a newcomer's setup: an empty nouez cache (and Codex home without Codex),
    and Codex or agy hidden, program by program, where a setup leaves it out."""
    env = {k: v for k, v in os.environ.items() if not k.startswith("NOUEZ_") or k == "NOUEZ_NO_UPDATE_CHECK"}
    env["NOUEZ_NO_USAGE_LOG"] = "1"
    hidden = {name for name, keep in (("codex", codex), ("agy", agy), ("antigravity", agy)) if not keep}
    real_agy_bin = os.path.join(os.environ.get("LOCALAPPDATA", ""), "agy", "bin")
    folders = []
    for i, folder in enumerate(path_folders(env.get("PATH"))):
        if any(program_files(folder, n) for n in hidden):
            folder = mirror_without(folder, hidden, os.path.join(scratch, f"path-{i}"))
        folders.append(folder)
    if os.name == "nt":
        env["LOCALAPPDATA"] = os.path.join(scratch, "localappdata")  # also hides agy's installer folder
        os.makedirs(env["LOCALAPPDATA"])
        if agy and not any(program_files(f, "agy") for f in folders) and os.path.isdir(real_agy_bin):
            if any(program_files(real_agy_bin, n) for n in hidden):
                real_agy_bin = mirror_without(real_agy_bin, hidden, os.path.join(scratch, "agy-bin"))
            folders.append(real_agy_bin)
    else:
        env["XDG_CACHE_HOME"] = os.path.join(scratch, "cache")
    if not codex:
        env["CODEX_HOME"] = os.path.join(scratch, "codex-home")
        os.makedirs(env["CODEX_HOME"])
    env["PATH"] = os.pathsep.join(folders)
    return env


def check_setup(label, codex, agy):
    import shutil
    import tempfile
    print(f"\n--- {label}")
    scratch = tempfile.mkdtemp(prefix="nouez-setup-")
    env = setup_env(codex, agy, scratch)
    cwd = os.path.join(scratch, "project")
    os.makedirs(cwd)
    started = []
    try:
        doctor = subprocess.run([sys.executable, "-I", SERVER, "doctor"], capture_output=True, text=True,
                                encoding="utf-8", errors="replace", cwd=cwd, env=env, timeout=300)
        out = doctor.stdout + doctor.stderr
        want = {"Codex": ("codex CLI " if codex else "Codex isn't installed"),
                "agy": ("agy is signed in" if agy else "Antigravity isn't installed")}
        missing = [w for w in want.values() if w not in out]
        if not codex and not agy and "no consultant CLI is installed" not in out:
            missing.append("no consultant CLI is installed")
        report(doctor.returncode == 0 and not missing, f"{label}: doctor exits 0 and reports each CLI",
               short(out, 600) if doctor.returncode or missing else "")
        top = subprocess.run([sys.executable, "-I", SERVER, "top", "--once"], capture_output=True, text=True,
                             encoding="utf-8", errors="replace", cwd=cwd, env={**env, "PYTHONIOENCODING": "utf-8"},
                             timeout=180)
        sections = [name for name, want in (("Codex", codex), ("Antigravity", agy)) if want and name not in top.stdout]
        report(top.returncode == 0 and "nouez" in top.stdout and not sections,
               f"{label}: top --once draws the screen with each installed CLI",
               ("missing: " + ", ".join(sections) + ". " if sections else "")
               + ("" if top.returncode == 0 and not sections else short(top.stdout + top.stderr)))
        client = Client(env=env, cwd=cwd)
        try:
            client.request("initialize", {"protocolVersion": "2025-06-18", "capabilities": {},
                                          "clientInfo": {"name": "nouez-verify", "version": "1"}})
            client.proc.stdin.write(json.dumps({"jsonrpc": "2.0", "method": "notifications/initialized"}) + "\n")
            client.proc.stdin.flush()
            tools = {t["name"] for t in client.request("tools/list", {})["result"]["tools"]}
            report(EXPECTED_TOOLS <= tools, f"{label}: tools/list has every tool", ", ".join(sorted(EXPECTED_TOOLS - tools)))
            text, err = client.call("ListConsultants", cwd=cwd)
            report(not err and (codex or "No consultants" in text), f"{label}: ListConsultants before any start",
                   short(text))
            text, err = client.call("ConsultantBudget", timeout=180)
            quota = [what for what, ok in (
                ("Codex usage", not codex or (re.search(r"^Codex( \(.+ plan\))?:\s*$", text, re.M) is not None
                                              and "Codex: not installed" not in text and "usage unavailable" not in text)),
                ("Codex: not installed", codex or "Codex: not installed" in text),
                ("Antigravity quota", not agy or ("Antigravity" in text and "usage not known" not in text)),
            ) if not ok]
            report(not err and not quota, f"{label}: ConsultantBudget shows each installed CLI's usage",
                   ("missing: " + ", ".join(quota) + ". " if quota else "") + (short(text, 300) if err or quota else ""))
            text, err = client.call("ListClaudeSessions")
            report(not err, f"{label}: ListClaudeSessions", short(text) if err else "")

            def start(**args):
                """(text, err, provider): provider is "Codex" or "Antigravity" for a start with an id."""
                text, err = client.call("StartConsultant", timeout=240, cwd=cwd, new=True, watch=False,
                                        title=f"nouez verify {label}", **args)
                match = re.search(r"^\s*id: (\S+)", text, re.M)
                model = re.search(r"^\s*model: .*\((.+)\)\s*$", text, re.M)
                provider = None
                if not err and match and "Started " in text:
                    provider = "Antigravity" if model and model.group(1) == "Antigravity" else "Codex"
                    started.append((match.group(1), provider))
                return text, err, provider
            text, err, provider = start()
            expected = "Codex" if codex else "Antigravity" if agy else None
            report(provider == expected, f"{label}: StartConsultant without provider gives "
                   + (f"a {expected} consultant with an id" if expected else "no consultant"),
                   "" if provider == expected else short(text))
            if codex:
                report(not err and "codex" in text.lower() and "Antigravity" not in text.split("\n")[0],
                       f"{label}: StartConsultant without provider starts Codex", short(text) if err else "")
            elif agy:
                report(not err and text.startswith("Codex isn't installed, so this is an Antigravity consultant"),
                       f"{label}: StartConsultant without provider starts Antigravity", short(text))
            else:
                report(err and "No consultant CLI is installed" in text,
                       f"{label}: StartConsultant without provider says no CLI is installed", short(text))
            text, err, provider = start(provider="antigravity")
            report(provider == "Antigravity" if agy else (err and "isn't installed" in text and not provider),
                   f"{label}: StartConsultant provider antigravity "
                   + ("starts an Antigravity consultant with an id" if agy else "is refused"), short(text))
            if not codex:
                text, err, _ = start(provider="codex")
                report(err and "Codex isn't installed" in text, f"{label}: StartConsultant provider codex is refused",
                       short(text))
            for cid, provider in started:  # every consultant started here answers once
                text, err = client.call("SendConsultantMessage", timeout=600, to=cid, wait="done",
                                        message="Reply with the single word ok, nothing else.",
                                        kind="other", reason=f"verify setups: {label}")
                reply = text.split(":", 1)[1].strip() if text.startswith("Reply from ") else ""
                report(not err and re.match(r"ok\b", reply, re.I) is not None,
                       f"{label}: the {provider} consultant answers", short(text, 200))
        finally:
            for cid, _ in started:
                text, err = client.call("StopConsultant", to=cid)
                report(not err, f"{label}: StopConsultant {cid}", short(text) if err else "")
            client.close()
    finally:
        shutil.rmtree(scratch, ignore_errors=True)


def installed_here(name):
    """Whether a CLI is installed, found without server.py's lookup, so a regression there makes a
    setup check fail rather than skip it: an executable on PATH, or agy where its installer puts it
    on Windows."""
    exts = PROGRAM_EXTS if os.name == "nt" else ("",)
    if any(os.path.isfile(f) and (os.name == "nt" or os.access(f, os.X_OK))
           for d in path_folders(os.environ.get("PATH")) for f in (os.path.join(d, name + e) for e in exts)):
        return True
    local = os.environ.get("LOCALAPPDATA") or ""
    return (name == "agy" and os.name == "nt" and os.path.isabs(local)
            and os.path.isfile(os.path.join(local, "agy", "bin", "agy.exe")))


def check_setups():
    """Each newcomer setup: Codex only, Antigravity only, both, neither."""
    have_codex, have_agy = installed_here("codex"), installed_here("agy")
    for label, codex, agy in (("Codex only", True, False), ("Antigravity only", False, True),
                              ("both", True, True), ("neither", False, False)):
        if (codex and not have_codex) or (agy and not have_agy):
            print(f"\n--- {label}: skipped, " + ("Codex" if codex and not have_codex else "agy") + " isn't installed here")
            continue
        check_setup(label, codex, agy)


if __name__ == "__main__":
    mode, flags = sys.argv[1:2], sys.argv[2:]
    if mode == ["static"] and flags[:1] == ["--range"] and len(flags) == 2:
        RANGE = flags.pop()
        flags.pop()
        if not re.fullmatch(r"[0-9A-Za-z_./^~-]+\.\.[0-9A-Za-z_./^~-]+", RANGE) or RANGE.startswith("-"):
            sys.exit(f"--range takes BASE..HEAD, not {RANGE!r}")
    allowed = {"static": set(), "live": {"--sessions", "--setups"}}.get(mode[0] if mode else "")
    if allowed is None or set(flags) - allowed:
        sys.exit(f"Unknown option(s): {' '.join(sorted(set(flags) - (allowed or set())))}\n{__doc__}"
                 if allowed is not None else __doc__)
    if mode == ["static"]:
        static()
    else:
        live("--sessions" in flags, "--setups" in flags)
    print(f"\n{'All checks passed.' if not failures else f'{len(failures)} check(s) failed.'}")
    sys.exit(1 if failures else 0)
