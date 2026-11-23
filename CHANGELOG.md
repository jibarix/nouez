# Changelog

All notable changes to this project are recorded here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and versions follow
[Semantic Versioning](https://semver.org/).

## [Unreleased]

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

[Unreleased]: https://github.com/jibarix/nouez/compare/v0.18.1...HEAD
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
