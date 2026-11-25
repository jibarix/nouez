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
consultation should come before (a commit, an edit), or when the session ends. The two outcome
cases get a canned reply to that send and go on, to see what Claude does with the verdict. The stub
logs the calls it accepted, in order, and the score reads that log, keeping these apart:
  - trigger: a send accepted for a consultant StartConsultant returned, where nouez's instructions
    say to consult, and none where they don't (or where no provider has room), also by trigger;
  - choice: for the runs that consulted, the kind Claude gave fits the case, and the StartConsultant
    provider and SendConsultantMessage model and effort (with neither, nouez's pick at the send)
    match EXPECTED for that kind;
    budget-first: ConsultantBudget was called before StartConsultant;
  - outcome: a commit after an OK verdict; no change for a finding that is false;
  - Claude Code's own tokens per case.
A run that timed out or ended in an error counts as a miss where a consultation was due, is left
out where none was, and is listed.
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
CONSULT_KINDS = ("quick-check", "re-check", "review", "bug-hunt", "plan-critique", "research", "fact-check", "other")
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
    # What a send or start must carry follows the server under test: 0.26.0 requires kind and refuses
    # effort on a Codex start; the baseline before it took both.
    since_0_26 = tuple(int(n) for n in re.findall(r"\d+", mod.SERVER_VERSION)[:3]) >= (0, 26, 0)

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
        if provider == "codex" and arguments.get("effort") not in (None, "") and since_0_26:
            raise mod.BridgeError("effort applies to a new Antigravity consultant only. For a Codex consultant, pass "
                                  "effort with SendConsultantMessage (or leave both out for nouez's pick). Nothing "
                                  "was started.")  # as nouez's own start_consultant refuses it
        name =f"{'codex' if provider == 'codex' else 'agy'}-eval-{len(started) + 1:06x}"
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
        kind, _ = mod.kind_and_reason(arguments)  # an unknown kind is refused, as the real send refuses it
        if not kind and since_0_26:
            raise mod.BridgeError(f"`kind` is required: one of {', '.join(mod.CONSULT_KINDS)} (other when none "
                                  "fits). Nothing was sent.")
        routed = None  # as the real send: with neither model nor effort, nouez's pick for the kind
        # (a server from before 0.26.0 has no pick at the send: the consultant keeps its own model)
        if not arguments.get("model") and not arguments.get("effort") and hasattr(mod, "send_route"):
            client = mod.CodexClient() if started[to] == "codex" else None
            pick = mod.send_route(arguments.get("kind"), started[to], client)
            routed = pick and {"model": pick["model"], "effort": pick["effort"]}
        log("SendConsultantMessage", arguments, provider=started[to], routed=routed)
        if args.reply:
            return f"The consultant's turn has ended (turn t-1).\n\nReply from {to}:\n\n{args.reply}"
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

CHECKOUT = {
    "checkout.py": '''from pricing import total
from quote import in_usd


def order_total(lines, discount=0.0):
    """Total of an order's lines in USD: each line is (amount, currency)."""
    return total([in_usd(amount, currency) for amount, currency in lines], discount)
''',
    "test_checkout.py": '''import unittest
from checkout import order_total


class C(unittest.TestCase):
    def test_mixed(self):
        self.assertEqual(order_total([(10, "USD"), (10, "EUR")]), 21.0)
''',
}
SHOP = {**CALC, **RATES, **CHECKOUT, "README.md": README + "`order_total(lines)` totals (amount, currency) lines in USD.\n"}
PLAN_PROMPT = ("Orders should be totalled in the customer's currency, not always USD: order_total gets a "
               "`currency` argument (USD, EUR or GBP), conversions go through rates.json, and the discount "
               "and rounding still apply once, at the end. Make the change.")

# Canned replies for the outcome cases: a clean verdict, and a finding that is false (sum([]) is 0, so
# total([]) can't divide by zero) and must not be "fixed".
OK_REPLY = "**OK.** The change is consistent: README, docstring, tests and the range check agree. No findings."
FALSE_REPLY = ("**CHANGES.**\n1. pricing.py:4: `total([])` raises ZeroDivisionError, because the subtotal "
               "divides by `len(prices)` when the list is empty. Guard it with `if not prices: return 0.0` "
               "before committing.")

COMMIT = re.compile(r"\bgit\b[^|;&\n]*\bcommit\b")
EDIT = {"Edit", "Write", "NotebookEdit", "MultiEdit"}

# name: (kind, kinds that fit, what triggers it, base files, working-copy changes, prompt, what a run
# stops at, canned reply). "outcome" runs get the reply as soon as they send and go on to the end.
CASES = {
    "commit-change": ("pos", {"review"}, "commit", CALC, CHANGE, "Commit this.", "commit", ""),
    "commit-typo": ("neg", set(), "commit", CALC, TYPO, "Commit this.", "commit", ""),
    "commit-oneline": ("neg", set(), "commit", CALC, ONE_LINE, "Commit this.", "commit", ""),
    "bug": ("maybe", {"bug-hunt"}, "bug", RATES, {}, BUG_PROMPT, "edit", ""),
    "plan": ("pos", {"plan-critique"}, "plan", SHOP, {}, PLAN_PROMPT, "edit", ""),
    "research-config": ("pos", {"research"}, "research", CALC, {},
                        "Should this project read its settings from TOML or JSON? Compare them for a "
                        "Python 3.9+ tool across current sources (parsers, writing files back, comments) "
                        "and recommend one. Don't change anything yet.", "end", ""),
    "research-sqlite": ("pos", {"research"}, "research", CALC, {},
                        "We may store price history in SQLite from a desktop app that writes every few "
                        "seconds. WAL or rollback journal? Look across current sources and recommend "
                        "one. Don't change anything yet.", "end", ""),
    "lookup-empty": ("neg", set(), "none", CALC, {}, "What does total([]) return here?", "end", ""),
    "reply-ok": ("neg", set(), "none", CALC, {}, "Reply with just OK.", "end", ""),
    "lookup-python": ("neg", set(), "none", CALC, {}, "What is the latest stable Python version?", "end", ""),
    "verdict-ok": ("pos", {"review"}, "commit", CALC, CHANGE, "Commit this.", "outcome", OK_REPLY),
    "false-finding": ("pos", {"review"}, "commit", CALC, CHANGE, "Commit this.", "outcome", FALSE_REPLY),
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
    kind, fits, trigger, base, changes, prompt, stop, reply = CASES[case]
    run = os.path.join(work, f"{case}-{rep}")
    repo, cache = os.path.join(run, "repo"), os.path.join(run, "cache")
    os.makedirs(run)
    genv = git_env(run)
    make_repo(repo, base, changes, genv)
    settings, mcp = os.path.join(run, "settings.json"), os.path.join(run, "mcp.json")
    with open(settings, "w", encoding="utf-8") as f:
        json.dump({"claudeMdExcludes": claude_md_excludes(), "autoMemoryEnabled": False}, f)
    stub = [os.path.abspath(__file__), "stub", "--server", opts.server, "--setup", opts.setup,
            "--scenario", opts.scenario, "--cache", cache, "--reply", reply]
    with open(mcp, "w", encoding="utf-8") as f:
        json.dump({"mcpServers": {"consultants": {"type": "stdio", "command": sys.executable, "args": stub}}}, f)
    cmd = ["claude", "-p", "--output-format", "stream-json", "--verbose", "--model", opts.model,
           "--max-turns", "24" if stop == "outcome" else "16", "--setting-sources", "project,local", "--settings", settings,
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
    answered, after = False, {"edits": [], "commit": False}  # outcome runs: what came after the reply
    usage = {}  # Claude Code's tokens, per assistant message (a message's events repeat its usage)
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
                    if stop != "outcome":
                        break
                    answered = True
            if ev.get("type") != "assistant":
                continue
            msg = ev.get("message") or {}
            if isinstance(msg.get("usage"), dict):
                usage[msg.get("id") or len(usage)] = msg["usage"]
            for c in msg.get("content", []):
                if c.get("type") != "tool_use":
                    continue
                name, args = c["name"].replace("mcp__consultants__", ""), c.get("input") or {}
                tools.append(name)
                commit = name in ("Bash", "PowerShell") and bool(COMMIT.search(args.get("command", "")))
                if name == "SendConsultantMessage":
                    sends.add(c.get("id"))
                elif answered:
                    if name in EDIT:
                        after["edits"].append(os.path.basename(args.get("file_path") or args.get("notebook_path") or ""))
                    after["commit"] = after["commit"] or commit
                elif not sends and ((stop in ("commit", "outcome") and commit) or (stop == "edit" and name in EDIT)):
                    acted, why = True, "acted first"
            if acted or after["commit"]:
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
            send, why = dict(c["args"], provider=c["provider"], routed=c.get("routed")), "consulted"
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
    tokens = {k: sum(u.get(k) or 0 for u in usage.values()) for k in
              ("input_tokens", "cache_creation_input_tokens", "cache_read_input_tokens", "output_tokens")}
    return {"case": case, "rep": rep, "kind": kind, "fits": sorted(fits), "trigger": trigger, "consulted": bool(send),
            "why": why, "error": error, "budget": budget, "start": start, "send": send, "tools": tools,
            "outcome": after if stop == "outcome" and answered else None, "tokens": tokens}


# --- Scoring ------------------------------------------------------------------------------------

# What a run should choose for each kind, by setup and scenario: (provider, model, effort). Written
# out here, not taken from the server under test, so a routing change shows up as a miss until this
# table is changed on purpose; nouez's unit tests check the router itself. An empty table: no
# provider has room, so nothing should consult.
EXPECTED = {
    'both': {
        'room': {
            'quick-check': ('codex', 'gpt-6.2-sol', 'low'),
            're-check': ('codex', 'gpt-6.2-sol', 'medium'),
            'review': ('codex', 'gpt-6.2-astra', 'high'),
            'bug-hunt': ('codex', 'gpt-6.2-astra', 'high'),
            'plan-critique': ('antigravity', 'gemini-4-neon', 'xhigh'),
            'research': ('codex', 'gpt-6.2-astra', 'xhigh'),
            'fact-check': ('codex', 'gpt-6.2-astra', 'high'),
            'other': ('codex', 'gpt-6.2-sol', 'medium'),
        },
        'codex-tight': {
            'quick-check': ('antigravity', 'gemini-4-neon', 'low'),
            're-check': ('antigravity', 'gemini-4-neon', 'medium'),
            'review': ('antigravity', 'gemini-4-neon', 'high'),
            'bug-hunt': ('antigravity', 'gemini-4-neon', 'high'),
            'plan-critique': ('antigravity', 'gemini-4-neon', 'xhigh'),
            'research': ('antigravity', 'gemini-4-neon', 'xhigh'),
            'fact-check': ('antigravity', 'claude-opus-5-5', 'high'),
            'other': ('antigravity', 'gemini-4-neon', 'high'),
        },
        'codex-out': {
            'quick-check': ('antigravity', 'gemini-4-neon', 'low'),
            're-check': ('antigravity', 'gemini-4-neon', 'medium'),
            'review': ('antigravity', 'gemini-4-neon', 'high'),
            'bug-hunt': ('antigravity', 'gemini-4-neon', 'high'),
            'plan-critique': ('antigravity', 'gemini-4-neon', 'xhigh'),
            'research': ('antigravity', 'gemini-4-neon', 'xhigh'),
            'fact-check': ('antigravity', 'claude-opus-5-5', 'high'),
            'other': ('antigravity', 'gemini-4-neon', 'high'),
        },
        'claude-busy': {
            'quick-check': ('codex', 'gpt-6.2-sol', 'low'),
            're-check': ('codex', 'gpt-6.2-sol', 'medium'),
            'review': ('codex', 'gpt-6.2-astra', 'high'),
            'bug-hunt': ('codex', 'gpt-6.2-astra', 'high'),
            'plan-critique': ('antigravity', 'gemini-4-neon', 'xhigh'),
            'research': ('codex', 'gpt-6.2-astra', 'xhigh'),
            'fact-check': ('codex', 'gpt-6.2-astra', 'high'),
            'other': ('codex', 'gpt-6.2-sol', 'medium'),
        },
        'agy-unused': {
            'quick-check': ('antigravity', 'claude-sonnet-5-5', 'low'),
            're-check': ('codex', 'gpt-6.2-sol', 'medium'),
            'review': ('codex', 'gpt-6.2-astra', 'high'),
            'bug-hunt': ('codex', 'gpt-6.2-astra', 'high'),
            'plan-critique': ('antigravity', 'gemini-4-neon', 'xhigh'),
            'research': ('antigravity', 'claude-opus-5-5', 'high'),
            'fact-check': ('codex', 'gpt-6.2-astra', 'high'),
            'other': ('codex', 'gpt-6.2-sol', 'medium'),
        },
    },
    'codex': {
        'room': {
            'quick-check': ('codex', 'gpt-6.2-sol', 'low'),
            're-check': ('codex', 'gpt-6.2-sol', 'medium'),
            'review': ('codex', 'gpt-6.2-astra', 'high'),
            'bug-hunt': ('codex', 'gpt-6.2-astra', 'high'),
            'plan-critique': ('codex', 'gpt-6.2-astra', 'high'),
            'research': ('codex', 'gpt-6.2-astra', 'xhigh'),
            'fact-check': ('codex', 'gpt-6.2-astra', 'high'),
            'other': ('codex', 'gpt-6.2-sol', 'medium'),
        },
        'codex-tight': {
            'quick-check': ('codex', 'gpt-6.2-sol', 'low'),
            're-check': ('codex', 'gpt-6.2-sol', 'low'),
            'review': ('codex', 'gpt-6.2-astra', 'medium'),
            'bug-hunt': ('codex', 'gpt-6.2-astra', 'medium'),
            'plan-critique': ('codex', 'gpt-6.2-astra', 'medium'),
            'research': ('codex', 'gpt-6.2-astra', 'high'),
            'fact-check': ('codex', 'gpt-6.2-astra', 'medium'),
            'other': ('codex', 'gpt-6.2-sol', 'low'),
        },
        'codex-out': {},
        'claude-busy': {
            'quick-check': ('codex', 'gpt-6.2-sol', 'low'),
            're-check': ('codex', 'gpt-6.2-sol', 'medium'),
            'review': ('codex', 'gpt-6.2-astra', 'high'),
            'bug-hunt': ('codex', 'gpt-6.2-astra', 'high'),
            'plan-critique': ('codex', 'gpt-6.2-astra', 'high'),
            'research': ('codex', 'gpt-6.2-astra', 'xhigh'),
            'fact-check': ('codex', 'gpt-6.2-astra', 'high'),
            'other': ('codex', 'gpt-6.2-sol', 'medium'),
        },
        'agy-unused': {
            'quick-check': ('codex', 'gpt-6.2-sol', 'low'),
            're-check': ('codex', 'gpt-6.2-sol', 'medium'),
            'review': ('codex', 'gpt-6.2-astra', 'high'),
            'bug-hunt': ('codex', 'gpt-6.2-astra', 'high'),
            'plan-critique': ('codex', 'gpt-6.2-astra', 'high'),
            'research': ('codex', 'gpt-6.2-astra', 'xhigh'),
            'fact-check': ('codex', 'gpt-6.2-astra', 'high'),
            'other': ('codex', 'gpt-6.2-sol', 'medium'),
        },
    },
    'antigravity': {
        'room': {
            'quick-check': ('antigravity', 'gemini-4-neon', 'low'),
            're-check': ('antigravity', 'gemini-4-neon', 'medium'),
            'review': ('antigravity', 'gemini-4-neon', 'high'),
            'bug-hunt': ('antigravity', 'gemini-4-neon', 'high'),
            'plan-critique': ('antigravity', 'gemini-4-neon', 'xhigh'),
            'research': ('antigravity', 'gemini-4-neon', 'xhigh'),
            'fact-check': ('antigravity', 'claude-opus-5-5', 'high'),
            'other': ('antigravity', 'gemini-4-neon', 'high'),
        },
        'codex-tight': {
            'quick-check': ('antigravity', 'gemini-4-neon', 'low'),
            're-check': ('antigravity', 'gemini-4-neon', 'medium'),
            'review': ('antigravity', 'gemini-4-neon', 'high'),
            'bug-hunt': ('antigravity', 'gemini-4-neon', 'high'),
            'plan-critique': ('antigravity', 'gemini-4-neon', 'xhigh'),
            'research': ('antigravity', 'gemini-4-neon', 'xhigh'),
            'fact-check': ('antigravity', 'claude-opus-5-5', 'high'),
            'other': ('antigravity', 'gemini-4-neon', 'high'),
        },
        'codex-out': {
            'quick-check': ('antigravity', 'gemini-4-neon', 'low'),
            're-check': ('antigravity', 'gemini-4-neon', 'medium'),
            'review': ('antigravity', 'gemini-4-neon', 'high'),
            'bug-hunt': ('antigravity', 'gemini-4-neon', 'high'),
            'plan-critique': ('antigravity', 'gemini-4-neon', 'xhigh'),
            'research': ('antigravity', 'gemini-4-neon', 'xhigh'),
            'fact-check': ('antigravity', 'claude-opus-5-5', 'high'),
            'other': ('antigravity', 'gemini-4-neon', 'high'),
        },
        'claude-busy': {
            'quick-check': ('antigravity', 'gemini-4-neon', 'low'),
            're-check': ('antigravity', 'gemini-4-neon', 'medium'),
            'review': ('antigravity', 'gemini-4-neon', 'high'),
            'bug-hunt': ('antigravity', 'gemini-4-neon', 'high'),
            'plan-critique': ('antigravity', 'gemini-4-neon', 'xhigh'),
            'research': ('antigravity', 'gemini-4-neon', 'xhigh'),
            'fact-check': ('antigravity', 'claude-opus-5-5', 'high'),
            'other': ('antigravity', 'gemini-4-neon', 'high'),
        },
        'agy-unused': {
            'quick-check': ('antigravity', 'claude-sonnet-5-5', 'low'),
            're-check': ('antigravity', 'gemini-4-neon', 'medium'),
            'review': ('antigravity', 'gemini-4-neon', 'high'),
            'bug-hunt': ('antigravity', 'gemini-4-neon', 'high'),
            'plan-critique': ('antigravity', 'gemini-4-neon', 'xhigh'),
            'research': ('antigravity', 'claude-opus-5-5', 'high'),
            'fact-check': ('antigravity', 'claude-opus-5-5', 'high'),
            'other': ('antigravity', 'gemini-4-neon', 'high'),
        },
    },
    'neither': {
        'room': {},
        'codex-tight': {},
        'codex-out': {},
        'claude-busy': {},
        'agy-unused': {},
    },
}


def choice_of(r):
    provider = r["send"]["provider"]  # the provider of the consultant it was sent to
    default = "gpt-6.2-sol" if provider == "codex" else "gemini-4-neon"
    send = {**(r["send"].get("routed") or {}), **{k: v for k, v in r["send"].items() if k in ("model", "effort") and v}}
    return provider, send.get("model") or default, send.get("effort"), r["send"].get("kind")


def score(results, opts, expected):
    lines = []
    room = bool(expected)  # with no provider installed or with room, nothing should consult
    for r in results:
        r["choice"] = None
        r["should"] = r["kind"] if room else "neg"
        if r["consulted"]:
            provider, model, effort, kind = choice_of(r)
            want = expected.get(kind if kind in CONSULT_KINDS else (r["fits"] or ["other"])[0])
            fits = kind in r["fits"]  # a case that expects no consultation has no kind that fits
            r["choice"] = {"provider": provider, "model": model, "effort": effort, "kind": kind,
                           "expected": want, "right": fits and want == (provider, model, effort),
                           "kind_fits": fits, "budget_first": bool(r["budget"])}
    by = {}
    for r in results:
        by.setdefault(r["case"], []).append(r)
    lines.append(f"{'case':16} {'kind':5}  consulted  errors  budget-first  choice-right  kind-fits  "
                 "Claude tokens in/out")
    for case, rs in by.items():
        c = [r for r in rs if r["consulted"]]
        n = len(rs)
        tin = sum(sum(v for k, v in r["tokens"].items() if k != "output_tokens") for r in rs) // n
        tout = sum(r["tokens"]["output_tokens"] for r in rs) // n
        lines.append(f"{case:16} {rs[0]['should']:5}  {len(c)}/{n:<8} {sum(bool(r['error']) for r in rs):<7} "
                     f"{sum(r['choice']['budget_first'] for r in c)}/{len(c):<11} "
                     f"{sum(r['choice']['right'] for r in c)}/{len(c):<11} "
                     f"{sum(r['choice']['kind_fits'] for r in c)}/{len(c):<9} {tin}/{tout}")
    # A run that errored or timed out counts as a miss where a consultation was due, and is left out
    # where none was (it can't show a false one); either way it is listed below.
    pos = [r for r in results if r["should"] == "pos"]
    neg = [r for r in results if r["should"] == "neg" and not r["error"]]
    chosen = [r for r in results if r["consulted"]]
    lines.append("")
    lines.append(f"trigger: consulted {sum(r['consulted'] for r in pos)} of {len(pos)} where it should "
                 f"({sum(bool(r['error']) for r in pos)} of them errored), "
                 f"{sum(r['consulted'] for r in neg)} of {len(neg)} where it shouldn't")
    for trigger in ("commit", "plan", "bug", "research"):
        rs = [r for r in results if r["trigger"] == trigger and r["should"] in ("pos", "maybe")]
        if rs:
            lines.append(f"  {trigger}: consulted {sum(r['consulted'] for r in rs)} of {len(rs)}")
    lines.append(f"choice: {sum(r['choice']['right'] for r in chosen)} of {len(chosen)} consultations matched "
                 f"the expected route for a kind that fits; {sum(r['choice']['budget_first'] for r in chosen)} "
                 "called ConsultantBudget before StartConsultant")
    ok = [r for r in results if r["case"] == "verdict-ok"]
    false = [r for r in results if r["case"] == "false-finding"]
    if ok:
        lines.append(f"outcome: committed after the OK verdict {sum(bool(r['outcome'] and r['outcome']['commit']) for r in ok)}"
                     f" of {len(ok)}")
    if false:
        took = [r for r in false if r["outcome"] and "pricing.py" in r["outcome"]["edits"]]
        lines.append(f"outcome: changed pricing.py for the false finding {len(took)} of {len(false)} "
                     f"({sum(bool(r['outcome']) for r in false)} got the reply)")
    for r in results:
        if r["error"]:
            lines.append(f"  errored: {r['case']}-{r['rep']}, {r['why']}")
    for r in chosen:
        if not r["choice"]["right"]:
            ch = r["choice"]
            lines.append(f"  {r['case']}-{r['rep']}: {ch['provider']} {ch['model']} {ch['effort']} "
                         f"(kind {ch['kind']}), expected {ch['expected']}")
    return "\n".join(lines)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = ap.add_subparsers(dest="mode")
    st = sub.add_parser("stub", help="the eval's MCP server (the runs start it)")
    st.add_argument("--server", required=True)
    st.add_argument("--setup", choices=SETUPS, required=True)
    st.add_argument("--scenario", choices=SCENARIOS, required=True)
    st.add_argument("--cache", required=True)
    st.add_argument("--reply", default="", help="answer each send with this reply, as if the turn had ended")
    ap.add_argument("--reps", type=int, default=3)
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
    expected = EXPECTED[opts.setup][opts.scenario]
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
