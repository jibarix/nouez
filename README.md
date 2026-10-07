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
| nouez | 0.2.0 |
| Claude Code | 2.1.293 |
| Codex CLI | 0.160.1 |
| Codex app-server daemon | 0.161.0 |
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

**3. Check it.** Run `claude mcp list`, or `/mcp` inside Claude Code. You should see `consultants` connected.

## Usage

**1. Make sure the Codex daemon is running.** It starts automatically whenever you open Codex. To start it on its own, run:

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

**3. Watch or join in (optional).** A background consultant is an ordinary Codex session. To see it work, ask Claude to start it with `watch: true`, or ask it to *"open the consultant in a terminal"* later (`WatchConsultant`). Either way, `codex resume <id>` opens next to Claude Code: as a split pane in the same tab when Claude Code runs in Windows Terminal or tmux, otherwise in a new terminal window. You can read along there or type into the session yourself. Codex can't open a session before its first message, so with `watch: true` the window appears when Claude sends that message. Without a split, Windows uses a new Windows Terminal window (falling back to a console window), macOS uses Terminal, and Linux uses `x-terminal-emulator`, `gnome-terminal` or `xterm`. Windows Terminal splits the active tab of the window you used most recently, and its command line can't target a particular tab, so stay on Claude Code's tab until the pane opens. If a terminal already shows the session, no second one opens. The window runs the Codex daemon's own `codex` binary, so it always matches the daemon's version.

### Reusing a consultant

A consultant keeps its whole conversation until you stop it, so you can keep going back to the same one. Refer to it and Claude finds it with `ListConsultants`:

> Ask the consultant to check the diff.

> Send this to codex-myproject-a1b2c3: …

> Open the consultant so I can watch.

This works from a new Claude Code session too: consultants that went idle still appear in the list, and the next message reloads them. Reuse is the default. The bridge tells Claude to list the consultants for its repo before starting one, and `StartConsultant` won't start another while one already works in the same git repo; it lists the existing ones instead. When you want a clean slate, ask for a new one, and Claude passes `new: true`:

> Start a new Codex consultant I can watch.

> Start a second consultant in ~/projects/other-repo and ask it to …

With more than one consultant running, name the one you mean. Once stopped, a consultant is archived and Claude can't reach it. To bring it back, run `codex unarchive <id>` (the id is in the stop message).

### Using a Codex session you opened yourself

If you'd rather see Codex work in its own window, open it yourself (`cd my-project && codex`) and ask Claude to *"list the consultants and send it …"*. Claude finds the session with `ListConsultants` and talks to it the same way. The message appears in that terminal as a new prompt. Sessions you open yourself use their own permission settings and approval prompts, and `StopConsultant` won't close them.

### Tips

- **Give Codex context.** Codex can read the files in its own working directory, so start it in the same repo. Tell Claude to include the specific file, diff or question in the message.
- **Give Claude standing instructions.** A line in your project's `CLAUDE.md` makes the workflow automatic, for example: *"Before committing non-trivial changes, ask the Codex consultant to review the diff and address its findings. Reuse the existing consultant for this repo if there is one; otherwise start one with watch on."*
- **Give the consultant a role.** `StartConsultant` takes `instructions`, for example *"You are a skeptical senior reviewer. Look for bugs and missing tests; don't rewrite code."*
- **Run several consultants.** Start several, for example in different repos or with different models. `ListConsultants` shows each one's name and working directory so Claude can pick the right one.
- **Long tasks.** By default Claude waits up to 10 minutes for a reply. For long jobs, ask Claude to send with `wait: false` and keep working. It can read the answer later with `GetConsultantReply`.
- **Idle consultants.** After about a minute without activity, the Codex daemon unloads a consultant. It still appears in `ListConsultants`, and the next message reloads it with the same sandbox and history.
- **Clean up.** Ask Claude to stop consultants when you're done, so they don't pile up in your Codex session list. Stopping archives a session rather than deleting it, and closes its watch window. On Windows, only windows the bridge opened are closed. On macOS and Linux, any `codex resume <id>` process for that session is ended, and a macOS Terminal window stays open at a shell prompt.

## Tools

