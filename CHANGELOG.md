# Changelog

All notable changes to this project are recorded here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and versions follow
[Semantic Versioning](https://semver.org/).

## [Unreleased]

## [0.30.2] - 2026-11-27

An update no longer asks a trust question twice, and projects-folder messages promise only what can happen. With the plugin, update with `claude plugin update nouez@nouez`, then start a Claude Code session or run `/reload-plugins` in one; the other open sessions then move to the new version by themselves once idle. With a clone, pull, then reconnect `consultants` with `/mcp` in each open Claude Code session, and run `server.py dispatcher install` again the way you first did, to restart the dispatcher.

### Fixed

- **Adding a projects folder no longer promises trust that can't happen.** Ana has `ask_trust` on and adds her work folder from the phone: nouez used to say its quiet projects were trusted at once, then asked for her yes at the computer anyway. Adding or promoting a projects folder, and the phone setup's guide, now say quiet trust happens only when it can: not with `ask_trust` or `no_trust_write` on ([trust without a question](docs/rules.md#rule-trust-without-a-question)).
- **An update no longer asks the same trust question twice.** Ana's phone shows a trust report for a folder while a plugin update lands. Her session used to move to the new version at once, which hadn't given that report, so her yes brought the report back. Now a session stays on its version while a trust report or the home folder's warning it gave waits for the user's answer, for up to 15 minutes; an answer nouez receives (her yes, opening the folder untrusted, finishing the phone setup) or the folder trusted at the computer ends the wait, and a report that can't be answered with a yes doesn't wait ([plugin launcher](docs/rules.md#rule-plugin-launcher)).

### Changed

- **Internal: three design loops broken, no other change in behavior.** Which model may take a piece of work is one rule that both ConsultantBudget's picks and the Antigravity send apply; the checks before a new folder is made and trusted live with the trust code; and the projects-folder messages ask the trust code what quiet trust can do now.

## [0.30.1] - 2026-11-27

Fixes from moving this laptop from a clone to the plugin. With the plugin, update with `claude plugin update nouez@nouez`, then `/reload-plugins` and `/nouez:setup` in a Claude Code session at the computer. With a clone, pull, then reconnect `consultants` with `/mcp` in each open Claude Code session; for the phone dispatcher, run `server.py dispatcher setup` and `install` again the way you first did.

### Fixed

- **The dispatcher step of `/nouez:setup` no longer stops at "Access is denied".** Robin runs `/nouez:setup` and says yes to the phone dispatcher: Claude Code's sandbox refused the change to the dispatcher folder's `.claude/settings.json`. The setup skill now says so first and runs that step outside the sandbox, and a refused write names the sandbox as a likely cause.
- **The phone dispatcher gets this version's instructions.** Robin's dispatcher folder still had the `CLAUDE.md` nouez 0.29.0 wrote, which says protections change only at the computer, so the phone kept refusing a change the plugin allows. `dispatcher setup` now recognises a `CLAUDE.md` an earlier nouez wrote word for word and replaces it, after a dated copy beside it; one the user edited is kept, with the note as before ([dispatcher setup](docs/rules.md#rule-dispatcher-setup)).
- **The clone's waiter rules go with the clone.** After the clone's registration is removed, `setup` takes the waiter allow rules that run the clone's `server.py` out of Claude Code's user settings (backed up first; another program's `server.py` rule stays), so `doctor` no longer suggests a hand edit ([plugin setup](docs/rules.md#rule-plugin-setup)).
- **Setup no longer says that sessions on the clone switch by themselves.** Open sessions on the plugin move to a new version by themselves; sessions opened while the clone was registered keep the clone's nouez until reopened, and setup and the README now say so.

## [0.30.0] - 2026-11-27

nouez installs as a Claude Code plugin, on Windows: `claude plugin marketplace add jibarix/nouez`, `claude plugin install nouez@nouez`, then `/nouez:setup` in a new session. Installed that way, an update reaches open sessions by itself, and a protection can change from the phone after a yes in Claude Code's own prompt. A clone keeps working as before: reconnect `consultants` with `/mcp` in each open session to load 0.30.0.

### Added

- **nouez as a plugin.** Robin installs it with two commands and runs `/nouez:setup`, which shows what it would add (the waiter's allow rules and, if wanted, nouez's status line), asks, runs `doctor` and offers to set up the phone dispatcher. `/nouez:uninstall` takes out what setup added and the dispatcher's sign-in start ([plugin setup](docs/rules.md#rule-plugin-setup)). Someone who also registered a clone is told nouez runs twice, with the command that removes the clone's registration and the environment variables it sets, which the plugin doesn't get; the phone dispatcher's allow rules move to the plugin's tool names.
- **Open sessions move to a new version by themselves.** Dana updates the plugin and runs `/reload-plugins` in one session while a review runs in another. That one keeps the running server until the review's reply is in; its next nouez call after that is answered by the new version, with no `/mcp` reconnect. The plugin's launcher asks the server whether anything is under way and moves only when nothing is; nothing is handed over ([the plugin](docs/rules.md#rule-plugin-launcher)).
- **Protections from the phone, behind Claude Code's prompt.** Sam, with the plugin, asks the phone to turn `ask_trust` off: Claude Code's own prompt naming that change shows on the phone, and it changes only on his Allow, once. In a mode that shows no prompt (`bypassPermissions`, `dontAsk`, `plan`) it is refused. Without the plugin, protections still change only at the computer ([protections](docs/rules.md#rule-protections-behind-the-prompt)).
- **Resumed sessions reach the phone again.** Kim resumes her fantasy_basket conversation from the phone and it connects. Resumed under its own id, a conversation reattaches to its old Remote Control session, which an account that now requires trusted devices refuses; so a resume now opens as a fork, a new conversation with the whole history and a new Remote Control session, and the original stays as it was. While the fork runs, the list marks the original "open, as a fork" and a second resume of it is refused; afterwards it shows "continued in <fork>" and "fork of <original>". Plan mode and permissions granted for that session only don't carry over. A session that lost the phone while running says so in the list, with its conversation id: Claude asks Kim before closing it and opening it again as a fork ([trusted devices](docs/rules.md#rule-trusted-devices)).

### Documentation

- The README and the setup guide say how to install, set up, update and remove the plugin; the architecture reference has a section on the launcher and the hook; the rulebook adds four rows; protections without the plugin still change only at the computer.

## [0.29.0] - 2026-11-27

The phone sets itself up. Open a chat with the dispatcher and it offers to walk you through picking your projects folders, what nouez changes in Claude Code and the switches, with no flags at the computer. Projects you picked open from the phone without the trust question when their settings run and allow nothing. Reconnect `consultants` with `/mcp` in each open Claude Code session to load the new version. For the phone dispatcher, run `server.py dispatcher install` again the way you first did; the dispatcher then adds the allow rules for the new tools itself.

### Added

- **Phone setup.** Kim installs the dispatcher with no `--projects`, opens it on her phone and says hi: the first reply offers to set up the phone. `PhoneSetup`, listed only in the dispatcher, lists the folders that look like they hold projects, with their counts, offers the home folder last with its warning, says what nouez changes in Claude Code (one trust mark per folder in `~/.claude.json`, a copy first, the newest 20 kept; nothing from the phone changes your user settings) and shows the switches. Until it is marked done the dispatcher's server offers it, an existing install included; *"set up this phone"* starts it again at any time ([phone setup](docs/rules.md#rule-phone-setup)).
- **Projects folders from the phone.** Lee adds `D:\work` from the phone and removes a folder he no longer uses; reinstalling doesn't bring it back. `NouezSettings` adds and removes projects folders (up to 20, none inside another). They are kept in nouez's settings file, copied once from a running 0.28 supervisor; `--projects` and `--no-projects` at the computer still replace them, and `--no-projects` locks them to the computer ([projects folders from the phone](docs/rules.md#rule-projects-folders-from-the-phone)).
- **The home folder, only if you insist.** Ana asks for her home folder: nouez first gives the warning that every folder in it, Downloads and Desktop too, could then be trusted from the phone, and adds it only when asked again after that warning was sent. Even then the home folder itself, Claude Code's settings folder, `~/.nouez`, nouez's cache and the temporary folder are never trusted ([home folder](docs/rules.md#rule-home-as-projects-folder)).
- **Trust without a question for quiet projects.** Ana says "open fantasy_basket", which has no project settings: it opens, and the result says it was trusted without a question and names the backup. Inside a projects folder you picked (from the phone or with `--projects`, not the install default), a project whose settings files are absent or hold only settings that run and allow nothing (deny or ask rules, a theme, an empty `.mcp.json`) needs no report and yes; her clone that pre-approves `Bash(*)` still gets the report first. `ask_trust` or `no_trust_write` turns this off ([trust without a question](docs/rules.md#rule-trust-without-a-question)).
- **nouez's settings file.** Lee turns the usage log off from the phone, and the next consultation logs nothing. The switches can now be set in `settings.json` in nouez's folder (`%LOCALAPPDATA%\nouez` on Windows) as well as by environment variable, which still wins when set; `NouezSettings` and `server.py settings` show each switch, where its value comes from and when a change applies ([settings file](docs/rules.md#rule-settings-file)).
- **Protections change only at the computer.** Asked from the phone to turn on "ask for each trust", nouez refuses and gives the command: `no_trust_write`, `ask_trust`, `no_user_sessions` and `ask_user_session` change only with `server.py settings set NAME on|off`, so the phone can't lock itself out of approvals only the computer shows, nor turn a protection off on Claude's word ([protections](docs/rules.md#rule-protections-at-the-computer)).
- **What did I lose?** After a Claude Code update, Dana's sessions ask for trust again and her `edgar` MCP server is gone. `RestoreClaudeConfig` compares `~/.claude.json` with nouez's copies of it and lists the trust marks and MCP servers gone now, secrets masked and environment and header values never shown. Trust marks come back from the phone through the same checks as new trust; an MCP server starts a command, so it comes back only at the computer, with `server.py restore ID` ([restore](docs/rules.md#rule-restore)).
- **Status on request.** Jo, on the train, asks "status?" and gets one short block: the sign-in's end, each subscription's use, consultants waiting, open sessions, the dispatcher, nouez's version and the settings, each line said to be unknown or off rather than left out (`NouezStatus`, [status](docs/rules.md#rule-status)).

### Changed

- **Asking in the dispatcher is refused at once.** With `ask_trust` or `ask_user_session` on, a phone request that needs that yes used to wait for a prompt only the computer's screen shows. It is now refused before any folder is made or anything changed, with the command that turns the switch off at the computer ([ask in the dispatcher](docs/rules.md#rule-ask-in-the-dispatcher)).
- **The sign-in warning reaches the phone.** In the dispatcher, the warning that Claude Code's sign-in ends soon now rides on the first nouez tool result of the day, errors included, and is counted only once that result was sent, so a reply lost on the way doesn't use it up ([sign-in in the dispatcher](docs/rules.md#rule-sign-in-in-the-dispatcher)).
- `dispatcher setup` and `install` in `~/.nouez/dispatcher` with neither `--projects` nor `--no-projects` are no longer refused: they list the folders that look like they hold projects and pick none, for the phone setup to pick.

### Security

- A settings file that can't be read, or a link in its place (to a file or to nothing), is never taken for an empty one: every protection reads on (but one whose environment variable is set) and the phone records no trust until `server.py settings reset` at the computer moves the file aside.

### Documentation

- The guides say why an Antigravity consultant's commands stay off even in agy's own sandbox: with agy 1.5.18 a turn whose command asked to run outside the sandbox ended with no reply, and agy offers no policy nouez could check.
- The phone guide has a "Setting up the phone" section; the rulebook adds ten rows, each with its scenario and tests.

## [0.28.6] - 2026-11-26

Antigravity quota failures are remembered, usage nouez can't place gives way to usage known to have room, and Claude is told more plainly when to get a review. Reconnect `consultants` with `/mcp` in each open Claude Code session to load the new version.

### Changed

- **An Antigravity turn that fails on its quota is remembered.** agy's usage report can lag its own limit: a research turn went to Opus while the report still showed its Claude and GPT group at half its week, and failed with "Third-party quota reached ... Resets in 162h49m57s". nouez now marks that group used up until the reset the error names, timed from when the turn ended, in every session, so its own picks go elsewhere and `ConsultantBudget` says when the group comes back. A later turn that succeeds in the group ends the mark sooner (an upgrade, or AI credits), whichever is read first. The marks hold in a session with no usage reading yet, or when agy's report fails, and show on the `top` screen, beside a failed reading too, each model in the group agy last listed it in. A send made while the consultant's previous turn is ending reads that turn again before it goes. A send that names a model in the group still goes, with a note that it may fail without credits, and nouez never resends a failed turn itself ([quota failures](docs/rules.md#rule-quota-hit)).
- **Usage nouez can't place gives way to known room.** Any first pick whose usage isn't known, not only an unmatched Antigravity group, now yields to a quota known to have room, after the rules that spend a week about to reset or behind pace. When agy lists no group members and renames a group, a model's group is the one reported group whose name has its family word (Claude or GPT, Argon, Gemini), never a guess when several or none match; a send to a model nouez still can't place says its usage isn't known ([quota groups](docs/rules.md#rule-quota-groups)).
- **The prompt hook speaks on an old busy reading.** When Claude Code's saved reading is over 30 minutes old and already past 70% of its week, each prompt now gets the hand-out line, saying the reading is old (before, only past 90%). `ConsultantBudget` and the status screen already counted it as busy ([Claude Code's workload](docs/rules.md#rule-claude-workload)).
- **The usage screen says "busy".** A week on pace past 70% now adds `busy` to its row and to a wide screen's card, still green, so a green row whose work goes elsewhere says why ([busy week](docs/rules.md#rule-busy-week)).
- **Clearer points for an unasked review and critique.** The review now follows the diff being committed: one that changes behavior, even by one line, gets one, so a one-line fix is no longer taken as too small. The critique comes before the first edit when your request leaves Claude a consequential choice, and not when the request spells the change out. The eval: reviews before a commit 8 of 8 (0.28.5: 7 of 8); the plan case is still missed, under three wordings ([automatic consultation](docs/rules.md#rule-automatic-consultation)). nouez's instructions are about 1,550 characters, against a test limit raised from 1,500 to 1,600.

### Internal

- Both send paths take their routing only from `send_route`, `send_check` and the new `independent_pick`, which moves a review off a Claude model; nothing a user sees changes.
- The consult eval adds a one-line change that alters behavior (should get a review) and a change to three files spelled out edit by edit (should get no critique).

## [0.28.5] - 2026-11-26

The rulebook is complete, and the other docs link to it instead of keeping copies that drift. Nothing nouez does changes. Reconnect `consultants` with `/mcp` in each open Claude Code session to load the new version.

### Documentation

- The rulebook (`docs/rules.md`) adds 39 rows for rules previously stated only in other docs or in the code, and restates 25 existing rows to match what nouez does. Each new row gives an example, says what holds the rule and names its test (or "none").
- Two rules got tests: which folder a consultant works in when Claude names none, and which consultant a folder outside git belongs to.
- The README says which systems new work is tried on: macOS and Linux work as of 0.28.4 and keep their unit tests on every release; new features are built and tried on Windows.
- The README, security notes, guides and architecture now state a rule briefly where you need it and link to its row in the rulebook for the full conditions. What you need to act stays in place: the security recipients and retention table, the table of files nouez keeps, the consultant-choice table, troubleshooting's error texts with their remedies, and the architecture's message formats.
- `verify.py static` checks Markdown rulebook links for relative paths, checks their `rule-` fragments against row anchors, and checks the architecture's rule links against the tag in the PDF title. It also compares the saved-diff lifetime in both retained tables with the rulebook. The review checklist asks for a row link when guide prose adds or revises a rule.

## [0.28.4] - 2026-11-26

The docs say what nouez does. Nothing nouez does changes; two tool descriptions Claude reads are corrected. Reconnect `consultants` with `/mcp` in each open Claude Code session to load the new version.

### Fixed

- `StartConsultant` told Claude that an omitted `cwd` means Claude Code's first workspace folder. A Claude Code that connects without the handshake shares no workspace folders, so it is the folder nouez started in; the description now says so, and the consultants guide says that outside git a subfolder then gets a consultant of its own. `ListConsultants`' description of a `cwd` filter outside git is corrected the same way.
- The rule that a refusal never waits for a usage reading didn't hold for a new Codex turn whose model Claude named: nouez reads Codex's usage first, with one request on the connection already open (about half a second), so a turn Codex would refuse (its limit reported reached, with no credits) is refused before anything is sent. The rulebook and the consultants guide now say that, and what does wait: an Antigravity send on nouez's own pick reads agy's usage first when no reading from the last 90 seconds is kept.
- Trust, corrected in the README, phone guide, tools reference and architecture: a report is kept per nouez server (in Claude Code, per conversation), Claude passes your yes on unless `NOUEZ_ASK_TRUST=1`, and a folder nouez creates outside git in the same call needs no report.
- Security, corrected in SECURITY.md and the README: a routed send reads usage with the usage log off, `ListProjects` reads no transcripts, `NOUEZ_NO_USER_SESSIONS=1` refuses sends to your own Codex sessions, and `CloseClaudeSession` reaches only interactive sessions of nouez's own Claude Code profile, never its caller or the sessions above it.
- Routing, corrected in the consultants guide, tools reference, limitations and architecture: effort fallbacks, kind `other` on a Claude model, `ConsultantBudget` holding a named provider for half an hour, and model ids in its suggestion.
- Sends and replies, corrected in the tools reference and consultants guide: when a blind second opinion is refused, how review rounds are counted, a steer repeating the turn's own model or effort (Codex only), Antigravity reply lookup by id, and the waiter for an unnamed client.
- Smaller corrections: `server/discover` without its `_meta` gets `-32602`, a `PATH` entry naming the project can supply `claude`, the saved-session search depth and the long-reply path in the architecture; and three rulebook rows (a reinstall keeping projects folders given explicitly, the prompt hook on a used-up window, `attach_diff: true` without a revision), plus a new one for an omitted `cwd`.

## [0.28.3] - 2026-11-26

Consultants found with the usage log off, and a send's reason that names the effort it ran at. Reconnect `consultants` with `/mcp` in each open Claude Code session to load the new version, and run `server.py dispatcher install` again, with the same `--folder` (and Claude Code profile) you installed it with, to restart the dispatcher.

### Fixed

- With the usage log off (`NOUEZ_NO_USAGE_LOG=1`), a Codex consultant the daemon had unloaded and that was past Codex's 50 most recent sessions was lost: `StartConsultant` started a second one beside it, a message by its name was refused and the consultations page left it out. Unloaded consultants are now found in Codex's own index of sessions, with the log on or off, among its 2,000 newest sessions not archived. Only the sessions Codex says nouez started are read, rather than each of the 50 newest, the user's own included, so listing is quicker too. A Codex whose index can't answer is checked in its 50 most recent sessions, as before, and a name the index doesn't hold is looked up once more on disk, as is a project the index shows no consultant in. A message to a name that matches none now says to look in `ListConsultants` rather than list the sessions it happened to read
- A send's result gave the pick's first reason, which named the suggested effort ("at xhigh ...") even when the week was tight and the turn ran one level down. It now adds "one level down while its week is tight" when it did

## [0.28.2] - 2026-11-26

A truer forecast for a week's first hours, and usage-log readings that say which week they belong to. Reconnect `consultants` with `/mcp` in each open Claude Code session to load the new version, and run `server.py dispatcher install` again, with the same `--folder` (and Claude Code profile) you installed it with, to restart the dispatcher.

### Changed

- A week's pace in its first 16 hours is the use so far spread over 16 hours, so a morning's work is no longer projected through every night of the week. Gemini's week at 7.8% by the evening of the day it began was "runs out before the reset", which sent plan critiques to Astra and put a "may run out" note on every Gemini send; it is now on pace for about 84%, busy, and plan critiques go to Neon again. Such a pace is called a first-day estimate in `ConsultantBudget`, the prompt hook and the status screen. A steady heavy week still shows: 30% a day is running out from the ninth hour, as before
- Each send in the usage log with any usage read has `usage_meta` beside `usage`: when each window resets and when it was read, so a later estimate from your own history can tell one week from the next. A reading Antigravity reused from its 90-second cache keeps the time agy answered, here and in its pace, rather than the time it was reused, in `ConsultantBudget`, routing and the status screen too

## [0.28.1] - 2026-11-26

One judgment of each usage window everywhere nouez shows or uses one, and a send that is refused only when its quota said no turn can run. Reconnect `consultants` with `/mcp` in each open Claude Code session to load the new version, and run `server.py dispatcher install` again, with the same `--folder` (and Claude Code profile) you installed it with, to restart the dispatcher.

### Changed

- One judgment of each usage window, which routing, `ConsultantBudget`, the prompt hook and the status screen all take. A reading too old to project from counts as the share already used, the least the window will reach: the screen shows it as `an old reading (45 min old): at least 93% by the reset`, amber past 90% as a fresh one is, and the prompt hook now speaks on such a reading past 90%, saying it is old. `ConsultantBudget`'s Claude Code line names a 5-hour window on pace past 90%, as the screen's amber does.
- The status screen's badge says `busy` when the week of the quota it shows is on pace past 70% (the colour stays green until 90%), and Claude Code's note line says what to hand out when its week is busy or tight. A used-up window from an old reading says it is an old reading, in the prompt hook too.
- A Codex send that would start a new turn is refused, with nothing sent, when Codex reports its limit reached and no credits to go past it; the refusal names another quota with room, or says to tell you. A used-up Antigravity group (agy never says whether AI credits can be spent) and a forecast that a window runs out before its reset only add a `(Usage: ...)` note to the send's result. A window at 100% that Codex hasn't reported as a reached limit only gets a note. When the refusal can't name room elsewhere it says why: no other consultant is set up, or Antigravity's usage isn't read yet. A note on a turn that went ahead names where later turns can go, never to send it again. A message added to a running turn is never refused and reads no usage before it goes, so a correction sent while a review runs can't miss it while nouez reads Codex's usage; a refusal never waits for a usage reading.
- `ConsultantBudget` takes `revision: true` and then gives the pick a message with the work's diff gets at send, never a Claude model; without it, a draft or research whose pick is a Claude model says so. An Antigravity consultant left on a Claude model moves to that same pick, or, when no model of another family has room, to the best one all the same, with the usage note, as the same send naming it would go.
- Antigravity's quota groups come from agy's own lists: a model counts against the group whose `/usage` list names it, so a model Antigravity adds to a group, such as Gemini 4 Argon, shows its usage there. A model no group lists has its usage not known, and a pick with known room comes before it. The subject note (Gemini 4 Neon for finance, legal and the rest) drops a level while Gemini's week is tight, as a pick does.

- The status screen's consultation tables (by model and effort, by kind, verdicts, by project) show each entry's share beside its count: of the period's messages, and for verdicts, of their replies read. A name cut to fit keeps its last word, so `claude-opus-5… high` and `claude-opus… medium` stay apart.
- When a conversation `OpenClaudeSession` resumed hasn't connected to Remote Control, its report adds the likely cause when your account requires trusted devices (the conversation's old Remote Control session is refused) and the fix: `/remote-control` typed in that window.

## [0.28.0] - 2026-11-26

Easier first steps and lighter use of Claude Code's week: a new dispatcher needs no `~/Projects`, setup offers the status line, research and drafts of code go to Antigravity's Claude models, and every rule in docs/rules.md has an example. Reconnect `consultants` with `/mcp` in each open Claude Code session to load the new version, and run `server.py dispatcher install` again, with the same `--folder` (and Claude Code profile) you installed it with, to restart the dispatcher.

### Added

- docs/rules.md has a "For example" column: a short scenario for every rule. Fifteen rules are also stated more exactly (the order of the routing rules, a named provider, the usage reminder, long replies, review rounds outside git, second opinions, files left out of a diff, additions to a running turn, the trust report, doctor's checks, the supervisor's allow rules, the Windows cache folder).
- doctor lists nouez's copies of `~/.claude.json` (how many, the newest, where) and how to put one back by hand. Each copy's name now carries a tag of the profile it came from, so with more than one Claude Code profile (`CLAUDE_CONFIG_DIR`), doctor offers only that profile's copies; others, and copies from before 0.28.0, are only counted.
- The README says what nouez changes in your Claude Code setup, and nothing else.

### Changed

- Research goes first to Antigravity's Claude models whenever that quota has room, sparing Claude Code's and Codex's usage; for research that needs a page's text the suggestion also names Codex, since Antigravity can search but can't open a page. A new kind, `draft`, sends code to write to the same models as text that Claude checks and applies, so Claude stays the only one editing your files; past 70% of Claude Code's week it is told to use it. The rule that research starts an Antigravity week not yet begun is gone: research goes there first anyway.
- `dispatcher setup` offers nouez's status line when Claude Code has none, and adds it only on a yes at the terminal or with `--statusline`, after a copy of the settings. A status line of your own is kept.
- A new install puts the phone dispatcher in `~/.nouez/dispatcher`; one set up in `~/Projects/dispatcher` stays there. `dispatcher setup` or `install` without `--projects` or `--no-projects` then lists the folders that look like they hold your projects, with how many trusted projects each holds, and changes nothing until you pick.
- `OpenClaudeSession` `create: true` makes the new folder a project: `git init` there (unless it is inside a git repository already, and without git's sample hooks) and a starter `CLAUDE.md`. Without git it says so and opens anyway.
- Resuming goes through the list: Claude is told to show it, and `OpenClaudeSession` `resume` takes only the id of a conversation from `ListClaudeSessions` with `cwd` (newest first, each marked open or not). `resume: "latest"` is refused with that pointer. The id's transcript must also have run in the same folder on disk, so a case-sensitive folder's `Repo` and `repo` are told apart.
- `ListProjects` has no `recent` list any more: recency matters only for resuming, and `ListClaudeSessions` with `cwd` lists a folder's conversations.
- **An Antigravity review now gets the diff's text, which goes to Google.** `revision: true` puts the diff in the message by default, since an Antigravity consultant runs no git; `attach_diff: false` sends only the revision line, as before (the consultant can still read the project's files).
- A provider you name ("ask Gemini") holds for the next message of that kind only, not for half an hour; the message after it gets nouez's usual pick again.
- For a review, the suggestion now says to have the reviewer weigh each finding itself before giving it: the user's setup and what they do, what goes wrong, where they would notice it, and whether a user in a normal setup would meet it. Only those count as findings and make the verdict CHANGES; the rest are left out or listed as not blocking. Re-checks, bug hunts and plan critiques weigh theirs the same way.
- An Antigravity consultant's standing instructions no longer say it can read web pages: it searches the web but opens no page.

## [0.27.0] - 2026-11-26

Projects in any folder: the phone dispatcher can have several projects folders, or none, and its folder no longer needs a `~/Projects`. Reconnect `consultants` with `/mcp` in each open Claude Code session to load the new version, and run `server.py dispatcher install` again, with the same `--folder` (and Claude Code profile) you installed it with, to restart the dispatcher.

### Added

- `dispatcher setup` and `install` take `--projects DIR`, once for each folder that holds your projects (up to 20, none inside another), or `--no-projects` to trust folders only at the computer. The phone records trust inside any of them. Without either, the folder that holds the dispatcher's is its projects folder, as before.
- `install` run again without `--projects` keeps the projects folders the running dispatcher was given, and says so. `dispatcher status` and doctor show them.
- `ListProjects` lists each projects folder in the dispatcher, and with `recent` up to 20 trusted folders Claude Code was used in lately, from anywhere on the computer, newest first.
- doctor says when Claude Code's registration, the waiter's allow rules, the status line, the prompt hook or the running dispatcher name another copy of `server.py`, and doctor, `setup` and `install` warn when nouez runs from the temporary or Downloads folder, which may be emptied.

### Changed

- Without a `~/Projects`, the dispatcher's folder is `~/.nouez/dispatcher`, which `setup` makes; it then needs `--projects` or `--no-projects`. When only one of the two is set up, that one is the default; when both are, `~/Projects/dispatcher`, as before.
- The dispatcher's `CLAUDE.md` no longer names a folder: it tells the dispatcher to decline trust outside the projects folders `ListProjects` names. `setup` keeps a `CLAUDE.md` already there, so delete yours and run `setup` again for the new one.
- The sign-in start's command carries the projects folders, and is refused past 8,000 characters.

## [0.26.4] - 2026-11-26

One reader for each subscription's usage, shared by the consultant suggestion, `ConsultantBudget`, the status screen, the usage log and `doctor`, so they no longer disagree. Reconnect `consultants` with `/mcp` in each open Claude Code session to load the new version; an open status screen restarts on it by itself.

### Fixed

- When Codex says a limit is reached, the status screen shows a used-up `limit` row. The suggestion already treated Codex as blocked then, while the screen showed only its windows.
- Antigravity's use is rounded once, to a tenth of a percent, before it is judged, so a group at 99.96% is used up on the screen as it is for the suggestion.
- A weekly percent that isn't a pace is no longer called one. When the reading is old, or too early in the week to project from, the suggestion and `ConsultantBudget` say "at 95% of its week or more" with the reason, instead of "on pace for about 95%".
- The usage log leaves out Codex and Antigravity windows that have reset, as it already did for Claude Code's and as the screen and `ConsultantBudget` do, and judges each reset at the time the reading arrives, so a window that resets while Codex answers isn't logged.
- When Codex answers with no usage windows, the status screen says so, instead of saying the daemon didn't answer.
- An Antigravity window of a kind nouez doesn't know is named on the screen as in `ConsultantBudget`, by the name agy gives it, rather than "usage".

## [0.26.3] - 2026-11-26

Recording trust made exact about which entry it writes and takes back, and the phone dispatcher's projects folder checked. Reconnect `consultants` with `/mcp` in each open Claude Code session to load the new version, and run `server.py dispatcher install` again, with the same `--folder` (and Claude Code profile) you installed it with, to restart the dispatcher.

### Fixed

- nouez writes trust to the one entry Claude Code's state file has for the folder, told by the folder on disk, and reads that entry back after writing. Until now any entry that read the same counted, so on Windows a case-sensitive folder's `projects` could be taken for its `Projects`, both when writing and when telling whether a folder is already trusted.
  - When the file spells the folder more than one way and none of them is trusted, nouez can't tell which one Claude Code reads, so it records none and says so; answer Claude Code's question on the computer.
  - Taking trust back changes only the entry nouez wrote. Trust already in the file nouez compares just before writing is left alone, and nouez no longer reports it as its own; a Claude Code session that saves the file in the moment between that comparison and the read-back can't be told apart.
  - If the file can't be read back after the write, nouez says so and names the backup, rather than retrying over it. A state file that can't be read no longer counts as an answer that the folder isn't trusted: `trust: true` is refused at once, before any report, prompt or new folder.
- The phone dispatcher records no trust when its projects folder is a drive's root or is or holds your home folder, Claude Code's settings folder or nouez's cache, also where a link takes them, or the temporary folder nouez's cache can fall back to: trust recorded there would reach far more than projects. `dispatcher setup` refuses such a folder and `dispatcher install` lists it as a problem; pass `--folder` with a folder inside a folder of projects. A projects folder that holds the nouez clone, such as `~/Projects`, is fine.
- In the dispatcher, a folder that `create: true` makes with `trust: true` is checked again right before it is made, after any prompt, so a link put in meanwhile is refused with nothing made through it.
- On Windows, the dispatcher accepts a folder spelled in another case than it is on disk when no link is on its path. Git keeps a worktree's main checkout as it was typed, so a worktree of a project inside the projects folder was refused.

## [0.26.2] - 2026-11-25

The status screen is no longer arranged. Reconnect `consultants` with `/mcp` in each open Claude Code session to load the new version. If you turned automatic arranging on, the arranger already running keeps the old behavior until it ends: turn it off and on again (`ArrangeWindows` with `auto: false`, then `auto: true`).

### Changed

- Arranging windows moves only the Claude Code session windows `OpenClaudeSession` opened. The status screen from `OpenStatusScreen` stays where you put it, and the sessions no longer leave room for it. Opening the status screen again while it is open still restores it if minimized and asks Windows to bring it forward (Windows may only flash it in the taskbar).

## [0.26.1] - 2026-11-25

The phone dispatcher's trust boundary now held by code, and the [rules](docs/rules.md) page made complete. Reconnect `consultants` with `/mcp` in each open Claude Code session to load the new version, and run `server.py dispatcher install` again, with the same `--folder` (and Claude Code profile) you installed it with, to restart the dispatcher.

### Fixed

- The phone dispatcher records trust only for a folder inside its projects folder, and for a git worktree only when its main checkout is inside it too. Until now only the dispatcher's instructions said so. The dispatcher passes the folder to its sessions' nouez, and a dispatcher started by an older nouez, which doesn't, records no trust from the phone until `dispatcher install` restarts it. Outside the dispatcher nothing changes.
  - Inside means spelled under the projects folder exactly as it is set, case included, with no link below it, and inside it with links resolved too. So a link into the projects folder, one leading out of it, and one inside it that could later be pointed elsewhere aren't inside, nor, on Windows, a case-sensitive folder's `projects` beside its `Projects`.
  - A new folder `create: true` would make in a repository is checked with that repository before it is made, so a refusal leaves nothing behind. The checks run again right before the write and right after it; if a link has taken the folder's place meanwhile, the trust just written is set back to false and the call refused.
  - In the dispatcher, a folder it won't record trust for gets its report with that said, and `open_untrusted: true` to answer Claude Code's own question at the computer, rather than an offer of `trust: true`.
  - `dispatcher setup` says the one-time `claude remote-control` run it asks for is plain Claude Code, without this limit, and is not for the phone.
- On Windows, nouez's state files are written again for up to a second when another process is reading them, rather than the write being lost. The dispatcher's last state (stopped) could be lost this way.
- A JSON file of nouez's own that is a link is no longer read: the latest-release cache, the Artificial Analysis scores, Claude Code's saved usage, `top`'s scan state and the consultants' records. A file over its size limit isn't read; before, one padded past it after a valid object was taken as valid.
- `create: true` with `trust: true` in a repository whose trust folder nouez can't tell is refused before the folder is made, not after.

### Changed

- [Rules](docs/rules.md) lists the rules nouez's code already held that the page left out: what `revision` leaves out of a diff, `StopConsultant` leaving your own Codex sessions alone, messages added only to turns nouez started, programs never run from the project folder, trust never recorded for the home folder or a drive's root, the copies of Claude Code's state file, checks before a session is closed or resumed, secrets masked in trust reports, the cache folder's protections and the two sites nouez contacts. Rows that were wrong are corrected: reviews and plan critiques can move to another subscription when the first choice is tight or busy, the spare-week window is under three days, and `CloseClaudeSession`'s refusal to close its own session was tested all along. Rows now say where a rule stops: an effort that can't go one level down stays, a send with no pick keeps its settings, a PATH entry naming the project by its full path is used, a password passed as a plain argument isn't masked, and Windows doesn't check the cache folder's owner. New rows cover what a Codex session you opened may still do, what `attach_diff` sends to Google, diffs that never make git fetch, a conversation already open never resumed, the dispatcher's sign-in start and update rules, and the limits on waits and replies.
- Tests check the values themselves where they compared a constant with itself: Codex's read-only sandbox and approval policy when a consultant starts, and each of Antigravity's deny rules. New tests cover `StopConsultant` refusing your own session, an approval answered after its 10 minutes, every wait that ends before the reply, each kind's advice reaching Claude by its own words, the dispatcher's own instructions, untracked files over 256 KB or past the 200th, the 100-turn reply lookup and a send with no pick.

## [0.26.0] - 2026-11-25

Rules nouez's code holds rather than asks for, listed on one page; nouez applies its pick of model and effort at send; approvals you can turn on, asked in Claude Code's own prompt; instructions to Claude at less than half their length; and MCP 2026-07-28, which Claude Code now connects with. Reconnect `consultants` with `/mcp` in each open Claude Code session to load the new version.

### Added

- nouez counts review rounds. Reviews and re-checks sent to a consultant on the same work (the same commit, no OK verdict to the chain's own last round, under a day apart) form a chain. Other consultations in between neither end it nor revive it, and a chain whose last reply nouez can no longer see starts over rather than guess its verdict. When the reply to the third round still asks for changes, nouez adds a note telling Claude to show you the open points and let you decide. Set `NOUEZ_REVIEW_ROUNDS_STOP=1` to have a fourth round refused instead.
- A blind second opinion that stays blind: `SendConsultantMessage` with `second_opinion_of` set to the first consultant sends the first brief of its review, bug hunt or plan critique, as it was, to a new consultant of the other provider. Neither Claude's findings nor the first consultant's reach it, and nouez refuses a message or the user's words alongside it, the same provider, and a consultant that has had messages already. It also refuses when the first consultant has had another message since that brief, so an older brief is never sent, and when a message was added to that review while it ran. A second opinion on a revision gets the diff the first review was sent with, in the same repository, and nothing is sent when nouez no longer has it, the commit has moved on, or the first review went without a diff that git didn't show as clean.
- Approvals you can turn on, for when Claude's word isn't enough. With `NOUEZ_ASK_TRUST=1`, nouez asks you in Claude Code's own prompt before recording trust in a folder. The prompt names the id of the report you were shown, and nothing is recorded if the folder's settings change while it is open. With `NOUEZ_ASK_USER_SESSION=1`, it asks before each message to a Codex session you opened, showing the session's full id, the start of the message, how much isn't shown, and any model or effort sent with it. With `revision`, the prompt names the commit and the diff taken before you're asked (its SHA-256), and the send is refused when nouez has no diff it can name, so your yes never covers a working tree that may change. With `NOUEZ_NO_USER_SESSIONS=1`, it never messages one. Each answer approves one call, and the model can't answer the prompt for you. Without these settings, trust and your own sessions work from the phone as before.
- A prompt hook, `server.py hook`, tells Claude what to hand to a consultant before it starts work. Until now only `ConsultantBudget` said so, after Claude had already decided to consult. Added as a `UserPromptSubmit` hook beside the status line, it adds one line to each prompt while Claude Code is on pace past 70% of its week, and nothing otherwise. `server.py doctor` says when the hook or the status line is missing and prints the settings entry for each, with your own Python and paths. See [Claude Code's usage](docs/consultants.md).
- Research and quick checks go to the subscription furthest behind an even pace through its week, when it is at least 15 points further behind than the first choice. Reviews, re-checks, bug hunts, plan critiques and fact checks keep their first choice.
- While Claude Code is past 70%, research starts Antigravity's Claude and GPT week if it hasn't begun. Its weeks start on first use, so each idle day pushes the later ones back.
- The live checks (`verify.py live`) ask a consultant of each installed CLI to create a file, and fail if it appears or the consultant's turn didn't run to its end.
- [Rules](docs/rules.md): every rule nouez applies, whether its code holds it or it only tells Claude, how to change it, and the test that covers it. The static checks keep it in step with the settings and tests.
- MCP 2026-07-28 alongside the handshake. nouez now answers `server/discover`, so Claude Code (2.1.332 checked) connects with 2026-07-28 rather than falling back to `initialize`. Each such request is handled on its own, from the version, capabilities and client its `_meta` names, and never inherits what an `initialize` set up. Results are marked complete and name nouez, and the version's errors apply (an unsupported version, missing capabilities). The opt-in approvals ask through the version's own way: the prompt goes back with the result, and nouez takes the user's answer only from the retried call that echoes that prompt's single-use id, for the same tool and the same arguments, every one of them. A request carrying any of the version's `_meta` keys is refused when its version is missing, so it never runs under the old rules, and a client that can't show a form gets the version's missing-capability error. A folder that `OpenClaudeSession` would create and trust is asked about before it is made, so a decline leaves nothing behind. nouez sends such a client no requests, so it doesn't read its folders: tools take `cwd`, as Claude is told to pass it, and outside git a call's consultants are looked for in the folder it names, never in the folder nouez was started in. A request without those keys that comes before `initialize`, other than `ping`, is refused (`-32600`). Clients that connect with `initialize` see no change, and `initialize` still never offers 2026-07-28.
- `server.py dispatcher setup` and `doctor` say when the dispatcher folder's `CLAUDE.md` isn't the one this nouez writes (an older nouez's, or edited), and how to take the current one. The file is still kept as it is.

### Changed

- `kind` is now required on `SendConsultantMessage` (`other` when none fits). A message without one is refused, with nothing sent.
- A review, re-check, bug hunt or plan critique, or any message with `revision: true`, never runs on a Claude model, now also at send. An Antigravity consultant left on a Claude model moves to the Gemini model `ConsultantBudget` suggests for that kind, and the result says so. A Claude model passed for one is refused.
- nouez applies its pick at send. A `SendConsultantMessage` with a kind and no model or effort runs on `ConsultantBudget`'s suggestion for that kind, within the consultant's provider, and says so. A model or effort passed wins. Claude no longer has to copy the values over, and a consultant left on an old model moves to the right one. After `ConsultantBudget` for a kind named a provider ("ask Gemini"), the send's pick keeps to it as the suggestion did, for half an hour; a later lookup without a provider doesn't undo it, and an Antigravity send for that kind with no Gemini model that has room is refused rather than run on another model. Kind `other` keeps the consultant's settings, and the pick is dropped rather than refuse a message steered into a running Codex turn.
- `ConsultantBudget` with a kind answers with only the suggestion, Claude Code's outlook and the notes. `details: true` adds each subscription's windows, the models and the benchmark scores, which a call without a kind still shows.
- Antigravity's quota reading is reused for 90 seconds, since agy takes seconds to answer and each send now reads it.
- What Claude hands out follows Claude Code's own pace. Under 70%, it hands out bulky reading (many files, long logs, audits, research). Past 70%, it hands out everything read-only that can go out. Past 90%, it hands out everything except what only Claude can do. It asks for short replies, and does a job itself when that takes seconds. A bug hunt's note says to have the consultant draft a small fix as a diff, which Claude checks and applies with `git apply`.
- nouez's instructions to Claude are down from 3,837 characters to about 1,500. They list the moments to consult (before committing a change to behavior, before the first edit built on a plan of Claude's own, a failure whose cause isn't obvious, and research or audits across many sources) and what to call. The rest moved to the tools' descriptions. Changes that leave behavior alone are exempt whatever their size, and only work that needs a verdict waits for it.
- Only Claude Code is told to run the waiter as a background command. A client that names itself otherwise when it connects is told to read the reply later with `GetConsultantReply`, also when it asks for a reply still being written. The usage log records the client of each event.
- Every later message to an Antigravity consultant starts with a short reminder of its read-only rules, not only the first.
- A verdict is also read from a `Verdict:` line among a reply's first five lines, when the first line gives none ("Reviewed commit abc.").
- Inputs that did nothing are refused instead, with nothing sent or started: `attach_diff` without `revision: true`, and `effort` on `StartConsultant` for a Codex consultant (pass it with `SendConsultantMessage`). `model` and `effort` on `SendConsultantMessage` say their 200-character limit in the schema.

### Fixed

- The waiter gave up only at its deadline when the Codex daemon accepted connections but couldn't list the turns. It now counts those as failures too. When it gives up, it says the wait ended, not the consultant's turn.

## [0.25.0] - 2026-11-25

Usage that would reset unused goes first, and Antigravity's Claude and GPT quota is no longer left idle. Reconnect `consultants` with `/mcp` in each open Claude Code session to load the new version.

### Changed

- Usage that would reset unused goes first. A week on pace for under 60% at a reset within three days (two before) now takes research and quick checks even when the first choice has room, the week that resets soonest first. Antigravity's two quota groups count as separate choices, so Opus and Sonnet on its Claude and GPT group, which is Google's quota and not Claude Code's, take research and quick checks (`claude-sonnet-5-5` at `low`) late in that group's week instead of resetting unused, and a tight Gemini group hands work to it. Reviews, re-checks, bug hunts and plan critiques never go to a Claude model, not even as Antigravity's default model: it shares the blind spots of the Claude that wrote the work. A tie in reset time keeps the first choice, and unknown usage is said as such, not as room. The reasons name the quota group, and switching a reused Antigravity consultant to another group's model is noted.

## [0.24.0] - 2026-11-25

nouez chooses the consultant. Claude asks `ConsultantBudget` before each consultation and gets the provider, model and effort to use, from public benchmarks and the usage left on each subscription, so consultations go where they cost least of what would run out, and Claude Code's own week lasts. No `CLAUDE.md` lines or skill are needed: if you copied nouez's `consult` skill to `~/.claude/skills/consult/`, delete it. Reconnect `consultants` with `/mcp` in each open Claude Code session to load the new version.

Also: Claude consults without being asked at the points where a second opinion pays, a consultant's turn can be stopped without losing the consultant, the phone can resume an earlier conversation and ask which reviews need you, a whole branch can be reviewed in one diff, and window arranging on Windows is off unless you turn it on.

### Added

- Stop a consultant's work without losing it: *"stop that review, the question changed"*. `StopConsultant` with `turn_only: true` ends the running turn, and the consultant keeps its context and takes the next message (Codex through `turn/interrupt`, Antigravity by ending the agy process nouez started). A plain `StopConsultant` of a Codex consultant now ends a turn still running before archiving the session, rather than leaving it working, and waits for a send to that consultant from another Claude Code session to finish first.
- `ListClaudeSessions` with a project folder (`cwd`) also lists that folder's saved conversations, newest first, so from the phone you can pick an earlier one to resume, not only the latest. Each shows its last activity, id, whether it is open, and any custom title and git branch, never the prompts.
- Ask the phone dispatcher “which reviews need me?”: `ListConsultants` now gives one line per consultant with its project, state, age, kind, verdict and title, never the messages. First come finished turns whose reply Claude hasn't fetched (“done, no reply logged”), changes, no or incomplete verdicts from the last day, and turns running for ten minutes. Run `dispatcher setup` again to allow `ListConsultants`.
- Review a whole branch: `SendConsultantMessage` with `revision: true` and a `base` such as `main` takes one diff from the branch's merge base with that base to the working tree, so commits on the branch and uncommitted work are both reviewed. Before, a branch with everything committed sent no diff. The base must be known locally; nouez never fetches, and the revision line names both commit ids.
- For contributors, `tests/consult_eval.py`, the consult eval: fresh `claude -p` sessions in scratch repos with made-up content, with nouez's real server and faked consultant CLIs and usage, scored on whether Claude consults where nouez's instructions say to (and not where they don't) and on whether it picks the suggested provider, model and effort. REVIEW.md item 15 asks for it when those instructions change. Results are in [the consultants guide](docs/consultants.md#the-consult-eval).

### Changed

- The phone dispatcher picks up the permissions an update brings: before it starts `claude`, its supervisor adds the allow rules for session tools added since the folder was set up (in 0.24.0, `ListConsultants`), backing the file up first. Only while the folder still has every rule an earlier nouez gave it, and once per rule, so one you take out stays out.
- Phone-only users hear about a new nouez: in the dispatcher, its tools' results carry the notice that a newer nouez is out, once per chat, and its server looks again for a release when its tools are used, at most hourly. The notice says the update takes the computer, then `dispatcher install` again, which ends the dispatcher's open chats. A server tells about each newer release, not only the first it found.
- Claude consults without being asked, with no `CLAUDE.md` lines or skill needed: a review of what it will commit before committing a change to behavior, several files or anything risky (not typos, formatting or one-line fixes), committing after the verdict; a bug hunt when a failure's cause isn't obvious after a first look; a critique of a consequential plan, design, formula or rule of its own before building on it, whose verdict it shows; and research across sources instead of searching the web itself, an audit or explanation spanning many files, or a consequential claim a first check left uncertain, with a short answer asked for. It skips one, saying so, when `ConsultantBudget` says no subscription has room. Until now it consulted only when asked or told to by your own instructions; those still override the default. Set `NOUEZ_NO_AUTO_CONSULT=1` to turn it off (with a Codex API key, each consultation costs money). It is off when no consultant CLI is installed.
- nouez chooses the consultant for each consultation, with no `CLAUDE.md` lines or skill needed. Claude calls `ConsultantBudget` with the kind of consultation (and the provider, if you named one), and it ends with a suggestion: the provider for `StartConsultant` and the model and effort for `SendConsultantMessage`, with the reason. The starting points come from public benchmarks (Artificial Analysis and BullshitBench, dated and credited in [the consultants guide](docs/consultants.md#how-nouez-picks-a-model)); Codex `gpt-6.2-astra` for reviews, bug hunts, research and fact checks, `gpt-6.2-sol` for quick checks and re-checks, and Antigravity's `gemini-4-neon` at `xhigh` for plan critiques. Then the usage left decides: a subscription that is used up or would run out before its reset is skipped, a tight week (over 90% on pace) moves the work to the other provider or one effort level down, and a week that would otherwise reset unused goes first. A model that is no longer listed falls back to the newest of its family, else the provider's default, and an effort it doesn't offer to the closest one it does, and says so. Usage read too long ago to project from never counts as room to spare. Since Claude passes the suggestion with every message, a message to a busy Codex consultant with the model and effort its turn already runs on is added to that turn, not refused. Past about 70% of its own week on pace, Claude Code hands read-only work that saves real effort to a consultant, and past about 90% also puts off optional work. Your own instructions and a model or provider you name still come first.
- Reviews ask for every finding in the first round and stop after three rounds of changes to show you the open points. Second opinions are blind: a new consultant on the other provider sees the brief and the work first, and the disputed finding only after its own verdict. A decision that is costly to undo goes to a Codex and an Antigravity consultant at once when both are installed and have room.
- The `consult` skill nouez shipped in `skills/consult/` is gone: `ConsultantBudget` does its job for everyone. If you copied it to `~/.claude/skills/consult/`, delete that copy, since your own skill comes before nouez's suggestions.
- Automatic window arranging on Windows is off by default. Ask Claude to turn it on. An existing `auto: true` setting stays on. You can still ask Claude to arrange the windows once.

### Fixed

- SECURITY.md didn't say that Codex consultants can use OpenAI's hosted web search, as Codex allows by default. It does now, with the Codex setting that turns it off.
- A stopped Codex consultant could still be reached by its full id, though the guide says it is out of reach until unarchived. nouez now refuses it and says how to bring it back.

## [0.23.0] - 2026-11-24

Phone first, and fewer windows. nouez now keeps the computer reachable from the Claude phone app: `server.py dispatcher` sets up a Remote Control server, the dispatcher, in a folder of its own, starts it at each sign-in and starts it again when it ends, so the app can open, resume and close Claude Code sessions in any project without anyone at the computer. The README now starts from that: the phone is where you work, the computer is the server. Set it up with Setup step 3 (`dispatcher setup`, one interactive run, `dispatcher install`).

Fewer windows: nouez no longer opens a Codex pane or window for each consultant: the status screen has a consultations page instead, where every consultant on the computer, Codex and Antigravity alike, is in one place with its latest turn shown as it runs. A server closes, once, the panes earlier versions opened, and only one status screen is ever open. On Windows, nouez arranges the windows it does open in a grid that fills one screen, and keeps them arranged as they open, close or are moved. [The status screen guide](docs/status-screen.md) has pictures of the status screen, its consultations page and the arranged windows. Reconnect `consultants` with `/mcp` in each open Claude Code session so it loads the new version. A status screen left open from an earlier version restarts on this one by itself, but its window, run by the old version's code, keeps only the period across later updates, not the page: close it with `q` and open it again once.

### Added

- **The phone dispatcher: `server.py dispatcher`.** `setup` makes the dispatcher folder (`~/Projects/dispatcher` unless `--folder`), writes its `CLAUDE.md` when there is none, and adds allow rules for `OpenClaudeSession`, `ListClaudeSessions`, `ListProjects`, `CloseClaudeSession`, `ConsultantBudget`, `OpenStatusScreen` and `ArrangeWindows` to its `.claude/settings.json`, after a dated copy, leaving alone a file that isn't valid JSON or a `.claude` that is a link. `install` checks the folder is set up and trusted (itself, or in git its repository, not only through a folder above it) and `claude` can be found, then starts the dispatcher at each sign-in and now: a Task Scheduler task `nouez dispatcher` on Windows (hidden, with `pythonw`), a launch agent on macOS, a desktop autostart entry on Linux. `uninstall` removes that and stops it; `status` shows whether it runs and is connected; `run` is what the sign-in start runs. `--dry-run` shows what `setup`, `install` and `uninstall` would do.
- **The dispatcher's supervisor** runs `claude remote-control --name dispatcher --spawn same-dir`, hidden, tells from its status line (`·✔︎· Connected · dispatcher`) when it is connected, starts it again when it ends (after 30 seconds, doubling up to 15 minutes), ends one that hasn't connected in 5 minutes, and stops it with itself (on Windows job objects, one for the supervisor and one holding each run's `claude` from its start; elsewhere its process group, emptied before `claude` is collected), ending each run's processes before the next. The windows nouez opens under it, its window arranger and the Codex daemon leave its jobs, so they outlive a run. Only one runs per user. `install` and `uninstall` stop it through a request file (a plain file only), never by process id, change only a sign-in start that is nouez's (exactly the command `install` writes, with nouez's own `server.py`, ending `--sign-in`, run as you, and on macOS no `Program` key), and one at a time; a supervisor started at sign-in waits while they work, then starts `claude` only while that start runs its own folder and profile, and exits otherwise or when it can't tell; `install` asks one that started meanwhile for another folder to stop, and starts the new one again, or fails if it doesn't stop. On Windows a supervisor that can't put itself in its job exits without starting `claude`. On Linux `install` records where it put the autostart entry, so `uninstall` finds it from any shell, and the `PATH` it ran with, which the supervisor started at sign-in puts ahead of the desktop's, so a `claude` from npm or nvm is found. On macOS `install` unloads only a launch agent launchd loaded from nouez's plist. Its files are always in `%LOCALAPPDATA%\nouez` or `~/.cache/nouez`, whatever the environment says. It logs to `dispatcher.log` and `dispatcher-claude.log` there, each capped at 1 MB with one older copy (a log whose older copy isn't a plain file stops growing).
- `doctor` has a phone dispatcher section: its folder, rules and trust, whether it starts at sign-in, whether it is connected, and any other `claude remote-control` running, by process id and name only, the name read from the process's own arguments, or the process id alone on systems other than Windows, macOS and Linux (one you set up yourself would make the app list the computer twice). The status screen's top bar has a dispatcher badge: green while connected, amber while not, red when its supervisor ended without being asked to, none once it was stopped.
- **nouez arranges its own windows (Windows, in Windows Terminal).** The Claude Code sessions `OpenClaudeSession` opens and the status screens `OpenStatusScreen` opens are put in a grid on one screen: two side by side, three as a tall one and two stacked, and so on in columns, the oldest first, each box close to a 16:10 shape and at least about 60 by 16 characters. Other windows, your own terminals included, are never moved. As windows open and close, the grid changes. A window minimized, maximized, on another virtual desktop or dragged into another window is left out until it comes back. Moving one by hand is taken as a request: dropped on another window, the two swap places; taken to another screen, it stays there; anywhere else, it goes back. The arranging is done by a small process (`server.py arrange`) that sleeps until Windows reports a change to a Windows Terminal window or a screen, and ends 10 seconds after the last window closes; it uses only the standard library and nothing leaves your computer.
- **`ArrangeWindows`** arranges those windows now, bringing back any taken to another screen, and says how many it arranged, left out or couldn't fit. `auto: false` stops nouez arranging them by itself (the windows stay where they are), and `auto: true` turns it back on; the setting is kept in `arrange.json` in nouez's cache folder.
- **The status screen's consultations page** (`c`, or `OpenStatusScreen` with `page: "consultations"`). It lists the consultants nouez started on this computer, from every project (an older Codex one, past the 50 newest Codex sessions, too, when it is among the last 100 the usage log names): working ones first, then the most recently active, with each one's state, when it was last active, the verdict of the reply to its last message and that message's kind (from the usage log), its project and its model. The selected one's latest turn is shown below and kept up to date while it runs: the message it was sent (with the user's own words Claude Code passed on, under a label of their own), its thinking summaries, the commands it ran (with a failing exit code), its searches and its messages. `↑` `↓` (or `k` `j`) select; Page Up, Page Down and Home scroll back through the turn, End follows it again. Under it is the command that opens the consultant in its own CLI (`codex resume <id> --remote unix://<socket>`, naming the daemon nouez reads so it finds the consultant from a terminal with another `CODEX_HOME`, or `agy --conversation <id>`), quoted for the shell, with its folder. The page reads over one Codex connection kept open while the screen runs (the list every 12 seconds, a running turn every 1.5) and sends no consultant anything. `server.py top --page consultations` starts on it; `--once` prints the usage page only.
- Pictures in [the status screen guide](docs/status-screen.md), drawn by nouez's own code with made-up data: the status screen, its consultations page, and three arranged windows.

### Changed

- **The README is phone-first:** a new opening and Why, a section with a diagram of the phone, Anthropic's Remote Control and the computer and what that asks of the computer, the Claude app in Requirements, the dispatcher as Setup step 3 (the consultant CLI is step 4 and the waiter step 5), and a From your phone section. "A dispatcher for every project" is now "The phone dispatcher", about nouez's own.
- **The README is a seventh of its length** (about 2,600 words, from 17,800), and its first line calls nouez a phone-first setup for Claude Code. It keeps the opening, requirements, a short setup, what to ask from the phone and of a consultant, and the security notes. The rest moved, unchanged, to guides in `docs/`: [setup](docs/setup.md) (each step in full, and updates), [the phone](docs/phone.md), [consultants](docs/consultants.md), [the status screen and windows](docs/status-screen.md), [tools](docs/tools.md), [troubleshooting](docs/troubleshooting.md), [how it works](docs/how-it-works.md) (with the files nouez keeps) and [limitations](docs/limitations.md). Messages and docs that named a README section now name its page, and `verify.py static` checks that every link between the Markdown files leads to a file and heading that exist.
- **One status screen.** `OpenStatusScreen` opens a window only when no status screen is open; otherwise it switches the open one to the `page` (`usage` or `consultations`) and the period asked for, and asks Windows to bring it forward. A screen started by hand with `server.py top` counts as open, and a second `server.py top` switches the open one (to its `--page` and `--days`, if given) and exits instead of starting another. A page asked for while the screen starts or restarts is applied once it runs, and only once. A new window starts on 7 days when `days` isn't given; if it hasn't started within 5 seconds, `OpenStatusScreen` says so instead of reporting it open.
- The status screen's `r` reads the consultants again too, and a screen restarted on an update keeps its page as well as its period.
- Text from a consultant or the usage log on the status screen (replies, the sender's name, errors, a message's kind) is shown without control or formatting characters, so it can't move the cursor, change colours or reorder what is shown.
- `GetConsultantHistory` names a turn typed in Codex itself "someone typing in Codex" (it was "someone in the Codex pane").

### Removed

- **Codex panes.** nouez no longer opens a pane beside Claude Code, or a window, for a Codex consultant. `WatchConsultant` is gone, and so is `StartConsultant`'s `watch` argument (a caller that still passes it is ignored). To watch a consultant, use the consultations page; to type to it, run the `codex resume <id>` the page shows, in a terminal of your own. `StopConsultant` no longer closes panes, and `doctor`'s terminal line now says where Claude Code sessions and the status screen open (tmux is no longer checked). When a 0.23.0 server starts, it closes, once and in the background, the panes earlier versions opened: only those carrying the token nouez gave them, so a `codex resume` you started yourself stays open. On Windows it ends a pane's `cmd` window only while nothing runs in it but that `codex` (through npm's `node` or not) and its console, so a program you started at the prompt a finished pane left is never ended. On Linux it signals the pane's `codex` process through a pidfd held while its arguments are read, so a process id passed on to another program is never signalled. macOS has no such handle, so there the panes are left open: close them yourself.

## [0.22.0] - 2026-11-24

Security hardening, and a [SECURITY.md](SECURITY.md) that says how to report a vulnerability privately and what nouez sends where, keeps and for how long. nouez now deletes the files it keeps after a set time, refuses links where it writes, and no longer lets the Artificial Analysis key follow a redirect. Reconnect `consultants` with `/mcp` in each open Claude Code session so it loads the new version.

### Added

- **SECURITY.md.** Report a vulnerability through GitHub's private reporting (the repository's Security tab → Advisories → Report a vulnerability). It also lists every contact nouez makes or causes (its two web requests, and what goes through Codex, Antigravity, Claude Code and git), what it does with credential files (looks at one's time, never opens one), each tool's permissions, what trust can and can't prove, and a retention table. The README's security note is now a summary that links to it.
- **`NOUEZ_NO_TRUST_WRITE=1`** turns trust writing off: `OpenClaudeSession` refuses `trust: true` for a folder not already trusted, before it makes or writes anything (even the folder `create: true` would make), and never writes `~/.claude.json`, so an untrusted folder is answered at Claude Code's own prompt on the computer. nouez can prove Claude received a folder's report, not that you read it; this is for when you want that proof.
- **The verify script checks SECURITY.md's lines in `server.py`'s code** on every run, in CI too: no network module, every web request through `fetch_json` to `RELEASES_URL` or `AA_MODELS_URL`, each pinned to its address, credential files named only to read a time, no permission-bypass word and no `curl`, `wget` or `Invoke-WebRequest`, Codex consultants read-only with approvals `never`, and all of Antigravity's deny rules. These catch a plain change, not every way around them. `tests/test_verify.py` covers each rule.

### Changed

- **The usage log is renamed each month** (or sooner past 20 MB, as before), and renamed logs are deleted a year after their last event, the oldest first while they add up to more than 100 MB. Before, a renamed log was kept forever. The status screen's "all" period now says "all kept". Two servers writing and renaming at once can't lose a line: each holds a lock (`usage-log.jsonl.lock`) from the rename check to the end of its append, and a rename takes a unique name. An event that waits over 2 seconds for the lock is skipped, never the tool call, and nothing is written to a log that isn't a regular file.
- **An Antigravity consultant's turn files are deleted 90 days after you stop it.** They hold each message (with an attached diff) and agy's output, and were kept forever. Its `consultant.json` stays, now with its agy conversation id, so `agy --conversation <id>` still opens it. A file that can't be deleted is tried again at the next start.
- Old files (long replies, saved diffs, Antigravity turns, usage logs) are removed in the background when a server starts, not only when a new one is saved.

### Fixed

- **The Artificial Analysis key could follow a redirect to another site.** Python's default redirect handling sends custom headers on, so a redirect from `artificialanalysis.ai` would have taken the key with it. Both of nouez's web requests now go through one function that starts only at those two addresses, refuses a redirect to another scheme, host or port, and reads at most a set size.
- **The folder report no longer shows permission rules unmasked,** and masks header-style secrets (`Authorization: Bearer …`, `X-Api-Token: …`, with or without a space after the colon) everywhere it masks, prompt hooks and fields it doesn't know included.
- **A linked settings file or folder in a project is reported as unread, not followed.** A project could link `.claude/settings.json` to a file elsewhere, and the report showed that file's content as the project's; trust then can't be recorded from the phone, as for any file nouez can't read. So is a file swapped for another while nouez reads it.
- **nouez refuses links where it writes and deletes:** Antigravity's folders and turn files, saved diffs, long replies, the usage log, the JSON caches, the pane key, lock files and the `~/.claude.json` backups. nouez trusts its cache folder itself and checks every folder below it. A link there could have made it write or delete elsewhere. Antigravity's turn files and the usage log are created readable by you only (macOS and Linux), and a backup folder that isn't private stops the trust change before anything is written.
- Taking a diff (`revision: true`) no longer lets git fetch objects missing from a partial clone: nouez passes `--no-lazy-fetch` (git 2.45 or later), and with an older git takes no diff of a partial clone or a repository with a promisor remote, and asks for a review of the working tree.
- The status line file (`claude-usage.json`) keeps only each window's percentage and reset time. It used to keep whatever else Claude Code put under `rate_limits`.
- On Windows, telling whether a process is nouez's own helper reads its command line directly instead of starting PowerShell.

## [0.21.0] - 2026-11-24

Reviewers get one diff, named by its SHA-256, the status screen counts a forked subagent's copied replies once, and a review that couldn't read its input is no longer counted as an approval. Reconnect `consultants` with `/mcp` in each open Claude Code session so it loads the new version. A running status screen restarts on it by itself and counts its numbers again once.

### Added

- **`revision: true` takes the uncommitted diff once and names it by its SHA-256.** The revision line used to give only the commit and the number of uncommitted paths, so a consultant reading the working tree a minute later could review changes made after the message was sent, and two consultants could review different code under the same line. nouez now takes the diff when the message is sent and saves it as `patches/<digest>.patch` in its cache folder for 14 days, and asks the consultant to review that file and name the digest. Git writes the whole diff, untracked files included, from a temporary copy of its index, so nothing in the repo changes. It leaves out binary files, untracked files over 256 KB and untracked files with a part of their path that looks like a secret, and the line names them. An Antigravity consultant can't run `git diff`, so with the new `attach_diff: true` it gets the diff in its message, up to 200,000 bytes; its text then goes to Google. Without it, an Antigravity consultant gets the line as before. nouez runs no git hooks while it takes the diff. The usage log records only the digest. When the diff can't be taken or saved, the line says so instead of naming one.

### Fixed

- **`server.py top` counts a Claude Code reply once when a forked subagent's transcript copies it.** A fork's transcript starts with its parent's history, under the same message ids, and those replies were counted again as the subagent's output; on the machine this was found on, that was about 3% of subagent output. A reply is now counted once across a session's transcripts, in the session's own transcript when it has it; when a transcript is removed or rewritten, its session is read again, so the counts always match a fresh read. The usage cache, `usage-weeks.json`, is read again from the transcripts once after the update, which can take half a minute, and is now larger, about 3 MB for three months of heavy use, since it keeps the message ids each transcript counted. (Codex forks were checked too: their running totals start from zero, so they were already counted once.)
- **A review that couldn't read its input is no longer logged as an approval.** A first line such as "Incomplete: no findings because the diff could not be read" used to be read as `yes` because it says "no findings". It is now `incomplete`, as is a turn that failed or was interrupted, whatever its text says; the status screen counts replies logged by older versions by the same rule, so an interrupted turn no longer extends a run of CHANGES rounds. A line that starts with "Verdict:" is read from the word after it, so "Verdict: yes. I couldn't run the tests" stays `yes`, "Verdict: yes, with changes" is `changes`, and a "verdict" quoted later in the line doesn't count. The status screen's verdict column is wider to fit the new word, and the README's brief template offers "incomplete" as a verdict.

## [0.20.0] - 2026-11-23

The waiter now says when a consultant may be stuck, and a message sent twice to a busy Codex consultant reaches it once. Reconnect `consultants` with `/mcp` in each open Claude Code session so it loads the new version.

### Added

- **The waiter says when a turn may be stuck.** When nouez sees no change in a running turn for 10 minutes (Codex's session file and agy's event file grow every minute or so while a turn works), the waiter exits early with the output so far, says the consultant may be stuck, thinking at length or running a long command, and gives the same command to keep waiting. Claude tells you then, instead of after the waiter's 25 minutes. An Antigravity turn waiting on agy's `schedule` tool, which nouez can't deny, is the known case.
- The consult skill's review loops: when Claude and the consultant still disagree about a finding and both Codex and Antigravity are installed, Claude sends the brief, the finding and both sides' reasons to a new consultant on the other one, for a view that hasn't seen the earlier rounds. If you copied the skill to `~/.claude/skills`, copy it again: `/mcp` reloads only the server.

### Changed

- **A message nouez already delivered to the running Codex turn isn't sent again.** Sent twice, as once Claude's context was summarised, it used to be steered into the turn a second time. The result now says it was already there and gives the turn's id; with `model` or `effort`, it says the running turn keeps them rather than refusing. A message sent again after the turn ended still starts a new turn.
- Cleanup, with no other change in behaviour: four functions only the tests called are gone (the tests check the code nouez runs instead), along with code that repeated `remove_file`. Each Codex connection is closed by `contextlib.closing`. Codex and Antigravity now share their reply, waiter and JSON-lines code, and opening a Linux terminal window is written once. The README no longer lists the "open in another app" pane problem, fixed in 0.19.0.
- The verify script's static checks also report a top-level function, class or constant that nothing else in its file uses. It follows Python's scopes, so a local, parameter, class attribute or comprehension variable with the same name doesn't count as a use; `tests/test_verify.py` covers it, and CI runs it.

### Fixed

- `server.py top` no longer stops with an error when the usage log has a line that isn't valid UTF-8; it skips that line, as it skips one that isn't JSON. A failure to save the usage scan's cache is now logged; before, the message for it could never show.
- The unit tests pass on a tag's detached checkout and no longer race Windows' clock, and a test can no longer open a real terminal window.

## [0.19.1] - 2026-11-23

`ListProjects` no longer calls every folder a link when the folder it lists is itself reached through one. Reconnect `consultants` with `/mcp` in each open Claude Code session so it loads the new version.

### Fixed

- **`ListProjects` marked every folder "a link to …" when the listed folder was reached through a link or a short Windows name** (on macOS, anything under `/var` or `/tmp`; on Windows, a path such as `C:\Users\RUNNER~1`). A folder now counts as a link only when it resolves somewhere other than its own place in the listed folder, resolved the same way.

## [0.19.0] - 2026-11-23

Trusting a folder from the phone now starts from a report nouez writes of everything the folder would run, a session can list your projects, and nouez warns a week ahead when Claude Code's sign-in on the computer is about to end. Reconnect `consultants` with `/mcp` in each open Claude Code session so it loads the new version. A running status screen restarts on it by itself.

### Added

- `ListProjects`: the folders in a folder, by default the one holding the session's own folder (for a dispatcher, your projects), each marked git, trusted (itself or through a folder above it) or not, with the Claude Code sessions running in it and its project settings files. Hidden folders (a dot name, or marked hidden on Windows) are left out. Reads only.
- `OpenStatusScreen`: opens the status screen (`server.py top`) in a new terminal window on the computer, with 1, 7 or 30 days of consultations or all of them.
- A sign-in warning. nouez reads the line `claude auth status --text` prints about when Claude Code's sign-in ends, keeps only that line in `nouez/claude-login.json`, and from 7 calendar days before the earlier date (3 days before the exact end the line gives) adds a warning, with how to renew, to the results of `OpenClaudeSession`, `ListClaudeSessions` and `ListProjects`. `ConsultantBudget` always shows the line; the status screen's top bar always shows the date to renew by and the days left, grey until the warning is on, then amber and red. It is read in the background when a server starts, about hourly (every 10 minutes in the last week) and when the credentials file's time changes; nouez never reads inside that file. `ConsultantBudget` waits for a reading that is due, up to about 25 seconds. The saved line is used only by servers with the same Claude Code config folder and sign-in variables (their names are saved, never their values). `NOUEZ_NO_LOGIN_CHECK=1` turns it off.

### Changed

- **`OpenClaudeSession` reports what an untrusted folder would run.** When it opens nothing because the folder isn't trusted, the result gives a report of `.claude/settings.json`, `.claude/settings.local.json` and `.mcp.json` in the folder trust would be recorded for, the checkout that opens and the folder itself: hooks with their matchers and other commands, the names of `env` variables (not their values), permission rules and mode, extra folders, MCP servers (variable and header names only), plugins on or off, marketplaces with their sources, and any setting it doesn't know. What looks like a password or key shows as `***`, characters that don't print are spelled out, and a shortened report says it is a summary. A file it can't read is reported as such, never as nothing. Claude is told to show it to the user with the question.
- **`trust: true` works only after that report.** nouez records trust only for a folder whose report it gave earlier in the same conversation, with the files unchanged to the byte since; otherwise it gives the report again and records nothing. When a settings file can't be read it never records trust: the user looks on the computer. A folder the same call creates outside a git repository needs no report.
- **A folder trusted only through one above it, with its own `.claude/settings.json`, is asked about first.** Such a folder can bring Claude Code's trust question back, so `OpenClaudeSession` no longer opens a window that may wait at it: it gives the report and asks, as for an untrusted folder. `open_untrusted: true` still opens it.
- README: the dispatcher's example `CLAUDE.md` uses `ListProjects` and the report, the permissions to allow include the new read-only tools, and a tip on following a hidden dispatcher from the computer (https://claude.ai/code in a browser, and a log file for the server's own output).

### Fixed

- **A Codex consultant's pane showed "This conversation is open in another app" instead of the consultant.** Given nouez's `-c` options, `codex resume` started an app server of its own inside the pane, which can't take the thread from the Codex daemon nouez uses, so the pane was locked out from its first message. The pane now attaches to that daemon (`--remote` with the daemon's own socket, so a terminal with another `CODEX_HOME` reaches the same one). Close a locked pane; nouez opens a working one on the consultant's next message.
- **So a pane now asks "Trust this folder?" in a folder Codex hasn't trusted.** A pane on the daemon asks the daemon, which takes no trust for one run, so nouez no longer passes one. Choosing **Trust and continue** saves the answer in your Codex config, and the pane doesn't ask there again.

## [0.18.1] - 2026-11-23

Claude consults when your own instructions call for it, not only when you ask. Reconnect `consultants` with `/mcp` in each open Claude Code session so it loads the new version. Reconnecting loads the server only: if you copied the consult skill, copy its new description into your installed copy too.

### Changed

- The MCP instructions tell Claude to start a consultant when the user's own instructions (their CLAUDE.md or a skill) call for one, as well as when the user asks.
- The shipped consult skill's description says to use it before substantial read-only work that the user's instructions send to a consultant, without waiting to be asked.
- README: a new section, "A dispatcher for every project", on what Remote Control does alone (a `claude remote-control` server is tied to the folder it runs in and its worktrees, and takes new sessions only while it runs) and how a dispatcher folder with nouez reaches every project from the phone, with a `CLAUDE.md` to adapt, its permission rules, starting it at sign-in, and what archiving a conversation did with Claude Code 2.1.330. Tips: a `~/.claude/CLAUDE.md` example for consulting without being asked.

## [0.18.0] - 2026-11-22

nouez now sets up for anyone who clones it: with Codex, Antigravity, both or neither, on Windows, macOS or Linux. Reconnect `consultants` with `/mcp` in each open Claude Code session so it loads the new version. A running status screen restarts on it by itself.

### Changed

- **StartConsultant without `provider` uses Codex when the codex CLI is installed, otherwise Antigravity**, and says so in its result. With neither installed it names both CLIs and `server.py doctor`, and says the Claude Code session tools still work. An explicit `provider` is kept as before.
- Without Codex, the consultant tools work with Antigravity consultants: ListConsultants lists them (or none, with the next step) instead of failing, and an unknown name gets "No consultant named …" with the Antigravity ones, not "`codex` CLI not found". ConsultantBudget says "Codex: not installed" in one line, and `top` leaves out the Codex card and badge.
- What Claude reads (the MCP instructions and tool descriptions) names both providers, marks what only Codex does (the daemon, panes, steering, shell commands), and says to put a diff or output in an Antigravity message, since agy can't run commands.
- `server.py doctor` reports Claude Code, Codex (on PATH, daemon, signed in) and Antigravity (found, version, signed in) each on its own, and reports a problem only when no consultant CLI works. It checks Python 3.9 or later for real, finds `claude` on every system, checks for tmux or a terminal emulator on Linux, and prints the allow rule's hint when Claude Code has no settings file yet.
- The allow rule for the waiter has a PowerShell form only on Windows.
- The waiter command quotes the server's path for the shell it is run in. When the Bash and PowerShell forms differ, the result gives both; a path that can't be quoted safely gets GetConsultantReply instead.
- README: setup rewritten for each of the four setups, with a table of what works in each, install and sign-in steps for each CLI, and `doctor` as the last step. New: how to install the shipped consult skill, how to add or change the Artificial Analysis key, the files nouez keeps and where, and what goes over the network.
- Linux panes and windows try more terminal emulators (konsole, xfce4-terminal, kitty, alacritty, wezterm, foot), in one list that doctor shares.

### Added

- `skills/consult/SKILL.md`: a consult skill for any setup, which picks a consultant's model and effort by the kind of question, the providers installed and the usage left. Copy it to `~/.claude/skills/consult/`.
- `server.py statusline`: a status-line command that saves Claude Code's usage windows for ConsultantBudget and `top` (under a lock, keeping the newer window, written atomically), prints a short status line or nothing with `--quiet`, and never fails. It replaces the PowerShell snippet in the README and works on every system.
- `verify.py live --setups` runs nouez as a clone with Codex only, Antigravity only, both and neither would, each with an empty cache and the left-out CLI hidden. Unknown options are refused.
- CI: the static checks and unit tests on Windows, macOS and Linux with Python 3.9 and 3.12.
- REVIEW.md item 11: changes to providers or setup are checked against every setup.

### Fixed

- On Python 3.9 and 3.10, a timestamp with other than 3 or 6 digits of fractional seconds (as Antigravity writes them) couldn't be read.
- A pane or window whose launcher failed (a tmux split, an emulator without a display, or on Windows `wt.exe`, or without it the console window, whose own process is now watched; codex's errors show in that window) was reported as opened. nouez now waits a moment, reports the error with what to run yourself, and suggests `watch: false` with no display.
- On macOS, the command for a new Terminal window went into the AppleScript's source. It is now passed as an argument, so no text in it can change what runs.
- A program in the current folder named `codex`, `agy`, `claude` or `tmux` could be run in place of the real one. Programs are now looked up on PATH's absolute folders only (on Windows, ones with a drive or share), doctor, the tools and the commands shown all use the same path, and no watch pane opens when `codex` can't be found.
- On macOS and Linux, CloseClaudeSession signalled the registry's pid without checking it. It now checks that the process is that Claude Code session (its program by name, a version the native installer keeps, or Node or Bun running Claude Code's `cli.js`; a start `ps` places before the session's registration; and Claude Code's registry still holding that session's entry for the pid, which a new process with the pid writes over) and not a process the server runs under, just before it signals, and declines when it can't tell, also when `ps` can't show every process the server runs under.
- nouez's files could land in the current folder with a relative `XDG_CACHE_HOME`, and long replies went to the shared temp folder. Its folder is now always absolute and, on macOS and Linux, readable by you only: one that is another user's, a link, in a folder other users can change, or can't be made private is not used: nouez keeps its files in a private `nouez-<uid>` folder in the temp folder, shared by all its processes, with a note saying so (only if that isn't usable either does a process get one of its own, and the note says what that loses). Long replies are saved in it as `replies/reply-<turn id>.md`, written whole or not at all, and deleted after 14 days (checked when nouez starts and when it saves another); only files with that name are deleted, and a `replies` folder that is a link or a junction is left alone.
- StartConsultant said it reused an Antigravity consultant even after agy was removed. It now checks agy first, ConsultantBudget lists agy's models even when its quota call fails, and an unavailable default model gets an error that says what to do.
- With neither consultant CLI installed, an unknown consultant name got "Codex isn't installed" alone. It now says neither is installed and points to `server.py doctor`.
- On Windows with agy outside PATH, doctor told you to run a bare `agy` to sign in. It now gives the command by its full path.
- Doctor's no-display note on Linux was left out when tmux was installed, though OpenClaudeSession needs a display either way. It now always shows, and says what it stops.
- Off Windows, CloseClaudeSession said the terminal stayed open even where it closes. It now says the window closes if the terminal closes when its command ends, and stays at a prompt otherwise.
- A message to a Codex consultant was steered into a turn typed in its watch pane, which may not be read-only. nouez now steers only a turn this server started, by its own record (a turn's text, or the turn it carries on, proves nothing), and otherwise says nothing was sent and to wait for that turn.
- When `claude` is a batch script (`claude.cmd`), OpenClaudeSession passed the first message through cmd, which can read characters in it as commands. It now opens the session without it and shows the message to paste.
- A path to agy, Python or nouez with characters a shell reads specially could give a command that doesn't run: doctor's sign-in command is quoted for the shell, a path with `*` gets no allow rule (the rule would match other paths too; `allow-rule` says so and exits 1), and a pane that can't be opened safely on Windows gives the PowerShell command to run when PowerShell can pass it to codex unchanged.
- With `LOCALAPPDATA` relative, nouez could look for agy under the current folder. It now only uses an absolute one.
- On Python 3.9 and 3.10, a Codex `config.toml` with a line nouez's small reader can't follow (an array or inline table, a value over several lines, a key given twice, or a value that isn't TOML) could give the wrong trust for the watch pane's folder. Such a file now counts as unknown, so the pane asks.
- Without Codex, StartConsultant passed a Codex model on to Antigravity when `agy models` didn't answer. It now uses Antigravity's default and says the model couldn't be checked.
- `server.py wait` printed a traceback when it couldn't read the Antigravity consultants file. It prints the error and exits 1.
- Doctor exited 1 when one consultant CLI was signed out though the other worked. One working CLI is now enough; the other's problem is shown. An agy that doesn't answer within 60 seconds is reported as slow or offline, not as signed out.
- The status line could save a window that had already reset, and could fail on a huge number or deeply nested JSON. It now drops such a window (from the line it prints and the usage log too), reads such input as nothing, and never fails. ConsultantBudget and `top` give each Claude Code window the pace of its own reading, so an old reading kept beside a fresh one shows no pace.
- README: the stdin form of `codex login --with-api-key` for each shell, and the status screen's network use (the Codex daemon's usage and agy's quota) instead of "Nothing leaves your computer".
- The consult skill uses a provider or model the user names before its own routing, and says so when that one isn't available.
- Tests and CI: tests that assumed Windows run on every system; the shell test uses Git Bash on Windows, not WSL's `bash`; Python 3.9 runs on `ubuntu-24.04`; the static checks run on the pushed or pull-request range (`verify.py static --range`, which fails when git can't read the range); and `verify.py live --setups` reads PATH as nouez does, keeps native programs as they are, and checks each setup's providers, ids, usage and a reply from each consultant.

## [0.17.0] - 2026-11-22

A new look for the status screen, from a design review. A running screen restarts on it by itself. Reconnect `consultants` with `/mcp` in each open Claude Code session so it reports the new version.

### Changed

- `server.py top` draws its parts in boxed panels, under a top bar with the version, the period, the time and a badge for each subscription: a dot in the colour of its most pressing window and that window's use, named when it isn't the weekly one (`● Claude 95% 5-hour`, `● AG Claude+GPT 82%`). The keys are in a bar on the bottom line.
- Each usage bar has a mark (`┊`) where the window's time has got to, so a bar filled past it is being used faster than evenly. The pace stays as text beside it.
- From 149 columns, each subscription is a card in a column on the left, with shorter outlooks (`~23% pace`, `out ~5h`), beside the consultations and the offload table. Below that the panels stack, at most 104 columns wide.
- With the 7- or 30-day period, CONSULTATIONS shows the messages sent each day as a line of small bars.
- `?` opens a help page on what the marks and columns mean, with the log's path; `?` or Esc goes back. Those notes no longer take lines under the offload table, and `--once` prints them at the end.
- On a short screen, whole lines are dropped by panel, so every box closes: the optional lists first, then weeks down to three, then the consultations' tables, then the rest of the weeks and whole panels. Before, the lines just above the offload table were cut one at a time.
- `--once` to a file or pipe prints one column 104 wide instead of lines up to 1000 long.
- Faint text uses bright black, which older consoles show, instead of the faint attribute. A Windows console other than Windows Terminal, ConEmu, or one that names itself gets square corners and `|` for the mark.

### Fixed

- Line widths were counted in characters, so a wide character (a CJK project name, for example) pushed a line past the screen's edge. They are now counted in terminal cells.
- An arrow or function key was read as two keys on Windows, and as Esc (quit) followed by letters elsewhere. It is now read whole and does nothing.
- The screen waited up to 5 seconds to fit a resized terminal. It now redraws at once.
- A line as wide as the terminal could wrap on consoles that wrap at the last column, and the last line's newline could scroll the screen. Lines now stop one column short, and the last one has no newline.

## [0.16.0] - 2026-11-22

The status screen follows updates and gets fixes from a review of its numbers and layout, plus fixes from a review of 0.15.1's Codex panes and Antigravity stops. Close a status screen started before this version and run `server.py top` again once; from then on it follows updates by itself. Reconnect `consultants` with `/mcp` in each open Claude Code session.

### Changed

- `server.py top` lists Antigravity's quota groups under one Antigravity line (Gemini, Claude+GPT, Argon) instead of as separate "AG" rows, and the OFFLOAD table's "consultants" column is now "Codex consultants", apart from the Antigravity column.
- `server.py top` colours only the filled part of a bar, so an empty one no longer looks full.
- `server.py top` fits a terminal 100 columns wide: shorter bars, a narrower OFFLOAD table, and the consultations' summary on two lines. Percentages, project counts and forecasts were cut off. On a screen too short for everything, the "which kind went where" and "reasons given" lists go first, then OFFLOAD's notes and older weeks, then the consultations' last lines, so OFFLOAD's latest week stays in view.
- CONSULTATIONS shows which kind of consultation went to which model, and the reasons given latest first. Antigravity models show their level once (`gemini-4-neon low`, not `gemini-4-neon-low low`), and models other than Gemini run on Antigravity are marked `(AG)`.
- `server.py top` kept running the version it started with after nouez was updated, so its numbers and header could be out of date. It now watches `server.py` and, once the file has stayed the same for a redraw, compiles and still has the status screen and its entry point, starts again on it with the same period. That doesn't prove the file whole: one cut short after those lines passes, and then the window waits as below. `top` runs the screen as a child process and restarts it, on every system. It notes the version before the screen's Python reads the file, so a change made while the screen starts counts too, and a fix written while a failed screen was starting is picked up at once. Once the screen has restarted, only quitting it (`q`, Esc or Ctrl+C) closes the window: a restarted screen that fails, or ends without being asked to (a file cut short that does nothing), leaves it waiting for the next update. Ctrl+C at any moment closes the window, and elsewhere than Windows, ending `top` (or closing its terminal) ends the screen too, which puts the terminal back as it was, even when it comes while the screen is starting. `--days` takes 0 to 65,535 (179 years); anything else is refused.

### Fixed

- The status screen's consultation counts disagreed: replies read in a period, to messages from any time, were set beside the period's messages, so there could be more replies, or more CHANGES verdicts, than messages. Replies are now those to the period's messages, each as first read; other replies read are counted apart, also in a period with no messages, and failed or interrupted ones are shown.
- A review loop counted every message, so messages steered into one turn counted as several CHANGES rounds, and the warning said "went past 3" for three. A loop now counts each turn once, and the warning says "3+ CHANGES rounds in a row".
- "Not approved" was read as a yes verdict, and a reply that was just "OK" had none. They are now no and yes.
- OFFLOAD showed 0 where nothing was measured: "messages" in weeks before the usage log began, and Antigravity tokens for turns that reported none. These now show a dash (a `+` when only some reported), the column is "sends", a week with messages but no transcripts is listed (with no share), and the share is said to be of the output known. Antigravity's tokens count in the week their message was sent, not the week the reply was read. Its share is labelled as output made outside Claude Code, since it includes your own Codex sessions.
- The usage log lost its history from the status screen when it was rotated at 20 MB. The rotated files are read too.
- A saved Codex or Claude Code reading gave a forecast that grew more hopeful as time passed with the same number. Its pace is now worked out as of when it was saved, and an old reading gives none (a used-up one says "used up at the last reading"). A window at 100% showed "too early to tell the pace" instead of "used up" when its reset was a whole window or more away.
- Reading Antigravity's quota (`agy -p /usage`, up to a minute) held up Codex's usage and the transcript scan, and `r` froze the screen while it ran. It now runs on its own, the Antigravity line says "checking" until the first reading, and `r` reads again in the background.
- An Antigravity message that changed only the level (`gemini-4-neon-high` to `-low`) was logged as a model change. It is now logged as an effort change.
- On Windows, `StopConsultant` took any `codex.exe` whose command line held the words `resume <id>` for a pane, so a `codex exec` prompt with those words could be ended, as could a `cmd /k` window you had opened yourself. It also missed a pane whose `codex` ran through npm's `node`, or had already exited. A pane now carries a token, `-c nouez_pane=<token>` (Codex ignores the unknown key), made from the thread id and a random key kept in nouez's cache folder (`pane-key`), and is found by its own `cmd` window's command: `codex resume <id>` with that token, and nothing else for `cmd` to run. A terminal you open yourself is left alone, whatever you type in it. Panes opened before 0.16.0 carry no token and are left open: close them yourself. On macOS and Linux, a stop also ends only a process whose program is `codex`, run as `codex resume <id>` with the token, checked again just before it is signalled: not one you started, and not the terminal emulator that runs it, which could hold other windows. A pane's processes count only if they started after their parent and still have that parent once all of them are held open, and each is checked and ended through a handle opened before the check, so a process id passed on to another program is never touched.
- `StopConsultant` said it had closed a pane as soon as it had found one. It now counts a pane closed only once its window's process has ended, and says when one is still open.
- A pane didn't open when both the path of `codex` and the project folder had spaces: `cmd` dropped the program's opening quote. The pane's command now reaches `cmd /d /s /k` as one quoted argument, in Windows Terminal and in a console window.
- A pane trusted the session's folder even when you had marked it untrusted in Codex. A folder marked untrusted in Codex's `config.toml` now stays so, and Codex asks as usual. If `config.toml` can't be read for sure (on Python before 3.11, an `untrusted` written other than as Codex writes it, or an escape outside a `'...'` string), no folder is trusted for the run, and an odd but valid `config.toml` no longer keeps the pane from opening.
- A folder with letters outside ASCII in its path (`C:\École`) got the wrong trust key, so its pane still asked. The key now lowercases only ASCII letters, as Codex does.
- On Windows, an agy process that exited with code 259 could be taken for one still running. nouez now asks Windows whether the process has ended, rather than reading its exit code.
- A waiter that read an Antigravity turn just as `StopConsultant` ended it could report it failed rather than stopped. nouez reads the turn's stop marks again once agy has gone. A stop that couldn't end agy retries taking back its mark, so a later failure isn't named a stop.

## [0.15.1] - 2026-11-22

Fixes from a review of 0.15.0's Antigravity consultants. Reconnect `consultants` with `/mcp` in each open Claude Code session.

### Fixed

- Two Antigravity consultants in the same folder could get the same name, so a message or a stop could reach the wrong one. A new consultant now gets more of its id in its name when needed, chosen under one lock for all Antigravity consultants, and a name two consultants share is refused, asking for the full id.
- A turn could be reported as failed when agy wrote its result just before exiting. nouez now checks whether agy runs before reading its output.
- A message over about 1 MB made its running turn invisible, so another message could start a second turn. The turn's record no longer holds a copy of the message.
- Two Claude Code sessions could start turns on the same consultant at once, and a stop landing while a turn started could leave it running. A send and a stop now take one lock per consultant, shared by every nouez server on the computer, and a send reads the consultant again under it.
- A turn whose agy process couldn't start was reported as "Stopped by StopConsultant"; it is now reported as failed, with the reason.
- `StopConsultant` ends a turn only if its process is the one nouez started (on Windows, the same start time and program as at launch; elsewhere, a process this server started). A process nouez can't check counts as running until agy's 30-minute limit and is never ended. A stop that can't end a turn changes nothing and says so, so it can be sent again.
- On Windows, a running agy process whose times Windows wouldn't give was taken for ended, so a stop could say it had ended a turn that ran on. Only an exit code nouez can read now counts as ended; otherwise the process counts as unknown.
- `StopConsultant` marked a turn stopped before ending its process, so if the process didn't end, and the mark couldn't be taken back, the turn read as stopped while agy ran on, and another message could start beside it. The turn is now marked stopped only after nouez has seen agy end; until then it reads as still running.
- A reply that came back while nouez couldn't save a new `model` or `effort` as the consultant's didn't say so, though a later message would use the old model. It now says so, as the "delivered" result already did.
- A turn whose files couldn't be written is removed, and an agy process whose id couldn't be saved is ended with the processes it started before nouez says to send again.
- A `model` or `effort` on `SendConsultantMessage` is resolved against the consultant as read under the lock; if the new model can't be saved, the reply still gives the turn's id.
- The model is checked again just before each turn starts, so an edited consultant record can't pass an option to agy.
- On a busy Windows computer, a Codex consultant could get a new pane on every message (one had six), and `StopConsultant` left its panes open while saying it had stopped. Both asked WMI through PowerShell, which could take minutes then, past nouez's 20-second limit. nouez now reads the process list and command lines straight from Windows, in milliseconds, ends a pane's processes without `taskkill`, and says if a pane still shows a stopped consultant.
- A Codex consultant's pane could stop at Codex's "Trust this folder?" or update question, so it showed nothing. The pane's `codex resume` now trusts the session's folder and its git root for that run only (nothing is saved to Codex's config) and skips the update check.
- The architecture document named agy's output file `.out`; it is `.jsonl`.

### Changed

- The README and the server's instructions no longer describe Antigravity consultants as Gemini only.
- `server.py top`: the offload table's Gemini column is now Antigravity, since an Antigravity consultant can run any model agy lists, and the share is "not Claude Code" instead of "not Anthropic".

## [0.15.0] - 2026-11-22

Consultants on Google's Antigravity CLI, for second opinions from Gemini models on Google's quota. Tested with Claude Code 2.1.330, Codex CLI 0.170.0 with app-server daemon 0.171.0, Antigravity CLI 1.5.14, Python 3.11.9 on Windows 11. After updating, reconnect `consultants` with `/mcp` in each open Claude Code session; open sessions keep running the old server until then.

### Added

- `StartConsultant` takes `provider`: `antigravity` starts a consultant on the Antigravity CLI (`agy`), on `gemini-4-neon` at level `high` unless `model` or the new `effort` says otherwise, and reuses one already in the repo unless `new: true`. `SendConsultantMessage`, `GetConsultantReply`, `GetConsultantHistory`, `ListConsultants` and `StopConsultant` work with it as with a Codex consultant, and the waiter command too. Each message runs one `agy -p` turn in the background, continuing the consultant's conversation.
  - Read-only by agy's deny rules: file writes and edits, commands, MCP tools and URL actions, with slash commands off. Probed against agy 1.5.14; its browser tools aren't available in this mode.
  - One message at a time: a message sent while a turn runs is refused, with nothing sent. Each turn ends after 30 minutes at most, reported as interrupted. It has no pane: `WatchConsultant` gives the `agy --conversation` command instead.
  - `model` and `effort` on `SendConsultantMessage` change the agy model level for later messages; an id agy doesn't list is refused.
- `ConsultantBudget` shows Antigravity's quota groups and its models, grouped by family with their levels, when `agy` is installed.
- The usage log records Antigravity consultants' events with `provider`, their replies' token counts, and Antigravity's quota at each send. `server.py top` adds a Gemini column to the offload table, counted in the share that wasn't Anthropic's.

### Changed

- `top` and `ConsultantBudget` wait up to 60 seconds for `agy -p /usage`, not 30: on a busy computer it took over 20, and `top` showed "agy didn't answer".

### Known issues

- agy's `schedule` tool can't be denied. It changes no files, but a turn that schedules something waits until the 30-minute limit. nouez asks the model not to schedule.

## [0.14.1] - 2026-11-22

`server.py top` shows Antigravity's quota, and the status line addition keeps Claude Code's numbers steady when several sessions are open. Tested with Claude Code 2.1.330, Codex CLI 0.170.0 with app-server daemon 0.171.0, Antigravity CLI 1.5.14, Python 3.11.9 on Windows 11. After updating, reconnect `consultants` with `/mcp` in each open Claude Code session; open sessions keep running the old server until then.

### Added

- `server.py top` shows each Antigravity quota group (Gemini models; Claude and GPT models; Argon) with its weekly and 5-hour windows, read once a minute with `agy -p /usage`, a read-only command that runs no model turn. Nothing shows when `agy` isn't installed.

### Fixed

- Every open Claude Code session's status line saves `claude-usage.json`, so a session holding older numbers could overwrite newer ones, and `top` and `ConsultantBudget` jumped between them (21% one moment, 19% the next). The README's status line addition now keeps, for each window, the later window and, within the same window, the higher percentage. Update your status line script from the README.

## [0.14.0] - 2026-11-22

A local usage log and `python server.py top`, a status screen for Codex and Claude Code usage and how much work goes to consultants. Tested with Claude Code 2.1.330, Codex CLI 0.170.0 with app-server daemon 0.171.0, Python 3.11.9 on Windows 11. After updating, reconnect `consultants` with `/mcp` in each open Claude Code session; open sessions keep running the old server until then.

### Added

- nouez keeps a usage log, `nouez/usage-log.jsonl` in your cache folder: one line per consultant started, message sent and reply finished. A send records the consultant, project, model and effort (and which of them the message changed), whether it steered a running turn, its kind and reason, its length, and the usage of each subscription at that moment. A reply records its status, time and verdict. Neither records the message or reply text. The log moves aside past 20 MB. `NOUEZ_NO_USAGE_LOG=1` turns it off.
- `SendConsultantMessage` takes `kind` (`quick-check`, `re-check`, `review`, `bug-hunt`, `plan-critique`, `research`, `fact-check` or `other`) and `reason` (a short sentence on why this model and effort), both optional and kept only in the log. An unknown `kind` is refused, with nothing sent.
- `python server.py top`: each subscription's usage windows with a bar and pace, the consultations logged (by model, kind, project and verdict, with review loops that ran past three CHANGES rounds), and per week the Claude Code output tokens beside the tokens consultants and your own Codex sessions spent. It reads the Claude Code transcripts and Codex session files on this computer, keeps its counts in `nouez/usage-weeks.json` and reads only what was added since. Keys: `1`, `7`, `3`, `a` for 1, 7 or 30 days or all; `r` to refresh; `q` to quit. `--once` prints one screen and exits.

## [0.13.0] - 2026-11-22

`ConsultantBudget`, for choosing a consultant's model and effort by the usage left and how strong each model is. Tested with Claude Code 2.1.330, Codex CLI 0.170.0 with app-server daemon 0.171.0, Python 3.11.9 on Windows 11. After updating, reconnect `consultants` with `/mcp` in each open Claude Code session; open sessions keep running the old server until then.

### Added
- `ConsultantBudget` (read-only) shows, in one call: each usage window on the Codex subscription, with the percentage used, the reset time and where the current pace lands at the reset (or when it runs out first), and any free full resets, from `account/rateLimits/read`; the Codex models and their effort levels, from `model/list`; Claude Code's own 5-hour and weekly windows, from a file the user's status line saves, with its age; and the Artificial Analysis Intelligence Index, price and speed of the top 8 OpenAI, Google and Anthropic models, credited to Artificial Analysis. A failure in one part is reported in its place and the rest still shows.
  - Model scores need `ARTIFICIAL_ANALYSIS_API_KEY` (a free key). On Windows it is also read from the user's saved environment variables, so a key saved after Claude Code started works without a restart. The list is fetched about once a week and kept in `nouez/aa-models.json` in the user's cache folder; a failed fetch waits 6 hours and the old list stays in use. `refresh: true` fetches again if the list is over an hour old.
  - nouez reports and doesn't choose: the result says to go by the user's own rules. The README's new "Choosing a consultant" section shows the status line addition that saves Claude Code's usage and outlines a `consult` skill.
- The latest-release cache and the new files are written through one helper that replaces each file whole.

## [0.12.4] - 2026-11-19

nouez follows a turn that Codex carries on after a daemon restart. Tested with Claude Code 2.1.329, Codex CLI 0.170.0 with app-server daemon 0.171.0, Python 3.11.9 on Windows 11.

### Fixed
- A consultant's turn cut off by a daemon restart is followed to the turn Codex carries it on in. Codex's scheduled daemon update (0.170.0 to 0.171.0) stopped the daemon in the middle of a turn. The restarted daemon reloaded the session and, 8 seconds later, carried the turn on in its next turn, started with no message, whose `rootTurnId` names the old one. The waiter reported "interrupted" and stopped there, though the work went on. The waiter, `GetConsultantReply` and a waiting `SendConsultantMessage` now follow an interrupted turn to such a continuation, through chains of them. Going by the root, a continuation is only the next turn in the thread, with no message, whose root is the interrupted turn (or that turn's own root, for a continuation cut off again); a turn with a message of its own, or a later turn that only shares the root, isn't taken. A continuation that a message steered later isn't recognised from the interrupted turn any more; a waiter that already followed it keeps it. A send still also follows a turn that holds its own text, as before.
  - While the interrupted turn is still the newest and, as far as its timestamps tell, ended just now, they wait up to 15 seconds for a continuation to start, sleeping no later than the end of the caller's `wait` (the last poll's round trip can add to it). `GetConsultantReply` with `wait: 0` doesn't wait. A turn stopped with Esc or `StopConsultant` may take up to 15 seconds longer to report.
  - The waiter says after the reply that it followed a continuation, and names the daemon's versions when they changed during the wait. A continuation followed during the wait is kept across a dropped connection.
  - `GetConsultantReply` looks for continuations among the same 100 turns it searches for `turn_id`, and its note names the turn finally shown. A wait whose turn is pushed out of the newest 10 by later turns looks for it among the newest 100.
- `GetConsultantHistory` no longer lists a turn with no message as an empty message "from someone in the Codex pane". A continuation reads "Codex carrying on the work of turn …, with no new message", naming its root, and any other turn without a message reads "with no message". nouez never sends a continuation, so it can't refuse one.

### Added
- `REVIEW.md` item 10, for code that reads a turn's status or messages.

## [0.12.3] - 2026-11-19

Fixes from a third round of a consultant's review, of 0.12.2. Tested with Claude Code 2.1.328, Codex CLI 0.170.0 with app-server daemon 0.170.0, Python 3.11.9 on Windows 11.

### Fixed
- `OpenClaudeSession` `resume` with an explicit id now also needs the transcript to record this folder. In this folder's own transcripts, one that recorded none was still taken, though the folder name is lossy and it may be a twin folder's. All 57 transcripts inspected on one machine recorded their folder within their first ten lines; a transcript whose folder can't be established is now refused.
- `StartConsultant` keeps a new consultant whatever error setting its `title` raises, including a broken pipe to the daemon, not just an error the daemon reports.
- The `verify` skill:
  - It recovers a consultant from a failed start only by this run's title, now made unique with a random suffix. It no longer takes "the one new consultant", which could stop someone else's consultant if the list call failed or another consultant started at the same time.
  - Its session cleanup says what it checks: no `nouez-verify` session runs 60s after the last open. A session that registers later still is left running; a later run refuses to start if it has registered by then.
  - Its TeX check reads comments out first, so a commented-out `\code{--x}` no longer fails, and `\\code` (a line break, then the word) isn't taken for the macro.

## [0.12.2] - 2026-11-19

Fixes to resuming a conversation and to starting a consultant, found by two rounds of a consultant's review of 0.12.1, and a verification layer for changes to nouez. Tested with Claude Code 2.1.328, Codex CLI 0.170.0 with app-server daemon 0.170.0, Python 3.11.9 on Windows 11.

### Fixed
- `OpenClaudeSession` `resume` checks the folder each transcript recorded, for `latest` as well as an explicit id. Claude Code names its transcript folders lossily (`C:\a-b` and `C:\a_b` share one), so `latest` could pick a conversation that ran in another folder. `latest` now takes only a transcript that recorded this folder, and an explicit id from another folder is refused with that folder named, as is one kept for another folder whose transcript doesn't say where it ran.
- A session id passed to `resume` is used in lowercase, the spelling of Claude Code's transcript files, so an uppercase id is found on case-sensitive file systems too.
- `resume` is refused when the running Claude Code sessions can't be read, instead of treating every conversation as free, which could open one twice. A new conversation still opens.
- With `latest`, the note lists only busy conversations newer than the one resumed as skipped.
- When `StartConsultant` can't set a new consultant's `title`, it still returns the consultant, which works without one, and says so. Before, the error lost a consultant the daemon had already started.

### Added
- For working on nouez: a `verify` skill (`.claude/skills/verify/`) with static checks on the diff, and live checks that run this working copy against the real Codex daemon and, with `--sessions`, open, close and resume a real Claude Code session; and `REVIEW.md`, a checklist of past incidents, each with a trigger read from the diff.

## [0.12.1] - 2026-11-19

Resuming a conversation from the phone works without a `/resume` prompt, and the connection check after opening a session is clearer. Tested with Claude Code 2.1.328, Codex CLI 0.170.0 with app-server daemon 0.170.0, Python 3.11.9 on Windows 11.

### Added
- `OpenClaudeSession` takes `resume`: a session id, or `latest` for the newest conversation held in the folder that no running session has open. The window runs `claude --resume <id>` with Remote Control, and the result names the conversation and when it was last active. It refuses a conversation that's already open in a running session, one that ran in another folder (naming that folder), and an id with no transcript. Before, Claude sent `/resume <id>` as the first message, which loaded the conversation late and left the connection check without the session.

### Changed
- A `prompt` starting with `/resume` or `/continue` is refused with a pointer to `resume`, and nothing is opened.
- The connection check after `OpenClaudeSession` waits up to 30 seconds instead of 15. When it doesn't see the session in time, the result tells Claude to check `ListClaudeSessions` before reporting a failure or opening another session. When it sees the session connected, it adds that the Claude app's list can lag, so Claude asks the user to refresh it instead of opening another.

## [0.12.0] - 2026-11-12

Results say more: what a reused consultant has been doing, what it runs on, and whether an opened session connected. There is a history tool, a reply can be read in pieces, and two opt-in send options. Defaults and the server instructions are unchanged. Tested with Claude Code 2.1.322, Codex CLI 0.165.0 with app-server daemon 0.167.2, Python 3.13.5 on Windows 11.

### Added
- `GetConsultantHistory` (read-only) lists a consultant's recent turns, newest first, one line each: turn id, status, when it started and how long it took, who sent it (the `from` of a bridge message, or "someone in the Codex pane"), the first line of the message and of the reply, and how many messages were added while it ran. For a message sent with `revision` or `owner_words`, the line shows the sender's own text. `limit` sets how many (default 20, up to 100).
- `GetConsultantReply` takes `offset`, a character position, and returns the reply from there, as much as fits, with the offset to read on from. A reply cut at 60,000 characters now names the turn id and offset to pass.
- `SendConsultantMessage` takes `owner_words`: the user's own words, as they typed them. They go first in the message, marked off from the rest, which is labelled as the sender's, so the consultant can tell the request from Claude's reading of it. Without it the message is unchanged.
- `SendConsultantMessage` takes `revision: true`: the message starts with a line giving the git commit, branch and number of uncommitted paths in the consultant's folder, and asks the consultant to name that revision in its answer. Without it the message is unchanged.
- `server.py doctor` checks the setup and prints one line per check: Python and the nouez path, the `codex` CLI and the app-server daemon (with any update notice), the waiter allow rules in Claude Code's `settings.json`, Windows Terminal and `claude` on the `PATH`. It exits 1 when something needs fixing.
- README: a brief and verdict template for consultant work, instead of the "skeptical senior reviewer" example.

### Changed
- When `StartConsultant` reuses a consultant, its result says when the consultant started and how many turns it has had, describes its last turn the way `GetConsultantHistory` does, and shows its reasoning effort next to its model. When `instructions` are ignored on reuse, it suggests sending them as a message, which keeps the context.
- `SendConsultantMessage` says which model and effort the consultant runs on when the send doesn't change them: in the "started a new turn" line, and after a reply that came back within the wait.
- A failed turn's result says that the turn failed inside Codex, not in nouez, and whether the message got no answer. It says sending again is safe because the consultant keeps its context, and that after a second failure of the same kind a new consultant with a short summary is the way on. An interrupted turn keeps its old wording.
- After `OpenClaudeSession` opens a window in a trusted folder, it checks Claude Code's session list for up to 15 seconds and says whether the new session is running and connected to Remote Control. It also says when another Claude Code session was already running in that folder. The window opens either way; a failed check only leaves the note out.
- A full thread id passed as `to` is read directly instead of being looked up in the thread list.

## [0.11.3] - 2026-11-12

Security fixes from a review of 0.11.2. Nothing changes in normal use. Tested with Claude Code 2.1.322, Codex CLI 0.165.0 with app-server daemon 0.167.2, Python 3.13.5 on Windows 11.

### Fixed
- `OpenClaudeSession` passed its `name` to `claude` unchecked, so a name starting with `-`, such as `--dangerously-skip-permissions`, was read as an option. A name must now start with a letter or digit and hold only letters (any language), digits, spaces, `.`, `_` and `-`, up to 64 characters; anything else is refused before a folder is created or a window opens. A name taken from the folder is cleaned up instead (other characters become `-`, leading ones are dropped). The window checks the name again before starting `claude`.
- A consultant was set read-only only when it started, so permissions changed later in its watch pane carried over to Claude's messages. Every `turn/start` to a consultant now sends a read-only sandbox and `approvalPolicy: never`, which Codex keeps for later turns too. Sessions the user opened keep their own settings.

### Changed
- The update notice suggests `git pull --ff-only`, so a copy with its own commits stops with git's message instead of merging.

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

[Unreleased]: https://github.com/jibarix/nouez/compare/v0.30.2...HEAD
[0.30.2]: https://github.com/jibarix/nouez/compare/v0.30.1...v0.30.2
[0.30.1]: https://github.com/jibarix/nouez/compare/v0.30.0...v0.30.1
[0.30.0]: https://github.com/jibarix/nouez/compare/v0.29.0...v0.30.0
[0.29.0]: https://github.com/jibarix/nouez/compare/v0.28.6...v0.29.0
[0.28.6]: https://github.com/jibarix/nouez/compare/v0.28.5...v0.28.6
[0.28.5]: https://github.com/jibarix/nouez/compare/v0.28.4...v0.28.5
[0.28.4]: https://github.com/jibarix/nouez/compare/v0.28.3...v0.28.4
[0.28.3]: https://github.com/jibarix/nouez/compare/v0.28.2...v0.28.3
[0.28.2]: https://github.com/jibarix/nouez/compare/v0.28.1...v0.28.2
[0.28.1]: https://github.com/jibarix/nouez/compare/v0.28.0...v0.28.1
[0.28.0]: https://github.com/jibarix/nouez/compare/v0.27.0...v0.28.0
[0.27.0]: https://github.com/jibarix/nouez/compare/v0.26.4...v0.27.0
[0.26.4]: https://github.com/jibarix/nouez/compare/v0.26.3...v0.26.4
[0.26.3]: https://github.com/jibarix/nouez/compare/v0.26.2...v0.26.3
[0.26.2]: https://github.com/jibarix/nouez/compare/v0.26.1...v0.26.2
[0.26.1]: https://github.com/jibarix/nouez/compare/v0.26.0...v0.26.1
[0.26.0]: https://github.com/jibarix/nouez/compare/v0.25.0...v0.26.0
[0.25.0]: https://github.com/jibarix/nouez/compare/v0.24.0...v0.25.0
[0.24.0]: https://github.com/jibarix/nouez/compare/v0.23.0...v0.24.0
[0.23.0]: https://github.com/jibarix/nouez/compare/v0.22.0...v0.23.0
[0.22.0]: https://github.com/jibarix/nouez/compare/v0.21.0...v0.22.0
[0.21.0]: https://github.com/jibarix/nouez/compare/v0.20.0...v0.21.0
[0.20.0]: https://github.com/jibarix/nouez/compare/v0.19.1...v0.20.0
[0.19.1]: https://github.com/jibarix/nouez/compare/v0.19.0...v0.19.1
[0.19.0]: https://github.com/jibarix/nouez/compare/v0.18.1...v0.19.0
[0.18.1]: https://github.com/jibarix/nouez/compare/v0.18.0...v0.18.1
[0.18.0]: https://github.com/jibarix/nouez/compare/v0.17.0...v0.18.0
[0.17.0]: https://github.com/jibarix/nouez/compare/v0.16.0...v0.17.0
[0.16.0]: https://github.com/jibarix/nouez/compare/v0.15.1...v0.16.0
[0.15.1]: https://github.com/jibarix/nouez/compare/v0.15.0...v0.15.1
[0.15.0]: https://github.com/jibarix/nouez/compare/v0.14.1...v0.15.0
[0.14.1]: https://github.com/jibarix/nouez/compare/v0.14.0...v0.14.1
[0.14.0]: https://github.com/jibarix/nouez/compare/v0.13.0...v0.14.0
[0.13.0]: https://github.com/jibarix/nouez/compare/v0.12.4...v0.13.0
[0.12.4]: https://github.com/jibarix/nouez/compare/v0.12.3...v0.12.4
[0.12.3]: https://github.com/jibarix/nouez/compare/v0.12.2...v0.12.3
[0.12.2]: https://github.com/jibarix/nouez/compare/v0.12.1...v0.12.2
[0.12.1]: https://github.com/jibarix/nouez/compare/v0.12.0...v0.12.1
[0.12.0]: https://github.com/jibarix/nouez/compare/v0.11.3...v0.12.0
[0.11.3]: https://github.com/jibarix/nouez/compare/v0.11.2...v0.11.3
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
