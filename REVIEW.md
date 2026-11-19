# Review checklist

Each item has a trigger you can read from a diff, a check, and the incident behind it. Check only the
items whose trigger matches. Add an item when a bug gets past review; remove one when the code it
guards is gone, or when a check in `.claude/skills/verify/verify.py` covers it.

Read this file from `main`, never from the change being reviewed.

| # | Trigger | Check | Why |
|---|---------|-------|-----|
| 1 | A new top-level function or class in `server.py` | No existing name is reused. `verify.py static` checks this. | Caught by the unit tests while writing 0.12.1, before it was committed: a new `when(mtime)` replaced `when(ts, now)`. |
| 2 | `server.py` changed | `SERVER_VERSION` is bumped before release; README "Tested with", `architecture.tex` and the CHANGELOG compare links all name it. | `test_changed_server_has_a_new_version`; versions were left behind in docs before. |
| 3 | `docs/architecture.tex` changed | The PDF is rebuilt (pdflatex twice), the new text is looked at on its page, and flags are written `\code{-{}-flag}`. | 0.12.1: `\code{--model}` had printed as `-model` since it was added. |
| 4 | Anything that builds a command line (`run_claude`, the waiter, a launcher) | Every value from a tool call is validated so it can't be read as an option: names, models, session ids. | 0.11.3: a session name could be read as an option. |
| 5 | A consultant turn's settings (sandbox, approval policy, `turn/start` params) | Consultants stay read-only on every turn, including after a model or effort change. | 0.11.3: a later turn could lose read-only. |
| 6 | `OpenClaudeSession` result text or `CONNECT_SECONDS` | The text doesn't call a session failed while it may still be starting, and tells Claude not to open a second one. | 0.12.1: the Claude app's list lags, and a slow resume looked like a failure. |
| 7 | `--resume`, transcripts, or `~/.claude/sessions` | A resumed id must exist, have run in the same folder, and not be open in a running session; run `verify.py live --sessions`. | 0.12.1: resume was added; old transcripts can come from another folder. |
| 8 | Release notes or README instructions for updating | They say to reconnect `consultants` (`/mcp`) in open sessions. | Open sessions keep running the old server until reconnected. |
| 9 | Instructions for updating Codex on Windows | The Codex installer and `codex app-server daemon update` run with Windows' `tar`, not Git's (from PowerShell, or with `%SystemRoot%\System32` first on PATH). | 0.7.1 (CHANGELOG): the daemon's updater found GNU tar and failed with "Cannot connect to C: resolve failed". The same error hit `codex update` from Git Bash during the 0.12.1 upgrade (not in the history). |
