# nouez

**A Claude Code plugin for people whose main tool for agentic programming is Claude Code.** nouez fills the gaps Claude Code leaves when you work from your phone, and when you have a second subscription, Codex or Antigravity, to help it: every project on your computer stays reachable from the Claude app from the moment you sign in to Windows, with every session closed, and Claude Code gets second opinions from your other subscriptions, on the model that fits each question and the quota nouez can read.

## What nouez adds

Claude Code's [Remote Control](https://code.claude.com/docs/en/remote-control) lets the Claude app drive a session on your computer. On its own, though, a Remote Control server starts sessions only in the project it was started in (or its worktrees), and nothing starts it again after a restart or a sign-out: until you start one again at the computer, the phone has nothing to talk to. And Claude Code doesn't consult your other subscriptions by itself. nouez adds:

- **A computer that is always there.** The phone dispatcher is a session that runs on your computer from the moment you sign in, and starts again if it ends. From the Claude app you open a session in any project, make the folder for a new one, resume an earlier conversation (as a fork with its whole history, so it reaches the phone even when your account requires trusted devices), trust a folder, and list or close sessions, **even when no session is open at the computer.** Each session opens in its project's folder, with that project's `CLAUDE.md`, settings and memory, in a window you can sit down at and carry on.
- **Second opinions from your other subscriptions.** A consultant reviews a plan, checks a diff before a commit, hunts a bug, checks a claim or does the research, on the Codex CLI or Google's Antigravity CLI, in the background. When a consultant has room, nouez tells Claude to ask it unasked, for example for a review before committing a change that alters behavior. Claude stays the main developer: it plans, writes the code and owns the work. **Consultants only read: they never edit your files.**
- **The right model for each question.** Routing is based on data from [Artificial Analysis](https://artificialanalysis.ai) and [BullshitBench](https://petergpt.github.io/bullshit-benchmark/), and on the quota you have left ([how nouez picks a model](docs/consultants.md#how-nouez-picks-a-model)).
- **Every quota used well.** nouez reads what is left on your Codex plan and Antigravity quota, and on Claude Code through nouez's status line. As Claude Code's week gets busy, nouez tells Claude to hand more work to consultants, to spare Claude Code; research and quick checks can go to spare quota in a window close to its reset; and a subscription that has run out gets no suggestions.

## Requirements

nouez is for you if Claude Code is your main tool, and the consultants if Codex or Antigravity is your second.

- **[Claude Code](https://code.claude.com/docs/en/quickstart)** on the computer, signed in with a claude.ai account whose plan includes [Remote Control](https://code.claude.com/docs/en/remote-control#requirements) (and, in an organization, where it's allowed), and the **Claude app** on your phone, signed in to the same account.
- **For consultants, a Codex or Antigravity subscription:** the [Codex CLI](https://developers.openai.com/codex/cli/) with a ChatGPT plan or an API key, or Google's [Antigravity CLI](https://antigravity.google/docs/cli-getting-started), or both. Without either, the phone dispatcher and the session tools still work.
- **Windows,** with [Python](https://www.python.org/downloads/windows/) 3.9 or later from python.org (nothing else to install). From a clone, nouez also runs on macOS and Linux; see [Tested with](#tested-with).
- **A computer that is on, awake and signed in.** The dispatcher starts when you sign in, not at boot; a locked screen doesn't stop it. Claude Code's own sign-in must be current: renewing it needs the computer, so from seven days before the earliest end date Claude Code reports, the dispatcher warns you on the phone, once a day.

## Setup

In any terminal (Claude Code installed), from any folder; it installs nouez for every project:

```sh
claude plugin marketplace add jibarix/nouez
claude plugin install nouez@nouez
```

Sign in to Codex or Antigravity if you use them, then run `/nouez:setup` in a new Claude Code session. It sets up what a plugin can't by itself (the waiter's allow rules, nouez's status line, auto-update, the phone dispatcher), asking before each change. [The setup guide](docs/setup.md) has each step and what it's for, updating and uninstalling, and running nouez from a clone.

## From your phone

In the Claude app, start a new session, pick the computer, `dispatcher`, and ask in plain language:

> Which projects do I have?

> Make a new project, economic-recession, and open a session there.

> Which sessions are open? Close the stuck one in hours-tracker.

The new session shows up in the app's list a few seconds later: tap it and work there.

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
                                                    (read-only)
```

The computer connects out to Anthropic, like the app: nothing on it listens for connections, so there is no port to open, no VPN and no remote desktop. More in [Working from your phone](docs/phone.md).

## Consultants

In a project's Claude Code session, from the phone or at the computer:

> Before you commit, send the diff to the consultant and ask it to look for bugs.

> Ask Gemini whether this plan holds up.

Claude starts a consultant in the project, or reuses the one already there, sends the question and gets the answer back, without a second terminal to copy text into. Asking how much usage you have left this week needs no consultant, and works in the dispatcher too. More in [Consultants](docs/consultants.md).

## Documentation

| Guide | What's in it |
|---|---|
| [Setup](docs/setup.md) | Each setup step, updating and uninstalling, and running nouez from a clone |
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

When something doesn't work, start with `doctor` (`/nouez:setup` runs it) and [Troubleshooting](docs/troubleshooting.md).

## Security

In short; [SECURITY.md](SECURITY.md) has the rest, and how to report a vulnerability privately.

- **No telemetry.** nouez's own web requests go to GitHub, for the latest release, and to Artificial Analysis, only with your key. Your messages go to OpenAI, Google or Anthropic through the CLIs you installed, as they would without nouez.
- **Consultants nouez starts only read.** A Codex session you opened yourself keeps its own permissions: Claude is told to message one only when you ask, and `NOUEZ_NO_USER_SESSIONS=1` refuses it.
- **Trust is recorded after a report.** Before nouez trusts a folder for you, Claude gets a report of what its settings would run, to show you before you say yes. An empty folder the same call made can skip the report, and in the dispatcher, a project with quiet settings inside a projects folder you picked can skip the question too ([trust without a question](docs/rules.md#rule-trust-without-a-question)).
- **Any session with nouez can close other Claude Code sessions** of your profile, except itself and the sessions it runs inside. Work in progress there is lost; the transcript is kept.
- **The dispatcher can do what you can:** anyone signed in to your claude.ai account (on a verified device, when your account requires one) can open, resume and close Claude Code sessions in your projects through it.

### Tested with

The protocol between nouez and Codex is experimental, so this is the last combination known to work. Newer versions will probably work too, but if something breaks, compare against this table.

| Component | Version |
|---|---|
| nouez | 0.31.2 |
| Claude Code | 2.1.332 |
| Codex CLI | 0.172.0 |
| Codex app-server daemon | 0.172.0 |
| Antigravity CLI (optional: Antigravity consultants, its quota) | 1.5.18 |
| Python | 3.11.9 |
| OS | Windows 11. macOS and Linux work as of 0.28.4, and the unit tests still run on them for every release, but new features are built and tried on Windows only; macOS and Linux changes come on request or by a pull request. The dispatcher's sign-in start on macOS and Linux is covered by tests, not yet run on those systems. |

Run `claude --version`, `codex --version` and `agy --version` to see your versions, or `doctor`, which also shows the version of the Codex daemon that is running. Codex updates its daemon by itself, so the daemon can be newer than the CLI.

## Tests

From the repo root: `python -m unittest discover tests` (standard library only; Codex isn't needed).

## Versioning

[Semantic Versioning](https://semver.org/). Releases are git tags (`v0.1.0`), and changes are listed in [CHANGELOG.md](CHANGELOG.md). Until 1.0, minor versions may include breaking changes to tool names or arguments.

## License

[MIT](LICENSE)
