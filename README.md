# nouez

An MCP server that lets Claude Code consult a second model, on the Codex CLI, Google's Antigravity CLI or both, and open, list and close Claude Code sessions on your computer, so you can start a new one from your phone. Claude Code is the only agent it needs: each consultant CLI is optional.

## Why

Two coding agents look at a problem differently. This bridge gives each one a fixed role:

- **Claude Code is the main developer.** It plans, writes the code or text, and owns the work.
- **A consultant gives second opinions.** It runs on the Codex CLI or Google's Antigravity CLI (Gemini and other models), whichever you have. Claude asks it for second opinions: reviewing a plan, checking a diff, finding a bug, validating a claim, or gathering context for research. The consultant only reads; it never edits your files.

Without the bridge, you run two terminals and copy text between them. With it, Claude starts a consultant in the background, sends it questions, reads the answers and keeps working, all from your single Claude Code terminal. If you prefer to watch Codex work, you can still open it yourself and Claude will talk to that session instead.

The same server also helps when you drive Claude Code from your phone with Remote Control: a session can open a new Claude Code session in another project on the computer, list the ones running, and close a stuck one (see [A new Claude Code session from your phone](#a-new-claude-code-session-from-your-phone)). A `claude remote-control` server alone is tied to the folder it runs in (and, with `--spawn worktree`, worktrees of it); with a [dispatcher](#a-dispatcher-for-every-project), one server reaches every project and can start new ones.

## Requirements

- [Claude Code](https://code.claude.com/docs/en/quickstart), the main tool.
- Python 3.9 or later (standard library only, nothing to install).
- For consultants, at least one of these, installed and signed in. Each is optional:
  - the [Codex CLI](https://developers.openai.com/codex/cli/) (`codex`), with a ChatGPT plan or an API key;
  - Google's [Antigravity CLI](https://antigravity.google/docs/cli-getting-started) (`agy`), for consultants on Gemini or another model it lists (see [Antigravity consultants](#antigravity-consultants)).

What works with each setup:

| Installed besides Claude Code | Consultants | `StartConsultant` without `provider` | Claude Code session tools, `ConsultantBudget`, `top` |
|---|---|---|---|
| Codex and Antigravity | both | Codex; Antigravity when you ask for it | yes |
| Codex only | Codex | Codex | yes |
| Antigravity only | Antigravity | Antigravity, and the result says so | yes |
| neither | none: the consultant tools say so | an error naming both CLIs | yes |

### Tested with

The protocol between the bridge and Codex is experimental, so this is the last combination known to work. Newer versions will probably work too, but if something breaks, compare against this table.

| Component | Version |
|---|---|
| nouez | 0.21.0 |
| Claude Code | 2.1.331 |
| Codex CLI | 0.170.0 |
| Codex app-server daemon | 0.171.0 |
| Antigravity CLI (optional: Antigravity consultants, its quota) | 1.5.16 |
| Python | 3.11.9 |
| OS | Windows 11 |

Run `claude --version`, `codex --version` and `agy --version` to see your versions, or `server.py doctor`, which also shows the version of the Codex daemon that is running. Codex updates its daemon by itself, so the daemon can be newer than the CLI.

## Setup

Run each command in a terminal. Where a path appears, use the absolute path to your copy of nouez, in quotes if it contains a space. On macOS and Linux, use `python3` wherever this says `python` if `python` isn't on your `PATH`. First check that `python --version` prints 3.9 or later. On Windows, if it opens the Microsoft Store or prints nothing, install Python from python.org (or use `py -3` wherever this says `python`). Run the commands outside any virtual environment, unless you mean nouez to run on that environment's Python.

**1. Get the code.**

```sh
git clone https://github.com/jibarix/nouez.git
```

**2. Install and sign in to a consultant CLI** (skip it to use only the Claude Code session tools). Either one is enough; with both, Codex is the default.

- **Codex:** install the [Codex CLI](https://developers.openai.com/codex/cli/), run `codex login` (with an API key instead, `codex login --with-api-key` reads it from standard input: `printenv OPENAI_API_KEY | codex login --with-api-key` in Bash or zsh, `$env:OPENAI_API_KEY | codex login --with-api-key` in PowerShell), then check with `codex login status`, which should say you are logged in. Usage windows in `ConsultantBudget` and `top` are those of a ChatGPT plan; with an API key there are none to show.
- **Antigravity:** install the [Antigravity CLI](https://antigravity.google/docs/cli-getting-started), run `agy` once in a terminal and sign in with your Google account, then check with `agy models`, which should list models. On Windows the installer puts `agy` in `%LOCALAPPDATA%\agy\bin`; nouez finds it there even when that folder isn't on your `PATH`. If `agy` isn't found in your terminal, run it by its full path instead, in PowerShell `& "$env:LOCALAPPDATA\agy\bin\agy.exe" models`.

If installing changed your `PATH`, quit and restart Claude Code (and the terminal it runs in), so the server it starts can find the new program.

**3. Register the server with Claude Code.**

```sh
# available in every project
claude mcp add --scope user consultants -- python "/absolute/path/to/nouez/server.py"

# or only in one project: run this from that project's folder
claude mcp add consultants -- python "/absolute/path/to/nouez/server.py"
```

On Windows, use a path like `"C:/Users/you/nouez/server.py"`. To get [model scores](#choosing-a-consultant), add `-e ARTIFICIAL_ANALYSIS_API_KEY=<your key>` before `--` now; to add it later, see there.

**4. Let Claude run the waiter** (skip it if you installed no consultant CLI). Replies often take minutes, so Claude doesn't wait for them: it starts a small waiter command in the background, and the waiter wakes Claude with the reply when the consultant finishes (see [Long tasks](#tips)). Claude Code asks before running a command it has no rule for, and in auto mode it may block one. To allow the waiter in every project, print its permission rules with the same `python` and path you registered:

```sh
python "/absolute/path/to/nouez/server.py" allow-rule
```

It prints the rules and the file to put them in: one rule for the Bash tool, and on Windows a second for the PowerShell tool. Add them to `permissions.allow` in that file (`~/.claude/settings.json`, or `settings.json` in `CLAUDE_CONFIG_DIR` if you set it; on Windows, `C:\Users\<you>\.claude\settings.json`), keeping anything already in it. If the file doesn't exist yet, create it. With no other permissions, on Windows it looks like this:

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

Instead of editing the file, you can approve the waiter the first time Claude Code asks and choose not to be asked again. The rules allow only this script's `wait` command with this interpreter, so auto mode keeps them. If you move nouez or change Python, run `allow-rule` again and replace them. Without them everything still works, but Claude Code asks each time, and if the waiter can't run Claude reads the reply only when you ask for it. Claude Code reads `settings.json` when a session starts, so start a new session after editing it; `/mcp` reconnects only the server. `/permissions` in Claude Code shows the rules in effect.

**5. Check it.** Run:

```sh
python "/absolute/path/to/nouez/server.py" doctor
```

It reports Claude Code's side (Python, `claude`, the waiter's rules, panes) and then each consultant CLI: whether it is installed, signed in and answering. A CLI you didn't install is a note, not a problem; doctor exits with 1 only when something installed doesn't work. Then run `claude mcp list`, or `/mcp` inside Claude Code: you should see `consultants` connected. Sessions that were already open keep the old server until you reconnect it there: `/mcp`, then reconnect `consultants`. Do the same after updating nouez (see [nouez updates](#nouez-updates)).

## Usage

**1. Nothing to start.** With Codex, if its daemon isn't running (it stops when the computer restarts), the first tool call starts it, which adds a few seconds. To start it yourself, run:

```sh
codex app-server daemon start
```

**2. Work in Claude Code as usual.** Whenever you want a second opinion, ask for it in plain language:

> Start a Codex consultant for this project.

> Start a Codex consultant I can watch.

> Ask Gemini whether this plan holds up.

> Ask the consultant to review the plan you just wrote. Push back on anything you disagree with before changing it.

> Before you commit, send the diff to the consultant and ask it to look for bugs.

> We're stuck on this test failure. Ask the consultant for its diagnosis and compare it with yours.

> We're done. Stop the consultant.

Claude calls `StartConsultant` to create a background consultant in your project (Codex if it is installed, otherwise Antigravity) (or reuses one already working there, see [Reusing a consultant](#reusing-a-consultant)), `SendConsultantMessage` to ask questions, and `StopConsultant` when you're finished. Each message reaches the consultant prefixed with `[Message from Claude Code via the consultants bridge]`, and Claude gets the answer back as a tool result.

**A consultant Claude starts is always read-only.** A Codex one can read your files and run read-only commands for auditing, validation and research; an Antigravity one can read files but runs no commands, so Claude puts the diff or test output it needs in the message. Neither can change anything. (A Codex session you opened yourself keeps its own permissions; see [below](#using-a-codex-session-you-opened-yourself).) It never stops to ask for approvals, because no terminal is attached to answer them. Claude does all the writing. There is no option to give a consultant write access.

**3. Watch or join in (optional, Codex).** A background Codex consultant is an ordinary Codex session. A consultant started by `StartConsultant` is shown automatically (pass `watch: false` to skip that); for a session you opened yourself, ask Claude to *"open the consultant in a terminal"* (`WatchConsultant`). Either way, `codex resume <id>` opens next to Claude Code: as a split pane in the same tab when Claude Code runs in Windows Terminal or tmux, otherwise in a new terminal window. You can read along there or type into the session yourself. Codex can't open a session before its first message, so the pane appears when Claude sends that message, and reappears on the next message if you close it. Without a split, Windows uses a new Windows Terminal window (falling back to a console window), macOS uses Terminal, and Linux uses the first terminal emulator it finds of `x-terminal-emulator`, `gnome-terminal`, `konsole`, `xfce4-terminal`, `kitty`, `alacritty`, `wezterm`, `foot` and `xterm`. If the pane can't open (no terminal emulator, no display as over SSH, or a launcher that fails), the result says why and gives the `codex resume` command to run yourself; the consultant works as usual. Without a display, pass `watch: false`, or run Claude Code inside tmux to get panes beside it. In Windows Terminal the pane opens in the window running the Claude Code session that asked for it, even if you last used another window: nouez brings that window to the front while `wt` runs, then gives the focus back. If Claude Code's tab isn't the selected tab in its window, the consultant opens in a new tab there instead, and if the window can't be found or brought to the front (a locked screen, say), it opens in a new window of its own rather than in another session's. If a terminal already shows the session, no second one opens. The pane's `codex resume` attaches to the same Codex daemon nouez talks to (`--remote` with that daemon's socket, so a terminal with another `CODEX_HOME` reaches it too) and skips Codex's update check. In a folder Codex hasn't trusted yet, the pane first asks "Trust this folder?": Codex asks the daemon, so nouez can't answer it for one run. Choosing **Trust and continue** saves your answer in your Codex config, as Codex does, and the pane won't ask again there; the consultant works on while the pane waits. nouez never answers it for you. The window runs the Codex daemon's own `codex` binary when it can find it, so it matches the daemon's version; otherwise it falls back to the `codex` on your `PATH` and warns if the versions differ.

### Reusing a consultant

A consultant keeps its whole conversation until you stop it, so you can keep going back to the same one. Refer to it and Claude finds it with `ListConsultants`:

> Ask the consultant to check the diff.

> Send this to codex-myproject-a1b2c3: …

> Open the consultant so I can watch.

This works from a new Claude Code session too: consultants that went idle still appear in the list, and the next message reloads them. Reuse is the default. `StartConsultant` searches first: if a consultant it started earlier already works in the same project, it returns that one and starts nothing; if none is found, it starts one. It never picks a Codex session you opened yourself, even in the same project, because that session keeps your permissions; it lists such sessions in its result instead. `model`, `title` and `instructions` only apply when a new consultant is started. The project is the git repo; outside git, it's the Claude Code workspace folder (the folder you launched Claude Code in), so a subfolder finds the consultant started at the top. When you want a clean slate, ask for a new one, and Claude passes `new: true`:

> Start a new Codex consultant I can watch.

> Start a second consultant in ~/projects/other-repo and ask it to …

With more than one consultant running, name the one you mean. Once stopped, a consultant is out of Claude's reach. A Codex one is archived: to bring it back, run `codex unarchive <id>` (the id is in the stop message). An Antigravity one is forgotten by nouez, but its conversation stays in agy (`agy --conversation <id>`).

### Using a Codex session you opened yourself

If you'd rather see Codex work in its own window, open it yourself (`cd my-project && codex`) and ask Claude to *"list the consultants and send it …"*. Claude finds the session with `ListConsultants` and talks to it the same way. `StartConsultant` never chooses your session on its own, and `SendConsultantMessage` refuses it unless Claude passes `allow_user_session: true`, which it is told to do only when you ask. The message appears in that terminal as a new prompt. Sessions you open yourself use their own permission settings and approval prompts, and `StopConsultant` won't close them.

### A new Claude Code session from your phone

Driving Claude Code from the Claude app with Remote Control, you can ask the session for another one: *"open a new Claude session for C:/Users/me/Projects/other"*. Claude calls `OpenClaudeSession`, which opens a new terminal window on the computer and starts `claude --remote-control <name>` in that folder. The new session shows up in the app's session list a few seconds later. It is an ordinary session that saves its transcript and can be resumed. A `claude` you start from Claude Code's own shell doesn't save its transcript, because it inherits `CLAUDE_CODE_CHILD_SESSION` and the other variables that mark it as a child session. `OpenClaudeSession` starts it without them, keeping any variable you set yourself in your environment. On Linux it needs a graphical desktop (an X or Wayland display): over SSH, or in tmux without one, no window can open. The folder can be a new one: *"open a new Claude session in a new folder C:/Users/me/Projects/economic-recession"* makes Claude pass `create: true`, and nouez creates it (its parent must exist). To pick up an earlier conversation, ask *"resume the latest hours-tracker session"*: Claude passes `resume: "latest"` (or a session id), and the window runs `claude --resume <id>` with Remote Control, so the conversation carries on where it stopped. "latest" is the newest conversation in that folder that no running session has open; a conversation already open in a running session is never opened twice. Claude Code's experimental Code Mode doesn't run with Remote Control, and a conversation held in Code Mode resumes only in a terminal with Code Mode on, so `resume` can't bring one back as a remote session.

Claude Code asks whether you trust a folder the first time it runs there, and a session waiting at that question can't connect to the app. So before opening a window, nouez checks Claude Code's settings (`~/.claude.json`). If the folder isn't trusted, nothing opens: the result gives a report of what the folder's project settings would make Claude Code run or allow, and Claude shows it to you and asks whether you trust the folder. The report covers `.claude/settings.json`, `.claude/settings.local.json` and `.mcp.json` in the folder trust would be recorded for, the checkout the session opens in (they differ for a worktree) and the folder itself: hooks with their events, matchers and commands, the status line and helper commands, the names of variables set in `env` (not their values), permission rules and mode, extra folders, MCP servers with their commands or URLs (the names of their variables and headers, not the values), plugins marked on or off, marketplaces with their sources, and the name of any setting it doesn't know. Values that look like passwords or keys (in a URL, or after a flag such as `--token`) show as `***`, characters that don't print are spelled out, and a report that had to shorten an entry or a list says it is a summary. The report is read from files in the folder, so Claude is told to treat it as data. A file it can't read is reported as such, never as nothing, and then nouez won't record trust from the phone at all: you look at the file on the computer. If you say yes, Claude calls it again with `trust: true`, and nouez records your answer in `~/.claude.json` the way Claude Code's trust dialog does, then opens the window, so this works from your phone. nouez records trust only for a folder whose report it has given earlier in the same conversation, and only if not a byte of those files has changed since (it keeps a fingerprint of them, not the report's text); otherwise `trust: true` gets the report again and records nothing. A folder the same call creates, outside a git repository, has no settings, so it needs no report. Before each change nouez saves a dated copy of the file (the newest 20 are kept, in `%LOCALAPPDATA%\nouez\claude-json-backups`, or `$XDG_STATE_HOME/nouez/claude-json-backups` elsewhere, by default `~/.local/state/nouez/claude-json-backups`) and the result names it. Only that one setting changes. If you're at the computer, Claude can instead open the window untrusted (`open_untrusted: true`) so you answer Claude Code's own question there. Trust works like Claude Code's: outside a git repository, trusting a folder covers the folders inside it, but a git repository is trusted on its own (for a worktree, its main checkout), so trusting `C:/Users/me/Projects` doesn't cover a repository in it. Even in a trusted folder Claude Code can still ask on the computer: a project's own `.claude/settings.json` allow rules need that folder itself trusted, not just a folder above it, and a project's `.mcp.json` servers have their own approval. So a folder trusted only through one above it that has its own `.claude/settings.json` is treated like an untrusted one: nothing opens, and you get the report and the question. The result mentions `.mcp.json` servers when the file is there, and says when nouez can't tell whether a folder is trusted (Claude Code's settings can't be read, or the git layout is unusual).

To see what's running, ask any session *"which Claude sessions are open?"*. `ListClaudeSessions` lists the interactive Claude Code sessions registered in your Claude Code config folder, whoever started them, each with its name, folder, status and whether Remote Control is on. To close one, such as a stuck one, say which: *"close hours-tracker"*. `CloseClaudeSession` ends its `claude` process. On Windows, a session `OpenClaudeSession` opened also gets its window closed. Elsewhere nouez ends only the `claude` process: a window `OpenClaudeSession` opened then closes if the terminal closes when its command ends, as most Linux terminals do, and stays at a prompt otherwise (macOS Terminal). A session you started yourself leaves its terminal at the shell prompt. On macOS and Linux nouez first checks with `ps` that the process is still Claude Code, started no later than the session was registered, and isn't one nouez itself runs under; if it can't confirm that, it signals nothing and says why. The transcript stays, so `claude --resume` in that folder picks it up again. Claude shows you the list and closes only the sessions you pick, one call each, and never the one you're talking to. The list comes from `~/.claude/sessions`, which Claude Code keeps but doesn't document, so a future Claude Code version could change it.

To find a project, ask *"which projects do I have?"*. `ListProjects` lists the folders in the folder that holds the session's own (for a dispatcher in `~/Projects/dispatcher`, your projects), or in another folder you name: for each, whether it is a git repository, whether Claude Code is trusted there (itself, or through a folder above it), the Claude Code sessions running in it and which project settings files it has. Hidden folders (a name starting with a dot, or marked hidden on Windows) are left out. It reads the disk each time, so a folder you add shows up at once.

Claude Code's sign-in on the computer lasts a set time; using Claude Code doesn't extend it, and Claude Code says it ends on a day between two dates. A Remote Control session that outlives it disconnects until you sign in again, and signing in needs the computer. So nouez reads the line `claude auth status --text` prints about it (`Sign-in ends: between … and …`, with the exact end in parentheses; the earlier date is 3 days before it), keeps only that line, and from 7 calendar days before the earlier date adds a warning to the results of `OpenClaudeSession`, `ListClaudeSessions` and `ListProjects`, with how to renew (`claude auth login` in a terminal on the computer, or `/login` in a session there). `ConsultantBudget` always shows the line, and the status screen's top bar always shows the date to renew by and the days left, grey until the warning is on, then amber and red. It reads the line in the background when a server starts and then about once an hour (every 10 minutes in the last week), and again when Claude Code's credentials file changes (nouez looks only at the file's time, never inside it), so other tools don't wait for it; `ConsultantBudget` waits for a reading that is due, up to about 25 seconds. It saves the line in `nouez/claude-login.json` for every nouez server to share, with Claude Code's config folder and the names of any sign-in variables (such as `ANTHROPIC_API_KEY`, never their values), so a server signed in another way doesn't use it. It shows nothing when you sign in another way (an API key, say) or when your Claude Code doesn't print the line. Set `NOUEZ_NO_LOGIN_CHECK=1` to turn it off.

To see the [status screen](#usage-log-and-status-screen) on the computer, ask for it: `OpenStatusScreen` opens `server.py top` in a new terminal window there, with 1, 7 or 30 days of consultations or all of them. It shows only on the computer; from the phone, ask for `ConsultantBudget` instead.

### A dispatcher for every project

Remote Control on its own works like this. While `claude remote-control` runs in a folder on your computer and is connected, the Claude app offers the computer: tap new session, pick it, and the session runs there. That server starts every new session in its own folder (or, with `--spawn worktree`, in a new worktree of it); the app has no folder picker for it. Reaching a second project means starting another server in that project's folder, at the computer, and after a restart or a sign-out none is running until you start it again. (The Claude desktop app can offer several registered folders instead, while it is open.)

With nouez, one Remote Control server reaches every project. A session in it can open a session in any folder with `OpenClaudeSession`, make a folder for a new project, and record your trust answer, all from the phone. Each session it opens runs in the project's own folder, so that project's `CLAUDE.md`, settings and memory load, and with nouez registered for every project (`--scope user`) it can consult as usual.

The tidiest home for that server is a small folder of its own, a dispatcher, whose `CLAUDE.md` gives it only that job. Make the folder, then in a terminal there run the exact command once, interactively, so you can answer Claude Code's trust question and any first-use question Remote Control asks (with no terminal, a server waiting at one never connects):

```sh
claude remote-control --name dispatcher --spawn same-dir
```

Check that it connects and that the app offers it, then stop it with Ctrl+C. `--spawn same-dir` picks the mode on the command line, so the server never stops to ask which one to use. A `CLAUDE.md` to adapt:

```markdown
This folder is a dispatcher: the user drives it from the Claude phone app to work in other
projects. Don't do project work here.
- List projects with ListProjects.
- Open a project with OpenClaudeSession (cwd: its folder) and say the session's name.
- Make a new project only directly in ~/Projects, with create: true, when the user asks for one.
- When OpenClaudeSession says a folder isn't trusted, show the user the folder trust would be
  recorded for and the whole report it gives, and pass trust: true only after a plain yes.
- List sessions with ListClaudeSessions; close only a session the user names.
- Usage: ConsultantBudget, in a few lines. Pass on any sign-in warning a result gives.
- Status screen or dashboard: OpenStatusScreen (it opens on the computer, not the phone).
- Don't start consultants here.
```

Allowing `mcp__consultants__OpenClaudeSession`, `mcp__consultants__ListClaudeSessions`, `mcp__consultants__ListProjects`, `mcp__consultants__ConsultantBudget`, `mcp__consultants__OpenStatusScreen` and `mcp__consultants__CloseClaudeSession` in the dispatcher's `.claude/settings.json` (`permissions.allow`) spares you a prompt for each.

To have it there after a restart, start the same command hidden at sign-in, with the dispatcher folder as its working directory: on Windows a Task Scheduler task with an "At log on" trigger, on macOS a launch agent, on Linux a systemd user service. nouez doesn't install one. A sign-in trigger starts it once, so if it can exit (a long network outage, say), run it under something that starts it again. It needs you signed in and the computer awake: a sleeping laptop is out of reach. A locked screen doesn't stop running programs, but reaching a locked computer from the phone hasn't been tested with nouez. Remote Control connects out to Anthropic; with Claude Code 2.1.330 the server listened on no port.

What we saw with Claude Code 2.1.330, in a conversation the server started from the app: `/exit` isn't available there ("isn't available in this environment"). Archiving the conversation in the app ended that conversation's process on the computer, while `claude remote-control` kept running (it showed "Ready" and 0 of 32 sessions), so the computer stayed in the app and a new conversation could start there. Sessions `OpenClaudeSession` opens run in their own terminal windows and weren't part of that test.

A dispatcher started hidden has no window on the computer. To follow its conversations there, open https://claude.ai/code in a browser signed in to the same account: it lists the Remote Control sessions as the phone app does. What the server itself prints goes wherever the program that starts it sends it, so have that program write it to a log file.

### Choosing model and effort

A Codex consultant uses the model and reasoning effort from your Codex config (`model` and `model_reasoning_effort` in `~/.codex/config.toml`); an Antigravity one starts on `gemini-4-neon` at level `high` (`ConsultantBudget` lists agy's models and their levels). Claude can change either one for a hard question without starting over: `SendConsultantMessage` takes `model` and `effort`, the consultant keeps its context, and the setting stays for later messages until Claude sends the usual values again. nouez tells Claude to do this only when you ask, or when your own instructions say when. Which model suits which work is your call, so nouez doesn't decide it for you.

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
- **Antigravity's quota,** when `agy` is installed: each quota group's windows the same way, and the models agy lists with their levels.
- **Claude Code's own usage.** Claude Code tells only its status line how much of its 5-hour and weekly windows is used, so nouez reads a file the status line saves (below). Without it this part says "not known".
- **Model scores.** The [Artificial Analysis](https://artificialanalysis.ai) Intelligence Index for the top OpenAI, Google and Anthropic models, with API price and speed. Higher is smarter. Data from Artificial Analysis; credit it when you share it.

nouez reports; it doesn't choose. Your rules decide, in `~/.claude/CLAUDE.md` (see [Choosing model and effort](#choosing-model-and-effort)) or a skill. nouez ships one to start from, `skills/consult/SKILL.md`: it sorts consultations by kind (quick check, review, bug hunt, plan critique, research), works with Codex, Antigravity, both or neither, gives each kind a starting model and effort, then moves up or down by what `ConsultantBudget` shows, for instance one effort level down when a subscription is on pace for over 90% of its week, and no consulting on a window that runs out before its reset. Edit its table to your own models. To use it in every project, copy it to your Claude Code skills folder (if you already have a `consult` skill there, compare them first rather than overwrite it):

```sh
# macOS and Linux
mkdir -p ~/.claude/skills/consult && cp "/absolute/path/to/nouez/skills/consult/SKILL.md" ~/.claude/skills/consult/
```

```powershell
# Windows (PowerShell)
New-Item -ItemType Directory -Force "$HOME\.claude\skills\consult" | Out-Null
Copy-Item "C:/Users/you/nouez/skills/consult/SKILL.md" "$HOME\.claude\skills\consult\"
```

To use it in one project only, copy it to that project's `.claude/skills/consult/` instead. In a new Claude Code session, `/consult` should then be listed, and asking for a second opinion uses it.

**Model scores need a free Artificial Analysis key.** Create an account at [artificialanalysis.ai](https://artificialanalysis.ai) and an API key (free tier, 100 requests a day). Set it as `ARTIFICIAL_ANALYSIS_API_KEY` in the environment Claude Code starts nouez from, for example as a user environment variable on Windows, or in the server's `env` when you register it:

```sh
claude mcp add consultants --scope user -e ARTIFICIAL_ANALYSIS_API_KEY=<your key> -- python /path/to/nouez/server.py
```

Use the same scope and path you registered nouez with (Setup step 3). If `consultants` is already registered, `claude mcp add` won't change it: remove it and add it again in the same scope, with the key (`claude mcp get consultants` shows the scope and command it has now):

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

### A brief and a verdict

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

### Tips

- **Give the consultant context.** A consultant can read the files in its own working directory, so start it in the same repo. Tell Claude to include the specific file, diff or question in the message; an Antigravity consultant can't run commands, so it needs the diff or output itself.
- **Give Claude standing instructions.** A line in your project's `CLAUDE.md` makes the workflow automatic, for example: *"Before committing non-trivial changes, ask the consultant to review the diff and address its findings. Reuse the existing consultant for this repo if there is one; otherwise start one."* (Say "the Codex consultant" only if you have Codex: it makes Claude ask for Codex by name.)
- **Consult without being asked.** Lines in `~/.claude/CLAUDE.md` apply in every project, and nouez and the shipped consult skill tell Claude to consult when your own instructions call for it. For example: *"Before substantial read-only work, consult without waiting for me to ask: reviewing a non-trivial diff before a commit, diagnosing a failure whose cause isn't obvious, critiquing a plan, or research across several sources. Keep writing code and one-line fixes in this session."*
- **Give the consultant a brief and ask for a verdict.** `StartConsultant` takes standing `instructions`, and each message can carry its own brief. A brief that says what is being decided gets a more useful answer than a role. See [A brief and a verdict](#a-brief-and-a-verdict).
- **Pass on the user's words.** When Claude is acting on something you asked for, it can send your words with `owner_words`, kept apart from its own reading of them, so the consultant checks the work against what you said rather than against Claude's summary.
- **Tie a review to a revision.** `revision: true` starts the message with the repo's commit, branch and number of uncommitted paths, and asks the consultant to name that revision in its answer, so a verdict can't be mistaken for one about a later state of the code. When there are uncommitted changes, nouez also takes their diff at that moment, untracked files included, saves it in its cache folder under its SHA-256 and names it, so the consultant reviews exactly that diff even if you keep editing, and two consultants given the same diff see the same digest. nouez writes nothing in the repo to do this, and runs none of its git hooks. An Antigravity consultant runs no commands, so it gets only the line unless you also pass `attach_diff: true`, which puts the diff in the message; its text then goes to Google, deleted lines and untracked files included. Binary files, untracked files over 256 KB and untracked files with a part of their path that looks like a secret (`.env`, keys, names with "secret", "token" or "password") are left out, and the line names them. When nouez can't take or save the diff, or it is too large for an Antigravity message or isn't UTF-8, the line says so, names no digest, and asks the consultant to review the working tree.
- **Run several consultants.** Start several, for example in different repos or with different models. `ListConsultants` shows each one's name and working directory so Claude can pick the right one.
- **Long tasks.** By default Claude waits 5 seconds after sending, enough to confirm delivery and catch a quick answer, then starts a small waiter in the background, tells you the consultation is under way, and is free again, and so are you. When the consultant finishes, the waiter exits with the reply and Claude Code wakes Claude with it, so Claude acts on the answer or reports it without you asking. Claude needs permission to run the waiter; see [Setup](#setup), step 4.
- **Idle consultants.** After about a minute without activity, the Codex daemon unloads a Codex consultant. It still appears in `ListConsultants`, and the next message reloads it with the same sandbox and history.
- **Clean up.** Ask Claude to stop consultants when you're done, so they don't pile up in your Codex session list or in `ListConsultants`. Stopping archives a Codex session rather than deleting it, and closes its watch window. Only panes and windows nouez opened are closed, on every system: each carries a token nouez gave it, so a `codex resume` you started yourself stays open. On macOS and Linux nouez ends the pane's `codex resume` process (checking its program and command line first), so a tmux pane or a Linux terminal window closes with it, while a macOS Terminal window stays open at a shell prompt.

### Antigravity consultants

A consultant can also run on Google's Antigravity CLI (`agy`) and its Gemini models, so a second opinion can come from a third family of models and from Google's quota instead of the Codex subscription. When Codex isn't installed, `StartConsultant` uses Antigravity without being asked, and says so. With both installed, Claude starts one with `provider: "antigravity"` only when you ask or your own rules say when. Either way it is used with the same tools as a Codex consultant. It starts on `gemini-4-neon` at level `high`; `model` and `effort` pick another (`ConsultantBudget` lists the models), and `SendConsultantMessage` changes them for later messages while the conversation keeps its context. Any model agy lists works, including the Claude and GPT models Antigravity runs on Google's quota; those use that quota, not your Claude Code or Codex usage.

How it differs from a Codex consultant:

- **Read-only by agy's own rules.** Every turn runs `agy -p` with deny rules for file writes and edits, commands, MCP tools and URL actions, and with slash commands off. Its browser tools aren't available in this mode. It can read files, search and read web pages, but can't run `git diff` or the tests: Claude puts the diff or output it should judge in the message.
- **One message at a time.** Each message runs one agy turn in the background. A message sent while a turn runs is refused, with nothing sent, since agy can't steer a running turn; this holds across all your Claude Code sessions. Wait for the reply, or stop the consultant.
- **No pane.** `WatchConsultant` gives the command to open its conversation in agy yourself (`agy --conversation <id>`, with agy's full path when it isn't on your `PATH`) instead.
- **A 30-minute limit per turn.** A turn still running then ends with what it has, reported as interrupted.
- `StopConsultant` ends a running turn and forgets the consultant; its conversation stays in agy. It ends only the process nouez started (on Windows, checked by its start time and program). If it can't end it, nothing is stopped and it says so; send the stop again.

nouez keeps each consultant, and each turn's input and output, in `nouez/agy/` in your cache folder. Replies are logged with their token counts, which `server.py top` shows in the offload table's Antigravity column.

### Usage log and status screen

nouez notes each consultation in `nouez/usage-log.jsonl` in your cache folder (`%LOCALAPPDATA%` on Windows, `~/.cache` elsewhere), one JSON line per event:

- **start:** a consultant started or reused, with its project and model.
- **send:** a message: the consultant, project, model and effort, which of those it changed, whether it steered a running turn, `kind` and `reason` if Claude gave them, its length in characters, whether it quoted your words, the digest of the diff `revision` took (never the diff), and each subscription's usage at that moment (as `ConsultantBudget` would show it).
- **reply:** how the turn ended: status, time taken, length, and the verdict read from the reply's first line (`yes`, `changes`, `no`, or `incomplete` when the reply says it couldn't read what it was given or the turn didn't finish); for an Antigravity consultant, also its token counts.

Events of Antigravity consultants carry `provider: "antigravity"`, and their sends also record Antigravity's quota at that moment.

It never holds the text of a message or reply. Past 20 MB it is renamed with the date and a new one starts. Set `NOUEZ_NO_USAGE_LOG=1` in nouez's environment to turn it off; that stops only this log, and an Antigravity consultant still keeps its turns in `nouez/agy/` (see [Files nouez keeps](#files-nouez-keeps)).

To see it, with the usage of each subscription, run in a terminal:

```sh
python /path/to/nouez/server.py top
```

It shows, in boxed panels:

- **A top bar:** the version, and each subscription's most pressing window: a dot in its colour and its use, named when it isn't the weekly window (`● Claude 95% 5-hour`, `● AG Claude+GPT 82%`); and a sign-in badge: the date to renew Claude Code's sign-in by and the days left (`● sign-in Dec 5, 12d`), grey until 7 days before, then amber, red from the day before, then `sign-in ending` and `sign-in ended`.
- **Usage:** each Codex and Claude Code window, with a bar, the reset, and where the pace lands at the reset (red when used up or running out first, amber over 90%). A dotted mark (`┊`) in the bar shows how much of the window's time has gone: a bar filled past it is being used faster than evenly. Codex is read live from the daemon once a minute; without the daemon, from Codex's last session file. Without Codex installed (and no Codex usage ever logged), its card and badge are left out. Claude Code's comes from the status line file (see [Choosing a consultant](#choosing-a-consultant)). If the Antigravity CLI (`agy`) is installed, on your `PATH` or where its installer puts it on Windows, each of its quota groups too, read once a minute with `agy -p /usage`, which runs no model turn and uses no quota. They are listed under an Antigravity line; its "Claude+GPT" group is Claude and GPT models run inside Antigravity on Google's quota, apart from Claude Code's.
- **Consultations:** messages sent, and how many of their replies were read (with any that failed or were interrupted), steered and with a changed model or effort; counts by model, kind, project and verdict, which kind went to which model, and the latest reasons given; the median and slowest reply times; and consultants with three or more CHANGES rounds in a row. Verdicts and reply times are those of the period's own messages; other replies read, to earlier messages, are counted apart.
- **Offload:** for each of the last 8 weeks, the output tokens of Claude Code (and its subagents) beside those of nouez's Codex consultants, of your own Codex sessions and of Antigravity consultants (from the usage log, in the week each message was sent), the messages logged ("sends"), and the share made outside Claude Code, your own Codex sessions included; then Claude Code's output by model. A dash means nothing was recorded: weeks before the usage log began, or Antigravity turns that reported no tokens; a `+` after a number, that some of that week's did. The share is of the output known. These come from the Claude Code transcripts (`~/.claude/projects`) and Codex session files (`~/.codex/sessions`) on this computer. A reply copied into another transcript of the same session, as a forked subagent's starts with its parent's history, counts once. The first run reads the last 13 weeks of them, which can take a minute; the counts are kept in `nouez/usage-weeks.json` and later runs read only what was added.

With the 7- or 30-day period, a line of small bars shows the messages sent each day. The screen fits a terminal 100 columns wide, with the panels one above the other; from 149 columns, each subscription gets a card in a column on the left, beside the consultations and the offload table. On a short screen the optional lists go first, then older weeks (down to three), then the consultations' tables and last lines, then the remaining weeks and whole panels, so every box closes and the latest week stays. Keys, shown in the bar at the bottom: `1`, `7`, `3` or `a` to show 1, 7 or 30 days of consultations or all of them; `r` to read usage again now (in the background); `?` for a help page that says what the marks and columns mean (`?` or Esc goes back); `q` or Esc to quit. `--days N` picks the period to start with (0 for everything, up to 65535), and `--once` prints one screen, with those notes at the end, and exits; to a file or pipe it prints one column 104 wide. In a Windows console other than Windows Terminal (or another terminal that names itself), boxes have square corners and the mark is `|`, for fonts without the rounded ones. When `server.py` is updated, the screen starts again on the new version by itself, with the same period, so its header always shows the version installed. It waits until the new file has stopped changing, compiles and still holds the status screen; if the new screen fails all the same, the window waits for the next update instead of closing. The screen reads local files, asks the Codex daemon for its usage (which the daemon gets from OpenAI) and agy for Antigravity's quota (`agy -p /usage`, no model turn, which agy gets from Google), and runs `claude auth status --text` for the sign-in line; nothing else leaves your computer through nouez.

## Tools

| Tool | What it does |
|---|---|
| `StartConsultant` | Starts a background consultant in a project directory: Codex when it is installed, otherwise Antigravity (always read-only; never asks for approvals). With neither installed, says so. If a consultant it started already works in that project, returns it and starts nothing unless `new: true`. Never reuses a session you opened yourself. Says so if a newer nouez is out (see [nouez updates](#nouez-updates)), or if the Codex CLI or daemon is out of date (see [Codex updates](#codex-updates)). |
| `ListConsultants` | Lists Antigravity consultants and Codex sessions (those loaded on the local daemon, plus recent `StartConsultant` sessions it has unloaded), with each one's name, working directory, model, status and who started it. With `cwd`, only the sessions in that repo. |
| `SendConsultantMessage` | Sends a message into a session, waits 5 seconds by default, and returns the reply if it is ready by then, or the turn id and a waiter command if not. If the session is idle the message starts a new turn; if a Codex session is busy it steers the running turn (a message this server already delivered to the running turn, as when Claude sends it again after its context was summarised, isn't sent twice: the result gives that turn's id), but only one this server started: a turn typed in the pane, or one from before the server restarted, is refused with nothing sent (as is any message to a busy Antigravity consultant). Unloaded Codex sessions are reloaded first. Refuses a session you opened yourself unless `allow_user_session: true`. |
| `GetConsultantReply` | Reads a reply without sending anything: the latest turn, or a specific turn id. Use it after sending with `wait: 0` or after a timeout. While the turn runs, it shows the output so far. With `offset`, reads a long reply from that character on. |
| `GetConsultantHistory` | Lists a consultant's recent turns, newest first, one line each: turn id, status, when, how long, who sent it, and the first line of the message and of the reply. Reads only. |
| `WatchConsultant` | Opens a Codex session in a split pane beside Claude Code, or a new terminal window, so you can watch it or type into it. Does nothing if a terminal already shows it. For an Antigravity consultant, gives the `agy --conversation` command to open it yourself. |
| `OpenClaudeSession` | Opens a new terminal window running an interactive Claude Code session with Remote Control in `cwd` (required), named `name` (default: the folder's name), optionally with a first `prompt`, or picking up an earlier conversation held in that folder with `resume` (a session id, or `latest`). It starts on Opus (`model`, default `opus`, the latest Opus) at medium effort (`effort`: `low`, `medium`, `high`, `xhigh` or `max`); Claude passes others only when you ask. The session saves its transcript like one you started yourself. `create: true` makes the folder if it doesn't exist. In a folder Claude Code hasn't been trusted in (or trusted only through a folder above it while it has its own `.claude/settings.json`), it opens nothing and gives a report of what the folder's settings would run, unless `trust: true` is given (you saw that report in this conversation and said you trust the folder: nouez records that, after a backup) or `open_untrusted: true` (it opens a session that waits at the trust question). In a trusted folder it then checks for up to 30 seconds that the new session is running and connected to Remote Control, and says if another session was already running in that folder. |
| `ListClaudeSessions` | Lists the interactive Claude Code sessions registered in your Claude Code config folder: name, process id, folder, status, Remote Control, and which one is the caller. |
| `ListProjects` | Lists the folders in `folder` (default: the one holding the session's own folder): git, trust, running sessions and project settings files. Reads only. |
| `OpenStatusScreen` | Opens the status screen (`server.py top`) in a new terminal window on the computer, with `days` 1, 7, 30 or 0 (all; default 7). |
| `CloseClaudeSession` | Closes one of them by `name` (or `pid` when names repeat), keeping its transcript. Never the caller, and on macOS and Linux only a process it confirms is that session. |
| `ConsultantBudget` | Shows the usage left on your Codex subscription and Claude Code's own and, with `agy` installed, Antigravity's quota groups, with reset times and pace; Claude Code's sign-in end; the Codex and Antigravity models and their levels; and Artificial Analysis model scores. Reads only; see [Choosing a consultant](#choosing-a-consultant). |
| `StopConsultant` | Archives a Codex session that `StartConsultant` started and closes the terminal panes nouez opened for it (a terminal you opened yourself stays open); ends an Antigravity consultant's running turn and forgets it. Needs the exact name or full thread id. Refuses sessions you opened yourself. |

`StartConsultant` arguments (all optional):

| Argument | Default | Meaning |
|---|---|---|
| `cwd` | Claude Code's first workspace folder | Absolute path of the project the consultant works in |
| `model` | your Codex config; Antigravity: `gemini-4-neon` | Model (new sessions only). Without `provider` and without Codex installed, a Codex model name is ignored, and the result says so |
| `title` | | Session title, shown in Codex and in `ListConsultants` (new sessions only) |
| `instructions` | | Standing instructions for the consultant's role (new sessions only) |
| `watch` | `true` | Codex only: show the session in a pane beside Claude Code once it has its first message, and again on later messages if the pane was closed |
| `new` | `false` | Start a new session even though a consultant already works in this project |
| `provider` | `codex` if installed, else `antigravity` | `codex`, or `antigravity` for a consultant on the Antigravity CLI (see [Antigravity consultants](#antigravity-consultants)). An explicit choice is kept: `codex` without Codex installed is an error |
| `effort` | `high` | Antigravity only: the model level of a new consultant |

`SendConsultantMessage` arguments:

| Argument | Required | Default | Meaning |
|---|---|---|---|
| `to` | yes | | Session name from `ListConsultants` (e.g. `codex-myproject-a1b2c3`), full thread id, or unique id prefix/suffix. `name` is accepted as an alias. |
| `message` | yes | | The text to send |
| `from` | no | `Claude Code` | Sender label shown to the consultant |
| `owner_words` | no | | The user's own words, as they typed them. Sent first and marked off, with the rest of the message labelled as the sender's. Claude passes it only when it has the user's words to quote |
| `revision` | no | `false` | Start the message with the git commit, branch and number of uncommitted paths in the consultant's folder, and ask the consultant to name that revision in its answer. With uncommitted changes, also take their diff once, save it under its SHA-256 and point the consultant at it |
| `attach_diff` | no | `false` | Antigravity only, with `revision`: put that diff in the message, since the consultant can't run git. Its text goes to Google |
| `model` | no | unchanged | Model id, e.g. `gpt-6-astra` (Codex) or `gemini-4-neon` (Antigravity), for this message and later ones. The consultant keeps its context. Refused, with nothing sent, while nouez sees the consultant mid-turn |
| `effort` | no | unchanged | Reasoning effort (Codex) or model level (Antigravity), such as `low`, `medium`, `high` or `xhigh`; the levels depend on the model, for this message and later ones; send the usual value again to go back. Refused, with nothing sent, while nouez sees the consultant mid-turn |
| `wait` | no | `5` | How long to wait for the reply: seconds (`0` returns once the message is delivered), or `"done"` to wait until the turn ends. Capped at 4 hours |
| `allow_user_session` | no | `false` | Allow sending to a session you opened yourself. Claude sets it only when you ask |
| `kind` | no | | What the consultation is for: `quick-check`, `re-check`, `review`, `bug-hunt`, `plan-critique`, `research`, `fact-check` or `other`. Kept only in the [usage log](#usage-log-and-status-screen); anything else is refused, with nothing sent |
| `reason` | no | | A short sentence on why this model and effort, for the usage log (cut at 300 characters) |

`GetConsultantReply` takes `to`, an optional `turn_id` (default: the latest turn; looked up among the 100 most recent turns), an optional `wait` like `SendConsultantMessage`'s, but defaulting to `0`, which returns at once if the turn is still running, and an optional `offset`: a character position in a finished reply to read from. A reply read with `offset` comes back in pieces of up to 60,000 characters, each ending with the offset to read on from.

`GetConsultantHistory` takes `to` and an optional `limit` (default 20, up to 100). The sender is the `from` label of a message sent through nouez, or "someone in the Codex pane" for one typed there. A turn with no message isn't anyone's: when a Codex daemon restart (an automatic update, say) cuts a turn off, the restarted daemon carries it on in a new turn with no message, listed as "Codex carrying on the work of turn …, with no new message".

Most replies take longer than the default 5 seconds. Claude is told not to wait for them. Instead the result gives a waiter command, `python server.py wait <thread_id> <turn_id>` with full paths, which Claude runs as a background command (the Bash or PowerShell tool with `run_in_background`). A path is quoted only when it needs it: in double quotes if it has spaces, in single quotes if it has a character a shell would expand (`$`, a backtick). Such a command runs as is in Bash and in PowerShell after `& `. A path with a single quote needs each shell's own escape, so the result then gives a PowerShell form too, and `allow-rule` prints a rule for each. The waiter checks the turn every 1.5 seconds; when the turn ends it prints the reply (cut at 20,000 characters, with the rest saved to a file) and exits, and Claude Code wakes Claude with that output. Claude Code stops a background command after 30 minutes by default, so after 25 minutes the waiter exits on its own with the output so far and the same command to run again, and Claude starts a new one. If nouez sees no change in the turn for 10 minutes (Codex's session file and agy's event file grow every minute or so while a turn works), the waiter exits early instead, saying the consultant may be stuck, with the same command to keep waiting; Claude tells you, so a stuck turn costs 10 minutes rather than 25. A single command that runs quietly for 10 minutes looks the same. It rides out up to three failed connections in a row, such as a daemon restart. A restart interrupts the running turn and Codex carries it on in a new one; the waiter, `GetConsultantReply` and a waiting send follow it there, and the waiter says so with the reply, naming the daemon's old and new version if it changed. In a client that can't run background commands, Claude reads the reply later by calling `GetConsultantReply` with the returned `turn_id`, which returns at once. If you would rather have Claude wait, ask it to; it then passes `wait: "done"`, and the call returns when the turn ends (checked every 1.5 seconds), on an error, or after 4 hours. Claude Code keeps such a call in the foreground for about two minutes before moving it to the background. A "still working" result is never a reply. It shows the turn's output so far (the latest 4,000 characters written since the last message reached it), labelled as a snapshot that may change.

While a call waits, nouez sends MCP progress notifications (`notifications/progress`, at most one every 10 seconds) naming the turn, the time so far and the latest line of output, when the client asked for them with a progress token. Claude Code 2.1.295 asks but doesn't display them.

If waiting fails after a message was delivered, the error starts with `Delivered to`, so Claude knows not to send it again.

Replies longer than 60,000 characters are cut there. The full text is saved to `nouez/replies/reply-<turn id>.md` in your cache folder (deleted after 14 days: nouez checks when it starts and each time it saves another), and the cut reply ends with that path and the `GetConsultantReply` offset to read the rest.

When `StartConsultant` reuses a consultant, its result says when the consultant started, how many turns it has had, and what its last turn was, so Claude can tell whether it is still the right one or a fresh one is wanted. `SendConsultantMessage` says which model and effort the consultant runs on. A turn that failed inside Codex (a dropped connection, for example) is reported as such: sending the message again is safe, since the consultant keeps its context.

`WatchConsultant` and `StopConsultant` take only `to`. `StopConsultant` doesn't accept an id prefix or suffix, so a typo can't stop the wrong session. `ListConsultants` takes an optional `cwd` to list only the sessions whose working directory is in that path's git repo (outside a repo: under the Claude Code workspace folder that contains the path, or under the path itself), and an optional `include_all` (default `false`, ignored with `cwd`) to also show Codex-internal threads such as subagents.

`wait` replaced `until_done`, `timeout_seconds` and the boolean `wait` in 0.4.0; the old arguments get an error that names the new form, and nothing is sent.

Boolean arguments take `true`/`false` (or the strings `"true"`/`"false"`); any other value is an error rather than a guess.

### nouez updates

When a newer nouez is released on GitHub, `StartConsultant` adds a notice to its result with a link to the release notes. Claude tells you about it and goes on with the consultation. Ask Claude to update and it runs `git -C '<your nouez folder>' pull --ff-only` in that same session. If git fails (local changes, a conflict, or your copy has commits GitHub doesn't), Claude stops there, shows you what git said and doesn't discard anything. Only after the pull succeeds does it ask you to run `/mcp` and reconnect `consultants` to load the new version. (If the folder's name has a `'` in it, Claude asks you to run the pull yourself.) Your consultants keep their conversations. Other open Claude Code sessions keep the old version until you reconnect there too.

To find out, nouez asks GitHub for the latest release (`api.github.com/repos/jibarix/nouez/releases/latest`). It sends no sign-in and nothing from your projects or sessions: GitHub sees an HTTPS request from your IP address with `nouez/<version>` as the client name, at the time the server starts, through your proxy if you have one set. An answer is reused for 24 hours and a failed attempt waits an hour before the next, kept in `nouez/latest-release.json` in your cache folder (`%LOCALAPPDATA%` on Windows, `$XDG_CACHE_HOME` or `~/.cache` elsewhere); servers that start at the same moment may each ask. The request runs in the background when the server starts, and each network step gives up after 3 seconds, so no tool waits for it; if you're offline there is simply no notice. The notice is given once per server process. To turn the check off, set the environment variable `NOUEZ_NO_UPDATE_CHECK=1`.

You can also watch the repository on GitHub (Watch → Custom → Releases) to get an email for each release.

### Codex updates

When the `codex` CLI on your `PATH` or the app-server daemon is older than the latest Codex release, `StartConsultant` adds a notice to its result. Claude tells you about it and goes on with the consultation. The latest version comes from `version.json` in your Codex home, the cache Codex keeps for its own update check, so nouez makes no network request. If that file is missing, or you dismissed that version in Codex, there is no notice. The notice is given once per server process (normally once per Claude Code session). nouez doesn't update anything itself. Ask Claude to update and it runs `codex update` for the CLI and `codex app-server daemon update` for the daemon. Updating the daemon may interrupt running Codex work, including consultants and your own sessions.

On Windows, if `codex app-server daemon update` fails with `Cannot connect to C: resolve failed`, the daemon was started from Git Bash and its updater found GNU tar instead of Windows' tar. nouez 0.7.1 and later start the daemon without Git Bash's environment. For a daemon started some other way, run `codex app-server daemon stop` and then `codex app-server daemon start` from PowerShell or cmd, then update again.

## Troubleshooting

To check the setup, run `python "/absolute/path/to/nouez/server.py" doctor`. It prints one line per check, first Claude Code's side (Python, `claude`, the waiter's allow rules, panes), then each consultant CLI (Codex: found, signed in, daemon; Antigravity: found, version, signed in), and says what to fix. It changes nothing, though checking the daemon starts it if it isn't running, and the Antigravity check asks agy for its quota (no model turn; up to 60 seconds). One working consultant CLI is enough: a problem with the other one is shown but does not fail the check.

| Message | Fix |
|---|---|
| `` `codex` CLI not found on PATH `` | Install the Codex CLI, or make sure the shell that launches Claude Code can find it, then restart Claude Code. |
| ``Codex isn't installed: `codex` isn't on PATH`` | `StartConsultant` was asked for `provider: "codex"`. Leave `provider` out to use Antigravity, or install Codex. |
| `No consultant CLI is installed` | Install and sign in to Codex or Antigravity ([Setup](#setup), step 2), restart Claude Code, and check with `doctor`. The Claude Code session tools work meanwhile. |
| `No consultant named 'x'. Codex isn't installed` | Only Antigravity consultants exist; the message lists them. Use one of those names, or start one. If it says neither CLI is installed, see [Setup](#setup), step 2. |
| `The Antigravity CLI (agy) isn't installed or can't be found` | Install agy, or put it on the `PATH` Claude Code starts with, then restart Claude Code. |
| `agy didn't report its quota` (doctor), or `Antigravity: usage not known` | Run `agy` in a terminal and sign in, then check `agy models` (on Windows, by its full path if `agy` isn't found: doctor prints it). |
| `Antigravity has no model 'x'` | Your account doesn't offer that model. Pass one of the listed models as `model`. |
| `Codex app-server daemon is not reachable, and starting it did not help` | Run `codex app-server daemon start` in a terminal to see why it fails, or open a Codex session. |
| `No consultants` | Ask Claude to start a consultant. Without Codex, the message also says whether Antigravity is installed. |
| `'x' is ambiguous` | Use the full name or thread id from `ListConsultants`. |
| `'x' names more than one session` | Two sessions share a name (names keep only the last six characters of the id). Use the full thread id. |
| `No Codex session named 'x'. Use its exact name or full thread id.` | `StopConsultant` matches exactly. Pass the name or full id from `ListConsultants`. |
| `` `x` must be true or false `` | A boolean argument got some other value. Pass `true` or `false`. |
| `` `wait` must be a number of seconds `` | Pass seconds (`0` or more) or `"done"`. |
| `no reply within 5s` | The consultant is still working; any output shown is not the reply. This is normal for the default 5-second wait. Claude starts a waiter that brings the reply back when it is ready. |
| `nouez has seen no change from … for 10 minutes` | The waiter saw no new output for 10 minutes. The consultant may be stuck (an Antigravity one on agy's `schedule` tool, say), thinking at length or running a long command; the turn is still running. Claude tells you and runs the waiter again; ask it to stop the consultant if you'd rather not wait (a Codex session you opened yourself you stop from its terminal). |
| Claude Code asks before running `server.py wait`, or auto mode blocks it | The waiter has no permission rule. Add the rules that `python server.py allow-rule` prints (see [Setup](#setup), step 4), then start a new session. Meanwhile, ask Claude for the reply with `GetConsultantReply`. |
| `is a Codex session the user opened` | `SendConsultantMessage` refuses your own sessions by default. Ask Claude to message it if you mean to; it then passes `allow_user_session: true`. |
| `` `until_done` was replaced by `wait` `` | The caller used a pre-0.4 argument. Reconnect the server (`/mcp`) so Claude sees the new tool definitions. |
| `Delivered to ..., but waiting for the reply failed` | The message reached the consultant; only the wait failed. Don't resend it. Read the reply with `GetConsultantReply`. |
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

For the Claude Code session tools, nouez doesn't talk to Claude Code at all. `OpenClaudeSession` opens a terminal window that runs `server.py claude`, which clears the variables Claude Code sets to tie its commands to its session and starts `claude --remote-control`. It runs the `claude` on your `PATH`, never one in the project folder. `ListClaudeSessions` reads the registry Claude Code keeps in `~/.claude/sessions`. On Windows it checks that each process is still the one that wrote its entry; elsewhere it lists those whose process exists, and `CloseClaudeSession` checks the program and start time before it signals one. `CloseClaudeSession` ends the chosen process. [docs/architecture.pdf](docs/architecture.pdf) has the details.

### Files nouez keeps

Everything is on your computer, under your user account. The cache folder is `%LOCALAPPDATA%\nouez` on Windows and `$XDG_CACHE_HOME/nouez` or `~/.cache/nouez` elsewhere (a relative `XDG_CACHE_HOME` is ignored). On macOS and Linux nouez makes that folder readable by you only (0700). If it can't (the folder is another user's or a link), nouez uses `nouez-<uid>` in the temp folder instead, made private the same way, and says so.

| File | What | Kept |
|---|---|---|
| `usage-log.jsonl` | One line per consultation event: model, effort, kind, reason, tokens; never message text. Off with `NOUEZ_NO_USAGE_LOG=1`. | Renamed with the date past 20 MB |
| `agy/<id>/` | Each Antigravity consultant: its record, and each turn's message and output (`turns/`) | Until you delete it; a stopped consultant's folder stays |
| `replies/reply-<turn id>.md` | The full text of a reply longer than 60,000 characters | 14 days |
| `patches/<sha256>.patch` | The uncommitted diff a message with `revision: true` named, by the first 16 hex digits of its SHA-256 | 14 days |
| `claude-usage.json` | Claude Code's usage windows, written by `server.py statusline` | Replaced on each update |
| `usage-weeks.json` | The weekly token counts `server.py top` read from Claude Code's and Codex's own files, so later runs read only what was added | Replaced on each run of `top` |
| `claude-login.json` | The sign-in line from `claude auth status`, when it was read, the credentials file's time, Claude Code's config folder and the names of any sign-in variables set. Off with `NOUEZ_NO_LOGIN_CHECK=1`. | Replaced about hourly |
| `aa-models.json` | Model scores from Artificial Analysis, with a key set | Replaced about weekly |
| `latest-release.json` | The latest nouez release seen on GitHub | Replaced about daily |
| `pane-key` | The local key that makes the token in each pane nouez opens | Kept |
| `claude-json-backups/` | Dated copies of `~/.claude.json` from before `OpenClaudeSession` recorded trust (`$XDG_STATE_HOME/nouez` or `~/.local/state/nouez` on macOS and Linux) | The newest 20 |

`OpenClaudeSession` also passes a first prompt through a private temporary file (0600) that the new window deletes once read. Codex keeps its own sessions in `~/.codex`, Antigravity its conversations in its own folder, and Claude Code its transcripts in `~/.claude`; nouez doesn't move or copy them.

Over the network, nouez talks only to: the local Codex daemon (which talks to OpenAI with your messages, as Codex always does); `agy`, which sends your messages to Google, and whose `/usage` call asks Google for your quota without a model turn; GitHub, for the latest release; and Artificial Analysis, only with a key set. Neither of the last two gets anything from your projects or sessions.

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
- Trusting a folder lets its Claude Code settings, hooks and MCP servers run. `OpenClaudeSession` records trust only with `trust: true`, which Claude is told to pass only when you've said you trust that folder, and only after it has given that folder's report in the same conversation with the files unchanged since, so trust can't be recorded in a folder whose report Claude hasn't received; if a settings file can't be read, never. Claude still has to show you the report: nouez can't see what reaches you. It never approves MCP servers. It changes nothing else in `~/.claude.json`, but Claude Code sessions rewrite that file all the time, and nothing outside Claude Code can lock it: nouez checks the file hasn't changed just before replacing it and reads the change back after, but a session saving in that same instant could still lose a setting. That's what the dated backups are for.
- `ConsultantBudget` sends your Artificial Analysis key, if you set one, to `artificialanalysis.ai` over HTTPS about once a week. It reads `nouez/claude-usage.json` from your cache folder; only `server.py statusline`, run by your status line, writes it.
- The `nouez` tag is a guard against mistakes, not a security boundary. Any local program that can reach the Codex daemon can set the same tag, and can archive sessions directly anyway.

## Limitations

- Local only: it talks to the Codex daemon and runs `agy` on the same machine, and opens and closes Claude Code sessions on the same machine.
- `ListClaudeSessions` reads `~/.claude/sessions` (under `CLAUDE_CONFIG_DIR` if you set it), which Claude Code keeps but doesn't document. A Claude Code update could change it. On Windows a session is listed only if its entry records when its process started, so an entry can't point at an unrelated process that reused the pid.
- In Windows Terminal, the moment between bringing Claude Code's window to the front and `wt` opening the pane is short but not locked: if you click another window in that instant, the pane can land there. Two tabs with the same title in one window can't be told apart, so the pane may split the other one.
- Finding Claude Code's own Windows Terminal window, and closing a session's window, are Windows-only. Elsewhere the pane opens as before, and closing a session ends its `claude` process; its window closes only if the terminal closes when its command ends.
- On macOS, the first Codex pane or `OpenClaudeSession` window makes macOS ask whether the app Claude Code runs in may control Terminal. Allow it, or nothing opens (System Settings → Privacy & Security → Automation changes it later).
- Telling the caller's own session apart is thorough only on Windows, where nouez walks the whole chain of parent processes. Elsewhere it walks the chain with `ps`, and refuses any session it runs under; if `ps` can't be run, it knows only its immediate parent.
- Nothing can start a session on the computer from your phone unless something there is already running and connected: an open Claude Code session with Remote Control, for instance, or a [dispatcher](#a-dispatcher-for-every-project) started at sign-in.
- The trust check reads git's files, not Claude Code's code. For a worktree whose git data was moved out with `--separate-git-dir`, it says it can't tell, except when that git folder is named `.git` and sits beside other files: then nouez, like `git worktree list`, takes that folder for the main checkout.
- `ConsultantBudget` names models as Artificial Analysis does ("GPT-6.2 Sol (high)"), not by Codex model id; matching them is left to Claude. Artificial Analysis scores API access at set effort levels, which may differ from a subscription's.
- `server.py top` counts tokens from Claude Code's transcripts and Codex's session files, which neither documents; an update to either could change them. Output tokens only: a reply's input and cached tokens aren't counted.
- `server.py top` runs the screen under a small process that restarts it on an update. That process keeps its own version until you close the window. A file changed again just as the screen restarts runs unchecked; if it fails, the window waits for the next update.
- On macOS and Linux, `StopConsultant` checks a pane's program and command line, token included, just before it signals it, but by process id: if the pane ends in that instant and its number goes to another `codex` run the same way, that one is ended. Unix has no handle that rules this out on macOS.
- If you stop an Antigravity consultant and the nouez server quits in the middle of the stop, a turn whose agy later fails on its own can read as stopped rather than failed.
- An Antigravity consultant can't be kept from agy's `schedule` tool: agy has no deny rule or setting for it. Scheduling changes no files, but it can keep a turn waiting until the 30-minute limit. nouez tells the model not to schedule anything, and the waiter says a turn may be stuck after 10 minutes without a new event. agy's `-p` mode and its event stream aren't documented as stable; an agy update could change them.
- Elsewhere than Windows, only the nouez server that started an Antigravity turn can tell its process is still agy, so after a reconnect, or from another session, `StopConsultant` won't end it; it ends at agy's 30-minute limit. There, too, that server keeps its turns' processes by process id alone, and a status check can reap an ended one just as a stop signals it; the time between is very short, and the stop signals only processes it started. nouez doesn't guard against a relative entry in `PATH` that finds `agy` inside the consultant's folder, or against links placed in its cache folder; both need someone who can already change your files.
- If nouez can neither save a new Antigravity turn's process id nor end that process (a full disk, say), it says so and asks you to end agy in Task Manager. Until you do, that agy runs unseen: after 30 seconds the turn counts as failed, so another message can start a second turn beside it.
- Only the 50 most recent saved sessions are checked for unloaded consultants. Older ones can still be reached by their full thread id.
- Uses the experimental Codex app-server protocol (`thread/start`, `thread/resume`, `thread/list`, `thread/loaded/list`, `thread/read`, `thread/name/set`, `thread/turns/list`, `thread/archive`, `turn/start`, `turn/steer`, `account/rateLimits/read`, `model/list`), which may change between Codex releases. See [Tested with](#tested-with).

## Versioning

[Semantic Versioning](https://semver.org/). Releases are git tags (`v0.1.0`), and changes are listed in [CHANGELOG.md](CHANGELOG.md). Until 1.0, minor versions may include breaking changes to tool names or arguments.

## License

[MIT](LICENSE)
