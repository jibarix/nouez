# Troubleshooting

Part of [nouez's documentation](../README.md#documentation).

To check the setup, run `python "/absolute/path/to/nouez/server.py" doctor`. It prints one line per check, first Claude Code's side (Python, `claude`, the waiter's allow rules, terminal windows), then the phone dispatcher (its folder, rules and trust, whether it starts at sign-in and is connected), then each consultant CLI (Codex: found, signed in, daemon; Antigravity: found, version, signed in), and says what to fix. It changes nothing, though checking the daemon starts it if it isn't running, and the Antigravity check asks agy for its quota (no model turn; up to 60 seconds). One working consultant CLI is enough: a problem with the other one is shown but does not fail the check.

| Message | Fix |
|---|---|
| `` `codex` CLI not found on PATH `` | Install the Codex CLI, or make sure the shell that launches Claude Code can find it, then restart Claude Code. |
| ``Codex isn't installed: `codex` isn't on PATH`` | `StartConsultant` was asked for `provider: "codex"`. Leave `provider` out to use Antigravity, or install Codex. |
| `No consultant CLI is installed` | Install and sign in to Codex or Antigravity ([Setup](setup.md#setup), step 4), restart Claude Code, and check with `doctor`. The Claude Code session tools work meanwhile. |
| `No consultant named 'x'. Codex isn't installed` | Only Antigravity consultants exist; the message lists them. Use one of those names, or start one. If it says neither CLI is installed, see [Setup](setup.md#setup), step 4. |
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
| Claude Code asks before running `server.py wait`, or auto mode blocks it | The waiter has no permission rule. Add the rules that `python server.py allow-rule` prints (see [Setup](setup.md#setup), step 5), then start a new session. Meanwhile, ask Claude for the reply with `GetConsultantReply`. |
| `is a Codex session the user opened` | `SendConsultantMessage` refuses your own sessions by default. Ask Claude to message it if you mean to; it then passes `allow_user_session: true`. |
| `` `until_done` was replaced by `wait` `` | The caller used a pre-0.4 argument. Reconnect the server (`/mcp`) so Claude sees the new tool definitions. |
| `Delivered to ..., but waiting for the reply failed` | The message reached the consultant; only the wait failed. Don't resend it. Read the reply with `GetConsultantReply`. |
| `was not started by StartConsultant` | That's a session you opened yourself. Close it from its own terminal. |
| `cwd must be the absolute path of an existing folder` | `OpenClaudeSession` needs a full path to a folder that exists. |
| A new session doesn't appear in the Claude app | It may be waiting at Claude Code's trust prompt on the computer. The result warns when the folder isn't trusted, and says so when Claude Code's settings couldn't be read. Answer the prompt there, or tell Claude you trust the folder so it can record that. A trusted folder can still ask there before connecting the project's `.mcp.json` servers, or about its `.claude/settings.json` allow rules when only a folder above it is trusted; the result notes these. Also check that `claude` is on the `PATH` of new terminals; if not, the new window says so. When the result says the session is connected, the app's list may just be slow to update: refresh it. |
| `No running Claude Code session matches` | The name must match exactly. The error lists the sessions that are running. |
| `That is the session you are running in` | `CloseClaudeSession` never closes its caller. Ask another session to close it, or quit it with `/exit`. |
| The Claude app doesn't list the computer as `dispatcher` | Run `server.py dispatcher status`. Not running: `server.py dispatcher install` (it says what's missing), or check that the computer is awake and you are signed in. Running but not connected: `dispatcher-claude.log` in nouez's cache folder shows what `claude` printed; a question there means running `claude remote-control --name dispatcher --spawn same-dir` in the dispatcher folder once and answering it ([Setup](setup.md#setup), step 3). A sign-in that ended: `claude auth login` at the computer. |
| `Nothing was installed:` (`dispatcher install`) | Each line says what's missing: the folder's `CLAUDE.md` (`dispatcher setup`), `claude`, trust in the folder (the interactive run in Setup step 3), or `pythonw.exe` beside Python on Windows. `--force` installs anyway, except without `pythonw.exe` or with a `CLAUDE_CONFIG_DIR` that isn't an absolute path. A start of the same name that isn't nouez's, or one nouez can't read, also stops it; rename or remove that one first. |
| `isn't valid JSON` (`dispatcher setup`) | The dispatcher folder's `.claude/settings.json` couldn't be read, so nouez left it alone. Fix the file, then run `setup` again. |
| The app lists the computer twice | Two Remote Control servers run with the same name. `server.py doctor` names any `claude remote-control` that isn't nouez's: remove whatever starts it. |
| Anything else after updating Codex | Compare your versions with the [Tested with](../README.md#tested-with) table. The Codex app-server protocol may have changed. |
