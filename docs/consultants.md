# Consultants

Part of [nouez's documentation](../README.md#documentation).

The [README](../README.md#consultants) shows what to ask for; this page has the detail. [Rules](rules.md) lists every rule below in one table, with the setting that changes each.

**1. Nothing to start.** With Codex, if its daemon isn't running (it stops when the computer restarts), the first tool call starts it, which adds a few seconds. To start it yourself, run:

```sh
codex app-server daemon start
```

**2. Work in Claude Code as usual.** Whenever you want a second opinion, ask for it in plain language:

> Start a Codex consultant for this project.

> Show me what the consultants are doing.

> Ask Gemini whether this plan holds up.

> Ask the consultant to review the plan you just wrote. Push back on anything you disagree with before changing it.

> Before you commit, send the diff to the consultant and ask it to look for bugs.

> We're stuck on this test failure. Ask the consultant for its diagnosis and compare it with yours.

> We're done. Stop the consultant.

**Claude also consults without being asked**, at four points: before committing a change to behavior, to several files or to anything risky (a review of what it will commit: all its uncommitted work, or else the staged diff; it commits after the verdict), when a failure's cause isn't obvious after a first look (a bug hunt), before the first edit built on a consequential plan, design, formula or rule of its own (a critique: it shows you the draft, and builds on it only after the verdict), and for research across sources instead of searching the web itself, an audit or explanation spanning many files, or a consequential claim a first check left uncertain (it asks for a short answer, which saves its own usage). Changes that leave behavior alone don't count, whatever their size, and only work that needs the verdict waits for it. It first calls `ConsultantBudget` and starts the consultant it suggests, and nouez applies the suggested model and effort when Claude sends (see [How nouez picks a model](#how-nouez-picks-a-model)). It skips one, saying so, when no subscription has room. nouez's server instructions say this, so it works with no `CLAUDE.md` lines and no skill. Your own instructions override it: write when to consult, or not to, in `~/.claude/CLAUDE.md`. To turn it off altogether, set `NOUEZ_NO_AUTO_CONSULT=1` in nouez's environment (with a Codex API key rather than a subscription, each consultation costs money). Without a consultant CLI it is off.

Claude calls `StartConsultant` to create a background consultant in your project (Codex if it is installed, otherwise Antigravity) (or reuses one already working there, see [Reusing a consultant](#reusing-a-consultant)), `SendConsultantMessage` to ask questions, and `StopConsultant` when you're finished. Each message reaches the consultant prefixed with `[Message from Claude Code via the consultants bridge]`, and Claude gets the answer back as a tool result.

**A consultant Claude starts is always read-only.** A Codex one can read your files and run read-only commands for auditing, validation and research; an Antigravity one can read files but runs no commands, so Claude puts the diff or test output it needs in the message. Neither can change anything. (A Codex session you opened yourself keeps its own permissions; see [below](#using-a-codex-session-you-opened-yourself).) It never stops to ask for approvals, because no terminal is attached to answer them. Claude does all the writing. There is no option to give a consultant write access.

**3. Watch or join in (optional).** Ask Claude to *"show me the consultations"*: it calls `OpenStatusScreen` with its consultations page, which opens nouez's status screen on that page, or switches the one already open to it. Every consultant on the computer is in one place, across projects, Codex and Antigravity alike: working ones first, each with the kind of its last message and the verdict of the reply. The selected one's latest turn is shown as it runs: the message it was sent, its thinking summaries, the commands it runs, and its reply. Under the turn is the command that opens the consultant in its own CLI, `codex resume <id> --remote unix://<socket>` or `agy --conversation <id>`, with its folder: run it in a terminal of your own to read the whole conversation there or type to the consultant yourself. A Codex consultant is an ordinary Codex session, and Claude's messages to it are refused while a turn you typed there runs. See [Usage log and status screen](status-screen.md#usage-log-and-status-screen) for the keys.

nouez opens no windows for consultants itself. Up to 0.22.0 it opened a Codex pane or window for each one; when a 0.23.0 server starts, it closes those once, in the background. It closes only panes an earlier nouez opened, which carry a token it gave them, so a `codex resume` you started yourself stays open, and on Windows only while nothing else runs in the pane. On macOS it can't tell a pane's process safely from one that took its id, so close those yourself.

## Reusing a consultant

A consultant keeps its whole conversation until you stop it, so you can keep going back to the same one. Refer to it and Claude finds it with `ListConsultants`:

> Ask the consultant to check the diff.

> Send this to codex-myproject-a1b2c3: …

> Show me what the consultant is doing.

This works from a new Claude Code session too: consultants that went idle still appear in the list, and the next message reloads them. Reuse is the default. `StartConsultant` searches first: if a consultant it started earlier already works in the same project, it returns that one and starts nothing; if none is found, it starts one. It never picks a Codex session you opened yourself, even in the same project, because that session keeps your permissions; it lists such sessions in its result instead. `model`, `title` and `instructions` only apply when a new consultant is started. The project is the git repo; outside git, it's the Claude Code workspace folder (the folder you launched Claude Code in), so a subfolder finds the consultant started at the top. When you want a clean slate, ask for a new one, and Claude passes `new: true`:

> Start a new Codex consultant for this.

> Start a second consultant in ~/projects/other-repo and ask it to …

With more than one consultant running, name the one you mean. Once stopped, a consultant is out of Claude's reach. A Codex one is archived: to bring it back, run `codex unarchive <id>` (the id is in the stop message). An Antigravity one is forgotten by nouez, but its conversation stays in agy (`agy --conversation <id>`).

## Using a Codex session you opened yourself

If you'd rather see Codex work in its own window, open it yourself (`cd my-project && codex`) and ask Claude to *"list the consultants and send it …"*. Claude finds the session with `ListConsultants` and talks to it the same way. `StartConsultant` never chooses your session on its own, and `SendConsultantMessage` refuses it unless Claude passes `allow_user_session: true`, which it is told to do only when you ask. With `NOUEZ_ASK_USER_SESSION=1`, nouez also asks you in Claude Code's own prompt before each message, and with `NOUEZ_NO_USER_SESSIONS=1` it never sends one. The message appears in that terminal as a new prompt. Sessions you open yourself use their own permission settings and approval prompts, and `StopConsultant` won't close them.

## Choosing model and effort

A Codex consultant starts on the model and reasoning effort from your Codex config (`model` and `model_reasoning_effort` in `~/.codex/config.toml`); an Antigravity one on `gemini-4-neon` at level `high`. Before each consultation, Claude calls `ConsultantBudget` with the kind of consultation, and nouez suggests the provider to pass to `StartConsultant` and the model and effort for `SendConsultantMessage`. The send applies the model and effort itself: a message with a kind and no `model` or `effort` runs on nouez's pick for that kind, within the consultant's provider, and the result says so. A model or effort Claude passes (yours, or another provider's suggestion) wins. A change keeps the consultant's context and stays for later messages. For kind `other`, or when no model has room, the consultant keeps what it has. With a kind, `ConsultantBudget` answers with only the suggestion and its notes; `details: true` adds the usage windows, the models and the scores. No `CLAUDE.md` lines or skill are needed for this.

You can always name your own: *"ask Gemini"*, *"use gpt-6.2-sol at low"*. Claude then asks `ConsultantBudget` for that provider only (for Antigravity, its Gemini models). Your own instructions also come first: to route differently, write your rules in `~/.claude/CLAUDE.md`.

### How nouez picks a model

Each kind of consultation has a starting point and a fallback on the other provider:

| Kind | First choice | Without it |
|---|---|---|
| Quick check | Codex `gpt-6.2-sol`, low | Antigravity `gemini-4-neon`, low; then Antigravity's `claude-sonnet-5-5`, low |
| Re-check (named fixes only) | Codex `gpt-6.2-sol`, medium | `gemini-4-neon`, medium |
| Review | Codex `gpt-6.2-astra`, high | `gemini-4-neon`, high |
| Bug hunt | Codex `gpt-6.2-astra`, high | `gemini-4-neon`, high |
| Plan critique | Antigravity `gemini-4-neon`, xhigh | Codex `gpt-6.2-astra`, high, asked first whether any premise is wrong |
| Research | Codex `gpt-6.2-astra`, xhigh | `gemini-4-neon`, xhigh; then Antigravity's `claude-opus-5-5`, high |
| Fact check | Codex `gpt-6.2-astra`, high | Antigravity's `claude-opus-5-5`, high; then `gemini-4-neon`, high |

Why these, from public benchmarks:

- **Artificial Analysis** ([artificialanalysis.ai](https://artificialanalysis.ai), Intelligence Index v5 and its benchmarks, 2026-11-22). GPT-6.2 Astra at high scores 60.1 and Sol at xhigh 55.7, so Sol is for quick checks and re-checks only. Gemini 4 Neon at xhigh leads every Codex model on finance, legal, medicine, economics and strategy, so for those subjects the suggestion names it too. On not making up an answer, Astra scores 59.1 and Neon 14.4, so fact checks go to Astra, and to Neon only last and with sources asked for.
- **BullshitBench** ([petergpt.github.io/bullshit-benchmark](https://petergpt.github.io/bullshit-benchmark/), 2026-11-19) asks questions built on a false premise. Neon at xhigh clearly says so 84% of the time, Astra at max 55% and Sol at max 42%. So plan critiques go to Neon at xhigh, and to Astra with the premise question asked outright.
- **A long-running coding benchmark** ([kevinkern.dev](https://kevinkern.dev/benchmarks/marlies-workflows/long-running/), one feature, a small private test) had GPT-6.2 Sol building with an Astra review on top. One task, so it only supports Astra as the reviewer.

The suggestion then follows the usage `ConsultantBudget` shows:

- **No room:** a subscription whose window is used up, or runs out before its reset at the current rate, isn't suggested. When none has room, the suggestion says to skip the consultation and tell you. Free full resets are never used; only you decide that.
- **An old reading:** usage read too long ago to project from counts only as the least that week will reach, so it can make a provider tight or busy but never spare. So does a reading too early in the week to project from. The suggestion then says "at 95% of its week or more" rather than giving a pace.
- **A limit Codex says is reached** blocks Codex whatever its windows show; the status screen shows it as a used-up `limit` row.
- **Each quota counts on its own:** Codex, and each of Antigravity's quota groups. Gemini models count against its Gemini group, and `claude-opus-5-5` and `claude-sonnet-5-5` against its Claude and GPT group, both on Google's quota, not Claude Code's. So a full Gemini group can hand work to the Claude and GPT group, and the other way round.
- **Tight:** when the first choice's week is on pace for over 90% at its reset, another quota with room takes it. Otherwise the first choice stays, one effort level down.
- **Would go unused:** a week on pace for under 60% at a reset within three days would reset with usage left. It takes the work from a first choice past 70%, except fact checks. For research and quick checks it goes first even when the first choice has room, the week that resets soonest first, so research can go to `claude-opus-5-5` and quick checks to `claude-sonnet-5-5` at `low` on Antigravity. Reviews, re-checks, bug hunts and plan critiques don't move this way, and never go to a Claude model, not even as Antigravity's default: it shares the blind spots of the Claude that wrote the work.
- **Claude Code's own week:** the goal is Claude Code's weekly usage as low as the other subscriptions allow. Under about 70% on pace, Claude hands bulky read-only work (reading many files or long logs, audits, research across sources) to a consultant. Past 70%, it hands out everything read-only that can go out, keeping writing code and edits. Past 90%, it hands out everything except what only Claude can do here (writing code, edits, the browser, your sign-ins), puts off optional work and says so. It always asks for short replies, and does a job itself when that takes seconds. The prompt hook (below) says this on each prompt past 70%.
- **Behind schedule:** for research and quick checks, a subscription at least 15 points further behind an even pace through its week than the first choice takes the work (10% used two days before a weekly reset is 61 points behind). Reading many files and audits go as research.
- **A week not yet begun:** Antigravity's weeks start on first use, so each idle day pushes later weeks back. While Claude Code is past 70%, research starts its Claude and GPT group's week when that hasn't begun.
- **Patches:** for a hard bug whose fix is small, Claude asks the consultant to draft the fix as a diff in its reply, checks it, and applies it with `git apply`.
- **A model that isn't listed:** nouez takes the newest listed model of the same family (`gpt-6.3-astra` for `gpt-6.2-astra`), else the provider's default model, and says so. An effort the model doesn't list becomes the closest listed level below it. A level is always named, since a reused consultant keeps the one it last had.

For reviews, the suggestion also says to ask for every finding in the first round, and to treat later rounds as re-checks. nouez counts the rounds on the same work, and when the third still asks for changes it tells Claude to show you the open points and let you decide (`NOUEZ_REVIEW_ROUNDS_STOP=1` refuses a fourth). When the other provider has room, a disagreement goes to it blind, on the model and effort nouez names for it: a new consultant gets the first round's brief and the work from nouez (`second_opinion_of`), never the findings, and sees the disputed finding only after its own verdict. A decision costly to undo goes to both at once.

nouez's own eval checks that fresh Claude Code sessions follow this. See [The consult eval](#the-consult-eval).

### The consult eval

`tests/consult_eval.py` checks two things on fresh Claude Code sessions: whether Claude consults where nouez's instructions say to, and not where they don't, and whether it takes the consultant `ConsultantBudget` suggests. Each run is a new `claude -p` session in its own scratch repo, with made-up code and prompts, none of your settings, memory or `CLAUDE.md`, and a stub nouez. The stub loads a real `server.py` but fakes the Codex and Antigravity CLIs, the usage numbers, and `StartConsultant` and `SendConsultantMessage`, so nothing reaches a real consultant or your cache. The scratch repos use none of your git config or hooks either. The stub logs the calls it accepted, in order, and the score comes from that log: a consultation counts only when a message reached a consultant `StartConsultant` returned, and it chose right only when its kind fits the case and its provider, model and effort match the route the eval expects for that kind, setup and scenario. Those routes are written out in the eval, not asked of the server under test, so a routing change shows up as a miss until the table is changed on purpose. With no provider installed or with room, every case counts as one that shouldn't consult, and a case that shouldn't consult has no kind that fits. A run that times out or ends in an error counts as a miss where a consultation was due, is left out where none was, and is listed either way. Two outcome cases get a canned reply as soon as Claude sends the review and go on: after an OK verdict, does Claude commit; after a finding that is false, does it change the code anyway. The score also shows Claude Code's own tokens per case, read from the session's output. It uses Claude Code usage, about a minute per run.

```
python tests/consult_eval.py                           # all cases, 3 runs each, both providers, room
python tests/consult_eval.py --setup antigravity --cases plan,research-config
python tests/consult_eval.py --scenario codex-tight    # also codex-out, claude-busy, agy-unused
python tests/consult_eval.py --server old-server.py    # compare with another version
```

The cases are a change to commit (should consult), a typo and a one-line change to commit (shouldn't), a change across several files that needs a plan, asked for without the word "plan" (should), two questions that need research across sources (should), three lookups or replies Claude can answer itself (shouldn't), a test that fails only after another one runs (may or may not), and the two outcome cases. The score gives the commit, plan, bug and research triggers each on a line of its own.

Results on 2026-11-25, with Claude Opus 5.5, both providers installed and plenty of room:

| Server | Consulted where it should | Consulted where it shouldn't | Took the suggestion |
|---|---|---|---|
| 0.23.0 | 1 of 8 | 0 of 10 | 0 of 1 (`gpt-6.2-sol`, no effort, for research) |
| 0.24.0 | 6 of 8 | 0 of 10 | 6 of 6, each after calling `ConsultantBudget` |
| 0.25.0 | 6 of 8 | 0 of 10 | 6 of 6, each after calling `ConsultantBudget` |
| 0.26.0 | 6 of 8 | 0 of 10 | 6 of 6, each after calling `ConsultantBudget` |

With only Codex, 2 of the 4 cases that should consult did (4 of 4 in an earlier run); with only Antigravity, 3 of 4; with Codex's week tight, where nouez moves every kind to Antigravity, 3 of 4. Each of those consultations took the suggestion. With neither installed, Claude didn't try to consult. The case missed most often is the plan, missed in every run: asked to plan and build, Claude writes a short plan and starts building before it asks. A change to commit is sometimes committed without a review. Research went from 0 of 4 to 4 of 4 when the instructions said "instead of searching the web yourself": Claude had treated its own web search as the research.

In 0.25.0, the suggestions in each of those setups and scenarios are the same as in 0.24.0, so the results above still hold. In the `agy-unused` scenario, where Antigravity's Claude and GPT group is idle two days before its reset, all 4 research consultations went to Antigravity's `claude-opus-5-5` at high as suggested, and the one review stayed on Codex `gpt-6.2-astra`; the plan was again missed in both runs and the change committed without a review in one.

0.26.0's shorter instructions were checked on 2026-11-25 against 0.25.0 in the same runs: the same 6 of 8, with the plan again missed in both runs. A draft that dropped "instead of searching the web yourself" consulted for research 0 of 4 times, calling `ConsultantBudget` and then searching the web itself; with the words back, 4 of 4. With only Codex and with only Antigravity, 3 of the 4 cases that should consult did (all but the plan), each with the suggestion.

## Choosing a consultant

`ConsultantBudget` gathers what a choice of model and effort depends on, in one call that changes nothing:

- **Codex usage.** Each usage window on your Codex subscription (5-hour, weekly) with the percentage used, when it resets, and where the current pace lands at the reset, or when it runs out first. Also any free full resets your plan has; only you decide to use one. And the models your account offers, with their effort levels.
- **Antigravity's quota,** when `agy` is installed: each quota group's windows the same way, and the models agy lists with their levels.
- **Claude Code's own usage.** Claude Code tells only its status line how much of its 5-hour and weekly windows is used, so nouez reads a file the status line saves (below). Without it this part says "not known".
- **Model scores.** The [Artificial Analysis](https://artificialanalysis.ai) Intelligence Index for the top OpenAI, Google and Anthropic models, with API price and speed. Higher is smarter. Data from Artificial Analysis; credit it when you share it.

`ConsultantBudget` ends with the suggestion (see [How nouez picks a model](#how-nouez-picks-a-model)). Earlier versions of nouez asked you to copy a `consult` skill to `~/.claude/skills/consult/`. If you did, delete that copy: as your own skill it comes before nouez's suggestions, with older tables.

**Model scores need a free Artificial Analysis key.** Create an account at [artificialanalysis.ai](https://artificialanalysis.ai) and an API key (free tier, 100 requests a day). Set it as `ARTIFICIAL_ANALYSIS_API_KEY` in the environment Claude Code starts nouez from, for example as a user environment variable on Windows, or in the server's `env` when you register it:

```sh
claude mcp add consultants --scope user -e ARTIFICIAL_ANALYSIS_API_KEY=<your key> -- python /path/to/nouez/server.py
```

Use the same scope and path you registered nouez with (Setup step 2). If `consultants` is already registered, `claude mcp add` won't change it: remove it and add it again in the same scope, with the key (`claude mcp get consultants` shows the scope and command it has now):

```sh
claude mcp remove consultants --scope user
claude mcp add consultants --scope user -e ARTIFICIAL_ANALYSIS_API_KEY=<your key> -- python /path/to/nouez/server.py
```

Or set the variable where Claude Code starts: in your shell profile on macOS and Linux (`export ARTIFICIAL_ANALYSIS_API_KEY=...` in `~/.zshrc` or `~/.bashrc`, then start Claude Code from a new terminal), or as a user environment variable on Windows (`[Environment]::SetEnvironmentVariable('ARTIFICIAL_ANALYSIS_API_KEY', '<your key>', 'User')` in PowerShell). On Windows, nouez also reads the key from your saved user environment variables, so a key saved while Claude Code is running works once you reconnect `consultants` in `/mcp`; no restart needed. A key given with `-e` is stored in plain text in Claude Code's config (`~/.claude.json`, or `.mcp.json` for project scope, which you shouldn't commit with a key in it). Then `ConsultantBudget` should show "Model scores: Artificial Analysis Intelligence Index" with a list, not the "no Artificial Analysis key" note.

nouez then asks `artificialanalysis.ai/api/v2/language/models/free` (two or so pages) about once a week, with the key and `nouez/<version>` as the client name and nothing from your projects. The list is kept in `nouez/aa-models.json` in your cache folder. A failed attempt waits 6 hours before the next and the old list stays in use. `refresh: true` fetches again if the list is over an hour old; Claude passes it only when you ask for fresh scores.

**Claude Code's usage needs your status line to pass it on.** Claude Code passes `rate_limits` only to the status line command, as JSON on its stdin (on Pro and Max plans, after a session's first reply). `server.py statusline` reads that JSON, saves the usage to `nouez/claude-usage.json` in your cache folder and prints a short status line (the model and both windows). Every open session's status line runs it, some with older numbers, so it keeps the better reading of each window (the later window, and within the same window the higher percentage), each with the time it was seen, under a lock and through a temporary file. It never fails: a broken input or a busy file only skips the save.

If you have no status line yet, add this to `~/.claude/settings.json` (`%USERPROFILE%\.claude\settings.json` on Windows), inside its outer `{ }` beside any other settings, with your own paths and the `python` you registered nouez with. A new file holds just this:

```json
{
  "statusLine": { "type": "command", "command": "python3 \"/absolute/path/to/nouez/server.py\" statusline" }
}
```

On Windows: `"command": "python \"C:/Users/you/nouez/server.py\" statusline"`. Start a new session to see it. If you already have a status line script, keep it and pass its input on, with `--quiet` so only your script prints. In bash, read the input once at the top, give it to nouez, and have the rest of the script read `"$input"` instead of stdin:

```sh
input=$(cat)
printf '%s' "$input" | python3 "/absolute/path/to/nouez/server.py" statusline --quiet
# the rest of your script reads "$input", e.g. echo "$input" | jq ...
```

In PowerShell, the same with `$raw`:

```powershell
$raw = [Console]::In.ReadToEnd()
$raw | & python "C:/Users/you/nouez/server.py" statusline --quiet
$data = $raw | ConvertFrom-Json
```

The status line runs only while a Claude Code session is open, so the numbers are as of the last update; nouez shows how old they are and flags them after 30 minutes.

**The prompt hook acts on that usage before Claude starts work.** `ConsultantBudget` tells Claude how busy Claude Code is only once it has decided to consult. `server.py hook`, a `UserPromptSubmit` hook, adds one line to each prompt when Claude Code's saved usage, read within the last 30 minutes, is on pace past 70% of its week or a window runs out first. The line says what to hand to a consultant (see Claude Code's own week, above). Otherwise it adds nothing. It reads only nouez's saved usage file, never starts Codex or Antigravity, and always exits 0. It adds under a second to each prompt (about 0.7 s on a Windows test machine), mostly Python starting. `NOUEZ_NO_AUTO_CONSULT=1` silences it. Add it to the same settings file, inside `hooks` beside any others:

```json
{
  "hooks": {
    "UserPromptSubmit": [
      { "hooks": [ { "type": "command", "command": "python3 /absolute/path/to/nouez/server.py hook", "timeout": 5 } ] }
    ]
  }
}
```

`server.py doctor` says when either one is missing, and prints both entries with your own Python and paths. Doctor names Python bare when your PATH finds it, and quotes a path only if it has spaces: on Windows the hook may run in PowerShell, which prints a quoted first word instead of running it.

## A brief and a verdict

A template for `instructions`, or for the start of a message. Adapt it; it is only a starting point:

```text
Question: <the one thing to decide, e.g. "is this diff safe to merge?">
Context: <what changed and why; the files, diff or commit to read>
Scope: <what to look at, and what to leave out>
Done when: <the bar, e.g. "no correctness bugs; tests cover the new paths">

Answer with:
1. Verdict: yes, no, yes with changes, or incomplete if you couldn't read
   what you were given, in one line.
2. Findings, most serious first. For each: file and line, what goes wrong,
   and how you know (what you read or ran). Mark guesses as guesses.
3. What you didn't check.
You are read-only: describe changes, don't make them.
```

A verdict line first makes the reply easy to act on, and "what you didn't check" makes the gaps visible instead of leaving silence to read as approval.

## Tips

- **Give the consultant context.** A consultant can read the files in its own working directory, so start it in the same repo. Tell Claude to include the specific file, diff or question in the message; an Antigravity consultant can't run commands, so it needs the diff or output itself.
- **Give Claude standing instructions.** A line in your project's `CLAUDE.md` makes the workflow automatic, for example: *"Before committing non-trivial changes, ask the consultant to review the diff and address its findings. Reuse the existing consultant for this repo if there is one; otherwise start one."* (Say "the Codex consultant" only if you have Codex: it makes Claude ask for Codex by name.)
- **Change when Claude consults on its own.** It already does at four points (see the top of this page). Lines in `~/.claude/CLAUDE.md` apply in every project and override that, for example to leave research to Claude: *"Consult on your own only for reviews before commits and bug hunts; do research and long reads in this session."*
- **Give the consultant a brief and ask for a verdict.** `StartConsultant` takes standing `instructions`, and each message can carry its own brief. A brief that says what is being decided gets a more useful answer than a role. See [A brief and a verdict](#a-brief-and-a-verdict).
- **Pass on the user's words.** When Claude is acting on something you asked for, it can send your words with `owner_words`, kept apart from its own reading of them, so the consultant checks the work against what you said rather than against Claude's summary.
- **Review a branch against a base.** Send `revision: true` and, for example, `base: "origin/main"`. nouez uses the locally available ref and takes one diff from its merge base with HEAD to the working tree. This includes commits on the branch and uncommitted work. The consultant gets the base name, both commit ids, the branch and the number of uncommitted paths. The same exclusions and Antigravity attachment rules apply. The local send log records the supplied base alongside the patch digest when one is available.
- **Tie a review to a revision.** `revision: true` starts the message with the repo's commit, branch and number of uncommitted paths, and asks the consultant to name that revision in its answer, so a verdict can't be mistaken for one about a later state of the code. When there are uncommitted changes, nouez also takes their diff at that moment, untracked files included, saves it in its cache folder under its SHA-256 and names it, so the consultant reviews exactly that diff even if you keep editing, and two consultants given the same diff see the same digest. nouez writes nothing in the repo to do this, and runs none of its git hooks. An Antigravity consultant runs no commands, so it gets only the line unless you also pass `attach_diff: true`, which puts the diff in the message; its text then goes to Google, deleted lines and untracked files included. Binary files, untracked files over 256 KB and untracked files with a part of their path that looks like a secret (`.env`, keys, names with "secret", "token" or "password") are left out, and the line names them. When nouez can't take or save the diff, or it is too large for an Antigravity message or isn't UTF-8, the line says so, names no digest, and asks the consultant to review the working tree.
- **Run several consultants.** Start several, for example in different repos or with different models. `ListConsultants` shows each one's name and working directory so Claude can pick the right one.
- **Long tasks.** By default Claude waits 5 seconds after sending, enough to confirm delivery and catch a quick answer, then starts a small waiter in the background, tells you the consultation is under way, and is free again, and so are you. When the consultant finishes, the waiter exits with the reply and Claude Code wakes Claude with it, so Claude acts on the answer or reports it without you asking. Claude needs permission to run the waiter; see [Setup](setup.md#setup), step 5. nouez offers the waiter only to Claude Code; in another MCP client, Claude reads the reply later with `GetConsultantReply`.
- **Idle consultants.** After about a minute without activity, the Codex daemon unloads a Codex consultant. It still appears in `ListConsultants`, and the next message reloads it with the same sandbox and history.
- **Clean up.** Ask Claude to stop consultants when you're done, so they don't pile up in your Codex session list or in `ListConsultants`. Stopping archives a Codex session rather than deleting it; a `codex resume` you opened on it yourself stays open.

## Antigravity consultants

A consultant can also run on Google's Antigravity CLI (`agy`) and its Gemini models, so a second opinion can come from a third family of models and from Google's quota instead of the Codex subscription. When Codex isn't installed, `StartConsultant` uses Antigravity without being asked, and says so. With both installed, Claude starts one with `provider: "antigravity"` only when you ask or your own rules say when. Either way it is used with the same tools as a Codex consultant. It starts on `gemini-4-neon` at level `high`; `model` and `effort` pick another (`ConsultantBudget` lists the models), and `SendConsultantMessage` changes them for later messages while the conversation keeps its context. Any model agy lists works, including the Claude and GPT models Antigravity runs on Google's quota; those use that quota, not your Claude Code or Codex usage.

How it differs from a Codex consultant:

- **Read-only by agy's own rules.** Every turn runs `agy -p` with deny rules for file writes and edits, commands, MCP tools and URL actions, and with slash commands off. Its browser tools aren't available in this mode. It can read files, search and read web pages, but can't run `git diff` or the tests: Claude puts the diff or output it should judge in the message.
- **One message at a time.** Each message runs one agy turn in the background. A message sent while a turn runs is refused, with nothing sent, since agy can't steer a running turn; this holds across all your Claude Code sessions. Wait for the reply, or stop the consultant.
- **Its own CLI.** The status screen's consultations page gives the command to open its conversation in agy yourself: `agy --conversation <id>`, with agy's full path when it isn't on your `PATH`.
- **A 30-minute limit per turn.** A turn still running then ends with what it has, reported as interrupted.
- `StopConsultant` ends a running turn and forgets the consultant; its conversation stays in agy. With `turn_only` it ends the turn and keeps the consultant for the next message. It ends only the process nouez started (on Windows, checked by its start time and program). If it can't end it, nothing is stopped and it says so; send the stop again.

nouez keeps each consultant, and each turn's input and output, in `nouez/agy/` in your cache folder. Replies are logged with their token counts, which `server.py top` shows in the offload table's Antigravity column.
