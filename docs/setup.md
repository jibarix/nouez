# Setup

Part of [nouez's documentation](../README.md#documentation). Every setting nouez reads is listed in [Rules](rules.md).

nouez installs two ways: as a Claude Code plugin on Windows, or from a clone (macOS, Linux, or to change the code). Install it one way only.

## As a plugin

[The README's steps](../README.md#setup) are the whole install: install the plugin, optionally sign in to a consultant CLI (step 4 of [From a clone](#from-a-clone) has the details), run `/nouez:setup`, then `/reload-plugins`. `/nouez:setup` writes the waiter's allow rules and, on your yes, nouez's status line into Claude Code's settings, runs `doctor`, and sets up or updates the phone dispatcher, asking before each change. The plugin ships the prompt hook, so the clone steps' settings edits don't apply.

- **Updating:** see [nouez updates](#nouez-updates). After `/reload-plugins` in one session, the other open sessions move to the new version by themselves, the next time they call nouez while nothing of nouez's runs there ([the plugin](rules.md#rule-plugin-launcher)).
- **Protections:** with the plugin, a protection can change from a session after a yes in Claude Code's own prompt ([protections](rules.md#rule-protections-behind-the-prompt)).
- **Moving from a clone:** `/nouez:setup` offers to remove the clone's `consultants` registration, so nouez doesn't run twice, then takes the clone's waiter rules out of your settings. A switch the clone's registration set as an environment variable doesn't reach the plugin: setup names each one and sets it in nouez's settings on your yes. Sessions opened before keep the clone's nouez until you reopen them. The clone's folder stays.
- **Uninstalling:** `/nouez:uninstall` asks before each step: it removes the dispatcher's sign-in start and stops it, then takes the waiter's allow rules out of Claude Code's settings, and nouez's own status line (a status line of yours that passes its input on to nouez stays). The dispatcher's folder and its `CLAUDE.md` stay, and so do nouez's settings, cache and usage log in `%LOCALAPPDATA%\nouez`. Then `claude plugin uninstall nouez@nouez` removes the plugin.

## From a clone

Run each command in a terminal. Where a path appears, use the absolute path to your copy of nouez, in quotes if it contains a space. On macOS and Linux, use `python3` wherever this says `python` if `python` isn't on your `PATH`. First check that `python --version` prints 3.9 or later. On Windows, if it opens the Microsoft Store or prints nothing, install Python from python.org (or use `py -3` wherever this says `python`). Run the commands outside any virtual environment, unless you mean nouez to run on that environment's Python.

**1. Get the code.**

```sh
git clone https://github.com/jibarix/nouez.git
```

**2. Register the server with Claude Code.**

```sh
# available in every project
claude mcp add --scope user consultants -- python "/absolute/path/to/nouez/server.py"

# or only in one project: run this from that project's folder. The dispatcher and the
# sessions it opens elsewhere then don't have nouez's tools, so use it for a trial only.
claude mcp add consultants -- python "/absolute/path/to/nouez/server.py"
```

On Windows, use a path like `"C:/Users/you/nouez/server.py"`. To get [model scores](consultants.md#choosing-a-consultant), add `-e ARTIFICIAL_ANALYSIS_API_KEY=<your key>` before `--` now; to add it later, see there.

**3. Set up the phone dispatcher.** The dispatcher is a Remote Control server in a folder of its own, `~/.nouez/dispatcher` by default. A dispatcher set up in `~/Projects/dispatcher` before 0.28 stays there (when both are set up, `~/Projects/dispatcher`). Three commands, with the `python` and path you registered:

```sh
python "/absolute/path/to/nouez/server.py" dispatcher setup
```

It makes the folder (`--folder` picks another; its parent must exist, except `~/.nouez`), writes a `CLAUDE.md` there that gives the dispatcher its job (open, list and close sessions, show usage; no project work), and adds allow rules for nouez's session tools to the folder's `.claude/settings.json`, so the dispatcher doesn't ask before each one. A `CLAUDE.md` already there is kept as it is, unless an earlier nouez wrote it and it wasn't changed since: then it is replaced with this version's, after a dated copy beside it ([dispatcher setup](rules.md#rule-dispatcher-setup)); a `settings.json` already there gets only the missing rules, after a dated copy beside it, and one that isn't valid JSON is left alone with a message. A `.claude` there that is a link rather than a folder stops `setup`: nothing is read or written through it. `--dry-run` shows what it would change.

The dispatcher opens sessions in any folder, but records your trust answer only inside its projects folders. You can pick them later from the phone ([Setting up the phone](phone.md#setting-up-the-phone)), so `setup` and `install` need no flag: for `~/.nouez/dispatcher`, run without one, they list the folders that look like they hold your projects (`~/Projects` and folders holding two or more folders you trusted Claude Code in, with how many each holds) and choose none; for `~/Projects/dispatcher`, the folder above it is the default. To pick them here instead, name each folder that holds projects with `--projects DIR`, once for each (up to 20, none inside another), or pass `--no-projects` to trust folders only at the computer, which also keeps the phone from picking them. A projects folder can't be a drive's root, nor a folder that is or holds your home folder (the home folder itself only from the phone, after a warning), Claude Code's settings folder, nouez's cache or `~/.nouez`. `ListProjects` then lists each projects folder. Run again without either flag, `setup` and `install` keep the folders already picked.

Then, once, in a terminal in that folder (`setup` prints how to get there; on Windows a PowerShell `Set-Location`):

```sh
claude remote-control --name dispatcher --spawn same-dir
```

Answer Claude Code's question about trusting the folder, and any question Remote Control asks the first time. Check that the Claude app lists the computer as `dispatcher`, then stop it with Ctrl+C. A server started at sign-in has no one to answer those questions, so this run is what lets it connect on its own. Don't use this run from the phone: it is plain Claude Code, without the trust limit nouez gives the dispatcher it starts ([Phone](phone.md)). Last:

```sh
python "/absolute/path/to/nouez/server.py" dispatcher install
```

It checks that the folder is set up and trusted (itself, or in git its repository: trust in a folder above it doesn't count, since the folder's own settings make Claude Code ask again) and that `claude` can be found, then has the dispatcher start at each sign-in, hidden, and starts it now: on Windows a Task Scheduler task, `nouez dispatcher` (at your sign-in, with your normal rights, on battery too, no time limit); on macOS a launch agent, `~/Library/LaunchAgents/io.github.jibarix.nouez.dispatcher.plist`; on Linux a desktop autostart entry, `~/.config/autostart/nouez-dispatcher.desktop` (or under `$XDG_CONFIG_HOME`; nouez notes where it put it, so `uninstall` finds it from any shell, and stops if that note can't be read), which starts it when you sign in to the desktop, so the sessions it opens can open windows there. If that name belongs to a different sign-in entry, installation stops and leaves the entry in place. Check its command before deciding whether to rename or remove it. See [how install recognizes nouez's sign-in entry](rules.md#rule-sign-in-ownership). A supervisor already running is asked to stop first, so the new one runs with the new folder and projects folders; when `CLAUDE_CONFIG_DIR` is set, the dispatcher uses that Claude Code profile too. A supervisor the sign-in start runs waits while an `install` or `uninstall` is at work, then starts `claude` only if nouez's sign-in start is there and runs its own folder and profile; otherwise, or if it still can't tell after a minute, it exits, so one that starts late can't outlive an `uninstall`; one that started for another folder or other projects folders while an `install` was at work is asked to stop, and the new one started again (if it doesn't stop, `install` says so and fails). On macOS `install` turns the launch agent on in launchd, and unloads one already loaded only when launchd says it came from nouez's plist; `uninstall` deletes the plist only once launchd has let it go. `server.py dispatcher status` shows whether it runs and is connected, and `server.py dispatcher uninstall` removes the sign-in start and stops it, leaving the folder. See [The phone dispatcher](phone.md#the-phone-dispatcher) for how it runs.

**4. Install and sign in to a consultant CLI** (optional: skip it to use only the phone and session tools). Either one is enough; with both, Codex is the default.

- **Codex:** install the [Codex CLI](https://developers.openai.com/codex/cli/), run `codex login` (with an API key instead, `codex login --with-api-key` reads it from standard input: `printenv OPENAI_API_KEY | codex login --with-api-key` in Bash or zsh, `$env:OPENAI_API_KEY | codex login --with-api-key` in PowerShell), then check with `codex login status`, which should say you are logged in. Usage windows in `ConsultantBudget` and `top` are those of a ChatGPT plan; with an API key there are none to show.
- **Antigravity:** install the [Antigravity CLI](https://antigravity.google/docs/cli-getting-started), run `agy` once in a terminal and sign in with your Google account, then check with `agy models`, which should list models. On Windows the installer puts `agy` in `%LOCALAPPDATA%\agy\bin`; nouez finds it there even when that folder isn't on your `PATH`. If `agy` isn't found in your terminal, run it by its full path instead, in PowerShell `& "$env:LOCALAPPDATA\agy\bin\agy.exe" models`.

If installing changed your `PATH`, quit and restart Claude Code (and the terminal it runs in), so the server it starts can find the new program.

**5. Let Claude run the waiter** (skip it if you installed no consultant CLI). Replies often take minutes, so Claude doesn't wait for them: it starts a small waiter command in the background, and the waiter wakes Claude with the reply when the consultant finishes (see [Long tasks](consultants.md#tips)). Claude Code asks before running a command it has no rule for, and in auto mode it may block one. To allow the waiter in every project, print its permission rules with the same `python` and path you registered:

```sh
python "/absolute/path/to/nouez/server.py" allow-rule
```

It prints the rules and the file to put them in: one rule for the Bash tool, and on Windows a second for the PowerShell tool. Add them to `permissions.allow` in that file (`~/.claude/settings.json`, or `settings.json` in `CLAUDE_CONFIG_DIR` if you set it; on Windows, `C:\Users\<you>\.claude\settings.json`), keeping anything already in it. If the file doesn't exist yet, create it. With no other permissions, on Windows it looks like this:

```json
{
  "permissions": {
    "allow": [
      "Bash(C:/Python313/python.exe -I C:/Users/you/nouez/server.py wait *)",
      "PowerShell(C:/Python313/python.exe -I C:/Users/you/nouez/server.py wait *)"
    ]
  }
}
```

Instead of editing the file, you can approve the waiter the first time Claude Code asks and choose not to be asked again. The rules allow only this script's `wait` command with this interpreter, so auto mode keeps them. If you move nouez or change Python, run `allow-rule` again and replace them. Without them everything still works, but Claude Code asks each time, and if the waiter can't run Claude reads the reply only when you ask for it. Claude Code reads `settings.json` when a session starts, so start a new session after editing it; `/mcp` reconnects only the server. `/permissions` in Claude Code shows the rules in effect.

**6. Check it.** Run:

```sh
python "/absolute/path/to/nouez/server.py" doctor
```

It reports Claude Code's side (Python, `claude`, the waiter's rules, the status line and prompt hook that let nouez act on Claude Code's own usage, terminal windows), then the phone dispatcher (its folder, rules and trust, whether it starts at sign-in and is connected), and then each consultant CLI: whether it is installed, signed in and answering. A missing optional CLI is a note. With consultant CLIs installed, one working consultant can suffice if the other required checks pass. See [when doctor succeeds](rules.md#rule-doctor-result). Then run `claude mcp list`, or `/mcp` inside Claude Code: you should see `consultants` connected. Sessions that were already open keep the old server until you reconnect it there: `/mcp`, then reconnect `consultants`. Do the same after updating nouez (see [nouez updates](#nouez-updates)).

**7. Let nouez see Claude Code's usage (recommended).** Claude Code gives its usage only to the status line, so without one nouez can't tell when to hand work out to spare it. When Claude Code's `settings.json` has no status line, `dispatcher setup` offers nouez's at its end: in a terminal it asks and adds it only on a yes, after a dated copy of the file; elsewhere it says to run again with `--statusline`. A status line of your own is kept. Doctor prints the two entries to add to `settings.json`, with your own Python and paths: a status line and a prompt hook. See [Claude Code's usage](consultants.md) for what each does, and how to keep a status line script you already have.

## What nouez changes

- **The MCP entry** for `consultants`, made by Claude Code's own `claude mcp add` (step 2), or the plugin, which Claude Code installs.
- **The waiter's allow rules** in Claude Code's own `settings.json`: added by you (step 5), or by `/nouez:setup` on your yes, copied first.
- **nouez's status line** in the same file, only on your yes and only when it has none, copied first.
- **One trust mark in `~/.claude.json`** for each folder you trust a session in, only after nouez reports what the folder's settings would run and you say yes (Claude passes your yes on; `NOUEZ_ASK_TRUST=1` makes nouez ask you in its own prompt). A folder nouez creates outside git, in the same call that marks it, has no settings, so it needs no report. In the dispatcher, an existing folder inside a projects folder you picked, whose settings run and allow nothing, is trusted with neither a report nor your yes; the result says so ([trust without a question](rules.md#rule-trust-without-a-question)). Before changing the file, nouez makes a dated backup. `doctor` reports the backup folder, counts this profile's copies, names the newest and says how to restore one. See [which trust backups nouez keeps](rules.md#rule-trust-backups). `NOUEZ_NO_TRUST_WRITE=1` turns this off.
- **An MCP server added back to `~/.claude.json`**, only when you run `server.py restore ID` at the computer for one that `RestoreClaudeConfig` found in nouez's copies and missing now; nothing else in the file changes, and it is copied first.
- **The dispatcher folder's own files:** its `CLAUDE.md`, and allow rules for nouez's session tools in its `.claude/settings.json`, copied first.
- **The sign-in start** that `dispatcher install` adds, which `dispatcher uninstall` removes.

nouez changes nothing else in your Claude Code settings.

## nouez updates

When a newer nouez is released on GitHub, `StartConsultant` adds a notice to its result with a link to the release notes. Claude tells you about it and goes on with the consultation. Ask Claude to update and it runs `git -C '<your nouez folder>' pull --ff-only` in that same session. If git fails (local changes, a conflict, or your copy has commits GitHub doesn't), Claude stops there, shows you what git said and doesn't discard anything. Only after the pull succeeds does it ask you to run `/mcp` and reconnect `consultants` to load the new version. (If the folder's name has a `'` in it, Claude asks you to run the pull yourself.) Your consultants keep their conversations. Other open Claude Code sessions keep the old version until you reconnect there too. On the phone, the notice appears in the dispatcher's own tool results. To update it at the computer, follow [the dispatcher update instructions](phone.md#the-phone-dispatcher).

To find out, nouez asks GitHub for the latest release (`api.github.com/repos/jibarix/nouez/releases/latest`). It sends no sign-in and nothing from your projects or sessions: GitHub sees an HTTPS request from your IP address with `nouez/<version>` as the client name, through your proxy if you have one set. The check runs in the background at startup and can run again after a dispatcher tool is used. Nouez keeps the result in `nouez/latest-release.json` in your cache folder (`%LOCALAPPDATA%` on Windows, `$XDG_CACHE_HOME` or `~/.cache` elsewhere). If you're offline, there is simply no notice. See [when nouez reuses or retries a release lookup](rules.md#rule-release-poll). The notice is given once for each new release in a server process. To turn the check off, set the environment variable `NOUEZ_NO_UPDATE_CHECK=1`.

With nouez installed as a plugin, Claude runs `claude plugin update nouez@nouez` instead, when you ask, and then asks you to run `/reload-plugins`. Your other open sessions move to the new version by themselves, the next time they call nouez while nothing of nouez's is running there; nothing needs reconnecting ([the plugin](rules.md#rule-plugin-launcher)). The phone dispatcher's notice says to update at the computer and run `/nouez:setup` there, which installs the dispatcher again.

You can also watch the repository on GitHub (Watch → Custom → Releases) to get an email for each release.

## Codex updates

When the `codex` CLI on your `PATH` or the app-server daemon is older than the latest Codex release, `StartConsultant` adds a notice to its result. Claude tells you about it and goes on with the consultation. The latest version comes from `version.json` in your Codex home, the cache Codex keeps for its own update check, so nouez makes no network request. If that file is missing, or you dismissed that version in Codex, there is no notice. The notice is given once per server process (normally once per Claude Code session). nouez doesn't update anything itself. Ask Claude to update and it runs `codex update` for the CLI and `codex app-server daemon update` for the daemon. Updating the daemon may interrupt running Codex work, including consultants and your own sessions.

On Windows, if `codex app-server daemon update` fails with `Cannot connect to C: resolve failed`, the daemon was started from Git Bash and its updater found GNU tar instead of Windows' tar. nouez 0.7.1 and later start the daemon without Git Bash's environment. For a daemon started some other way, run `codex app-server daemon stop` and then `codex app-server daemon start` from PowerShell or cmd, then update again.
