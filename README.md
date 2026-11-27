# nouez

A phone-first setup for Claude Code: work from the Claude phone app, with your computer as the server. nouez is an MCP server for Claude Code that keeps your computer reachable from the app, opens, lists and closes Claude Code sessions in any project there, and lets those sessions consult a second model on the Codex CLI, Google's Antigravity CLI or both. Claude Code is the only agent it needs: each consultant CLI is optional.

## Why

**Your phone is where you work; your computer does the running.** Claude Code's Remote Control lets the Claude app drive a session on your computer, but on its own a `claude remote-control` server is tied to the one folder it runs in, and nothing starts it again after a restart. nouez adds the missing pieces:

- **A dispatcher that is always there.** `server.py dispatcher install` starts a Remote Control server at sign-in, in a folder of its own, and starts it again if it ends. Open the app, pick the computer, and you are talking to it.
- **Every project from one place.** The dispatcher has nouez's session tools: it lists your projects, opens a session in any of them (or in a new one), resumes an old conversation, records your answer when a folder needs trusting, and closes a stuck session. Each session opens in its project's own folder, with that project's `CLAUDE.md`, settings and memory, and shows up in the app.
- **A second opinion on the way.** A consultant gives Claude Code second opinions on another model: reviewing a plan, checking a diff, finding a bug, validating a claim, or gathering context for research. It runs on the Codex CLI or Google's Antigravity CLI (Gemini and other models), whichever you have, in the background, and only reads; it never edits your files. Claude Code stays the main developer: it plans, writes the code or text, and owns the work.

You can use nouez at the computer alone, too: in a terminal, Claude starts a consultant, sends it questions, reads the answers and keeps working, without a second terminal to copy text into. If you prefer to watch Codex work, open it yourself and Claude will talk to that session instead.

## Your phone and your computer

```text
 Claude phone app            Anthropic              your computer (signed in, awake)
 ─────────────────────       ──────────────         ──────────────────────────────────────────
 pick "dispatcher":     ──►  Remote Control  ◄────  claude remote-control --name dispatcher
 "open hours-tracker"                               (nouez starts it at sign-in, and again
                                                     if it ends)
                                                       │ ListProjects, OpenClaudeSession, …
                                                       ▼
 the new session shows  ◄──  Remote Control  ◄────  Claude Code in ~/Projects/hours-tracker
 in the list: tap it                                (its own window, CLAUDE.md and memory)
                                                       │ SendConsultantMessage
                                                       ▼
                                                    a consultant: Codex or Antigravity
                                                    (read-only; optional)
```

The app talks only to Anthropic, and the computer connects out to Anthropic too: nothing on the computer listens for connections, so there is no port to open, no VPN and no remote desktop. What that asks of the computer:

- **It must be on, awake and signed in to your user account.** A sleeping laptop is out of reach; the dispatcher starts when you sign in, not at boot. A locked screen doesn't stop it.
- **Claude Code's own sign-in must be current.** It lasts a set time, and renewing it needs the computer (`claude auth login`). nouez warns you from the phone a week ahead (see [the sign-in warning](docs/phone.md#a-new-claude-code-session-from-your-phone)).
- **The first run of each part happens at the computer:** Claude Code's trust question in the dispatcher folder, and signing in to each CLI. After that, everything else can be done from the phone.

The sessions the dispatcher opens run in terminal windows on the computer, so you can sit down and carry on in the same conversation there. On Windows, ask Claude to arrange the windows once or turn on automatic arranging. It is off by default. Each box needs about 60 by 16 characters, so a 1920 by 1200 laptop screen at 150% scaling fits four; extra windows stay where they are.

https://claude.ai/code in a browser lists the same Remote Control sessions as the app.

## Requirements

