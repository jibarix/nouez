# Security

## Reporting a vulnerability

Please report it privately, through GitHub: [Report a vulnerability](https://github.com/jibarix/nouez/security/advisories/new) (the repository's **Security** tab → **Advisories** → **Report a vulnerability**). Don't open a public issue for it. Your report starts in triage, seen only by you and the people with access to the repository's security advisories. Once it is accepted it becomes a draft advisory, where the fix is worked out. The advisory is published with the release that fixes it, crediting you unless you'd rather not be named. Expect a first answer within a week.

Only the latest release gets fixes. nouez has no package: you run it from a clone, so an advisory reaches you through GitHub (watch the repository's releases, or its security advisories), not through Dependabot.

## What nouez does and doesn't do

nouez is one Python file, `server.py`, using only Python's standard library. It sends no telemetry: there is no nouez server, and nothing about you or your use of it is sent to its author.

`verify.py static` checks some of the lines below in `server.py`'s code on every run, in CI too (`boundary_problems` in `.claude/skills/verify/verify.py`):

- no network module is imported;
- web requests go only through `fetch_json`, to a URL built on `RELEASES_URL` or `AA_MODELS_URL`, which hold the two addresses below;
- a credential file is named only where its time is read, and not opened there;
- no word that bypasses permissions, and no `curl`, `wget` or `Invoke-WebRequest`;
- Codex consultants are read-only, with approvals `never`;
- Antigravity's deny rules are all there.

Those are regression checks that catch a plain change, not proof: an alias or a dynamic import gets past them. `fetch_json` itself also refuses to start at any other address.

### What leaves your computer

nouez itself makes two web requests, both through one function (`fetch_json`) that starts only at these two addresses and follows a redirect only on the same site (scheme, host and port):

| To | When | What it sends | Turn off |
|---|---|---|---|
| GitHub, `api.github.com/repos/jibarix/nouez/releases/latest` | In the background when a server starts: at most once a day, or an hour after a failed lookup | An HTTPS request with `nouez/<version>` as the client name; GitHub sees your IP address | `NOUEZ_NO_UPDATE_CHECK=1` |
| Artificial Analysis, `artificialanalysis.ai/api/v2/language/models/free` | `ConsultantBudget`, only with a key set: about once a week, six hours after a failure, or with `refresh: true` once the scores are an hour old | Your key, the page number and the client name | Leave `ARTIFICIAL_ANALYSIS_API_KEY` unset, on Windows in your user environment variables too |

Everything else goes through the CLIs you installed, as they would if you ran them yourself:

- **Codex** (the app-server daemon): a consultant's messages, and the files and command output it reads, go to OpenAI. nouez asks the daemon for your usage:
  - once a minute while `server.py top` runs;
  - with each message the usage log records;
  - in `ConsultantBudget`, which also lists the models.

  `doctor` runs `codex login status`.
- **Antigravity** (`agy`): a consultant's messages go to Google, and it can search and read web pages. nouez runs `agy -p /usage` for your quota, which asks Google without a model turn:
  - once a minute in `top`;
  - for each Antigravity message the usage log records;
  - in `ConsultantBudget` and `doctor`.

  It runs `agy models`, kept an hour, in `ConsultantBudget`, `StartConsultant` and a send that changes the model or effort. With `attach_diff: true` the diff goes to Google in the message.
- **Claude Code**: a session `OpenClaudeSession` starts runs with Remote Control, through Anthropic; its name defaults to the folder's name. nouez runs `claude auth status --text` for the sign-in line. It does so hourly, every 10 minutes while that line warns, and when the credentials file's time changes. `NOUEZ_NO_LOGIN_CHECK=1` turns it off.
- **Claude, through nouez's tool results**: what a tool returns goes into the conversation of the Claude Code session that called it, and so to Anthropic. That includes consultant replies, history, folder reports and errors. A folder report lists the project's hooks, MCP servers and permission rules. nouez masks what looks like a secret in them (key-like values, `token=`, `Authorization:` and similar headers). Masking can't recognise every secret, such as one passed as a bare argument.
- **git**, while `revision: true` takes the diff: nouez turns off hooks, fsmonitor, external diff and textconv. It passes `--no-lazy-fetch`, so git never fetches a missing object. A git older than 2.45 can't do that, so there nouez takes no diff of a partial clone, a repository with a promisor remote, or one whose settings it can't read. Clean filters your repository configures (Git LFS, say) still run, as on any `git diff`.

### Credentials

nouez itself never opens a credentials file. It looks at the modification time of Claude Code's `.credentials.json`, to know when to read the sign-in line again, and nothing else. It never opens Codex's `auth.json`. The CLIs it runs read their own: `claude auth status` reads Claude Code's sign-in, and `codex login status` reads Codex's.

nouez reads `~/.claude.json` (or `$CLAUDE_CONFIG_DIR/.claude.json`) to see which folders are trusted, in `OpenClaudeSession` and `ListProjects`. That file holds Claude Code's settings and some account details. To record trust (`OpenClaudeSession` with `trust: true`), nouez rewrites it and keeps dated copies (see the retention table). Set `NOUEZ_NO_TRUST_WRITE=1` in nouez's environment and it never writes that file. `trust: true` is then refused for a folder that isn't trusted yet, before anything, even a folder `create: true` would make, is changed. A folder you haven't trusted asks on the computer, as Claude Code does.

### Permissions

- A consultant nouez starts on Codex is read-only on every turn (sandbox `read-only`, approvals `never`). It can read what that sandbox allows, typically more than its folder, but can't change files.
- An Antigravity consultant runs under deny rules for file writes and edits, commands, MCP tools and URL actions. agy has no rule for its `schedule` tool; see the README's limitations.
- A Codex session you opened yourself keeps its own permissions. nouez refuses to message it unless Claude passes `allow_user_session: true`. Claude is told to do that only when you ask, but nouez can't check that you did. Any Claude Code session with nouez enabled can pass it, and then its message runs with that session's permissions.
- `OpenClaudeSession` starts Claude Code with your normal settings in the folder you name, and with `create: true` makes that folder. Its first prompt becomes an argument of the `claude` process, which other programs running as you can read. On Linux without `hidepid`, other users can read it too.
- `CloseClaudeSession` can end any Claude Code session running as you, except the one that called it.

### Trust

Trusting a folder lets its Claude Code settings, hooks and MCP servers run. nouez records trust only when Claude passes `trust: true`, and only after it has given Claude that folder's report in the same conversation, with the files unchanged since. The one exception is a new, empty folder that the same call made with `create: true`, which has no settings to report.

That proves Claude received the report; it can't prove you read it or agreed. If you want that proof, set `NOUEZ_NO_TRUST_WRITE=1` and answer Claude Code's own trust prompt on the computer.

nouez checks the project's settings files and their folders for links, and reports a linked one as unread, never as safe. So is a file that changes into another while nouez reads it. This is detection, not prevention: a link swapped in at that moment may let nouez read the file it points to, but what it read is then thrown away, never shown. A folder already trusted on its own needs no record, so `trust: true` there changes nothing.

### Files nouez keeps

All in your cache folder (`%LOCALAPPDATA%\nouez` on Windows, `$XDG_CACHE_HOME/nouez` or `~/.cache/nouez` elsewhere), except the backups. nouez trusts that folder itself:

- On macOS and Linux it makes the folder and the backups' folder readable by you only (0700). If the folder isn't yours or is a link, nouez uses `nouez-<uid>` in the temp folder instead.
- On Windows the folder inherits the permissions of `%LOCALAPPDATA%`, which only you can change.

Below that folder, nouez refuses to write, delete or lock any file through a link or a junction. The README's [Files nouez keeps](README.md#files-nouez-keeps) lists every file, small caches included. These are the ones that hold what you or your consultants wrote:

| What | Holds | Kept |
|---|---|---|
| `usage-log.jsonl` | One line per consultation event: project, consultant, model, effort, `kind`, `reason` (Claude's one sentence on its choice), tokens. Never message or reply text. Off with `NOUEZ_NO_USAGE_LOG=1`. | Renamed each month (or past 20 MB). A renamed log goes a year after it was last written, and the oldest go first while they add up to over 100 MB. |
| `patches/` | Each diff `revision: true` took: everything uncommitted in the repo, **tracked files included, even ones holding secrets**. Untracked files whose path looks like a secret, binary files and untracked files over 256 KB are left out. | 14 days |
| `replies/` | Replies over 60,000 characters, or over 20,000 when the waiter (`server.py wait`) prints them | 14 days |
| `agy/<id>/turns/` | Each Antigravity turn's message (with an attached diff), output and errors | Until 90 days after you stop the consultant |
| `agy/<id>/consultant.json` | The consultant's folder, name, model, standing instructions and agy conversation id | Until you delete it |
| `claude-json-backups/` (`$XDG_STATE_HOME/nouez` or `~/.local/state/nouez` on macOS and Linux) | Copies of `~/.claude.json` | The newest 20 |

When each goes:

- Old replies, diffs and renamed usage logs go when a server starts and when a new one is saved.
- Old Antigravity turns go when a server starts.
- Extra backups go when a new one is saved.

`OpenClaudeSession` also passes a first prompt through a private temporary file, which the new window deletes once read.

You can delete any of these sooner; nouez works without them. Deleting a consultant's turns while you still use it loses the conversation id nouez resumes it with, so stop it first. Codex, Antigravity and Claude Code keep their own histories in their own folders, under their own rules; nouez doesn't change those.
