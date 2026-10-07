# Changelog

All notable changes to this project are recorded here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and versions follow
[Semantic Versioning](https://semver.org/).

## [Unreleased]

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

[Unreleased]: https://github.com/jibarix/nouez/compare/v0.2.0...HEAD
[0.2.0]: https://github.com/jibarix/nouez/compare/v0.1.0...v0.2.0
[0.1.0]: https://github.com/jibarix/nouez/releases/tag/v0.1.0
