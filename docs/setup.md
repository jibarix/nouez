# Setup

Part of [nouez's documentation](../README.md#documentation).

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

**3. Set up the phone dispatcher.** The dispatcher is a Remote Control server in a folder of its own, `~/Projects/dispatcher` by default, beside your projects, so that listing its neighbours lists them. Three commands, with the `python` and path you registered:

```sh
python "/absolute/path/to/nouez/server.py" dispatcher setup
```

It makes the folder (its parent must exist; `--folder` picks another), writes a `CLAUDE.md` there that gives the dispatcher its job (open, list and close sessions, show usage; no project work), and adds allow rules for nouez's session tools to the folder's `.claude/settings.json`, so the dispatcher doesn't ask before each one. A `CLAUDE.md` already there is kept as it is; a `settings.json` already there gets only the missing rules, after a dated copy beside it, and one that isn't valid JSON is left alone with a message. A `.claude` there that is a link rather than a folder stops `setup`: nothing is read or written through it. `--dry-run` shows what it would change. Then, once, in a terminal in that folder (`setup` prints how to get there; on Windows a PowerShell `Set-Location`):

```sh
claude remote-control --name dispatcher --spawn same-dir
```

Answer Claude Code's question about trusting the folder, and any question Remote Control asks the first time. Check that the Claude app lists the computer as `dispatcher`, then stop it with Ctrl+C. A server started at sign-in has no one to answer those questions, so this run is what lets it connect on its own. Last:

```sh
python "/absolute/path/to/nouez/server.py" dispatcher install
```

It checks that the folder is set up and trusted (itself, or in git its repository: trust in a folder above it doesn't count, since the folder's own settings make Claude Code ask again) and that `claude` can be found, then has the dispatcher start at each sign-in, hidden, and starts it now: on Windows a Task Scheduler task, `nouez dispatcher` (at your sign-in, with your normal rights, on battery too, no time limit); on macOS a launch agent, `~/Library/LaunchAgents/io.github.jibarix.nouez.dispatcher.plist`; on Linux a desktop autostart entry, `~/.config/autostart/nouez-dispatcher.desktop` (or under `$XDG_CONFIG_HOME`; nouez notes where it put it, so `uninstall` finds it from any shell, and stops if that note can't be read), which starts it when you sign in to the desktop, so the sessions it opens can open windows there. A start of that name that isn't nouez's is left alone, and nothing is installed: nouez's runs exactly the command `install` writes (a Python by its full path with `-I`, nouez's `server.py`, told by how the file begins, then `dispatcher run --folder <folder> --sign-in`), and on Windows as you, so one that runs anything else, or as another user, is someone else's; so is a macOS launch agent that names its program with `Program`. A supervisor already running is asked to stop first, so the new one runs with the new folder; when `CLAUDE_CONFIG_DIR` is set, the dispatcher uses that Claude Code profile too. A supervisor the sign-in start runs waits while an `install` or `uninstall` is at work, then starts `claude` only if nouez's sign-in start is there and runs its own folder and profile; otherwise, or if it still can't tell after a minute, it exits, so one that starts late can't outlive an `uninstall`; one that started for another folder while an `install` was at work is asked to stop, and the new one started again (if it doesn't stop, `install` says so and fails). On macOS `install` turns the launch agent on in launchd, and unloads one already loaded only when launchd says it came from nouez's plist; `uninstall` deletes the plist only once launchd has let it go. `server.py dispatcher status` shows whether it runs and is connected, and `server.py dispatcher uninstall` removes the sign-in start and stops it, leaving the folder. See [The phone dispatcher](phone.md#the-phone-dispatcher) for how it runs.

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

It reports Claude Code's side (Python, `claude`, the waiter's rules, terminal windows), then the phone dispatcher (its folder, rules and trust, whether it starts at sign-in and is connected), and then each consultant CLI: whether it is installed, signed in and answering. A CLI you didn't install is a note, not a problem; doctor exits with 1 only when something installed doesn't work. Then run `claude mcp list`, or `/mcp` inside Claude Code: you should see `consultants` connected. Sessions that were already open keep the old server until you reconnect it there: `/mcp`, then reconnect `consultants`. Do the same after updating nouez (see [nouez updates](#nouez-updates)).

## nouez updates

When a newer nouez is released on GitHub, `StartConsultant` adds a notice to its result with a link to the release notes. Claude tells you about it and goes on with the consultation. Ask Claude to update and it runs `git -C '<your nouez folder>' pull --ff-only` in that same session. If git fails (local changes, a conflict, or your copy has commits GitHub doesn't), Claude stops there, shows you what git said and doesn't discard anything. Only after the pull succeeds does it ask you to run `/mcp` and reconnect `consultants` to load the new version. (If the folder's name has a `'` in it, Claude asks you to run the pull yourself.) Your consultants keep their conversations. Other open Claude Code sessions keep the old version until you reconnect there too.

To find out, nouez asks GitHub for the latest release (`api.github.com/repos/jibarix/nouez/releases/latest`). It sends no sign-in and nothing from your projects or sessions: GitHub sees an HTTPS request from your IP address with `nouez/<version>` as the client name, at the time the server starts, through your proxy if you have one set. An answer is reused for 24 hours and a failed attempt waits an hour before the next, kept in `nouez/latest-release.json` in your cache folder (`%LOCALAPPDATA%` on Windows, `$XDG_CACHE_HOME` or `~/.cache` elsewhere); servers that start at the same moment may each ask. The request runs in the background when the server starts, and each network step gives up after 3 seconds, so no tool waits for it; if you're offline there is simply no notice. The notice is given once per server process. To turn the check off, set the environment variable `NOUEZ_NO_UPDATE_CHECK=1`.

You can also watch the repository on GitHub (Watch → Custom → Releases) to get an email for each release.

## Codex updates

When the `codex` CLI on your `PATH` or the app-server daemon is older than the latest Codex release, `StartConsultant` adds a notice to its result. Claude tells you about it and goes on with the consultation. The latest version comes from `version.json` in your Codex home, the cache Codex keeps for its own update check, so nouez makes no network request. If that file is missing, or you dismissed that version in Codex, there is no notice. The notice is given once per server process (normally once per Claude Code session). nouez doesn't update anything itself. Ask Claude to update and it runs `codex update` for the CLI and `codex app-server daemon update` for the daemon. Updating the daemon may interrupt running Codex work, including consultants and your own sessions.

On Windows, if `codex app-server daemon update` fails with `Cannot connect to C: resolve failed`, the daemon was started from Git Bash and its updater found GNU tar instead of Windows' tar. nouez 0.7.1 and later start the daemon without Git Bash's environment. For a daemon started some other way, run `codex app-server daemon stop` and then `codex app-server daemon start` from PowerShell or cmd, then update again.
