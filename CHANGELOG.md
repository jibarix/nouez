# Changelog

All notable changes to this project are recorded here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and versions follow
[Semantic Versioning](https://semver.org/).

## [Unreleased]

## [0.11.2] - 2026-11-12

Anyone who installs nouez can set up their own model and effort routing. Tested with Claude Code 2.1.322, Codex CLI 0.165.0 with app-server daemon 0.167.2, Python 3.13.5 on Windows 11.

### Added
- README: "Choosing model and effort" explains where a consultant's model and effort come from, how Claude changes them, and how to write your own routing rules in `~/.claude/CLAUDE.md` so they apply in every project, with a template to adapt.

### Changed
- The server instructions tell Claude to change a consultant's model or effort only when the user asks or the user's own instructions call for it, and to send the usual values again once the harder part is done, since the setting stays.

## [0.11.1] - 2026-11-12

Fixes from a Codex review of 0.11.0. Tested with Claude Code 2.1.322, Codex CLI 0.165.0 with app-server daemon 0.167.2, Python 3.13.5 on Windows 11.

### Fixed
- `model` refused ids with `:` or `/`, such as `gpt-oss:20b` from a local provider. nouez now refuses only an empty value, blanks and control characters, and leaves the rest to Codex.
- A reply that came back within the wait didn't say that `model` or `effort` had changed for later messages. It now ends with a line naming the new setting.

### Changed
- The `effort` description gives levels as examples and says they depend on the model, instead of a fixed list.
- The docs say the busy check covers turns nouez can see: a turn another client starts at the same moment isn't caught, as with the choice between starting and steering a turn.

## [0.11.0] - 2026-11-12

A consultant's Codex model and reasoning effort can be changed while it keeps its context. Tested with Claude Code 2.1.322, Codex CLI 0.165.0 with app-server daemon 0.167.2, Python 3.13.5 on Windows 11.

### Added
- `SendConsultantMessage` takes `model` and `effort`, such as `effort: "xhigh"` for a hard question or `model: "gpt-6-astra"`, so a consultant can be turned up or down without starting a new session. They go into Codex's `turn/start`, and Codex keeps them for the session's later turns too: the result says so, and going back means sending the usual values again. Each must be a plain name (letters, digits, `.`, `_`, `-`); Codex rejects one the model doesn't support. A running turn can't change them, so a send with either to a busy consultant is refused and nothing is sent; send again once the turn ends, or without them to steer the running turn.
- When `StartConsultant` reuses a consultant and ignores `model`, its result points to `SendConsultantMessage`'s `model`.

## [0.10.0] - 2026-11-07

`OpenClaudeSession` can record that the user trusts a folder, so a session in a new project can be opened from the phone. Tested with Claude Code 2.1.319 and Python 3.11.9 on Windows 11; the Codex side was last tested with Codex CLI 0.165.0 and app-server daemon 0.165.0, with nouez 0.7.1.

### Added
- `OpenClaudeSession` takes `trust: true`, for when the user has said they trust the folder. nouez records that in Claude Code's state file (`~/.claude.json`, under `CLAUDE_CONFIG_DIR` if set) as `hasTrustDialogAccepted` for the folder Claude Code keeps it on (in git, the repository's root; for a worktree, its main checkout), the way the trust dialog does, and then opens the window. Before each change it saves a dated copy of the file to its own folder (`%LOCALAPPDATA%\nouez\claude-json-backups`, or `$XDG_STATE_HOME`/`~/.local/state/nouez/claude-json-backups`), keeps the newest 20, and names the copy in the result. Only that one value changes; the file is checked unchanged just before it's replaced and read back after. It refuses the home folder, a drive's root, Claude Code's own folder and git layouts it can't place, and changes nothing when the file can't be read or isn't laid out as expected.

### Changed
- Sessions `OpenClaudeSession` opens start on Opus at medium effort (`--model opus --effort medium`) instead of the user's Claude Code defaults. `model` and `effort` arguments choose others, when the user asks; a model must be an alias or a model's full name, never something that reads as an option.
- When a folder isn't trusted, the result tells Claude to ask the user whether they trust it, and to pass `trust: true` only if they say yes, instead of sending them to the computer. `open_untrusted: true` still opens a window that waits at the trust question.

## [0.9.0] - 2026-11-07

