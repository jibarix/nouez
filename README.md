# nouez

An MCP server that lets Claude Code consult live Codex sessions, and open, list and close Claude Code sessions on your computer, so you can start a new one from your phone.

## Why

Two coding agents look at a problem differently. This bridge gives each one a fixed role:

- **Claude Code is the main developer.** It plans, writes the code or text, and owns the work.
- **Codex is the consultant.** Claude asks it for second opinions: reviewing a plan, checking a diff, finding a bug, validating a claim, or gathering context for research. The consultant only reads; it never edits your files.

Without the bridge, you run two terminals and copy text between them. With it, Claude starts a Codex consultant in the background, sends it questions, reads the answers and keeps working, all from your single Claude Code terminal. If you prefer to watch Codex work, you can still open it yourself and Claude will talk to that session instead.

The same server also helps when you drive Claude Code from your phone with Remote Control: a session can open a new Claude Code session in another project on the computer, list the ones running, and close a stuck one (see [A new Claude Code session from your phone](#a-new-claude-code-session-from-your-phone)).

## Requirements

- Python 3.9+ (standard library only, nothing to install)
- [Claude Code](https://docs.claude.com/en/docs/claude-code)
- The [Codex CLI](https://github.com/openai/codex) on your `PATH`, logged in
- Optional: Google's Antigravity CLI (`agy`), signed in, for consultants on Gemini or another model it lists (see [Antigravity consultants](#antigravity-consultants))

### Tested with

The protocol between the bridge and Codex is experimental, so this is the last combination known to work. Newer versions will probably work too, but if something breaks, compare against this table.

| Component | Version |
|---|---|
| nouez | 0.15.2 |
| Claude Code | 2.1.330 |
| Codex CLI | 0.170.0 |
| Codex app-server daemon | 0.171.0 |
| Antigravity CLI (optional: Antigravity consultants, its quota) | 1.5.14 |
| Python | 3.11.9 |
| OS | Windows 11 |

Run `claude --version` and `codex --version` to see your versions. Codex updates its daemon by itself, so the daemon can be newer than the CLI; the folder under `~/.codex/packages/app-server-daemon/releases/` shows its version.

## Setup

**1. Get the code.**

```sh
git clone https://github.com/jibarix/nouez.git
```

**2. Register the server with Claude Code.** Use the absolute path to `server.py`:

```sh
# available in every project
claude mcp add --scope user consultants -- python /absolute/path/to/nouez/server.py

# or only in the current project
claude mcp add consultants -- python /absolute/path/to/nouez/server.py
```

On macOS/Linux, use `python3` if `python` isn't on your `PATH`. On Windows, use a path like `C:/Users/you/nouez/server.py`.

**3. Let Claude run the waiter.** Codex replies often take minutes, so Claude doesn't wait for them: it starts a small waiter command in the background, and the waiter wakes Claude with the reply when Codex finishes (see [Long tasks](#tips)). Claude Code asks before running a command it has no rule for, and in auto mode it may block one. To allow the waiter in every project, print its permission rules with the same `python` and path you registered:

```sh
python /absolute/path/to/nouez/server.py allow-rule
```

On Windows, quote a path that contains spaces: `python "C:/Users/you/My Projects/nouez/server.py" allow-rule`. It prints two rules, one for the Bash tool and one for the PowerShell tool. Add them to `permissions.allow` in `~/.claude/settings.json` (on Windows, `C:\Users\<you>\.claude\settings.json`), keeping anything already in the file. With no other permissions, the file looks like this:

```json
{
  "permissions": {
    "allow": [
      "Bash(C:/Python313/python.exe -I C:/Users/you/nouez/server.py wait *)",
      "PowerShell(C:/Python313/python.exe -I C:/Users/you/nouez/server.py wait *)"
    ]
  }
}
```

Instead of editing the file, you can approve the waiter the first time Claude Code asks and choose not to be asked again. The rules allow only this script's `wait` command with this interpreter, so auto mode keeps them. If you move nouez or change Python, run `allow-rule` again and replace them. Without them everything still works, but Claude Code asks each time, and if the waiter can't run Claude reads the reply only when you ask for it.

**4. Check it.** Run `claude mcp list`, or `/mcp` inside Claude Code. You should see `consultants` connected. Sessions that were already open keep the old server until you reconnect it there: `/mcp`, then reconnect `consultants`. Do the same after updating nouez (see [nouez updates](#nouez-updates)). A change to `settings.json` applies to sessions started after it.

## Usage

**1. Nothing to start.** If the Codex daemon isn't running (it stops when the computer restarts), the first tool call starts it, which adds a few seconds. To start it yourself, run:

```sh
codex app-server daemon start
```

**2. Work in Claude Code as usual.** Whenever you want a second opinion, ask for it in plain language:

> Start a Codex consultant for this project.

> Start a Codex consultant I can watch.

> Ask the consultant to review the plan you just wrote. Push back on anything you disagree with before changing it.

> Before you commit, send the diff to the consultant and ask it to look for bugs.

> We're stuck on this test failure. Ask the consultant for its diagnosis and compare it with yours.

> We're done. Stop the consultant.

Claude calls `StartConsultant` to create a background Codex session in your project (or reuses one already working there, see [Reusing a consultant](#reusing-a-consultant)), `SendConsultantMessage` to ask questions, and `StopConsultant` when you're finished. Each message reaches Codex prefixed with `[Message from Claude Code via the consultants bridge]`, and Claude gets the answer back as a tool result.

**The consultant is always read-only.** It can read your files and run read-only commands for auditing, validation and research, but it can't change anything. It never stops to ask for approvals, because no terminal is attached to answer them. Claude does all the writing. There is no option to give a consultant write access.

**3. Watch or join in (optional).** A background consultant is an ordinary Codex session. A consultant started by `StartConsultant` is shown automatically (pass `watch: false` to skip that); for a session you opened yourself, ask Claude to *"open the consultant in a terminal"* (`WatchConsultant`). Either way, `codex resume <id>` opens next to Claude Code: as a split pane in the same tab when Claude Code runs in Windows Terminal or tmux, otherwise in a new terminal window. You can read along there or type into the session yourself. Codex can't open a session before its first message, so the pane appears when Claude sends that message, and reappears on the next message if you close it. Without a split, Windows uses a new Windows Terminal window (falling back to a console window), macOS uses Terminal, and Linux uses `x-terminal-emulator`, `gnome-terminal` or `xterm`. In Windows Terminal the pane opens in the window running the Claude Code session that asked for it, even if you last used another window: nouez brings that window to the front while `wt` runs, then gives the focus back. If Claude Code's tab isn't the selected tab in its window, the consultant opens in a new tab there instead, and if the window can't be found or brought to the front (a locked screen, say), it opens in a new window of its own rather than in another session's. If a terminal already shows the session, no second one opens. The pane's `codex resume` trusts the session's folder for that run only, so Codex doesn't stop at "Trust this folder?" (nothing is saved to your Codex config; the folder's own `.codex` config and hooks load in the pane, as if you had answered yes), and it skips Codex's update check. A folder you marked untrusted in Codex stays so, and Codex asks as usual; so does every folder when nouez can't read Codex's config for sure. The window runs the Codex daemon's own `codex` binary when it can find it, so it matches the daemon's version; otherwise it falls back to the `codex` on your `PATH` and warns if the versions differ.

### Reusing a consultant

A consultant keeps its whole conversation until you stop it, so you can keep going back to the same one. Refer to it and Claude finds it with `ListConsultants`:

> Ask the consultant to check the diff.

> Send this to codex-myproject-a1b2c3: …

> Open the consultant so I can watch.

This works from a new Claude Code session too: consultants that went idle still appear in the list, and the next message reloads them. Reuse is the default. `StartConsultant` searches first: if a consultant it started earlier already works in the same project, it returns that one and starts nothing; if none is found, it starts one. It never picks a Codex session you opened yourself, even in the same project, because that session keeps your permissions; it lists such sessions in its result instead. `model`, `title` and `instructions` only apply when a new consultant is started. The project is the git repo; outside git, it's the Claude Code workspace folder (the folder you launched Claude Code in), so a subfolder finds the consultant started at the top. When you want a clean slate, ask for a new one, and Claude passes `new: true`:

> Start a new Codex consultant I can watch.

> Start a second consultant in ~/projects/other-repo and ask it to …

With more than one consultant running, name the one you mean. Once stopped, a consultant is archived and Claude can't reach it. To bring it back, run `codex unarchive <id>` (the id is in the stop message).

### Using a Codex session you opened yourself

If you'd rather see Codex work in its own window, open it yourself (`cd my-project && codex`) and ask Claude to *"list the consultants and send it …"*. Claude finds the session with `ListConsultants` and talks to it the same way. `StartConsultant` never chooses your session on its own, and `SendConsultantMessage` refuses it unless Claude passes `allow_user_session: true`, which it is told to do only when you ask. The message appears in that terminal as a new prompt. Sessions you open yourself use their own permission settings and approval prompts, and `StopConsultant` won't close them.

### A new Claude Code session from your phone

Driving Claude Code from the Claude app with Remote Control, you can ask the session for another one: *"open a new Claude session for C:/Users/me/Projects/other"*. Claude calls `OpenClaudeSession`, which opens a new terminal window on the computer and starts `claude --remote-control <name>` in that folder. The new session shows up in the app's session list a few seconds later. It is an ordinary session that saves its transcript and can be resumed. A `claude` you start from Claude Code's own shell doesn't save its transcript, because it inherits `CLAUDE_CODE_CHILD_SESSION` and the other variables that mark it as a child session. `OpenClaudeSession` starts it without them, keeping any variable you set yourself in your Windows environment. The folder can be a new one: *"open a new Claude session in a new folder C:/Users/me/Projects/economic-recession"* makes Claude pass `create: true`, and nouez creates it (its parent must exist). To pick up an earlier conversation, ask *"resume the latest hours-tracker session"*: Claude passes `resume: "latest"` (or a session id), and the window runs `claude --resume <id>` with Remote Control, so the conversation carries on where it stopped. "latest" is the newest conversation in that folder that no running session has open; a conversation already open in a running session is never opened twice. Claude Code's experimental Code Mode doesn't run with Remote Control, and a conversation held in Code Mode resumes only in a terminal with Code Mode on, so `resume` can't bring one back as a remote session.

Claude Code asks whether you trust a folder the first time it runs there, and a session waiting at that question can't connect to the app. So before opening a window, nouez checks Claude Code's settings (`~/.claude.json`). If the folder isn't trusted, nothing opens and Claude asks you whether you trust it. If you say yes, Claude calls it again with `trust: true`, and nouez records your answer in `~/.claude.json` the way Claude Code's trust dialog does, then opens the window, so this works from your phone. Before each change nouez saves a dated copy of the file (the newest 20 are kept, in `%LOCALAPPDATA%\nouez\claude-json-backups`, or `$XDG_STATE_HOME/nouez/claude-json-backups` elsewhere, by default `~/.local/state/nouez/claude-json-backups`) and the result names it. Only that one setting changes. If you're at the computer, Claude can instead open the window untrusted (`open_untrusted: true`) so you answer Claude Code's own question there. Trust works like Claude Code's: outside a git repository, trusting a folder covers the folders inside it, but a git repository is trusted on its own (for a worktree, its main checkout), so trusting `C:/Users/me/Projects` doesn't cover a repository in it. Even in a trusted folder Claude Code can still ask on the computer: a project's own `.claude/settings.json` allow rules need that folder itself trusted, not just a folder above it, and a project's `.mcp.json` servers have their own approval. The result mentions these when the files are there, and says when nouez can't tell whether a folder is trusted (Claude Code's settings can't be read, or the git layout is unusual).

To see what's running, ask any session *"which Claude sessions are open?"*. `ListClaudeSessions` lists the interactive Claude Code sessions registered in your Claude Code config folder, whoever started them, each with its name, folder, status and whether Remote Control is on. To close one, such as a stuck one, say which: *"close hours-tracker"*. `CloseClaudeSession` ends its `claude` process. A session `OpenClaudeSession` opened also gets its window closed; one you started yourself leaves its terminal at the shell prompt. The transcript stays, so `claude --resume` in that folder picks it up again. Claude shows you the list and closes only the sessions you pick, one call each, and never the one you're talking to. The list comes from `~/.claude/sessions`, which Claude Code keeps but doesn't document, so a future Claude Code version could change it.

### Choosing model and effort

A consultant uses the model and reasoning effort from your Codex config (`model` and `model_reasoning_effort` in `~/.codex/config.toml`). Claude can change either one for a hard question without starting over: `SendConsultantMessage` takes `model` and `effort`, the consultant keeps its context, and the setting stays for later messages until Claude sends the usual values again. nouez tells Claude to do this only when you ask, or when your own instructions say when. Which model suits which work is your call, so nouez doesn't decide it for you.

To have Claude route work this way without being asked, write your rules in `~/.claude/CLAUDE.md`. Claude Code reads that file in every project, so the rules apply wherever you use a consultant. A project's own `CLAUDE.md` covers only that project. A starting point to adapt (the model ids are examples; `/model` in Codex lists the ones your account offers):

```markdown
- **Model and effort routing.** Defaults: Claude Code on <model> at <effort>; Codex consultants on
  gpt-6.1-sol at high. Send research to a Codex consultant (StartConsultant, then
  SendConsultantMessage); for hard research across many sources, send that message with
  model "gpt-6-astra". When a result is poor, find out why before changing anything: missing
  information → fix the context or the prompt; steps skipped or rushed → raise effort one level;
  tried properly and still failed → a stronger model. Use the top effort levels only after the
  level below has failed. A consultant's model and effort stay set for later messages, so send
  the defaults again once the hard part is done.
```

### Choosing a consultant

`ConsultantBudget` gathers what a choice of model and effort depends on, in one call that changes nothing:

- **Codex usage.** Each usage window on your Codex subscription (5-hour, weekly) with the percentage used, when it resets, and where the current pace lands at the reset, or when it runs out first. Also any free full resets your plan has; only you decide to use one. And the models your account offers, with their effort levels.
- **Claude Code's own usage.** Claude Code tells only its status line how much of its 5-hour and weekly windows is used, so nouez reads a file the status line saves (below). Without it this part says "not known".
- **Model scores.** The [Artificial Analysis](https://artificialanalysis.ai) Intelligence Index for the top OpenAI, Google and Anthropic models, with API price and speed. Higher is smarter. Data from Artificial Analysis; credit it when you share it.

nouez reports; it doesn't choose. Your rules decide, in `~/.claude/CLAUDE.md` (see [Choosing model and effort](#choosing-model-and-effort)) or a skill. A `consult` skill to start from would sort consultations by kind (quick check, review, bug hunt, plan critique, research), give each a starting model and effort, then move up or down by what `ConsultantBudget` shows: for instance, one effort level down when Codex is on pace for over 90% of its week, and no consulting on a window that runs out before its reset.

**Model scores need a free Artificial Analysis key.** Create an account at [artificialanalysis.ai](https://artificialanalysis.ai) and an API key (free tier, 100 requests a day). Set it as `ARTIFICIAL_ANALYSIS_API_KEY` in the environment Claude Code starts nouez from, for example as a user environment variable on Windows, or in the server's `env` when you register it:

```sh
claude mcp add consultants --scope user -e ARTIFICIAL_ANALYSIS_API_KEY=<your key> -- python /path/to/nouez/server.py
```

On Windows, nouez also reads the key from your saved user environment variables, so a key saved while Claude Code is running works once you reconnect `consultants` in `/mcp`; no restart needed.

nouez then asks `artificialanalysis.ai/api/v2/language/models/free` (two or so pages) about once a week, with the key and `nouez/<version>` as the client name and nothing from your projects. The list is kept in `nouez/aa-models.json` in your cache folder. A failed attempt waits 6 hours before the next and the old list stays in use. `refresh: true` fetches again if the list is over an hour old; Claude passes it only when you ask for fresh scores.

**Claude Code's usage needs one addition to your status line.** Claude Code passes `rate_limits` to the status line command as JSON (on Pro and Max plans, after a session's first reply). Have your status line script save it, with the time, to `nouez/claude-usage.json` in your cache folder: `{"saved": <unix seconds>, "rate_limits": <as received>}`. Every open session's status line writes this file, and a session that hasn't heard from Claude Code lately holds older numbers, so keep the newer reading: for each window, the later window, and within the same window the higher percentage. Write it to a temporary file and rename it, so nouez never reads half a file, and never let a failure here break the status line. In PowerShell:

```powershell
if ($null -ne $data.rate_limits -and $env:LOCALAPPDATA) {
    try {
        $dir = Join-Path $env:LOCALAPPDATA 'nouez'
        if (-not (Test-Path $dir)) { New-Item -ItemType Directory -Force $dir | Out-Null }
        $file = Join-Path $dir 'claude-usage.json'
        # Every open session writes this file, some with older numbers. Per window, keep the later
        # window, and within the same window (resets within 10 min) the higher percentage.
        $limits = @{}
        foreach ($p in $data.rate_limits.PSObject.Properties) { $limits[$p.Name] = $p.Value }
        $saved = $null
        try { $saved = [IO.File]::ReadAllText($file) | ConvertFrom-Json } catch {}
        if ($null -ne $saved -and $null -ne $saved.rate_limits) {
            foreach ($k in @('five_hour', 'seven_day')) {
                $old = $saved.rate_limits.$k; $new = $limits[$k]
                if ($null -eq $old -or $null -eq $old.resets_at -or $null -eq $old.used_percentage) { continue }
                if ([double]$old.resets_at -le [DateTimeOffset]::UtcNow.ToUnixTimeSeconds()) { continue }
                if ($null -eq $new -or $null -eq $new.resets_at -or $null -eq $new.used_percentage) { $limits[$k] = $old; continue }
                $gap = [double]$old.resets_at - [double]$new.resets_at
                if ($gap -gt 600 -or ([math]::Abs($gap) -le 600 -and [double]$old.used_percentage -gt [double]$new.used_percentage)) {
                    $limits[$k] = $old
                }
            }
        }
        $json = @{ saved = [DateTimeOffset]::UtcNow.ToUnixTimeSeconds(); rate_limits = $limits } | ConvertTo-Json -Depth 5 -Compress
        $tmp = Join-Path $dir "claude-usage.$PID.tmp"
        [IO.File]::WriteAllText($tmp, $json, (New-Object System.Text.UTF8Encoding $false))
        Move-Item -Force $tmp $file
    } catch { if ($tmp) { Remove-Item -Force -ErrorAction SilentlyContinue $tmp } }
}
```

Here `$data` is the status line's input (`$data = [Console]::In.ReadToEnd() | ConvertFrom-Json`). The status line runs only while a Claude Code session is open, so the numbers are as of the last update; nouez shows how old they are and flags them after 30 minutes.

### A brief and a verdict

A template for `instructions`, or for the start of a message. Adapt it; it is only a starting point:

```text
Question: <the one thing to decide, e.g. "is this diff safe to merge?">
Context: <what changed and why; the files, diff or commit to read>
Scope: <what to look at, and what to leave out>
Done when: <the bar, e.g. "no correctness bugs; tests cover the new paths">

Answer with:
1. Verdict: yes, no, or yes with changes, in one line.
2. Findings, most serious first. For each: file and line, what goes wrong,
   and how you know (what you read or ran). Mark guesses as guesses.
3. What you didn't check.
You are read-only: describe changes, don't make them.
```

A verdict line first makes the reply easy to act on, and "what you didn't check" makes the gaps visible instead of leaving silence to read as approval.

### Tips

- **Give Codex context.** Codex can read the files in its own working directory, so start it in the same repo. Tell Claude to include the specific file, diff or question in the message.
- **Give Claude standing instructions.** A line in your project's `CLAUDE.md` makes the workflow automatic, for example: *"Before committing non-trivial changes, ask the Codex consultant to review the diff and address its findings. Reuse the existing consultant for this repo if there is one; otherwise start one."*
- **Give the consultant a brief and ask for a verdict.** `StartConsultant` takes standing `instructions`, and each message can carry its own brief. A brief that says what is being decided gets a more useful answer than a role. See [A brief and a verdict](#a-brief-and-a-verdict).
- **Pass on the user's words.** When Claude is acting on something you asked for, it can send your words with `owner_words`, kept apart from its own reading of them, so the consultant checks the work against what you said rather than against Claude's summary.
- **Tie a review to a revision.** `revision: true` starts the message with the repo's commit, branch and number of uncommitted paths, and asks the consultant to name that revision in its answer, so a verdict can't be mistaken for one about a later state of the code.
- **Run several consultants.** Start several, for example in different repos or with different models. `ListConsultants` shows each one's name and working directory so Claude can pick the right one.
- **Long tasks.** By default Claude waits 5 seconds after sending, enough to confirm delivery and catch a quick answer, then starts a small waiter in the background, tells you the consultation is under way, and is free again, and so are you. When Codex finishes, the waiter exits with the reply and Claude Code wakes Claude with it, so Claude acts on the answer or reports it without you asking. Claude needs permission to run the waiter; see [Setup](#setup), step 3.
- **Idle consultants.** After about a minute without activity, the Codex daemon unloads a consultant. It still appears in `ListConsultants`, and the next message reloads it with the same sandbox and history.
- **Clean up.** Ask Claude to stop consultants when you're done, so they don't pile up in your Codex session list. Stopping archives a session rather than deleting it, and closes its watch window. On Windows, only windows the bridge opened are closed. On macOS and Linux, any `codex resume <id>` process for that session is ended, and a macOS Terminal window stays open at a shell prompt.

### Antigravity consultants

A consultant can also run on Google's Antigravity CLI (`agy`) and its Gemini models, so a second opinion can come from a third family of models and from Google's quota instead of the Codex subscription. Claude starts one with `StartConsultant` and `provider: "antigravity"`, only when you ask or your own rules say when, and then uses it with the same tools as a Codex consultant. It starts on `gemini-4-neon` at level `high`; `model` and `effort` pick another (`ConsultantBudget` lists the models), and `SendConsultantMessage` changes them for later messages while the conversation keeps its context. Any model agy lists works, including the Claude and GPT models Antigravity runs on Google's quota; those use that quota, not your Claude Code or Codex usage.

How it differs from a Codex consultant:

- **Read-only by agy's own rules.** Every turn runs `agy -p` with deny rules for file writes and edits, commands, MCP tools and URL actions, and with slash commands off. Its browser tools aren't available in this mode. It can read files, search and read web pages.
- **One message at a time.** Each message runs one agy turn in the background. A message sent while a turn runs is refused, with nothing sent, since agy can't steer a running turn; this holds across all your Claude Code sessions. Wait for the reply, or stop the consultant.
- **No pane.** `WatchConsultant` gives the command to open its conversation in agy yourself (`agy --conversation <id>`) instead.
- **A 30-minute limit per turn.** A turn still running then ends with what it has, reported as interrupted.
- `StopConsultant` ends a running turn and forgets the consultant; its conversation stays in agy. It ends only the process nouez started (on Windows, checked by its start time and program). If it can't end it, nothing is stopped and it says so; send the stop again.

nouez keeps each consultant, and each turn's input and output, in `nouez/agy/` in your cache folder. Replies are logged with their token counts, which `server.py top` shows in the offload table's Antigravity column.

### Usage log and status screen

nouez notes each consultation in `nouez/usage-log.jsonl` in your cache folder (`%LOCALAPPDATA%` on Windows, `~/.cache` elsewhere), one JSON line per event:

- **start:** a consultant started or reused, with its project and model.
- **send:** a message: the consultant, project, model and effort, which of those it changed, whether it steered a running turn, `kind` and `reason` if Claude gave them, its length in characters, whether it quoted your words, and each subscription's usage at that moment (as `ConsultantBudget` would show it).
- **reply:** how the turn ended: status, time taken, length, and the verdict read from the reply's first line (`yes`, `changes` or `no`); for an Antigravity consultant, also its token counts.

Events of Antigravity consultants carry `provider: "antigravity"`, and their sends also record Antigravity's quota at that moment.

It never holds the text of a message or reply. Past 20 MB it is renamed with the date and a new one starts. Set `NOUEZ_NO_USAGE_LOG=1` in nouez's environment to turn it off.

To see it, with the usage of each subscription, run in a terminal:

```sh
python /path/to/nouez/server.py top
```

It shows:

- **Usage:** each Codex and Claude Code window, with a bar, the reset, and where the pace lands at the reset (red when used up or running out first, yellow over 90%). Codex is read live from the daemon once a minute; without the daemon, from Codex's last session file. Claude Code's comes from the status line file (see [Choosing a consultant](#choosing-a-consultant)). If the Antigravity CLI (`agy`) is installed, on your `PATH` or where its installer puts it on Windows, each of its quota groups too, read once a minute with `agy -p /usage`, which runs no model turn and uses no quota. The "AG Claude+GPT" group is Claude and GPT models run inside Antigravity on Google's quota, apart from Claude Code's.
- **Consultations:** messages sent, steered and with a changed model or effort; counts by model, kind, project and verdict; the median and slowest reply times; and review loops that went past three CHANGES rounds in a row.
- **Offload:** for each of the last 8 weeks, the output tokens of Claude Code (and its subagents) beside those of nouez's Codex consultants, of your own Codex sessions and of Antigravity consultants (from the usage log), and the share done outside Claude Code; then Claude Code's output by model. These come from the Claude Code transcripts (`~/.claude/projects`) and Codex session files (`~/.codex/sessions`) on this computer. The first run reads the last 13 weeks of them, which can take a minute; the counts are kept in `nouez/usage-weeks.json` and later runs read only what was added.

Keys: `1`, `7`, `3` or `a` to show 1, 7 or 30 days of consultations or all of them; `r` to refresh now; `q` or Esc to quit. `--days N` picks the period to start with (0 for everything, up to 65535), and `--once` prints one screen and exits. When `server.py` is updated, the screen starts again on the new version by itself, with the same period, so its header always shows the version installed. It waits until the new file has stopped changing, compiles and still holds the status screen; if the new screen fails all the same, the window waits for the next update instead of closing. Nothing leaves your computer.

## Tools

| Tool | What it does |
|---|---|
| `StartConsultant` | Starts a background Codex session in a project directory (always read-only; never asks for approvals). If a consultant it started already works in that project, returns it and starts nothing unless `new: true`. Never reuses a session you opened yourself. Says so if a newer nouez is out (see [nouez updates](#nouez-updates)), or if the Codex CLI or daemon is out of date (see [Codex updates](#codex-updates)). |
| `ListConsultants` | Lists Codex sessions loaded on the local daemon, plus recent `StartConsultant` sessions it has unloaded, with each one's name, working directory, model, status and who started it. With `cwd`, only the sessions in that repo. |
| `SendConsultantMessage` | Sends a message into a session, waits 5 seconds by default, and returns the reply if it is ready by then, or the turn id and a waiter command if not. If the session is idle the message starts a new turn; if it's busy it steers the running turn. Unloaded sessions are reloaded first. Refuses a session you opened yourself unless `allow_user_session: true`. |
| `GetConsultantReply` | Reads a reply without sending anything: the latest turn, or a specific turn id. Use it after sending with `wait: 0` or after a timeout. While the turn runs, it shows the output so far. With `offset`, reads a long reply from that character on. |
| `GetConsultantHistory` | Lists a consultant's recent turns, newest first, one line each: turn id, status, when, how long, who sent it, and the first line of the message and of the reply. Reads only. |
| `WatchConsultant` | Opens a session in a split pane beside Claude Code, or a new terminal window, so you can watch it or type into it. Does nothing if a terminal already shows it. |
| `OpenClaudeSession` | Opens a new terminal window running an interactive Claude Code session with Remote Control in `cwd` (required), named `name` (default: the folder's name), optionally with a first `prompt`, or picking up an earlier conversation held in that folder with `resume` (a session id, or `latest`). It starts on Opus (`model`, default `opus`, the latest Opus) at medium effort (`effort`: `low`, `medium`, `high`, `xhigh` or `max`); Claude passes others only when you ask. The session saves its transcript like one you started yourself. `create: true` makes the folder if it doesn't exist. In a folder Claude Code hasn't been trusted in, it opens nothing unless `trust: true` is given (you said you trust the folder: nouez records that, after a backup) or `open_untrusted: true` (it opens a session that waits at the trust question). In a trusted folder it then checks for up to 30 seconds that the new session is running and connected to Remote Control, and says if another session was already running in that folder. |
| `ListClaudeSessions` | Lists the interactive Claude Code sessions registered in your Claude Code config folder: name, process id, folder, status, Remote Control, and which one is the caller. |
| `CloseClaudeSession` | Closes one of them by `name` (or `pid` when names repeat), keeping its transcript. Never the caller. |
| `ConsultantBudget` | Shows the usage left on your Codex subscription and Claude Code's own and, with `agy` installed, Antigravity's quota groups, with reset times and pace; the Codex and Antigravity models and their levels; and Artificial Analysis model scores. Reads only; see [Choosing a consultant](#choosing-a-consultant). |
| `StopConsultant` | Archives a session that `StartConsultant` started and closes the terminal panes nouez opened for it (a terminal you opened yourself stays open). Needs the exact name or full thread id. Refuses sessions you opened yourself. |

`StartConsultant` arguments (all optional):

| Argument | Default | Meaning |
|---|---|---|
| `cwd` | Claude Code's first workspace folder | Absolute path of the project Codex works in |
| `model` | your Codex config | Codex model (new sessions only) |
| `title` | | Session title shown in Codex (new sessions only) |
| `instructions` | | Standing instructions for the consultant's role (new sessions only) |
| `watch` | `true` | Show the session in a pane beside Claude Code once it has its first message, and again on later messages if the pane was closed |
| `new` | `false` | Start a new session even though a consultant already works in this project |
| `provider` | `codex` | `antigravity` for a consultant on the Antigravity CLI (see [Antigravity consultants](#antigravity-consultants)) |
| `effort` | `high` | Antigravity only: the model level of a new consultant |

`SendConsultantMessage` arguments:

| Argument | Required | Default | Meaning |
|---|---|---|---|
| `to` | yes | | Session name from `ListConsultants` (e.g. `codex-myproject-a1b2c3`), full thread id, or unique id prefix/suffix. `name` is accepted as an alias. |
| `message` | yes | | The text to send |
| `from` | no | `Claude Code` | Sender label shown to Codex |
| `owner_words` | no | | The user's own words, as they typed them. Sent first and marked off, with the rest of the message labelled as the sender's. Claude passes it only when it has the user's words to quote |
| `revision` | no | `false` | Start the message with the git commit, branch and number of uncommitted paths in the consultant's folder, and ask the consultant to name that revision in its answer |
| `model` | no | unchanged | Codex model id, e.g. `gpt-6-astra`, for this message and later ones. The consultant keeps its context. Refused, with nothing sent, while nouez sees the consultant mid-turn |
| `effort` | no | unchanged | Codex reasoning effort (such as `low`, `medium`, `high` or `xhigh`; the levels depend on the model) for this message and later ones; send the usual value again to go back. Refused, with nothing sent, while nouez sees the consultant mid-turn |
| `wait` | no | `5` | How long to wait for the reply: seconds (`0` returns once the message is delivered), or `"done"` to wait until the turn ends. Capped at 4 hours |
| `allow_user_session` | no | `false` | Allow sending to a session you opened yourself. Claude sets it only when you ask |
| `kind` | no | | What the consultation is for: `quick-check`, `re-check`, `review`, `bug-hunt`, `plan-critique`, `research`, `fact-check` or `other`. Kept only in the [usage log](#usage-log-and-status-screen); anything else is refused, with nothing sent |
| `reason` | no | | A short sentence on why this model and effort, for the usage log (cut at 300 characters) |

`GetConsultantReply` takes `to`, an optional `turn_id` (default: the latest turn; looked up among the 100 most recent turns), an optional `wait` like `SendConsultantMessage`'s, but defaulting to `0`, which returns at once if the turn is still running, and an optional `offset`: a character position in a finished reply to read from. A reply read with `offset` comes back in pieces of up to 60,000 characters, each ending with the offset to read on from.

`GetConsultantHistory` takes `to` and an optional `limit` (default 20, up to 100). The sender is the `from` label of a message sent through nouez, or "someone in the Codex pane" for one typed there. A turn with no message isn't anyone's: when a Codex daemon restart (an automatic update, say) cuts a turn off, the restarted daemon carries it on in a new turn with no message, listed as "Codex carrying on the work of turn …, with no new message".

Most replies take longer than the default 5 seconds. Claude is told not to wait for them. Instead the result gives a waiter command, `python server.py wait <thread_id> <turn_id>` with full paths, which Claude runs as a background command (the Bash or PowerShell tool with `run_in_background`). A path is quoted only if it contains a space, so the command runs as is in either shell and the permission rules from `allow-rule` match it. The waiter checks the turn every 1.5 seconds; when the turn ends it prints the reply (cut at 20,000 characters, with the rest saved to a file) and exits, and Claude Code wakes Claude with that output. Claude Code stops a background command after 30 minutes by default, so after 25 minutes the waiter exits on its own with the output so far and the same command to run again, and Claude starts a new one. It rides out up to three failed connections in a row, such as a daemon restart. A restart interrupts the running turn and Codex carries it on in a new one; the waiter, `GetConsultantReply` and a waiting send follow it there, and the waiter says so with the reply, naming the daemon's old and new version if it changed. In a client that can't run background commands, Claude reads the reply later by calling `GetConsultantReply` with the returned `turn_id`, which returns at once. If you would rather have Claude wait, ask it to; it then passes `wait: "done"`, and the call returns when the turn ends (checked every 1.5 seconds), on an error, or after 4 hours. Claude Code keeps such a call in the foreground for about two minutes before moving it to the background. A "still working" result is never a reply. It shows the turn's output so far (the latest 4,000 characters written since the last message reached it), labelled as a snapshot that may change.

While a call waits, nouez sends MCP progress notifications (`notifications/progress`, at most one every 10 seconds) naming the turn, the time so far and the latest line of output, when the client asked for them with a progress token. Claude Code 2.1.295 asks but doesn't display them.

If waiting fails after a message was delivered, the error starts with `Delivered to`, so Claude knows not to send it again.

Replies longer than 60,000 characters are cut there. The full text is saved to `nouez/<turn id>.md` in the system temp folder, and the cut reply ends with that path and the `GetConsultantReply` offset to read the rest.

When `StartConsultant` reuses a consultant, its result says when the consultant started, how many turns it has had, and what its last turn was, so Claude can tell whether it is still the right one or a fresh one is wanted. `SendConsultantMessage` says which model and effort the consultant runs on. A turn that failed inside Codex (a dropped connection, for example) is reported as such: sending the message again is safe, since the consultant keeps its context.

`WatchConsultant` and `StopConsultant` take only `to`. `StopConsultant` doesn't accept an id prefix or suffix, so a typo can't stop the wrong session. `ListConsultants` takes an optional `cwd` to list only the sessions whose working directory is in that path's git repo (outside a repo: under the Claude Code workspace folder that contains the path, or under the path itself), and an optional `include_all` (default `false`, ignored with `cwd`) to also show Codex-internal threads such as subagents.

`wait` replaced `until_done`, `timeout_seconds` and the boolean `wait` in 0.4.0; the old arguments get an error that names the new form, and nothing is sent.

Boolean arguments take `true`/`false` (or the strings `"true"`/`"false"`); any other value is an error rather than a guess.

### nouez updates

When a newer nouez is released on GitHub, `StartConsultant` adds a notice to its result with a link to the release notes. Claude tells you about it and goes on with the consultation. Ask Claude to update and it runs `git -C '<your nouez folder>' pull --ff-only` in that same session. If git fails (local changes, a conflict, or your copy has commits GitHub doesn't), Claude stops there, shows you what git said and doesn't discard anything. Only after the pull succeeds does it ask you to run `/mcp` and reconnect `consultants` to load the new version. (If the folder's name has a `'` in it, Claude asks you to run the pull yourself.) Your consultants keep their Codex sessions. Other open Claude Code sessions keep the old version until you reconnect there too.

To find out, nouez asks GitHub for the latest release (`api.github.com/repos/jibarix/nouez/releases/latest`). It sends no sign-in and nothing from your projects or sessions: GitHub sees an HTTPS request from your IP address with `nouez/<version>` as the client name, at the time the server starts, through your proxy if you have one set. An answer is reused for 24 hours and a failed attempt waits an hour before the next, kept in `nouez/latest-release.json` in your cache folder (`%LOCALAPPDATA%` on Windows, `$XDG_CACHE_HOME` or `~/.cache` elsewhere); servers that start at the same moment may each ask. The request runs in the background when the server starts, and each network step gives up after 3 seconds, so no tool waits for it; if you're offline there is simply no notice. The notice is given once per server process. To turn the check off, set the environment variable `NOUEZ_NO_UPDATE_CHECK=1`.

You can also watch the repository on GitHub (Watch → Custom → Releases) to get an email for each release.

### Codex updates

When the `codex` CLI on your `PATH` or the app-server daemon is older than the latest Codex release, `StartConsultant` adds a notice to its result. Claude tells you about it and goes on with the consultation. The latest version comes from `version.json` in your Codex home, the cache Codex keeps for its own update check, so nouez makes no network request. If that file is missing, or you dismissed that version in Codex, there is no notice. The notice is given once per server process (normally once per Claude Code session). nouez doesn't update anything itself. Ask Claude to update and it runs `codex update` for the CLI and `codex app-server daemon update` for the daemon. Updating the daemon may interrupt running Codex work, including consultants and your own sessions.

On Windows, if `codex app-server daemon update` fails with `Cannot connect to C: resolve failed`, the daemon was started from Git Bash and its updater found GNU tar instead of Windows' tar. nouez 0.7.1 and later start the daemon without Git Bash's environment. For a daemon started some other way, run `codex app-server daemon stop` and then `codex app-server daemon start` from PowerShell or cmd, then update again.

## Troubleshooting

To check the setup, run `python /absolute/path/to/nouez/server.py doctor`. It prints one line per check (Python, the Codex CLI and daemon, the waiter's allow rules, Windows Terminal, `claude`) and says what to fix. It changes nothing, though checking the daemon starts it if it isn't running.

| Message | Fix |
|---|---|
| `` `codex` CLI not found on PATH `` | Install the Codex CLI, or make sure the shell that launches Claude Code can find it. |
| `Codex app-server daemon is not reachable, and starting it did not help` | Run `codex app-server daemon start` in a terminal to see why it fails, or open a Codex session. |
| `No Codex sessions` | Ask Claude to start a consultant, or open Codex in a terminal. |
| `'x' is ambiguous` | Use the full name or thread id from `ListConsultants`. |
| `'x' names more than one session` | Two sessions share a name (names keep only the last six characters of the id). Use the full thread id. |
| `No Codex session named 'x'. Use its exact name or full thread id.` | `StopConsultant` matches exactly. Pass the name or full id from `ListConsultants`. |
| `` `x` must be true or false `` | A boolean argument got some other value. Pass `true` or `false`. |
| `` `wait` must be a number of seconds `` | Pass seconds (`0` or more) or `"done"`. |
| `no reply within 5s` | Codex is still working; any output shown is not the reply. This is normal for the default 5-second wait. Claude starts a waiter that brings the reply back when it is ready. |
| Claude Code asks before running `server.py wait`, or auto mode blocks it | The waiter has no permission rule. Add the rules that `python server.py allow-rule` prints (see [Setup](#setup), step 3), then start a new session. Meanwhile, ask Claude for the reply with `GetConsultantReply`. |
| `is a Codex session the user opened` | `SendConsultantMessage` refuses your own sessions by default. Ask Claude to message it if you mean to; it then passes `allow_user_session: true`. |
| `` `until_done` was replaced by `wait` `` | The caller used a pre-0.4 argument. Reconnect the server (`/mcp`) so Claude sees the new tool definitions. |
| `Delivered to ..., but waiting for the reply failed` | The message reached Codex; only the wait failed. Don't resend it. Read the reply with `GetConsultantReply`. |
| `was not started by StartConsultant` | That's a session you opened yourself. Close it from its own terminal. |
| The terminal window opens but shows an error | Make sure `codex` is on the `PATH` of new terminals, and that the session has had its first message. |
| The terminal window asks to restart the daemon ("incompatible feature set") | The window's `codex` is a different version from the daemon. Choose **Cancel**: restarting interrupts running consultants, and running without the daemon shows a separate copy of the session. The bridge normally avoids this by using the daemon's own binary; if it warned that it couldn't find it, update the Codex CLI to the daemon's version. |
| The consultant's pane opened in a new window instead of beside Claude Code | nouez couldn't find Claude Code's Windows Terminal window, or couldn't bring it to the front (a locked screen, or a program that isn't responding has the focus), so it used a new window rather than another session's. |
| `cwd must be the absolute path of an existing folder` | `OpenClaudeSession` needs a full path to a folder that exists. |
| A new session doesn't appear in the Claude app | It may be waiting at Claude Code's trust prompt on the computer. The result warns when the folder isn't trusted, and says so when Claude Code's settings couldn't be read. Answer the prompt there, or tell Claude you trust the folder so it can record that. A trusted folder can still ask there before connecting the project's `.mcp.json` servers, or about its `.claude/settings.json` allow rules when only a folder above it is trusted; the result notes these. Also check that `claude` is on the `PATH` of new terminals; if not, the new window says so. When the result says the session is connected, the app's list may just be slow to update: refresh it. |
| `No running Claude Code session matches` | The name must match exactly. The error lists the sessions that are running. |
| `That is the session you are running in` | `CloseClaudeSession` never closes its caller. Ask another session to close it, or quit it with `/exit`. |
| Anything else after updating Codex | Compare your versions with the [Tested with](#tested-with) table. The Codex app-server protocol may have changed. |

## How it works

`codex app-server proxy` relays stdio to the daemon's control socket, which speaks JSON-RPC over WebSocket. The server does the WebSocket handshake and framing itself, opens one short-lived connection per tool call, and polls the turn until it finishes. Sessions the bridge starts are tagged with `threadSource: "nouez"`, so it can find them again after the daemon unloads them and so `StopConsultant` knows which ones it may archive.

For the Claude Code session tools, nouez doesn't talk to Claude Code at all. `OpenClaudeSession` opens a terminal window that runs `server.py claude`, which clears the variables Claude Code sets to tie its commands to its session and starts `claude --remote-control`. It runs the `claude` on your `PATH`, never one in the project folder. `ListClaudeSessions` reads the registry Claude Code keeps in `~/.claude/sessions`. On Windows it checks that each process is still the one that wrote its entry; elsewhere only that the process exists. `CloseClaudeSession` ends the chosen process. [docs/architecture.pdf](docs/architecture.pdf) has the details.

## Tests

The protocol tests use only the standard library and don't need Codex. From the repo root:

```sh
python -m unittest discover tests
```

## Security note

- Every Claude Code session with this server enabled can send messages into **any** Codex session on the machine, and those messages run with that session's permissions and sandbox settings. Enabling the server gives Claude the ability to drive your Codex sessions. If you register the server with `--scope user`, this applies to every project you open in Claude Code.
- Consultants started by the bridge never ask for approvals, so their read-only sandbox is the only limit. They can't edit files, but they can read anything the sandbox allows, which typically includes files outside `cwd`. Write access can't be requested through the bridge. A session you open yourself keeps its own permissions, and messages sent to it run with them.
- `CloseClaudeSession` can end **any** Claude Code session running under your account on the computer, including ones you started yourself; only its caller is refused. Claude is told to close only sessions you pick from the list. The transcript is kept, but work in progress in that session (a running command, an unsent message) is lost.
- `OpenClaudeSession` starts Claude Code with your normal settings and permissions in the folder you name. Its first prompt, if any, is passed through a temporary file that the new window deletes once it has read it, so it stays off Windows Terminal's command line (it still becomes an argument of the `claude` process).
- Trusting a folder lets its Claude Code settings, hooks and MCP servers run. `OpenClaudeSession` records trust only with `trust: true`, which Claude is told to pass only when you've said you trust that folder; it never approves MCP servers. It changes nothing else in `~/.claude.json`, but Claude Code sessions rewrite that file all the time, and nothing outside Claude Code can lock it: nouez checks the file hasn't changed just before replacing it and reads the change back after, but a session saving in that same instant could still lose a setting. That's what the dated backups are for.
- `ConsultantBudget` sends your Artificial Analysis key, if you set one, to `artificialanalysis.ai` over HTTPS about once a week. It reads `nouez/claude-usage.json` from your cache folder but never writes it.
- The `nouez` tag is a guard against mistakes, not a security boundary. Any local program that can reach the Codex daemon can set the same tag, and can archive sessions directly anyway.

## Limitations

- Local only: it talks to the Codex daemon on the same machine, and opens and closes Claude Code sessions on the same machine.
- `ListClaudeSessions` reads `~/.claude/sessions` (under `CLAUDE_CONFIG_DIR` if you set it), which Claude Code keeps but doesn't document. A Claude Code update could change it. On Windows a session is listed only if its entry records when its process started, so an entry can't point at an unrelated process that reused the pid.
- In Windows Terminal, the moment between bringing Claude Code's window to the front and `wt` opening the pane is short but not locked: if you click another window in that instant, the pane can land there. Two tabs with the same title in one window can't be told apart, so the pane may split the other one.
- Finding Claude Code's own Windows Terminal window, and closing a session's window, are Windows-only. Elsewhere the pane opens as before, and a closed session's terminal stays open.
- Telling the caller's own session apart is thorough only on Windows, where nouez walks the whole chain of parent processes. Elsewhere it knows only its immediate parent, so if a wrapper sits between Claude Code and nouez, `CloseClaudeSession` may not recognise the caller.
- Nothing can start a session on the computer from your phone unless something there is already running and connected: an open Claude Code session with Remote Control, for instance.
- The trust check reads git's files, not Claude Code's code. For a worktree whose git data was moved out with `--separate-git-dir`, it says it can't tell, except when that git folder is named `.git` and sits beside other files: then nouez, like `git worktree list`, takes that folder for the main checkout.
- `ConsultantBudget` names models as Artificial Analysis does ("GPT-6.2 Sol (high)"), not by Codex model id; matching them is left to Claude. Artificial Analysis scores API access at set effort levels, which may differ from a subscription's.
- `server.py top` counts tokens from Claude Code's transcripts and Codex's session files, which neither documents; an update to either could change them. Output tokens only: a reply's input and cached tokens aren't counted.
- `server.py top` runs the screen under a small process that restarts it on an update. That process keeps its own version until you close the window. A file changed again just as the screen restarts runs unchecked; if it fails, the window waits for the next update.
- On macOS and Linux, `StopConsultant` checks a pane's program and command line, token included, just before it signals it, but by process id: if the pane ends in that instant and its number goes to another `codex` run the same way, that one is ended. Unix has no handle that rules this out on macOS.
- If you stop an Antigravity consultant and the nouez server quits in the middle of the stop, a turn whose agy later fails on its own can read as stopped rather than failed.
- Codex 0.171 lets one app at a time hold a conversation, so a pane that opens while the consultant's turn runs shows "This conversation is open in another app". Press `r` in the pane once the turn is done and it shows the conversation.
- An Antigravity consultant can't be kept from agy's `schedule` tool: agy has no deny rule or setting for it. Scheduling changes no files, but it can keep a turn waiting until the 30-minute limit. nouez tells the model not to schedule anything. agy's `-p` mode and its event stream aren't documented as stable; an agy update could change them.
- Elsewhere than Windows, only the nouez server that started an Antigravity turn can tell its process is still agy, so after a reconnect, or from another session, `StopConsultant` won't end it; it ends at agy's 30-minute limit. There, too, that server keeps its turns' processes by process id alone, and a status check can reap an ended one just as a stop signals it; the time between is very short, and the stop signals only processes it started. nouez doesn't guard against a relative entry in `PATH` that finds `agy` inside the consultant's folder, or against links placed in its cache folder; both need someone who can already change your files.
- If nouez can neither save a new Antigravity turn's process id nor end that process (a full disk, say), it says so and asks you to end agy in Task Manager. Until you do, that agy runs unseen: after 30 seconds the turn counts as failed, so another message can start a second turn beside it.
- Only the 50 most recent saved sessions are checked for unloaded consultants. Older ones can still be reached by their full thread id.
- Uses the experimental Codex app-server protocol (`thread/start`, `thread/resume`, `thread/list`, `thread/loaded/list`, `thread/read`, `thread/name/set`, `thread/turns/list`, `thread/archive`, `turn/start`, `turn/steer`, `account/rateLimits/read`, `model/list`), which may change between Codex releases. See [Tested with](#tested-with).

## Versioning

[Semantic Versioning](https://semver.org/). Releases are git tags (`v0.1.0`), and changes are listed in [CHANGELOG.md](CHANGELOG.md). Until 1.0, minor versions may include breaking changes to tool names or arguments.

## License

[MIT](LICENSE)
