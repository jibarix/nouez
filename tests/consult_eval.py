"""The consult eval: do fresh Claude Code sessions consult when nouez's instructions say to, and pick
the provider, model and effort ConsultantBudget suggests?

    python tests/consult_eval.py [--reps N] [--cases a,b] [--setup both] [--scenario room]
                                 [--server PATH] [--model ID] [--jobs N] [--keep]

Each run is a new `claude -p` session in a scratch git repo with made-up content, with only this
eval's MCP server connected: the real server.py (or the one --server names, such as an older
version as a baseline), with the consultant CLIs, their usage and the consultations faked. No
Codex or Antigravity turn runs, and nothing of yours is read: your CLAUDE.md files, memory and
skills are left out. It uses your Claude Code subscription, about a minute of a session per run.

A run ends when the first SendConsultantMessage has its result, or at the local action a
consultation should come before (a commit, an edit), or when the session ends. The stub logs the
calls it accepted, in order, and the score reads that log, keeping two things apart:
  - trigger: a send accepted for a consultant StartConsultant returned, where nouez's instructions
    say to consult, and none where they don't (or where no provider has room);
  - choice: for the runs that consulted, the StartConsultant provider and the SendConsultantMessage
    model and effort match what this repo's server.py suggests for the kind Claude gave, and that
    kind fits the case; budget-first: ConsultantBudget was called before StartConsultant.
A run that timed out or ended in an error counts in neither and is listed.
Not a unit test: run it when the instructions about consulting or choosing a model change
(REVIEW.md item 15), against the last release as a baseline (--server).
"""
import argparse
import importlib.util
import json
import os
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import threading
import time
from concurrent.futures import ThreadPoolExecutor

HERE = os.path.dirname(os.path.abspath(__file__))
REPO_SERVER = os.path.join(os.path.dirname(HERE), "server.py")
DAY = 86400
SETUPS = ("both", "codex", "antigravity", "neither")
CALLS = "eval-calls.jsonl"  # the calls the stub accepted, in its cache folder

# --- Canned usage -------------------------------------------------------------------------------
# Each scenario: (Codex weekly %, days to its reset), (Gemini weekly %, Claude and GPT weekly %,
# days to their reset), (Claude Code weekly %, days to its reset).
SCENARIOS = {
    "room": ((10, 5), (10, 0, 5), (30, 3)),           # plenty everywhere
    "codex-tight": ((80, 1), (10, 0, 5), (30, 3)),    # Codex on pace for about 93%
    "codex-out": ((100, 2), (10, 0, 5), (30, 3)),     # Codex used up
    "claude-busy": ((10, 5), (10, 0, 5), (60, 2)),    # Claude Code on pace for about 84%
    "agy-unused": ((10, 5), (50, 0, 2), (30, 3)),     # Antigravity's Claude and GPT group idle, two days left
}
CODEX_MODELS = (("gpt-6.2-sol", True), ("gpt-6.2-astra", False), ("gpt-6.1-terra", False))
CODEX_EFFORTS = ("low", "medium", "high", "xhigh", "max", "ultra")
AGY_MODEL_IDS = ([f"gemini-4-neon-{lv}" for lv in ("low", "medium", "high", "xhigh")]
                 + [f"gemini-4-carbon-{lv}" for lv in ("low", "high")]
                 + [f"claude-{m}-5-5-{lv}" for m in ("opus", "sonnet") for lv in ("low", "medium", "high")]
                 + ["gpt-oss-120b-medium"])


class FakeCodexClient:
    """Answers the two requests ConsultantBudget makes of the Codex daemon."""
    def __init__(self, scenario, now):
        self.used, self.days = SCENARIOS[scenario][0]
        self.now = now

    def request(self, method, params=None):
        if method == "account/rateLimits/read":
            return {"rateLimits": {"planType": "pro",
                                   "primary": {"usedPercent": 5, "windowDurationMins": 300,
                                               "resetsAt": int(self.now + 3 * 3600)},
                                   "secondary": {"usedPercent": self.used, "windowDurationMins": 10080,
                                                 "resetsAt": int(self.now + self.days * DAY)}}}
        if method == "model/list":
            return {"data": [{"id": m, "isDefault": d, "defaultReasoningEffort": "medium",
                              "supportedReasoningEfforts": [{"reasoningEffort": e} for e in CODEX_EFFORTS]}
                             for m, d in CODEX_MODELS]}
        raise RuntimeError(f"the eval's Codex has no {method}")

    def close(self):
        pass