| Tool | What it does |
|---|---|
| `StartConsultant` | Starts a background Codex session in a project directory (always read-only; never asks for approvals). If sessions already work in that git repo, lists them and starts nothing unless `new: true`. |
| `ListConsultants` | Lists Codex sessions loaded on the local daemon, plus recent `StartConsultant` sessions it has unloaded, with each one's name, working directory, model, status and who started it. With `cwd`, only the sessions in that repo. |
| `SendConsultantMessage` | Sends a message into a session and, by default, waits for and returns the reply. If the session is idle the message starts a new turn; if it's busy it steers the running turn. Unloaded sessions are reloaded first. |
| `GetConsultantReply` | Reads a reply without sending anything: the latest turn, or a specific turn id. Use it after sending with `wait: false` or after a timeout. |
| `WatchConsultant` | Opens a session in a split pane beside Claude Code, or a new terminal window, so you can watch it or type into it. Does nothing if a terminal already shows it. |
| `StopConsultant` | Archives a session that `StartConsultant` started and closes any terminal window watching it. Refuses sessions you opened yourself. |

`StartConsultant` arguments (all optional):

| Argument | Default | Meaning |
|---|---|---|
| `cwd` | the bridge server's working directory | Absolute path of the project Codex works in |
| `model` | your Codex config | Codex model |
| `title` | | Session title shown in Codex |
| `instructions` | | Standing instructions for the consultant's role |
| `watch` | `false` | Open the session in a terminal window when its first message is sent |
| `new` | `false` | Start a new session even though sessions already work in this git repo |

`SendConsultantMessage` arguments:

| Argument | Required | Default | Meaning |
|---|---|---|---|
| `to` | yes | | Session name from `ListConsultants` (e.g. `codex-myproject-a1b2c3`), full thread id, or unique id prefix/suffix |
| `message` | yes | | The text to send |
| `from` | no | `Claude Code` | Sender label shown to Codex |
| `wait` | no | `true` | Wait for the reply |
| `timeout_seconds` | no | `600` | Maximum time to wait for the reply |

`GetConsultantReply` takes `to`, an optional `turn_id` (default: the latest turn; looked up among the 100 most recent turns), and an optional `timeout_seconds` (default `0`, which returns at once if the turn is still running).

`WatchConsultant` and `StopConsultant` take only `to`. `ListConsultants` takes an optional `cwd` to list only the sessions whose working directory is in that path's git repo (or under the path, outside a repo), and an optional `include_all` (default `false`, ignored with `cwd`) to also show Codex-internal threads such as subagents.

## Troubleshooting

| Message | Fix |
|---|---|
| `` `codex` CLI not found on PATH `` | Install the Codex CLI, or make sure the shell that launches Claude Code can find it. |
| `Codex app-server daemon is not reachable` | Open a Codex session, or run `codex app-server daemon start`. |
| `No Codex sessions` | Ask Claude to start a consultant, or open Codex in a terminal. |
| `'x' is ambiguous` | Use the full name or thread id from `ListConsultants`. |
| `no reply within 600s` | Codex is still working. Ask Claude to read it later with `GetConsultantReply`, or to wait longer with `timeout_seconds`. |
| `was not started by StartConsultant` | That's a session you opened yourself. Close it from its own terminal. |
| `Not started: ... already work in` | A consultant already works in this repo. Send to it, or ask for a new one (`new: true`). |
| The terminal window opens but shows an error | Make sure `codex` is on the `PATH` of new terminals, and that the session has had its first message. |
| The terminal window asks to restart the daemon ("incompatible feature set") | The window's `codex` is a different version from the daemon. Choose **Cancel**: restarting interrupts running consultants, and running without the daemon shows a separate copy of the session. The bridge normally avoids this by using the daemon's own binary; if it warned that it couldn't find it, update the Codex CLI to the daemon's version. |
| Anything else after updating Codex | Compare your versions with the [Tested with](#tested-with) table. The Codex app-server protocol may have changed. |

## How it works

`codex app-server proxy` relays stdio to the daemon's control socket, which speaks JSON-RPC over WebSocket. The server does the WebSocket handshake and framing itself, opens one short-lived connection per tool call, and polls the turn until it finishes. Sessions the bridge starts are tagged with `threadSource: "nouez"`, so it can find them again after the daemon unloads them and so `StopConsultant` knows which ones it may archive.

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
