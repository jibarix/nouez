# nouez

An MCP server that lets Claude Code consult live Codex sessions.

## Why

Two coding agents look at a problem differently. This bridge gives each one a fixed role:

- **Claude Code is the main developer.** It plans, writes the code or text, and owns the work.
- **Codex is the consultant.** Claude asks it for second opinions: reviewing a plan, checking a diff, finding a bug, validating a claim, or gathering context for research. The consultant only reads; it never edits your files.

Without the bridge, you run two terminals and copy text between them. With it, Claude starts a Codex consultant in the background, sends it questions, reads the answers and keeps working, all from your single Claude Code terminal. If you prefer to watch Codex work, you can still open it yourself and Claude will talk to that session instead.

## Requirements

- Python 3.9+ (standard library only, nothing to install)
- [Claude Code](https://docs.claude.com/en/docs/claude-code)
- The [Codex CLI](https://github.com/openai/codex) on your `PATH`, logged in

### Tested with

The protocol between the bridge and Codex is experimental, so this is the last combination known to work. Newer versions will probably work too, but if something breaks, compare against this table.

| Component | Version |
|---|---|
| nouez | 0.6.1 |
| Claude Code | 2.1.296 |
| Codex CLI | 0.160.1 |
| Codex app-server daemon | 0.162.1 |
| Python | 3.13.5 |
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

**4. Check it.** Run `claude mcp list`, or `/mcp` inside Claude Code. You should see `consultants` connected. Sessions that were already open keep the old server until you reconnect it there: `/mcp`, then reconnect `consultants`. Do the same after updating nouez. A change to `settings.json` applies to sessions started after it.

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

**3. Watch or join in (optional).** A background consultant is an ordinary Codex session. A consultant started by `StartConsultant` is shown automatically (pass `watch: false` to skip that); for a session you opened yourself, ask Claude to *"open the consultant in a terminal"* (`WatchConsultant`). Either way, `codex resume <id>` opens next to Claude Code: as a split pane in the same tab when Claude Code runs in Windows Terminal or tmux, otherwise in a new terminal window. You can read along there or type into the session yourself. Codex can't open a session before its first message, so the pane appears when Claude sends that message, and reappears on the next message if you close it. Without a split, Windows uses a new Windows Terminal window (falling back to a console window), macOS uses Terminal, and Linux uses `x-terminal-emulator`, `gnome-terminal` or `xterm`. Windows Terminal splits the active tab of the window you used most recently, and its command line can't target a particular tab, so stay on Claude Code's tab until the pane opens. If a terminal already shows the session, no second one opens. The window runs the Codex daemon's own `codex` binary, so it always matches the daemon's version.

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

### Tips

- **Give Codex context.** Codex can read the files in its own working directory, so start it in the same repo. Tell Claude to include the specific file, diff or question in the message.
- **Give Claude standing instructions.** A line in your project's `CLAUDE.md` makes the workflow automatic, for example: *"Before committing non-trivial changes, ask the Codex consultant to review the diff and address its findings. Reuse the existing consultant for this repo if there is one; otherwise start one."*
- **Give the consultant a role.** `StartConsultant` takes `instructions`, for example *"You are a skeptical senior reviewer. Look for bugs and missing tests; don't rewrite code."*
- **Run several consultants.** Start several, for example in different repos or with different models. `ListConsultants` shows each one's name and working directory so Claude can pick the right one.
- **Long tasks.** By default Claude waits 5 seconds after sending, enough to confirm delivery and catch a quick answer, then starts a small waiter in the background, tells you the consultation is under way, and is free again, and so are you. When Codex finishes, the waiter exits with the reply and Claude Code wakes Claude with it, so Claude acts on the answer or reports it without you asking. Claude needs permission to run the waiter; see [Setup](#setup), step 3.
- **Idle consultants.** After about a minute without activity, the Codex daemon unloads a consultant. It still appears in `ListConsultants`, and the next message reloads it with the same sandbox and history.
- **Clean up.** Ask Claude to stop consultants when you're done, so they don't pile up in your Codex session list. Stopping archives a session rather than deleting it, and closes its watch window. On Windows, only windows the bridge opened are closed. On macOS and Linux, any `codex resume <id>` process for that session is ended, and a macOS Terminal window stays open at a shell prompt.

## Tools

| Tool | What it does |
|---|---|
| `StartConsultant` | Starts a background Codex session in a project directory (always read-only; never asks for approvals). If a consultant it started already works in that project, returns it and starts nothing unless `new: true`. Never reuses a session you opened yourself. |
| `ListConsultants` | Lists Codex sessions loaded on the local daemon, plus recent `StartConsultant` sessions it has unloaded, with each one's name, working directory, model, status and who started it. With `cwd`, only the sessions in that repo. |
| `SendConsultantMessage` | Sends a message into a session, waits 5 seconds by default, and returns the reply if it is ready by then, or the turn id and a waiter command if not. If the session is idle the message starts a new turn; if it's busy it steers the running turn. Unloaded sessions are reloaded first. Refuses a session you opened yourself unless `allow_user_session: true`. |
| `GetConsultantReply` | Reads a reply without sending anything: the latest turn, or a specific turn id. Use it after sending with `wait: 0` or after a timeout. While the turn runs, it shows the output so far. |
| `WatchConsultant` | Opens a session in a split pane beside Claude Code, or a new terminal window, so you can watch it or type into it. Does nothing if a terminal already shows it. |
| `StopConsultant` | Archives a session that `StartConsultant` started and closes any terminal window watching it. Needs the exact name or full thread id. Refuses sessions you opened yourself. |

`StartConsultant` arguments (all optional):

| Argument | Default | Meaning |
|---|---|---|
| `cwd` | Claude Code's first workspace folder | Absolute path of the project Codex works in |
| `model` | your Codex config | Codex model (new sessions only) |
| `title` | | Session title shown in Codex (new sessions only) |
| `instructions` | | Standing instructions for the consultant's role (new sessions only) |
| `watch` | `true` | Show the session in a pane beside Claude Code once it has its first message, and again on later messages if the pane was closed |
| `new` | `false` | Start a new session even though a consultant already works in this project |

`SendConsultantMessage` arguments:

| Argument | Required | Default | Meaning |
|---|---|---|---|
| `to` | yes | | Session name from `ListConsultants` (e.g. `codex-myproject-a1b2c3`), full thread id, or unique id prefix/suffix. `name` is accepted as an alias. |
| `message` | yes | | The text to send |
| `from` | no | `Claude Code` | Sender label shown to Codex |
| `wait` | no | `5` | How long to wait for the reply: seconds (`0` returns once the message is delivered), or `"done"` to wait until the turn ends. Capped at 4 hours |
| `allow_user_session` | no | `false` | Allow sending to a session you opened yourself. Claude sets it only when you ask |

`GetConsultantReply` takes `to`, an optional `turn_id` (default: the latest turn; looked up among the 100 most recent turns), and an optional `wait` like `SendConsultantMessage`'s, but defaulting to `0`, which returns at once if the turn is still running.

Most replies take longer than the default 5 seconds. Claude is told not to wait for them. Instead the result gives a waiter command, `python server.py wait <thread_id> <turn_id>` with full paths, which Claude runs as a background command (the Bash or PowerShell tool with `run_in_background`). A path is quoted only if it contains a space, so the command runs as is in either shell and the permission rules from `allow-rule` match it. The waiter checks the turn every 1.5 seconds; when the turn ends it prints the reply (cut at 20,000 characters, with the rest saved to a file) and exits, and Claude Code wakes Claude with that output. Claude Code stops a background command after 30 minutes by default, so after 25 minutes the waiter exits on its own with the output so far and the same command to run again, and Claude starts a new one. It rides out up to three failed connections in a row, such as a daemon restart. In a client that can't run background commands, Claude reads the reply later by calling `GetConsultantReply` with the returned `turn_id`, which returns at once. If you would rather have Claude wait, ask it to; it then passes `wait: "done"`, and the call returns when the turn ends (checked every 1.5 seconds), on an error, or after 4 hours. Claude Code keeps such a call in the foreground for about two minutes before moving it to the background. A "still working" result is never a reply. It shows the turn's output so far (the latest 4,000 characters written since the last message reached it), labelled as a snapshot that may change.

While a call waits, nouez sends MCP progress notifications (`notifications/progress`, at most one every 10 seconds) naming the turn, the time so far and the latest line of output, when the client asked for them with a progress token. Claude Code 2.1.295 asks but doesn't display them.

If waiting fails after a message was delivered, the error starts with `Delivered to`, so Claude knows not to send it again.

Replies longer than 60,000 characters are cut there. The full text is saved to `nouez/<turn id>.md` in the system temp folder, and the cut reply ends with that path.

`WatchConsultant` and `StopConsultant` take only `to`. `StopConsultant` doesn't accept an id prefix or suffix, so a typo can't stop the wrong session. `ListConsultants` takes an optional `cwd` to list only the sessions whose working directory is in that path's git repo (outside a repo: under the Claude Code workspace folder that contains the path, or under the path itself), and an optional `include_all` (default `false`, ignored with `cwd`) to also show Codex-internal threads such as subagents.

`wait` replaced `until_done`, `timeout_seconds` and the boolean `wait` in 0.4.0; the old arguments get an error that names the new form, and nothing is sent.

Boolean arguments take `true`/`false` (or the strings `"true"`/`"false"`); any other value is an error rather than a guess.

## Troubleshooting

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
| Anything else after updating Codex | Compare your versions with the [Tested with](#tested-with) table. The Codex app-server protocol may have changed. |

## How it works

`codex app-server proxy` relays stdio to the daemon's control socket, which speaks JSON-RPC over WebSocket. The server does the WebSocket handshake and framing itself, opens one short-lived connection per tool call, and polls the turn until it finishes. Sessions the bridge starts are tagged with `threadSource: "nouez"`, so it can find them again after the daemon unloads them and so `StopConsultant` knows which ones it may archive.

## Tests

The protocol tests use only the standard library and don't need Codex. From the repo root:

```sh
python -m unittest discover tests
```

## Security note

- Every Claude Code session with this server enabled can send messages into **any** Codex session on the machine, and those messages run with that session's permissions and sandbox settings. Enabling the server gives Claude the ability to drive your Codex sessions. If you register the server with `--scope user`, this applies to every project you open in Claude Code.
- Consultants started by the bridge never ask for approvals, so their read-only sandbox is the only limit. They can't edit files, but they can read anything the sandbox allows, which typically includes files outside `cwd`. Write access can't be requested through the bridge. A session you open yourself keeps its own permissions, and messages sent to it run with them.
- The `nouez` tag is a guard against mistakes, not a security boundary. Any local program that can reach the Codex daemon can set the same tag, and can archive sessions directly anyway.

## Limitations

- Local only: it talks to the Codex daemon on the same machine.
- Only the 50 most recent saved sessions are checked for unloaded consultants. Older ones can still be reached by their full thread id.
- Uses the experimental Codex app-server protocol (`thread/start`, `thread/resume`, `thread/list`, `thread/loaded/list`, `thread/read`, `thread/name/set`, `thread/turns/list`, `thread/archive`, `turn/start`, `turn/steer`), which may change between Codex releases. See [Tested with](#tested-with).

## Versioning

[Semantic Versioning](https://semver.org/). Releases are git tags (`v0.1.0`), and changes are listed in [CHANGELOG.md](CHANGELOG.md). Until 1.0, minor versions may include breaking changes to tool names or arguments.

## License

[MIT](LICENSE)