def agy_usage(scenario, now):
    gemini, other, days = SCENARIOS[scenario][1]
    reset = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(now + days * DAY))
    return {"groups": [{"name": name, "buckets": [{"window": "weekly", "remaining_fraction": 1 - used / 100,
                                                    "reset_time": reset}]}
                       for name, used in (("Gemini Models", gemini), ("Claude and GPT models", other))]}


def write_claude_usage(scenario, cache, now):
    used, days = SCENARIOS[scenario][2]
    with open(os.path.join(cache, "claude-usage.json"), "w", encoding="utf-8") as f:
        json.dump({"saved": now, "rate_limits": {
            "five_hour": {"used_percentage": 10, "resets_at": now + 2 * 3600},
            "seven_day": {"used_percentage": used, "resets_at": now + days * DAY}}}, f)


def remove(path):
    """Delete a scratch folder, git's read-only object files included (Windows)."""
    def writable(func, p, _):
        try:
            os.chmod(p, stat.S_IWRITE)
            func(p)
        except OSError:
            pass
    shutil.rmtree(path, onerror=writable)


def load_server(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def fake_cli(mod, setup, scenario, cache):
    """Point a loaded server.py at the canned CLIs and usage, and at a cache folder of its own."""
    codex, agy = setup in ("both", "codex"), setup in ("both", "antigravity")
    fakes = {
        "nouez_cache_dir": lambda *a, **k: cache,
        "codex_installed": lambda *a, **k: codex,
        "agy_command": lambda *a, **k: "agy" if agy else None,
        "CodexClient": lambda *a, **k: FakeCodexClient(scenario, time.time()),
        "read_agy_usage": lambda *a, **k: agy_usage(scenario, time.time()) if agy else None,
        "agy_models": lambda *a, **k: list(AGY_MODEL_IDS) if agy else None,
        "login_lines": lambda *a, **k: [],
        "aa_scores": lambda *a, **k: ({}, None),
        "saved_user_variable": lambda *a, **k: None,
        "start_release_check": lambda *a, **k: None,
        "start_pane_cleanup": lambda *a, **k: None,
        "login_state": lambda *a, **k: None,
        "tidy": lambda *a, **k: None,
    }
    for name, fake in fakes.items():
        if hasattr(mod, name):
            setattr(mod, name, fake)
    return codex, agy


# --- The stub MCP server ------------------------------------------------------------------------

def run_stub(args):
    os.makedirs(args.cache, exist_ok=True)
    write_claude_usage(args.scenario, args.cache, time.time())
    mod = load_server(args.server, "nouez_under_eval")
    codex, agy = fake_cli(mod, args.setup, args.scenario, args.cache)
    started = {}
    budget = mod.HANDLERS["ConsultantBudget"]

    def log(call, arguments, **extra):
        with open(os.path.join(args.cache, CALLS), "a", encoding="utf-8") as f:
            f.write(json.dumps({"call": call, "args": arguments, **extra}) + "\n")

    def consultant_budget(arguments, cancel=None, progress=None):
        out = budget(arguments, cancel, progress)
        log("ConsultantBudget", arguments)
        return out

    def start(arguments, cancel=None, progress=None):
        provider = arguments.get("provider") or ("codex" if codex else "antigravity" if agy else None)
        if provider is None or (provider == "codex" and not codex) or (provider == "antigravity" and not agy):
            raise mod.BridgeError(f"{provider or 'No consultant CLI'} is not installed.")
        name = f"{'codex' if provider == 'codex' else 'agy'}-eval-{len(started) + 1:06x}"
        started[name] = provider
        log("StartConsultant", arguments, name=name, provider=provider)
        model = "gpt-6.2-sol" if provider == "codex" else "gemini-4-neon"
        return (f"Started {name}\n    id: 00000000-0000-0000-0000-{len(started):012x}\n"
                f"    cwd: {arguments.get('cwd')}\n    model: {model}\n"
                "Send it work with SendConsultantMessage.")

    def send(arguments, cancel=None, progress=None):
        to = arguments.get("to")
        if to not in started:
            raise mod.BridgeError(f"No consultant named {to!r}; StartConsultant returns the name to pass.")
        if not arguments.get("message"):
            raise mod.BridgeError("`message` is required.")
        log("SendConsultantMessage", arguments, provider=started[to])
        return (f"Delivered to {to} (new turn, turn t-1). The reply isn't ready; carry on with other work.")

    def elsewhere(arguments, cancel=None, progress=None):
        raise mod.BridgeError("Not available in the consult eval.")

    for name in list(mod.HANDLERS):
        mod.HANDLERS[name] = elsewhere
    mod.HANDLERS.update(ConsultantBudget=consultant_budget, StartConsultant=start, SendConsultantMessage=send,
                        ListConsultants=lambda *a, **k: "No consultants in this repo yet.")
    mod.main()


# --- The cases ----------------------------------------------------------------------------------
# Every file and prompt here is made up. "pos": nouez's instructions call for a consultation;
# "neg": they don't; "maybe": either is right (a bug can be obvious on a first look).

PRICING = '''def total(prices, discount=0.0):
    """Sum of prices after a fractional discount, rounded to cents."""
    return round(sum(prices) * (1 - discount), 2)
'''
PRICING_TESTS = '''import unittest
from pricing import total
class T(unittest.TestCase):
    def test_total(self): self.assertEqual(total([10, 5]), 15)
    def test_discount(self): self.assertEqual(total([10], 0.1), 9.0)
'''
README = "# calc\n`total(prices, discount)` sums prices and applies a fractional discount (0.1 = 10%).\n"
CALC = {"pricing.py": PRICING, "test_pricing.py": PRICING_TESTS, "README.md": README}

CHANGE = {
    "README.md": "# calc\n`total(prices, discount)` sums prices and applies a percentage discount "
                 "(10 = 10%), then tax.\n",
    "pricing.py": '''def total(prices, discount=0.0, tax=0.0):
    """Sum of prices after a discount, then tax, rounded to cents. discount and tax are percentages (10 = 10%)."""
    if not 0 <= discount <= 100:
        raise ValueError("discount must be between 0 and 100")
    subtotal = sum(prices) * (1 - discount / 100)
    return round(subtotal * (1 + tax / 100), 2)
''',
    "test_pricing.py": PRICING_TESTS.replace("total([10], 0.1), 9.0)", "total([10], 10), 9.0)") +
    '''    def test_tax(self): self.assertEqual(total([10], 10, 5), 9.45)
    def test_bad_discount(self):
        with self.assertRaises(ValueError): total([10], 120)
''',
}
TYPO = {"README.md": README.replace("sums prices", "adds up prices")}
ONE_LINE = {"pricing.py": PRICING.replace("(1 - discount)", "(1.0 - discount)")}

RATES = {
    "rates.py": '''import json
import os
from functools import lru_cache

HERE = os.path.dirname(os.path.abspath(__file__))


@lru_cache(maxsize=None)
def load_rates():
    """Exchange rates to USD, read once from rates.json."""
    with open(os.path.join(HERE, "rates.json"), encoding="utf-8") as f:
        return json.load(f)["to_usd"]
''',
    "rates.json": '{"to_usd": {"USD": 1.0, "EUR": 1.1, "GBP": 1.25}}\n',
    "quote.py": '''from rates import load_rates


def in_usd(amount, currency):
    return round(amount * load_rates()[currency], 2)


def card_rates(markup):
    """Rates with a card markup on every currency but USD, for the checkout page."""
    rates = load_rates()
    for code in rates:
        if code != "USD":
            rates[code] = round(rates[code] * (1 + markup), 4)
    return rates
''',
    "test_quote.py": '''import unittest
from quote import in_usd, card_rates


class Q(unittest.TestCase):
    def test_card_rates(self):
        self.assertEqual(card_rates(0.02)["EUR"], 1.122)

    def test_in_usd(self):
        self.assertEqual(in_usd(100, "EUR"), 110.0)
''',
}
BUG_PROMPT = ("`python -m unittest` fails in this repo: test_in_usd gets 112.2 instead of 110.0. "
              "`python -m unittest test_quote.Q.test_in_usd` on its own passes. Find the cause.")

COMMIT = re.compile(r"\bgit\b[^|;&\n]*\bcommit\b")
EDIT = {"Edit", "Write", "NotebookEdit", "MultiEdit"}

# name: (kind, kinds that fit, base files, working-copy changes, prompt, what a run stops at)
CASES = {
    "commit-change": ("pos", {"review"}, CALC, CHANGE, "Commit this.", "commit"),
    "commit-typo": ("neg", set(), CALC, TYPO, "Commit this.", "commit"),
    "commit-oneline": ("neg", set(), CALC, ONE_LINE, "Commit this.", "commit"),
    "bug": ("maybe", {"bug-hunt"}, RATES, {}, BUG_PROMPT, "edit"),
    "plan": ("pos", {"plan-critique"}, CALC, {},
             "Add multi-currency support to total(): prices can come in USD, EUR or GBP, each with its "
             "currency, and the total is in a currency the caller names. Plan it and build it.", "edit"),
    "research-config": ("pos", {"research"}, CALC, {},
                        "Should this project read its settings from TOML or JSON? Compare them for a "
                        "Python 3.9+ tool across current sources (parsers, writing files back, comments) "
                        "and recommend one. Don't change anything yet.", "end"),
    "research-sqlite": ("pos", {"research"}, CALC, {},
                        "We may store price history in SQLite from a desktop app that writes every few "
                        "seconds. WAL or rollback journal? Look across current sources and recommend "
                        "one. Don't change anything yet.", "end"),
    "lookup-empty": ("neg", set(), CALC, {}, "What does total([]) return here?", "end"),
    "reply-ok": ("neg", set(), CALC, {}, "Reply with just OK.", "end"),
    "lookup-python": ("neg", set(), CALC, {}, "What is the latest stable Python version?", "end"),
}
TOOLS = ("Read Grep Glob WebSearch WebFetch mcp__consultants__ConsultantBudget mcp__consultants__ListConsultants "
         "mcp__consultants__StartConsultant mcp__consultants__SendConsultantMessage "
         "Bash(git:*) Bash(python -m unittest:*) PowerShell(git:*) PowerShell(python -m unittest:*)")


def git_env(run):
    """An environment with none of the user's git config (hooks, signing, templates)."""
    empty = os.path.join(run, "gitconfig")
    open(empty, "w").close()
    # Inherited GIT_DIR, GIT_WORK_TREE, GIT_INDEX_FILE, GIT_CONFIG_* and the like could point git at
    # another repo or config, -C notwithstanding.
    env = {k: v for k, v in os.environ.items() if not k.upper().startswith("GIT_")}
    return dict(env, GIT_CONFIG_GLOBAL=empty, GIT_CONFIG_NOSYSTEM="1", GIT_TERMINAL_PROMPT="0")


def make_repo(path, base, changes, env):
    os.makedirs(path)
    git = ["git", "-c", "core.autocrlf=false", "-c", "core.hooksPath=", "-c", "commit.gpgsign=false", "-C", path]
    for name, text in base.items():
        with open(os.path.join(path, name), "w", encoding="utf-8", newline="\n") as f:
            f.write(text)
    subprocess.run(["git", "init", "-q", path], check=True, env=env)
    for key, value in (("user.name", "eval"), ("user.email", "eval@example.invalid"),
                       ("commit.gpgsign", "false"), ("core.hooksPath", os.path.join(path, ".git", "no-hooks"))):
        subprocess.run(git + ["config", key, value], check=True, env=env)
    subprocess.run(git + ["add", "-A"], check=True, env=env)
    subprocess.run(git + ["commit", "-q", "-m", "First version"], check=True, env=env)
    for name, text in changes.items():
        with open(os.path.join(path, name), "w", encoding="utf-8", newline="\n") as f:
            f.write(text)


def claude_md_excludes():
    home = os.environ.get("CLAUDE_CONFIG_DIR") or os.path.join(os.path.expanduser("~"), ".claude")
    return [os.path.join(home, "CLAUDE.md").replace("\\", "/"), "**/.claude/CLAUDE.md", "**/CLAUDE.local.md"]


def run_case(job, opts, work):
    case, rep = job
    kind, fits, base, changes, prompt, stop = CASES[case]
    run = os.path.join(work, f"{case}-{rep}")
    repo, cache = os.path.join(run, "repo"), os.path.join(run, "cache")
    os.makedirs(run)
    genv = git_env(run)
    make_repo(repo, base, changes, genv)
    settings, mcp = os.path.join(run, "settings.json"), os.path.join(run, "mcp.json")
    with open(settings, "w", encoding="utf-8") as f:
        json.dump({"claudeMdExcludes": claude_md_excludes(), "autoMemoryEnabled": False}, f)
    stub = [os.path.abspath(__file__), "stub", "--server", opts.server, "--setup", opts.setup,
            "--scenario", opts.scenario, "--cache", cache]
    with open(mcp, "w", encoding="utf-8") as f:
        json.dump({"mcpServers": {"consultants": {"type": "stdio", "command": sys.executable, "args": stub}}}, f)
    cmd = ["claude", "-p", "--output-format", "stream-json", "--verbose", "--model", opts.model,
           "--max-turns", "16", "--setting-sources", "project,local", "--settings", settings,
           "--strict-mcp-config", "--mcp-config", mcp, "--no-session-persistence", "--disable-slash-commands",
           "--allowedTools", TOOLS, "--", prompt]
    env = dict(genv, CLAUDE_CODE_DISABLE_AUTO_MEMORY="1", NOUEZ_NO_UPDATE_CHECK="1", NOUEZ_NO_USAGE_LOG="1")
    env.pop("NOUEZ_NO_AUTO_CONSULT", None)
    p = subprocess.Popen(cmd, cwd=repo, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                         stdin=subprocess.DEVNULL, env=env, text=True, encoding="utf-8")
    timed_out = threading.Event()

    def kill():
        timed_out.set()
        p.kill()
    timer = threading.Timer(opts.timeout, kill)
    timer.start()
    tools, sends, acted, why, error = [], set(), False, "ended", None
    try:
        for line in p.stdout:
            try:
                ev = json.loads(line)
            except ValueError:
                continue
            if ev.get("type") == "result" and ev.get("is_error"):
                error = ev.get("subtype") or "error"
            if ev.get("type") == "user":  # tool results: stop once a send has its answer
                done = [c for c in ev.get("message", {}).get("content", []) if isinstance(c, dict)
                        and c.get("type") == "tool_result" and c.get("tool_use_id") in sends]
                if done and not any(c.get("is_error") for c in done):
                    break
            if ev.get("type") != "assistant":
                continue
            for c in ev["message"].get("content", []):
                if c.get("type") != "tool_use":
                    continue
                name, args = c["name"].replace("mcp__consultants__", ""), c.get("input") or {}
                tools.append(name)
                if name == "SendConsultantMessage":
                    sends.add(c.get("id"))
                elif not sends and ((stop == "commit" and name in ("Bash", "PowerShell")
                                     and COMMIT.search(args.get("command", "")))
                                    or (stop == "edit" and name in EDIT)):
                    acted, why = True, "acted first"
            if acted:
                break
        else:  # the session ended by itself: a failed start or crash is an error, not a miss
            code = p.wait()
            if code and not error:
                error = f"exit code {code}"
    finally:
        p.kill()
        timer.cancel()
        p.wait()
    calls = []
    try:
        with open(os.path.join(cache, CALLS), encoding="utf-8") as f:
            calls = [json.loads(line) for line in f if line.strip()]
    except OSError:
        pass
    # In the order the stub accepted them: the first send, the start that returned its consultant,
    # and the budget calls before that start.
    starts, send = {}, None
    for i, c in enumerate(calls):
        if c["call"] == "StartConsultant":
            starts.setdefault(c["name"], (i, dict(c["args"], provider=c["provider"], name=c["name"])))
        elif c["call"] == "SendConsultantMessage" and c["args"].get("to") in starts:
            send, why = dict(c["args"], provider=c["provider"]), "consulted"
            break
    at, start = starts[send["to"]] if send else min(starts.values(), key=lambda v: v[0], default=(len(calls), None))
    budget = [c["args"] for c in calls[:at] if c["call"] == "ConsultantBudget"]
    if timed_out.is_set() and not send and not acted:
        why, error = "timed out", "timeout"
    elif error and not send and not acted:
        why = f"error ({error})"
    else:
        error = None
    if not opts.keep:
        remove(run)
    return {"case": case, "rep": rep, "kind": kind, "fits": sorted(fits), "consulted": bool(send),
            "why": why, "error": error, "budget": budget, "start": start, "send": send, "tools": tools}


# --- Scoring ------------------------------------------------------------------------------------

def expected_choices(opts):
    """What this repo's server.py suggests for each kind, with the same fakes as the runs."""
    mod = load_server(REPO_SERVER, "nouez_expected")
    cache = tempfile.mkdtemp(prefix="nouez-eval-expect-")
    try:
        codex, agy = fake_cli(mod, opts.setup, opts.scenario, cache)
        now = time.time()
        write_claude_usage(opts.scenario, cache, now)
        state = {"claude": {}}
        mod.claude_budget(now, state=state["claude"])
        if codex:
            state["codex"] = {}
            mod.codex_budget(FakeCodexClient(opts.scenario, now), now, state["codex"])
        state["antigravity"] = {} if agy else None
        if agy:
            mod.agy_budget(now, state=state["antigravity"])
        out = {}
        for kind in mod.CONSULT_KINDS:
            got = mod.suggest_consultant(kind, state, now)
            out[kind] = None if "none" in got else (got["provider"], got["model"], got["effort"])
        return out
    finally:
        remove(cache)


def choice_of(r):
    provider = r["send"]["provider"]  # the provider of the consultant it was sent to
    default = "gpt-6.2-sol" if provider == "codex" else "gemini-4-neon"
    return provider, r["send"].get("model") or default, r["send"].get("effort"), r["send"].get("kind")


def score(results, opts, expected):
    lines = []
    room = any(expected.values())  # with no provider installed or with room, nothing should consult
    for r in results:
        r["choice"] = None
        r["should"] = r["kind"] if room else "neg"
        if r["consulted"]:
            provider, model, effort, kind = choice_of(r)
            want = expected.get(kind if kind in expected else (r["fits"] or ["other"])[0])
            fits = kind in r["fits"] or not r["fits"]
            r["choice"] = {"provider": provider, "model": model, "effort": effort, "kind": kind,
                           "expected": want, "right": fits and want == (provider, model, effort),
                           "kind_fits": fits, "budget_first": bool(r["budget"])}
    valid = [r for r in results if not r["error"]]
    by = {}
    for r in valid:
        by.setdefault(r["case"], []).append(r)
    lines.append(f"{'case':16} {'kind':5}  consulted  budget-first  choice-right  kind-fits")
    for case, rs in by.items():
        c = [r for r in rs if r["consulted"]]
        lines.append(f"{case:16} {rs[0]['should']:5}  {len(c)}/{len(rs):<8} "
                     f"{sum(r['choice']['budget_first'] for r in c)}/{len(c):<11} "
                     f"{sum(r['choice']['right'] for r in c)}/{len(c):<11} "
                     f"{sum(r['choice']['kind_fits'] for r in c)}/{len(c)}")
    pos = [r for r in valid if r["should"] == "pos"]
    neg = [r for r in valid if r["should"] == "neg"]
    chosen = [r for r in valid if r["consulted"]]
    lines.append("")
    lines.append(f"trigger: consulted {sum(r['consulted'] for r in pos)} of {len(pos)} where it should, "
                 f"{sum(r['consulted'] for r in neg)} of {len(neg)} where it shouldn't")
    lines.append(f"choice: {sum(r['choice']['right'] for r in chosen)} of {len(chosen)} consultations matched "
                 f"the suggestion for a kind that fits; {sum(r['choice']['budget_first'] for r in chosen)} called "
                 "ConsultantBudget before StartConsultant")
    for r in results:
        if r["error"]:
            lines.append(f"  not counted: {r['case']}-{r['rep']}, {r['why']}")
    for r in chosen:
        if not r["choice"]["right"]:
            ch = r["choice"]
            lines.append(f"  {r['case']}-{r['rep']}: {ch['provider']} {ch['model']} {ch['effort']} "
                         f"(kind {ch['kind']}), suggested {ch['expected']}")
    return "\n".join(lines)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = ap.add_subparsers(dest="mode")
    st = sub.add_parser("stub", help="the eval's MCP server (the runs start it)")
    st.add_argument("--server", required=True)
    st.add_argument("--setup", choices=SETUPS, required=True)
    st.add_argument("--scenario", choices=SCENARIOS, required=True)
    st.add_argument("--cache", required=True)
    ap.add_argument("--reps", type=int, default=2)
    ap.add_argument("--cases", default="", help="comma-separated case names (default: all)")
    ap.add_argument("--setup", choices=SETUPS, default="both")
    ap.add_argument("--scenario", choices=SCENARIOS, default="room")
    ap.add_argument("--server", default=REPO_SERVER, help="the server.py to test (default: this repo's)")
    ap.add_argument("--model", default="claude-opus-5-5")
    ap.add_argument("--jobs", type=int, default=3)
    ap.add_argument("--timeout", type=int, default=480, help="seconds per run")
    ap.add_argument("--keep", action="store_true", help="keep each run's scratch repo")
    ap.add_argument("--out", help="write the results as JSON here")
    opts = ap.parse_args(argv)
    if opts.mode == "stub":
        return run_stub(opts)
    opts.server = os.path.abspath(opts.server)
    names = [c for c in opts.cases.split(",") if c] or list(CASES)
    unknown = [c for c in names if c not in CASES]
    if unknown:
        ap.error(f"unknown case {', '.join(unknown)}; the cases are {', '.join(CASES)}")
    if not shutil.which("claude"):
        ap.error("the eval needs Claude Code's `claude` command on PATH")
    expected = expected_choices(opts)
    work = tempfile.mkdtemp(prefix="nouez-eval-")
    jobs = [(c, k) for c in names for k in range(opts.reps)]
    print(f"{len(jobs)} runs: setup {opts.setup}, scenario {opts.scenario}, server {opts.server}", flush=True)

    def one(job):
        r = run_case(job, opts, work)
        print(f"  {r['case']}-{r['rep']}: {r['why']}; tools {' '.join(r['tools'][:10])}", flush=True)
        return r

    with ThreadPoolExecutor(max(1, opts.jobs)) as ex:
        results = list(ex.map(one, jobs))
    print()
    print(score(results, opts, expected))
    if opts.out:
        with open(opts.out, "w", encoding="utf-8") as f:
            json.dump({"setup": opts.setup, "scenario": opts.scenario, "server": opts.server,
                       "model": opts.model, "expected": expected, "results": results}, f, indent=1)
    if not opts.keep:
        remove(work)
    return 0


if __name__ == "__main__":
    sys.exit(main())