`StartConsultant` says when a newer nouez is out, and `OpenClaudeSession` can create the folder and won't open a window that would sit at the trust question. Tested with Claude Code 2.1.319 and Python 3.11.9 on Windows 11; the Codex side was last tested with Codex CLI 0.165.0 and app-server daemon 0.165.0, with nouez 0.7.1.

### Added
- When a newer nouez is released on GitHub, `StartConsultant`'s result starts its notices with one that names both versions and links to the release notes. Claude tells the user and goes on with the consultation. Only if the user asks does Claude update, by running `git -C '<nouez folder>' pull` (the folder in single quotes, which PowerShell and POSIX shells read literally; for a folder whose name has a `'`, Claude asks the user to run the pull). If git fails, Claude stops, shows what git said and discards nothing; only after a successful pull does it ask the user to reconnect with `/mcp`. To find the latest release, nouez asks GitHub's API (`releases/latest`) with no credentials, in the background when the server starts, with a 3-second timeout on each network step. GitHub sees the request's IP address, time and `nouez/<version>` client name, and nothing from projects or sessions. An answer is reused for 24 hours and a failed attempt waits an hour, kept in `nouez/latest-release.json` in the user's cache folder. If the lookup fails, there is no notice, and nothing about the check (a bad cache file, a thread that can't start) can fail `initialize` or `StartConsultant`. The notice appears once per server process. Set `NOUEZ_NO_UPDATE_CHECK=1` to turn the lookup off.
- `OpenClaudeSession` takes `create: true` to make the folder if it doesn't exist (its parent must). In a folder Claude Code hasn't been trusted in, it no longer opens a window that would sit at the trust question and never connect to the app: it opens nothing, and Claude tells the user to answer the question on the computer. `open_untrusted: true` opens the window anyway, for a user at the computer. nouez only reads `~/.claude.json` (under `CLAUDE_CONFIG_DIR` if set) and never answers the question itself. When a trusted folder may still ask on the computer (a `.mcp.json`, whose servers are approved separately, or a `.claude/settings.json` whose allow rules need the folder itself trusted, not just one above it), the result says so, and when nouez can't tell whether a folder is trusted, the result says that too.

### Fixed
- The trust check behind `OpenClaudeSession`'s warning treated a git repository inside a trusted folder as trusted. Claude Code trusts a repository only on its own (a worktree through its main checkout), so a session there waited at the trust question with no warning. The check now follows Claude Code's rule. A worktree whose git data is kept outside its main checkout (`--separate-git-dir`, even when that folder is itself named `.git`) counts as unknown rather than being keyed on the wrong folder. The `.mcp.json` and `.claude/settings.json` notes look in the folder being opened, so a worktree's own files count.
- README: the consultant window uses the daemon's `codex` binary when it can find it, and otherwise the one on the `PATH` with a warning, not always the daemon's. Session listing checks a process's identity only on Windows, and the caller's own session is recognised through the whole chain of parent processes only on Windows.

## [0.8.0] - 2026-11-07

Consultant panes open beside the Claude Code session that asked for them, and a session can open, list and close other Claude Code sessions on the computer. Tested with Claude Code 2.1.319 and Python 3.11.9 on Windows 11; the Codex side was last tested with Codex CLI 0.165.0 and app-server daemon 0.165.0, with nouez 0.7.1.

### Added
- `OpenClaudeSession` opens a new terminal window and starts an interactive Claude Code session there with Remote Control, so you can ask a session you're driving from your phone for another one, in another project. The session saves its transcript like one you started yourself. A `claude` started from Claude Code's own shell inherits `CLAUDE_CODE_CHILD_SESSION` and the other variables that tie it to its parent, and doesn't save its transcript; the new session starts without them. Only those go: your own settings, such as `CLAUDE_CODE_OAUTH_TOKEN` or a provider choice, stay. It runs the `claude` on your `PATH`, never one in the project folder, and passes the first prompt after `--`, so a prompt can't turn into an option. The name and first prompt reach it through a temporary file, which keeps the prompt off Windows Terminal's command line (the name is the window title, and both become arguments of the `claude` process). The result warns when the folder hasn't been trusted yet, since the new session would wait at the trust prompt on the computer.
- `ListClaudeSessions` lists the Claude Code sessions running on the computer, whoever started them: name, process id, folder, status, whether Remote Control is on, and which one is the caller. It reads the registry Claude Code keeps in `~/.claude/sessions` (under `CLAUDE_CONFIG_DIR` if set) and, on Windows, lists an entry only while a process created at the time it records is running.
- `CloseClaudeSession` closes one of them, such as a stuck one, by name (or process id when names repeat): it ends its `claude` process and keeps the transcript, so it can be resumed. A session `OpenClaudeSession` opened also gets its window closed; for others the terminal stays open at the shell prompt. On Windows it holds the process open from the identity check to the end, so the pid can't pass to another process in between, and it reports an error if the process is still running. It never closes the caller, and Claude is told to show you the list and close only the ones you pick.

### Fixed
- With two or more Windows Terminal windows open, a consultant's pane opened in whichever window was used last, often another Claude Code session's. It now opens in the window running the Claude Code session that asked for it. The server finds that window through Claude Code's console and brings it to the front just while `wt` runs, then gives the focus back. If Claude Code's tab isn't the selected one in its window, the consultant gets a new tab there. If the window can't be found or brought to the front, the consultant gets a new window rather than a pane in another session's window. Names and folders with a `;` no longer break `wt`, which reads it as the start of another command.

## [0.7.1] - 2026-10-28

`codex app-server daemon update` works on a daemon nouez started from Git Bash. Tested with Claude Code 2.1.312, Codex CLI 0.165.0 with app-server daemon 0.165.0, Python 3.13.5 on Windows 11.

### Fixed
- On Windows, a daemon that nouez started from Git Bash (the waiter runs in Claude Code's Bash tool) inherited MSYS's `PATH`, and so did its updater. The update script's bare `tar` then found GNU tar, which reads `C:` as a remote host, and `codex app-server daemon update` failed with "Cannot connect to C: resolve failed". When `MSYSTEM` is set, nouez now starts the daemon without Git Bash's variables (`MSYSTEM`, `SHELL`, `EXEPATH`) and without the `PATH` folders that hold `msys-2.0.dll`, such as `Git\usr\bin`. Outside Git Bash the environment is passed on unchanged. A daemon started before this version keeps its environment until it is stopped: run `codex app-server daemon stop` from PowerShell or cmd, then `codex app-server daemon start`.

## [0.7.0] - 2026-10-28

`StartConsultant` says when Codex is out of date. Tested with Claude Code 2.1.312, Codex CLI 0.163.0 with app-server daemon 0.162.1, Python 3.13.5 on Windows 11.

### Added
- When the `codex` CLI on the PATH or the app-server daemon is older than the latest Codex release, `StartConsultant`'s result ends with a notice. It names the versions and tells Claude to let the user know and go on with the consultation. Only if the user asks does Claude update, with `codex update` for the CLI and `codex app-server daemon update` for the daemon (which may interrupt running Codex work). The latest version comes from the cache Codex keeps for its own update check (`version.json` in the Codex home), so there is no network request. The notice appears once per server process, and not for a version the user dismissed in Codex.

## [0.6.1] - 2026-10-14

The waiter works in new conversations, under either shell and without a permission prompt. Tested with Claude Code 2.1.296, Codex CLI 0.160.1 with app-server daemon 0.162.1, Python 3.13.5 on Windows 11.

### Added
- `server.py allow-rule` prints the Claude Code permission rules (Bash and PowerShell) that let the waiter run without asking, including in auto mode. The README's setup now has a step for them.

### Fixed
- Claude Code stops a background command after 30 minutes by default, which killed the waiter on long consultations. The waiter now exits after 25 minutes with the output so far and the command to run again.
- The waiter command quotes a path only if it contains a space, so it runs as is in PowerShell as well as bash, and a permission rule can match it by prefix. Claude is told it may use the Bash or the PowerShell tool.

## [0.6.0] - 2026-10-14

A finished consultation now wakes Claude with the reply. Tested with Claude Code 2.1.296, Codex CLI 0.160.1 with app-server daemon 0.162.1, Python 3.13.5 on Windows 11.

### Added
- `server.py wait <thread_id> <turn_id>`: waits until a turn ends, prints its reply (up to 20,000 characters; the rest is saved to a file) and exits. Run as a background command, its exit wakes Claude with the reply. It rides out up to three failed connections in a row and gives up after 4 hours.

### Changed
- When a send returns before the reply, its result gives the waiter command with full paths and tells Claude to run it in the background, then carry on or end its turn. The server instructions say the same. `GetConsultantReply`'s 'still working' result offers the waiter too.

## [0.5.0] - 2026-10-13

Claude no longer waits for a consultant's reply by default, and the Codex daemon is started when it isn't running. Tested with Claude Code 2.1.296, Codex CLI 0.160.1 with app-server daemon 0.162.1, Python 3.13.5 on Windows 11.

### Changed
- `SendConsultantMessage` waits 5 seconds by default instead of 600: long enough to confirm delivery and return a quick reply, short enough that Claude is free again right away. Read a longer reply with `GetConsultantReply`, or pass a larger `wait` when sending.
- The server instructions and the results of a send no longer tell Claude to wait for the reply with `wait: "done"`. Claude now says the consultation is under way and carries on or ends its turn, and reads the reply when asked or when it next needs it. `wait: "done"` remains for when the user wants Claude to wait.
- When the Codex daemon is not running (for example after a reboot), the first tool call starts it with `codex app-server daemon start` and retries, instead of failing with `Codex app-server daemon is not reachable`. The error now appears only if the daemon still can't be reached about 20 seconds later.

## [0.4.0] - 2026-10-09

Breaking: `SendConsultantMessage` and `GetConsultantReply` take a single `wait` argument instead of `wait`, `timeout_seconds` and `until_done`.

### Changed
- `wait` is a number of seconds (`0` means don't wait) or `"done"` (wait until the turn ends, up to 4 hours). Defaults: 600 seconds for `SendConsultantMessage`, 0 for `GetConsultantReply`. The old arguments are refused with an error that names the new form, before anything is sent. The old `wait: true/false` is refused too.
- `SendConsultantMessage` refuses a Codex session the user opened unless `allow_user_session: true`. Such a session keeps the user's permissions and may be able to edit files; until now only the instructions kept Claude from messaging it. Nothing is sent when it refuses.

### Added
- Progress notifications. When a `tools/call` carries a progress token, a waiting `SendConsultantMessage` or `GetConsultantReply` sends `notifications/progress` at most every 10 seconds, with the turn id, the time so far and the latest line of output. None are sent after a cancellation.

### Fixed
- `wait` with a number too large for a float (such as `1e400` written out as an integer) gave "Unexpected error"; it now gets the usual `wait` error.
- Deadlines and waited times use a monotonic clock, so a system clock change can't cut a wait short or stretch it.

## [0.3.2] - 2026-10-09

Fixes from a Codex review of 0.3.1 and of the architecture document.

### Fixed
- `StartConsultant` could reuse a Codex session the user opened. That session keeps the user's permissions, so a "read-only consultant" could edit files. It now reuses only sessions it started, which are always read-only, and lists the user's sessions in its result without using them.
- Two sessions can share a name (names keep only the last six characters of the id), and the first one silently won, including for `StopConsultant`. A shared name is now refused with both full ids.
- If waiting for a reply failed after the message was delivered, the result was a plain error that invited a resend. It now starts with `Delivered to`, gives the turn id, and says not to send the message again.
- A timeout after an interrupted turn moved on to its continuation reported the original turn id. It now reports the turn the message continued in.
- A request with `"id": null` was treated as a notification and got no response; it now gets `-32600 Invalid Request`. `params: []` and `arguments: []` were read as `{}`; they now get `-32602 Invalid params`.
- Opening a pane now checks the thread id like closing one does, so a malformed id never reaches a command line.

### Changed
- A timeout shows the turn's output so far: the latest 4,000 characters written since the last message reached the turn, labelled as a snapshot that is not the reply. This applies to `SendConsultantMessage` and `GetConsultantReply`, and to `GetConsultantReply` while it waits.
- Timeout and "still working" results name the turn id to pass to `GetConsultantReply`.
- `StartConsultant` says when `model`, `title` or `instructions` were ignored because a consultant was reused, and `watch` now also applies when reusing one.
- Tool descriptions and the server instructions match the code: reuse is limited to nouez's own sessions, until_done returns when the turn ends, on an error or after 4 hours, and closing windows is best effort.

### Added
- Tool annotations: `ListConsultants` and `GetConsultantReply` are read-only, `StopConsultant` is destructive, and `WatchConsultant` is idempotent.
- Tests for the handlers against a fake daemon (reuse, partial output, failure after delivery), shared names, and the new protocol cases.

## [0.3.1] - 2026-10-09

Hardening from an MCP best-practices review. Tested with Claude Code 2.1.295, Codex CLI 0.160.1 with app-server daemon 0.162.0, Python 3.13.5 on Windows 11.

### Fixed
- One malformed line could stop the server. A JSON value that isn't an object (such as `[]`), an id that isn't a string or number, or a `notifications/cancelled` with non-object params raised in the read loop, and every later request went unanswered. These now get `-32600 Invalid Request` (or are ignored, for notifications), and no single message can end the loop.
- `initialize` echoed whatever protocol version the client asked for, even ones the server doesn't know. It now answers with the requested version if it is one of 2025-11-25, 2025-06-18 or 2025-03-26, and with 2025-11-25 otherwise.
- `tools/call` with params or `arguments` that aren't objects never got a response, or got an "Unexpected error" result. Both now get `-32602 Invalid params`, and any request with an id gets a response even if handling it fails (`-32603`).
- `timeout_seconds` accepted negative and non-finite numbers ("no reply within -5s"). It must now be 0 or more.
- `StopConsultant` could report "Unexpected error" for a stop that had succeeded, if PowerShell printed something unexpected while closing the watch window.

### Changed
- Waits are capped at 4 hours, `until_done` included, so a hung Codex turn can't hold a call and its Codex connection forever. When the cap is reached the result says the turn is still running, as for any timeout.
- Replies longer than 60,000 characters are cut, and the full text is saved to `nouez/<turn id>.md` in the system temp folder.
- `StopConsultant` only accepts the exact name or full thread id, not a unique prefix or suffix.
- A send that times out now says not to send the message again.

### Added
- Protocol tests in `tests/` (standard library only, no Codex needed): `python -m unittest discover tests`.

## [0.3.0] - 2026-10-08

Tested with Claude Code 2.1.295, Codex CLI 0.160.1 with app-server daemon 0.162.0, Python 3.13.5 on Windows 11.

### Fixed
- `ListConsultants` with `cwd` and `StartConsultant` could hang indefinitely on Windows. Finding the repo ran `git rev-parse`; when git stalled, Python's `subprocess.run` killed only the `Git\cmd\git.exe` wrapper at the timeout and then waited, with no limit, for pipes still held by the real `git.exe`. The repo root is now found by looking for `.git`, with no subprocess.
- All helper commands (`codex --version`, PowerShell process checks, `taskkill`, `pgrep`) kill the whole process tree on timeout and never wait on pipes afterwards.
- The daemon handshake deadline no longer depends on the killed proxy closing its pipe.
- A long Codex turn gave no signal when it finished. `GetConsultantReply` returned "still working" when its timeout ran out, and a client running the call in the background reported that as done, so a finished reply could sit unread.
- Outside git, a consultant started at the project top wasn't found from a subfolder, so `StartConsultant` started a duplicate. Sessions are now matched against Claude Code's workspace folder (MCP roots): outside a repo, a path belongs to the workspace folder that contains it. Inside a git repo, the repo still decides.
- Boolean arguments sent as strings were read as true whenever the string was non-empty, so `"false"` meant true. `until_done`, `wait`, `new`, `watch` and `include_all` now accept `true`/`false` or `"true"`/`"false"` and reject anything else with an error, and `timeout_seconds` must be a number.

### Changed
- `StartConsultant` is the one call for getting a consultant. It searches the repo first: if a session already works there, it returns that one as the consultant to use (preferring `StartConsultant` sessions, most recent first) instead of refusing with "Not started"; if none is found, it starts one. The MCP instructions tell Claude to call it whenever the user asks for a consultant, even when its earlier context about the consultant was compacted away, so no `ListConsultants` call is needed first.
- `GetConsultantReply` and `SendConsultantMessage` take `until_done`: wait until the turn ends, with no time limit (still cancellable). "Still working" results say they are not a reply and point to `until_done`, and the MCP instructions describe the send-then-wait pattern.
- `watch` now defaults to `true`. `StartConsultant` sessions are shown in a pane beside Claude Code: on their first message, when reused, and again on the next message if the pane was closed. This no longer depends on in-memory state, so it survives an MCP reconnect.
- `StartConsultant` without `cwd` uses Claude Code's workspace folder, not the bridge server's working directory.
- The tools that take `to` also accept `name`, the word `StartConsultant`'s reply used, and that reply now says to pass the name as `to`.

## [0.2.0] - 2026-10-07

Tested with Claude Code 2.1.293, Codex CLI 0.160.1 with app-server daemon 0.161.0, Python 3.13.5 on Windows 11.

### Changed
- `StartConsultant` checks for existing sessions in the same git repo first. If there are any, it lists them and starts nothing, unless called with the new `new: true`.
- Watch windows run `codex resume` with the daemon's own `codex` binary instead of the one on `PATH`. Codex auto-updates its managed daemon separately from the CLI, and a viewer on a different version could refuse to attach and offer to restart the shared daemon ("Background server has incompatible feature set"). If the daemon's binary can't be found, the bridge falls back to `codex` on `PATH` and warns when the versions differ.
- `WatchConsultant` and `watch: true` don't open a second window when a `codex resume` for that session is already running.

### Added
- `ListConsultants` takes `cwd` to list only the sessions in that path's git repo.
- MCP server instructions telling Claude to list the repo's consultants and reuse one before starting another.

## [0.1.0] - 2026-10-06

First public release. Tested with Claude Code 2.1.292, Codex CLI 0.160.1, Python 3.13.5 on Windows 11.

### Added
- `StartConsultant`: start a background Codex session from Claude Code, with no terminal needed. Consultants are always read-only: they audit, validate and research, and never edit.
- `ListConsultants`: list Codex sessions loaded on the local app-server daemon, plus recent `StartConsultant` sessions it has unloaded.
- `SendConsultantMessage`: send a message into a session (new turn, or steer a busy one) and return the reply. Unloaded sessions are reloaded first.
- `GetConsultantReply`: read a reply later, after sending with `wait: false` or after a timeout.
- `WatchConsultant` and `StartConsultant`'s `watch` option: open a session in a split pane beside Claude Code (Windows Terminal, tmux) or a new terminal window (Windows, macOS, Linux).
- `StopConsultant`: archive a session started by `StartConsultant` and close its watch window; refuses user-opened sessions.
- MCP request cancellation: a cancelled call stops waiting and sends no response. A message already delivered to Codex is not withdrawn.

[Unreleased]: https://github.com/jibarix/nouez/compare/v0.11.2...HEAD
[0.11.2]: https://github.com/jibarix/nouez/compare/v0.11.1...v0.11.2
[0.11.1]: https://github.com/jibarix/nouez/compare/v0.11.0...v0.11.1
[0.11.0]: https://github.com/jibarix/nouez/compare/v0.10.0...v0.11.0
[0.10.0]: https://github.com/jibarix/nouez/compare/v0.9.0...v0.10.0
[0.9.0]: https://github.com/jibarix/nouez/compare/v0.8.0...v0.9.0
[0.8.0]: https://github.com/jibarix/nouez/compare/v0.7.1...v0.8.0
[0.7.1]: https://github.com/jibarix/nouez/compare/v0.7.0...v0.7.1
[0.7.0]: https://github.com/jibarix/nouez/compare/v0.6.1...v0.7.0
[0.6.1]: https://github.com/jibarix/nouez/compare/v0.6.0...v0.6.1
[0.6.0]: https://github.com/jibarix/nouez/compare/v0.5.0...v0.6.0
[0.5.0]: https://github.com/jibarix/nouez/compare/v0.4.0...v0.5.0
[0.4.0]: https://github.com/jibarix/nouez/compare/v0.3.2...v0.4.0
[0.3.2]: https://github.com/jibarix/nouez/compare/v0.3.1...v0.3.2
[0.3.1]: https://github.com/jibarix/nouez/compare/v0.3.0...v0.3.1
[0.3.0]: https://github.com/jibarix/nouez/compare/v0.2.0...v0.3.0
[0.2.0]: https://github.com/jibarix/nouez/compare/v0.1.0...v0.2.0
[0.1.0]: https://github.com/jibarix/nouez/releases/tag/v0.1.0