- [Claude Code](https://code.claude.com/docs/en/quickstart) on the computer, signed in with a claude.ai account, and the Claude app on your phone, signed in to the same account. The app reaches the computer through Claude Code's [Remote Control](https://code.claude.com/docs/en/remote-control).
- Python 3.9 or later (standard library only, nothing to install).
- For consultants, at least one of these, installed and signed in. Each is optional:
  - the [Codex CLI](https://developers.openai.com/codex/cli/) (`codex`), with a ChatGPT plan or an API key;
  - Google's [Antigravity CLI](https://antigravity.google/docs/cli-getting-started) (`agy`), for consultants on Gemini or another model it lists (see [Antigravity consultants](docs/consultants.md#antigravity-consultants)).

What works with each setup:

| Installed besides Claude Code | Consultants | `StartConsultant` without `provider` | Claude Code session tools, `ConsultantBudget`, `top` |
|---|---|---|---|
| Codex and Antigravity | both | Codex; Antigravity when you ask for it | yes |
| Codex only | Codex | Codex | yes |
| Antigravity only | Antigravity | Antigravity, and the result says so | yes |
| neither | none: the consultant tools say so | an error naming both CLIs | yes |

The phone dispatcher works with any of these: it needs only Claude Code and nouez.

### Tested with

The protocol between the bridge and Codex is experimental, so this is the last combination known to work. Newer versions will probably work too, but if something breaks, compare against this table.

| Component | Version |
|---|---|
| nouez | 0.30.1 |
| Claude Code | 2.1.332 |
| Codex CLI | 0.172.0 |
| Codex app-server daemon | 0.172.0 |
| Antigravity CLI (optional: Antigravity consultants, its quota) | 1.5.18 |
| Python | 3.11.9 |
| OS | Windows 11. macOS and Linux work as of 0.28.4, and the unit tests still run on them for every release, but new features are built and tried on Windows only; macOS and Linux changes come on request or by a pull request. The dispatcher's sign-in start on macOS and Linux is covered by tests, not yet run on those systems. |

Run `claude --version`, `codex --version` and `agy --version` to see your versions, or `server.py doctor`, which also shows the version of the Codex daemon that is running. Codex updates its daemon by itself, so the daemon can be newer than the CLI.

## Setup

nouez installs as a Claude Code plugin on Windows. The plugin starts it with the Python launcher (`py -3`), which comes with python.org's Python for Windows. To run nouez from a clone instead (macOS, Linux, or to change the code), see [the setup guide](docs/setup.md#from-a-clone).

**1. Install the plugin.** In a terminal:

```sh
claude plugin marketplace add jibarix/nouez
claude plugin install nouez@nouez
```

From the next Claude Code session on, every session has nouez's tools.

**2. Sign in to a consultant CLI** (optional: skip it to use only the phone and session tools). Either one is enough; with both, Codex is the default. Do it before step 3, so setup's check finds it. If installing changed your `PATH`, reopen the terminal and Claude Code.

- **Codex:** install the [Codex CLI](https://developers.openai.com/codex/cli/), run `codex login`, then check with `codex login status`.
- **Antigravity:** install the [Antigravity CLI](https://antigravity.google/docs/cli-getting-started), run `agy` once in a terminal and sign in with your Google account, then check with `agy models`.

**3. Run `/nouez:setup` in a new Claude Code session.** A plugin can't change Claude Code's settings or Windows by itself, so setup does it once, for every session. It shows each change before making it, asks, and backs up a file before changing it. In this order:

| Step | What it's for | If you say no |
|---|---|---|
| **The waiter's allow rules** | After Claude sends a consultant a question, it runs a small command in the background, the waiter, which brings the reply when it's ready. The rules let it run without asking. | Claude Code asks before each waiter, and auto mode may block it. If the waiter can't run, Claude reads the reply only when you ask. |
| **nouez's status line**, asked with the rules, only when you have none | Claude Code tells only its status line how much of your usage is left. nouez's saves it, for the status screen and for handing work to consultants before Claude Code runs out. A status line of your own is kept, and setup says what to add to it. | nouez can't see Claude Code's usage. |
| **Removing a clone's registration**, only if you registered nouez from a clone before | So nouez doesn't run twice. Setup then takes the clone's waiter rules out too. | Both copies run. |
| **The phone dispatcher** (optional) | The session the Claude app talks to: it opens, lists and closes sessions in your projects. Setup prepares its folder; you run it once in a terminal to answer Claude Code's first questions; then setup installs it to start at each Windows sign-in. With one installed, setup offers to update it instead. | The phone reaches only sessions you start with Remote Control at the computer. Declining an update leaves the installed dispatcher running as it is. |

Between the clone question and the dispatcher, setup runs `doctor`, which asks nothing: it checks Python, `claude`, the settings above, the dispatcher and each consultant CLI (installed, signed in, answering), and says what to fix.

**4. Run `/reload-plugins`** in that session, or start a new one.

Updating and uninstalling nouez, and everything nouez changes on your computer, are in [the setup guide](docs/setup.md#as-a-plugin).

## From your phone

In the Claude app, start a new session and pick the computer, `dispatcher`. Then ask in plain language:

> Which projects do I have?

> Open a session in hours-tracker.

> Show my earlier nouez conversations, then resume the one I pick.

> Make a new project, economic-recession, and open a session there.

> Which sessions are open? Close the stuck one in hours-tracker.

> How much usage do I have left this week?

> Open the status screen on the computer, and arrange the windows.

The dispatcher answers with nouez's tools: `ListProjects`, `OpenClaudeSession` (with `resume` or `create` when you ask), `ListClaudeSessions`, `CloseClaudeSession`, `ListConsultants`, `ConsultantBudget`, `OpenStatusScreen` and `ArrangeWindows`. A session it opens shows up in the app's list a few seconds later, named after the project: tap it and work there. That session runs in the project's folder on the computer, with the project's own `CLAUDE.md`, settings and memory, so it builds, tests and commits there, and with nouez registered for every project it can consult as below. When a folder isn't trusted yet, the dispatcher shows you what its settings would run and asks before it records your answer. The details are in [A new Claude Code session from your phone](docs/phone.md#a-new-claude-code-session-from-your-phone).

## Consultants

In any Claude Code session with nouez, from the phone or at the computer, ask for a second opinion in plain language:

> Ask the consultant to review the plan you just wrote. Push back on anything you disagree with before changing it.

> Before you commit, send the diff to the consultant and ask it to look for bugs.

> Ask Gemini whether this plan holds up.

> Show me the consultations.

> We're done. Stop the consultant.

Claude starts a background consultant in the project (Codex if it is installed, otherwise Antigravity), or reuses the one already working there, sends it the question and gets the answer back as a tool result, without a second terminal to copy text into. A consultant Claude starts is always read-only: it never edits your files.

When a consultant has room, Claude can consult without being asked. For example, it asks for a review before committing a behavior change. See [when Claude consults on its own](docs/rules.md#rule-automatic-consultation). nouez suggests the provider, model and effort for each from the usage left and public benchmarks. Your own `CLAUDE.md` can change that, and `NOUEZ_NO_AUTO_CONSULT=1` turns it off. [Consultants](docs/consultants.md) covers reusing one, your own Codex session, how nouez picks a model and effort, briefs and verdicts, and Antigravity.

## Documentation

| Guide | What's in it |
|---|---|
| [Setup](docs/setup.md) | Each setup step in full, and updating nouez and Codex |
| [Working from your phone](docs/phone.md) | Opening, resuming, listing and closing sessions; trusting a folder from the phone; the sign-in warning; how the dispatcher runs |
| [Consultants](docs/consultants.md) | Reusing a consultant, your own Codex session, how nouez picks a model and effort, usage and model scores, briefs, tips, Antigravity |
| [Status screen and windows](docs/status-screen.md) | The usage log, the status screen (`server.py top`) and its consultations page, and arranging nouez's windows on Windows |
| [Tools](docs/tools.md) | Every tool and its arguments, and how Claude waits for a reply |
| [Troubleshooting](docs/troubleshooting.md) | `doctor`, and what to do about each message |
| [How it works](docs/how-it-works.md) | How nouez talks to Codex and Claude Code, and every file it keeps and for how long |
| [Rules](docs/rules.md) | Every rule nouez applies: whether its code enforces it or only tells Claude, the setting that changes it, and its test |
| [Limitations](docs/limitations.md) | What nouez can't do, and what it relies on that may change |
| [Architecture](docs/architecture.pdf) | The design in detail (PDF) |
| [SECURITY.md](SECURITY.md) | Reporting a vulnerability; what nouez sends where, keeps and runs |
| [CHANGELOG.md](CHANGELOG.md) | What changed in each release |

When something doesn't work, start with `server.py doctor` and [Troubleshooting](docs/troubleshooting.md).

## Tests

The protocol tests use only the standard library and don't need Codex. From the repo root:

```sh
python -m unittest discover tests
```

## Security

[SECURITY.md](SECURITY.md) says how to report a vulnerability (privately, through GitHub), and what nouez sends where, what it keeps and for how long, and which permissions each tool runs with. In short:

- nouez sends no telemetry. It makes two web requests of its own: GitHub, for the latest release, and Artificial Analysis, only with your key set. Your messages go to OpenAI, Google or Anthropic through the CLIs you installed, as they would without nouez.
- Every Claude Code session with this server enabled can send messages into **any** Codex session on the machine, and those messages run with that session's permissions. With `--scope user`, that's every project you open in Claude Code. Claude messages a session you opened only when you ask, and `NOUEZ_NO_USER_SESSIONS=1` refuses it even then.
- Consultants nouez starts are read-only and never ask for approvals, so the read-only sandbox (Codex) or the deny rules (Antigravity) are their only limit. They can read anything that allows, which typically includes files outside `cwd`.
- `CloseClaudeSession` can end **any** interactive Claude Code session of the profile nouez runs under, including ones you started yourself; only its caller and the sessions above it are refused, and on macOS and Linux a session nouez can no longer verify is left alone. Work in progress in that session is lost; the transcript is kept.
- Trusting a folder lets its Claude Code settings, hooks and MCP servers run. `OpenClaudeSession` records trust only after Claude has received that folder's report, with the files unchanged since (or for a new, empty folder the same call made); nouez can't see whether the report reached you. It changes only that setting in `~/.claude.json`, after a dated backup, but a Claude Code session saving that file in the same instant could still lose a setting. `NOUEZ_ASK_TRUST=1` asks you in Claude Code's own prompt before each recording, and `NOUEZ_NO_TRUST_WRITE=1` turns trust writing off.
- The phone dispatcher, once installed, runs `claude remote-control` from your sign-in on: anyone signed in to your claude.ai account can start a session in its folder, and through nouez's tools open, resume and close Claude Code sessions in your projects, and record trust in a folder after its report. `setup` adds allow rules for those tools and the phone setup's (twelve in all) only; rules already in the folder's settings, and your user settings, still apply. It opens no port; the computer connects out to Anthropic. `dispatcher uninstall` stops it.
- The `nouez` tag is a guard against mistakes, not a security boundary: any local program that can reach the Codex daemon can set it.

## Versioning

[Semantic Versioning](https://semver.org/). Releases are git tags (`v0.1.0`), and changes are listed in [CHANGELOG.md](CHANGELOG.md). Until 1.0, minor versions may include breaking changes to tool names or arguments.

## License

[MIT](LICENSE)
