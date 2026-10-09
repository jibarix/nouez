# Changelog

All notable changes to this project are recorded here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and versions follow
[Semantic Versioning](https://semver.org/).

## [Unreleased]

## [0.3.0] - 2026-10-08

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

[Unreleased]: https://github.com/jibarix/nouez/compare/v0.3.0...HEAD
[0.3.0]: https://github.com/jibarix/nouez/compare/v0.2.0...v0.3.0
[0.2.0]: https://github.com/jibarix/nouez/compare/v0.1.0...v0.2.0
[0.1.0]: https://github.com/jibarix/nouez/releases/tag/v0.1.0
